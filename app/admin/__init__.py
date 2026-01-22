import logging

from flask import Blueprint, current_app

# Define the blueprint for admin/team management routes
# Templates will be looked for in app/templates/admin/
admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')

# Create a logger for the blueprint
admin_bp.logger = logging.getLogger(__name__)
admin_bp.logger.propagate = False

# Set logger level based on app.debug
@admin_bp.before_app_request
def configure_admin_blueprint_logger():
    admin_bp.logger.setLevel(logging.INFO)

# Import routes after blueprint definition
from . import routes
