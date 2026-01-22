# app/ethical_approvals/__init__.py
from flask import Blueprint

ethical_approvals_bp = Blueprint('ethical_approvals', __name__, template_folder='../templates/ethical_approvals')

from app.ethical_approvals import routes