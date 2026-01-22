# app/sampling/routes.py
import json
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

import pandas as pd
from flask import (current_app, flash, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from flask_babel import lazy_gettext as _l
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import (AnimalModel, Anticoagulant, DerivedSampleType,
                        ExperimentalGroup, Organ, Project, Sample,
                        SampleStatus, SampleType, Staining, Storage, Team,
                        TissueCondition)
from app.sampling import sampling_bp
from app.services.sampling_service import SamplingService

from ..helpers import generate_display_id
from ..permissions import check_group_permission
from .forms import BatchCommonSampleDetailsForm, SingleSampleForm

sampling_service = SamplingService()

@sampling_bp.route('/get_storage_locations', methods=['GET'])
@login_required
def get_storage_locations():
    user = current_user
    try:
        if user.is_super_admin:
            storages = Storage.query.order_by(Storage.name).all()
        else:
            user_team_ids = [team.id for team in user.get_teams()]
            if not user_team_ids:
                return jsonify({'success': True, 'storage_locations': []})
            storages = Storage.query.filter(Storage.team_id.in_(user_team_ids)).order_by(Storage.name).all()

        storage_list = [{'id': s.id, 'name': s.name, 'location_details': s.location_details} for s in storages]
        return jsonify({'success': True, 'storage_locations': storage_list})
    except Exception as e:
        current_app.logger.error(f"Error fetching storage locations for UI: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Could not retrieve storage locations.'}), 500


@sampling_bp.route('/group/<string:group_id>/samples', methods=['GET'])
@login_required
def list_group_samples(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        flash(_l("Experimental Group not found."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'read'):
        flash(_l("You do not have permission to view samples for this group."), "danger")
        return redirect(url_for('groups.manage_groups'))

    # This view now uses Server-Side DataTable via API, so we just render the template
    # We pass necessary enums/lists for filters if needed in the template
    
    return render_template(
        'sampling/list_group_samples.html',
        title=_l("Samples for Group: %(group_name)s", group_name=group.name),
        group=group,
        SampleType=SampleType,
        SampleStatus=SampleStatus,
        organs=Organ.query.order_by(Organ.name).all(),
        stainings=Staining.query.order_by(Staining.name).all(),
        anticoagulants=Anticoagulant.query.order_by(Anticoagulant.name).all(),
        derived_types=DerivedSampleType.query.order_by(DerivedSampleType.name).all(),
        tissue_conditions=TissueCondition.query.order_by(TissueCondition.name).all()
    )

@sampling_bp.route('/group/<string:group_id>/log_batch', methods=['GET', 'POST'])
@login_required
def log_batch_samples_for_group(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        flash(_l("Experimental Group not found."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'edit_exp_group'):
        flash(_l("You do not have permission to log samples for this group."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if group.is_archived:
        flash(_l("Cannot log samples for an archived group."), "warning")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': _l("Invalid JSON data received.")}), 400

        common_details = data.get('common_details', {})
        sample_set = data.get('sample_set', [])
        animal_indices = data.get('animal_indices', [])

        if not all([common_details, sample_set, animal_indices]):
            return jsonify({'success': False, 'message': _l("Missing data for sample creation.")}), 400

        # Use Service
        samples_created_count, batch_errors = sampling_service.log_batch_samples(
            group, common_details, sample_set, animal_indices
        )

        if not batch_errors:
            flash(_l("%(count)s sample(s) created for %(num_animals)s animal(s) in group '%(group_name)s'.", 
                     count=samples_created_count, num_animals=len(animal_indices), group_name=group.name), "success")
            return jsonify({'success': True, 'redirect_url': url_for('sampling.list_group_samples', group_id=group.id)})
        else:
            return jsonify({'success': False, 'message': _l("Errors occurred during sample creation."), 'errors': batch_errors}), 400

    # GET request logic
    common_details_form = BatchCommonSampleDetailsForm(team_id=group.team_id, prefix="common_")
    animal_model_field_names = [f.name for f in group.model.analytes] if group.model and group.model.analytes else []

    storage_locations = Storage.query.filter_by(team_id=group.team_id).order_by(Storage.name).all()
    storage_locations_json = [{'id': s.id, 'text': f"{s.name} ({s.location_details or _l('No details')})"} for s in storage_locations]
    
    organ_choices_json = [(o.id, o.name) for o in Organ.query.order_by(Organ.name).all()]
    tissue_condition_choices_json = [(c.id, c.name) for c in TissueCondition.query.order_by(TissueCondition.name).all()]
    sample_type_enum_json = {k: v.value for k, v in SampleType.__members__.items()}
    anticoagulant_choices_json = [(a.id, a.name) for a in Anticoagulant.query.order_by(Anticoagulant.name).all()]

    return render_template(
        'sampling/log_batch_samples.html',
        title=_l("Log Batch Samples for Group: %(group_name)s", group_name=group.name),
        group=group,
        common_details_form=common_details_form,
        animal_model_field_names=animal_model_field_names,
        storage_locations_json=json.dumps(storage_locations_json),
        organ_choices_json=json.dumps(organ_choices_json),
        tissue_condition_choices_json=json.dumps(tissue_condition_choices_json),
        sample_type_enum_json=json.dumps(sample_type_enum_json),
        anticoagulant_choices_json=json.dumps(anticoagulant_choices_json),
        today_date=date.today().isoformat()
    )

@sampling_bp.route('/api/group/<string:group_id>/available_animals', methods=['GET'])
@login_required
def get_available_animals(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        return jsonify({'success': False, 'message': 'Group not found'}), 404

    if not check_group_permission(group, 'read'):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    collection_date_str = request.args.get('date')
    if not collection_date_str:
        return jsonify({'success': False, 'message': 'Date parameter is required'}), 400

    try:
        collection_date = datetime.strptime(collection_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format. Use YYYY-MM-DD.'}), 400

    available_animals = []
    if group.animal_data:
        for idx, animal_info in enumerate(group.animal_data):
            death_date_str = animal_info.get('death_date')
            if death_date_str:
                try:
                    death_date = datetime.strptime(death_date_str, '%Y-%m-%d').date()
                    if death_date < collection_date:
                        continue
                except (ValueError, TypeError):
                    pass

            animal_display_info = {'index': idx}
            animal_model_field_names = []
            if group.model and group.model.analytes:
                 animal_model_field_names = [f.name for f in group.model.analytes]

            for field_name in animal_model_field_names:
                animal_display_info[field_name] = animal_info.get(field_name, _l('N/A'))
            if 'ID' not in animal_display_info:
                 animal_display_info['ID'] = animal_info.get('ID', f"Index {idx}")

            available_animals.append(animal_display_info)

    return jsonify({'success': True, 'animals': available_animals})

@sampling_bp.route('/api/samples_server_side', methods=['GET'])
@login_required
def samples_server_side():
    """
    Server-side processing for DataTables.js.
    """
    # 1. Parse DataTables Request Parameters
    draw = request.args.get('draw', type=int)
    start = request.args.get('start', type=int, default=0)
    length = request.args.get('length', type=int, default=10)
    search_value = request.args.get('search[value]', '').lower()
    order_column_index = request.args.get('order[0][column]', type=int)
    order_dir = request.args.get('order[0][dir]', 'asc')
    
    # 2. Custom Filters
    project_slug_filter = request.args.get('project_slug', '')
    group_id_filter = request.args.get('group_id', '')
    status_filter = request.args.get('status_filter', '')
    
    # --- NEW FILTERS ---
    sample_type_filter = request.args.get('sample_type', '')
    organ_id_filter = request.args.get('organ_id', type=int)
    storage_id_filter = request.args.get('storage_id', type=int)
    
    # Handle list filters
    condition_id_filter = request.args.getlist('condition_id[]') or request.args.getlist('condition_id') 
    staining_id_filter = request.args.getlist('staining_id[]') or request.args.getlist('staining_id')
    anticoagulant_id_filter = request.args.getlist('anticoagulant_id[]') or request.args.getlist('anticoagulant_id')
    derived_type_id_filter = request.args.getlist('derived_type_id[]') or request.args.getlist('derived_type_id')

    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # Archive Filter
    show_archived = request.args.get('show_archived') == 'true'

    # 3. Base Query
    query = Sample.query.join(ExperimentalGroup).join(Project)
    
    if not current_user.is_super_admin:
        user_teams = current_user.get_teams()
        user_team_ids = [t.id for t in user_teams] if user_teams else []
        query = query.filter(Project.team_id.in_(user_team_ids))

    # 4. Apply Filters
    
    # Archive Logic: If NOT showing archived, filter out archived parents
    if not show_archived:
        query = query.filter(
            ExperimentalGroup.is_archived == False,
            Project.is_archived == False
        )

    if group_id_filter:
        query = query.filter(ExperimentalGroup.id == group_id_filter)
    elif project_slug_filter:
        query = query.filter(Project.slug == project_slug_filter)
        
    if status_filter and status_filter != 'all':
        statuses = status_filter.split(',')
        status_enums = []
        for s in statuses:
            try: status_enums.append(SampleStatus[s])
            except KeyError: pass
        if status_enums: query = query.filter(Sample.status.in_(status_enums))

    if sample_type_filter:
        try:
            query = query.filter(Sample.sample_type == SampleType[sample_type_filter])
        except KeyError: pass

    if organ_id_filter:
        query = query.filter(Sample.organ_id == organ_id_filter)

    if storage_id_filter:
        query = query.filter(Sample.storage_id == storage_id_filter)

    if condition_id_filter:
        # Filter for samples that have ANY of the selected conditions
        try:
             # Clean up and ensure ints
            cond_ids = [int(cid) for cid in condition_id_filter if cid]
            if cond_ids:
                query = query.filter(Sample.collection_conditions.any(TissueCondition.id.in_(cond_ids)))
        except ValueError: pass

    if staining_id_filter:
        try:
            s_ids = [int(sid) for sid in staining_id_filter if sid]
            if s_ids:
                query = query.filter(Sample.staining_id.in_(s_ids))
        except ValueError: pass
        
    if anticoagulant_id_filter:
        try:
            ac_ids = [int(aid) for aid in anticoagulant_id_filter if aid]
            if ac_ids:
                query = query.filter(Sample.anticoagulant_id.in_(ac_ids))
        except ValueError: pass
        
    if derived_type_id_filter:
        try:
            dt_ids = [int(dtid) for dtid in derived_type_id_filter if dtid]
            if dt_ids:
                query = query.filter(Sample.derived_type_id.in_(dt_ids))
        except ValueError: pass

    if date_from:
        try:
            d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(Sample.collection_date >= d_from)
        except ValueError: pass

    if date_to:
        try:
            d_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(Sample.collection_date <= d_to)
        except ValueError: pass

    # Global Search
    if search_value:
        search_pattern = f"%{search_value}%"
        query = query.filter(or_(
            Sample.display_id.ilike(search_pattern),
            func.cast(Sample.id, db.String).ilike(search_pattern),
            ExperimentalGroup.name.ilike(search_pattern),
            Project.name.ilike(search_pattern),
            Sample.notes.ilike(search_pattern)
        ))

    # Counts
    total_records = Sample.query.count() 
    filtered_records = query.count()

    # Sorting
    sort_column = None
    if order_column_index == 1: sort_column = Sample.display_id
    elif order_column_index == 3: sort_column = Sample.sample_type
    elif order_column_index == 5: sort_column = Sample.collection_date
    elif order_column_index == 6: sort_column = Sample.is_terminal
    elif order_column_index == 8: sort_column = Sample.status
    
    if sort_column:
        if order_dir == 'desc': query = query.order_by(sort_column.desc())
        else: query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(Sample.collection_date.desc(), Sample.id.desc())

    # Pagination
    samples = query.offset(start).limit(length).all()

    # Format Data
    data = []
    for s in samples:
        animal_id_display = "N/A"
        if s.experimental_group and s.experimental_group.animal_data:
            try:
                animal_info = s.experimental_group.animal_data[s.animal_index_in_group]
                animal_id_display = animal_info.get('ID', f"Index {s.animal_index_in_group}")
            except (IndexError, TypeError): pass

        edit_url = url_for('sampling.view_edit_sample', sample_id=s.id)
        actions_html = f'<a href="{edit_url}" class="btn btn-sm btn-primary" title="{_("Edit")}"><i class="fas fa-edit"></i></a>'

        organs_display = ""
        if s.sample_type == SampleType.BIOLOGICAL_TISSUE:
            organs_display = f'<span class="badge bg-info text-dark">{s.organ.name if s.organ else "N/A"}</span>'
            if s.collection_conditions:
                conds = ", ".join([c.name for c in s.collection_conditions])
                organs_display += f'<br><small class="text-muted">({conds})</small>'
        
        type_display = s.sample_type.value
        if s.parent_sample_id:
            type_display = f'<span class="badge bg-secondary me-1">{_("Derived")}</span> {type_display}'

        row = {
            "0": f'<input type="checkbox" class="sample-select-checkbox" value="{s.id}" data-group-id="{s.experimental_group_id}">',
            "1": s.display_id or str(s.id),
            "2": animal_id_display,
            "3": type_display,
            "4": organs_display,
            "5": s.collection_date.strftime('%Y-%m-%d') if s.collection_date else '',
            "6": '<span class="badge bg-danger">Yes</span>' if s.is_terminal else '<span class="badge bg-success">No</span>',
            "7": s.storage_location.name if s.storage_location else _('N/A'),
            "8": f'<span class="badge bg-secondary">{s.status.value}</span>',
            "9": s.notes or '',
            "10": actions_html,
            "DT_RowId": f"row_{s.id}",
            "DT_RowData": { 
                "status": s.status.name,
                "group_id": s.experimental_group_id
            }
        }
        data.append(row)

    return jsonify({
        "draw": draw,
        "recordsTotal": total_records,
        "recordsFiltered": filtered_records,
        "data": data
    })

@sampling_bp.route('/explorer', methods=['GET']) # Renamed for clarity, but keeps old route below
@sampling_bp.route('/all_samples', methods=['GET'])
@login_required
def all_samples_list():
    storage_id = request.args.get('storage_id', type=int)
    storage = None

    # 1. Fetch Sidebar Data (Hierarchy)
    from app.services.project_service import ProjectService
    project_service = ProjectService()
    sidebar_data = project_service.get_sidebar_hierarchy(current_user)
    
    # 2. Apply Storage Context Filter (if applicable)
    if storage_id:
        storage = db.session.get(Storage, storage_id)
        if not storage:
            flash(_l("Storage not found."), "danger")
            return redirect(url_for('sampling.all_samples_list'))
        
        # If viewing a specific storage, we might want to filter the sidebar 
        # to only show projects relevant to this storage. 
        # However, for consistency, showing the full hierarchy is often better UX,
        # as the main table will filter by storage anyway.
        # If strict filtering is needed, you would filter `sidebar_data` here.

    # 3. Fetch Filter Options for Dropdowns
    storage_query = Storage.query
    if not current_user.is_super_admin:
        user_teams = current_user.get_teams()
        team_ids = [t.id for t in user_teams]
        storage_query = storage_query.filter(Storage.team_id.in_(team_ids))
    
    storages = storage_query.order_by(Storage.name).all()
    organs = Organ.query.order_by(Organ.name).all()
    conditions = TissueCondition.query.order_by(TissueCondition.name).all()

    return render_template(
        'sampling/all_samples_list.html', 
        title=_l("Storage Explorer") if storage else _l("Sample Explorer"),
        sidebar_data=sidebar_data, # Pass the hierarchy
        storage=storage,
        SampleStatus=SampleStatus,
        SampleType=SampleType,
        organs=organs,
        conditions=conditions,
        storages=storages,
        stainings=Staining.query.order_by(Staining.name).all(),
        anticoagulants=Anticoagulant.query.order_by(Anticoagulant.name).all(),
        derived_types=DerivedSampleType.query.order_by(DerivedSampleType.name).all()
    )

@sampling_bp.route('/sample/<int:sample_id>/edit', methods=['GET', 'POST'])
@login_required
def view_edit_sample(sample_id):
    sample = db.session.query(Sample).options(
        db.joinedload(Sample.collection_conditions)
    ).get(sample_id)
    if not sample:
        flash(_l("Sample not found."), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))

    group = sample.experimental_group
    if not check_group_permission(group, 'edit_exp_group'):
        flash(_l("You do not have permission to edit samples for this group."), "danger")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    form = SingleSampleForm(team_id=group.team_id)
    
    # Pre-populate disabled field before validation to prevent "Not a valid choice" error
    # Disabled fields don't submit values, so we need to set it from the sample object
    if request.method == 'POST':
        form.sample_type.data = sample.sample_type.name

    if form.validate_on_submit():
        # Check tissue-specific validation
        is_form_valid = True
        if sample.sample_type == SampleType.BIOLOGICAL_TISSUE and not form.organ_id.data:
            form.organ_id.errors.append(_l('An organ must be selected for biological tissue.'))
            is_form_valid = False

        if is_form_valid:
            try:
                sample.collection_date = form.collection_date.data
                sample.is_terminal = form.is_terminal.data
                sample.status = form.status.data
                sample.storage_id = form.storage_id.data
                sample.notes = form.notes.data

                today_str = date.today().isoformat()
                original_notes = form.notes.data or ''

                if form.status.data == SampleStatus.SHIPPED:
                    sample.shipment_date = date.today()
                    sample.destruction_date = None
                    destination = form.shipment_destination.data
                    if destination:
                        note_update = str(_l("Shipped to %(dest)s on %(date)s.", dest=destination, date=today_str))
                        sample.notes = f"{original_notes}\n{note_update}".strip()
                elif form.status.data == SampleStatus.DESTROYED:
                    sample.destruction_date = date.today()
                    sample.shipment_date = None
                    note_update = str(_l("Destroyed on %(date)s.", date=today_str))
                    sample.notes = f"{original_notes}\n{note_update}".strip()
                else:
                    sample.shipment_date = None
                    sample.destruction_date = None
                    sample.notes = original_notes

                if sample.sample_type == SampleType.BLOOD:
                    sample.anticoagulant = form.anticoagulant.data
                    sample.volume = form.volume.data
                    sample.volume_unit = form.volume_unit.data
                elif sample.sample_type == SampleType.URINE:
                    sample.volume = form.volume.data
                    sample.volume_unit = form.volume_unit.data
                elif sample.sample_type == SampleType.BIOLOGICAL_TISSUE:
                    sample.organ_id = form.organ_id.data.id
                    sample.piece_id = form.piece_id.data
                    condition_ids = form.collection_conditions.data
                    sample.collection_conditions = TissueCondition.query.filter(TissueCondition.id.in_(condition_ids)).all() if condition_ids else []
                    if sample.derived_type:
                        staining_id = request.form.get('staining_id')
                        if staining_id: sample.staining_id = int(staining_id)
                elif sample.sample_type == SampleType.OTHER:
                    sample.notes = form.other_description.data

                db.session.commit()
                flash(_l("Sample ID %(id)s updated successfully.", id=sample.id), "success")
                return redirect(url_for('sampling.list_group_samples', group_id=group.id))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating sample {sample.id}: {e}", exc_info=True)
                flash(_l("Error updating sample: %(error)s", error=str(e)), "danger")
        else:
            current_app.logger.warning(f"Form validation failed for sample {sample.id}. Errors: {form.errors}")
    
    if request.method == 'GET':
        form.sample_type.data = sample.sample_type.name
        form.collection_date.data = sample.collection_date
        form.is_terminal.data = sample.is_terminal
        form.status.data = sample.status
        form.storage_id.data = sample.storage_id
        form.notes.data = sample.notes
        
        if sample.sample_type == SampleType.BLOOD:
            form.anticoagulant.data = sample.anticoagulant
            form.volume.data = sample.volume
            form.volume_unit.data = sample.volume_unit
        elif sample.sample_type == SampleType.URINE:
            form.volume.data = sample.volume
            form.volume_unit.data = sample.volume_unit
        elif sample.sample_type == SampleType.BIOLOGICAL_TISSUE:
            form.organ_id.data = sample.organ
            form.piece_id.data = sample.piece_id
            form.collection_conditions.data = [c.id for c in sample.collection_conditions]
            if sample.derived_type and sample.staining:
                form.staining_id.data = sample.staining_id
        elif sample.sample_type == SampleType.OTHER:
            form.other_description.data = sample.notes

    animal_id_display = "N/A"
    if group.animal_data and 0 <= sample.animal_index_in_group < len(group.animal_data):
        animal_id_display = group.animal_data[sample.animal_index_in_group].get('ID', f"Index {sample.animal_index_in_group}")

    derived_samples = sample.derived_samples.order_by(Sample.collection_date.desc()).all()

    parent_sample = None
    if sample.parent_sample_id:
        parent_sample = db.session.query(Sample).options(
            db.joinedload(Sample.collection_conditions)
        ).get(sample.parent_sample_id)

    return render_template(
        'sampling/view_edit_sample.html',
        title=_l("Edit Sample ID: %(id)s", id=sample.id),
        form=form,
        sample=sample,
        group=group,
        animal_id_display=animal_id_display,
        derived_samples=derived_samples,
        parent_sample=parent_sample
    )

@sampling_bp.route('/sample/<int:sample_id>/delete', methods=['POST'])
@login_required
def delete_sample(sample_id):
    sample = db.session.get(Sample, sample_id)
    if not sample:
        flash(_l("Sample not found."), "danger")
        return redirect(request.referrer or url_for('groups.manage_groups'))

    group = sample.experimental_group
    if not check_group_permission(group, 'edit_exp_group'):
        flash(_l("You do not have permission to delete samples for this group."), "danger")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    try:
        db.session.delete(sample)
        db.session.commit()
        flash(_l("Sample ID %(id)s deleted successfully.", id=sample_id), "success")
    except Exception as e:
        db.session.rollback()
        flash(_l("Error deleting sample: %(error)s", error=str(e)), "danger")
        current_app.logger.error(f"Error deleting sample {sample_id}: {e}", exc_info=True)

    if request.referrer and 'all_samples' in request.referrer:
        return redirect(url_for('sampling.all_samples_list'))
    return redirect(url_for('sampling.list_group_samples', group_id=group.id))

@sampling_bp.route('/generate_sample_list', methods=['GET'])
@login_required
def generate_sample_list_page():
    sample_ids_str = request.args.get('sample_ids', '')
    list_type = request.args.get('list_type', 'shipment')

    if not sample_ids_str:
        flash(_l("No samples selected."), "warning")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))

    try:
        sample_ids = [int(sid) for sid in sample_ids_str.split(',')]
    except ValueError:
        flash(_l("Invalid sample ID format."), "danger")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))

    samples_query = Sample.query.filter(Sample.id.in_(sample_ids)).options(
        db.joinedload(Sample.experimental_group).joinedload(ExperimentalGroup.project).joinedload(Project.team),
        db.joinedload(Sample.experimental_group).joinedload(ExperimentalGroup.model),
        db.joinedload(Sample.storage_location),
    ).order_by(Sample.experimental_group_id, Sample.animal_index_in_group, Sample.id)

    samples_to_list = samples_query.all()

    if not samples_to_list:
        flash(_l("Selected samples not found."), "warning")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))

    prepared_data = []
    for s in samples_to_list:
        project = s.experimental_group.project
        partner_company = _l('N/A')
        partner_email = _l('N/A')

        data_item = {
            'id': s.id,
            'animal_id': s.animal_display_id,
            'sample_type': str(s.sample_type.value),
            'collection_date': s.collection_date.strftime('%Y-%m-%d') if s.collection_date else '',
            'storage_location': s.storage_location.name if s.storage_location else _l('N/A'),
            'notes': s.notes,
            'anticoagulant': s.anticoagulant.name if s.anticoagulant else '',
            'volume': s.volume,
            'volume_unit': s.volume_unit,
            'project_name': project.name,
            'group_id': s.experimental_group_id,
            'group_name': s.experimental_group.name,
            'partner_company': partner_company,
            'partner_email': partner_email,
            'current_status': str(s.status.value),
        }
        prepared_data.append(data_item)

    page_title = _l("Shipment Manifest") if list_type == 'shipment' else _l("Discard List")
    action_button_text = _l("Confirm Shipment & Update Status") if list_type == 'shipment' else _l("Confirm Discard & Update Status")
    
    session['last_sample_list_url'] = request.referrer or url_for('sampling.all_samples_list')

    return render_template('sampling/sample_list_display.html',
                           samples_data=prepared_data,
                           title=page_title,
                           list_type=list_type,
                           sample_ids_csv=sample_ids_str,
                           action_button_text=action_button_text)
            
@sampling_bp.route('/download_sample_list_file', methods=['GET'])
@login_required
def download_sample_list_file():
    sample_ids_str = request.args.get('sample_ids', '')
    file_format = request.args.get('format', 'excel').lower()

    if not sample_ids_str:
        flash(_l("No sample IDs provided."), "danger")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))
    
    try:
        sample_ids = [int(sid) for sid in sample_ids_str.split(',')]
    except ValueError:
        flash(_l("Invalid sample ID format."), "danger")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))

    samples_query = Sample.query.filter(Sample.id.in_(sample_ids)).options(
        db.joinedload(Sample.experimental_group).joinedload(ExperimentalGroup.project),
        db.joinedload(Sample.storage_location),
        db.joinedload(Sample.organ),
        db.joinedload(Sample.collection_conditions)
    )
    samples_to_list = samples_query.all()
    if not samples_to_list:
        flash(_l("Samples not found."), "warning")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))

    data_for_df = []
    for s in samples_to_list:
        project = s.experimental_group.project
        animal_id_display = s.animal_display_id
        
        base_data = {
            'Sample ID': s.display_id or s.id,
            'Internal Sample ID': s.id,
            'Project': project.name,
            'Project Slug': project.slug,
            'Group': s.experimental_group.name,
            'Animal ID': animal_id_display,
            'Sample Type': str(s.sample_type.value),
            'Collection Date': s.collection_date.strftime('%Y-%m-%d') if s.collection_date else '',
            'Is Terminal': 'Yes' if s.is_terminal else 'No',
            'Volume': s.volume,
            'Unit': '' if s.sample_type == SampleType.BIOLOGICAL_TISSUE else s.volume_unit,
            'Anticoagulant': s.anticoagulant.name if s.anticoagulant else '',
            'Organ/Tissue Name': s.organ.name if s.organ else '',
            'Piece ID': s.piece_id,
            'Conditions': ", ".join([c.name for c in s.collection_conditions]) if s.collection_conditions else "",
            'Storage': s.storage_location.name if s.storage_location else '',
            'Notes': s.notes,
            'Status': str(s.status.value)
        }
        data_for_df.append(base_data)

    df = pd.DataFrame(data_for_df)
    
    column_order = [
        'Sample ID', 'Project', 'Group', 'Animal ID', 'Sample Type', 'Collection Date', 
        'Organ/Tissue Name', 'Piece ID', 'Conditions', 'Volume', 'Unit', 'Anticoagulant', 
        'Storage', 'Status', 'Is Terminal', 'Notes', 'Internal Sample ID', 'Project Slug'
    ]
    df = df.reindex(columns=[col for col in column_order if col in df.columns])

    output = BytesIO()
    filename = f"sample_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if file_format == 'excel':
        df.to_excel(output, index=False, sheet_name='Samples')
        mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        filename += ".xlsx"
    elif file_format == 'csv':
        df.to_csv(output, index=False, encoding='utf-8')
        mimetype = 'text/csv'
        filename += ".csv"
    else:
        flash(_l("Invalid file format requested."), "danger")
        return redirect(request.referrer or url_for('sampling.all_samples_list'))

    output.seek(0)
    return send_file(output, download_name=filename, as_attachment=True, mimetype=mimetype)


