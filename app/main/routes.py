from flask import (current_app, flash, redirect, render_template, request,
                   Response, session, url_for)
from flask_babel import Babel
from flask_babel import gettext as _  # Import gettext and Babel
from flask_login import (current_user, login_required,  # Added logout_user
                         logout_user)
from sqlalchemy import distinct, func, or_

from app.extensions import db  # Assuming db is initialized in extensions
from app.forms import (ChangeEmailForm, ChangePasswordForm, CkanSettingsForm,
                       CreateAPITokenForm, GlobalSearchForm,
                       RegenerateCalendarTokenForm,
                       RegenerateTeamCalendarTokenForm, SmtpSettingsForm)
from app.helpers import (confirm_token,  # Changed from app.utils
                         generate_confirmation_token, send_email)
from app.models import (AnimalModel, APIToken, DataTable, EthicalApproval,
                        ExperimentalGroup, Partner, Project, ProtocolModel,
                        TeamMembership, User)

from ..permissions import (check_datatable_permission, check_group_permission,
                           check_project_permission)
from . import main_bp  # Import the blueprint instance

# Define routes using the blueprint instance

@main_bp.route('/')
def index():
    """
    Renders the main index page.
    Redirects authenticated users to their 'My Page'.
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.my_page'))
    
    # For unauthenticated users, show the original welcome page
    try:
        return render_template('main/index.html') # This is your current welcome page
    except Exception as e:
        current_app.logger.error(f"Error rendering index template: {e}", exc_info=True)
        return "<h1>Internal Server Error</h1>", 500

@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Handles user settings, including password, email, and language changes."""
    password_form = ChangePasswordForm(prefix='pw')
    email_form = ChangeEmailForm(prefix='em')
    smtp_test_form = SmtpSettingsForm(prefix='smtp_test')
    api_token_form = CreateAPITokenForm(prefix='api')
    ckan_form = CkanSettingsForm(prefix='ckan', obj=current_user)
    calendar_token_form = RegenerateCalendarTokenForm(prefix='cal')
    team_calendar_token_form = RegenerateTeamCalendarTokenForm(prefix='team_cal')
    language = session.get('language', 'en')
    newly_generated_token = None

    if request.method == 'POST':
        if password_form.submit_password.data and password_form.validate_on_submit():
            if current_user.check_password(password_form.current_password.data):
                current_user.set_password(password_form.new_password.data)
                db.session.commit()
                flash(_('Your password has been updated successfully.'), 'success')
            else:
                flash(_('Invalid current password.'), 'danger')
            return redirect(url_for('main.settings'))

        if email_form.submit_email.data and email_form.validate_on_submit():
            if current_user.check_password(email_form.current_password.data):
                new_email = email_form.new_email.data
                existing_user = User.query.filter(User.email == new_email, User.id != current_user.id).first()
                if existing_user:
                    flash(_('That email address is already in use.'), 'danger')
                elif new_email == current_user.email:
                     flash(_('Please enter a different email address.'), 'warning')
                else:
                    token = generate_confirmation_token(new_email)
                    confirm_url = url_for('main.confirm_email', token=token, _external=True)
                    send_email(
                        to=new_email,
                        subject=_('Confirm Your New Email Address'),
                        template_path='email/change_email.html',
                        user=current_user,
                        confirm_url=confirm_url
                    )
                    flash(_('A confirmation email has been sent to {}. Please check your inbox.').format(new_email), 'info')
            else:
                flash(_('Invalid current password.'), 'danger')
            return redirect(url_for('main.settings'))

        # --- START MODIFICATION ---
        # Move the test email logic INSIDE the POST block
        if smtp_test_form.submit_test_email.data and smtp_test_form.validate_on_submit():
            test_email_address = smtp_test_form.test_email.data or current_user.email
            try:
                send_email(
                    to=test_email_address,
                    subject=_('Precliniset Test Email'),
                    template_path='email/test_email.html',
                    user=current_user
                )
                flash(_('Test email sent successfully to {}.').format(test_email_address), 'success')
            except Exception as e:
                current_app.logger.error(f"Error sending test email: {e}", exc_info=True)
                flash(_('Failed to send test email. Please check the application logs and ensure your .env file has the correct MAIL_ settings. Error: {}').format(e), 'danger')
            return redirect(url_for('main.settings'))
        # --- END MODIFICATION ---

        if 'submit_language' in request.form and 'language' in request.form:
            language = request.form['language']
            if language in current_app.config['LANGUAGES']:
                session['language'] = language
                flash(_('Language updated successfully.'), 'success')
            else:
                flash(_('Invalid language selection.'), 'danger')
            return redirect(url_for('main.settings'))

        if api_token_form.submit_create_token.data and api_token_form.validate_on_submit():
            token_name = api_token_form.name.data
            existing_token_with_name = APIToken.query.filter_by(user_id=current_user.id, name=token_name).first()
            if existing_token_with_name:
                flash(_("You already have a token with the name '%(name)s'. Please choose a different name.", name=token_name), 'warning')
            else:
                api_token = APIToken(user_id=current_user.id, name=token_name)
                db.session.add(api_token)
                db.session.commit()
                newly_generated_token = api_token.raw_token
                flash(_("API Token '%(name)s' created successfully. Make sure to copy your token now. You will not be able to see it again.", name=token_name), 'success')
            return redirect(url_for('main.settings', _anchor='api-tokens-section', new_token=newly_generated_token))

        if calendar_token_form.submit_regenerate.data and calendar_token_form.validate_on_submit():
            current_user.generate_calendar_token()
            db.session.commit()
            flash(_('Your personal calendar URL has been regenerated. Please update your calendar application.'), 'success')
            return redirect(url_for('main.settings', _anchor='calendar-subscription-section'))

        if team_calendar_token_form.submit_regenerate_team.data and team_calendar_token_form.validate_on_submit():
            current_user.generate_team_calendar_token()
            db.session.commit()
            flash(_('Your team calendar URL has been regenerated. Please update your calendar application.'), 'success')
            return redirect(url_for('main.settings', _anchor='calendar-subscription-section'))

        if ckan_form.submit_ckan_settings.data and ckan_form.validate_on_submit():
            current_user.ckan_url = ckan_form.ckan_url.data.strip()
            current_user.ckan_api_key = ckan_form.ckan_api_key.data.strip()
            db.session.commit()
            flash(_('CKAN settings updated successfully.'), 'success')
            return redirect(url_for('main.settings', _anchor='ckan-settings-section'))

    # This part is for GET requests
    user_api_tokens = APIToken.query.filter_by(user_id=current_user.id).order_by(APIToken.created_at.desc()).all()
    
    if request.args.get('new_token'):
        newly_generated_token = request.args.get('new_token')

    # --- START MODIFICATION ---
    # Correct the variable name in the render_template call
    return render_template('main/settings.html', title=_('Settings'),
                           password_form=password_form, email_form=email_form,
                           smtp_test_form=smtp_test_form,
                           ckan_form=ckan_form,
                           calendar_token_form=calendar_token_form,
                           team_calendar_token_form=team_calendar_token_form,
                           current_language=language,
                           api_token_form=api_token_form,
                           user_api_tokens=user_api_tokens,
                           newly_generated_token=newly_generated_token,
                           current_app=current_app)


