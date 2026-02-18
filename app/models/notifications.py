# app/models/notifications.py
from datetime import datetime, timezone

from app.extensions import db


class NotificationType:
    INFO = 'info'
    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'
    ANALYSIS_DONE = 'analysis_done'
    WORKPLAN_UPDATE = 'workplan_update'
    EMAIL_FALLBACK = 'email_fallback'


class Notification(db.Model):
    """
    In-app notification model.
    Used as a fallback when SMTP is not configured, and for async task completion alerts.
    """
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(32), nullable=False, default=NotificationType.INFO)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    link = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Notification {self.id} user={self.user_id} type={self.type} read={self.is_read}>'

    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message,
            'type': self.type,
            'is_read': self.is_read,
            'link': self.link,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
