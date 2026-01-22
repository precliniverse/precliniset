# app/forms/workplans.py
"""Workplan forms."""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import FileField, IntegerField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange


class WorkplanForm(FlaskForm):
    name = StringField(_l('Workplan Name'), validators=[DataRequired(), Length(max=150)])
    planned_animal_count = IntegerField(_l('Planned Number of Animals'), validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField(_l('Create Workplan'))


class WorkplanImportForm(FlaskForm):
    xlsx_file = FileField(_l('Upload XLSX File'), validators=[
        DataRequired(),
        FileAllowed(['xlsx'], _l('Only .xlsx files are allowed.'))
    ])
    submit_import = SubmitField(_l('Import Workplan'))
