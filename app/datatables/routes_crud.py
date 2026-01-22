# app/datatables/routes_crud.py
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime

import pandas as pd
from flask import (
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_babel import gettext as _ 
from flask_babel import lazy_gettext
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.attributes import flag_modified
from werkzeug.utils import secure_filename

from app.services.tm_connector import TrainingManagerConnector

from app.models import user_has_permission
from app.permissions import (
    can_create_datatable_for_group,
    check_datatable_permission,
    check_group_permission
)
from app.utils.files import dataframe_to_excel_bytes, read_excel_to_list
from app.services.datatable_service import DataTableService
from app.services.project_service import ProjectService

from ..extensions import db
from ..forms import DataTableForm, DataTableUploadForm, EditDataTableForm
from ..forms.controlled_molecules import MoleculeUsageForm
from ..helpers import (
    get_field_types,
    get_ordered_column_names,
    sort_analytes_list_by_name,
    validate_and_convert
)
from ..models import (
    AnalyteDataType,
    AnimalModelAnalyteAssociation,
    DataTable,
    DataTableFile,
    ExperimentalGroup,
    ExperimentDataRow,
    HousingConditionSet,
    Project,
    ProjectTeamShare,
    ProtocolAnalyteAssociation,
    ProtocolAnalyteAssociation,
    ProtocolModel,
    ProtocolMoleculeAssociation,
    DataTableMoleculeUsage,
    ControlledMolecule,
    ReferenceRange,
    Team,
    TeamMembership,
    Workplan,
    WorkplanEvent
)
from . import datatables_bp
from .analysis_utils import identify_outliers_and_calc_stats, get_age_range_from_df_view_helper
from .plot_utils import get_custom_ordered_columns

from app.services.datatable_service import DataTableService
from app.services.project_service import ProjectService
from app.services.calculation_service import CalculationService
from app.tasks import declare_tm_practice_task

# Instantiate the service
datatable_service = DataTableService()
project_service = ProjectService()
calculation_service = CalculationService()

@datatables_bp.route('/create', methods=['GET', 'POST'])
@datatables_bp.route('/create/project/<int:project_id>', methods=['GET', 'POST'])
@login_required
def create_data_table(project_id=None):
    if not current_user.is_authenticated and not current_user.get_teams():
        flash(_("You must be part of a team to create or view DataTables."), "warning")
        return redirect(url_for('main.index'))    
    
    # Fetch hierarchy for sidebar using ProjectService
    sidebar_data = project_service.get_sidebar_hierarchy(current_user)

    include_archived = request.args.get('include_archived', 'false').lower() == 'true'
    group_id_prefill_str = request.args.get('group_id_prefill', None)
    form = DataTableForm(project_id=project_id, include_archived=include_archived, group_id_prefill=group_id_prefill_str)
    
    if form.group.data or group_id_prefill_str:
        group_id = form.group.data if form.group.data else group_id_prefill_str
        group_prefill = db.session.get(ExperimentalGroup, group_id)
        if group_prefill:
            assignable_users = {}
            if group_prefill.project.team:
                for membership in group_prefill.project.team.memberships:
                    if membership.user:
                        assignable_users[membership.user.id] = membership.user
            
            shared_permissions = ProjectTeamShare.query.filter(
                ProjectTeamShare.project_id == group_prefill.project.id,
                or_(
                    ProjectTeamShare.can_create_datatables == True,
                    ProjectTeamShare.can_edit_datatables == True
                )
            ).options(joinedload(ProjectTeamShare.team).joinedload(Team.memberships).joinedload(TeamMembership.user)).all()

            for perm in shared_permissions:
                if perm.team:
                    for membership in perm.team.memberships:
                        if membership.user:
                            assignable_users[membership.user.id] = membership.user
            
            sorted_users = sorted(assignable_users.values(), key=lambda u: u.email)
            form.assigned_to_id.choices = [('', _('Unassigned'))] + [(u.id, u.email) for u in sorted_users]

    if request.method == 'GET' and group_id_prefill_str:
        group_prefill = db.session.get(ExperimentalGroup, group_id_prefill_str)
        if group_prefill and check_group_permission(group_prefill, 'read'):
            if any(choice[0] == group_id_prefill_str for choice in form.group.choices):
                form.group.data = group_id_prefill_str
            else:
                flash(_("Prefilled group ID is not valid or accessible."), "warning")
        else:
            flash(_("Prefilled group not found or you don't have permission to access it."), "warning")    
    
    current_project_obj = None
    if project_id:
        current_project_obj = db.session.get(Project, project_id)
        if not current_project_obj:
            flash(lazy_gettext("Project {project_id} not found.").format(project_id=project_id), "warning")
            return redirect(url_for('datatables.create_data_table', include_archived=include_archived))

    if form.validate_on_submit():
        group_id = form.group.data
        group = db.session.get(ExperimentalGroup, group_id)
        if group:
            form.assigned_to_id.choices = [('', '-- ' + _('Unassigned') + ' --')] + [(m.user.id, m.user.email) for m in group.project.team.memberships]
        if not group:
            flash(lazy_gettext("Invalid experimental group selected."), "danger")
            return redirect(url_for('datatables.create_data_table', project_id=project_id, include_archived=include_archived))

        if not can_create_datatable_for_group(group):
            flash(lazy_gettext("You do not have permission to create DataTables for this group."), "danger")
            return redirect(url_for('datatables.create_data_table', project_id=project_id, include_archived=include_archived))

        protocol_model_id = form.protocol.data
        protocol_model = db.session.get(ProtocolModel, protocol_model_id)
        if not protocol_model:
            flash(lazy_gettext("Invalid protocol model selected."), "danger")
            return redirect(url_for('datatables.create_data_table', project_id=project_id, include_archived=include_archived))

        date_str = form.date.data.strip()
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            flash(lazy_gettext("Invalid date format. Please use YYYY-MM-DD."), "danger")
            return redirect(url_for('datatables.create_data_table', project_id=project_id, include_archived=include_archived))

        # --- SEVERITY AND DATE CHECK ---
        ethical_approval = group.ethical_approval
        protocol_severity = protocol_model.severity
        datatable_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

        if ethical_approval:
            ea_severity = ethical_approval.overall_severity
            if protocol_severity > ea_severity:
                flash(_("Protocol Severity Mismatch: The selected protocol ('%(protocol_name)s' - Severity: %(protocol_severity)s) has a higher severity than the group's ethical approval ('%(ea_ref)s' - Max Severity: %(ea_severity)s). DataTable cannot be created.",
                                  protocol_name=protocol_model.name,
                                  protocol_severity=protocol_severity.value,
                                  ea_ref=ethical_approval.reference_number,
                                  ea_severity=ea_severity.value), "danger")
                return redirect(url_for('datatables.create_data_table', project_id=project_id, include_archived=include_archived))

            ea_start_date = ethical_approval.start_date
            ea_end_date = ethical_approval.end_date
            if (ea_start_date and datatable_date_obj < ea_start_date) or \
               (ea_end_date and datatable_date_obj > ea_end_date):
                flash(_("Date Out of Range: The DataTable date (%(dt_date)s) is outside the ethical approval's effective period (%(start)s to %(end)s).",
                                  dt_date=datatable_date_obj.strftime('%Y-%m-%d'),
                                  start=ea_start_date.strftime('%Y-%m-%d') if ea_start_date else 'N/A',
                                  end=ea_end_date.strftime('%Y-%m-%d') if ea_end_date else 'N/A'), "danger")
                return redirect(url_for('datatables.create_data_table', project_id=project_id, include_archived=include_archived))

        try:
            data_table = DataTable(
                group_id=group.id, 
                protocol_id=protocol_model.id, 
                date=date_str,
                creator_id=current_user.id,
                assigned_to_id=form.assigned_to_id.data
            )

            # Skill Validation Integration
            if protocol_model.external_skill_ids and data_table.assigned_to_id:
                user = db.session.get(User, data_table.assigned_to_id)
                if user:
                    try:
                        connector = TrainingManagerConnector()
                        # external_skill_ids is already a list of ints in the JSON field
                        skill_ids = protocol_model.external_skill_ids 
                        if skill_ids:
                            result = connector.check_competency([user.email], skill_ids)
                            if result and user.email in result:
                                user_result = result[user.email]
                                if not user_result.get('valid', True):
                                    details = user_result.get('details', [])
                                    msg = _("Warning: The assigned user '%(email)s' may not be qualified for this protocol. Issues: %(issues)s", email=user.email, issues=", ".join(details))
                                    flash(msg, "warning")
                    except Exception as e:
                        current_app.logger.error(f"Error validating skills with Training Manager: {e}")
            
            data_table.housing_condition_set_id = form.housing_condition_set_id.data if form.housing_condition_set_id.data else None

            db.session.add(data_table)
            db.session.flush() 

            if group.animal_data:
                ordered_cols_for_new_dt = get_ordered_column_names(data_table)

                protocol_defaults = {}
                if protocol_model.analyte_associations:
                    for assoc in protocol_model.analyte_associations:
                        if assoc.default_value is not None and str(assoc.default_value).strip() != '':
                            protocol_defaults[assoc.analyte.name] = assoc.default_value

                animal_model_defaults = {}
                if group.model and group.model.analyte_associations:
                    for assoc in group.model.analyte_associations:
                        if assoc.analyte.default_value is not None and str(assoc.analyte.default_value).strip() != '':
                            animal_model_defaults[assoc.analyte.name] = assoc.analyte.default_value
                
                combined_defaults_ordered = {}
                for col_name in ordered_cols_for_new_dt:
                    if col_name in protocol_defaults:
                        combined_defaults_ordered[col_name] = protocol_defaults[col_name]
                    elif col_name in animal_model_defaults:
                        combined_defaults_ordered[col_name] = animal_model_defaults[col_name]

                for i in range(len(group.animal_data)):
                    animal_info_ordered = {}
                    current_animal_data = group.animal_data[i].copy() if i < len(group.animal_data) else {}
                    for col_name in ordered_cols_for_new_dt:
                        if col_name in current_animal_data:
                            animal_info_ordered[col_name] = current_animal_data[col_name]

                    row_data = {**combined_defaults_ordered, **animal_info_ordered}
                    exp_row = ExperimentDataRow(data_table_id=data_table.id, row_index=i, row_data=row_data)
                    db.session.add(exp_row)

            db.session.commit()

            # Declare practice if protocol has required skills
            if protocol_model.external_skill_ids and data_table.assigned_to_id:
                user = db.session.get(User, data_table.assigned_to_id)
                if user:
                    declare_tm_practice_task.delay(user.email, protocol_model.external_skill_ids, data_table.date, 'DataTable creation')

            flash(lazy_gettext("Table created for Group '{group_name}' / Protocol '{protocol_name}'").format(
                group_name=group.name, protocol_name=protocol_model.name), "success")
            return redirect(url_for('datatables.edit_data_table', id=data_table.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating table: {e}", exc_info=True)
            flash(lazy_gettext("Error: {error_msg}").format(error_msg=str(e)), "danger")
        
    base_query = DataTable.query.join(ExperimentalGroup, DataTable.group_id == ExperimentalGroup.id) \
                                .join(Project, ExperimentalGroup.project_id == Project.id)
    if project_id and current_project_obj:
        if not include_archived and current_project_obj.is_archived: base_query = base_query.filter(db.false()) 
        else:
            base_query = base_query.filter(ExperimentalGroup.project_id == project_id)
            if not include_archived: base_query = base_query.filter(ExperimentalGroup.is_archived == False)
    else:
        if not include_archived:
            base_query = base_query.filter(ExperimentalGroup.is_archived == False)
            base_query = base_query.filter(Project.is_archived == False)
    if group_id_prefill_str:
        base_query = base_query.filter(ExperimentalGroup.id == group_id_prefill_str)

    all_data_tables_query_results = base_query.options(
        db.joinedload(DataTable.group).joinedload(ExperimentalGroup.team),
        db.joinedload(DataTable.group).joinedload(ExperimentalGroup.project), 
        db.joinedload(DataTable.protocol)
    ).order_by(DataTable.date.desc(), DataTable.id.desc()).limit(50).all()
    
    # Batch-fetch permissions
    from app.services.permission_service import PermissionService
    perm_service = PermissionService()
    unique_projects = {dt.group.project for dt in all_data_tables_query_results if dt.group and dt.group.project}
    project_permissions = perm_service.get_bulk_project_permissions(current_user, unique_projects)
    
    processed_data_tables = []
    for dt in all_data_tables_query_results:
        # Check permission using pre-computed dict
        has_permission = False
        if dt.group and dt.group.project:
            perms = project_permissions.get(dt.group.project.id, {})
            has_permission = perms.get('can_view_datatables', False)
            
        if has_permission:
            total_animals = len(dt.group.animal_data) if dt.group.animal_data else 0
            animals_alive = sum(1 for animal in dt.group.animal_data if isinstance(animal, dict) and animal.get('status') != 'dead') if dt.group.animal_data else 0
            dt.total_animals = total_animals
            dt.animals_alive = animals_alive
            processed_data_tables.append(dt)
            
    # Fetch all protocols for the filter dropdown
    all_protocols = ProtocolModel.query.order_by(ProtocolModel.name).all()

    return render_template('datatables/create_data_table.html', 
                           form=form, data_tables=processed_data_tables, project_id=project_id,
                           project=current_project_obj, include_archived=include_archived,
                           today_date_iso=date.today().isoformat(),
                           group_id_prefill=group_id_prefill_str,
                           sidebar_data=sidebar_data,
                           protocols=all_protocols)
                           
@datatables_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_data_table(id):
    data_table = db.session.get(DataTable, id)
    if not data_table or not data_table.group:
        flash(lazy_gettext("Table/Group not found."), "error"); return redirect(url_for('main.index'))
    
    # 1. Check Read Permission
    if not check_datatable_permission(data_table, 'read', allow_abort=True):
        flash(lazy_gettext("Permission denied to view this DataTable."), "danger"); return redirect(url_for('groups.manage_groups'))
    
    # 2. Check Edit Permission (don't abort, just set flag)
    is_read_only = not check_datatable_permission(data_table, 'edit_datatable', allow_abort=False)

    
    upload_form = DataTableUploadForm()
    edit_form = EditDataTableForm(obj=data_table)
    
    assignee_and_housing_form = DataTableForm(obj=data_table)
    if data_table.group and data_table.group.project:
        project = data_table.group.project
        assignable_users = {}

        if project.team:
            for membership in project.team.memberships:
                if membership.user:
                    assignable_users[membership.user.id] = membership.user

        shared_permissions = ProjectTeamShare.query.filter(
            ProjectTeamShare.project_id == project.id,
            or_(
                ProjectTeamShare.can_create_exp_groups == True,
                ProjectTeamShare.can_edit_exp_groups == True,
                ProjectTeamShare.can_delete_exp_groups == True,
                ProjectTeamShare.can_create_datatables == True,
                ProjectTeamShare.can_edit_datatables == True,
                ProjectTeamShare.can_delete_datatables == True
            )
        ).options(joinedload(ProjectTeamShare.team).joinedload(Team.memberships).joinedload(TeamMembership.user)).all()

        for perm in shared_permissions:
            if perm.team:
                for membership in perm.team.memberships:
                    if membership.user:
                        assignable_users[membership.user.id] = membership.user
        
        sorted_users = sorted(assignable_users.values(), key=lambda u: u.email)
        assignee_and_housing_form.assigned_to_id.choices = [('', lazy_gettext('Unassigned'))] + [(u.id, u.email) for u in sorted_users]
    
    group_animal_data = data_table.group.animal_data or []
    
    column_names = get_ordered_column_names(data_table)
    field_types = get_field_types(data_table)

    animal_model_analytes_ordered = []
    if data_table.group and data_table.group.model:
        animal_model_associations = AnimalModelAnalyteAssociation.query.filter_by(
            animal_model_id=data_table.group.model.id
        ).order_by(AnimalModelAnalyteAssociation.order).all()
        animal_model_analytes_ordered = [assoc.analyte for assoc in animal_model_associations]

    animal_model_field_names = [a.name for a in animal_model_analytes_ordered] if animal_model_analytes_ordered else []
    if 'Age (Days)' not in animal_model_field_names:
        animal_model_field_names.append('Age (Days)')

    protocol_analytes_ordered = []
    if data_table.protocol:
        protocol_associations = ProtocolAnalyteAssociation.query.filter_by(
            protocol_model_id=data_table.protocol.id
        ).order_by(ProtocolAnalyteAssociation.order).all()
        protocol_analytes_ordered = [assoc.analyte for assoc in protocol_associations]

    protocol_analytes_map = {a.name: a for a in protocol_analytes_ordered} if protocol_analytes_ordered else {}
    protocol_field_names = [a.name for a in protocol_analytes_ordered] if protocol_analytes_ordered else []
    protocol_field_units = {a.name: a.unit for a in protocol_analytes_ordered} if protocol_analytes_ordered else {}
    date_fields = [a.name for a in protocol_analytes_ordered if a.data_type.value == 'date'] if protocol_analytes_ordered else []

    metadata_fields = set()
    EXCLUDED_METADATA_FIELDS = {'ID', 'Date of Birth', 'Age (Days)'} 

    if animal_model_analytes_ordered:
        for analyte in animal_model_analytes_ordered:
            if analyte.is_metadata and analyte.name not in EXCLUDED_METADATA_FIELDS:
                metadata_fields.add(analyte.name)
    if protocol_analytes_ordered:
        for analyte in protocol_analytes_ordered:
            if analyte.is_metadata and analyte.name not in EXCLUDED_METADATA_FIELDS:
                metadata_fields.add(analyte.name)
    
    if data_table.housing_condition:
        for item_assoc in data_table.housing_condition.item_associations:
            if item_assoc.item.name not in EXCLUDED_METADATA_FIELDS:
                metadata_fields.add(item_assoc.item.name)

    existing_rows_query = data_table.experiment_rows.order_by(ExperimentDataRow.row_index)
    existing_data_rows_dict = {r.row_index: r.row_data for r in existing_rows_query.all()}
    num_expected_rows = len(group_animal_data)

    def prepare_template_data(current_rows_dict, current_group_data, all_columns_list):
        rows = []
        for i in range(len(current_group_data)):
            merged = current_group_data[i].copy() if i < len(current_group_data) else {}
            merged.update(current_rows_dict.get(i, {}))
            age_in_days = None; date_of_birth_str = merged.get('Date of Birth') 
            if date_of_birth_str and data_table.date:
                try:
                    dob = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date(); dt_date = datetime.strptime(data_table.date, '%Y-%m-%d').date()
                    delta = dt_date - dob; age_in_days = delta.days
                except (ValueError, TypeError) as e: current_app.logger.warning(f"Could not calculate age for animal index {i} in datatable {data_table.id}: {e}"); age_in_days = None 
            
            row_data = {col: merged.get(col) for col in all_columns_list}
            if 'Age (Days)' in all_columns_list:
                row_data['Age (Days)'] = age_in_days

            rows.append({'row_index': i, 'row_data': row_data})
        return rows

    if request.method == 'POST':
        if is_read_only:
            flash(lazy_gettext("This table is read-only."), "danger")
            return redirect(url_for('datatables.edit_data_table', id=id))

        if edit_form.files.data and any(f.filename for f in edit_form.files.data):
            if edit_form.validate_on_submit():
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'datatables', str(id))
                if not os.path.exists(upload_dir):
                    os.makedirs(upload_dir)

                files_uploaded = False
                for file_storage in edit_form.files.data:
                    if file_storage and file_storage.filename:
                        original_filename = secure_filename(file_storage.filename)
                        filename_base, file_extension = os.path.splitext(original_filename)
                        
                        unique_filename = f"{filename_base}_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_extension}"
                        filepath = os.path.join(upload_dir, unique_filename)
                        
                        file_storage.save(filepath)
                        
                        new_file = DataTableFile(
                            data_table_id=data_table.id,
                            filename=original_filename,
                            filepath=filepath,
                            size=os.path.getsize(filepath)
                        )
                        db.session.add(new_file)
                        files_uploaded = True
                
                if files_uploaded:
                    db.session.commit()
                    flash(('Files uploaded successfully.'), 'success')
                else:
                    flash(lazy_gettext('No files selected for upload.'), 'info')
                return redirect(url_for('datatables.edit_data_table', id=id))
            else:
                for field, errors in edit_form.errors.items():
                    for error in errors:
                        flash(f"{field}: {error}", "danger")
                return redirect(url_for('datatables.edit_data_table', id=id))

        if 'raw_data_url' in request.form and not (edit_form.files.data and any(f.filename for f in edit_form.files.data)):
            if edit_form.validate_on_submit():
                data_table.raw_data_url = edit_form.raw_data_url.data
                try:
                    db.session.commit()
                    flash(lazy_gettext('Raw Data URL updated successfully.'), 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(lazy_gettext('Error updating Raw Data URL: %(error)s') % {'error': str(e)}, 'danger')
                return redirect(url_for('datatables.edit_data_table', id=id))
            else:
                for field, errors in edit_form.errors.items():
                    for error in errors:
                        flash(f"{field}: {error}", "danger")
                return redirect(url_for('datatables.edit_data_table', id=id))

        elif 'update_metadata' in request.form:
            new_hc_id = request.form.get('housing_condition_set_id')
            new_assignee_id = request.form.get('assigned_to_id')

            data_table.housing_condition_set_id = int(new_hc_id) if new_hc_id else None
            data_table.housing_condition_set_id = int(new_hc_id) if new_hc_id else None
            
            old_assignee_id = data_table.assigned_to_id
            new_assignee_id_int = int(new_assignee_id) if new_assignee_id else None
            data_table.assigned_to_id = new_assignee_id_int
            
            # Skill Validation Integration (Metadata Update)
            if new_assignee_id_int and (new_assignee_id_int != old_assignee_id) and data_table.protocol.external_skill_ids:
                 user = db.session.get(User, new_assignee_id_int)
                 if user:
                    try:
                        connector = TrainingManagerConnector()
                        skill_ids = data_table.protocol.external_skill_ids
                        if skill_ids:
                            result = connector.check_competency([user.email], skill_ids)
                            if result and user.email in result:
                                user_result = result[user.email]
                                if not user_result.get('valid', True):
                                    details = user_result.get('details', [])
                                    msg = lazy_gettext("Warning: The assigned user '%(email)s' may not be qualified for this protocol. Issues: %(issues)s") % {'email': user.email, 'issues': ", ".join(details)}
                                    flash(msg, "warning")
                    except Exception as e:
                        current_app.logger.error(f"Error validating skills on update: {e}")
            
            if 'date' in request.form:
                new_date_str = request.form.get('date')
                if new_date_str:
                    try:
                        new_date_obj = datetime.strptime(new_date_str, '%Y-%m-%d').date()
                        new_date = new_date_obj.strftime('%Y-%m-%d')
                        data_table.date = new_date
                        
                        if data_table.generated_from_event and data_table.generated_from_event.workplan and data_table.generated_from_event.workplan.study_start_date:
                            wp_start_date = data_table.generated_from_event.workplan.study_start_date
                            if isinstance(wp_start_date, datetime):
                                wp_start_date = wp_start_date.date()
                            
                            delta = new_date_obj - wp_start_date
                            data_table.generated_from_event.offset_days = delta.days
                    except ValueError:
                        flash(lazy_gettext('Invalid date format.'), 'danger')
            
            try:
                db.session.commit()
                flash(lazy_gettext('Metadata updated successfully.'), 'success')
            except Exception as e:
                db.session.rollback()
                flash(lazy_gettext('Error updating metadata: %(error)s') % {'error': str(e)}, 'danger')
            return redirect(url_for('datatables.edit_data_table', id=id))



        if 'submit_molecule_usage' in request.form:
             if not check_datatable_permission(data_table, 'edit_datatable'):
                 flash(lazy_gettext("You do not have permission to edit this DataTable."), "danger")
                 return redirect(url_for('datatables.edit_data_table', id=id))
                 
             mol_id_str = request.form.get('molecule_id')
             if mol_id_str:
                 mol_form = MoleculeUsageForm(prefix=f"mol_{mol_id_str}")
                 if mol_form.validate_on_submit():
                     try:
                         animal_ids_list = json.loads(mol_form.animal_ids.data) if mol_form.animal_ids.data else []
                         usage = DataTableMoleculeUsage(
                             data_table_id=data_table.id,
                             molecule_id=int(mol_id_str),
                             volume_used=mol_form.volume_used.data,
                             animal_ids=animal_ids_list,
                             number_of_animals=len(animal_ids_list),
                             recorded_by_id=current_user.id,
                             notes=mol_form.notes.data
                         )
                         db.session.add(usage)
                         db.session.commit()
                         flash(lazy_gettext("Molecule usage recorded successfully."), "success")
                     except Exception as e:
                         db.session.rollback()
                         current_app.logger.error(f"Error recording molecule usage: {e}", exc_info=True)
                         flash(lazy_gettext("Error recording usage: %(error)s") % {'error': str(e)}, "danger")
                 else:
                     for error in mol_form.errors.values():
                         flash(f"Error in usage form: {error}", "danger")
             
             return redirect(url_for('datatables.edit_data_table', id=id))

        elif upload_form.submit_upload.data and upload_form.validate_on_submit():
            file = request.files.get('file')
            if not file:
                flash(lazy_gettext("No file selected for upload."), "danger")
                return redirect(url_for('datatables.edit_data_table', id=id))

            try:
                # Use utility to read Excel
                data_list, columns = read_excel_to_list(file.stream)
                df = pd.DataFrame(data_list)
                current_app.logger.info(f"Uploaded Excel file for DataTable {id} read successfully. Columns: {columns}")

                id_col_name = None
                for col in columns:
                    if col.lower() == 'id':
                        id_col_name = col
                        break
                
                if not id_col_name:
                    flash(lazy_gettext("Uploaded file must contain an 'ID' column to match animals."), "danger")
                    return redirect(url_for('datatables.edit_data_table', id=id))

                protocol_analytes_map_for_upload = {a.name: a for a in data_table.protocol.analytes} if data_table.protocol and data_table.protocol.analytes else {}
                
                animal_id_to_row_index = {}
                for i, animal in enumerate(data_table.group.animal_data or []):
                    animal_id = animal.get('ID')
                    if animal_id is not None:
                        animal_id_to_row_index[str(animal_id).strip()] = i
                
                updates_from_upload = defaultdict(dict)
                upload_errors = []
                rows_updated_count = 0

                for row_idx, row in df.iterrows():
                    animal_id_from_file_raw = row.get(id_col_name)
                    if pd.isna(animal_id_from_file_raw):
                        upload_errors.append(lazy_gettext("Skipping row with missing 'ID'."))
                        continue
                    
                    animal_id_from_file = str(animal_id_from_file_raw).strip()
                    row_index = animal_id_to_row_index.get(animal_id_from_file)
                    if row_index is None:
                        upload_errors.append(lazy_gettext("Skipping row for ID '{animal_id}' not found in this group.").format(animal_id=animal_id_from_file))
                        continue
                    
                    data_changed_in_row = False
                    for col_name, value in row.items():
                        if col_name == id_col_name:
                            continue

                        if col_name in protocol_analytes_map_for_upload:
                            analyte_obj = protocol_analytes_map_for_upload[col_name]
                            try:
                                converted_value = validate_and_convert(value, analyte_obj, col_name, row_index)
                                
                                current_row_data = existing_data_rows_dict.get(row_index, {})
                                existing_value = current_row_data.get(col_name)

                                is_different = False
                                if existing_value is None and converted_value is not None: is_different = True
                                elif existing_value is not None and converted_value is None: is_different = True
                                elif isinstance(existing_value, float) and math.isnan(existing_value):
                                     if not (isinstance(converted_value, float) and math.isnan(converted_value)): is_different = True
                                elif isinstance(converted_value, float) and math.isnan(converted_value):
                                     if not (isinstance(existing_value, float) and math.isnan(existing_value)): is_different = True
                                elif str(existing_value) != str(converted_value): is_different = True

                                if is_different:
                                    updates_from_upload[row_index][col_name] = converted_value
                                    data_changed_in_row = True

                            except ValueError as e_val:
                                upload_errors.append(lazy_gettext("Row for ID '{animal_id}', Column '{col}': {error_msg}").format(animal_id=animal_id_from_file, col=col_name, error_msg=e_val))
                            except Exception as e_generic:
                                upload_errors.append(lazy_gettext("Row for ID '{animal_id}', Column '{col}': Unexpected error - {error_msg}").format(animal_id=animal_id_from_file, col=col_name, error_msg=e_generic))
                    
                    if data_changed_in_row:
                        rows_updated_count += 1

                if upload_errors:
                    for err in upload_errors:
                        flash(err, "danger")
                    flash(lazy_gettext("Upload completed with errors. Some data may not have been updated."), "warning")
                
                if updates_from_upload or any(a.calculation_formula for a in data_table.protocol.analyte_associations if data_table.protocol):
                    has_calc = any(a.calculation_formula for a in data_table.protocol.analyte_associations) if data_table.protocol else False
                    
                    # Iterate through ALL rows to ensure calculations are consistent
                    for r_idx in range(num_expected_rows):
                        vals = updates_from_upload.get(r_idx, {})
                        exp_row = existing_rows_query.filter(ExperimentDataRow.row_index == r_idx).first()
                        
                        # Prepare context: Combine Animal Data + Protocol Data + Manual Edits
                        current_data = {}
                        
                        # 1. Animal Model Data
                        if data_table.group and data_table.group.animal_data and r_idx < len(data_table.group.animal_data):
                            anim_row = data_table.group.animal_data[r_idx]
                            current_data.update(anim_row)
                            
                            # 1b. Inject Age (Days) into context if possible
                            date_of_birth_str = anim_row.get('Date of Birth')
                            if date_of_birth_str and data_table.date:
                                try:
                                    dob = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                                    dt_date = datetime.strptime(data_table.date, '%Y-%m-%d').date()
                                    current_data['Age (Days)'] = (dt_date - dob).days
                                except: pass

                        # 2. Existing Protocol Data
                        if exp_row:
                            current_data.update(exp_row.row_data or {})
                        
                        # 3. New updates from upload
                        current_data.update(vals)
                        
                        # 4. Apply Calculation
                        if has_calc:
                             current_data = calculation_service.calculate_row(current_data, data_table.protocol.analyte_associations)

                        # 5. Extract ONLY protocol fields for storage
                        protocol_only_data = {k: v for k, v in current_data.items() if k in protocol_field_names}
                        
                        if exp_row:
                            if exp_row.row_data != protocol_only_data:
                                exp_row.row_data = protocol_only_data
                                flag_modified(exp_row, "row_data")
                        elif protocol_only_data:
                            exp_row = ExperimentDataRow(data_table_id=id, row_index=r_idx, row_data=protocol_only_data)
                            db.session.add(exp_row)

                    db.session.commit()
                    flash(lazy_gettext("Successfully uploaded and updated {count} rows from the Excel file.").format(count=rows_updated_count), "success")
                else:
                    if not upload_errors:
                        flash(lazy_gettext("No data changes detected from the uploaded file."), "info")

                return redirect(url_for('datatables.edit_data_table', id=id))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error processing uploaded Excel file for DataTable {id}: {e}", exc_info=True)
                flash(lazy_gettext("Error processing uploaded file: {error_msg}").format(error_msg=str(e)), "danger")
            return redirect(url_for('datatables.edit_data_table', id=id))

        elif 'submit_grid' in request.form:
            validation_errors, data_changed = False, False
            updates = {}
            for k, v_form in request.form.items():
                if k in ['csrf_token', 'submit_grid'] or not k.startswith('cell_'): continue
                parts = k.split('_')
                if len(parts) == 3:
                    try:
                        r_idx, c_idx = int(parts[1]), int(parts[2])
                        if 0 <= r_idx < num_expected_rows and 0 <= c_idx < len(column_names):
                            col_name_manual = column_names[c_idx]
                            if col_name_manual in protocol_field_names:
                                analyte_obj_manual = protocol_analytes_map.get(col_name_manual)
                                if not analyte_obj_manual:
                                    flash(lazy_gettext("Cell edit error ({cell_id}) for column '{col}': Analyte definition not found.").format(cell_id=k, col=col_name_manual), 'danger'); validation_errors = True; continue
                                try:
                                    converted_value = validate_and_convert(v_form, analyte_obj_manual, col_name_manual, r_idx)
                                    current_row_data = existing_data_rows_dict.get(r_idx, {}); existing_value = current_row_data.get(col_name_manual); is_different = False
                                    if existing_value is None and converted_value is not None: is_different = True
                                    elif existing_value is not None and converted_value is None: is_different = True
                                    elif isinstance(existing_value, float) and math.isnan(existing_value):
                                         if not (isinstance(converted_value, float) and math.isnan(converted_value)): is_different = True
                                    elif isinstance(converted_value, float) and math.isnan(converted_value):
                                         if not (isinstance(existing_value, float) and math.isnan(existing_value)): is_different = True
                                    elif str(existing_value) != str(converted_value): is_different = True
                                    if is_different:
                                        if r_idx not in updates: updates[r_idx] = {}
                                        updates[r_idx][col_name_manual] = converted_value; data_changed = True
                                except ValueError as e_val_manual: flash(lazy_gettext("Row {row_num} Col '{col}': {error_msg}").format(row_num=r_idx+1, col=col_name_manual, error_msg=e_val_manual), 'danger'); validation_errors = True
                                except Exception as e_generic_manual: flash(lazy_gettext("Cell edit error ({cell_id}) for column '{col}': {error_msg}").format(cell_id=k, col=col_name_manual, error_msg=e_generic_manual), 'danger'); current_app.logger.error(f"Manual edit error cell {k} DT {id}: {e_generic_manual}"); validation_errors = True
                    except ValueError: current_app.logger.warning(f"Received malformed input name: {k}")
                    except Exception as e_outer_manual: current_app.logger.error(f"Unexpected error processing form key {k}: {e_outer_manual}"); validation_errors = True
            
            if (data_changed or any(a.calculation_formula for a in data_table.protocol.analyte_associations if data_table.protocol)) and not validation_errors:
                try:
                    has_calc = any(a.calculation_formula for a in data_table.protocol.analyte_associations) if data_table.protocol else False
                    
                    # Iterate through ALL rows to ensure calculations are consistent
                    for r_idx in range(num_expected_rows):
                        vals = updates.get(r_idx, {})
                        exp_row = existing_rows_query.filter(ExperimentDataRow.row_index == r_idx).first()
                        
                        # Prepare context: Combine Animal Data + Protocol Data + Manual Edits
                        current_data = {}
                        
                        # 1. Animal Model Data
                        if data_table.group and data_table.group.animal_data and r_idx < len(data_table.group.animal_data):
                            anim_row = data_table.group.animal_data[r_idx]
                            current_data.update(anim_row)
                            
                            # 1b. Inject Age (Days) into context
                            date_of_birth_str = anim_row.get('Date of Birth')
                            if date_of_birth_str and data_table.date:
                                try:
                                    dob = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                                    dt_date = datetime.strptime(data_table.date, '%Y-%m-%d').date()
                                    current_data['Age (Days)'] = (dt_date - dob).days
                                except: pass

                        # 2. Existing Protocol Data
                        if exp_row:
                            current_data.update(exp_row.row_data or {})
                        
                        # 3. Manual Edits from THIS session
                        current_data.update(vals)
                        
                        # 4. Apply Calculation
                        if has_calc:
                             current_data = calculation_service.calculate_row(current_data, data_table.protocol.analyte_associations)

                        # 5. Extract ONLY protocol fields for storage
                        protocol_only_data = {k: v for k, v in current_data.items() if k in protocol_field_names}
                        
                        if exp_row:
                            if exp_row.row_data != protocol_only_data:
                                exp_row.row_data = protocol_only_data
                                flag_modified(exp_row, "row_data")
                        elif protocol_only_data:
                            exp_row = ExperimentDataRow(data_table_id=id, row_index=r_idx, row_data=protocol_only_data)
                            db.session.add(exp_row)
                    db.session.commit()
                    flash(lazy_gettext('Modifications saved.'), 'success')
                    return redirect(url_for('datatables.edit_data_table', id=id))
                except Exception as e_db_manual: db.session.rollback(); flash(lazy_gettext("Database save error: {error_msg}").format(error_msg=e_db_manual), 'danger'); current_app.logger.error(f"Database error saving manual edits for DataTable {id}: {e_db_manual}"); validation_errors = True
            elif not data_changed and not validation_errors: flash(lazy_gettext('No changes were made.'), 'info')
            elif validation_errors: flash(lazy_gettext("Changes not saved due to validation errors."), 'warning')

    updated_rows = data_table.experiment_rows.order_by(ExperimentDataRow.row_index).all()
    updated_dict = {r.row_index: r.row_data for r in updated_rows}
    updated_group_data = data_table.group.animal_data or []
    template_data = prepare_template_data(updated_dict, updated_group_data, column_names)
    protocol_field_units = {a.name: a.unit for a in data_table.protocol.analytes} if data_table.protocol else {}
    date_fields = [a.name for a in data_table.protocol.analytes if a.data_type == AnalyteDataType.DATE] if data_table.protocol else []
    
    calculated_fields = [a.analyte.name for a in data_table.protocol.analyte_associations if a.calculation_formula] if data_table.protocol else []

    controlled_molecules_data = []
    if data_table.protocol and data_table.protocol.molecule_associations:
        for assoc in data_table.protocol.molecule_associations:
            molecule = assoc.molecule
            if molecule.is_active:
                form_prefix = f"mol_{molecule.id}"
                
                # Check for submitted form data for this specific molecule
                if request.method == 'POST' and request.form.get('molecule_id') == str(molecule.id):
                    mol_form = MoleculeUsageForm(prefix=form_prefix)
                else:
                    mol_form = MoleculeUsageForm(prefix=form_prefix)

                usages = DataTableMoleculeUsage.query.filter_by(
                    data_table_id=data_table.id,
                    molecule_id=molecule.id
                ).order_by(DataTableMoleculeUsage.recorded_at.desc()).all()
                
                controlled_molecules_data.append({
                    'molecule': molecule,
                    'form': mol_form,
                    'usages': usages
                })

    return render_template('datatables/edit_data_table.html',
                           data_table=data_table, column_names=column_names, num_rows=num_expected_rows,
                           template_data=template_data, protocol_field_units=protocol_field_units,
                           is_read_only=is_read_only, upload_form=upload_form, date_fields=date_fields,
                           animal_model_field_names=animal_model_field_names,
                           metadata_fields=list(metadata_fields), assignee_and_housing_form=assignee_and_housing_form,
                           edit_form=edit_form, calculated_fields=calculated_fields,
                           controlled_molecules_data=controlled_molecules_data)


@datatables_bp.route('/<int:datatable_id>/move', methods=['POST'])
@login_required
def move_datatable(datatable_id):
    dt = db.session.get(DataTable, datatable_id)
    if not dt:
        return jsonify({'success': False, 'message': 'DataTable not found'}), 404
    if not check_datatable_permission(dt, 'edit_datatable'):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()
    new_date_str = data.get('new_date')
    if not new_date_str:
        return jsonify({'success': False, 'message': 'New date is required.'}), 400

    try:
        new_date_obj = datetime.strptime(new_date_str, '%Y-%m-%d').date()
        new_date = new_date_obj.strftime('%Y-%m-%d')
        dt.date = new_date
        
        # If linked to a workplan event, update the event offset to keep calendar in sync
        if dt.generated_from_event and dt.generated_from_event.workplan and dt.generated_from_event.workplan.study_start_date:
            wp_start_date = dt.generated_from_event.workplan.study_start_date
            # Ensure we are comparing dates
            if isinstance(wp_start_date, datetime):
                wp_start_date = wp_start_date.date()
                
            delta = new_date_obj - wp_start_date
            dt.generated_from_event.offset_days = delta.days

        db.session.commit()
        return jsonify({'success': True, 'message': 'DataTable date updated.'})
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format.'}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error moving datatable {datatable_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@datatables_bp.route('/<int:datatable_id>/reassign', methods=['POST'])
@login_required
def reassign_datatable(datatable_id):
    dt = db.session.get(DataTable, datatable_id)
    if not dt:
        return jsonify({'success': False, 'message': 'DataTable not found'}), 404
    if not check_datatable_permission(dt, 'edit_datatable'):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()
    new_assignee_id = data.get('assignee_id')

    try:
        dt.assigned_to_id = int(new_assignee_id) if new_assignee_id else None
        
        warning_message = None
        # Skill Validation Integration (Reassign API)
        if dt.assigned_to_id and dt.protocol.external_skill_ids:
             user = db.session.get(User, dt.assigned_to_id)
             if user:
                try:
                    connector = TrainingManagerConnector()
                    skill_ids = dt.protocol.external_skill_ids
                    if skill_ids:
                        result = connector.check_competency([user.email], skill_ids)
                        if result and user.email in result:
                            user_result = result[user.email]
                            if not user_result.get('valid', True):
                                details = user_result.get('details', [])
                                warning_message = _("Warning: The user '%(email)s' may not be qualified. Issues: %(issues)s", email=user.email, issues=", ".join(details))
                except Exception as e:
                    current_app.logger.error(f"Error validating skills on reassign: {e}")

        db.session.commit()
        return jsonify({'success': True, 'message': 'Assignee updated.', 'warning': warning_message})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error reassigning datatable {datatable_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@datatables_bp.route('/edit/<int:id>/delete_file/<int:file_id>', methods=['POST'])
@login_required
def delete_data_table_file(id, file_id):
    data_table = db.session.get(DataTable, id)
    if not data_table or not check_datatable_permission(data_table, 'edit_datatable'):
        flash(lazy_gettext("Permission denied."), "danger")
        return redirect(url_for('main.index'))

    file_to_delete = db.session.get(DataTableFile, file_id)
    if not file_to_delete or file_to_delete.data_table_id != id:
        flash(lazy_gettext("File not found."), "error")
        return redirect(url_for('datatables.edit_data_table', id=id))

    try:
        if os.path.exists(file_to_delete.filepath):
            os.remove(file_to_delete.filepath)
        db.session.delete(file_to_delete)
        db.session.commit()
        flash(lazy_gettext("File deleted successfully."), "success")
    except Exception as e:
        db.session.rollback()
        flash(lazy_gettext("Error deleting file: %(error)s", error=str(e)), "danger")
        current_app.logger.error(f"Error deleting file {file_id} from datatable {id}: {e}", exc_info=True)

    return redirect(url_for('datatables.edit_data_table', id=id))

@datatables_bp.route('/edit/<int:id>/view_file/<int:file_id>')
@login_required
def view_data_table_file(id, file_id):
    data_table = db.session.get(DataTable, id)
    if not data_table or not check_datatable_permission(data_table, 'read'):
        flash(lazy_gettext("Permission denied."), "danger")
        return redirect(url_for('main.index'))

    file_to_view = db.session.get(DataTableFile, file_id)
    if not file_to_view or file_to_view.data_table_id != id:
        flash(lazy_gettext("File not found."), "error")
        return redirect(url_for('datatables.edit_data_table', id=id))

    try:
        return send_file(file_to_view.filepath, as_attachment=False)
    except Exception as e:
        current_app.logger.error(f"Error sending file {file_id} from datatable {id}: {e}", exc_info=True)
        flash(lazy_gettext("Error sending file."), "danger")
        return redirect(url_for('datatables.edit_data_table', id=id))
                           
@datatables_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete_data_table(id):
    dt_obj = db.session.get(DataTable, id)
    if not dt_obj or not dt_obj.group:
        flash(lazy_gettext("Table not found."), "error"); return redirect(url_for('main.index'))
    gid = dt_obj.group_id
    if not check_datatable_permission(dt_obj, 'delete_datatable'):
        flash(lazy_gettext("You do not have permission to delete this DataTable."), "danger")
        return redirect(url_for('datatables.list_group_datatables', group_id=gid))
    try:
        db.session.delete(dt_obj)
        db.session.commit(); flash(lazy_gettext("DataTable successfully deleted."), "success")
    except Exception as e:
        db.session.rollback(); flash(lazy_gettext("Error deleting DataTable: {error_msg}").format(error_msg=str(e)), "danger")
        current_app.logger.error(f"Error deleting DataTable {id}: {e}", exc_info=True)
    return redirect(url_for('datatables.list_group_datatables', group_id=gid))

@datatables_bp.route('/list/model/<string:model_type>/<int:model_id>')
@login_required
def list_model_datatables(model_type, model_id):
    ModelClass = None; model_name_display = ""; base_query_list = None
    if model_type == 'animal': ModelClass = AnimalModel
    elif model_type == 'protocol': ModelClass = ProtocolModel
    else: flash(lazy_gettext("Invalid model type specified."), 'error'); return redirect(url_for('core_models.manage_models'))
    model_obj_display = db.session.get(ModelClass, model_id)
    if not model_obj_display:
        flash(lazy_gettext("{model_type} with ID {model_id} not found.").format(model_type=ModelClass.__name__, model_id=model_id), 'error')
        return redirect(url_for('core_models.manage_models'))
    model_name_display = model_obj_display.name
    if model_type == 'animal': base_query_list = DataTable.query.join(ExperimentalGroup).filter(ExperimentalGroup.model_id == model_obj_display.id)
    elif model_type == 'protocol': base_query_list = DataTable.query.filter(DataTable.protocol_id == model_obj_display.id)
    readable_dts_list = []
    if base_query_list:
        query_list = base_query_list.options(db.joinedload(DataTable.group).joinedload(ExperimentalGroup.model), db.joinedload(DataTable.protocol), db.joinedload(DataTable.group).joinedload(ExperimentalGroup.project)).order_by(DataTable.date.desc(), DataTable.id.desc())
        all_related_list = query_list.all()
        
        # Batch-fetch permissions
        from app.services.permission_service import PermissionService
        perm_service = PermissionService()
        unique_projects = {dt.group.project for dt in all_related_list if dt.group and dt.group.project}
        project_permissions = perm_service.get_bulk_project_permissions(current_user, unique_projects)
        
        readable_dts_list = []
        for dt_item in all_related_list:
            if dt_item.group and dt_item.group.project:
                perms = project_permissions.get(dt_item.group.project.id, {})
                if perms.get('can_view_datatables', False):
                    readable_dts_list.append(dt_item)
    if model_type == 'animal':
        if readable_dts_list:
             first_accessible_group_list = next((dt_item.group for dt_item in readable_dts_list if dt_item.group), None)
             if first_accessible_group_list:
                  flash(lazy_gettext("This page lists datatables associated with {model_type} '{model_name}'. You can download aggregated data from the Group's datatable list.").format(model_type=model_type, model_name=model_name_display), 'info')
                  return redirect(url_for('datatables.list_group_datatables', group_id=first_accessible_group_list.id))
             else: flash(lazy_gettext("No accessible groups found for datatables associated with {model_type} '{model_name}'").format(model_type=model_type, model_name=model_name_display), 'warning'); return redirect(url_for('main.index'))
        else: flash(lazy_gettext("No accessible datatables found for {model_type} '{model_name}'").format(model_type=model_type, model_name=model_name_display), 'warning'); return render_template('datatables/list_model_datatables.html', model_type=model_type, model_name=model_name_display, data_tables=[], show_download_button=False)
    if not readable_dts_list and model_type == 'protocol':
        flash(lazy_gettext("No accessible datatables found for {model_type} '{model_name}'").format(model_type=model_type, model_name=model_name_display), 'warning')
        return render_template('datatables/list_model_datatables.html', model_type=model_type, model_name=model_name_display, data_tables=[], show_download_button=False)
    if model_type == 'protocol':
        all_animal_keys_union_list = set(); all_protocol_keys_union_list = set()
        for dt_item in readable_dts_list:
             dt_animal_data_keys_list = set().union(*(d.keys() for d in (dt_item.group.animal_data or []))) if dt_item.group and dt_item.group.animal_data else set()
             dt_protocol_field_names_list = [a.name for a in dt_item.protocol.analytes] if dt_item.protocol and dt_item.protocol.analytes else []
             all_animal_keys_union_list.update(dt_animal_data_keys_list); all_protocol_keys_union_list.update(dt_protocol_field_names_list)
        final_ordered_data_cols_list = get_custom_ordered_columns(all_animal_keys_union_list, all_protocol_keys_union_list)
        final_cols_list = ['Group', 'Protocol', 'Date'] + final_ordered_data_cols_list; all_rows_list = []
        for dt_item in readable_dts_list:
            g_name_list = dt_item.group.name if dt_item.group else "N/A"; p_name_list = dt_item.protocol.name if dt_item.protocol else "N/A"; t_date_list = dt_item.date
            rows_q_list = dt_item.experiment_rows.order_by(ExperimentDataRow.row_index); data_dict_list = {r.row_index: r.row_data for r in rows_q_list.all()}
            group_anim_data_list = dt_item.group.animal_data or []
            for i_list in range(len(group_anim_data_list)):
                merged_list = group_anim_data_list[i_list].copy() if i_list < len(group_anim_data_list) else {}; merged_list.update(data_dict_list.get(i_list, {}))
                row_dict_list = {'Group': g_name_list, 'Protocol': p_name_list, 'Date': t_date_list.strftime('%Y-%m-%d') if hasattr(t_date_list, 'strftime') else str(t_date_list)}
                row_data_values_list = {f: merged_list.get(f) for f in final_ordered_data_cols_list}; row_dict_list.update(row_data_values_list)
                all_rows_list.append(row_dict_list)
        if not all_rows_list:
             flash(lazy_gettext("No data rows found across accessible datatables for Protocol '{protocol_name}'").format(protocol_name=model_name_display), 'warning')
             return render_template('datatables/list_model_datatables.html', model_type=model_type, model_name=model_name_display, data_tables=[], show_download_button=False)
        
        df_list = pd.DataFrame(all_rows_list, columns=final_cols_list)
        if 'Date' in df_list.columns: df_list['Date'] = pd.to_datetime(df_list['Date'], errors='coerce')
        
        # Use utility for download
        output_list = dataframe_to_excel_bytes(df_list)
        fname_list = f'{model_name_display}_all_datatables_agg'.replace(' ', '_').replace('/','-').replace(':','-') + '.xlsx'
        mime_list = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        return send_file(output_list, mimetype=mime_list, as_attachment=True, download_name=fname_list)

    return render_template('datatables/list_model_datatables.html', model_type=model_type, model_name=model_name_display, data_tables=[], show_download_button=False)

@datatables_bp.route('/list/group/<string:group_id>')
@login_required
def list_group_datatables(group_id):
    # Handle cases where group_id might be literally 'undefined' from client-side issues
    if group_id == 'undefined':
        flash(lazy_gettext("Invalid group identifier provided."), "error")
        return redirect(url_for('main.index'))

    group_obj = db.session.get(ExperimentalGroup, group_id)
    if not group_obj: flash(lazy_gettext("Group not found."), "error"); return redirect(url_for('main.index'))
    
    if not check_group_permission(group_obj, 'read'): flash(lazy_gettext("Permission denied."), "danger"); return redirect(url_for('groups.manage_groups'))

    if request.args.get('download_agg') == 'True':
        # Get all datatables for this group that the user can read
        datatables = DataTable.query.filter_by(group_id=group_id).all()
        accessible_dt_ids = [str(dt.id) for dt in datatables if check_datatable_permission(dt, 'read')]
        
        if not accessible_dt_ids:
            flash(_("No accessible datatables found to download."), "warning")
            return redirect(url_for('datatables.list_group_datatables', group_id=group_id))

        # Reuse the aggregation service logic
        df_combined, errors, unused_sources_ids = datatable_service.aggregate_selected_datatables(accessible_dt_ids)
        
        if errors:
            for err in errors: flash(err, "danger")
            return redirect(url_for('datatables.list_group_datatables', group_id=group_id))
            
        if df_combined is None or df_combined.empty:
            flash(_("No data available to download."), "warning")
            return redirect(url_for('datatables.list_group_datatables', group_id=group_id))

        fname = f'{group_obj.name}_all_data.xlsx'
        mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        
        try:
            output = dataframe_to_excel_bytes(df_combined)
            return send_file(output, mimetype=mime, as_attachment=True, download_name=fname)
        except Exception as e:
            current_app.logger.error(f"Error generating aggregated download for group {group_id}: {e}", exc_info=True)
            flash(_("Error generating file."), "danger")
            return redirect(url_for('datatables.list_group_datatables', group_id=group_id))

    # Fetch all protocols for the filter dropdown
    all_protocols = ProtocolModel.query.order_by(ProtocolModel.name).all()

    return render_template('datatables/list_group_datatables.html', group=group_obj, protocols=all_protocols)
@datatables_bp.route('/batch_delete_datatables', methods=['POST'])
@login_required
def batch_delete_datatables():
    data = request.get_json()
    datatable_ids_from_payload = data.get('datatable_ids', [])
    select_all_matching = data.get('select_all_matching', 'false') == 'true'
    filters = data.get('filters', {})

    datatables_to_process_ids = []

    if select_all_matching:
        # Construct filters dictionary for the service call
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'group_id': filters.get('group_id'),
            'protocol_id': filters.get('protocol_id'),
            'date_from': filters.get('date_from'),
            'date_to': filters.get('date_to')
        }
        
        # Retrieve all matching datatables using the service (ignoring pagination for batch ops)
        all_matching_datatables_result = datatable_service.get_server_side_datatables(
            user=current_user,
            filters=service_filters,
            page=1, # Get all results
            per_page=9999999, # Large number to get all results
            sort_column='created_at', # Dummy sort
            sort_direction='asc' # Dummy sort
        )
        datatables_to_process_ids = [dt.id for dt in all_matching_datatables_result['items']]
    else:
        datatables_to_process_ids = datatable_ids_from_payload

    if not datatables_to_process_ids:
        return jsonify({'success': False, 'message': _('No datatables selected or found for deletion.')}), 400

    deleted_count = 0
    errors = []
    for dt_id in datatables_to_process_ids:
        dt = db.session.get(DataTable, dt_id)
        if not dt:
            errors.append(_(f"Datatable {dt_id} not found."))
            continue
        if not check_datatable_permission(dt, 'delete_datatable'):
            errors.append(_(f"Permission denied for datatable {dt.name}."))
            continue

        try:
            db.session.delete(dt)
            db.session.commit()
            deleted_count += 1
        except Exception as e:
            db.session.rollback()
            errors.append(_(f"Error deleting datatable {dt.name}: {e}"))
            
    if errors:
        return jsonify({'success': False, 'message': _('Some datatables could not be deleted.'), 'errors': errors}), 400
    return jsonify({'success': True, 'message': _(f'Successfully deleted {deleted_count} datatables.')}), 200

@datatables_bp.route('/get_batch_analysis_ids', methods=['POST'])
@login_required
def get_batch_analysis_ids():
    data = request.get_json()
    datatable_ids_from_payload = data.get('datatable_ids', [])
    select_all_matching = data.get('select_all_matching', 'false') == 'true'
    filters = data.get('filters', {})

    datatables_to_process_ids = []

    if select_all_matching:
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'group_id': filters.get('group_id'),
            'protocol_id': filters.get('protocol_id'),
            'date_from': filters.get('date_from'),
            'date_to': filters.get('date_to')
        }
        
        all_matching_datatables_result = datatable_service.get_server_side_datatables(
            user=current_user,
            filters=service_filters,
            page=1, 
            per_page=9999999, 
            sort_column='created_at',
            sort_direction='asc'
        )
        datatables_to_process_ids = [dt.id for dt in all_matching_datatables_result['items']]
    else:
        datatables_to_process_ids = [int(x) for x in datatable_ids_from_payload if isinstance(x, (int, str)) and str(x).isdigit()]
    
    return jsonify({
        'success': True,
        'datatable_ids': datatables_to_process_ids,
        'message': _('Datatable IDs resolved for batch analysis.')
    }), 200

@datatables_bp.route('/download_merged_selected', methods=['POST'])
@login_required
def download_merged_selected_datatables():
    # Handle both JSON (from JS fetch) and Form Data (from standard submit)
    if request.is_json:
        data = request.get_json()
        datatable_ids_from_payload = data.get('datatable_ids', [])
        select_all_matching = data.get('select_all_matching', 'false') == 'true'
        filters = data.get('filters', {})
    else:
        # Fallback for standard form submission
        datatable_ids_from_payload = request.form.getlist('selected_datatable_ids[]')
        # Convert string IDs to integers
        datatable_ids_from_payload = [int(x) for x in datatable_ids_from_payload if x.isdigit()]
        select_all_matching = request.form.get('select_all_matching') == 'true'
        # Filters might need to be passed as hidden fields if using select_all_matching with form submit
        filters = {} 

    datatables_to_process_ids = []

    if select_all_matching:
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'group_id': filters.get('group_id'),
            'protocol_id': filters.get('protocol_id'),
            'date_from': filters.get('date_from'),
            'date_to': filters.get('date_to')
        }
        all_matching_datatables_result = datatable_service.get_server_side_datatables(
            user=current_user,
            filters=service_filters,
            page=1,
            per_page=9999999,
            sort_column='created_at',
            sort_direction='asc'
        )
        datatables_to_process_ids = [dt.id for dt in all_matching_datatables_result['items']]
    else:
        datatables_to_process_ids = datatable_ids_from_payload

    if not datatables_to_process_ids:
        flash(_("No DataTables selected or found for download."), "warning") 
        # If it was an AJAX request, return JSON
        if request.is_json:
             return jsonify({'success': False, 'message': _('No DataTables selected or found for download.')}), 400
        return redirect(request.referrer or url_for('datatables.create_data_table'))
    
    selected_ids_str_merged = [str(dt_id) for dt_id in datatables_to_process_ids]

    # Use the service method for aggregation
    df_combined_merged, errors_merged, source_identifiers_merged = datatable_service.aggregate_selected_datatables(selected_ids_str_merged)
    
    if errors_merged:
        for err_merged in errors_merged: flash(err_merged, "danger")
    
    if df_combined_merged is None or df_combined_merged.empty: 
        flash(_("No data available to download after merging."), "warning")
        if request.is_json:
            return jsonify({'success': False, 'message': _('No data available to download after merging.')}), 400
        return redirect(request.referrer or url_for('datatables.create_data_table'))
    
    fname_part_merged = "merged_selection"
    if source_identifiers_merged: 
        # Create a safe filename from the first identifier or a generic one
        safe_id = source_identifiers_merged[0].replace(" ", "_").replace("/", "-").replace(":", "-")
        fname_part_merged = f"{safe_id}_plus_{len(source_identifiers_merged)-1}" if len(source_identifiers_merged) > 1 else safe_id

    fname_merged = f'{fname_part_merged}_merged_data.xlsx'
    mime_merged = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    try:
        output_merged = dataframe_to_excel_bytes(df_combined_merged)
        response = make_response(output_merged)
        response.headers["Content-Disposition"] = f"attachment; filename={fname_merged}"
        response.headers["Content-Type"] = mime_merged
        return response
    except Exception as e:
        current_app.logger.error(f"Merged Excel download error: {e}", exc_info=True)
        flash(_("Error generating merged file for download: {error_msg}").format(error_msg=str(e)), 'error')
        if request.is_json:
            return jsonify({'success': False, 'message': _('Error generating merged file for download.')}), 500
        return redirect(request.referrer or url_for('datatables.create_data_table'))

@datatables_bp.route('/download_merged_transposed_selected', methods=['POST'])
@login_required
def download_merged_transposed_selected_datatables():
    # Handle both JSON (from JS fetch) and Form Data (from standard submit)
    if request.is_json:
        data = request.get_json()
        datatable_ids_from_payload = data.get('datatable_ids', [])
        select_all_matching = data.get('select_all_matching', 'false') == 'true'
        filters = data.get('filters', {})
    else:
        # Fallback for standard form submission
        datatable_ids_from_payload = request.form.getlist('selected_datatable_ids[]')
        datatable_ids_from_payload = [int(x) for x in datatable_ids_from_payload if x.isdigit()]
        select_all_matching = request.form.get('select_all_matching') == 'true'
        filters = {}

    datatables_to_process_ids = []

    if select_all_matching:
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'group_id': filters.get('group_id'),
            'protocol_id': filters.get('protocol_id'),
            'date_from': filters.get('date_from'),
            'date_to': filters.get('date_to')
        }
        all_matching_datatables_result = datatable_service.get_server_side_datatables(
            user=current_user,
            filters=service_filters,
            page=1,
            per_page=9999999,
            sort_column='created_at',
            sort_direction='asc'
        )
        datatables_to_process_ids = [dt.id for dt in all_matching_datatables_result['items']]
    else:
        datatables_to_process_ids = datatable_ids_from_payload

    if not datatables_to_process_ids:
        flash(_("No DataTables selected or found for download."), "warning") 
        if request.is_json:
            return jsonify({'success': False, 'message': _('No DataTables selected or found for download.')}), 400
        return redirect(request.referrer or url_for('datatables.create_data_table'))
    
    selected_ids_str_trans_merged = [str(dt_id) for dt_id in datatables_to_process_ids]

    # Use the service method for aggregation
    df_combined_trans_merged, errors_trans_merged, source_identifiers_trans_merged = datatable_service.aggregate_selected_datatables(selected_ids_str_trans_merged)
    
    if errors_trans_merged:
        for err_trans_merged in errors_trans_merged: flash(err_trans_merged, "danger")
    
    if df_combined_trans_merged is None or df_combined_trans_merged.empty: 
        flash(_("No data available to download after merging."), "warning")
        if request.is_json:
            return jsonify({'success': False, 'message': _('No data available to download after merging.')}), 400
        return redirect(request.referrer or url_for('datatables.create_data_table'))
    
    df_for_transpose_trans_merged = df_combined_trans_merged.copy(); original_subject_id_col_name_trans_merged = 'ID'
    source_cols_trans_merged = ['_source_datatable_id', '_source_experimental_group_name', '_source_protocol_name', '_source_datatable_date']
    
    parameter_cols_trans_merged = [col for col in df_for_transpose_trans_merged.columns if col not in source_cols_trans_merged]
    
    df_for_transpose_trans_merged['_temp_row_identifier_'] = range(len(df_for_transpose_trans_merged))
    
    index_for_pivot_trans_merged = '_unique_subject_header_'
    
    if original_subject_id_col_name_trans_merged in df_for_transpose_trans_merged.columns:
        df_for_transpose_trans_merged[original_subject_id_col_name_trans_merged] = df_for_transpose_trans_merged[original_subject_id_col_name_trans_merged].astype(str).fillna('UnknownID')
        source_group_col = '_source_experimental_group_name'
        if source_group_col in df_for_transpose_trans_merged.columns:
             df_for_transpose_trans_merged[source_group_col] = df_for_transpose_trans_merged[source_group_col].astype(str).fillna('UnknownGroup')
             df_for_transpose_trans_merged['_candidate_subject_header_'] = df_for_transpose_trans_merged.apply(lambda row: f"{row[source_group_col]}_{row[original_subject_id_col_name_trans_merged]}", axis=1)
        else:
             df_for_transpose_trans_merged['_candidate_subject_header_'] = df_for_transpose_trans_merged[original_subject_id_col_name_trans_merged]

        if df_for_transpose_trans_merged['_candidate_subject_header_'].duplicated().any():
            df_for_transpose_trans_merged['_unique_subject_header_'] = df_for_transpose_trans_merged.groupby('_candidate_subject_header_').cumcount().astype(str).radd('_v').radd(df_for_transpose_trans_merged['_candidate_subject_header_'])
            flash(lazy_gettext("Warning: Some subjects from different original tables had identical Group_ID combinations. Counters appended to make transposed column headers unique."), "warning")
        else: 
            df_for_transpose_trans_merged['_unique_subject_header_'] = df_for_transpose_trans_merged['_candidate_subject_header_']
    else:
        flash(lazy_gettext("Original Subject ID column ('{col}') not found or not suitable for merged transposed headers. Using generic 'Subject_X' based on row order.").format(col=original_subject_id_col_name_trans_merged), "warning")
        df_for_transpose_trans_merged['_unique_subject_header_'] = "Subject_" + (df_for_transpose_trans_merged['_temp_row_identifier_'] + 1).astype(str)
    
    try:
        df_to_pivot_trans_merged = df_for_transpose_trans_merged[parameter_cols_trans_merged + [index_for_pivot_trans_merged]]
        df_pivot_ready_trans_merged = df_to_pivot_trans_merged.set_index(index_for_pivot_trans_merged)
        df_transposed_final_trans_merged = df_pivot_ready_trans_merged.transpose()
    except Exception as e_pivot_trans_merged:
        current_app.logger.error(f"Error during pivot/transpose for merged data: {e_pivot_trans_merged}. Falling back to basic transpose.", exc_info=True)
        flash(lazy_gettext("Error creating transposed table structure: {error_msg}. Attempting basic transpose with generic headers.").format(error_msg=str(e_pivot_trans_merged)), "warning")
        df_transposed_final_trans_merged = df_for_transpose_trans_merged[parameter_cols_trans_merged].transpose() 
        df_transposed_final_trans_merged.columns = [f"Subject_{i_trans_merged_col+1}" for i_trans_merged_col in range(len(df_transposed_final_trans_merged.columns))]
    
    fname_part_trans_merged = "merged_selection"
    if source_identifiers_trans_merged: 
        safe_id = source_identifiers_trans_merged[0].replace(" ", "_").replace("/", "-").replace(":", "-")
        fname_part_trans_merged = f"{safe_id}_plus_{len(source_identifiers_trans_merged)-1}" if len(source_identifiers_trans_merged) > 1 else safe_id

    fname_trans_merged = f'{fname_part_trans_merged}_merged_transposed_prism.xlsx'
    mime_trans_merged = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    try:
        output_trans_merged = dataframe_to_excel_bytes(df_transposed_final_trans_merged, index=True, header=True)
        response = make_response(output_trans_merged)
        response.headers["Content-Disposition"] = f"attachment; filename={fname_trans_merged}"
        response.headers["Content-Type"] = mime_trans_merged
        return response
    except Exception as e_trans_merged_excel:
        current_app.logger.error(f"Merged transposed Excel download error: {e_trans_merged_excel}", exc_info=True)
        flash(lazy_gettext("Error generating merged transposed file for download: {error_msg}").format(error_msg=str(e_trans_merged_excel)), 'error')
        if request.is_json:
            return jsonify({'success': False, 'message': _('Error generating merged transposed file for download.')}), 500
        return redirect(request.referrer or url_for('datatables.create_data_table'))

