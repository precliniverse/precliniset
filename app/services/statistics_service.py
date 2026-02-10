import pandas as pd
import scipy.stats as stats
import statsmodels.api as sm
import statsmodels.formula.api as smf
import statsmodels.stats.multicomp as multi
import pingouin as pg
from flask import current_app
from flask_babel import lazy_gettext as _l
from scipy.stats import ttest_ind, ttest_rel, mannwhitneyu, wilcoxon, kruskal, friedmanchisquare
from app.datatables.analysis_utils import detect_outliers, sanitize_df_columns_for_patsy, quote_name

class StatisticsService:
    """
    Service responsible for executing statistical tests on DataFrames.
    Returns raw data structures (dicts/lists), NOT HTML.
    """

    def execute_test(self, df, test_key, dv_col, grouping_cols, is_repeated, subject_id_col, exclude_outliers=False, extra_params=None):
        """
        Main entry point to execute a statistical test.
        """
        result = {
            'test': self._get_test_name(test_key),
            'statistic': None, 
            'p_value': None, 
            'results_data': None, 
            'posthoc_data': None, 
            'error': None, 
            'groups_compared': None, 
            'n_pairs': None, 
            'n_subjects': None, 
            'notes': [], 
            'outliers_excluded_for_test': 0
        }

        if test_key in ['none', 'error', 'summary_only', 'error_rm_grouping']:
            return self._handle_special_keys(test_key, result)

        try:
            # 1. Prepare Data
            outlier_method = extra_params.get('outlier_method', 'iqr') if extra_params else 'iqr'
            outlier_threshold = extra_params.get('outlier_threshold', 1.5) if extra_params else 1.5
            
            df_test, outliers_count = self._prepare_data_for_test(
                df, test_key, dv_col, grouping_cols, is_repeated, subject_id_col, 
                exclude_outliers, outlier_method, outlier_threshold
            )
            if outliers_count > 0:
                result['outliers_excluded_for_test'] = outliers_count
                result['notes'].append(_l("{n} outlier(s) excluded before test.").format(n=outliers_count))

            if df_test.empty:
                raise ValueError(_l("No valid data available for test after filtering."))

            # 2. Dispatch
            handler_name = f"_run_{test_key}"
            if hasattr(self, handler_name):
                handler = getattr(self, handler_name)
                # Check if handler accepts extra_params
                import inspect
                sig = inspect.signature(handler)
                if 'extra_params' in sig.parameters:
                    handler(df_test, dv_col, grouping_cols, subject_id_col, result, extra_params=extra_params)
                else:
                    handler(df_test, dv_col, grouping_cols, subject_id_col, result)
            else:
                # Fallback for aliased tests
                if test_key == 'anova_rm_mixed_sm':
                    self._run_pingouin_mixed_anova(df_test, dv_col, grouping_cols, subject_id_col, result)
                elif test_key == 'anova_rm_oneway_sm':
                    self._run_anova_rm_oneway(df_test, dv_col, grouping_cols, subject_id_col, result)
                else:
                    result['error'] = _l("Internal error: Unhandled test key '{key}'.").format(key=test_key)

        except Exception as e:
            result['error'] = str(e)
            current_app.logger.error(f"Error executing test {test_key}: {e}", exc_info=True)

        # Ensure serializable types
        if isinstance(result.get('statistic'), (int, float)): 
            result['statistic'] = float(result['statistic'])
        if isinstance(result.get('p_value'), (int, float)): 
            result['p_value'] = float(result['p_value'])
        
        return result

    def _prepare_data_for_test(self, df, test_key, dv_col, grouping_cols, is_repeated, subject_id_col, exclude_outliers, outlier_method='iqr', outlier_threshold=1.5):
        df_test = df.copy()
        cols_to_numeric = []
        
        if test_key == 'manova': 
            cols_to_numeric = dv_col if isinstance(dv_col, list) else [dv_col]
        elif test_key in ['correlation', 'chi_square']:
            cols_to_numeric = [] # Skip numeric coercion for these tests
        elif is_repeated: 
            cols_to_numeric = ['_MeasurementValue_']
        else: 
            cols_to_numeric = [dv_col]

        for col in cols_to_numeric:
            if col in df_test.columns:
                df_test[col] = pd.to_numeric(df_test[col], errors='coerce')
        
        outliers_count = 0
        if exclude_outliers and test_key != 'chi_square':
            if is_repeated and '_MeasurementValue_' in df_test.columns:
                mask, _ = detect_outliers(df_test['_MeasurementValue_'], method=outlier_method, threshold=outlier_threshold)
                outliers_count = int(mask.sum())
                df_test = df_test[~mask]
            elif test_key != 'manova' and dv_col in df_test.columns:
                mask, _ = detect_outliers(df_test[dv_col], method=outlier_method, threshold=outlier_threshold)
                outliers_count = int(mask.sum())
                df_test = df_test[~mask]

        if test_key != 'manova':
            # Ensure grouping columns are present
            valid_grouping = [g for g in (grouping_cols or []) if g in df_test.columns]
            df_test = df_test.dropna(subset=cols_to_numeric + valid_grouping)
        
        return df_test, outliers_count
    
    def _run_lmm_blocking(self, df, dv, groups, subject_id, res, extra_params=None):
        """
        Runs a Linear Mixed Model (LMM) to account for a Blocking Factor (Random Effect).
        Model: DV ~ Group + (1|Block)
        """
        block = extra_params.get('random_effect')
        if not block or block not in df.columns:
            res['error'] = "Blocking factor (random effect) not specified or not found."
            return

        group_col = self._get_single_group_col(df, groups)
        
        try:
            # Using Pingouin's mixed_linear_model
            # Formula API is cleaner: dv ~ fixed + (1|random)
            # Pingouin syntax: formula="dv ~ fixed", groups="random"
            
            # Ensure numeric
            df[dv] = pd.to_numeric(df[dv], errors='coerce')
            df = df.dropna(subset=[dv, group_col, block])
            
            # Simple model: Fixed effect = Group, Random Intercept = Block
            lmm = pg.mixed_linear_model(
                data=df, 
                dv=dv, 
                formula=f"{quote_name(dv)} ~ C({quote_name(group_col)})", 
                groups=block
            )
            
            res['results_data'] = {
                'title': _l('Linear Mixed Model (Corrected for %(block)s)', block=block),
                'columns': lmm.columns.tolist(),
                'rows': lmm.to_dict('records')
            }
            
            # Extract Fixed Effect P-value for the Group
            # Pingouin returns terms like "Intercept", "C(Group)[T.Val]"
            # We look for the Group term
            
            # LMM p-values in Pingouin are often labelled 'pval'
            group_rows = lmm[lmm['Term'].str.contains(group_col, na=False)]
            if not group_rows.empty:
                # If multiple levels (e.g. Group B vs A, Group C vs A), we might have multiple p-values.
                # LMM doesn't give a single "Omnibus" p-value for the factor like ANOVA does easily 
                # without running a separate anova() on the model object.
                # However, Pingouin's mixed_linear_model return includes a stats table.
                
                # For scientific reporting, users usually want the Omnibus ANOVA style F-test of the fixed effect.
                # We can try statsmodels for that if Pingouin is limited, or just report the coefficients table.
                
                res['p_value'] = group_rows['pval'].min() # Heuristic: report min p-value of contrasts
                res['notes'].append(_l("Result shows model coefficients. p-value indicates significance of specific contrasts vs reference level."))
            else:
                res['p_value'] = None
                
            res['notes'].append(_l("Used Linear Mixed Model to control for random effect of '%(block)s'.", block=block))

        except Exception as e:
            res['error'] = f"LMM Failed: {str(e)}"
            current_app.logger.error(f"LMM Error: {e}", exc_info=True)

    # --- Specific Test Handlers ---

    def _run_ttest_ind(self, df, dv, groups, res, equal_var):
        group_col = self._get_single_group_col(df, groups)
        groups_data = [g[dv].dropna() for name, g in df.groupby(group_col) if not g[dv].dropna().empty]
        if len(groups_data) != 2: raise ValueError(_l("Independent T-test requires exactly 2 groups."))
        t_stat, p_val = ttest_ind(groups_data[0], groups_data[1], equal_var=equal_var, nan_policy='omit')
        res.update({'statistic': t_stat, 'p_value': p_val, 'groups_compared': 2})

    def _run_ttest_ind_equal_var(self, df, dv, groups, subject_id, res):
        self._run_ttest_ind(df, dv, groups, res, equal_var=True)

    def _run_ttest_ind_unequal_var(self, df, dv, groups, subject_id, res):
        self._run_ttest_ind(df, dv, groups, res, equal_var=False)

    def _run_mannwhitneyu(self, df, dv, groups, subject_id, res):
        group_col = self._get_single_group_col(df, groups)
        groups_data = [g[dv].dropna() for name, g in df.groupby(group_col) if not g[dv].dropna().empty]
        if len(groups_data) != 2: raise ValueError(_l("Mann-Whitney U requires exactly 2 groups."))
        u_stat, p_val = mannwhitneyu(groups_data[0], groups_data[1], alternative='two-sided', nan_policy='omit')
        res.update({'statistic': u_stat, 'p_value': p_val, 'groups_compared': 2})

    def _run_wilcoxon(self, df, dv, groups, subject_id, res):
        df_wide = df.pivot(index=subject_id, columns='_WithinFactorLevel_', values='_MeasurementValue_').dropna()
        if df_wide.shape[1] != 2: raise ValueError(_l("Wilcoxon requires exactly 2 time points/conditions."))
        cols = df_wide.columns
        stat, p_val = wilcoxon(df_wide[cols[0]], df_wide[cols[1]])
        res.update({'statistic': stat, 'p_value': p_val, 'n_pairs': len(df_wide)})

    def _run_kruskalwallis(self, df, dv, groups, subject_id, res, extra_params=None):
        group_col = self._get_single_group_col(df, groups)
        groups_data = [g[dv].dropna() for name, g in df.groupby(group_col) if not g[dv].dropna().empty]
        if len(groups_data) < 2: raise ValueError(_l("Kruskal-Wallis requires at least 2 groups."))
        stat, p_val = kruskal(*groups_data)
        res.update({'statistic': stat, 'p_value': p_val, 'groups_compared': len(groups_data)})
        
        if p_val <= 0.05:
            try:
                # Use Pingouin for robust non-parametric pairwise tests
                # padjust='holm' is generally better than bonf while still being safe
                dunn = pg.pairwise_tests(data=df, dv=dv, between=group_col, padjust='holm', parametric=False)
                
                control_group = extra_params.get('control_group') if extra_params else None
                if control_group and control_group in df[group_col].unique():
                    # Filter for comparisons vs control (A or B matches control)
                    dunn = dunn[(dunn['A'] == control_group) | (dunn['B'] == control_group)]
                    title = _l(f"Post-Hoc (Non-parametric vs Control: {control_group})")
                    res['notes'].append(_l("Non-parametric pairwise comparisons performed (Comparing vs Control)."))
                else:
                    title = _l("Post-Hoc (Non-parametric All-Pairs: Dunn equivalent)")
                    res['notes'].append(_l("Non-parametric pairwise comparisons performed (All-pairs)."))

                res['posthoc_data'] = {
                    'title': title,
                    'columns': dunn.columns.tolist(),
                    'rows': dunn.to_dict('records'),
                    'rationale': _l("Non-parametric pairwise tests (using Mann-Whitney U with Holm correction) were selected because the data distribution either violated normality or variance homogeneity assumptions.")
                }
            except Exception as e:
                res['notes'].append(f"Post-hoc failed: {e}")

    def _run_friedman(self, df, dv, groups, subject_id, res):
        df_wide = df.pivot(index=subject_id, columns='_WithinFactorLevel_', values='_MeasurementValue_').dropna()
        if df_wide.shape[1] < 3: raise ValueError(_l("Friedman requires at least 3 time points/conditions."))
        data_arrays = [df_wide[col] for col in df_wide.columns]
        stat, p_val = friedmanchisquare(*data_arrays)
        res.update({'statistic': stat, 'p_value': p_val, 'n_subjects': len(df_wide)})

    def _run_anova_oneway(self, df, dv, groups, subject_id, res, extra_params=None):
        group_col = self._get_single_group_col(df, groups)
        df_clean = df.copy()
        mapping = sanitize_df_columns_for_patsy(df_clean, [dv, group_col])
        safe_dv = mapping.get(dv, dv)
        safe_group = mapping.get(group_col, group_col)
        
        formula = f"{quote_name(safe_dv)} ~ C({quote_name(safe_group)})"
        model = smf.ols(formula, data=df_clean).fit()
        anova_tbl = sm.stats.anova_lm(model, typ=2)
        
        res['results_data'] = {
            'columns': ['Source', 'sum_sq', 'df', 'F', 'PR(>F)'],
            'rows': anova_tbl.reset_index().rename(columns={'index': 'Source'}).to_dict('records')
        }
        res['p_value'] = anova_tbl['PR(>F)'][0]
        res['statistic'] = anova_tbl['F'][0]
        
        if res['p_value'] <= 0.05:
            # Check for Dunnett's (Control Group)
            control_group = extra_params.get('control_group') if extra_params else None
            
            if control_group and control_group in df_clean[safe_group].values:
                try:
                    # Dunnett's Test using scipy.stats.dunnett (requires Scipy 1.11+)
                    if hasattr(stats, 'dunnett'):
                        # Important: scipy.stats.dunnett results correspond to samples in Order of appearance 
                        # or specific list. We must ensure mapping is correct.
                        unique_groups = [g for g in df_clean[safe_group].unique() if g != control_group]
                        samples = [df_clean[df_clean[safe_group] == g][safe_dv].values for g in unique_groups]
                        control_sample = df_clean[df_clean[safe_group] == control_group][safe_dv].values
                        
                        dunnett_res = stats.dunnett(*samples, control=control_sample)
                        
                        rows = []
                        for i, group in enumerate(unique_groups):
                            rows.append({
                                'Group A': control_group, 
                                'Group B': group, 
                                'Statistic': float(dunnett_res.statistic[i]), 
                                'p-value': float(dunnett_res.pvalue[i])
                            })
                            
                        res['posthoc_data'] = {
                            'title': _l(f"Post-Hoc (Dunnett's Test vs Control: {control_group})"),
                            'columns': ['Group A', 'Group B', 'Statistic', 'p-value'],
                            'rows': rows,
                            'rationale': _l("Dunnett's test was selected to maximize statistical power for comparing multiple treatments against a single control, while maintaining control over the family-wise error rate.")
                        }
                        res['notes'].append(_l("Dunnett's test applied (Comparing all groups against Control)."))
                    else:
                        # Fallback for older Scipy or error
                        m_comp = multi.pairwise_tukeyhsd(endog=df_clean[safe_dv], groups=df_clean[safe_group], alpha=0.05)
                        df_posthoc = pd.DataFrame(data=m_comp._results_table.data[1:], columns=m_comp._results_table.data[0])
                        res['posthoc_data'] = {
                            'title': _l('Post-Hoc (Tukey HSD)'),
                            'columns': df_posthoc.columns.tolist(),
                            'rows': df_posthoc.to_dict('records')
                        }
                except Exception as e:
                     res['notes'].append(f"Dunnett's failed: {e}")
            else:
                try:
                    # All-pairs comparison using Tukey HSD
                    m_comp = multi.pairwise_tukeyhsd(endog=df_clean[safe_dv], groups=df_clean[safe_group], alpha=0.05)
                    df_posthoc = pd.DataFrame(data=m_comp._results_table.data[1:], columns=m_comp._results_table.data[0])
                    res['posthoc_data'] = {
                        'title': _l('Post-Hoc (Tukey HSD)'),
                        'columns': df_posthoc.columns.tolist(),
                        'rows': df_posthoc.to_dict('records'),
                        'rationale': _l("Tukey HSD was selected for all-pairs comparison as it provides an optimal balance of power and error-rate control when no specific control group is prioritized.")
                    }
                    res['notes'].append(_l("Tukey HSD applied (All-pairs comparison)."))
                except Exception as e:
                    res['notes'].append(f"Tukey HSD failed: {e}")

    def _run_anova_twoway(self, df, dv, groups, subject_id, res, extra_params=None):
        if len(groups) != 2: raise ValueError("Two-Way ANOVA requires 2 factors.")
        df_clean = df.copy()
        sanitize_df_columns_for_patsy(df_clean, [dv] + groups)
        formula = f"{quote_name(dv)} ~ C({quote_name(groups[0])}) * C({quote_name(groups[1])})"
        
        model = smf.ols(formula, data=df_clean).fit()
        anova_tbl = sm.stats.anova_lm(model, typ=2)
        
        res['results_data'] = {
            'columns': ['Source', 'sum_sq', 'df', 'F', 'PR(>F)'],
            'rows': anova_tbl.reset_index().rename(columns={'index': 'Source'}).to_dict('records')
        }
        
        # Automated Post-Hoc Analysis
        try:
            interaction_term = f"C({quote_name(groups[0])}):C({quote_name(groups[1])})"
            p_interaction = anova_tbl.loc[interaction_term, 'PR(>F)'] if interaction_term in anova_tbl.index else 1.0
            
            p_main0 = anova_tbl.loc[f"C({quote_name(groups[0])})", 'PR(>F)'] if f"C({quote_name(groups[0])})" in anova_tbl.index else 1.0
            p_main1 = anova_tbl.loc[f"C({quote_name(groups[1])})", 'PR(>F)'] if f"C({quote_name(groups[1])})" in anova_tbl.index else 1.0

            control_group = extra_params.get('control_group') if extra_params else None

            if p_interaction <= 0.05:
                # Significant interaction -> Simple Effects Analysis
                # For independent Two-Way ANOVA, both factors are 'between', not 'within'
                ph = pg.pairwise_tests(data=df_clean, dv=dv, between=groups, padjust='holm')
                
                # If control group is across BOTH factors or specific, we might filter. 
                # But simple effects usually show the landscape.
                res['posthoc_data'] = {
                    'title': _l("Post-Hoc: Simple Effects (Group Interaction)"),
                    'columns': ph.columns.tolist(),
                    'rows': ph.to_dict('records'),
                    'rationale': _l("Simple Effects analysis was performed because a significant interaction was found. This avoids misleading results by testing comparisons separately at each level of the interacting factors.")
                }
                res['notes'].append(_l("Significant interaction found. Simple effects (pairwise comparisons within each factor level) performed."))
            elif p_main0 <= 0.05 or p_main1 <= 0.05:
                # Significant main effects (no interaction) -> Pairwise on main factors
                ph_list = []
                if p_main0 <= 0.05:
                    ph0 = pg.pairwise_tests(data=df_clean, dv=dv, between=groups[0], padjust='holm')
                    if control_group and control_group in df_clean[groups[0]].unique():
                        ph0 = ph0[(ph0['A'] == control_group) | (ph0['B'] == control_group)]
                    ph0['Factor'] = groups[0]
                    ph_list.append(ph0)
                if p_main1 <= 0.05:
                    ph1 = pg.pairwise_tests(data=df_clean, dv=dv, between=groups[1], padjust='holm')
                    if control_group and control_group in df_clean[groups[1]].unique():
                        ph1 = ph1[(ph1['A'] == control_group) | (ph1['B'] == control_group)]
                    ph1['Factor'] = groups[1]
                    ph_list.append(ph1)
                
                if ph_list:
                    ph_combined = pd.concat(ph_list)
                    res['posthoc_data'] = {
                        'title': _l("Post-Hoc: Pairwise Comparisons (Main Effects)"),
                        'columns': ph_combined.columns.tolist(),
                        'rows': ph_combined.to_dict('records'),
                        'rationale': _l("Pairwise comparisons were performed for significant main effects to identify specific group differences, using Holm correction for robust error control.")
                    }
                    if control_group:
                        res['notes'].append(_l("Significant main effects found. Pairwise comparisons performed (vs Control where applicable)."))
                    else:
                        res['notes'].append(_l("Significant main effects found. Pairwise comparisons performed."))
        except Exception as e:
            res['notes'].append(f"Automated post-hoc failed: {e}")
            current_app.logger.warning(f"Post-hoc failed for Two-Way ANOVA: {e}")

    def _run_anova_nway(self, df, dv, groups, subject_id, res, extra_params=None):
        if not groups: raise ValueError("N-Way ANOVA requires grouping factors.")
        df_clean = df.copy()
        sanitize_df_columns_for_patsy(df_clean, [dv] + groups)
        
        terms = [f"C({quote_name(g)})" for g in groups]
        formula = f"{quote_name(dv)} ~ {' * '.join(terms)}"
        
        try:
            model = smf.ols(formula, data=df_clean).fit()
            anova_tbl = sm.stats.anova_lm(model, typ=2)
            
            res['results_data'] = {
                'columns': ['Source', 'sum_sq', 'df', 'F', 'PR(>F)'],
                'rows': anova_tbl.reset_index().rename(columns={'index': 'Source'}).to_dict('records')
            }
            
            # --- Automated Post-Hoc for N-Way (Main Effects) ---
            try:
                control_group = extra_params.get('control_group') if extra_params else None
                ph_list = []
                for factor in groups:
                    term = f"C({quote_name(factor)})"
                    if term in anova_tbl.index:
                        p_val = anova_tbl.loc[term, 'PR(>F)']
                        if p_val <= 0.05:
                            ph = pg.pairwise_tests(data=df_clean, dv=dv, between=factor, padjust='holm')
                            if control_group and control_group in df_clean[factor].unique():
                                ph = ph[(ph['A'] == control_group) | (ph['B'] == control_group)]
                            ph['Factor'] = factor
                            ph_list.append(ph)
                
                if ph_list:
                    ph_combined = pd.concat(ph_list)
                    res['posthoc_data'] = {
                        'title': _l("Post-Hoc: Pairwise Comparisons (Main Effects)"),
                        'columns': ph_combined.columns.tolist(),
                        'rows': ph_combined.to_dict('records'),
                        'rationale': _l("Pairwise comparisons were performed for significant main effects to identify specific group differences, using Holm correction for robust error control.")
                    }
                    res['notes'].append(_l("Significant main effects found. Pairwise comparisons performed (vs Control where applicable)."))
            except Exception as ph_e:
                current_app.logger.warning(f"Post-hoc failed for N-Way ANOVA: {ph_e}")
        except Exception as e:
            msg = str(e)
            if "constraint matrix" in msg.lower() or "singular matrix" in msg.lower():
                res['error'] = _l("Statistical error: The design matrix is singular or has empty cells. Check for missing combinations of groups (e.g., a specific Genotype+Treatment combination has no data).")
            else:
                res['error'] = f"ANOVA failed: {msg}"

    def _run_manova(self, df, dv, groups, subject_id, res, extra_params=None):
        if not isinstance(dv, list) or len(dv) < 2:
            raise ValueError(_l("MANOVA requires at least 2 dependent variables."))
        
        from statsmodels.multivariate.manova import MANOVA
        
        df_clean = df.copy()
        sanitize_df_columns_for_patsy(df_clean, dv + groups)
        
        dv_formula = " + ".join([quote_name(d) for d in dv])
        group_formula = " + ".join([f"C({quote_name(g)})" for g in groups])
        formula = f"{dv_formula} ~ {group_formula}"
        
        ma = MANOVA.from_formula(formula, data=df_clean)
        mv_res = ma.mv_test()
        
        rows = []
        for factor, result_instance in mv_res.results.items():
            stat_table = result_instance['stat']
            for idx, row in stat_table.iterrows():
                r_dict = row.to_dict()
                r_dict['Source'] = factor
                r_dict['Test'] = idx
                rows.append(r_dict)
                
        res['results_data'] = {
            'columns': ['Source', 'Test', 'Value', 'Num DF', 'Den DF', 'F Value', 'Pr > F'],
            'rows': rows
        }

    def _run_ancova(self, df, dv, groups, subject_id, res, extra_params=None):
        """
        Robust ANCOVA with Homogeneity of Slopes Assumption Checking.
        
        Strategy:
        1. Test interaction model: dv ~ group * covariate
        2. If interaction p > 0.05: assumption met → run standard ANCOVA
        3. If interaction p ≤ 0.05: assumption violated → return interaction model
        """
        covar = extra_params.get('covariate') if extra_params else None
        if not covar:
            res['error'] = "Covariate not specified for ANCOVA."
            return
            
        if covar not in df.columns:
            res['error'] = f"Covariate '{covar}' not found in data."
            return
 
        group_col = self._get_single_group_col(df, groups)
        
        # Ensure covariate is numeric
        df_work = df.copy()
        df_work[covar] = pd.to_numeric(df_work[covar], errors='coerce')
        df_clean = df_work.dropna(subset=[dv, group_col, covar])
        
        if df_clean.empty:
            res['error'] = "No valid data after removing missing values."
            return

        try:
            # Step A: Run OLS interaction model to test homogeneity of slopes
            df_test = df_clean.copy()
            mapping = sanitize_df_columns_for_patsy(df_test, [dv, group_col, covar])
            safe_dv = mapping.get(dv, dv)
            safe_group = mapping.get(group_col, group_col)
            safe_covar = mapping.get(covar, covar)
            
            interaction_formula = f"{quote_name(safe_dv)} ~ C({quote_name(safe_group)}) * {quote_name(safe_covar)}"
            model_interaction = smf.ols(interaction_formula, data=df_test).fit()
            anova_interaction = sm.stats.anova_lm(model_interaction, typ=2)
            
            # Step B: Extract p-value for interaction term
            # The interaction term is labeled as "C(group):covariate" in the ANOVA table
            interaction_term = None
            for idx in anova_interaction.index:
                if ':' in str(idx):  # Interaction terms contain ':'
                    interaction_term = idx
                    break
            
            if interaction_term is None:
                # Fallback: couldn't find interaction term, proceed with standard ANCOVA
                res['notes'].append(_l("Warning: Could not detect interaction term. Proceeding with standard ANCOVA."))
                assumption_met = True
                p_interaction = None
            else:
                p_interaction = anova_interaction.loc[interaction_term, 'PR(>F)']
                assumption_met = p_interaction > 0.05
            
            # Step C or D: Choose appropriate analysis based on assumption
            if assumption_met:
                # Step C: Assumption met → Run standard ANCOVA
                try:
                    ancova = pg.ancova(data=df_clean, dv=dv, between=group_col, covar=covar)
                    res['results_data'] = {
                        'title': _l('ANCOVA Results'),
                        'columns': ancova.columns.tolist(),
                        'rows': ancova.to_dict('records')
                    }
                    # Extract main effect of Group
                    group_row = ancova[ancova['Source'] == group_col]
                    if not group_row.empty:
                        res['p_value'] = group_row['p-unc'].iloc[0]
                        res['statistic'] = group_row['F'].iloc[0]
                    
                    if p_interaction is not None:
                        res['notes'].append(
                            _l("Homogeneity of slopes assumption met (interaction p={p:.3f}). Standard ANCOVA applied.").format(p=p_interaction)
                        )
                except Exception as e:
                    # If Pingouin ANCOVA fails, fall back to interaction model
                    res['notes'].append(_l("Standard ANCOVA failed, using interaction model: {e}").format(e=str(e)))
                    assumption_met = False
            
            if not assumption_met:
                # Step D: Assumption violated → Return OLS interaction model
                res['test'] = _l('Linear Regression with Interaction')
                res['results_data'] = {
                    'title': _l('Linear Regression with Interaction (Non-parallel slopes)'),
                    'columns': ['Source', 'sum_sq', 'df', 'F', 'PR(>F)'],
                    'rows': anova_interaction.reset_index().rename(columns={'index': 'Source'}).to_dict('records')
                }
                
                # Extract interaction effect as the primary result
                if interaction_term:
                    res['p_value'] = p_interaction
                    res['statistic'] = anova_interaction.loc[interaction_term, 'F']
                
                if p_interaction is not None:
                    res['notes'].append(
                        _l("Assumption of homogeneity of regression slopes violated (interaction p={p:.3f}). "
                           "The effect of the covariate differs by group. Reporting Linear Regression with "
                           "Interaction to model these differences.").format(p=p_interaction)
                    )
                else:
                    res['notes'].append(
                        _l("Assumption of homogeneity of regression slopes violated. "
                           "Reporting Linear Regression with Interaction to model group-specific covariate effects.")
                    )
                
        except Exception as e:
            res['error'] = f"ANCOVA analysis failed: {e}"
            current_app.logger.error(f"ANCOVA error: {e}", exc_info=True)

    def _run_ttest_paired(self, df, dv, groups, subject_id, res, extra_params=None):
        df_wide = df.pivot(index=subject_id, columns='_WithinFactorLevel_', values='_MeasurementValue_').dropna()
        if df_wide.shape[1] != 2: raise ValueError(_l("Paired T-test requires exactly 2 time points/conditions."))
        cols = df_wide.columns
        t_stat, p_val = ttest_rel(df_wide[cols[0]], df_wide[cols[1]])
        res.update({'statistic': t_stat, 'p_value': p_val, 'n_pairs': len(df_wide)})

    def _run_anova_rm_oneway(self, df, dv, groups, subject_id, res, extra_params=None):
        """
        One-Way Repeated Measures ANOVA with automatic LMM fallback for missing data.
        """
        # 1. Check for Missing Data (NaNs) in the repeated measures
        has_missing = df['_MeasurementValue_'].isna().any()
        
        if has_missing:
            # Automatically switch to LMM for robustness
            res['notes'].append(_l("Missing values detected. Switching to Linear Mixed Model (LMM) for robustness."))
            try:
                # LMM Implementation using Pingouin
                # Formula: _MeasurementValue_ ~ _WithinFactorLevel_
                # Random effects: subject (random intercepts)
                lmm = pg.mixed_linear_model(
                    data=df, 
                    dv='_MeasurementValue_', 
                    subject=subject_id, 
                    formula="_MeasurementValue_ ~ C(_WithinFactorLevel_)"
                )
                
                res['test'] = _l('Linear Mixed Model (Repeated Measures)')
                res['results_data'] = {
                    'title': _l('Linear Mixed Model Results (Robust to Missing Data)'),
                    'columns': lmm.columns.tolist(),
                    'rows': lmm.to_dict('records')
                }
                
                # Extract p-value for the within-factor effect
                # LMM table has multiple rows for different effects
                within_effect = lmm[lmm['Term'].str.contains('_WithinFactorLevel_', na=False)]
                if not within_effect.empty and 'pval' in within_effect.columns:
                    res['p_value'] = within_effect['pval'].iloc[0]
                
                return  # Exit early as LMM structure differs
                
            except Exception as e:
                res['notes'].append(_l("LMM failed ({e}). Attempting standard RM ANOVA with list-wise deletion.").format(e=str(e)))
                # Continue to standard RM ANOVA below
              
        # 2. Standard RM ANOVA (no missing data or LMM failed)
        # Check Sphericity
        try:
            spher, _, chisq, dof, p_spher = pg.sphericity(df, dv='_MeasurementValue_', subject=subject_id, within='_WithinFactorLevel_')
            if not spher:
                 res['notes'].append(_l("Sphericity assumption violated (p={p:.3f}). Applying Greenhouse-Geisser correction.").format(p=p_spher))
        except Exception:
            pass # Sphericity test can fail if insufficient data/variance

        aov = pg.rm_anova(data=df, dv='_MeasurementValue_', within='_WithinFactorLevel_', subject=subject_id, correction='auto')
        
        res['results_data'] = {
            'columns': aov.columns.tolist(),
            'rows': aov.to_dict('records')
        }
        if not aov.empty:
            # Pingouin puts 'p-GG-corr' or 'p-unc' depending on correction
            p_col = 'p-GG-corr' if 'p-GG-corr' in aov.columns else 'p-unc'
            res['p_value'] = aov[p_col].iloc[0]
            res['statistic'] = aov['F'].iloc[0]
            
            if res['p_value'] <= 0.05:
                try:
                    ph = pg.pairwise_tests(data=df, dv='_MeasurementValue_', within='_WithinFactorLevel_', subject=subject_id, padjust='bonf')
                    res['posthoc_data'] = {
                        'title': _l("Post-Hoc (Pairwise T-tests, Bonferroni)"),
                        'columns': ph.columns.tolist(),
                        'rows': ph.to_dict('records')
                    }
                except Exception as e:
                    res['notes'].append(f"Post-hoc failed: {e}")

    def _run_pingouin_mixed_anova(self, df, dv, groups, subject_id, res, extra_params=None):
        if not groups:
            raise ValueError(_l("Mixed ANOVA requires at least one between-subject grouping factor."))
        
        group_col = self._get_single_group_col(df, groups)
        
        # 1. Missing Data Logic
        if df['_MeasurementValue_'].isna().any():
            res['notes'].append(_l("Missing values detected. Switching to Linear Mixed Model (LMM) engine for robustness."))
            try:
                # LMM Implementation using formula
                # formula: _MeasurementValue_ ~ _WithinFactorLevel_ * group_col
                # re_formula: ~ 1 | subject_id (random intercepts)
                lmm = pg.mixed_linear_model(
                    data=df, 
                    dv='_MeasurementValue_', 
                    subject=subject_id, 
                    formula=f"_MeasurementValue_ ~ C(_WithinFactorLevel_) * C({quote_name(group_col)})"
                )
                 # LMM returns fixed effects table
                res['results_data'] = {
                    'title': _l('Linear Mixed Model Test Results (Robust to Missing Data)'),
                    'columns': lmm.columns.tolist(),
                    'rows': lmm.to_dict('records')
                }
                # P-value extraction is tricky from LMM table as there are multiple effects.
                # Usually we return the table and let user see.
                return # Exit early as structure differs for LMM
            except Exception as e:
                res['notes'].append(f"LMM failed ({str(e)}). Falling back to standard Mixed ANOVA (list-wise deletion).")

        # 2. Sphericity Logic
        try:
             spher, _, _, _, p_spher = pg.sphericity(data=df, dv='_MeasurementValue_', subject=subject_id, within='_WithinFactorLevel_')
             if not spher:
                  res['notes'].append(_l("Sphericity violated (p={p:.3f}). GG correction applied.").format(p=p_spher))
        except:
             pass

        aov = pg.mixed_anova(
            data=df, 
            dv='_MeasurementValue_', 
            within='_WithinFactorLevel_', 
            subject=subject_id, 
            between=group_col,
            correction='auto'
        )
        
        res['results_data'] = {
            'columns': aov.columns.tolist(),
            'rows': aov.to_dict('records')
        }
        
        interaction_row = aov[aov['Source'] == 'Interaction']
        significant = False
        if not interaction_row.empty:
            p_col = 'p-GG-corr' if 'p-GG-corr' in interaction_row else 'p-unc'
            p_int = interaction_row[p_col].iloc[0]
            res['p_value'] = p_int
            res['statistic'] = interaction_row['F'].iloc[0]
            res['notes'].append(_l("P-value shown is for the Interaction effect."))
            if p_int <= 0.05: significant = True
        
        if significant:
             try:
                ph = pg.pairwise_tests(data=df, dv='_MeasurementValue_', within='_WithinFactorLevel_', between=group_col, subject=subject_id, padjust='bonf')
                res['posthoc_data'] = {
                    'title': _l("Post-Hoc (Pairwise Tests, Bonferroni)"),
                    'columns': ph.columns.tolist(),
                    'rows': ph.to_dict('records'),
                    'rationale': _l("For this Mixed-ANOVA, pairwise comparisons were performed to decompose the observed interaction between 'Between' and 'Within' factors.")
                }
             except Exception as e:
                 res['notes'].append(f"Post-hoc failed: {e}")

    def _get_single_group_col(self, df, groups):
        if not groups: raise ValueError("Grouping required.")
        if len(groups) == 1: return groups[0]
        col_name = '_combined_group_svc'
        if col_name not in df.columns:
            df[col_name] = df[groups].astype(str).agg('_'.join, axis=1)
        return col_name

    def _get_test_name(self, key):
        map = {
            'ttest_ind_equal_var': _l('Independent T-test (Equal Var)'),
            'ttest_ind_unequal_var': _l("Welch's T-test"),
            'mannwhitneyu': _l('Mann-Whitney U'),
            'anova_oneway': _l('One-Way ANOVA'),
            'ttest_paired': _l('Paired T-test'),
            'anova_rm_oneway': _l('One-Way RM ANOVA'),
            'pingouin_mixed_anova': _l('Mixed ANOVA'),
            'anova_rm_mixed_sm': _l('Mixed ANOVA'),
            'anova_nway': _l('N-Way ANOVA'),
            'manova': _l('MANOVA'),
            'ancova': _l('ANCOVA'),
            'logrank': _l('Log-Rank Test'),
            'dunnett': _l("Dunnett's Test"),
            'correlation': _l("Correlation Matrix")
        }
        return map.get(key, key.replace('_', ' ').title())

    def _run_correlation_matrix(self, df, dv, groups, subject_id, res, extra_params=None):
        """
        Calculates a correlation matrix for all numerical columns.
        Ignores 'dv' and 'groups' inputs as this is a global test.
        """
        # We need all numerical columns. We can infer them from the DF or assume passed in extra_params?
        # Better: Filter DF for all numeric columns.
        df_numeric = df.select_dtypes(include=['number'])
        
        # Exclude IDs if possible (heuristic)
        cols_to_drop = [c for c in df_numeric.columns if 'id' in c.lower() or 'index' in c.lower()]
        df_numeric = df_numeric.drop(columns=cols_to_drop, errors='ignore')

        if df_numeric.shape[1] < 2:
            res['error'] = _l("Need at least 2 numerical columns for correlation matrix.")
            return

        corr = df_numeric.corr(method='pearson').round(3)
        
        # Calculate p-values
        p_values = df_numeric.corr(method=lambda x, y: stats.pearsonr(x, y)[1]) - 1.0 # Self corr is 1, p is 0. adjustment needed?
        # Actually panda's corr doesn't give p-values easily. Pingouin does.
        try:
            rcorr = pg.rcorr(df_numeric, method='pearson', stars=False)
            # rcorr gives a formatted table.
            res['results_data'] = {
                'title': _l('Correlation Matrix (Pearson)'),
                'columns': rcorr.columns.tolist(),
                'rows': rcorr.to_dict('records')
            }
        except Exception:
             # Fallback to simple pandas corr
             res['results_data'] = {
                'title': _l('Correlation Matrix (Pearson) - Coefficients'),
                'columns': ['Parameter'] + corr.columns.tolist(),
                'rows': corr.reset_index().rename(columns={'index': 'Parameter'}).to_dict('records')
            }

    def _run_chi_square(self, df, dv, groups, subject_id, res, extra_params=None):
        """
        Chi-Square Test of Independence for categorical variables.
        Automatically switches to Fisher's Exact Test if expected frequencies < 5.
        """
        if not groups or len(groups) == 0:
            res['error'] = "Chi-Square requires at least one grouping variable."
            return
        
        # Create grouping column (combine multiple grouping variables if needed)
        if len(groups) == 1:
            group_col = groups[0]
        else:
            # Combine multiple grouping columns
            df['_CombinedGroup_'] = df[groups].astype(str).agg(' / '.join, axis=1)
            group_col = '_CombinedGroup_'
        
        # Remove missing values
        df_clean = df[[dv, group_col]].dropna()
        
        if df_clean.empty:
            res['error'] = "No valid data after removing missing values."
            return
        
        try:
            # Create contingency table
            contingency_table = pd.crosstab(df_clean[group_col], df_clean[dv])
            
            # Check if we have enough data
            if contingency_table.size == 0:
                res['error'] = "Contingency table is empty."
                return
            
            # Perform Chi-Square test
            chi2, p_value, dof, expected_freq = stats.chi2_contingency(contingency_table)
            
            # Check if expected frequencies are too low (< 5)
            min_expected = expected_freq.min()
            use_fisher = min_expected < 5
            
            if use_fisher and contingency_table.shape == (2, 2):
                # Use Fisher's Exact Test for 2x2 tables with low expected frequencies
                oddsratio, p_value_fisher = stats.fisher_exact(contingency_table)
                
                res['test'] = _l("Fisher's Exact Test")
                res['p_value'] = p_value_fisher
                res['statistic'] = oddsratio
                res['notes'].append(
                    _l("Fisher's Exact Test used because expected frequencies were below 5 (min={min:.2f}).").format(min=min_expected)
                )
                
                # Display contingency table
                res['results_data'] = {
                    'title': _l('Contingency Table'),
                    'columns': ['Group'] + list(contingency_table.columns),
                    'rows': contingency_table.reset_index().to_dict('records')
                }
                
                # Add test results
                res['test_results'] = {
                    'title': _l("Fisher's Exact Test Results"),
                    'columns': ['Statistic', 'Value'],
                    'rows': [
                        {'Statistic': 'Odds Ratio', 'Value': f'{oddsratio:.4f}'},
                        {'Statistic': 'p-value', 'Value': f'{p_value_fisher:.4f}'}
                    ]
                }
            else:
                # Use Chi-Square
                res['test'] = _l('Chi-Square Test of Independence')
                res['p_value'] = p_value
                res['statistic'] = chi2
                
                if min_expected < 5:
                    res['notes'].append(
                        _l("Warning: Some expected frequencies are below 5 (min={min:.2f}). Results may be unreliable. "
                           "Consider Fisher's Exact Test for 2x2 tables or combining categories.").format(min=min_expected)
                    )
                
                # Display contingency table
                res['results_data'] = {
                    'title': _l('Contingency Table'),
                    'columns': ['Group'] + list(contingency_table.columns),
                    'rows': contingency_table.reset_index().to_dict('records')
                }
                
                # Add test results
                res['test_results'] = {
                    'title': _l('Chi-Square Test Results'),
                    'columns': ['Statistic', 'Value'],
                    'rows': [
                        {'Statistic': 'Chi-Square', 'Value': f'{chi2:.4f}'},
                        {'Statistic': 'Degrees of Freedom', 'Value': str(dof)},
                        {'Statistic': 'p-value', 'Value': f'{p_value:.4f}'}
                    ]
                }
                
                # Add expected frequencies table
                expected_df = pd.DataFrame(
                    expected_freq,
                    index=contingency_table.index,
                    columns=contingency_table.columns
                )
                res['expected_frequencies'] = {
                    'title': _l('Expected Frequencies'),
                    'columns': ['Group'] + list(expected_df.columns),
                    'rows': expected_df.reset_index().to_dict('records')
                }
                
        except Exception as e:
            res['error'] = f"Chi-Square test failed: {e}"
            current_app.logger.error(f"Chi-Square error: {e}", exc_info=True)

    def _handle_special_keys(self, key, res):
        if key == 'error': res['error'] = _l("Data check error.")
        elif key == 'summary_only': res['test'] = _l('Summary Only')
        return res
