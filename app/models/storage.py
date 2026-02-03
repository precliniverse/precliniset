# app/models/storage.py
"""
Storage and sample-related models for the Precliniset application.
"""
from datetime import datetime, timezone

from sqlalchemy import Enum as SQLAlchemyEnum

from ..extensions import db
from .enums import SampleStatus, SampleType
from .resources import sample_conditions_association


class Storage(db.Model):
    """Model for Storage locations."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    capacity = db.Column(db.String(100), nullable=True)
    location_details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    team = db.relationship('Team', back_populates='storages')
    samples = db.relationship('Sample', back_populates='storage_location', lazy='dynamic')
    __table_args__ = (db.UniqueConstraint('team_id', 'name', name='_storage_team_name_uc'),)

    def __repr__(self):
        return f'<Storage {self.name} (Team: {self.team_id})>'


class StorageLocation(db.Model):
    """Model for specific storage locations within storage units."""
    id = db.Column(db.Integer, primary_key=True)
    storage_id = db.Column(db.Integer, db.ForeignKey('storage.id', ondelete='CASCADE'), nullable=False)
    label = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<StorageLocation {self.label}>'


class Sample(db.Model):
    """Model for Samples."""
    id = db.Column(db.Integer, primary_key=True)
    display_id = db.Column(db.String(100), nullable=True, index=True)
    parent_sample_id = db.Column(db.Integer, db.ForeignKey('sample.id'), nullable=True)
    derived_samples = db.relationship('Sample', backref=db.backref('parent_sample', remote_side=[id]), lazy='dynamic')

    experimental_group_id = db.Column(db.String(40), db.ForeignKey('experimental_group.id', ondelete='CASCADE'), nullable=False)
    animal_index_in_group = db.Column(db.Integer, nullable=False)
    sample_type = db.Column(SQLAlchemyEnum(SampleType), nullable=False)
    collection_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    is_terminal = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.Enum(SampleStatus), nullable=False, default=SampleStatus.STORED)
    shipment_date = db.Column(db.Date, nullable=True)
    destruction_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    derived_type_id = db.Column(db.Integer, db.ForeignKey('derived_sample_type.id'), nullable=True)
    staining_id = db.Column(db.Integer, db.ForeignKey('staining.id'), nullable=True)
    storage_id = db.Column(db.Integer, db.ForeignKey('storage.id', ondelete='SET NULL'), nullable=True)

    # Type-specific fields
    # For BLOOD and URINE
    anticoagulant_id = db.Column(db.Integer, db.ForeignKey('anticoagulant.id'), nullable=True)
    anticoagulant = db.relationship('Anticoagulant', backref='samples')
    volume = db.Column(db.Float, nullable=True)
    volume_unit = db.Column(db.String(20), nullable=True, default='µL')

    # For BIOLOGICAL_TISSUE
    organ_id = db.Column(db.Integer, db.ForeignKey('organ.id'), nullable=True)
    piece_id = db.Column(db.String(100), nullable=True)

    # Many-to-Many relationship for conditions
    collection_conditions = db.relationship('TissueCondition', secondary=sample_conditions_association, lazy='subquery',
                                            backref=db.backref('samples', lazy=True))

    experimental_group = db.relationship('ExperimentalGroup', back_populates='samples')
    storage_location = db.relationship('Storage', back_populates='samples', foreign_keys=[storage_id])
    organ = db.relationship('Organ', backref='samples')
    derived_type = db.relationship('DerivedSampleType', backref='samples')
    staining = db.relationship('Staining', backref='samples')

    @property
    def animal_display_id(self):
        """
        Constructs a display ID for the animal based on available data.
        Tries to use the Animal UID from the relationship.
        """
        if self.experimental_group:
            # Note: animal_index_in_group is still used to link Sample to Animal list index
            # sorted by ID for consistency.
            animals = sorted(self.experimental_group.animals, key=lambda a: a.id)
            if 0 <= self.animal_index_in_group < len(animals):
                return animals[self.animal_index_in_group].uid
        return f"Index {self.animal_index_in_group}"

    def __repr__(self):
        base_repr = f'<Sample ID: {self.id} Type: {self.sample_type.value}>'
        if self.sample_type == SampleType.BIOLOGICAL_TISSUE and self.organ:
            return f'{base_repr} Organ: {self.organ.name}'
        return base_repr


class DerivedSample(db.Model):
    """Model for Derived Samples (legacy - now handled by Sample with parent_sample_id)."""
    id = db.Column(db.Integer, primary_key=True)
    # Note: This model might be deprecated in favor of Sample.parent_sample_id
    def __repr__(self):
        return f'<DerivedSample {self.id}>'