@datatables_bp.route('/api/reference_range_options/<int:protocol_id>', methods=['GET'])
@login_required
def get_reference_range_options(protocol_id):
    groups_with_protocol = ExperimentalGroup.query.join(DataTable).filter(
        DataTable.protocol_id == protocol_id
    ).distinct(ExperimentalGroup.id).all()

    parameters_by_model = defaultdict(lambda: defaultdict(set))
    model_info = {}

    for group in groups_with_protocol:
        if not check_group_permission(group, 'read'):
            continue
        
        if group.model and group.animal_data and isinstance(group.animal_data, list):
            model_id = group.model.id
            if model_id not in model_info:
                model_info[model_id] = group.model.name
            
            for animal in group.animal_data:
                for key, value in animal.items():
                    if key.lower() not in ['id', 'date of birth'] and value is not None and str(value).strip() != '':
                        parameters_by_model[model_id][key].add(str(value))

    final_params_by_model = {
        model_id: {param: sorted(list(values)) for param, values in params.items()}
        for model_id, params in parameters_by_model.items()
    }

    return jsonify({
        'models': [{'id': mid, 'name': mname} for mid, mname in model_info.items()],
        'parameters_by_model': final_params_by_model
    })

@datatables_bp.route('/api/calculate_reference_range/<int:datatable_id>', methods=['POST'])
@login_required
def calculate_reference_range(datatable_id):
    data_table = db.session.get(DataTable, datatable_id)
    if not data_table:
        return jsonify({'error': 'DataTable not found'}), 404

    data = request.get_json()
    ref_range_id = data.get('reference_range_id')
    age_tolerance_days = data.get('age_tolerance_days')

    ref_range = db.session.get(ReferenceRange, ref_range_id)
    if not ref_range:
        return jsonify({'error': 'Reference Range definition not found.'}), 404
    
    datatables_query = DataTable.query.join(ExperimentalGroup).filter(
        DataTable.protocol_id == ref_range.protocol_id
    )
    
    all_matching_dts = datatables_query.all()

    reference_data = defaultdict(list)
    
    potential_numerical_protocol_fields = []
    if ref_range.protocol and ref_range.protocol.analytes:
        for analyte in ref_range.protocol.analytes:
            if analyte.data_type.value in ['integer', 'float']:
                potential_numerical_protocol_fields.append(analyte.name)
    
    current_dt_avg_age = None
    if age_tolerance_days is not None and data_table.group.animal_data:
        ages = []
        try:
            current_dt_date = datetime.strptime(data_table.date, '%Y-%m-%d').date()
            for animal in data_table.group.animal_data:
                dob_str = animal.get('Date of Birth')
                if dob_str:
                    try:
                        dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                        ages.append((current_dt_date - dob).days)
                    except (ValueError, TypeError):
                        continue
            if ages:
                current_dt_avg_age = sum(ages) / len(ages)
        except (ValueError, TypeError):
             pass

    reference_dt_ids = []
    for dt in all_matching_dts:
        if not check_datatable_permission(dt, 'read'):
            continue
        
        reference_dt_ids.append(dt.id)
        
        if not dt.group.animal_data:
            continue

        try:
            dt_date = datetime.strptime(dt.date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue

        for i, animal in enumerate(dt.group.animal_data):
            if not ref_range.included_animals:
                matches_cohort_or_inclusion = True
            elif str(dt.group.id) in ref_range.included_animals and i in ref_range.included_animals[str(dt.group.id)]:
                matches_cohort_or_inclusion = True
            else:
                matches_cohort_or_inclusion = False

            if not matches_cohort_or_inclusion:
                continue

            if current_dt_avg_age is not None and age_tolerance_days is not None:
                dob_str = animal.get('Date of Birth')
                if dob_str:
                    try:
                        dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                        age = (dt_date - dob).days
                        if abs(age - current_dt_avg_age) > age_tolerance_days:
                            continue
                    except (ValueError, TypeError):
                        continue
                else: 
                    continue

            exp_row = dt.experiment_rows.filter_by(row_index=i).first()
            if exp_row and exp_row.row_data:
                for field in potential_numerical_protocol_fields:
                    if field in exp_row.row_data:
                        value = exp_row.row_data[field]
                        try:
                            numeric_value = float(value)
                            if not math.isnan(numeric_value):
                                reference_data[field].append(numeric_value)
                        except (ValueError, TypeError):
                            pass

    results = {}
    for field, values in reference_data.items():
        if values:
            df_series = pd.Series(values)
            std_val = df_series.std()
            if pd.isna(std_val):
                std_val = 0.0
            results[field] = {
                'mean': float(df_series.mean()),
                'std': float(std_val),
                'n': int(len(values)),
                'min': float(df_series.min()),
                'max': float(df_series.max())
            }
    
    return jsonify({
        'stats': results,
        'reference_dt_ids': reference_dt_ids
    })

@datatables_bp.route('/api/get_team_members_for_group/<string:group_id>')
@login_required
def get_team_members_for_group(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not check_group_permission(group, 'read'):
        return jsonify({'error': 'Group not found or permission denied'}), 404
    
    members = group.project.team.memberships
    member_list = [{'id': m.user.id, 'text': m.user.email} for m in members]
    return jsonify(member_list)

@datatables_bp.route('/api/get_reference_range_data/<int:datatable_id>', methods=['GET'])
@login_required
def get_reference_range_data(datatable_id):
    data_table = db.session.get(DataTable, datatable_id)
    if not data_table:
        return jsonify({'error': 'DataTable not found'}), 404

    if not check_datatable_permission(data_table, 'read'):
        return jsonify({'error': 'Permission denied'}), 403

    # Placeholder for future persistence
    return jsonify({})

@datatables_bp.route('/api/check_competency/<int:user_id>/<int:protocol_id>', methods=['GET'])
@login_required
def check_competency(user_id, protocol_id):
    from app.models import User, ProtocolModel
    from app.services.tm_connector import TrainingManagerConnector

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'valid': False, 'details': ['User not found']}), 404

    protocol = db.session.get(ProtocolModel, protocol_id)
    if not protocol:
        return jsonify({'valid': False, 'details': ['Protocol not found']}), 404

    if not protocol.external_skill_ids:
        return jsonify({'valid': True, 'details': []})  # No skills required

    connector = TrainingManagerConnector()
    result = connector.check_competency([user.email], protocol.external_skill_ids)
    if not result:
        return jsonify({'valid': False, 'details': ['Unable to check competency']}), 503

    competency_data = result.get(user.email, {'valid': False, 'details': ['No data']})
    return jsonify(competency_data)
    
