# app/api/groups_api.py
from datetime import datetime
from flask import g, request, render_template_string, current_app, jsonify
from flask_restx import Resource, fields
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import AnimalModel, EthicalApproval, ExperimentalGroup, Project, ProjectTeamShare, ProjectUserShare, Team, User
from app.permissions import (
    can_create_group_for_project,
    check_group_permission, 
    check_project_permission,
    can_create_datatable_for_group
)
from app.services.group_service import GroupService

from . import api
from .auth import token_required
from .datatables_api import ns as groups_ns

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

group_item_model = groups_ns.model("ExperimentalGroupItem", {
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
        from sqlalchemy.orm import selectinload, joinedload
        
        query = Project.query.options(
            # Eager load groups and animals to prevent N+1
            selectinload(Project.groups).selectinload(ExperimentalGroup.animals)
        )

        if str(project_slug_or_id).isdigit():
            project = query.filter_by(id=int(project_slug_or_id)).first()
        else:
            project = query.filter_by(slug=project_slug_or_id).first()
        
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

@groups_ns.route("/<string:group_id>")
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


# ============================================================================
# RPC-style endpoints migrated from groups/routes.py
# ============================================================================

# Parser for group search query parameters
group_search_parser = groups_ns.parser()
group_search_parser.add_argument('q', type=str, help='Search term for group name', location='args')
group_search_parser.add_argument('project_id', type=str, help='Filter by project ID', location='args')
group_search_parser.add_argument('page', type=int, help='Page number (default: 1)', location='args')

group_search_result_model = groups_ns.model('GroupSearchResult', {
    'id': fields.String,
    'text': fields.String
})

group_search_response_model = groups_ns.model('GroupSearchResponse', {
    'results': fields.List(fields.Nested(group_search_result_model)),
    'total_count': fields.Integer,
    'pagination': fields.Nested(groups_ns.model('Pagination', {
        'more': fields.Boolean
    }))
})

@groups_ns.route("/search")
class GroupSearch(Resource):
    """Search experimental groups for autocompletion.
    
    Migrated from groups/routes.py search_groups_ajax.
    Returns a paginated list of groups matching the search term.
    """
    decorators = [token_required]
    
    @groups_ns.doc("search_groups")
    @groups_ns.expect(group_search_parser)
    @groups_ns.marshal_with(group_search_response_model)
    def get(self):
        """Search groups by name or project."""
        from sqlalchemy import or_
        
        args = group_search_parser.parse_args()
        search_term = args.get('q', '').strip()
        project_id = args.get('project_id')
        page = args.get('page', 1)
        per_page = 15
        
        query = ExperimentalGroup.query.join(Project)
        
        # Filter by project if provided
        if project_id and project_id != '0':
            query = query.filter(ExperimentalGroup.project_id == project_id)
            
        # Permission check: Only groups from projects accessible to the user
        accessible_projects = g.current_user.get_accessible_projects()
        project_ids = [p.id for p in accessible_projects]
        query = query.filter(ExperimentalGroup.project_id.in_(project_ids))
        query = query.options(joinedload(ExperimentalGroup.animals))
        
        # Only active groups and projects
        query = query.filter(ExperimentalGroup.is_archived == False)
        query = query.filter(Project.is_archived == False)
        
        if search_term:
            query = query.filter(
                or_(
                    ExperimentalGroup.name.ilike(f'%{search_term}%'),
                    Project.name.ilike(f'%{search_term}%'),
                    Project.slug.ilike(f'%{search_term}%')
                )
            )
        
        total_count = query.count()
        groups = query.order_by(ExperimentalGroup.name).offset((page - 1) * per_page).limit(per_page).all()
        
        results = []
        for g in groups:
            results.append({
                'id': g.id,
                'text': f"{g.name} ({g.project.name})"
            })
        
        return {
            'results': results,
            'total_count': total_count,
            'pagination': {'more': (page * per_page) < total_count}
        }


@groups_ns.route("/<string:group_id>/assignable_users")
class GroupAssignableUsers(Resource):
    """Get users who can be assigned to datatables for this group.
    
    Migrated from groups/routes.py get_assignable_users_ajax.
    Returns a list of users who have create/edit permissions for datatables.
    """
    decorators = [token_required]
    
    @api.doc("get_assignable_users")
    def get(self, group_id):
        """Get list of assignable users for a group."""
        from sqlalchemy import or_
        
        group = db.session.get(ExperimentalGroup, group_id)
        if not group:
            return {'error': 'Group not found'}, 404
            
        if not check_group_permission(group, 'read'):
            return {'error': 'Permission denied'}, 403
            
        project = group.project
        assignable_users = {}
        
        # 1. Members of the owning team
        if project.team:
            for membership in project.team.memberships:
                if membership.user:
                    assignable_users[membership.user.id] = {
                        'id': membership.user.id,
                        'email': membership.user.email
                    }
            for link in project.team.user_roles:
                if link.user:
                    assignable_users[link.user.id] = {
                        'id': link.user.id,
                        'email': link.user.email
                    }
                    
        # 2. Members of shared teams who have 'create_datatables' or 'edit_datatables' perms
        shared_permissions = ProjectTeamShare.query.filter(
            ProjectTeamShare.project_id == project.id,
            or_(
                ProjectTeamShare.can_create_datatables == True,
                ProjectTeamShare.can_edit_datatables == True
            )
        ).all()
        
        for perm in shared_permissions:
            if perm.team:
                for membership in perm.team.memberships:
                    if membership.user:
                        assignable_users[membership.user.id] = {
                            'id': membership.user.id,
                            'email': membership.user.email
                        }
                for link in perm.team.user_roles:
                    if link.user:
                        assignable_users[link.user.id] = {
                            'id': link.user.id,
                            'email': link.user.email
                        }
                        
        # 3. Direct user shares
        shared_users = ProjectUserShare.query.filter(
            ProjectUserShare.project_id == project.id,
            or_(
                ProjectUserShare.can_create_datatables == True,
                ProjectUserShare.can_edit_datatables == True
            )
        ).all()
        
        for share in shared_users:
            if share.user:
                assignable_users[share.user.id] = {
                    'id': share.user.id,
                    'email': share.user.email
                }
                
        # Sort by email
        results = sorted(assignable_users.values(), key=lambda x: x['email'])
        
        return results
