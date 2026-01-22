import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, urlencode, parse_qs

from flask import g, request, session
from werkzeug.exceptions import HTTPException


# --- Custom Filters ---
class SQLAlchemyFilter(logging.Filter):
    def filter(self, record):
        # Filter out routine SQLAlchemy INFO messages unless SQL_DEBUG is explicitly on
        if record.name == 'sqlalchemy.engine' and record.levelno == logging.INFO:
            return current_app.config.get('SQL_DEBUG', False) # Only show if SQL_DEBUG is True
        return True

class RequestContextFilter(logging.Filter):
    """Adds request context to log records if available, scrubbing sensitive data."""

    def _scrub_url(self, url):
        """Removes sensitive query parameters from URL."""
        if not url: return 'N/A'
        try:
            parsed = urlparse(url)
            if not parsed.query:
                return url

            qs = parse_qs(parsed.query)
            sensitive_keys = ['token', 'api_key', 'password', 'secret', 'key']

            for key in qs:
                if any(s in key.lower() for s in sensitive_keys):
                    qs[key] = ['***REDACTED***']

            new_query = urlencode(qs, doseq=True)
            return parsed._replace(query=new_query).geturl()
        except Exception:
            return url # Fallback

    def filter(self, record):
        try:
            # Check if we are in a request context
            if request:
                record.url = self._scrub_url(request.url)
                record.remote_addr = request.remote_addr
                # Check if current_user is available and authenticated
                if hasattr(request, 'current_user') and request.current_user and request.current_user.is_authenticated:
                    record.user_id = str(request.current_user.id)
                else:
                    record.user_id = 'anonymous'
            else: # Not in a request context
                record.url = 'N/A (no request context)'
                record.remote_addr = 'N/A'
                record.user_id = 'N/A'
        except RuntimeError: # Outside of request context
            record.url = 'N/A (RuntimeError accessing request)'
            record.remote_addr = 'N/A'
            record.user_id = 'N/A'
        return True

# --- Custom Formatter ---
class RichFormatter(logging.Formatter):
    """
    A flexible formatter that includes more context and handles missing 'extra' fields.
    """
    def format(self, record):
        # Ensure standard 'extra' fields are present from RequestContextFilter
        record.url = getattr(record, 'url', 'N/A')
        record.remote_addr = getattr(record, 'remote_addr', 'N/A')
        record.user_id = getattr(record, 'user_id', 'N/A')
        
        # For error records, exc_info might be True or a tuple
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info if record.exc_info is not True else sys.exc_info())
        else:
            record.exc_text = ""

        # Handle custom 'stack' if provided in 'extra', otherwise use formatted exception
        # For general logs, stack_info will be N/A unless an error occurred or 'stack' was passed in extra
        record.stack_info = getattr(record, 'stack', record.exc_text if record.exc_text else 'N/A')
        
        return super().format(record)

