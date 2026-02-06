# app/datatables/routes_analysis.py
from flask import current_app, flash, redirect, render_template, request, session, url_for, jsonify
from flask_babel import gettext as _
from flask_login import login_required, current_user

from app.extensions import db
from app.models import DataTable
from app.permissions import check_datatable_permission
from app.services.analysis_service import AnalysisService
from app.tasks import perform_analysis_task
from celery.result import AsyncResult
from app.helpers import replace_undefined 

from . import datatables_bp

analysis_service = AnalysisService()

@datatables_bp.route('/analyze/<int:datatable_id>', methods=['GET', 'POST'])
@login_required
def analyze_datatable(datatable_id):
    data_table = db.session.get(DataTable, datatable_id)
    if not data_table or not data_table.group:
        flash(_("Table/Group not found."), "error")
        return redirect(url_for('main.index'))
    if not check_datatable_permission(data_table, 'read'):
        flash(_("Permission denied."), "danger")
        return redirect(url_for('groups.manage_groups'))

    # 1. Prepare Data
    # OPTIMIZATION: On GET (initial load), do NOT load the full dataframe.
    # Use Schema Inspection instead.
    
    if request.method == 'GET' and not 'latest_analysis_results' in session:
         # FAST PATH
         numerical_cols, categorical_cols, column_types = analysis_service.get_datatable_metadata(data_table)
         df = None # We don't need the DF for the form
         subject_id_col = 'ID' # Default
         subject_id_col_present = True # Assumed for form
    else:
         # SLOW PATH (Analysis execution or Result display)
         df, numerical_cols, categorical_cols = analysis_service.prepare_dataframe(data_table)
         
         # Build column_types from the dataframe
         column_types = {}
         for col in numerical_cols:
             column_types[col] = 'numerical'
         for col in categorical_cols:
             column_types[col] = 'categorical'
         
         if df is None or df.empty:
            flash(_("No data rows available in this DataTable to analyze."), "warning")
            return redirect(url_for('datatables.edit_data_table', id=datatable_id))
            
         subject_id_col = 'ID'
         subject_id_col_present = subject_id_col in df.columns

    # 2. Handle State & Session
    analysis_stage = 'initial_selection'
    form_data = {}
    analysis_results = {}
    
    session_key = f'analysis_params_{datatable_id}'

    # CHECK FOR ASYNC RESULTS FIRST
    if 'latest_analysis_results' in session:
        # We found results from a just-finished background task
        analysis_results = session.pop('latest_analysis_results')
        analysis_stage = 'show_results'
        
        # Restore form data for context
        if session_key in session:
            form_data = session.get(session_key)
            
    elif request.method == 'GET' and session_key in session:
        # Restore previous state
        form_data = session.get(session_key)
        analysis_stage = form_data.get('analysis_stage', 'initial_selection')
        # If we were executing, reset to initial to avoid getting stuck
        if analysis_stage == 'execute_analysis':
            analysis_stage = 'initial_selection'

    elif request.method == 'POST':
        analysis_stage = request.form.get('analysis_stage', 'initial_selection')
        form_data = _extract_form_data(request.form, analysis_stage)

        # 3. ASYNC HANDOFF
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('is_async') == 'true'
        
        if analysis_stage == 'execute_analysis' and is_ajax:
            # Save form data so we can restore it after reload
            session[session_key] = replace_undefined(form_data)
            
            task = perform_analysis_task.delay(
                form_data=form_data,
                datatable_id=datatable_id,
                user_id=current_user.id
            )
            return jsonify({'status': 'submitted', 'task_id': task.id})

        # 4. Synchronous Fallback (e.g. Propose Workflow)
        if analysis_stage == 'propose_workflow':
            # We MUST have the DF here. If we came from POST, we loaded it above (else block of step 1).
            # But wait, step 1 logic: 
            # if request.method == 'GET'... else ... (POST falls into else)
            # So df IS loaded for POST.
            
            analysis_results = analysis_service.perform_analysis(
                df, form_data, subject_id_col, subject_id_col_present, 
                numerical_cols, categorical_cols
            )
        elif analysis_stage == 'execute_analysis':
             analysis_results = analysis_service.perform_analysis(
                df, form_data, subject_id_col, subject_id_col_present, 
                numerical_cols, categorical_cols
            )
             analysis_stage = 'show_results'

    return render_template(
        'datatables/analysis.html',
        data_table=data_table,
        categorical_columns=categorical_cols,
        numerical_columns=numerical_cols,
        column_types=column_types,
        analysis_stage=analysis_stage,
        form_data=form_data,
        analysis_results=analysis_results,
        subject_id_col=subject_id_col,
        subject_id_col_present=subject_id_col_present,
        source_identifiers=[f"{data_table.group.name} - {data_table.protocol.name} ({data_table.date})"]
    )