@sampling_bp.route('/update_samples_status', methods=['POST'])
@login_required
def update_samples_status_action():
    sample_ids_str = request.form.get('sample_ids', '')
    new_status_name = request.form.get('new_status_name', '')
    destination = request.form.get('destination') # For shipment

    if not sample_ids_str or not new_status_name:
        flash(_l("Missing required information to update status."), "danger")
        return redirect(session.get('last_sample_list_url', url_for('sampling.all_samples_list')))

    try:
        sample_ids = [int(sid) for sid in sample_ids_str.split(',')]
        new_status_enum = SampleStatus[new_status_name]
    except (ValueError, KeyError):
        flash(_l("Invalid data for status update."), "danger")
        return redirect(session.get('last_sample_list_url', url_for('sampling.all_samples_list')))

    # Filter samples by permission
    samples_to_update = []
    permission_errors = []
    
    for sample in Sample.query.filter(Sample.id.in_(sample_ids)).all():
        if not check_group_permission(sample.experimental_group, 'edit_exp_group'):
            permission_errors.append(_l("No permission to update sample ID %(id)s.", id=sample.id))
        else:
            samples_to_update.append(sample.id)

    if permission_errors:
        for error in permission_errors: flash(error, "warning")
        if not samples_to_update:
            return redirect(session.pop('last_sample_list_url', url_for('sampling.all_samples_list')))

    # Use Service
    try:
        updated_count = sampling_service.batch_update_status(samples_to_update, new_status_enum, destination)
        flash(_l("%(count)s sample(s) status updated to %(status)s.", count=updated_count, status=new_status_enum.value), "success")
    except Exception as e:
        flash(_l("Database error during status update: %(error)s", error=str(e)), "danger")
        current_app.logger.error(f"Error updating sample statuses: {e}", exc_info=True)

    return redirect(session.pop('last_sample_list_url', url_for('sampling.all_samples_list')))

