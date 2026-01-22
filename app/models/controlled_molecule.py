# app/models/controlled_molecule.py
"""
Models for controlled molecules (narcotics and regulated substances) tracking.
Implements regulatory compliance for French pharmaceutical law.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Enum as SQLAlchemyEnum

from ..extensions import db
from .enums import RegulationCategory


class ControlledMolecule(db.Model):
    """Model for controlled/regulated molecules (stupéfiants, molécules contrôlées)."""
    __tablename__ = 'controlled_molecule'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    regulation_category = db.Column(SQLAlchemyEnum(RegulationCategory), nullable=False, index=True)
    storage_location = db.Column(db.String(500), nullable=True)
    responsible_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    cas_number = db.Column(db.String(50), nullable=True)
    internal_reference = db.Column(db.String(100), nullable=True, index=True)
    unit = db.Column(db.String(20), nullable=True)  # mL, mg, UI, etc.
    requires_secure_prescription = db.Column(db.Boolean, default=False, nullable=False)
    max_prescription_days = db.Column(db.Integer, nullable=True)  # Regulatory max duration
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), 
                          onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    responsible = db.relationship('User', backref=db.backref('managed_molecules', lazy='dynamic'))
    protocol_associations = db.relationship('ProtocolMoleculeAssociation', back_populates='molecule', 
                                           cascade="all, delete-orphan")
    usage_records = db.relationship('DataTableMoleculeUsage', back_populates='molecule', 
                                   lazy='dynamic', cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<ControlledMolecule {self.name} ({self.regulation_category.value})>'
    
    def to_dict(self):
        """Return dictionary representation."""
        return {
            'id': self.id,
            'name': self.name,
            'regulation_category': self.regulation_category.name,
            'regulation_category_label': self.regulation_category.value,
            'storage_location': self.storage_location,
            'responsible_id': self.responsible_id,
            'responsible_name': self.responsible.username if self.responsible else None,
            'cas_number': self.cas_number,
            'internal_reference': self.internal_reference,
            'unit': self.unit,
            'requires_secure_prescription': self.requires_secure_prescription,
            'max_prescription_days': self.max_prescription_days,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ProtocolMoleculeAssociation(db.Model):
    """Association between ProtocolModel and ControlledMolecule."""
    __tablename__ = 'protocol_molecule_association'
    
    protocol_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id', ondelete='CASCADE'), 
                           primary_key=True)
    molecule_id = db.Column(db.Integer, db.ForeignKey('controlled_molecule.id', ondelete='CASCADE'), 
                           primary_key=True)
    is_required = db.Column(db.Boolean, default=True, nullable=False)
    default_volume = db.Column(db.Numeric(10, 4), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    protocol = db.relationship('ProtocolModel', back_populates='molecule_associations')
    molecule = db.relationship('ControlledMolecule', back_populates='protocol_associations')
    
    def __repr__(self):
        return f'<ProtocolMoleculeAssociation Protocol:{self.protocol_id} Molecule:{self.molecule_id}>'


class DataTableMoleculeUsage(db.Model):
    """Record of controlled molecule usage in a DataTable (experiment)."""
    __tablename__ = 'data_table_molecule_usage'
    
    id = db.Column(db.Integer, primary_key=True)
    data_table_id = db.Column(db.Integer, db.ForeignKey('data_table.id', ondelete='CASCADE'), 
                             nullable=False, index=True)
    molecule_id = db.Column(db.Integer, db.ForeignKey('controlled_molecule.id'), 
                           nullable=False, index=True)
    volume_used = db.Column(db.Numeric(10, 4), nullable=False)  # Actual volume/quantity used
    
    # Store list of animal IDs (strings) from the experimental group
    animal_ids = db.Column(db.JSON, nullable=True) 
    number_of_animals = db.Column(db.Integer, nullable=False)  # Number of animals treated
    
    batch_number = db.Column(db.String(100), nullable=True)  # Lot number
    administration_route = db.Column(db.String(100), nullable=True)  # Route of administration
    notes = db.Column(db.Text, nullable=True)
    
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    recorded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    data_table = db.relationship('DataTable', back_populates='molecule_usages')
    molecule = db.relationship('ControlledMolecule', back_populates='usage_records')
    recorded_by = db.relationship('User', backref=db.backref('recorded_molecule_usages', lazy='dynamic'))
    
    def __repr__(self):
        return f'<DataTableMoleculeUsage DataTable:{self.data_table_id} Molecule:{self.molecule_id} Volume:{self.volume_used}>'
    
    def to_dict(self):
        """Return dictionary representation."""
        return {
            'id': self.id,
            'data_table_id': self.data_table_id,
            'molecule_id': self.molecule_id,
            'molecule_name': self.molecule.name if self.molecule else None,
            'volume_used': float(self.volume_used) if self.volume_used else None,
            'number_of_animals': self.number_of_animals,
            'animal_ids': self.animal_ids,
            'batch_number': self.batch_number,
            'administration_route': self.administration_route,
            'notes': self.notes,
            'recorded_by_id': self.recorded_by_id,
            'recorded_by_name': self.recorded_by.username if self.recorded_by else None,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None
        }