@datatables_bp.route('/analyze_selected_datatables', methods=['GET', 'POST'])
@login_required
def analyze_selected_datatables():
    form_data = {}
    selected_ids = []
    session_key_merged = None 
    analysis_results = {}
    analysis_stage = 'initial_selection'

    # 1. Resolve IDs
    if request.method == 'POST':
        raw_ids = request.form.getlist('selected_datatable_ids[]')
        try:
            selected_ids = sorted([int(x) for x in raw_ids if x.isdigit()])
            if selected_ids:
                session_key_merged = f'analysis_params_merged_{"_".join(map(str, selected_ids))}'
        except ValueError:
            pass
    elif request.method == 'GET':
        # Check for async results first
        if 'latest_analysis_results' in session:
            analysis_results = session.pop('latest_analysis_results')
            analysis_stage = 'show_results'
            current_app.logger.debug(f"Multi-datatable show_results: analysis_results keys: {list(analysis_results.keys())}")
            
            # Try to find the matching session key for form data
            prefix = 'analysis_params_merged_'
            for key in list(session.keys()): 
                 if key.startswith(prefix):
                      session_key_merged = key
                      selected_ids = [int(x) for x in key[len(prefix):].split('_') if x.isdigit()]
                      form_data = session.get(key)
                      break
        else:
            # Standard GET restore
            prefix = 'analysis_params_merged_'
            for key in list(session.keys()): 
                 if key.startswith(prefix):
                      session_key_merged = key
                      selected_ids = [int(x) for x in key[len(prefix):].split('_') if x.isdigit()]
                      form_data = session.get(key)
                      analysis_stage = form_data.get('analysis_stage', 'initial_selection')
                      if analysis_stage == 'execute_analysis': analysis_stage = 'initial_selection'
                      break
    
    if not selected_ids: 
        flash(_("No valid datatables identified for analysis."), "danger")
        return redirect(url_for('datatables.create_data_table'))

    # 2. Prepare Metadata
    df_combined, agg_errors, source_identifiers = analysis_service.aggregate_datatables(selected_ids)

    if agg_errors:
        for err in agg_errors: flash(err, "danger")
    if df_combined is None or df_combined.empty:
        flash(_("No data available to analyze after merging."), "danger")
        return redirect(request.referrer or url_for('datatables.create_data_table'))
    
    subject_id_col = 'ID'
    subject_id_col_present = subject_id_col in df_combined.columns
    
    numerical_cols = []
    categorical_cols = []
    column_types = {}  # New: track column types
    import pandas as pd
    internal_cols = ['_source_datatable_id', '_source_experimental_group_name', '_source_protocol_name', '_source_datatable_date']
    for col in df_combined.columns:
        if col in internal_cols or col == subject_id_col: continue
        if pd.api.types.is_numeric_dtype(df_combined[col]):
            numerical_cols.append(col)
            column_types[col] = 'numerical'
        else:
            categorical_cols.append(col)
            column_types[col] = 'categorical'

    # 3. Handle POST Actions
    if request.method == 'POST':
        analysis_stage = request.form.get('analysis_stage', 'initial_selection')
        form_data = _extract_form_data(request.form, analysis_stage)
        form_data['selected_datatable_ids'] = [str(x) for x in selected_ids]

        # ASYNC HANDOFF
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('is_async') == 'true'
        current_app.logger.debug(f"Multi-datatable analysis: analysis_stage={analysis_stage}, is_ajax={is_ajax}, is_async={request.form.get('is_async')}")
        if analysis_stage == 'execute_analysis' and is_ajax:
            if session_key_merged:
                session[session_key_merged] = replace_undefined(form_data)
            
            task = perform_analysis_task.delay(
                form_data=form_data,
                selected_ids=selected_ids,
                user_id=current_user.id
            )
            return jsonify({'status': 'submitted', 'task_id': task.id})

        # Sync Fallback
        if analysis_stage == 'propose_workflow':
            analysis_results = analysis_service.perform_analysis(
                df_combined, form_data, subject_id_col, subject_id_col_present, 
                numerical_cols, categorical_cols
            )
        elif analysis_stage == 'execute_analysis':
             analysis_results = analysis_service.perform_analysis(
                df_combined, form_data, subject_id_col, subject_id_col_present, 
                numerical_cols, categorical_cols
            )
             analysis_stage = 'show_results'

    page_title = _("Merged Analysis") + f" ({len(source_identifiers)} datatables)"

    return render_template(
        'datatables/analysis.html',
        analysis_page_title=page_title,
        categorical_columns=sorted(categorical_cols),
        numerical_columns=sorted(numerical_cols),
        column_types=column_types,
        analysis_stage=analysis_stage,
        form_data=form_data,
        analysis_results=analysis_results,
        subject_id_col=subject_id_col,
        subject_id_col_present=subject_id_col_present,
        source_identifiers=source_identifiers
    )