@datatables_bp.route('/download_reference_comparison/<int:datatable_id>')
@login_required
def download_reference_comparison(datatable_id):
    ref_dt_ids_str = request.args.get('ref_dt_ids', '')
    if not ref_dt_ids_str:
        flash(_("No reference datatables specified for download."), "warning")
        return redirect(url_for('datatables.view_data_table', datatable_id=datatable_id))

    try:
        ref_dt_ids = [int(id_str) for id_str in ref_dt_ids_str.split(',')]
    except ValueError:
        flash(_("Invalid reference datatable IDs."), "danger")
        return redirect(url_for('datatables.view_data_table', datatable_id=datatable_id))

    all_ids_to_aggregate = [str(datatable_id)] + [str(ref_id) for ref_id in ref_dt_ids]

    # Use the service method for aggregation
    df_combined, errors, unused_source_info = datatable_service.aggregate_selected_datatables(all_ids_to_aggregate)

    if errors:
        for err in errors:
            flash(err, "danger")
    
    if df_combined is None or df_combined.empty:
        flash(_("No data available to download for the comparison."), "warning")
        return redirect(url_for('datatables.view_data_table', datatable_id=datatable_id))

    df_combined['Source'] = df_combined['_source_datatable_id'].apply(lambda x: 'Current' if x == datatable_id else 'Reference')

    # Use utility for download
    output = dataframe_to_excel_bytes(df_combined)
    fname = f'datatable_{datatable_id}_with_reference_data.xlsx'
    mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return send_file(output, mimetype=mime, as_attachment=True, download_name=fname)

