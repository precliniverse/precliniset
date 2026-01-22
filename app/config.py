# app/config.py
import os

import pytz
from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

# Load environment variables from .env file first
load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SECURITY_PASSWORD_SALT = os.environ.get('SECURITY_PASSWORD_SALT')

    @staticmethod
    def init_app(app):
        """Initialize the application configuration."""
        pass

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_COMMIT_ON_TEARDOWN = False  # Explicit session management (recommended)
    APP_LOG_LEVEL = os.environ.get('APP_LOG_LEVEL', 'INFO').upper()
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true' # Log SQL queries
    SQL_DEBUG = os.environ.get('SQL_DEBUG', 'False').lower() == 'true' # Log SQL queries
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't', 'yes', 'on'] # More robust boolean conversion
    ENABLE_CACHING = os.environ.get('ENABLE_CACHING', 'False').lower() == 'true'
    ENABLE_COMPRESSION = os.environ.get('ENABLE_COMPRESSION', 'True').lower() == 'true'
    # FORCE_HTTPS defaults to True in production (not DEBUG), False in development
    force_https_env = os.environ.get('FORCE_HTTPS')
    if force_https_env is not None:
        FORCE_HTTPS = force_https_env.lower() == 'true'
    else:
        FORCE_HTTPS = not DEBUG

    # Timezone Configuration
    TIMEZONE = os.environ.get('TIMEZONE', 'UTC')
    UTC_TZ = pytz.timezone(TIMEZONE)

    # Mail Configuration
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    # --- Project Paths ---
    basedir = os.path.abspath(os.path.dirname(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(basedir, os.pardir))
    
    # --- Database Configuration ---
    DB_TYPE = os.environ.get('DB_TYPE', 'sqlite')

    if DB_TYPE == 'mysql':
        # MariaDB/MySQL configuration
        DB_USER = os.environ.get('DB_USER')
        DB_PASSWORD = os.environ.get('DB_PASSWORD')
        DB_HOST = os.environ.get('DB_HOST')
        DB_PORT = os.environ.get('DB_PORT', '3306')
        DB_NAME = os.environ.get('DB_NAME')

        if not all([DB_USER, DB_PASSWORD, DB_HOST, DB_NAME]):
            raise ValueError("For DB_TYPE=mysql, you must set DB_USER, DB_PASSWORD, DB_HOST, and DB_NAME environment variables.")

        # The 'mysql+pymysql' driver is specified here.
        SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,  # Check connections before using them
            'pool_size': 10,
            'max_overflow': 20,
            'pool_recycle': 3600,  # Recycle connections after 1 hour
            'pool_timeout': 30,
            'isolation_level': 'READ COMMITTED',  # Ensure proper transaction isolation
            'connect_args': {'ssl': False}
        }
    else:
        # Default to SQLite
        # Use INSTANCE_PATH if set (e.g. in Docker), otherwise default to 'instance' folder in project root
        instance_dir = os.environ.get('INSTANCE_PATH', os.path.join(PROJECT_ROOT, 'instance'))
        db_path = os.path.join(instance_dir, 'experiment_app.db')
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')

        SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {
                'timeout': 30,  # Increase timeout for concurrent access
                'check_same_thread': False  # CRITICAL: Allow SQLite to be used across threads/processes
            },
            'pool_pre_ping': True,
            'poolclass': None,  # Disable connection pooling for SQLite to avoid stale connections
            'execution_options': {'sqlite_journal_mode': 'WAL'}  # Write-Ahead Logging for better concurrency
        }

    # Rate Limiting
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_HEADERS_ENABLED = os.environ.get('RATELIMIT_HEADERS_ENABLED', 'True').lower() == 'true'
    # Default limits (can be overridden per blueprint/route)
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_API_DEFAULT = "1000 per hour;100 per minute" # Example for API

    # Super Admin Configuration (used during app initialization)
    SUPERADMIN_EMAIL = os.environ.get('SUPERADMIN_EMAIL')
    SUPERADMIN_PASSWORD = os.environ.get('SUPERADMIN_PASSWORD')

    # Babel Configuration
    LANGUAGES = ['en', 'fr']
    BABEL_DEFAULT_LOCALE = 'en'
    # Use absolute path for translations and uploads
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(PROJECT_ROOT, 'translations')
    UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, 'uploads')
    
    # Max Content Length (default 64MB) to prevent 413 errors on large forms/uploads
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 64 * 1024 * 1024))
    
    # Werkzeug Form Limits (default to allow large forms with many fields)
    MAX_FORM_PARTS = int(os.environ.get('MAX_FORM_PARTS', 10000))
    MAX_FORM_MEMORY_SIZE = int(os.environ.get('MAX_FORM_MEMORY_SIZE', 64 * 1024 * 1024))
    
    # Audit Log Configuration
    ENABLE_AUDIT_LOG = os.environ.get('ENABLE_AUDIT_LOG', 'True').lower() == 'true'
    # Whether to log actions by super admins (can be disabled for performance during massive edits)
    AUDIT_LOG_SUPERADMIN = os.environ.get('AUDIT_LOG_SUPERADMIN', 'True').lower() == 'true'

    # Training Manager Integration
    TM_API_URL = os.environ.get('TM_API_URL')
    TM_API_KEY = os.environ.get('TM_API_KEY')
    TM_VERIFY_SSL = os.environ.get('TM_VERIFY_SSL', 'True').lower() == 'true'
    TM_ENABLED = os.environ.get('TM_ENABLED', 'False').lower() == 'true'
    TM_PUBLIC_URL = os.environ.get('TM_PUBLIC_URL')

    # SSO Secret Key for seamless login
    SSO_SECRET_KEY = os.environ.get('SSO_SECRET_KEY')

    # PC API URL for reverse SSO (when TM redirects to PC)
    PC_API_URL = os.environ.get('PC_API_URL')


    # Celery Configuration (using modern lowercase names for Celery 6+)
    broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

    @classmethod
    def check_configuration(cls):
        """
        Validates that critical configuration variables are set.
        Raises ValueError if any are missing in a production environment.
        """
        # We assume 'production' if FLASK_DEBUG is not enabled.
        # However, checking os.environ directly is safer for the 'source of truth'.
        debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't', 'yes', 'on']

        if not debug_mode:
            missing = []
            if not cls.SECRET_KEY:
                missing.append('SECRET_KEY')
            if not cls.SECURITY_PASSWORD_SALT:
                missing.append('SECURITY_PASSWORD_SALT')

            if missing:
                raise ValueError(f"CRITICAL: The following environment variables are missing in production configuration: {', '.join(missing)}")


class TestingConfig(Config):
    """Configuration for testing environment."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'  # Use in-memory SQLite database
    WTF_CSRF_ENABLED = False  # Disable CSRF forms validation in tests
    SESSION_TYPE = None # Disable server-side sessions for tests
    LOGIN_DISABLED = False # Keep login enabled to test auth, but can be disabled for specific tests
    SERVER_NAME = 'localhost.localdomain' # Required for url_for to work in tests without a request context
    # Disable caching and compression for tests
    ENABLE_CACHING = False
    ENABLE_COMPRESSION = False
    # Disable rate limiting for tests
    RATELIMIT_ENABLED = False 
    
    # Use a different secret key for testing
    SECRET_KEY = 'test-secret-key'

    broker_url = 'memory://'
    result_backend = 'memory://'
    task_always_eager = True # Run tasks synchronously for easier testing
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'check_same_thread': False
        },
        'poolclass': StaticPool, 
        'pool_pre_ping': False
    }
