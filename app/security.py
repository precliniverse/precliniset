# app/security.py
from datetime import timedelta

# Talisman removed - we handle CSP manually in app/__init__.py to avoid conflicts
# from flask_talisman import Talisman

from .extensions import limiter  # Import the limiter instance from extensions


def init_security(app):
    """
    Initialize security middleware for the Flask application.
    """
    
    # --- Talisman REMOVED ---
    # We handle CSP manually in app/__init__.py (apply_csp_header)
    # to avoid conflicts with our custom nonce generation.
    # All other security headers are set manually as well.
    
    # --- Rate Limiting and Session Config  ---
    app.config.setdefault('RATELIMIT_STORAGE_URI', 'memory://')
    app.config.setdefault('RATELIMIT_HEADERS_ENABLED', True)
    limiter.init_app(app)

    is_local_http_dev = (app.config.get('ENV') == 'development' and 
                         not app.config.get('FORCE_HTTPS', False))

    app.config.update(
        SESSION_COOKIE_SECURE=not is_local_http_dev and not app.testing,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        REMEMBER_COOKIE_SECURE=not is_local_http_dev and not app.testing,
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax'
    )