@sampling_bp.route('/group/<string:group_id>/log_derived_samples', methods=['GET', 'POST'])
@login_required
def log_derived_samples(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        flash(_l("Experimental Group not found."), "danger")
        return redirect(url_for('groups.manage_groups'))

    if not check_group_permission(group, 'edit_exp_group'):
        flash(_l("You do not have permission to log samples for this group."), "danger")
        return redirect(url_for('groups.manage_groups'))
    
    if group.is_archived:
        flash(_l("Cannot create derived samples for an archived group."), "warning")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': _l("Invalid JSON data received.")}), 400

        common_details = data.get('common_details', {})
        derivation_plan = data.get('derivation_plan', [])
        parent_sample_ids = data.get('parent_sample_ids', [])
        update_parent_status = data.get('update_parent_status', False)

        if not common_details or not derivation_plan or not parent_sample_ids:
            return jsonify({'success': False, 'message': _l("Missing data for derived sample creation.")}), 400

        # Use Service
        samples_created_count, batch_errors = sampling_service.create_derived_samples(
            group, parent_sample_ids, derivation_plan, common_details, update_parent_status
        )

        if not batch_errors:
            flash(_l("%(count)s derived sample record(s) created from %(num_parents)s parent sample(s).", 
                     count=samples_created_count, num_parents=len(parent_sample_ids)), "success")
            return jsonify({'success': True, 'message': _l("%(count)s derived samples logged.", count=samples_created_count)})
        else:
            return jsonify({'success': False, 'message': _l("Errors occurred during derived sample creation."), 'errors': batch_errors}), 400

    # GET request logic
    parent_sample_ids_str = request.args.get('parent_sample_ids')
    if not parent_sample_ids_str:
        flash(_l("No parent samples selected for derivation."), "warning")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    try:
        parent_ids = [int(sid) for sid in parent_sample_ids_str.split(',')]
        parent_samples = Sample.query.filter(Sample.id.in_(parent_ids)).options(db.joinedload(Sample.organ)).all()
        parent_samples = [s for s in parent_samples if s.experimental_group_id == group.id]
    except ValueError:
        flash(_l("Invalid parent sample ID format."), "danger")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))
    
    if not parent_samples:
        flash(_l("No valid parent samples found for derivation."), "warning")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    first_parent_type = parent_samples[0].sample_type
    if not all(s.sample_type == first_parent_type for s in parent_samples):
        flash(_l("All selected parent samples must be of the same type (e.g., all Blood or all Tissue)."), "danger")
        return redirect(url_for('sampling.list_group_samples', group_id=group.id))

    team_id_for_storage = group.team_id
    form = BatchCommonSampleDetailsForm(team_id=team_id_for_storage, prefix="common")

    storage_locations_for_team = []
    if team_id_for_storage:
        storages = Storage.query.filter_by(team_id=team_id_for_storage).order_by(Storage.name).all()
        storage_locations_for_team = [{'id': s.id, 'text': f"{s.name} ({s.location_details or _l('No details')})"} for s in storages]

    derivation_options = {st.name: [] for st in SampleType}
    for dt in DerivedSampleType.query.all():
        derivation_options[dt.parent_type.name].append({'id': dt.id, 'name': dt.name})
    
    staining_options = [{'id': s.id, 'name': s.name} for s in Staining.query.order_by(Staining.name).all()]

    return render_template(
        'sampling/log_derived_samples.html',
        title=_l("Create Derived Samples for Group: %(group_name)s", group_name=group.name),
        group=group,
        parent_samples=parent_samples,
        form=form,
        storage_locations_json=json.dumps(storage_locations_for_team),
        derivation_options_json=json.dumps(derivation_options),
        staining_options_json=json.dumps(staining_options),
        today_date=date.today().isoformat()
    )

