import logging

from flask import Blueprint, current_app

# Define the blueprint for core model (Animal/Protocol) management routes
# Templates will be looked for in app/templates/core_models/
core_models_bp = Blueprint('core_models', __name__, template_folder='../templates/core_models')

# Create a logger for the blueprint
core_models_bp.logger = logging.getLogger(__name__)
core_models_bp.logger.propagate = False

# Set logger level based on app.debug
@core_models_bp.before_app_request
def configure_core_models_blueprint_logger():
    core_models_bp.logger.setLevel(logging.INFO)

# Import routes after blueprint definition
from . import routes
