# app/forms/admin.py
"""Admin and resource management forms."""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import (BooleanField, DateField, FieldList, FileField, FormField,
                     HiddenField, IntegerField, SelectField,
                     SelectMultipleField, StringField, SubmitField,
                     TextAreaField)
from wtforms.validators import (DataRequired, Email, Length, NumberRange,
                                Optional, ValidationError)

from app.models import (AnalyteDataType, ControlledMolecule, HousingConditionItem, ImportPipeline, SampleType,
                        Severity)
from app.widgets import DateInput

from .common import CoreModelForm


class OrganForm(FlaskForm):
    name = StringField(_l('Organ Name'), validators=[DataRequired(), Length(max=100)])
    submit = SubmitField(_l('Add Organ'))


class TissueConditionForm(FlaskForm):
    name = StringField(_l('Condition Name'), validators=[DataRequired(), Length(max=100)])
    submit = SubmitField(_l('Add Condition'))


class StainingForm(FlaskForm):
    name = StringField(_l('Staining/Treatment Name'), validators=[DataRequired(), Length(max=100)])
    submit = SubmitField(_l('Add Staining'))


class DerivedSampleTypeForm(FlaskForm):
    name = StringField(_l('Derived Type Name'), validators=[DataRequired(), Length(max=100)])
    parent_type = SelectField(_l('Parent Sample Type'), choices=[(st.name, st.value) for st in SampleType], validators=[DataRequired()])
    submit = SubmitField(_l('Add Derived Type'))


class AnalyteForm(FlaskForm):
    name = StringField(_l('Analyte Name'), validators=[DataRequired(), Length(max=100)])
    description = TextAreaField(_l('Description / Aliases'), validators=[Optional()])
    unit = StringField(_l('Unit'), validators=[Optional(), Length(max=50)])
    data_type = SelectField(_l('Data Type'), choices=[(dt.name, dt.value) for dt in AnalyteDataType], validators=[DataRequired()])
    allowed_values = StringField(_l('Allowed Values (for Category type)'), 
                                 description=_l("For 'Category' type, provide a semicolon-separated list of values (e.g., Value1;Value2;Value3)."),
                                 validators=[Optional()])
    default_value = StringField(_l('Default Value'), validators=[Optional()], 
                                description=_l("A default value for this analyte when added to a protocol. This can be edited in the datatable."))
    is_metadata = BooleanField(_l('Is Metadata?'), 
                               description=_l("If checked, this analyte will be treated as metadata and included in downloads/API extractions, but not in analysis/graphs."))
    submit = SubmitField(_l('Save Analyte'))

    def validate_allowed_values(self, field):
        if self.data_type.data == AnalyteDataType.CATEGORY.name and not field.data:
            raise ValidationError(_l("The 'Allowed Values' field is required when the data type is 'Category'."))
        if self.data_type.data != AnalyteDataType.CATEGORY.name and field.data:
            raise ValidationError(_l("The 'Allowed Values' field should only be filled out when the data type is 'Category'."))


class AnalyteUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Analytes'))


class OrganUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Organs'))


class DerivedSampleTypeUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Derived Sample Types'))


class TissueConditionUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Tissue Conditions'))


class StainingUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Stainings'))


class AnticoagulantForm(FlaskForm):
    name = StringField(_l('Anticoagulant Name'), validators=[DataRequired(), Length(max=100)])
    submit = SubmitField(_l('Add Anticoagulant'))


class AnticoagulantUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Anticoagellants'))


class HousingSetItemAssociationForm(FlaskForm):
    item_id = HiddenField()
    default_value = StringField(_l('Default Value'))


class HousingConditionSetForm(FlaskForm):
    name = StringField(_l('Set Name'), validators=[DataRequired(), Length(max=100)])
    description = TextAreaField(_l('Description'))
    
    item_associations = FieldList(FormField(HousingSetItemAssociationForm), min_entries=0)
    
    add_items = SelectMultipleField(_l('Add Housing Condition Items'), coerce=int, validators=[Optional()])
    submit_set = SubmitField(_l('Create Set'))

    def __init__(self, *args, **kwargs):
        super(HousingConditionSetForm, self).__init__(*args, **kwargs)
        self.add_items.choices = [(item.id, item.name) for item in HousingConditionItem.query.order_by(HousingConditionItem.name).all()]


