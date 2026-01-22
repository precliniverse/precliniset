from flask import Blueprint

calendar_bp = Blueprint('calendar', __name__, template_folder='../templates/calendar')

from . import routes