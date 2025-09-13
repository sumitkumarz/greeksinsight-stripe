
from functools import wraps
from flask import request, g
import jwt
import time
from app.config import Config

def verify_app_access_token(token):
    """
    Helper to verify app access token (moved from /verify-access-token endpoint)
    Returns (claims, error_message) tuple
    """
    try:
        claims = jwt.decode(token, Config.APP_JWT_SECRET, algorithms=[Config.APP_JWT_ALG])
        expected_iss = "your-backend-service"
        now = int(time.time())
        errors = []
        if claims.get("iss") != expected_iss:
            errors.append("Invalid issuer")
        if not claims.get("sub"):
            errors.append("Missing subject (sub)")
        if not claims.get("iat") or not isinstance(claims["iat"], int) or claims["iat"] > now + 60:
            errors.append("Invalid issued-at (iat)")
        if not claims.get("exp") or not isinstance(claims["exp"], int) or claims["exp"] < now:
            errors.append("Token expired (exp)")
        if errors:
            return None, ", ".join(errors)
        return claims, None
    except Exception as e:
        return None, f"App access token verification failed: {e}"

# Decorator to require JWT token
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', None)
        if not auth_header or not auth_header.startswith('Bearer '):
            return {'error': 'Authorization header missing or invalid'}, 401

        token = auth_header.split(' ')[1]

        claims, err = verify_app_access_token(token)
        if err:
            return {'error': err}, 401
        if not claims:
            return {'error': 'Token claims missing'}, 401
        g.user_claims = claims
        return f(*args, **kwargs)
    return decorated
