# app/services/admin_service.py
import secrets
from datetime import datetime

from flask import current_app, url_for
from flask_babel import lazy_gettext as _l
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.helpers import generate_confirmation_token, send_email
from app.models import (Permission, Project, ProjectUserShare, Role, Team,
                        TeamMembership, User, UserTeamRoleLink)
from app.services.base import BaseService


class AdminService(BaseService):
    
    def create_team(self, name):
        """Creates a team and its default roles."""
        team = Team(name=name)
        db.session.add(team)
        db.session.flush() # Get ID
        self._ensure_default_roles(team)
        db.session.commit()
        return team

    def delete_team(self, team):
        """Deletes a team and cleans up associations."""
        # Manual cleanup of relationships if cascade doesn't cover everything
        # (Though SQLAlchemy cascade usually handles this, explicit is safe)
        UserTeamRoleLink.query.filter_by(team_id=team.id).delete()
        TeamMembership.query.filter_by(team_id=team.id).delete()
        Role.query.filter_by(team_id=team.id).delete()
        db.session.delete(team)
        db.session.commit()

    def invite_user_to_team(self, email, team, role_id=None):
        """
        Invites a user to a team. Creates the user if they don't exist.
        Returns: (success: bool, message: str, category: str)
        """
        user = User.query.filter_by(email=email).first()
        is_new_user = False

        if not user:
            is_new_user = True
            temp_password = secrets.token_urlsafe(16)
            user = User(email=email)
            user.set_password(temp_password)
            user.email_confirmed = False
            user.is_active = True
            db.session.add(user)
            db.session.flush()

            # Send welcome email
            token = generate_confirmation_token(user.email)
            set_password_url = url_for('auth.set_password', token=token, _external=True)
            email_sent = send_email(
                to=user.email,
                subject=str(_l("Set Your Precliniset Password")),
                template_path='email/set_password.html',
                set_password_url=set_password_url,
                user=user
            )
            if not email_sent:
                # Add a hint about the manual link to the result message later
                kwargs_for_msg = {'manual_link': set_password_url}
            else:
                kwargs_for_msg = {}

        # Check existing membership
        if TeamMembership.query.filter_by(user_id=user.id, team_id=team.id).first():
            return False, _l('User %(email)s is already a member of team %(team)s.', email=email, team=team.name), 'info'

        # Add membership
        membership = TeamMembership(user_id=user.id, team_id=team.id)
        db.session.add(membership)

        # Assign Role
        role_assigned_name = None
        if role_id:
            role = db.session.get(Role, role_id)
            # Validate role belongs to team or is global
            if role and (role.team_id is None or role.team_id == team.id):
                self._assign_role_link(user, team, role)
                role_assigned_name = role.name
        
        # Fallback to default 'Member' role if no valid role provided
        if not role_assigned_name:
            default_roles = self._ensure_default_roles(team)
            member_role = default_roles['member']
            self._assign_role_link(user, team, member_role)
            role_assigned_name = member_role.name

        db.session.commit()
        
        msg = _l('User %(email)s added to team "%(team)s" with role "%(role)s".', email=email, team=team.name, role=role_assigned_name)
        if is_new_user:
            if not email_sent:
                msg = _l('User account created for %(email)s (SMTP OFF). PLEASE MANUALLY SHARE THIS LINK: %(link)s . ', email=email, link=set_password_url) + msg
            else:
                msg = _l('User account created for %(email)s. ', email=email) + msg
            
        return True, msg, 'success'

    def assign_role_to_user(self, team, user, role_id):
        role = db.session.get(Role, role_id)
        if not role or (role.team_id is not None and role.team_id != team.id):
            raise ValueError("Invalid role selected.")

        if UserTeamRoleLink.query.filter_by(user_id=user.id, team_id=team.id, role_id=role.id).first():
            return False, _l('User already has this role.')

        self._assign_role_link(user, team, role)
        db.session.commit()
        return True, _l('Role "%(role)s" assigned.', role=role.name)

    def unassign_role_from_user(self, team, user, role_id):
        link = UserTeamRoleLink.query.filter_by(user_id=user.id, team_id=team.id, role_id=role_id).first()
        if link:
            db.session.delete(link)
            db.session.commit()
            return True
        return False

    def remove_user_from_team(self, team, user):
        membership = TeamMembership.query.filter_by(user_id=user.id, team_id=team.id).first()
        if not membership:
            return False

        # Remove roles and membership
        UserTeamRoleLink.query.filter_by(user_id=user.id, team_id=team.id).delete()
        db.session.delete(membership)
        db.session.commit()
        return True

    def delete_user_fully(self, user):
        """Permanently deletes a user and their shares."""
        ProjectUserShare.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()

    def batch_update_users(self, user_ids, action, current_user):
        users = User.query.filter(User.id.in_(user_ids)).all()
        success_count = 0
        fail_count = 0
        
        # Handle "Add to Team" special action
        if action.startswith('add_to_team_'):
            try:
                team_id = int(action.split('_')[-1])
                team = db.session.get(Team, team_id)
                if not team: return 0, 0
                
                # Get default member role
                default_roles = self._ensure_default_roles(team)
                member_role = default_roles['member']

                for user in users:
                    if not TeamMembership.query.filter_by(user_id=user.id, team_id=team.id).first():
                        db.session.add(TeamMembership(user=user, team=team))
                        self._assign_role_link(user, team, member_role)
                        success_count += 1
                    else:
                        fail_count += 1
                db.session.commit()
                return success_count, fail_count
            except Exception as e:
                current_app.logger.error(f"Batch add to team failed: {e}")
                return 0, len(users)

        # Handle standard actions
        for user in users:
            if action == 'activate':
                user.is_active = True
                success_count += 1
            elif action == 'deactivate':
                if user.id != current_user.id:
                    user.is_active = False
                    success_count += 1
                else:
                    fail_count += 1
            elif action == 'validate':
                user.email_confirmed = True
                success_count += 1
            elif action == 'delete':
                # Check permissions and ownership
                # (Assuming permission check passed in route)
                if user.owned_projects.count() == 0:
                    self.delete_user_fully(user)
                    success_count += 1
                else:
                    fail_count += 1
        
        if action != 'delete': # Delete commits individually in helper
            db.session.commit()
            
        return success_count, fail_count

    def create_role(self, name, description, scope, team_id, permission_ids):
        role = Role(
            name=name,
            description=description,
            team_id=team_id if scope == 'team_specific' else None
        )
        if permission_ids:
            perms = Permission.query.filter(Permission.id.in_(permission_ids)).all()
            role.permissions.extend(perms)
        
        db.session.add(role)
        db.session.commit()
        return role

    def update_role(self, role, name, description, scope, team_id, permission_ids):
        role.name = name
        role.description = description
        role.team_id = team_id if scope == 'team_specific' else None
        
        role.permissions.clear()
        if permission_ids:
            perms = Permission.query.filter(Permission.id.in_(permission_ids)).all()
            role.permissions.extend(perms)
            
        db.session.commit()
        return role

    # --- Helpers ---
    def _assign_role_link(self, user, team, role):
        """Helper to create UserTeamRoleLink if it doesn't exist."""
        if not UserTeamRoleLink.query.filter_by(user_id=user.id, team_id=team.id, role_id=role.id).first():
            link = UserTeamRoleLink(user_id=user.id, team_id=team.id, role_id=role.id)
            db.session.add(link)

    def _ensure_default_roles(self, team):
        """Ensures a team has default 'Team Admin' and 'Member' roles."""
        # Define default permissions
        admin_perms = [
            ('Project', 'read'), ('Project', 'create'), ('Project', 'edit'), ('Project', 'delete'), ('Project', 'archive'), ('Project', 'view_unblinded_data'),
            ('ExperimentalGroup', 'read'), ('ExperimentalGroup', 'create'), ('ExperimentalGroup', 'edit'), ('ExperimentalGroup', 'delete'), ('ExperimentalGroup', 'archive_exp_group'), ('ExperimentalGroup', 'edit_exp_group'), ('ExperimentalGroup', 'delete_exp_group'),
            ('DataTable', 'read'), ('DataTable', 'create'), ('DataTable', 'edit'), ('DataTable', 'edit_datatable'), ('DataTable', 'delete'), ('DataTable', 'delete_datatable'),
            ('EthicalApproval', 'view'), ('EthicalApproval', 'create'), ('EthicalApproval', 'edit'),
            ('Workplan', 'view'), ('Workplan', 'create'), ('Workplan', 'edit'),
            ('ReferenceRange', 'view'), ('ReferenceRange', 'create'), ('ReferenceRange', 'edit'),
            ('Storage', 'view'), ('Storage', 'create'), ('Storage', 'edit'),
            ('Team', 'manage_members'), ('Team', 'view'),
            ('Role', 'view'), ('Role', 'create'), ('Role', 'edit'), ('Role', 'delete')
        ]
        member_perms = [
            ('Project', 'read'),
            ('ExperimentalGroup', 'read'),
            ('DataTable', 'read'), ('DataTable', 'create'), ('DataTable', 'edit_datatable'),
            ('EthicalApproval', 'view'),
            ('Workplan', 'view'),
            ('ReferenceRange', 'view'),
            ('Storage', 'view'),
            ('Team', 'view')
        ]

        admin_role = self._create_role_if_missing(team, 'Team Admin', 'Administrative access within the team.', admin_perms)
        member_role = self._create_role_if_missing(team, 'Member', 'Can view and contribute to team projects.', member_perms)
        
        return {'team_admin': admin_role, 'member': member_role}

    def _create_role_if_missing(self, team, name, description, perm_tuples):
        role = Role.query.filter_by(name=name, team_id=team.id).first()
        if not role:
            role = Role(name=name, description=description, team_id=team.id)
            db.session.add(role) # <--- MOVED UP: Add to session before querying permissions
            
            for res, act in perm_tuples:
                p = Permission.query.filter_by(resource=res, action=act).first()
                if p: role.permissions.append(p)
            
            db.session.commit()
        return role