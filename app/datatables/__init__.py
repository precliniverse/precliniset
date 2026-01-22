import logging

from flask import Blueprint, current_app

# Define the blueprint for data table management routes
# Templates will be looked for in app/templates/datatables/
datatables_bp = Blueprint('datatables', __name__, template_folder='../templates/datatables')

# Create a logger for the blueprint
datatables_bp.logger = logging.getLogger(__name__)
datatables_bp.logger.propagate = False # Prevent duplicate logs if root logger is also configured

# Set logger level based on app.debug or a specific config
@datatables_bp.before_app_request
def configure_datatables_blueprint_logger():
    # Ensure logger is configured, e.g., level based on app config
    # This might be redundant if global logging config handles blueprint loggers,
    # but good for explicitness if needed.
    if current_app.debug:
        datatables_bp.logger.setLevel(logging.DEBUG)
    else:
        # Use the app's configured log level for consistency
        log_level_str = current_app.config.get('APP_LOG_LEVEL', 'INFO').upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        datatables_bp.logger.setLevel(log_level)

    # If you have specific handlers for this blueprint, add them here.
    # Otherwise, it will use handlers configured on parent/root loggers if propagate=True.
    # Since propagate is False, ensure a handler is added if you want output from this logger.
    # For example, if you want it to use the app's general file handler:
    # if not datatables_bp.logger.handlers:
    #     for handler in current_app.logger.handlers:
    #         datatables_bp.logger.addHandler(handler)


# Import routes from the new files to register them with the blueprint
from . import routes_analysis, routes_crud
