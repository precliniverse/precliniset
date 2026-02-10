# app/queries/project_query.py
"""
Custom Query class for Project model.
Implements chainable methods for filtering projects.
"""
from sqlalchemy import or_

from app.extensions import db


class ProjectQuery(db.Query):
    """
    Custom query class for Project model.
    Provides chainable methods for filtering projects.
    """
    
    def active(self):
        """Filter out archived projects."""
        # Import deferred to avoid circular imports
        from app.models import Project
        return self.filter(Project.is_archived == False)
    
    def search(self, term):
        """
        Search projects by name, description, or slug.
        :param term: Search term string
        """
        if not term:
            return self
        
        from app.models import Project
        search_pattern = f"%{term}%"
        return self.filter(
            or_(
                Project.name.ilike(search_pattern),
                Project.description.ilike(search_pattern),
                Project.slug.ilike(search_pattern)
            )
        )
    
    def accessible_by(self, user):
        """
        Filter projects accessible to the given user.
        
        Access rules:
        1. Super Admin sees all projects
        2. User can see projects owned by their teams (if they have Project:read permission)
        3. User can see projects shared with their teams (via ProjectTeamShare)
        4. User can see projects shared directly with them (via ProjectUserShare)
        
        :param user: User object
        """
        from app.models import (
            Project, ProjectTeamShare, ProjectUserShare,
            UserTeamRoleLink, Role, role_permissions, Permission
        )
        
        if not user or not user.is_authenticated:
            # Return empty query for unauthenticated users
            return self.filter(db.literal(False))
        
        if user.is_super_admin:
            # Super admin sees everything
            return self
        
        # Get user's team IDs
        user_teams = user.get_teams()
        user_team_ids = [team.id for team in user_teams]
        
        if not user_team_ids:
            # User has no teams, check for direct shares only
            return self._filter_by_direct_shares(user.id)
        
        # Check for Project:read permission on owned teams
        # A project is "owned" by a user if:
        # - The user is a member of the team that owns the project
        # - AND the user has 'Project:read' permission for that team
        
        has_project_read_permission = db.session.query(db.literal(1)).select_from(
            UserTeamRoleLink
        ).join(Role).join(role_permissions).join(Permission).filter(
            UserTeamRoleLink.user_id == user.id,
            Permission.resource == 'Project',
            Permission.action == 'read',
            UserTeamRoleLink.team_id == Project.team_id,
            or_(Role.team_id == Project.team_id, Role.team_id.is_(None))
        ).exists()
        
        # Subquery for projects owned by user's teams WITH read permission
        owned_projects_subq = db.session.query(Project.id).filter(
            Project.team_id.in_(user_team_ids),
            has_project_read_permission
        ).union(
            # Subquery for projects shared with user's teams
            db.session.query(ProjectTeamShare.project_id).filter(
                ProjectTeamShare.team_id.in_(user_team_ids),
                ProjectTeamShare.can_view_project == True
            ),
            # Subquery for projects shared directly with user
            db.session.query(ProjectUserShare.project_id).filter(
                ProjectUserShare.user_id == user.id,
                ProjectUserShare.can_view_project == True
            )
        )
        
        return self.filter(Project.id.in_(owned_projects_subq))
    
    def _filter_by_direct_shares(self, user_id):
        """
        Internal: Filter only by direct user shares (no team membership).
        """
        from app.models import ProjectUserShare
        return self.join(
            ProjectUserShare,
            (ProjectUserShare.project_id == Project.id) & (ProjectUserShare.user_id == user_id)
        ).filter(
            ProjectUserShare.can_view_project == True
        )
    
    def with_relations(self):
        """
        Eagerly load common relations to prevent N+1 queries.
        """
        from app.models import Project
        return self.options(
            db.selectinload(Project.team),
            db.selectinload(Project.owner),
            db.selectinload(Project.groups),
        )
