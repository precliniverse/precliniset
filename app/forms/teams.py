# app/forms/teams.py
"""
Team management and role assignment forms for the Precliniset application.
"""
from flask_babel import lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import (SelectField, SelectMultipleField, StringField,
                     SubmitField, TextAreaField)
from wtforms.validators import (DataRequired, Email, Length, Optional,
                                ValidationError)

from app.models import user_has_permission


class TeamForm(FlaskForm):
    """Form for creating a new team."""
    name = StringField(_l('Team Name'), validators=[DataRequired()])
    submit = SubmitField(_l('Create Team'))


class InviteUserForm(FlaskForm):
    """Form for inviting a user to a team with a specific role."""
    email = StringField(_l('User Email'), validators=[DataRequired(), Email()])
    team_id = SelectField(_l('Team'), coerce=lambda x: int(x) if x else None, 
                         validators=[DataRequired(_l("Please select a team for the new user."))])
    role_id = SelectField(_l('Role'), coerce=lambda x: int(x) if x else None, 
                         validators=[DataRequired(_l("Please select a role for the new user within the team."))])
    submit_invite_member = SubmitField(_l('Invite User'))

    def __init__(self, *args, **kwargs):
        super(InviteUserForm, self).__init__(*args, **kwargs)
        from app.models import Role, Team
        from app.permissions import is_admin_or_super_admin

        accessible_teams = []
        if current_user.is_super_admin:
            accessible_teams = Team.query.order_by(Team.name).all()
        else:
            user_team_ids = [m.team_id for m in current_user.memberships if is_admin_or_super_admin(m.team_id)]
            accessible_teams = Team.query.filter(Team.id.in_(user_team_ids)).order_by(Team.name).all()
        
        self.team_id.choices = [('', _l('Select Team...'))] + [(t.id, t.name) for t in accessible_teams]

        # Populate role choices with global roles and roles from accessible teams
        all_relevant_roles = set()
        if current_user.is_super_admin or user_has_permission(current_user, 'Role', 'view', team_id=None):
            all_relevant_roles.update(Role.query.filter(Role.team_id.is_(None)).all())
        
        for team in accessible_teams:
            all_relevant_roles.update(Role.query.filter_by(team_id=team.id).all())
        
        self.role_id.choices = [('', _l('Select Role...'))] + sorted(
            [(r.id, f"{r.name} ({r.team.name if r.team else 'Global'})") for r in all_relevant_roles], 
            key=lambda x: x[1]
        )


class UpdateMemberRoleForm(FlaskForm):
    """Form for updating a team member's role."""
    role = SelectField(_l('Role'), 
                      choices=[('member', _l('Member')), ('team_admin', _l('Team Admin'))], 
                      validators=[DataRequired()])
    submit = SubmitField(_l('Update Role'))


class AddUserToTeamForm(FlaskForm):
    """Form for adding a user to a team."""
    team = SelectField(_l('Team'), coerce=int, validators=[DataRequired()])
    submit_add_user = SubmitField(_l('Add to Team'))

    def __init__(self, *args, **kwargs):
        super(AddUserToTeamForm, self).__init__(*args, **kwargs)
        from app.models import Team
        self.team.choices = [(t.id, t.name) for t in Team.query.order_by('name').all()]


class RoleForm(FlaskForm):
    """Form for creating or editing RBAC roles."""
    name = StringField(_l('Role Name'), validators=[DataRequired(), Length(min=3, max=80)])
    description = TextAreaField(_l('Description'), validators=[Optional(), Length(max=255)])
    scope = SelectField(_l('Scope'), 
                       choices=[('global', _l('Global')), ('team_specific', _l('Team Specific'))], 
                       validators=[DataRequired()])
    team_id = SelectField(_l('Team'), coerce=lambda x: int(x) if x and x != '' else None, 
                         validators=[Optional()])
    permissions = SelectMultipleField(_l('Permissions'), coerce=int, validators=[Optional()])
    submit = SubmitField(_l('Save Role'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from app.models import Team
        from app.permissions import is_admin_or_super_admin

        # Dynamically populate team choices based on user's admin access
        accessible_teams = []
        if current_user.is_super_admin:
            accessible_teams = Team.query.order_by(Team.name).all()
        else:
            # Get teams where user is admin
            user_team_ids = [m.team_id for m in current_user.memberships if is_admin_or_super_admin(m.team_id)]
            accessible_teams = Team.query.filter(Team.id.in_(user_team_ids)).order_by(Team.name).all()
        
        self.team_id.choices = [('', _l('Select Team...'))] + [(t.id, t.name) for t in accessible_teams]

    def validate_team_id(self, field):
        if self.scope.data == 'team_specific' and not field.data:
            raise ValidationError(_l('Team selection is required for team-specific roles.'))
        elif self.scope.data == 'global' and field.data:
            raise ValidationError(_l('Team selection should not be provided for global roles.'))
