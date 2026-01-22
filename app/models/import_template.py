# app/models/import_template.py
from datetime import datetime, timezone
from ..extensions import db

class ImportTemplate(db.Model):
    """Model for storing import mapping templates."""
    __tablename__ = 'import_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    protocol_model_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id', ondelete='CASCADE'), nullable=False)
    
    # Stores the mapping: { "file_column_name": "analyte_id", ... }
    mapping_json = db.Column(db.JSON, nullable=False)
    
    # Advanced options
    skip_rows = db.Column(db.Integer, default=0, nullable=False)
    anchor_text = db.Column(db.String(255), nullable=True)
    anchor_offset = db.Column(db.Integer, default=0, nullable=False)
    row_interval = db.Column(db.Integer, default=1, nullable=False)
    advanced_logic = db.Column(db.JSON, nullable=True) # Stores { "analyte_id": "formula", ... }
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    protocol_model = db.relationship('ProtocolModel', backref=db.backref('import_templates', lazy='dynamic', cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<ImportTemplate {self.name} for Protocol {self.protocol_model_id}>'
