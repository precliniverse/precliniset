# app/forms/common.py
"""
Common base forms and utilities for the Precliniset application.
"""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


class CoreModelForm(FlaskForm):
    """Base form for core models with name field."""
    name = StringField(_l('Name'), validators=[DataRequired()])
    submit = SubmitField('Submit')


class GlobalSearchForm(FlaskForm):
    """Form for global search functionality."""
    q = StringField(_l('Search'), validators=[DataRequired(), Length(min=1, max=100)])
    submit = SubmitField(_l('Search'))
