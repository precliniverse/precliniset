# app/models/resources.py
"""
Resource models for the Precliniset application.
Includes Analytes, Organs, Protocols, Animal Models, and Housing Conditions.
"""
from sqlalchemy import Enum as SQLAlchemyEnum

from ..extensions import db
from .enums import AnalyteDataType, SampleType, Severity


class Anticoagulant(db.Model):
    """Model for Anticoagulants used in samples."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<Anticoagulant {self.name}>'


class Organ(db.Model):
    """Model for Organs."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<Organ {self.name}>'


class TissueCondition(db.Model):
    """Model for Tissue Conditions."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<TissueCondition {self.name}>'


# Association table for Sample-TissueCondition relationship
sample_conditions_association = db.Table('sample_conditions',
    db.Column('sample_id', db.Integer, db.ForeignKey('sample.id', ondelete='CASCADE'), primary_key=True),
    db.Column('condition_id', db.Integer, db.ForeignKey('tissue_condition.id', ondelete='CASCADE'), primary_key=True)
)


class Staining(db.Model):
    """Model for Staining types."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<Staining {self.name}>'


class HousingSetItemAssociation(db.Model):
    """Association between HousingConditionSet and HousingConditionItem."""
    __tablename__ = 'housing_set_item_association'
    set_id = db.Column(db.Integer, db.ForeignKey('housing_condition_set.id', ondelete='CASCADE'), primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('housing_condition_item.id', ondelete='CASCADE'), primary_key=True)
    default_value = db.Column(db.Text, nullable=True)

    condition_set = db.relationship('HousingConditionSet', back_populates='item_associations')
    item = db.relationship('HousingConditionItem', back_populates='set_associations')

    def __repr__(self):
        return f'<HousingSetItemAssociation Set:{self.set_id} Item:{self.item_id} Value:{self.default_value}>'