@datatables_bp.route('/download/<int:id>')
@login_required
def download_data_table(id):
    data_table_dl = db.session.get(DataTable, id)
    if not data_table_dl or not data_table_dl.group:
        flash(lazy_gettext("Table/Group not found."), "error")
        return redirect(request.referrer or url_for('main.index'))
    
    if not check_datatable_permission(data_table_dl, 'read'):
        flash(lazy_gettext("Permission denied to download this DataTable."), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))
    
    blinding_mode = request.args.get('blinding', 'default') 
    can_view_unblinded = user_has_permission(current_user, 'Project', 'view_unblinded_data', team_id=data_table_dl.group.project.team_id)
    
    group_animal_data_dl = data_table_dl.group.animal_data or []
    
    ordered_model_and_age_cols_dl = get_ordered_column_names(data_table_dl)

    rows_query_dl = data_table_dl.experiment_rows.order_by(ExperimentDataRow.row_index)
    existing_data_rows_dict_dl = {r.row_index: r.row_data for r in rows_query_dl.all()}
    data_for_df_dl = []
    all_actual_data_keys_dl = set(ordered_model_and_age_cols_dl)
    
    for i_dl in range(len(group_animal_data_dl)):
        merged_row_data_dl = group_animal_data_dl[i_dl].copy() if i_dl < len(group_animal_data_dl) else {}
        merged_row_data_dl.update(existing_data_rows_dict_dl.get(i_dl, {}))
        
        age_in_days_dl = None
        date_of_birth_str_dl = merged_row_data_dl.get('Date of Birth')
        if date_of_birth_str_dl and data_table_dl.date:
            try:
                dob_dl = datetime.strptime(date_of_birth_str_dl, '%Y-%m-%d').date()
                dt_date_obj_dl = datetime.strptime(data_table_dl.date, '%Y-%m-%d').date()
                delta_dl = dt_date_obj_dl - dob_dl
                age_in_days_dl = delta_dl.days
            except (ValueError, TypeError) as e_age_dl: 
                current_app.logger.warning(f"Could not calculate age for animal index {i_dl} in datatable {id} for download: {e_age_dl}")
                age_in_days_dl = None
        
        merged_row_data_dl['Age (Days)'] = age_in_days_dl
        all_actual_data_keys_dl.update(merged_row_data_dl.keys())
        data_for_df_dl.append(merged_row_data_dl)
        
    if not data_for_df_dl: 
        flash(lazy_gettext("No data found in this DataTable to download."), "warning")
        return redirect(request.referrer or url_for('datatables.edit_data_table', id=id))
        
    final_columns_for_df_dl = ordered_model_and_age_cols_dl[:]
    for col in all_actual_data_keys_dl:
        if col not in final_columns_for_df_dl:
            final_columns_for_df_dl.append(col)       
            
    df_dl = pd.DataFrame(data_for_df_dl, columns=final_columns_for_df_dl)

    from ..permissions import can_view_unblinded_data
    is_unblinded = data_table_dl.group.randomization_details.get('unblinded_at') if data_table_dl.group.randomization_details else False
    can_view_unblinded_dl = (can_view_unblinded_data(data_table_dl.group) or is_unblinded)
    
    has_randomization = bool(data_table_dl.group.randomization_details)
    is_blinded = data_table_dl.group.randomization_details.get('use_blinding', False) if has_randomization else False

    if has_randomization:
        if is_blinded:
            if can_view_unblinded_dl and blinding_mode == 'unblinded':
                # Map blinded names to actual names if requested and permitted
                blinding_key = data_table_dl.group.randomization_details.get('blinding_key', {})
                df_dl['Treatment Group'] = df_dl['Blinded Group'].map(blinding_key)
            else:
                # Keep blinded group, but hide treatment group
                if 'Treatment Group' in df_dl.columns:
                    df_dl = df_dl.drop(columns=['Treatment Group'])
        else:
            # Not blinded, keep treatment group, but blinded group column is likely irrelevant/empty
            if 'Blinded Group' in df_dl.columns:
                df_dl = df_dl.drop(columns=['Blinded Group'])
    else:
        # No randomization, hide both
        cols_to_drop = [c for c in ['Blinded Group', 'Treatment Group'] if c in df_dl.columns]
        if cols_to_drop:
            df_dl = df_dl.drop(columns=cols_to_drop)

    if data_table_dl.housing_condition:
        housing_conditions_data = {}
        for item_assoc in data_table_dl.housing_condition.item_associations:
            column_name = item_assoc.item.name
            housing_conditions_data[column_name] = item_assoc.default_value

        for col_name, value in housing_conditions_data.items():
            df_dl[col_name] = value

    # Use utility for download
    output_dl = dataframe_to_excel_bytes(df_dl)
    fname_dl = f'{data_table_dl.group.name}_{data_table_dl.protocol.name}_{data_table_dl.date}'.replace(' ', '_').replace('/','-').replace(':','-') + '.xlsx'
    mime_dl = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return send_file(output_dl, mimetype=mime_dl, as_attachment=True, download_name=fname_dl)


