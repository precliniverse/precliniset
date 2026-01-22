from flask import request
from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address  # Import this
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import scoped_session

# Initialize extensions without app context initially
# They will be initialized with the app in the factory function (create_app)
db = SQLAlchemy()
mail = Mail()
babel = Babel()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=lambda: get_remote_address() if request else "global_key_for_non_request_context",
    # default_limits will be picked up from app.config during init_app
    # storage_uri will be picked up from app.config during init_app
)

# Configure SQLAlchemy echo
def configure_sqlalchemy_echo(app):
    with app.app_context():
        db.engine.echo = app.config['SQL_DEBUG']


# Instantiate LoginManager
login_manager = LoginManager()

# Use scoped_session for request-local sessions
db.session = scoped_session(db.session)

# Configure LoginManager
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'
login_manager.login_message = "Please log in to access this page."

