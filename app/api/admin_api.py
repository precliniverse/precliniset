# app/api/admin_api.py
from flask import g, request
from flask_restx import Resource, fields

from app.decorators import permission_required
from app.extensions import db
from app.models import (AuditLog, Permission, Role, Team, TeamMembership, User,
                        UserTeamRoleLink, user_has_permission)

from . import api
from .auth import token_required

ns = api.namespace('admin', description='User and Team administration')

team_model = ns.model('Team', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True)
})

membership_model = ns.model('TeamMembership', {
    'user_id': fields.Integer(required=True)
})

user_model = ns.model('User', {
    'id': fields.Integer(readonly=True),
    'email': fields.String(required=True),
    'is_active': fields.Boolean,
    'is_super_admin': fields.Boolean(readonly=True, description="Super admin status cannot be changed via this endpoint."),
    'email_confirmed': fields.Boolean
})

permission_model = ns.model('Permission', {
    'id': fields.Integer(readonly=True),
    'resource': fields.String,
    'action': fields.String
})

role_model = ns.model('Role', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True),
    'description': fields.String,
    'team_id': fields.Integer(nullable=True),
    'permissions': fields.List(fields.Nested(permission_model), readonly=True)
})

role_input_model = ns.model('RoleInput', {
    'name': fields.String(required=True),
    'description': fields.String,
    'team_id': fields.Integer(nullable=True, description="Omit for global role"),
    'permission_ids': fields.List(fields.Integer, required=True, description="List of permission IDs to assign")
})

role_assignment_model = ns.model('RoleAssignment', {
    'role_id': fields.Integer(required=True)
})

audit_log_model = ns.model('AuditLog', {
    'id': fields.Integer(readonly=True),
    'user_id': fields.Integer,
    'action': fields.String,
    'resource_type': fields.String,
    'resource_id': fields.String,
    'changes': fields.String(description='JSON string of changes'),
    'timestamp': fields.DateTime
})


@ns.route('/teams')
class TeamList(Resource):
    decorators = [token_required]

    @ns.doc('list_teams')
    @ns.marshal_list_with(team_model)
    @permission_required('Team', 'view')
    def get(self):
        """List all teams"""
        if g.current_user.is_super_admin:
            return Team.query.order_by(Team.name).all()
        return g.current_user.get_teams()

    @ns.doc('create_team')
    @ns.expect(team_model)
    @ns.marshal_with(team_model, code=201)
    @permission_required('Team', 'create')
    def post(self):
        """Create a new team"""
        data = request.get_json()
        new_team = Team(name=data['name'])
        db.session.add(new_team)
        db.session.commit()
        return new_team, 201

@ns.route('/teams/<int:team_id>')
class TeamItem(Resource):
    decorators = [token_required]

    @ns.doc('get_team')
    @ns.marshal_with(team_model)
    def get(self, team_id):
        """Get a single team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'view', team_id=team.id):
            ns.abort(403, "Permission denied.")
        return team

    @ns.doc('update_team')
    @ns.expect(team_model)
    @ns.marshal_with(team_model)
    def put(self, team_id):
        """Update a team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'edit', team_id=team.id):
            ns.abort(403, "Permission denied to edit this team.")
        data = request.get_json()
        team.name = data.get('name', team.name)
        db.session.commit()
        return team

    @ns.doc('delete_team')
    @ns.response(204, 'Team deleted')
    def delete(self, team_id):
        """Delete a team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'delete', team_id=team.id):
            ns.abort(403, "Permission denied to delete this team.")
        db.session.delete(team)
        db.session.commit()
        return '', 204

@ns.route('/teams/<int:team_id>/members')
class TeamMemberList(Resource):
    decorators = [token_required]

    @ns.doc('add_team_member')
    @ns.expect(membership_model)
    @permission_required('Team', 'manage_members')
    def post(self, team_id):
        """Add a member to a team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'manage_members', team_id=team.id):
            ns.abort(403, "Permission denied.")
        
        data = request.get_json()
        user = db.session.get(User, data['user_id'])
        if not user:
            ns.abort(404, "User not found.")

        membership = TeamMembership(
            team_id=team.id,
            user_id=user.id
        )
        db.session.add(membership)
        db.session.commit()
        return {'message': 'User added to team'}, 201

