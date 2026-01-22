"""
This script serves as the main entry point for the Precliniset application.

It loads environment variables, creates the Flask app instance using the application
factory pattern, and starts a Waitress production server. It also provides startup
logging to confirm the application's configuration, including debug mode status,
host, and port.
"""
import os
import logging
from dotenv import load_dotenv
from waitress import serve
from app import create_app

# Load environment variables from .env file
load_dotenv(verbose=True)

# Create the Flask app instance using the factory
app = create_app()

if __name__ == '__main__':
    # BEST PRACTICE: Add startup logging to confirm configuration
    log = logging.getLogger('waitress')
    log.setLevel(logging.INFO)

    config_name = os.getenv('FLASK_CONFIG', 'development')
    debug_mode = app.debug

    log.info("--- Precliniset Application Starting ---")
    log.info("Configuration: '%s'", config_name)
    log.info("Debug Mode: %s", debug_mode)
    if debug_mode and config_name != 'development':
        log.warning("WARNING: Debug mode is enabled but configuration is not 'development'.")

    # Get host and port from environment variables or use defaults
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))

    log.info("Server starting on http://%s:%s", host, port)

    serve(app, host=host, port=port)
