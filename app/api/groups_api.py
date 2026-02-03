# app/api/groups_api.py
from flask import g, request, render_template_string, current_app, url_for
from flask_restx import Resource, fields
import json

from app.extensions import db
from app.models import AnimalModel, EthicalApproval, ExperimentalGroup, Project, Team
from app.permissions import (
    can_create_group_for_project,
    check_group_permission, 
    check_project_permission,
    can_create_datatable_for_group
)
from app.services.group_service import GroupService

from . import api
from .auth import token_required

# This namespace is for group operations WITHIN a project context
ns = api.namespace("projects", description="Project related operations")
server_side_ns = api.namespace("server_side_groups", description="Server-side DataTables endpoints for Groups")

group_service = GroupService()

group_model = ns.model("ExperimentalGroupInput", {
    "name": fields.String(required=True),
    "model_id": fields.Integer(required=True),
    "ethical_approval_id": fields.Integer(),
    "animal_data": fields.List(fields.Raw, description="List of animal dictionaries")
})

group_output_model = ns.model("ExperimentalGroupOutput", {
    "id": fields.String(readonly=True),
    "name": fields.String(required=True),
    "model_id": fields.Integer(required=True),
    "ethical_approval_id": fields.Integer(),
    "animal_data": fields.List(fields.Raw, description="List of animal dictionaries")
})

group_item_model = api.namespace("groups").model("ExperimentalGroupItem", {
    "id": fields.String(readonly=True),
    "name": fields.String(required=True),
    "model_id": fields.Integer(required=True),
    "ethical_approval_id": fields.Integer(),
    "animal_data": fields.List(fields.Raw, description="List of animal dictionaries")
})


@ns.route("/<string:project_slug_or_id>/groups")
class GroupList(Resource):
    decorators = [token_required]

    def get_project(self, project_slug_or_id, permission="read"):
        project = None
        if str(project_slug_or_id).isdigit():
            project = db.session.get(Project, int(project_slug_or_id))
        if not project:
            project = Project.query.filter_by(slug=project_slug_or_id).first()
        
        if not project or not check_project_permission(project, permission):
            ns.abort(404, "Project not found or permission denied.")
        return project

    @ns.marshal_list_with(group_output_model)
    def get(self, project_slug_or_id):
        """List all experimental groups for a project."""
        project = self.get_project(project_slug_or_id, "read")
        groups = []
        for group in project.groups:
            g_dict = {
                "id": group.id,
                "name": group.name,
                "model_id": group.model_id,
                "ethical_approval_id": group.ethical_approval_id,
                "animal_data": [a.to_dict() for a in group.animals]
            }
            groups.append(g_dict)
        return groups

    @ns.marshal_with(group_output_model, code=201)
    def post(self, project_slug_or_id):
        """Create a new experimental group in a project."""
        project = self.get_project(project_slug_or_id, "edit")
        if not can_create_group_for_project(project):
            ns.abort(403, "You do not have permission to create groups in this project.")

        data = request.get_json()
        
        group_count = ExperimentalGroup.query.filter_by(project_id=project.id).count()
        new_group_id = f"{project.slug}-G{group_count + 1}"
        while db.session.get(ExperimentalGroup, new_group_id):
            group_count += 1
            new_group_id = f"{project.slug}-G{group_count + 1}"

        new_group = group_service.create_group(
            id=new_group_id,
            name=data["name"],
            project_id=project.id,
            model_id=data["model_id"],
            ethical_approval_id=data.get("ethical_approval_id"),
            animal_data=data.get("animal_data", []),
            owner_id=g.current_user.id,
            team_id=project.team_id
        )
        
        return {
            "id": new_group.id,
            "name": new_group.name,
            "model_id": new_group.model_id,
            "ethical_approval_id": new_group.ethical_approval_id,
            "animal_data": [a.to_dict() for a in new_group.animals]
        }, 201

