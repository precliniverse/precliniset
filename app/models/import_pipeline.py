# app/models/import_pipeline.py
from datetime import datetime, timezone
from ..extensions import db

class ImportPipeline(db.Model):
    """
    Model for storing custom import logic scripts.
    Used to transform incoming data during the import process.
    """
    __tablename__ = 'import_pipeline'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    script_content = db.Column(db.Text, nullable=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    creator = db.relationship('User', backref=db.backref('import_pipelines', lazy='dynamic'))

    def __repr__(self):
        return f'<ImportPipeline {self.name}>'
