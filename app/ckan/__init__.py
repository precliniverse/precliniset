from flask import Blueprint

ckan_bp = Blueprint('ckan', __name__, template_folder='../templates/ckan')

from . import routes