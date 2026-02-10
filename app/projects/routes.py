# app/projects/routes.py
import os
import time
from datetime import datetime

import magic
from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app import db
from app.forms import (AttachmentForm, LinkEthicalApprovalForm, LinkGroupForm,
                       LinkPartnerForm, PartnerForm, ProjectDescriptionForm,
                       ProjectForm, ShareProjectForm, WorkplanForm)
from app.models import (Animal, AnimalModel, Attachment, DataTable, EthicalApproval,
                        ExperimentalGroup, ExperimentDataRow, Partner, Project,
                        ProjectEthicalApprovalAssociation,
                        ProjectPartnerAssociation, ProjectTeamShare,
                        ProjectUserShare, Sample, Team, TeamMembership, User,
                        Workplan, user_has_permission)
from app.permissions import check_group_permission, check_project_permission

projects_bp = Blueprint('projects', __name__, template_folder='../templates/projects')

from app.services.group_service import GroupService
from app.services.permission_service import PermissionService
from app.services.project_service import ProjectService

project_service = ProjectService()
group_service = GroupService()
perm_service = PermissionService()


def get_manageable_projects_for_team(team_id, current_project_id_to_exclude=None):
    if not current_user.is_authenticated:
        return []
    
    manageable_projects = []
    if user_has_permission(current_user, 'Project', 'edit', team_id=team_id):
        query = Project.query.filter(Project.team_id == team_id)
        if current_project_id_to_exclude:
            query = query.filter(Project.id != current_project_id_to_exclude)
        manageable_projects.extend(query.all())
    return sorted(list(set(manageable_projects)), key=lambda p: p.name)

# --- Routes ---