@api.namespace("groups").route("/<string:group_id>")
class GroupItem(Resource):
    decorators = [token_required]

    def get_group(self, group_id, permission="read"):
        group = db.session.get(ExperimentalGroup, group_id)
        if not group or not check_group_permission(group, permission):
            api.abort(404, "Group not found or permission denied.")
        return group

    @api.marshal_with(group_item_model)
    def get(self, group_id):
        """Fetch a single experimental group."""
        group = self.get_group(group_id, "read")
        return {
            "id": group.id,
            "name": group.name,
            "model_id": group.model_id,
            "ethical_approval_id": group.ethical_approval_id,
            "animal_data": [a.to_dict() for a in group.animals]
        }

    @api.marshal_with(group_item_model)
    def put(self, group_id):
        """Update an experimental group."""
        group = self.get_group(group_id, "edit_exp_group")
        data = request.get_json()

        group_service.update_group_details(
            group,
            name=data.get("name", group.name),
            model_id=data.get("model_id", group.model_id),
            ethical_approval_id=data.get("ethical_approval_id", group.ethical_approval_id)
        )
        
        if "animal_data" in data:
            group_service.save_group_data(group, data["animal_data"], update_datatables=True)
        else:
            db.session.commit()
            
        return {
            "id": group.id,
            "name": group.name,
            "model_id": group.model_id,
            "ethical_approval_id": group.ethical_approval_id,
            "animal_data": [a.to_dict() for a in group.animals]
        }

    @api.doc("delete_group")
    @api.response(204, "Group deleted")
    def delete(self, group_id):
        """Delete an experimental group."""
        group = self.get_group(group_id, "delete_exp_group")
        
        if group.data_tables.first():
            api.abort(400, "Cannot delete group because it has associated data tables.")

        db.session.delete(group)
        db.session.commit()
        return "", 204

