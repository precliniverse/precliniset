from flask import Blueprint

workplans_bp = Blueprint('workplans', __name__, template_folder='../templates/workplans')

from . import routes