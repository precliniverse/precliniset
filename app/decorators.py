from functools import wraps

from flask import abort, flash, g, redirect, request, url_for
from flask_babel import lazy_gettext as _l
from flask_login import current_user

from .models import user_has_permission


def permission_required(resource, action):
    """
    Decorator to ensure the user has the required permission for a resource and action.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            is_api_request = request.blueprint == 'api'
            user_to_check = g.current_user if is_api_request and hasattr(g, 'current_user') else current_user

            if not user_to_check or not user_to_check.is_authenticated:
                if is_api_request:
                    abort(401, description="Authentication required.")
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('auth.login', next=request.url))

            # Determine the team context
            team_id = kwargs.get('team_id')
            if not team_id:
                # Try to get team_id from project, group, etc.
                project_id = kwargs.get('project_id')
                if project_id:
                    from .models import Project, db
                    project = db.session.get(Project, project_id)
                    if project:
                        team_id = project.team_id
                # Add more context lookups as needed (e.g., for ExperimentalGroup)

            if not user_has_permission(user_to_check, resource, action, team_id=team_id):
                if is_api_request:
                    abort(403, description="You do not have permission to perform this action.")
                # For web routes, aborting with 403 is cleaner for testing and security.
                # A global error handler can catch this and show a nice "permission denied" page.
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def super_admin_required(f):
    """
    Decorator to ensure the user is authenticated and is a super admin.
    This is a special case of permission_required for global admin actions.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_api_request = request.blueprint == 'api'
        user_to_check = g.current_user if is_api_request and hasattr(g, 'current_user') else current_user

        if not user_to_check or not user_to_check.is_authenticated:
            if is_api_request:
                abort(401, description="Authentication required.")
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('auth.login', next=request.url))

        if not user_to_check.is_super_admin:
            if is_api_request:
                abort(403, description="Super admin privileges required for this resource.")
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function

def team_admin_or_super_admin_required(f):
    """
    Decorator to ensure the user is authenticated and is either a team admin
    for the specified team or a super admin.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_api_request = request.blueprint == 'api'
        user_to_check = g.current_user if is_api_request and hasattr(g, 'current_user') else current_user

        if not user_to_check or not user_to_check.is_authenticated:
            if is_api_request:
                abort(401, description="Authentication required.")
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('auth.login', next=request.url))

        team_id = kwargs.get('team_id')
        if not team_id:
            # Attempt to get team_id from other kwargs if available
            project_id = kwargs.get('project_id')
            if project_id:
                from .models import Project, db
                project = db.session.get(Project, project_id)
                if project:
                    team_id = project.team_id
            # Add more context lookups as needed (e.g., for ExperimentalGroup)

        if not user_to_check.is_super_admin and not user_has_permission(user_to_check, 'Team', 'manage_members', team_id=team_id):
            if is_api_request:
                abort(403, description="Team admin or super admin privileges required for this resource.")
            flash("You do not have sufficient privileges to access this page.", "danger")
            return redirect(url_for('main.index'))

        return f(*args, **kwargs)
    return decorated_function

def transactional(f):
    """
    Decorator to wrap a function in a database transaction.
    
    It will:
    - Execute the function.
    - Commit the transaction on success.
    - Rollback the transaction on exception and re-raise.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from .extensions import db
        from flask import current_app
        try:
            result = f(*args, **kwargs)
            db.session.commit()
            return result
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Transaction failed in {f.__name__}: {str(e)}", exc_info=True)
            raise e
    return decorated_function