@datatables_bp.route('/analysis/status/<task_id>')
@login_required
def analysis_status(task_id):
    task = AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {'state': 'PENDING', 'status': 'Analysis in progress...'}
    elif task.state != 'FAILURE':
        clean_results = replace_undefined(task.result)
        session['latest_analysis_results'] = clean_results
        current_app.logger.debug("Set latest_analysis_results in session for multi-datatable")
        
        response = {
            'state': 'SUCCESS',
            # We don't need to send the full result JSON to the frontend, 
            # just the signal to reload.
        }
        
        if isinstance(task.result, dict) and 'error' in task.result:
             response['state'] = 'FAILURE'
             response['status'] = task.result['error']
    else:
        response = {
            'state': 'FAILURE',
            'status': str(task.info)
        }
    return jsonify(response)

@datatables_bp.route('/api/group_levels/<int:datatable_id>', methods=['POST'])
@login_required
def api_get_group_levels(datatable_id):
    """
    API endpoint to fetch unique levels (or combinations) for selected grouping columns.
    Used to populate the 'Control Group' dropdown for statistical tests.
    """
    data_table = db.session.get(DataTable, datatable_id)
    if not data_table:
        return jsonify({'error': _("DataTable not found")}), 404
    
    if not check_datatable_permission(data_table, 'read'):
         return jsonify({'error': _("Permission denied")}), 403

    group_cols = request.json.get('groups', [])
    
    # Validation
    if not isinstance(group_cols, list):
         group_cols = [group_cols] if group_cols else []

    if not group_cols:
        return jsonify({'levels': []})

    # Load Data (Fast path not possible as we need actual data values)
    df, _, _ = analysis_service.prepare_dataframe(data_table)
    
    if df is None or df.empty:
        return jsonify({'levels': []})

    # Validate columns exist
    valid_cols = [c for c in group_cols if c in df.columns]
    if not valid_cols:
         return jsonify({'levels': []})

    try:
        if len(valid_cols) == 1:
            # Single column: just unique values
            levels = sorted(df[valid_cols[0]].dropna().unique().astype(str).tolist())
        else:
            # Multiple columns: combinations joined by ' / '
            df_subset = df[valid_cols].dropna() 
            if df_subset.empty:
                 levels = []
            else:
                levels = sorted(df_subset.astype(str).agg(' / '.join, axis=1).unique().tolist())
                
        return jsonify({'levels': levels})
    except Exception as e:
        current_app.logger.error(f"Error fetching group levels: {e}")
        return jsonify({'error': str(e)}), 500


