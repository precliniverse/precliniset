import json
import threading
from datetime import date, datetime, timezone
from contextlib import contextmanager

from flask import has_request_context, current_app
from flask_login import current_user
from sqlalchemy import event, inspect
from sqlalchemy.orm.attributes import get_history, NO_VALUE
try:
    from deepdiff import DeepDiff
except ImportError:
    DeepDiff = None

from app.extensions import db
from app.models import (AuditLog, DataTable, EthicalApproval, ExperimentalGroup,
                        ExperimentDataRow, Project, Sample, Team, User)

AUDITABLE_MODELS = [
    Project,
    ExperimentalGroup,
    DataTable,
    ExperimentDataRow,
    Sample,
    EthicalApproval,
    User,
    Team
]

# Thread-local storage for audit suppression
_audit_context = threading.local()

@contextmanager
def suppress_audit():
    """Context manager to temporarily disable audit logging in the current thread."""
    if not hasattr(_audit_context, 'suppressed'):
        _audit_context.suppressed = 0
    _audit_context.suppressed += 1
    try:
        yield
    finally:
        _audit_context.suppressed -= 1

def is_audit_suppressed():
    """Checks if audit logging is currently suppressed in this thread."""
    return getattr(_audit_context, 'suppressed', 0) > 0

def _get_current_user_id():
    """
    Helper to safely get current user ID.
    Returns None if no user is logged in or if outside of a request context (System).
    """
    try:
        if has_request_context():
            # current_user is a local proxy; is_authenticated is True if user is logged in
            if current_user and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                return current_user.id
    except Exception:
        # Gracious fallback for any context or proxy issues
        pass
    return None

