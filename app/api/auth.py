# app/api/auth.py
from functools import wraps
from flask import current_app, g, request
from werkzeug.exceptions import Unauthorized
from flask_login import current_user
from flask_wtf.csrf import validate_csrf

from app.models import APIToken
# Do not import 'csrf' extension here to avoid circular imports if not needed, 
# validate_csrf function is enough.

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token_str = None
        
        # 1. Check for Bearer Token (Priority)
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token_type, token_val = auth_header.split(None, 1)
                if token_type.lower() == 'bearer':
                    token_str = token_val
            except ValueError:
                pass
        
        # 2. If Bearer Token found, Validate it
        if token_str:
            user_from_token = APIToken.verify_token(token_str)
            if not user_from_token:
                raise Unauthorized('Invalid or expired API token')
            g.current_user = user_from_token
            return f(*args, **kwargs)

        # 3. Fallback to Session Authentication (Strict CSRF)
        if current_user.is_authenticated:
            # For session auth, we MUST enforce CSRF to prevent attacks
            try:
                # Flask-WTF looks for X-CSRFToken header or csrf_token form field
                # We can call validate_csrf directly which checks request.headers['X-CSRFToken']
                validate_csrf(request.headers.get('X-CSRFToken'))
            except Exception: # Catching generic exception as validate_csrf raises various errors depending on version
                raise Unauthorized('Session active but CSRF token missing or invalid')
            
            g.current_user = current_user
            return f(*args, **kwargs)

        # 4. No valid credential found
        raise Unauthorized('Authentication required (Bearer Token or Session+CSRF)')

    return decorated_function