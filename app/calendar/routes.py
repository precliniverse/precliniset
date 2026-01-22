# app/calendar/routes.py
import textwrap
from collections import defaultdict
from datetime import datetime, timedelta

from flask import (Response, current_app, jsonify, render_template, request,
                   url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, subqueryload

from app import db
from app.models import (DataTable, EthicalApproval, ExperimentalGroup, Project,
                        ProjectSharedTeamPermission, ProtocolModel, Severity,
                        User, Workplan, WorkplanEvent, WorkplanStatus,
                        WorkplanVersion)
from app.permissions import check_project_permission
from app.services.tm_connector import TrainingManagerConnector

from . import calendar_bp


def fold_line(line):
    """Folds a long iCalendar line into multiple lines of max 75 chars."""
    return textwrap.fill(line, width=75, subsequent_indent=' ', break_long_words=False, break_on_hyphens=False)

@calendar_bp.route('/')
@login_required
def view_calendar():
    """Renders the main calendar page."""
    return render_template('calendar/calendar.html', title=_l("Experimental Calendar"))

@calendar_bp.route('/events.json')
@login_required
def events_json():
    """Provides the JSON feed for the calendar."""
    
    assigned_to_ids_str = request.args.get('assigned_to_ids')
    include_unassigned = request.args.get('include_unassigned', 'false').lower() == 'true'

    assigned_to_ids = []
    if assigned_to_ids_str:
        try:
            assigned_to_ids = [int(x) for x in assigned_to_ids_str.split(',') if x.strip()]
        except ValueError:
            current_app.logger.warning(f"Invalid assigned_to_ids parameter: {assigned_to_ids_str}")
            return jsonify([]) # Or handle error as appropriate

    # --- Base Query for Accessible Projects ---
    accessible_projects = current_user.get_accessible_projects(include_archived=False)
    accessible_project_ids = [p.id for p in accessible_projects]
    if not accessible_project_ids:
        return jsonify([])

    calendar_events = []

    # --- Query 1: Get events from Workplans ---
    workplan_event_filter = []
    if assigned_to_ids:
        workplan_event_filter.append(WorkplanEvent.assigned_to_id.in_(assigned_to_ids))
    if include_unassigned:
        workplan_event_filter.append(WorkplanEvent.assigned_to_id.is_(None))
    
    # If no specific assigned_to_ids and not including unassigned, default to current user
    if not assigned_to_ids and not include_unassigned:
        workplan_event_filter.append(WorkplanEvent.assigned_to_id == current_user.id)
    
    # If filters are empty (e.g., assigned_to_ids is empty and include_unassigned is false, and current_user.id is not added),
    # then no events should be returned.
    if not workplan_event_filter:
        workplan_query = Workplan.query.filter(db.false()) # Return no workplans
    else:
        workplan_query = Workplan.query.filter(
            Workplan.project_id.in_(accessible_project_ids),
            Workplan.study_start_date.isnot(None),
            Workplan.status.in_([WorkplanStatus.DRAFT, WorkplanStatus.PLANNED, WorkplanStatus.RUNNING, WorkplanStatus.COMPLETED])
        ).join(WorkplanEvent).filter(db.or_(*workplan_event_filter))
        
    workplans = workplan_query.options(
        joinedload(Workplan.project),
        joinedload(Workplan.generated_group)
    ).all()

    for wp in workplans:
        # Filter events within the workplan based on the same criteria
        events_for_workplan_query = wp.events.options(
            joinedload(WorkplanEvent.protocol),
            joinedload(WorkplanEvent.assignee)
        )
        if workplan_event_filter:
            events_for_workplan_query = events_for_workplan_query.filter(db.or_(*workplan_event_filter))
        
        events_for_workplan = events_for_workplan_query.all()

        for event in events_for_workplan:
            event_date = wp.study_start_date + timedelta(days=event.offset_days)
            week_number = event_date.isocalendar()[1]
            
            color = '#0d6efd'
            if wp.status == WorkplanStatus.PLANNED: color = '#0dcaf0'
            elif wp.status == WorkplanStatus.RUNNING: color = '#0d6efd'
            elif wp.status == WorkplanStatus.COMPLETED: color = '#198754'
            elif wp.status == WorkplanStatus.DRAFT: color = '#6c757d'

            # Collect datatable URLs for this event
            datatable_urls = []
            for dt in event.generated_datatables:
                datatable_urls.append(url_for('datatables.view_data_table', datatable_id=dt.id))

            # Determine the primary URL for the event click
            primary_url = url_for('workplans.edit_workplan', workplan_id=wp.id)
            if datatable_urls:
                primary_url = datatable_urls[0] # Use the first datatable URL if available

            calendar_events.append({
                'id': event.id,
                'title': f"{wp.project.slug}: {event.protocol.name}",
                'start': event_date.isoformat(),
                'allDay': True,
                'extendedProps': {
                    'workplan_name': wp.name,
                    'group_name': wp.generated_group.name if wp.generated_group else _l('Group not yet generated'),
                    'project_name': wp.project.name,
                    'event_name': event.event_name or '',
                    'status': wp.status.value,
                    'assignee': event.assignee.email if event.assignee else _l('Unassigned'),
                    'week_number': week_number,
                    'expected_dob': wp.expected_dob.isoformat() if wp.expected_dob else None,
                    'datatable_urls': datatable_urls if datatable_urls else None # Add datatable URLs
                },
                'url': primary_url, # Use the determined primary URL
                'backgroundColor': color,
                'borderColor': color,
                'classNames': ['unassigned-event'] if not event.assignee else [] # Add class for unassigned
            })

    # --- Query 2: Get events from standalone DataTables ---
    datatable_filter = []
    if assigned_to_ids:
        datatable_filter.append(DataTable.assigned_to_id.in_(assigned_to_ids))
    if include_unassigned:
        datatable_filter.append(DataTable.assigned_to_id.is_(None))

    # If no specific assigned_to_ids and not including unassigned, default to current user
    if not assigned_to_ids and not include_unassigned:
        datatable_filter.append(DataTable.assigned_to_id == current_user.id)

    if not datatable_filter:
        standalone_datatables_query = DataTable.query.filter(db.false()) # Return no datatables
    else:
        standalone_datatables_query = DataTable.query.join(ExperimentalGroup).filter(
            ExperimentalGroup.project_id.in_(accessible_project_ids),
            DataTable.workplan_event_id.is_(None)
        ).filter(db.or_(*datatable_filter))

    standalone_datatables = standalone_datatables_query.options(
        joinedload(DataTable.group).joinedload(ExperimentalGroup.project),
        joinedload(DataTable.protocol),
        joinedload(DataTable.assignee)
    ).all()

    for dt in standalone_datatables:
        try:
            event_date = datetime.strptime(dt.date, '%Y-%m-%d').date()
            week_number = event_date.isocalendar()[1]
            
            calendar_events.append({
                'id': f"dt-{dt.id}",
                'title': f"{dt.group.project.slug}: {dt.protocol.name}",
                'start': dt.date,
                'allDay': True,
                'extendedProps': {
                    'workplan_name': _l('Ad-hoc Entry'),
                    'group_name': dt.group.name,
                    'project_name': dt.group.project.name,
                    'event_name': _l('Data Collection'),
                    'status': 'Ad-hoc',
                    'assignee': dt.assignee.email if dt.assignee else _l('Unassigned'),
                    'week_number': week_number,
                    'expected_dob': dt.group.created_from_workplan.expected_dob.isoformat() if dt.group.created_from_workplan and dt.group.created_from_workplan.expected_dob else None
                },
                'url': url_for('datatables.view_data_table', datatable_id=dt.id),
                'backgroundColor': '#ffc107',
                'borderColor': '#ffc107',
                'classNames': ['unassigned-event'] if not dt.assignee else [] # Add class for unassigned
            })
        except (ValueError, TypeError) as e:
            current_app.logger.warning(f"Could not parse date for standalone DataTable ID {dt.id}: {dt.date}. Error: {e}")

    return jsonify(calendar_events)

def generate_ics_feed(user, events, cal_name, cal_desc):
    """Helper function to generate the .ics file content with maximum compatibility."""
    current_app.logger.info(f"Generating ICS feed '{cal_name}' for user '{user.email}'. Found {len(events)} events.")
    
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//Precliniset//NONSGML v1.0//EN",
        fold_line(f"X-WR-CALNAME:{cal_name}"),
        fold_line(f"X-WR-CALDESC:{cal_desc}"),
    ]

    for event_item in events:
        if isinstance(event_item, WorkplanEvent):
            wp = event_item.workplan
            event = event_item
            if not wp.study_start_date: continue
            start_date = wp.study_start_date + timedelta(days=event.offset_days)
            summary = f"[{wp.project.slug}] {event.protocol.name}"
            if event.event_name:
                summary += f" ({event.event_name})"
            assignee_str = event.assignee.email if event.assignee else 'Unassigned'
            project_url = url_for('projects.view_edit_project', project_slug=wp.project.slug, _external=True)
            group_url = url_for('groups.edit_group', id=wp.generated_group.id, _external=True) if wp.generated_group else 'N/A'
            protocol_url = url_for('core_models.edit_model', model_type='protocol', id=event.protocol.id, _external=True)
            workplan_url = url_for('workplans.edit_workplan', workplan_id=wp.id, _external=True)

            description = (
                f"Project: {wp.project.name} ({project_url})\\n"
                f"Group: {wp.generated_group.name if wp.generated_group else 'N/A'} ({group_url})\\n"
                f"Protocol: {event.protocol.name} ({protocol_url})\\n"
                f"Workplan: {wp.name} ({workplan_url})\\n"
                f"Assigned To: {assignee_str}"
            )

            # Add datatable links to the description if available
            if event.generated_datatables:
                datatable_links = []
                for dt in event.generated_datatables:
                    datatable_links.append(url_for('datatables.view_data_table', datatable_id=dt.id, _external=True))
                
                if datatable_links:
                    description += "\\n\\n"
                    for i, link in enumerate(datatable_links):
                        description += f"View DataTable {i+1}: \\n {link}\\n"

            uid = f"precliniset-event-{event.id}-{wp.updated_at.strftime('%Y%m%d%H%M%S')}@precliniset.app"
        
        elif isinstance(event_item, DataTable):
            dt = event_item
            try:
                start_date = datetime.strptime(dt.date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                continue
            
            summary = f"[{dt.group.project.slug}] {dt.protocol.name} (Ad-hoc)"
            assignee_str = dt.assignee.email if dt.assignee else 'Unassigned'
            project_url = url_for('projects.view_edit_project', project_slug=dt.group.project.slug, _external=True)
            group_url = url_for('groups.edit_group', id=dt.group.id, _external=True)
            protocol_url = url_for('core_models.edit_model', model_type='protocol', id=dt.protocol.id, _external=True)
            datatable_url = url_for('datatables.view_data_table', datatable_id=dt.id, _external=True)

            description = (
                f"Project: {dt.group.project.name} ({project_url})\\n"
                f"Group: {dt.group.name} ({group_url})\\n"
                f"Protocol: {dt.protocol.name} ({protocol_url})\\n"
                f"Assigned To: {assignee_str}\\n\\n"
                f"View Datatable: {datatable_url}"
            )
            uid = f"precliniset-datatable-{dt.id}-{dt.group.project.updated_at.strftime('%Y%m%d%H%M%S')}@precliniset.app"
        else:
            continue

        end_date = start_date + timedelta(days=1)
        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = end_date.strftime('%Y%m%d')
        dtstamp = datetime.now(current_app.config['UTC_TZ']).strftime('%Y%m%dT%H%M%SZ')

        ics_lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{start_date_str}",
            f"DTEND;VALUE=DATE:{end_date_str}",
            fold_line(f"SUMMARY:{summary}"),
            fold_line(f"DESCRIPTION:{description}"),
            "END:VEVENT",
        ])

    ics_lines.append("END:VCALENDAR")
    
    ics_content = "\r\n".join(ics_lines)
    current_app.logger.info(f"--- BEGIN ICS CONTENT for {user.email} ---")
    current_app.logger.info(ics_content)
    current_app.logger.info(f"--- END ICS CONTENT for {user.email} ---")
    return ics_content.encode('utf-8')

