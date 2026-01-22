# app/services/permission_service.py
from flask import current_app, g  # Import current_app for logging

from app.extensions import db
from app.models import (Project, ProjectTeamShare, ProjectUserShare,
                        user_has_permission)


class PermissionService:
    """
    Centralizes logic to determine what a user can do on a Project
    and its children (Groups, DataTables).
    """

    def get_effective_project_permissions(self, user, project):
        """
        Returns a dict of boolean flags representing what the user can do 
        on this specific project.
        """
        # --- Request-Level Caching ---
        cache_key = f"perms_{user.id}_{project.id}"
        if not hasattr(g, 'permission_cache'):
            g.permission_cache = {}
        
        if cache_key in g.permission_cache:
            # current_app.logger.debug(f"-> Serving permissions from cache for '{user.email}' on '{project.name}'")
            return g.permission_cache[cache_key]
            
        current_app.logger.debug(f"--- PERM CHECK for User '{user.email}' on Project '{project.name}' ---")

        perms = {
            'can_view_project': False,
            'can_view_exp_groups': False,
            'can_view_datatables': False,
            'can_view_samples': False,
            'can_create_exp_groups': False,
            'can_edit_exp_groups': False,
            'can_delete_exp_groups': False,
            'can_create_datatables': False,
            'can_edit_datatables': False,
            'can_delete_datatables': False,
            'can_view_unblinded_data': False,
            'is_owner_team_member': False, # Meta flag
            'is_admin': False # Can manage project settings/shares
        }

        if not user or not user.is_authenticated:
            current_app.logger.debug("-> User not authenticated. Returning all False.")
            return perms

        if user.is_super_admin:
            current_app.logger.debug("-> User is Super Admin. Granting all permissions.")
            return {k: True for k in perms}

        user_teams = user.get_teams()
        if project.team in user_teams:
            perms['is_owner_team_member'] = True
            # If user has general 'Project:read' for the team, grant all read permissions
            if user_has_permission(user, 'Project', 'read', team_id=project.team_id):
                perms['can_view_project'] = True
                perms['can_view_exp_groups'] = True
                perms['can_view_datatables'] = True
                perms['can_view_samples'] = True

            perms['is_admin'] = user_has_permission(user, 'Project', 'edit', team_id=project.team_id) # Can edit project settings
            
            perms['can_create_exp_groups'] = user_has_permission(user, 'ExperimentalGroup', 'create', team_id=project.team_id)
            perms['can_edit_exp_groups'] = user_has_permission(user, 'ExperimentalGroup', 'edit', team_id=project.team_id)
            perms['can_delete_exp_groups'] = user_has_permission(user, 'ExperimentalGroup', 'delete', team_id=project.team_id)
            
            perms['can_create_datatables'] = user_has_permission(user, 'DataTable', 'create', team_id=project.team_id)
            perms['can_edit_datatables'] = user_has_permission(user, 'DataTable', 'edit_datatable', team_id=project.team_id)
            perms['can_delete_datatables'] = user_has_permission(user, 'DataTable', 'delete_datatable', team_id=project.team_id)
            
            perms['can_view_unblinded_data'] = user_has_permission(user, 'Project', 'view_unblinded_data', team_id=project.team_id)
            current_app.logger.debug(f"-> User is on owning team '{project.team.name}'. Initial RBAC perms: {perms}")

        user_share = ProjectUserShare.query.filter_by(project_id=project.id, user_id=user.id).first()
        if user_share:
            current_app.logger.debug(f"-> Found direct user share for '{user.email}'. Applying additive permissions.")
            self._apply_share_mixin(perms, user_share)

        if user_teams:
            user_team_ids = [t.id for t in user_teams]
            team_shares = ProjectTeamShare.query.filter(
                ProjectTeamShare.project_id == project.id, 
                ProjectTeamShare.team_id.in_(user_team_ids)
            ).all()
            for share in team_shares:
                current_app.logger.debug(f"-> Found team share for user's team '{share.team.name}'. Applying additive permissions.")
                self._apply_share_mixin(perms, share)

        current_app.logger.debug(f"--- FINAL PERMS for '{user.email}' on '{project.name}': {perms} ---")
        g.permission_cache[cache_key] = perms
        return perms

    def _apply_share_mixin(self, perms_dict, share_obj):
        """Merges share flags into the permissions dict (OR logic)."""
        perms_dict['can_view_project'] = perms_dict['can_view_project'] or share_obj.can_view_project
        perms_dict['can_view_exp_groups'] = perms_dict['can_view_exp_groups'] or share_obj.can_view_exp_groups
        perms_dict['can_view_datatables'] = perms_dict['can_view_datatables'] or share_obj.can_view_datatables
        perms_dict['can_view_samples'] = perms_dict['can_view_samples'] or share_obj.can_view_samples
        perms_dict['can_create_exp_groups'] = perms_dict['can_create_exp_groups'] or share_obj.can_create_exp_groups
        perms_dict['can_edit_exp_groups'] = perms_dict['can_edit_exp_groups'] or share_obj.can_edit_exp_groups
        perms_dict['can_delete_exp_groups'] = perms_dict['can_delete_exp_groups'] or share_obj.can_delete_exp_groups
        perms_dict['can_create_datatables'] = perms_dict['can_create_datatables'] or share_obj.can_create_datatables
        perms_dict['can_edit_datatables'] = perms_dict['can_edit_datatables'] or share_obj.can_edit_datatables
        perms_dict['can_delete_datatables'] = perms_dict['can_delete_datatables'] or share_obj.can_delete_datatables
        perms_dict['can_view_unblinded_data'] = perms_dict['can_view_unblinded_data'] or share_obj.can_view_unblinded_data

    def get_visible_projects_query(self, user):
        """
        Returns a SQLAlchemy query for all projects visible to the given user.
        Optimized for dashboards/lists to avoid N+1 permission checks.
        """
        from sqlalchemy import or_

        # 1. Super Admin sees everything
        if user.is_super_admin:
            return Project.query

        # 2. Get User's Team IDs
        # We assume user.teams is a relationship returning Team objects
        # We need IDs for the IN clause
        user_team_ids = [t.id for t in user.get_teams()] # Use get_teams() method

        # 3. Construct Filter
        query = Project.query.outerjoin(
            ProjectUserShare, 
            (ProjectUserShare.project_id == Project.id) & (ProjectUserShare.user_id == user.id)
        ).outerjoin(
            ProjectTeamShare, 
            (ProjectTeamShare.project_id == Project.id) & (ProjectTeamShare.team_id.in_(user_team_ids) if user_team_ids else False)
        )

        filter_condition = or_(
            # A. Owned by User's Team
            Project.team_id.in_(user_team_ids) if user_team_ids else False,
            
            # B. Direct User Share exist
            ProjectUserShare.project_id.isnot(None),
            
            # C. Team Share exist
            ProjectTeamShare.project_id.isnot(None)
        )
        
        return query.filter(filter_condition)

    def get_bulk_project_permissions(self, user, projects):
        """
        Get permissions for multiple projects at once - Optimized.
        """
        results = {}
        
        # 0. Request-Level Cache Setup
        if not hasattr(g, 'permission_cache'):
            g.permission_cache = {}
            
        projects_to_process = []
        
        # 1. Check Cache
        for project in projects:
            cache_key = f"perms_{user.id}_{project.id}"
            if cache_key in g.permission_cache:
                results[project.id] = g.permission_cache[cache_key]
            else:
                projects_to_process.append(project)

        if not projects_to_process:
            return results

        # 2. Super Admin Check
        if user.is_super_admin:
             # Fast fill for all
             for p in projects_to_process:
                 cache_key = f"perms_{user.id}_{p.id}"
                 # Generate full True dict
                 mock_full = self.get_effective_project_permissions(user, p)
                 g.permission_cache[cache_key] = mock_full
                 results[p.id] = mock_full
             return results
        
        # 3. Batch Fetch Info
        project_ids = [p.id for p in projects_to_process]
        user_teams = user.get_teams()
        user_team_ids = [t.id for t in user_teams]
        
        # A. User Shares
        user_shares_map = {}
        if project_ids:
            u_shares = ProjectUserShare.query.filter(
                ProjectUserShare.project_id.in_(project_ids),
                ProjectUserShare.user_id == user.id
            ).all()
            for s in u_shares:
                user_shares_map[s.project_id] = s
            
        # B. Team Shares
        team_shares_map = {} # project_id -> list of shares
        if project_ids and user_team_ids:
            t_shares = ProjectTeamShare.query.filter(
                 ProjectTeamShare.project_id.in_(project_ids),
                 ProjectTeamShare.team_id.in_(user_team_ids)
            ).all()
            for s in t_shares:
                if s.project_id not in team_shares_map:
                    team_shares_map[s.project_id] = []
                team_shares_map[s.project_id].append(s)

        # 4. Compute In-Memory
        for project in projects_to_process:
            cache_key = f"perms_{user.id}_{project.id}"
            
            perms = {
                'can_view_project': False,
                'can_view_exp_groups': False,
                'can_view_datatables': False,
                'can_view_samples': False,
                'can_create_exp_groups': False,
                'can_edit_exp_groups': False,
                'can_delete_exp_groups': False,
                'can_create_datatables': False,
                'can_edit_datatables': False,
                'can_delete_datatables': False,
                'can_view_unblinded_data': False,
                'is_owner_team_member': False,
                'is_admin': False 
            }
            
            # Team Membership Logic
            if project.team_id in user_team_ids:
                perms['is_owner_team_member'] = True
                if user_has_permission(user, 'Project', 'read', team_id=project.team_id):
                    perms['can_view_project'] = True
                    perms['can_view_exp_groups'] = True
                    perms['can_view_datatables'] = True
                    perms['can_view_samples'] = True

                perms['is_admin'] = user_has_permission(user, 'Project', 'edit', team_id=project.team_id)
                perms['can_create_exp_groups'] = user_has_permission(user, 'ExperimentalGroup', 'create', team_id=project.team_id)
                perms['can_edit_exp_groups'] = user_has_permission(user, 'ExperimentalGroup', 'edit', team_id=project.team_id)
                perms['can_delete_exp_groups'] = user_has_permission(user, 'ExperimentalGroup', 'delete', team_id=project.team_id)
                perms['can_create_datatables'] = user_has_permission(user, 'DataTable', 'create', team_id=project.team_id)
                perms['can_edit_datatables'] = user_has_permission(user, 'DataTable', 'edit_datatable', team_id=project.team_id)
                perms['can_delete_datatables'] = user_has_permission(user, 'DataTable', 'delete_datatable', team_id=project.team_id)
                perms['can_view_unblinded_data'] = user_has_permission(user, 'Project', 'view_unblinded_data', team_id=project.team_id)

            # Apply User Share
            if project.id in user_shares_map:
                self._apply_share_mixin(perms, user_shares_map[project.id])
            
            # Apply Team Shares
            if project.id in team_shares_map:
                for share in team_shares_map[project.id]:
                    self._apply_share_mixin(perms, share)

            g.permission_cache[cache_key] = perms
            results[project.id] = perms
            
        return results
