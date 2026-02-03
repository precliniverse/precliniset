# app/services/import_wizard_service.py
import pandas as pd
import json
import os
import math
from asteval import Interpreter
from flask import current_app
from sqlalchemy.orm.attributes import flag_modified
from app.extensions import db
from app.models import ProtocolModel, Analyte, ExperimentalGroup, ExperimentDataRow, DataTable, ImportTemplate
from app.services.audit_service import log_action

class ImportWizardService:
    @staticmethod
    def find_anchor(file_path, anchor_text):
        """Finds the line number where anchor_text appears."""
        if not anchor_text:
            return 0
        try:
            with open(file_path, 'r', errors='ignore') as f:
                for i, line in enumerate(f):
                    if anchor_text in line:
                        return i + 1 # Return 1-based line index
            return 0
        except Exception:
            return 0

    @staticmethod
    def secure_eval(expression, value):
        """Evaluates a mathematical expression safely with 'x' as the input value using asteval."""
        if not expression:
            return value
        
        try:
            aeval = Interpreter()
            aeval.symtable['x'] = value
            # Whitelist some common math functions if not already there
            # Interpreter already has many math functions by default
            result = aeval(expression)
            
            if len(aeval.error) > 0:
                return value
                
            return result
        except Exception as e:
            return value

    @staticmethod
    def parse_file(file_path, skip_rows=0, anchor_text=None, anchor_offset=0, row_interval=1):
        """Parses the uploaded file and returns headers and first 5 rows for preview."""
        row_interval = int(row_interval)
        ext = os.path.splitext(file_path)[1].lower()
                
        # Calculate final skip_rows if anchor is provided
        final_skip = skip_rows
        if anchor_text:
            anchor_line = ImportWizardService.find_anchor(file_path, anchor_text)
            if anchor_line > 0:
                final_skip = anchor_line + anchor_offset

        try:
            if ext == '.csv':
                
                df = pd.read_csv(file_path, skiprows=final_skip)
            elif ext in ['.xls', '.xlsx']:
                
                df = pd.read_excel(file_path, skiprows=final_skip)
            elif ext == '.json':
                # Read JSON file, handling NaN explicitly as it's not valid JSON
                import re
                import io
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Replace 'NaN' (not valid JSON) with 'null' (valid JSON)
                # This handles cases like: "key": NaN, or [..., NaN, ...]
                content = re.sub(r'(?<![a-zA-Z0-9])NaN(?![a-zA-Z0-9])', 'null', content)
                
                df = pd.read_json(io.StringIO(content))
            elif ext == '.txt':
                
                df = pd.read_csv(file_path, sep=None, engine='python', skiprows=final_skip)
            else:
                raise ValueError(f"Unsupported file format: {ext}")
            
            # SECURITY COMPATIBILITY: Strip leading single quotes added during export
            # This allows "Round-Trip" of sanitized Excel files
            if df is not None:
                for col in df.select_dtypes(include=['object']).columns:
                    # Remove leading ' if it exists and the string looks like a formula injection attempt
                    df[col] = df[col].apply(
                        lambda x: x[1:] if isinstance(x, str) and x.startswith("'") and len(x) > 1 and x[1] in ['=', '+', '-', '@'] else x
                    )

            # Apply row interval
            if row_interval > 1:
                df = df.iloc[::row_interval]
            
            # Replace NaN values with None for JSON serialization
            df = df.replace(math.nan, None)

            headers = df.columns.tolist()
            preview = df.head(5).to_dict(orient='records')
            return {
                'headers': headers,
                'preview': preview,
                'total_rows': len(df),
                'detected_skip': final_skip
            }
        except Exception as e:
            
            raise

    @staticmethod
    def validate_animal_ids(file_path, group_id, animal_id_column, pipeline_id=None):
        """Validates that animal IDs in the file exist in the ExperimentalGroup."""
        ext = os.path.splitext(file_path)[1].lower()
        
        if pipeline_id:
            from app.services.import_pipeline_service import ImportPipelineService
            pipeline_service = ImportPipelineService()
            # Execute script to get transformed data
            data = pipeline_service.execute_pipeline(pipeline_id, file_path)
            df = pd.DataFrame(data)
        elif ext == '.csv':
            df = pd.read_csv(file_path)
        elif ext in ['.xls', '.xlsx']:
            df = pd.read_excel(file_path)
        elif ext == '.json':
            # Read JSON file, handling NaN explicitly as it's not valid JSON
            import re
            import io
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Replace 'NaN' (not valid JSON) with 'null' (valid JSON)
            content = re.sub(r'(?<![a-zA-Z0-9])NaN(?![a-zA-Z0-9])', 'null', content)
            df = pd.read_json(io.StringIO(content))
        else:
            df = pd.read_csv(file_path, sep=None, engine='python')

        # SECURITY COMPATIBILITY: Strip leading single quotes added during export
        # This allows "Round-Trip" of sanitized Excel files
        if df is not None:
            for col in df.select_dtypes(include=['object']).columns:
                # Remove leading ' if it exists and the string looks like a formula injection attempt
                df[col] = df[col].apply(
                    lambda x: x[1:] if isinstance(x, str) and x.startswith("'") and len(x) > 1 and x[1] in ['=', '+', '-', '@'] else x
                )

        if animal_id_column not in df.columns:
            return {'valid': False, 'error': f"Column '{animal_id_column}' not found in file."}

        file_animal_ids = set(df[animal_id_column].astype(str).unique())

        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            return {'valid': False, 'error': "Experimental Group not found."}


        valid_animal_ids = {str(a.uid).strip() for a in group.animals}


        missing_ids = file_animal_ids - valid_animal_ids
        
        return {
            'valid': len(missing_ids) == 0,
            'missing_ids': list(missing_ids),
            'total_found': len(file_animal_ids)
        }

    @staticmethod
    def process_import(file_path, data_table_id, mapping, animal_id_column, user_id,
                       skip_rows=0, anchor_text=None, anchor_offset=0, row_interval=1, advanced_logic=None, pipeline_id=None):
        """
        Processes the import.
        If pipeline_id is provided, executes the script to get the DataFrame.
        Otherwise, reads from the file.
        """
        row_interval = int(row_interval)
        
        # FIX: Initialize variable to prevent UnboundLocalError in Pipeline mode
        final_skip = 0 
        
        data_table = db.session.get(DataTable, data_table_id)
        if not data_table:
            raise ValueError("DataTable not found")

        # Get the protocol associated with the data table
        protocol = db.session.get(ProtocolModel, data_table.protocol_id)
        if not protocol:
            raise ValueError(f"Protocol with ID {data_table.protocol_id} not found for DataTable {data_table_id}")

        # Create a set of valid analyte IDs for this protocol for efficient lookup
        protocol_analyte_ids = {a.id for a in protocol.analytes}

        # Fetch existing ExperimentDataRow for this data_table
        existing_experiment_rows = db.session.query(ExperimentDataRow).filter_by(data_table_id=data_table.id).all()
        
        # Map existing rows by animal_id for efficient lookup and find max row_index
        existing_rows_by_animal_id = {}
        max_existing_row_index = -1
        for erow in existing_experiment_rows:
            if erow.row_data:
                # Name-resilient ID lookup
                aid = erow.row_data.get('ID') or erow.row_data.get('id') or erow.row_data.get('uid')
                if aid is not None:
                    existing_rows_by_animal_id[str(aid)] = erow
            if erow.row_index > max_existing_row_index:
                max_existing_row_index = erow.row_index

        next_row_index = max_existing_row_index + 1

        # Identify fields that belong to the Animal Model (to sync)
        animal_model_fields = set()
        animals_by_uid = {}
        if data_table.group:
            if data_table.group.model and data_table.group.model.analytes:
                animal_model_fields = {a.name for a in data_table.group.model.analytes}
            from app.models import Animal
            animals_by_uid = {a.uid: a for a in data_table.group.animals}

        # --- LOAD DATA (Pipeline vs File) ---
        if pipeline_id:
            try:
                # Local import to avoid circular dependency
                from app.services.import_pipeline_service import ImportPipelineService
                pipeline_service = ImportPipelineService()
                data = pipeline_service.execute_pipeline(pipeline_id, file_path)
                df = pd.DataFrame(data)
            except Exception as e:
                raise ValueError(f"Pipeline execution failed: {str(e)}")
        else:
            # Calculate final skip_rows
            final_skip = skip_rows
            if anchor_text:
                anchor_line = ImportWizardService.find_anchor(file_path, anchor_text)
                if anchor_line > 0:
                    final_skip = anchor_line + anchor_offset

            ext = os.path.splitext(file_path)[1].lower()
            try:
                if ext == '.csv':
                    df = pd.read_csv(file_path, skiprows=final_skip)
                elif ext in ['.xls', '.xlsx']:
                    df = pd.read_excel(file_path, skiprows=final_skip)
                elif ext == '.json':
                    df = pd.read_json(file_path)
                else:
                    df = pd.read_csv(file_path, sep=None, engine='python', skiprows=final_skip)
            except Exception as e:
                raise ValueError(f"Error reading file: {str(e)}")

        # SECURITY COMPATIBILITY: Strip leading single quotes added during export
        if df is not None:
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].apply(
                    lambda x: x[1:] if isinstance(x, str) and x.startswith("'") and len(x) > 1 and x[1] in ['=', '+', '-', '@'] else x
                )

        # Apply row interval
        if row_interval > 1:
            df = df.iloc[::row_interval]

        # validation
        if animal_id_column not in df.columns:
            raise ValueError(f"Animal ID column '{animal_id_column}' not found in data")

        # Prep advanced logic map
        logic_map = {}
        if advanced_logic:
            logic_map = {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in advanced_logic.items()}

        # Map and save
        results = []
        for index, row in df.iterrows():
            animal_id = str(row[animal_id_column])
            
            # Prepare row_data for the current record, including default ID
            current_row_data = {'ID': animal_id}
            
            # If mapping is provided (Manual or Auto-Mapped in JS), use it
            if mapping:
                for file_col, analyte_id in mapping.items():
                    if analyte_id and file_col in row:
                        # Ensure the analyte ID is valid for the protocol
                        if analyte_id not in protocol_analyte_ids:
                            current_app.logger.warning(f"Analyte ID {analyte_id} from mapping is not associated with Protocol ID {protocol.id}. Importing anyway.")

                        analyte = db.session.get(Analyte, analyte_id)
                        if analyte:
                            val = row[file_col]
                            if isinstance(val, float) and math.isnan(val):
                                val = None
                            
                            # Apply advanced logic
                            if analyte.id in logic_map:
                                try:
                                    val = ImportWizardService.secure_eval(logic_map[analyte.id], val)
                                except Exception:
                                    pass 
                            
                            current_row_data[analyte.name] = val
            
            # Check if an existing row for this animal_id needs to be updated
            if animal_id in existing_rows_by_animal_id:
                erow = existing_rows_by_animal_id[animal_id]
                erow.row_data.update(current_row_data)
                flag_modified(erow, "row_data")
                db.session.add(erow)
                results.append(erow.row_data)
            else:
                new_row = ExperimentDataRow(
                    data_table_id=data_table.id,
                    row_index=next_row_index,
                    row_data=current_row_data
                )
                db.session.add(new_row)
                results.append(new_row.row_data)
                next_row_index += 1

            # --- SYNC TO ANIMAL TABLE ---
            if animal_id in animals_by_uid:
                animal = animals_by_uid[animal_id]
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
                for col, val in current_row_data.items():
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
                
                if modified:
                    animal.measurements = measurements
                    from datetime import timezone
                    animal.updated_at = datetime.now(timezone.utc)
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(animal, "measurements")
                    db.session.add(animal)

        # Audit Log
        log_action(
            resource_type='DataTable',
            resource_id=data_table.id,
            action='IMPORT_RAW_DATA',
            details=f"Imported {len(df)} rows via {'Pipeline ' + str(pipeline_id) if pipeline_id else 'File Upload'}",
            new_value={'row_count': len(df), 'mapping': mapping, 'advanced_options': {'skip_rows': final_skip, 'anchor': anchor_text, 'anchor_offset': anchor_offset, 'row_interval': row_interval, 'logic': advanced_logic}}
        )

        db.session.commit()

        return len(results)

    @staticmethod
    def save_template(name, protocol_model_id, mapping, skip_rows=0, anchor_text=None, anchor_offset=0, row_interval=1, advanced_logic=None):
        """Saves a mapping template for a protocol model with super advanced options."""
        template = ImportTemplate(
            name=name,
            protocol_model_id=protocol_model_id,
            mapping_json=mapping,
            skip_rows=skip_rows,
            anchor_text=anchor_text,
            anchor_offset=anchor_offset,
            row_interval=row_interval,
            advanced_logic=advanced_logic
        )
        db.session.add(template)
        db.session.commit()
        return template

    @staticmethod
    def export_template(template_id):
        """Exports a template as a portable JSON object."""
        template = db.session.get(ImportTemplate, template_id)
        if not template:
            raise ValueError("Template not found")
        
        # We want the mapping to be portable, so we resolve analyte IDs to names
        portable_mapping = {}
        for file_col, analyte_id in template.mapping_json.items():
            if analyte_id:
                analyte = db.session.get(Analyte, analyte_id)
                if analyte:
                    portable_mapping[file_col] = analyte.name

        portable_logic = {}
        if template.advanced_logic:
            for analyte_id, formula in template.advanced_logic.items():
                analyte = db.session.get(Analyte, int(analyte_id))
                if analyte:
                    portable_logic[analyte.name] = formula

        return {
            'name': template.name,
            'skip_rows': template.skip_rows,
            'anchor_text': template.anchor_text,
            'anchor_offset': template.anchor_offset,
            'row_interval': template.row_interval,
            'mapping': portable_mapping,
            'advanced_logic': portable_logic,
            'version': '1.0'
        }

    @staticmethod
    def import_template(data, protocol_model_id):
        """Imports a template from a JSON object, matching analytes by name."""
        name = data.get('name', 'Imported Template')
        
        # Resolve names back to IDs for this protocol
        protocol = db.session.get(ProtocolModel, protocol_model_id)
        if not protocol:
            raise ValueError("Protocol not found")
        
        analyte_map = {a.name: a.id for a in protocol.analytes}
        
        mapping = {}
        for file_col, analyte_name in data.get('mapping', {}).items():
            if analyte_name in analyte_map:
                mapping[file_col] = analyte_map[analyte_name]

        advanced_logic = {}
        for analyte_name, formula in data.get('advanced_logic', {}).items():
            if analyte_name in analyte_map:
                advanced_logic[analyte_map[analyte_name]] = formula

        return ImportWizardService.save_template(
            name=name,
            protocol_model_id=protocol_model_id,
            mapping=mapping,
            skip_rows=data.get('skip_rows', 0),
            anchor_text=data.get('anchor_text'),
            anchor_offset=data.get('anchor_offset', 0),
            row_interval=data.get('row_interval', 1),
            advanced_logic=advanced_logic
        )

    @staticmethod
    def get_templates(protocol_model_id):
        """Returns all templates for a protocol model."""
        return ImportTemplate.query.filter_by(protocol_model_id=protocol_model_id).all()