@datatables_bp.route('/download_transposed/<int:id>')
@login_required
def download_transposed_data_table(id):
    data_table_trans = db.session.get(DataTable, id)
    if not data_table_trans or not data_table_trans.group:
        flash(lazy_gettext("Table/Group not found."), "error")
        return redirect(request.referrer or url_for('main.index'))
    
    if not check_datatable_permission(data_table_trans, 'read'):
        flash(lazy_gettext("Permission denied to download this DataTable."), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))
        
    group_animal_data_trans = data_table_trans.group.animal_data or []
    
    ordered_model_and_age_cols_trans = get_ordered_column_names(data_table_trans)

    rows_query_trans = data_table_trans.experiment_rows.order_by(ExperimentDataRow.row_index)
    existing_data_rows_dict_trans = {r.row_index: r.row_data for r in rows_query_trans.all()}
    data_for_df_trans = []
    all_actual_data_keys_trans = set(ordered_model_and_age_cols_trans)
    
    for i_trans in range(len(group_animal_data_trans)):
        merged_row_data_trans = group_animal_data_trans[i_trans].copy() if i_trans < len(group_animal_data_trans) else {}
        merged_row_data_trans.update(existing_data_rows_dict_trans.get(i_trans, {}))
        
        age_in_days_trans = None
        date_of_birth_str_trans = merged_row_data_trans.get('Date of Birth')
        if date_of_birth_str_trans and data_table_trans.date:
            try:
                dob_trans = datetime.strptime(date_of_birth_str_trans, '%Y-%m-%d').date()
                dt_date_obj_trans = datetime.strptime(data_table_trans.date, '%Y-%m-%d').date()
                delta_trans = dt_date_obj_trans - dob_trans
                age_in_days_trans = delta_trans.days
            except (ValueError, TypeError): 
                age_in_days_trans = None
        
        merged_row_data_trans['Age (Days)'] = age_in_days_trans
        all_actual_data_keys_trans.update(merged_row_data_trans.keys())
        data_for_df_trans.append(merged_row_data_trans)
        
    if not data_for_df_trans: 
        flash(lazy_gettext("No data found in this DataTable to download."), "warning")
        return redirect(request.referrer or url_for('datatables.edit_data_table', id=id))
        
    final_columns_for_df_trans = ordered_model_and_age_cols_trans[:]
    for col in all_actual_data_keys_trans:
        if col not in final_columns_for_df_trans:
            final_columns_for_df_trans.append(col)        
            
    df_trans = pd.DataFrame(data_for_df_trans, columns=final_columns_for_df_trans)
    
    # Blinding logic for transposed download
    from ..permissions import can_view_unblinded_data
    is_unblinded = data_table_trans.group.randomization_details.get('unblinded_at') if data_table_trans.group.randomization_details else False
    can_view_unblinded_trans = (can_view_unblinded_data(data_table_trans.group) or is_unblinded)
    
    has_randomization = bool(data_table_trans.group.randomization_details)
    is_blinded = data_table_trans.group.randomization_details.get('use_blinding', False) if has_randomization else False

    if has_randomization:
        if is_blinded:
            if not can_view_unblinded_trans:
                if 'Treatment Group' in df_trans.columns:
                    df_trans = df_trans.drop(columns=['Treatment Group'])
            # We don't support 'unblinded' mode parameter for transposed yet, 
            # so we just show what's permitted.
        else:
            if 'Blinded Group' in df_trans.columns:
                df_trans = df_trans.drop(columns=['Blinded Group'])
    else:
        cols_to_drop = [c for c in ['Blinded Group', 'Treatment Group'] if c in df_trans.columns]
        if cols_to_drop:
            df_trans = df_trans.drop(columns=cols_to_drop)

    df_prepared_for_transpose_trans = df_trans.copy()
    subject_id_col_trans = 'ID'
    use_subject_id_as_header_trans = False
    
    if subject_id_col_trans in df_prepared_for_transpose_trans.columns:
        id_series_trans = df_prepared_for_transpose_trans[subject_id_col_trans]
        if id_series_trans.notna().all() and id_series_trans.nunique() == len(df_prepared_for_transpose_trans):
            try: 
                df_prepared_for_transpose_trans = df_prepared_for_transpose_trans.set_index(subject_id_col_trans)
                use_subject_id_as_header_trans = True
                current_app.logger.info(f"Using '{subject_id_col_trans}' as index for transposition for DataTable {id}.")
            except Exception as e_set_index_trans: 
                current_app.logger.warning(f"Error setting '{subject_id_col_trans}' as index: {e_set_index_trans}. DataTable {id}. Using generic headers.")
                flash(lazy_gettext("Warning: Could not use '{col}' as subject headers due to an issue ({error_msg}). Transposed table will use generic 'Subject_X' headers.").format(col=subject_id_col_trans, error_msg=str(e_set_index_trans)), "warning")
        else:
            msg_trans = lazy_gettext("Subject ID column '{col}' contains missing values.") if not id_series_trans.notna().all() else lazy_gettext("Subject ID column '{col}' values are not unique.")
            flash(lazy_gettext("Transposed table will use generic 'Subject_X' headers."), "warning")
            current_app.logger.warning(f"{msg_trans.format(col=subject_id_col_trans)} Using generic 'Subject_X' headers for DataTable {id}.")
    else:
        msg_no_id_trans = lazy_gettext("Subject ID column '{col}' not found.")
        flash(lazy_gettext("Transposed table will use generic 'Subject_X' headers."), "warning")
        current_app.logger.warning(f"{msg_no_id_trans.format(col=subject_id_col_trans)} Using generic 'Subject_X' headers for DataTable {id}.")
        
    df_transposed_final = df_prepared_for_transpose_trans.transpose()
    if not use_subject_id_as_header_trans: 
        df_transposed_final.columns = [f"Subject_{i_trans_col+1}" for i_trans_col in range(len(df_transposed_final.columns))]
    
    # Use utility with index=True
    base_fname_trans = f'{data_table_trans.group.name}_{data_table_trans.protocol.name}_{data_table_trans.date}'.replace(' ', '_').replace('/','-').replace(':','-')
    fname_trans = f'{base_fname_trans}_transposed_prism.xlsx'
    mime_trans = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    try:
        output_trans = dataframe_to_excel_bytes(df_transposed_final, index=True, header=True)
        return send_file(output_trans, mimetype=mime_trans, as_attachment=True, download_name=fname_trans)
    except Exception as e_trans_excel:
        current_app.logger.error(f"Transposed Excel download error for DataTable {id}: {e_trans_excel}", exc_info=True)
        flash(lazy_gettext("Error generating transposed file for download: {error_msg}").format(error_msg=str(e_trans_excel)), 'error')
        return redirect(request.referrer or url_for('datatables.edit_data_table', id=id))

