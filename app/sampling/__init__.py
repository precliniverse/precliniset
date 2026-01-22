from flask import Blueprint

sampling_bp = Blueprint('sampling', __name__, template_folder='../templates/sampling')

from . import routes  # noqa