# app/datatables/analysis_utils.py
import keyword
import re
import pandas as pd
from flask import current_app
from flask_babel import lazy_gettext

def sanitize_df_columns_for_patsy(df, columns_to_sanitize):
    renamed_cols = {}
    sanitized_mapping = {}
    for col_name in columns_to_sanitize:
        if col_name not in df.columns:
            continue

        name_safe_for_formula = col_name.replace(' ', '_')
        is_valid_identifier = re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name_safe_for_formula) is not None
        is_keyword = keyword.iskeyword(name_safe_for_formula)

        if is_valid_identifier and not is_keyword:
            if col_name != name_safe_for_formula:
                renamed_cols[col_name] = name_safe_for_formula
            sanitized_mapping[col_name] = name_safe_for_formula
        else:
            sanitized_mapping[col_name] = col_name

    if renamed_cols:
        df.rename(columns=renamed_cols, inplace=True)
    return sanitized_mapping

def quote_name(name):
    name_safe = name.replace(' ', '_')
    is_valid_identifier = re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name_safe) is not None
    is_keyword = keyword.iskeyword(name_safe)

    if not is_valid_identifier or is_keyword:
         escaped_name = name.replace("'", "\\'")
         return f"Q('{escaped_name}')"
    else:
         return name_safe

def detect_outliers(series, method='iqr', threshold=1.5):
    """
    Detect outliers using IQR, standard deviation, or Grubbs' method.
    Returns: (mask, metadata_dict)
    """
    if series.empty or series.nunique() < 2:
        return pd.Series([False] * len(series), index=series.index), {}

    metadata = {'method': method, 'threshold': threshold}

    if method == 'iqr':
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            return pd.Series([False] * len(series), index=series.index), {}
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
        metadata['bounds'] = (float(lower), float(upper))
        return (series < lower) | (series > upper), metadata

    elif method == 'std':
        mean = series.mean()
        std = series.std()
        if std == 0 or pd.isna(std):
            return pd.Series([False] * len(series), index=series.index), {}
        lower = mean - threshold * std
        upper = mean + threshold * std
        metadata['bounds'] = (float(lower), float(upper))
        return (series < lower) | (series > upper), metadata

    elif method == 'grubbs':
        # Grubbs' test for a single outlier
        n = len(series)
        if n < 3:
            return pd.Series([False] * len(series), index=series.index), {}
        
        import numpy as np
        from scipy import stats
        
        mean = series.mean()
        std = series.std()
        if std == 0 or pd.isna(std):
            return pd.Series([False] * len(series), index=series.index), {}
            
        z_scores = abs(series - mean) / std
        max_idx = z_scores.idxmax()
        g_val = z_scores.max()
        
        # alpha default for Grubbs is 0.05
        # If threshold is small (e.g. 0.01-0.1), use it as alpha, else 0.05
        alpha = threshold if (0 < threshold < 0.5) else 0.05
        
        try:
            t_dist = stats.t.ppf(1 - alpha / (2 * n), n - 2)
            g_crit = ((n - 1) / np.sqrt(n)) * np.sqrt(t_dist**2 / (n - 2 + t_dist**2))
            
            mask = pd.Series(False, index=series.index)
            metadata['g_val'] = float(g_val)
            metadata['g_crit'] = float(g_crit)
            metadata['alpha'] = alpha
            
            if g_val > g_crit:
                mask.loc[max_idx] = True
            return mask, metadata
        except Exception:
            return pd.Series([False] * len(series), index=series.index), {}

    else:
        current_app.logger.warning(f"Unknown outlier detection method '{method}', defaulting to IQR.")
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            return pd.Series([False] * len(series), index=series.index), {}
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
        metadata['bounds'] = (float(lower), float(upper))
        return (series < lower) | (series > upper), metadata

def identify_outliers_and_calc_stats(df_group, numerical_cols):
    """Calculates basic stats and identifies outliers for a dataframe group."""
    group_stats = {}
    df_outlier_flags = pd.DataFrame(False, index=df_group.index, columns=numerical_cols)
    outlier_metadata = {}
    
    for col in numerical_cols:
        if col in df_group.columns and pd.api.types.is_numeric_dtype(df_group[col]):
            series = df_group[col].dropna()
            if not series.empty:
                mean = series.mean()
                sd = series.std() if len(series) > 1 else 0
                sem = series.sem() if len(series) > 1 else 0
                count = len(series)

                is_outlier_for_col_series, meta = detect_outliers(series, method='iqr', threshold=1.5)
                outlier_metadata[col] = meta
                
                aligned_outlier_mask = pd.Series(False, index=df_group.index)
                valid_indices = is_outlier_for_col_series.index.intersection(aligned_outlier_mask.index)
                aligned_outlier_mask.loc[valid_indices] = is_outlier_for_col_series.loc[valid_indices]                
                df_outlier_flags[col] = aligned_outlier_mask

                q1 = series.quantile(0.25)
                q3 = series.quantile(0.75)
                iqr_val = q3 - q1
                lower_bound_iqr = q1 - 1.5 * iqr_val if pd.notnull(iqr_val) and iqr_val != 0 else None
                upper_bound_iqr = q3 + 1.5 * iqr_val if pd.notnull(iqr_val) and iqr_val != 0 else None

                group_stats[col] = {
                    'mean': mean, 'sd': sd, 'sem': sem, 'count': count, 
                    'lower_bound_iqr': lower_bound_iqr, 'upper_bound_iqr': upper_bound_iqr,
                    'outlier_meta': meta
                }
            else:
                group_stats[col] = {'mean': None, 'sd': None, 'sem': None, 'count': 0}
        else:
            group_stats[col] = {'mean': None, 'sd': None, 'sem': None, 'count': 0}
            
    return df_outlier_flags, group_stats

def get_age_range_from_df_view_helper(df_group_local):
    """Helper to format age range string."""
    age_range_str_local = lazy_gettext('N/A') 
    if 'age_days' in df_group_local.columns and not df_group_local['age_days'].isnull().all():
        min_age = df_group_local['age_days'].min()
        max_age = df_group_local['age_days'].max()
        if pd.notnull(min_age) and pd.notnull(max_age):
            if min_age == max_age:
                age_range_str_local = f"{int(min_age)}d"
            else:
                age_range_str_local = f"{int(min_age)}-{int(max_age)}d"
    return age_range_str_local