from functools import wraps
from flask import request, jsonify, g
import requests

# Decorator to require JWT token
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', None)
        if not auth_header or not auth_header.startswith('Bearer '):
            return {'error': 'Authorization header missing or invalid'}, 401

        token = auth_header.split(' ')[1]
        print("Token received:", token)  # Debugging line
        verify_url = f"{request.host_url.rstrip('/')}/auth/verify-access-token"

        try:
            resp = requests.post(verify_url, json={'appToken': token}, timeout=3)

            if resp.status_code != 200:
                return {'error': 'Invalid or expired token'}, 401
            try:
                claims = resp.json().get('claims')
            except ValueError:
                return {'error': 'Invalid response from auth service'}, 502

            if not claims:
                return {'error': 'Token claims missing'}, 401

            g.user_claims = claims

        except requests.exceptions.RequestException as e:
            return {'error': 'Authorization service unavailable', 'details': str(e)}, 503

        return f(*args, **kwargs)
    return decorated
