import logging
import os
from functools import wraps

from flask_caching import Cache


def configure_cache(app):
    """Configure Redis-based caching with multiple regions"""
    # Set cache configuration in app.config
    app.config['CACHE_TYPE'] = os.environ.get('CACHE_TYPE', 'RedisCache')
    app.config['CACHE_DEFAULT_TIMEOUT'] = int(os.environ.get('CACHE_DEFAULT_TIMEOUT', 300)) # 5 minutes default
    app.config['CACHE_REDIS_URL'] = os.environ.get('CACHE_REDIS_URL', 'redis://localhost:6379/0')
    
    # Example of configuring multiple caches if needed (though Flask-Caching primarily uses CACHE_TYPE)
    # app.config['CACHE_CONFIG'] = {
    #     'default': {
    #         'CACHE_TYPE': 'RedisCache',
    #         'CACHE_DEFAULT_TIMEOUT': 300,
    #         'CACHE_REDIS_URL': 'redis://localhost:6379/0'
    #     },
    #     'short_term': {
    #         'CACHE_TYPE': 'RedisCache',
    #         'CACHE_DEFAULT_TIMEOUT': 60,
    #         'CACHE_REDIS_URL': 'redis://localhost:6379/1' # Use a different DB for separation
    #     }
    # }
    
    cache = Cache() # Initialize without config dict
    cache.init_app(app) # Config will be read from app.config
    
    # Add cache versioning support
    app.config['CACHE_VERSION'] = os.environ.get('CACHE_VERSION', 'v1')
    
    return cache

def cache_key_with_user(prefix, request):
    """Generate cache key with user context"""
    from flask_login import current_user
    user_id = getattr(current_user, 'id', 'anonymous')
    path = request.path
    return f"{prefix}_{app.config['CACHE_VERSION']}_{user_id}_{path}"

def cache_for_user(ttl=300, cache_type='default'):
    """Cache decorator that separates caches by user"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            from flask import request
            from flask_caching import make_template_fragment_key
            
            cache_key = cache_key_with_user(f.__name__, request)
            
            # Check cache first
            cache = args[0].cache if hasattr(args[0], 'cache') else args[0].app.cache
            response = cache.get(cache_key)
            
            if response is None:
                response = f(*args, **kwargs)
                cache.set(cache_key, response, ttl=ttl, type=cache_type)
            
            return response
        return wrapper
    return decorator

def invalidate_user_cache(prefix):
    """Invalidate cache for current user"""
    from flask import request
    from flask_login import current_user
    
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cache_key = cache_key_with_user(prefix, request)
            result = f(*args, **kwargs)
            
            # Invalidate cache
            if hasattr(args[0], 'cache'):
                args[0].cache.delete(cache_key)
            else:
                args[0].app.cache.delete(cache_key)
            
            return result
        return wrapper
    return decorator

from flask import request


def init_app(app):
    """Initialize caching for the Flask application"""
    if not app.config.get('ENABLE_CACHING', True):
        return
    
    configure_cache(app)
    
    # Add cache control middleware
    @app.before_request
    def set_cache_control():
        if '/static/' in request.path:
            return
            
        # Set cache control headers for authenticated users
        from flask_login import current_user
        if getattr(current_user, 'is_authenticated', False):
            request.cache_control = 'private'
        else:
            request.cache_control = 'public'
