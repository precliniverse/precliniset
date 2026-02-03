"""
Animal model for hybrid SQL+JSON data storage.

This module defines the Animal model which stores core animal data in SQL columns
and dynamic scientific measurements in a JSON column.
"""
from datetime import date, datetime, timezone
from typing import Optional

from ..extensions import db


class Animal(db.Model):
    """Animal model with hybrid SQL+JSON storage.
    
    Core fields (ID, sex, status, date of birth) are stored in indexed SQL columns
    for efficient querying. Dynamic scientific measurements (weight, tumor size, etc.)
    are stored in a JSON column for flexibility.
    
    Attributes:
        id: Primary key
        uid: Unique animal identifier (e.g., "A001", "Mouse-1")
        group_id: Foreign key to ExperimentalGroup
        sex: Animal sex (user-configurable values)
        status: Animal status (alive, dead, etc.)
        date_of_birth: Date of birth
        measurements: JSON column for dynamic scientific data
        created_at: Timestamp of record creation
        updated_at: Timestamp of last update
    """
    
    __tablename__ = 'animal'
    
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(100), nullable=False, index=True)
    group_id = db.Column(
        db.String(40),
        db.ForeignKey('experimental_group.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    sex = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='alive', index=True)
    date_of_birth = db.Column(db.Date, nullable=True, index=True)
    measurements = db.Column(db.JSON, nullable=True, default=dict)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'uid', name='_group_animal_uid_uc'),
    )
    
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    # Relationships
    group = db.relationship(
        'ExperimentalGroup',
        back_populates='animals'
    )
    
    def __repr__(self) -> str:
        """String representation of Animal.
        
        Returns:
            String representation showing UID and group
        """
        return f'<Animal {self.uid} (Group: {self.group_id})>'
    
    def to_dict(self, include_measurements: bool = True) -> dict:
        """Convert animal to dictionary.
        
        Args:
            include_measurements: Whether to include measurements
            
        Returns:
            Dictionary representation of animal
        """
        dob_iso = self.date_of_birth.isoformat() if self.date_of_birth else None
        result = {
            'id': self.id,
            'uid': self.uid,
            'ID': self.uid,  # Compatibility for capitalized lookup
            'group_id': self.group_id,
            'sex': self.sex,
            'status': self.status,
            'date_of_birth': dob_iso,
            'Date of Birth': dob_iso,  # Compatibility for capitalized lookup
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_measurements and self.measurements:
            # Flatten measurements for frontend compatibility
            result.update(self.measurements)
        
        return result
