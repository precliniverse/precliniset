# app/services/group_service.py
import json
from datetime import datetime

from flask import current_app
from sqlalchemy.orm.attributes import flag_modified

from app.extensions import db
from app.helpers import update_associated_data_tables
# Added Team to imports
from app.models import (AnimalModel, AnimalModelAnalyteAssociation,
                        ExperimentalGroup, Project, EthicalApproval, 
                        ProjectEthicalApprovalAssociation, Team)
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
        group = self.create(
            name=name,
            project_id=project_id,
            team_id=team_id,
            owner_id=owner_id,
            model_id=model_id,
            animal_data=animal_data or []
        )
        return group

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
        """
        Validates and saves animal data to the group.
        """
        # 1. Validate Data Integrity
        if group.model:
            # Always run in non-strict mode to detect new categories even if not yet allowed
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
                    from app.models import Analyte
                    for analyte_id, new_values in new_categories.items():
                        analyte = db.session.get(Analyte, analyte_id)
                        if analyte:
                            # Split by semicolon and strip whitespace
                            existing = [v.strip() for v in (analyte.allowed_values or "").split(';') if v.strip()]
                            updated = existing + [v for v in new_values if v not in existing]
                            analyte.allowed_values = "; ".join(updated)
                            db.session.add(analyte)
                    db.session.flush()
                else:
                    # Return new categories in a structured way if not allowed yet
                    # This will be caught by the route and converted to a prompt
                    raise ValueError(json.dumps({'type': 'new_categories', 'data': new_categories}))

        # 2. Filter and Order Keys (Mass Assignment Protection)
        # We exclude Age (Days), Blinded Group, and Treatment Group from authorized_keys 
        # so they cannot be overwritten via XLSX upload or manual form injection.
        authorized_keys = {'ID', 'Date of Birth', 'status'}
        if group.model:
            for assoc in group.model.analyte_associations:
                authorized_keys.add(assoc.analyte.name)

        final_ordered_keys = ['ID', 'Date of Birth', 'Age (Days)', 'Blinded Group', 'Treatment Group']
        final_ordered_keys_set = set(final_ordered_keys)

        if group.model_id:
            associations = AnimalModelAnalyteAssociation.query.filter_by(
                animal_model_id=group.model_id
            ).order_by(AnimalModelAnalyteAssociation.order).all()
            for assoc in associations:
                if assoc.analyte.name not in final_ordered_keys_set:
                    final_ordered_keys.append(assoc.analyte.name)
                    final_ordered_keys_set.add(assoc.analyte.name)

        # Also authorized metadata fields from protocol datatables? 
        # Usually group animal_data is fixed by the animal model.
        
        ordered_data = []
        for animal in animal_data_list:
            # SECURITY FIX: Only allow authorized keys
            ordered_animal = {k: animal.get(k) for k in final_ordered_keys if k in animal and k in authorized_keys}
            # Special case for 'status' which might not be in final_ordered_keys but is legitimate
            if 'status' in animal:
                ordered_animal['status'] = animal['status']
            ordered_data.append(ordered_animal)

        # 3. Save
        group.animal_data = ordered_data
        flag_modified(group, "animal_data")
        
        if group.project:
            group.project.updated_at = datetime.now(current_app.config['UTC_TZ'])

        db.session.flush()

        if update_datatables:
            with suppress_audit():
                update_associated_data_tables(db, group, ordered_data, final_ordered_keys)

        db.session.commit()
        return group

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