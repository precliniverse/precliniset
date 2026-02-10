# app/reference_ranges/routes.py

import io
from collections import defaultdict
from datetime import datetime

import pandas as pd
from flask import (current_app, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required

from app import db
from app.extensions import limiter
from app.models import \
    user_has_permission  # Added for granular permission check
from app.models import (Analyte, AnimalModel, DataTable, ExperimentalGroup,
                        ExperimentDataRow, Project, ProtocolModel,
                        ReferenceRange, Team)
from app.permissions import (can_edit_reference_range,
                             can_view_reference_range,
                             check_datatable_permission,
                             check_group_permission)

from . import reference_ranges_bp


# This route will list all available reference ranges
@reference_ranges_bp.route('/')
@login_required
def list_reference_ranges():
    # Query filters
    analyte_id = request.args.get('analyte_id', type=int)
    protocol_id = request.args.get('protocol_id', type=int)

    # Query logic to get accessible reference ranges
    query = ReferenceRange.query
    
    if analyte_id:
        query = query.filter(ReferenceRange.analyte_id == analyte_id)
    if protocol_id:
        query = query.filter(ReferenceRange.protocol_id == protocol_id)

    ranges = query.order_by(ReferenceRange.name).all()
    
    # NEW: Prepare summary data for each range
    ranges_with_summary = []
    for r in ranges:
        summary = {
            'total_animals': 0,
            'protocols': set(),
            'projects': set(),
            'groups': set()
        }
        if r.included_animals:
            group_ids = r.included_animals.keys()
            if group_ids:
                # Fetch all relevant groups at once
                groups_in_range = ExperimentalGroup.query.filter(ExperimentalGroup.id.in_(group_ids)).options(
                    db.joinedload(ExperimentalGroup.project),
                    db.joinedload(ExperimentalGroup.model)
                ).all()
                
                for group in groups_in_range:
                    # JSON keys are strings, ensure we use string version of group.id for lookup
                    num_animals_in_group = len(r.included_animals.get(str(group.id), []))
                    summary['total_animals'] += num_animals_in_group
                    if group.project:
                        summary['projects'].add(group.project.name)
                    summary['groups'].add(group.name)
        
        # The protocol is directly on the reference range model
        if r.protocol:
            summary['protocols'].add(r.protocol.name)
            
        ranges_with_summary.append({'range': r, 'summary': summary})

    # Get all analytes and protocols that have at least one reference range (for filters)
    used_analyte_ids = db.session.query(ReferenceRange.analyte_id).distinct().all()
    used_analyte_ids = [a[0] for a in used_analyte_ids if a[0] is not None]
    analytes = Analyte.query.filter(Analyte.id.in_(used_analyte_ids)).order_by(Analyte.name).all() if used_analyte_ids else []

    used_protocol_ids = db.session.query(ReferenceRange.protocol_id).distinct().all()
    used_protocol_ids = [p[0] for p in used_protocol_ids if p[0] is not None]
    protocols = ProtocolModel.query.filter(ProtocolModel.id.in_(used_protocol_ids)).order_by(ProtocolModel.name).all() if used_protocol_ids else []

    return render_template('reference_ranges/list_reference_ranges.html', 
                           ranges_with_summary=ranges_with_summary,
                           analytes=analytes,
                           protocols=protocols,
                           current_analyte_id=analyte_id,
                           current_protocol_id=protocol_id)

# This route will handle creation and editing
@reference_ranges_bp.route('/edit', methods=['GET', 'POST'])
@reference_ranges_bp.route('/edit/<int:range_id>', methods=['GET', 'POST'])
@login_required
def create_edit_reference_range(range_id=None):
    ref_range = db.session.get(ReferenceRange, range_id) if range_id else None
    if range_id and not ref_range:
        flash(_l("Reference Range not found."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))

    # Check permissions
    if ref_range and not can_edit_reference_range(ref_range.id):
        flash(_l("You do not have permission to edit this Reference Range."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))
    elif not ref_range and not user_has_permission(current_user, 'ReferenceRange', 'create', allow_any_team=True):
        flash(_l("You do not have permission to create a new Reference Range."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))

    if request.method == 'POST':
        # Re-check permissions for POST requests
        if ref_range and not can_edit_reference_range(ref_range.id):
            return jsonify({'success': False, 'message': 'Permission denied.'}), 403
        elif not ref_range and not user_has_permission(current_user, 'ReferenceRange', 'create', allow_any_team=True):
            return jsonify({'success': False, 'message': 'Permission denied.'}), 403
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid JSON data.'}), 400

        name = data.get('name')
        team_id = data.get('team_id')
        included_animals = data.get('included_animals', {})
        protocol_id = data.get('protocol_id')
        analyte_id = data.get('analyte_id')
        animal_model_id = data.get('animal_model_id')

        if not all([name, team_id, protocol_id, analyte_id, animal_model_id]):
            return jsonify({'success': False, 'message': 'Missing required fields (Name, Team, Analyte, Protocol, Animal Model).'}), 400

        # Check for name uniqueness within the team
        query = ReferenceRange.query.filter_by(team_id=team_id, name=name)
        if ref_range:
            query = query.filter(ReferenceRange.id != ref_range.id)
        if query.first():
            return jsonify({'success': False, 'message': _l('A Reference Range with this name already exists in the selected team.')}), 409

        if not ref_range:
            ref_range = ReferenceRange(owner_id=current_user.id)
            db.session.add(ref_range)
        
        ref_range.name = name
        ref_range.description = data.get('description')
        ref_range.team_id = team_id
        ref_range.analyte_id = analyte_id
        ref_range.protocol_id = protocol_id
        ref_range.animal_model_id = animal_model_id
        ref_range.min_age = data.get('min_age')
        ref_range.max_age = data.get('max_age')
        ref_range.included_animals = included_animals
        ref_range.is_globally_shared = data.get('is_globally_shared', False)

        # Handle team sharing
        shared_team_ids = data.get('shared_with_team_ids', [])
        if ref_range.is_globally_shared:
            ref_range.shared_with_teams = []
        else:
            teams_to_share = Team.query.filter(Team.id.in_(shared_team_ids)).all()
            ref_range.shared_with_teams = teams_to_share
        
        try:
            db.session.commit()
            flash(_l('Reference Range saved successfully!'), 'success')
            return jsonify({'success': True, 'redirect_url': url_for('reference_ranges.list_reference_ranges')})
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving reference range: {e}", exc_info=True)
            return jsonify({'success': False, 'message': str(e)}), 500

    # GET request logic
    teams = current_user.get_teams()
    
    # Get details for already included animals
    included_animals_details = []
    if ref_range and ref_range.included_animals:
        for group_id, animal_indices in ref_range.included_animals.items():
            group = db.session.get(ExperimentalGroup, group_id)
            # Get animals sorted by ID to maintain index compatibility
            animals = sorted(group.animals, key=lambda a: a.id)
            if animals:
                for index in animal_indices:
                    if 0 <= index < len(animals):
                        animal = animals[index].to_dict()
                        animal_info = {
                            'group_id': group.id,
                            'group_name': group.name,
                            'project_name': group.project.name,
                            'animal_index': index,
                            'animal_id': animal.get('uid') or animal.get('ID', f"Index {index}")
                        }
                        # Merge all other animal parameters
                        animal_info.update(animal)
                        included_animals_details.append(animal_info)

    # Calculate extra columns for headers
    extra_columns = set()
    fixed_keys = {'group_id', 'group_name', 'project_name', 'animal_index', 'animal_id', 'ID'}
    for animal in included_animals_details:
        for key in animal.keys():
            if key not in fixed_keys:
                extra_columns.add(key)
    extra_columns_list = sorted(list(extra_columns))

    import json
    existing_data = ref_range.to_dict() if ref_range else {}
    if ref_range and ref_range.analyte:
        existing_data['analyte_name'] = ref_range.analyte.name
    existing_data_json = json.dumps(existing_data)
    
    # Get all teams for the sharing dropdown, excluding the owning team
    all_teams = Team.query.order_by(Team.name).all()
    shareable_teams = [t for t in all_teams if t.id != (ref_range.team_id if ref_range else None)]

    return render_template('reference_ranges/create_edit_reference_range.html',
                           ref_range=ref_range,
                           teams=teams,
                           existing_data_json=existing_data_json,
                           included_animals_details=included_animals_details,
                           extra_columns=extra_columns_list,
                           all_teams=shareable_teams)

@reference_ranges_bp.route('/download_data/<int:range_id>')
@login_required
def download_reference_range_data(range_id):
    ref_range = db.session.get(ReferenceRange, range_id)
    if not ref_range:
        flash(_l("Reference Range not found."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))

    # Check permissions: user must have view access to the reference range
    if not can_view_reference_range(ref_range.id):
        flash(_l("You do not have permission to download data for this Reference Range."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))

    all_data_rows = []

    groups_to_fetch = set(ref_range.included_animals.keys())
    
    # Fetch all relevant groups
    experimental_groups = ExperimentalGroup.query.filter(ExperimentalGroup.id.in_(groups_to_fetch)).options(
        db.joinedload(ExperimentalGroup.model),
        db.joinedload(ExperimentalGroup.project)
    ).all()

    # Create a dictionary for quick lookup of groups by ID
    group_map = {group.id: group for group in experimental_groups}

    # Fetch all relevant data tables and their experiment rows in separate queries
    all_group_ids = list(groups_to_fetch)
    
    # Fetch all DataTables for these groups and the specific protocol
    data_tables = DataTable.query.filter(
        DataTable.group_id.in_(all_group_ids),
        DataTable.protocol_id == ref_range.protocol_id
    ).options(
        db.joinedload(DataTable.protocol)
    ).all()

    # Map data tables to their groups and then to their animal data
    data_table_map = defaultdict(list)
    for dt in data_tables:
        data_table_map[dt.group_id].append(dt)

    # Fetch all ExperimentDataRows for these DataTables
    data_table_ids = [dt.id for dt in data_tables]
    experiment_rows = ExperimentDataRow.query.filter(
        ExperimentDataRow.data_table_id.in_(data_table_ids)
    ).all()

    # Map experiment rows to their data tables
    experiment_row_map = defaultdict(dict)
    for er in experiment_rows:
        experiment_row_map[er.data_table_id][er.row_index] = er

    for group_id_str, animal_indices in ref_range.included_animals.items():
        group = group_map.get(group_id_str)
        if not group: continue

        # STRICT SORTING: Must match the index stored in JSON
        # Ideally we would store Animal IDs, but for legacy compat we strictly sort by PK
        animals = sorted(group.animals, key=lambda a: a.id)
        
        for animal_idx in animal_indices:
            if animal_idx >= len(animals): continue # Safety check
            
            animal_obj = animals[animal_idx]
            animal_info = animal_obj.to_dict()
            
            # Base row with animal and group/project info
            base_row = {
                'Reference Range Name': ref_range.name,
                'Reference Range Description': ref_range.description,
                'Animal ID': animal_info.get('uid') or animal_info.get('ID', f'Index {animal_idx}'),
                'Group Name': group.name,
                'Project Name': group.project.name if group.project else 'N/A',
                'Animal Model': group.model.name if group.model else 'N/A',
            }
            
            # Add all animal model fields
            if group.model and group.model.analytes:
                for field_def in group.model.analytes:
                    field_name = field_def.name
                    base_row[f'Animal_{field_name}'] = animal_info.get(field_name)

            # Collect all data tables for this group that match the reference range's protocol
            relevant_data_tables = data_table_map.get(group.id, [])

            if not relevant_data_tables:
                # If no relevant data tables, still add the animal's base info
                all_data_rows.append(base_row)
                continue

            for data_table in relevant_data_tables:
                # Add protocol model fields
                protocol_info = {
                    'Protocol Name': data_table.protocol.name if data_table.protocol else 'N/A',
                    'Protocol Severity': data_table.protocol.severity.value if data_table.protocol and data_table.protocol.severity else 'N/A',
                    'Data Table Date': data_table.date,
                }
                if data_table.protocol and data_table.protocol.analytes:
                    for field_def in data_table.protocol.analytes:
                        field_name = field_def.name
                        # Protocol fields are usually descriptive, not result-oriented, so no direct mapping to results here
                        # If there were protocol-specific results, they would be handled differently.
                        pass

                # Find the experiment row corresponding to this animal index
                animal_data_row = experiment_row_map.get(data_table.id, {}).get(animal_idx)

                if animal_data_row and animal_data_row.row_data:
                    combined_row = {**base_row, **protocol_info}
                    # Add all experiment data row fields (results)
                    for key, value in animal_data_row.row_data.items():
                        combined_row[f'Result_{key}'] = value
                    all_data_rows.append(combined_row)
                else:
                    # If no specific experiment data row for this animal, still add base + protocol info
                    all_data_rows.append({**base_row, **protocol_info})

    if not all_data_rows:
        flash(_l("No data found for the included animals in this Reference Range."), "info")
        return redirect(url_for('reference_ranges.create_edit_reference_range', range_id=range_id))

    df = pd.DataFrame(all_data_rows)

    # Reorder columns to put key identifiers first
    desired_order = [
        'Reference Range Name',
        'Animal ID',
        'Group Name',
        'Project Name',
        'Animal Model',
        'Protocol Name',
        'Data Table Date',
        'Reference Range Description',
        'Protocol Severity',
    ]
    # Add any other columns that are in the DataFrame but not in desired_order
    existing_cols = df.columns.tolist()
    final_columns = [col for col in desired_order if col in existing_cols]
    final_columns.extend([col for col in existing_cols if col not in final_columns])
    df = df[final_columns]

    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='ReferenceRangeData')
    writer.close()
    output.seek(0)

    filename = f"reference_range_data_{ref_range.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@reference_ranges_bp.route('/delete/<int:range_id>', methods=['POST'])