class HousingConditionSet(db.Model):
    """Model for a set of housing conditions."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    creator = db.relationship('User', backref=db.backref('created_housing_condition_sets', lazy='dynamic'))

    item_associations = db.relationship('HousingSetItemAssociation', back_populates='condition_set', cascade="all, delete-orphan")
    items = db.relationship('HousingConditionItem', secondary='housing_set_item_association', lazy='dynamic', back_populates='sets', overlaps="condition_set,item_associations,item")
    datatables = db.relationship('DataTable', back_populates='housing_condition', lazy='dynamic')

    def __repr__(self):
        return f'<HousingConditionSet {self.name}>'


class HousingConditionItem(db.Model):
    """Model for an individual housing condition item."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    data_type = db.Column(SQLAlchemyEnum(AnalyteDataType), nullable=False)
    allowed_values = db.Column(db.Text, nullable=True)
    unit = db.Column(db.String(50), nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    default_value = db.Column(db.Text, nullable=True)

    creator = db.relationship('User', backref=db.backref('created_housing_condition_items', lazy='dynamic'))

    set_associations = db.relationship('HousingSetItemAssociation', back_populates='item', cascade="all, delete-orphan", overlaps="items")
    sets = db.relationship('HousingConditionSet', secondary='housing_set_item_association', lazy='dynamic', back_populates='items', overlaps="item,set_associations,condition_set,item_associations")

    def __repr__(self):
        return f'<HousingConditionItem {self.name}>'


class DerivedSampleType(db.Model):
    """Model for derived sample types."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    parent_type = db.Column(SQLAlchemyEnum(SampleType), nullable=False)

    def __repr__(self):
        return f'<DerivedSample Type {self.name} (from {self.parent_type.name})>'


class AnimalModelAnalyteAssociation(db.Model):
    """Association between AnimalModel and Analyte."""
    __tablename__ = 'animal_model_analyte_association'
    animal_model_id = db.Column(db.Integer, db.ForeignKey('animal_model.id'), primary_key=True)
    analyte_id = db.Column(db.Integer, db.ForeignKey('analyte.id'), primary_key=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    is_grouping = db.Column(db.Boolean, default=False, nullable=False)

    animal_model = db.relationship('AnimalModel', back_populates='analyte_associations')
    analyte = db.relationship('Analyte', back_populates='animal_model_associations')

    def __repr__(self):
        return f'<AnimalModelAnalyteAssociation AnimalModel:{self.animal_model_id} Analyte:{self.analyte_id} Order:{self.order}>'


class ProtocolAnalyteAssociation(db.Model):
    """Association between ProtocolModel and Analyte."""
    __tablename__ = 'protocol_analyte_association'
    protocol_model_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id'), primary_key=True)
    analyte_id = db.Column(db.Integer, db.ForeignKey('analyte.id'), primary_key=True)
    default_value = db.Column(db.Text, nullable=True)
    is_metadata = db.Column(db.Boolean, default=False, nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    calculation_formula = db.Column(db.Text, nullable=True) # Stores formula e.g. "[Weight] / [Height]"
    is_grouping = db.Column(db.Boolean, default=False, nullable=False)

    protocol_model = db.relationship('ProtocolModel', back_populates='analyte_associations')
    analyte = db.relationship('Analyte', back_populates='protocol_associations')

    def __repr__(self):
        return f'<ProtocolAnalyteAssociation Protocol:{self.protocol_model_id} Analyte:{self.analyte_id}>'


# Association table for ProtocolModel-ImportPipeline relationship
protocol_pipeline_association = db.Table('protocol_pipeline_association',
    db.Column('protocol_id', db.Integer, db.ForeignKey('protocol_model.id', ondelete='CASCADE'), primary_key=True),
    db.Column('pipeline_id', db.Integer, db.ForeignKey('import_pipeline.id', ondelete='CASCADE'), primary_key=True)
)


class Analyte(db.Model):
    """Model for Analytes."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    unit = db.Column(db.String(50), nullable=True)
    data_type = db.Column(SQLAlchemyEnum(AnalyteDataType), nullable=False)
    allowed_values = db.Column(db.Text, nullable=True)
    default_value = db.Column(db.Text, nullable=True)
    is_metadata = db.Column(db.Boolean, default=False, nullable=False)
    is_sensitive = db.Column(db.Boolean, default=False, nullable=False)
    is_mandatory = db.Column(db.Boolean, default=False, nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    creator = db.relationship('User', backref=db.backref('created_analytes', lazy='dynamic'))

    protocol_associations = db.relationship('ProtocolAnalyteAssociation', back_populates='analyte', cascade="all, delete-orphan")
    animal_model_associations = db.relationship('AnimalModelAnalyteAssociation', back_populates='analyte', cascade="all, delete-orphan")

    def to_dict(self):
        """Return dictionary representation."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'unit': self.unit,
            'data_type': self.data_type.value,
            'allowed_values': self.allowed_values,
            'default_value': self.default_value,
            'is_metadata': self.is_metadata,
            'is_sensitive': self.is_sensitive
        }

    def __repr__(self):
        return f'<Analyte {self.name}>'


class AnimalModel(db.Model):
    """Model for Animal Models."""
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    groups = db.relationship('ExperimentalGroup', back_populates='model', lazy='dynamic')

    analyte_associations = db.relationship('AnimalModelAnalyteAssociation', back_populates='animal_model', cascade="all, delete-orphan")
    analytes = db.relationship('Analyte', secondary='animal_model_analyte_association', viewonly=True, lazy='subquery', backref=db.backref('animal_models', lazy=True))

    def to_dict(self):
        """Return dictionary representation."""
        return {
            'id': self.id,
            'name': self.name,
            'analytes': [analyte.to_dict() for analyte in self.analytes]
        }

    def __repr__(self):
        return f'<AnimalModel {self.name}>'


class ProtocolModel(db.Model):
    """Model for Protocols."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(255), nullable=True)
    severity = db.Column(SQLAlchemyEnum(Severity), default=Severity.NONE, nullable=False)
    external_skill_ids = db.Column(db.JSON, nullable=True)  # IDs of skills from Training Manager
    enable_import_wizard = db.Column(db.Boolean, default=False, nullable=False)
    data_tables = db.relationship('DataTable', back_populates='protocol', lazy='dynamic')
    attachments = db.relationship('ProtocolAttachment', back_populates='protocol', lazy='dynamic', cascade="all, delete-orphan")

    analyte_associations = db.relationship('ProtocolAnalyteAssociation', back_populates='protocol_model', cascade="all, delete-orphan", order_by="ProtocolAnalyteAssociation.order")
    analytes = db.relationship('Analyte', secondary='protocol_analyte_association', viewonly=True, lazy='subquery')
    
    molecule_associations = db.relationship('ProtocolMoleculeAssociation', back_populates='protocol', cascade="all, delete-orphan")
    controlled_molecules = db.relationship('ControlledMolecule', secondary='protocol_molecule_association', viewonly=True, lazy='subquery')

    import_pipelines = db.relationship('ImportPipeline', secondary=protocol_pipeline_association, backref=db.backref('protocols', lazy='dynamic'))

    def __repr__(self):
        return f'<ProtocolModel {self.name}>'


class ProtocolAttachment(db.Model):
    """Model for Protocol Attachments."""
    id = db.Column(db.Integer, primary_key=True)
    protocol_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id',  ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)

    protocol = db.relationship('ProtocolModel', back_populates='attachments')

    def __repr__(self):
        return f'<ProtocolAttachment {self.filename} for Protocol {self.protocol_id}>'
