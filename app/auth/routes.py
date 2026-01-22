from datetime import datetime

from flask import (current_app, flash, redirect, render_template, request,
                   url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required, login_user, logout_user
# Import for password reset token generation
from itsdangerous import (BadTimeSignature, SignatureExpired,
                          URLSafeTimedSerializer)

from ..extensions import db, limiter  # Import limiter
from ..forms import (LoginForm, RegistrationForm, RequestResetPasswordForm,
                     SetPasswordForm)
from ..helpers import confirm_token, generate_confirmation_token, send_email
from ..models import User
from itsdangerous import URLSafeTimedSerializer
# Import blueprint, extensions, models, forms, utils
from . import auth_bp


@auth_bp.route('/set_password/<token>', methods=['GET', 'POST'])
def set_password(token):
    """Allows an invited user to set their initial password."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    email = confirm_token(token)
    if not email:
        flash(_l('The password setup link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    if user.email_confirmed and user.password_hash: # If already set password and confirmed
        flash(_l('Your password has already been set. Please login.'), 'info')
        return redirect(url_for('auth.login'))

    form = SetPasswordForm()
    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            user.email_confirmed = True # Mark as confirmed once they set their password
            user.email_confirmed_on = datetime.now(current_app.config['UTC_TZ'])
            db.session.add(user)
            db.session.commit()
            flash(_l('Your password has been set successfully. You can now log in.'), 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error setting password for {email}: {e}")
            flash(_l('An error occurred while setting your password. Please try again.'), 'danger')
    
    return render_template('auth/set_password.html', title=_l('Set Password'), form=form, user=user, token=token)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Handles user registration."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index')) # Redirect logged-in users

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            # SECURITY FIX: Use a generic message to prevent user enumeration.
            flash(_l('If an account with this email does not already exist, a confirmation email has been sent. Please check your inbox.'), 'info')
            return redirect(url_for('auth.login'))
        try:
            user = User(email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()

            # Send confirmation email
            token = generate_confirmation_token(user.email)
            confirm_url = url_for('auth.confirm_email', token=token, _external=True)
            email_sent = send_email(
                to=user.email,
                subject=str(_l("Welcome to Precliniset! Please Confirm Your Email")),
                template_path='email/activate.html',
                confirm_url=confirm_url,
                user=user
            )

            if email_sent:
                flash(_l('A confirmation email has been sent. Please check your inbox.'), 'success')
            else:
                flash(_l('Account created but SMTP is not configured. Please contact an administrator to activate your account.'), 'warning')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error during registration for {form.email.data}: {str(repr(e))}")
            flash(_l('An error occurred during registration. Please try again.'), 'danger')

    return render_template('auth/register.html', title=_l('Register'), form=form)

@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    """Handles email confirmation links."""
    email = confirm_token(token)
    if not email:
        flash(_l('The confirmation link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    if user.email_confirmed:
        flash(_l('Account already confirmed. Please login.'), 'info')
    else:
        try:
            user.email_confirmed = True
            user.email_confirmed_on = datetime.now(current_app.config['UTC_TZ'])
            db.session.add(user)
            db.session.commit()
            flash(_l('You have confirmed your account. Thanks! You can now log in.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error confirming email for {email}: {e}")
            flash(_l('An error occurred while confirming your email. Please try again or contact support.'), 'danger')

    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute") # SECURITY FIX: Stricter rate limit for login attempts
def login():
    """Handles user login."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash(_l('Your account is inactive. Please contact an administrator.'), 'danger')
                return redirect(url_for('auth.login'))
            if user.email_confirmed:
                login_user(user, remember=form.remember.data)
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('main.index')
                flash(_l('Login Successful!'), 'success')
                return redirect(next_page)
            else:
                flash(_l('Please confirm your email address first. Check your inbox for the confirmation link.'), 'warning')
                return redirect(url_for('auth.login'))
        else:
            flash(_l('Login Unsuccessful. Please check email and password.'), 'danger')

    return render_template('auth/login.html', title=_l('Login'), form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    """Handles user logout."""
    logout_user()
    flash(_l('You have been logged out.'), 'success')
    return redirect(url_for('main.index'))

@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allows users to change their password. Forced if force_password_change is True."""
    from ..forms import \
        ChangePasswordForm  # Import locally to avoid circular imports if any
    form = ChangePasswordForm()
    
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash(_l('Invalid current password.'), 'danger')
        else:
            current_user.set_password(form.new_password.data)
            current_user.force_password_change = False # Reset the flag
            db.session.add(current_user)
            db.session.commit()
            flash(_l('Your password has been updated.'), 'success')
            return redirect(url_for('main.index'))
            
    return render_template('auth/change_password.html', title=_l('Change Password'), form=form)


@auth_bp.route('/reset_password_request', methods=['GET', 'POST'])
@limiter.limit("5 per hour") # Limit password reset requests
def reset_password_request():
    """Handles the request for a password reset."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RequestResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            # Generate a password reset token
            s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = s.dumps(user.email, salt='password-reset-salt')
            
            # Send password reset email
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            email_sent = send_email(
                to=user.email,
                subject=str(_l("Reset Your Precliniset Password")),
                template_path='email/reset_password.html', # New template
                reset_url=reset_url,
                user=user
            )
            if email_sent:
                flash(_l('A password reset email has been sent to your email address.'), 'info')
            else:
                flash(_l('SMTP is not configured. Please contact an administrator to reset your password.'), 'warning')
        else:
            # SECURITY FIX: Use a generic message to prevent user enumeration.
            flash(_l('If an account with that email exists, a password reset email has been sent.'), 'info')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/request_reset_password.html', title=_l('Reset Password'), form=form)


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Allows a user to set a new password via a reset token."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600) # Token valid for 1 hour
    except SignatureExpired:
        flash(_l('The password reset link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.login'))
    except BadTimeSignature:
        flash(_l('The password reset link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.login'))
    except Exception as e:
        current_app.logger.error(f"Error decoding password reset token: {e}")
        flash(_l('An error occurred with the password reset link.'), 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    form = SetPasswordForm() # Reuse the SetPasswordForm
    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            # Ensure email is confirmed and active if not already
            if not user.email_confirmed:
                user.email_confirmed = True
                user.email_confirmed_on = datetime.now(current_app.config['UTC_TZ'])
            # Consider activating user if they were inactive but now resetting password
            if not user.is_active:
                user.is_active = True 
            
            db.session.add(user)
            db.session.commit()
            flash(_l('Your password has been reset successfully. You can now log in.'), 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error resetting password for {email}: {e}")
            flash(_l('An error occurred while resetting your password. Please try again.'), 'danger')
    
    return render_template('auth/reset_password.html', title=_l('Reset Password'), form=form, user=user, token=token)


@auth_bp.route('/sso/training_manager')
@login_required
def sso_training_manager():
    """Redirects user to Training Manager with SSO token."""
    tm_url = current_app.config.get('TM_API_URL')
    if not tm_url:
        flash(_l('Training Manager URL not configured.'), 'danger')
        return redirect(url_for('main.index'))

    serializer = URLSafeTimedSerializer(current_app.config.get('SSO_SECRET_KEY'))
    token = serializer.dumps({'email': current_user.email}, salt='sso-salt')

    redirect_url = f"{tm_url.rstrip('/')}/auth/sso_login?token={token}"
    return redirect(redirect_url)

@auth_bp.route('/sso_login')
def sso_login():
    """Accepts SSO tokens from Training Manager."""
    token = request.args.get('token')
    if not token:
        flash(_l('Invalid SSO request'), 'danger')
        return redirect(url_for('auth.login'))

    serializer = URLSafeTimedSerializer(current_app.config.get('SSO_SECRET_KEY'))
    try:
        data = serializer.loads(token, max_age=30)
        email = data.get('email')
        if not email:
            flash(_l('Invalid SSO token'), 'danger')
            return redirect(url_for('auth.login'))

        user = User.query.filter_by(email=email).first()
        if not user or not user.is_active:
            flash(_l('User not found or not active'), 'danger')
            return redirect(url_for('auth.login'))

        login_user(user)
        flash(_l('Successfully logged in via Training Manager'), 'success')
        return redirect(url_for('main.index'))

    except (BadSignature, SignatureExpired):
        flash(_l('Invalid or expired SSO token'), 'danger')
        return redirect(url_for('auth.login'))

@auth_bp.before_app_request
def check_password_change_enforcement():
    """Forces users with force_password_change=True to change their password."""
    if current_user.is_authenticated and current_user.force_password_change:
        # Allow access to static files, logout, and the change_password route itself
        if (request.endpoint and
            request.endpoint not in ['auth.change_password', 'auth.logout', 'static'] and
            not request.endpoint.startswith('static')):
            flash(_l('You must change your password before proceeding.'), 'warning')
            return redirect(url_for('auth.change_password'))
