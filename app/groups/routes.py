# app/groups/routes.py
import io
import json
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import re
from flask import (abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_file, url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from app.permissions import (can_create_group_for_project,
                             can_view_unblinded_data, check_group_permission,
                             check_project_permission)
from app.services.group_service import GroupService
from app.services.project_service import ProjectService
from app.services.datatable_service import DataTableService
from app.exceptions import ValidationError, BusinessError # New exceptions

from app.services.ethical_approval_service import (
    get_animals_available_for_ea, get_eligible_ethical_approvals) # NEW IMPORT

from ..extensions import db
from ..forms import GroupForm
from ..helpers import (generate_unique_name, generate_xlsx_template,
                       get_ordered_analytes_for_model, replace_undefined,
                       sort_analytes_list_by_name,
                       update_associated_data_tables, validate_and_convert)
from ..models import (Analyte, AnalyteDataType, AnimalModel, DataTable,
                      DataTableMoleculeUsage, ControlledMolecule,
                      EthicalApproval, ExperimentalGroup, ExperimentDataRow,
                      Project, Team, TeamMembership, User, Workplan)
# Import blueprint, extensions, models, forms
from . import groups_bp

group_service = GroupService()
project_service = ProjectService()
datatable_service = DataTableService()

@groups_bp.route('/<string:group_id>', methods=['GET'])
@login_required
def get_group(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group: return jsonify({'error': 'Group not found'}), 404
    if not check_group_permission(group, 'read'): return jsonify({'error': 'Permission denied'}), 403
    return jsonify({'id': group.id, 'name': group.name, 'is_archived': group.is_archived})

@groups_bp.route('/search_ajax', methods=['GET'])
@login_required
def search_groups_ajax():
    search_term = request.args.get('q', '').strip()
    project_id = request.args.get('project_id')
    page = request.args.get('page', 1, type=int)
    per_page = 15

    query = ExperimentalGroup.query.join(Project)
    
    # Filter by project if provided
    if project_id and project_id != '0':
        query = query.filter(ExperimentalGroup.project_id == project_id)
        
    # Permission check: Only groups from projects accessible to the user
    accessible_projects = current_user.get_accessible_projects()
    project_ids = [p.id for p in accessible_projects]
    query = query.filter(ExperimentalGroup.project_id.in_(project_ids)).options(joinedload(ExperimentalGroup.animals))
    
    # Only active groups and projects
    query = query.filter(ExperimentalGroup.is_archived == False)
    query = query.filter(Project.is_archived == False)

    if search_term:
        query = query.filter(
            or_(
                ExperimentalGroup.name.ilike(f'%{search_term}%'),
                Project.name.ilike(f'%{search_term}%'),
                Project.slug.ilike(f'%{search_term}%')
            )
        )

    total_count = query.count()
    groups = query.order_by(ExperimentalGroup.name).offset((page - 1) * per_page).limit(per_page).all()

    results = []
    for g in groups:
        results.append({
            'id': g.id,
            'text': f"{g.name} ({g.project.name})"
        })

    return jsonify({
        'results': results,
        'total_count': total_count,
        'pagination': {'more': (page * per_page) < total_count}
    })

@groups_bp.route('/', methods=['GET'])
@login_required
def manage_groups():
    # Fetch hierarchy for sidebar
    sidebar_data = project_service.get_sidebar_hierarchy(current_user)
    
    # Fetch all animal models for filter dropdown
    all_animal_models = AnimalModel.query.order_by(AnimalModel.name).all()
    
    # Fetch user teams for filter dropdown (or all teams for super admin)
    if current_user.is_super_admin:
        user_teams_display = Team.query.order_by(Team.name).all()
    else:
        user_teams_display = current_user.get_teams()
    
    return render_template('groups/manage_groups.html', 
                           sidebar_data=sidebar_data,
                           animal_models=all_animal_models, 
                           user_teams=user_teams_display, # Explicitly passing as user_teams
                           check_group_permission=check_group_permission)

@groups_bp.route('/batch_archive', methods=['POST'])
@login_required
def batch_archive_groups():
    data = request.get_json()
    group_ids_from_payload = data.get('group_ids', [])
    select_all_matching = data.get('select_all_matching', 'false') == 'true'
    filters = data.get('filters', {}) # Filters should be directly part of the data payload if select_all_matching is true

    groups_to_process_ids = []

    if select_all_matching:
        # Construct filters dictionary for the service call
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'project_id': filters.get('project_id'),
            'team_id': filters.get('team_id'),
            'model_id': filters.get('model_id'),
            'is_archived': filters.get('is_archived')
        }
        # Convert is_archived filter to boolean if present
        if service_filters['is_archived'] is not None:
            if service_filters['is_archived'].lower() == 'true':
                service_filters['is_archived'] = True
            elif service_filters['is_archived'].lower() == 'false':
                service_filters['is_archived'] = False
            else:
                service_filters['is_archived'] = None # Invalid value

        # Retrieve all matching groups using the service (ignoring pagination for batch ops)
        # Note: A dedicated service method that returns *all* matching IDs might be more efficient
        # than calling get_server_side_groups with a very large per_page.
        all_matching_groups_result = group_service.get_server_side_groups(
            user=current_user,
            filters=service_filters,
            page=1, # Get all results
            per_page=9999999, # Large number to get all results
            sort_column='created_at', # Dummy sort
            sort_direction='asc' # Dummy sort
        )
        groups_to_process_ids = [g.id for g in all_matching_groups_result['items']]
    else:
        groups_to_process_ids = group_ids_from_payload

    if not groups_to_process_ids:
        return jsonify({'success': False, 'message': _l('No groups selected or found for archiving.')}), 400
    
    archived_count = 0
    errors = []
    for group_id in groups_to_process_ids:
        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            errors.append(_l(f"Group {group_id} not found."))
            continue
        if not check_group_permission(group, 'archive_exp_group'):
            errors.append(_l(f"Permission denied for group {group.name}."))
            continue
        
        try:
            if not group.is_archived:
                group.is_archived = True
                group.archived_at = datetime.now(current_app.config['UTC_TZ'])
                db.session.commit()
                archived_count += 1
        except Exception as e:
            db.session.rollback()
            errors.append(_l(f"Error archiving group {group.name}: {e}"))
            
    if errors:
        return jsonify({'success': False, 'message': _l('Some groups could not be archived.'), 'errors': errors}), 400
    return jsonify({'success': True, 'message': _l(f'Successfully archived {archived_count} groups.')}), 200

@groups_bp.route('/batch_unarchive', methods=['POST'])
@login_required
def batch_unarchive_groups():
    data = request.get_json()
    group_ids_from_payload = data.get('group_ids', [])
    select_all_matching = data.get('select_all_matching', 'false') == 'true'
    filters = data.get('filters', {})

    groups_to_process_ids = []

    if select_all_matching:
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'project_id': filters.get('project_id'),
            'team_id': filters.get('team_id'),
            'model_id': filters.get('model_id'),
            'is_archived': filters.get('is_archived')
        }
        if service_filters['is_archived'] is not None:
            if service_filters['is_archived'].lower() == 'true':
                service_filters['is_archived'] = True
            elif service_filters['is_archived'].lower() == 'false':
                service_filters['is_archived'] = False
            else:
                service_filters['is_archived'] = None
        
        all_matching_groups_result = group_service.get_server_side_groups(
            user=current_user,
            filters=service_filters,
            page=1,
            per_page=9999999,
            sort_column='created_at',
            sort_direction='asc'
        )
        groups_to_process_ids = [g.id for g in all_matching_groups_result['items']]
    else:
        groups_to_process_ids = group_ids_from_payload

    if not groups_to_process_ids:
        return jsonify({'success': False, 'message': _l('No groups selected or found for unarchiving.')}), 400
    
    unarchived_count = 0
    errors = []
    for group_id in groups_to_process_ids:
        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            errors.append(_l(f"Group {group_id} not found."))
            continue
        if not check_group_permission(group, 'archive_exp_group'):
            errors.append(_l(f"Permission denied for group {group.name}."))
            continue
        
        try:
            if group.is_archived:
                group.is_archived = False
                group.archived_at = None
                db.session.commit()
                unarchived_count += 1
        except Exception as e:
            db.session.rollback()
            errors.append(_l(f"Error unarchiving group {group.name}: {e}"))
            
    if errors:
        return jsonify({'success': False, 'message': _l('Some groups could not be unarchived.'), 'errors': errors}), 400
    return jsonify({'success': True, 'message': _l(f'Successfully unarchived {unarchived_count} groups.')}), 200

