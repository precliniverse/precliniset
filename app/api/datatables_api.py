# app/api/datatables_api.py
from flask import g, request, render_template_string, current_app, url_for
from flask_restx import Resource, fields

from app.extensions import db
from app.models import DataTable, ExperimentalGroup, ExperimentDataRow, ProtocolModel, Project
from app.permissions import (can_create_datatable_for_group,
                             check_datatable_permission,
                             check_group_permission)
from app.services.datatable_service import DataTableService

from . import api
from .auth import token_required

ns = api.namespace('groups', description='Experimental Group and DataTable operations')
server_side_ns = api.namespace('server_side_datatables', description='Server-side DataTables endpoints for DataTables')

datatable_service = DataTableService()

group_for_datatable_model = ns.model('GroupForDataTable', {
    'model_id': fields.Integer,
})

experiment_data_row_model = ns.model('ExperimentDataRow', {
    'id': fields.Integer(readonly=True),
    'data_table_id': fields.Integer(required=True),
    'animal_id': fields.Integer(required=True),
    'row_data': fields.Raw(description='JSON data for the experiment row')
})

datatable_model = ns.model('DataTable', {
    'id': fields.Integer(readonly=True),
    'protocol_id': fields.Integer(required=True),
    'group': fields.Nested(group_for_datatable_model),
    'date': fields.String(required=True, description='Date in YYYY-MM-DD format'),
    'notes': fields.String,
    'assigned_to_id': fields.Integer,
    'housing_condition_set_id': fields.Integer,
    'experiment_rows': fields.List(fields.Nested(experiment_data_row_model), description='List of data row dictionaries')
})


@ns.route('/<string:group_id>/datatables')
class DataTableList(Resource):
    decorators = [token_required]

    def get_group(self, group_id, permission='read'):
        group = db.session.get(ExperimentalGroup, group_id)
        if not group or not check_group_permission(group, permission):
            ns.abort(404, "Group not found or permission denied.")
        return group

    @ns.doc('list_datatables')
    @ns.marshal_list_with(datatable_model)
    def get(self, group_id):
        """List all datatables for a group."""
        group = self.get_group(group_id, 'read')
        return group.data_tables.all()

    @ns.doc('create_datatable')
    @ns.expect(datatable_model)
    @ns.marshal_with(datatable_model, code=201)
    def post(self, group_id):
        """Create a new datatable in a group."""
        group = self.get_group(group_id, 'edit_exp_group')
        if not can_create_datatable_for_group(group):
            ns.abort(403, "You do not have permission to create datatables in this group.")

        data = request.get_json()
        
        new_datatable = DataTable(
            group_id=group.id,
            protocol_id=data['protocol_id'],
            date=data['date'],
            notes=data.get('notes'),
            assigned_to_id=data.get('assigned_to_id'),
            housing_condition_set_id=data.get('housing_condition_set_id'),
            creator_id=g.current_user.id
        )
        db.session.add(new_datatable)
        db.session.commit()

        if 'experiment_rows' in data:
            for row_data in data['experiment_rows']:
                new_row = ExperimentDataRow(
                    data_table_id=new_datatable.id,
                    animal_id=row_data['animal_id'],
                    row_data=row_data['row_data']
                )
                db.session.add(new_row)
            db.session.commit()

        return new_datatable, 201

@ns.route('/datatables/<int:datatable_id>')
class DataTableItem(Resource):
    decorators = [token_required]

    def get_datatable(self, datatable_id, permission='read'):
        datatable = db.session.get(DataTable, datatable_id)
        if not datatable or not check_datatable_permission(datatable, permission):
            ns.abort(404, "DataTable not found or permission denied.")
        return datatable

    @ns.doc('get_datatable')
    @ns.marshal_with(datatable_model)
    def get(self, datatable_id):
        """Fetch a single datatable."""
        return self.get_datatable(datatable_id, 'read')

    @ns.doc('update_datatable')
    @ns.expect(datatable_model)
    @ns.marshal_with(datatable_model)
    def put(self, datatable_id):
        """Update a datatable."""
        datatable = self.get_datatable(datatable_id, 'edit_datatable')
        data = request.get_json()

        datatable.protocol_id = data.get('protocol_id', datatable.protocol_id)
        datatable.date = data.get('date', datatable.date)
        datatable.notes = data.get('notes', datatable.notes)
        datatable.assigned_to_id = data.get('assigned_to_id', datatable.assigned_to_id)
        datatable.housing_condition_set_id = data.get('housing_condition_set_id', datatable.housing_condition_set_id)

        if 'experiment_rows' in data:
            ExperimentDataRow.query.filter_by(data_table_id=datatable.id).delete()
            for row_data in data['experiment_rows']:
                new_row = ExperimentDataRow(
                    data_table_id=datatable.id,
                    animal_id=row_data['animal_id'],
                    row_data=row_data['row_data']
                )
                db.session.add(new_row)
            db.session.commit()

        return datatable

    @ns.doc('delete_datatable')
    @ns.response(204, 'DataTable deleted')
    def delete(self, datatable_id):
        """Delete a datatable."""
        datatable = self.get_datatable(datatable_id, 'delete_datatable')
        db.session.delete(datatable)
        db.session.commit()
        return '', 204