@main_bp.route('/settings/api_tokens/<int:token_id>/revoke', methods=['POST'])
@login_required
def revoke_api_token(token_id):
    token_to_revoke = APIToken.query.filter_by(id=token_id, user_id=current_user.id).first_or_404()
    # Instead of deleting, mark as inactive or actually delete
    # db.session.delete(token_to_revoke) # Option 1: Permanent delete
    token_to_revoke.is_active = False # Option 2: Mark as inactive
    db.session.commit()
    flash(_("API Token '%(name)s' has been revoked.", name=token_to_revoke.name), 'success')
    return redirect(url_for('main.settings', _anchor='api-tokens-section'))

@main_bp.route('/search', methods=['GET'])
@login_required
def search_results():
    query_string = request.args.get('q', '').strip()
    # Pass csrf_enabled=False if you are using Option 1 for form validation
    # If using Option 2 (manual length check), this instantiation is mainly for the template
    search_form = GlobalSearchForm(request.args, csrf_enabled=False) 

    current_app.logger.debug(f"SEARCH_DEBUG: Raw 'q' from request.args: '{request.args.get('q')}'")
    current_app.logger.debug(f"SEARCH_DEBUG: Stripped query_string for logic: '{query_string}'")

    results = {
        'projects': [], 'groups': [], 'ethical_approvals': [],
        'protocols': [], 'animal_models': [], 'partners': [], 'datatables': []
    }
    search_performed = False
    
    if query_string:
        if not (1 <= len(query_string) <= 100): # Manual length check
            flash(_("Search term is too short or too long."), "warning")
            search_performed = True
        else:
            search_performed = True
            term = f"%{query_string}%"
            current_app.logger.info(f"Performing search with term: {term}")
            user_teams_ids = [t.id for t in current_user.get_teams()]

            # --- Search Projects ---
            project_query = Project.query.filter(
                or_(Project.name.ilike(term), Project.description.ilike(term), Project.slug.ilike(term))
            )
            all_found_projects_raw = project_query.all()
            current_app.logger.debug(f"SEARCH_RAW_RESULTS: Found {len(all_found_projects_raw)} projects before permission check.")
            # for p_debug in all_found_projects_raw: current_app.logger.debug(f"  - Raw Project: {p_debug.name}")
            
            results['projects'] = [p for p in all_found_projects_raw if check_project_permission(p, 'read')]
            current_app.logger.debug(f"SEARCH_FILTERED_RESULTS: {len(results['projects'])} projects after permission check.")

            # --- Search Experimental Groups ---
            group_query = ExperimentalGroup.query.filter(
                or_(ExperimentalGroup.name.ilike(term), ExperimentalGroup.id.ilike(term))
            )
            all_found_groups_raw = group_query.all()
            current_app.logger.debug(f"SEARCH_RAW_RESULTS: Found {len(all_found_groups_raw)} groups before permission check.")
            
            results['groups'] = [g for g in all_found_groups_raw if check_group_permission(g, 'read')]
            current_app.logger.debug(f"SEARCH_FILTERED_RESULTS: {len(results['groups'])} groups after permission check.")
            
            # --- Search Ethical Approvals ---
            ea_query = EthicalApproval.query.filter(
                or_(EthicalApproval.title.ilike(term), EthicalApproval.reference_number.ilike(term), EthicalApproval.description.ilike(term))
            )
            results['ethical_approvals'] = ea_query.all() # Assuming all logged-in users can see all EAs for now
            current_app.logger.debug(f"SEARCH_RESULTS: Found {len(results['ethical_approvals'])} ethical approvals.")


            # --- Search Protocol Models ---
            results['protocols'] = ProtocolModel.query.filter(ProtocolModel.name.ilike(term)).all()
            current_app.logger.debug(f"SEARCH_RESULTS: Found {len(results['protocols'])} protocol models.")
            
            # --- Search Animal Models ---
            results['animal_models'] = AnimalModel.query.filter(AnimalModel.name.ilike(term)).all()
            current_app.logger.debug(f"SEARCH_RESULTS: Found {len(results['animal_models'])} animal models.")

            # --- Search Partners ---
            partner_query_raw = Partner.query.filter(or_(Partner.company_name.ilike(term), Partner.contact_email.ilike(term)))
            all_found_partners_raw = partner_query_raw.all()
            current_app.logger.debug(f"SEARCH_RAW_RESULTS: Found {len(all_found_partners_raw)} partners before project access check.")

            # Filter partners based on accessible projects
            accessible_partners = []
            if current_user.is_super_admin:
                accessible_partners = all_found_partners_raw
            else:
                for partner_raw in all_found_partners_raw:
                    # Check if this partner is linked to any project the user can access
                    is_linked_to_accessible_project = partner_raw.projects.filter(
                        Project.team_id.in_(user_teams_ids)
                    ).first() is not None
                    if is_linked_to_accessible_project:
                        accessible_partners.append(partner_raw)
            results['partners'] = accessible_partners
            current_app.logger.debug(f"SEARCH_FILTERED_RESULTS: {len(results['partners'])} partners after project access check.")
            
            # --- Search DataTables ---
            dt_query = DataTable.query.join(ExperimentalGroup, DataTable.group_id == ExperimentalGroup.id)\
                                      .join(ProtocolModel, DataTable.protocol_id == ProtocolModel.id)\
                                      .filter(or_(ProtocolModel.name.ilike(term), ExperimentalGroup.name.ilike(term), DataTable.date.ilike(term)))
            all_found_datatables_raw = dt_query.all()
            current_app.logger.debug(f"SEARCH_RAW_RESULTS: Found {len(all_found_datatables_raw)} datatables before permission check.")

            results['datatables'] = [dt for dt in all_found_datatables_raw if check_datatable_permission(dt, 'read')]
            current_app.logger.debug(f"SEARCH_FILTERED_RESULTS: {len(results['datatables'])} datatables after permission check.")

    elif not query_string and request.method == 'GET' and 'q' in request.args:
        flash(_("Please enter a valid search term."), "warning")
        search_performed = True

    return render_template('main/search_results.html', 
                           title=_("Search Results"), 
                           query=query_string, 
                           results=results,
                           search_form=search_form, 
                           search_performed=search_performed)


