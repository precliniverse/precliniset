from flask import Blueprint

resources_bp = Blueprint('resources', __name__, template_folder='templates')

from . import routes
from . import routes_pipelines
