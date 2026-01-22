# app/forms/datatables.py
"""DataTable forms."""
from flask_babel import lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from werkzeug.datastructures import FileStorage
from wtforms import FileField, SelectField, StringField, SubmitField, URLField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.extensions import db
from app.models import ExperimentalGroup, Project, ProtocolModel
from app.permissions import can_create_datatable_for_group

# Helper function kept for legacy or specific uses, but not called by default in form init
def get_project_groups(project_id=None, include_archived=False):
    query = ExperimentalGroup.query
    
    if project_id:
        project = db.session.get(Project, project_id)
        if not project:
            return ExperimentalGroup.query.filter(db.false())

        if not include_archived and project.is_archived:
            return ExperimentalGroup.query.filter(db.false())

        query = query.filter_by(project_id=project_id)
    else:
        accessible_projects = current_user.get_accessible_projects(include_archived=include_archived)
        if not accessible_projects:
            return ExperimentalGroup.query.filter(db.false())
        
        project_ids = [p.id for p in accessible_projects]
        query = ExperimentalGroup.query.filter(ExperimentalGroup.project_id.in_(project_ids))

    if not include_archived:
        query = query.filter(ExperimentalGroup.is_archived == False)
        if not project_id:
             query = query.join(ExperimentalGroup.project).filter(Project.is_archived == False)

    # Limit results to prevent memory crashes if called directly
    all_groups = query.options(db.selectinload(ExperimentalGroup.project)).order_by(ExperimentalGroup.name).limit(50).all()
    
    if not all_groups:
        return []

    from app.services.permission_service import PermissionService
    perm_service = PermissionService()
    unique_projects = {g.project for g in all_groups if g.project}
    project_permissions = perm_service.get_bulk_project_permissions(current_user, unique_projects)
    
    accessible_groups = []
    for g in all_groups:
        if g.project:
            perms = project_permissions.get(g.project.id, {})
            if perms.get('can_create_datatables', False):
                accessible_groups.append(g)
    
    return accessible_groups


def get_protocol_models():
    return ProtocolModel.query.order_by(ProtocolModel.name)

def coerce_int_or_keep_placeholder(value):
    if value == '':
        return ''
    try:
        return int(value)
    except (ValueError, TypeError):
        return value

class DataTableForm(FlaskForm):
    group = SelectField(
        _l('Experimental Group'),
        validators=[DataRequired(_l('Please select a group.'))],
        validate_choice=False  # CRITICAL: Allows AJAX values not present at init
    )
    protocol = SelectField(
        _l('Protocol Model'),
        coerce=coerce_int_or_keep_placeholder,
        validators=[DataRequired(_l('Please select a protocol.'))]
    )
    date = StringField(_l('Date'), validators=[DataRequired(), Length(max=80)])
    assigned_to_id = SelectField(_l('Assign To'), coerce=lambda x: int(x) if str(x).isdigit() else None, validators=[Optional()])
    housing_condition_set_id = SelectField(_l('Housing Conditions'), coerce=lambda x: int(x) if x else None, validators=[Optional()])
    submit = SubmitField(_l('Create Data Table'))

    def __init__(self, project_id=None, include_archived=False, group_id_prefill=None, *args, **kwargs):
        from app.models import HousingConditionSet
        super().__init__(*args, **kwargs)
        
        # --- OPTIMIZATION: Do NOT load all groups by default ---
        self.group.choices = []
        
        # Handle Prefill Case (Creation from Group Page)
        if group_id_prefill:
            prefill_group = db.session.get(ExperimentalGroup, group_id_prefill)
            if prefill_group:
                self.group.choices = [(str(prefill_group.id), f"{prefill_group.name} ({prefill_group.project.name})")]
                self.group.data = str(prefill_group.id)
        
        # Handle Edit Case (Existing Object)
        elif 'obj' in kwargs and kwargs['obj'] and kwargs['obj'].group:
             g = kwargs['obj'].group
             self.group.choices = [(str(g.id), f"{g.name} ({g.project.name})")]
             self.group.data = str(g.id)
             
        # Handle Postback Case (Form submitted with errors)
        elif self.group.data:
             # Try to fetch the submitted group to repopulate the choice
             g = db.session.get(ExperimentalGroup, self.group.data)
             if g:
                 self.group.choices = [(str(g.id), f"{g.name} ({g.project.name})")]

        # Standard Fields
        self.protocol.choices = [(p.id, p.name) for p in get_protocol_models()]
        self.protocol.choices.insert(0, ('', _l('Select Protocol Model...')))
        
        self.assigned_to_id.choices = [('', '-- ' + _l('Unassigned') + ' --')]

        self.housing_condition_set_id.choices = [('', '-- ' + _l('None') + ' --')] + [(hc.id, hc.name) for hc in HousingConditionSet.query.order_by(HousingConditionSet.name).all()]


class MultipleFileField(FileField):
    def process_formdata(self, valuelist):
        if valuelist:
            self.data = [v for v in valuelist if isinstance(v, FileStorage) and v.filename]
        else:
            self.data = []


class EditDataTableForm(FlaskForm):
    raw_data_url = URLField(_l('Raw Data URL'), validators=[Optional(), Length(max=512)])
    files = MultipleFileField(_l('Upload Files'), validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'pdf'], _l('Images and PDFs only!')),
    ])
    submit_edit = SubmitField(_l('Save Changes'))

    def validate_files(self, field):
        if field.data:
            for file in field.data:
                if file.content_length > 5 * 1024 * 1024:
                    raise ValidationError(_l('File size must be less than 5MB'))


class DataTableUploadForm(FlaskForm):
    file = FileField(_l('Upload CSV/XLSX File'), validators=[
        FileAllowed(['csv', 'xlsx', 'xls'], _l('Only CSV and Excel files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Overwrite'))