@groups_bp.route('/batch_delete', methods=['POST'])
@login_required
def batch_delete_groups():
    data = request.get_json()
    group_ids_from_payload = data.get('group_ids', [])
    select_all_matching = data.get('select_all_matching', 'false') == 'true'
    filters = data.get('filters', {})

    groups_to_process_ids = []

    if select_all_matching:
        service_filters = {
            'search_value': filters.get('search_value', ''),
            'project_id': filters.get('project_id'),
            'team_id': filters.get('team_id'),
            'model_id': filters.get('model_id'),
            'is_archived': filters.get('is_archived')
        }
        if service_filters['is_archived'] is not None:
            if service_filters['is_archived'].lower() == 'true':
                service_filters['is_archived'] = True
            elif service_filters['is_archived'].lower() == 'false':
                service_filters['is_archived'] = False
            else:
                service_filters['is_archived'] = None
        
        all_matching_groups_result = group_service.get_server_side_groups(
            user=current_user,
            filters=service_filters,
            page=1,
            per_page=9999999,
            sort_column='created_at',
            sort_direction='asc'
        )
        groups_to_process_ids = [g.id for g in all_matching_groups_result['items']]
    else:
        groups_to_process_ids = group_ids_from_payload

    if not groups_to_process_ids:
        return jsonify({'success': False, 'message': _l('No groups selected or found for deletion.')}), 400

    deleted_count = 0
    errors = []
    for group_id in groups_to_process_ids:
        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            errors.append(_l(f"Group {group_id} not found."))
            continue
        if not check_group_permission(group, 'delete_exp_group'):
            errors.append(_l(f"Permission denied for group {group.name}."))
            continue

        if group.data_tables.first():
            errors.append(_l(f"Group {group.name} cannot be deleted because it has associated data tables."))
            continue

        try:
            group_service.delete_group(group)
            deleted_count += 1
        except Exception as e:
            db.session.rollback()
            errors.append(_l(f"Error deleting group {group.name}: {e}"))
            
    if errors:
        return jsonify({'success': False, 'message': _l('Some groups could not be deleted.'), 'errors': errors}), 400
    return jsonify({'success': True, 'message': _l(f'Successfully deleted {deleted_count} groups.')}), 200


