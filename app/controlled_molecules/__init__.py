# app/controlled_molecules/__init__.py
"""Blueprint for controlled molecules management."""
from flask import Blueprint

controlled_molecules_bp = Blueprint('controlled_molecules', __name__)

from . import routes  # noqa: F401, E402
