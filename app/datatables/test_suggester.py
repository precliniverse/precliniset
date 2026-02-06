# app/datatables/test_suggester.py
from flask_babel import lazy_gettext as _l


def suggest_statistical_tests(num_orig_group_params, num_orig_analysis_params, is_repeated, param_checks_by_param, subject_id_col, subject_id_col_present, available_numerical_cols, extra_context=None, column_types=None):
    """
    Suggest appropriate statistical tests based on data characteristics.
    
    Args:
        column_types: Optional dict mapping column names to 'numerical' or 'categorical'
    """
    if extra_context is None: extra_context = {}
    if column_types is None: column_types = {}
    has_covariate = extra_context.get('has_covariate', False)
    has_control_group = extra_context.get('has_control_group', False)

    suggestions = {}
    overall_suggestion_notes = []

    def add_test(test_list, key, name, reason, suggested=False):
        test_list.append({'key': key, 'name': name, 'reason': reason, 'suggested': suggested})

    if is_repeated:
        # ... (Existing RM logic - minimally touched logic, just indent/context)
        # For brevity in this tool call, I will need to be careful not to delete the RM block if I don't match it all.
        # I am replacing the WHOLE function to be safe or just the start and end?
        # The file is 170 lines. I will replace the signature and the independent logic block.
        # This is risky with `replace_file_content` on large blocks. Will try `multi_replace`.
        pass 
        rm_suggestions = {'possible_tests': [], 'overall_suggestion_notes': []}
        suggestions['repeated_measures_test_suggestions'] = rm_suggestions

        if not subject_id_col_present:
            add_test(rm_suggestions['possible_tests'], 'error_rm_grouping', _l('Error: Subject ID column missing'), _l('Cannot perform RM tests without the subject ID column.'), suggested=True)
            rm_suggestions['overall_suggestion_notes'].append(_l("<strong>Cannot perform Repeated Measures tests:</strong> The required Subject ID column ('{col}') was not found.").format(col=subject_id_col))
            add_test(rm_suggestions['possible_tests'], 'summary_only', _l('Summary Statistics Only'), _l('Skip statistical testing.'), suggested=False)
            add_test(rm_suggestions['possible_tests'], 'none', _l('None Selected'), _l('No test was automatically suggested.'), suggested=False)
            suggestions['checks_by_parameter'] = param_checks_by_param
            suggestions['overall_suggestion_notes'] = overall_suggestion_notes + rm_suggestions['overall_suggestion_notes']
            return suggestions

        if num_orig_analysis_params < 2:
             add_test(rm_suggestions['possible_tests'], 'error_rm_grouping', _l('Error: Need >1 numerical param for RM'), _l('Repeated Measures analysis requires at least two numerical parameters.'), suggested=True)
             rm_suggestions['overall_suggestion_notes'].append(_l("<strong>Cannot perform Repeated Measures tests:</strong> Requires selecting at least two 'Parameters to Analyze' which represent the repeated measurements."))
             add_test(rm_suggestions['possible_tests'], 'summary_only', _l('Summary Statistics Only'), _l('Skip statistical testing.'), suggested=False)
             add_test(rm_suggestions['possible_tests'], 'none', _l('None Selected'), _l('No test was automatically suggested.'), suggested=False)
             suggestions['checks_by_parameter'] = param_checks_by_param
             suggestions['overall_suggestion_notes'] = overall_suggestion_notes + rm_suggestions['overall_suggestion_notes']
             return suggestions

        num_between_factors = num_orig_group_params
        num_within_levels = num_orig_analysis_params
        any_param_check_error = any(pc.get('error') for pc in param_checks_by_param.values() if pc)
        any_group_not_normal_across_params = any(pc.get('any_group_not_normal', False) for pc in param_checks_by_param.values() if pc and not pc.get('error'))
        any_variance_issue_across_params = any(
    not pc.get('equal_variance', True) 
    for pc in param_checks_by_param.values() 
    if pc and pc.get('variance_results') and pc.get('variance_results').get('p_value') is not None and not pc.get('error')
)
        assumptions_met_for_parametric_rm = not any_param_check_error and not any_group_not_normal_across_params and not any_variance_issue_across_params
        rm_suggestions['overall_suggestion_notes'].append(_l("RM tests (ANOVA) also assume Sphericity for within-subject factors with >2 levels. Pingouin's Mixed ANOVA includes sphericity correction ('auto'). Statsmodels AnovaRM may require manual checks/corrections."))
        rm_suggestions['overall_suggestion_notes'].append(_l("<b>Robustness Note:</b> If Precliniset detects missing data points during RM ANOVA execution, it will automatically switch to a <b>Linear Mixed Model (LMM)</b> using REML to ensure valid results despite incomplete data."))

        if num_between_factors == 0:
            if num_within_levels == 2:
                 add_test(rm_suggestions['possible_tests'], 'ttest_paired', _l('Paired Samples t-test'), _l("Parametric test for 2 related groups."), suggested=assumptions_met_for_parametric_rm)
                 add_test(rm_suggestions['possible_tests'], 'wilcoxon', _l('Wilcoxon Signed-Rank Test'), _l("Non-parametric alternative for 2 related groups."), suggested=not assumptions_met_for_parametric_rm)
            elif num_within_levels > 2:
                add_test(rm_suggestions['possible_tests'], 'anova_rm_oneway', _l('One-Way Repeated Measures ANOVA (Pingouin)'), _l("Parametric test for >2 related groups. Uses Pingouin."), suggested=assumptions_met_for_parametric_rm)
                add_test(rm_suggestions['possible_tests'], 'friedman', _l('Friedman Test'), _l("Non-parametric alternative for >2 related groups."), suggested=not assumptions_met_for_parametric_rm)
            if num_within_levels > 2:
                 add_test(rm_suggestions['possible_tests'], 'anova_rm_oneway_sm', _l('One-Way Repeated Measures ANOVA (Statsmodels)'), _l("Parametric test for >2 related groups. Uses Statsmodels."))
        elif num_between_factors >= 1:
             num_factors_total = num_between_factors + 1
             test_name_mixed_anova = f"{num_factors_total}-Way Mixed ANOVA (Pingouin)" if num_factors_total > 2 else "Mixed ANOVA (Pingouin)"
             reason_mixed_anova = f"Parametric test with {num_between_factors} between-subject factor(s) and 1 within-subject factor ({num_within_levels} levels). Uses Pingouin library."
             add_test(rm_suggestions['possible_tests'], 'pingouin_mixed_anova', _l(test_name_mixed_anova), _l(reason_mixed_anova), suggested=assumptions_met_for_parametric_rm)
             rm_suggestions['overall_suggestion_notes'].append(_l("Non-parametric alternatives for mixed designs are not standard. Consider running non-parametric tests (e.g., Friedman) separately at each level combination of the between-subject factors, or using robust methods if parametric assumptions are not met for Mixed ANOVA."))
             if not assumptions_met_for_parametric_rm:
                 add_test(rm_suggestions['possible_tests'], 'summary_only', _l('Summary Only'), _l('Parametric assumptions for Mixed ANOVA not met. No standard non-parametric multi-way test directly suggested here.'), suggested=True)
             add_test(rm_suggestions['possible_tests'], 'anova_rm_mixed_sm', _l('Mixed ANOVA (Statsmodels)'), _l("Alternative Mixed ANOVA. May have limitations with between-subject effects in some library versions."))

        add_test(rm_suggestions['possible_tests'], 'summary_only', _l('Summary Statistics Only'), _l('Skip statistical testing.'), suggested=False)
        add_test(rm_suggestions['possible_tests'], 'none', _l('None Selected'), _l('No test was automatically suggested.'), suggested=False)

        if not any(t['key'].startswith('error') for t in rm_suggestions['possible_tests']):
             if not any(t['suggested'] for t in rm_suggestions['possible_tests']):
                  for t_loop in rm_suggestions['possible_tests']:
                       if t_loop['key'] == 'summary_only':
                            t_loop['suggested'] = True
                            rm_suggestions['overall_suggestion_notes'].append(_l("No specific parametric or non-parametric RM test was automatically suggested based on the selected parameters and data checks. Consider 'Summary Statistics Only' or manually select a test if appropriate."))
                            break
        suggestions['overall_suggestion_notes'] = overall_suggestion_notes + rm_suggestions['overall_suggestion_notes']
        suggestions['checks_by_parameter'] = param_checks_by_param
        return suggestions
    else:
        num_group_params = num_orig_group_params
        num_analysis_params = num_orig_analysis_params
        if num_analysis_params == 0:
             overall_suggestion_notes.append(_l("No numerical parameters selected for analysis."))
             return {'checks_by_parameter': param_checks_by_param, 'overall_suggestion_notes': overall_suggestion_notes}

        for param_name, checks in param_checks_by_param.items():
            param_suggestions_list = []
            if 'overall_suggestion_notes' not in checks or not isinstance(checks['overall_suggestion_notes'], list):
                 checks['overall_suggestion_notes'] = []
            if checks.get('error'):
                add_test(param_suggestions_list, 'error', _l('Error during checks'), checks['error'], suggested=True)
                checks['possible_tests'] = param_suggestions_list
                checks['overall_suggestion_notes'].append(_l("Statistical tests cannot be suggested due to errors during data checks for this parameter."))
                continue
            
            # --- General Scientific Transparency Notes ---
            if extra_context.get('exclude_outliers'):
                method = extra_context.get('outlier_method', 'iqr')
                if method == 'grubbs':
                    checks['overall_suggestion_notes'].append(_l("<b>Grubbs' Test</b> is selected for outlier detection. This is ideal for identifying a single most extreme outlier in normally distributed groups."))
                elif method == 'std':
                    checks['overall_suggestion_notes'].append(_l("<b>Standard Deviation (3x)</b> is selected for outlier detection. This assumes a relatively normal distribution of your data."))
                else:
                    checks['overall_suggestion_notes'].append(_l("<b>IQR (1.5x)</b> outlier detection is active. This is a conservative, non-parametric method to identify potential outliers."))
            
            # NEW: Check if this parameter is categorical
            param_is_categorical = column_types.get(param_name) == 'categorical'
            
            if param_is_categorical:
                # Categorical outcome variable detected
                # Suggest frequency-based tests (Chi-Square, Fisher's Exact)
                checks['overall_suggestion_notes'].append(
                    _l("'{param}' is a categorical variable. Frequency-based tests are appropriate.").format(param=param_name)
                )
                
                if num_group_params >= 1:
                    # We have grouping variables - suggest Chi-Square
                    add_test(
                        param_suggestions_list, 
                        'chi_square', 
                        _l('Chi-Square Test of Independence'),
                        _l('Suggested because both outcome and grouping variables are categorical. Tests association between categorical variables.'),
                        suggested=True
                    )
                    checks['overall_suggestion_notes'].append(
                        _l("Chi-Square Test suggested. Fisher's Exact Test will be used automatically if expected frequencies are low (<5).")
                    )
                else:
                    # No grouping - just descriptive
                    checks['overall_suggestion_notes'].append(
                        _l("No grouping parameters selected. Only frequency distribution will be shown.")
                    )
                    add_test(
                        param_suggestions_list,
                        'summary_only',
                        _l('Frequency Distribution'),
                        _l('Show frequency counts and percentages.'),
                        suggested=True
                    )
                
                add_test(param_suggestions_list, 'none', _l('Do Not Test'), _l('Skip statistical test.'))
                checks['possible_tests'] = param_suggestions_list
                continue  # Skip numerical test suggestions for categorical variables
            
            # Continue with numerical variable logic
            num_groups = checks.get('group_details', {}).get('count', 0)
            all_groups_normal = checks.get('all_groups_normal', False)
            equal_variance = checks.get('equal_variance', False)
            normality_could_be_checked = any(isinstance(r, dict) and 'p_value' in r for r in checks.get('normality_results', {}).values())
            variance_could_be_checked = checks.get('variance_results', {}).get('p_value') is not None
            
            # Debug logging
            from flask import current_app
            current_app.logger.debug(f"[TEST_SUGGESTER] Parameter: {param_name}")
            current_app.logger.debug(f"[TEST_SUGGESTER]   num_groups={num_groups}, num_group_params={num_orig_group_params}")
            current_app.logger.debug(f"[TEST_SUGGESTER]   all_groups_normal={all_groups_normal}, normality_could_be_checked={normality_could_be_checked}")
            current_app.logger.debug(f"[TEST_SUGGESTER]   equal_variance={equal_variance}, variance_could_be_checked={variance_could_be_checked}")
            current_app.logger.debug(f"[TEST_SUGGESTER]   normality_results={checks.get('normality_results', {})}")
            current_app.logger.debug(f"[TEST_SUGGESTER]   variance_results={checks.get('variance_results', {})}")
            
            add_test(param_suggestions_list, 'summary_only', _l('Summary Statistics Only'), _l('Skip statistical testing for this parameter.'), suggested=False)

            if num_groups == 0:
                 checks['overall_suggestion_notes'].append(_l("No grouping parameters selected. Cannot perform group comparisons."))
                 for t_loop in param_suggestions_list:
                      if t_loop['key'] == 'summary_only': t_loop['suggested'] = True; break
            elif num_groups == 1:
                 checks['overall_suggestion_notes'].append(_l("Only one group found. Cannot perform group comparisons."))
                 for t_loop in param_suggestions_list:
                      if t_loop['key'] == 'summary_only': t_loop['suggested'] = True; break
            elif num_groups == 2:
                 suggested_parametric = False
                 if normality_could_be_checked and all_groups_normal:
                     if variance_could_be_checked:
                         if equal_variance: 
                             p_var = checks['variance_results'].get('p_value', 0)
                             reason = _l('Suggested because data is normal and variances are equal (Levene p={p:.3f} > 0.05).').format(p=p_var)
                             add_test(param_suggestions_list, 'ttest_ind_equal_var', _l('Independent T-test'), reason, suggested=True); suggested_parametric = True
                         else: 
                             p_var = checks['variance_results'].get('p_value', 0)
                             reason = _l("Suggested because data is normal but variances are unequal (Levene p={p:.3f} < 0.05).").format(p=p_var)
                             add_test(param_suggestions_list, 'ttest_ind_unequal_var', _l("Welch's T-test"), reason, suggested=True); suggested_parametric = True
                     else: 
                         add_test(param_suggestions_list, 'ttest_ind_unequal_var', _l("Welch's T-test"), _l('Suggested because data is normal. Variance could not be checked, so robust Welch\'s test is safer.'), suggested=True); suggested_parametric = True; checks['overall_suggestion_notes'].append(_l("Variance homogeneity could not be checked due to insufficient data/groups. Welch's t-test suggested."))
                 
                 if not suggested_parametric:
                      add_test(param_suggestions_list, 'mannwhitneyu', _l('Mann-Whitney U Test'), _l('Suggested because normality assumption was not met (p < 0.05 in one or more groups).'), suggested=True)
                      if not (normality_could_be_checked and all_groups_normal):
                           checks['overall_suggestion_notes'].append(_l("Normality assumption not met or could not be checked. Non-parametric Mann-Whitney U test suggested."))
                 if not any(t['key'] == 'ttest_ind_equal_var' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'ttest_ind_equal_var', _l('Independent T-test'), _l('Parametric, 2 groups, assumes normality & equal variance.'))
                 if not any(t['key'] == 'ttest_ind_unequal_var' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'ttest_ind_unequal_var', _l('Welch\'s T-test'), _l('Parametric, 2 groups, assumes normality, allows unequal variances.'))
                 if not any(t['key'] == 'mannwhitneyu' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'mannwhitneyu', _l('Mann-Whitney U Test'), _l('Non-parametric alternative for 2 independent groups.'))
                 if not any(t['key'] == 'kruskalwallis' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'kruskalwallis', _l('Kruskal-Wallis H Test'), _l('Non-parametric alternative for >=2 independent groups.'))
            elif num_groups > 2:
                 suggested_parametric = False
                 if normality_could_be_checked and all_groups_normal and variance_could_be_checked and equal_variance:
                      p_var = checks['variance_results'].get('p_value', 0)
                      reason_base = _l('Suggested because data is normal and variances are equal (Levene p={p:.3f}).').format(p=p_var)
                      
                      if num_group_params == 1: 
                          add_test(param_suggestions_list, 'anova_oneway', _l('One-Way ANOVA'), reason_base, suggested=True); suggested_parametric = True; checks['overall_suggestion_notes'].append(_l("One-Way ANOVA suggested. Post-hoc (Tukey) will run if significant."))
                      elif num_group_params == 2: 
                          add_test(param_suggestions_list, 'anova_twoway', _l('Two-Way ANOVA'), reason_base, suggested=True); suggested_parametric = True; checks['overall_suggestion_notes'].append(_l("Two-Way ANOVA suggested."))
                      elif num_group_params > 2: 
                          add_test(param_suggestions_list, 'anova_nway', _l('N-Way ANOVA'), reason_base, suggested=True); suggested_parametric = True; checks['overall_suggestion_notes'].append(_l("N-Way ANOVA suggested."))
                 
                 if not suggested_parametric:
                     add_test(param_suggestions_list, 'kruskalwallis', _l('Kruskal-Wallis H Test'), _l('Suggested because normality or variance assumptions were not met.'), suggested=True)
                     checks['overall_suggestion_notes'].append(_l("Normality/Variance tests failed. Deducting Non-Parametric test (Kruskal-Wallis)."))
                     if num_groups > 2: checks['overall_suggestion_notes'].append(_l("Post-hoc (Dunn's) will run if significant."))
                 
                 if num_group_params == 1 and not any(t['key'] == 'anova_oneway' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'anova_oneway', _l('One-Way ANOVA'), _l('Parametric, >2 groups (1 factor), assumes normality & equal variance.'))
                 elif num_group_params == 2 and not any(t['key'] == 'anova_twoway' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'anova_twoway', _l('Two-Way ANOVA'), _l('Parametric, 2 independent grouping factors, assumes normality & equal variance.'))
                 elif num_group_params > 2 and not any(t['key'] == 'anova_nway' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'anova_nway', _l('N-Way ANOVA'), _l('Parametric, >2 independent grouping factors, assumes normality & equal variance.'))
                 if not any(t['key'] == 'kruskalwallis' and t.get('suggested') for t in param_suggestions_list): add_test(param_suggestions_list, 'kruskalwallis', _l('Kruskal-Wallis H Test'), _l('Non-parametric alternative for >=2 independent groups.'))

            if num_analysis_params == 1 and num_group_params == 1 and len(available_numerical_cols) >= 1:
                 # ANCOVA
                 if has_covariate:
                      add_test(param_suggestions_list, 'ancova', _l('ANCOVA'), _l('Parametric test controlling for selected covariate.'), suggested=True)
                      checks['overall_suggestion_notes'].append(_l("ANCOVA suggested due to presence of a covariate."))
                 else:
                      add_test(param_suggestions_list, 'ancova', _l('ANCOVA'), _l('Parametric test for 1 DV, 1 IV, controlling for a covariate (requires selecting a numerical covariate).'), suggested=False)

                 # Dunnett's
                 if has_control_group:
                      add_test(param_suggestions_list, 'dunnett', _l("Dunnett's Test"), _l('Compare all groups against the selected Control Group.'), suggested=True)
                      checks['overall_suggestion_notes'].append(_l("Dunnett's test suggested because a Control Group is selected."))
                 elif num_groups > 2: # Logic to suggest Dunnett as *possible* if not selected?
                      add_test(param_suggestions_list, 'dunnett', _l("Dunnett's Test"), _l('Compare all groups against a Control Group (requires selecting a Control Group).'), suggested=False)
            add_test(param_suggestions_list, 'none', _l('Do Not Test'), _l('Skip statistical test.'))
            is_any_suggested = any(test.get('suggested', False) for test in param_suggestions_list)
            if not is_any_suggested:
                 summary_exists = any(test['key'] == 'summary_only' for test in param_suggestions_list)
                 if not summary_exists:
                     is_only_error = all(t['key'].startswith('error') for t in param_suggestions_list if t.get('suggested'))
                     if not is_only_error: 
                         add_test(param_suggestions_list, 'summary_only', _l('Summary Only'), _l('View descriptive statistics and graph without a formal test.'))
                 summary_exists_now = any(test['key'] == 'summary_only' for test in param_suggestions_list)
                 if summary_exists_now and not is_any_suggested:
                     for t_loop in param_suggestions_list: 
                         if t_loop['key'] == 'summary_only': t_loop['suggested'] = True; break
            checks['possible_tests'] = param_suggestions_list 

        if num_analysis_params > 1 and num_group_params > 0: 
             if not any(isinstance(item, dict) and item.get('key') == 'manova' for item in overall_suggestion_notes):
                  all_params_normal_for_manova = all(pc.get('all_groups_normal', False) for pc in param_checks_by_param.values() if pc is not None and not pc.get('error'))
                  all_params_equal_variance_for_manova = all(
    pc.get('equal_variance', True) 
    for pc in param_checks_by_param.values() 
    if pc and pc.get('variance_results') and pc.get('variance_results').get('p_value') is not None and not pc.get('error')
)
                  assumptions_met_for_manova_proxy = all_params_normal_for_manova and all_params_equal_variance_for_manova
                  overall_suggestion_notes.append({'key': 'manova', 'name': _l('MANOVA'), 'reason': _l('Multivariate test for multiple DVs and one or more IVs.'), 'suggested': assumptions_met_for_manova_proxy})
                  overall_suggestion_notes.append(_l("MANOVA is suggested as you have selected multiple parameters to analyze and grouping parameters. It tests the effect of grouping on the combination of parameters."))
        suggestions['overall_suggestion_notes'] = overall_suggestion_notes
        suggestions['checks_by_parameter'] = param_checks_by_param 
        return suggestions
    return {}
