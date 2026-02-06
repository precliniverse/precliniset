# app/services/analysis_service.py
import pandas as pd
from sqlalchemy import func
from datetime import datetime
from flask import current_app
from flask_babel import lazy_gettext as _l

from app.extensions import db
from app.models import DataTable, ExperimentDataRow, ExperimentalGroup
from app.datatables.data_prepper import perform_data_checks
from app.datatables.plot_utils import generate_plot, get_custom_ordered_columns
from app.datatables.test_suggester import suggest_statistical_tests
from app.helpers import replace_undefined
from app.services.statistics_service import StatisticsService
from app.permissions import check_datatable_permission

class AnalysisService:
    def __init__(self):
        self.stats_service = StatisticsService()

    def prepare_dataframe(self, data_table):
        """Convert DataTable to DataFrame using Animal model (V2 refactored).
        
        Queries the Animal table directly instead of parsing JSON,
        providing better performance and type safety.
        
        Args:
            data_table: DataTable instance
            
        Returns:
            Tuple of (DataFrame, numerical_columns, categorical_columns)
        """
        from app.models import Animal
        
        # 1. Determine fields to extract
        # Core columns in the Animal model that we already query explicitly
        core_cols = {'sex', 'status', 'date_of_birth', 'id', 'uid'}
        
        json_fields = []
        if data_table.group and data_table.group.model:
            json_fields.extend([
                a.name for a in data_table.group.model.analytes 
                if a.name and a.name.lower() not in core_cols
            ])
        
        # 2. Build optimized SQL query
        # We select core columns + specific JSON keys
        query = db.session.query(
            Animal.uid.label('ID'),
            Animal.date_of_birth,
            Animal.sex,
            Animal.status,
            *[func.json_extract(Animal.measurements, f'$.{field}').label(field) for field in json_fields]
        ).filter_by(group_id=data_table.group_id).order_by(Animal.id)
        
        try:
             # Execute SQL query directly into a list of dictionaries
             results = query.all()
             
             # Convert Row objects to dicts
             animal_data = []
             for row in results:
                 row_dict = {
                     'ID': row.ID,
                     'date_of_birth': row.date_of_birth.isoformat() if row.date_of_birth else None,
                     'Date of Birth': row.date_of_birth.isoformat() if row.date_of_birth else None, # Compatibility
                     'sex': row.sex,
                     'Sex': row.sex, # Compatibility
                     'status': row.status,
                     'Status': row.status, # Compatibility
                 }
                 # Add extracted JSON fields
                 for field in json_fields:
                     row_dict[field] = getattr(row, field, None)
                 animal_data.append(row_dict)

        except Exception as e:
            current_app.logger.warning(f"Optimized SQL JSON query failed: {e}")
            # Fallback: legacy object loading
            animals = Animal.query.filter_by(group_id=data_table.group_id).order_by(Animal.id).all()
            animal_data = []
            for animal in animals:
                animal_data.append(animal.to_dict())

        if not animal_data:
             return None, [], []
                
        # 3. Merge with protocol data from ExperimentDataRow
        rows_query = data_table.experiment_rows.order_by(ExperimentDataRow.row_index)
        existing_data_rows_dict = {row.row_index: row.row_data for row in rows_query.all()}
        
        # Match animals by index (assuming same order)
        for i, row in enumerate(animal_data):
            if i in existing_data_rows_dict:
                row.update(existing_data_rows_dict[i])
        
        # 4. Calculate Age (Days)
        for row in animal_data:
            age_in_days = None
            date_of_birth_str = row.get('Date of Birth') or row.get('date_of_birth')
            if date_of_birth_str and data_table.date:
                try:
                    dob = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                    dt_date_obj = datetime.strptime(data_table.date, '%Y-%m-%d').date()
                    delta = dt_date_obj - dob
                    age_in_days = delta.days
                except (ValueError, TypeError):
                    age_in_days = None
            row['Age (Days)'] = age_in_days
        
        # 5. Create DataFrame
        df = pd.DataFrame(animal_data)
        
        if df.empty:
            return None, [], []
        
        # 6. Type Conversion based on Analyte definitions
        all_field_defs = (
            (data_table.group.model.analytes if data_table.group.model else []) +
            (data_table.protocol.analytes if data_table.protocol else [])
        )
        
        for field_def in all_field_defs:
            if field_def:
                field_name, field_type = field_def.name, field_def.data_type.value
                if field_name in df.columns and field_type in ['int', 'float']:
                    df[field_name] = pd.to_numeric(df[field_name], errors='coerce')
        
        if 'Age (Days)' in df.columns:
            df['Age (Days)'] = pd.to_numeric(df['Age (Days)'], errors='coerce')
        
        # 7. Identify Column Types
        numerical_columns = []
        categorical_columns = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                numerical_columns.append(col)
            else:
                categorical_columns.append(col)
        
        return df, numerical_columns, categorical_columns

    def get_datatable_metadata(self, data_table):
        """
        Fast-path to get column metadata without loading the full DataFrame.
        Relies on Model definitions rather than inspecting every row.
        
        Returns:
            Tuple of (numerical_columns, categorical_columns, column_types)
            where column_types is a dict mapping column name to 'numerical' or 'categorical'
        """
        numerical_columns = []
        categorical_columns = []
        column_types = {}  # New: maps column name to type
        
        # 1. Animal Model Fields
        if data_table.group and data_table.group.model:
            # We skip internal IDs and raw date fields (Age is provided separately)
            # sex and status are biological factors and must be available for grouping.
            skip_fields = {'id', 'uid', 'animal_id', 'date_of_birth', 'date of birth'}
            for analyte in data_table.group.model.analytes:
                if not analyte.name or analyte.name.lower() in skip_fields:
                    continue
                
                # Use Title Case for these core factors for better UI display
                # while keeping compatibility with prepare_dataframe keys
                display_name = analyte.name
                if display_name.lower() == 'sex': display_name = 'Sex'
                if display_name.lower() == 'status': display_name = 'Status'

                if analyte.data_type.value in ['int', 'float']:
                    numerical_columns.append(display_name)
                    column_types[display_name] = 'numerical'
                else:
                    categorical_columns.append(display_name)
                    column_types[display_name] = 'categorical'
        
        # 2. Protocol Fields
        if data_table.protocol:
             # Sort analytes by ProtocolAnalyteAssociation.order
             sorted_analytes = sorted(
                 data_table.protocol.analyte_associations,
                 key=lambda assoc: assoc.order
             )
             for assoc in sorted_analytes:
                 analyte = assoc.analyte
                 if analyte.data_type.value in ['int', 'float']:
                     numerical_columns.append(analyte.name)
                     column_types[analyte.name] = 'numerical'
                 else:
                     categorical_columns.append(analyte.name)
                     column_types[analyte.name] = 'categorical'
        
        # 3. Calculated Age
        # We assume if 'Date of Birth' is in the model (or implicitly available) and we have a Date, we have Age.
        # But wait, prepare_dataframe calculates it if 'Date of Birth' is in the data.
        # Let's check the Animal Model for 'Date of Birth'.
        has_dob = False
        if data_table.group and data_table.group.model:
            dob_names = {'date of birth', 'date_of_birth'}
            if any(a.name and a.name.lower() in dob_names for a in data_table.group.model.analytes):
                has_dob = True
        
        # If not in model, it might still be in data... but this is FAST PATH.
        # We'll assume strict Model adherence for fast path.
        if has_dob and data_table.date:
             numerical_columns.append('Age (Days)')
             column_types['Age (Days)'] = 'numerical'
             
        # Also ensure ID is not in either list (usually handled by UI exclusion, but good to be safe)
        
        return numerical_columns, categorical_columns, column_types

    def aggregate_datatables(self, selected_datatable_ids, user_id=None):
        """
        Merges multiple DataTables into one DataFrame.
        """
        if not selected_datatable_ids:
            return None, [_l("No datatables were selected.")], []

        datatables_to_process = []
        errors = []
        source_identifiers = []
        
        for dt_id in selected_datatable_ids:
            dt = db.session.get(DataTable, dt_id)
            if not dt or not dt.group:
                errors.append(_l("DataTable with ID {dt_id} not found or group missing.").format(dt_id=dt_id))
                continue
            if not check_datatable_permission(dt, 'read', user_id=user_id):
                errors.append(_l("Permission denied for DataTable {dt_id}.").format(dt_id=dt_id))
                continue
            datatables_to_process.append(dt)
            source_identifiers.append(f"{dt.group.name}-{dt.protocol.name}-{dt.date}")

        if not datatables_to_process:
            return None, errors, source_identifiers

        all_long_data = []
        animal_model_fields = set()

        for dt in datatables_to_process:
            # Load experiment rows for this datatable
            from app.models import ExperimentDataRow
            exp_rows_dict = {row.row_index: row.row_data for row in dt.experiment_rows.all()}
            
            # Use animals relationship instead of animal_data
            animals = sorted(dt.group.animals, key=lambda a: a.id)
            for i, animal in enumerate(animals):
                animal_info = animal.to_dict()
                animal_id = animal_info.get('uid')
                if not animal_id: continue

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

        # Filter to analytes present in all datatables
        analyte_counts = long_df.groupby('analyte_name')['_source_datatable_id'].nunique()
        common_analytes = analyte_counts[analyte_counts == len(datatables_to_process)].index
        long_df = long_df[long_df['analyte_name'].isin(common_analytes)]

        if long_df.empty:
            return pd.DataFrame(), [_l("No common analytes found across all selected datatables.")], source_identifiers
        
        # Create unique column names for measurements
        # MODIFIED: Use analyte_name only to align data across datatables (pooling/comparison)
        # instead of separating by date/protocol which creates disjoint variables.
        long_df['measurement_label'] = long_df['analyte_name']
        
        # Base animal data
        all_animal_data_df = []
        seen_animal_ids = set()
        for dt in datatables_to_process:
            for animal in dt.group.animals:
                animal_info = animal.to_dict()
                animal_id = animal_info.get('uid')
                if animal_id and animal_id not in seen_animal_ids:
                    all_animal_data_df.append(animal_info)
                    seen_animal_ids.add(animal_id)
        
        animal_df = pd.DataFrame(all_animal_data_df)
        if 'ID' not in animal_df.columns:
            return pd.DataFrame(), [_l("Could not find 'ID' column in animal data.")], source_identifiers
        
        animal_df = animal_df.drop_duplicates(subset=['ID']).set_index('ID')
        
        # Pivot measurements
        pivoted_df = long_df.pivot_table(
            index='ID',
            columns='measurement_label',
            values='analyte_value',
            aggfunc='first'
        )
        
        # Join
        final_df = animal_df.join(pivoted_df, how='left')
        
        # Reorder columns
        animal_cols_ordered = sorted([col for col in final_df.columns if col in animal_model_fields and col != 'ID'])
        measurement_cols_ordered = sorted([col for col in final_df.columns if col not in animal_model_fields])
        final_column_order = animal_cols_ordered + measurement_cols_ordered
        
        final_df = final_df[final_column_order].reset_index()

        return final_df, errors, source_identifiers

    def perform_analysis(self, df, form_data, subject_id_col, subject_id_col_present, available_numerical, available_categorical):
        """
        Orchestrates the entire analysis pipeline: Checks -> Suggestions -> Execution -> Plotting.
        """
        results = {
            'checks_by_parameter': {},
            'results_by_parameter': {},
            'overall_error': None,
            'overall_notes': [],
            'repeated_measures_test_suggestions': {},
            'overall_suggestion_notes': []
        }

        grouping_params = form_data.get('grouping_params', [])
        numerical_params = form_data.get('numerical_params', [])
        is_repeated = form_data.get('is_repeated_measures', False)
        exclude_outliers = form_data.get('exclude_outliers', False)
        chosen_tests = form_data.get('chosen_tests', {})
        graph_type = form_data.get('graph_type', 'Box Plot')
        start_y_at_zero = form_data.get('start_y_at_zero', False)

        # 1. Data Checks & Suggestions
        checks = perform_data_checks(df.copy(), grouping_params, numerical_params, is_repeated, subject_id_col, exclude_outliers)
        results['checks_by_parameter'] = checks
        
        # 1.5 Suggest Tests
        extra_context = {
            'has_control_group': bool(form_data.get('control_group_param')),
            'has_covariate': bool(form_data.get('covariate_param')),
            'exclude_outliers': bool(exclude_outliers),
            'outlier_method': form_data.get('outlier_method', 'iqr'),
            'outlier_threshold': float(form_data.get('outlier_threshold', 1.5))
        }
        
        # Build column_types dictionary for test suggester
        column_types = {}
        for col in available_numerical:
            column_types[col] = 'numerical'
        for col in available_categorical:
            column_types[col] = 'categorical'

        suggestions = suggest_statistical_tests(
            len(grouping_params), len(numerical_params), is_repeated, 
            checks, subject_id_col, subject_id_col_present, available_numerical,
            extra_context=extra_context,
            column_types=column_types
        )
        results['repeated_measures_test_suggestions'] = suggestions.get('repeated_measures_test_suggestions', {})
        results['overall_suggestion_notes'] = suggestions.get('overall_suggestion_notes', [])
        # Update checks_by_parameter with the enriched version that includes possible_tests
        results['checks_by_parameter'] = suggestions.get('checks_by_parameter', checks)

        # If only proposing, stop here
        if form_data.get('analysis_stage') == 'propose_workflow':
            return replace_undefined(results)

        # 2. Execution (Stats & Plots)
        ref_range_summary = None
        ref_range_id = form_data.get('reference_range_id')
        splitting_param = form_data.get('splitting_param')
        
        if ref_range_id:
            try:
                ref_range_summary = self._calculate_reference_range_summary(int(ref_range_id), splitting_param)
            except Exception as e:
                current_app.logger.error(f"Error calculating reference range summary: {e}")
                results['overall_notes'].append(_l("Error loading reference range data."))


        enable_survival = form_data.get('enable_survival')
        if enable_survival and form_data.get('survival_time_col') and form_data.get('survival_event_col'):
             self._analyze_survival(df, grouping_params, form_data, results)

        if is_repeated:
            self._analyze_repeated(df, grouping_params, numerical_params, chosen_tests, graph_type, start_y_at_zero, subject_id_col, exclude_outliers, results, form_data, reference_range_summary=ref_range_summary, suggestions=suggestions)
        else:
            self._analyze_independent(df, grouping_params, numerical_params, chosen_tests, graph_type, start_y_at_zero, subject_id_col, exclude_outliers, results, form_data, reference_range_summary=ref_range_summary, suggestions=suggestions)

        return replace_undefined(results)

    def _analyze_survival(self, df, grouping, form_data, results):
        time_col = form_data.get('survival_time_col')
        event_col = form_data.get('survival_event_col')
        
        # Calculate duration if time_col is a Date (simplistic check, better to do in prep)
        # However, for this version, we assume `prepare_dataframe` logic (which we need to add) or that it is already a duration.
        # Actually, let's implement the duration calc in `_analyze_survival` or rely on prep.
        # Given `prepare_dataframe` returns a DF, we can do it here if we have reference dates.
        # BUT `prepare_dataframe` is better for global logic.
        # Let's assume `time_col` IS the duration or we calculate it here if needed?
        # The user said "animals have a date of death". We have `Age (Days)`.
        # Better: Use `prepare_dataframe` to calculate `_SurvivalDuration_` if dates provided.
        # For now, let's assume `time_col` holds the numerical duration OR we attempt to convert.
        
        # Simple Robust Check: Is time_col numeric?
        if not pd.api.types.is_numeric_dtype(df[time_col]):
             # Attempt to convert to date and diff against start? 
             # We lack 'Start Date' easily here unless we pass it.
             # Assumption: parameters passed in UI are ALREADY durations or ready-to-use numbers.
             # If user selects "Date of Death", we need to convert it.
             # See Step 3 of plan: "Data Prep: Handle Date of Death".
             results['survival_results'] = {'error': _l("Survival Analysis requires a numeric Duration column. Please ensure 'Date of Death' is converted to duration (Age) or select 'Age (Days)'.")}
             return

        # Perform Log-Rank
        try:
             stats_res = self.stats_service.execute_test(df, 'logrank', time_col, grouping, False, None, exclude_outliers=False, extra_params={'event_col': event_col})
             
             # Generate Plot Data (Kaplan-Meier)
             # We use `plot_utils` which we need to update.
             from app.datatables.plot_utils import generate_survival_plot
             graph_data, notes = generate_survival_plot(df, time_col, event_col, grouping)
             results['overall_notes'].extend(notes)
             
             results['survival_results'] = {
                 'graph_data': graph_data,
                 'stats_data': stats_res.get('results_data'), # Table
                 'p_value': stats_res.get('p_value'),
                 'error': stats_res.get('error')
             }
        except Exception as e:
             current_app.logger.error(f"Survival Error: {e}")
             results['survival_results'] = {'error': f"Survival Analysis Failed: {str(e)}"}


    def _calculate_reference_range_summary(self, range_id, splitting_param=None):
        """Fetches and calculates descriptive statistics for a reference range."""
        from app.models import ReferenceRange, ExperimentalGroup, DataTable, ExperimentDataRow
        from collections import defaultdict
        
        ref_range = db.session.get(ReferenceRange, range_id)
        if not ref_range or not ref_range.included_animals:
            return None

        # Collect measurement values:
        # 1. Global (for all animals)
        # 2. Split (if splitting_param provided)
        values_global = defaultdict(list)
        values_split = defaultdict(lambda: defaultdict(list)) # [SplitVal][Param]
        
        group_ids = [gid for gid in ref_range.included_animals.keys()]
        experimental_groups = ExperimentalGroup.query.filter(ExperimentalGroup.id.in_(group_ids)).all()
        group_map = {g.id: g for g in experimental_groups}
        
        data_tables = DataTable.query.filter(
            DataTable.group_id.in_(group_ids),
            DataTable.protocol_id == ref_range.protocol_id
        ).all()
        dt_ids = [dt.id for dt in data_tables]
        
        rows = ExperimentDataRow.query.filter(ExperimentDataRow.data_table_id.in_(dt_ids)).all()
        rows_by_dt = defaultdict(dict)
        for r in rows:
            rows_by_dt[r.data_table_id][r.row_index] = r.row_data

        for group_id_str, animal_indices in ref_range.included_animals.items():
            gid = group_id_str
            group = group_map.get(gid)
            if not group: continue
            
            animals = sorted(group.animals, key=lambda a: a.id)
            relevant_dts = [dt for dt in data_tables if dt.group_id == gid]
            
            for dt in relevant_dts:
                dt_rows = rows_by_dt.get(dt.id, {})
                for idx in animal_indices:
                    row_meas = dt_rows.get(idx, {})
                    if not row_meas: continue
                    
                    # Fetch split value for this animal if requested
                    animal = animals[idx] if idx < len(animals) else None
                    animal_info = animal.to_dict() if animal else {}
                    split_val = str(animal_info.get(splitting_param)) if splitting_param and animal_info.get(splitting_param) is not None else None
                    
                    for param, val in row_meas.items():
                        try:
                            num_val = float(val)
                            if pd.notnull(num_val):
                                values_global[param].append(num_val)
                                if split_val:
                                    values_split[split_val][param].append(num_val)
                        except (ValueError, TypeError):
                            continue
        
        def calc_stats(vals_dict):
            stats = {}
            for param, vals in vals_dict.items():
                if not vals: continue
                s = pd.Series(vals)
                stats[param] = {
                    'mean': float(s.mean()),
                    'sd': float(s.std()) if len(s) > 1 else 0.0,
                    'min': float(s.min()),
                    'max': float(s.max()),
                    'n': int(len(s))
                }
                # Mapping for RM
                if ref_range.analyte and param == ref_range.analyte.name:
                    stats['_MeasurementValue_'] = stats[param]
            return stats

        summary = {
            'global': calc_stats(values_global),
            'splits': {val: calc_stats(p_dict) for val, p_dict in values_split.items()}
        }
        
        return summary

    def _analyze_repeated(self, df, grouping, numerical, tests, graph_type, start_y_zero, subject_id, exclude_outliers, results, form_data, reference_range_summary=None, suggestions=None):
        # Handle Splitting (Must be done before id_vars def)
        splitting_param = form_data.get('splitting_param')
        
        # Determine graph type (form overrides argument)
        chosen_graph_type = form_data.get('graph_type_rm_set', graph_type)
        test_key = tests.get('rm_set', 'none')

        if splitting_param and splitting_param in df.columns:
            # --- FULL SPLIT ANALYSIS (RM) ---
            # We do NOT add splitting_param to grouping because we filter by it.
            # grouping stays as the main factors (e.g. Genotype)
            
            unique_splits = sorted(df[splitting_param].dropna().unique())
            split_results_list = []
            
            for split_val in unique_splits:
                # Filter Data
                sub_df = df[df[splitting_param] == split_val].copy()
                if sub_df.empty: continue
                
                # Reshape
                id_vars = [subject_id] + grouping
                df_long = pd.melt(sub_df, id_vars=[c for c in id_vars if c in sub_df.columns], value_vars=numerical, var_name='_WithinFactorLevel_', value_name='_MeasurementValue_')

                # Stats
                outlier_method = form_data.get('outlier_method', 'iqr')
                outlier_threshold = float(form_data.get('outlier_threshold', 1.5))
                extra_params = {
                    'outlier_method': outlier_method,
                    'outlier_threshold': outlier_threshold,
                    'control_group': form_data.get('control_group_param')
                }
                sub_stats = self.stats_service.execute_test(df_long, test_key, '_MeasurementValue_', grouping, True, subject_id, exclude_outliers, extra_params=extra_params)

                # Plot - Use split-specific ref range if available
                split_ref_range = reference_range_summary.get('splits', {}).get(str(split_val)) if reference_range_summary else None
                if not split_ref_range and reference_range_summary:
                    split_ref_range = reference_range_summary.get('global')

                sub_graph, sub_notes = generate_plot(
                    df_long, '_MeasurementValue_', grouping, chosen_graph_type, start_y_zero, True, subject_id, numerical, 
                    exclude_outliers=exclude_outliers, stats_results=sub_stats, reference_range_summary=split_ref_range,
                    outlier_method=outlier_method, outlier_threshold=outlier_threshold
                )

                results['overall_notes'].extend(sub_notes)
                
                # Summary (Not standard for RM set to have table, but maybe future?)
                
                split_results_list.append({
                    'split_label': f'{splitting_param}: {split_val}',
                    'graph_data': sub_graph,
                    'statistical_results': sub_stats,
                    'notes': sub_notes,
                    'is_rm_set': True,
                    'test_name': self.stats_service._get_test_name(test_key)
                })
            
            results['results_by_parameter']['repeated_measures_set'] = {
                'is_split_analysis': True,
                'splitting_param': splitting_param,
                'splits': split_results_list,
                'is_rm_set': True
            }

        else:
             # Standard (No Split) - Or if Split was originally just a grouping?
             # My previous logic ADDED split to grouping.
             # If we want consistent behavior, "Split By" should ALWAYS separate results?
             # Yes, based on user input.
        
             # Reshape for RM
             id_vars = [subject_id] + grouping
             df_long = pd.melt(df, id_vars=[c for c in id_vars if c in df.columns], value_vars=numerical, var_name='_WithinFactorLevel_', value_name='_MeasurementValue_')
            
             # Stats
             outlier_method = form_data.get('outlier_method', 'iqr')
             outlier_threshold = float(form_data.get('outlier_threshold', 1.5))
             extra_params = {
                 'outlier_method': outlier_method,
                 'outlier_threshold': outlier_threshold,
                 'control_group': form_data.get('control_group_param')
             }
             stats_res = self.stats_service.execute_test(df_long, test_key, '_MeasurementValue_', grouping, True, subject_id, exclude_outliers, extra_params=extra_params)
             
             # Inject Rationale
             if suggestions:
                 rm_sug = suggestions.get('repeated_measures_test_suggestions', {}).get('possible_tests', [])
                 for t in rm_sug:
                     if t['key'] == test_key and t.get('reason'):
                         stats_res['rationale'] = t['reason']
                         break

             # Plot (Pass stats_res for significance stars)
             global_ref_range = reference_range_summary.get('global') if reference_range_summary else None
             graph_data, notes = generate_plot(
                 df_long, '_MeasurementValue_', grouping, chosen_graph_type, start_y_zero, True, subject_id, numerical, 
                 exclude_outliers=exclude_outliers, stats_results=stats_res, reference_range_summary=global_ref_range,
                 outlier_method=outlier_method, outlier_threshold=outlier_threshold
             )

             results['overall_notes'].extend(notes)
            
             results['results_by_parameter']['repeated_measures_set'] = {
                'graph_data': graph_data,
                'statistical_results': stats_res,
                'is_rm_set': True,
                'test_name': self.stats_service._get_test_name(test_key)
             }
             
             # Check for Cage Effect (on the long data? or original wide data? Better on long for 1-way?)
             # Actually, simpler to check on long data (Measurement ~ Cage) ignoring Time, or check per timepoint?
             # Checking overall cage effect is a good start.
             self._check_cage_effect(df_long, '_MeasurementValue_', results)

    def _analyze_independent(self, df, grouping, numerical, tests, graph_type, start_y_zero, subject_id, exclude_outliers, results, form_data, reference_range_summary=None, suggestions=None):
        # Handle Splitting
        splitting_param = form_data.get('splitting_param')
        
        # Prepare grouping for PLOTS and SUMMARY (Combined)
        grouping_for_plots = list(grouping)
        if splitting_param and splitting_param in df.columns and splitting_param not in grouping_for_plots:
            grouping_for_plots.append(splitting_param)
        
        # Prepare grouping for STATS (Iterative if splitting)
        grouping_for_stats = list(grouping) # Original grouping without split factor
        
        # Generate group summary table (descriptive statistics)
        # We use the combined grouping so we get descriptive stats for all subgroups (e.g. KO/M, KO/F)
        group_summary_html = self._generate_group_summary_table(df, grouping_for_plots, numerical)
        results['group_summary_html'] = group_summary_html
        
        for param in numerical:
            # Determine graph type for this parameter
            chosen_graph_type = form_data.get(f'chosen_graph_{param}', graph_type)
            
            # Stats (Run first to pass to plot)
            test_key = tests.get(param, 'none')
            
            # Helper to find rationale
            rationale = None
            if suggestions:
                param_checks = suggestions.get('checks_by_parameter', {}).get(param, {})
                possible = param_checks.get('possible_tests', [])
                for t in possible:
                    if t['key'] == test_key and t.get('reason'):
                        rationale = t['reason']
                        break
            
            # Check for Cage Effect
            self._check_cage_effect(df, param, results)
            
            # Prepare extra params for advanced tests (ANCOVA / Dunnett)
            outlier_method = form_data.get('outlier_method', 'iqr')
            outlier_threshold = float(form_data.get('outlier_threshold', 1.5))
            extra_params = {
                'control_group': form_data.get('control_group_param'),
                'covariate': form_data.get('covariate_param'),
                'event_col': form_data.get('survival_event_col'),
                'outlier_method': outlier_method,
                'outlier_threshold': outlier_threshold
            }

            stats_res = {'p_value': None, 'results_data': None, 'error': None}

            if splitting_param and splitting_param in df.columns:
                # --- FULL SPLIT ANALYSIS ---
                unique_splits = sorted(df[splitting_param].dropna().unique())
                split_results_list = []
                
                for split_val in unique_splits:
                    # Filter Data
                    sub_df = df[df[splitting_param] == split_val].copy()
                    if sub_df.empty: continue

                    # 1. Stats
                    sub_stats = self.stats_service.execute_test(
                        sub_df, test_key, param, grouping_for_stats, False, subject_id, exclude_outliers, extra_params=extra_params
                    )
                    
                    # 2. Graph - Use split-specific ref range if available
                    split_ref_range = reference_range_summary.get('splits', {}).get(str(split_val)) if reference_range_summary else None
                    if not split_ref_range and reference_range_summary:
                        split_ref_range = reference_range_summary.get('global')

                    sub_graph, sub_notes = generate_plot(
                        sub_df, param, grouping_for_stats, chosen_graph_type, start_y_zero, False, subject_id, None, 
                        exclude_outliers=exclude_outliers, stats_results=sub_stats, reference_range_summary=split_ref_range,
                        outlier_method=outlier_method, outlier_threshold=outlier_threshold
                    )

                    results['overall_notes'].extend(sub_notes)

                    # 3. Summary
                    sub_summary = self._generate_parameter_summary_table(sub_df, grouping_for_stats, param)
                    
                    split_results_list.append({
                        'split_label': f"{splitting_param}: {split_val}",
                        'graph_data': sub_graph,
                        'statistical_results': sub_stats,
                        'summary_table_html': sub_summary,
                        'notes': sub_notes
                    })

                results['results_by_parameter'][param] = {
                    'is_split_analysis': True,
                    'splitting_param': splitting_param,
                    'splits': split_results_list
                }
            
            else:
                # --- STANDARD ANALYSIS (No Split) ---
                stats_res = self.stats_service.execute_test(
                    df, test_key, param, grouping_for_plots, False, subject_id, exclude_outliers, extra_params=extra_params
                )
                if rationale: stats_res['rationale'] = rationale
                
                global_ref_range = reference_range_summary.get('global') if reference_range_summary else None
                graph_data, notes = generate_plot(
                    df, param, grouping_for_plots, chosen_graph_type, start_y_zero, False, subject_id, None, 
                    exclude_outliers=exclude_outliers, stats_results=stats_res, reference_range_summary=global_ref_range,
                    outlier_method=outlier_method, outlier_threshold=outlier_threshold
                )

                results['overall_notes'].extend(notes)
                
                param_summary_html = self._generate_parameter_summary_table(df, grouping_for_plots, param)
                
                results['results_by_parameter'][param] = {
                    'graph_data': graph_data,
                    'statistical_results': stats_res,
                    'summary_table_html': param_summary_html,
                    'notes': notes
                }

        # 3. Overall Analysis (Correlation Matrix)
        # Run automatically if >1 numerical parameters are selected and we have sufficient data
        if len(numerical) > 1 and len(df) > 5:
             # Pass a dummy 'dv' and 'grouping' as _run_correlation_matrix ignores them or expects global DF
             # We use the filtered DF (but we should probably use the original DF restricted to chosen params?)
             # execute_test expects a DF. We can pass the main DF.
             # We need to register 'correlation' in StatisticsService or call a specific method?
             # StatisticsService.execute_test dispatched to `_run_{key}`.
             # We added `_run_correlation_matrix`.
             
             try:
                 corr_res = self.stats_service.execute_test(
                     df[numerical], # Pass only numerical columns of interest? Or let it filter?
                     'correlation', 
                     None, # dv
                     None, # grouping
                     False, 
                     subject_id
                 )
                 if not corr_res.get('error'):
                     results['results_by_parameter']['_correlation_matrix_'] = {
                         'graph_data': None, # Could add heatmap?
                         'statistical_results': corr_res,
                         'is_overall': True
                     }
             except Exception as e:
                 current_app.logger.warning(f"Correlation matrix failed: {e}")

    def _generate_group_summary_table(self, df, grouping_params, numerical_params):
        """Generate structured data for group composition summary table."""
        if not grouping_params:
            return None

        try:
            # Create combined group column for display
            if len(grouping_params) == 1:
                group_col = grouping_params[0]
            else:
                df = df.copy()
                df['_combined_group_'] = df[grouping_params].astype(str).agg(' / '.join, axis=1)
                group_col = '_combined_group_'

            # Count by group
            group_counts = df.groupby(group_col).size().reset_index(name='Count (n)')

            # Return structured data for template rendering
            return {
                'grouping_params': grouping_params,
                'rows': [
                    {
                        'group_value': str(row[group_col]),
                        'count': int(row['Count (n)'])
                    }
                    for _, row in group_counts.iterrows()
                ],
                'total': len(df)
            }
        except Exception as e:
            current_app.logger.warning(f"Could not generate group summary table: {e}")
            return None

    def _generate_parameter_summary_table(self, df, grouping_params, numerical_param):
        """Generate an HTML table with descriptive statistics for a parameter by group."""
        import html
        if not grouping_params or numerical_param not in df.columns:
            return None

        try:
            # Create combined group column
            if len(grouping_params) == 1:
                group_col = grouping_params[0]
                df_work = df
            else:
                df_work = df.copy()
                df_work['_combined_group_'] = df_work[grouping_params].astype(str).agg(' / '.join, axis=1)
                group_col = '_combined_group_'

            # Calculate descriptive stats by group
            stats_df = df_work.groupby(group_col)[numerical_param].agg([
                ('n', 'count'),
                ('Mean', 'mean'),
                ('SD', 'std'),
                ('SEM', lambda x: x.std() / (len(x) ** 0.5) if len(x) > 1 else 0),
                ('Min', 'min'),
                ('Max', 'max'),
                ('Median', 'median')
            ]).reset_index()

            # Format numbers
            for col in ['Mean', 'SD', 'SEM', 'Min', 'Max', 'Median']:
                stats_df[col] = stats_df[col].apply(lambda x: f'{x:.2f}' if pd.notnull(x) else 'N/A')

            # Build HTML table
            html_str = '<table class="table table-sm table-striped table-bordered">'
            html_str += '<thead class="table-light"><tr>'
            html_str += f'<th class="text-center">Group</th><th class="text-center">n</th><th class="text-center">Mean</th><th class="text-center">SD</th><th class="text-center">SEM</th><th class="text-center">Min</th><th class="text-center">Max</th><th class="text-center">Median</th>'
            html_str += '</tr></thead><tbody>'

            for _, row in stats_df.iterrows():
                safe_group_val = html.escape(str(row[group_col]))
                html_str += f'<tr><td class="text-center">{safe_group_val}</td>'
                html_str += f'<td class="text-center">{row["n"]}</td>'
                html_str += f'<td class="text-center">{row["Mean"]}</td>'
                html_str += f'<td class="text-center">{row["SD"]}</td>'
                html_str += f'<td class="text-center">{row["SEM"]}</td>'
                html_str += f'<td class="text-center">{row["Min"]}</td>'
                html_str += f'<td class="text-center">{row["Max"]}</td>'
                html_str += f'<td class="text-center">{row["Median"]}</td></tr>'

            html_str += '</tbody></table>'
            return html_str
        except Exception as e:
            current_app.logger.warning(f"Could not generate parameter summary table: {e}")
            return None
    

    def _check_cage_effect(self, df, param, results):
        """Checks for significant cage effects and warns if found."""
        if 'Cage' not in df.columns or df['Cage'].nunique() < 2:
            return

        try:
            # Run simple One-Way ANOVA: Param ~ Cage
            # use stats_service to reuse robust ANOVA logic
            cage_res = self.stats_service.execute_test(
                df, 
                'anova_oneway', 
                param, 
                ['Cage'], 
                False, # is_repeated
                'ID', # subject_id (dummy if not RM, but needed for signature)
                exclude_outliers=False 
            )
            
            p_val = cage_res.get('p_value')
            if p_val is not None and p_val < 0.05:
                 results['overall_notes'].append(_l("<strong>Warning: Significant Cage Effect detected for '{param}' (p={p:.3f}).</strong> Data may be non-independent. Consider using Mixed Models with Cage as a random effect.").format(param=param, p=p_val))
        except Exception as e:
            # Swallow errors in background check
            current_app.logger.warning(f"Cage effect check failed: {e}") 