@datatables_bp.route('/api/group_levels/merged', methods=['POST'])
@login_required
def api_get_group_levels_merged():
    """
    API endpoint to fetch unique levels for selected grouping columns across MULTIPLE datatables.
    """
    payload = request.json or {}
    group_cols = payload.get('groups', [])
    datatable_ids = payload.get('datatable_ids', [])
    
    # Validation
    if not isinstance(group_cols, list): group_cols = [group_cols] if group_cols else []
    if not isinstance(datatable_ids, list): 
         # Try to get from session if not in payload?
         # For now, require it in payload (simplest for JS to send from CONFIG)
         return jsonify({'levels': []}) 
         
    if not group_cols or not datatable_ids:
        return jsonify({'levels': []})

    # Convert IDs
    try:
        dt_ids = [int(x) for x in datatable_ids if str(x).isdigit()]
    except:
        return jsonify({'levels': []})
        
    if not dt_ids: return jsonify({'levels': []})

    try:
        # We need to aggregate to get the levels across all tables
        # Using analysis_service.aggregate_datatables is heavy but accurate.
        # Ideally we'd optimize this, but for < 50 tables it's fine.
        df, _, _ = analysis_service.aggregate_datatables(dt_ids, user_id=current_user.id)
        
        if df is None or df.empty:
            return jsonify({'levels': []})

        valid_cols = [c for c in group_cols if c in df.columns]
        if not valid_cols:
             return jsonify({'levels': []})

        if len(valid_cols) == 1:
            levels = sorted(df[valid_cols[0]].dropna().unique().astype(str).tolist())
        else:
            df_subset = df[valid_cols].dropna() 
            if df_subset.empty:
                 levels = []
            else:
                levels = sorted(df_subset.astype(str).agg(' / '.join, axis=1).unique().tolist())
                
        return jsonify({'levels': levels})
        
    except Exception as e:
        current_app.logger.error(f"Error fetching merged group levels: {e}")
        return jsonify({'error': str(e)}), 500


def _extract_form_data(form, stage):
    """Helper to extract and persist form data."""
    data = {
        'grouping_params': form.getlist('grouping_params') or form.getlist('confirmed_grouping_params'),
        'numerical_params': form.getlist('numerical_params') or form.getlist('confirmed_numerical_params'),
        'splitting_param': form.get('splitting_param') or form.get('confirmed_splitting_param'),
        'is_repeated_measures': (form.get('is_repeated_measures') == 'on') or (form.get('confirmed_is_repeated') == 'true'),
        'graph_type': form.get('graph_type') or form.get('confirmed_graph_type', 'Box Plot'),
        'start_y_at_zero': (form.get('start_y_at_zero') == 'true') or (form.get('confirmed_start_y_at_zero') == 'true'),
        'exclude_outliers': (form.get('exclude_outliers') == 'true') or (form.get('confirmed_exclude_outliers') == 'true'),
        'outlier_method': form.get('outlier_method') or form.get('confirmed_outlier_method', 'iqr'),
        'outlier_threshold': float(form.get('outlier_threshold') or form.get('confirmed_outlier_threshold', 1.5)),
        'reference_range_id': form.get('reference_range_id') or form.get('confirmed_reference_range_id'),
        'control_group_param': form.get('control_group_param') or form.get('confirmed_control_group_param'),
        'covariate_param': form.get('covariate_param') or form.get('confirmed_covariate_param'),
        'survival_time_col': form.get('survival_time_col') or form.get('confirmed_survival_time_col'),
        'survival_event_col': form.get('survival_event_col') or form.get('confirmed_survival_event_col'),
        'enable_survival': (form.get('enable_survival') == 'true') or (form.get('confirmed_enable_survival') == 'true'),
        'graph_type_rm_set': form.get('graph_type_rm_set') or form.get('confirmed_graph_type_rm_set'),
        'chosen_tests': {k.replace('chosen_test_', ''): v for k, v in form.items() if k.startswith('chosen_test_')},
        'analysis_stage': stage
    }
    
    # Capture per-parameter graph selections
    graph_selections = {k: v for k, v in form.items() if k.startswith('chosen_graph_')}
    data.update(graph_selections)

    # Persist confirmed values
    data.update({
        'confirmed_grouping_params': data['grouping_params'],
        'confirmed_numerical_params': data['numerical_params'],
        'confirmed_splitting_param': data['splitting_param'],
        'confirmed_is_repeated': data['is_repeated_measures'],
        'confirmed_graph_type': data['graph_type'],
        'confirmed_start_y_at_zero': data['start_y_at_zero'],
        'confirmed_exclude_outliers': data['exclude_outliers'],
        'confirmed_outlier_method': data['outlier_method'],
        'confirmed_outlier_threshold': data['outlier_threshold'],
        'confirmed_reference_range_id': data['reference_range_id'],
        'confirmed_control_group_param': data['control_group_param'],
        'confirmed_covariate_param': data['covariate_param'],
        'confirmed_survival_time_col': data['survival_time_col'],
        'confirmed_survival_event_col': data['survival_event_col'],
        'confirmed_enable_survival': data['enable_survival'],
        'confirmed_graph_type_rm_set': data['graph_type_rm_set']
    })
    return data