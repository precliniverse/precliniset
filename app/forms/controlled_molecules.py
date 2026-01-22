# app/forms/controlled_molecules.py
"""Forms for controlled molecules management."""
from decimal import Decimal

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (BooleanField, DecimalField, HiddenField, IntegerField,
                     SelectField, SelectMultipleField, StringField,
                     SubmitField, TextAreaField)
from wtforms.validators import (DataRequired, Length, NumberRange, Optional,
                                 Regexp)

from app.models import ControlledMolecule, RegulationCategory, User


class ControlledMoleculeForm(FlaskForm):
    """Form for creating/editing a controlled molecule."""
    name = StringField(_l('Molecule Name'), validators=[DataRequired(), Length(max=200)])
    regulation_category = SelectField(
        _l('Regulation Category'),
        choices=[(cat.name, cat.value) for cat in RegulationCategory],
        validators=[DataRequired()],
        coerce=str
    )
    storage_location = StringField(_l('Storage Location'), validators=[Optional(), Length(max=500)])
    responsible_id = SelectField(
        _l('Responsible Person'),
        coerce=int,
        validators=[Optional()],
        description=_l("Designate a responsible person for this controlled substance")
    )
    cas_number = StringField(
        _l('CAS Number'),
        validators=[Optional(), Length(max=50)],
        description=_l("Chemical Abstracts Service registry number (optional)")
    )
    internal_reference = StringField(
        _l('Internal Reference'),
        validators=[Optional(), Length(max=100)],
        description=_l("Your internal tracking reference")
    )
    unit = StringField(
        _l('Unit'),
        validators=[Optional(), Length(max=20)],
        description=_l("e.g., mL, mg, UI, g")
    )
    requires_secure_prescription = BooleanField(
        _l('Requires Secure Prescription'),
        description=_l("Check if this substance requires a secure prescription (ordonnance sécurisée)")
    )
    max_prescription_days = IntegerField(
        _l('Max Prescription Days'),
        validators=[Optional(), NumberRange(min=1, max=365)],
        description=_l("Regulatory maximum prescription duration (e.g., 28 days for most narcotics)")
    )
    notes = TextAreaField(_l('Notes'), validators=[Optional()])
    is_active = BooleanField(_l('Active'), default=True)
    submit = SubmitField(_l('Save Molecule'))

    def __init__(self, *args, **kwargs):
        super(ControlledMoleculeForm, self).__init__(*args, **kwargs)
        # Populate responsible_id choices
        self.responsible_id.choices = [(0, _l('-- Select Responsible Person --'))] + [
            (u.id, u.email) for u in User.query.order_by(User.email).all()
        ]


class MoleculeUsageForm(FlaskForm):
    """Form for recording controlled molecule usage in a DataTable."""
    molecule_id = HiddenField(validators=[DataRequired()])
    volume_used = DecimalField(
        _l('Volume/Quantity Used'),
        validators=[DataRequired(), NumberRange(min=0)],
        places=4,
        description=_l("Actual volume or quantity used")
    )
    # Changed to HiddenField as it will be calculated from selected animals
    number_of_animals = HiddenField(validators=[Optional()])
    # Store selected animal IDs as JSON string or comma-separated values
    animal_ids = HiddenField(validators=[Optional()])
    
    batch_number = StringField(
        _l('Batch/Lot Number'),
        validators=[Optional(), Length(max=100)],
        description=_l("Batch or lot number of the substance")
    )
    administration_route = StringField(
        _l('Administration Route'),
        validators=[Optional(), Length(max=100)],
        description=_l("Route of administration (e.g., IV, IP, SC, oral)")
    )
    notes = TextAreaField(_l('Notes'), validators=[Optional()])


class ControlledMoleculeUploadForm(FlaskForm):
    """Form for bulk upload of controlled molecules (future feature)."""
    file = FileField(_l('XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_upload = SubmitField(_l('Upload Controlled Molecules'))
