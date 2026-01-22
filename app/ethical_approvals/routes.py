# app/ethical_approvals/routes.py
import re
from defusedxml import ElementTree as ET
from types import SimpleNamespace
import io
from datetime import date, datetime

import openpyxl
import pandas as pd
from dateutil.relativedelta import relativedelta
from flask import (current_app, flash, jsonify, redirect, render_template,
                   request, session, url_for, send_file)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required
from sqlalchemy import func, or_, Date, cast
from sqlalchemy.exc import IntegrityError
from wtforms.validators import DataRequired

from app.services.ethical_approval_service import (
    get_animals_available_for_ea, validate_ea_unshare_from_team)

from .. import db
from ..forms import EthicalApprovalForm, XMLImportForm
from ..models import user_has_permission
from ..models import (DataTable, EthicalApproval,
                      EthicalApprovalProcedure, ExperimentalGroup,
                      ExperimentDataRow, Project, ProtocolModel, Severity,
                      Team)
from ..permissions import check_datatable_permission
from . import ethical_approvals_bp


@ethical_approvals_bp.route("/", methods=['GET'])
@login_required
def list_ethical_approvals():
    """
    OPTIMIZED: Uses server-side pagination and batch-fetch for counts.
    HEAVY CALCULATION DISABLED: Animal usage count from JSON is disabled for performance.
    """
    can_manage_eas = user_has_permission(current_user, 'EthicalApproval', 'edit') or user_has_permission(current_user, 'EthicalApproval', 'delete')
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    per_page = min(per_page, 100)
    
    base_query = EthicalApproval.query.options(db.joinedload(EthicalApproval.owner_team))

    if not current_user.is_super_admin:
        user_teams = current_user.get_teams()
        if not user_teams:
            base_query = base_query.filter(db.false())
        else:
            user_team_ids = [team.id for team in user_teams]
            base_query = base_query.filter(
                db.or_(
                    EthicalApproval.team_id.in_(user_team_ids),
                    EthicalApproval.shared_with_teams.any(Team.id.in_(user_team_ids))
                )
            )

    total_count = base_query.count()
    
    ethical_approvals = base_query.order_by(EthicalApproval.start_date.desc())\
        .offset((page - 1) * per_page)\
        .limit(per_page)\
        .all()
    
    approval_summaries = []
    
    if ethical_approvals:
        ea_ids = [ea.id for ea in ethical_approvals]
        
        # 1. Group Counts
        group_counts_query = db.session.query(
            ExperimentalGroup.ethical_approval_id,
            func.count(ExperimentalGroup.id).label('group_count')
        ).filter(
            ExperimentalGroup.ethical_approval_id.in_(ea_ids)
        ).group_by(ExperimentalGroup.ethical_approval_id).all()
        
        group_counts_map = {r.ethical_approval_id: r.group_count for r in group_counts_query}
        
        # 2. DataTable Counts
        datatable_counts_query = db.session.query(
            ExperimentalGroup.ethical_approval_id,
            func.count(DataTable.id).label('dt_count')
        ).join(DataTable)\
         .filter(ExperimentalGroup.ethical_approval_id.in_(ea_ids))\
         .group_by(ExperimentalGroup.ethical_approval_id).all()
        
        datatable_counts_map = {r.ethical_approval_id: r.dt_count for r in datatable_counts_query}
        
        # 3. Animal Counts (DISABLED FOR PERFORMANCE)
        # Parsing JSON for 80k groups causes timeouts.
        # animal_counts_map = {} 
        
        for approval in ethical_approvals:
            # animals_used = animal_counts_map.get(approval.id, 0)
            # animals_available = approval.number_of_animals - animals_used
            
            # Placeholder values to prevent crash
            animals_used = "Calc. Disabled" 
            animals_available = "N/A"

            approval_summaries.append({
                'approval': approval,
                'team_name': approval.owner_team.name if approval.owner_team else _l("N/A"),
                'animals_available_count': "...",
                'animals_used_count': "...", 
                'animals_linked_count': "...",
                'contributing_groups_count': group_counts_map.get(approval.id, 0),
                'linked_datatables_count': datatable_counts_map.get(approval.id, 0),
                'ea_id': approval.id
            })
    
    total_pages = (total_count + per_page - 1) // per_page

    return render_template('ethical_approvals/list_ethical_approvals.html',
                           title=_l('Ethical Approvals'),
                           approval_summaries=approval_summaries,
                           can_manage=can_manage_eas,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages)


