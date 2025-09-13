
from functools import wraps
from flask import g
from app.decorators.token_required import token_required

def requires_role(role):
    def decorator(f):
        @token_required
        @wraps(f)
        def wrapped(*args, **kwargs):
            claims = getattr(g, 'user_claims', {})
            roles = claims.get('roles', [])
            if role not in roles:
                return {'error': f'Missing required role: {role}'}, 403
            return f(*args, **kwargs)
        return wrapped
    return decorator

# Admin-only decorator (moved from admin.py)
def admin_required(func):
    @token_required
    @wraps(func)
    def wrapper(*args, **kwargs):
        claims = getattr(g, 'user_claims', {})
        groups = claims.get('cognito:groups', []) or claims.get('roles', [])
        print("User groups:", groups)  # Debugging line
        if not groups or 'admin' not in [str(grp).lower() for grp in groups]:
            return {'error': 'Admin role required'}, 403
        return func(*args, **kwargs)
    return wrapper
