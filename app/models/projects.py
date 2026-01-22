# app/models/projects.py
"""
Project-related models for the Precliniset application.
"""
from datetime import datetime, timezone

from ..extensions import db


# --- Mixin for Shared Permissions ---
class ProjectShareMixin:
    """Standard columns for project sharing (User or Team)."""
    can_view_project = db.Column(db.Boolean, default=True, nullable=False)
    can_view_exp_groups = db.Column(db.Boolean, default=False, nullable=False)
    can_view_datatables = db.Column(db.Boolean, default=False, nullable=False)
    can_view_samples = db.Column(db.Boolean, default=False, nullable=False)
    # Experimental Group Permissions
    can_create_exp_groups = db.Column(db.Boolean, default=False, nullable=False)
    can_edit_exp_groups = db.Column(db.Boolean, default=False, nullable=False)
    can_delete_exp_groups = db.Column(db.Boolean, default=False, nullable=False)
    
    # DataTable Permissions
    can_create_datatables = db.Column(db.Boolean, default=False, nullable=False)
    can_edit_datatables = db.Column(db.Boolean, default=False, nullable=False)
    can_delete_datatables = db.Column(db.Boolean, default=False, nullable=False)
    
    # Sensitive Data
    can_view_unblinded_data = db.Column(db.Boolean, default=False, nullable=False)

# --- Association Tables ---

class ProjectPartnerAssociation(db.Model):
    __tablename__ = 'project_partner_association'
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id', ondelete='CASCADE'), primary_key=True)

    project = db.relationship('Project', back_populates='partner_associations')
    partner = db.relationship('Partner', back_populates='project_associations')

    def __repr__(self):
        return f'<ProjectPartnerAssociation Project:{self.project_id} Partner:{self.partner_id}>'


class ProjectEthicalApprovalAssociation(db.Model):
    __tablename__ = 'project_ethical_approval_association'
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True)
    ethical_approval_id = db.Column(db.Integer, db.ForeignKey('ethical_approval.id', ondelete='CASCADE'), primary_key=True)

    project = db.relationship('Project', back_populates='ethical_approval_associations')
    ethical_approval = db.relationship('EthicalApproval', back_populates='project_associations')

    def __repr__(self):
        return f'<ProjectEthicalApprovalAssociation Project:{self.project_id} EthicalApproval:{self.ethical_approval_id}>'


class Project(db.Model):
    """Model for Projects."""
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(20), unique=True, nullable=True, index=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    ckan_upload_date = db.Column(db.DateTime, nullable=True)
    ckan_dataset_id = db.Column(db.String(255), nullable=True)
    ckan_organization_id = db.Column(db.String(255), nullable=True)

    team = db.relationship('Team', back_populates='projects')
    owner = db.relationship('User', backref=db.backref('owned_projects', lazy='dynamic'))
    attachments = db.relationship('Attachment', back_populates='project', lazy='dynamic', cascade="all, delete-orphan")

    partner_associations = db.relationship('ProjectPartnerAssociation', back_populates='project', cascade="all, delete-orphan")
    partners = db.relationship('Partner', secondary='project_partner_association', viewonly=True, lazy='dynamic')

    groups = db.relationship('ExperimentalGroup', back_populates='project', cascade="all, delete-orphan")

    ethical_approval_associations = db.relationship('ProjectEthicalApprovalAssociation', back_populates='project', cascade="all, delete-orphan")
    ethical_approvals = db.relationship('EthicalApproval', secondary='project_ethical_approval_association', viewonly=True, lazy='dynamic')
    workplans = db.relationship('Workplan', back_populates='project', lazy='dynamic', cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint('team_id', 'name', name='_project_team_name_uc'),)

    def __repr__(self):
        return f'<Project {self.name} (Slug: {self.slug})>'


class ProjectTeamShare(db.Model, ProjectShareMixin):
    """Association for sharing projects with teams."""
    __tablename__ = 'project_team_share'
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), primary_key=True)
    
    # Mixin provides the boolean flags (can_view_project, can_create_exp_groups, etc.)

    project = db.relationship('Project', backref=db.backref('team_shares', cascade="all, delete-orphan"))
    team = db.relationship('Team', backref=db.backref('shared_projects', lazy='dynamic'))

    def __repr__(self):
        return f'<ProjectTeamShare Project:{self.project_id} Team:{self.team_id}>'


class ProjectUserShare(db.Model, ProjectShareMixin):
    """Association for sharing projects with users."""
    __tablename__ = 'project_user_share'
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    
    # Mixin provides the boolean flags.
    # We keep permission_level temporarily to avoid breaking existing data during migration, 
    # but logic will rely on flags.
    permission_level = db.Column(db.String(20), nullable=True) 

    project = db.relationship('Project', backref=db.backref('user_shares', cascade="all, delete-orphan"))
    user = db.relationship('User', backref=db.backref('shared_projects', lazy='dynamic'))

    def __repr__(self):
        return f'<ProjectUserShare Project:{self.project_id} User:{self.user_id}>'


class Partner(db.Model):
    """Model for Partners."""
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    contact_email = db.Column(db.String(120), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    project_associations = db.relationship('ProjectPartnerAssociation', back_populates='partner', cascade="all, delete-orphan")
    projects = db.relationship('Project', secondary='project_partner_association', viewonly=True, lazy='dynamic')

    def __repr__(self):
        return f'<Partner {self.company_name}>'


class Attachment(db.Model):
    """Model for Project Attachments."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    size = db.Column(db.Integer, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    project = db.relationship('Project', back_populates='attachments')

    def __repr__(self):
        return f'<Attachment {self.filename}>'


class ReferenceRange(db.Model):
    """Model for Reference Ranges."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    analyte_id = db.Column(db.Integer, db.ForeignKey('analyte.id'), nullable=True)
    protocol_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id'), nullable=True)
    animal_model_id = db.Column(db.Integer, db.ForeignKey('animal_model.id'), nullable=True)

    min_age = db.Column(db.Integer, nullable=True)
    max_age = db.Column(db.Integer, nullable=True)

    included_animals = db.Column(db.JSON, nullable=True)

    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_globally_shared = db.Column(db.Boolean, default=False, nullable=False)

    analyte = db.relationship('Analyte', backref=db.backref('reference_ranges', lazy='dynamic'))
    protocol = db.relationship('ProtocolModel', backref=db.backref('reference_ranges', lazy='dynamic'))
    animal_model = db.relationship('AnimalModel', backref=db.backref('reference_ranges', lazy='dynamic'))
    owner_team = db.relationship('Team', backref=db.backref('owned_reference_ranges', lazy='dynamic'))
    owner = db.relationship('User', backref=db.backref('owned_reference_ranges', lazy='dynamic'))

    from .teams import reference_range_team_share
    shared_with_teams = db.relationship('Team', secondary=reference_range_team_share, back_populates='shared_reference_ranges', lazy='dynamic')

    __table_args__ = (db.UniqueConstraint('team_id', 'name', name='_reference_range_team_name_uc'),)

    def __repr__(self):
        return f'<ReferenceRange {self.name}>'
    
    def to_dict(self):
        """Return dictionary representation."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'analyte_id': self.analyte_id,
            'protocol_id': self.protocol_id,
            'animal_model_id': self.animal_model_id,
            'min_age': self.min_age,
            'max_age': self.max_age,
            'team_id': self.team_id,
            'included_animals': self.included_animals or {},
            'is_globally_shared': self.is_globally_shared,
            'shared_with_team_ids': [team.id for team in self.shared_with_teams]
        }