@ethical_approvals_bp.route("/animals_usage_counts", methods=['POST'])
@login_required
def get_animals_usage_counts():
    """
    Optimized endpoint to fetch animal counts for a list of Ethical Approvals.
    Calculates both Linked (Reserved) and Used (Effective) counts.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        ea_ids = data.get('ea_ids', [])
        
        # Ensure unique integers
        ea_ids = list(set([int(x) for x in ea_ids if str(x).isdigit()]))
        
        if not ea_ids:
            return jsonify({})

        # 1. Animals Linked (Reserved)
        # OPTIMIZATION: Fetch ONLY ethical_approval_id and animal_data column. 
        # Avoids hydrating full ExperimentalGroup objects which is slow.
        groups_data = db.session.query(
            ExperimentalGroup.ethical_approval_id, 
            ExperimentalGroup.animal_data
        ).filter(ExperimentalGroup.ethical_approval_id.in_(ea_ids)).all()
        
        linked_counts = {ea_id: 0 for ea_id in ea_ids}
        for ea_id, animal_data in groups_data:
            if animal_data and isinstance(animal_data, list):
                linked_counts[ea_id] += len(animal_data)

        # 2. Animals Used (Effective)
        # OPTIMIZATION: Filter first, then join. 
        # Also, using a compound unique string for COUNT(DISTINCT) is often faster 
        # and more portable (SQLite) than tuple distincts in subqueries for simple counts.
        
        # Step A: Get all Group IDs involved
        # group_ids_qr = db.session.query(ExperimentalGroup.id).filter(ExperimentalGroup.ethical_approval_id.in_(ea_ids)).all()
        # group_ids = [r[0] for r in group_ids_qr]

        # Step B: Query directly
        # We perform the join and distinct check. 
        # Note: SQLite doesn't support COUNT(DISTINCT col1, col2).
        # We use a subquery approach which is standard but we ensure we select minimal data.
        
        subq = db.session.query(
            ExperimentalGroup.ethical_approval_id.label('ea_id'),
             # We don't need group_id in output, we just need unique combinations of group+row
            ExperimentalGroup.id.label('group_id'),
            ExperimentDataRow.row_index.label('row_index')
        ).join(DataTable, ExperimentalGroup.id == DataTable.group_id) \
         .join(ExperimentDataRow, DataTable.id == ExperimentDataRow.data_table_id) \
         .filter(ExperimentalGroup.ethical_approval_id.in_(ea_ids)) \
         .distinct().subquery()
        
        # Counting the distinct rows found per EA
        used_counts_query = db.session.query(
            subq.c.ea_id,
            func.count().label('count')
        ).group_by(subq.c.ea_id).all()

        used_counts_map = {r.ea_id: r.count for r in used_counts_query}

        # 3. Get EA Limits for "Available" calculation
        # Fetch only ID and limit
        ea_limits = db.session.query(EthicalApproval.id, EthicalApproval.number_of_animals)\
            .filter(EthicalApproval.id.in_(ea_ids)).all()
        ea_limits_map = {r.id: r.number_of_animals for r in ea_limits}

        results = {}
        for ea_id in ea_ids:
            used = used_counts_map.get(ea_id, 0)
            linked = linked_counts.get(ea_id, 0)
            limit = ea_limits_map.get(ea_id, 0) or 0
            
            results[ea_id] = {
                'linked': linked,
                'used': used,
                'available': max(0, limit - used)
            }

        return jsonify(results)
    except Exception as e:
        current_app.logger.error(f"Error in get_animals_usage_counts: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@ethical_approvals_bp.route("/create", methods=['GET', 'POST'])
@ethical_approvals_bp.route("/<int:ea_id>/edit", methods=['GET', 'POST'])
@login_required
def create_edit_ethical_approval(ea_id=None):
    if ea_id:
        ea = db.session.get(EthicalApproval, ea_id)
        if ea:
            if not user_has_permission(current_user, 'EthicalApproval', 'edit', team_id=ea.team_id):
                flash(_l("You do not have permission to edit this Ethical Approval."), "danger")
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))
    else:
        has_create_permission = user_has_permission(current_user, 'EthicalApproval', 'create', allow_any_team=True)
        
        if not has_create_permission:
            flash(_l("You do not have permission to create Ethical Approvals."), "danger")
            return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    ea = db.session.get(EthicalApproval, ea_id) if ea_id else None
    if ea_id and not ea:
        flash(_l("Ethical Approval not found."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    form = EthicalApprovalForm(obj=ea)

    groups_count = 0
    datatables_count = 0
    if ea:
        groups_count = ea.experimental_groups.count()
        datatables_count = db.session.query(func.count(DataTable.id)).join(ExperimentalGroup).filter(ExperimentalGroup.ethical_approval_id == ea.id).scalar()

    if ea:
        form.team_id.validators = [v for v in form.team_id.validators if not isinstance(v, DataRequired)]

    if request.method == 'POST':
        form_data = request.form.copy()
        if ea and 'team_id' not in form_data:
            form_data['team_id'] = str(ea.team_id)
        
        form = EthicalApprovalForm(form_data)
        if ea:
            form.team_id.validators = [v for v in form.team_id.validators if not isinstance(v, DataRequired)]

        if form.validate_on_submit():
            if not ea:
                target_team_id = form.team_id.data
                if not user_has_permission(current_user, 'EthicalApproval', 'create', team_id=target_team_id):
                     flash(_l("You do not have permission to create Ethical Approvals for the selected team."), "danger")
                     return render_template('ethical_approvals/create_edit_ethical_approval.html',
                                       title=_l("Create Ethical Approval"),
                                       form=form,
                                       ea=ea,
                                       groups_count=0, datatables_count=0)

            is_new_ea = not ea
            if is_new_ea:
                ea = EthicalApproval(team_id=form.team_id.data)
                db.session.add(ea)
            
            ea.reference_number = form.reference_number.data
            ea.apafis_reference = form.apafis_reference.data
            ea.apafis_version = form.apafis_version.data
            ea.title = form.title.data
            ea.start_date = form.start_date.data
            ea.species = form.species.data
            ea.sex_justification = form.sex_justification.data
            ea.number_of_animals = form.number_of_animals.data
            ea.euthanasia_method = form.euthanasia_method.data
            ea.description = form.description.data

            if form.start_date.data:
                ea.end_date = form.start_date.data + relativedelta(
                    years=form.duration_years.data,
                    months=form.duration_months.data
                )
            else:
                flash(_l("Start Date is a required field."), "danger")
                return render_template('ethical_approvals/create_edit_ethical_approval.html',
                                       title=_l("Edit Ethical Approval") if ea else _l("Create Ethical Approval"),
                                       form=form,
                                       ea=ea,
                                       groups_count=groups_count, datatables_count=datatables_count)

            current_shared_teams = {team.id for team in ea.shared_with_teams}
            selected_shared_teams = set(form.shared_with_teams.data)
            
            teams_to_add = selected_shared_teams - current_shared_teams
            teams_to_remove = current_shared_teams - selected_shared_teams

            unshare_validation_errors = []
            if ea:
                for team_id_to_remove in teams_to_remove:
                    validation_result = validate_ea_unshare_from_team(ea.id, team_id_to_remove)
                    if not validation_result['is_valid']:
                        affected_groups_str = ", ".join([f"{g['group_name']} (Owner: {g['owner_name']})" for g in validation_result['affected_groups']])
                        team_obj = db.session.get(Team, team_id_to_remove)
                        team_name = team_obj.name if team_obj else f"ID {team_id_to_remove}"
                        unshare_validation_errors.append(
                            _l("Cannot unshare Ethical Approval from team '%(team_name)s' because it would leave the following groups without an Ethical Approval: %(groups)s",
                               team_name=team_name, groups=affected_groups_str)
                        )
            
            if unshare_validation_errors:
                for error_msg in unshare_validation_errors:
                    flash(error_msg, "danger")
                return render_template('ethical_approvals/create_edit_ethical_approval.html',
                                       title=_l("Edit Ethical Approval") if ea else _l("Create Ethical Approval"),
                                       form=form,
                                       ea=ea,
                                       groups_count=groups_count, datatables_count=datatables_count)

            for team_id in teams_to_add:
                team = db.session.get(Team, team_id)
                if team: ea.shared_with_teams.append(team)
            
            for team_id in teams_to_remove:
                team = db.session.get(Team, team_id)
                if team: ea.shared_with_teams.remove(team)

            for proc in list(ea.procedures):
                db.session.delete(proc)
            
            max_severity_level = 0
            for proc_form in form.procedures.entries:
                new_proc = EthicalApprovalProcedure(
                    name=proc_form.data['name'],
                    severity=Severity[proc_form.data['severity']],
                    description=proc_form.data['description'],
                    pain_management=proc_form.data['pain_management'],
                    is_euthanasia_endpoint=proc_form.data['is_euthanasia_endpoint']
                )
                if new_proc.severity.level > max_severity_level:
                    max_severity_level = new_proc.severity.level
                ea.procedures.append(new_proc)
            
            ea.overall_severity = Severity(next((s for s in Severity if s.level == max_severity_level), Severity.NONE))

            try:
                db.session.commit()
                flash(_l('Ethical Approval saved successfully!'), 'success')
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))
            except IntegrityError as e:
                db.session.rollback()
                if 'UNIQUE constraint failed: ethical_approval.reference_number' in str(e.orig):
                    flash(_l("An ethical approval with this Short Reference Number already exists. Please choose a unique one."), 'danger')
                    form.reference_number.errors.append(_l("This reference number is already in use."))
                else:
                    current_app.logger.error(f"Database integrity error saving ethical approval: {e}", exc_info=True)
                    flash(_l('A database integrity error occurred. Please check your input.'), 'danger')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error saving ethical approval: {e}", exc_info=True)
                flash(_l('An error occurred while saving: %(error)s', error=str(e)), 'danger')
        else:
            flash(_l("Please correct the errors in the form."), "danger")

    elif request.method == 'GET' and ea:
        if ea.start_date and ea.end_date:
            delta = relativedelta(ea.end_date, ea.start_date)
            form.duration_years.data = delta.years
            form.duration_months.data = delta.months
        form.shared_with_teams.data = [team.id for team in ea.shared_with_teams]

        while len(form.procedures.entries) > 0:
            form.procedures.pop_entry()

        for proc in ea.procedures:
            form.procedures.append_entry({
                'name': proc.name,
                'severity': proc.severity.name,
                'description': proc.description,
                'pain_management': proc.pain_management,
                'is_euthanasia_endpoint': proc.is_euthanasia_endpoint
            })
        
        if not ea.procedures.count():
            form.procedures.append_entry()

    return render_template('ethical_approvals/create_edit_ethical_approval.html',
                           title=_l("Edit Ethical Approval") if ea else _l("Create Ethical Approval"),
                           form=form,
                           ea=ea,
                           groups_count=groups_count, datatables_count=datatables_count)


@ethical_approvals_bp.route("/import", methods=['GET', 'POST'])
@login_required
def import_ethical_approval():
    has_create_permission = False
    if user_has_permission(current_user, 'EthicalApproval', 'create'):
            has_create_permission = True
    else:
            for team in current_user.get_teams():
                if user_has_permission(current_user, 'EthicalApproval', 'create', team_id=team.id):
                    has_create_permission = True
                    break
    
    if not has_create_permission:
        flash(_l("You do not have permission to import Ethical Approvals."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    form = XMLImportForm()
    if form.validate_on_submit():
        xml_file = form.xml_file.data
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            def find_text(path):
                node = root.find(path)
                return node.text if node is not None and node.text else None

            form_for_render = EthicalApprovalForm()

            form_for_render.apafis_reference.data = find_text('InformationsGenerales/ReferenceDossier')
            form_for_render.apafis_version.data = find_text('InformationsGenerales/NumVersion')
            form_for_render.title.data = find_text('InformationsGenerales/TitreProjet')
            form_for_render.duration_years.data = int(find_text('InformationsGenerales/DureeProjet/DureeAnnees') or 0)
            form_for_render.duration_months.data = int(find_text('InformationsGenerales/DureeProjet/DureeMois') or 0)
            form_for_render.number_of_animals.data = int(find_text('InformationsAdministrativesEtReglementaires/Animaux/AnimauxUtilises/NombreAnimauxUtilises') or 0)
            form_for_render.euthanasia_method.data = find_text('InformationsAdministrativesEtReglementaires/Projet/MethodeMiseAMort')
            form_for_render.description.data = find_text('InformationsAdministrativesEtReglementaires/Projet/DescriptionProjet2/ObjectifsDuProjet')
            form_for_render.sex_justification.data = find_text('InformationsAdministrativesEtReglementaires/Animaux/SexeAnimauxUtilisesJustification')
            
            species_node = root.find('InformationsAdministrativesEtReglementaires/Animaux/ListeAnimaux')
            if species_node is not None:
                for child in species_node:
                    if child.text == 'true':
                        form_for_render.species.data = child.tag
                        break
            
            while form_for_render.procedures.entries:
                form_for_render.procedures.pop_entry()

            procedures_node = root.find('ProceduresExperimentales/ExplicationsProcedures')
            if procedures_node is not None:
                for proc_node in procedures_node.findall('Procedure'):
                    severity_map = {
                        'Classe légère': 'LIGHT',
                        'Classe modérée': 'MODERATE',
                        'Classe sévère': 'SEVERE',
                        'Classe sans réveil': 'NONE',
                        'Sans réveil': 'NONE'
                    }
                    severity_text = proc_node.findtext('ClassificationProcedure')
                    proc_data = {
                        'name': proc_node.findtext('NomProcedure'),
                        'severity': severity_map.get(severity_text, 'NONE'),
                        'description': proc_node.findtext('DescriptionDetaillee/PertinenceJustification'),
                        'pain_management': proc_node.findtext('DescriptionDetaillee/MethodeSuppressionDouleur'),
                        'is_euthanasia_endpoint': proc_node.findtext('DevenirAnimaux/MiseAMortAnimaux') == 'true'
                    }
                    form_for_render.procedures.append_entry(proc_data)

            flash(_l("Form pre-filled from XML import. Please review, add the short reference number and start date, then save."), "info")
            return render_template('ethical_approvals/create_edit_ethical_approval.html',
                                   title=_l("Create Ethical Approval from Import"),
                                   form=form_for_render,
                                   ea=None)

        except ET.ParseError as e:
            flash(_l("Error parsing XML file: %(error)s", error=str(e)), "danger")
        except Exception as e:
            flash(_l("An unexpected error occurred during import: %(error)s", error=str(e)), "danger")
            current_app.logger.error(f"Error importing EA XML: {e}", exc_info=True)

    return render_template('ethical_approvals/import_ethical_approval.html',
                           title=_l("Import Ethical Approval from XML"),
                           form=form)

@ethical_approvals_bp.route("/<int:ea_id>/delete", methods=['POST'])
@login_required
def delete_ethical_approval(ea_id):
    ea_to_delete = db.session.get(EthicalApproval, ea_id)
    if not ea_to_delete:
        flash(_l("Ethical Approval not found."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    if not user_has_permission(current_user, 'EthicalApproval', 'delete', team_id=ea_to_delete.team_id):
        flash(_l("You do not have permission to delete this Ethical Approval."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    action = request.form.get('delete_action')
    target_ea_id_str = request.form.get('target_ea_id_for_reassign')
    
    linked_groups = list(ea_to_delete.experimental_groups)

    try:
        if action == "reassign_groups" and linked_groups:
            if not target_ea_id_str or not target_ea_id_str.isdigit():
                flash(_l("Invalid target Ethical Approval selected for reassignment."), "danger")
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))
            
            target_ea_id = int(target_ea_id_str)
            if target_ea_id == ea_to_delete.id:
                flash(_l("Cannot reassign groups to the same Ethical Approval being deleted."), "warning")
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))

            target_ea = db.session.get(EthicalApproval, target_ea_id)
            if not target_ea:
                flash(_l("Target Ethical Approval for reassignment not found."), "danger")
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))

            animals_to_reassign_count = sum(len(group.animal_data) for group in linked_groups if group.animal_data and isinstance(group.animal_data, list))
            current_animals_in_target_ea = sum(len(group.animal_data) for group in target_ea.experimental_groups if group.animal_data and isinstance(group.animal_data, list))

            if (current_animals_in_target_ea + animals_to_reassign_count) > target_ea.number_of_animals:
                flash(_l("Reassignment Failed: The target EA '%(target_ref)s' (Max Animals: %(max_animals)s) does not have enough capacity for the %(reassign_animals)s animals being reassigned (Current Animals: %(current_animals)s).",
                        target_ref=target_ea.reference_number,
                        max_animals=target_ea.number_of_animals,
                        reassign_animals=animals_to_reassign_count,
                        current_animals=current_animals_in_target_ea), "danger")
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))

            max_protocol_severity_level = max(
                (proto.severity.level for group in linked_groups for dt in group.data_tables if (proto := dt.protocol) and proto.severity),
                default=Severity.NONE.level
            )
            
            if target_ea.overall_severity.level < max_protocol_severity_level:
                max_prot_sev_enum = next((s for s in Severity if s.level == max_protocol_severity_level), Severity.NONE)
                flash(_l("Reassignment Failed: The target EA '%(target_ref)s' (Severity: %(target_sev)s) does not have a high enough severity for all protocols used (Max Protocol Severity: %(max_prot_sev)s).",
                        target_ref=target_ea.reference_number,
                        target_sev=target_ea.overall_severity.value,
                        max_prot_sev=max_prot_sev_enum.value), "danger")
                return redirect(url_for('ethical_approvals.list_ethical_approvals'))

            for group_to_update in linked_groups:
                group_to_update.ethical_approval_id = target_ea.id
            
            flash_message_reassign = _l("Linked groups reassigned to '%(target_ref)s'.", target_ref=target_ea.reference_number)
            db.session.delete(ea_to_delete)
            db.session.commit()
            flash(flash_message_reassign + " " + _l("Original approval '%(ref)s' deleted successfully.", ref=ea_to_delete.reference_number), "success")

        elif action == "delete_ea_only" or not linked_groups:
            original_ref = ea_to_delete.reference_number
            if linked_groups:
                for group_to_nullify in linked_groups:
                    group_to_nullify.ethical_approval_id = None
                flash_message_delete_only = _l("Ethical Approval '%(ref)s' deleted. Linked groups no longer have an approval assigned.", ref=original_ref)
            else:
                flash_message_delete_only = _l("Ethical Approval '%(ref)s' deleted successfully.", ref=original_ref)
            
            db.session.delete(ea_to_delete)
            db.session.commit()
            flash(flash_message_delete_only, "success" if not linked_groups else "warning")
        
        else:
            flash(_l("Invalid delete action specified."), "danger")
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting/reassigning for Ethical Approval {ea_id}: {e}", exc_info=True)
        flash(_l("An error occurred: %(error)s", error=str(e)), "danger")

    return redirect(url_for('ethical_approvals.list_ethical_approvals'))

@ethical_approvals_bp.route("/<int:ea_id>/get_delete_info", methods=['GET'])
@login_required
def get_ea_delete_info(ea_id):
    ea = db.session.get(EthicalApproval, ea_id)
    if not ea:
        return jsonify({'error': 'Ethical Approval not found'}), 404

    if not user_has_permission(current_user, 'EthicalApproval', 'delete', team_id=ea.team_id):
        return jsonify({'error': 'Permission denied'}), 403

    linked_groups = ea.experimental_groups.all()
    linked_groups_count = len(linked_groups)
    
    max_protocol_severity_level = max(
        (proto.severity.level for group in linked_groups for dt in group.data_tables if (proto := dt.protocol) and proto.severity),
        default=Severity.NONE.level
    )
    max_protocol_severity_name = next((s.name for s in Severity if s.level == max_protocol_severity_level), 'NONE')

    other_eas_for_reassign = []
    if linked_groups_count > 0:
        all_other_eas = EthicalApproval.query.filter(EthicalApproval.id != ea_id).order_by(EthicalApproval.reference_number).all()
        for other_ea in all_other_eas:
            if other_ea.overall_severity.level >= max_protocol_severity_level:
                other_eas_for_reassign.append({
                    'id': other_ea.id, 
                    'text': f"{other_ea.reference_number} - {other_ea.title} (Severity: {other_ea.overall_severity.value})"
                })

    return jsonify({
        'id': ea.id,
        'title': ea.title,
        'reference_number': ea.reference_number,
        'linked_groups_count': linked_groups_count,
        'max_protocol_severity_in_linked_groups': max_protocol_severity_name,
        'other_ethical_approvals_for_reassign': other_eas_for_reassign
    })

@ethical_approvals_bp.route("/<int:ethical_approval_id>/groups", methods=['GET'])
@login_required
def list_groups_for_ethical_approval(ethical_approval_id):
    approval = db.session.get(EthicalApproval, ethical_approval_id)
    if not approval:
        flash(_l("Ethical Approval not found."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))
    
    if not current_user.is_super_admin:
        user_teams = current_user.get_teams()
        if not user_teams:
            return redirect(url_for('main.index'))
        user_team_ids = [team.id for team in user_teams]
        
        is_owner = approval.team_id in user_team_ids
        is_shared = approval.shared_with_teams.filter(Team.id.in_(user_team_ids)).first() is not None
        
        if not (is_owner or is_shared):
            flash(_l("You do not have permission to view this ethical approval's details."), "danger")
            return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    linked_groups = approval.experimental_groups.order_by(ExperimentalGroup.name).all()

    # --- Statistics Calculation ---
    stats = {
        'total_allowed': approval.number_of_animals,
        'total_used': 0,
        'yearly_breakdown': {}
    }

    try:
        # Calculate unique animals used based on their FIRST appearance (earliest DataTable date)
        # 1. Subquery to find the MINIMUM date for each unique animal ID (group_id + row_index)
        # Note: We cast row_index to string to ensure consistent grouping if needed, though usually int is fine.
        
        # We need to find the earliest DataTable date for each (group_id, row_index) pair
        # ONLY for groups linked to this Ethical Approval.
        
        min_date_subq = db.session.query(
            ExperimentalGroup.id.label('group_id'),
            ExperimentDataRow.row_index.label('row_index'),
            func.min(DataTable.date).label('first_use_date')
        ).join(DataTable, ExperimentalGroup.id == DataTable.group_id)\
         .join(ExperimentDataRow, DataTable.id == ExperimentDataRow.data_table_id)\
         .filter(ExperimentalGroup.ethical_approval_id == approval.id)\
         .group_by(ExperimentalGroup.id, ExperimentDataRow.row_index)\
         .subquery()

        # 2. Query to aggregate these minimum dates by Year
        # We extract the year from the 'first_use_date'
        
        # SQLite/MySQL compatible year extraction for grouping
        # For universal compatibility in SQLAlchemy we can use extract('year', ...) if date column is Date type.
        # However, DataTable.date is defined as String(80) in the model... which complicates things.
        # Assuming format is YYYY-MM-DD or similar where first 4 chars are year.
        
        year_expr = func.substr(min_date_subq.c.first_use_date, 1, 4)
        
        yearly_counts = db.session.query(
            year_expr.label('year'),
            func.count().label('count')
        ).group_by(year_expr).all()

        total_unique_used = 0
        for year, count in yearly_counts:
            if year: # Ensure year is not null or empty
                stats['yearly_breakdown'][year] = count
                total_unique_used += count
        
        stats['total_used'] = total_unique_used

    except Exception as e:
        current_app.logger.error(f"Error calculating stats for EA {approval.id}: {e}", exc_info=True)
        flash(_l("Error calculating statistics."), "warning")

    return render_template('ethical_approvals/list_groups_for_approval.html',
                           approval=approval,
                           groups=linked_groups,
                           stats=stats,
                           title=_l("Groups for Approval: %(ref)s", ref=approval.reference_number))

@ethical_approvals_bp.route("/<int:ethical_approval_id>/datatables", methods=['GET'])
@login_required
def list_datatables_for_ethical_approval(ethical_approval_id):
    approval = db.session.get(EthicalApproval, ethical_approval_id)
    if not approval:
        flash(_l("Ethical Approval not found."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    base_datatables_query = DataTable.query.join(ExperimentalGroup).filter(ExperimentalGroup.ethical_approval_id == approval.id)

    year_tuples = base_datatables_query.with_entities(func.strftime('%Y', DataTable.date)).distinct().order_by(func.strftime('%Y', DataTable.date).desc()).all()
    available_years = [year[0] for year in year_tuples if year[0]]

    selected_year = request.args.get('year', None)

    datatables_query = base_datatables_query
    if selected_year:
        datatables_query = datatables_query.filter(func.strftime('%Y', DataTable.date) == selected_year)

    all_related_datatables = datatables_query.options(
        db.joinedload(DataTable.group).joinedload(ExperimentalGroup.project),
        db.joinedload(DataTable.protocol)
    ).order_by(DataTable.date.desc(), DataTable.id.desc()).all()

    accessible_datatables = [dt for dt in all_related_datatables if check_datatable_permission(dt, 'read')]
    
    for dt in accessible_datatables:
        dt.animal_count = len(dt.group.animal_data) if dt.group and dt.group.animal_data else 0

    return render_template('ethical_approvals/list_datatables_for_approval.html',
                           approval=approval,
                           datatables=accessible_datatables,
                           title=_l("DataTables for Approval: %(ref)s", ref=approval.reference_number),
                           available_years=available_years,
                           selected_year=selected_year)

@ethical_approvals_bp.route("/export_statistics", methods=['GET'])
@login_required
def export_statistics():
    if not user_has_permission(current_user, 'EthicalApproval', 'view'):
         if not (user_has_permission(current_user, 'EthicalApproval', 'create') or user_has_permission(current_user, 'EthicalApproval', 'edit')):
            flash(_l("You do not have permission to export statistics."), "danger")
            return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    selected_severities_str = request.args.getlist('severities')

    if not start_date_str or not end_date_str or not selected_severities_str:
        flash(_l("Missing parameters for statistics export."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        selected_severities = [Severity[s] for s in selected_severities_str if s in Severity.__members__]
    except (ValueError, KeyError) as e:
        flash(_l("Invalid date or severity format: %(error)s", error=str(e)), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    if not selected_severities:
        flash(_l("No valid severity levels selected."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    base_ea_query = EthicalApproval.query
    if not current_user.is_super_admin:
        user_team_ids = [team.id for team in current_user.get_teams()]
        if not user_team_ids:
            base_ea_query = base_ea_query.filter(db.false())
        else:
            base_ea_query = base_ea_query.filter(
                db.or_(
                    EthicalApproval.team_id.in_(user_team_ids),
                    EthicalApproval.shared_with_teams.any(Team.id.in_(user_team_ids))
                )
            )
    accessible_ea_ids = [ea.id for ea in base_ea_query.with_entities(EthicalApproval.id).all()]

    output_data = []
    current_app.logger.info(f"Found {len(accessible_ea_ids)} accessible ethical approvals.")
    if accessible_ea_ids:
        raw_data_query = db.session.query(
            ExperimentalGroup.ethical_approval_id,
            ExperimentalGroup.id.label('group_id'),
            ExperimentDataRow.row_index,
            ProtocolModel.severity
        ).select_from(ExperimentalGroup).join(
            DataTable, ExperimentalGroup.id == DataTable.group_id
        ).join(
            ExperimentDataRow, DataTable.id == ExperimentDataRow.data_table_id
        ).join(
            ProtocolModel, DataTable.protocol_id == ProtocolModel.id
        ).filter(
            ExperimentalGroup.ethical_approval_id.in_(accessible_ea_ids),
            DataTable.date >= start_date.strftime('%Y-%m-%d'),
            DataTable.date <= end_date.strftime('%Y-%m-%d'),
            ProtocolModel.severity.in_(selected_severities)
        ).all()
        current_app.logger.info(f"Raw data query returned {len(raw_data_query)} rows.")

        aggregated_data = {}
        for ea_id, group_id, animal_index, severity in raw_data_query:
            key = (ea_id, group_id)
            if key not in aggregated_data:
                aggregated_data[key] = {
                    'animals': set(),
                    'max_severity': Severity.NONE
                }
            
            aggregated_data[key]['animals'].add(animal_index)
            if severity.level > aggregated_data[key]['max_severity'].level:
                aggregated_data[key]['max_severity'] = severity

        if aggregated_data:
            all_group_ids = [key[1] for key in aggregated_data.keys()]
            all_ea_ids = [key[0] for key in aggregated_data.keys()]

            groups_map = {g.id: g for g in ExperimentalGroup.query.filter(ExperimentalGroup.id.in_(all_group_ids)).all()}
            eas_map = {ea.id: ea for ea in EthicalApproval.query.filter(EthicalApproval.id.in_(all_ea_ids)).all()}

            for (ea_id, group_id), data in aggregated_data.items():
                group = groups_map.get(group_id)
                ea = eas_map.get(ea_id)

                if group and ea:
                    valid_animals = set()
                    if group.animal_data and isinstance(group.animal_data, list):
                        group_size = len(group.animal_data)
                        for animal_index in data['animals']:
                            if animal_index < group_size:
                                valid_animals.add(animal_index)
                    
                    if valid_animals:
                        output_data.append({
                            'ea_short_ref': ea.reference_number,
                            'ea_title': ea.title,
                            'group_name': group.name,
                            'nb_animals_with_datatable': len(valid_animals),
                            'highest_severity_in_range': data['max_severity'].value
                        })
            
            output_data.sort(key=lambda x: (x['ea_short_ref'], x['group_name']))
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(_l("Animal Usage Statistics"))

    headers = [
        str(_l('Ethical Approval Short Ref')),
        str(_l('Ethical Approval Title')),
        str(_l('Group Name')),
        str(_l('Number of Animals with DataTable')),
        str(_l('Highest Severity in Range'))
    ]
    ws.append(headers)

    for row_data in output_data:
        ws.append([
            row_data['ea_short_ref'],
            row_data['ea_title'],
            row_data['group_name'],
            row_data['nb_animals_with_datatable'],
            row_data['highest_severity_in_range']
        ])

    excel_file = io.BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    filename = f"animal_usage_statistics_{start_date_str}_to_{end_date_str}.xlsx"
    return send_file(excel_file,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name=filename)

@ethical_approvals_bp.route("/<int:ethical_approval_id>/export_animals", methods=['GET'])
@login_required
def export_animals_for_ethical_approval(ethical_approval_id):
    approval = db.session.get(EthicalApproval, ethical_approval_id)
    if not approval:
        flash(_l("Ethical Approval not found."), "danger")
        return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    if not current_user.is_super_admin:
        user_teams = current_user.get_teams()
        if not user_teams:
            return redirect(url_for('main.index'))
        user_team_ids = [team.id for team in user_teams]

        is_owner = approval.team_id in user_team_ids
        is_shared = approval.shared_with_teams.filter(Team.id.in_(user_team_ids)).first() is not None

        if not (is_owner or is_shared):
            flash(_l("You do not have permission to view this ethical approval's details."), "danger")
            return redirect(url_for('ethical_approvals.list_ethical_approvals'))

    # Collect all groups linked to this EA
    linked_groups = approval.experimental_groups.all()

    export_data = []
    for group in linked_groups:
        if not group.animal_data:
            continue
        for animal in group.animal_data:
            if not isinstance(animal, dict):
                continue

            # Calculate age at death
            age_at_death = None
            birth_date_str = animal.get('Date of Birth')
            death_date_str = animal.get('death_date')
            if birth_date_str and death_date_str:
                try:
                    birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()
                    death_date = datetime.strptime(death_date_str, '%Y-%m-%d').date()
                    age_at_death = (death_date - birth_date).days
                except ValueError:
                    pass

            row = {
                'Group Name': group.name,
                'Animal ID': animal.get('ID', ''),
                'Status': animal.get('status', 'alive'),
                'Date of Birth': animal.get('Date of Birth', ''),
                'Death Date': animal.get('death_date', ''),
                'Age at Death (Days)': age_at_death,
                'Euthanasia Reason': animal.get('euthanasia_reason', ''),
                'Severity': animal.get('severity', '')
            }
            export_data.append(row)

    df = pd.DataFrame(export_data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Animals')

    output.seek(0)

    # Safe filename
    safe_ref = re.sub(r'[^\w\s-]', '', approval.reference_number or 'unknown').strip().replace(' ', '_')
    filename = f"Animals_{safe_ref}_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )