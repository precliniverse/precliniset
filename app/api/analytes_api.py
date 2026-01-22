# app/api/analytes_api.py
from flask import g, request
from flask_restx import Resource, fields

from app.extensions import db
from app.models import Analyte, AnalyteDataType, user_has_permission

from . import api
from .auth import token_required

ns = api.namespace('analytes', description='Analyte operations')

analyte_model = ns.model('Analyte', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True, description='Analyte name'),
    'description': fields.String(description='Analyte description'),
    'unit': fields.String(description='Unit of measurement'),
    'data_type': fields.String(required=True, enum=[e.name for e in AnalyteDataType], description='Data type'),
    'allowed_values': fields.String(description='Semicolon-separated values for category type'),
    'creator_id': fields.Integer(readonly=True)
})

@ns.route('/')
class AnalyteList(Resource):
    decorators = [token_required]

    @ns.doc('list_analytes')
    @ns.marshal_list_with(analyte_model)
    def get(self):
        """List all analytes"""
        return Analyte.query.order_by(Analyte.name).all()

    @ns.doc('create_analyte')
    @ns.expect(analyte_model)
    @ns.marshal_with(analyte_model, code=201)
    def post(self):
        """Create a new analyte"""
        if not user_has_permission(g.current_user, 'Analyte', 'create'):
            ns.abort(403, "User does not have permission to create analytes.")
        
        data = request.get_json()
        
        existing_analyte = Analyte.query.filter_by(name=data['name']).first()
        if existing_analyte:
            ns.abort(409, f"An analyte with the name '{data['name']}' already exists.")

        new_analyte = Analyte(
            name=data['name'],
            description=data.get('description'),
            unit=data.get('unit'),
            data_type=AnalyteDataType[data['data_type']],
            allowed_values=data.get('allowed_values'),
            creator_id=g.current_user.id
        )
        db.session.add(new_analyte)
        db.session.commit()
        return new_analyte, 201

@ns.route('/<int:id>')
@ns.response(404, 'Analyte not found')
@ns.param('id', 'The analyte identifier')
class AnalyteItem(Resource):
    decorators = [token_required]

    @ns.doc('get_analyte')
    @ns.marshal_with(analyte_model)
    def get(self, id):
        """Fetch an analyte given its identifier"""
        return Analyte.query.get_or_404(id)

    @ns.doc('update_analyte')
    @ns.expect(analyte_model)
    @ns.marshal_with(analyte_model)
    def put(self, id):
        """Update an analyte"""
        if not user_has_permission(g.current_user, 'Analyte', 'edit'):
            ns.abort(403, "User does not have permission to update analytes.")

        analyte = Analyte.query.get_or_404(id)
        data = request.get_json()

        if 'name' in data and data['name'] != analyte.name:
            existing_analyte = Analyte.query.filter(Analyte.name == data['name'], Analyte.id != id).first()
            if existing_analyte:
                ns.abort(409, f"An analyte with the name '{data['name']}' already exists.")
            analyte.name = data['name']

        analyte.description = data.get('description', analyte.description)
        analyte.unit = data.get('unit', analyte.unit)
        if 'data_type' in data:
            analyte.data_type = AnalyteDataType[data['data_type']]
        analyte.allowed_values = data.get('allowed_values', analyte.allowed_values)
        
        db.session.commit()
        return analyte

    @ns.doc('delete_analyte')
    @ns.response(204, 'Analyte deleted')
    def delete(self, id):
        """Delete an analyte"""
        if not user_has_permission(g.current_user, 'Analyte', 'delete'):
            ns.abort(403, "User does not have permission to delete analytes.")

        analyte = Analyte.query.get_or_404(id)
        
        if analyte.animal_models.first() or analyte.protocol_associations.first():
            ns.abort(400, "Cannot delete analyte because it is in use by animal or protocol models.")

        db.session.delete(analyte)
        db.session.commit()
        return '', 204