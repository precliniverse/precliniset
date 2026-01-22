"""
This module initializes the Flask application and its extensions.

It follows the application factory pattern, allowing for easy configuration
switching and testing. It also sets up security headers (CSP), logging,
and registers blueprints.
"""
import os
import secrets


from flask import Flask, g, render_template, request, session
from flask_migrate import Migrate
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from app.ckan.helpers import sanitize_ckan_name
from app.config import TestingConfig

from .celery_utils import celery_app
from .extensions import babel, csrf, db, limiter, login_manager, mail
from .helpers import clean_param_name_for_id, get_ordered_analytes_for_model
from .logging_config import configure_logging
from .performance import caching, compression
from .security import init_security
from .services.audit_service import register_audit_listeners

# Initialize Flask-Session
sess = Session()

def create_app(config_class=None):
    """
    Create and configure an instance of the Flask application.

    Args:
        config_class: The configuration class to use. Can be a class object,
                      a string path to the class, or None (defaults to env var).

    Returns:
        The configured Flask application instance.
    """
    if config_class is None:
        config_class_name = os.getenv('FLASK_CONFIG', 'development')
        if config_class_name == 'testing':
            config_class = TestingConfig
        elif config_class_name == 'development':
            config_class = 'app.config.Config'
        else:
            config_class = 'app.config.Config'

    base_dir = os.path.abspath(os.path.dirname(__file__))
    template_dir = os.path.join(base_dir, '../templates')
    static_dir = os.path.join(base_dir, '../static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    # --- CONFIGURE SERVER-SIDE SESSIONS ---
    import redis
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_PERMANENT'] = False
    # Use the same Redis URL as Celery
    app.config['SESSION_REDIS'] = redis.from_url(os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1'))
    
    # Load Version
    try:
        version_path = os.path.join(base_dir, '../VERSION')
        with open(version_path, 'r') as f:
            app.config['VERSION'] = f.read().strip()
    except FileNotFoundError:
        app.config['VERSION'] = '0.0.0-dev'

    # Initialize the extension
    sess.init_app(app)

    app.jinja_env.add_extension('jinja2.ext.do')

    if isinstance(config_class, str):
        app.config.from_object(config_class)
        # Import the class dynamically to call the check if it's a string
        # But simpler: if we are using the default Config, we can check it.
        if config_class == 'app.config.Config':
            from app.config import Config
            Config.check_configuration()
    else:
        app.config.from_object(config_class)
        if hasattr(config_class, 'check_configuration'):
            config_class.check_configuration()

    # Configure Werkzeug form limits after config is loaded
    # These are needed for large forms (like editing 200 animals at once)
    if hasattr(app.request_class, 'max_form_parts'):
        app.request_class.max_form_parts = app.config.get('MAX_FORM_PARTS', 10000)
    if hasattr(app.request_class, 'max_form_memory_size'):
        app.request_class.max_form_memory_size = app.config.get('MAX_FORM_MEMORY_SIZE', 64 * 1024 * 1024)

    celery_app.conf.update(app.config)

    app.jinja_env.globals['clean_param_name_for_id'] = clean_param_name_for_id
    app.jinja_env.globals['sanitize_ckan_name'] = sanitize_ckan_name
    app.jinja_env.globals['get_ordered_analytes'] = get_ordered_analytes_for_model

    csrf.init_app(app)

    db.init_app(app)
    # db.create_all() is removed to avoid conflicts with Flask-Migrate and potential locks
    # Migration scripts (flask db upgrade) should handle table creation.
    # with app.app_context():
    #     db.create_all()
    mail.init_app(app)
    Migrate(app, db)

    def get_locale():
        """Determine the best match for supported languages."""
        if not request:
            return app.config.get('BABEL_DEFAULT_LOCALE', 'en')

        if 'language' in session:
            g.current_lang = session['language']
            return session['language']
        best_match = request.accept_languages.best_match(app.config['LANGUAGES'])
        g.current_lang = best_match if best_match else app.config['BABEL_DEFAULT_LOCALE']
        return g.current_lang

    babel.init_app(app, locale_selector=get_locale)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Initialize security BEFORE registering request hooks
    init_security(app)

    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        """User loader callback for Flask-Login."""
        return db.session.get(User, int(user_id))

    configure_logging(app)

    # Removed create_super_admin from factory to avoid side-effects
    # This should be handled by CLI commands during deployment.

    if app.config.get('ENABLE_CACHING', False):
        caching.init_app(app)
    if app.config.get('ENABLE_COMPRESSION', True):
        compression.configure_compression(app)

    # Register Audit Listeners (GLP)
    register_audit_listeners(app)

    # Removed ensure_mandatory_analytes_exist from factory
    # This should be handled by CLI commands during deployment.

    @app.route('/favicon.ico')
    def favicon():
        """Serve the favicon."""
        return '', 204
        
    @app.after_request
    def normalize_flashes(response):
        """
        Intercepts the session before it is saved to Redis.
        Converts all 'LazyString' objects in flash messages to standard Python strings.
        This prevents serialization errors with Flask-Session.
        """
        if '_flashes' in session:
            try:
                session['_flashes'] = [
                    (category, str(message)) 
                    for category, message in session['_flashes']
                ]
            except Exception as e:
                app.logger.error(f"Error normalizing flash messages: {e}")
        return response

    from app.admin.routes import admin_bp
    from app.api import api_bp as api_blueprint
    from app.auth.routes import auth_bp
    from app.calendar import calendar_bp
    from app.ckan.routes import ckan_bp
    from app.controlled_molecules import controlled_molecules_bp
    from app.core_models.routes import core_models_bp
    from app.datatables import datatables_bp
    from app.ethical_approvals import ethical_approvals_bp
    from app.groups.routes import groups_bp
    from app.main.routes import main_bp
    from app.projects.routes import projects_bp
    from app.reference_ranges import reference_ranges_bp
    from app.resources import resources_bp
    from app.sampling import sampling_bp
    from app.storage import storage_bp
    from app.workplans import workplans_bp

    # SECURITY NOTE: The API blueprint is exempt from session-based CSRF protection
    # because it uses token-based authentication (@token_required decorator).
    # It is CRITICAL that all state-changing API endpoints (POST, PUT, DELETE)
    # are protected by the @token_required decorator to prevent CSRF vulnerabilities.
    csrf.exempt(api_blueprint)

    @app.errorhandler(403)
    def forbidden_page(error):
        """Render a custom 403 Forbidden page."""
        return render_template('errors/403.html'), 403

    limiter.limit(app.config.get("RATELIMIT_API_DEFAULT", "1000/hour;100/minute"))(api_blueprint)

    app.register_blueprint(main_bp)
    app.register_blueprint(projects_bp, url_prefix='/projects')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(core_models_bp, url_prefix='/core_models')
    app.register_blueprint(datatables_bp, url_prefix='/datatables')
    app.register_blueprint(groups_bp, url_prefix='/groups')
    app.register_blueprint(ethical_approvals_bp, url_prefix='/ethical_approvals')
    app.register_blueprint(storage_bp, url_prefix='/storage')
    app.register_blueprint(sampling_bp, url_prefix='/sampling')
    app.register_blueprint(api_blueprint)
    app.register_blueprint(reference_ranges_bp, url_prefix='/reference_ranges')
    app.register_blueprint(resources_bp, url_prefix='/resources')
    app.register_blueprint(ckan_bp, url_prefix='/ckan')
    app.register_blueprint(workplans_bp, url_prefix='/workplans')
    app.register_blueprint(calendar_bp, url_prefix='/calendar')
    app.register_blueprint(controlled_molecules_bp, url_prefix='/controlled_molecules')

    from app.cli.setup_commands import setup_bp
    app.register_blueprint(setup_bp)

    @app.before_request
    def create_csp_nonce():
        """Create a nonce for Content Security Policy."""
        g.csp_nonce = secrets.token_hex(16)

    @app.after_request
    def apply_csp_header(response):
        """Apply Content Security Policy headers to the response."""
        if request.blueprint == 'api':
            return response

        cdn_domains_scripts = [
            "https://cdn.plot.ly", "https://code.jquery.com", "https://cdn.jsdelivr.net",
            "https://cdnjs.cloudflare.com", "https://cdn.datatables.net", "https://fonts.gstatic.com"
        ]
        cdn_domains_styles = [
            "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://cdn.datatables.net", "https://fonts.gstatic.com", "https://fonts.googleapis.com"
        ]

        csp = {
            'default-src': ["'self'"],
            # SECURITY FIX: Re-added 'unsafe-inline' to style-src. This is a necessary
            # trade-off for compatibility with libraries like Plotly and FullCalendar
            # that dynamically inject inline styles. The risk is mitigated by the
            # very strict script-src policy.
            'style-src': ["'self'", "'unsafe-inline'", *cdn_domains_styles],
            'connect-src': ["'self'", "https://cdn.jsdelivr.net", "https://unpkg.com", "https://cdnjs.cloudflare.com", "https://cdn.plot.ly"],
            'img-src': ["'self'", "data:", "blob:"],
            'font-src': ["'self'", "data:", "https://cdnjs.cloudflare.com", "https://cdn.jsdelivr.net", "https://cdn.datatables.net", "https://fonts.gstatic.com"],
            'object-src': ["'none'"],
            'media-src': ["'self'"],
            'frame-src': ["'self'", "blob:"],
            'worker-src': ["'self'", "blob:"],
            'form-action': ["'self'"],
            'base-uri': ["'self'"],
            'script-src': [
                "'self'",
                "'unsafe-eval'",
                "blob:",
                f"'nonce-{getattr(g, 'csp_nonce', '')}'",
                "https://cdn.plot.ly",
                *cdn_domains_scripts,
                "'sha256-XYPfW30ecQIlTrs1XjDnukHi7tHB7jDOoSnoRYzIZro='",
                "'sha256-tNzOJ4epn8JZXET29Rotbx7N5v6tT2OrAC1BSHJsEzE='"
            ]
        }

        policy_parts = []
        for directive, sources in csp.items():
            policy_parts.append(f"{directive} {' '.join(sources)}")

        csp_header = "; ".join(policy_parts)

        response.headers['Content-Security-Policy'] = csp_header
        
        # Additional security headers (previously provided by Talisman)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Only set HSTS if HTTPS is forced (not in development)
        if app.config.get('FORCE_HTTPS', False) and not app.testing:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        response.headers['Permissions-Policy'] = "camera=(), microphone=(), geolocation=(), usb=(), interest-cohort=()"
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        return response

    from .permissions import (check_datatable_permission,
                              check_group_permission, check_project_permission)

    @app.context_processor
    def inject_permissions():
        """Inject permission check functions into templates."""
        from app.models import user_has_permission
        return dict(
            check_group_permission=check_group_permission,
            check_project_permission=check_project_permission,
            check_datatable_permission=check_datatable_permission,
            user_has_permission=user_has_permission
        )

    @app.context_processor
    def inject_user():
        """Inject current user, CSP nonce, and App Version into templates."""
        from flask_login import current_user
        return dict(
            current_user=current_user, 
            csp_nonce=getattr(g, 'csp_nonce', ''),
            app_version=app.config.get('VERSION', '0.0.0-dev')
        )

    return app
