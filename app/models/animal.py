"""
Animal model for hybrid SQL+JSON data storage.

This module defines the Animal model which stores core animal data in SQL columns
and dynamic scientific measurements in a JSON column.
"""
from datetime import date, datetime, timezone
from typing import Optional
import secrets

from ..extensions import db


class Animal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(100), unique=True, nullable=False, default=lambda: secrets.token_hex(12))
    display_id = db.Column(db.String(50), nullable=False, index=True) # The "Simple ID" user sees
    group_id = db.Column(db.String(40), db.ForeignKey('experimental_group.id', ondelete='CASCADE'), index=True)
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

    @property
    def age_days(self) -> Optional[int]:
        """Calculate animal's age in days relative to today."""
        if not self.date_of_birth:
            return self.measurements.get('age_days') if self.measurements else None
        
        delta = date.today() - self.date_of_birth
        return delta.days

    def get_age_at(self, reference_date: date) -> Optional[int]:
        """Calculate animal's age in days relative to a reference date."""
        if not self.date_of_birth:
            return self.measurements.get('age_days') if self.measurements else None
        
        delta = reference_date - self.date_of_birth
        return delta.days
    
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
            'display_id': self.display_id,  # The "Simple ID" user sees
            'group_id': self.group_id,
            'sex': self.sex,
            'status': self.status,
            'date_of_birth': dob_iso,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_measurements and self.measurements:
            # Flatten measurements for frontend compatibility
            result.update(self.measurements)
        
        # Ensure canonical metadata fields are present (even if they were in measurements)
        result['age_days'] = self.age_days
        if self.measurements:
            result['blinded_group'] = self.measurements.get('blinded_group')
            result['treatment_group'] = self.measurements.get('treatment_group')
        
        return result
