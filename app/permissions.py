# app/permissions.py
"""
This module defines the permission checking functions for the application.
It uses the PermissionService to determine effective permissions based on
ownership and sharing.
"""
from flask import abort, current_app
from flask_login import current_user

from app.services.permission_service import PermissionService

from .extensions import db
from .models import (DataTable, ExperimentalGroup, Project, ReferenceRange,
                     user_has_permission, User)

perm_service = PermissionService()

# A hardcoded list of all resources and actions in the application.
AVAILABLE_PERMISSIONS = {
    'Project': [
        'read', 'create', 'edit', 'delete', 'archive', 'view_unblinded_data'
    ],
    'ExperimentalGroup': [
        'read', 'create', 'edit', 'delete', 'archive_exp_group', 'edit_exp_group',
        'delete_exp_group'
    ],
    'DataTable': [
        'read', 'create', 'edit', 'delete', 'edit_datatable', 'delete_datatable'
    ],
    'Analyte': ['view', 'create', 'edit', 'delete'],
    'EthicalApproval': ['view', 'create', 'edit', 'delete'],
    'CoreModel': ['read', 'create', 'edit', 'delete'],
    'ReferenceRange': ['view', 'create', 'edit', 'delete'],
    'Storage': ['view', 'create', 'edit', 'delete'],
    'Workplan': ['view', 'create', 'edit', 'delete'],
    'Resource': ['view', 'create', 'edit', 'delete'],
    'Team': ['view', 'create', 'edit', 'delete', 'manage_members'],
    'Role': ['view', 'create', 'edit', 'delete'],
    'User': ['view', 'create', 'edit', 'delete'],
    'ControlledMolecule': ['view', 'create', 'edit', 'delete'],
    'ImportPipeline': ['view', 'create', 'edit', 'delete']
}

def check_project_permission(project_or_id, action, allow_abort=True):
    """
    Checks if the current user has permission to perform an action on a project.
    """
    if not current_user.is_authenticated:
        if allow_abort: abort(403)
        return False

    if isinstance(project_or_id, Project):
        project = project_or_id
    else:
        project = db.session.get(Project, project_or_id)

    if not project:
        if allow_abort: abort(404)
        return False

    perms = perm_service.get_effective_project_permissions(current_user, project)
    
    allowed = False
    if action == 'read':
        allowed = perms['can_view_project']
    elif action == 'edit': # Project Settings / Metadata
        allowed = perms['is_admin']
    elif action == 'archive' or action == 'delete':
        allowed = perms['is_admin']
    
    if not allowed and allow_abort:
        abort(403)
    return allowed


def check_group_permission(group_or_id, action, allow_abort=True):
    """Checks if the current user has permission to perform an action on a group."""
    if not current_user.is_authenticated:
        if allow_abort: abort(403)
        return False
        
    if isinstance(group_or_id, ExperimentalGroup):
        group = group_or_id
    else:
        group = db.session.get(ExperimentalGroup, group_or_id)
        
    if not group or not group.project:
        if allow_abort: abort(404)
        return False
    
    perms = perm_service.get_effective_project_permissions(current_user, group.project)
    
    allowed = False
    if action == 'read': allowed = perms['can_view_exp_groups']
    elif action == 'create': allowed = perms['can_create_exp_groups']
    elif action == 'edit_exp_group': allowed = perms['can_edit_exp_groups']
    elif action == 'delete_exp_group': allowed = perms['can_delete_exp_groups']
    elif action == 'archive_exp_group': allowed = perms['can_edit_exp_groups'] # Archive treated as edit
    
    if allowed: return True
    if allow_abort: abort(403)
    return False


def check_datatable_permission(datatable_or_id, action, allow_abort=True, user_id=None):
    """Checks if the current user has permission to perform an action on a datatable."""
    _user = None
    if user_id:
        _user = db.session.get(User, user_id)
        if not _user: # User not found
            if allow_abort: abort(403)
            return False
    else:
        _user = current_user

    if not _user or not _user.is_authenticated:
        if allow_abort: abort(403)
        return False
        
    if isinstance(datatable_or_id, DataTable):
        datatable = datatable_or_id
    else:
        datatable = db.session.get(DataTable, datatable_or_id)
        
    if not datatable or not datatable.group or not datatable.group.project:
        if allow_abort: abort(404)
        return False
    
    perms = perm_service.get_effective_project_permissions(_user, datatable.group.project)
    
    allowed = False
    if action == 'read': allowed = perms['can_view_datatables']
    elif action == 'create': allowed = perms['can_create_datatables']
    elif action == 'edit_datatable': allowed = perms['can_edit_datatables']
    elif action == 'delete_datatable': allowed = perms['can_delete_datatables']
    
    if allowed: return True
    if allow_abort: abort(403)
    return False

def can_create_datatable_for_group(group_or_id):
    """Checks if the current user can create a datatable for a group."""
    try:
        if isinstance(group_or_id, ExperimentalGroup):
            group = group_or_id
        else:
            group = db.session.get(ExperimentalGroup, group_or_id)
        if not group or not group.project:
            return False
        
        perms = perm_service.get_effective_project_permissions(current_user, group.project)
        return perms['can_create_datatables']
    except Exception:
        return False

def can_create_group_for_project(project_or_id):
    """Checks if the current user can create a group for a project."""
    try:
        if isinstance(project_or_id, Project):
            project = project_or_id
        else:
            project = db.session.get(Project, project_or_id)
        if not project:
            return False
        
        perms = perm_service.get_effective_project_permissions(current_user, project)
        return perms['can_create_exp_groups']
    except Exception:
        return False

def can_view_unblinded_data(group):
    """Checks if the current user can view unblinded data for a group."""
    try:
        if not current_user.is_authenticated:
            return False
        if current_user.is_super_admin:
            return True
        if not group or not group.project:
            return False
        
        perms = perm_service.get_effective_project_permissions(current_user, group.project)
        return perms['can_view_unblinded_data']
    except Exception:
        return False

# Keep existing helpers for ReferenceRange/Admin as they rely on Team permissions directly
def can_edit_reference_range(reference_range_id):
    try:
        ref_range = db.session.get(ReferenceRange, reference_range_id)
        if not ref_range: return False
        return user_has_permission(current_user, 'ReferenceRange', 'edit', team_id=ref_range.team_id)
    except Exception: return False

def can_view_reference_range(reference_range_id):
    try:
        ref_range = db.session.get(ReferenceRange, reference_range_id)
        if not ref_range: return False
        return user_has_permission(current_user, 'ReferenceRange', 'view', team_id=ref_range.team_id)
    except Exception: return False

def is_admin_or_super_admin(team_id=None):
    if not current_user.is_authenticated: return False
    if current_user.is_super_admin: return True
    if team_id: return user_has_permission(current_user, 'Team', 'manage_members', team_id=team_id)
    return False