@main_bp.route('/my_page')
@login_required
def my_page():
    # Fetch items bookmarked by the current user
    my_groups = current_user.my_page_groups.join(ExperimentalGroup.project)\
        .options(db.joinedload(ExperimentalGroup.project).joinedload(Project.team),
                 db.joinedload(ExperimentalGroup.model))\
        .order_by(Project.name, ExperimentalGroup.name).all()
    
    my_datatables = current_user.my_page_datatables.join(DataTable.group).join(ExperimentalGroup.project)\
        .options(db.joinedload(DataTable.group).joinedload(ExperimentalGroup.project).joinedload(Project.team),
                 db.joinedload(DataTable.group).joinedload(ExperimentalGroup.model),
                 db.joinedload(DataTable.protocol))\
        .order_by(DataTable.date.desc(), DataTable.id.desc()).all()

    created_groups = ExperimentalGroup.query.filter_by(owner_id=current_user.id)\
        .join(ExperimentalGroup.project)\
        .options(db.joinedload(ExperimentalGroup.project).joinedload(Project.team),
                 db.joinedload(ExperimentalGroup.model))\
        .order_by(Project.name, ExperimentalGroup.name).all()
    
    try:
        created_datatables = DataTable.query.filter_by(creator_id=current_user.id)\
            .join(DataTable.group).join(ExperimentalGroup.project)\
            .options(db.joinedload(DataTable.group).joinedload(ExperimentalGroup.project).joinedload(Project.team),
                     db.joinedload(DataTable.group).joinedload(ExperimentalGroup.model),
                     db.joinedload(DataTable.protocol))\
            .order_by(DataTable.date.desc(), DataTable.id.desc()).all()
    except Exception as e:
        current_app.logger.error(f"Error fetching created datatables for my_page: {e}")
        created_datatables = []

    # ADDED: Fetch projects from the user's teams that are not archived
    team_ids = [team.id for team in current_user.get_teams()]
    team_projects = Project.query.filter(
        Project.team_id.in_(team_ids),
        Project.is_archived == False
    ).order_by(Project.name).all()

    # Determine if the page is effectively empty
    my_groups_exist = bool(my_groups)
    my_datatables_exist = bool(my_datatables)
    non_bookmarked_created_groups_exist = any(g not in my_groups for g in created_groups)
    non_bookmarked_created_datatables_exist = any(dt not in my_datatables for dt in created_datatables)
    team_projects_exist = bool(team_projects)

    is_my_page_empty = not (my_groups_exist or 
                            my_datatables_exist or 
                            non_bookmarked_created_groups_exist or 
                            non_bookmarked_created_datatables_exist or
                            team_projects_exist) # MODIFIED

    return render_template(
        'main/my_page.html',
        title=_('My Page'),
        my_groups=my_groups,
        my_datatables=my_datatables,
        created_groups=created_groups,
        created_datatables=created_datatables,
        team_projects=team_projects, # ADDED
        is_my_page_empty=is_my_page_empty
    )




