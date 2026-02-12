# app/services/group_service.py
import json
import secrets
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from flask import current_app
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import insert, update
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.helpers import sort_analytes_list_by_name
# Added Team to imports
from app.models import (AnimalModel, AnimalModelAnalyteAssociation,
                        ExperimentalGroup, Project, EthicalApproval, 
                        ProjectEthicalApprovalAssociation, Team, Animal, Analyte, User)
from app.schemas.animal import AnimalSchema
from app.schemas.group import GroupCreateSchema
from app.exceptions import ValidationError, BusinessError
from app.services.audit_service import suppress_audit
from app.services.base import BaseService
from app.services.ethical_approval_service import validate_group_ea_unlinking
from app.services.validation_service import ValidationService
from app.utils.files import read_excel_to_list


class GroupService(BaseService):
    model = ExperimentalGroup

    def __init__(self) -> None:
        super().__init__()
        self.validator = ValidationService()

    def generate_group_id(self, name: str, project_id: int) -> str:
        """Generates a structured ID for a group based on project slug and date."""
        project = db.session.get(Project, project_id)
        if not project or not project.slug:
            return secrets.token_hex(20)
            
        today_str = datetime.now(timezone.utc).strftime('%y%m%d')
        prefix = f"{project.slug}-{today_str}-"
        
        last_group = ExperimentalGroup.query.filter(
            ExperimentalGroup.id.like(f"{prefix}%")
        ).order_by(db.desc(ExperimentalGroup.id)).first()
        
        sequence = 1
        if last_group:
            try:
                last_sequence_str = last_group.id.split('-')[-1]
                sequence = int(last_sequence_str) + 1
            except (ValueError, IndexError):
                pass
        
        return f"{prefix}{sequence}"

    def create_group(self, name, project_id, team_id, owner_id, model_id=None, animal_data=None, **kwargs):
        """Create a group with initial animals."""
        if 'id' not in kwargs:
            kwargs['id'] = self.generate_group_id(name, project_id)

        group = ExperimentalGroup(
            name=name,
            project_id=project_id,
            team_id=team_id,
            owner_id=owner_id,
            model_id=model_id,
            **kwargs
        )
        db.session.add(group)
        db.session.flush()
        
        if animal_data:
            self.save_group_data(group, animal_data)
        
        return group

    def update_group_details(self, group, name, model_id, ethical_approval_id, default_euthanasia_reason=None, default_severity=None):
        """Updates basic metadata of the group."""
        ea_ids_for_validation = [ethical_approval_id] if ethical_approval_id else []
        validation_result = validate_group_ea_unlinking(group.id, ea_ids_for_validation)

        if not validation_result['is_valid']:
            raise BusinessError("; ".join(validation_result['errors']))

        group.name = name
        group.model_id = model_id
        group.ethical_approval_id = ethical_approval_id
        group.default_euthanasia_reason = default_euthanasia_reason
        group.default_severity = default_severity
        return group

    def save_group_data(self, group, animal_data_list, update_datatables=True, allow_new_categories=False):
        """
        Main logic for syncing animal entities.
        App generates UID, scientist controls display_id.
        """
        # 1. VALIDATE
        if group.model:
            validation_result = self.validator.validate_animal_data(animal_data_list, group.model, strict=False)
            if validation_result.get('errors'):
                raise BusinessError("Validation Failed: " + "; ".join([str(e) for e in validation_result['errors'][:5]]))

            if validation_result.get('new_categories') and not allow_new_categories:
                raise BusinessError(json.dumps({'type': 'new_categories', 'data': validation_result['new_categories']}))

        # 2. MATCHING
        existing_animals = Animal.query.filter_by(group_id=group.id).all()
        existing_animals_by_pk = {a.id: a for a in existing_animals}
        existing_animals_by_uid = {a.uid: a for a in existing_animals}
        
        touched_pks = set()
        to_insert = []
        to_update = []
        now = datetime.now(timezone.utc)

        for animal_dict in animal_data_list:
            pk = animal_dict.get('id')
            existing_animal = None
            
            if pk and str(pk).isdigit() and int(pk) in existing_animals_by_pk:
                existing_animal = existing_animals_by_pk[int(pk)]
            
            if not existing_animal:
                provided_uid = animal_dict.get('uid')
                if provided_uid and provided_uid in existing_animals_by_uid:
                    existing_animal = existing_animals_by_uid[provided_uid]

            # Scientist Label (display_id)
            scientist_label = animal_dict.get('display_id') or animal_dict.get('ID') or animal_dict.get('uid')

            # Core Fields
            sex = animal_dict.get('sex')
            status = animal_dict.get('status') or animal_dict.get('Status') or 'alive'
            
            dob = None
            dob_val = animal_dict.get('date_of_birth') or animal_dict.get('date of birth')
            if dob_val:
                try:
                    if isinstance(dob_val, str):
                        dob = datetime.strptime(dob_val.split('T')[0], '%Y-%m-%d').date()
                    elif hasattr(dob_val, 'date'):
                        dob = dob_val.date()
                except: pass

            # JSON Measurements
            measurements = {k: v for k, v in animal_dict.items() 
                           if k.lower() not in ['id', 'uid', 'display_id', 'date_of_birth', 'sex', 'status', 'age_days']}

            if existing_animal:
                touched_pks.add(existing_animal.id)
                to_update.append({
                    'id': existing_animal.id,
                    'display_id': str(scientist_label or existing_animal.display_id),
                    'sex': sex or existing_animal.sex,
                    'status': status,
                    'date_of_birth': dob or existing_animal.date_of_birth,
                    'measurements': measurements,
                    'updated_at': now
                })
            else:
                # FIX: Use provided UID if available, otherwise generate new one
                # This fixes the mismatch in demo data population
                uid_to_use = animal_dict.get('uid') or secrets.token_hex(12)
                
                to_insert.append({
                    'uid': uid_to_use,
                    'display_id': str(scientist_label),
                    'group_id': group.id,
                    'sex': sex,
                    'status': status,
                    'date_of_birth': dob,
                    'measurements': measurements,
                    'created_at': now,
                    'updated_at': now
                })

        # 3. DB EXECUTION
        for pk, animal in existing_animals_by_pk.items():
            if pk not in touched_pks:
                db.session.delete(animal)

        if to_insert:
            db.session.execute(insert(Animal), to_insert)
        if to_update:
            db.session.execute(update(Animal), to_update)
        
        if group.project:
            group.project.updated_at = now
            
        db.session.flush()
        return group

    def process_animal_data(self, group, request_form, request_files):
        """Helper to parse raw request data."""
        from app.utils.files import read_excel_to_list
        animal_data_list = []
        animal_field_names = set()

        if 'xlsx_upload' in request_files and request_files['xlsx_upload'].filename != '':
            animal_data_list, columns = read_excel_to_list(request_files['xlsx_upload'])
            animal_field_names.update(columns)
        elif request_form.get('animal_data'):
            animal_data_list = json.loads(request_form.get('animal_data'))
        
        animal_data_list = self._convert_timestamps(animal_data_list)
        return animal_data_list, animal_field_names

    def _convert_timestamps(self, data: Any) -> Any:
        """Helper to recursively convert date objects to ISO strings for JSON."""
        if isinstance(data, dict):
            return {k: self._convert_timestamps(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_timestamps(elem) for elem in data]
        elif hasattr(data, 'isoformat'):
            return data.date().isoformat() if hasattr(data, 'date') else data.isoformat()
        return data

    def delete_group(self, group: ExperimentalGroup) -> bool:
        """Deletes a group and updates project timestamp."""
        if group.project:
            group.project.updated_at = datetime.now(timezone.utc)
        db.session.delete(group)
        db.session.commit()
        return True

    def reassign_group(self, group: ExperimentalGroup, target_project: Project) -> ExperimentalGroup:
        """Moves a group to a new project."""
        group.project_id = target_project.id
        target_project.updated_at = datetime.now(timezone.utc)
        db.session.flush()
        return group

    def get_server_side_groups(
        self, 
        user: User, 
        filters: Dict[str, Any], 
        page: int, 
        per_page: int, 
        sort_column: str, 
        sort_direction: str
    ) -> Dict[str, Any]:
        from sqlalchemy.orm import joinedload, selectinload
        from app.services.permission_service import PermissionService
        
        query = db.session.query(ExperimentalGroup) \
            .join(Project, ExperimentalGroup.project_id == Project.id) \
            .join(Team, ExperimentalGroup.team_id == Team.id) \
            .options(
                joinedload(ExperimentalGroup.project),
                joinedload(ExperimentalGroup.team),
                joinedload(ExperimentalGroup.model),
                selectinload(ExperimentalGroup.animals)
            )

        # Apply permissions: only accessible projects (optimized query)
        if not user.is_super_admin:
            perm_service = PermissionService()
            visible_projects_query = perm_service.get_visible_projects_query(user)
            accessible_project_ids = [p.id for p in visible_projects_query.with_entities(Project.id).all()]
            query = query.filter(ExperimentalGroup.project_id.in_(accessible_project_ids))

        # Apply filters
        if 'project_id' in filters and filters['project_id']:
            query = query.filter(ExperimentalGroup.project_id == filters['project_id'])
        if 'team_id' in filters and filters['team_id']:
            query = query.filter(ExperimentalGroup.team_id == filters['team_id'])
        if 'model_id' in filters and filters['model_id']:
            query = query.filter(ExperimentalGroup.model_id == filters['model_id'])
        
        is_archived_filter = filters.get('is_archived')
        
        if is_archived_filter is True:
            query = query.filter(ExperimentalGroup.is_archived == True)
        elif is_archived_filter is False:
            query = query.filter(ExperimentalGroup.is_archived == False)
        elif is_archived_filter == 'all':
            pass # Do not filter, show everything
        else:
            # Default to Active Only if no filter provided
            query = query.filter(ExperimentalGroup.is_archived == False)
        
        search_value = filters.get('search_value')
        if search_value:
            search_pattern = f"%{search_value}%"
            query = query.filter(
                (ExperimentalGroup.name.ilike(search_pattern)) |
                (Project.name.ilike(search_pattern)) |
                (Team.name.ilike(search_pattern))
            )

        total_records = query.count() # Count after filters for pagination
        filtered_records = total_records

        # Apply sorting
        sort_column_map = {
            'name': ExperimentalGroup.name,
            'project_name': Project.name,
            'team_name': Team.name,
            'model_name': AnimalModel.name,
            'created_at': ExperimentalGroup.created_at,
            'updated_at': ExperimentalGroup.updated_at,
            'is_archived': ExperimentalGroup.is_archived
        }
        
        # Add a join for AnimalModel if sorting by model_name
        if sort_column == 'model_name':
            query = query.join(AnimalModel, ExperimentalGroup.model_id == AnimalModel.id)

        column_to_sort = sort_column_map.get(sort_column, ExperimentalGroup.created_at) # Default sort
        if sort_direction == 'desc':
            query = query.order_by(column_to_sort.desc())
        else:
            query = query.order_by(column_to_sort.asc())

        # Apply pagination
        offset = (page - 1) * per_page
        items = query.offset(offset).limit(per_page).all()

        return {
            'total_records': total_records,
            'filtered_records': filtered_records,
            'items': items
        }