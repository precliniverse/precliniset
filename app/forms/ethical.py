# app/forms/ethical.py
"""Ethical approval forms."""
from flask_babel import lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import (BooleanField, DateField, FieldList, FileField, FormField,
                     IntegerField, SelectField, SelectMultipleField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import (DataRequired, InputRequired, Length,
                                NumberRange, Optional)

from app.models import EthicalApproval, Severity, Team, user_has_permission
from app.widgets import DateInput


class XMLImportForm(FlaskForm):
    xml_file = FileField(_l('APAFIS XML File'), validators=[
        DataRequired(_l('Please select an XML file to import.')),
        FileAllowed(['xml'], _l('Only XML files are allowed.'))
    ])
    submit_import = SubmitField(_l('Import and Pre-fill Form'))


class ProcedureSubForm(FlaskForm):
    name = StringField(_l('Procedure Name'), validators=[DataRequired(), Length(max=255)])
    severity = SelectField(_l('Severity'), choices=[(s.name, s.value) for s in Severity], validators=[DataRequired()], coerce=str)
    description = TextAreaField(_l('Description'), validators=[Optional()])
    pain_management = TextAreaField(_l('Pain Management'), validators=[Optional()])
    is_euthanasia_endpoint = BooleanField(_l('Is Euthanasia an Endpoint?'))


class EthicalApprovalForm(FlaskForm):
    reference_number = StringField(_l('Short Reference Number'), validators=[DataRequired(), Length(max=50)], description=_l("A short, unique identifier for this approval (e.g., 'PROJ-001-EA')."))
    apafis_reference = StringField(_l('APAFIS Reference (Optional)'), validators=[Optional(), Length(max=50)], description=_l("The official APAFIS dossier reference, e.g., '2022051318545240'."))
    apafis_version = IntegerField(_l('APAFIS Version (Optional)'), validators=[Optional(), NumberRange(min=1)])
    title = StringField(_l('Project Title'), validators=[DataRequired(), Length(max=255)])
    start_date = DateField(_l('Start Date'), validators=[DataRequired()], widget=DateInput())
    duration_years = IntegerField(_l('Duration (Years)'), default=5, validators=[InputRequired(), NumberRange(min=0, max=20)])
    duration_months = IntegerField(_l('Duration (Months)'), default=0, validators=[InputRequired(), NumberRange(min=0, max=11)])
    number_of_animals = IntegerField(_l('Total Animals Authorized'), validators=[InputRequired(), NumberRange(min=1)])
    species = StringField(_l('Species'), validators=[Optional(), Length(max=100)])
    sex_justification = TextAreaField(_l('Sex Justification'), validators=[Optional()])
    euthanasia_method = TextAreaField(_l('Euthanasia Method'), validators=[Optional()])
    description = TextAreaField(_l('Project Description/Objectives'), validators=[Optional()])
    
    procedures = FieldList(FormField(ProcedureSubForm), min_entries=1, label=_l("Procedures"))
    
    team_id = SelectField(_l('Owning Team'), coerce=int, validators=[DataRequired(_l("Please select an owning team."))])
    shared_with_teams = SelectMultipleField(_l('Share with other Teams (Optional)'), coerce=int, validators=[Optional()])
    
    submit_ethical_approval = SubmitField(_l('Save Ethical Approval'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if user_has_permission(current_user, 'EthicalApproval', 'edit'):
            if current_user.is_super_admin:
                admin_of_teams = Team.query.order_by(Team.name).all()
            else:
                admin_of_teams = Team.query.order_by(Team.name).all()
            
            self.team_id.choices = [(t.id, t.name) for t in admin_of_teams]
            
            all_teams = Team.query.order_by(Team.name).all()
            self.shared_with_teams.choices = [(t.id, t.name) for t in all_teams]

            ea = kwargs.get('obj')
            if ea and ea.team_id:
                self.team_id.data = ea.team_id
                self.team_id.render_kw = {'disabled': True}
                self.shared_with_teams.choices = [(t.id, t.name) for t in all_teams if t.id != ea.team_id]


class LinkEthicalApprovalForm(FlaskForm):
    ethical_approvals = SelectMultipleField(_l('Link Ethical Approvals'), coerce=int, validators=[Optional()])
    submit_link_ethical_approval = SubmitField(_l('Update Linked Ethical Approvals'))

    def __init__(self, project=None, formdata=None, obj=None, **kwargs):
        super().__init__(formdata=formdata, obj=obj, **kwargs)
        if project and project.team:
            owned_eas = EthicalApproval.query.filter_by(team_id=project.team_id).all()
            shared_eas = project.team.shared_ethical_approvals.all()
            
            all_available_eas = sorted(list(set(owned_eas + shared_eas)), key=lambda ea: ea.reference_number)
            
            self.ethical_approvals.choices = [(ea.id, f"{ea.reference_number} - {ea.title}") for ea in all_available_eas]
            
            if formdata is None and self.ethical_approvals.data is None:
                 self.ethical_approvals.data = [ea.id for ea in project.ethical_approvals]
        else:
             self.ethical_approvals.choices = []


def get_ethical_approvals():
    return EthicalApproval.query.order_by(EthicalApproval.reference_number).all()


class EthicalApprovalStatisticsForm(FlaskForm):
    start_date = DateField(_l('Start Date (DataTables Creation)'), validators=[DataRequired()], widget=DateInput())
    end_date = DateField(_l('End Date (DataTables Creation)'), validators=[DataRequired()], widget=DateInput())
    severities = SelectMultipleField(_l('Include Severities'), choices=[(s.name, s.value) for s in Severity], validators=[DataRequired()], coerce=str)
    submit = SubmitField(_l('Export to XLSX'))
