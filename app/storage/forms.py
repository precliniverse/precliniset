from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class StorageForm(FlaskForm):
    name = StringField(_l('Storage Name'), validators=[DataRequired(), Length(min=3, max=100)])
    capacity = StringField(_l('Capacity (e.g., 1000 tubes, 3 shelves)'), validators=[Optional(), Length(max=100)])
    location_details = TextAreaField(_l('Location Details (e.g., Freezer -80C, Room 4B, Shelf 2)'), validators=[Optional(), Length(max=500)])
    submit = SubmitField(_l('Save Storage'))