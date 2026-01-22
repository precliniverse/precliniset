""" 
This script initializes the Celery worker for the Precliniset application.

It sets up the Flask application context to ensure that Celery tasks have access
to the application's configuration, extensions, and other context-bound objects.
A custom `ContextTask` class is defined to wrap each task execution within the
Flask app context, making database connections and other app-related 
functionalities available within the tasks.
"""
import os
from app import create_app
from app.celery_utils import celery_app
from celery.signals import worker_process_init

# Set the FLASK_CONFIG environment variable before creating the app.
# This ensures the factory function picks up the correct configuration.
os.environ.setdefault('FLASK_CONFIG', 'development')

# Create a Flask app instance for the Celery worker
# --- FIX: Call create_app() with no arguments to let the factory handle the config ---
app = create_app()
app.app_context().push()

# Update the Celery app's configuration from the Flask app's config
# This is now correctly handled inside the app factory, but an explicit update is safe.
celery_app.conf.update(app.config)

# CRITICAL: Reset database connections after forking
# This is essential for SQLite to work properly with Celery's prefork pool
@worker_process_init.connect
def init_worker_process(**kwargs):
    """Reset database connections in child processes after fork."""
    from app.extensions import db
    # Close any existing connections from the parent process
    db.engine.dispose()
    # Force SQLAlchemy to create fresh connections in this process
    with app.app_context():
        db.session.remove()
        # Test the connection
        try:
            db.session.execute(db.text('SELECT 1'))
            db.session.commit()
            print(f"[Celery Worker PID {os.getpid()}] Database connection initialized successfully")
        except Exception as e:
            print(f"[Celery Worker PID {os.getpid()}] Database connection failed: {e}")

# Create a custom Task class that ensures tasks run within the Flask app context
class ContextTask(celery_app.Task):
    """A custom Celery Task that runs within the Flask application context."""
    # pylint: disable=too-few-public-methods
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)

celery_app.Task = ContextTask