def _json_serializer(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    # Handle other types if necessary
    return str(obj)

def _calculate_json_diff(old_value, new_value):
    """
    Calculates the difference between two JSON-like objects using DeepDiff.
    Returns a serializable dictionary.
    """
    if old_value == new_value:
        return None

    # Ensure values are parsed if they are strings (sometimes historians return strings for JSON cols)
    if isinstance(old_value, str):
        try:
            old_value = json.loads(old_value)
        except (ValueError, TypeError):
            pass
    if isinstance(new_value, str):
        try:
            new_value = json.loads(new_value)
        except (ValueError, TypeError):
            pass

    # If either is None, return a simple old/new structure as we can't deep diff
    if old_value is None or new_value is None:
        return {'old': old_value, 'new': new_value}

    try:
        # Use DeepDiff with ignore_order=True to get the delta
        if DeepDiff:
            diff = DeepDiff(old_value, new_value, ignore_order=True)
            if diff:
                 # Convert to dict and return
                 return json.loads(diff.to_json())
    except Exception:
        pass
        
    # Fallback to simple structure
    return {'old': old_value, 'new': new_value}

def _create_log_entry(connection, action, target, changes=None):
    """
    Inserts an AuditLog entry using Core SQL to avoid session conflicts.
    """
    if not current_app.config.get('ENABLE_AUDIT_LOG', True) or is_audit_suppressed():
        return

    user_id = _get_current_user_id()
    
    # Check if we should skip superadmin logging
    if not current_app.config.get('AUDIT_LOG_SUPERADMIN', True):
        # We need current_user to check if is_super_admin
        if has_request_context() and current_user and hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            if current_user.is_super_admin:
                return

    resource_type = target.__class__.__name__
    resource_id = str(target.id)
    
    # Ensure changes is a JSON-serializable dict (convert dates to strings)
    # This avoids TypeError: Object of type datetime is not JSON serializable
    serializable_changes = None
    if changes:
        try:
            # We already have a dict, but it might contain datetime etc.
            serializable_changes = json.loads(json.dumps(changes, default=_json_serializer))
        except Exception:
            # Fallback if serialization fails
            serializable_changes = str(changes)
    
    audit_values = {
        'user_id': user_id,
        'action': action,
        'resource_type': resource_type,
        'resource_id': resource_id,
        'changes': serializable_changes,
        'timestamp': datetime.now(timezone.utc)
    }
    
    connection.execute(AuditLog.__table__.insert().values(**audit_values))


def log_action(resource_type, resource_id, action, details=None, old_value=None, new_value=None):
    """
    Public helper to manually log an action (e.g. from a route).
    Useful for actions that don't directly map to a single DB commit or need custom details.
    Uses a separate connection to ensure the log is written even if the main transaction fails?
    Actually, for consistency, we should probably stick to the session if possible, 
    but `_create_log_entry` uses Core.
    
    Here we'll keep it simple and use the current session's connection or a new one.
    """
    try:
        changes = None
        if old_value is not None or new_value is not None:
            changes = {'old': old_value, 'new': new_value}
            
        # We need a connection object. Accessing via db.session.connection()
        connection = db.session.connection()
        
        # Check suppression
        if current_app.config.get('ENABLE_AUDIT_LOG', True) and not is_audit_suppressed():
            user_id = _get_current_user_id()
            
            serializable_changes = None
            if changes:
                try:
                    serializable_changes = json.loads(json.dumps(changes, default=_json_serializer))
                except Exception:
                    serializable_changes = str(changes)

            audit_values = {
                'user_id': user_id,
                'action': action.upper(),
                'resource_type': resource_type,
                'resource_id': str(resource_id),
                'changes': serializable_changes,
                'timestamp': datetime.now(timezone.utc)
            }

            # Put details in changes since AuditLog has changes column
            if details:
                if not changes:
                    changes = {}
                changes['details'] = details
                audit_values['changes'] = json.loads(json.dumps(changes, default=_json_serializer))
            
            connection.execute(AuditLog.__table__.insert().values(**audit_values))
            
    except Exception as e:
        current_app.logger.error(f"Manual audit log failed: {e}")


def register_audit_listeners(app):
    """
    Registers SQLAlchemy event listeners for all AUDITABLE_MODELS.
    This should be called during app initialization.
    """
    
    for model_cls in AUDITABLE_MODELS:
        
        @event.listens_for(model_cls, 'after_insert')
        def after_insert_listener(mapper, connection, target):
            # For inserts, we could log all fields, but usually just knowing ID is enough
            # or we can log the initial state. Let's log initial state for GLP.
            state = {}
            for column in mapper.columns:
                val = getattr(target, column.key)
                if val is not None:
                    state[column.key] = val
                    
            _create_log_entry(connection, 'INSERT', target, changes=state)

        @event.listens_for(model_cls, 'after_delete')
        def after_delete_listener(mapper, connection, target):
            # Capture state before death? 
            # In after_delete, the row is gone from DB, but target object still has data.
            # We log that it was deleted.
            _create_log_entry(connection, 'DELETE', target)

        @event.listens_for(model_cls, 'before_update')
        def before_update_listener(mapper, connection, target):
            changes = {}
            has_changes = False
            state = inspect(target)
            
            # Fetch the current record from the DB to be absolute sure about 'old' values
            # ( SQLAlchemy history can be unreliable for JSON/Mutable types )
            db_original = None
            try:
                table = mapper.local_table
                pk_column = mapper.primary_key[0]
                stmt = table.select().where(pk_column == getattr(target, pk_column.key))
                res = connection.execute(stmt).fetchone()
                if res:
                    # Row mapping access is more compatible (SQLAlchemy 1.4+)
                    db_original = res._asdict() if hasattr(res, '_asdict') else res._mapping
            except Exception as e:
                current_app.logger.error(f"Audit: Failed to fetch original record: {e}")

            for column in mapper.columns:
                prop_name = column.key
                
                # LOGISTICAL NOISE FIX: Skip updated_at and created_at 
                # These are updated automatically and clog the audit trail.
                if prop_name in ('updated_at', 'created_at'):
                    continue

                old_val = db_original.get(prop_name) if db_original else None
                
                # FALLBACK: If raw DB fetch returned None or failed, try SQLAlchemy history
                if old_val is None:
                    attr_state = state.attrs.get(prop_name)
                    hist = attr_state.history
                    if hist.deleted:
                        old_val = hist.deleted[0]
                    if old_val is NO_VALUE:
                        old_val = state.committed_state.get(prop_name, None)

                new_val = getattr(target, prop_name)
                
                # For JSON columns, we need to compare content, not just identity
                is_json = False
                if prop_name == 'animal_data' or prop_name == 'row_data':
                    is_json = True
                else:
                    try:
                        if hasattr(column.type, 'python_type') and column.type.python_type in (dict, list):
                            is_json = True
                    except (NotImplementedError, AttributeError):
                        pass

                if old_val != new_val:
                    if is_json:
                        # Normalize old_val if it's a string (common in SQLite core select)
                        parsed_old = old_val
                        if isinstance(old_val, str):
                            try:
                                parsed_old = json.loads(old_val)
                            except (ValueError, TypeError):
                                pass
                        
                        # Compare content after normalization
                        if parsed_old == new_val:
                             continue

                        # Use DeepDiff for JSON delta
                        diff = _calculate_json_diff(parsed_old, new_val)
                        
                        # SAFETY: If DeepDiff failed to find actual changes or returned empty
                        # but we know they differ, fall back to old/new
                        if not diff and parsed_old != new_val:
                            changes[prop_name] = {'old': parsed_old, 'new': new_val}
                            has_changes = True
                        elif diff:
                            changes[prop_name] = diff
                            has_changes = True
                    else:
                        # Standard column: record old and new values
                        changes[prop_name] = {
                            'old': old_val, 
                            'new': new_val
                        }
                        has_changes = True
            
            if has_changes:
                _create_log_entry(connection, 'UPDATE', target, changes=changes)
