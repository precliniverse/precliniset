# app/forms/__init__.py
"""
Forms for the Precliniset application.
Re-exports all forms from domain-specific modules.
"""

from .admin import *
from .auth import *
from .ckan import *
# Import all forms from refactored modules
from .common import *
from .datatables import *
from .ethical import *
from .groups import *
from .misc import *
from .projects import *
from .teams import *
from .workplans import *
