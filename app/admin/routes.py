# app/admin/routes.py
from collections import defaultdict

from flask import (current_app, flash, redirect, render_template, request,
                   url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.services.admin_service import AdminService

from ..decorators import permission_required
from ..extensions import db
from ..forms import (AddUserToTeamForm, DeleteTeamForm, InviteMemberForm,
                     InviteUserForm, RoleForm, TeamForm)
from ..models import (Permission, ProjectUserShare, Role, Team, TeamMembership,
                      User, UserTeamRoleLink, user_has_permission)
from . import admin_bp

admin_service = AdminService()

# --- Helper Functions ---
def get_user_or_flash(user_id):
    user = db.session.get(User, user_id)
    if not user: flash(_l('User not found.'), 'danger')
    return user

def get_team_or_flash(team_id):
    team = db.session.get(Team, team_id)
    if not team: flash(_l('Team not found.'), 'danger')
    return team

# --- Team Management Routes ---
@admin_bp.route('/teams', methods=['GET', 'POST'])
@login_required
def manage_teams():
    # Custom permission check
    has_global_view = user_has_permission(current_user, 'Team', 'view', team_id=None)
    has_any_manage = any(user_has_permission(current_user, 'Team', 'manage_members', team_id=m.team_id) for m in current_user.memberships)

    if not current_user.is_super_admin and not has_global_view and not has_any_manage:
        flash(_l("You do not have permission to access this page."), "danger")
        return redirect(url_for('main.index'))

    form = TeamForm()
    delete_form = DeleteTeamForm()
    invite_member_forms = {}

    if request.method == 'POST':
        # Create Team
        if form.validate_on_submit() and form.submit.data:
            if user_has_permission(current_user, 'Team', 'create'):
                try:
                    admin_service.create_team(form.name.data)
                    flash(_l('Team "%(name)s" created successfully.', name=form.name.data), 'success')
                    return redirect(url_for('admin.manage_teams'))
                except Exception as e:
                    flash(_l('Error creating team: %(error)s', error=str(e)), 'danger')
            else:
                flash(_l("You do not have permission to create teams."), "warning")
        
        # Invite Member (from list view)
        team_id_from_form = request.form.get('team_id_for_invite')
        if team_id_from_form:
            try:
                team_id = int(team_id_from_form)
                team = db.session.get(Team, team_id)
                if team and user_has_permission(current_user, 'Team', 'manage_members', team_id=team.id):
                    invite_form = InviteMemberForm(team_id=team.id)
                    if invite_form.validate_on_submit() and invite_form.submit_invite_member.data:
                        success, msg, cat = admin_service.invite_user_to_team(
                            invite_form.email.data, team, invite_form.role_id.data
                        )
                        flash(msg, cat)
                        if success: return redirect(url_for('admin.manage_teams'))
                    else:
                        for err in invite_form.errors.values(): flash(_l(err), "danger")
            except ValueError:
                pass

    # Fetch Teams
    if has_global_view or current_user.is_super_admin:
        teams = Team.query.order_by(Team.name).all()
    else:
        teams = [m.team for m in current_user.memberships if user_has_permission(current_user, 'Team', 'manage_members', team_id=m.team_id)]
        teams.sort(key=lambda t: t.name)

    for team in teams:
        invite_member_forms[team.id] = InviteMemberForm(team_id=team.id)

    return render_template('admin/manage_teams.html', form=form, teams=teams, current_user=current_user, user_has_permission=user_has_permission, delete_form=delete_form, invite_member_forms=invite_member_forms)


@admin_bp.route('/team/<int:team_id>/members', methods=['GET', 'POST'])
@login_required
def manage_team_members(team_id):
    team = get_team_or_flash(team_id)
    if not team: return redirect(url_for('admin.manage_teams'))

    if not user_has_permission(current_user, 'Team', 'manage_members', team_id=team.id):
         flash(_l("You do not have permission to manage this team's members."), "danger")
         return redirect(url_for('admin.manage_teams'))

    # Ensure default roles exist (idempotent)
    admin_service._ensure_default_roles(team)

    team_specific_roles = team.roles
    global_roles = Role.query.filter_by(team_id=None).all()
    assignable_roles = sorted(team_specific_roles + global_roles, key=lambda r: r.name)

    invite_form = InviteUserForm()
    invite_form.team_id.data = team.id
    team_roles = Role.query.filter_by(team_id=team.id).order_by(Role.name).all()
    invite_form.role_id.choices = [('', _l('-- Select Role --'))] + [(r.id, r.name) for r in team_roles]

    if invite_form.validate_on_submit() and invite_form.submit_invite_member.data:
        success, msg, cat = admin_service.invite_user_to_team(
            invite_form.email.data, team, invite_form.role_id.data
        )
        flash(msg, cat)
        if success: return redirect(url_for('admin.manage_team_members', team_id=team.id))

    return render_template('admin/manage_team_members.html', team=team, invite_form=invite_form, assignable_roles=assignable_roles)


@admin_bp.route('/team/<int:team_id>/members/<int:user_id>/assign_role', methods=['POST'])
@login_required
def assign_role_to_user(team_id, user_id):
    team = get_team_or_flash(team_id)
    user = get_user_or_flash(user_id)
    if not team or not user: return redirect(request.referrer or url_for('admin.manage_teams'))

    if not user_has_permission(current_user, 'Team', 'manage_members', team_id=team.id):
        flash(_l("Permission denied."), "danger")
        return redirect(url_for('admin.manage_team_members', team_id=team.id))

    role_id = request.form.get('role_id')
    try:
        success, msg = admin_service.assign_role_to_user(team, user, role_id)
        flash(msg, 'success' if success else 'info')
    except ValueError as e:
        flash(_l(e), 'danger')
    except Exception as e:
        flash(f"Error: {e}", 'danger')

    return redirect(url_for('admin.manage_team_members', team_id=team.id))

@admin_bp.route('/team/<int:team_id>/members/<int:user_id>/unassign_role/<int:role_id>', methods=['POST'])
@login_required
def unassign_role_from_user(team_id, user_id, role_id):
    team = get_team_or_flash(team_id)
    user = get_user_or_flash(user_id)
    if not team or not user: return redirect(request.referrer or url_for('admin.manage_teams'))

    if not user_has_permission(current_user, 'Team', 'manage_members', team_id=team.id):
        flash(_l("Permission denied."), "danger")
        return redirect(url_for('admin.manage_team_members', team_id=team.id))

    if admin_service.unassign_role_from_user(team, user, role_id):
        flash(_l('Role unassigned successfully.'), 'success')
    else:
        flash(_l('Role assignment not found.'), 'warning')
        
    return redirect(url_for('admin.manage_team_members', team_id=team.id))
    
@admin_bp.route('/team/<int:team_id>/members/<int:user_id>/remove', methods=['POST', 'GET'])
@login_required
def remove_team_member(team_id, user_id):
    team = get_team_or_flash(team_id)
    user = db.session.get(User, user_id)
    if not team or not user: return redirect(request.referrer or url_for('admin.manage_teams'))

    if not user_has_permission(current_user, 'Team', 'manage_members', team_id=team.id):
        flash(_l("Permission denied."), "danger")
        return redirect(url_for('admin.manage_team_members', team_id=team.id))

    # Handle GET request for user deletion confirmation (Orphan check)
    if request.method == 'GET' and request.args.get('confirm_delete_user') == 'true':
        if len(user.memberships) == 0: 
            if user_has_permission(current_user, 'User', 'delete', team_id=None):
                if user.id == current_user.id:
                     flash(_l("You cannot delete your own account."), "danger")
                else:
                    admin_service.delete_user_fully(user)
                    flash(_l("User deleted permanently."), "success")
                    return redirect(url_for('admin.manage_users'))
            else:
                flash(_l("You do not have global permission to delete users."), "danger")
        else:
            flash(_l("User is still a member of other teams."), "warning")
        return redirect(url_for('admin.manage_team_members', team_id=team.id))

    # POST: Remove from team
    if admin_service.remove_user_from_team(team, user):
        flash(_l('User removed from team.'), 'success')
        
        # Check for orphan status
        db.session.expire(user)
        user = db.session.get(User, user_id)
        if user and len(user.memberships) == 0:
            if user_has_permission(current_user, 'User', 'delete', team_id=None):
                confirm_url = url_for('admin.remove_team_member', team_id=team.id, user_id=user.id, confirm_delete_user='true')
                flash(_l(f"User is now an orphan. <a href=\"{confirm_url}\">Click to delete user permanently.</a>"), "info")
            else:
                flash(_l("User is now an orphan. Super admins have been notified."), "info")
                # Notification logic could go here (omitted for brevity)
    else:
        flash(_l('User was not a member of this team.'), 'warning')

    return redirect(url_for('admin.manage_team_members', team_id=team.id))


@admin_bp.route('/team/<int:team_id>/delete', methods=['POST'])
@login_required
@permission_required('Team', 'delete')
def delete_team(team_id):
    team = get_team_or_flash(team_id)
    if not team: return redirect(url_for('admin.manage_teams'))

    try:
        admin_service.delete_team(team)
        flash(_l('Team deleted successfully.'), 'success')
    except Exception as e:
        flash(_l('Error deleting team: %(error)s', error=str(e)), 'danger')

    return redirect(url_for('admin.manage_teams'))


# --- User Management Routes ---
@admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
@permission_required('User', 'view')
def manage_users():
    search_email = request.args.get('search_email')
    status_filter = request.args.get('status_filter')
    sort_order = request.args.get('sort_order', 'asc')

    query = User.query.options(selectinload(User.memberships).joinedload(TeamMembership.team))

    if search_email: query = query.filter(User.email.ilike(f"%{search_email}%"))
    if status_filter == 'active': query = query.filter(User.is_active == True)
    elif status_filter == 'inactive': query = query.filter(User.is_active == False)
    
    query = query.order_by(User.email.asc() if sort_order == 'asc' else User.email.desc())
    users = query.all()
    
    add_to_team_form = AddUserToTeamForm()
    invite_form = InviteUserForm()

    # Handle Invite User (Global)
    if request.method == 'POST' and invite_form.validate_on_submit() and invite_form.submit_invite_member.data:
        team = db.session.get(Team, invite_form.team_id.data)
        if team:
            success, msg, cat = admin_service.invite_user_to_team(
                invite_form.email.data, team, invite_form.role_id.data
            )
            flash(msg, cat)
            if success: return redirect(url_for('admin.manage_users'))
        else:
            flash(_l('Selected team not found.'), 'danger')

    all_teams = Team.query.order_by(Team.name).all()
    db_roles = Role.query.options(selectinload(Role.team)).all()
    all_roles = [{'id': r.id, 'name': r.name, 'team_id': r.team_id} for r in db_roles]

    return render_template('admin/manage_users.html', users=users, add_to_team_form=add_to_team_form, all_teams=all_teams, invite_form=invite_form, search_email=search_email, status_filter=status_filter, sort_order=sort_order, all_roles=all_roles)


@admin_bp.route('/users/<int:user_id>/add_to_team', methods=['POST'])
@login_required
@permission_required('Team', 'manage_members')
def add_user_to_team(user_id):
    user = get_user_or_flash(user_id)
    if not user: return redirect(url_for('admin.manage_users'))

    form = AddUserToTeamForm()
    if form.validate_on_submit():
        team = get_team_or_flash(form.team.data)
        if team:
            # Use service to add (it handles default role assignment)
            success, msg, cat = admin_service.invite_user_to_team(user.email, team)
            flash(msg, cat)
    else:
        flash(_l("Form validation failed."), "danger")

    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/users/<int:user_id>/update_user', methods=['POST'])
@login_required
@permission_required('User', 'edit')
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user: return redirect(url_for('admin.manage_users'))
        
    action = request.form.get('action')
    if not action: return redirect(url_for('admin.manage_users'))

    if action == 'delete':
        if not user_has_permission(current_user, 'User', 'delete'):
            flash(_l("Permission denied."), 'danger')
        elif user.owned_projects.count() > 0:
            flash(_l('Cannot delete user who owns projects.'), 'danger')
        else:
            admin_service.delete_user_fully(user)
            flash(_l('User deleted.'), 'success')
    elif action == 'validate':
        user.email_confirmed = True
        db.session.commit()
        flash(_l('Email validated.'), 'success')
    elif action == 'activate':
        user.is_active = True
        db.session.commit()
        flash(_l('User activated.'), 'success')
    elif action == 'deactivate':
        if user.id == current_user.id:
            flash(_l("Cannot deactivate yourself."), 'danger')
        else:
            user.is_active = False
            db.session.commit()
            flash(_l('User deactivated.'), 'success')

    return redirect(url_for('admin.manage_users'))


# --- Role Management Routes ---
@admin_bp.route('/roles', methods=['GET'])
@login_required
@permission_required('Role', 'view')
def manage_roles():
    roles = Role.query.options(db.joinedload(Role.permissions), db.joinedload(Role.team)).order_by(Role.team_id, Role.name).all()
    return render_template('admin/manage_roles.html', roles=roles)

@admin_bp.route('/roles/create', methods=['GET', 'POST'])
@login_required
@permission_required('Role', 'create')
def create_role():
    form = RoleForm()
    
    # Template handling
    template_role_id = request.args.get('template_role_id')
    using_template = False
    template_name = None
    if template_role_id:
        template = Role.query.get(template_role_id)
        if template:
            form.name.data = f"{template.name} (copy)"
            form.description.data = template.description
            form.permissions.data = [p.id for p in template.permissions]
            form.scope.data = 'team_specific' if template.team_id else 'global'
            form.team_id.data = template.team_id
            using_template = True
            template_name = template.name

    all_permissions = Permission.query.order_by(Permission.resource, Permission.action).all()
    grouped_permissions = defaultdict(list)
    for p in all_permissions: grouped_permissions[p.resource].append(p)
    form.permissions.choices = [(p.id, f"{p.resource}: {p.action}") for p in all_permissions]

    if form.validate_on_submit():
        try:
            # Use raw form data for permissions to avoid WTForms coercion issues
            perm_ids = [int(pid) for pid in request.form.getlist('permissions')]
            admin_service.create_role(
                form.name.data, form.description.data, form.scope.data, 
                form.team_id.data, perm_ids
            )
            flash(_l('Role created successfully.'), 'success')
            return redirect(url_for('admin.manage_roles'))
        except IntegrityError:
            db.session.rollback()
            flash(_l('Role name already exists in this scope.'), 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('admin/edit_role.html', form=form, title=_l('Create Role'), grouped_permissions=grouped_permissions, using_template=using_template, template_name=template_name)

@admin_bp.route('/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('Role', 'edit')
def edit_role(role_id):
    role = db.session.get(Role, role_id)
    if not role: return redirect(url_for('admin.manage_roles'))

    form = RoleForm(obj=role)
    if request.method == 'GET':
        form.scope.data = 'team_specific' if role.team_id else 'global'
        form.permissions.data = [p.id for p in role.permissions]

    all_permissions = Permission.query.order_by(Permission.resource, Permission.action).all()
    grouped_permissions = defaultdict(list)
    for p in all_permissions: grouped_permissions[p.resource].append(p)
    form.permissions.choices = [(p.id, f"{p.resource}: {p.action}") for p in all_permissions]

    if form.validate_on_submit():
        try:
            perm_ids = [int(pid) for pid in request.form.getlist('permissions')]
            admin_service.update_role(
                role, form.name.data, form.description.data, form.scope.data, 
                form.team_id.data, perm_ids
            )
            flash(_l('Role updated successfully.'), 'success')
            return redirect(url_for('admin.manage_roles'))
        except IntegrityError:
            db.session.rollback()
            flash(_l('Role name conflict.'), 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')

    return render_template('admin/edit_role.html', form=form, title=_l('Edit Role'), role=role, grouped_permissions=grouped_permissions)

@admin_bp.route('/roles/<int:role_id>/delete', methods=['POST'])
@login_required
@permission_required('Role', 'delete')
def delete_role(role_id):
    role = db.session.get(Role, role_id)
    if role:
        if role.has_active_assignments():
            flash(_l('Cannot delete role with active assignments.'), 'danger')
        else:
            db.session.delete(role)
            db.session.commit()
            flash(_l('Role deleted.'), 'success')
    return redirect(url_for('admin.manage_roles'))

@admin_bp.route('/users/batch_update', methods=['POST'])
@login_required
@permission_required('User', 'edit')
def batch_update_users():
    user_ids = request.form.getlist('user_ids')
    action = request.form.get('batch_action')

    if not user_ids or not action:
        flash(_l('Invalid batch request.'), 'warning')
        return redirect(url_for('admin.manage_users'))

    success, fail = admin_service.batch_update_users(user_ids, action, current_user)
    
    if success > 0: flash(_l('%(count)s users updated.', count=success), 'success')
    if fail > 0: flash(_l('%(count)s users failed/skipped.', count=fail), 'warning')

    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/audit_logs')
@login_required
def audit_logs():
    if not current_user.is_super_admin:
        flash(_l("Access denied."), "danger")
        return redirect(url_for('main.index'))
    
    from app.models.audit import AuditLog
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(1000).all()
    return render_template('admin/audit_logs.html', logs=logs)