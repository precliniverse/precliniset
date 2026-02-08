# app/forms/groups.py
"""Experimental group forms."""
from flask_babel import lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.extensions import db
from app.models import AnimalModel, Project
from app.services.ethical_approval_service import (
    get_animals_available_for_ea, get_eligible_ethical_approvals)


def get_animal_models():
    return AnimalModel.query.order_by(AnimalModel.name)

def coerce_int_or_keep_placeholder(value):
    if value == '':
        return ''
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot coerce '{value}' to int for SelectField.")

class GroupForm(FlaskForm):
    project = SelectField(
        _l('Project'),
        coerce=coerce_int_or_keep_placeholder,
        validators=[DataRequired(_l('Please select a project.'))],
        validate_choice=False
    )
    name = StringField(_l('Group Name'), validators=[DataRequired(), Length(max=80)])
    model = SelectField(
        _l('Animal Model'),
        coerce=coerce_int_or_keep_placeholder,
        validators=[DataRequired(_l('Please select an animal model.'))]
    )
    ethical_approval = SelectField(
        _l('Ethical Approval'),
        coerce=coerce_int_or_keep_placeholder,
        validators=[Optional()]
    )
    default_euthanasia_reason = SelectField(
        _l('Default Euthanasia Reason'),
        choices=[
            ('', _l('Select reason...')),
            ('état de santé', _l('état de santé')),
            ('fin de protocole', _l('fin de protocole')),
            ('atteinte d\'un point limite', _l('atteinte d\'un point limite'))
        ],
        validators=[Optional()]
    )
    default_severity = SelectField(
        _l('Default Severity'),
        choices=[
            ('', _l('Select severity...')),
            ('légère', _l('légère')),
            ('modérée', _l('modérée')),
            ('sévère', _l('sévère'))
        ],
        validators=[Optional()]
    )
    submit = SubmitField(_l('Save Group'))

    def __init__(self, *args, **kwargs):
        editing_group = kwargs.get('obj')
        formdata = kwargs.get('formdata')
        team_id_for_eas = kwargs.pop('team_id_for_eas', None)
        prefilled_project = kwargs.pop('prefilled_project', None)
        
        self.original_name = None
        if editing_group and editing_group.name:
            self.original_name = editing_group.name

        super().__init__(*args, **kwargs)

        # Lazy loading projects via AJAX on the frontend.
        # Initialize choices with an empty list or the current project if editing/prefilled.
        project_choices = []
        if editing_group and editing_group.project:
            project_choices = [(editing_group.project.id, editing_group.project.name)]
        elif prefilled_project:
            project_choices = [(prefilled_project.id, prefilled_project.name)]
        
        self.project.choices = [('', _l('Select Project...'))] + project_choices

        model_choices = [(m.id, m.name) for m in get_animal_models()]
        self.model.choices = [('', _l('Select Model...'))] + model_choices

        self.ethical_approval.choices = [('', _l('Select Ethical Approval...'))]
        
        selected_project_id = None
        if editing_group and editing_group.project:
            selected_project_id = editing_group.project.id
        elif prefilled_project:
            selected_project_id = prefilled_project.id
            if not self.project.data:
                self.project.data = prefilled_project.id
        elif formdata and 'project' in formdata and formdata['project'] != '':
            try:
                selected_project_id = int(formdata['project'])
            except ValueError:
                pass 

        if selected_project_id and team_id_for_eas:
            eligible_eas = get_eligible_ethical_approvals(selected_project_id, team_id_for_eas)
            self.ethical_approval.choices.extend(
                [(ea.id, f"{ea.reference_number} - {ea.title} ({ea.owner_team.name}) [Available: {get_animals_available_for_ea(ea)}]") for ea in eligible_eas]
            )
        else:
            self.ethical_approval.choices = [('', _l('Select a project first...'))]
        


        if editing_group:
            self.project.validators = [v for v in self.project.validators if not isinstance(v, DataRequired)]
            if not any(isinstance(v, Optional) for v in self.project.validators):
                self.project.validators.append(Optional())

            if formdata is None:
                if editing_group.project_id:
                    self.project.data = editing_group.project_id
                if editing_group.model_id:
                    self.model.data = editing_group.model_id
                if editing_group.ethical_approval_id:
                    self.ethical_approval.data = editing_group.ethical_approval_id
                if editing_group.default_euthanasia_reason:
                    self.default_euthanasia_reason.data = editing_group.default_euthanasia_reason
                if editing_group.default_severity:
                    self.default_severity.data = editing_group.default_severity
        else:
            if not any(isinstance(v, DataRequired) for v in self.project.validators):
                self.project.validators.insert(0, DataRequired(_l('Please select a project.')))
            if not any(isinstance(v, DataRequired) for v in self.model.validators):
                self.model.validators.insert(0, DataRequired(_l('Please select an animal model.')))

    def validate_name(self, field):
        from app.models import ExperimentalGroup
        
        # Only validate if a project is selected
        if self.project.data:
            query = ExperimentalGroup.query.filter_by(
                project_id=self.project.data,
                name=field.data
            )
            
            # If editing an existing group, exclude the current group from the uniqueness check

            if hasattr(self, 'obj') and self.obj and self.obj.id:  # self.obj refers to the instance of the model passed to the form
                query = query.filter(ExperimentalGroup.id != self.obj.id)
            
            if query.first():
                raise ValidationError(_l('A group with this name already exists in the selected project. Please choose a different name.'))