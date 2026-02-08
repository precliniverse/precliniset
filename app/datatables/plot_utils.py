# app/datatables/plot_utils.py
import json  # Import json for fig.to_json()

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from flask import current_app
from flask_babel import gettext as _  # Use gettext for immediate translation


# --- Helper function for custom column ordering (used by generate_plot) ---
# If this is used elsewhere (e.g. core_models), consider moving to app/helpers.py
def get_custom_ordered_columns(animal_keys, protocol_keys):
    """Orders columns: ID first, then other animal keys (sorted), then protocol keys (sorted)."""
    animal_keys_set = set(animal_keys)
    protocol_keys_set = set(protocol_keys)

    # Ensure uid is treated as an animal key if it exists anywhere
    has_id = 'uid' in animal_keys_set or 'uid' in protocol_keys_set
    if has_id:
        animal_keys_set.add('uid')
        protocol_keys_set.discard('uid') # Remove from protocol if it was there

    # Separate animal keys (excluding uid) and sort them
    other_animal_keys = sorted(list(animal_keys_set - {'uid'}))

    # Sort protocol keys
    # MODIFIED: Respect provided order in protocol_keys if available, otherwise sort
    if isinstance(protocol_keys, list):
         # Deduplicate while preserving order of 'protocol_keys'
         seen_p = set()
         sorted_protocol_keys = [x for x in protocol_keys if x in protocol_keys_set and not (x in seen_p or seen_p.add(x))]
    else:
         sorted_protocol_keys = sorted(list(protocol_keys_set))

    # Combine in the desired order
    final_order = []
    if has_id:
        final_order.append('uid')
    final_order.extend(other_animal_keys)
    final_order.extend(sorted_protocol_keys)

    # Ensure all original keys are included, even if not explicitly categorized
    all_original_keys = set(animal_keys) | set(protocol_keys)
    missing_keys = sorted(list(all_original_keys - set(final_order)))
    final_order.extend(missing_keys) # Append any missed keys at the end

    # Remove duplicates while preserving order
    seen = set()
    final_order_unique = [x for x in final_order if not (x in seen or seen.add(x))]

    return final_order_unique