def configure_logging(app):
    print("--- configure_logging called ---", file=sys.stderr)
    
    # --- Determine Log Level ---
    # Use app.debug directly, which is correctly set by Flask based on FLASK_DEBUG env var
    if app.debug: 
        effective_log_level_str = 'DEBUG'
        print("app.debug is True, setting effective_log_level_str to DEBUG.", file=sys.stderr)
    else:
        effective_log_level_str = app.config.get('APP_LOG_LEVEL', 'INFO').upper()
        print(f"app.debug is False, using APP_LOG_LEVEL: {effective_log_level_str}", file=sys.stderr)

    log_level = getattr(logging, effective_log_level_str, logging.INFO) 
    # If app.debug is True, ensure log_level is DEBUG regardless of APP_LOG_LEVEL for development
    if app.debug and log_level != logging.DEBUG:
        print(f"Warning: app.debug is True, but APP_LOG_LEVEL ('{app.config.get('APP_LOG_LEVEL')}') resulted in {logging.getLevelName(log_level)}. Forcing DEBUG.", file=sys.stderr)
        log_level = logging.DEBUG

    print(f"Effective Python logging level set to: {logging.getLevelName(log_level)} ({log_level})", file=sys.stderr)

    # --- Base Formatter ---
    base_format = (
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d (%(module)s.%(funcName)s)\n"
        "  Message: %(message)s\n"
        "  Request: %(url)s (From: %(remote_addr)s, User: %(user_id)s)"
    )
    # For errors, the RichFormatter will append exc_text (traceback)
    formatter = RichFormatter(base_format, datefmt='%Y-%m-%d %H:%M:%S')

    # --- Clear Existing Handlers from app.logger and root ---
    for h in list(app.logger.handlers): app.logger.removeHandler(h)
    # Optionally clear root handlers if they cause issues, but be cautious
    # for h in list(logging.getLogger().handlers): logging.getLogger().removeHandler(h)
    print("Cleared existing handlers from app.logger.", file=sys.stderr)

    # --- Console Handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level) 
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestContextFilter())
    console_handler.addFilter(SQLAlchemyFilter()) 
    app.logger.addHandler(console_handler)

    # --- File Handler ---
    if not app.config.get('TESTING', False): # Don't create log files during testing
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            try:
                os.mkdir(log_dir)
                print(f"Created logs directory: {log_dir}", file=sys.stderr)
            except OSError as e:
                # Use basic print for this critical bootstrap error, as logger might not be fully set up
                print(f"CRITICAL: Could not create logs directory '{log_dir}': {e}", file=sys.stderr)
        
        if os.path.exists(log_dir): # Only add file handler if directory exists/was created
            file_handler = RotatingFileHandler(
                os.path.join(log_dir, 'app.log'), 
                maxBytes=2 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(log_level) 
            file_handler.setFormatter(formatter) 
            file_handler.addFilter(RequestContextFilter())
            file_handler.addFilter(SQLAlchemyFilter())
            app.logger.addHandler(file_handler)
            print(f"File handler added to app.logger. file_handler level: {logging.getLevelName(file_handler.level)}", file=sys.stderr)
        else:
            print("WARNING: File handler not added because logs directory could not be ensured.", file=sys.stderr)


    # --- Set Logger Levels ---
    app.logger.setLevel(log_level) 
    app.logger.propagate = False # Crucial: app.logger handles its messages, don't pass to root.

    # --- SQLAlchemy Logging ---
    sql_echo_enabled = app.config.get('SQLALCHEMY_ECHO', False) # From Config class
    sql_debug_enabled = app.config.get('SQL_DEBUG', False)     # From Config class
    sql_logger = logging.getLogger('sqlalchemy.engine')
    for h in list(sql_logger.handlers): sql_logger.removeHandler(h) # Clear its handlers

    if sql_echo_enabled or sql_debug_enabled:
        sql_logger.setLevel(logging.INFO) # SQL statements are INFO
        sql_logger.addHandler(console_handler) # Send to our configured console handler
        if not app.config.get('TESTING') and 'file_handler' in locals() and file_handler in app.logger.handlers:
            sql_logger.addHandler(file_handler) # And to file if it was set up
        sql_logger.propagate = False 
    else:
        sql_logger.setLevel(logging.WARNING) 
        sql_logger.propagate = False


    # --- Request/Response Logging Hooks ---
    @app.before_request
    def log_request_info_hook():
        if request and hasattr(request, 'path') and '/static/' not in request.path and request.endpoint != 'static':
            app.logger.debug(f"HOOK: Incoming request: {request.method} {request.path}")
    
    @app.after_request
    def log_response_info_hook(response):
        if request and hasattr(request, 'path') and '/static/' not in request.path and request.endpoint != 'static':
            app.logger.debug(f"HOOK: Outgoing response: {response.status_code} for {request.method} {request.path}")
        return response
    
    # --- Global Error Handler ---
    if not app.testing:
        @app.errorhandler(HTTPException)
        def handle_http_exception(e):
            # Log the exception
            app.logger.error(
                f"HTTP exception caught by global handler: {e.name} ({e.code}) for {request.url}",
                exc_info=False # Set to True if you want full trace for all HTTP errors
            )
            
            # For API requests, we want Flask-RESTx to format the error.
            # Re-raising the exception allows Flask-RESTx's error handlers to catch it.
            if request.blueprint == 'api':
                # If this is an API request, re-raise the exception.
                # Flask-RESTx's @api.errorhandler should then catch it.
                # If you removed @api.errorhandler(HTTPException) from api/__init__.py,
                # then RESTx's *default* HTTPException handling should take over.
                raise e # <--- CRITICAL: Re-raise for API blueprint

            # For non-API parts of the app, you can return a custom HTML page or the default Werkzeug page.
            # from flask import render_template
            # return render_template(f"errors/{e.code}.html", error=e), e.code
            return e # Let Werkzeug/Flask handle default HTML error pages for non-API

        @app.errorhandler(Exception)
        def handle_generic_exception(e):
            # Log the exception
            app.logger.error(
                f"Unhandled application exception caught by global handler: {e} for {request.url}",
                exc_info=True
            )

            # For API requests, re-raise to let the @api.errorhandler(Exception) in api/__init__.py handle it.
            if request.blueprint == 'api':
                raise e # <--- CRITICAL: Re-raise for API blueprint

            # For non-API parts of the app
            if not app.debug:
                # from flask import render_template
                # return render_template("errors/500.html", error=e), 500
                return "Internal Server Error", 500 # Or a rendered template
            raise e
