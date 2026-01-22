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
            df_test, outliers_count = self._prepare_data_for_test(
                df, test_key, dv_col, grouping_cols, is_repeated, subject_id_col, exclude_outliers
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

    def _prepare_data_for_test(self, df, test_key, dv_col, grouping_cols, is_repeated, subject_id_col, exclude_outliers):
        df_test = df.copy()
        cols_to_numeric = []
        
        if test_key == 'manova': 
            cols_to_numeric = dv_col if isinstance(dv_col, list) else [dv_col]
        elif test_key == 'correlation':
            cols_to_numeric = [] # Correlation handles its own numeric selection/cleaning logic
        elif is_repeated: 
            cols_to_numeric = ['_MeasurementValue_']
        else: 
            cols_to_numeric = [dv_col]

        for col in cols_to_numeric:
            if col in df_test.columns:
                df_test[col] = pd.to_numeric(df_test[col], errors='coerce')
        
        outliers_count = 0
        if exclude_outliers:
            if is_repeated and '_MeasurementValue_' in df_test.columns:
                mask = detect_outliers(df_test['_MeasurementValue_'])
                outliers_count = int(mask.sum())
                df_test = df_test[~mask]
            elif test_key != 'manova' and dv_col in df_test.columns:
                mask = detect_outliers(df_test[dv_col])
                outliers_count = int(mask.sum())
                df_test = df_test[~mask]

        if test_key != 'manova':
            # Ensure grouping columns are present
            valid_grouping = [g for g in (grouping_cols or []) if g in df_test.columns]
            df_test = df_test.dropna(subset=cols_to_numeric + valid_grouping)
        
        return df_test, outliers_count

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

    def _run_kruskalwallis(self, df, dv, groups, subject_id, res):
        group_col = self._get_single_group_col(df, groups)
        groups_data = [g[dv].dropna() for name, g in df.groupby(group_col) if not g[dv].dropna().empty]
        if len(groups_data) < 2: raise ValueError(_l("Kruskal-Wallis requires at least 2 groups."))
        stat, p_val = kruskal(*groups_data)
        res.update({'statistic': stat, 'p_value': p_val, 'groups_compared': len(groups_data)})
        
        if p_val <= 0.05:
            try:
                dunn = pg.pairwise_tests(data=df, dv=dv, between=group_col, padjust='bonf', parametric=False)
                res['posthoc_data'] = {
                    'title': _l("Post-Hoc (Dunn's Test)"),
                    'columns': dunn.columns.tolist(),
                    'rows': dunn.to_dict('records')
                }
            except Exception as e:
                res['notes'].append(f"Post-hoc failed: {e}")

    def _run_friedman(self, df, dv, groups, subject_id, res):
        df_wide = df.pivot(index=subject_id, columns='_WithinFactorLevel_', values='_MeasurementValue_').dropna()
        if df_wide.shape[1] < 3: raise ValueError(_l("Friedman requires at least 3 time points/conditions."))
        data_arrays = [df_wide[col] for col in df_wide.columns]
        stat, p_val = friedmanchisquare(*data_arrays)
        res.update({'statistic': stat, 'p_value': p_val, 'n_subjects': len(df_wide)})

    def _run_anova_oneway(self, df, dv, groups, subject_id, res):
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
            try:
                m_comp = multi.pairwise_tukeyhsd(endog=df_clean[safe_dv], groups=df_clean[safe_group], alpha=0.05)
                df_posthoc = pd.DataFrame(data=m_comp._results_table.data[1:], columns=m_comp._results_table.data[0])
                res['posthoc_data'] = {
                    'title': _l('Post-Hoc (Tukey HSD)'),
                    'columns': df_posthoc.columns.tolist(),
                    'rows': df_posthoc.to_dict('records')
                }
            except Exception as e:
                res['notes'].append(f"Tukey HSD failed: {e}")

    def _run_anova_twoway(self, df, dv, groups, subject_id, res):
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
        
        if any(anova_tbl['PR(>F)'].dropna() <= 0.05):
             res['notes'].append(_l('Significant effects found. Post-hoc analysis recommended.'))

    def _run_anova_nway(self, df, dv, groups, subject_id, res):
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
        except Exception as e:
            msg = str(e)
            if "constraint matrix" in msg.lower() or "singular matrix" in msg.lower():
                res['error'] = _l("Statistical error: The design matrix is singular or has empty cells. Check for missing combinations of groups (e.g., a specific Genotype+Treatment combination has no data).")
            else:
                res['error'] = f"ANOVA failed: {msg}"

    def _run_manova(self, df, dv, groups, subject_id, res):
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
        covar = extra_params.get('covariate') if extra_params else None
        if not covar:
            res['error'] = "Covariate not specified for ANCOVA."
            return
            
        if covar not in df.columns:
            res['error'] = f"Covariate '{covar}' not found in data."
            return

        group_col = self._get_single_group_col(df, groups)
        
        # Ensure covariate is numeric
        df[covar] = pd.to_numeric(df[covar], errors='coerce')
        df_clean = df.dropna(subset=[dv, group_col, covar])

        try:
            ancova = pg.ancova(data=df_clean, dv=dv, between=group_col, covar=covar)
            res['results_data'] = {
                'columns': ancova.columns.tolist(),
                'rows': ancova.to_dict('records')
            }
            # Extract main effect of Group
            group_row = ancova[ancova['Source'] == group_col]
            if not group_row.empty:
                res['p_value'] = group_row['p-unc'].iloc[0]
                res['statistic'] = group_row['F'].iloc[0]
        except Exception as e:
            res['error'] = f"ANCOVA failed: {e}"

    def _run_ttest_paired(self, df, dv, groups, subject_id, res):
        df_wide = df.pivot(index=subject_id, columns='_WithinFactorLevel_', values='_MeasurementValue_').dropna()
        if df_wide.shape[1] != 2: raise ValueError(_l("Paired T-test requires exactly 2 time points/conditions."))
        cols = df_wide.columns
        t_stat, p_val = ttest_rel(df_wide[cols[0]], df_wide[cols[1]])
        res.update({'statistic': t_stat, 'p_value': p_val, 'n_pairs': len(df_wide)})

    def _run_anova_rm_oneway(self, df, dv, groups, subject_id, res):
        aov = pg.rm_anova(data=df, dv='_MeasurementValue_', within='_WithinFactorLevel_', subject=subject_id, correction='auto')
        
        res['results_data'] = {
            'columns': aov.columns.tolist(),
            'rows': aov.to_dict('records')
        }
        if not aov.empty:
            res['p_value'] = aov['p-unc'].iloc[0]
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

    def _run_pingouin_mixed_anova(self, df, dv, groups, subject_id, res):
        if not groups:
            raise ValueError(_l("Mixed ANOVA requires at least one between-subject grouping factor."))
        
        group_col = self._get_single_group_col(df, groups)
        
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
        
        # Check for significant effects (Interaction or Main Effects)
        # We usually prioritize Interaction. If Interaction is significant, we look at simple main effects.
        # If not, we look at main effects.
        # Simplification: Run pairwise tests if any p < 0.05 in the table?
        # Or specifically check Interaction.
        
        interaction_row = aov[aov['Source'] == 'Interaction']
        significant = False
        if not interaction_row.empty:
            p_int = interaction_row['p-unc'].iloc[0]
            res['p_value'] = p_int
            res['statistic'] = interaction_row['F'].iloc[0]
            res['notes'].append(_l("P-value shown is for the Interaction effect."))
            if p_int <= 0.05: significant = True
        
        # Also check main effects if interaction is not significant? 
        # For now, let's trigger post-hoc if *any* effect is significant or just Interaction?
        # A common approach in automated tools is to run the pairwise breakdown if interaction is significant.
        
        if significant:
             try:
                # Pairwise tests for mixed design
                # This returns tests for within-factor at each level of between-factor, AND between-factor at each level of within-factor (if interaction=True? No, pingouin pairwise_tests handles this).
                ph = pg.pairwise_tests(data=df, dv='_MeasurementValue_', within='_WithinFactorLevel_', between=group_col, subject=subject_id, padjust='bonf')
                res['posthoc_data'] = {
                    'title': _l("Post-Hoc (Pairwise Tests, Bonferroni)"),
                    'columns': ph.columns.tolist(),
                    'rows': ph.to_dict('records')
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

    def _handle_special_keys(self, key, res):
        if key == 'error': res['error'] = _l("Data check error.")
        elif key == 'summary_only': res['test'] = _l('Summary Only')
        return res
