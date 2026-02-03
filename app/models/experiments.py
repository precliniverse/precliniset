# app/models/experiments.py
import secrets
from datetime import datetime, timezone

from ..extensions import db

class ExperimentalGroup(db.Model):
    id = db.Column(db.String(40), primary_key=True, default=lambda: secrets.token_hex(20))
    name = db.Column(db.String(80), nullable=False, index=True)
    
    # --- PERFORMANCE FIX: Added index=True here ---
    ethical_approval_id = db.Column(db.Integer, db.ForeignKey('ethical_approval.id', ondelete='SET NULL'), nullable=True, index=True)
    
    model_id = db.Column(db.Integer, db.ForeignKey('animal_model.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), nullable=False, index=True)
    randomization_details = db.Column(db.JSON, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)
    created_from_workplan_id = db.Column(db.Integer, db.ForeignKey('workplan.id'), nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    archived_at = db.Column(db.DateTime, nullable=True)

    # Default euthanasia details for group
    default_euthanasia_reason = db.Column(db.String(100), nullable=True)
    default_severity = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    model = db.relationship('AnimalModel', back_populates='groups')
    owner = db.relationship('User', backref=db.backref('owned_groups', lazy='dynamic'))
    team = db.relationship('Team')
    project = db.relationship('Project', back_populates='groups')
    data_tables = db.relationship('DataTable', back_populates='group', lazy='dynamic', cascade="all, delete-orphan")
    ethical_approval = db.relationship('EthicalApproval', backref=db.backref('experimental_groups', lazy='dynamic'))
    samples = db.relationship('Sample', back_populates='experimental_group', lazy='dynamic', cascade="all, delete-orphan")
    animals = db.relationship('Animal', back_populates='group', cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint('project_id', 'name', name='_project_group_name_uc'),)

    def __init__(self, **kwargs):
        # 1. Handle ID generation/assignment first to ensure setters have it
        group_id = kwargs.get('id')
        if group_id is None:
            project_id = kwargs.get('project_id')
            if project_id:
                from .projects import Project 
                project = db.session.get(Project, project_id) 
                if project and project.slug:
                    today_str = datetime.now(timezone.utc).strftime('%y%m%d')
                    prefix = f"{project.slug}-{today_str}-"
                    
                    last_group = ExperimentalGroup.query.filter(
                        ExperimentalGroup.id.like(f"{prefix}%")
                    ).order_by(db.desc(ExperimentalGroup.id)).first()
                    
                    sequence = 1
                    if last_group:
                        try:
                            last_sequence_str = last_group.id.split('-')[-1]
                            sequence = int(last_sequence_str) + 1
                        except ValueError:
                            pass
                    
                    group_id = f"{prefix}{sequence}"
                else:
                    group_id = secrets.token_hex(20)
            else:
                group_id = secrets.token_hex(20)
        
        # Explicitly set self.id and ensure it's in kwargs for super().__init__
        self.id = group_id
        kwargs['id'] = group_id
        
        # 2. Call super constructor - this will trigger other setters
        super(ExperimentalGroup, self).__init__(**kwargs)

    @property
    def sample_count(self):
        return self.samples.count()
    
    def __repr__(self):
        return f'<ExperimentalGroup ID: {self.id} Name: {self.name}>'


class DataTable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.String(40), db.ForeignKey('experimental_group.id', ondelete='CASCADE'), nullable=False, index=True)
    protocol_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id'), nullable=False)
    date = db.Column(db.String(80), nullable=False, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    raw_data_url = db.Column(db.String(512), nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    group = db.relationship('ExperimentalGroup', back_populates='data_tables')
    protocol = db.relationship('ProtocolModel', back_populates='data_tables')
    experiment_rows = db.relationship('ExperimentDataRow', backref='data_table', lazy='dynamic', cascade="all, delete-orphan")
    creator = db.relationship('User', foreign_keys=[creator_id], backref=db.backref('created_datatables', lazy='dynamic'))
    assignee = db.relationship('User', foreign_keys=[assigned_to_id], backref=db.backref('assigned_datatables', lazy='dynamic'))
    workplan_event_id = db.Column(db.Integer, db.ForeignKey('workplan_event.id'), nullable=True)
    housing_condition_set_id = db.Column(db.Integer, db.ForeignKey('housing_condition_set.id'), nullable=True)
    housing_condition = db.relationship('HousingConditionSet', back_populates='datatables')
    files = db.relationship('DataTableFile', back_populates='data_table', lazy='dynamic', cascade="all, delete-orphan")
    molecule_usages = db.relationship('DataTableMoleculeUsage', back_populates='data_table', lazy='dynamic', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<DataTable Group: {self.group_id} Protocol: {self.protocol_id} Date: {self.date}>'


class DataTableFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_table_id = db.Column(db.Integer, db.ForeignKey('data_table.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    filepath = db.Column(db.String(512), nullable=False, unique=True)
    size = db.Column(db.Integer, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    data_table = db.relationship('DataTable', back_populates='files')

    def __repr__(self):
        return f'<DataTableFile {self.filename}>'


class ExperimentDataRow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_table_id = db.Column(db.Integer, db.ForeignKey('data_table.id', ondelete='CASCADE'), nullable=False)
    row_index = db.Column(db.Integer, nullable=False)
    row_data = db.Column(db.JSON)
    __table_args__ = (db.UniqueConstraint('data_table_id', 'row_index', name='_data_table_row_uc'),)

    def __repr__(self):
        return f'<ExperimentDataRow Table: {self.data_table_id} Index: {self.row_index}>'