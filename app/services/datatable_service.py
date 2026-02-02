# app/services/datatable_service.py
from datetime import datetime, timedelta
import pandas as pd
from flask_babel import lazy_gettext as _l

from sqlalchemy import or_

from app.extensions import db
from app.models import DataTable, ExperimentalGroup, ProtocolModel, Project
from app.services.base import BaseService
from app.services.calculation_service import CalculationService # Added
from app.permissions import check_datatable_permission

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
            group_animal_data = dt.group.animal_data or []
            exp_rows_dict = {row.row_index: row.row_data for row in dt.experiment_rows.all()}
            
            if dt.group.model and dt.group.model.analytes:
                animal_model_fields.update(a.name for a in dt.group.model.analytes)

            for i, animal_info in enumerate(group_animal_data):
                animal_id = animal_info.get('ID')
                if not animal_id:
                    continue

                merged_data = {**animal_info, **exp_rows_dict.get(i, {})}
                
                if dt.protocol and dt.protocol.analytes:
                    for analyte in dt.protocol.analytes:
                        if analyte.name in merged_data:
                            all_long_data.append({
                                'ID': animal_id,
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
        seen_animal_ids = set()
        for dt in datatables_to_process:
            for animal_info in (dt.group.animal_data or []):
                animal_id = animal_info.get('ID')
                if animal_id and animal_id not in seen_animal_ids:
                    all_animal_data_df.append(animal_info)
                    seen_animal_ids.add(animal_id)
        
        animal_df = pd.DataFrame(all_animal_data_df)
        if 'ID' not in animal_df.columns:
            return pd.DataFrame(), [_l("Could not find 'ID' column in animal data for merging.")], source_identifiers
        
        animal_df = animal_df.drop_duplicates(subset=['ID']).set_index('ID')
        
        pivoted_df = long_df.pivot_table(
            index='ID',
            columns='measurement_label',
            values='analyte_value',
            aggfunc='first'
        )
        
        final_df = animal_df.join(pivoted_df, how='left')
        
        animal_cols_ordered = sorted([col for col in final_df.columns if col in animal_model_fields and col != 'ID'])
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
        animal_data = group.animal_data or []
        animal_ids = [animal.get('ID') for animal in animal_data if animal.get('ID')]
        if not animal_ids:
            return None, ["No animals found in group."], []

        # Structure: {animal_id: {analyte_name: [(date, value), ...]}}
        concatenated_data = {aid: {} for aid in animal_ids}

        for dt in datatables:
            dt_date = dt.date
            # Get experiment rows
            exp_rows = {row.row_index: row.row_data for row in dt.experiment_rows.all()}

            for idx, animal in enumerate(animal_data):
                animal_id = animal.get('ID')
                if not animal_id or idx not in exp_rows:
                    continue

                row_data = exp_rows[idx]
                for analyte in analytes:
                    if analyte.name in row_data and row_data[analyte.name] is not None:
                        if analyte.name not in concatenated_data[animal_id]:
                            concatenated_data[animal_id][analyte.name] = []
                        concatenated_data[animal_id][analyte.name].append((dt_date, row_data[analyte.name]))

        # Sort each list by date
        for aid in concatenated_data:
            for analyte_name in concatenated_data[aid]:
                concatenated_data[aid][analyte_name].sort(key=lambda x: x[0])


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
            updates: Dict of {row_index: {col_name: value}}
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
        rows_by_index = {r.row_index: r for r in existing_rows}
        
        # Prepare for Animal Sync
        group = data_table.group
        animals_by_uid = {}
        if group:
            from app.models import Animal
            animals_query = Animal.query.filter_by(group_id=group.id).all()
            animals_by_uid = {a.uid: a for a in animals_query}
            
            # Identify fields that belong to the Animal Model (to sync)
            animal_model_fields = set()
            if group.model and group.model.analytes:
                animal_model_fields = {a.name for a in group.model.analytes}

        try:
            for r_idx, new_vals in updates.items():
                r_idx = int(r_idx)
                
                # A. Update ExperimentDataRow (Protocol Data)
                # Fetch existing data to merge
                exp_row = rows_by_index.get(r_idx)
                current_data = exp_row.row_data.copy() if exp_row and exp_row.row_data else {}
                
                # Include Animal Data in context for calculations (like Body Weight)
                if group and r_idx < len(group.animal_data):
                    anim_row = group.animal_data[r_idx]
                    current_data.update(anim_row)
                
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
                    exp_row = ExperimentDataRow(data_table_id=data_table.id, row_index=r_idx, row_data=protocol_data)
                    rows_by_index[r_idx] = exp_row # Cache for next loop
                    db.session.add(exp_row)
                
                # B. Sync to Animal Table (V2 Logic)
                # We sync updated values (including calculated ones!) if they belong to Animal Model
                if group and r_idx < len(group.animal_data):
                    animal_info = group.animal_data[r_idx]
                    animal_id = animal_info.get('ID')
                    
                    if animal_id and animal_id in animals_by_uid:
                        animal = animals_by_uid[animal_id]
                        measurements = animal.measurements or {}
                        modified = False
                        
                        # Sync any value in current_data that is an animal model field
                        for col, val in current_data.items():
                            if col in animal_model_fields:
                                # Update if changed or new
                                if measurements.get(col) != val:
                                    measurements[col] = val
                                    modified = True
                        
                        if modified:
                            animal.measurements = measurements
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(animal, "measurements")
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            from flask import current_app
            current_app.logger.error(f"Error saving datatable edits for {datatable_id}: {e}")
            raise

    def process_upload(self, datatable_id, df, protocol_field_names, id_col_name='ID'):
        """
        Process Excel upload, update ExperimentDataRows, and sync to Animal table.
        """
        data_table = db.session.get(DataTable, datatable_id)
        if not data_table:
            raise ValueError(_l("DataTable not found"))

        group = data_table.group
        # Map Animal IDs to Row Indices
        animal_id_to_row_index = {}
        for i, animal in enumerate(group.animal_data or []):
            animal_id = animal.get('ID')
            if animal_id is not None:
                animal_id_to_row_index[str(animal_id).strip()] = i
        
        updates_by_row = {} # row_index -> {col: val}
        
        for _, row in df.iterrows():
            animal_id_raw = row.get(id_col_name)
            if pd.isna(animal_id_raw): continue
            
            animal_id = str(animal_id_raw).strip()
            row_index = animal_id_to_row_index.get(animal_id)
            
            if row_index is not None:
                if row_index not in updates_by_row: updates_by_row[row_index] = {}
                
                for col, val in row.items():
                    if col == id_col_name: continue
                    # Basic cleaning (NaN -> None) handled by caller or here
                    if pd.isna(val): continue
                    updates_by_row[row_index][col] = val

        # Reuse single-row save logic effectively
        if updates_by_row:
            self.save_manual_edits(datatable_id, updates_by_row, protocol_field_names)
        
        return len(updates_by_row)