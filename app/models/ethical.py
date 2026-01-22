# app/models/ethical.py
"""
Ethical approval models for the Precliniset application.
"""
from sqlalchemy import Enum as SQLAlchemyEnum

from ..extensions import db
from .enums import Severity


class EthicalApproval(db.Model):
    """Model for Ethical Approvals."""
    id = db.Column(db.Integer, primary_key=True)
    reference_number = db.Column(db.String(50), nullable=False, unique=True)
    apafis_reference = db.Column(db.String(50), nullable=True, index=True)
    apafis_version = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(255), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    species = db.Column(db.String(100), nullable=True)
    sex_justification = db.Column(db.Text, nullable=True)
    number_of_animals = db.Column(db.Integer, nullable=False)
    euthanasia_method = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    overall_severity = db.Column(SQLAlchemyEnum(Severity), default=Severity.NONE, nullable=False)

    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    owner_team = db.relationship('Team', back_populates='ethical_approvals')
    
    # Import at function level to avoid circular imports
    from .teams import ethical_approval_team_share
    shared_with_teams = db.relationship('Team', secondary=ethical_approval_team_share, back_populates='shared_ethical_approvals', lazy='dynamic')

    project_associations = db.relationship('ProjectEthicalApprovalAssociation', back_populates='ethical_approval', cascade="all, delete-orphan")
    projects = db.relationship('Project', secondary='project_ethical_approval_association', viewonly=True, lazy='dynamic')

    procedures = db.relationship('EthicalApprovalProcedure', back_populates='ethical_approval', lazy='dynamic', cascade="all, delete-orphan")

    def __repr__(self):
        return f"<EthicalApproval('{self.reference_number}', Severity: '{self.overall_severity.value}')>"


class EthicalApprovalProcedure(db.Model):
    """Model for Ethical Approval Procedures."""
    __tablename__ = 'ethical_approval_procedure'
    id = db.Column(db.Integer, primary_key=True)
    ethical_approval_id = db.Column(db.Integer, db.ForeignKey('ethical_approval.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    severity = db.Column(SQLAlchemyEnum(Severity), default=Severity.NONE, nullable=False)
    description = db.Column(db.Text, nullable=True)
    pain_management = db.Column(db.Text, nullable=True)
    is_euthanasia_endpoint = db.Column(db.Boolean, default=False, nullable=False)

    ethical_approval = db.relationship('EthicalApproval', back_populates='procedures')

    def __repr__(self):
        return f"<EthicalApprovalProcedure('{self.name}', Severity: '{self.severity.value}')>"
