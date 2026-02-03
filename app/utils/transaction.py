from functools import wraps
from flask import current_app
from app.extensions import db

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
        try:
            result = f(*args, **kwargs)
            db.session.commit()
            return result
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Transaction failed in {f.__name__}: {str(e)}", exc_info=True)
            raise e
    return decorated_function
