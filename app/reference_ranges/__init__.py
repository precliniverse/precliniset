# app/reference_ranges/__init__.py
from flask import Blueprint

reference_ranges_bp = Blueprint('reference_ranges', __name__, template_folder='../templates/reference_ranges')

from . import routes