@main_bp.route('/my_page/add_group/<string:group_id>', methods=['POST'])
@login_required
def add_group_to_my_page(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if not group:
        flash(_("Group not found."), "danger")
        return redirect(request.referrer or url_for('main.my_page'))
    
    # Optional: Check if user has read permission for the group before bookmarking
    # check_group_permission is imported from ..permissions
    if not check_group_permission(group, 'read'):
        flash(_("You do not have permission to access this group."), "danger")
        return redirect(request.referrer or url_for('main.my_page'))

    if group not in current_user.my_page_groups:
        current_user.my_page_groups.append(group)
        db.session.commit()
        flash(_("Group '%(name)s' added to My Page.", name=group.name), "success")
    else:
        flash(_("Group '%(name)s' is already on My Page.", name=group.name), "info")
    return redirect(request.referrer or url_for('main.my_page'))

@main_bp.route('/my_page/remove_group/<string:group_id>', methods=['POST'])
@login_required
def remove_group_from_my_page(group_id):
    group = db.session.get(ExperimentalGroup, group_id)
    if group and group in current_user.my_page_groups:
        current_user.my_page_groups.remove(group)
        db.session.commit()
        flash(_("Group '%(name)s' removed from My Page.", name=group.name), "success")
    elif not group:
        flash(_("Group not found."), "danger")
    else:
        flash(_("Group '%(name)s' was not on My Page.", name=group.name), "info")
    return redirect(request.referrer or url_for('main.my_page'))

@main_bp.route('/my_page/add_datatable/<int:datatable_id>', methods=['POST'])
@login_required
def add_datatable_to_my_page(datatable_id):
    datatable = db.session.get(DataTable, datatable_id)
    if not datatable:
        flash(_("DataTable not found."), "danger")
        return redirect(request.referrer or url_for('main.my_page'))

    # check_datatable_permission is imported from ..permissions
    if not check_datatable_permission(datatable, 'read'):
        flash(_("You do not have permission to access this DataTable."), "danger")
        return redirect(request.referrer or url_for('main.my_page'))

    if datatable not in current_user.my_page_datatables:
        current_user.my_page_datatables.append(datatable)
        db.session.commit()
        flash(_("DataTable from group '%(group_name)s' (%(date)s) added to My Page.", 
                group_name=datatable.group.name, date=datatable.date), "success")
    else:
        flash(_("This DataTable is already on My Page."), "info")
    return redirect(request.referrer or url_for('main.my_page'))

@main_bp.route('/my_page/remove_datatable/<int:datatable_id>', methods=['POST'])
@login_required
def remove_datatable_from_my_page(datatable_id):
    datatable = db.session.get(DataTable, datatable_id)
    if datatable and datatable in current_user.my_page_datatables:
        current_user.my_page_datatables.remove(datatable)
        db.session.commit()
        flash(_("DataTable from group '%(group_name)s' (%(date)s) removed from My Page.", 
                group_name=datatable.group.name, date=datatable.date), "success")
    elif not datatable:
        flash(_("DataTable not found."), "danger")
    else:
        flash(_("This DataTable was not on My Page."), "info")
    return redirect(request.referrer or url_for('main.my_page'))


@main_bp.route('/confirm/<token>')
@login_required # User must be logged in to confirm their email change
def confirm_email(token):
    """Handles email confirmation link."""
    try:
        new_email = confirm_token(token) # Verify the token
    except Exception as e: # Catch potential errors during token confirmation
        flash(_('The confirmation link is invalid or has expired. Error: {}').format(e), 'danger')
        return redirect(url_for('main.settings')) # Redirect back to settings

    if new_email is False or new_email is None:
        flash(_('The confirmation link is invalid or has expired.'), 'danger')
        return redirect(url_for('main.settings'))

    # Check if the new email is already taken by *another* user
    user_with_new_email = User.query.filter(User.email == new_email, User.id != current_user.id).first()
    if user_with_new_email:
        flash(_('This email address is already associated with another account.'), 'danger')
        return redirect(url_for('main.settings'))

    # Check if the user is trying to confirm their current email (shouldn't happen via link normally)
    if new_email == current_user.email:
        flash(_('This is already your current email address.'), 'info')
        return redirect(url_for('main.settings'))

    # Update the user's email
    current_user.email = new_email
    # Optionally, mark email as confirmed if your User model has such a field
    # current_user.email_confirmed = True
    db.session.commit()
    flash(_('Your email address has been updated successfully. Please log in again.'), 'success')
    logout_user() # Log out user after email change for security
    return redirect(url_for('auth.login'))

# Add other main/core routes here if necessary

@main_bp.route('/set_session_value', methods=['POST'])
def set_session_value():
    key = request.form.get('key')
    value = request.form.get('value')
    if key and value:
        session[key] = value
        return '', 204 # No Content
    return '', 400 # Bad Request


@main_bp.route('/documentation')
def documentation():
    """Renders the application documentation page."""
    return render_template('main/documentation.html', title=_('Documentation'))


@main_bp.route('/docs/data')
def docs_data():
    """Provides a dynamic JSON representation of application features and API for external site building."""
    features = [
        {
            "name": "Project Management",
            "description": "Organize experimental data into projects with team-based access control.",
            "api_endpoints": ["/api/projects/"],
            "permissions": ["Project:view", "Project:create", "Project:edit"]
        },
        {
            "name": "Experimental Groups",
            "description": "Define animal groups within projects, including animal metadata and randomization.",
            "api_endpoints": ["/api/groups/"],
            "permissions": ["Group:view", "Group:create", "Group:edit"]
        },
        {
            "name": "Audit Trail (GLP)",
            "description": "Automatic logging of all data modifications for GLP compliance.",
            "api_endpoints": ["/api/admin/audit_logs"],
            "permissions": ["User:view (Admin)"]
        }
    ]
    return {"features": features, "version": current_app.config.get('VERSION', '0.0.0-dev')}

@main_bp.route('/docs/site/', defaults={'path': 'index.html'})
@main_bp.route('/docs/site/<path:path>')
def serve_docs(path):
    """
    Serves the static MkDocs site.
    Injects CSP nonce into HTML files to allow search scripts to run without 'unsafe-inline'.
    """
    import os
    from flask import send_from_directory, g, Response

    docs_dir = os.path.join(current_app.root_path, '..', 'site')
    
    # Handle directory requests
    if path == "" or path.endswith("/"):
        path += "index.html"

    # Security check: prevent directory traversal
    safe_path = os.path.normpath(os.path.join(docs_dir, path))
    if not safe_path.startswith(os.path.abspath(docs_dir)):
        return "Forbidden", 403

    # If it's an HTML file, inject the nonce
    if path.endswith('.html'):
        try:
            with open(safe_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Inject nonce into all script tags
            # We use a simple string replace which is safe enough for MkDocs output
            nonce = getattr(g, 'csp_nonce', '')
            if nonce:
                content = content.replace('<script', f'<script nonce="{nonce}"')
            
            return Response(content, mimetype='text/html')
        except FileNotFoundError:
            return "Not Found", 404

    # For non-HTML files (JS, CSS, Images), serve directly
    return send_from_directory(docs_dir, path)


@main_bp.route('/.well-known/security.txt')
def security_txt():
    """Serves the security.txt file for vulnerability disclosure."""
    content = """Contact: mailto:security@bio.benetnath.fr
Expires: 2026-12-31T23:59:59Z
Preferred-Languages: en, fr"""
    return Response(content, mimetype='text/plain')


@main_bp.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_json():
    """Handles Chrome DevTools JSON requests by returning 404 without logging an error."""
    return Response(status=404)
