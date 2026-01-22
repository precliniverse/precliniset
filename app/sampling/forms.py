# app/sampling/forms.py
from datetime import date

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import (BooleanField, DateField, FieldList, FloatField, FormField,
                     HiddenField, SelectField, SelectMultipleField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from wtforms_sqlalchemy.fields import QuerySelectField

from app import db
from app.models import (Anticoagulant, Organ, SampleStatus, SampleType,
                        Staining, Storage, TissueCondition)
from app.widgets import DateInput


def organ_query_factory():
    return Organ.query.order_by(Organ.name)

def get_organ_label(item):
    return item.name

def staining_query_factory():
    return Staining.query.order_by(Staining.name)

def anticoagulant_query_factory():
    return Anticoagulant.query.order_by(Anticoagulant.name)

def get_anticoagulant_label(item):
    return item.name

class BatchCommonSampleDetailsForm(FlaskForm):
    collection_date = DateField(
        _l('Collection Date for Event'),
        validators=[DataRequired(_l("Collection date is required."))],
        widget=DateInput(),
        default=date.today,
        description=_l("This date will apply to all samples logged in this batch.")
    )
    is_terminal_event = BooleanField(
        _l('Terminal Procedure for this Event?'),
        default=False,
        description=_l("If checked, all samples logged in this batch will be marked as terminal.")
    )
    default_storage_id = SelectField(
        _l('Default Storage Location for Event'),
        validators=[Optional()],
        coerce=lambda x: int(x) if isinstance(x, str) and x.isdigit() else (x if isinstance(x, int) else None),
        description=_l("Default storage for all samples in this batch. Can be overridden per sample.")
    )
    status = SelectField(
        _l('Initial Status'),
        choices=[(SampleStatus.TO_BE_COLLECTED.name, SampleStatus.TO_BE_COLLECTED.value),
                 (SampleStatus.STORED.name, SampleStatus.STORED.value)],
        default=SampleStatus.STORED.name,
        validators=[DataRequired()],
        coerce=SampleStatus.coerce,
        description=_l("Set the initial status for all samples in this batch.")
    )
    event_notes = TextAreaField(
        _l('General Notes for this Sampling Event'),
        validators=[Optional(), Length(max=1000)],
        description=_l("These notes will be appended to or used as base for individual sample notes if not overridden.")
    )

    def __init__(self, team_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        storage_choices = [('', _l('-- Select Default Storage --'))]
        if team_id:
            storages = Storage.query.filter_by(team_id=team_id).order_by(Storage.name).all()
            storage_choices.extend(
                [(s.id, f"{s.name} ({s.location_details or _l('No details')})") for s in storages]
            )
        else:
            storage_choices.append(('', _l('-- No Team Context for Storage --')))
        self.default_storage_id.choices = storage_choices

class SingleSampleForm(FlaskForm):
    """
    Un formulaire unique et robuste pour éditer tous les aspects d'un échantillon.
    """
    # Champs communs
    sample_type = SelectField(_l('Sample Type'), choices=[(st.name, st.value) for st in SampleType], coerce=str, render_kw={"disabled": True})
    collection_date = DateField(_l('Collection Date'), validators=[DataRequired()], widget=DateInput())
    is_terminal = BooleanField(_l('Terminal Procedure?'))
    status = SelectField(_l('Status'), choices=SampleStatus.choices(), coerce=SampleStatus.coerce, validators=[DataRequired()])
    storage_id = SelectField(_l('Storage Location'), coerce=lambda x: int(x) if str(x).isdigit() else None, validators=[Optional()])
    notes = TextAreaField(_l('Notes'), validators=[Optional(), Length(max=2000)])
    
    # Champs spécifiques
    anticoagulant = QuerySelectField(_l('Anticoagulant'), query_factory=anticoagulant_query_factory, get_label=get_anticoagulant_label, allow_blank=True, blank_text='-- Select Anticoagulant --', validators=[Optional()])
    volume = FloatField(_l('Volume'), validators=[Optional(), NumberRange(min=0)])
    volume_unit = StringField(_l('Volume Unit'), validators=[Optional(), Length(max=20)])
    
    organ_id = QuerySelectField(_l('Organ/Tissue'), query_factory=organ_query_factory, get_label='name', allow_blank=True, blank_text='-- Select Organ --', validators=[Optional()])
    piece_id = StringField(_l('Piece ID / Sub-location'), validators=[Optional(), Length(max=100)])
    collection_conditions = SelectMultipleField(_l('Collection Conditions'), coerce=int, validators=[Optional()])
    staining_id = QuerySelectField(_l('Staining'), query_factory=staining_query_factory, get_label='name', allow_blank=True, blank_text='-- Select Staining --', validators=[Optional()])
    other_description = TextAreaField(_l('Description (for Other type)'), validators=[Optional(), Length(max=500)])
    
    # Champs pour la mise à jour du statut
    shipment_destination = StringField(_l('Shipment Destination'), validators=[Optional(), Length(max=255)])
    
    submit = SubmitField(_l('Update Sample'))

    def __init__(self, team_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        storage_choices = [('', _l('-- No Storage --'))]
        if team_id:
            storages = Storage.query.filter_by(team_id=team_id).order_by(Storage.name).all()
            storage_choices.extend([(s.id, f"{s.name} ({s.location_details or _l('No details')})") for s in storages])
        self.storage_id.choices = storage_choices
        self.collection_conditions.choices = [(c.id, c.name) for c in TissueCondition.query.order_by(TissueCondition.name).all()]

    def validate(self, extra_validators=None):
        # Custom validation for status dates is removed as they are now auto-set.
        return super().validate(extra_validators)

def storage_location_query_factory():
    return Storage.query.order_by(Storage.name)

def get_storage_location_label(item):
    return f"{item.name} ({item.location_details or _l('No details')})"

class ChangeStorageForm(FlaskForm):
    new_storage_location = QuerySelectField(
        _l('New Storage Location'),
        query_factory=storage_location_query_factory,
        get_label=get_storage_location_label,
        allow_blank=False,
        blank_text=_l('-- Select New Storage --'),
        validators=[DataRequired(_l("Please select a storage location."))]
    )
    submit = SubmitField(_l('Change Storage'))
