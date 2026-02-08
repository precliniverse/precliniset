# app/tasks.py
from flask import current_app, render_template
from flask_mail import Message

from .celery_utils import celery_app
from .extensions import db, mail
from .models import Project, User, Workplan, DataTable
from .services.tm_connector import TrainingManagerConnector
from requests.exceptions import RequestException


@celery_app.task(name='tasks.send_email')
def send_email_task(to, subject, template_path, **kwargs):
    """
    A Celery task to send an email using a rendered HTML template.
    It re-fetches database objects from IDs passed in kwargs.
    """
    if not current_app.config.get('MAIL_SERVER'):
        current_app.logger.warning(f"SMTP is not configured. Email task to {to} aborted.")
        return

    # The task runs within the app context provided by ContextTask in celery_worker.py
    # but we need a request context for url_for and translations.
    app = current_app._get_current_object()
    with app.test_request_context():
        # --- FIX: Re-fetch objects from the database using their IDs ---
        if 'user_id' in kwargs:
            user = db.session.get(User, kwargs['user_id'])
            if not user:
                current_app.logger.error(f"Could not find user with ID {kwargs.get('user_id')} for email task.")
                return # Stop if user not found
            kwargs['user'] = user
        
        if 'project_id' in kwargs:
            project = db.session.get(Project, kwargs['project_id'])
            kwargs['project'] = project

        if 'workplan_id' in kwargs:
            workplan = db.session.get(Workplan, kwargs['workplan_id'])
            kwargs['workplan'] = workplan
        
        if isinstance(to, str):
            recipients_list = [to]
        elif isinstance(to, list):
            recipients_list = to
        else:
            current_app.logger.error(f"Invalid 'to' field for email task: {to}. Must be a string or list.")
            return

        # url_for and translations will now work inside here
        html_content = render_template(template_path, **kwargs)
        msg = Message(
            subject,
            recipients=recipients_list,
            html=html_content,
            sender=current_app.config['MAIL_DEFAULT_SENDER']
        )
        try:
            mail.send(msg)
            current_app.logger.info(f"Email task sent successfully to {to}")
        except Exception as e:
            current_app.logger.error(f"Error in email task to {to}: {e}", exc_info=True)
            # Optionally, you can retry the task
            # raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, name='tasks.perform_analysis')
def perform_analysis_task(self, form_data, datatable_id=None, selected_ids=None, user_id=None):
    """
    Background task to perform statistical analysis.
    Reconstructs the DataFrame inside the worker to avoid passing large data objects.
    Note: ContextTask (in celery_worker.py) already provides app_context, no need to create another.
    """
    # Import here to avoid circular dependency with helpers -> tasks
    from .services.analysis_service import AnalysisService 
    
    # CRITICAL: Expire all cached objects to ensure fresh data from DB
    # This is essential in multi-process environments (separate containers)
    db.session.expire_all()
    
    service = AnalysisService()
    
    # 1. Reconstruct the DataFrame
    df = None
    numerical_cols = []
    categorical_cols = []
    
    try:
        if datatable_id:
            # Force fresh query by using execute with explicit session
            dt = db.session.query(DataTable).filter_by(id=datatable_id).first()
            if not dt:
                current_app.logger.error(f"DataTable {datatable_id} not found in async task (checked via query)")
                # Try one more time with get after rollback
                db.session.rollback()
                dt = db.session.get(DataTable, datatable_id)
                if not dt:
                    current_app.logger.error(f"DataTable {datatable_id} still not found after rollback")
                    return {'error': 'DataTable not found'}
            current_app.logger.info(f"Processing DataTable {datatable_id} in async task")
            df, numerical_cols, categorical_cols = service.prepare_dataframe(dt)
        elif selected_ids:
            # Convert strings back to ints if necessary
            ids = [int(x) for x in selected_ids]
            current_app.logger.info(f"Aggregate datatables async task for IDs: {ids}, user_id: {user_id}")
            df, errors, _ = service.aggregate_datatables(ids, user_id=user_id)
            if errors:
                current_app.logger.error(f"Errors aggregating datatables: {errors}")
                return {'error': ' ; '.join(errors)}
            
            # Re-identify columns for merged data
            import pandas as pd
            internal_cols = ['_source_datatable_id', '_source_experimental_group_name', '_source_protocol_name', '_source_datatable_date']
            for col in df.columns:
                if col in internal_cols or col == 'uid': continue
                if pd.api.types.is_numeric_dtype(df[col]):
                    numerical_cols.append(col)
                else:
                    categorical_cols.append(col)
        
        if df is None or df.empty:
            return {'error': 'No data available for analysis.'}

        # 2. Run Analysis
        subject_id_col = 'uid'
        subject_id_col_present = subject_id_col in df.columns
        
        results = service.perform_analysis(
            df, form_data, subject_id_col, subject_id_col_present,
            numerical_cols, categorical_cols
        )
        
        return results

    except Exception as e:
        current_app.logger.error(f"Async Analysis Failed: {e}", exc_info=True)
        return {'error': str(e)}

@celery_app.task(bind=True, autoretry_for=(RequestException,), retry_backoff=True, max_retries=72, name='tasks.declare_tm_practice')
def declare_tm_practice_task(self, email, skill_ids, date, source):
    """
    Background task to declare practice in Training Manager.
    Retries up to 72 times (approx 3 days) in case TM is offline.
    """
    try:
        connector = TrainingManagerConnector()
        result = connector.declare_practice(email, skill_ids, date, source)
        if result:
            current_app.logger.info(f"Successfully declared practice for {email} on {date}")
        else:
            current_app.logger.warning(f"Failed to declare practice for {email} on {date} - TM offline or error")
    except Exception as e:
        current_app.logger.error(f"Error declaring practice for {email}: {e}", exc_info=True)
        raise  # Re-raise to trigger retry
