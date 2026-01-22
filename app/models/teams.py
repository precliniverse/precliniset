# app/models/teams.py
"""
Team-related models for the Precliniset application.
"""
from datetime import datetime, timezone

from ..extensions import db

# Association tables for team sharing
ethical_approval_team_share = db.Table('ethical_approval_team_share',
    db.Column('ethical_approval_id', db.Integer, db.ForeignKey('ethical_approval.id', ondelete='CASCADE'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), primary_key=True)
)

reference_range_team_share = db.Table('reference_range_team_share',
    db.Column('reference_range_id', db.Integer, db.ForeignKey('reference_range.id', ondelete='CASCADE'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), primary_key=True)
)


class Team(db.Model):
    """Model for Teams."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    memberships = db.relationship('TeamMembership', back_populates='team', cascade="all, delete-orphan")
    projects = db.relationship('Project', back_populates='team', lazy='dynamic', cascade="all, delete-orphan")
    storages = db.relationship('Storage', back_populates='team', lazy='dynamic', cascade="all, delete-orphan")
    ethical_approvals = db.relationship('EthicalApproval', back_populates='owner_team', lazy='dynamic', cascade="all, delete-orphan")
    shared_ethical_approvals = db.relationship('EthicalApproval', secondary=ethical_approval_team_share, back_populates='shared_with_teams', lazy='dynamic')
    shared_reference_ranges = db.relationship('ReferenceRange', secondary=reference_range_team_share, back_populates='shared_with_teams', lazy='dynamic')

    # RBAC relationships
    roles = db.relationship('Role', back_populates='team', cascade="all, delete-orphan")
    user_roles = db.relationship('UserTeamRoleLink', back_populates='team', cascade="all, delete-orphan")

    @property
    def members(self):
        """Returns a list of User objects who are members of this team."""
        return [membership.user for membership in self.memberships]

    def __repr__(self):
        return f'<Team {self.name}>'


class TeamMembership(db.Model):
    """Model for Team Memberships."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id', ondelete='CASCADE'), nullable=False)

    user = db.relationship('User', back_populates='memberships')
    team = db.relationship('Team', back_populates='memberships')
    __table_args__ = (db.UniqueConstraint('user_id', 'team_id', name='_user_team_uc'),)

    def __repr__(self):
        return f'<TeamMembership User: {self.user_id} Team: {self.team_id}>'
