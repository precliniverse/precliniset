from datetime import datetime, timezone
from app.extensions import db

class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Nullable for system actions or deleted users
    action = db.Column(db.String(50), nullable=False) # INSERT, UPDATE, DELETE
    resource_type = db.Column(db.String(50), nullable=False) # Table name or Model name
    resource_id = db.Column(db.String(50), nullable=True) # ID of the modified resource
    changes = db.Column(db.JSON, nullable=True) # JSON diff
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Optional: Relationship to user if needed for display
    user = db.relationship('User')

    def __repr__(self):
        return f"<AuditLog {self.action} {self.resource_type}:{self.resource_id} by {self.user_id}>"
