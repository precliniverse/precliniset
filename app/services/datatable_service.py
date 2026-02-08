# app/services/datatable_service.py
from datetime import datetime, timedelta, timezone
import pandas as pd
from flask_babel import lazy_gettext as _l, gettext as _

from sqlalchemy import or_

from app.extensions import db
from app.models import DataTable, ExperimentalGroup, ProtocolModel, Project, Animal, ExperimentDataRow, User, AnimalModel
from app.services.base import BaseService
from app.services.calculation_service import CalculationService # Added
from app.permissions import check_datatable_permission, can_create_datatable_for_group
from app.decorators import transactional
from app.tasks import declare_tm_practice_task
from app.services.tm_connector import TrainingManagerConnector
from app.helpers import validate_and_convert, get_ordered_column_names, get_field_types

class DataTableService(BaseService):
    model = DataTable

    def __init__(self):
        super().__init__()

    def get_server_side_datatables(self, user, filters, page, per_page, sort_column, sort_direction):
        from sqlalchemy import or_ # Ensure import is available locally if not at top
        from sqlalchemy.orm import joinedload
        from app.services.permission_service import PermissionService

        query = db.session.query(DataTable) \
            .join(ExperimentalGroup, DataTable.group_id == ExperimentalGroup.id) \
            .join(ProtocolModel, DataTable.protocol_id == ProtocolModel.id) \
            .join(Project, ExperimentalGroup.project_id == Project.id) \
            .options(
                joinedload(DataTable.group).joinedload(ExperimentalGroup.project),
                joinedload(DataTable.protocol)
            )

        # Apply permissions: only accessible projects (optimized query)
        if not user.is_super_admin:
            perm_service = PermissionService()
            visible_projects_query = perm_service.get_visible_projects_query(user)
            accessible_project_ids = [p.id for p in visible_projects_query.with_entities(Project.id).all()]
            query = query.filter(ExperimentalGroup.project_id.in_(accessible_project_ids))

        total_records = query.count()

        if 'project_id' in filters and filters['project_id']:
            # Ensure we filter by the Project ID joined via ExperimentalGroup
            query = query.filter(ExperimentalGroup.project_id == filters['project_id'])
            
        # Apply filters
        if 'group_id' in filters and filters['group_id']:
            query = query.filter(DataTable.group_id == filters['group_id'])
        if 'protocol_id' in filters and filters['protocol_id']:
            query = query.filter(DataTable.protocol_id == filters['protocol_id'])
        
        # Date range filter
        if 'date_from' in filters and filters['date_from']:
            query = query.filter(DataTable.date >= filters['date_from'])
        if 'date_to' in filters and filters['date_to']:
            query = query.filter(DataTable.date <= filters['date_to'])

        # Archive Status Filter
        # is_archived = True: Show ONLY archived (Group OR Project is archived)
        # is_archived = False: Show ONLY active (Group AND Project are active)
        # is_archived = None (or 'all'): Show EVERYTHING
        if 'is_archived' in filters and filters['is_archived'] is not None:
            if filters['is_archived'] is True:
                # Show items where Group IS archived OR Project IS archived
                query = query.filter(
                    or_(
                        ExperimentalGroup.is_archived == True,
                        Project.is_archived == True
                    )
                )
            elif filters['is_archived'] is False:
                # Show items where Group is NOT archived AND Project is NOT archived
                query = query.filter(
                    ExperimentalGroup.is_archived == False,
                    Project.is_archived == False
                )

        search_value = filters.get('search_value')
        if search_value:
            search_pattern = f"%{search_value}%"
            query = query.filter(
                (DataTable.date.ilike(search_pattern)) | \
                (ExperimentalGroup.name.ilike(search_pattern)) | \
                (ProtocolModel.name.ilike(search_pattern)) | \
                (Project.name.ilike(search_pattern))
            )

        filtered_records = query.count()

        # Apply sorting
        sort_column_map = {
            'name': DataTable.date, # Defaulting name to date for sorting if name col used for date
            'group_name': ExperimentalGroup.name,
            'protocol_name': ProtocolModel.name,
            'project_name': Project.name,
            'created_at': DataTable.id, # Fallback
            'updated_at': DataTable.id
        }
        
        column_to_sort = sort_column_map.get(sort_column, DataTable.date) # Default sort
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

    def aggregate_selected_datatables(self, selected_datatable_ids_str_list):
        """
        Aggregates data from multiple datatables into a single DataFrame.
        """
        if not selected_datatable_ids_str_list:
            return None, [_l("No datatables were selected.")], []

        try:
            selected_datatable_ids = sorted([int(id_str) for id_str in selected_datatable_ids_str_list if str(id_str).isdigit()])
        except ValueError:
            return None, [_l("Invalid datatable ID received.")], []

        datatables_to_process = []
        errors = []
        source_identifiers = []
        
        for dt_id in selected_datatable_ids:
            dt = db.session.get(DataTable, dt_id)
            if not dt or not dt.group:
                errors.append(_l("DataTable with ID {dt_id} not found or group missing.").format(dt_id=dt_id))
                continue
            if not check_datatable_permission(dt, 'read'):
                errors.append(_l("Permission denied for DataTable {dt_id} from group '{group_name}'.").format(dt_id=dt_id, group_name=dt.group.name))
                continue
            datatables_to_process.append(dt)
            source_identifiers.append(f"{dt.group.name}-{dt.protocol.name}-{dt.date}")

        if not datatables_to_process:
            return None, errors, source_identifiers

        all_long_data = []
        animal_model_fields = set()

        for dt in datatables_to_process:
            exp_rows_dict = {row.row_index: row.row_data for row in dt.experiment_rows.all()}
            
            if dt.group.model and dt.group.model.analytes:
                animal_model_fields.update(a.name for a in dt.group.model.analytes)

            # Use animals relationship instead of animal_data
            for i, animal in enumerate(sorted(dt.group.animals, key=lambda a: a.id)):
                animal_info = animal.to_dict()
                animal_id = animal_info.get('uid')
                if not animal_id:
                    continue

                merged_data = {**animal_info, **exp_rows_dict.get(i, {})}
                
                if dt.protocol and dt.protocol.analytes:
                    for analyte in dt.protocol.analytes:
                        if analyte.name in merged_data:
                            all_long_data.append({
                                'uid': animal_id,
                                'analyte_name': analyte.name,
                                'analyte_value': merged_data[analyte.name],
                                'protocol_name': dt.protocol.name,
                                'datatable_date': dt.date,
                                # Meta info for tracking
                                '_source_datatable_id': dt.id,
                                '_source_experimental_group_name': dt.group.name,
                                '_source_protocol_name': dt.protocol.name,
                                '_source_datatable_date': dt.date
                            })

        if not all_long_data:
            return pd.DataFrame(), errors, source_identifiers

        long_df = pd.DataFrame(all_long_data)
        
        long_df['measurement_label'] = long_df['analyte_name'] + '_' + long_df['protocol_name'] + '_' + long_df['datatable_date']
        
        all_animal_data_df = []
        seen_animal_uids = set()
        for dt in datatables_to_process:
            for animal in dt.group.animals:
                if animal.uid not in seen_animal_uids:
                    all_animal_data_df.append(animal.to_dict())
                    seen_animal_uids.add(animal.uid)
        
        animal_df = pd.DataFrame(all_animal_data_df)
        if 'uid' not in animal_df.columns:
            return pd.DataFrame(), [_l("Could not find 'uid' column in animal data for merging.")], source_identifiers
        
        animal_df = animal_df.drop_duplicates(subset=['uid']).set_index('uid')
        
        pivoted_df = long_df.pivot_table(
            index='uid',
            columns='measurement_label',
            values='analyte_value',
            aggfunc='first'
        )
        
        final_df = animal_df.join(pivoted_df, how='left')
        
        animal_cols_ordered = sorted([col for col in final_df.columns if col in animal_model_fields and col != 'uid'])
        measurement_cols_ordered = sorted([col for col in final_df.columns if col not in animal_model_fields])
        final_column_order = animal_cols_ordered + measurement_cols_ordered
        
        final_df = final_df[final_column_order].reset_index()

        return final_df, errors, source_identifiers

    def get_concatenated_analyte_data_for_group(self, group_id, user):
        """
        Concatenates analyte data from all datatables of a group, sorted chronologically.
        Returns data structured for frontend display.
        """
        from app.models import ExperimentalGroup, AnalyteDataType
        from sqlalchemy.orm import joinedload
        from app.permissions import check_group_permission

        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            return None, ["Group not found."], []

        if not check_group_permission(group, 'read'):
            return None, ["Permission denied."], []

        # Get all datatables for the group, ordered by date
        datatables = db.session.query(DataTable).filter_by(group_id=group_id).options(
            joinedload(DataTable.protocol)
        ).order_by(DataTable.date).all()

        if not datatables:
            return None, ["No datatables found for this group."], []

        # Collect all analytes across protocols
        analyte_set = set()
        for dt in datatables:
            if dt.protocol and dt.protocol.analytes:
                for analyte in dt.protocol.analytes:
                    analyte_set.add(analyte)

        analytes = sorted(list(analyte_set), key=lambda a: a.name)
        analyte_info = {a.id: {'id': a.id, 'name': a.name, 'type': a.data_type.value, 'unit': a.unit or ''} for a in analytes}

        # Get animal data
        animals = sorted(group.animals, key=lambda a: a.id)
        animal_uids = [a.uid for a in animals]
        if not animal_uids:
            return None, ["No animals found in group."], []

        # Structure: {animal_id: {analyte_name: [(date, value), ...]}}
        concatenated_data = {uid: {} for uid in animal_uids}

        for dt in datatables:
            dt_date = dt.date
            # Get experiment rows
            exp_rows = {row.row_index: row.row_data for row in dt.experiment_rows.all()}

            for idx, animal in enumerate(animals):
                animal_id = animal.uid
                if idx not in exp_rows:
                    continue

                row_data = exp_rows[idx]
                for analyte in analytes:
                    if analyte.name in row_data and row_data[analyte.name] is not None:
                        if analyte.name not in concatenated_data[animal_id]:
                            concatenated_data[animal_id][analyte.name] = []
                        protocol_name = dt.protocol.name if dt.protocol else 'Unknown'
                        concatenated_data[animal_id][analyte.name].append({
                            'date': dt_date, 
                            'value': row_data[analyte.name],
                            'protocol': protocol_name
                        })

        # Sort each list by date
        for aid in concatenated_data:
            for analyte_name in concatenated_data[aid]:
                concatenated_data[aid][analyte_name].sort(key=lambda x: x['date'])


        return {
            'analytes': analyte_info,
            'animal_data': concatenated_data,
            'datatables': [{'id': dt.id, 'protocol_name': dt.protocol.name if dt.protocol else 'Unknown', 'date': dt.date} for dt in datatables],
            'group_name': group.name
        }, [], []

    def save_manual_edits(self, datatable_id, updates, protocol_field_names):
        """
        Save manual grid edits to ExperimentDataRow and sync to Animal table.
        
        Args:
            datatable_id: ID of the DataTable
            updates: Dict of {animal.id: {col_name: value}}
            protocol_field_names: List of protocol field names to save to ExperimentDataRow
        """
        data_table = db.session.get(DataTable, datatable_id)
        if not data_table:
            raise ValueError(_l("DataTable not found"))

        # Initialize Services
        calc_service = CalculationService()
        has_calc = any(a.calculation_formula for a in data_table.protocol.analyte_associations) if data_table.protocol else False

        # 1. Update ExperimentDataRows
        existing_rows = data_table.experiment_rows.all()
        rows_by_animal_id = {r.animal_id: r for r in existing_rows}
        
        # Prepare for Animal Sync
        group = data_table.group
        animals_by_id = {}
        if group:
            animals_query = Animal.query.filter_by(group_id=group.id).all()
            animals_by_id = {a.id: a for a in animals_query}
            
            # Identify fields that belong to the Animal Model (to sync)
            animal_model_fields = set()
            if group.model and group.model.analytes:
                animal_model_fields = {a.name for a in group.model.analytes}

        try:
            for animal_id, new_vals in updates.items():
                animal_id = int(animal_id)
                
                # A. Update ExperimentDataRow (Protocol Data)
                # Fetch existing data to merge
                exp_row = rows_by_animal_id.get(animal_id)
                current_data = exp_row.row_data.copy() if exp_row and exp_row.row_data else {}
                
                # Include Animal Data in context for calculations (like Body Weight)
                animal = animals_by_id.get(animal_id)
                if animal:
                    current_data.update(animal.to_dict())
                
                # Merge updates (overwrites existing)
                current_data.update(new_vals)
                
                # Apply Calculations
                if has_calc and data_table.protocol:
                     current_data = calc_service.calculate_row(current_data, data_table.protocol.analyte_associations)

                # Filter to protocol fields only for ExperimentDataRow storage
                protocol_data = {k: v for k, v in current_data.items() if k in protocol_field_names}
                
                if exp_row:
                    if exp_row.row_data != protocol_data:
                        exp_row.row_data = protocol_data
                else:
                    exp_row = ExperimentDataRow(data_table_id=data_table.id, animal_id=animal_id, row_data=protocol_data)
                    rows_by_animal_id[animal_id] = exp_row # Cache for next loop
                    db.session.add(exp_row)
                
                # B. Sync to Animal Table (V2 Logic)
                # We sync updated values (including calculated ones!) if they belong to Animal Model
                if animal:
                    measurements = animal.measurements or {}
                    modified = False
                    
                    # Mapping of animal core fields for sync
                    core_fields_map = {
                        'sex': 'sex',
                        'status': 'status',
                        'date_of_birth': 'date_of_birth',
                        'date of birth': 'date_of_birth'
                    }

                    # Sync values if they belong to Animal Model or are core fields
                    for col, val in current_data.items():
                        col_lower = col.lower()
                        
                        # 1. Update Core Fields
                        if col_lower in core_fields_map:
                            attr_name = core_fields_map[col_lower]
                            # Special handling for dates
                            if attr_name == 'date_of_birth' and isinstance(val, str):
                                try:
                                    val = datetime.strptime(val.split('T')[0], '%Y-%m-%d').date()
                                except (ValueError, TypeError):
                                    pass
                            
                            if getattr(animal, attr_name) != val:
                                setattr(animal, attr_name, val)
                                modified = True
                        
                        # 2. Update Measurements
                        elif col in animal_model_fields or col_lower in {a.lower() for a in animal_model_fields}:
                            # Find the actual case sensitive name in animal_model_fields if it was a case-insensitive match
                            actual_col = next((a for a in animal_model_fields if a.lower() == col_lower), col)
                            if measurements.get(actual_col) != val:
                                measurements[actual_col] = val
                                modified = True
                        
                        # 3. Longitudinal Weight Sync: Save weight to measurements['last_weight']
                        elif col_lower in ['weight', 'body weight', 'bodyweight']:
                            if measurements.get('last_weight') != val:
                                measurements['last_weight'] = val
                                modified = True
                    
                    if modified:
                        animal.measurements = measurements
                        animal.updated_at = datetime.now(timezone.utc)
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(animal, "measurements")
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            from flask import current_app
            current_app.logger.error(f"Error saving datatable edits for {datatable_id}: {e}")
            raise

    def process_upload(self, datatable_id, df, protocol_field_names, id_col_name='uid'):
        """
        Process Excel upload, update ExperimentDataRows, and sync to Animal table.
        """
        data_table = db.session.get(DataTable, datatable_id)
        if not data_table:
            raise ValueError(_l("DataTable not found"))

        group = data_table.group
        # Map Animal UIDs to Animal IDs
        animal_uid_to_id = {a.uid: a.id for a in group.animals}
        
        updates_by_row = {} # animal.id -> {col: val}
        
        for _, row in df.iterrows():
            animal_uid_raw = row.get(id_col_name)
            if pd.isna(animal_uid_raw): continue
            
            animal_uid = str(animal_uid_raw).strip()
            animal_id = animal_uid_to_id.get(animal_uid)
            
            if animal_id is not None:
                if animal_id not in updates_by_row: updates_by_row[animal_id] = {}
                
                for col, val in row.items():
                    if col == id_col_name: continue
                    # Basic cleaning (NaN -> None) handled by caller or here
                    if pd.isna(val): continue
                    updates_by_row[animal_id][col] = val

        # Reuse single-row save logic effectively
        if updates_by_row:
            self.save_manual_edits(datatable_id, updates_by_row, protocol_field_names)
        
        return len(updates_by_row)

    @transactional
    def update_datatable_from_grid(self, datatable_id: int, form_data: dict) -> tuple[bool, bool, list[str]]:
        """
        Processes grid submission from the frontend.
        Returns (data_changed, validation_errors_occurred, error_messages)
        """
        data_table = db.session.get(DataTable, datatable_id)
        if not data_table:
            raise ValueError(_l("DataTable not found"))

        column_names = get_ordered_column_names(data_table)
        protocol_analytes_ordered = []
        if data_table.protocol:
            from app.models import ProtocolAnalyteAssociation
            protocol_associations = ProtocolAnalyteAssociation.query.filter_by(
                protocol_model_id=data_table.protocol.id
            ).order_by(ProtocolAnalyteAssociation.order).all()
            protocol_analytes_ordered = [assoc.analyte for assoc in protocol_associations]

        protocol_analytes_map = {a.name: a for a in protocol_analytes_ordered} if protocol_analytes_ordered else {}
        protocol_field_names = [a.name for a in protocol_analytes_ordered] if protocol_analytes_ordered else []
        
        num_expected_rows = len(data_table.group.animals) if data_table.group else 0
        animals = sorted(data_table.group.animals, key=lambda a: a.id)
        animal_map = {i: animal for i, animal in enumerate(animals)}

        existing_rows_query = data_table.experiment_rows
        existing_data_rows_dict = {r.animal_id: r.row_data for r in existing_rows_query.all()}

        validation_errors, data_changed = False, False
        error_messages = []
        updates = {} # this will be keyed by animal.id now

        for k, v_form in form_data.items():
            if k in ['csrf_token', 'submit_grid'] or not k.startswith('cell_'):
                continue
            parts = k.split('_')
            if len(parts) == 3:
                try:
                    r_idx, c_idx = int(parts[1]), int(parts[2])
                    animal = animal_map.get(r_idx)
                    if not animal:
                        continue

                    if 0 <= r_idx < num_expected_rows and 0 <= c_idx < len(column_names):
                        col_name_manual = column_names[c_idx]
                        
                        if col_name_manual in protocol_field_names:
                            analyte_obj_manual = protocol_analytes_map.get(col_name_manual)
                            if analyte_obj_manual:
                                try:
                                    converted_value = validate_and_convert(v_form, analyte_obj_manual, col_name_manual, r_idx)
                                    current_row_data = existing_data_rows_dict.get(animal.id, {})
                                    existing_value = current_row_data.get(col_name_manual)
                                    
                                    is_different = False
                                    if existing_value is None and converted_value is not None: is_different = True
                                    elif existing_value is not None and converted_value is None: is_different = True
                                    elif str(existing_value) != str(converted_value): is_different = True
                                    
                                    if is_different:
                                        if animal.id not in updates: updates[animal.id] = {}
                                        updates[animal.id][col_name_manual] = converted_value
                                        data_changed = True
                                except ValueError as e:
                                    error_messages.append(f"Row {r_idx+1} Col '{col_name_manual}': {str(e)}")
                                    validation_errors = True
                except Exception as e:
                    from flask import current_app
                    current_app.logger.error(f"Error parsing grid cell {k}: {e}")

        if data_changed and not validation_errors:
            self.save_manual_edits(data_table.id, updates, protocol_field_names)
        
        return data_changed, validation_errors, error_messages

    def create_datatable_from_form(self, form, current_user):
        """Create a datatable from form data using service logic."""
        group_id = form.group.data
        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            raise ValueError(_l("Invalid experimental group selected."))

        if not can_create_datatable_for_group(group):
            raise ValueError(_l("You do not have permission to create DataTables for this group."))

        protocol_model_id = form.protocol.data
        protocol_model = db.session.get(ProtocolModel, protocol_model_id)
        if not protocol_model:
            raise ValueError(_l("Invalid protocol model selected."))

        date_str = form.date.data.strip()
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise ValueError(_l("Invalid date format. Please use YYYY-MM-DD."))

        # --- SEVERITY AND DATE CHECK ---
        ethical_approval = group.ethical_approval
        protocol_severity = protocol_model.severity
        datatable_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

        if ethical_approval:
            ea_severity = ethical_approval.overall_severity
            if protocol_severity > ea_severity:
                raise ValueError(_("Protocol Severity Mismatch: The selected protocol ('%(protocol_name)s' - Severity: %(protocol_severity)s) has a higher severity than the group's ethical approval ('%(ea_ref)s' - Max Severity: %(ea_severity)s). DataTable cannot be created.",
                                  protocol_name=protocol_model.name,
                                  protocol_severity=protocol_severity.value,
                                  ea_ref=ethical_approval.reference_number,
                                  ea_severity=ea_severity.value))

            ea_start_date = ethical_approval.start_date
            ea_end_date = ethical_approval.end_date
            if (ea_start_date and datatable_date_obj < ea_start_date) or \
               (ea_end_date and datatable_date_obj > ea_end_date):
                raise ValueError(_("Date Out of Range: The DataTable date (%(dt_date)s) is outside the ethical approval's effective period (%(start)s to %(end)s).",
                                  dt_date=datatable_date_obj.strftime('%Y-%m-%d'),
                                  start=ea_start_date.strftime('%Y-%m-%d') if ea_start_date else 'N/A',
                                  end=ea_end_date.strftime('%Y-%m-%d') if ea_end_date else 'N/A'))

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
                                # Store warning for later display
                                data_table._validation_warning = msg
                except Exception as e:
                    current_app.logger.error(f"Error validating skills with Training Manager: {e}")
        
        data_table.housing_condition_set_id = form.housing_condition_set_id.data if form.housing_condition_set_id.data else None

        db.session.add(data_table)
        db.session.flush() 

        animals = sorted(group.animals, key=lambda a: a.id)
        if animals:
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

            for i, animal in enumerate(animals):
                animal_info_ordered = {}
                current_animal_dict = animal.to_dict()
                for col_name in ordered_cols_for_new_dt:
                    if col_name in current_animal_dict:
                        animal_info_ordered[col_name] = current_animal_dict[col_name]

                row_data = {**combined_defaults_ordered, **animal_info_ordered}
                exp_row = ExperimentDataRow(data_table_id=data_table.id, animal_id=animal.id, row_data=row_data)
                db.session.add(exp_row)

        db.session.commit()

        # Declare practice if protocol has required skills
        if protocol_model.external_skill_ids and data_table.assigned_to_id:
            user = db.session.get(User, data_table.assigned_to_id)
            if user:
                declare_tm_practice_task.delay(user.email, protocol_model.external_skill_ids, data_table.date, 'DataTable creation')

        return data_table

    def get_recent_datatables_for_form(self, current_user, project_id, include_archived, group_id_prefill_str):
        """Get recent datatables for the form display."""
        base_query = db.session.query(DataTable) \
            .join(ExperimentalGroup, DataTable.group_id == ExperimentalGroup.id) \
            .join(Project, ExperimentalGroup.project_id == Project.id)

        if project_id:
            if not include_archived:
                base_query = base_query.filter(ExperimentalGroup.project_id == project_id)
                base_query = base_query.filter(ExperimentalGroup.is_archived == False)
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
                if dt.group:
                    animals = sorted(dt.group.animals, key=lambda a: a.id)
                    total_animals = len(animals)
                    animals_alive = sum(1 for animal in animals if animal.status != 'dead')
                    dt.total_animals = total_animals
                    dt.animals_alive = animals_alive
                    processed_data_tables.append(dt)
        
        return processed_data_tables
