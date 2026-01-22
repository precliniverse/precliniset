# app/api/sampling_api.py
from flask import g, request
from flask_restx import Resource, fields

from app.extensions import db
from app.models import (ExperimentalGroup, Sample, SampleStatus, SampleType,
                        Storage, Team)
from app.permissions import check_group_permission

from . import api
from .auth import token_required

ns = api.namespace('storage', description='Storage location operations')

storage_model = ns.model('Storage', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True),
    'team_id': fields.Integer(required=True),
    'capacity': fields.Integer,
    'location_details': fields.String
})

@ns.route('/')
class StorageList(Resource):
    decorators = [token_required]

    @ns.doc('list_storage_locations')
    @ns.marshal_list_with(storage_model)
    def get(self):
        """List accessible storage locations"""
        user = g.current_user
        if user.is_super_admin:
            return Storage.query.order_by(Storage.name).all()
        
        user_team_ids = [team.id for team in user.get_teams()]
        if not user_team_ids:
            return []
        return Storage.query.filter(Storage.team_id.in_(user_team_ids)).order_by(Storage.name).all()

    @ns.doc('create_storage_location')
    @ns.expect(storage_model)
    @ns.marshal_with(storage_model, code=201)
    def post(self):
        """Create a new storage location"""
        user = g.current_user
        data = request.get_json()
        team_id = data['team_id']
        
        team = db.session.get(Team, team_id)
        if not team or (not user.is_super_admin and not user.is_member_of(team)):
            ns.abort(403, "Permission denied: You must be a member of the team to add storage.")

        new_storage = Storage(
            name=data['name'],
            team_id=team_id,
            capacity=data.get('capacity'),
            location_details=data.get('location_details')
        )
        db.session.add(new_storage)
        db.session.commit()
        return new_storage, 201

@ns.route('/<int:storage_id>')
class StorageItem(Resource):
    decorators = [token_required]

    def get_storage(self, storage_id, permission='read'):
        storage = Storage.query.get_or_404(storage_id)
        user = g.current_user
        if not user.is_super_admin and not user.is_member_of(storage.team):
            ns.abort(403, "Permission denied.")
        
        if permission == 'edit' and not user.is_super_admin and not user.is_admin_of(storage.team):
            ns.abort(403, "Admin rights required to edit.")
            
        return storage

    @ns.doc('get_storage_location')
    @ns.marshal_with(storage_model)
    def get(self, storage_id):
        """Get a single storage location"""
        return self.get_storage(storage_id, 'read')

    @ns.doc('update_storage_location')
    @ns.expect(storage_model)
    @ns.marshal_with(storage_model)
    def put(self, storage_id):
        """Update a storage location"""
        storage = self.get_storage(storage_id, 'edit')
        data = request.get_json()
        storage.name = data.get('name', storage.name)
        storage.capacity = data.get('capacity', storage.capacity)
        storage.location_details = data.get('location_details', storage.location_details)
        db.session.commit()
        return storage

    @ns.doc('delete_storage_location')
    @ns.response(204, 'Storage deleted')
    def delete(self, storage_id):
        """Delete a storage location"""
        storage = self.get_storage(storage_id, 'edit')
        if storage.samples.first():
            ns.abort(400, "Cannot delete storage as it contains samples.")
        db.session.delete(storage)
        db.session.commit()
        return '', 204

# --- Sample Management ---
ns_samples = api.namespace('samples', description='Sample logging and management')

sample_model = ns_samples.model('Sample', {
    'id': fields.Integer(readonly=True),
    'experimental_group_id': fields.String(required=True),
    'animal_index_in_group': fields.Integer(required=True),
    'collection_date': fields.Date(required=True),
    'is_terminal': fields.Boolean,
    'status': fields.String(enum=[s.name for s in SampleStatus]),
    'notes': fields.String,
    'sample_type': fields.String(enum=[s.name for s in SampleType]),
    'storage_id': fields.Integer,
    'anticoagulant_id': fields.Integer,
    'volume': fields.Float,
    'volume_unit': fields.String,
    'organ_id': fields.Integer,
    'piece_id': fields.String,
    'collection_condition_ids': fields.List(fields.Integer),
    'parent_sample_id': fields.Integer,
    'derived_type_id': fields.Integer,
    'staining_id': fields.Integer
})

@ns_samples.route('/group/<string:group_id>')
class SampleList(Resource):
    decorators = [token_required]

    @ns_samples.doc('list_samples')
    @ns_samples.marshal_list_with(sample_model)
    def get(self, group_id):
        """List all samples for a group"""
        group = ExperimentalGroup.query.get_or_404(group_id)
        if not check_group_permission(group, 'read'):
            ns_samples.abort(403, "Permission denied.")
        return group.samples.all()

    @ns_samples.doc('log_sample')
    @ns_samples.expect(sample_model)
    @ns_samples.marshal_with(sample_model, code=201)
    def post(self, group_id):
        """Log a new sample for a group"""
        group = ExperimentalGroup.query.get_or_404(group_id)
        if not check_group_permission(group, 'edit_exp_group'):
            ns_samples.abort(403, "Permission denied.")
        
        data = request.get_json()
        new_sample = Sample(**data)
        db.session.add(new_sample)
        db.session.commit()
        return new_sample, 201
