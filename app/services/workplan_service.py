# app/services/workplan_service.py
import json
from datetime import datetime, timedelta

import pandas as pd
from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import (DataTable, EthicalApproval, ExperimentalGroup, Project,
                        ProtocolModel, Severity, Workplan, WorkplanEvent,
                        WorkplanStatus, WorkplanVersion)
from app.services.base import BaseService
from app.services.ethical_approval_service import validate_group_ea_unlinking


class WorkplanService(BaseService):
    model = Workplan

    def create_workplan(self, project_id, name, planned_animal_count):
        workplan = self.create(
            project_id=project_id,
            name=name,
            planned_animal_count=planned_animal_count
        )
        return workplan

    def update_workplan(self, workplan, new_state, user, change_comment="Workplan updated.", notify_team=False):
        """
        Updates workplan details and events, creating a new version.
        new_state should be a dict with:
        - study_start_date (str or date)
        - expected_dob (str or date)
        - notes (str)
        - events (list of dicts with offset_days, protocol_id, event_name, assigned_to_id)
        """
        # Create New Version
        last_version_num = db.session.query(func.max(WorkplanVersion.version_number))\
            .filter_by(workplan_id=workplan.id).scalar() or 0
        
        # Snapshot creation logic (could be extracted)
        snapshot_events = sorted([{
            'offset_days': item.get('offset_days'),
            'protocol_id': item.get('protocol_id'),
            'event_name': item.get('event_name') or "",
            'assigned_to_id': item.get('assigned_to_id')
        } for item in new_state.get('events', [])], key=lambda x: int(x['offset_days']))

        new_version = WorkplanVersion(
            workplan=workplan,
            version_number=last_version_num + 1,
            created_by_id=user.id,
            change_comment=change_comment,
            snapshot={
                'animal_model_name': workplan.animal_model.name if workplan.animal_model else 'N/A',
                'number_of_animals': workplan.planned_animal_count,
                'events': snapshot_events
            }
        )
        db.session.add(new_version)

        # Update Workplan fields
        workplan.notes = new_state.get('notes', "")
        
        start_date = new_state.get('study_start_date')
        if isinstance(start_date, str):
            workplan.study_start_date = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
        else:
            workplan.study_start_date = start_date

        dob = new_state.get('expected_dob')
        if isinstance(dob, str):
            workplan.expected_dob = datetime.strptime(dob, '%Y-%m-%d').date() if dob else None
        else:
            workplan.expected_dob = dob
        
        # Update Planned Animal Count if provided
        if 'planned_animal_count' in new_state:
             workplan.planned_animal_count = new_state['planned_animal_count']

        # Update Events
        # Delete existing events and recreate (simplest approach for full update)
        workplan.events.delete()
        
        for event_data in new_state.get('events', []):
            assignee_id = event_data.get('assigned_to_id')
            # Normalize assignee_id
            if assignee_id is not None and assignee_id != "":
                try:
                    assignee_id = int(assignee_id)
                except (ValueError, TypeError):
                    assignee_id = None
            else:
                assignee_id = None

            event = WorkplanEvent(
                workplan=workplan,
                protocol_id=int(event_data.get('protocol_id')),
                assigned_to_id=assignee_id,
                offset_days=int(event_data.get('offset_days')),
                event_name=event_data.get('event_name')
            )
            db.session.add(event)

        db.session.flush()
        workplan.current_version_id = new_version.id
        db.session.commit()

        if notify_team:
            from app.helpers import send_workplan_update_notification
            send_workplan_update_notification(workplan.id, user.id, str(change_comment))

        return workplan

    def finalize_workplan(self, workplan, user, ea_id, group_name=None, group_id=None, animal_model_id=None, notify_team=False):
        ea = db.session.get(EthicalApproval, ea_id)
        if not ea:
            raise ValueError("Selected Ethical Approval not found.")

        target_group = None
        flash_group_name = ""

        if group_id:
            # Link to Existing Group
            target_group = db.session.get(ExperimentalGroup, group_id)
            if not target_group:
                raise ValueError("Selected existing group not found.")
            if target_group.project_id != workplan.project_id:
                raise ValueError("Selected group does not belong to this project.")
            if target_group.created_from_workplan_id is not None:
                raise ValueError("Selected group is already linked to another workplan.")
            
            target_group.created_from_workplan_id = workplan.id
            target_group.ethical_approval_id = ea.id
            flash_group_name = target_group.name

            # Validate the ethical approval change
            db.session.flush() # Ensure the change is visible for validation
            validation_result = validate_group_ea_unlinking(target_group.id, [ea.id])
            if not validation_result['is_valid']:
                raise ValueError("; ".join(validation_result['errors']))
        
        else:
            # Create New Group
            if not animal_model_id:
                raise ValueError("Animal Model is required when creating a new group.")
            
            # Generate ID logic
            group_count = ExperimentalGroup.query.filter_by(project_id=workplan.project_id).count()
            new_group_id = f"{workplan.project.slug}-G{group_count + 1}"
            while db.session.get(ExperimentalGroup, new_group_id):
                group_count += 1
                new_group_id = f"{workplan.project.slug}-G{group_count + 1}"

            target_group = ExperimentalGroup(
                id=new_group_id,
                name=group_name,
                project_id=workplan.project_id,
                model_id=animal_model_id,
                ethical_approval_id=ea.id,
                created_from_workplan_id=workplan.id,
                owner_id=user.id,
                team_id=workplan.project.team_id
            )
            db.session.add(target_group)
            
            # Validate the ethical approval change
            db.session.flush() # Ensure the new group and its EA are visible for validation
            validation_result = validate_group_ea_unlinking(target_group.id, [ea.id])
            if not validation_result['is_valid']:
                raise ValueError("; ".join(validation_result['errors']))

            flash_group_name = group_name

        db.session.flush()

        # Create DataTables
        for event in workplan.events.all():
            event_date = workplan.study_start_date + timedelta(days=event.offset_days)
            dt = DataTable(
                group_id=target_group.id,
                protocol_id=event.protocol_id,
                date=event_date.isoformat(),
                creator_id=user.id,
                assigned_to_id=event.assigned_to_id,
                workplan_event_id=event.id
            )
            db.session.add(dt)
        
        # Update Workplan Status
        workplan.status = WorkplanStatus.PLANNED
        last_version_num = db.session.query(func.max(WorkplanVersion.version_number)).filter_by(workplan_id=workplan.id).scalar() or 0
        
        from flask_babel import lazy_gettext as _l
        change_comment = _l("Status changed to PLANNED. Generated/Linked Group '%(group_name)s' and %(dt_count)s DataTables.", group_name=flash_group_name, dt_count=workplan.events.count())
        
        new_version = WorkplanVersion(
            workplan=workplan, version_number=last_version_num + 1, created_by_id=user.id,
            change_comment=str(change_comment),
            snapshot=workplan.current_version.snapshot if workplan.current_version else {}
        )
        db.session.add(new_version)
        db.session.flush()
        workplan.current_version_id = new_version.id

        db.session.commit()

        if notify_team:
            from app.helpers import send_workplan_update_notification
            send_workplan_update_notification(workplan.id, user.id, str(change_comment))

        return target_group

    def move_event(self, event, delta_days, user, change_comment, notify_team=False):
        workplan = event.workplan
        event.offset_days += int(delta_days)
        
        last_version_num = db.session.query(func.max(WorkplanVersion.version_number)).filter_by(workplan_id=workplan.id).scalar() or 0
        
        current_events_snapshot = [{
            'protocol_id': ev.protocol_id,
            'assigned_to_id': ev.assigned_to_id,
            'offset_days': ev.offset_days,
            'event_name': ev.event_name
        } for ev in workplan.events.order_by(WorkplanEvent.offset_days).all()]

        new_version = WorkplanVersion(
            workplan=workplan,
            version_number=last_version_num + 1,
            created_by_id=user.id,
            change_comment=change_comment,
            snapshot={
                'animal_model_name': workplan.animal_model.name if workplan.animal_model else 'N/A',
                'number_of_animals': workplan.planned_animal_count,
                'events': current_events_snapshot
            }
        )
        db.session.add(new_version)
        db.session.flush()
        workplan.current_version_id = new_version.id
        
        db.session.commit()
        
        if notify_team:
            db.session.refresh(workplan)
            from app.helpers import send_workplan_update_notification
            send_workplan_update_notification(workplan.id, user.id, str(change_comment))

    def restore_version(self, workplan, version_id, user, change_comment, notify_team=False):
        version_to_restore = db.session.get(WorkplanVersion, version_id)
        if not version_to_restore or version_to_restore.workplan_id != workplan.id:
            raise ValueError("Version not found or does not belong to this workplan")

        last_version_num = db.session.query(func.max(WorkplanVersion.version_number)).filter_by(workplan_id=workplan.id).scalar() or 0
        
        new_version = WorkplanVersion(
            workplan=workplan,
            version_number=last_version_num + 1,
            created_by_id=user.id,
            change_comment=change_comment,
            snapshot=version_to_restore.snapshot
        )
        db.session.add(new_version)

        workplan.events.delete()
        restored_events_data = version_to_restore.snapshot.get('events', [])
        for event_data in restored_events_data:
            event = WorkplanEvent(
                workplan=workplan,
                protocol_id=event_data.get('protocol_id'),
                assigned_to_id=event_data.get('assigned_to_id'),
                offset_days=event_data.get('offset_days'),
                event_name=event_data.get('event_name')
            )
            db.session.add(event)
        
        db.session.flush()
        workplan.current_version_id = new_version.id
        db.session.commit()

        if notify_team:
            from app.helpers import send_workplan_update_notification
            send_workplan_update_notification(workplan.id, user.id, str(change_comment))