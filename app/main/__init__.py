from flask import Blueprint

# Define the blueprint: 'main' is the name of the blueprint,
# __name__ helps determine the root path for resources.
# template_folder='templates' specifies where to look for templates relative to this blueprint's directory.
# However, Flask searches the app's main template folder first, then blueprint folders.
# It's often cleaner to keep all templates in the main `app/templates` directory, organized by blueprint name.
main_bp = Blueprint('main', __name__) # Removed template_folder argument

# Import routes after blueprint definition to avoid circular imports
from . import routes
