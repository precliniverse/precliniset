# app/forms/projects.py
"""Project-related forms."""
from flask_babel import lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import (BooleanField, FileField, SelectField, SelectMultipleField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import (DataRequired, Email, Length, Optional,
                                ValidationError)

from app.models import ExperimentalGroup, Partner, Project, Team, User


class ProjectForm(FlaskForm):
    name = StringField(_l('Project Name'), validators=[DataRequired(), Length(max=150)])
    team = SelectField(_l('Team'), coerce=int, validators=[DataRequired()])
    submit = SubmitField(_l('Save Project'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        project = kwargs.get('obj')
        if project and project.team_id:
            self.team.data = project.team_id


class ProjectDescriptionForm(FlaskForm):
    description = TextAreaField(_l('Description'), validators=[Optional()])
    submit_description = SubmitField(_l('Save Description'))


class AttachmentForm(FlaskForm):
    file = FileField(_l('File'), validators=[
        DataRequired(),
        FileAllowed(['jpg', 'png', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'zip'], _l('Allowed file types only!'))
    ])
    description = StringField(_l('Description'), validators=[Optional(), Length(max=255)])
    submit_attachment = SubmitField(_l('Upload Attachment'))


class PartnerForm(FlaskForm):
    company_name = StringField(_l('Company Name'), validators=[DataRequired(), Length(max=150)])
    contact_email = StringField(_l('Contact Email'), validators=[DataRequired(), Email(), Length(max=120)])
    submit_partner = SubmitField(_l('Create Partner'))


class LinkPartnerForm(FlaskForm):
    existing_partner = SelectField(_l('Select Existing Partner'), coerce=int, validators=[Optional()])
    new_company_name = StringField(_l('New Company Name'), validators=[Optional(), Length(max=150)])
    new_contact_email = StringField(_l('New Contact Email'), validators=[Optional(), Email(), Length(max=120)])
    submit_link_partner = SubmitField(_l('Link Partner'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing_partner.choices = [(0, _l('-- Select Existing --'))] + [(p.id, f"{p.company_name} ({p.contact_email})") for p in Partner.query.order_by(Partner.company_name).all()]

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        if not self.existing_partner.data and not (self.new_company_name.data and self.new_contact_email.data):
            msg = _l('Please select an existing partner or provide details for a new one.')
            self.existing_partner.errors.append(msg)
            self.new_company_name.errors.append(msg)
            return False
        if self.existing_partner.data and (self.new_company_name.data or self.new_contact_email.data):
            msg = _l('Please either select an existing partner OR provide new details, not both.')
            self.existing_partner.errors.append(msg)
            self.new_company_name.errors.append(msg)
            return False
        return True


class LinkGroupForm(FlaskForm):
    groups = SelectMultipleField(_l('Link Experimental Groups'), validators=[Optional()])
    submit_link_group = SubmitField(_l('Update Linked Groups'))

    def __init__(self, project=None, formdata=None, obj=None, *args, **kwargs):
        super().__init__(formdata=formdata, obj=obj, *args, **kwargs)
        if project:
            self.groups.choices = [(g.id, g.name) for g in ExperimentalGroup.query.filter_by(team_id=project.team_id, is_archived=False).order_by(ExperimentalGroup.name).all()]
            if formdata is None and self.groups.data is None:
                 self.groups.data = [g.id for g in project.groups if not g.is_archived]
        else:
             self.groups.choices = []


class ShareProjectForm(FlaskForm):
    share_type = SelectField(_l('Share With'), choices=[('team', _l('Team')), ('user', _l('User'))], validators=[Optional()])
    team_to_share = SelectField(_l('Team'), coerce=int, validators=[Optional()])
    user_to_share = SelectField(_l('User'), coerce=int, validators=[Optional()])
    
    # Granular Permissions
    can_view_project = BooleanField(_l('Can View Project'), default=True)
    can_view_exp_groups = BooleanField(_l('Can View Groups'))
    can_view_datatables = BooleanField(_l('Can View DataTables'))
    can_view_samples = BooleanField(_l('Can View Samples'))
    can_create_exp_groups = BooleanField(_l('Can Create Experimental Groups'))
    can_edit_exp_groups = BooleanField(_l('Can Edit Experimental Groups'))
    can_delete_exp_groups = BooleanField(_l('Can Delete Experimental Groups'))
    can_create_datatables = BooleanField(_l('Can Create DataTables'))
    can_edit_datatables = BooleanField(_l('Can Edit DataTables'))
    can_delete_datatables = BooleanField(_l('Can Delete DataTables'))
    can_view_unblinded_data = BooleanField(_l('Can View Unblinded Data'))
    
    submit_share = SubmitField(_l('Save Permissions'))

    def __init__(self, project=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            other_teams = Team.query.filter(Team.id != project.team_id).order_by(Team.name).all()
            self.team_to_share.choices = [(0, _l('-- Select a Team --'))] + [(t.id, t.name) for t in other_teams]
            
            all_users = User.query.filter(User.id != current_user.id).all()
            if project.owner_id:
                all_users = [u for u in all_users if u.id != project.owner_id]
            self.user_to_share.choices = [(0, _l('-- Select a User --'))] + [(u.id, u.email) for u in all_users]

    def validate(self, extra_validators=None):
        # This validation is now handled in the route, but we keep it for safety
        if not super().validate(extra_validators):
            return False

        if self.share_type.data == 'team':
            if not self.team_to_share.data:
                self.team_to_share.errors.append(_l('Please select a team.'))
                return False
        elif self.share_type.data == 'user':
            if not self.user_to_share.data:
                self.user_to_share.errors.append(_l('Please select a user.'))
                return False
        
        return True


class CreateAPITokenForm(FlaskForm):
    name = StringField(_l('Token Name'), validators=[DataRequired(), Length(min=3, max=100)],
                       description=_l("A descriptive name for your token (e.g., 'My Script', 'Data Analysis Tool')."))
    submit_create_token = SubmitField(_l('Create New Token'))