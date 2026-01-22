# app/api/auth.py
from functools import wraps
from flask import current_app, g, request
from werkzeug.exceptions import Unauthorized
from flask_login import current_user

from app.models import APIToken

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Check for Session Authentication (Flask-Login)
        # This allows the web UI (DataTables, etc.) to use API endpoints 
        # without needing to generate/pass a separate API token.
        if current_user.is_authenticated:
            g.current_user = current_user
            return f(*args, **kwargs)

        # 2. Check for API Token (Bearer or Query Param)
        token_str = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token_type, token_str = auth_header.split(None, 1)
                if token_type.lower() != 'bearer':
                    token_str = None # Not a bearer token
            except ValueError:
                # Header format is wrong
                token_str = None
        
        if not token_str:
            # Also check for token in query parameter as a fallback
            token_str = request.args.get('api_token') 
            if token_str:
                current_app.logger.warning("API token received via query parameter. Prefer Authorization header.")

        if not token_str:
            raise Unauthorized('API token is missing!')

        user_from_token = APIToken.verify_token(token_str)
        if not user_from_token:
            raise Unauthorized('API token is invalid or expired!')
        
        g.current_user = user_from_token 
        return f(*args, **kwargs)
    return decorated_function