import sys
import os
import logging
from dotenv import load_dotenv
from app import create_app

# Load environment variables from .env file
load_dotenv(verbose=True)

# Create the Flask app instance using the factory
app = create_app()

if __name__ == '__main__':
    # BEST PRACTICE: Add startup logging to confirm configuration
    if sys.platform == 'win32':
        from waitress import serve
        log = logging.getLogger('waitress')
    else:
        from gunicorn.app.base import BaseApplication
        log = logging.getLogger('gunicorn')

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

    if sys.platform == 'win32':
        serve(app, host=host, port=port)
    else:
        class StandaloneApplication(BaseApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()

            def load_config(self):
                config = {key: value for key, value in self.options.items()
                          if key in self.cfg.settings and value is not None}
                for key, value in config.items():
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        gunicorn_options = {
            'bind': f"{host}:{port}",
            'workers': int(os.environ.get('GUNICORN_WORKERS', 4)),
            'worker_class': os.environ.get('GUNICORN_WORKER_CLASS', 'sync'),
            'loglevel': os.environ.get('GUNICORN_LOG_LEVEL', 'info'),
        }
        StandaloneApplication(app, gunicorn_options).run()
