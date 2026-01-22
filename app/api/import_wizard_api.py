# app/api/import_wizard_api.py
import os
from flask import request, g, current_app
from flask_restx import Resource, fields
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import DataTable, ProtocolModel, ImportTemplate
from app.services.import_wizard_service import ImportWizardService
from . import api
from .auth import token_required

ns = api.namespace('import_wizard', description='Import Wizard operations')

import_wizard_service = ImportWizardService()

# Models for API documentation
mapping_field = ns.model('Mapping', {
    'file_column': fields.String(required=True),
    'analyte_id': fields.Integer(required=True)
})

import_request = ns.model('ImportRequest', {
    'data_table_id': fields.Integer(required=True),
    'mapping': fields.Raw(required=True),
    'animal_id_column': fields.String(required=True),
    'file_path': fields.String(required=True),
    'skip_rows': fields.Integer(default=0),
    'anchor_text': fields.String(nullable=True),
    'anchor_offset': fields.Integer(default=0),
    'row_interval': fields.Integer(default=1),
    'advanced_logic': fields.Raw(nullable=True),
    'pipeline_id': fields.Integer(nullable=True)
})

template_model = ns.model('ImportTemplate', {
    'id': fields.Integer(readonly=True),
    'name': fields.String(required=True),
    'protocol_model_id': fields.Integer(required=True),
    'mapping_json': fields.Raw(required=True),
    'skip_rows': fields.Integer(default=0),
    'anchor_text': fields.String(nullable=True),
    'anchor_offset': fields.Integer(default=0),
    'row_interval': fields.Integer(default=1),
    'advanced_logic': fields.Raw(nullable=True)
})

@ns.route('/parse')
class FileParse(Resource):
    decorators = [token_required]

    def post(self):
        """Upload and parse a file for preview."""
        if 'file' not in request.files:
            ns.abort(400, "No file part")
        
        file = request.files['file']
        if file.filename == '':
            ns.abort(400, "No selected file")

        pipeline_id = request.form.get('pipeline_id', type=int)
        skip_rows = request.form.get('skip_rows', 0, type=int)
        anchor_text = request.form.get('anchor_text')
        anchor_offset = request.form.get('anchor_offset', 0, type=int)
        row_interval = request.form.get('row_interval', 1, type=int)

        filename = secure_filename(file.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)

        try:
            if pipeline_id:
                from app.services.import_pipeline_service import ImportPipelineService
                pipeline_service = ImportPipelineService()
                parsed_data = pipeline_service.execute_pipeline(pipeline_id, file_path)
                
                if not parsed_data:
                    return {'headers': [], 'preview': [], 'file_path': file_path, 'total_rows': 0}
                
                headers = list(parsed_data[0].keys())
                preview = parsed_data[:10]
                return {
                    'headers': headers,
                    'preview': preview,
                    'total_rows': len(parsed_data),
                    'file_path': file_path
                }
            else:
                result = import_wizard_service.parse_file(
                    file_path, 
                    skip_rows=skip_rows, 
                    anchor_text=anchor_text,
                    anchor_offset=anchor_offset,
                    row_interval=row_interval
                )
                result['file_path'] = file_path # Return path for subsequent steps
                return result
        except Exception as e:
            ns.abort(500, str(e))

@ns.route('/validate_animals')
class ValidateAnimals(Resource):
    decorators = [token_required]

    def post(self):
        """Validate animal IDs in the file."""
        data = request.get_json()
        file_path = data.get('file_path')
        group_id = data.get('group_id')
        animal_id_column = data.get('animal_id_column')

        pipeline_id = data.get('pipeline_id')

        if not all([file_path, group_id, animal_id_column]):
            ns.abort(400, "Missing required parameters")

        try:
            result = import_wizard_service.validate_animal_ids(file_path, group_id, animal_id_column, pipeline_id=pipeline_id)
            return result
        except Exception as e:
            ns.abort(500, str(e))

@ns.route('/import')
class ProcessImport(Resource):
    decorators = [token_required]

    @ns.expect(import_request)
    def post(self):
        """Finalize the import process."""
        data = request.get_json()
        try:
            count = import_wizard_service.process_import(
                file_path=data['file_path'],
                data_table_id=data['data_table_id'],
                mapping=data['mapping'],
                animal_id_column=data['animal_id_column'],
                user_id=g.current_user.id,
                skip_rows=data.get('skip_rows', 0),
                anchor_text=data.get('anchor_text'),
                anchor_offset=data.get('anchor_offset', 0),
                row_interval=data.get('row_interval', 1),
                advanced_logic=data.get('advanced_logic'),
                pipeline_id=data.get('pipeline_id')
            )
            return {'message': f'Successfully imported {count} rows', 'count': count}
        except Exception as e:
            ns.abort(500, str(e))

@ns.route('/templates/<int:protocol_model_id>')
class TemplateList(Resource):
    decorators = [token_required]

    @ns.marshal_list_with(template_model)
    def get(self, protocol_model_id):
        """Get templates for a protocol model."""
        return import_wizard_service.get_templates(protocol_model_id)

    @ns.expect(template_model)
    def post(self, protocol_model_id):
        """Save a new template."""
        data = request.get_json()
        template = import_wizard_service.save_template(
            name=data['name'],
            protocol_model_id=protocol_model_id,
            mapping=data['mapping_json'],
            skip_rows=data.get('skip_rows', 0),
            anchor_text=data.get('anchor_text'),
            anchor_offset=data.get('anchor_offset', 0),
            row_interval=data.get('row_interval', 1),
            advanced_logic=data.get('advanced_logic')
        )
        return {'message': 'Template saved', 'id': template.id}, 201

@ns.route('/pipelines/<int:protocol_id>')
class PipelineList(Resource):
    decorators = [token_required]

    def get(self, protocol_id):
        """Get pipelines for a protocol model."""
        protocol = db.session.get(ProtocolModel, protocol_id)
        if not protocol:
            ns.abort(404, "Protocol not found")
        
        return [{'id': p.id, 'name': p.name, 'description': p.description} for p in protocol.import_pipelines]

@ns.route('/templates/<int:template_id>/export')
class TemplateExport(Resource):
    decorators = [token_required]

    def get(self, template_id):
        """Export a template as JSON."""
        try:
            return import_wizard_service.export_template(template_id)
        except Exception as e:
            ns.abort(500, str(e))

@ns.route('/templates/import/<int:protocol_model_id>')
class TemplateImport(Resource):
    decorators = [token_required]

    def post(self, protocol_model_id):
        """Import a template from JSON."""
        data = request.get_json()
        try:
            template = import_wizard_service.import_template(data, protocol_model_id)
            return {'message': 'Template imported', 'id': template.id}, 201
        except Exception as e:
            ns.abort(500, str(e))