@datatables_bp.route('/view/<int:datatable_id>', methods=['GET', 'POST'])
@login_required
def view_data_table(datatable_id):
    data_table_view = db.session.get(DataTable, datatable_id)
    if not data_table_view or not data_table_view.group:
        flash(lazy_gettext("DataTable or associated Group not found."), "error"); return redirect(url_for('main.index'))
    if not check_datatable_permission(data_table_view, 'read'):
        flash(lazy_gettext("Permission denied to view this DataTable."), "danger"); return redirect(url_for('groups.manage_groups'))

    from ..permissions import can_view_unblinded_data
    is_unblinded = data_table_view.group.randomization_details.get('unblinded_at') if data_table_view.group.randomization_details else False
    can_view_unblinded = (can_view_unblinded_data(data_table_view.group) or is_unblinded)
    randomization_details = data_table_view.group.randomization_details or {}

    assignee_and_housing_form = DataTableForm(obj=data_table_view)
    if data_table_view.group and data_table_view.group.project:
        project = data_table_view.group.project
        assignable_users = {}
        if project.team:
            for membership in project.team.memberships:
                if membership.user:
                    assignable_users[membership.user.id] = membership.user
        shared_permissions = ProjectTeamShare.query.filter(
            ProjectTeamShare.project_id == project.id,
            or_(
                ProjectTeamShare.can_create_exp_groups == True,
                ProjectTeamShare.can_edit_exp_groups == True,
                ProjectTeamShare.can_delete_exp_groups == True,
                ProjectTeamShare.can_create_datatables == True,
                ProjectTeamShare.can_edit_datatables == True,
                ProjectTeamShare.can_delete_datatables == True
            )
        ).options(joinedload(ProjectTeamShare.team).joinedload(Team.memberships).joinedload(TeamMembership.user)).all()

        for perm in shared_permissions:
            if perm.team:
                for membership in perm.team.memberships:
                    if membership.user:
                        assignable_users[membership.user.id] = membership.user
        
        sorted_users = sorted(assignable_users.values(), key=lambda u: u.email)
        assignee_and_housing_form.assigned_to_id.choices = [('', lazy_gettext('Unassigned'))] + [(u.id, u.email) for u in sorted_users]

    if request.method == 'POST':
        if not check_datatable_permission(data_table_view, 'edit_datatable'):
            flash(lazy_gettext("Permission denied to edit this DataTable."), "danger")
            return redirect(url_for('datatables.view_data_table', datatable_id=datatable_id))
        
        if 'update_metadata' in request.form:
            try:
                if 'assigned_to_id' in request.form:
                    new_assignee_id = request.form.get('assigned_to_id')
                    data_table_view.assigned_to_id = int(new_assignee_id) if new_assignee_id else None
                
                if 'date' in request.form:
                    new_date_str = request.form.get('date')
                    if new_date_str:
                        try:
                            # Apply similar logic to move_datatable to keep calendar in sync
                            new_date_obj = datetime.strptime(new_date_str, '%Y-%m-%d').date()
                            new_date = new_date_obj.strftime('%Y-%m-%d')
                            data_table_view.date = new_date
                            
                            if data_table_view.generated_from_event and data_table_view.generated_from_event.workplan and data_table_view.generated_from_event.workplan.study_start_date:
                                wp_start_date = data_table_view.generated_from_event.workplan.study_start_date
                                if isinstance(wp_start_date, datetime):
                                    wp_start_date = wp_start_date.date()
                                
                                delta = new_date_obj - wp_start_date
                                data_table_view.generated_from_event.offset_days = delta.days
                        except ValueError:
                            flash(lazy_gettext('Invalid date format.'), 'danger')
                            return redirect(url_for('datatables.view_data_table', datatable_id=datatable_id))

                db.session.commit()
                flash(lazy_gettext('Metadata updated successfully.'), 'success')
            except Exception as e:
                db.session.rollback()
                flash(lazy_gettext('Error updating metadata: %(error)s', error=str(e)), 'danger')
            return redirect(url_for('datatables.view_data_table', datatable_id=datatable_id))

    metadata_fields = set()
    EXCLUDED_METADATA_FIELDS = {'ID', 'Date of Birth', 'Age (Days)'}

    if data_table_view.group and data_table_view.group.model and data_table_view.group.model.analytes:
        for analyte in data_table_view.group.model.analytes:
            if analyte.is_metadata and analyte.name not in EXCLUDED_METADATA_FIELDS:
                metadata_fields.add(analyte.name)
    if data_table_view.protocol and data_table_view.protocol.analyte_associations:
        for assoc in data_table_view.protocol.analyte_associations:
            if assoc.is_metadata and assoc.analyte.name not in EXCLUDED_METADATA_FIELDS:
                metadata_fields.add(assoc.analyte.name)
    
    if data_table_view.housing_condition:
        for item_assoc in data_table_view.housing_condition.item_associations:
            if item_assoc.item.name not in EXCLUDED_METADATA_FIELDS:
                metadata_fields.add(item_assoc.item.name)

    
    experimental_group_view = data_table_view.group
    animal_model_view = experimental_group_view.model
    animal_data_list_view = experimental_group_view.animal_data or []
    experiment_rows_query_view = data_table_view.experiment_rows.order_by(ExperimentDataRow.row_index)
    experiment_rows_dict_view = {row.row_index: row.row_data for row in experiment_rows_query_view.all()}
    if not animal_data_list_view: flash(lazy_gettext("No animal data found for the group associated with this DataTable."), "warning")
    processed_data_for_df_view = []
    for i_view, animal_info_view in enumerate(animal_data_list_view):
        exp_row_data_view = experiment_rows_dict_view.get(i_view, {})
        merged_data_view = {**animal_info_view, **exp_row_data_view}
        processed_data_for_df_view.append(merged_data_view)

    df_processed_orig_view = pd.DataFrame(processed_data_for_df_view)

    if data_table_view.housing_condition:
        housing_conditions_data = {}
        for item_assoc in data_table_view.housing_condition.item_associations:
            column_name = item_assoc.item.name
            housing_conditions_data[column_name] = item_assoc.default_value

        for col_name, value in housing_conditions_data.items():
            if col_name not in df_processed_orig_view.columns:
                 df_processed_orig_view[col_name] = value

    if 'Date of Birth' in df_processed_orig_view.columns and data_table_view.date:
        try:
            birth_dates = pd.to_datetime(df_processed_orig_view['Date of Birth'], errors='coerce')
            datatable_date = pd.to_datetime(data_table_view.date)
            age_deltas = datatable_date - birth_dates
            df_processed_orig_view['Age (Days)'] = age_deltas.dt.days
        except Exception as e_age_view:
            current_app.logger.warning(f"Could not calculate age for datatable {datatable_id} in view mode: {e_age_view}")
            df_processed_orig_view['Age (Days)'] = None
    elif 'Age (Days)' not in df_processed_orig_view.columns:
        df_processed_orig_view['Age (Days)'] = None
    
    animal_model_analytes_view = []
    if animal_model_view and animal_model_view.analytes:
        animal_model_analytes_view = sort_analytes_list_by_name(animal_model_view.analytes)

    animal_model_grouping_params_view = [a.name for a in animal_model_analytes_view]
    
    if not animal_model_grouping_params_view and not df_processed_orig_view.empty and animal_model_view:
        flash(lazy_gettext("No animal model parameters defined for grouping."), "warning")
    
    protocol_analytes_view = []
    numerical_protocol_cols_view = []
    
    if data_table_view.protocol and data_table_view.protocol.analytes:
        protocol_analytes_view = sort_analytes_list_by_name(data_table_view.protocol.analytes)
        for analyte in protocol_analytes_view:
            if analyte.name in df_processed_orig_view.columns:

                if analyte.data_type.value in ['integer', 'float']:
                    df_processed_orig_view[analyte.name] = pd.to_numeric(df_processed_orig_view[analyte.name], errors='coerce')
                    if not df_processed_orig_view[analyte.name].isnull().all():
                        numerical_protocol_cols_view.append(analyte.name)

    base_headers = get_ordered_column_names(data_table_view)
    final_headers = []

    for header in base_headers:
        if header in df_processed_orig_view.columns:
            final_headers.append(header)

    for col in df_processed_orig_view.columns:
        if col not in final_headers:
            final_headers.append(col)
    # Filter and preserve order of headers, respecting randomization blinding
    has_randomization = bool(data_table_view.group.randomization_details)
    is_blinded = data_table_view.group.randomization_details.get('use_blinding', False) if has_randomization else False

    all_table_headers_view = []
    for h in final_headers:
        if h == 'Blinded Group':
            if has_randomization and is_blinded:
                all_table_headers_view.append(h)
        elif h == 'Treatment Group':
            if has_randomization:
                if not is_blinded or can_view_unblinded:
                    all_table_headers_view.append(h)
        else:
            all_table_headers_view.append(h)
    selected_grouping_params_view = []
    exclude_outliers_view = request.form.get('exclude_outliers') == 'on' if request.method == 'POST' else request.args.get('exclude_outliers') == 'true'
    

    available_reference_ranges = []
    if data_table_view.protocol_id:
        available_reference_ranges = ReferenceRange.query.filter_by(
            protocol_id=data_table_view.protocol_id
        ).order_by(ReferenceRange.name).all()

    if request.method == 'POST': selected_grouping_params_view = request.form.getlist('grouping_params')
    elif request.method == 'GET': selected_grouping_params_view = request.args.getlist('grouping_params')
    valid_grouping_params_view = [p for p in selected_grouping_params_view if p in df_processed_orig_view.columns]
    subgroup_summaries_view = {}
    all_display_rows_with_outlier_info_view = []
    if not valid_grouping_params_view:
        if selected_grouping_params_view: flash(lazy_gettext("Selected grouping parameters are not valid for this dataset. Showing overall data."), "warning")
        df_temp_overall_view = df_processed_orig_view.copy()
        df_outlier_flags_overall_view, overall_stats_initial_view = identify_outliers_and_calc_stats(df_temp_overall_view, numerical_protocol_cols_view)
        df_for_display_overall_view = df_temp_overall_view.copy()
        temp_outliers_list_view = []
        for idx_view in df_for_display_overall_view.index:
            row_outliers_view = {}
            for col_view in numerical_protocol_cols_view: row_outliers_view[col_view] = df_outlier_flags_overall_view.at[idx_view, col_view] if col_view in df_outlier_flags_overall_view.columns else False
            temp_outliers_list_view.append(row_outliers_view)
        df_for_display_overall_view['_outliers'] = temp_outliers_list_view
        df_for_stats_overall_view = df_temp_overall_view.copy()
        if exclude_outliers_view:
            for col_view_stats in numerical_protocol_cols_view:
                if col_view_stats in df_outlier_flags_overall_view.columns: df_for_stats_overall_view.loc[df_outlier_flags_overall_view[col_view_stats], col_view_stats] = pd.NA
            _, overall_stats_final_view = identify_outliers_and_calc_stats(df_for_stats_overall_view, numerical_protocol_cols_view)
        else: overall_stats_final_view = overall_stats_initial_view
        all_display_rows_with_outlier_info_view = df_for_display_overall_view.to_dict(orient='records')
        subgroup_summaries_view["Overall"] = {'label': lazy_gettext("Overall (all animals)"), 'stats': overall_stats_final_view, 'age_range': get_age_range_from_df_view_helper(df_for_stats_overall_view), 'animal_count': len(df_for_stats_overall_view.dropna(subset=numerical_protocol_cols_view, how='all')), 'initial_animal_count': len(df_temp_overall_view)}
    else:
        all_display_rows_list_of_dfs_view = []
        try:
            for group_key_view, group_df_orig_loop_view in df_processed_orig_view.groupby(valid_grouping_params_view, dropna=False):
                df_temp_group_view = group_df_orig_loop_view.copy()
                group_identifier_tuple_view = tuple(group_key_view) if isinstance(group_key_view, (list, tuple)) else (str(group_key_view),)
                group_identifier_str_view = " / ".join(map(str, group_identifier_tuple_view))
                current_group_numerical_cols_view = [col for col in numerical_protocol_cols_view if col in df_temp_group_view.columns and not df_temp_group_view[col].isnull().all()]
                df_outlier_flags_group_view, group_stats_initial_view = identify_outliers_and_calc_stats(df_temp_group_view, current_group_numerical_cols_view)
                df_for_display_group_view = df_temp_group_view.copy()
                temp_outliers_list_group_view = []
                for idx_g_view in df_for_display_group_view.index:
                    row_outliers_g_view = {}
                    for col_g_view in current_group_numerical_cols_view: row_outliers_g_view[col_g_view] = df_outlier_flags_group_view.at[idx_g_view, col_g_view] if col_g_view in df_outlier_flags_group_view.columns else False
                    temp_outliers_list_group_view.append(row_outliers_g_view)
                df_for_display_group_view['_outliers'] = temp_outliers_list_group_view
                all_display_rows_list_of_dfs_view.append(df_for_display_group_view)
                df_for_stats_group_view = df_temp_group_view.copy()
                if exclude_outliers_view:
                    for col_view_stats_group in current_group_numerical_cols_view:
                         if col_view_stats_group in df_outlier_flags_group_view.columns: df_for_stats_group_view.loc[df_outlier_flags_group_view[col_view_stats_group], col_view_stats_group] = pd.NA
                    _, group_stats_final_view = identify_outliers_and_calc_stats(df_for_stats_group_view, current_group_numerical_cols_view)
                else: group_stats_final_view = group_stats_initial_view
                subgroup_summaries_view[group_identifier_tuple_view] = {'label': group_identifier_str_view, 'stats': group_stats_final_view, 'age_range': get_age_range_from_df_view_helper(df_for_stats_group_view), 'animal_count': len(df_for_stats_group_view.dropna(subset=current_group_numerical_cols_view, how='all')), 'initial_animal_count': len(df_temp_group_view)}
            if all_display_rows_list_of_dfs_view:
                df_combined_for_display_view = pd.concat(all_display_rows_list_of_dfs_view)
                sort_keys_view = valid_grouping_params_view[:]
                if 'ID' in df_combined_for_display_view.columns: sort_keys_view.append('ID')
                sort_keys_present_view = [key for key in sort_keys_view if key in df_combined_for_display_view.columns]
                if sort_keys_present_view: df_combined_for_display_view = df_combined_for_display_view.sort_values(by=sort_keys_present_view)
                all_display_rows_with_outlier_info_view = df_combined_for_display_view.to_dict(orient='records')
        except Exception as e_grouping_view:
            flash(lazy_gettext("Error grouping data: {}").format(str(e_grouping_view)), "danger") 
            current_app.logger.error(f"Error grouping data for DataTable {datatable_id}: {e_grouping_view}", exc_info=True)
            df_temp_overall_fallback = df_processed_orig_view.copy()
            df_outlier_flags_overall_fallback, overall_stats_initial_fallback = identify_outliers_and_calc_stats(df_temp_overall_fallback, numerical_protocol_cols_view)
            df_for_display_overall_fallback = df_temp_overall_fallback.copy()
            temp_outliers_list_fallback_err = []
            for idx_f_err in df_for_display_overall_fallback.index:
                row_outliers_f_err = {}
                for col_f_err in numerical_protocol_cols_view: row_outliers_f_err[col_f_err] = df_outlier_flags_overall_fallback.at[idx_f_err, col_f_err] if col_f_err in df_outlier_flags_overall_fallback.columns else False
                temp_outliers_list_fallback_err.append(row_outliers_f_err)
            df_for_display_overall_fallback['_outliers'] = temp_outliers_list_fallback_err
            df_for_stats_overall_fallback = df_temp_overall_fallback.copy()
            if exclude_outliers_view:
                for col_fallback in numerical_protocol_cols_view:
                    if col_fallback in df_outlier_flags_overall_fallback.columns: df_for_stats_overall_fallback.loc[df_outlier_flags_overall_fallback[col_fallback], col_fallback] = pd.NA
                _, overall_stats_final_fallback = identify_outliers_and_calc_stats(df_for_stats_overall_fallback, numerical_protocol_cols_view)
            else: overall_stats_final_fallback = overall_stats_initial_fallback
            all_display_rows_with_outlier_info_view = df_for_display_overall_fallback.to_dict(orient='records')
            subgroup_summaries_view["Overall"] = {'label': lazy_gettext("Overall (all animals)"), 'stats': overall_stats_final_fallback, 'age_range': get_age_range_from_df_view_helper(df_for_stats_overall_fallback), 'animal_count': len(df_for_stats_overall_fallback.dropna(subset=numerical_protocol_cols_view, how='all')), 'initial_animal_count': len(df_temp_overall_fallback)}

    return render_template('datatables/view_data_table.html',
                           data_table=data_table_view, experimental_group=experimental_group_view,
                           all_table_headers=all_table_headers_view, all_display_rows=all_display_rows_with_outlier_info_view, 
                           subgroup_summaries=subgroup_summaries_view, animal_model_grouping_params=animal_model_grouping_params_view, 
                           selected_grouping_params=valid_grouping_params_view, protocol_field_names=[a.name for a in protocol_analytes_view], 
                           numerical_protocol_cols=numerical_protocol_cols_view, exclude_outliers_checked=exclude_outliers_view,
                           available_reference_ranges=available_reference_ranges,
                           numerical_protocol_cols_json=json.dumps(numerical_protocol_cols_view),
                           metadata_fields=list(metadata_fields),
                           assignee_and_housing_form=assignee_and_housing_form,
                           can_view_unblinded=can_view_unblinded,
                           randomization_details=randomization_details)
