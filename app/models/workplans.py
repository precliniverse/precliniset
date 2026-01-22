# app/models/workplans.py
"""
Workplan models for the Precliniset application.
"""
from datetime import datetime, timezone

from sqlalchemy import Enum as SQLAlchemyEnum

from ..extensions import db
from .enums import WorkplanEventStatus, WorkplanStatus


class Workplan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    animal_model_id = db.Column(db.Integer, db.ForeignKey('animal_model.id'), nullable=True)
    planned_animal_count = db.Column(db.Integer, nullable=False)
    status = db.Column(SQLAlchemyEnum(WorkplanStatus), default=WorkplanStatus.DRAFT, nullable=False)
    study_start_date = db.Column(db.Date, nullable=True)
    expected_dob = db.Column(db.Date, nullable=True)
    current_version_id = db.Column(db.Integer, db.ForeignKey('workplan_version.id', use_alter=True, name='fk_workplan_current_version'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    project = db.relationship('Project', back_populates='workplans')
    animal_model = db.relationship('AnimalModel')
    events = db.relationship('WorkplanEvent', back_populates='workplan', lazy='dynamic', cascade="all, delete-orphan")
    versions = db.relationship('WorkplanVersion', back_populates='workplan', lazy='dynamic', cascade="all, delete-orphan", foreign_keys='WorkplanVersion.workplan_id')
    current_version = db.relationship('WorkplanVersion', foreign_keys=[current_version_id], post_update=True)
    generated_group = db.relationship('ExperimentalGroup', backref='created_from_workplan', uselist=False, foreign_keys='ExperimentalGroup.created_from_workplan_id')


class WorkplanVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workplan_id = db.Column(db.Integer, db.ForeignKey('workplan.id', ondelete='CASCADE'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    change_comment = db.Column(db.Text, nullable=True)
    snapshot = db.Column(db.JSON, nullable=False)

    workplan = db.relationship('Workplan', back_populates='versions', foreign_keys=[workplan_id])
    creator = db.relationship('User')


class WorkplanEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workplan_id = db.Column(db.Integer, db.ForeignKey('workplan.id', ondelete='CASCADE'), nullable=False)
    protocol_id = db.Column(db.Integer, db.ForeignKey('protocol_model.id'), nullable=False)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    offset_days = db.Column(db.Integer, nullable=False)
    event_name = db.Column(db.String(255), nullable=True)
    status = db.Column(SQLAlchemyEnum(WorkplanEventStatus), default=WorkplanEventStatus.PLANNED, nullable=False)

    workplan = db.relationship('Workplan', back_populates='events')
    protocol = db.relationship('ProtocolModel')
    assignee = db.relationship('User')
    generated_datatables = db.relationship('DataTable', backref='generated_from_event', lazy='dynamic')
