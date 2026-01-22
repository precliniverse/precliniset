from flask import (current_app, flash, redirect, render_template, request,
                   url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required

from app import db
from app.models import (ExperimentalGroup, Project, Sample, SampleStatus,
                        SampleType, Storage, Team, user_has_permission)
from app.storage import storage_bp
from app.storage.forms import StorageForm
from sqlalchemy import func, or_

@storage_bp.route('/', methods=['GET', 'POST'])
@login_required
def manage_storages():
    form = StorageForm()

    user_teams = current_user.get_teams()
    if not user_teams and not current_user.is_super_admin:
        flash(_l("You must be part of a team to manage storages."), "warning")
        return redirect(url_for('main.index'))

    team_id_filter = request.args.get('team_id', type=int)
    selected_team = None

    if current_user.is_super_admin:
        teams_for_select = Team.query.order_by(Team.name).all()
        if team_id_filter:
            selected_team = db.session.get(Team, team_id_filter)
            storages_query = Storage.query.filter_by(team_id=team_id_filter)
        else:
            # Show all storages if no team is selected by super admin
            storages_query = Storage.query
    else:
        # Non-super admin: can only manage storages for their own teams
        teams_for_select = user_teams
        if not teams_for_select:  # Should be caught above, but defensive
            storages_query = Storage.query.filter(db.false())
        elif team_id_filter and any(t.id == team_id_filter for t in teams_for_select):
            selected_team = db.session.get(Team, team_id_filter)
            storages_query = Storage.query.filter_by(team_id=team_id_filter)
        elif teams_for_select:  # Default to first team if multiple and none selected
            selected_team = teams_for_select[0]
            storages_query = Storage.query.filter_by(team_id=selected_team.id)
        else:  # No teams, no storages
            storages_query = Storage.query.filter(db.false())

    if form.validate_on_submit():
        target_team_id_form = request.form.get('team_for_storage', type=int)

        if not target_team_id_form:
            flash(_l("Please select a team for the new storage."), "danger")
        else:
            # --- PERMISSION CHECK ---
            # Check specific RBAC permission for the target team
            if not user_has_permission(current_user, 'Storage', 'create', team_id=target_team_id_form):
                flash(_l("You do not have permission to create storage for the selected team."), "danger")
            else:
                existing_storage = Storage.query.filter_by(team_id=target_team_id_form, name=form.name.data).first()
                if existing_storage:
                    flash(_l("A storage with this name already exists in the selected team."), "danger")
                else:
                    storage = Storage(
                        name=form.name.data,
                        team_id=target_team_id_form,
                        capacity=form.capacity.data,
                        location_details=form.location_details.data
                    )
                    db.session.add(storage)
                    try:
                        db.session.commit()
                        flash(_l("Storage '%(name)s' created successfully.", name=storage.name), "success")
                        return redirect(url_for('storage.manage_storages', team_id=target_team_id_form))
                    except Exception as e:
                        db.session.rollback()
                        flash(_l("Error creating storage: %(error)s", error=str(e)), "danger")
                        current_app.logger.error(f"Error creating storage: {e}", exc_info=True)

    storages = storages_query.order_by(Storage.name).all()

    # For super admins, if no team_id_filter, selected_team might be None.
    # For non-super admins, selected_team should ideally always be set if they have teams.
    default_team_id_for_form = None
    if selected_team:
        default_team_id_for_form = selected_team.id
    elif not current_user.is_super_admin and teams_for_select:
        default_team_id_for_form = teams_for_select[0].id

    return render_template(
        'storage/manage_storages.html',
        title=_l("Manage Storages"),
        form=form,
        storages=storages,
        teams_for_select=teams_for_select,
        selected_team_id=selected_team.id if selected_team else None,
        default_team_id_for_form=default_team_id_for_form
    )

@storage_bp.route('/<int:storage_id>')
@login_required
def view_storage(storage_id):
    storage = db.session.get(Storage, storage_id)
    if not storage:
        flash(_l("Storage not found."), "danger")
        return redirect(url_for('storage.manage_storages'))

    if not user_has_permission(current_user, 'Storage', 'view', team_id=storage.team_id):
        flash(_l("You do not have permission to view this storage."), "danger")
        return redirect(url_for('storage.manage_storages'))

    # --- Summary Statistics (Optimized) ---
    # We still calculate the summary for the top table, but we do it via SQL grouping
    # instead of fetching all objects.
    
    summary_query = db.session.query(
        Project.name.label('project_name'),
        Project.slug.label('project_slug'),
        Sample.sample_type,
        func.count(Sample.id).label('count')
    ).join(ExperimentalGroup, Sample.experimental_group_id == ExperimentalGroup.id)\
     .join(Project, ExperimentalGroup.project_id == Project.id)\
     .filter(Sample.storage_id == storage.id, Sample.status == SampleStatus.STORED)\
     .group_by(Project.name, Project.slug, Sample.sample_type)\
     .all()

    grouped_samples_data = []
    for row in summary_query:
        grouped_samples_data.append({
            'project_name': row.project_name,
            'project_slug': row.project_slug,
            'sample_type': row.sample_type.value,
            'sample_type_enum': row.sample_type.name, # For filtering
            'count': row.count
        })
    
    # Get list of projects for the filter dropdown
    projects = db.session.query(Project.name, Project.slug).join(ExperimentalGroup).join(Sample).filter(Sample.storage_id == storage.id).distinct().order_by(Project.name).all()

    return redirect(url_for('sampling.all_samples_list', storage_id=storage_id))

    


@storage_bp.route('/<int:storage_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_storage(storage_id):
    storage = db.session.get(Storage, storage_id)
    if not storage:
        flash(_l("Storage not found."), "danger")
        return redirect(url_for('storage.manage_storages'))

    # --- PERMISSION CHECK ---
    if not user_has_permission(current_user, 'Storage', 'edit', team_id=storage.team_id):
        flash(_l("You do not have permission to edit this storage."), "danger")
        return redirect(url_for('storage.view_storage', storage_id=storage.id))

    form = StorageForm(obj=storage)
    if form.validate_on_submit():
        # Check for name conflict within the same team, excluding self
        existing_storage = Storage.query.filter(
            Storage.team_id == storage.team_id,
            Storage.name == form.name.data,
            Storage.id != storage.id
        ).first()
        if existing_storage:
            flash(_l("A storage with this name already exists in this team."), "danger")
        else:
            storage.name = form.name.data
            storage.capacity = form.capacity.data
            storage.location_details = form.location_details.data
            try:
                db.session.commit()
                flash(_l("Storage '%(name)s' updated successfully.", name=storage.name), "success")
                return redirect(url_for('storage.view_storage', storage_id=storage.id))
            except Exception as e:
                db.session.rollback()
                flash(_l("Error updating storage: %(error)s", error=str(e)), "danger")
                current_app.logger.error(f"Error updating storage {storage_id}: {e}", exc_info=True)

    return render_template(
        'storage/edit_storage.html',
        title=_l("Edit Storage: %(name)s", name=storage.name),
        form=form,
        storage=storage
    )


@storage_bp.route('/<int:storage_id>/delete', methods=['POST'])
@login_required
def delete_storage(storage_id):
    storage = db.session.get(Storage, storage_id)
    if not storage:
        flash(_l("Storage not found."), "danger")
        return redirect(url_for('storage.manage_storages'))

    # --- PERMISSION CHECK ---
    if not user_has_permission(current_user, 'Storage', 'delete', team_id=storage.team_id):
        flash(_l("You do not have permission to delete this storage."), "danger")
        return redirect(url_for('storage.manage_storages'))

    if storage.samples.first():  # Check if there are any samples in this storage
        flash(_l("Cannot delete storage '%(name)s' because it contains samples. Please reassign or delete samples first.", name=storage.name), "warning")
        return redirect(url_for('storage.view_storage', storage_id=storage.id))

    team_id_redirect = storage.team_id
    storage_name = storage.name
    try:
        db.session.delete(storage)
        db.session.commit()
        flash(_l("Storage '%(name)s' deleted successfully.", name=storage_name), "success")
    except Exception as e:
        db.session.rollback()
        flash(_l("Error deleting storage: %(error)s", error=str(e)), "danger")
        current_app.logger.error(f"Error deleting storage {storage_id}: {e}", exc_info=True)

    return redirect(url_for('storage.manage_storages', team_id=team_id_redirect))

@storage_bp.route('/<int:storage_id>/download_inventory')
@login_required
def download_inventory(storage_id):
    storage = db.session.get(Storage, storage_id)
    if not storage:
        flash(_l("Storage not found."), "danger")
        return redirect(url_for('storage.manage_storages'))

    # --- PERMISSION CHECK ---
    if not user_has_permission(current_user, 'Storage', 'view', team_id=storage.team_id):
        flash(_l("You do not have permission to view this storage."), "danger")
        return redirect(url_for('storage.manage_storages'))

    samples_in_storage = Sample.query.filter_by(storage_id=storage.id, status=SampleStatus.STORED) \
        .options(
            db.joinedload(Sample.organ),
            db.joinedload(Sample.collection_conditions)
        ) \
        .all()

    # Prepare data for CSV
    csv_data = "Sample ID,Creation Date,Reference,Project,Sample Type,Organ,Collection Conditions\n"
    for sample in samples_in_storage:
        organ_name = sample.organ.name if sample.organ else 'N/A'
        conditions = ', '.join([cond.name for cond in sample.collection_conditions]) if sample.collection_conditions else 'N/A'
        csv_data += f"{sample.id},{sample.collection_date},{sample.experimental_group.project.name if sample.experimental_group and sample.experimental_group.project else 'N/A'},{sample.sample_type},{organ_name},{conditions}\n"

    # Create a response with the CSV data
    response = current_app.response_class(
        csv_data,
        mimetype='text/csv'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=storage_{storage.id}_inventory.csv'

    return response