def generate_plot(df, numerical_param_or_dv, grouping_params, graph_type, start_y_at_zero, is_repeated, subject_id_col='uid', numerical_params_selected=None, exclude_outliers=False, reference_range_summary=None, stats_results=None, outlier_method='iqr', outlier_threshold=1.5):
    """
    Generates Plotly figure data (JSON). Handles both independent and RM plots.
    """
    notes = []
    fig = None
    df_plot = df.copy()

    current_app.logger.debug(f"generate_plot: numerical_param_or_dv={numerical_param_or_dv}, grouping_params={grouping_params}, graph_type={graph_type}, is_repeated={is_repeated}")
    current_app.logger.debug(f"generate_plot: df.head()=\n{df.head().to_string()}")
    
    if exclude_outliers:
        param_to_check_for_outliers = '_MeasurementValue_' if is_repeated else numerical_param_or_dv
        if param_to_check_for_outliers in df_plot.columns and pd.api.types.is_numeric_dtype(df_plot[param_to_check_for_outliers]):
            try:
                from .analysis_utils import detect_outliers
                outliers_mask, _ = detect_outliers(df_plot[param_to_check_for_outliers], method=outlier_method, threshold=outlier_threshold)
                n_outliers_plot = outliers_mask.sum()
                if n_outliers_plot > 0:
                    excluded_param_name_for_message = ""
                    if is_repeated:
                        if numerical_params_selected and len(numerical_params_selected) > 0:
                            excluded_param_name_for_message = _("the repeated measures set ({params})").format(params=", ".join(numerical_params_selected))
                        else:
                            excluded_param_name_for_message = _("the repeated measures data")
                    else:
                        excluded_param_name_for_message = f"'{numerical_param_or_dv}'"
                    notes.append(
                        _("{n} outlier(s) were excluded from the data for plot generation of '{param}'.").format(
                            n=n_outliers_plot, param=param_to_check_for_outliers # Corrected param name here
                        )
                    )
                    df_plot = df_plot[~outliers_mask].copy()
            except ImportError:
                notes.append(_("Warning: Outlier detection utility not found for plotting."))
            except Exception as e_outlier_plot:
                notes.append(_("Warning: Error during outlier detection for plotting: {e}").format(e=str(e_outlier_plot)))
                current_app.logger.warning(f"Error detecting outliers for plot: {e_outlier_plot}")

    try:
        if is_repeated:
            if '_MeasurementValue_' not in df_plot.columns or '_WithinFactorLevel_' not in df_plot.columns:
                 raise ValueError(_("RM plotting requires data in long format with '_MeasurementValue_' and '_WithinFactorLevel_' columns."))
            df_plot['_MeasurementValue_'] = pd.to_numeric(df_plot['_MeasurementValue_'], errors='coerce')
            df_plot = df_plot.dropna(subset=['_MeasurementValue_']).copy()
            if df_plot.empty:
                 notes.append(_("No valid data available for plotting Repeated Measures after handling missing values."))
                 return None, notes

            plot_args_rm = {'data_frame': df_plot, 'x': '_WithinFactorLevel_', 'y': '_MeasurementValue_'}
            
            # --- MODIFICATION: Enforce categorical order for _WithinFactorLevel_ ---
            # This prevents lines connecting in the wrong order (zig-zag) if 'Day 10' comes before 'Day 2' alphabetically.
            if numerical_params_selected:
                # Create a CategoricalDtype with the specific order
                cat_type = pd.CategoricalDtype(categories=numerical_params_selected, ordered=True)
                df_plot['_WithinFactorLevel_'] = df_plot['_WithinFactorLevel_'].astype(cat_type)
                df_plot = df_plot.sort_values(by=['_WithinFactorLevel_'])
                # Update plot args to use sorted df
                plot_args_rm['data_frame'] = df_plot
            # -----------------------------------------------------------------------

            title_suffix = f' by {", ".join(grouping_params)}' if grouping_params else ""
            rm_measure_names = ", ".join(numerical_params_selected) if numerical_params_selected else '_WithinFactorLevel_'
            plot_args_rm['title'] = f'{_("Repeated Measures")}: {rm_measure_names}{title_suffix}'
            color_param_rm = None
            if grouping_params:
                 if len(grouping_params) > 1:
                     sorted_gps = sorted(grouping_params)
                     combined_color_col_name = '_combined_group_plot_color'
                     df_temp_combine = df_plot[sorted_gps].astype(str).fillna('N/A').copy()
                     df_plot[combined_color_col_name] = df_temp_combine.apply(lambda r: '_'.join(r.values), axis=1)
                     color_param_rm = combined_color_col_name
                 else:
                    color_param_rm = grouping_params[0]
                 if color_param_rm not in df_plot.columns:
                      notes.append(_("Warning: Grouping column(s) '{cols}' selected for color/grouping not found in data for plotting.").format(cols=', '.join(grouping_params)))
                      color_param_rm = None
                 else:
                      df_plot[color_param_rm] = df_plot[color_param_rm].astype(str).fillna('N/A')
            hover_name_rm = None
            if graph_type == 'Scatter Plot' and subject_id_col and subject_id_col in df_plot.columns:
                 hover_name_rm = subject_id_col

            # --- START MODIFICATION: Correct graph type handling for RM ---
            if graph_type == 'Line Plot (Mean/SEM)':
                group_by_cols = ['_WithinFactorLevel_']
                if color_param_rm: group_by_cols.append(color_param_rm)
                group_by_cols_agg = [col for col in group_by_cols if col in df_plot.columns]
                if group_by_cols_agg:
                    summary_rm = df_plot.groupby(group_by_cols_agg, sort=False)['_MeasurementValue_'].agg(['mean', 'sem']).reset_index()
                    if not summary_rm.empty:
                        summary_rm_sorted = summary_rm.sort_values(by='_WithinFactorLevel_')
                        line_args = {'data_frame': summary_rm_sorted, 'x': '_WithinFactorLevel_', 'y': 'mean', 'title': plot_args_rm['title']}
                        if color_param_rm and color_param_rm in summary_rm_sorted.columns: line_args['color'] = color_param_rm
                        fig = px.line(**line_args, markers=True)
                        if 'sem' in summary_rm_sorted.columns:
                            if color_param_rm and color_param_rm in summary_rm_sorted.columns:
                                for group_name, group_df in summary_rm_sorted.groupby(color_param_rm):
                                      group_df = group_df.sort_values(by='_WithinFactorLevel_')
                                      fill_color = 'rgba(0,0,0,0.1)' # Default, can be made dynamic
                                      trace_color = next((trace.line.color for trace in fig.data if trace.name == str(group_name)), fill_color)
                                      sem_fill_color = fill_color
                                      if trace_color and not trace_color.startswith('rgba'):
                                          try:
                                              rgb_tuple = px.colors.hex_to_rgb(trace_color)
                                              sem_fill_color = f'rgba({rgb_tuple[0]}, {rgb_tuple[1]}, {rgb_tuple[2]}, 0.2)'
                                          except (ValueError, TypeError):
                                              sem_fill_color = fill_color # Fallback on error

                                      fig.add_trace(go.Scatter(x=group_df['_WithinFactorLevel_'], y=group_df['mean'] + group_df['sem'], mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip', fillcolor=sem_fill_color, name=f'{group_name}_upper_sem'))
                                      fig.add_trace(go.Scatter(x=group_df['_WithinFactorLevel_'], y=group_df['mean'] - group_df['sem'], mode='lines', line=dict(width=0), fill='tonexty', showlegend=False, hoverinfo='skip', fillcolor=sem_fill_color, name=f'{group_name}_lower_sem'))
                            else: # No color grouping
                                fig.add_trace(go.Scatter(x=summary_rm_sorted['_WithinFactorLevel_'], y=summary_rm_sorted['mean'] + summary_rm_sorted['sem'], mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip', fillcolor='rgba(0,0,0,0.1)', name='upper_sem'))
                                fig.add_trace(go.Scatter(x=summary_rm_sorted['_WithinFactorLevel_'], y=summary_rm_sorted['mean'] - summary_rm_sorted['sem'], mode='lines', line=dict(width=0), fill='tonexty', showlegend=False, hoverinfo='skip', fillcolor='rgba(0,0,0,0.1)', name='lower_sem'))
                        else: notes.append(_("SEM could not be calculated for Line Plot (Mean/SEM). Only mean line will be shown."))
                    else: notes.append(_("No data for summary statistics to plot Bar/Line (Mean/SEM) for RM set.")); fig = None
                else: notes.append(_("Could not aggregate data for Bar/Line (Mean/SEM) RM plot due to missing grouping columns.")); fig = None
            # --- END MODIFICATION ---
            elif graph_type == 'Box Plot':
                fig = px.box(**plot_args_rm, color=color_param_rm, points="all", hover_name=hover_name_rm)
            elif graph_type == 'Violin Plot':
                fig = px.violin(**plot_args_rm, color=color_param_rm, box=True, points="all", hover_name=hover_name_rm)
            elif graph_type == 'Bar (Mean/SEM)':
                group_by_cols = ['_WithinFactorLevel_']
                if color_param_rm: group_by_cols.append(color_param_rm)
                group_by_cols_agg = [col for col in group_by_cols if col in df_plot.columns]
                if group_by_cols_agg:
                    summary_rm = df_plot.groupby(group_by_cols_agg, sort=False)['_MeasurementValue_'].agg(['mean', 'sem']).reset_index()
                    if not summary_rm.empty:
                        # Ensure sorted order for plotting
                        summary_rm = summary_rm.sort_values(by='_WithinFactorLevel_')
                        bar_args_rm = {'data_frame': summary_rm, 'x': '_WithinFactorLevel_', 'y': 'mean', 'error_y': 'sem' if 'sem' in summary_rm.columns else None, 'title': plot_args_rm['title']}
                        if color_param_rm and color_param_rm in summary_rm.columns: bar_args_rm['color'] = color_param_rm
                        bar_args_rm['barmode'] = 'group' if color_param_rm else 'relative'
                        current_app.logger.debug(f"generate_plot: Calling px.bar with bar_args_rm={bar_args_rm}")
                        fig = px.bar(**bar_args_rm)
                        current_app.logger.debug(f"generate_plot: px.bar returned fig={fig}")
                    else: notes.append(_("No data for summary statistics to plot Bar/Line (Mean/SEM) for RM set.")); fig = None
                else: notes.append(_("Could not aggregate data for Bar/Line (Mean/SEM) RM plot due to missing grouping columns.")); fig = None
            elif graph_type == 'Scatter Plot':
                 scatter_args = plot_args_rm.copy()
                 scatter_color = None
                 if subject_id_col and subject_id_col in df_plot.columns:
                      scatter_color = subject_id_col
                      scatter_args['hover_name'] = subject_id_col
                 elif grouping_params:
                      if len(grouping_params) > 1:
                          sorted_gps = sorted(grouping_params)
                          combined_color_col_name = '_combined_group_plot_color'
                          df_temp_combine = df_plot[sorted_gps].astype(str).fillna('N/A').copy()
                          df_plot[combined_color_col_name] = df_temp_combine.apply(lambda r: '_'.join(r.values), axis=1)
                          scatter_color = combined_color_col_name
                      else:
                         scatter_color = grouping_params[0]
                      if scatter_color and scatter_color in df_plot.columns:
                          df_plot[scatter_color] = df_plot[scatter_color].astype(str).fillna('N/A')
                          # scatter_args['color'] = scatter_color # Color is already set by color_param_rm
                      else: notes.append(_("Warning: Grouping column(s) '{cols}' selected for color not found in data for plotting.").format(cols=', '.join(grouping_params)))
                 if color_param_rm: # Use the already determined color_param_rm
                    scatter_args['color'] = color_param_rm
                 fig = px.scatter(**scatter_args)
            else: notes.append(_("Unsupported graph type '{graph_type}' selected for Repeated Measures.").format(graph_type=graph_type)); fig = None

            if fig:
                 # --- START MODIFICATION: Use translated string for axis title ---
                 fig.update_layout(margin=dict(l=20,r=20,t=50,b=20), title_x=0.5, xaxis_title=_("Repeated Measure"))
                 # --- END MODIFICATION ---
                 if start_y_at_zero: fig.update_yaxes(rangemode='tozero')
                 if df_plot['_WithinFactorLevel_'].nunique() > 5: fig.update_xaxes(tickangle=45, automargin=True)
                 
                 # Enforce order of X-axis ticks (Analytes) if provided
                 if numerical_params_selected:
                     fig.update_xaxes(categoryorder='array', categoryarray=numerical_params_selected)

        else: # Not Repeated Measures
            cols_for_plotting = [numerical_param_or_dv] + grouping_params
            df_plot[numerical_param_or_dv] = pd.to_numeric(df_plot[numerical_param_or_dv], errors='coerce')
            for col in grouping_params:
                 if col in df_plot.columns: df_plot[col] = df_plot[col].astype(str).fillna('')
                 else: raise KeyError(f"Grouping column '{col}' missing for plotting.")
            df_plot = df_plot.dropna(subset=cols_for_plotting).copy()
            if df_plot.empty:
                 notes.append(_("No data available for plotting '{param}' after handling missing values.").format(param=numerical_param_or_dv))
                 return None, notes

            plot_group_col = None
            if not grouping_params: plot_group_col = '_OverallPlotGroup'; df_plot[plot_group_col] = 'Overall'
            elif len(grouping_params) == 1: plot_group_col = grouping_params[0]
            else:
                sorted_gps = sorted(grouping_params)
                if not all(col in df_plot.columns for col in sorted_gps): raise KeyError(f"Grouping columns missing for plot.")
                df_temp_combine = df_plot[sorted_gps].astype(str).fillna('N/A').copy()
                df_plot['_combined_group_plot'] = df_temp_combine.apply(lambda r: '_'.join(r.values), axis=1)
                plot_group_col = '_combined_group_plot'

            sort_cols_plot = [col for col in ([plot_group_col] if plot_group_col else []) if col in df_plot.columns]
            df_plot_sorted = df_plot.sort_values(by=sort_cols_plot).copy() if sort_cols_plot else df_plot.copy()
            title_plot = f'{numerical_param_or_dv} by {", ".join(grouping_params) if grouping_params else _("Overall")}'
            x_param_plot = None; color_param_plot = None; group_by_cols_for_summary = []

            if not grouping_params:
                x_param_plot = '_OverallPlotGroup'
                if x_param_plot not in df_plot_sorted.columns: df_plot_sorted[x_param_plot] = 'Overall'
                if x_param_plot in df_plot_sorted.columns: group_by_cols_for_summary.append(x_param_plot)
            elif len(grouping_params) == 1:
                x_param_plot = grouping_params[0]
                if x_param_plot in df_plot_sorted.columns: group_by_cols_for_summary.append(x_param_plot)
            else: # More than 1 grouping param
                x_param_plot = grouping_params[0] # First for X-axis
                color_param_plot = grouping_params[1] # Second for color
                if x_param_plot in df_plot_sorted.columns: group_by_cols_for_summary.append(x_param_plot)
                if color_param_plot in df_plot_sorted.columns:
                    df_plot_sorted[color_param_plot] = df_plot_sorted[color_param_plot].astype(str).fillna('N/A')
                    group_by_cols_for_summary.append(color_param_plot)
                # If more than 2 grouping_params, they are combined into plot_group_col for faceting/hover,
                # but px.bar/box etc. typically use one for x and one for color directly.

            plot_func_map = {'Bar (Mean/SEM)': px.bar, 'Box Plot': px.box, 'Violin Plot': px.violin, 'Scatter Plot': px.strip}
            plot_df_used = None

            if graph_type == 'Bar (Mean/SEM)':
                 if group_by_cols_for_summary and all(c in df_plot_sorted.columns for c in group_by_cols_for_summary):
                      summary_stats = df_plot_sorted.groupby(group_by_cols_for_summary, sort=False, as_index=False).agg(mean=(numerical_param_or_dv, 'mean'), sem=(numerical_param_or_dv, 'sem'))
                      plot_df_used = summary_stats
                      if 'mean' not in plot_df_used.columns: notes.append(_("Could not calculate mean for Bar (Mean/SEM) plot for '{param}'.")).format(param=numerical_param_or_dv); fig = None
                 else: notes.append(_("Could not aggregate data for Bar (Mean/SEM) plot for '{param}' due to missing or invalid grouping columns.")).format(param=numerical_param_or_dv); fig = None
            else: plot_df_used = df_plot_sorted

            if fig is None and graph_type in plot_func_map and plot_df_used is not None and not plot_df_used.empty and x_param_plot and x_param_plot in plot_df_used.columns:
                 plot_args = {'data_frame': plot_df_used, 'x': x_param_plot, 'y': numerical_param_or_dv if graph_type != 'Bar (Mean/SEM)' else 'mean', 'title': title_plot}
                 if color_param_plot and color_param_plot in plot_df_used.columns: plot_args['color'] = color_param_plot
                 
                 specific_call_args = plot_args.copy()
                 if graph_type == 'Bar (Mean/SEM)':
                     specific_call_args.update({'y': 'mean', 'error_y': 'sem' if 'sem' in plot_df_used.columns else None, 'labels': {'mean': f'Mean {numerical_param_or_dv}'}})
                     if color_param_plot and color_param_plot in plot_df_used.columns: specific_call_args['barmode'] = 'group'
                     if 'sem' not in plot_df_used.columns: specific_call_args.pop('error_y', None)
                 elif graph_type in ['Box Plot', 'Violin Plot']: specific_call_args['points'] = "all"
                 if graph_type == 'Violin Plot': specific_call_args['box'] = True
                 
                 if specific_call_args['y'] in plot_df_used.columns: fig = plot_func_map[graph_type](**specific_call_args)
                 else: notes.append(_("Plotting error for '{param}': Required Y-axis column '{y_col}' not found in data.")).format(param=numerical_param_or_dv, y_col=specific_call_args['y']); fig = None
            elif fig is None and (plot_df_used is None or plot_df_used.empty) : notes.append(_("No data for plotting '{param}'.")).format(param=numerical_param_or_dv); fig = None
            elif fig is None: notes.append(_("Plotting error for '{param}'.")).format(param=numerical_param_or_dv); fig = None

            if fig:
                 fig.update_layout(margin=dict(l=20,r=20,t=50,b=20), title_x=0.5)
                 if start_y_at_zero: fig.update_yaxes(rangemode='tozero')
                 if plot_group_col and plot_group_col.startswith('_combined_group_'): fig.update_xaxes(title_text=", ".join(grouping_params))
                 if plot_df_used is not None and x_param_plot in plot_df_used.columns and plot_df_used[x_param_plot].nunique() > 5: fig.update_xaxes(tickangle=45, automargin=True)

        # --- START: Reference Range Plotting Logic ---
        # This logic is now generalized for both repeated and non-repeated measures plots.
        # For repeated measures, the reference range is applied across all levels.
        param_to_check_in_ref = '_MeasurementValue_' if is_repeated else numerical_param_or_dv

        if fig and reference_range_summary and param_to_check_in_ref in reference_range_summary:
            ref_stats = reference_range_summary[param_to_check_in_ref]
            ref_mean = ref_stats.get('mean')
            ref_min = ref_stats.get('min')
            ref_max = ref_stats.get('max')

            if all(v is not None for v in [ref_mean, ref_min, ref_max]):
                ref_color = 'rgba(128, 0, 128, 0.2)'  # Purple with transparency for the band
                ref_line_color = 'rgb(128, 0, 128)'  # Solid purple for the mean line

                # Add a dummy trace for the legend
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='lines',
                    line=dict(color=ref_line_color, width=2, dash='dash'),
                    fill='tozeroy',
                    fillcolor=ref_color,
                    name=_('Reference Range')
                ))

                # Using shapes is a robust way to add horizontal bands and lines
                # that span the entire width of the plot, regardless of x-axis type.
                new_shapes = [
                    # Shaded rectangle for the min-max range
                    go.layout.Shape(
                        type="rect",
                        xref="paper", yref="y",
                        x0=0, x1=1,
                        y0=ref_min, y1=ref_max,
                        fillcolor=ref_color,
                        layer="below",
                        line_width=0,
                    ),
                    # Dashed line for the mean
                    go.layout.Shape(
                        type="line",
                        xref="paper", yref="y",
                        x0=0, x1=1,
                        y0=ref_mean, y1=ref_mean,
                        line=dict(color=ref_line_color, width=2, dash='dash'),
                        layer="below"
                    )
                ]
                
                # Add new shapes to any existing shapes in the layout
                fig.update_layout(shapes=new_shapes + list(fig.layout.shapes))

                notes.append(_("Reference range (min-max band and mean line) for '{param}' has been added to the plot.").format(param=param_to_check_in_ref))
            else:
                notes.append(_("Reference range for '{param}' is missing some statistical values (mean, min, max) and could not be plotted.").format(param=param_to_check_in_ref))
        
        # --- Significance Stars Logic (Simple 2-Group) ---
        if fig and stats_results and not stats_results.get('error'):
             if stats_results.get('groups_compared') == 2 and stats_results.get('p_value', 1.0) < 0.05:
                  p_val = stats_results.get('p_value')
                  symbol = '***' if p_val < 0.001 else '**' if p_val < 0.01 else '*'
                  
                  # Must calculate max Y to place annotation
                  y_max = df_plot[param_to_check_in_ref].max()
                  y_range = y_max - df_plot[param_to_check_in_ref].min()
                  y_text = y_max + (y_range * 0.1)
                  
                  # Simple centered annotation for now since we don't know X-coords of categories easily
                  fig.add_annotation(
                       x=0.5, xref="paper", 
                       y=y_text, 
                       text=f"{symbol} (p={p_val:.3f})", 
                       showarrow=False, 
                       font=dict(size=14, color="black")
                  )
                  # Expand Y axis to fit
                  fig.update_layout(yaxis=dict(range=[None, y_text + (y_range * 0.1)]))

        elif fig and reference_range_summary:
            notes.append(_("Selected reference range does not contain data for the parameter '{param}' or could not be plotted for this configuration.").format(param=param_to_check_in_ref))
        # --- END: Reference Range Plotting Logic ---

        # Convert figure to JSON string if it exists
        graph_json_data = fig.to_json() if fig else None
    except Exception as e_plot:
        graph_json_data = None
        notes.append(_("Plotting Error: {e}").format(e=str(e_plot)))
        current_app.logger.error(f"Plotting error for {numerical_param_or_dv}: {e_plot}", exc_info=True)

    current_app.logger.debug(f"generate_plot: Returning graph_json_data={graph_json_data}, notes={notes}")
    return graph_json_data, notes





def generate_survival_plot(df, time_col, event_col, grouping_params):
    """
    Generates Kaplan-Meier survival plot using lifelines (or manual calc) and styling with Plotly.
    """
    notes = []
    try:
        from lifelines import KaplanMeierFitter
        
        fig = go.Figure()
        kmf = KaplanMeierFitter()
        
        df_clean = df.dropna(subset=[time_col, event_col]).copy()
        # Convert Event to Binary (1/0 or True/False)
        # Heuristic: If string, 'Dead'/'Event'/'1' = 1.
        if not pd.api.types.is_numeric_dtype(df_clean[event_col]):
             # dangerous guess, but useful
             positive_indicators = ['dead', 'died', 'event', '1', 'yes', 'true']
             df_clean[event_col] = df_clean[event_col].astype(str).str.lower().isin(positive_indicators).astype(int)
        
        # Grouping
        if not grouping_params:
             # Overall
             kmf.fit(df_clean[time_col], df_clean[event_col], label=_('All Subjects'))
             # Plot Step
             # Re-do properly:
             timeline = kmf.timeline
             
             # Add Line
             fig.add_trace(go.Scatter(x=timeline, y=kmf.survival_function_.iloc[:, 0], mode='lines', name=_('All Subjects'), line_shape='hv'))
             
        else:
             # By Group
             # Create combined group col
             if len(grouping_params) == 1:
                 grp_col = grouping_params[0]
             else:
                 grp_col = '_survival_grp'
                 df_clean[grp_col] = df_clean[grouping_params].astype(str).agg(' / '.join, axis=1)
            
             for name, grouped_df in df_clean.groupby(grp_col):
                  kmf.fit(grouped_df[time_col], grouped_df[event_col], label=str(name))
                  
                  # Add trace
                  fig.add_trace(go.Scatter(x=kmf.timeline, y=kmf.survival_function_.iloc[:, 0], mode='lines', name=str(name), line_shape='hv'))

        fig.update_layout(
            title=_('Kaplan-Meier Survival Curve'),
            xaxis_title=time_col,
            yaxis_title=_('Survival Probability'),
            yaxis=dict(range=[0, 1.05]),
            template='plotly_white'
        )
        return fig.to_json(), notes

    except ImportError:
         return None, [_l("Survival Library (lifelines) not installed.")]
    except Exception as e:
         current_app.logger.error(f"KM Plot Error: {e}")
         return None, [str(e)]
