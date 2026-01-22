import os
from datetime import datetime
from io import StringIO

import pandas as pd
from flask import (current_app, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_babel import lazy_gettext as _l
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Attachment, DataTable, ExperimentalGroup, Project

from ..helpers import get_ordered_column_names
from . import ckan_bp
from . import helpers as ckan_api
from .helpers import sanitize_ckan_name


@ckan_bp.route('/<string:project_slug>/upload', methods=['GET'])
@login_required
def upload_project(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()

    if not current_user.ckan_url or not current_user.ckan_api_key:
        flash(_l('Please set your CKAN URL and API Key in your settings before uploading.'), 'warning')
        return redirect(url_for('main.settings', _anchor='ckan-settings-section'))

    try:
        organizations = ckan_api.get_user_organizations(current_user.ckan_api_key, current_user.ckan_url)
    except Exception as e:
        flash(_l('Could not connect to CKAN. Please check your URL and API Key. Error: %(error)s', error=str(e)), 'danger')
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    if not organizations:
        flash(_l('You are not a member of any organizations on the specified CKAN portal. You must belong to an organization to create a dataset.'), 'warning')
        return redirect(url_for('projects.view_edit_project', project_slug=project.slug))

    # Get all datatables for this project, and their associated protocol attachments
    datatables_in_project = db.session.query(DataTable).join(ExperimentalGroup).filter(
        ExperimentalGroup.project_id == project.id
    ).order_by(DataTable.date.asc()).all()
    
    datatable_data = []
    protocol_attachments_map = {}
    for dt in datatables_in_project:
        datatable_data.append({'id': dt.id, 'name': f"{dt.protocol.name} on {dt.date}"})
        attachment = dt.protocol.attachments.first()
        if attachment:
            # Avoid duplicates
            if attachment.id not in protocol_attachments_map:
                protocol_attachments_map[attachment.id] = {
                    'id': attachment.id,
                    'filename': attachment.filename,
                    'protocol_name': dt.protocol.name
                }

    # Get all project-level attachments
    project_attachments = project.attachments.all()
    project_attachment_data = [{'id': att.id, 'filename': att.filename} for att in project_attachments]

    return render_template('ckan/upload_project.html', 
                           project=project, 
                           organizations=organizations, 
                           datatables=datatable_data, 
                           project_attachments=project_attachment_data,
                           protocol_attachments=list(protocol_attachments_map.values()))


@ckan_bp.route('/<string:project_slug>/start_upload', methods=['POST'])
@login_required
def start_upload(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    data = request.get_json()
    dataset_name = data.get('name')

    if not dataset_name:
        return jsonify({'status': 'error', 'message': 'Dataset name is required.'}), 400

    try:
        existing_dataset = ckan_api.package_show(current_user.ckan_api_key, current_user.ckan_url, dataset_name)
        if existing_dataset:
            return jsonify({
                'status': 'exists',
                'dataset_id': existing_dataset['id'],
                'resources': [{'id': res['id'], 'name': res['name']} for res in existing_dataset.get('resources', [])]
            })
        else:
            return jsonify({'status': 'new'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@ckan_bp.route('/<string:project_slug>/create_dataset', methods=['POST'])
@login_required
def create_dataset(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    data = request.get_json()
    
    try:
        sanitized_name = sanitize_ckan_name(data.get('name'))
        if not sanitized_name:
            return jsonify({'status': 'error', 'message': 'Dataset name cannot be empty after sanitization.'}), 400

        is_private = data.get('private', True)
        if not isinstance(is_private, bool):
            # Ensure the value is a true boolean, handling strings like "true" or "false"
            is_private = str(is_private).lower() in ['true', 'on', '1']

        new_dataset = ckan_api.package_create(
            api_key=current_user.ckan_api_key,
            ckan_url=current_user.ckan_url,
            name=sanitized_name,
            title=project.name,
            owner_org=data.get('organization_id'),
            private=is_private,
            notes=project.description or ''
        )
        project.ckan_dataset_id = new_dataset['id']
        project.ckan_organization_id = new_dataset['owner_org']
        db.session.commit()
        return jsonify({'status': 'success', 'dataset_id': new_dataset['id']})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@ckan_bp.route('/<string:project_slug>/upload_resource/<int:datatable_id>', methods=['POST'])
@login_required
def upload_resource(project_slug, datatable_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    datatable = DataTable.query.get_or_404(datatable_id)
    data = request.get_json()
    dataset_id = data.get('dataset_id')

    # --- Convert DataTable to CSV in memory ---
    column_names = get_ordered_column_names(datatable)
    data_for_df = []
    for row in datatable.experiment_rows.order_by('row_index'):
        row_data = {}
        if datatable.group.animal_data and row.row_index < len(datatable.group.animal_data):
            row_data.update(datatable.group.animal_data[row.row_index])
        row_data.update(row.row_data)

        # Calculate Age (Days) on the fly for the export
        age_in_days = None
        date_of_birth_str = row_data.get('Date of Birth')
        if date_of_birth_str and datatable.date:
            try:
                dob = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                dt_date = datetime.strptime(datatable.date, '%Y-%m-%d').date()
                delta = dt_date - dob
                age_in_days = delta.days
            except (ValueError, TypeError):
                current_app.logger.warning(
                    f"Could not calculate age for animal index {row.row_index} in datatable {datatable.id} during CKAN upload due to invalid date format."
                )
        row_data['Age (Days)'] = age_in_days

        data_for_df.append(row_data)
    
    df = pd.DataFrame(data_for_df, columns=column_names)

    # --- Add Housing Conditions Metadata ---
    if datatable.housing_condition:
        housing_conditions_data = {}
        for item_assoc in datatable.housing_condition.item_associations:
            column_name = item_assoc.item.name
            housing_conditions_data[column_name] = item_assoc.default_value

        for col_name, value in housing_conditions_data.items():
            df[col_name] = value
    # --- End Housing Conditions ---

    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_content = csv_buffer.getvalue().encode('utf-8')
    # --- End CSV Conversion ---

    # Create a standardized, unique name for the resource
    sanitized_protocol_name = sanitize_ckan_name(datatable.protocol.name)
    resource_name = f"datatable_{datatable.id}_{sanitized_protocol_name}_{datatable.date}.csv"
    
    # Enrich description with protocol details
    description = f"Data from protocol '{datatable.protocol.name}' collected on {datatable.date} for group '{datatable.group.name}'."
    if datatable.protocol.description:
        description += f"\n\nProtocol Description: {datatable.protocol.description}"
    if datatable.protocol.url:
        description += f"\nProtocol URL: {datatable.protocol.url}"


    try:
        # Check if a resource with this name already exists in the dataset
        dataset_details = ckan_api.package_show(current_user.ckan_api_key, current_user.ckan_url, dataset_id)
        existing_resource = next((res for res in dataset_details.get('resources', []) if res['name'] == resource_name), None)

        if existing_resource:
            # If it exists, update it
            result = ckan_api.resource_update(
                api_key=current_user.ckan_api_key,
                ckan_url=current_user.ckan_url,
                resource_id=existing_resource['id'],
                file_content=csv_content,
                name=resource_name,
                description=description
            )
        else:
            # If it doesn't exist, create it
            result = ckan_api.resource_create(
                api_key=current_user.ckan_api_key,
                ckan_url=current_user.ckan_url,
                package_id=dataset_id,
                name=resource_name,
                description=description,
                file_content=csv_content
            )

        # Now, handle the protocol attachment
        protocol_attachment = datatable.protocol.attachments.first()
        if protocol_attachment:
            attachment_resource_name = f"protocol_{datatable.protocol.id}_{protocol_attachment.filename}"
            
            # Check if this attachment has already been uploaded for this dataset
            attachment_exists = any(res['name'] == attachment_resource_name for res in dataset_details.get('resources', []))

            if not attachment_exists:
                try:
                    file_path = protocol_attachment.filepath
                    with open(file_path, 'rb') as f:
                        attachment_content = f.read()
                    
                    ckan_api.resource_create(
                        api_key=current_user.ckan_api_key,
                        ckan_url=current_user.ckan_url,
                        package_id=dataset_id,
                        name=attachment_resource_name,
                        description=f"Attachment for protocol '{datatable.protocol.name}'.",
                        file_content=attachment_content
                    )
                except FileNotFoundError:
                    current_app.logger.error(f"Protocol attachment file not found at {protocol_attachment.filepath}")
                except Exception as e:
                    current_app.logger.error(f"Failed to upload protocol attachment {protocol_attachment.filename}: {e}")


        return jsonify({'status': 'success', 'resource_name': result['name']})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@ckan_bp.route('/<string:project_slug>/finalize_upload', methods=['POST'])
@login_required
def finalize_upload(project_slug):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    project.ckan_upload_date = datetime.now(current_app.config['UTC_TZ'])
    try:
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@ckan_bp.route('/<string:project_slug>/upload_attachment/<int:attachment_id>', methods=['POST'])
@login_required
def upload_attachment(project_slug, attachment_id):
    project = Project.query.filter_by(slug=project_slug).first_or_404()
    attachment = Attachment.query.get_or_404(attachment_id)
    if attachment.project_id != project.id:
        return jsonify({'status': 'error', 'message': 'Attachment does not belong to this project.'}), 403

    data = request.get_json()
    dataset_id = data.get('dataset_id')
    resource_id_to_update = data.get('resource_id')

    # --- Read attachment file from disk ---
    try:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.filepath)
        with open(file_path, 'rb') as f:
            file_content = f.read()
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': f"Attachment file not found on server: {attachment.filename}"}), 404
    except Exception as e:
        current_app.logger.error(f"Error reading attachment file {file_path}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f"Could not read attachment file: {attachment.filename}"}), 500
    # --- End file reading ---

    resource_name = attachment.filename
    description = attachment.description or f"Project attachment uploaded on {datetime.now(current_app.config['UTC_TZ']).strftime('%Y-%m-%d')}."

    try:
        if resource_id_to_update:
            result = ckan_api.resource_update(
                api_key=current_user.ckan_api_key,
                ckan_url=current_user.ckan_url,
                resource_id=resource_id_to_update,
                file_content=file_content,
                name=resource_name
            )
        else:
            result = ckan_api.resource_create(
                api_key=current_user.ckan_api_key,
                ckan_url=current_user.ckan_url,
                package_id=dataset_id,
                name=resource_name,
                description=description,
                file_content=file_content
            )
        return jsonify({'status': 'success', 'resource_name': result['name']})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
