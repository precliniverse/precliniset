# app/datatables/data_prepper.py
import pandas as pd
from flask import current_app
from flask_babel import lazy_gettext
from scipy.stats import levene, shapiro

from .analysis_utils import detect_outliers


def perform_data_checks(df, grouping_params, numerical_params, is_repeated, subject_id_col='ID', exclude_outliers=False):
    results_by_param = {}
    min_shapiro_size = 3
    min_levene_groups = 2
    min_levene_size_per_group = 2
    alpha = 0.05

    df_temp_orig = df.copy()

    # --- START MODIFICATION: Handle Repeated Measures Separately and Robustly ---
    if is_repeated:
        id_vars = [col for col in [subject_id_col] + grouping_params if col in df_temp_orig.columns]
        if not id_vars or not numerical_params:
            results_by_param['rm_set_error'] = {'error': lazy_gettext("Could not prepare data for RM checks; ID or grouping columns missing.")}
            return results_by_param

        try:
            df_long = pd.melt(df_temp_orig, id_vars=id_vars, value_vars=numerical_params,
                              var_name='_WithinFactorLevel_', value_name='_MeasurementValue_')
            df_long['_MeasurementValue_'] = pd.to_numeric(df_long['_MeasurementValue_'], errors='coerce')
        except Exception as e:
            results_by_param['rm_set_error'] = {'error': lazy_gettext("Failed to reshape data for RM checks: %(error)s", error=str(e))}
            return results_by_param

        for param_name in numerical_params:
            param_results = {
                'group_details': {}, 'normality_results': {}, 'variance_results': None,
                'notes': [], 'error': None, 'all_groups_normal': False, 'any_group_not_normal': False,
                'equal_variance': False, 'group_col_used': None, 'outliers_excluded_for_checks': 0
            }
            
            df_level_initial = df_long[df_long['_WithinFactorLevel_'] == param_name].copy()
            
            # --- START MODIFICATION: Detailed check for what is being dropped ---
            if df_level_initial.empty:
                param_results['error'] = lazy_gettext("No data exists for the parameter '{param}'.").format(param=param_name)
                results_by_param[param_name] = param_results
                continue

            missing_value_cols = [col for col in ['_MeasurementValue_'] + grouping_params if df_level_initial[col].isnull().any()]
            
            df_level = df_level_initial.dropna(subset=['_MeasurementValue_'] + grouping_params)

            if df_level.empty:
                reason = ""
                if '_MeasurementValue_' in missing_value_cols:
                    reason += lazy_gettext("all measurement values are missing")
                
                grouping_cols_with_missing = [col for col in grouping_params if col in missing_value_cols]
                if grouping_cols_with_missing:
                    if reason: reason += "; "
                    reason += lazy_gettext("missing values found in grouping parameter(s): {params}").format(params=', '.join(grouping_cols_with_missing))
                
                if not reason:
                     reason = lazy_gettext("an unknown reason (data might be sparse across groups).")

                param_results['error'] = lazy_gettext("For repeated measure '{param}', no valid data remains after filtering because {reason}.").format(param=param_name, reason=reason)
                results_by_param[param_name] = param_results
                continue
            # --- END MODIFICATION ---

            group_col = None
            if not grouping_params:
                group_col = '_OverallCheckGroup'; df_level[group_col] = 'Overall'
            elif len(grouping_params) == 1:
                group_col = grouping_params[0]
            else:
                sorted_gps = sorted(grouping_params)
                df_level['combined_group_check'] = df_level[sorted_gps].astype(str).fillna('N/A').apply(lambda r: '_'.join(r.values), axis=1)
                group_col = 'combined_group_check'
            
            param_results['group_col_used'] = group_col
            combined_groups = df_level[group_col].unique()
            group_data_for_levene = []
            param_results['all_groups_normal'] = True
            param_results['any_group_not_normal'] = False

            for group_name_val in combined_groups:
                group_data = df_level[df_level[group_col] == group_name_val]['_MeasurementValue_'].dropna()
                n = len(group_data)
                param_results['group_details'][str(group_name_val)] = {'count': n}
                
                if n >= min_shapiro_size and group_data.nunique() > 1:
                    stat, p_val_shapiro = shapiro(group_data)
                    param_results['normality_results'][str(group_name_val)] = {'p_value': float(p_val_shapiro), 'n': n, 'stat': float(stat)}
                    if p_val_shapiro < alpha:
                        param_results['all_groups_normal'] = False
                        param_results['any_group_not_normal'] = True
                elif group_data.nunique() <= 1:
                    param_results['normality_results'][str(group_name_val)] = {'note': lazy_gettext('Constant data in group'), 'n': n}
                    param_results['all_groups_normal'] = False
                    param_results['any_group_not_normal'] = True
                else:
                    param_results['normality_results'][str(group_name_val)] = {'note': lazy_gettext('Insufficient data (n<{min_shapiro_size})').format(min_shapiro_size=min_shapiro_size), 'n': n}
                    param_results['all_groups_normal'] = False
                    param_results['notes'].append(lazy_gettext("Normality check could not be performed for group '{group_name}' due to insufficient data (n={n} < {min_shapiro_size}).").format(group_name=group_name_val, n=n, min_shapiro_size=min_shapiro_size))

                if len(group_data) >= min_levene_size_per_group and group_data.var(ddof=1) > 1e-10:
                    group_data_for_levene.append(group_data)

            param_results['equal_variance'] = False
            if len(group_data_for_levene) >= min_levene_groups:
                stat_levene, p_levene = levene(*group_data_for_levene)
                param_results['variance_results'] = {'p_value': float(p_levene), 'stat': float(stat_levene)}
                if p_levene > alpha:
                    param_results['equal_variance'] = True
            else:
                param_results['variance_results'] = {'note': lazy_gettext('Insufficient groups with non-constant data ( < {min_levene_groups})').format(min_levene_groups=min_levene_groups)}
                param_results['notes'].append(lazy_gettext("Variance homogeneity check (Levene's) could not be performed due to insufficient groups with data (need >= {min_levene_groups} groups with >= {min_levene_size_per_group} non-constant data points).").format(min_levene_groups=min_levene_groups, min_levene_size_per_group=min_levene_size_per_group))

            results_by_param[param_name] = param_results
        return results_by_param
    # --- END MODIFICATION ---

    # Original logic for independent groups
    for col in grouping_params:
         if col in df_temp_orig.columns:
              df_temp_orig[col] = df_temp_orig[col].astype(str).fillna('')
         else:
              current_app.logger.error(f"Grouping column '{col}' not found in DataFrame for analysis checks.")
              for num_param_error in numerical_params:
                  param_results_error = {
                      'error': lazy_gettext("Grouping column '{col}' not found in the data for checks.").format(col=col), # Use lazy_gettext
                      'group_details': {}, 'normality_results': {}, 'variance_results': None, 'notes': [],
                      'all_groups_normal': False, 'any_group_not_normal': False, 'equal_variance': False, 'group_col_used': None,
                      'overall_suggestion_notes': [], 'outliers_excluded_for_checks': 0
                  }
                  results_by_param[num_param_error] = param_results_error
              return results_by_param

    subject_id_col_present_for_checks = subject_id_col in df_temp_orig.columns
    if is_repeated and subject_id_col in df_temp_orig.columns:
         try:
            if df_temp_orig[subject_id_col].dropna().empty:
                 current_app.logger.warning(f"Subject ID column '{subject_id_col}' contains only missing values after dropping NaNs.")
                 subject_id_col_present_for_checks = False
                 for param_note in numerical_params:
                      if param_note not in results_by_param: results_by_param[param_note] = {}
                      results_by_param[param_note]['notes'] = results_by_param[param_note].get('notes', []) + [lazy_gettext("Subject ID column '{col}' contains only missing values.").format(col=subject_id_col)]
            else:
                df_temp_orig[subject_id_col] = df_temp_orig[subject_id_col].astype(str)
                subject_id_col_present_for_checks = True
         except Exception as e:
             current_app.logger.error(f"Error processing subject ID col {subject_id_col} for checks: {e}", exc_info=True)
             subject_id_col_present_for_checks = False
             for param_note in numerical_params:
                  if param_note not in results_by_param: results_by_param[param_note] = {}
                  results_by_param[param_note]['notes'] = results_by_param[param_note].get('notes', []) + [lazy_gettext("Subject ID column '{col}' could not be processed for RM checks due to format issues or missing values.").format(col=subject_id_col)]

    for num_param in numerical_params:
        param_results = {
            'group_details': {}, 'normality_results': {}, 'variance_results': None,
            'notes': [], 'error': None, 'all_groups_normal': False, 'any_group_not_normal': False,
            'equal_variance': False, 'group_col_used': None, 'overall_suggestion_notes': [],
            'outliers_excluded_for_checks': 0
        }
        if num_param in results_by_param and 'notes' in results_by_param[num_param]:
             param_results['notes'].extend(results_by_param[num_param]['notes'])

        try:
            cols_for_this_param_checks = [num_param] + grouping_params
            df_clean_for_param = df_temp_orig.dropna(subset=cols_for_this_param_checks).copy()
            df_clean_for_param[num_param] = pd.to_numeric(df_clean_for_param[num_param], errors='coerce')
            df_clean_for_param = df_clean_for_param.dropna(subset=[num_param])

            group_col = None
            if not grouping_params:
                group_col = '_OverallCheckGroup'; df_clean_for_param[group_col] = 'Overall'
            elif len(grouping_params) == 1:
                group_col = grouping_params[0]
            else:
                # Deduplicate grouping params to avoid duplicate columns issues
                sorted_gps = sorted(list(set(grouping_params)))
                
                if not all(col in df_clean_for_param.columns for col in sorted_gps):
                    param_results['error'] = lazy_gettext("Internal error: Grouping column missing for combined group creation.")
                    results_by_param[num_param] = param_results; continue
                
                # Ensure no duplicate columns in the dataframe to avoid ambiguity
                df_clean_for_param = df_clean_for_param.loc[:, ~df_clean_for_param.columns.duplicated()]

                # Use vectorized string concatenation for performance and stability
                if sorted_gps:
                    # Initialize with the first column
                    combined_series = df_clean_for_param[sorted_gps[0]].astype(str).fillna('N/A')
                    for col in sorted_gps[1:]:
                        combined_series = combined_series + '_' + df_clean_for_param[col].astype(str).fillna('N/A')
                    df_clean_for_param['combined_group_check'] = combined_series
                else:
                    df_clean_for_param['combined_group_check'] = 'Overall'
                
                group_col = 'combined_group_check'
            
            param_results['group_col_used'] = group_col

            if exclude_outliers and num_param in df_clean_for_param.columns and pd.api.types.is_numeric_dtype(df_clean_for_param[num_param]):
                df_clean_after_outliers_list = []
                total_outliers_for_param_checks = 0
                for _, group_df_iter in df_clean_for_param.groupby(group_col, dropna=False):
                    current_group_series = group_df_iter[num_param].dropna()
                    if not current_group_series.empty:
                        outliers_mask_group = detect_outliers(current_group_series)
                        n_outliers_in_group = outliers_mask_group.sum()
                        total_outliers_for_param_checks += n_outliers_in_group
                        df_clean_after_outliers_list.append(group_df_iter[~outliers_mask_group])
                    else:
                        df_clean_after_outliers_list.append(group_df_iter)

                if total_outliers_for_param_checks > 0:
                    param_results['notes'].append(
                        lazy_gettext("For data checks on '{param}', {n} outlier(s) were identified (IQR 1.5x) and excluded across groups.").format(
                            n=total_outliers_for_param_checks, param=num_param
                        )
                    )
                    param_results['outliers_excluded_for_checks'] = total_outliers_for_param_checks
                
                if df_clean_after_outliers_list:
                    df_clean_for_param = pd.concat(df_clean_after_outliers_list)
                else: 
                    df_clean_for_param = pd.DataFrame(columns=df_clean_for_param.columns)


            if df_clean_for_param.empty:
                 param_results['error'] = lazy_gettext("No valid data found for '{num_param}' after filtering (and potentially outlier exclusion) for checks.").format(num_param=num_param)
                 results_by_param[num_param] = param_results
                 continue

            param_results['group_details'].update({'type': 'none' if not grouping_params else ('single' if len(grouping_params) == 1 else 'combined'), 'original_params': grouping_params})
            combined_groups = df_clean_for_param[group_col].unique()
            num_combined_groups = len(combined_groups)
            param_results['group_details']['count'] = num_combined_groups
            param_results['group_details']['names'] = list(combined_groups)


            if num_combined_groups < 2 and len(grouping_params) > 0:
                # Identify which original grouping parameter(s) have only one unique value
                problematic_params = []
                for gp in grouping_params:
                    if df_clean_for_param[gp].nunique() < 2:
                        problematic_params.append(gp)
                
                if problematic_params:
                    error_msg = lazy_gettext("Grouping parameter(s) '{params}' must have at least 2 unique values for comparison, but fewer were found.").format(params=', '.join(problematic_params))
                else:
                    # This case might occur if the combination of groups is what results in < 2 levels, which is less common but possible
                    error_msg = lazy_gettext("Fewer than 2 distinct combined groups found for the selected grouping parameters (found {count}).").format(count=num_combined_groups)
                
                param_results['error'] = error_msg
                results_by_param[num_param] = param_results
                continue

            group_data_for_levene = []
            param_results['all_groups_normal'] = True; param_results['any_group_not_normal'] = False

            for group_name_val in combined_groups:
                group_data = df_clean_for_param[df_clean_for_param[group_col] == group_name_val][num_param].dropna(); n = len(group_data)
                param_results['group_details'][str(group_name_val)] = {'count': n}
                if n >= min_shapiro_size and group_data.nunique() > 1:
                    try:
                        stat, p_val_shapiro = shapiro(group_data)
                        param_results['normality_results'][str(group_name_val)] = {'p_value': float(p_val_shapiro), 'n': n, 'stat': float(stat)}
                        if p_val_shapiro < alpha: param_results['all_groups_normal'] = False; param_results['any_group_not_normal'] = True
                    except Exception as shapiro_err: param_results['normality_results'][str(group_name_val)] = {'note': lazy_gettext('Shapiro failed: {err}').format(err=shapiro_err), 'n': n}; param_results['all_groups_normal'] = False; param_results['any_group_not_normal'] = True; current_app.logger.warning(f"Shapiro test failed for param {num_param}, group {group_name_val}: {shapiro_err}"); param_results['notes'].append(lazy_gettext("Normality check failed for group '{group_name}'. Check data for this group.").format(group_name=group_name_val))
                elif group_data.nunique() <= 1: param_results['normality_results'][str(group_name_val)] = {'note': lazy_gettext('Constant data in group'), 'n': n}; param_results['all_groups_normal'] = False; param_results['any_group_not_normal'] = True
                else: param_results['normality_results'][str(group_name_val)] = {'note': lazy_gettext('Insufficient data (n<{min_shapiro_size})').format(min_shapiro_size=min_shapiro_size), 'n': n}; param_results['all_groups_normal'] = False; param_results['notes'].append(lazy_gettext("Normality check could not be performed for group '{group_name}' due to insufficient data (n={n} < {min_shapiro_size}).").format(group_name=group_name_val, n=n, min_shapiro_size=min_shapiro_size))
                if len(group_data) >= min_levene_size_per_group and group_data.var(ddof=1) > 1e-10: group_data_for_levene.append(group_data)

            param_results['equal_variance'] = False
            if len(group_data_for_levene) >= min_levene_groups:
                try:
                    stat_levene, p_levene = levene(*group_data_for_levene)
                    param_results['variance_results'] = {'p_value': float(p_levene), 'stat': float(stat_levene)}
                    if p_levene > alpha: param_results['equal_variance'] = True
                except Exception as levene_err: param_results['variance_results'] = {'note': lazy_gettext('Levene failed: {err}').format(err=levene_err)}; current_app.logger.warning(f"Levene test failed for param {num_param}: {levene_err}"); param_results['notes'].append(lazy_gettext("Variance homogeneity check (Levene's) failed unexpectedly."))
            else: param_results['variance_results'] = {'note': lazy_gettext('Insufficient groups with non-constant data ( < {min_levene_groups})').format(min_levene_groups=min_levene_groups)}; param_results['notes'].append(lazy_gettext("Variance homogeneity check (Levene's) could not be performed due to insufficient groups with data (need >= {min_levene_groups} groups with >= {min_levene_size_per_group} non-constant data points).").format(min_levene_groups=min_levene_groups, min_levene_size_per_group=min_levene_size_per_group))

            if param_results['any_group_not_normal']: param_results['notes'].append(lazy_gettext("Normality assumption likely violated in one or more groups. Consider non-parametric tests or transformations."))
            if not param_results['equal_variance'] and param_results['variance_results'] and param_results['variance_results'].get('p_value') is not None: param_results['notes'].append(lazy_gettext("Homogeneity of variances assumption likely violated. Consider Welch's t-test (for 2 groups) or non-parametric tests."))
        except KeyError as ke:
            param_results['error'] = lazy_gettext("Column '{key}' not found during data checks.").format(key=str(ke))
            current_app.logger.error(f"KeyError checking param {num_param}: {ke}", exc_info=True)
        except Exception as e:
            error_msg_str = str(e)
            param_results['error'] = lazy_gettext("An unexpected error occurred during data checks: %(error_message)s") % {'error_message': error_msg_str}
            current_app.logger.error(f"Unexpected error during perform_data_checks for parameter '{num_param}'. Error: {error_msg_str}", exc_info=True)
        results_by_param[num_param] = param_results
    return results_by_param