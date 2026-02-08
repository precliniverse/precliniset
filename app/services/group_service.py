import json
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
            import secrets
            return secrets.token_hex(20)
            
        today_str = datetime.now(timezone.utc).strftime('%y%m%d')
        prefix = f"{project.slug}-{today_str}-"
        
        # We need the last sequence for THIS prefix
        last_group = ExperimentalGroup.query.filter(
            ExperimentalGroup.id.like(f"{prefix}%")
        ).order_by(db.desc(ExperimentalGroup.id)).first()
        
        sequence = 1
        if last_group:
            try:
                # Assuming ID format prefixX where X is the sequence
                last_sequence_str = last_group.id.split('-')[-1]
                sequence = int(last_sequence_str) + 1
            except (ValueError, IndexError):
                pass
        
        return f"{prefix}{sequence}"

    def create_group(
        self, 
        name: str, 
        project_id: int, 
        team_id: int, 
        owner_id: int, 
        model_id: Optional[int] = None, 
        animal_data: Optional[List[Dict[str, Any]]] = None, 
        **kwargs: Any
    ) -> ExperimentalGroup:
        """Create a group with Animal entities (V2 refactored).
        
        Args:
            name: Group name
            project_id: Project ID
            team_id: Team ID
            owner_id: Owner user ID
            model_id: Animal model ID
            animal_data: List of animal dictionaries (will be converted to Animal entities)
            **kwargs: Additional fields for ExperimentalGroup (e.g., id, ethical_approval_id)
            
        Returns:
            Created ExperimentalGroup
        """
        # Prepare ID if not provided
        if 'id' not in kwargs:
            kwargs['id'] = self.generate_group_id(name, project_id)

        # Create the group (no animal_data column anymore)
        group = ExperimentalGroup(
            name=name,
            project_id=project_id,
            team_id=team_id,
            owner_id=owner_id,
            model_id=model_id,
            **kwargs
        )
        db.session.add(group)
        db.session.flush()  # Get group ID
        
        # Create Animal entities if data provided
        if animal_data:
            to_insert = []
            # Validate and create animals
            for i, animal_dict in enumerate(animal_data):
                animal_id = animal_dict.get('uid') or f"{group.id}-A{i+1}"
                display_id = animal_dict.get('display_id') or f"Animal {i+1}"
                
                # Validate using AnimalSchema
                try:
                    # Ensure uid and display_id are in dict for schema
                    if 'uid' not in animal_dict:
                        animal_dict['uid'] = animal_id
                    if 'display_id' not in animal_dict:
                        animal_dict['display_id'] = display_id
                    schema = AnimalSchema(**animal_dict)
                except PydanticValidationError as e:
                    raise ValidationError(f"Invalid animal data for {animal_id}: {str(e)}")
                
                # Dynamic validation against Analyte configuration
                if schema.sex and model_id:
                    sex_analyte = Analyte.query.filter_by(name='sex').first()
                    if sex_analyte and sex_analyte.allowed_values:
                        allowed_values = [v.strip() for v in sex_analyte.allowed_values.split(';') if v.strip()]
                        if schema.sex not in allowed_values:
                            raise ValidationError(
                                f"Invalid sex value '{schema.sex}' for animal {animal_id}. "
                                f"Allowed values: {', '.join(allowed_values)}"
                            )
                
                # Collect for bulk insert
                to_insert.append({
                    'uid': schema.uid,
                    'display_id': schema.display_id,
                    'group_id': group.id,
                    'sex': schema.sex,
                    'date_of_birth': schema.date_of_birth,
                    'status': animal_dict.get('status') or animal_dict.get('Status') or 'alive',
                    'measurements': schema.measurements or {},
                    'created_at': datetime.now(timezone.utc),
                    'updated_at': datetime.now(timezone.utc)
                })
            
            if to_insert:
                db.session.execute(insert(Animal), to_insert)
        
        return group

    def update_group_details(
        self, 
        group: ExperimentalGroup, 
        name: str, 
        model_id: Optional[int], 
        ethical_approval_id: Optional[int], 
        default_euthanasia_reason: Optional[str] = None, 
        default_severity: Optional[str] = None
    ) -> ExperimentalGroup:
        """Updates basic metadata of the group."""

        # Validate ethical approval change
        ea_ids_for_validation = [ethical_approval_id] if ethical_approval_id else []
        validation_result = validate_group_ea_unlinking(group.id, ea_ids_for_validation)

        if not validation_result['is_valid']:
            raise BusinessError("; ".join(validation_result['errors']))

        group.name = name
        group.model_id = model_id
        group.ethical_approval_id = ethical_approval_id
        group.default_euthanasia_reason = default_euthanasia_reason
        group.default_severity = default_severity

        # Automatically link Ethical Approval to Project if not already linked
        if ethical_approval_id and group.project_id:
            existing_association = ProjectEthicalApprovalAssociation.query.filter_by(
                project_id=group.project_id,
                ethical_approval_id=ethical_approval_id
            ).first()
            if not existing_association:
                new_association = ProjectEthicalApprovalAssociation(
                    project_id=group.project_id,
                    ethical_approval_id=ethical_approval_id
                )
                db.session.add(new_association)
                db.session.flush()

        return group

    def process_animal_data(
        self, 
        group: ExperimentalGroup, 
        request_form: Dict[str, Any], 
        request_files: Dict[str, Any]
    ) -> tuple[List[Dict[str, Any]], set[str]]:
        """
        Handles the complex logic of parsing animal data from forms or files.
        """
        animal_data_list = []
        animal_field_names = set()

        # 1. Handle Excel Upload
        if 'xlsx_upload' in request_files and request_files['xlsx_upload'].filename != '':
            file = request_files['xlsx_upload']
            animal_data_list, columns = read_excel_to_list(file)
            animal_field_names.update(columns)
        
        # 2. Handle JSON String
        elif request_form.get('animal_data'):
            try:
                raw_json = json.loads(request_form.get('animal_data'))
                if isinstance(raw_json, list):
                    animal_data_list = raw_json
                    for item in animal_data_list:
                        if isinstance(item, dict):
                            animal_field_names.update(item.keys())
            except json.JSONDecodeError:
                current_app.logger.error("Failed to decode animal_data JSON")
                animal_data_list = []

        # 3. Handle Dynamic Form Fields
        else:
            parsed_animals = {} 
            for key, value in request_form.items():
                if key.startswith('animal_') and '_field_' in key:
                    try:
                        parts = key.split('_field_')
                        if len(parts) == 2:
                            index_str = parts[0].replace('animal_', '')
                            index = int(index_str)
                            field_name = parts[1]
                            
                            if index not in parsed_animals:
                                parsed_animals[index] = {}
                            
                            parsed_animals[index][field_name] = value
                            animal_field_names.add(field_name)
                    except (ValueError, IndexError):
                        continue
            
            if parsed_animals:
                for i in sorted(parsed_animals.keys()):
                    animal_data_list.append(parsed_animals[i])

        # 4. Post-Processing
        animal_data_list = self._convert_timestamps(animal_data_list)
        
        for i, d in enumerate(animal_data_list):
            current_id = d.get('uid')
            if not current_id:
                d['uid'] = f"{group.id}-A{i+1}"
            else:
                # Ensure it's in canonical 'uid'
                d['uid'] = current_id
 
        return animal_data_list, animal_field_names

    def save_group_data(
        self, 
        group: ExperimentalGroup, 
        animal_data_list: List[Dict[str, Any]], 
        update_datatables: bool = True, 
        allow_new_categories: bool = False
    ) -> ExperimentalGroup:
        """Validates and saves animal data to Animal entities (V2 refactored).
        
        Args:
            group: ExperimentalGroup instance
            animal_data_list: List of animal dictionaries
            update_datatables: Whether to update associated datatables
            allow_new_categories: Whether to allow new category values
            
        Returns:
            ExperimentalGroup instance
        """
        # 1. Validate Data Integrity
        if group.model:
            validation_result = self.validator.validate_animal_data(animal_data_list, group.model, strict=False)
            errors = validation_result.get('errors', [])
            new_categories = validation_result.get('new_categories', {})

            if errors:
                error_strings = [str(err) for err in errors[:5]]
                error_msg = "Validation Failed: " + "; ".join(error_strings)
                if len(errors) > 5:
                    error_msg += f" ...and {len(errors) - 5} more errors."
                raise BusinessError(error_msg)

            if new_categories:
                if allow_new_categories:
                    for analyte_id, new_values in new_categories.items():
                        analyte = db.session.get(Analyte, analyte_id)
                        if analyte:
                            existing = [v.strip() for v in (analyte.allowed_values or "").split(';') if v.strip()]
                            updated = existing + [v for v in new_values if v not in existing]
                            analyte.allowed_values = "; ".join(updated)
                            db.session.add(analyte)
                    db.session.flush()
                else:
                    raise BusinessError(json.dumps({'type': 'new_categories', 'data': new_categories}))

        # 2. Update, create or delete Animal entities
        existing_animals = {a.uid: a for a in Animal.query.filter_by(group_id=group.id).all()}
        new_animal_uids = {d.get('uid') for d in animal_data_list if d.get('uid')}
        
        # Delete animals not in the new list
        for uid, animal in list(existing_animals.items()):
            if uid not in new_animal_uids:
                db.session.delete(animal)
                del existing_animals[uid]
        
        to_insert = []
        to_update = []
        
        now = datetime.now(timezone.utc)
        
        for animal_dict in animal_data_list:
            animal_id = animal_dict.get('uid')
            if not animal_id:
                continue
            
            # 1. Parse keys into core vs measurements
            measurements = {}
            parsed_core = {}
            
            # Core keys are normalized to lowercase for mapping
            core_keys_map = {
                'uid': 'uid',
                'display_id': 'display_id',
                'date_of_birth': 'date_of_birth',
                'sex': 'sex',
                'status': 'status'
            }
            # Special keys to skip from measurements (system calculated or internal)
            internal_keys = {'age_days', 'age (days)', 'blinded_group', 'blinded group', 'treatment_group', 'treatment group'}
            
            for key, value in animal_dict.items():
                low_key = key.lower()
                if low_key in core_keys_map:
                    parsed_core[core_keys_map[low_key]] = value
                elif low_key not in internal_keys:
                    measurements[key] = value
            
            # 2. Longitudinal Weight logic: Save weight to measurements['last_weight']
            # Check for weight in various case-insensitive formats
            weight_value = None
            for weight_key in ['weight', 'Weight', 'WEIGHT']:
                if weight_key in animal_dict and animal_dict[weight_key]:
                    weight_value = animal_dict[weight_key]
                    break
            
            if weight_value is not None:
                measurements['last_weight'] = weight_value

            # 2. Parse typed fields from parsed_core
            dob = None
            dob_val = parsed_core.get('date_of_birth')
            if dob_val:
                try:
                    if isinstance(dob_val, str):
                        dob = datetime.strptime(dob_val.split('T')[0], '%Y-%m-%d').date()
                    elif hasattr(dob_val, 'date'):
                        dob = dob_val.date()
                    else:
                        dob = dob_val
                except (ValueError, TypeError):
                    pass

            sex = parsed_core.get('sex', animal_dict.get('sex'))
            status = parsed_core.get('status', animal_dict.get('status', 'alive'))
            display_id = parsed_core.get('display_id', animal_dict.get('display_id'))

            if animal_id in existing_animals:
                # Update existing animal
                existing_animal = existing_animals[animal_id]
                # Preserve existing display_id if not provided in update
                if not display_id:
                    display_id = existing_animal.display_id
                to_update.append({
                    'id': existing_animal.id,
                    'sex': sex,
                    'status': status,
                    'date_of_birth': dob,
                    'display_id': display_id,
                    'measurements': measurements,
                    'updated_at': now
                })
            else:
                # Create new animal
                # Ensure display_id is provided
                if not display_id:
                    display_id = f"Animal {len(to_insert) + 1}"
                
                to_insert.append({
                    'uid': animal_id,
                    'display_id': display_id,
                    'group_id': group.id,
                    'sex': sex,
                    'status': status,
                    'date_of_birth': dob,
                    'measurements': measurements,
                    'created_at': now,
                    'updated_at': now
                })
        
        if to_insert:
            db.session.execute(insert(Animal), to_insert)
        
        if to_update:
            db.session.execute(update(Animal), to_update)
        
        # 3. Update project timestamp
        if group.project:
            group.project.updated_at = now

        db.session.flush()

        # 4. Update associated datatables if requested
        if update_datatables:
            # Refresh from DB to get updated fields and ensure all animals are loaded
            db.session.expire(group, ['animals'])
            animals = sorted(group.animals, key=lambda a: a.id)
            
            # Prepare ordered data for datatable update
            ordered_data = [a.to_dict() for a in animals]
            
            # Determine column order from Animal Model
            final_ordered_keys = ['uid', 'date_of_birth', 'age_days', 'blinded_group', 'treatment_group']
            if group.model_id:
                associations = AnimalModelAnalyteAssociation.query.filter_by(
                    animal_model_id=group.model_id
                ).order_by(AnimalModelAnalyteAssociation.order).all()
                for assoc in associations:
                    if assoc.analyte.name not in final_ordered_keys:
                        final_ordered_keys.append(assoc.analyte.name)
            
            # Note: update_associated_data_tables function has been removed as part of legacy cleanup
            # The new animal_id foreign key system handles data synchronization automatically

        return group

    def _convert_timestamps(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: self._convert_timestamps(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_timestamps(elem) for elem in data]
        elif hasattr(data, 'isoformat'):
            return data.date().isoformat() if hasattr(data, 'date') else data.isoformat()
        return data

    def delete_group(self, group: ExperimentalGroup) -> bool:
        if group.project:
            group.project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        return self.delete(group)

    def reassign_group(self, group: ExperimentalGroup, target_project: Project) -> ExperimentalGroup:
        original_project = group.project
        group.project_id = target_project.id
        target_project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        if original_project:
            original_project.updated_at = datetime.now(current_app.config['UTC_TZ'])
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
        from sqlalchemy.orm import joinedload
        from app.services.permission_service import PermissionService
        
        query = db.session.query(ExperimentalGroup) \
            .join(Project, ExperimentalGroup.project_id == Project.id) \
            .join(Team, ExperimentalGroup.team_id == Team.id) \
            .options(
                joinedload(ExperimentalGroup.project),
                joinedload(ExperimentalGroup.team),
                joinedload(ExperimentalGroup.model),
                joinedload(ExperimentalGroup.animals)
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
        # Note: DataTables expects totalRecords to be total BEFORE filtering, but filteredRecords AFTER.
        # For server-side simple implementation, often total=filtered is returned if deep counting is expensive.
        # But to be precise:
        # total_records = db.session.query(ExperimentalGroup).count() 
        # filtered_records = query.count()

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