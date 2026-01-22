import logging

from flask import Blueprint, current_app

# Define the blueprint for experimental group management routes
# Templates will be looked for in app/templates/groups/
groups_bp = Blueprint('groups', __name__, template_folder='../templates/groups')

# Create a logger for the blueprint
groups_bp.logger = logging.getLogger(__name__)
groups_bp.logger.propagate = False

# Set logger level based on app.debug
@groups_bp.before_app_request
def configure_groups_blueprint_logger():
    groups_bp.logger.setLevel(logging.INFO)

# Import routes after blueprint definition
from . import routes
