# app/forms/misc.py
"""Miscellaneous forms."""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired


class RegenerateCalendarTokenForm(FlaskForm):
    submit_regenerate = SubmitField(_l('Generate New URL'))


class RegenerateTeamCalendarTokenForm(FlaskForm):
    submit_regenerate_team = SubmitField(_l('Generate New URL'))


class SearchForm(FlaskForm):
    q = StringField(_l('Search'), validators=[DataRequired()])

    def __init__(self, *args, **kwargs):
        if 'formdata' not in kwargs:
            kwargs['formdata'] = None
        if 'csrf_enabled' not in kwargs:
            kwargs['csrf_enabled'] = False
        super(SearchForm, self).__init__(*args, **kwargs)