@calendar_bp.route('/feed/<int:user_id>/<string:token>.ics')
def personal_feed(user_id, token):
    user = db.session.get(User, user_id)
    if not user or not user.calendar_token or user.calendar_token != token:
        return Response("Forbidden", status=403)

    wp_events = WorkplanEvent.query.join(Workplan).filter(
        WorkplanEvent.assigned_to_id == user.id,
        Workplan.status.in_([WorkplanStatus.PLANNED, WorkplanStatus.RUNNING, WorkplanStatus.COMPLETED]),
        Workplan.study_start_date.isnot(None)
    ).options(
        joinedload(WorkplanEvent.workplan).joinedload(Workplan.project),
        joinedload(WorkplanEvent.workplan).joinedload(Workplan.generated_group),
        joinedload(WorkplanEvent.protocol)
    ).all()

    dt_events = DataTable.query.join(ExperimentalGroup).join(Project).filter(
        DataTable.assigned_to_id == user.id,
        DataTable.workplan_event_id.is_(None)
    ).options(
        joinedload(DataTable.group).joinedload(ExperimentalGroup.project),
        joinedload(DataTable.protocol)
    ).all()

    events = wp_events + dt_events

    cal_name = "Precliniset Assignments"
    cal_desc = f"Your personal calendar for assigned tasks in Precliniset."
    ics_content = generate_ics_feed(user, events, cal_name, cal_desc)
    
    return Response(
        ics_content,
        mimetype='text/calendar; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=personal_calendar.ics'}
    )

@calendar_bp.route('/feed/teams/<int:user_id>/<string:token>.ics')
def team_feed(user_id, token):
    user = db.session.get(User, user_id)
    if not user or not user.team_calendar_token or user.team_calendar_token != token:
        return Response("Forbidden", status=403)

    accessible_projects = user.get_accessible_projects(include_archived=False)
    accessible_project_ids = [p.id for p in accessible_projects]
    if not accessible_project_ids:
        return Response("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR", mimetype='text/calendar')

    wp_events = WorkplanEvent.query.join(Workplan).filter(
        Workplan.project_id.in_(accessible_project_ids),
        Workplan.status.in_([WorkplanStatus.PLANNED, WorkplanStatus.RUNNING, WorkplanStatus.COMPLETED]),
        Workplan.study_start_date.isnot(None)
    ).all()

    dt_events = DataTable.query.join(ExperimentalGroup).filter(
        ExperimentalGroup.project_id.in_(accessible_project_ids),
        DataTable.workplan_event_id.is_(None)
    ).all()

    all_events = wp_events + dt_events

    cal_name = f"Precliniset Teams: {user.email}"
    cal_desc = "All events from projects you have access to in Precliniset."
    ics_content = generate_ics_feed(user, all_events, cal_name, cal_desc)
    
    return Response(
        ics_content,
        mimetype='text/calendar; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=team_calendar.ics'}
    )

@calendar_bp.route('/team_members.json')
@login_required
def team_members_json():
    """Provides a JSON feed of team members for filtering."""
    team_members = []
    if current_user.is_super_admin:
        # Super admin can see all users
        users = User.query.order_by(User.email).all()
    else:
        # Get users from current user's teams
        user_teams = current_user.get_teams()
        user_ids_in_teams = set()
        for team in user_teams:
            for member in team.members:
                user_ids_in_teams.add(member.id)
        users = User.query.filter(User.id.in_(list(user_ids_in_teams))).order_by(User.email).all()
    
    for user in users:
        team_members.append({
            'id': user.id,
            'name': user.email
        })
    return jsonify(team_members)

@calendar_bp.route('/api/tm_events')
@login_required
def tm_events():
    """Proxy for Training Manager calendar events."""
    connector = TrainingManagerConnector()
    events = connector.get_user_calendar(current_user.email)
    if events:
        return jsonify(events)
    else:
        return jsonify([])