# --- Helper to resolve samples for batch actions ---
def _resolve_samples_for_batch(request_form):
    """
    Determines which samples to act upon.
    If 'select_all_matching' is true, re-runs the query filter.
    Otherwise, uses the list of IDs.
    """
    if request_form.get('select_all_matching') == 'true':
        # Reconstruct filters from form data
        filters = {
            'search_value': request_form.get('search_value', '').lower(),
            'project_slug': request_form.get('project_slug', ''),
            'group_id': request_form.get('group_id', ''),
            'status_filter': request_form.get('status_filter', ''),
            'sample_type': request_form.get('sample_type', ''),
            'organ_id': request_form.get('organ_id', type=int),
            'storage_id': request_form.get('storage_id', type=int),
            'condition_id': request_form.get('condition_id', type=int),
            'date_from': request_form.get('date_from', ''),
            'date_to': request_form.get('date_to', '')
        }
        query = sampling_service.build_sample_query(current_user, filters)
        # Return IDs only for performance
        return [s.id for s in query.with_entities(Sample.id).all()]
    else:
        # Standard selection
        ids_str = request_form.get('sample_ids', '')
        if not ids_str: return []
        return [int(x) for x in ids_str.split(',') if x.isdigit()]

# --- Updated Batch Routes ---

@sampling_bp.route('/batch_ship_samples', methods=['POST'])
@login_required
def batch_ship_samples():
    sample_ids = _resolve_samples_for_batch(request.form)
    destination = request.form.get('destination')
    
    if not sample_ids or not destination:
        return jsonify({'success': False, 'message': _l("Missing data.")}), 400

    try:
        updated_count = sampling_service.batch_update_status(sample_ids, SampleStatus.SHIPPED, destination)
        return jsonify({'success': True, 'message': _l('%(count)s sample(s) shipped.', count=updated_count)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@sampling_bp.route('/batch_destroy_samples', methods=['POST'])
@login_required
def batch_destroy_samples():
    sample_ids = _resolve_samples_for_batch(request.form)
    if not sample_ids: return jsonify({'success': False, 'message': _l("No samples.")}), 400
    
    try:
        updated_count = sampling_service.batch_update_status(sample_ids, SampleStatus.DESTROYED)
        return jsonify({'success': True, 'message': _l('%(count)s sample(s) destroyed.', count=updated_count)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@sampling_bp.route('/batch_store_samples', methods=['POST'])
@login_required
def batch_store_samples():
    sample_ids = _resolve_samples_for_batch(request.form)
    if not sample_ids: return jsonify({'success': False, 'message': _l("No samples.")}), 400
    
    try:
        updated_count = sampling_service.batch_update_status(sample_ids, SampleStatus.STORED)
        return jsonify({'success': True, 'message': _l('%(count)s sample(s) stored.', count=updated_count)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@sampling_bp.route('/batch_not_collected_samples', methods=['POST'])
@login_required
def batch_not_collected_samples():
    sample_ids = _resolve_samples_for_batch(request.form)
    if not sample_ids: return jsonify({'success': False, 'message': _l("No samples.")}), 400
    
    try:
        updated_count = sampling_service.batch_update_status(sample_ids, SampleStatus.NOT_COLLECTED)
        return jsonify({'success': True, 'message': _l('%(count)s sample(s) marked as not collected.', count=updated_count)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@sampling_bp.route('/batch_change_storage', methods=['POST'])
@login_required
def batch_change_storage():
    # This one comes as JSON usually, need to handle both or standardize
    if request.is_json:
        data = request.get_json()
        if data.get('select_all_matching'):
             # Extract filter keys directly from the JSON data
             # Ensure integer IDs are cast to int for correct filtering
             filters = {
                 'group_id': data.get('group_id'),
                 'storage_id': int(data['storage_id']) if data.get('storage_id') else None, # Cast to int
                 'status_filter': data.get('status_filter'),
                 'sample_type': data.get('sample_type'),
                 'organ_id': int(data['organ_id']) if data.get('organ_id') else None, # Cast to int
                 'condition_id': int(data['condition_id']) if data.get('condition_id') else None, # Cast to int
                 'date_from': data.get('date_from'),
                 'date_to': data.get('date_to'),
                 'search_value': data.get('search_value'),
                 'project_slug': data.get('project_slug')
             }
             current_app.logger.debug(f"Batch change storage (select_all_matching): Filters received: {filters}")
             query = sampling_service.build_sample_query(current_user, filters)
             sample_ids = [s.id for s in query.with_entities(Sample.id).all()]
        else:
             sample_ids = data.get('sample_ids', [])
        
        new_storage_id = data.get('new_storage_location_id')
        current_app.logger.debug(f"Batch change storage: Received sample_ids: {sample_ids}, New Storage ID: {new_storage_id}, Raw Data: {data}")
    else:
        # Form data fallback
        sample_ids = _resolve_samples_for_batch(request.form)
        new_storage_id = request.form.get('new_storage_location_id')

    if not sample_ids or not new_storage_id:
        return jsonify({'success': False, 'message': _l("Missing data.")}), 400

    try:
        updated_count = sampling_service.batch_change_storage(sample_ids, int(new_storage_id))
        return jsonify({'success': True, 'message': _l('%(count)s sample(s) moved.', count=updated_count)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500