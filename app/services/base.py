# app/services/base.py
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db


class BaseService:
    """Base class for all services."""
    
    model = None

    def __init__(self):
        pass

    def get(self, id):
        """Get a record by ID."""
        return db.session.get(self.model, id)

    def get_all(self):
        """Get all records."""
        return self.model.query.all()

    def create(self, **kwargs):
        """Create a new record."""
        try:
            instance = self.model(**kwargs)
            db.session.add(instance)
            db.session.commit()
            return instance
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating {self.model.__name__}: {str(e)}")
            raise e

    def update(self, instance, **kwargs):
        """Update an existing record."""
        try:
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            db.session.commit()
            return instance
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating {self.model.__name__}: {str(e)}")
            raise e

    def delete(self, instance):
        """Delete a record."""
        try:
            db.session.delete(instance)
            db.session.commit()
            return True
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Error deleting {self.model.__name__}: {str(e)}")
            raise e
