# app/models/auth.py
"""
Authentication and RBAC models for the Precliniverse application.
Includes User, Role, Permission, and their associations.
"""
import secrets
import hashlib
from datetime import datetime, timezone
from flask import g
from flask_login import UserMixin
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash
from ..extensions import db

# Association table for the many-to-many relationship between Role and Permission
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permission.id'), primary_key=True)
)

class Permission(db.Model):
    __tablename__ = 'permission'
    id = db.Column(db.Integer, primary_key=True)
    resource = db.Column(db.String(100), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint('resource', 'action', name='uq_permission_resource_action'),)

    def __repr__(self):
        return f'<Permission {self.resource}:{self.action}>'

class Role(db.Model):
    __tablename__ = 'role'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(255))
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True, index=True)

    team = db.relationship('Team', back_populates='roles')
    permissions = db.relationship('Permission', secondary=role_permissions,
                                  lazy='subquery', backref=db.backref('roles', lazy=True))

    __table_args__ = (db.UniqueConstraint('name', 'team_id', name='uq_role_name_team'),)

    def has_active_assignments(self):
        if self.team_id:
            count = db.session.query(UserTeamRoleLink).filter_by(team_id=self.team_id, role_id=self.id).count()
            return count > 0
        count = db.session.query(UserTeamRoleLink).filter_by(role_id=self.id).count()
        return count > 0

class UserTeamRoleLink(db.Model):
    __tablename__ = 'user_team_role_link'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)

    user = db.relationship("User", back_populates="team_roles")
    team = db.relationship("Team", back_populates="user_roles")
    role = db.relationship("Role")

# Association tables for user bookmarks
user_my_page_groups = db.Table('user_my_page_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('group_id', db.String(40), db.ForeignKey('experimental_group.id', ondelete='CASCADE'), primary_key=True)
)

user_my_page_datatables = db.Table('user_my_page_datatables',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('datatable_id', db.Integer, db.ForeignKey('data_table.id', ondelete='CASCADE'), primary_key=True)
)

