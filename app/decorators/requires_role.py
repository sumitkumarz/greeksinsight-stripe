from functools import wraps
from flask import jsonify, g
from app.decorators.token_required import token_required

def requires_role(role):
    def decorator(f):
        @token_required
        @wraps(f)
        def wrapped(*args, **kwargs):
            claims = getattr(g, 'user_claims', {})
            roles = claims.get('roles', [])
            if role not in roles:
                return jsonify({'error': f'Missing required role: {role}'}), 403
            return f(*args, **kwargs)
        return wrapped
    return decorator
