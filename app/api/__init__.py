# app/api/__init__.py
from flask import Blueprint, current_app
from flask_restx import Api
from werkzeug.exceptions import Forbidden, HTTPException, NotFound

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

authorizations = {
    'BearerAuth': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'Authorization',
        'description': "Type in the *'Value'* input box below: **'Bearer <JWT>'**, where JWT is the token"
    }
}

api = Api(
    api_bp,
    version='1.0',
    title='Precliniverse API',
    description='A RESTful API for Precliniverse application',
    doc='/doc/',
    authorizations=authorizations,
    security='BearerAuth'
)

# Import and add namespaces
from .analytes_api import ns as analytes_ns

api.add_namespace(analytes_ns)

# The 'groups' namespace handles individual group management (GET/PUT/DELETE /groups/<id>)
# and datatable management within a group (e.g., /groups/<id>/datatables).
# The 'projects' namespace handles group creation and listing within a project (/projects/<id>/groups).
# While not perfectly RESTful, the code for all ExperimentalGroup resources is now consolidated in groups_api.py.
from .datatables_api import ns as datatables_ns
from .groups_api import group_item_model
from .groups_api import ns as groups_ns_from_projects

api.add_namespace(datatables_ns)
api.add_namespace(groups_ns_from_projects)

from .core_models_api import ns_am as animal_models_ns
from .core_models_api import ns_protocols as protocols_ns

api.add_namespace(protocols_ns)
api.add_namespace(animal_models_ns)

from .ethical_approvals_api import ns as ethical_approvals_ns

api.add_namespace(ethical_approvals_ns)

from .sampling_api import ns as storage_ns
from .sampling_api import ns_samples as sampling_ns

api.add_namespace(storage_ns)
api.add_namespace(sampling_ns)

from .admin_api import ns as admin_ns

api.add_namespace(admin_ns)

# This namespace is for project-specific group operations (listing/creating groups under a project)
from .groups_api import ns as projects_ns

api.add_namespace(projects_ns)


@api.errorhandler(NotFound)
def handle_not_found_error(error):
    """Catches 404 Not Found errors raised in the API."""
    current_app.logger.warning(f"API Not Found error: {error.description}")
    return {'message': error.description or 'Resource not found.'}, 404

@api.errorhandler(Forbidden)
def handle_forbidden_error(error):
    """Catches 403 Forbidden errors raised in the API."""
    current_app.logger.warning(f"API Forbidden error: {error.description}")
    return {'message': error.description or 'Permission denied.'}, 403


@api.errorhandler(Exception) 
def handle_unexpected_api_error(error):
    if isinstance(error, HTTPException):
        current_app.logger.error(f"API's generic error handler received an HTTPException: {error.code} {error.name}. This should be rare.", exc_info=True)
        return {'message': error.description or error.name, 'error_code': error.code}, error.code
    
    current_app.logger.error(f"Unhandled API Exception (non-HTTP) in api_bp: {error}", exc_info=True)
    return {'message': 'An unexpected server error occurred within the API.'}, 500


@api_bp.route('/redoc')
def redoc_ui():
    """Renders the Redoc UI for the API."""
    from flask import render_template
    return render_template('api/redoc.html')

from .import_wizard_api import ns as import_wizard_ns

api.add_namespace(import_wizard_ns)

# Import controlled molecules API routes to register them with the blueprint
from . import controlled_molecules