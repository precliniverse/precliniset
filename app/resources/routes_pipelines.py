import os
import tempfile
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import ImportPipeline, user_has_permission
from app.forms.import_pipeline import ImportPipelineForm
from app.services.import_pipeline_service import ImportPipelineService
from . import resources_bp

pipeline_service = ImportPipelineService()

@resources_bp.route('/pipelines')
@login_required
def list_pipelines():
    """List all import pipelines."""
    pipelines = ImportPipeline.query.all()
    return render_template('resources/pipelines/list.html', pipelines=pipelines)

@resources_bp.route('/pipelines/create', methods=['GET', 'POST'])
@login_required
def create_pipeline():
    """Create a new import pipeline."""
    if not user_has_permission(current_user, 'ImportPipeline', 'create', allow_any_team=True):
        flash("You do not have permission to create import pipelines.", "danger")
        return redirect(url_for('resources.list_pipelines'))

    form = ImportPipelineForm()
    if form.validate_on_submit():
        try:
            pipeline_service.create_pipeline(
                name=form.name.data,
                script_content=form.script_content.data,
                description=form.description.data,
                created_by_id=current_user.id
            )
            flash("Pipeline created successfully.", "success")
            return redirect(url_for('resources.list_pipelines'))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Error creating pipeline: {str(e)}")
            flash("An unexpected error occurred.", "danger")

    return render_template('resources/pipelines/edit.html', form=form, title="Create Pipeline")

@resources_bp.route('/pipelines/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_pipeline(id):
    """Edit an existing import pipeline."""
    pipeline = db.session.get(ImportPipeline, id)
    if not pipeline:
        flash("Pipeline not found.", "danger")
        return redirect(url_for('resources.list_pipelines'))

    if not user_has_permission(current_user, 'ImportPipeline', 'edit', allow_any_team=True):
        flash("You do not have permission to edit import pipelines.", "danger")
        return redirect(url_for('resources.list_pipelines'))

    form = ImportPipelineForm(obj=pipeline)
    if form.validate_on_submit():
        try:
            pipeline_service.update_pipeline(
                id,
                name=form.name.data,
                script_content=form.script_content.data,
                description=form.description.data
            )
            flash("Pipeline updated successfully.", "success")
            return redirect(url_for('resources.list_pipelines'))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Error updating pipeline: {str(e)}")
            flash("An unexpected error occurred.", "danger")

    return render_template('resources/pipelines/edit.html', form=form, pipeline=pipeline, title="Edit Pipeline")

@resources_bp.route('/pipelines/<int:id>/delete', methods=['POST'])
@login_required
def delete_pipeline(id):
    """Delete an import pipeline."""
    if not user_has_permission(current_user, 'ImportPipeline', 'delete', allow_any_team=True):
        flash("You do not have permission to delete import pipelines.", "danger")
        return redirect(url_for('resources.list_pipelines'))

    try:
        pipeline_service.delete_pipeline(id)
        flash("Pipeline deleted successfully.", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
    
    return redirect(url_for('resources.list_pipelines'))

@resources_bp.route('/pipelines/test', methods=['POST'])
@login_required
def test_pipeline():
    """AJAX endpoint to test a script with a file upload."""
    script_content = request.form.get('script_content')
    uploaded_file = request.files.get('test_file')

    if not script_content or not uploaded_file:
        return jsonify({'success': False, 'error': 'Missing script content or file.'}), 400

    # Save file to a temporary location
    fd, temp_path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, 'wb') as tmp:
            uploaded_file.save(tmp)
        
        # We need a temporary pipeline object or modify execute_pipeline to accept content
        # For now, let's create a dummy object if we want to reuse the service logic
        # OR just use the validation + execution logic directly.
        
        try:
            pipeline_service.validate_script(script_content)
        except ValueError as e:
            return jsonify({'success': False, 'error': f"Validation Error: {str(e)}"}), 400

        result = pipeline_service.execute_script(script_content, temp_path)
        return jsonify({'success': True, 'result': result})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