@server_side_ns.route("/server_side")
class ServerSideGroupList(Resource):
    decorators = [token_required]

    def _render_group_actions(self, group, permissions):
        """
        Renders the HTML for the action buttons for a given group.
        
        Args:
            group: ExperimentalGroup instance
            permissions: Pre-computed permission dict for the group's project
        """
        import json
        
        # Serialize model fields for the data attribute
        if group.model and group.model.analytes:
            fields_list = [{'name': a.name} for a in group.model.analytes]
        else:
            fields_list = []

        # Extract permission flags from pre-computed dict
        can_edit = permissions.get('can_edit_exp_groups', False)
        can_view = permissions.get('can_view_exp_groups', False)
        can_archive = permissions.get('can_delete_exp_groups', False)
        can_create_dt = permissions.get('can_create_datatables', False)

        return render_template_string(
            """
            <div class="btn-group" role="group">
                {% if can_edit %}
                <a href="{{ url_for('groups.edit_group', id=group.id) }}" class="btn btn-sm btn-primary" title="Edit">
                    <i class="fas fa-edit"></i>
                </a>
                {% endif %}
                {% if can_create_dt %}
                <a href="{{ url_for('datatables.create_data_table', group_id_prefill=group.id) }}" class="btn btn-sm btn-success" title="Create Data Table">
                    <i class="fas fa-plus"></i>
                </a>
                {% endif %}
                {% if can_view %}
                <a href="{{ url_for('datatables.list_group_datatables', group_id=group.id) }}" class="btn btn-sm btn-info" title="View DataTables">
                    <i class="fas fa-table"></i>
                </a>
                {% endif %}
                {% if can_edit %}
                <a href="{{ url_for('sampling.log_batch_samples_for_group', group_id=group.id) }}" class="btn btn-sm btn-success" title="Log Samples">
                    <i class="fas fa-vials"></i>
                </a>
                {% endif %}

                {# Declare Death Button #}
                {% if can_edit %}
                <button type="button" class="btn btn-sm btn-dark declare-dead-btn"
                        data-group-id="{{ group.id }}"
                        data-group-name="{{ group.name }}"
                        data-model-fields='{{ fields_list|tojson }}'
                        data-default-euthanasia-reason="{{ group.default_euthanasia_reason or '' }}"
                        data-default-severity="{{ group.default_severity or '' }}"
                        title="Declare Death">
                    <i class="fas fa-skull-crossbones"></i>
                </button>
                {% endif %}

                {% if can_archive %}
                <button type="button" class="btn btn-sm btn-warning archive-group-btn" data-group-id="{{ group.id }}" title="Archive">
                    <i class="fas fa-archive"></i>
                </button>
                {% endif %}
            </div>
            """,
            group=group,
            can_edit=can_edit,
            can_view=can_view,
            can_archive=can_archive,
            can_create_dt=can_create_dt,
            fields_list=fields_list
        )

    @server_side_ns.doc("list_server_side_groups")
    def get(self):
        """Return a paginated and filtered list of experimental groups for DataTables."""
        draw = int(request.args.get("draw", 1))
        start = int(request.args.get("start", 0))
        length = int(request.args.get("length", 10))
        search_value = request.args.get("search[value]", "")

        page = (start // length) + 1
        per_page = length

        # Parse sorting
        order_column_idx = request.args.get("order[0][column]")
        order_direction = request.args.get("order[0][dir]", "asc")
        
        sort_column_name = "created_at" # Default
        if order_column_idx:
            # Map DataTables column index to model column name
            # This mapping needs to match the order of columns in the DataTables JS config
            column_names = ["select", "name", "project_name", "team_name", "model_name", "animal_count", "is_archived", "actions"]
            if int(order_column_idx) < len(column_names):
                sort_column_name = column_names[int(order_column_idx)]
            
            # Adjust sort column name for service
            if sort_column_name == "project_name":
                sort_column_name = "project_name" 
            elif sort_column_name == "team_name":
                sort_column_name = "team_name" 
            elif sort_column_name == "model_name":
                sort_column_name = "model_name" 
            elif sort_column_name == "animal_count":
                # Sorting by JSON array length in SQL is complex/db-specific. 
                # Fallback to created_at or handle in service if critical.
                sort_column_name = "created_at" 

        # Parse is_archived filter
        is_archived_param = request.args.get("is_archived")
        is_archived = None
        
        if is_archived_param == "true":
            is_archived = True
        elif is_archived_param == "false":
            is_archived = False
        elif is_archived_param == "all":
            is_archived = "all"

        filters = {
            "search_value": search_value,
            "project_id": request.args.get("project_id"), 
            "team_id": request.args.get("team_id"),       
            "model_id": request.args.get("model_id"),     
            "is_archived": is_archived
        }

        result = group_service.get_server_side_groups(
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
        
        unique_projects = {group.project for group in result["items"] if group.project}
        project_permissions = perm_service.get_bulk_project_permissions(g.current_user, unique_projects)

        data = []
        with current_app.test_request_context(): # Required for url_for to work outside of a request context
            for group in result["items"]:
                # Get pre-computed permissions for this group's project
                perms = project_permissions.get(group.project_id, {})
                
                # Calculate animal counts and serialize for tooltip
                animals_list = [a.to_dict() for a in group.animals]
                total_animals = len(animals_list)
                alive_animals = 0
                dead_animals = 0
                euthanasia_summary = {}
                
                for a in animals_list:
                    if a.get("status") == "dead":
                        dead_animals += 1
                        reason = a.get("euthanasia_reason", "Unknown")
                        sev = a.get("severity", "Unknown")
                        key = f"{reason} - {sev}"
                        euthanasia_summary[key] = euthanasia_summary.get(key, 0) + 1
                    else:
                        alive_animals += 1

                animal_count_display = f"{alive_animals} / {total_animals}"

                # Create tooltip content for dead animals
                tooltip_content = ""
                if dead_animals > 0:
                    tooltip_parts = [f"Dead animals ({dead_animals}):"]
                    for a in animals_list:
                        if a.get("status") == "dead":
                            reason = a.get("euthanasia_reason", "Unknown reason")
                            animal_id = a.get("uid", "Unknown ID")
                            tooltip_parts.append(f"• {animal_id}: {reason}")

                    # Join with actual HTML line breaks
                    tooltip_content = "<br>".join(tooltip_parts)

                # Add data attributes for frontend styling and tooltips
                data_class = "text-danger" if dead_animals > 0 else ""
                data_tooltip = f'data-bs-toggle="tooltip" data-bs-html="true" title="{tooltip_content}"' if dead_animals > 0 else ''
                animal_count_display = f'<span class="animal-count {data_class}" {data_tooltip}>{animal_count_display}</span>'

                data.append({
                    "id": group.id,
                    "name": group.name,
                    "project_name": group.project.name if group.project else "",
                    "team_name": group.team.name if group.team else "",
                    "model_name": group.model.name if group.model else "N/A",
                    "animal_count": animal_count_display,
                    "created_at": group.created_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(group, "created_at", None) else "",
                    "updated_at": group.updated_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(group, "updated_at", None) else "",
                    "is_archived": group.is_archived,
                    "actions": self._render_group_actions(group, perms)  # Pass pre-computed permissions
                })

        return {
            "draw": draw,
            "recordsTotal": result["total_records"],
            "recordsFiltered": result["filtered_records"],
            "data": data
        }
