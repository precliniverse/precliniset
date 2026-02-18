# app/workplans/routes.py
import json
import textwrap
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from flask import (current_app, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)
from flask_babel import get_locale
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app import db
from app.forms import WorkplanForm, WorkplanImportForm
from app.helpers import send_email, send_workplan_update_notification
from app.models import (AnimalModel, DataTable, EthicalApproval,
                        ExperimentalGroup, ExperimentDataRow, Project,
                        ProjectTeamShare, ProtocolModel, Severity, Team,
                        TeamMembership, User, Workplan, WorkplanEvent,
                        WorkplanEventStatus, WorkplanStatus, WorkplanVersion)
from app.permissions import check_project_permission
from app.services.ethical_approval_service import (
    get_animals_available_for_ea, get_eligible_ethical_approvals)
from app.services.workplan_service import WorkplanService

from . import workplans_bp

workplan_service = WorkplanService()

@workplans_bp.route('/project/<string:project_slug>/create', methods=['GET', 'POST'])
@login_required
def create_workplan(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l("You do not have permission to create a workplan for this project."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    form = WorkplanForm()
    if form.validate_on_submit():
        try:
            new_workplan = workplan_service.create_workplan(
                project_id=project.id,
                name=form.name.data,
                planned_animal_count=form.planned_animal_count.data
            )
            flash(_l("Workplan '%(name)s' created successfully.", name=new_workplan.name), 'success')
            return redirect(url_for('workplans.edit_workplan', workplan_id=new_workplan.id))
        except Exception as e:
            current_app.logger.error(f"Error creating workplan for project {project.slug}: {e}", exc_info=True)
            flash(_l("An error occurred while creating the workplan."), "danger")

    return render_template('workplans/create_workplan.html', form=form, project=project)

@workplans_bp.route('/<int:workplan_id>', methods=['GET', 'POST'])
@login_required
def edit_workplan(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        flash(_l("Workplan not found."), "danger")
        return redirect(url_for('projects.list_projects'))

    project = workplan.project
    if not check_project_permission(project, 'edit'):
        flash(_l("You do not have permission to manage this workplan."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    if request.method == 'POST': # AJAX Save/Update
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid data'}), 400
        
        # --- Data Comparison for Versioning ---
        # Create a dictionary representing the current state of the workplan
        current_state = {
            'study_start_date': workplan.study_start_date.isoformat() if workplan.study_start_date else None,
            'expected_dob': workplan.expected_dob.isoformat() if workplan.expected_dob else None,
            'notes': workplan.notes or "",
            'planned_animal_count': workplan.planned_animal_count,
            'events': sorted([{
                'offset_days': str(e.offset_days),
                'protocol_id': str(e.protocol_id),
                'event_name': e.event_name or "",
                'assigned_to_id': e.assigned_to_id # Keep as int or None
            } for e in workplan.events.all()], key=lambda x: int(x['offset_days']))
        }

        # Create a dictionary representing the new state from the UI
        new_state = {
            'study_start_date': data.get('study_start_date'),
            'expected_dob': data.get('expected_dob'),
            'notes': data.get('notes') or "",
            'planned_animal_count': int(data.get('planned_animal_count')) if data.get('planned_animal_count') is not None else 0,
            'events': sorted([{
                'offset_days': str(item.get('offset_days')),
                'protocol_id': str(item.get('protocol_id')),
                'event_name': item.get('event_name') or "",
                'assigned_to_id': (lambda x: int(x) if x is not None and x != '' else None)(item.get('assigned_to_id'))
            } for item in data.get('events', [])], key=lambda x: int(x['offset_days']))
        }
        
        if json.dumps(current_state) == json.dumps(new_state):
            return jsonify({'success': True, 'message': _l('No changes detected. Workplan not saved.')})

        try:
            workplan_service.update_workplan(
                workplan, 
                new_state, 
                current_user, 
                change_comment=data.get('change_comment', 'Workplan updated.'),
                notify_team=data.get('notify_team', False)
            )
            return jsonify({'success': True, 'message': _l('Workplan saved successfully.')})
        except Exception as e:
            current_app.logger.error(f"Error saving workplan {workplan_id}: {e}", exc_info=True)
            return jsonify({'success': False, 'message': str(e)}), 500

    # --- GET Request Logic ---
    def get_import_form():
        return WorkplanImportForm()

    generated_datatables = []
    if workplan.status != WorkplanStatus.DRAFT:
        event_ids = [event.id for event in workplan.events]
        if event_ids:
            generated_datatables = DataTable.query.filter(
                DataTable.workplan_event_id.in_(event_ids)
            ).options(
                joinedload(DataTable.protocol)
            ).order_by(DataTable.date).all()

    protocols = ProtocolModel.query.order_by(ProtocolModel.name).all()
    
    assignable_users = {} 
    if project.team:
        for membership in project.team.memberships:
            if membership.user:
                assignable_users[membership.user.id] = membership.user

    shared_permissions = ProjectTeamShare.query.filter(
        ProjectTeamShare.project_id == project.id,
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
    assignable_users_json = json.dumps([{'id': u.id, 'email': u.email} for u in sorted_users])

    animal_models = AnimalModel.query.order_by(AnimalModel.name).all()
    animal_models_json = json.dumps([{'id': m.id, 'name': m.name} for m in animal_models])

    events_data = [{
        'offset_days': event.offset_days,
        'protocol_id': event.protocol_id,
        'event_name': event.event_name or "",
        'assigned_to_id': event.assigned_to_id
    } for event in workplan.events.order_by(WorkplanEvent.offset_days).all()]

    total_animals_in_group = 0
    alive_animals_in_group = 0
    group_datatable_count = 0
    if workplan.generated_group:
        animals = workplan.generated_group.animals
        total_animals_in_group = len(animals)
        # Count alive animals
        alive_animals_in_group = sum(1 for a in animals if a.status != 'dead')
        group_datatable_count = workplan.generated_group.data_tables.count()

    return render_template(
        'workplans/edit_workplan.html',
        project=project,
        workplan=workplan,
        events_json=json.dumps(events_data),
        protocols_json=json.dumps([{'id': p.id, 'name': p.name} for p in protocols]),
        team_members_json=assignable_users_json,
        animal_models_json=animal_models_json,
        assignable_users=sorted_users,
        get_import_form=get_import_form,
        WorkplanStatus=WorkplanStatus,
        generated_datatables=generated_datatables,
        total_animals_in_group=total_animals_in_group,
        alive_animals_in_group=alive_animals_in_group,
        group_datatable_count=group_datatable_count,
        current_locale=str(get_locale())
    )

@workplans_bp.route('/<int:workplan_id>/export.xlsx')
@login_required
def export_workplan(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        flash(_l("Workplan not found."), "danger")
        return redirect(request.referrer or url_for('projects.list_projects'))
    if not check_project_permission(workplan.project, 'read'):
        flash(_l("Permission denied."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=workplan.project.slug))

    events = workplan.events.order_by(WorkplanEvent.offset_days).all()
    
    events_data = []
    for event in events:
        event_dict = {
            'ProtocolName': event.protocol.name,
            'DayOffset': event.offset_days,
            'EventName': event.event_name,
            'AssignedToEmail': event.assignee.email if event.assignee else ''
        }
        events_data.append(event_dict)
    df_events = pd.DataFrame(events_data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        bold_format = workbook.add_format({'bold': True})
        
        current_locale = str(get_locale())
        
        if current_locale.startswith('fr'):
            date_num_format = 'ddd - dd/mm/yy'
        else:
            date_num_format = 'ddd. - yyyy/mm/dd'

        date_format = workbook.add_format({'num_format': date_num_format})
        
        worksheet = workbook.add_worksheet('Workplan')
        writer.sheets['Workplan'] = worksheet

        start_date_cell = 'B5'
        dob_cell = 'B6'
        data_start_row = 9

        metadata = [
            (_l("Workplan Name"), workplan.name),
            (_l("Animal Model"), workplan.animal_model.name if workplan.animal_model else _l("Not Set")),
            (_l("Project"), workplan.project.name),
            (_l("Planned Animal Count"), workplan.planned_animal_count)
        ]
        for i, (key, value) in enumerate(metadata):
            worksheet.write(i, 0, str(key), bold_format)
            worksheet.write(i, 1, str(value))
        
        worksheet.write('A5', str(_l("Study Start Date")), bold_format)
        if workplan.study_start_date:
            worksheet.write_datetime(start_date_cell, workplan.study_start_date, date_format)
        
        worksheet.write('A6', str(_l("Expected data of birth")), bold_format)
        if workplan.expected_dob:
            worksheet.write_datetime(dob_cell, workplan.expected_dob, date_format)

        if not df_events.empty:
            projected_date_formulas = []
            for i in range(len(df_events)):
                current_row_num = data_start_row + i
                projected_date_formulas.append(f'=IF(ISNUMBER({start_date_cell}), {start_date_cell}+C{current_row_num}, "")')
            
            df_events.insert(2, 'Projected Date', projected_date_formulas)

            projected_date_col_letter = 'D'
            age_formulas = []
            for i in range(len(df_events)):
                current_row_num = data_start_row + i
                formula = (
                    f'=IF(AND(ISNUMBER({projected_date_col_letter}{current_row_num}), ISNUMBER({dob_cell})), '
                    f'INT(ROUND(({projected_date_col_letter}{current_row_num}-{dob_cell})/7, 0)) & "w (" & '
                    f'ROUND({projected_date_col_letter}{current_row_num}-{dob_cell}, 0) & "d)", '
                    f'""'
                    f')'
                )
                age_formulas.append(formula)
            
            df_events.insert(0, 'Age in wks (days)', age_formulas)

        df_events.to_excel(writer, sheet_name='Workplan', startrow=data_start_row - 2, index=False)

        if not df_events.empty:
            projected_date_col_index = df_events.columns.get_loc('Projected Date')
            worksheet.set_column(projected_date_col_index, projected_date_col_index, 12, date_format)

        all_protocols = ProtocolModel.query.order_by(ProtocolModel.name).all()
        df_protocols = pd.DataFrame([{'ProtocolName': p.name} for p in all_protocols])

        team_members = workplan.project.team.memberships
        df_users = pd.DataFrame([{'UserEmail': m.user.email} for m in team_members])

        df_protocols.to_excel(writer, sheet_name='Available_Protocols', index=False)
        df_users.to_excel(writer, sheet_name='Available_Users', index=False)
        
        max_row = data_start_row + len(df_events) + 100
        header_row_list = df_events.columns.tolist()
        
        try:
            protocol_col_letter = chr(ord('A') + header_row_list.index('ProtocolName'))
            protocol_count = len(df_protocols)
            if protocol_count > 0:
                worksheet.data_validation(f'{protocol_col_letter}{data_start_row}:{protocol_col_letter}{max_row}', {
                    'validate': 'list',
                    'source': f"=Available_Protocols!$A$2:$A${protocol_count + 1}"
                })
        except ValueError: pass

        try:
            assignee_col_letter = chr(ord('A') + header_row_list.index('AssignedToEmail'))
            user_count = len(df_users)
            if user_count > 0:
                worksheet.data_validation(f'{assignee_col_letter}{data_start_row}:{assignee_col_letter}{max_row}', {
                    'validate': 'list',
                    'source': f"=Available_Users!$A$2:$A${user_count + 1}"
                })
        except ValueError: pass
        
        for i, col in enumerate(df_events.columns):
            if col == 'Projected Date':
                continue
            column_len = max(df_events[col].astype(str).map(len).max(), len(col))
            worksheet.set_column(i, i, column_len + 2)

    output.seek(0)
    
    filename = f"workplan_{workplan.project.slug}_{workplan.name.replace(' ', '_')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@workplans_bp.route('/<int:workplan_id>/finalize_info', methods=['GET'])
@login_required
def get_finalize_info(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan or not check_project_permission(workplan.project, 'read'):
        return jsonify({'error': 'Not found or permission denied'}), 404

    if not workplan.study_start_date or not workplan.expected_dob:
        return jsonify({'error': 'Start date and DOB must be set.'}), 400

    min_offset = db.session.query(func.min(WorkplanEvent.offset_days)).filter_by(workplan_id=workplan.id).scalar() or 0
    max_offset = db.session.query(func.max(WorkplanEvent.offset_days)).filter_by(workplan_id=workplan.id).scalar() or 0
    first_event_date = workplan.study_start_date + timedelta(days=min_offset)
    last_event_date = workplan.study_start_date + timedelta(days=max_offset)

    # Calculate max severity from all protocols in the workplan
    protocols = ProtocolModel.query.join(WorkplanEvent).filter(WorkplanEvent.workplan_id == workplan.id).all()
    max_severity = Severity.NONE
    for p in protocols:
        if p.severity and p.severity.level > max_severity.level:
            max_severity = p.severity

    # EAs directly linked to the project (always shown, regardless of other criteria)
    project_linked_eas = list(workplan.project.ethical_approvals.all())
    project_linked_ea_ids = {ea.id for ea in project_linked_eas}

    # EAs eligible via team ownership/sharing
    team_id = workplan.project.team_id if workplan.project.team_id else -1
    eligible_eas_from_service = get_eligible_ethical_approvals(workplan.project_id, team_id)

    # Merge: project-linked EAs first, then team EAs not already included
    all_eas_to_evaluate = list(project_linked_eas)
    seen_ids = set(project_linked_ea_ids)
    for ea in eligible_eas_from_service:
        if ea.id not in seen_ids:
            all_eas_to_evaluate.append(ea)
            seen_ids.add(ea.id)

    valid_eas = []
    for ea in all_eas_to_evaluate:
        animals_available_for_ea = get_animals_available_for_ea(ea)
        is_project_linked = ea.id in project_linked_ea_ids

        # Check each criterion
        date_ok = (ea.start_date <= first_event_date and ea.end_date >= last_event_date)
        severity_ok = (ea.overall_severity is None or ea.overall_severity.level >= max_severity.level)
        capacity_ok = (workplan.planned_animal_count is None or workplan.planned_animal_count == 0 or
                       workplan.planned_animal_count <= animals_available_for_ea)

        # Build warning suffix for EAs that don't meet criteria
        warnings = []
        if not date_ok:
            warnings.append(_l("date range mismatch"))
        if not severity_ok:
            warnings.append(_l("severity too low"))
        if not capacity_ok:
            warnings.append(_l("insufficient animal quota"))

        # EAs linked to the project are ALWAYS shown (with warnings if needed).
        # Non-project-linked EAs are excluded only if ALL criteria fail simultaneously.
        if not is_project_linked and not date_ok and not severity_ok and not capacity_ok:
            continue

        warning_suffix = f" ⚠ {', '.join(str(w) for w in warnings)}" if warnings else ""

        valid_eas.append({
            'id': ea.id,
            'text': f"{ea.reference_number} - {ea.title} ({ea.owner_team.name}) [Available: {animals_available_for_ea}]{warning_suffix}"
        })

    existing_groups = ExperimentalGroup.query.filter(
        ExperimentalGroup.project_id == workplan.project_id,
        ExperimentalGroup.created_from_workplan_id.is_(None),
        ExperimentalGroup.is_archived == False
    ).order_by(ExperimentalGroup.name).all()

    existing_groups_data = [{'id': g.id, 'name': g.name} for g in existing_groups]

    return jsonify({
        'valid_eas': valid_eas,
        'event_count': workplan.events.count(),
        'max_severity': max_severity.value,
        'existing_groups': existing_groups_data
    })


@workplans_bp.route('/<int:workplan_id>/finalize', methods=['POST'])
@login_required
def finalize_workplan(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan or not check_project_permission(workplan.project, 'edit'):
        return jsonify({'success': False, 'message': 'Not found or permission denied'}), 404
    
    data = request.get_json()
    group_name = data.get('group_name')
    group_id = data.get('group_id')
    ea_id = data.get('ea_id')
    notify_team = data.get('notify_team', False)
    animal_model_id = data.get('animal_model_id')

    if not ea_id or (not group_name and not group_id):
        return jsonify({'success': False, 'message': 'Group name or ID, and Ethical Approval are required.'}), 400

    try:
        target_group = workplan_service.finalize_workplan(
            workplan, current_user, ea_id, 
            group_name=group_name, 
            group_id=group_id, 
            animal_model_id=animal_model_id,
            notify_team=notify_team
        )
        flash(_l("Successfully planned study! You are now on the group's page to add animal details."), 'success')
        return jsonify({'success': True, 'redirect_url': url_for('groups.edit_group', id=target_group.id)})

    except Exception as e:
        current_app.logger.error(f"Error finalizing workplan {workplan_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@workplans_bp.route('/<int:workplan_id>/import', methods=['POST'])
@login_required
def import_workplan(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        flash(_l("Workplan not found."), "danger")
        return redirect(url_for('projects.list_projects'))
    if not check_project_permission(workplan.project, 'edit'):
        flash(_l("Permission denied."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=workplan.project.slug))

    form = WorkplanImportForm()
    if form.validate_on_submit():
        file = form.xlsx_file.data
        try:
            # Read metadata from the top of the sheet
            df_meta = pd.read_excel(file, sheet_name='Workplan', header=None, nrows=6, index_col=0).to_dict('index')
            
            # Find the header row for the events table
            df_full = pd.read_excel(file, sheet_name='Workplan', header=None)
            header_row_index = -1
            for i, row in df_full.iterrows():
                if 'DayOffset' in row.values:
                    header_row_index = i
                    break
            
            if header_row_index == -1:
                flash(_l("Import failed. Could not find the 'DayOffset' header in the 'Workplan' sheet."), "danger")
                return redirect(url_for('workplans.edit_workplan', workplan_id=workplan_id))

            # Read the events table starting from the header row
            df_events = pd.read_excel(file, sheet_name='Workplan', header=header_row_index)

            # --- Validation ---
            protocols_map = {p.name: p.id for p in ProtocolModel.query.all()}
            users_map = {m.user.email: m.user.id for m in workplan.project.team.memberships}
            
            new_events_data = []
            errors = []
            has_assignee_col = 'AssignedToEmail' in df_events.columns

            for index, row in df_events.iterrows():
                protocol_name = row.get('ProtocolName')
                if pd.isna(protocol_name) or not str(protocol_name).strip() or str(protocol_name).strip() not in protocols_map:
                    errors.append(f"Row {header_row_index + index + 2}: Protocol '{protocol_name}' is missing or not found.")
                    continue

                user_id = None
                if has_assignee_col:
                    email_val = row.get('AssignedToEmail')
                    if pd.notna(email_val) and str(email_val).strip():
                        email_str = str(email_val).strip()
                        if email_str in users_map:
                            user_id = users_map[email_str]
                        else:
                            errors.append(f"Row {header_row_index + index + 2}: User email '{email_str}' not found in project team.")
                            continue
                
                new_events_data.append({
                    'offset_days': int(row['DayOffset']),
                    'protocol_id': protocols_map[str(protocol_name).strip()],
                    'event_name': str(row.get('EventName', '')).strip() if pd.notna(row.get('EventName')) else "",
                    'assigned_to_id': user_id
                })

            if errors:
                for error in errors: flash(error, 'danger')
                return redirect(url_for('workplans.edit_workplan', workplan_id=workplan_id))

            # --- Update Workplan from Metadata ---
            start_date_val = df_meta.get(str(_l("Study Start Date")), {}).get(1)
            dob_val = df_meta.get(str(_l("Expected data of birth")), {}).get(1)
            
            study_start_date = pd.to_datetime(start_date_val).date() if pd.notna(start_date_val) and start_date_val != 'Not Set' else None
            expected_dob = pd.to_datetime(dob_val).date() if pd.notna(dob_val) and dob_val != 'Not Set' else None

            change_comment = request.form.get('change_comment', str(_l("Workplan updated via Excel import.")))
            notify_team = request.form.get('notify_team') == 'on'
            
            # Use Service to update
            new_state = {
                'study_start_date': study_start_date,
                'expected_dob': expected_dob,
                'notes': workplan.notes, # Keep existing notes
                'planned_animal_count': workplan.planned_animal_count, # Keep existing count
                'events': new_events_data
            }
            
            workplan_service.update_workplan(workplan, new_state, current_user, change_comment, notify_team)

            flash(_l("Workplan successfully imported and a new version has been created."), "success")

        except Exception as e:
            db.session.rollback()
            flash(_l("An error occurred during import: %(error)s", error=str(e)), "danger")
            current_app.logger.error(f"Error importing workplan {workplan_id}: {e}", exc_info=True)
    
    return redirect(url_for('workplans.edit_workplan', workplan_id=workplan_id))

@workplans_bp.route('/events/<int:event_id>/move', methods=['POST'])
@login_required
def move_workplan_event(event_id):
    event = db.session.get(WorkplanEvent, event_id)
    if not event:
        return jsonify({'success': False, 'message': 'Event not found'}), 404

    workplan = event.workplan
    if not check_project_permission(workplan.project, 'edit'):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()
    delta_days = data.get('delta_days')
    change_comment = data.get('change_comment')
    notify_team = data.get('notify_team', False)

    if delta_days is None:
        return jsonify({'success': False, 'message': 'delta_days is required'}), 400

    try:
        workplan_service.move_event(event, delta_days, current_user, change_comment, notify_team)
        return jsonify({'success': True, 'message': 'Event moved and new version created.'})

    except Exception as e:
        current_app.logger.error(f"Error moving workplan event {event_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@workplans_bp.route('/<int:workplan_id>/bulk_assign', methods=['POST'])
@login_required
def bulk_assign_events(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan or not check_project_permission(workplan.project, 'edit'):
        return jsonify({'success': False, 'message': _l('Workplan not found or permission denied.')}), 404

    if workplan.status != WorkplanStatus.DRAFT:
        return jsonify({'success': False, 'message': _l('Events can only be bulk assigned in a draft workplan.')}), 400

    data = request.get_json()
    protocol_ids = data.get('protocol_ids', []) 
    assigned_to_id = data.get('assigned_to_id') 
    change_comment = data.get('change_comment', _l("Bulk assigned events."))
    notify_team = data.get('notify_team', False)

    try:
        if assigned_to_id == '':
            assigned_to_id = None
        elif assigned_to_id is not None:
            assigned_to_id = int(assigned_to_id)

        # Fetch events to be updated
        query = WorkplanEvent.query.filter_by(workplan_id=workplan.id)
        if protocol_ids:
            int_protocol_ids = [int(pid) for pid in protocol_ids if pid]
            query = query.filter(WorkplanEvent.protocol_id.in_(int_protocol_ids))
        
        events_to_update = query.all()
        
        if not events_to_update:
            return jsonify({'success': False, 'message': _l('No events found matching the criteria to assign.')}), 400

        # Prepare new state for service update
        # We need to get ALL events, modify the target ones, and pass the whole list to update_workplan
        # Actually, update_workplan expects a full state replacement.
        # It might be cleaner to implement a specific bulk_assign method in the service, 
        # but update_workplan is robust. Let's construct the new state.
        
        all_events = workplan.events.all()
        new_events_data = []
        for event in all_events:
            # Check if this event is in the list to update
            new_assignee = event.assigned_to_id
            if event in events_to_update:
                new_assignee = assigned_to_id
            
            new_events_data.append({
                'offset_days': event.offset_days,
                'protocol_id': event.protocol_id,
                'event_name': event.event_name,
                'assigned_to_id': new_assignee
            })
            
        new_state = {
            'study_start_date': workplan.study_start_date,
            'expected_dob': workplan.expected_dob,
            'notes': workplan.notes,
            'planned_animal_count': workplan.planned_animal_count,
            'events': new_events_data
        }

        workplan_service.update_workplan(workplan, new_state, current_user, change_comment, notify_team)

        return jsonify({'success': True, 'message': _l('Events bulk assigned successfully.')})

    except Exception as e:
        current_app.logger.error(f"Error bulk assigning events for workplan {workplan_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@workplans_bp.route('/<int:workplan_id>/history', methods=['GET'])
@login_required
def workplan_history(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        return jsonify({'error': 'Workplan not found'}), 404
    if not check_project_permission(workplan.project, 'read'):
        return jsonify({'error': 'Permission denied'}), 403

    versions = workplan.versions.order_by(WorkplanVersion.version_number.desc()).all()
    
    history_data = [{
        'id': v.id, 
        'version_number': v.version_number,
        'created_at': v.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'created_by': v.creator.email,
        'change_comment': v.change_comment,
        'snapshot': v.snapshot
    } for v in versions]

    return jsonify(history_data)

@workplans_bp.route('/<int:workplan_id>/restore_version', methods=['POST'])
@login_required
def restore_workplan_version(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        return jsonify({'success': False, 'message': 'Workplan not found'}), 404
    if not check_project_permission(workplan.project, 'edit'):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()
    version_id_to_restore = data.get('version_id')
    change_comment = data.get('change_comment')
    notify_team = data.get('notify_team', False)

    try:
        workplan_service.restore_version(workplan, version_id_to_restore, current_user, change_comment, notify_team)
        flash(_l('Workplan successfully restored.'), 'success')
        return jsonify({'success': True})

    except Exception as e:
        current_app.logger.error(f"Error restoring workplan version for workplan {workplan_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@workplans_bp.route('/<int:workplan_id>/clear_events', methods=['POST'])
@login_required
def clear_workplan_events(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        return jsonify({'success': False, 'message': 'Workplan not found'}), 404
    if not check_project_permission(workplan.project, 'edit'):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    if workplan.status != WorkplanStatus.DRAFT:
        return jsonify({'success': False, 'message': 'Cannot clear events from a non-draft workplan.'}), 400

    data = request.get_json()
    change_comment = data.get('change_comment', _l("All events cleared from workplan."))
    notify_team = data.get('notify_team', False)

    try:
        # Use update_workplan with empty events list
        new_state = {
            'study_start_date': workplan.study_start_date,
            'expected_dob': workplan.expected_dob,
            'notes': workplan.notes,
            'planned_animal_count': workplan.planned_animal_count,
            'events': []
        }
        workplan_service.update_workplan(workplan, new_state, current_user, change_comment, notify_team)

        return jsonify({'success': True, 'message': _l('All events cleared successfully.')})

    except Exception as e:
        current_app.logger.error(f"Error clearing events for workplan {workplan_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@workplans_bp.route('/<int:workplan_id>/clone', methods=['POST'])
@login_required
def clone_workplan(workplan_id):
    original_wp = db.session.get(Workplan, workplan_id)
    if not original_wp or not check_project_permission(original_wp.project, 'edit'):
        flash(_l("Workplan not found or permission denied."), "danger")
        return redirect(request.referrer or url_for('projects.list_projects'))

    try:
        new_wp = workplan_service.create_workplan(
            project_id=original_wp.project_id,
            name=f"{original_wp.name} (Copy)",
            planned_animal_count=original_wp.planned_animal_count
        )
        
        # Copy details
        new_wp.animal_model_id = original_wp.animal_model_id
        new_wp.notes = original_wp.notes
        
        # Copy events
        events_to_copy = original_wp.events.order_by(WorkplanEvent.offset_days).all()
        for event in events_to_copy:
            new_event = WorkplanEvent(
                workplan_id=new_wp.id,
                protocol_id=event.protocol_id,
                assigned_to_id=event.assigned_to_id,
                offset_days=event.offset_days,
                event_name=event.event_name,
                status=WorkplanEventStatus.PLANNED
            )
            db.session.add(new_event)
        
        db.session.commit()
        flash(_l("Workplan cloned successfully. You are now editing the new copy."), "success")
        return redirect(url_for('workplans.edit_workplan', workplan_id=new_wp.id))
    except Exception as e:
        db.session.rollback()
        flash(_l("Error cloning workplan: %(error)s", error=str(e)), "danger")
        return redirect(url_for('workplans.edit_workplan', workplan_id=original_wp.id))


@workplans_bp.route('/<int:workplan_id>/delete', methods=['POST'])
@login_required
def delete_workplan(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan:
        flash(_l("Workplan not found."), "danger")
        return redirect(url_for('projects.list_projects'))

    project = workplan.project
    if not check_project_permission(project, 'edit'):
        flash(_l("You do not have permission to delete this workplan."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    linked_group = ExperimentalGroup.query.filter_by(created_from_workplan_id=workplan.id).first()
    if linked_group:
        flash(_l("Cannot delete this workplan because it has already been used to generate an experimental group ('%(group_name)s'). Please delete the group first.", group_name=linked_group.name), 'danger')
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    try:
        workplan_service.delete(workplan)
        flash(_l("Workplan '%(name)s' deleted successfully.", name=workplan.name), 'success')
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))
    except Exception as e:
        current_app.logger.error(f"Error deleting workplan {workplan_id}: {e}", exc_info=True)
        flash(_l("An error occurred while deleting the workplan."), "danger")
        return redirect(url_for('workplans.edit_workplan', workplan_id=workplan_id))


@workplans_bp.route('/<int:workplan_id>/delete-info', methods=['GET'])
@login_required
def get_workplan_delete_info(workplan_id):
    workplan = db.session.get(Workplan, workplan_id)
    if not workplan or not check_project_permission(workplan.project, 'read'):
        return jsonify({'error': 'Not found or permission denied'}), 404

    linked_group = ExperimentalGroup.query.filter_by(created_from_workplan_id=workplan.id).first()

    if not linked_group:
        return jsonify({'can_delete': True})

    datatables = DataTable.query.filter_by(group_id=linked_group.id).order_by(DataTable.date).all()
    
    response_data = {
        'can_delete': False,
        'group': {
            'name': linked_group.name,
            'url': url_for('groups.edit_group', id=linked_group.id)
        },
        'datatables': [{
            'protocol_name': dt.protocol.name,
            'date': dt.date,
            'url': url_for('datatables.view_data_table', datatable_id=dt.id)
        } for dt in datatables]
    }
    return jsonify(response_data)