@groups_bp.route('/edit', methods=['GET', 'POST'])
@groups_bp.route('/edit/<string:id>', methods=['GET', 'POST'])
@groups_bp.route('/view/<string:id>', methods=['GET'], endpoint='view_group') # View should only be GET
@login_required
def edit_group(id=None):
    if id:
        group = ExperimentalGroup.query.options(joinedload(ExperimentalGroup.animals)).filter_by(id=id).first_or_404()
    else:
        group = None
    
    can_edit = False

    # --- PERMISSION CHECK ---
    if group:
        # 1. Check READ permission first. If they can't read, abort.
        if not check_group_permission(group, 'read', allow_abort=True):
            abort(403) # This will correctly trigger for users without view rights
        
        # 2. Check EDIT permission to determine UI state. Do NOT abort if false.
        can_edit = check_group_permission(group, 'edit_exp_group', allow_abort=False)
    else:
        # Creating new group
        can_edit = True 

    is_read_only = not can_edit

    # --- FORM SETUP ---
    # Handle project prefill from query parameters (common when clicking "Create Group" from a project page)
    prefill_project_id = request.args.get('project_id') or request.args.get('project_id_prefill')
    prefilled_project = None
    if prefill_project_id and not group:
        prefilled_project = db.session.get(Project, prefill_project_id)

    team_id_for_eas = group.project.team_id if group and group.project else (prefilled_project.team_id if prefilled_project else None)
    
    if not team_id_for_eas and request.method == 'POST':
        # Try to get team ID from selected project to populate EAs
        pid = request.form.get('project')
        if pid:
            p = db.session.get(Project, pid)
            if p: team_id_for_eas = p.team_id
        
    form = GroupForm(obj=group, team_id_for_eas=team_id_for_eas, formdata=request.form if request.method == 'POST' else None)
    
    # Apply prefill to form if applicable
    if prefilled_project and request.method == 'GET':
        form.project.data = prefilled_project.id
        # Ensure the project is in the choices (since it's a lazy-loaded select2)
        form.project.choices = [('', _l('Select Project...')), (prefilled_project.id, prefilled_project.name)]

    if request.method == 'POST':
        if not form.validate():
             flash(_l("Form validation failed. Please check the fields."), "danger")
        else:
            if is_read_only: 
                abort(403) # Double check for safety on POST
                
            is_ajax = request.form.get('is_ajax') == 'true'
            update_dts_flag = request.form.get('update_data_tables', 'yes') == 'yes'
            
            try:
                # 1. Create Group if New
                if not group:
                    project_id = form.project.data
                    project = db.session.get(Project, project_id)
                    if not project:
                        raise ValueError(_l("Selected project not found."))
                    
                    if not can_create_group_for_project(project):
                        raise ValueError(_l("You do not have permission to create groups in this project."))
                    
                    group = group_service.create_group(
                        name=form.name.data,
                        project_id=project.id,
                        team_id=project.team_id,
                        owner_id=current_user.id,
                        model_id=form.model.data
                    )
                    # Handle workplan link if present
                    group.created_from_workplan_id = request.form.get('from_workplan_id')
                    db.session.add(group) # Ensure it's in session

                # 2. Update Details
                group_service.update_group_details(
                    group,
                    name=form.name.data,
                    model_id=form.model.data,
                    ethical_approval_id=form.ethical_approval.data if form.ethical_approval.data else None,
                    default_euthanasia_reason=form.default_euthanasia_reason.data or None,
                    default_severity=form.default_severity.data or None
                )
                
                allow_new_categories = request.form.get('allow_new_categories') == 'true'
                
                # 3. Process Animal Data
                animal_data_list, _ = group_service.process_animal_data(group, request.form, request.files)
                
                # 4. Save Data
                group_service.save_group_data(group, animal_data_list, update_datatables=update_dts_flag, allow_new_categories=allow_new_categories)
                
                if is_ajax:
                    return jsonify({'success': True, 'message': _l('Group details and animal data saved successfully.'), 'group_id': group.id, 
'redirect_url': url_for('groups.edit_group', id=group.id)})
                else:
                    flash('Group details and animal data saved successfully', 'success')
                    return redirect(url_for('groups.edit_group', id=group.id))

            except (ValidationError, ValueError) as e:
                db.session.rollback()
                error_msg = str(e)
                # Check if this is a structured error (e.g. for new categories)
                try:
                    structured_error = json.loads(error_msg)
                    if isinstance(structured_error, dict) and structured_error.get('type') == 'new_categories':
                        if is_ajax:
                            return jsonify({'success': False, 'type': 'new_categories', 'data': structured_error['data']}), 400
                except (json.JSONDecodeError, TypeError):
                    pass

                current_app.logger.warning(f"Validation error saving group {id or 'new'}: {e}")
                if is_ajax:
                    return jsonify({'success': False, 'message': error_msg}), 400
                else:
                    flash(f"Validation Error: {error_msg}", "danger")
            
            except BusinessError as e:
                db.session.rollback()
                current_app.logger.warning(f"Business error saving group {id or 'new'}: {e}")
                if is_ajax:
                    # 409 Conflict is appropriate for business rule violations
                    return jsonify({'success': False, 'message': str(e)}), 409
                else:
                    flash(f"Business Error: {str(e)}", "danger")

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error saving group {id or 'new'}: {e}", exc_info=True)
                if is_ajax:
                    return jsonify({'success': False, 'message': str(e)}), 500
                else:
                    flash(f"Error saving group: {e}", "danger")

    # --- GET Request Logic (Prepare Template Data) ---
    selected_model_id = group.model_id if group else form.model.data
    selected_model_analytes = []
    if selected_model_id:
        model = db.session.get(AnimalModel, selected_model_id)
        if model:
            selected_model_analytes = get_ordered_analytes_for_model(model.id)

    is_unblinded = group.randomization_details.get('unblinded_at') if group and group.randomization_details else False
    can_view_unblinded = (can_view_unblinded_data(group) or is_unblinded) if group else False
    current_app.logger.debug(f"Rendering group '{group.name if group else 'new'}'. is_read_only = {is_read_only}")

    return render_template(
        'groups/edit_group.html',
        form=form,
        group=group,
        prefilled_project_id=prefilled_project.id if prefilled_project else None,
        is_read_only=is_read_only,
        can_view_unblinded=can_view_unblinded,
        selected_model_analytes=selected_model_analytes,
        animal_models_data=[model.to_dict() for model in AnimalModel.query.order_by(AnimalModel.name).all()],
        js_strings={'deceased_label': str(_l('Deceased:'))}
    )


@groups_bp.route('/api/project/<int:project_id>/ethical_approvals')
@login_required
def get_ethical_approvals_for_project(project_id):
    project = db.session.get(Project, project_id)
    if not project or not check_project_permission(project, 'read'):
        return jsonify({'error': 'Project not found or permission denied'}), 404

    # Use the service function to get eligible EAs
    # The team_id_for_eas is derived from the project owner's team, ensuring context
    eligible_eas = get_eligible_ethical_approvals(project_id, project.team_id)

    ea_list = []
    # Add an empty option as the first choice
    ea_list.append({'id': '', 'text': _l('Select Ethical Approval...')})

    # Populate with eligible EAs, including owner team and available animals
    for ea in eligible_eas:
        ea_list.append({
            'id': ea.id,
            'text': f"{ea.reference_number} - {ea.title} ({ea.owner_team.name}) [Available: {get_animals_available_for_ea(ea)}]"
        })
    
    return jsonify(ea_list)


@groups_bp.route('/api/animal_model/<int:model_id>/fields', methods=['GET'])
@login_required
def get_animal_model_fields(model_id):
    try:
        model = db.session.get(AnimalModel, model_id)
        if not model:
            return jsonify({'success': False, 'error': 'Animal model not found'}), 404
        
        analytes = get_ordered_analytes_for_model(model_id)
        fields_data = []
        for analyte in analytes:
            fields_data.append({
                'id': analyte.id,
                'name': analyte.name,
                'type': analyte.data_type.value,
                'unit': analyte.unit or '',
                'allowed_values': analyte.allowed_values or '',
                'default_value': analyte.default_value or '',
                'is_metadata': analyte.is_metadata,
                'is_sensitive': getattr(analyte, 'is_sensitive', False)
            })
        
        return jsonify({'success': True, 'model_name': model.name, 'fields': fields_data})
    except Exception as e:
        current_app.logger.error(f"Error in get_animal_model_fields: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'An unexpected error occurred: {e}'}), 500


@groups_bp.route('/delete/<string:id>', methods=['POST'])
@login_required
def delete_group(id):
    group = db.session.get(ExperimentalGroup, id)
    if not group:
        flash(_l("Experimental Group not found."), "error")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'delete_exp_group'):
        flash(_l("You do not have permission to delete this group."), "danger")
        return redirect(url_for('groups.manage_groups'))

    cascade = request.form.get('cascade') == 'true'
    datatables = DataTable.query.filter_by(group_id=id).all()

    if datatables and not cascade:
        flash(_l('Cannot delete group because it is in use by data tables. Please delete associated data tables first or confirm cascading delete.'), 
'danger')
        return redirect(url_for('groups.manage_groups'))

    try:
        group_name = group.name
        if cascade:
            for dt in datatables:
                db.session.delete(dt)
        
        group_service.delete_group(group)
        
        if cascade and datatables:
            flash(_l("Group '%(group_name)s' and its %(count)s associated data table(s) were permanently deleted.", group_name=group_name, count=len
(datatables)), "success")
        else:
            flash('Group deleted successfully', "success")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting group ID {id}: {e}", exc_info=True)
        flash(_l(f"Error deleting group: {e}"), "danger")

    return redirect(url_for('groups.manage_groups'))


def _safe_filename(name):
    if not isinstance(name, str): name = str(name)
    name = name.strip()
    name = "".join(c if c.isalnum() or c in ['-', '_'] else '_' for c in name)
    name = '_'.join(filter(None, name.split('_')))
    return name if name else "data"

@groups_bp.route('/download_template/<int:model_id>')
@login_required
def download_template(model_id):
    model = db.session.get(AnimalModel, model_id)
    if not model:
        flash(_l("Animal Model not found."), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))

    if not model.analytes:
        flash(_l(f"Cannot generate template: Model '{model.name}' has no analytes defined."), "warning")
        return redirect(request.referrer or url_for('groups.manage_groups'))

    try:
        from app.models import AnalyteDataType
        # Get ordered analytes
        associations = AnimalModelAnalyteAssociation.query.filter_by(animal_model_id=model.id).order_by(AnimalModelAnalyteAssociation.order).all()
        ordered_animal_model_analytes = [assoc.analyte for assoc in associations]

        final_field_names_set = set(["ID", "Date of Birth"])
        final_field_names = ["ID", "Date of Birth"]
        
        excluded_fields = {'Age (Days)', 'Blinded Group', 'Treatment Group', 'status'}
        for analyte in ordered_animal_model_analytes:
            if analyte.name not in final_field_names_set and analyte.name not in excluded_fields:
                final_field_names.append(analyte.name)
                final_field_names_set.add(analyte.name)

        excel_file = generate_xlsx_template(ordered_animal_model_analytes, base_fields=final_field_names)
        download_filename = f"{_safe_filename(model.name)}_upload_template.xlsx"
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=download_filename
        )
    except Exception as e:
        current_app.logger.error(f"Error generating XLSX template for model {model_id}: {e}", exc_info=True)
        flash(_l(f"Error generating template file: {e}"), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))