class HousingConditionItemForm(FlaskForm):
    name = StringField(_l('Item Name'), validators=[DataRequired(), Length(max=100)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    data_type = SelectField(_l('Data Type'), choices=[(dt.name, dt.value) for dt in AnalyteDataType], validators=[DataRequired()])
    allowed_values = StringField(_l('Allowed Values (semicolon-separated for category type)'),
                                 description=_l("For 'Category' type, provide a semicolon-separated list of values (e.g., Value1;Value2;Value3)."),
                                 validators=[Optional()])
    default_value = StringField(_l('Default Value'), validators=[Optional()], 
                                description=_l("A default value for this item when added to a set. This can be edited in the set configuration."))
    unit = StringField(_l('Unit'), validators=[Optional(), Length(max=50)])
    submit_item = SubmitField(_l('Add Item'))

    def validate_allowed_values(self, field):
        if self.data_type.data == AnalyteDataType.CATEGORY.name and not field.data:
            raise ValidationError(_l("The 'Allowed Values' field is required when the data type is 'Category'."))
        if self.data_type.data != AnalyteDataType.CATEGORY.name and field.data:
            raise ValidationError(_l("The 'Allowed Values' field should only be filled out when the data type is 'Category'."))


class HousingDataUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload and Add/Update Housing Data'))


class ProtocolModelForm(FlaskForm):
    name = StringField(_l('Name'), validators=[DataRequired(), Length(max=80)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    url = StringField(_l('URL'), validators=[Optional(), Length(max=255)])
    attachment = FileField(_l('Attachment'), validators=[
        Optional(),
        FileAllowed(['jpg', 'png', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'zip'], _l('Allowed file types only!'))
    ])
    severity = SelectField(_l('Severity'), choices=[(s.name, s.value) for s in Severity], validators=[DataRequired()], coerce=str)
    controlled_molecules = SelectMultipleField(_l('Associated Controlled Molecules'), coerce=int, validators=[Optional()])
    import_pipelines = SelectMultipleField(_l('Linked Import Pipelines'), coerce=int, validators=[Optional()])
    enable_import_wizard = BooleanField(_l('Enable Raw Data Import Wizard?'), description=_l("If checked, users will be able to use an assistant to import data into datatables using this protocol."))
    submit = SubmitField(_l('Save Protocol Model'))

    def __init__(self, *args, **kwargs):
        super(ProtocolModelForm, self).__init__(*args, **kwargs)
        self.controlled_molecules.choices = [(m.id, f"{m.name} ({m.regulation_category.value})") 
                                            for m in ControlledMolecule.query.filter_by(is_active=True).order_by(ControlledMolecule.name).all()]
        self.import_pipelines.choices = [(p.id, p.name) for p in ImportPipeline.query.order_by(ImportPipeline.name).all()]


class CustomFieldForm(FlaskForm):
    field_name = StringField('Field Name', validators=[DataRequired()])
    field_type = StringField('Field Type', validators=[DataRequired()])
    unit = StringField('Unit', validators=[DataRequired()])
    prefill_value = StringField('Prefill Value')
    

class AnimalModelForm(CoreModelForm):
    name = StringField(_l('Name'), validators=[DataRequired(), Length(max=80)])
    date_of_birth = DateField(_l('Date of Birth'), validators=[Optional()], widget=DateInput())
    date_of_exclusion = DateField(_l('Date of Exclusion'), validators=[Optional()], widget=DateInput())
    severity = SelectField(_l('Severity'), choices=[(s.value, s.name) for s in Severity], validators=[Optional()])
    fields = FieldList(FormField(CustomFieldForm), min_entries=0)


class ProtocolBulkUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('XLSX files only!'))
    ])
    submit_upload = SubmitField(_l('Upload and Review'))


class AnimalModelBulkUploadForm(FlaskForm):
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('XLSX files only!'))
    ])
    submit_upload = SubmitField(_l('Upload and Review'))


class DeleteTeamForm(FlaskForm):
    submit = SubmitField(_l('Delete Team'))


class InviteMemberForm(FlaskForm):
    email = StringField(_l('User Email'), validators=[DataRequired(), Email()])
    role_id = SelectField(_l('Role'), coerce=int, validators=[DataRequired()])
    submit_invite_member = SubmitField(_l('Invite Member'))

    def __init__(self, team_id, *args, **kwargs):
        super(InviteMemberForm, self).__init__(*args, **kwargs)
        from app.models import Role
        self.role_id.choices = [(r.id, r.name) for r in Role.query.filter(
            (Role.team_id.is_(None)) | 
            (Role.team_id == team_id)
        ).order_by(Role.name).all()]