@projects_bp.route('/<string:project_slug>/groups/search_team_groups', methods=['GET'])
@login_required
def search_team_groups_for_project(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        return jsonify({'error': 'Permission denied'}), 403

    search_term = request.args.get('term', '').lower()
    
    groups_in_team = ExperimentalGroup.query.filter(
        ExperimentalGroup.team_id == project.team_id,
        ExperimentalGroup.project_id != project.id,
        ExperimentalGroup.name.ilike(f"%{search_term}%")
    ).limit(10).all()
    
    from app.permissions import \
        check_group_permission as check_group_read_permission
    
    results = [
        {'id': group.id, 'text': f"{group.name} (Currently in: {group.project.name if group.project else 'N/A'})"}
        for group in groups_in_team if check_group_read_permission(group, 'read')
    ]
    return jsonify({'results': results})


@projects_bp.route('/<string:project_slug>/groups/<string:group_id>/reassign', methods=['POST'])
@login_required
def reassign_group_to_project(project_slug, group_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    group_to_move = db.session.get(ExperimentalGroup, group_id)

    if not group_to_move:
        flash(_l("Group not found."), "danger")
        return redirect(request.referrer or url_for('projects.view_edit_project', project_slug=project.slug))

    if not check_project_permission(project, 'edit') or \
       not check_group_permission(group_to_move, 'edit_exp_group') or \
       group_to_move.team_id != project.team_id:
        flash(_l("You do not have permission to reassign this group to this project, or teams do not match."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')

    if project.is_archived:
        flash(_l("Cannot reassign groups to an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')

    original_project_slug = group_to_move.project.slug if group_to_move.project else None
    
    try:
        group_service.reassign_group(group_to_move, project)
        flash(_l("Group '%(group_name)s' successfully reassigned to project '%(project_name)s'.", group_name=group_to_move.name, project_name=project.name), "success")
    except Exception as e:
        flash(_l("Error reassigning group: %(error)s", error=str(e)), "danger")
        current_app.logger.error(f"Error reassigning group {group_id} to project {project.slug}: {e}")

    if original_project_slug and original_project_slug != project.slug:
         return redirect(url_for('projects.view_edit_project', project_slug=original_project_slug) + '#collapseExpGroups')
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')


@projects_bp.route('/<string:project_slug>/groups/<string:group_id>/handle_unlink', methods=['POST'])
@login_required
def handle_unlink_group_from_project(project_slug, group_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    group = db.session.get(ExperimentalGroup, group_id)

    if not group:
        flash(_l("Group not found."), "danger")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')

    if not check_project_permission(project, 'edit'):
        flash(_l("You do not have permission to modify groups for this project."), "danger")
        abort(403)
    
    if group.project_id != project.id:
        flash(_l("Group is not part of this project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')

    action = request.form.get('unlink_action')
    target_project_id = request.form.get('target_project_id')

    if action == "reassign":
        if not target_project_id:
            flash(_l("No target project selected for reassignment."), "danger")
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')
        
        target_project = db.session.get(Project, int(target_project_id))
        if not target_project:
            flash(_l("Target project for reassignment not found."), "danger")
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')

        if not check_project_permission(target_project, 'edit') or target_project.team_id != group.team_id:
            flash(_l("You do not have permission to reassign to the target project or teams do not match."), "danger")
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')
        if target_project.is_archived:
            flash(_l("Cannot reassign group to an archived project."), "warning")
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')


        try:
            group_service.reassign_group(group, target_project)
            flash(_l("Group '%(group_name)s' reassigned to project '%(target_project_name)s'.", group_name=group.name, target_project_name=target_project.name), "success")
        except Exception as e:
            flash(_l("Error reassigning group: %(error)s", error=str(e)), "danger")
    
    elif action == "delete":
        if not check_group_permission(group, 'delete_exp_group'):
            flash(_l("You do not have permission to delete this group."), "danger")
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')

        try:
            group_name = group.name
            group_service.delete_group(group)
            flash(_l("Group '%(group_name)s' and its DataTables permanently deleted.", group_name=group_name), "success")
        except Exception as e:
            flash(_l("Error deleting group: %(error)s", error=str(e)), "danger")
    else:
        flash(_l("Invalid action specified for unlinking group."), "warning")

    return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseExpGroups')


@projects_bp.route('/')
@login_required
def list_projects():
    """
    OPTIMIZED: Uses server-side pagination to prevent memory exhaustion.
    Stats are computed only for the current page's projects.
    """
    show_archived = request.args.get('show_archived', 'false').lower() == 'true'
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    
    # Limit per_page to prevent abuse
    per_page = min(per_page, 100)
    
    # Use the optimized permission service query instead of loading all projects
    from app.services.permission_service import PermissionService
    perm_service = PermissionService()
    
    # Get base query for visible projects
    if current_user.is_super_admin:
        base_query = Project.query
    else:
        base_query = perm_service.get_visible_projects_query(current_user)
    
    # Apply archive filter
    if not show_archived:
        base_query = base_query.filter(Project.is_archived == False)
    
    # Apply search filter
    if search_query:
        search_pattern = f"%{search_query}%"
        base_query = base_query.filter(
            or_(
                Project.name.ilike(search_pattern),
                Project.description.ilike(search_pattern),
                Project.slug.ilike(search_pattern)
            )
        )
    
    # Get total count BEFORE pagination (for pagination controls)
    total_count = base_query.distinct().count()
    
    # Apply pagination - get just the project IDs for this page first
    paginated_projects = base_query.join(Team).distinct().order_by(
        Team.name.asc(), 
        Project.updated_at.desc()
    )\
    .offset((page - 1) * per_page)\
    .limit(per_page)\
    .all()
    
    projects_with_stats = []
    
    if paginated_projects:
        # Get IDs for just this page
        page_project_ids = [p.id for p in paginated_projects]
        
        # Build stats queries only for this page's projects (much more efficient)
        group_counts = db.session.query(
            ExperimentalGroup.project_id,
            func.count(ExperimentalGroup.id).label('group_count')
        ).filter(
            ExperimentalGroup.project_id.in_(page_project_ids),
            ExperimentalGroup.is_archived == False
        ).group_by(ExperimentalGroup.project_id).all()
        
        datatable_counts = db.session.query(
            ExperimentalGroup.project_id,
            func.count(DataTable.id).label('datatable_count')
        ).join(DataTable)\
         .filter(
             ExperimentalGroup.project_id.in_(page_project_ids),
             ExperimentalGroup.is_archived == False
         ).group_by(ExperimentalGroup.project_id).all()
        
        sample_counts = db.session.query(
            ExperimentalGroup.project_id,
            func.count(Sample.id).label('sample_count')
        ).join(Sample)\
         .filter(
             ExperimentalGroup.project_id.in_(page_project_ids),
             ExperimentalGroup.is_archived == False
         ).group_by(ExperimentalGroup.project_id).all()
        
        # Animal count from Animal table
        animal_counts = db.session.query(
            ExperimentalGroup.project_id,
            func.count(Animal.id).label('animal_count')
        ).join(Animal, ExperimentalGroup.id == Animal.group_id)\
         .filter(
            ExperimentalGroup.project_id.in_(page_project_ids),
            ExperimentalGroup.is_archived == False
        ).group_by(ExperimentalGroup.project_id).all()
        
        ea_refs_query = db.session.query(
            ExperimentalGroup.project_id,
            func.group_concat(EthicalApproval.reference_number.distinct()).label('ea_refs')
        ).join(EthicalApproval, ExperimentalGroup.ethical_approval_id == EthicalApproval.id)\
         .filter(
             ExperimentalGroup.project_id.in_(page_project_ids),
             ExperimentalGroup.is_archived == False
         ).group_by(ExperimentalGroup.project_id).all()
        
        # Convert to dicts for O(1) lookup
        group_counts_map = {r.project_id: r.group_count for r in group_counts}
        datatable_counts_map = {r.project_id: r.datatable_count for r in datatable_counts}
        sample_counts_map = {r.project_id: r.sample_count for r in sample_counts}
        animal_counts_map = {r.project_id: r.animal_count for r in animal_counts}
        ea_refs_map = {r.project_id: r.ea_refs for r in ea_refs_query}
        
        for project in paginated_projects:
            stats = {
                'group_count': group_counts_map.get(project.id, 0),
                'datatable_count': datatable_counts_map.get(project.id, 0),
                'sample_count': sample_counts_map.get(project.id, 0),
                'animal_count': animal_counts_map.get(project.id) or 0,
                'ea_refs': ea_refs_map.get(project.id) or _l('N/A')
            }
            projects_with_stats.append({'project': project, 'stats': stats})
    
    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page
    start = (page - 1) * per_page + 1 if total_count > 0 else 0
    end = min(page * per_page, total_count)
    
    return render_template('projects/projects.html', 
                           projects=projects_with_stats, 
                           title=_l("Projects"), 
                           show_archived=show_archived,
                           # Pagination info
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages,
                           start=start,
                           end=end,
                           total=total_count,  # Alias for template compatibility
                           search_query=search_query)

@projects_bp.route('/search_projects_ajax')
@login_required
def search_projects_ajax():
    search_term = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    show_archived = request.args.get('show_archived', 'false').lower() == 'true'
    per_page = 10 

    items, total_count = project_service.search_projects(
        user=current_user,
        search_term=search_term,
        show_archived=show_archived,
        page=page,
        per_page=per_page
    )

    results = []
    for project in items:
        results.append({
            'id': project.id,
            'text': project.name,
            'name': project.name,
            'description': project.description if project.description else _l('No description provided.'),
            'slug': project.slug
        })

    return jsonify({
        'results': results,
        'total_count': total_count,
        'pagination': {'more': (page * per_page) < total_count}
    })

@projects_bp.route('/partners')
@login_required
def partners():
    can_manage_partners = user_has_permission(current_user, 'Partner', 'edit') or user_has_permission(current_user, 'Partner', 'create') or user_has_permission(current_user, 'Partner', 'delete')
    
    partners_query = Partner.query
    
    if not user_has_permission(current_user, 'Partner', 'read'):
        user_teams = current_user.get_teams()
        if not user_teams:
            partners_query = partners_query.filter(db.false())
        else:
            user_team_ids = [team.id for team in user_teams]
            accessible_projects_filter = Project.team_id.in_(user_team_ids)
            partners_query = partners_query.filter(
                Partner.projects.any(accessible_projects_filter)
            )

    all_partners = partners_query.order_by(Partner.company_name).all()
    
    partners_data = []
    user_teams = current_user.get_teams()
    user_team_ids = [team.id for team in user_teams]

    for partner in all_partners:
        linked_projects_query = partner.projects 
        
        if not user_has_permission(current_user, 'Partner', 'read'):
            accessible_projects_filter = Project.team_id.in_(user_team_ids)
            linked_projects_query = linked_projects_query.filter(accessible_projects_filter)

        total_linked_projects = linked_projects_query.count()
        active_linked_projects = linked_projects_query.filter(Project.is_archived == False).count()
        
        if total_linked_projects > 0 or current_user.is_super_admin:
            partners_data.append({
                'id': partner.id,
                'company_name': partner.company_name,
                'contact_email': partner.contact_email,
                'total_projects': total_linked_projects,
                'active_projects': active_linked_projects
            })

    return render_template('projects/partners.html', 
                           partners_data=partners_data,
                           title=_l("Partners"))


@projects_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_project():
    form = ProjectForm()
    form.team.choices = [(team.id, team.name) for team in current_user.get_teams()]

    if not form.team.choices:
         flash(_l('You must be a member of at least one team to create a project.'), 'warning')
         return redirect(url_for('main.index')) 

    if form.validate_on_submit():
        team = db.session.get(Team, form.team.data)
        if not team:
            abort(404)
            
        if not user_has_permission(current_user, 'Project', 'create', team_id=team.id):
             flash(_l('You do not have permission to create a project in this team.'), 'danger')
             abort(403) 

        existing_project = Project.query.filter_by(team_id=team.id, name=form.name.data, is_archived=False).first()
        if existing_project:
            flash(_l('An active project with this name already exists in this team.'), 'danger')
            return render_template('projects/create_edit_project.html', form=form, title=_l("Create Project"), is_new=True)

        try:
            project = project_service.create_project(
                name=form.name.data,
                team_id=team.id,
                owner_id=current_user.id
            )
            
            flash(_l('Project "%(name)s" created successfully!', name=project.name), 'success')
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

        except sqlalchemy_exc.IntegrityError as e:
            current_app.logger.error(f"Integrity error creating project '{form.name.data}': {e}", exc_info=True)
            flash(_l('A project with this name may already exist or another database constraint was violated.'), 'danger')
        except Exception as e:
            current_app.logger.error(f"Error creating project '{form.name.data}': {e}", exc_info=True)
            if "database is locked" in str(e).lower():
                flash(_l('Database is busy, please try creating the project again shortly.'), 'danger')
            else:
                flash(_l('Error creating project: %(error)s', error=str(e)), 'danger')

    return render_template('projects/create_edit_project.html', form=form, title=_l("Create Project"), is_new=True)


@projects_bp.route('/<string:project_slug>', methods=['GET', 'POST'])
@login_required
def view_edit_project(project_slug):
    from sqlalchemy.orm import selectinload
    
    project = Project.query.filter_by(slug=project_slug).options(
       selectinload(Project.groups).selectinload(ExperimentalGroup.animals)
    ).first_or_404()
    
    if not check_project_permission(project, 'read', allow_abort=True):
        abort(403)

    project_perms = perm_service.get_effective_project_permissions(current_user, project)
    
    can_edit_project_details = project_perms['is_admin']
    can_archive_project = project_perms['is_admin']
    can_delete_project = user_has_permission(current_user, 'Project', 'delete')
    effective_can_edit_forms = can_edit_project_details and not project.is_archived

    form = ProjectForm(obj=project) if can_edit_project_details else None
    if form:
        form.team.choices = [(team.id, team.name) for team in current_user.get_teams()]

    description_form = ProjectDescriptionForm() if effective_can_edit_forms else None
    if description_form and request.method == 'GET':
        description_form.description.data = project.description

    attachment_form = AttachmentForm() if effective_can_edit_forms else None
    link_partner_form = LinkPartnerForm() if effective_can_edit_forms else None
    link_group_form = LinkGroupForm(project=project, formdata=request.form if request.method == 'POST' else None, obj=project) if effective_can_edit_forms else None
    link_ethical_approval_form = LinkEthicalApprovalForm(project=project, formdata=request.form if request.method == 'POST' else None) if effective_can_edit_forms else None
    
    share_team_form = ShareProjectForm(project=project, prefix='team') if effective_can_edit_forms else None
    share_user_form = ShareProjectForm(project=project, prefix='user') if effective_can_edit_forms else None
    
    workplan_form = WorkplanForm() if effective_can_edit_forms else None

    if project.is_archived and request.method == 'POST' and not request.form.get('unarchive_project_submit'):
        flash(_l("This project is archived. Most actions are disabled. Please unarchive it first."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    if description_form and description_form.submit_description.data and description_form.validate_on_submit():
        try:
            project_service.update_project(
                project,
                description=description_form.description.data.strip() if description_form.description.data else None
            )
            flash(_l('Project description updated successfully!'), 'success')
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug))
        except Exception as e:
            flash(_l('Error updating project description: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error updating project description for {project.slug}: {e}")

    if form and form.submit.data and form.validate_on_submit():
        if form.name.data != project.name:
             existing_project = Project.query.filter(
                 Project.team_id == form.team.data,
                 Project.name == form.name.data,
                 Project.id != project.id,
                 Project.is_archived == False
             ).first()
             if existing_project:
                 flash(_l('An active project with this name already exists in this team.'), 'danger')
                 return render_template('projects/project.html', project=project, form=form,
                                        description_form=description_form,
                                        attachment_form=attachment_form, link_partner_form=link_partner_form,
                                        link_ethical_approval_form=link_ethical_approval_form,
                                        link_group_form=link_group_form, 
                                        share_team_form=share_team_form, share_user_form=share_user_form,
                                        workplan_form=workplan_form,
                                        attachments=project.attachments.order_by(Attachment.uploaded_at.desc()).all(), 
                                        partners=project.partners.order_by(Partner.company_name).all(), 
                                        groups_with_datatables=[], 
                                        ethical_approvals=project.ethical_approvals.all(),
                                        can_edit=effective_can_edit_forms, can_edit_project_details=can_edit_project_details, can_archive_project=can_archive_project,
                                        can_delete_project=can_delete_project,
                                        project_perms=project_perms, 
                                        title=project.name, project_slug=project.slug, 
                                        ckan_config_complete=bool(current_user.ckan_url and current_user.ckan_api_key),
                                        Workplan=Workplan,
                                        shared_with_teams=project.team_shares,
                                        shared_with_users=project.user_shares)

        new_team_id = form.team.data
        if new_team_id != project.team_id:
            new_team = Team.query.get_or_404(new_team_id)
            if new_team not in current_user.get_teams():
                 flash(_l('You cannot move the project to a team you are not a member of.'), 'danger')
                 abort(403) 
            project.team_id = new_team_id 

        try:
            project_service.update_project(
                project,
                name=form.name.data,
                team_id=new_team_id
            )
            flash(f'Project "{project.name}" updated successfully!', 'success')
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug))
        except Exception as e:
            flash(_l('Error updating project: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error updating project {project.slug}: {e}")

    if link_ethical_approval_form and link_ethical_approval_form.submit_link_ethical_approval.data and link_ethical_approval_form.validate_on_submit():
        if not effective_can_edit_forms: abort(403)

        selected_ethical_approval_ids = set(link_ethical_approval_form.ethical_approvals.data)
        try:
            project_service.update_ethical_approvals(project, selected_ethical_approval_ids)
            flash(_l('Linked ethical approvals updated successfully.'), 'success')
            return redirect(url_for('projects.view_edit_project', project_slug=project.slug))
        except Exception as e:
            flash(_l('Error updating linked ethical approvals: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error updating linked ethical approvals for project {project.slug}: {e}")

    db.session.refresh(project) 

    attachments = project.attachments.order_by(Attachment.uploaded_at.desc()).all()
    partners = project.partners.order_by(Partner.company_name).all()
    
    all_groups = sorted(project.groups, key=lambda g: g.name)
    
    ethical_approvals = project.ethical_approvals.all()

    groups_with_datatables = []
    for group_item in all_groups:
        from ..permissions import check_datatable_permission as check_dt_perm
        
        group_dts_query = group_item.data_tables.order_by(DataTable.date.desc())
        all_group_dts = group_dts_query.all()
        
        accessible_group_dts = [dt for dt in all_group_dts if check_dt_perm(dt, 'read')]
        
        groups_with_datatables.append({
            'group': group_item,
            'datatables_preview': accessible_group_dts[:5],
            'total_datatables_count': len(accessible_group_dts)
        })

    overall_project_datatables = []
    for g_data in groups_with_datatables:
        overall_project_datatables.extend(g_data['datatables_preview']) 

    shared_with_teams = project.team_shares
    shared_with_users = project.user_shares

    return render_template('projects/project.html', 
                           project=project, 
                           form=form,
                           description_form=description_form,
                           attachment_form=attachment_form, 
                           link_partner_form=link_partner_form,
                           link_group_form=link_group_form,
                           link_ethical_approval_form=link_ethical_approval_form,
                           share_team_form=share_team_form,
                           share_user_form=share_user_form,
                           workplan_form=workplan_form,
                           attachments=attachments, 
                           partners=partners,
                           groups_with_datatables=groups_with_datatables,
                           datatables=list(set(overall_project_datatables)),
                           ethical_approvals=ethical_approvals,
                           can_edit=effective_can_edit_forms,
                           can_edit_project_details=can_edit_project_details,
                           can_archive_project=can_archive_project,
                           can_delete_project=can_delete_project,
                           project_perms=project_perms,
                           check_project_permission=check_project_permission,
                           title=project.name,
                           project_slug=project.slug,
                           ckan_config_complete=bool(current_user.ckan_url and current_user.ckan_api_key),
                           Workplan=Workplan,
                           shared_with_teams=shared_with_teams,
                           shared_with_users=shared_with_users)

# --- Attachment Routes ---
@projects_bp.route('/<string:project_slug>/attachments/upload', methods=['POST'])
@login_required
def upload_attachment(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to upload attachments to this project.'), 'danger')
        abort(403)
    if project.is_archived:
        flash(_l("Cannot upload attachments to an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    form = AttachmentForm()
    if form.validate_on_submit():
        file = form.file.data
        description = form.description.data
        if not current_app.config.get('UPLOAD_FOLDER'):
             flash(_l('File uploads are not configured correctly.'), 'danger')
             current_app.logger.error("UPLOAD_FOLDER not set in Flask config.")
             return redirect(url_for('projects.view_edit_project', project_slug=project.slug))
        try:
            attachment = project_service.save_attachment(file, project, description)
            if attachment:
                flash(_l('Attachment "%(filename)s" uploaded successfully.', filename=attachment.filename), 'success')
            else:
                 flash(_l('Upload failed. Invalid file or error saving.'), 'danger')
        except ValueError as e:
             flash(str(e), 'danger')
        except Exception as e:
            flash(_l('Error saving attachment record: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error saving attachment record for project {project.slug}: {e}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", 'danger')
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

@projects_bp.route('/<string:project_slug>/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(project_slug, attachment_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    attachment = Attachment.query.get_or_404(attachment_id)
    if attachment.project_id != project.id: abort(404)
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to delete attachments from this project.'), 'danger')
        abort(403)
    if project.is_archived:
        flash(_l("Cannot delete attachments from an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    filepath_to_delete = os.path.join(current_app.config.get('UPLOAD_FOLDER', ''), attachment.filepath)
    filename = attachment.filename 
    db.session.delete(attachment)
    project.updated_at = datetime.now(current_app.config['UTC_TZ'])
    try:
        db.session.commit()
        try:
            if os.path.exists(filepath_to_delete):
                 os.remove(filepath_to_delete)
                 flash(_l('Attachment "%(filename)s" deleted successfully.', filename=filename), 'success')
            else:
                 flash(_l('Attachment record deleted, but the file was not found on the server.'), 'warning')
                 current_app.logger.warning(f"Attachment file not found for deletion: {filepath_to_delete}")
        except OSError as e:
            flash(_l('Attachment record deleted, but failed to delete the file: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error deleting attachment file {filepath_to_delete}: {e}")
    except Exception as e:
        db.session.rollback()
        flash(_l('Error deleting attachment record: %(error)s', error=str(e)), 'danger')
        current_app.logger.error(f"Error deleting attachment record {attachment_id} for project {project.slug}: {e}")
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

@projects_bp.route('/<string:project_slug>/attachments/<int:attachment_id>') 
@login_required
def download_attachment(project_slug, attachment_id): 
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'read'): abort(403)
    attachment = Attachment.query.get_or_404(attachment_id)
    if attachment.project_id != project.id: abort(404)
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    if not upload_folder: abort(500)
    safe_filepath = os.path.normpath(attachment.filepath)
    if safe_filepath.startswith('/') or '..' in safe_filepath.split(os.path.sep): abort(400) 
    directory = os.path.dirname(os.path.join(upload_folder, safe_filepath))
    actual_filename = os.path.basename(safe_filepath) 
    try:
        download_name = attachment.filename
        return send_from_directory(directory, actual_filename, as_attachment=True, download_name=download_name)
    except FileNotFoundError:
        abort(404)

# --- Partner Linking Routes ---
@projects_bp.route('/<string:project_slug>/partners/link', methods=['POST'])
@login_required
def link_partner(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to modify partners for this project.'), 'danger')
        abort(403)
    if project.is_archived:
        flash(_l("Cannot link partners to an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    form = LinkPartnerForm()
    if form.validate_on_submit():
        # --- PERMISSION CHECK ---
        if form.new_company_name.data or form.new_contact_email.data:
             if not user_has_permission(current_user, 'Resource', 'create', team_id=None):
                flash(_l('You do not have permission to create new Partners globally.'), 'danger')
                return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

        success, message, category = project_service.link_partner(project, form)
        flash(_l(message), category)
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", 'danger')
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

@projects_bp.route('/<string:project_slug>/partners/<int:partner_id>/unlink', methods=['POST'])
@login_required
def unlink_partner(project_slug, partner_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to modify partners for this project.'), 'danger')
        abort(403)
    if project.is_archived:
        flash(_l("Cannot unlink partners from an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))
        
    success, partner_name = project_service.unlink_partner(project, partner_id)
    if success:
        flash(_l('Partner "%(name)s" unlinked successfully.', name=partner_name), 'success')
    else:
        flash(_l('Partner not found or not linked to this project.'), 'warning')
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

@projects_bp.route('/partners/<int:partner_id>')
@login_required
def partner_details(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    user_teams = current_user.get_teams()
    team_ids = [team.id for team in user_teams]
    
    accessible_projects_filter = Project.team_id.in_(team_ids)
    
    can_view_partner = False
    if current_user.is_super_admin:
        can_view_partner = True
    else:
        can_view_partner = partner.projects.filter(accessible_projects_filter).first() is not None

    if not can_view_partner:
        flash(_l("You do not have permission to view this partner's details."), "danger")
        return redirect(url_for('projects.partners'))

    accessible_projects = partner.projects.filter(accessible_projects_filter, Project.is_archived == False).order_by(Project.updated_at.desc()).all()
    
    groups = []
    for project in accessible_projects:
        groups.extend(project.groups)
        
    datatables = []
    return render_template('projects/partner_details.html',
                           partner=partner,
                           projects=accessible_projects,
                           groups=groups,
                           datatables=datatables,
                           title=_l("Partner Details: %(name)s", name=partner.company_name))


@projects_bp.route('/by_partner/<int:partner_id>')
@login_required
def list_projects_by_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    user_teams = current_user.get_teams()
    team_ids = [team.id for team in user_teams]
    accessible_projects_filter = Project.team_id.in_(team_ids)
    accessible_projects = partner.projects.filter(accessible_projects_filter, Project.is_archived == False).order_by(Project.updated_at.desc()).all()
    return render_template('projects/partner_projects.html', 
                           partner=partner,
                           projects=accessible_projects,
                           title=_l("Projects for Partner: %(name)s", name=partner.company_name))

# --- Experimental Group Linking Routes ---
@projects_bp.route('/<string:project_slug>/groups/link', methods=['POST'])
@login_required
def link_groups(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to modify linked groups for this project.'), 'danger')
        abort(403)
    if project.is_archived:
        flash(_l("Cannot link groups to an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    form = LinkGroupForm(project=project, formdata=request.form) 
    if form.validate_on_submit(): 
        selected_group_ids = set(form.groups.data)
        current_group_ids = {group.id for group in project.groups}
        
        groups_to_add = selected_group_ids - current_group_ids
        groups_to_remove = current_group_ids - selected_group_ids
        
        for group_id in groups_to_add:
            group = db.session.query(ExperimentalGroup).filter_by(id=group_id, team_id=project.team_id, is_archived=False).first() 
            if group and group not in project.groups:
                project.groups.append(group)
        for group_id in groups_to_remove:
            group = db.session.get(ExperimentalGroup, group_id)
            if group and group in project.groups:
                project.groups.remove(group)
        project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        try:
            db.session.commit()
            flash(_l('Linked experimental groups updated successfully.'), 'success')
        except Exception as e:
            db.session.rollback()
            flash(_l('Error updating linked groups: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error updating linked groups for project {project.slug}: {e}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", 'danger')
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

# --- Project Archive/Unarchive Routes ---
@projects_bp.route('/<string:project_slug>/archive_info', methods=['GET'])
@login_required
def get_project_archive_info(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'archive'):
        return jsonify({'error': 'Permission denied'}), 403

    active_groups_count = sum(1 for g in project.groups if not g.is_archived)
    
    active_datatables_count = db.session.query(func.count(DataTable.id)).join(ExperimentalGroup).filter(
        ExperimentalGroup.project_id == project.id,
        ExperimentalGroup.is_archived == False
    ).scalar()
    
    last_datatable_date = db.session.query(func.max(DataTable.date)).join(ExperimentalGroup).filter(
        ExperimentalGroup.project_id == project.id,
        ExperimentalGroup.is_archived == False
    ).scalar()

    return jsonify({
        'project_name': project.name,
        'active_groups_count': active_groups_count,
        'active_datatables_count': active_datatables_count,
        'last_datatable_date': last_datatable_date if last_datatable_date else _l('N/A')
    })

@projects_bp.route('/<string:project_slug>/archive', methods=['POST'])
@login_required
def archive_project(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'archive'):
        flash(_l('You do not have permission to archive this project.'), 'danger')
        abort(403)

    if project.is_archived:
        flash(_l("Project is already archived."), "info")
    else:
        cascade_archive_groups = request.form.get('cascade_archive_groups') == 'true'
        try:
            archived_groups_count = project_service.archive_project(project, cascade_groups=cascade_archive_groups)
            
            flash_message = _l('Project "%(name)s" has been archived.', name=project.name)
            if cascade_archive_groups and archived_groups_count > 0:
                flash_message += _l(' %(count)s associated active group(s) also archived.', count=archived_groups_count)
            elif cascade_archive_groups:
                flash_message += _l(' No active groups to archive.')
            flash(flash_message, "success")
        except Exception as e:
            db.session.rollback()
            flash(_l('Error archiving project: %(error)s', error=str(e)), "danger")
            current_app.logger.error(f"Error archiving project {project_slug}: {e}", exc_info=True)
            
    return redirect(url_for('projects.list_projects', show_archived=True))


@projects_bp.route('/<string:project_slug>/unarchive', methods=['POST'])
@login_required
def unarchive_project(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'archive'):
        flash(_l('You do not have permission to unarchive this project.'), 'danger')
        abort(403)

    if not project.is_archived:
        flash(_l("Project '%(name)s' is not archived.", name=project.name), "info")
    else:
        try:
            unarchived_groups_count = project_service.unarchive_project(project)
            flash_message = _l('Project "%(name)s" has been unarchived.', name=project.name)
            if unarchived_groups_count > 0:
                flash_message += _l(' %(count)s associated archived group(s) also unarchived.', count=unarchived_groups_count)
            flash(flash_message, "success")
        except Exception as e:
            db.session.rollback()
            flash(_l('Error unarchiving project: %(error)s', error=str(e)), "danger")
            current_app.logger.error(f"Error unarchiving project {project_slug}: {e}", exc_info=True)
            
    return redirect(url_for('projects.list_projects', show_archived=False))

@projects_bp.route('/<string:project_slug>/ethical_approvals/<int:ea_id>/unlink', methods=['POST'])
@login_required
def unlink_ethical_approval(project_slug, ea_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to modify linked ethical approvals for this project.'), 'danger')
        abort(403)
    if project.is_archived:
        flash(_l("Cannot unlink ethical approvals from an archived project."), "warning")
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    try:
        success = project_service.unlink_ethical_approval(project, ea_id)
        if success:
            flash(_l('Ethical Approval unlinked successfully.'), 'success')
        else:
            flash(_l('Ethical Approval not found or not linked to this project.'), 'warning')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('projects.view_edit_project', project_slug=project.slug) + '#collapseEthicalApprovals')

@projects_bp.route('/<string:project_slug>/delete_project_cascade', methods=['POST'])
@login_required
def delete_project_cascade(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()

    if not user_has_permission(current_user, 'Project', 'delete'):
        flash(_l("You do not have permission to delete this project."), "danger")
        abort(403)

    project_name = project.name
    try:
        project_service.delete_project_fully(project)
        flash(_l('Project "%(name)s" and all its related groups and datatables have been permanently deleted.', name=project_name), 'success')
        current_app.logger.info(f"Super admin deleted project '{project_name}' (Slug: {project_slug}) and its related data.")
        return redirect(url_for('projects.list_projects'))
    except Exception as e:
        db.session.rollback()
        flash(_l('Error deleting project: %(error)s', error=str(e)), 'danger')
        current_app.logger.error(f"Error during cascade delete of project {project.slug}: {e}", exc_info=True)
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

@projects_bp.route('/manageable_projects_for_team/<int:team_id>', methods=['GET'])
@login_required
def api_get_manageable_projects_for_team(team_id):
    exclude_project_id_str = request.args.get('exclude_project_id')
    exclude_project_id = None
    if exclude_project_id_str and exclude_project_id_str.isdigit():
        exclude_project_id = int(exclude_project_id_str)
    
    projects_list = get_manageable_projects_for_team(team_id, current_project_id_to_exclude=exclude_project_id)
    
    return jsonify(projects=[
        {'id': p.id, 'name': p.name, 'slug': p.slug} 
        for p in projects_list
    ])

@projects_bp.route('/<string:project_slug>/permissions/team/<int:team_id>', methods=['GET'])
@login_required
def get_team_permissions(project_slug, team_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        return jsonify({'error': 'Permission denied'}), 403

    perm = ProjectTeamShare.query.filter_by(project_id=project.id, team_id=team_id).first()
    if perm:
        return jsonify({
            'can_view_project': perm.can_view_project,
            'can_view_exp_groups': perm.can_view_exp_groups,
            'can_view_datatables': perm.can_view_datatables,
            'can_view_samples': perm.can_view_samples,
            'can_create_exp_groups': perm.can_create_exp_groups,
            'can_edit_exp_groups': perm.can_edit_exp_groups,
            'can_delete_exp_groups': perm.can_delete_exp_groups,
            'can_create_datatables': perm.can_create_datatables,
            'can_edit_datatables': perm.can_edit_datatables,
            'can_delete_datatables': perm.can_delete_datatables,
            'can_view_unblinded_data': perm.can_view_unblinded_data
        })
    return jsonify({})

@projects_bp.route('/<string:project_slug>/permissions/user/<int:user_id>', methods=['GET'])
@login_required
def get_user_permissions(project_slug, user_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        return jsonify({'error': 'Permission denied'}), 403

    perm = ProjectUserShare.query.filter_by(project_id=project.id, user_id=user_id).first()
    if perm:
        return jsonify({
            'can_view_project': perm.can_view_project,
            'can_view_exp_groups': perm.can_view_exp_groups,
            'can_view_datatables': perm.can_view_datatables,
            'can_view_samples': perm.can_view_samples,
            'can_create_exp_groups': perm.can_create_exp_groups,
            'can_edit_exp_groups': perm.can_edit_exp_groups,
            'can_delete_exp_groups': perm.can_delete_exp_groups,
            'can_create_datatables': perm.can_create_datatables,
            'can_edit_datatables': perm.can_edit_datatables,
            'can_delete_datatables': perm.can_delete_datatables,
            'can_view_unblinded_data': perm.can_view_unblinded_data
        })
    return jsonify({})

@projects_bp.route('/<string:project_slug>/share', methods=['POST'])
@login_required
def share_project(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to share this project.'), 'danger')
        abort(403)

    share_type = request.form.get('share_type')
    current_app.logger.debug(f"--- SHARE PROJECT ---")
    current_app.logger.debug(f"Share Type: {share_type}")
    current_app.logger.debug(f"Form Data: {request.form.to_dict()}")

    if share_type == 'user':
        form = ShareProjectForm(project=project, prefix='user')
    elif share_type == 'team':
        form = ShareProjectForm(project=project, prefix='team')
    else:
        flash(_l('Invalid share type specified.'), 'danger')
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    form.share_type.data = share_type

    if form.validate_on_submit():
        current_app.logger.debug(f"Form validation successful.")
        current_app.logger.debug(f"Form Data (processed by WTForms): {form.data}")

        if share_type == 'team':
            target_id = form.team_to_share.data
            share = ProjectTeamShare.query.filter_by(project_id=project.id, team_id=target_id).first()
            team_name = db.session.get(Team, target_id).name
            if not share:
                share = ProjectTeamShare(project_id=project.id, team_id=target_id)
                db.session.add(share)
            flash_message = _l('Project sharing permissions updated for team "%(name)s".', name=team_name)
        
        else: # share_type == 'user'
            target_id = form.user_to_share.data
            share = ProjectUserShare.query.filter_by(project_id=project.id, user_id=target_id).first()
            user_email = db.session.get(User, target_id).email
            if not share:
                share = ProjectUserShare(project_id=project.id, user_id=target_id)
                db.session.add(share)
            flash_message = _l('Project sharing permissions updated for user "%(email)s".', email=user_email)
            
        # Apply all permissions from the validated form
        share.can_view_project = form.can_view_project.data
        share.can_view_exp_groups = form.can_view_exp_groups.data
        share.can_view_datatables = form.can_view_datatables.data
        share.can_view_samples = form.can_view_samples.data
        share.can_create_exp_groups = form.can_create_exp_groups.data
        share.can_edit_exp_groups = form.can_edit_exp_groups.data
        share.can_delete_exp_groups = form.can_delete_exp_groups.data
        share.can_create_datatables = form.can_create_datatables.data
        share.can_edit_datatables = form.can_edit_datatables.data
        share.can_delete_datatables = form.can_delete_datatables.data
        share.can_view_unblinded_data = form.can_view_unblinded_data.data

        current_app.logger.debug(f"SAVING SHARE: View Groups = {share.can_view_exp_groups}, View Tables = {share.can_view_datatables}")

        project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        try:
            db.session.commit()
            flash(flash_message, 'success')
        except Exception as e:
            db.session.rollback()
            flash(_l('Error updating project sharing: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error sharing project {project.slug} with {share_type} {target_id}: {e}")
    else:
        current_app.logger.error(f"Form validation FAILED. Errors: {form.errors}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", 'danger')

    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

@projects_bp.route('/<string:project_slug>/unshare_with_team/<int:team_id>', methods=['POST'])
@login_required
def unshare_with_team(project_slug, team_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to unshare this project.'), 'danger')
        abort(403)

    share_to_delete = ProjectTeamShare.query.filter_by(project_id=project.id, team_id=team_id).first()
    if share_to_delete:
        team_name = share_to_delete.team.name
        db.session.delete(share_to_delete)
        project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        try:
            db.session.commit()
            flash(_l('Project unshared from team "%(team_name)s" successfully.', team_name=team_name), 'success')
        except Exception as e:
            db.session.rollback()
            flash(_l('Error unsharing project: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error unsharing project {project.slug} from team {team_id}: {e}")
    else:
        flash(_l('Project was not shared with this team.'), 'info')

    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))


@projects_bp.route('/<string:project_slug>/unshare_with_user/<int:user_id>', methods=['POST'])
@login_required
def unshare_with_user(project_slug, user_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    if not check_project_permission(project, 'edit'):
        flash(_l('You do not have permission to unshare this project.'), 'danger')
        abort(403)

    share_to_delete = ProjectUserShare.query.filter_by(project_id=project.id, user_id=user_id).first()
    if share_to_delete:
        user_email = share_to_delete.user.email
        db.session.delete(share_to_delete)
        project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        try:
            db.session.commit()
            flash(_l('Project unshared from user "%(user_email)s" successfully.', user_email=user_email), 'success')
        except Exception as e:
            db.session.rollback()
            flash(_l('Error unsharing project: %(error)s', error=str(e)), 'danger')
            current_app.logger.error(f"Error unsharing project {project.slug} from user {user_id}: {e}")
    else:
        flash(_l('Project was not shared with this user.'), 'info')

    return redirect(url_for('projects.view_edit_project', project_slug=project.slug))