@ns.route('/teams/<int:team_id>/members/<int:user_id>')
class TeamMemberItem(Resource):
    decorators = [token_required]

    @ns.doc('remove_team_member')
    @ns.response(204, 'Member removed')
    @permission_required('Team', 'manage_members')
    def delete(self, team_id, user_id):
        """Remove a member from a team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'manage_members', team_id=team.id):
            ns.abort(403, "Permission denied.")
        
        membership = TeamMembership.query.filter_by(team_id=team_id, user_id=user_id).first()
        if not membership:
            ns.abort(404, "Membership not found")

        db.session.delete(membership)
        db.session.commit()
        return '', 204

# --- User Management ---

@ns.route('/users')
class UserList(Resource):
    decorators = [token_required]

    @ns.doc('list_users')
    @ns.marshal_list_with(user_model)
    @permission_required('User', 'view')
    def get(self):
        """List all users"""
        return User.query.order_by(User.email).all()

    @ns.doc('create_user')
    @ns.expect(user_model)
    @ns.marshal_with(user_model, code=201)
    @permission_required('User', 'create')
    def post(self):
        """Create a new user"""
        data = request.get_json()
        new_user = User(
            email=data['email'],
            is_active=data.get('is_active', True),
            # is_super_admin cannot be set here for security
            email_confirmed=data.get('email_confirmed', True)
        )
        new_user.set_password('defaultpassword')
        db.session.add(new_user)
        db.session.commit()
        return new_user, 201

@ns.route('/users/<int:user_id>')
class UserItem(Resource):
    decorators = [token_required]

    @ns.doc('get_user')
    @ns.marshal_with(user_model)
    @permission_required('User', 'view')
    def get(self, user_id):
        """Get a single user"""
        user = db.session.get(User, user_id)
        if not user:
            ns.abort(404, "User not found")
        return user

    @ns.doc('update_user')
    @ns.expect(user_model)
    @ns.marshal_with(user_model)
    @permission_required('User', 'edit')
    def put(self, user_id):
        """Update a user"""
        user = db.session.get(User, user_id)
        if not user:
            ns.abort(404, "User not found")
        data = request.get_json()
        user.email = data.get('email', user.email)
        user.is_active = data.get('is_active', user.is_active)
        user.email_confirmed = data.get('email_confirmed', user.email_confirmed)
        db.session.commit()
        return user

    @ns.doc('delete_user')
    @ns.response(204, 'User deleted')
    @permission_required('User', 'delete')
    def delete(self, user_id):
        """Delete a user"""
        user = db.session.get(User, user_id)
        if not user:
            ns.abort(404, "User not found")
        db.session.delete(user)
        db.session.commit()
        return '', 204

# --- Role Management ---

@ns.route('/roles')
class RoleList(Resource):
    decorators = [token_required, permission_required('Role', 'view')]

    @ns.doc('list_roles')
    @ns.marshal_list_with(role_model)
    def get(self):
        """List all roles"""
        return Role.query.order_by(Role.name).all()

    @ns.doc('create_role')
    @ns.expect(role_input_model)
    @ns.marshal_with(role_model, code=201)
    @permission_required('Role', 'create')
    def post(self):
        """Create a new role"""
        data = request.get_json()
        team_id = data.get('team_id')
        if team_id and not user_has_permission(g.current_user, 'Role', 'create', team_id=team_id):
            ns.abort(403, "Permission denied to create roles for this team.")

        new_role = Role(
            name=data['name'],
            description=data.get('description'),
            team_id=team_id
        )
        permissions = Permission.query.filter(Permission.id.in_(data['permission_ids'])).all()
        new_role.permissions.extend(permissions)
        db.session.add(new_role)
        db.session.commit()
        return new_role, 201

@ns.route('/roles/<int:role_id>')
class RoleItem(Resource):
    decorators = [token_required]

    @ns.doc('get_role')
    @ns.marshal_with(role_model)
    @permission_required('Role', 'view')
    def get(self, role_id):
        """Get a single role"""
        role = db.session.get(Role, role_id)
        if not role:
            ns.abort(404, "Role not found")
        return role

    @ns.doc('update_role')
    @ns.expect(role_input_model)
    @ns.marshal_with(role_model)
    @permission_required('Role', 'edit')
    def put(self, role_id):
        """Update a role"""
        role = db.session.get(Role, role_id)
        if not role:
            ns.abort(404, "Role not found")
        # Check permission for the specific role's context
        if not user_has_permission(g.current_user, 'Role', 'edit', team_id=role.team_id):
            ns.abort(403, "Permission denied to edit this role.")

        data = request.get_json()
        role.name = data.get('name', role.name)
        role.description = data.get('description', role.description)
        role.team_id = data.get('team_id', role.team_id)
        
        role.permissions.clear()
        permissions = Permission.query.filter(Permission.id.in_(data['permission_ids'])).all()
        role.permissions.extend(permissions)
        
        db.session.commit()
        return role

    @ns.doc('delete_role')
    @ns.response(204, 'Role deleted')
    @permission_required('Role', 'delete')
    def delete(self, role_id):
        """Delete a role"""
        role = db.session.get(Role, role_id)
        if not role:
            ns.abort(404, "Role not found")
        # Check permission for the specific role's context
        if not user_has_permission(g.current_user, 'Role', 'delete', team_id=role.team_id):
            ns.abort(403, "Permission denied to delete this role.")
        if role.has_active_assignments():
            ns.abort(400, "Cannot delete role because it is assigned to users.")
        db.session.delete(role)
        db.session.commit()
        return '', 204

# --- Role Assignment ---

@ns.route('/teams/<int:team_id>/members/<int:user_id>/roles')
class TeamMemberRole(Resource):
    decorators = [token_required]

    @ns.doc('assign_role')
    @ns.expect(role_assignment_model)
    @permission_required('Team', 'manage_members')
    def post(self, team_id, user_id):
        """Assign a role to a user within a team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'manage_members', team_id=team.id):
            ns.abort(403, "Permission denied.")
        
        user = db.session.get(User, user_id)
        if not user:
            ns.abort(404, "User not found")
        data = request.get_json()
        role = db.session.get(Role, data['role_id'])
        if not role:
            ns.abort(404, "Role not found")

        if role.team_id is not None and role.team_id != team.id:
            ns.abort(400, "Role does not belong to this team.")

        link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=role.id)
        db.session.add(link)
        db.session.commit()
        return {'message': 'Role assigned'}, 201

@ns.route('/teams/<int:team_id>/members/<int:user_id>/roles/<int:role_id>')
class TeamMemberRoleItem(Resource):
    decorators = [token_required]

    @ns.doc('unassign_role')
    @ns.response(204, 'Role unassigned')
    @permission_required('Team', 'manage_members')
    def delete(self, team_id, user_id, role_id):
        """Unassign a role from a user within a team"""
        team = db.session.get(Team, team_id)
        if not team:
            ns.abort(404, "Team not found")
        if not user_has_permission(g.current_user, 'Team', 'manage_members', team_id=team.id):
            ns.abort(403, "Permission denied.")
        
        link = UserTeamRoleLink.query.filter_by(
            team_id=team_id, 
            user_id=user_id, 
            role_id=role_id
        ).first()
        
        if not link:
            ns.abort(404, "Role assignment not found")

        db.session.delete(link)
        db.session.commit()
        return '', 204

# --- Audit Logs ---

@ns.route('/audit_logs')
class AuditLogList(Resource):
    decorators = [token_required, permission_required('User', 'view')] # accessible to admins

    @ns.doc('list_audit_logs')
    @ns.marshal_list_with(audit_log_model)
    def get(self):
        """List all audit logs"""
        return AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(100).all()
