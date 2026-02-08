# app/services/project_service.py
import os
from datetime import datetime

from flask import current_app
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import (Attachment, DataTable, ExperimentalGroup,
                        ExperimentDataRow, Partner, Project,
                        ProjectEthicalApprovalAssociation,
                        ProjectPartnerAssociation, Team, User, Workplan,
                        WorkplanEvent, WorkplanVersion)
from app.services.base import BaseService
from app.utils.files import validate_file_type  # Import utility


class ProjectService(BaseService):
    model = Project

    def get_by_slug(self, slug):
        return self.model.query.filter_by(slug=slug).first()

    def get_next_slug(self):
        max_slug_num = db.session.query(func.max(func.substr(Project.slug, 2).cast(db.Integer)))\
            .filter(Project.slug.like('P%'))\
            .scalar()

        if max_slug_num is not None:
            next_num = max_slug_num + 1
        else:
            next_num = 1
            
        potential_slug = f"P{next_num:04d}"
        while Project.query.filter_by(slug=potential_slug).first() is not None:
            next_num += 1
            potential_slug = f"P{next_num:04d}"
            
        return potential_slug

    def create_project(self, name, team_id, owner_id, description=None):
        project = self.create(
            name=name,
            team_id=team_id,
            owner_id=owner_id,
            description=description,
            slug=self.get_next_slug()
        )
        return project

    def update_project(self, project, **kwargs):
        if 'updated_at' not in kwargs:
            kwargs['updated_at'] = datetime.now(current_app.config['UTC_TZ'])
        return self.update(project, **kwargs)

    def search_projects(self, user, search_term=None, show_archived=False, page=1, per_page=10):
        """
        Search for projects accessible to the user, including:
        - Projects owned by teams the user is a member of
        - Projects shared with the user's teams (ProjectTeamShare)
        - Projects shared directly with the user (ProjectUserShare)
        """
        from sqlalchemy import or_
        from app.models import ProjectTeamShare, ProjectUserShare
        
        # For super admin, return all projects
        if user.is_super_admin:
            base_query = self.model.query
            
            if not show_archived:
                base_query = base_query.filter(self.model.is_archived == False)
            
            if search_term:
                search_pattern = f"%{search_term}%"
                base_query = base_query.filter(
                    or_(
                        self.model.name.ilike(search_pattern),
                        self.model.description.ilike(search_pattern),
                        self.model.slug.ilike(search_pattern)
                    )
                )
            
            pagination = base_query.order_by(self.model.name).paginate(page=page, per_page=per_page, error_out=False)
            return pagination.items, pagination.total
        
        # For regular users, get accessible projects
        user_teams = user.get_teams()
        team_ids = [team.id for team in user_teams]
        
        # Build subqueries for accessible project IDs
        # 1. Projects owned by user's teams (with Project:read permission)
        from app.models import UserTeamRoleLink, Role, role_permissions, Permission
        
        has_permission_for_project_team = db.session.query(db.literal(1)).select_from(UserTeamRoleLink).join(Role).join(role_permissions).join(Permission).filter(
            UserTeamRoleLink.user_id == user.id,
            Permission.resource == 'Project',
            Permission.action == 'read',
            UserTeamRoleLink.team_id == Project.team_id,
            or_(Role.team_id == Project.team_id, Role.team_id.is_(None))
        ).exists()
        
        owned_project_ids_q = db.session.query(Project.id).filter(has_permission_for_project_team)
        
        # 2. Projects shared with user's teams
        team_shared_project_ids_q = db.session.query(ProjectTeamShare.project_id).filter(
            ProjectTeamShare.team_id.in_(team_ids) if team_ids else False,
            ProjectTeamShare.can_view_project == True
        )
        
        # 3. Projects shared directly with user
        user_shared_project_ids_q = db.session.query(ProjectUserShare.project_id).filter(
            ProjectUserShare.user_id == user.id,
            ProjectUserShare.can_view_project == True
        )
        
        # Union all accessible project IDs
        accessible_project_ids_q = owned_project_ids_q.union(team_shared_project_ids_q).union(user_shared_project_ids_q)
        
        # Build the main query
        base_query = self.model.query.filter(self.model.id.in_(accessible_project_ids_q))
        
        if not show_archived:
            base_query = base_query.filter(self.model.is_archived == False)
        
        if search_term:
            search_pattern = f"%{search_term}%"
            base_query = base_query.filter(
                or_(
                    self.model.name.ilike(search_pattern),
                    self.model.description.ilike(search_pattern),
                    self.model.slug.ilike(search_pattern)
                )
            )
        
        # Execute query with pagination
        # Use flask-sqlalchemy's paginate for cleaner logic
        pagination = base_query.order_by(self.model.name).paginate(page=page, per_page=per_page, error_out=False)
        return pagination.items, pagination.total

    def update_ethical_approvals(self, project, new_approval_ids):
        current_ids = {assoc.ethical_approval_id for assoc in project.ethical_approval_associations}
        new_ids = set(new_approval_ids)

        to_add = new_ids - current_ids
        to_remove = current_ids - new_ids

        for ea_id in to_add:
            assoc = ProjectEthicalApprovalAssociation(project_id=project.id, ethical_approval_id=ea_id)
            db.session.add(assoc)

        for ea_id in to_remove:
            assoc = ProjectEthicalApprovalAssociation.query.filter_by(
                project_id=project.id,
                ethical_approval_id=ea_id
            ).first()
            if assoc:
                db.session.delete(assoc)
        
        project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        db.session.commit()

    def unlink_ethical_approval(self, project, ea_id):
        association = ProjectEthicalApprovalAssociation.query.filter_by(
            project_id=project.id,
            ethical_approval_id=ea_id
        ).first()
        
        if association:
            # Check for dependent Experimental Groups
            dependent_groups = ExperimentalGroup.query.filter_by(
                project_id=project.id,
                ethical_approval_id=ea_id
            ).all()

            if dependent_groups:
                group_names = ", ".join([g.name for g in dependent_groups])
                raise ValueError(f"Cannot unlink Ethical Approval (ID: {ea_id}) from project '{project.name}' because the following experimental groups are still linked to it: {group_names}. Please reassign or unlink them first.")

            db.session.delete(association)
            project.updated_at = datetime.now(current_app.config['UTC_TZ'])
            db.session.commit()
            return True
        return False

    def link_partner(self, project, form):
        partner_to_link = None
        
        if form.existing_partner.data:
            partner_to_link = db.session.get(Partner, form.existing_partner.data)
            if not partner_to_link:
                return False, "Selected partner not found.", "danger"
        
        elif form.new_company_name.data and form.new_contact_email.data:
            existing_partner = Partner.query.filter_by(contact_email=form.new_contact_email.data).first()
            if existing_partner:
                partner_to_link = existing_partner
                msg = f"A partner with email {existing_partner.contact_email} already exists. Linking existing partner."
                category = "info"
            else:
                partner_to_link = Partner(
                    company_name=form.new_company_name.data,
                    contact_email=form.new_contact_email.data
                )
                db.session.add(partner_to_link)
                db.session.flush()
                msg = f"New partner \"{partner_to_link.company_name}\" created."
                category = "success"
        
        if partner_to_link:
            existing_association = ProjectPartnerAssociation.query.filter_by(
                project_id=project.id, partner_id=partner_to_link.id
            ).first()
            
            if not existing_association:
                association = ProjectPartnerAssociation(project_id=project.id, partner_id=partner_to_link.id)
                db.session.add(association)
                project.updated_at = datetime.now(current_app.config['UTC_TZ'])
                db.session.commit()
                return True, f"Partner \"{partner_to_link.company_name}\" linked successfully.", "success"
            else:
                return False, f"Partner \"{partner_to_link.company_name}\" is already linked to this project.", "info"
        
        return False, "No valid partner data provided.", "danger"

    def unlink_partner(self, project, partner_id):
        association = ProjectPartnerAssociation.query.filter_by(
            project_id=project.id, partner_id=partner_id
        ).first()
        
        if association:
            partner_name = association.partner.company_name
            db.session.delete(association)
            project.updated_at = datetime.now(current_app.config['UTC_TZ'])
            db.session.commit()
            return True, partner_name
        return False, None

    def archive_project(self, project, cascade_groups=False):
        project.is_archived = True
        project.archived_at = datetime.now(current_app.config['UTC_TZ'])
        
        archived_groups_count = 0
        if cascade_groups:
            for group in project.groups:
                if not group.is_archived:
                    group.is_archived = True
                    group.archived_at = datetime.now(current_app.config['UTC_TZ'])
                    archived_groups_count += 1
        
        db.session.commit()
        return archived_groups_count

    def unarchive_project(self, project):
        project.is_archived = False
        project.archived_at = None
        project.updated_at = datetime.now(current_app.config['UTC_TZ'])

        unarchived_groups_count = 0
        groups_to_unarchive = [g for g in project.groups if g.is_archived]
        for group in groups_to_unarchive:
            group.is_archived = False
            group.archived_at = None
            unarchived_groups_count += 1
        
        db.session.commit()
        return unarchived_groups_count

    def delete_project_fully(self, project):
        upload_folder_base = current_app.config.get('UPLOAD_FOLDER')
        if upload_folder_base:
            for attachment in project.attachments:
                try:
                    filepath_to_delete = os.path.join(upload_folder_base, attachment.filepath)
                    if os.path.exists(filepath_to_delete):
                        os.remove(filepath_to_delete)
                except OSError as e:
                    current_app.logger.error(f"Error deleting attachment file {attachment.filepath}: {e}")
        
        db.session.delete(project)
        db.session.commit()

    def save_attachment(self, file, project, description=None):
        if not file:
            return None
            
        filename = secure_filename(file.filename)
        if not filename:
            return None

        # Use utility for validation
        validate_file_type(file)

        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'projects', project.slug)
        os.makedirs(upload_folder, exist_ok=True)
        
        filepath = os.path.join(upload_folder, filename)
        counter = 1
        original_filepath = filepath
        while os.path.exists(filepath):
            name, ext = os.path.splitext(original_filepath)
            filepath = f"{name}_{counter}{ext}"
            counter += 1
            
        file.save(filepath)
        relative_filepath = os.path.join('projects', project.slug, os.path.basename(filepath))
        
        attachment = Attachment(
            project_id=project.id,
            filename=os.path.basename(filepath),
            filepath=relative_filepath,
            description=description,
            size=os.path.getsize(filepath)
        )
        db.session.add(attachment)
        project.updated_at = datetime.now(current_app.config['UTC_TZ'])
        db.session.commit()
        return attachment

    def get_sidebar_hierarchy(self, user, max_projects_per_team=50):
        """
        Returns a list of dicts: [{'id': team_id, 'name': team_name, 'projects': [project_objs]}]
        
        OPTIMIZED: Limits projects per team to prevent memory issues with large datasets.
        Uses a direct query with eager loading instead of loading all projects.
        """
        from collections import defaultdict
        from sqlalchemy.orm import joinedload
        
        # For super admin, use a more efficient query
        if user.is_super_admin:
            # Get teams with project counts, ordered by name
            teams_with_projects_info = db.session.query(Team, func.count(Project.id).label('project_count'))\
                .outerjoin(Project, (Project.team_id == Team.id) & (Project.is_archived == False))\
                .group_by(Team.id)\
                .order_by(Team.name)\
                .limit(50)\
                .all()
            
            if not teams_with_projects_info:
                return []
                
            team_ids = [t[0].id for t in teams_with_projects_info]
            
            # Batch Get projects for these teams
            # We fetch all (since max 50 per team * 50 teams = 2500, which is manageable)
            # and slice in Python to implement the 'per team' limit precisely.
            projects_query = Project.query\
                .filter(Project.team_id.in_(team_ids), Project.is_archived == False)\
                .order_by(Project.team_id, Project.updated_at.desc())\
                .all()
            
            projects_by_team = defaultdict(list)
            for p in projects_query:
                if len(projects_by_team[p.team_id]) < max_projects_per_team:
                    projects_by_team[p.team_id].append(p)
            
            hierarchy = []
            for team, count in teams_with_projects_info:
                hierarchy.append({
                    'id': team.id,
                    'name': team.name,
                    'projects': projects_by_team[team.id],
                    'total_count': count,
                    'has_more': count > max_projects_per_team
                })
            return hierarchy
        
        # For regular users, get their team memberships first
        user_teams = user.get_teams()
        if not user_teams:
            return []
        
        user_team_ids = [t.id for t in user_teams]
        
        # Get projects user owns (in their teams) - limited
        from app.models import ProjectTeamShare, ProjectUserShare
        
        hierarchy = []
        teams_map = defaultdict(lambda: {'projects': [], 'total_count': 0})
        
        # 1. Get owned projects (from user's teams) with limit per team
        
        # 1. Get owned projects (Optimized: Batch Query)
        # A. Get Counts
        owned_counts = db.session.query(Project.team_id, func.count(Project.id))\
             .filter(
                 Project.team_id.in_(user_team_ids),
                 Project.is_archived == False
             )\
             .group_by(Project.team_id).all()
        counts_map = {tid: count for tid, count in owned_counts}

        # B. Get Projects (Fetch all active, then slice in Python)
        # Assuming active count is reasonable (e.g. < 2000 globally for user).
        # We rely on is_archived + updated_at index for speed.
        all_owned_projects = Project.query\
            .filter(
                Project.team_id.in_(user_team_ids),
                Project.is_archived == False
            )\
            .order_by(Project.updated_at.desc())\
            .all()
            
        for project in all_owned_projects:
            # We need the team object. Project.team should be joinedloaded or accessible.
            # Project model usually has 'team' relationship. 
            # In original code: 'team' loop var was used. Here we access project.team.
            # To avoid N+1 on project.team access, we should options(joinedload(Project.team)).
            # Or iterate user_teams to link.
            # Creating the entry:
             if project.team_id not in teams_map:
                 # Find the team object from user_teams list to avoid DB hit
                 team_obj = next((t for t in user_teams if t.id == project.team_id), None)
                 if team_obj:
                     teams_map[project.team_id] = {
                         'team': team_obj,
                         'projects': [],
                         'total_count': counts_map.get(project.team_id, 0)
                     }
             
             if project.team_id in teams_map:
                 if len(teams_map[project.team_id]['projects']) < max_projects_per_team:
                     teams_map[project.team_id]['projects'].append(project)
        
        # 2. Get shared projects (via team shares) - limited
        team_shared_project_ids = db.session.query(ProjectTeamShare.project_id)\
            .filter(
                ProjectTeamShare.team_id.in_(user_team_ids),
                ProjectTeamShare.can_view_project == True
            )\
            .limit(max_projects_per_team * 5)\
            .all()
        
        if team_shared_project_ids:
            shared_ids = [p[0] for p in team_shared_project_ids]
            shared_projects = Project.query\
                .options(joinedload(Project.team))\
                .filter(Project.id.in_(shared_ids), Project.is_archived == False)\
                .order_by(Project.updated_at.desc())\
                .limit(max_projects_per_team * 2)\
                .all()
            
            for project in shared_projects:
                if project.team_id not in teams_map:
                    teams_map[project.team_id] = {
                        'team': project.team,
                        'projects': [],
                        'total_count': 0
                    }
                if len(teams_map[project.team_id]['projects']) < max_projects_per_team:
                    if project not in teams_map[project.team_id]['projects']:
                        teams_map[project.team_id]['projects'].append(project)
        
        # 3. Get direct user shares - limited
        user_shared_project_ids = db.session.query(ProjectUserShare.project_id)\
            .filter(
                ProjectUserShare.user_id == user.id,
                ProjectUserShare.can_view_project == True
            )\
            .limit(max_projects_per_team * 2)\
            .all()
        
        if user_shared_project_ids:
            user_shared_ids = [p[0] for p in user_shared_project_ids]
            user_shared_projects = Project.query\
                .options(joinedload(Project.team))\
                .filter(Project.id.in_(user_shared_ids), Project.is_archived == False)\
                .order_by(Project.updated_at.desc())\
                .all()
                
            for project in user_shared_projects:
                if project.team_id not in teams_map:
                    teams_map[project.team_id] = {
                        'team': project.team,
                        'projects': [],
                        'total_count': 0
                    }
                if len(teams_map[project.team_id]['projects']) < max_projects_per_team:
                    if project not in teams_map[project.team_id]['projects']:
                        teams_map[project.team_id]['projects'].append(project)
        
        # 4. Format output
        for team_id, data in sorted(teams_map.items(), key=lambda x: x[1]['team'].name):
            hierarchy.append({
                'id': team_id,
                'name': data['team'].name,
                'projects': sorted(data['projects'], key=lambda p: p.name),
                'total_count': data['total_count'],
                'has_more': data['total_count'] > max_projects_per_team
            })
            
        return hierarchy