@groups_bp.route('/download_group_data/<string:group_id>')
@login_required
def download_group_data(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        flash(_l("Experimental Group not found."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'read'):
        flash(_l("You do not have permission to view this group's data."), "danger")
        return redirect(url_for('groups.manage_groups'))

    model = group.model
    if not model:
        flash(_l(f"Cannot generate file: Group '{group.name}' has no associated Animal Model."), "warning")
        return redirect(url_for('groups.edit_group', id=group_id))

    try:
        import openpyxl
        from openpyxl.comments import Comment
        from openpyxl.worksheet.datavalidation import DataValidation
        from app.models import AnimalModelAnalyteAssociation, AnalyteDataType
        
        # Get ordered analytes
        associations = AnimalModelAnalyteAssociation.query.filter_by(animal_model_id=model.id).order_by(AnimalModelAnalyteAssociation.order).all()
        ordered_animal_model_analytes = [assoc.analyte for assoc in associations]

        final_ordered_field_names_set = set()
        final_ordered_field_names = []

        # Add standard fields (ID and DOB are mandatory)
        standard_fields = ["ID", "Date of Birth"]

        for key in standard_fields:
            if key not in final_ordered_field_names_set:
                final_ordered_field_names.append(key)
                final_ordered_field_names_set.add(key)

        # Add model analytes (excluding system-calculated/mock fields)
        excluded_fields = {'Age (Days)', 'Blinded Group', 'Treatment Group', 'status'}
        for analyte in ordered_animal_model_analytes:
            if analyte.name not in final_ordered_field_names_set and analyte.name not in excluded_fields:
                final_ordered_field_names.append(analyte.name)
                final_ordered_field_names_set.add(analyte.name)
        
        if 'Death Date' not in final_ordered_field_names_set:
            final_ordered_field_names.append('Death Date')
            final_ordered_field_names_set.add('Death Date')

        # Prepare data first to handle renames
        animal_data = group.animal_data if isinstance(group.animal_data, list) else []
        processed_animal_data = []
        for animal in animal_data:
            processed_animal = animal.copy()
            if 'death_date' in processed_animal:
                processed_animal['Death Date'] = processed_animal.pop('death_date')
            if 'euthanasia_reason' in processed_animal:
                processed_animal['Euthanasia Reason'] = processed_animal.pop('euthanasia_reason')
            if 'severity' in processed_animal:
                processed_animal['Severity'] = processed_animal.pop('severity')
            processed_animal_data.append(processed_animal)

        # Now build field names from processed data
        final_ordered_field_names_set = set()
        final_ordered_field_names = []

        # Add standard fields
        is_blinded = group.randomization_details.get('use_blinding', False) if group.randomization_details else False
        can_unblind = can_view_unblinded_data(group)

        standard_fields = ["ID", "Date of Birth", "Age (Days)"]
        if is_blinded:
            standard_fields.append("Blinded Group")
            if can_unblind:
                standard_fields.append("Treatment Group")
        else:
            standard_fields.append("Treatment Group")

        for key in standard_fields:
            if key not in final_ordered_field_names_set:
                final_ordered_field_names.append(key)
                final_ordered_field_names_set.add(key)

        # Add model analytes
        for analyte in ordered_animal_model_analytes:
            if analyte.name not in final_ordered_field_names_set:
                final_ordered_field_names.append(analyte.name)
                final_ordered_field_names_set.add(analyte.name)

        if 'Death Date' not in final_ordered_field_names_set:
            final_ordered_field_names.append('Death Date')
            final_ordered_field_names_set.add('Death Date')

        # Add dynamic fields from processed data
        for animal in processed_animal_data:
            for key in animal.keys():
                if key not in final_ordered_field_names_set:
                    final_ordered_field_names.append(key)
                    final_ordered_field_names_set.add(key)

        # Ensure all animals have all fields
        for processed_animal in processed_animal_data:
            for field_name in final_ordered_field_names:
                if field_name not in processed_animal:
                    processed_animal[field_name] = None

        df = pd.DataFrame(processed_animal_data, columns=final_ordered_field_names)
        df = df.fillna('')

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Animal Data')
            
            # Add data validation for category fields (like the template does)
            workbook = writer.book
            worksheet = writer.sheets['Animal Data']
            
            # Create a mapping of field names to analytes for validation
            analyte_map = {analyte.name: analyte for analyte in ordered_animal_model_analytes}
            
            for col_idx, field_name in enumerate(final_ordered_field_names, 1):
                if field_name in analyte_map:
                    analyte = analyte_map[field_name]
                    col_letter = openpyxl.utils.get_column_letter(col_idx)
                    header_cell = worksheet.cell(row=1, column=col_idx)
                    comment_lines = []
                    
                    if analyte.description:
                        comment_lines.append(f"Description: {analyte.description}")
                    if analyte.unit:
                        comment_lines.append(f"Unit: {analyte.unit}")
                    
                    # Add data validation for category fields
                    if analyte.data_type == AnalyteDataType.CATEGORY and analyte.allowed_values:
                        allowed_list = [v.strip() for v in analyte.allowed_values.split(';')]
                        formula = f'"{",".join(allowed_list)}"'
                        dv = DataValidation(type="list", formula1=formula, allow_blank=True)
                        worksheet.add_data_validation(dv)
                        dv.add(f'{col_letter}2:{col_letter}1048576')
                        comment_lines.append(f"Allowed values: {', '.join(allowed_list)}")
                    
                    # Add date validation
                    elif analyte.data_type == AnalyteDataType.DATE:
                        dv = DataValidation(type="date", operator="greaterThan", formula1="1900-01-01")
                        worksheet.add_data_validation(dv)
                        dv.add(f'{col_letter}2:{col_letter}1048576')
                        comment_lines.append("Format: YYYY-MM-DD")
                        for cell in worksheet[col_letter][1:]:
                            cell.number_format = 'YYYY-MM-DD'
                    
                    if comment_lines:
                        header_cell.comment = Comment("\n".join(comment_lines), "System")
        
        output.seek(0)

        safe_group_name = _safe_filename(group.name)
        safe_model_name = _safe_filename(model.name)
        project_slug = _safe_filename(group.project.slug if group.project else 'unknown_project')
        download_filename = f"{project_slug}_{safe_group_name}_{safe_model_name}_data.xlsx"

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=download_filename
        )
    except Exception as e:
        current_app.logger.error(f"Error generating group data file for group {group_id}: {e}", exc_info=True)
        flash(_l(f"Error generating data file: {e}"), "danger")
        return redirect(url_for('groups.edit_group', id=group_id))

@groups_bp.route('/declare_dead/<string:group_id>', methods=['POST'])
@login_required
def declare_dead(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group: return jsonify({'success': False, 'message': 'Group not found'}), 404
    if not check_group_permission(group, 'edit_exp_group'): return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()
    death_date_str = data.get('death_date')
    animals_data = data.get('animals', [])

    if not death_date_str or not animals_data:
        return jsonify({'success': False, 'message': 'Missing data'}), 400

    # Validate euthanasia fields
    valid_reasons = ["état de santé", "fin de protocole", "Point limite atteint"]
    valid_severities = ["légère", "modérée", "sévère"]

    try:
        death_date = datetime.strptime(death_date_str, '%Y-%m-%d').date().isoformat()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format'}), 400

    for animal_info in animals_data:
        index = animal_info.get('index')
        euthanasia_reason = animal_info.get('euthanasia_reason')
        severity = animal_info.get('severity')

        if not euthanasia_reason or euthanasia_reason not in valid_reasons:
            return jsonify({'success': False, 'message': f'Invalid euthanasia reason for animal {index}'}), 400
        if not severity or severity not in valid_severities:
            return jsonify({'success': False, 'message': f'Invalid severity for animal {index}'}), 400

        try:
            index = int(index)
            if 0 <= index < len(group.animal_data):
                group.animal_data[index]['status'] = 'dead'
                group.animal_data[index]['death_date'] = death_date
                group.animal_data[index]['euthanasia_reason'] = euthanasia_reason
                group.animal_data[index]['severity'] = severity
        except (ValueError, IndexError):
            pass

    flag_modified(group, "animal_data")
    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Animals declared dead.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error declaring animals dead for group {group_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Database error'}), 500

@groups_bp.route('/archive/<string:id>', methods=['POST'])
@login_required
def archive_group(id):
    group = db.session.get(ExperimentalGroup, id)
    if not group:
        flash(_l("Experimental Group not found."), "error")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'archive_exp_group'):
        flash(_l("You do not have permission to archive this group."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if group.is_archived:
        flash(_l("Group is already archived."), "info")
    else:
        group.is_archived = True
        group.archived_at = datetime.now(current_app.config['UTC_TZ'])
        try:
            db.session.commit()
            flash(_l(f"Group '{group.name}' has been archived."), "success")
        except Exception as e:
            db.session.rollback()
            flash(_l(f"Error archiving group: {e}"), "danger")
    return redirect(request.referrer or url_for('groups.manage_groups', show_archived=True))

@groups_bp.route('/unarchive/<string:id>', methods=['POST'])
@login_required
def unarchive_group(id):
    group = db.session.get(ExperimentalGroup, id)
    if not group:
        flash(_l("Group not found."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'archive_exp_group'):
        flash(_l("You do not have permission to unarchive this group."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if not group.is_archived:
        flash(_l("Group is not archived."), "info")
    else:
        group.is_archived = False
        group.archived_at = None
        try:
            db.session.commit()
            flash(_l(f"Group '{group.name}' has been unarchived."), "success")
        except Exception as e:
            db.session.rollback()
            flash(_l(f"Error unarchiving group: {e}"), "danger")
    return redirect(request.referrer or url_for('groups.manage_groups', show_archived=True))

@groups_bp.route('/<string:group_id>/generate_datatables', methods=['POST'])
@login_required
def generate_datatables_from_workplan(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not group.created_from_workplan_id:
        return jsonify({'success': False, 'message': 'Group not found or not linked to a workplan.'}), 404
    if not check_group_permission(group, 'edit_exp_group'):
        return jsonify({'success': False, 'message': 'Permission denied.'}), 403

    workplan = group.created_from_workplan
    if not workplan or not workplan.study_start_date:
        return jsonify({'success': False, 'message': 'Linked workplan or its start date is missing.'}), 400

    created_count = 0
    skipped_count = 0
    try:
        for event in workplan.events.all():
            event_date = workplan.study_start_date + timedelta(days=event.offset_days)
            date_str = event_date.isoformat()

            existing_dt = DataTable.query.filter_by(
                group_id=group.id,
                protocol_id=event.protocol_id,
                date=date_str
            ).first()

            if existing_dt:
                skipped_count += 1
                continue

            dt = DataTable(
                group_id=group.id,
                protocol_id=event.protocol_id,
                date=date_str,
                creator_id=current_user.id,
                workplan_event_id=event.id
            )
            db.session.add(dt)
            db.session.flush()

            if group.animal_data:
                for i in range(len(group.animal_data)):
                    exp_row = ExperimentDataRow(data_table_id=dt.id, row_index=i, row_data={})
                    db.session.add(exp_row)
            
            created_count += 1
        
        db.session.commit()
        return jsonify({
            'success': True, 
            'created_count': created_count,
            'skipped_count': skipped_count
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating datatables for group {group_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@groups_bp.route('/api/group/<string:group_id>/datatables_for_randomization')
@login_required
def get_group_datatables_for_randomization(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not check_group_permission(group, 'read'):
        return jsonify({'error': 'Group not found or permission denied'}), 404

    datatables = DataTable.query.filter_by(group_id=group.id).order_by(DataTable.date.desc()).all()
    
    dt_data = []
    for dt in datatables:
        numerical_analytes = [
            {'name': a.name} 
            for a in dt.protocol.analytes 
            if a.data_type in [AnalyteDataType.FLOAT, AnalyteDataType.INT]
        ]
        if numerical_analytes:
            dt_data.append({
                'id': dt.id,
                'text': f"{dt.protocol.name} ({dt.date})",
                'analytes': numerical_analytes
            })

    return jsonify(dt_data)

@groups_bp.route('/<string:group_id>/randomize', methods=['POST'])
@login_required
def randomize_group(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not check_group_permission(group, 'edit_exp_group'):
        return jsonify({'success': False, 'message': 'Permission denied.'}), 403

    if group.randomization_details:
        current_app.logger.warning(f"Re-randomizing group {group_id}. Old details will be overwritten.")
        # We allow re-randomization now. 
        # Optionally, we could call delete_randomization logic here internally, 
        # but the following code will overwrite the keys anyway.

    data = request.get_json()
    use_blinding = data.get('use_blinding', True)
    
    # 1. Define the total pool of animals
    all_animals = [{'index': i, **animal} for i, animal in enumerate(group.animal_data) if animal.get('status') != 'dead']
    
    # 2. Apply primary stratification
    stratification_factor = data.get('stratification_factor')
    animal_pools = []
    if stratification_factor:
        strata = defaultdict(list)
        for animal in all_animals:
            stratum_key = animal.get(stratification_factor, 'N/A')
            strata[stratum_key].append(animal)
        animal_pools = list(strata.values())
    else:
        animal_pools.append(all_animals)

    # 3. Process each pool
    final_assignments = {} # animal_index -> {'blinded': name, 'actual': name}
    assignment_method = data.get('assignment_method', 'Simple')
    minimization_details = data.get('minimization_details')
    
    # Pre-fetch baseline data if minimization
    baseline_values = {}
    if assignment_method == 'Minimization' and minimization_details:
        analyte_name = minimization_details['analyte']
        if minimization_details['source'] == 'animal_model':
            for animal in all_animals:
                try:
                    baseline_values[animal['index']] = float(animal.get(analyte_name))
                except (ValueError, TypeError, AttributeError):
                    baseline_values[animal['index']] = None
        else: # datatable source
            datatable_rows = ExperimentDataRow.query.filter_by(data_table_id=minimization_details['datatable_id']).all()
            datatable_row_map = {row.row_index: row.row_data for row in datatable_rows}
            for animal in all_animals:
                row_data = datatable_row_map.get(animal['index'])
                if row_data and analyte_name in row_data:
                    try:
                        baseline_values[animal['index']] = float(row_data[analyte_name])
                    except (ValueError, TypeError, AttributeError):
                        baseline_values[animal['index']] = None
                else:
                    baseline_values[animal['index']] = None

    for pool in animal_pools:
        unit_key = data['randomization_unit']
        allow_splitting = data.get('allow_splitting', False)
        
        units = []
        if unit_key == '__individual__' or allow_splitting:
            units = [[animal] for animal in pool]
        else:
            clusters = defaultdict(list)
            for animal in pool:
                clusters[animal.get(unit_key, 'N/A')].append(animal)
            units = list(clusters.values())

        total_pool_units = len(units)
        total_requested_units_overall = sum(tg['count'] for tg in data['treatment_groups'])
        
        assignment_pool = []
        if total_requested_units_overall > 0:
            for tg in data['treatment_groups']:
                num_to_assign = round((tg['count'] / total_requested_units_overall) * total_pool_units)
                # Store the FULL treatment group object or a tuple of names
                tg_info = {'blinded': tg['blinded_name'], 'actual': tg['actual_name']}
                assignment_pool.extend([tg_info] * int(num_to_assign))
            
            while len(assignment_pool) < total_pool_units:
                if not assignment_pool:
                    all_possible_groups = [{'blinded': tg['blinded_name'], 'actual': tg['actual_name']} for tg in data['treatment_groups']]
                    if not all_possible_groups: break
                    assignment_pool.append(random.choice(all_possible_groups))
                else:
                    assignment_pool.append(random.choice(assignment_pool))

            assignment_pool = assignment_pool[:total_pool_units]
            random.shuffle(assignment_pool)

        random.shuffle(units)
        
        if assignment_method == 'Minimization' and minimization_details:
            # For minimization, we need to track counts of ASSIGNED groups to stay balanced
            group_assignments = defaultdict(list)
            
            for unit in units:
                unit_values = [baseline_values.get(animal['index']) for animal in unit]
                unit_values = [v for v in unit_values if v is not None]
                if not unit_values: continue

                unit_mean = np.mean(unit_values)
                
                best_group_info = None
                min_imbalance = float('inf')
                tied_groups = []

                # Unique group identifiers for mapping
                available_group_indices = list(range(len(assignment_pool)))
                unique_groups = []
                seen_actuals = set()
                for info in assignment_pool:
                    if info['actual'] not in seen_actuals:
                        unique_groups.append(info)
                        seen_actuals.add(info['actual'])

                for group_info in unique_groups:
                    group_name = group_info['blinded' if use_blinding else 'actual']
                    current_group_values = [item for sublist in group_assignments[group_name] for item in sublist]
                    hypothetical_values = current_group_values + [unit_mean]
                    
                    imbalance = 0
                    all_group_means = []
                    for g_info in unique_groups:
                        g_name = g_info['blinded' if use_blinding else 'actual']
                        g_values = [item for sublist in group_assignments[g_name] for item in sublist]
                        if g_name == group_name:
                            all_group_means.append(np.mean(hypothetical_values))
                        elif g_values:
                            all_group_means.append(np.mean(g_values))
                    
                    if len(all_group_means) > 1:
                        imbalance = np.var(all_group_means)

                    if imbalance < min_imbalance:
                        min_imbalance = imbalance
                        tied_groups = [group_info]
                    elif imbalance == min_imbalance:
                        tied_groups.append(group_info)

                best_group_info = random.choice(tied_groups)
                g_key = best_group_info['blinded' if use_blinding else 'actual']
                group_assignments[g_key].append([unit_mean])
                
                # Remove one instance of this group from the pool
                for item in assignment_pool:
                    if item['actual'] == best_group_info['actual']:
                        assignment_pool.remove(item)
                        break
                
                for animal in unit:
                    final_assignments[animal['index']] = best_group_info
        else:
            for i, unit in enumerate(units):
                assignment_info = assignment_pool[i]
                for animal in unit:
                    final_assignments[animal['index']] = assignment_info

    # 4. Calculate Final Summary Statistics
    minimization_summary = None
    if assignment_method == 'Minimization' and minimization_details:
        group_stats = defaultdict(lambda: {'values': []})
        for index, info in final_assignments.items():
            assignment = info['blinded' if use_blinding else 'actual']
            value = baseline_values.get(index)
            if value is not None:
                group_stats[assignment]['values'].append(value)
        
        minimization_summary = {}
        for group_name, stats in group_stats.items():
            values = stats['values']
            if len(values) > 0:
                minimization_summary[group_name] = {
                    'mean': np.mean(values),
                    'sem': np.std(values, ddof=1) / np.sqrt(len(values)) if len(values) > 1 else 0,
                    'n': len(values)
                }

    # 5. Apply assignments
    for index, info in final_assignments.items():
        # ALWAYS set Treatment Group
        group.animal_data[index]["Treatment Group"] = info['actual']
        if use_blinding:
            group.animal_data[index]["Blinded Group"] = info['blinded']
        elif "Blinded Group" in group.animal_data[index]:
            # Clean up if we re-randomized without blinding
            del group.animal_data[index]["Blinded Group"]
    
    flag_modified(group, "animal_data")

    if minimization_details and minimization_details.get('source') == 'datatable':
        datatable = db.session.get(DataTable, minimization_details['datatable_id'])
        if datatable:
            minimization_details['source_name'] = f"{datatable.protocol.name} ({datatable.date})"
            minimization_details['source_url'] = url_for('datatables.edit_data_table', id=datatable.id)
    
    group.randomization_details = {
        "use_blinding": use_blinding,
        "unit_of_randomization": data['randomization_unit'],
        "allow_splitting": data.get('allow_splitting', False),
        "min_subgroup_size": data.get('min_subgroup_size'),
        "stratification_factor": stratification_factor,
        "assignment_method": assignment_method,
        "minimization_details": minimization_details,
        "minimization_summary": minimization_summary,
        "requested_group_sizes": {tg['blinded_name' if use_blinding else 'actual_name']: tg['count'] for tg in data['treatment_groups']},
        "blinding_key": {tg['blinded_name']: tg['actual_name'] for tg in data['treatment_groups']} if use_blinding else None,
        "randomized_at": datetime.now(current_app.config['UTC_TZ']).isoformat(),
        "randomized_by": current_user.email
    }
    
    flag_modified(group, "randomization_details")

    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'Randomization complete.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error during randomization commit: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500
    
@groups_bp.route('/<string:group_id>/delete_randomization', methods=['POST'])
@login_required
def delete_randomization(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not check_group_permission(group, 'edit_exp_group'):
        return jsonify({'success': False, 'message': 'Permission denied.'}), 403

    if not group.randomization_details:
        return jsonify({'success': False, 'message': 'Group has not been randomized.'}), 400

    use_blinding = group.randomization_details.get('use_blinding', True)
    assignment_analyte_name = "Blinded Group" if use_blinding else "Treatment Group"

    for animal in group.animal_data:
        if assignment_analyte_name in animal:
            del animal[assignment_analyte_name]
    
    flag_modified(group, "animal_data")
    group.randomization_details = None
    flag_modified(group, "randomization_details")

    try:
        db.session.commit()
        flash(_l('Randomization details have been deleted.'), 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting randomization for group {group_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500
        
@groups_bp.route('/<string:group_id>/unblind', methods=['POST'])
@login_required
def unblind_group(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not can_view_unblinded_data(group):
        flash(_l("Group not found or permission denied."), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))

    if not group.randomization_details or not group.randomization_details.get('use_blinding'):
        flash(_l("This group was not blinded, so no unblinding action is necessary."), "info")
        return redirect(url_for('groups.edit_group', id=group.id))

    if 'blinding_key' not in group.randomization_details:
        flash(_l("Group has not been randomized or blinding key is missing."), "warning")
        return redirect(url_for('groups.edit_group', id=group.id))

    if group.randomization_details.get('unblinded_at'):
        flash(_l("This group has already been unblinded."), "info")
        return redirect(url_for('groups.edit_group', id=group.id))

    try:
        treatment_analyte_name = "Treatment Group"
        treatment_analyte = Analyte.query.filter_by(name=treatment_analyte_name).first()
        if not treatment_analyte:
            treatment_analyte = Analyte(
                name=treatment_analyte_name,
                data_type=AnalyteDataType.TEXT,
                description="The unblinded treatment group assignment for an animal.",
                is_metadata=True
            )
            db.session.add(treatment_analyte)
        
        if treatment_analyte not in group.model.analytes:
            group.model.analytes.append(treatment_analyte)

        blinding_key = group.randomization_details['blinding_key']
        for animal in group.animal_data:
            blinded_value = animal.get("Blinded Group")
            if blinded_value in blinding_key:
                animal[treatment_analyte_name] = blinding_key[blinded_value]
        flag_modified(group, "animal_data")

        group.randomization_details['unblinded_at'] = datetime.now(current_app.config['UTC_TZ']).isoformat()
        group.randomization_details['unblinded_by'] = current_user.email
        flag_modified(group, "randomization_details")

        db.session.commit()
        flash(_l("Group '%(name)s' has been successfully unblinded.", name=group.name), "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error unblinding group {group.id}: {e}", exc_info=True)
        flash(_l("An error occurred during unblinding."), "danger")

    return redirect(url_for('groups.edit_group', id=group.id))

@groups_bp.route('/api/group/<string:group_id>/randomization_summary', methods=['GET'])
@login_required
def get_randomization_summary(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not check_group_permission(group, 'read'):
        return jsonify({'error': 'Group not found or permission denied'}), 404

    if not group.randomization_details:
        return jsonify({'message': 'Group has not been randomized yet.'}), 200
    
    summary_data = group.randomization_details.copy()

    # Calculate actual group sizes
    if group.animal_data:
        assignment_analyte_name = "Blinded Group" if group.randomization_details.get('use_blinding') else "Treatment Group"
        actual_assignments = defaultdict(int)
        for animal in group.animal_data:
            assignment = animal.get(assignment_analyte_name)
            if assignment:
                actual_assignments[assignment] += 1
        summary_data['actual_group_sizes'] = dict(actual_assignments)

    return jsonify(summary_data)

@groups_bp.route('/api/<string:group_id>/animal_data', methods=['GET'])
@login_required
def get_group_animal_data(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group or not check_group_permission(group, 'read'):
        return jsonify({'error': 'Group not found or permission denied'}), 404

    # Get datatable info for animals
    datatable_info = {}
    if group.animal_data:
        # Get all datatables for this group
        datatables = DataTable.query.filter_by(group_id=group_id).options(db.joinedload(DataTable.protocol)).all()

        # For each animal index, collect datatables they participated in
        for dt in datatables:
            rows = ExperimentDataRow.query.filter_by(data_table_id=dt.id).with_entities(ExperimentDataRow.row_index).all()
            for row in rows:
                animal_idx = row.row_index
                if animal_idx not in datatable_info:
                    datatable_info[animal_idx] = []
                datatable_info[animal_idx].append({
                    'id': dt.id,
                    'name': dt.protocol.name if dt.protocol else 'Unknown',
                    'date': dt.date,
                    'severity': dt.protocol.severity.value if dt.protocol and dt.protocol.severity else 'Unknown'
                })

    response = {
        'animals': group.animal_data or [],
        'datatable_info': datatable_info
    }

    return jsonify(response)

@groups_bp.route('/api/<string:group_id>/concatenated_analytes', methods=['GET'])
@login_required
def get_concatenated_analytes_for_group(group_id):
    try:
        data, errors, _ = datatable_service.get_concatenated_analyte_data_for_group(group_id, current_user)
        if errors:
            return jsonify({'error': '; '.join(errors)}), 400
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching concatenated analytes for group {group_id}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@groups_bp.route('/export_concatenated/<string:group_id>', methods=['POST'])
@login_required
def export_concatenated_analytes(group_id):
    try:
        data = request.get_json()
        concatenated_data = data.get('concatenated_data', {})

        # Convert to DataFrame-like structure for export
        rows = []
        analytes = Object.keys(concatenated_data.get('analytes', {}))
        animal_data = concatenated_data.get('animal_data', {})

        for animal_id, analyte_data in animal_data.items():
            for analyte_name, values in analyte_data.items():
                for date, value in values:
                    rows.append({
                        'Animal ID': animal_id,
                        'Analyte': analyte_name,
                        'Date': date,
                        'Value': value
                    })

        df = pd.DataFrame(rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Concatenated Data')
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'concatenated_analytes_{group_id}.xlsx'
        )
    except Exception as e:
        current_app.logger.error(f"Error exporting concatenated data for group {group_id}: {e}", exc_info=True)
        return jsonify({'error': 'Export failed'}), 500

@groups_bp.route('/<string:group_id>/molecule_usage', methods=['GET'])
@login_required
def group_molecule_usage_summary(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        abort(404)
    if not check_group_permission(group, 'read'):
        abort(403)

    # Fetch all molecule usage records for all datatables in this group
    usages = db.session.query(
        DataTableMoleculeUsage, 
        DataTable, 
        ControlledMolecule
    ).join(
        DataTable, DataTableMoleculeUsage.data_table_id == DataTable.id
    ).join(
        ControlledMolecule, DataTableMoleculeUsage.molecule_id == ControlledMolecule.id
    ).filter(
        DataTable.group_id == group_id
    ).order_by(DataTable.date.desc(), DataTableMoleculeUsage.recorded_at.desc()).all()

    # Aggregate by animal ID
    animal_usage = defaultdict(list)
    used_molecules = {} # id -> name
    
    for usage, dt, molecule in usages:
        used_molecules[molecule.id] = molecule.name
        target_animals = usage.animal_ids if usage.animal_ids else []
        
        dose_per_animal = None
        if usage.volume_used is not None and usage.number_of_animals and usage.number_of_animals > 0:
            dose_per_animal = float(usage.volume_used) / usage.number_of_animals

        usage_info = {
            'molecule_name': molecule.name,
            'molecule_id': molecule.id,
            'unit': molecule.unit,
            'date': dt.date,
            'dose': dose_per_animal,
            'total_volume': float(usage.volume_used) if usage.volume_used else None,
            'batch': usage.batch_number,
            'route': usage.administration_route,
            'notes': usage.notes,
            'recorded_by': usage.recorded_by.username if usage.recorded_by else None,
            'datatable_id': dt.id
        }
        
        for animal_id in target_animals:
            animal_usage[str(animal_id)].append(usage_info)

    # Get model analytes for filtering
    analytes = get_ordered_analytes_for_model(group.model_id) if group else []

    animals = []
    if group.animal_data:
        for animal in group.animal_data:
            a_id = animal.get('ID')
            # Extract only the analyte values for client-side filtering
            animal_metadata = {a.name: animal.get(a.name) for a in analytes}
            
            animals.append({
                'id': a_id,
                'status': animal.get('status', 'alive'),
                'treatment_group': animal.get('Treatment Group') or animal.get('Blinded Group'),
                'usages': animal_usage.get(str(a_id), []),
                'metadata': animal_metadata
            })

    return render_template(
        'groups/molecule_usage_summary.html',
        group=group,
        animals=animals,
        used_molecules=used_molecules,
        analytes=analytes,
        can_view_unblinded=can_view_unblinded_data(group)
    )

@groups_bp.route('/<string:group_id>/molecule_usage/export', methods=['GET'])
@login_required
def export_molecule_usage_summary(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        abort(404)
    if not check_group_permission(group, 'read'):
        abort(403)

    # Re-fetch usages for export
    usages = db.session.query(
        DataTableMoleculeUsage, 
        DataTable, 
        ControlledMolecule
    ).join(
        DataTable, DataTableMoleculeUsage.data_table_id == DataTable.id
    ).join(
        ControlledMolecule, DataTableMoleculeUsage.molecule_id == ControlledMolecule.id
    ).filter(
        DataTable.group_id == group_id
    ).order_by(DataTable.date.desc(), DataTableMoleculeUsage.recorded_at.desc()).all()

    # Aggregate by animal ID
    animal_usage = defaultdict(list)
    for usage, dt, molecule in usages:
        target_animals = usage.animal_ids if usage.animal_ids else []
        dose_per_animal = None
        if usage.volume_used is not None and usage.number_of_animals and usage.number_of_animals > 0:
            dose_per_animal = float(usage.volume_used) / usage.number_of_animals
        
        usage_info = {
            'Date': dt.date,
            'Molecule': molecule.name,
            'Dose': dose_per_animal,
            'Unit': molecule.unit,
            'Batch': usage.batch_number,
            'Route': usage.administration_route,
            'Notes': usage.notes
        }
        for animal_id in target_animals:
            animal_usage[str(animal_id)].append(usage_info)

    export_data = []
    if group.animal_data:
        for animal in group.animal_data:
            a_id = str(animal.get('ID'))
            base_info = {
                'Animal ID': a_id,
                'Status': animal.get('status', 'alive'),
                'Group/Blinding': animal.get('Treatment Group') or animal.get('Blinded Group')
            }
            # Add animal metadata from animal_data
            for key, val in animal.items():
                if key not in ['ID', 'status', 'Treatment Group', 'Blinded Group']:
                    base_info[key] = val
                    
            animal_usages = animal_usage.get(a_id, [])
            if not animal_usages:
                export_data.append(base_info)
            else:
                for u in animal_usages:
                    row = base_info.copy()
                    row.update(u)
                    export_data.append(row)

    df = pd.DataFrame(export_data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Molecule Usage')
        # Simple formatting could be added here if needed
    
    output.seek(0)
    
    # Safe filename
    safe_name = re.sub(r'[^\w\s-]', '', group.name).strip().replace(' ', '_')
    filename = f"Molecule_Usage_{safe_name}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
