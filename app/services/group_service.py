# app/services/group_service.py
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from flask import current_app
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.helpers import update_associated_data_tables
# Added Team to imports
from app.models import (AnimalModel, AnimalModelAnalyteAssociation,
                        ExperimentalGroup, Project, EthicalApproval, 
                        ProjectEthicalApprovalAssociation, Team, Animal, Analyte)
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

    def __init__(self):
        super().__init__()
        self.validator = ValidationService()

    def create_group(self, name, project_id, team_id, owner_id, model_id=None, animal_data=None):
        """Create a group with Animal entities (V2 refactored).
        
        Args:
            name: Group name
            project_id: Project ID
            team_id: Team ID
            owner_id: Owner user ID
            model_id: Animal model ID
            animal_data: List of animal dictionaries (will be converted to Animal entities)
            
        Returns:
            Created ExperimentalGroup
        """
        try:
            # Create the group (no animal_data column anymore)
            group = ExperimentalGroup(
                name=name,
                project_id=project_id,
                team_id=team_id,
                owner_id=owner_id,
                model_id=model_id
            )
            db.session.add(group)
            db.session.flush()  # Get group ID
            
            # Create Animal entities if data provided
            if animal_data:
                # Validate and create animals
                for i, animal_dict in enumerate(animal_data):
                    animal_id = animal_dict.get('ID') or f"{group.id}-A{i+1}"
                    
                    # Validate using AnimalSchema
                    try:
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
                    
                    # Create Animal entity
                    animal = Animal(
                        uid=schema.animal_id,
                        group_id=group.id,
                        sex=schema.sex,
                        date_of_birth=schema.date_of_birth,
                        status='alive',
                        measurements=schema.measurements
                    )
                    db.session.add(animal)
            
            db.session.commit()
            return group
            
        except PydanticValidationError as e:
            db.session.rollback()
            raise ValidationError(f"Animal data validation failed: {str(e)}")
        except Exception as e:
            db.session.rollback()
            raise

    def update_group_details(self, group, name, model_id, ethical_approval_id, default_euthanasia_reason=None, default_severity=None):
        """Updates basic metadata of the group."""

        # Validate ethical approval change
        ea_ids_for_validation = [ethical_approval_id] if ethical_approval_id else []
        validation_result = validate_group_ea_unlinking(group.id, ea_ids_for_validation)

        if not validation_result['is_valid']:
            raise ValueError("; ".join(validation_result['errors']))

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

    def process_animal_data(self, group, request_form, request_files):
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
            if 'ID' not in d or not d['ID']:
                d['ID'] = f"{group.id}-A{i+1}"

        return animal_data_list, animal_field_names

    def save_group_data(self, group, animal_data_list, update_datatables=True, allow_new_categories=False):
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
                raise ValueError(error_msg)

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
                    raise ValueError(json.dumps({'type': 'new_categories', 'data': new_categories}))

        # 2. Determine authorized keys for security
        authorized_keys = {'ID', 'Date of Birth', 'status'}
        if group.model:
            for assoc in group.model.analyte_associations:
                authorized_keys.add(assoc.analyte.name)

        # 3. Update or create Animal entities
        try:
            for animal_dict in animal_data_list:
                animal_id = animal_dict.get('ID')
                if not animal_id:
                    continue
                
                # Find existing animal or create new
                animal = Animal.query.filter_by(uid=animal_id, group_id=group.id).first()
                
                if animal:
                    # Update existing animal
                    if 'Date of Birth' in animal_dict:
                        dob_str = animal_dict['Date of Birth']
                        if dob_str:
                            try:
                                animal.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
                            except (ValueError, TypeError):
                                pass
                    
                    if 'sex' in animal_dict:
                        animal.sex = animal_dict.get('sex')
                    
                    if 'status' in animal_dict:
                        animal.status = animal_dict.get('status', 'alive')
                    
                    # Update measurements (merge with existing)
                    measurements = animal.measurements or {}
                    for key, value in animal_dict.items():
                        if key not in {'ID', 'Date of Birth', 'sex', 'status', 'Age (Days)', 'Blinded Group', 'Treatment Group'}:
                            measurements[key] = value
                    
                    animal.measurements = measurements
                    flag_modified(animal, "measurements")
                else:
                    # Create new animal
                    dob = None
                    if 'Date of Birth' in animal_dict:
                        try:
                            dob = datetime.strptime(animal_dict['Date of Birth'], '%Y-%m-%d').date()
                        except (ValueError, TypeError):
                            pass
                    
                    measurements = {}
                    for key, value in animal_dict.items():
                        if key not in {'ID', 'Date of Birth', 'sex', 'status', 'Age (Days)', 'Blinded Group', 'Treatment Group'}:
                            measurements[key] = value
                    
                    animal = Animal(
                        uid=animal_id,
                        group_id=group.id,
                        sex=animal_dict.get('sex'),
                        status=animal_dict.get('status', 'alive'),
                        date_of_birth=dob,
                        measurements=measurements if measurements else None
                    )
                    db.session.add(animal)
            
            # 4. Update project timestamp
            if group.project:
                group.project.updated_at = datetime.now(current_app.config['UTC_TZ'])

            db.session.flush()

            # 5. Update associated datatables if requested
            if update_datatables:
                # Reconstruct the ordered data for datatable update
                animals = Animal.query.filter_by(group_id=group.id).order_by(Animal.id).all()
                ordered_data = []
                for animal in animals:
                    animal_dict = {
                        'ID': animal.uid,
                        'Date of Birth': animal.date_of_birth.isoformat() if animal.date_of_birth else None,
                    }
                    if animal.sex:
                        animal_dict['sex'] = animal.sex
                    if animal.status and animal.status != 'alive':
                        animal_dict['status'] = animal.status
                    if animal.measurements:
                        animal_dict.update(animal.measurements)
                    ordered_data.append(animal_dict)
                
                # Determine column order
                final_ordered_keys = ['ID', 'Date of Birth', 'Age (Days)', 'Blinded Group', 'Treatment Group']
                if group.model_id:
                    associations = AnimalModelAnalyteAssociation.query.filter_by(
                        animal_model_id=group.model_id
                    ).order_by(AnimalModelAnalyteAssociation.order).all()
                    for assoc in associations:
                        if assoc.analyte.name not in final_ordered_keys:
                            final_ordered_keys.append(assoc.analyte.name)
                
                with suppress_audit():
                    update_associated_data_tables(db, group, ordered_data, final_ordered_keys)

            db.session.commit()
            return group
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving group data for {group.id}: {e}")
            raise

    def _convert_timestamps(self, data):
        if isinstance(data, dict):
            return {k: self._convert_timestamps(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._convert_timestamps(elem) for elem in data]
        elif hasattr(data, 'isoformat'):
            return data.date().isoformat() if hasattr(data, 'date') else data.isoformat()
        return data

    def delete_group(self, group):
        if group.project:
            group.project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        return self.delete(group)

    def reassign_group(self, group, target_project):
        original_project = group.project
        group.project_id = target_project.id
        target_project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        if original_project:
            original_project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        db.session.commit()
        return group

    def get_server_side_groups(self, user, filters, page, per_page, sort_column, sort_direction):
        from sqlalchemy.orm import joinedload
        from app.services.permission_service import PermissionService
        
        query = db.session.query(ExperimentalGroup) \
            .join(Project, ExperimentalGroup.project_id == Project.id) \
            .join(Team, ExperimentalGroup.team_id == Team.id) \
            .options(
                joinedload(ExperimentalGroup.project),
                joinedload(ExperimentalGroup.team),
                joinedload(ExperimentalGroup.model)
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