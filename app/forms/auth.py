# app/forms/auth.py
"""
Authentication and password management forms for the Precliniset application.
"""
from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


class RegistrationForm(FlaskForm):
    """Form for user registration."""
    email = StringField(_l('Email'),
                           validators=[DataRequired(), Email()])
    password = PasswordField(_l('Password'), validators=[DataRequired()])
    confirm_password = PasswordField(_l('Confirm Password'),
                                     validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField(_l('Sign Up'))


class LoginForm(FlaskForm):
    """Form for user login."""
    email = StringField(_l('Email'),
                        validators=[DataRequired(), Email()])
    password = PasswordField(_l('Password'), validators=[DataRequired()])
    remember = BooleanField(_l('Remember Me'))
    submit = SubmitField(_l('Login'))


class SetPasswordForm(FlaskForm):
    """Form for setting a new password (e.g., first login or password reset)."""
    password = PasswordField(_l('New Password'), validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(_l('Confirm New Password'),
                                     validators=[DataRequired(), EqualTo('password', message=_l('Passwords must match.'))])
    submit = SubmitField(_l('Set Password'))


class ChangePasswordForm(FlaskForm):
    """Form for changing password when user is logged in."""
    current_password = PasswordField(_l('Current Password'), validators=[DataRequired()])
    new_password = PasswordField(_l('New Password'), validators=[DataRequired(), Length(min=8)])
    confirm_new_password = PasswordField(_l('Confirm New Password'),
                                         validators=[DataRequired(), EqualTo('new_password', message=_l('Passwords must match.'))])
    submit_password = SubmitField(_l('Change Password'))


class ChangeEmailForm(FlaskForm):
    """Form for changing email address."""
    new_email = StringField(_l('New Email'), validators=[DataRequired(), Email()])
    current_password = PasswordField(_l('Current Password (for verification)'), validators=[DataRequired()])
    submit_email = SubmitField(_l('Request Email Change'))


class SmtpSettingsForm(FlaskForm):
    """Form for SMTP settings and testing."""
    test_email = StringField(_l('Test Email Address'), validators=[Email(), Optional()], 
                            description=_l("Enter an email address to send a test message to. If left blank, it will be sent to your own email address."))
    submit_test_email = SubmitField(_l('Send Test Email'))


class RequestResetPasswordForm(FlaskForm):
    """Form for requesting a password reset."""
    email = StringField(_l('Email'), validators=[DataRequired(), Email()])
    submit = SubmitField(_l('Request Password Reset'))
