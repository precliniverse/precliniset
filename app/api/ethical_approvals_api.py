from flask import current_app, g
from flask_restx import Resource, fields, reqparse
from sqlalchemy import or_

from app.extensions import db, limiter
from app.models import EthicalApproval, Project, Severity, user_has_permission

from . import api
from .auth import token_required

ns = api.namespace('ethical_approvals', description='Ethical Approval operations')

# --- flask-restx Models ---
ethical_approval_input = ns.model('EthicalApprovalInput', {
    'title': fields.String(required=True, description='Title of the approval', max_length=150),
    'reference_number': fields.String(required=True, description='Official reference number', max_length=50),
    'start_date': fields.Date(required=True, description='Approval start date (YYYY-MM-DD)'),
    'end_date': fields.Date(required=True, description='Approval end date (YYYY-MM-DD)'),
    'number_of_animals': fields.Integer(required=True, description='Total number of animals approved'),
    'severity': fields.String(required=True, description='Severity level', enum=[s.name for s in Severity]),
    'description': fields.String(description='Description of the approval'),
    'endpoints': fields.String(description='Defined endpoints for the study')
})

ethical_approval_output = ns.model('EthicalApprovalOutput', {
    'id': fields.Integer(readonly=True),
    'title': fields.String,
    'reference_number': fields.String,
    'start_date': fields.Date,
    'end_date': fields.Date,
    'number_of_animals': fields.Integer,
    'severity': fields.String(attribute=lambda x: x.severity.name),
    'description': fields.String,
    'endpoints': fields.String
})

# --- Decorator for Admin Permissions ---
def ethical_approval_permission_required(action):
    def decorator(f):
        @token_required
        def wrapper(*args, **kwargs):
            if not user_has_permission(g.current_user, 'EthicalApproval', action):
                ns.abort(403, "You do not have permission to perform this action on Ethical Approvals.")
            return f(*args, **kwargs)
        return wrapper
    return decorator

@ns.route('/')
class EthicalApprovalList(Resource):
    decorators = [token_required, limiter.limit("100/minute")]

    @ns.doc('list_ethical_approvals')
    @ns.marshal_list_with(ethical_approval_output)
    def get(self):
        """List all accessible ethical approvals"""
        user = g.current_user
        accessible_projects = user.get_accessible_projects(include_archived=True)
        if not accessible_projects:
            return []
        
        accessible_project_ids = [p.id for p in accessible_projects]
        
        query = EthicalApproval.query.filter(
            EthicalApproval.projects.any(Project.id.in_(accessible_project_ids))
        )

        return query.order_by(EthicalApproval.start_date.desc()).all()

    @ns.doc('create_ethical_approval')
    @ns.expect(ethical_approval_input, validate=True)
    @ns.marshal_with(ethical_approval_output, code=201)
    @ethical_approval_permission_required('create')
    def post(self):
        """Create a new ethical approval"""
        data = ns.payload
        
        if EthicalApproval.query.filter_by(reference_number=data['reference_number']).first():
            ns.abort(409, f"An ethical approval with reference number '{data['reference_number']}' already exists.")

        try:
            severity_enum = Severity[data['severity'].upper()]
        except KeyError:
            ns.abort(400, f"Invalid severity value. Allowed values are: {[s.name for s in Severity]}")

        new_ea = EthicalApproval(
            title=data['title'],
            reference_number=data['reference_number'],
            start_date=data['start_date'],
            end_date=data['end_date'],
            number_of_animals=data['number_of_animals'],
            severity=severity_enum,
            description=data.get('description'),
            endpoints=data.get('endpoints')
        )
        db.session.add(new_ea)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"API: Error creating ethical approval: {e}", exc_info=True)
            ns.abort(500, "Could not create ethical approval.")
        return new_ea, 201

@ns.route('/<int:ea_id>')
class EthicalApprovalItem(Resource):
    decorators = [token_required, limiter.limit("120/minute")]

    def get_ea_or_abort(self, ea_id):
        ea = db.session.get(EthicalApproval, ea_id)
        if not ea:
            ns.abort(404, f"EthicalApproval with ID {ea_id} not found.")
        # Basic permission check: can user see any project linked to it?
        user = g.current_user
        if not user.is_super_admin:
            user_teams = user.get_teams()
            if not user_teams: ns.abort(403, "Permission denied.")
            user_team_ids = [team.id for team in user_teams]
            accessible_projects_filter = Project.team_id.in_(user_team_ids)
            if not ea.projects.filter(accessible_projects_filter).first():
                ns.abort(403, "You do not have permission to view this ethical approval.")
        return ea

    @ns.doc('get_ethical_approval')
    @ns.marshal_with(ethical_approval_output)
    def get(self, ea_id):
        """Fetch an ethical approval"""
        return self.get_ea_or_abort(ea_id)

    @ns.doc('update_ethical_approval')
    @ns.expect(ethical_approval_input, validate=True)
    @ns.marshal_with(ethical_approval_output)
    @ethical_approval_permission_required('edit')
    def put(self, ea_id):
        """Update an ethical approval"""
        ea = db.session.get(EthicalApproval, ea_id) or ns.abort(404, f"EthicalApproval with ID {ea_id} not found.")
        data = ns.payload

        if 'reference_number' in data and data['reference_number'] != ea.reference_number:
            if EthicalApproval.query.filter(EthicalApproval.id != ea_id, EthicalApproval.reference_number == data['reference_number']).first():
                ns.abort(409, f"An ethical approval with reference number '{data['reference_number']}' already exists.")
        
        ea.title = data.get('title', ea.title)
        ea.reference_number = data.get('reference_number', ea.reference_number)
        ea.start_date = data.get('start_date', ea.start_date)
        ea.end_date = data.get('end_date', ea.end_date)
        ea.number_of_animals = data.get('number_of_animals', ea.number_of_animals)
        ea.description = data.get('description', ea.description)
        ea.endpoints = data.get('endpoints', ea.endpoints)
        
        if 'severity' in data:
            try:
                ea.severity = Severity[data['severity'].upper()]
            except KeyError:
                ns.abort(400, f"Invalid severity value. Allowed values are: {[s.name for s in Severity]}")

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"API: Error updating ethical approval {ea_id}: {e}", exc_info=True)
            ns.abort(500, "Could not update ethical approval.")
        return ea

    @ns.doc('delete_ethical_approval')
    @ns.response(204, 'Ethical approval deleted')
    @ethical_approval_permission_required('delete')
    def delete(self, ea_id):
        """Delete an ethical approval"""
        ea = db.session.get(EthicalApproval, ea_id) or ns.abort(404, f"EthicalApproval with ID {ea_id} not found.")
        
        if ea.experimental_groups.first():
            ns.abort(409, "Cannot delete approval because it is linked to experimental groups. Please reassign groups first.")
        
        db.session.delete(ea)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"API: Error deleting ethical approval {ea_id}: {e}", exc_info=True)
            ns.abort(500, "Could not delete ethical approval.")
        return '', 204