@login_required
def delete_reference_range(range_id):
    if not user_has_permission(current_user, 'ReferenceRange', 'delete', allow_any_team=True):
        flash(_l("You do not have permission to delete Reference Ranges."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))

    ref_range = db.session.get(ReferenceRange, range_id)
    if not ref_range:
        flash(_l("Reference Range not found."), "danger")
        return redirect(url_for('reference_ranges.list_reference_ranges'))

    try:
        db.session.delete(ref_range)
        db.session.commit()
        flash(_l('Reference Range deleted successfully!'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting reference range {range_id}: {e}", exc_info=True)
        flash(_l('Error deleting Reference Range.'), 'danger')

    return redirect(url_for('reference_ranges.list_reference_ranges'))

@reference_ranges_bp.route('/api/get_reference_search_filters')
@login_required
def get_reference_search_filters():
    protocol_id = request.args.get('protocol_id', type=int)
    model_id = request.args.get('model_id', type=int)

    if not protocol_id:
        return jsonify({'error': 'A protocol must be selected.'}), 400

    # Base query for groups linked to the protocol
    base_query = ExperimentalGroup.query.join(
        DataTable, ExperimentalGroup.id == DataTable.group_id
    ).filter(DataTable.protocol_id == protocol_id)

    # If no model_id is provided, return available animal models
    if not model_id:
        groups = base_query.distinct().all()
        unique_models = {group.model for group in groups if group.model}
        models_data = [{'id': model.id, 'name': model.name} for model in sorted(unique_models, key=lambda m: m.name)]
        return jsonify({'animal_models': models_data})

    # If model_id is provided, return parameters for that model within the protocol
    query = base_query.filter(ExperimentalGroup.model_id == model_id).distinct()
    groups = query.all()
    
    parameters = defaultdict(set)
    animal_model = db.session.get(AnimalModel, model_id)
    if not animal_model:
        return jsonify({'parameters': {}})

    animal_field_names = [field.name for field in animal_model.analytes]
    for group in groups:
        animals = sorted(group.animals, key=lambda a: a.id)
        for animal_obj in animals:
            animal = animal_obj.to_dict()
            for key, value in animal.items():
                if key in animal_field_names and value is not None and str(value).strip() != '':
                    parameters[key].add(str(value))

    parameters_sorted = {k: sorted(list(v)) for k, v in parameters.items()}
    return jsonify({'parameters': parameters_sorted})


@reference_ranges_bp.route('/api/search_animals_for_reference')
@login_required
def search_animals_for_reference():
    protocol_id = request.args.get('protocol_id', type=int)
    model_id = request.args.get('model_id', type=int)
    filters_json = request.args.get('filters', '{}')
    
    if not protocol_id:
        return jsonify({'error': 'A protocol must be selected.'}), 400

    try:
        import json
        filters = json.loads(filters_json)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid filters format.'}), 400

    query = ExperimentalGroup.query.join(
        DataTable, ExperimentalGroup.id == DataTable.group_id
    ).filter(DataTable.protocol_id == protocol_id).distinct()
    
    if model_id:
        query = query.filter(ExperimentalGroup.model_id == model_id)
    
    groups = query.all()
    
    results = []
    dynamic_columns = set()

    for group in groups:
        animals = sorted(group.animals, key=lambda a: a.id)
        for i, animal_obj in enumerate(animals):
            animal = animal_obj.to_dict()
            match = all(str(animal.get(key)) == value for key, value in filters.items() if value)
            
            if match:
                animal_data = {
                    'group_id': group.id,
                    'group_name': group.name,
                    'project_name': group.project.name,
                    'animal_index': i,
                    'Animal ID': animal.get('uid') or animal.get('ID', f"Index {i}")
                }
                
                # Add dynamic parameters and collect column names
                for key, value in animal.items():
                    if key != 'ID':
                        animal_data[key] = value
                        dynamic_columns.add(key)

                results.append(animal_data)

    # Prepare final response
    base_columns = ['Animal ID', 'group_name', 'project_name']
    final_columns = base_columns + sorted(list(dynamic_columns))
    
    return jsonify({
        'columns': final_columns,
        'data': results
    })

@reference_ranges_bp.route('/api/search_analytes')
@login_required
def search_analytes():
    search_term = request.args.get('q', '').strip()
    if not search_term:
        return jsonify([]) # Return an empty array if no search term

    query = Analyte.query.filter(
        (Analyte.name.ilike(f'%{search_term}%')) |
        (Analyte.description.ilike(f'%{search_term}%'))
    ).order_by(Analyte.name).limit(50)
    
    analytes = [{
        'id': a.id, 
        'name': a.name, # Keep 'name' for edit_model.html
        'text': a.name, # Add 'text' for Select2 compatibility in create_edit_reference_range.html
        'description': a.description,
        'unit': a.unit,
        'data_type': a.data_type.name,
        'allowed_values': a.allowed_values
    } for a in query.all()]
    
    if request.args.get('for_core_model_editor'):
        return jsonify(analytes)
    else:
        return jsonify({'items': analytes}) # Wrap in 'items' key for Select2

@reference_ranges_bp.route('/api/get_protocols_for_analyte')
@login_required
def get_protocols_for_analyte():
    analyte_id = request.args.get('analyte_id', type=int)
    if not analyte_id:
        return jsonify({'error': 'An analyte must be selected.'}), 400

    analyte = db.session.get(Analyte, analyte_id)
    if not analyte:
        return jsonify({'error': 'Analyte not found.'}), 404

    protocols = ProtocolModel.query.join(ProtocolModel.analytes).filter(Analyte.id == analyte_id).order_by(ProtocolModel.name).all()
    
    protocols_data = [{'id': p.id, 'name': p.name} for p in protocols]
    return jsonify({'protocols': protocols_data})

@reference_ranges_bp.route('/api/reference_ranges_stats')
@login_required
def reference_ranges_stats():
    # Get global stats and data for charts
    ranges = ReferenceRange.query.order_by(ReferenceRange.name).all()

    total_ranges = len(ranges)
    total_animals = 0
    all_values = []
    timeline_data = []

    for r in ranges:
        if not r.included_animals:
            continue
        group_ids = list(r.included_animals.keys())
        if not group_ids:
            continue

        groups = ExperimentalGroup.query.filter(ExperimentalGroup.id.in_(group_ids)).options(
            db.joinedload(ExperimentalGroup.model),
            db.joinedload(ExperimentalGroup.project)
        ).all()

        for group in groups:
            num_animals = len(r.included_animals.get(str(group.id), []))
            total_animals += num_animals

            # Get data tables
            data_tables = DataTable.query.filter(
                DataTable.group_id == group.id,
                DataTable.protocol_id == r.protocol_id
            ).options(db.joinedload(DataTable.protocol)).all()

            for dt in data_tables:
                experiment_rows = ExperimentDataRow.query.filter(
                    ExperimentDataRow.data_table_id == dt.id
                ).all()

                for er in experiment_rows:
                    if er.row_index in r.included_animals.get(str(group.id), []):
                        if er.row_data and r.analyte:
                            result_key = f'Result_{r.analyte.name}'
                            value = er.row_data.get(r.analyte.name)
                            if value is not None:
                                try:
                                    val = float(value)
                                    all_values.append(val)
                                    if dt.date:
                                        timeline_data.append({'date': dt.date, 'value': val, 'range_name': r.name})
                                except ValueError:
                                    pass

    stats = {
        'total_ranges': total_ranges,
        'total_animals': total_animals,
        'min_value': min(all_values) if all_values else None,
        'max_value': max(all_values) if all_values else None,
        'avg_value': sum(all_values) / len(all_values) if all_values else None,
        'count_values': len(all_values)
    }

    return jsonify({
        'stats': stats,
        'timeline_data': timeline_data,
        'scatter_data': [{'x': i, 'y': v} for i, v in enumerate(all_values)]  # simple scatter
    })


@reference_ranges_bp.route('/api/reference_range/<int:range_id>/data')
@login_required
def reference_range_data(range_id):
    ref_range = db.session.get(ReferenceRange, range_id)
    if not ref_range or not can_view_reference_range(range_id):
        return jsonify({'error': 'Not found'}), 404

    all_values = []
    timeline_data = []
    scatter_data = []

    if ref_range.included_animals:
        group_ids = list(ref_range.included_animals.keys())
        groups = ExperimentalGroup.query.filter(ExperimentalGroup.id.in_(group_ids)).options(
            db.joinedload(ExperimentalGroup.model),
            db.joinedload(ExperimentalGroup.project)
        ).all()

        for group in groups:
            data_tables = DataTable.query.filter(
                DataTable.group_id == group.id,
                DataTable.protocol_id == ref_range.protocol_id
            ).options(db.joinedload(DataTable.protocol)).all()

            for dt in data_tables:
                experiment_rows = ExperimentDataRow.query.filter(
                    ExperimentDataRow.data_table_id == dt.id
                ).all()

                for er in experiment_rows:
                    if er.row_index in ref_range.included_animals.get(str(group.id), []):
                        if er.row_data and ref_range.analyte:
                            value = er.row_data.get(ref_range.analyte.name)
                            if value is not None:
                                try:
                                    val = float(value)
                                    all_values.append(val)
                                    
                                    # Get animal ID if available
                                    animal_id = 'Unknown'
                                    animals = sorted(group.animals, key=lambda a: a.id)
                                    if animals and er.row_index < len(animals):
                                        animal_id = animals[er.row_index].uid or f"Index {er.row_index}"
                                    
                                    if dt.date:
                                        timeline_data.append({'date': dt.date, 'value': val})
                                    scatter_data.append({
                                        'x': len(scatter_data), 
                                        'y': val,
                                        'group': group.name,
                                        'animal_id': animal_id
                                    })
                                except ValueError:
                                    pass

    return jsonify({
        'timeline_data': timeline_data,
        'scatter_data': scatter_data
    })


@reference_ranges_bp.route('/api/datatable/<int:datatable_id>/available_reference_ranges')
@login_required
def available_reference_ranges(datatable_id):
    datatable = db.session.get(DataTable, datatable_id)
    if not datatable:
        return jsonify({"error": "Datatable not found"}), 404

    if not check_datatable_permission(datatable, 'read'):
        return jsonify({"error": "Permission denied"}), 403

    # Get analytes from both Protocol and Animal Model
    protocol_analytes = [analyte.id for analyte in datatable.protocol.analytes]
    model_analytes = []
    if datatable.group and datatable.group.model:
        model_analytes = [analyte.id for analyte in datatable.group.model.analytes]
    
    all_relevant_analyte_ids = list(set(protocol_analytes + model_analytes))
    
    # Logic to get ONLY accessible reference ranges:
    # 1. Owned by current user
    # 2. In teams the user belongs to
    # 3. Shared with teams the user belongs to
    # 4. Globally shared
    
    user_team_ids = [t.id for t in current_user.get_teams()]
    
    from sqlalchemy import or_
    # Try filtering by Protocol first as it's the safest bet
    # Also include ALL ranges if the user is super admin for debugging
    if current_user.is_super_admin:
        query = db.session.query(ReferenceRange).filter(
            or_(
                ReferenceRange.protocol_id == datatable.protocol_id,
                ReferenceRange.analyte_id.in_(all_relevant_analyte_ids)
            )
        )
    else:
        query = db.session.query(ReferenceRange).filter(
            or_(
                ReferenceRange.analyte_id.in_(all_relevant_analyte_ids),
                ReferenceRange.protocol_id == datatable.protocol_id
            )
        ).filter(
            or_(
                ReferenceRange.owner_id == int(current_user.id),
                ReferenceRange.team_id.in_(user_team_ids),
                ReferenceRange.is_globally_shared == True,
                ReferenceRange.shared_with_teams.any(Team.id.in_(user_team_ids))
            )
        )
    
    query = query.distinct()
    
    ranges = query.all()
    
    # Priority sorting: if protocol matches, put first
    ranges.sort(key=lambda r: (r.protocol_id != datatable.protocol_id, r.name))
    
    return jsonify([r.to_dict() for r in ranges])
