# app/services/analysis_service.py
import pandas as pd
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
        """
        Converts a single DataTable into a Pandas DataFrame suitable for analysis.
        Handles merging animal data, protocol data, and calculating Age.
        """
        # 1. Determine Columns
        group_animal_data_keys = set()
        if data_table.group and data_table.group.animal_data:
            for animal_row in data_table.group.animal_data:
                group_animal_data_keys.update(animal_row.keys())

        protocol_field_names = []
        if data_table.protocol:
             # Sort analytes by ProtocolAnalyteAssociation.order
             sorted_analytes = sorted(
                 data_table.protocol.analyte_associations,
                 key=lambda assoc: assoc.order
             )
             protocol_field_names = [assoc.analyte.name for assoc in sorted_analytes]

        all_possible_cols = get_custom_ordered_columns(group_animal_data_keys, protocol_field_names)
        if not all_possible_cols:
            return None, [], []

        # 2. Fetch Data
        rows_query = data_table.experiment_rows.order_by(ExperimentDataRow.row_index)
        existing_data_rows_dict = {row.row_index: row.row_data for row in rows_query.all()}
        group_animal_data = data_table.group.animal_data or []

        data_for_df = []
        for i in range(len(group_animal_data)):
             merged = group_animal_data[i].copy() if i < len(group_animal_data) else {}
             merged.update(existing_data_rows_dict.get(i, {}))

             # Calculate Age
             age_in_days = None
             date_of_birth_str = merged.get('Date of Birth') 
             if date_of_birth_str and data_table.date:
                 try:
                     dob = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                     dt_date_obj = datetime.strptime(data_table.date, '%Y-%m-%d').date()
                     delta = dt_date_obj - dob
                     age_in_days = delta.days
                 except (ValueError, TypeError):
                     age_in_days = None 

             row_dict = {col: merged.get(col) for col in all_possible_cols}
             row_dict['Age (Days)'] = age_in_days 
             data_for_df.append(row_dict)

        if not data_for_df:
            return None, [], []

        # 3. Create DataFrame
        final_all_possible_cols = all_possible_cols[:]
        if 'Age (Days)' not in final_all_possible_cols:
            final_all_possible_cols.append('Age (Days)')

        df = pd.DataFrame(data_for_df, columns=final_all_possible_cols) 

        # 4. Type Conversion
        all_field_defs = (data_table.group.model.analytes if data_table.group.model else []) + (data_table.protocol.analytes if data_table.protocol else [])
        for field_def in all_field_defs:
            if field_def:
                field_name, field_type = field_def.name, field_def.data_type.value
                if field_name in df.columns and field_type in ['int', 'float']:
                    df[field_name] = pd.to_numeric(df[field_name], errors='coerce')
        
        if 'Age (Days)' in df.columns:
            df['Age (Days)'] = pd.to_numeric(df['Age (Days)'], errors='coerce')

        # 5. Identify Column Types
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
        """
        numerical_columns = []
        categorical_columns = []
        
        # 1. Animal Model Fields
        if data_table.group and data_table.group.model:
            for analyte in data_table.group.model.analytes:
                if analyte.name in ['ID', 'Date of Birth']:
                    continue
                if analyte.data_type.value in ['int', 'float']:
                    numerical_columns.append(analyte.name)
                else:
                    categorical_columns.append(analyte.name)
        
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
                 else:
                     categorical_columns.append(analyte.name)
        
        # 3. Calculated Age
        # We assume if 'Date of Birth' is in the model (or implicitly available) and we have a Date, we have Age.
        # But wait, prepare_dataframe calculates it if 'Date of Birth' is in the data.
        # Let's check the Animal Model for 'Date of Birth'.
        has_dob = False
        if data_table.group and data_table.group.model:
            if any(a.name == 'Date of Birth' for a in data_table.group.model.analytes):
                has_dob = True
        
        # If not in model, it might still be in data... but this is FAST PATH.
        # We'll assume strict Model adherence for fast path.
        if has_dob and data_table.date:
             numerical_columns.append('Age (Days)')
             
        # Also ensure ID is not in either list (usually handled by UI exclusion, but good to be safe)
        
        return numerical_columns, categorical_columns

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
            group_animal_data = dt.group.animal_data or []
            exp_rows_dict = {row.row_index: row.row_data for row in dt.experiment_rows.all()}
            
            if dt.group.model and dt.group.model.analytes:
                animal_model_fields.update(a.name for a in dt.group.model.analytes)

            for i, animal_info in enumerate(group_animal_data):
                animal_id = animal_info.get('ID')
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
            for animal_info in (dt.group.animal_data or []):
                animal_id = animal_info.get('ID')
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
            'has_covariate': bool(form_data.get('covariate_param'))
        }

        suggestions = suggest_statistical_tests(
            len(grouping_params), len(numerical_params), is_repeated, 
            checks, subject_id_col, subject_id_col_present, available_numerical,
            extra_context=extra_context
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
            self._analyze_repeated(df, grouping_params, numerical_params, chosen_tests, graph_type, start_y_at_zero, subject_id_col, exclude_outliers, results, form_data, reference_range_summary=ref_range_summary)
        else:
            self._analyze_independent(df, grouping_params, numerical_params, chosen_tests, graph_type, start_y_at_zero, subject_id_col, exclude_outliers, results, form_data, reference_range_summary=ref_range_summary)

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
            
            animal_metadata = group.animal_data or []
            relevant_dts = [dt for dt in data_tables if dt.group_id == gid]
            
            for dt in relevant_dts:
                dt_rows = rows_by_dt.get(dt.id, {})
                for idx in animal_indices:
                    row_meas = dt_rows.get(idx, {})
                    if not row_meas: continue
                    
                    # Fetch split value for this animal if requested
                    meta = animal_metadata[idx] if idx < len(animal_metadata) else {}
                    split_val = str(meta.get(splitting_param)) if splitting_param and meta.get(splitting_param) is not None else None
                    
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

    def _analyze_repeated(self, df, grouping, numerical, tests, graph_type, start_y_zero, subject_id, exclude_outliers, results, form_data, reference_range_summary=None):
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
                 sub_stats = self.stats_service.execute_test(df_long, test_key, '_MeasurementValue_', grouping, True, subject_id, exclude_outliers)

                 # Plot - Use split-specific ref range if available
                 split_ref_range = reference_range_summary.get('splits', {}).get(str(split_val)) if reference_range_summary else None
                 if not split_ref_range and reference_range_summary:
                     split_ref_range = reference_range_summary.get('global')

                 sub_graph, sub_notes = generate_plot(df_long, '_MeasurementValue_', grouping, chosen_graph_type, start_y_zero, True, subject_id, numerical, exclude_outliers=exclude_outliers, stats_results=sub_stats, reference_range_summary=split_ref_range)

                 results['overall_notes'].extend(sub_notes)
                 
                 # Summary (Not standard for RM set to have table, but maybe future?)
                 
                 split_results_list.append({
                     'split_label': f"{splitting_param}: {split_val}",
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
             stats_res = self.stats_service.execute_test(df_long, test_key, '_MeasurementValue_', grouping, True, subject_id, exclude_outliers)

             # Plot (Pass stats_res for significance stars)
             global_ref_range = reference_range_summary.get('global') if reference_range_summary else None
             graph_data, notes = generate_plot(df_long, '_MeasurementValue_', grouping, chosen_graph_type, start_y_zero, True, subject_id, numerical, exclude_outliers=exclude_outliers, stats_results=stats_res, reference_range_summary=global_ref_range)

             results['overall_notes'].extend(notes)
            
             results['results_by_parameter']['repeated_measures_set'] = {
                'graph_data': graph_data,
                'statistical_results': stats_res,
                'is_rm_set': True,
                'test_name': self.stats_service._get_test_name(test_key)
             }

    def _analyze_independent(self, df, grouping, numerical, tests, graph_type, start_y_zero, subject_id, exclude_outliers, results, form_data, reference_range_summary=None):
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
            
            # Prepare extra params for advanced tests (ANCOVA / Dunnett)
            extra_params = {
                'control_group': form_data.get('control_group_param'),
                'covariate': form_data.get('covariate_param'),
                'event_col': form_data.get('survival_event_col')
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

                    sub_graph, sub_notes = generate_plot(sub_df, param, grouping_for_stats, chosen_graph_type, start_y_zero, False, subject_id, None, exclude_outliers=exclude_outliers, stats_results=sub_stats, reference_range_summary=split_ref_range)

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
                
                global_ref_range = reference_range_summary.get('global') if reference_range_summary else None
                graph_data, notes = generate_plot(df, param, grouping_for_plots, chosen_graph_type, start_y_zero, False, subject_id, None, exclude_outliers=exclude_outliers, stats_results=stats_res, reference_range_summary=global_ref_range)

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
        """Generate an HTML table summarizing group composition and sample sizes."""
        import html
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

            # Format as HTML table
            html_str = '<table class="table table-sm table-striped table-bordered">'
            html_str += '<thead class="table-light"><tr>'
            if len(grouping_params) == 1:
                html_str += f'<th class="text-center">{html.escape(str(grouping_params[0]))}</th>'
            else:
                safe_groups = [html.escape(str(g)) for g in grouping_params]
                html_str += '<th class="text-center">Group (' + ' / '.join(safe_groups) + ')</th>'
            html_str += '<th class="text-center">Count (n)</th></tr></thead><tbody>'

            for _, row in group_counts.iterrows():
                safe_group_val = html.escape(str(row[group_col]))
                html_str += f'<tr><td class="text-center">{safe_group_val}</td><td class="text-center">{row["Count (n)"]}</td></tr>'

            # Total
            html_str += f'<tr class="table-info fw-bold"><td class="text-center">Total</td><td class="text-center">{len(df)}</td></tr>'
            html_str += '</tbody></table>'

            return html_str
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