@server_side_ns.route('/server_side')
class ServerSideDataTableList(Resource):
    decorators = [token_required]

    def _render_datatable_actions(self, datatable, permissions):
        """
        Renders the HTML for the action buttons for a given datatable.
        
        Args:
            datatable: DataTable instance
            permissions: Pre-computed permission dict for the datatable's project
        """
        # Extract permission flags from pre-computed dict
        can_view = permissions.get('can_view_datatables', False)
        can_edit = permissions.get('can_edit_datatables', False)
        can_delete = permissions.get('can_delete_datatables', False)
        
        return render_template_string(
            """
            <div class="btn-group" role="group">
                {% if can_view %}
                <a href="{{ url_for('datatables.view_data_table', datatable_id=datatable.id) }}" class="btn btn-sm btn-info" title="View">
                    <i class="fas fa-eye"></i>
                </a>
                {% endif %}
                {% if can_edit %}
                <a href="{{ url_for('datatables.edit_data_table', id=datatable.id) }}" class="btn btn-sm btn-primary" title="Edit">
                    <i class="fas fa-edit"></i>
                </a>
                {% endif %}
                {% if can_view %}
                <a href="{{ url_for('datatables.analyze_datatable', datatable_id=datatable.id) }}" class="btn btn-sm btn-success" title="Analyze">
                    <i class="fas fa-chart-bar"></i>
                </a>
                {% endif %}
                {% if can_view %}
                <a href="{{ url_for('datatables.download_data_table', id=datatable.id) }}" class="btn btn-sm btn-secondary" title="Download">
                    <i class="fas fa-download"></i>
                </a>
                {% endif %}
                {% if can_delete %}
                <form method="POST" action="{{ url_for('datatables.delete_data_table', id=datatable.id) }}" style="display:inline;" class="confirm-delete-form">
                    <input type="hidden" name="csrf_token" value="CSRF_TOKEN_PLACEHOLDER"/>
                    <button type="submit" class="btn btn-sm btn-danger" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </form>
                {% endif %}
            </div>
            """,
            datatable=datatable,
            can_view=can_view,
            can_edit=can_edit,
            can_delete=can_delete
        )

    @server_side_ns.doc('list_server_side_datatables')
    def get(self):
        """Return a paginated and filtered list of datatables for DataTables."""
        draw = int(request.args.get('draw', 1))
        start = int(request.args.get('start', 0))
        length = int(request.args.get('length', 10))
        search_value = request.args.get('search[value]', '')

        page = (start // length) + 1
        per_page = length

        # Parse sorting
        order_column_idx = request.args.get('order[0][column]')
        order_direction = request.args.get('order[0][dir]', 'asc')
        
        sort_column_name = 'created_at' # Default
        if order_column_idx:
            # Map DataTables column index to model column name
            # This mapping needs to match the order of columns in the DataTables JS config
            column_names = ['select', 'date', 'protocol_name', 'group_name', 'project_name', 'actions']
            if int(order_column_idx) < len(column_names):
                sort_column_name = column_names[int(order_column_idx)]
        
        # Parse is_archived filter
        is_archived_param = request.args.get('is_archived')
        is_archived = None
        if is_archived_param == 'true':
            is_archived = True
        elif is_archived_param == 'false':
            is_archived = False
            
        filters = {
            'search_value': search_value,
            'group_id': request.args.get('group_id'),
            'project_id': request.args.get('project_id'), # Added project_id
            'protocol_id': request.args.get('protocol_id'),
            'date_from': request.args.get('date_from'),
            'date_to': request.args.get('date_to'),
            'is_archived': is_archived
        }

        result = datatable_service.get_server_side_datatables(
            user=g.current_user,
            filters=filters,
            page=page,
            per_page=per_page,
            sort_column=sort_column_name,
            sort_direction=order_direction
        )

        # Batch-fetch permissions for all unique projects (performance optimization)
        from app.services.permission_service import PermissionService
        perm_service = PermissionService()
        
        unique_projects = {dt.group.project for dt in result['items'] if dt.group and dt.group.project}
        project_permissions = perm_service.get_bulk_project_permissions(g.current_user, unique_projects)

        data = []
        with current_app.test_request_context(): # Required for url_for and other Flask functions.
            for dt in result['items']:
                # Get pre-computed permissions for this datatable's project
                project_id = dt.group.project.id if dt.group and dt.group.project else None
                perms = project_permissions.get(project_id, {})
                
                data.append({
                    'id': dt.id,
                    'date': dt.date, # Use date instead of name
                    'group_name': dt.group.name if dt.group else '',
                    'protocol_name': dt.protocol.name if dt.protocol else '',
                    'project_name': dt.group.project.name if dt.group and dt.group.project else '',
                    'actions': self._render_datatable_actions(dt, perms)  # Pass pre-computed permissions
                })

        return {
            "draw": draw,
            "recordsTotal": result['total_records'],
            "recordsFiltered": result['filtered_records'],
            "data": data
        }