from flask import Blueprint

storage_bp = Blueprint('storage', __name__, template_folder='../templates/storage')

from . import routes