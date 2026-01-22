# app/api/core_models_api.py
from flask import g, request
from flask_restx import Resource, fields

from app.extensions import db
from app.models import (Analyte, AnimalModel, ProtocolAnalyteAssociation,
                        ProtocolModel, Severity, user_has_permission)

from . import api
from .auth import token_required

# --- Namespace for Protocols ---
ns_protocols = api.namespace('protocols', description='Protocol Model operations')

analyte_association_model = ns_protocols.model('AnalyteAssociation', {
    'analyte_id': fields.Integer(required=True),
    'default_value': fields.String,
    'is_metadata': fields.Boolean(default=False)
})

protocol_model = ns_protocols.model('Protocol', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True),
    'description': fields.String,
    'severity': fields.String(enum=[s.name for s in Severity]),
    'url': fields.String,
    'analytes': fields.List(fields.Nested(analyte_association_model))
})

# For the Import Wizard, we need analyte names
protocol_detail_model = ns_protocols.model('ProtocolDetail', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True),
    'analytes': fields.List(fields.Nested(ns_protocols.model('AnalyteInfo', {
        'id': fields.Integer(readonly=True),
        'name': fields.String(required=True)
    })))
})

@ns_protocols.route('/')
class ProtocolList(Resource):
    decorators = [token_required]

    @ns_protocols.doc('list_protocols')
    @ns_protocols.marshal_list_with(protocol_model)
    def get(self):
        """List all protocol models"""
        return ProtocolModel.query.order_by(ProtocolModel.name).all()

    @ns_protocols.doc('create_protocol')
    @ns_protocols.expect(protocol_model)
    @ns_protocols.marshal_with(protocol_model, code=201)
    def post(self):
        """Create a new protocol model"""
        if not user_has_permission(g.current_user, 'CoreModel', 'create'):
            ns_protocols.abort(403, "Permission denied.")
        
        data = request.get_json()
        new_protocol = ProtocolModel(
            name=data['name'],
            description=data.get('description'),
            severity=Severity[data.get('severity', 'NONE')],
            url=data.get('url')
        )
        db.session.add(new_protocol)
        db.session.commit()

        if 'analytes' in data:
            for assoc_data in data['analytes']:
                analyte = db.session.get(Analyte, assoc_data['analyte_id'])
                if analyte:
                    assoc = ProtocolAnalyteAssociation(
                        protocol_model_id=new_protocol.id,
                        analyte_id=analyte.id,
                        default_value=assoc_data.get('default_value'),
                        is_metadata=assoc_data.get('is_metadata', False)
                    )
                    db.session.add(assoc)
            db.session.commit()

        return new_protocol, 201

@ns_protocols.route('/<int:id>')
@ns_protocols.response(404, 'Protocol not found')
@ns_protocols.param('id', 'The protocol identifier')
class ProtocolItem(Resource):
    decorators = [token_required]

    @ns_protocols.doc('get_protocol')
    @ns_protocols.marshal_with(protocol_detail_model)
    def get(self, id):
        """Fetch a protocol model given its identifier"""
        return ProtocolModel.query.get_or_404(id)

# --- Namespace for Animal Models ---
ns_am = api.namespace('animal_models', description='Animal Model operations')

animal_model_input = ns_am.model('AnimalModelInput', {
    'name': fields.String(required=True),
    'analyte_ids': fields.List(fields.Integer, description='List of analyte IDs to associate')
})

animal_model_output = ns_am.model('AnimalModelOutput', {
    'id': fields.Integer(readonly=True),
    'name': fields.String,
    'analytes': fields.List(fields.Nested(api.models['Analyte'])) # Reusing analyte model from other namespace
})


@ns_am.route('/<int:id>')
@ns_am.response(404, 'Animal Model not found')
@ns_am.param('id', 'The animal model identifier')
class AnimalModelItem(Resource):
    decorators = [token_required]

    @ns_am.doc('get_animal_model')
    @ns_am.marshal_with(animal_model_output)
    def get(self, id):
        """Fetch an animal model given its identifier"""
        return AnimalModel.query.get_or_404(id)


@ns_am.route('/')
class AnimalModelList(Resource):
    decorators = [token_required]

    @ns_am.doc('list_animal_models')
    @ns_am.marshal_list_with(animal_model_output)
    def get(self):
        """List all animal models"""
        return AnimalModel.query.order_by(AnimalModel.name).all()

    @ns_am.doc('create_animal_model')
    @ns_am.expect(animal_model_input)
    @ns_am.marshal_with(animal_model_output, code=201)
    def post(self):
        """Create a new animal model"""
        if not user_has_permission(g.current_user, 'CoreModel', 'create'):
            ns_am.abort(403, "Permission denied.")
        
        data = request.get_json()
        new_model = AnimalModel(name=data['name'])
        
        if 'analyte_ids' in data:
            analytes = Analyte.query.filter(Analyte.id.in_(data['analyte_ids'])).all()
            new_model.analytes.extend(analytes)
            
        db.session.add(new_model)
        db.session.commit()
        return new_model, 201