def user_has_permission(user, resource, action, team_id=None, allow_any_team=False):
    """
    Checks if a user has a specific permission with request-level memoization.

    :param user: The user object to check.
    :param resource: The resource name (e.g., 'Project', 'CoreModel').
    :param action: The action name (e.g., 'create', 'edit').
    :param team_id: Optional ID of the team to check against.
    :param allow_any_team: If True and team_id is None, checks if the user has the permission
                          in ANY team (including global roles). If False and team_id is None,
                          only global roles are checked.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_super_admin:
        return True

    # --- CACHING LOGIC START ---
    cache_key = (user.id, resource, action, team_id, allow_any_team)
    
    # Initialize cache if not present (flask.g is unique per request)
    if not hasattr(g, '_permission_cache'):
        g._permission_cache = {}
    
    if cache_key in g._permission_cache:
        return g._permission_cache[cache_key]
    # --- CACHING LOGIC END ---

    query = db.session.query(Permission).join(role_permissions).join(Role).join(UserTeamRoleLink).filter(
        UserTeamRoleLink.user_id == user.id,
        Permission.resource == resource,
        Permission.action == action
    )

    if team_id:
        query = query.filter(UserTeamRoleLink.team_id == team_id, or_(Role.team_id == team_id, Role.team_id.is_(None)))
    elif not allow_any_team:
        # Default behavior: if no team_id is provided, only check global roles
        query = query.filter(Role.team_id.is_(None))
    # If allow_any_team is True and team_id is None, we don't add the filter on Role.team_id,
    # effectively checking all roles (global and team-specific) assigned to the user.

    result = db.session.query(query.exists()).scalar()
    
    # Store result in cache
    g._permission_cache[cache_key] = result
    return result

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    registered_on = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    email_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    email_confirmed_on = db.Column(db.DateTime, nullable=True)
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    force_password_change = db.Column(db.Boolean, default=False, nullable=False)
    ckan_url = db.Column(db.String(255), nullable=True)
    ckan_api_key = db.Column(db.String(255), nullable=True)
    calendar_token = db.Column(db.String(64), nullable=True)
    team_calendar_token = db.Column(db.String(64), nullable=True)

    memberships = db.relationship('TeamMembership', back_populates='user', cascade="all, delete-orphan")
    team_roles = db.relationship('UserTeamRoleLink', back_populates='user', cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint('calendar_token', name='uq_user_calendar_token'),
        db.UniqueConstraint('team_calendar_token', name='uq_user_team_calendar_token'),
    )

    my_page_groups = db.relationship('ExperimentalGroup', secondary=user_my_page_groups, lazy='dynamic',
                                    backref=db.backref('bookmarked_by_users', lazy='dynamic'))
    my_page_datatables = db.relationship('DataTable', secondary=user_my_page_datatables, lazy='dynamic',
                                        backref=db.backref('bookmarked_by_users', lazy='dynamic'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_calendar_token(self):
        self.calendar_token = secrets.token_urlsafe(32)

    def generate_team_calendar_token(self):
        self.team_calendar_token = secrets.token_urlsafe(32)

    def get_teams(self):
        return [m.team for m in self.memberships]

    def is_admin_of(self, team):
        if not team: return False
        return user_has_permission(self, 'Team', 'manage_members', team_id=team.id)

    def get_accessible_projects(self, include_archived=False):
        from .projects import Project, ProjectTeamShare, ProjectUserShare
        
        if self.is_super_admin:
            query = Project.query
            if not include_archived:
                query = query.filter(Project.is_archived == False)
            return query.order_by(Project.name).all()

        user_team_ids = [m.team_id for m in self.memberships]
        if not user_team_ids:
            return []

        has_permission_for_project_team = db.session.query(db.literal(1)).select_from(UserTeamRoleLink).join(Role).join(role_permissions).join(Permission).filter(
            UserTeamRoleLink.user_id == self.id,
            Permission.resource == 'Project',
            Permission.action == 'read',
            UserTeamRoleLink.team_id == Project.team_id,
            or_(Role.team_id == Project.team_id, Role.team_id.is_(None))
        ).exists()

        owned_project_ids_q = db.session.query(Project.id).filter(has_permission_for_project_team)
        team_shared_project_ids_q = db.session.query(ProjectTeamShare.project_id).filter(
            ProjectTeamShare.team_id.in_(user_team_ids), ProjectTeamShare.can_view_project == True
        )
        user_shared_project_ids_q = db.session.query(ProjectUserShare.project_id).filter(
            ProjectUserShare.user_id == self.id, ProjectUserShare.can_view_project == True
        )

        accessible_project_ids_q = owned_project_ids_q.union(team_shared_project_ids_q).union(user_shared_project_ids_q)
        query = Project.query.filter(Project.id.in_(accessible_project_ids_q))

        if not include_archived:
            query = query.filter(Project.is_archived == False)

        return query.order_by(Project.name).all()

    @property
    def username(self):
        return self.email

    def __repr__(self):
        return f'<User {self.email}>'

class APIToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    token_hash = db.Column(db.String(128), unique=True, nullable=False, index=True)
    prefix_hash = db.Column(db.String(128), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship('User', backref=db.backref('api_tokens', lazy='dynamic', cascade="all, delete-orphan"))

    def __init__(self, user_id, name):
        self.user_id = user_id
        self.name = name
        raw_token = f"pcv_{secrets.token_urlsafe(32)}"
        # SECURITY FIX: Store a SHA256 hash of the prefix for O(1) secure lookup
        prefix = raw_token[:8]
        self.prefix_hash = hashlib.sha256(prefix.encode()).hexdigest()
        self.token_hash = generate_password_hash(raw_token)
        self._raw_token = raw_token

    @property
    def raw_token(self):
        if hasattr(self, '_raw_token'):
            return self._raw_token
        return None

    @staticmethod
    def verify_token(token_str):
        if not token_str or not token_str.startswith("pcv_"):
            return None
        
        # PERFORMANCE & SECURITY FIX: O(1) lookup via prefix hash
        prefix = token_str[:8]
        h = hashlib.sha256(prefix.encode()).hexdigest()
        
        token_obj = APIToken.query.filter_by(prefix_hash=h, is_active=True).first()
        if token_obj and check_password_hash(token_obj.token_hash, token_str):
            token_obj.last_used_at = datetime.now(timezone.utc)
            db.session.commit()
            return token_obj.user
        return None