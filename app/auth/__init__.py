import logging

from flask import Blueprint, current_app

# Define the blueprint for authentication routes
# We'll keep templates in the main app/templates/auth directory
auth_bp = Blueprint('auth', __name__, template_folder='../templates/auth')

# Create a logger for the blueprint
auth_bp.logger = logging.getLogger(__name__)
auth_bp.logger.propagate = False

# Set logger level based on app.debug
@auth_bp.before_app_request
def configure_auth_blueprint_logger():
    auth_bp.logger.setLevel(logging.INFO)

# Import routes after blueprint definition to avoid circular imports
from . import routes
