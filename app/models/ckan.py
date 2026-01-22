# app/models/ckan.py
"""
CKAN upload and resource task models for the Precliniset application.
"""
from datetime import datetime, timezone

from ..extensions import db


class CKANUploadTask(db.Model):
    """Model for CKAN upload tasks."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    project = db.relationship('Project', backref=db.backref('ckan_upload_tasks', lazy='dynamic'))

    def __repr__(self):
        return f'<CKANUploadTask Project:{self.project_id} Status:{self.status}>'


class CKANResourceTask(db.Model):
    """Model for CKAN resource tasks."""
    id = db.Column(db.Integer, primary_key=True)
    upload_task_id = db.Column(db.Integer, db.ForeignKey('ckan_upload_task.id', ondelete='CASCADE'), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='pending')
    ckan_resource_id = db.Column(db.String(255), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    upload_task = db.relationship('CKANUploadTask', backref=db.backref('resource_tasks', lazy='dynamic', cascade="all, delete-orphan"))

    def __repr__(self):
        return f'<CKANResourceTask Type:{self.resource_type} ID:{self.resource_id} Status:{self.status}>'
