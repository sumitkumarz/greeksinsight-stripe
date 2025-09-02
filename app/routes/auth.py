from flask_restx import Namespace, Resource, fields
import os
from app.config import Config
from flask import request, jsonify
import jwt
import time
import requests
import hmac
import hashlib
import base64
import json

from app.util.auth_utils import get_app_claims_from_db, issue_app_jwt, verify_cognito_id_token
auth_ns = Namespace('auth', description='Authentication and authorization operations')

user_model = auth_ns.model('User', {
    'username': fields.String(required=True, description='Username'),
    'password': fields.String(required=True, description='Password'),
})

cognito_token_model = auth_ns.model('CognitoTokenRequest', {
    'username': fields.String(required=True, description='Cognito username'),
    'password': fields.String(required=True, description='Cognito password'),
})

cognito_idp_token_model = auth_ns.model('CognitoIdpTokenRequest', {
    'username': fields.String(required=True, description='Cognito username'),
    'password': fields.String(required=True, description='Cognito password'),
})

verify_id_token_model = auth_ns.model('VerifyIdTokenRequest', {
    'IdToken': fields.String(required=True, description='Cognito ID token'),
})

verify_access_token_model = auth_ns.model('VerifyAccessTokenRequest', {
    'appToken': fields.String(required=True, description='App JWT token'),
})

JWKS_URL = Config.JWKS_URL  # If you want to add JWKS_URL to config.py, do so
CLIENT_ID = Config.CLIENT_ID
APP_JWT_SECRET = Config.APP_JWT_SECRET or Config.SECRET_KEY
APP_JWT_ALG = 'HS256'  # You can add to config.py if needed
APP_JWT_TTL_SECONDS = 3600  # You can add to config.py if needed


@auth_ns.route('/dummy')
class Dummy(Resource):
    def get(self):
        """Dummy GET endpoint for testing"""
        return {'message': 'Auth dummy endpoint is working.'}, 200


@auth_ns.route('/verify-id-token')
class VerifyIdToken(Resource):
    @auth_ns.expect(verify_id_token_model)
    def post(self):
        data = request.get_json()
        id_token = data.get("IdToken")  # Expect capital I
        if not id_token:
            return jsonify({"error": "IdToken required"}), 400
        print("Verifying ID token...")
        print("ID Token:", id_token)
        claims, error = verify_cognito_id_token(id_token, JWKS_URL, CLIENT_ID)
        print("Verification result - Claims:", claims)
        print("Verification result - Error:", error)
        if error:
            return jsonify({"error": f"ID token verification failed: {error}"}), 401
        # Optional: enrich with app roles
        extra = get_app_claims_from_db(claims["sub"])
        app_token = issue_app_jwt(claims, extra, APP_JWT_SECRET, APP_JWT_ALG, APP_JWT_TTL_SECONDS)
        resp = jsonify({
            "appToken": app_token,
            "expiresIn": APP_JWT_TTL_SECONDS
        })
        # Set cookie with HttpOnly and Secure flags
        resp.set_cookie(
            "appToken",
            app_token,
            max_age=APP_JWT_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="Strict"
        )
        return resp


@auth_ns.route('/verify-access-token')
class VerifyAccessToken(Resource):
    @auth_ns.expect(verify_access_token_model)
    def post(self):
        data = request.get_json()
        token = data.get("appToken")
        if not token:
            return jsonify({"error": "appToken required"}), 400
        try:
            claims = jwt.decode(token, APP_JWT_SECRET, algorithms=[APP_JWT_ALG])
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
                return jsonify({"error": ", ".join(errors)}), 403
            return jsonify({"claims": claims, "authorized": True})
        except Exception as e:
            return jsonify({"error": f"App access token verification failed: {e}"}), 401




def get_secret_hash(username):
    message = username + Config.CLIENT_ID
    key = Config.CLIENT_SECRET.encode('utf-8')
    dig = hmac.new(key, message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


@auth_ns.route('/cognito-idp-token')
class CognitoIdpToken(Resource):
    @auth_ns.expect(cognito_idp_token_model)
    def post(self):
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return {"error": "username and password required"}, 400
        print('DEBUG: Username:', username)
        print('DEBUG: Password:', password)
        secret_hash = get_secret_hash(username)
        print('DEBUG: SecretHash:', secret_hash)
        payload = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": {
                "USERNAME": username,
                "PASSWORD": password,
                "SECRET_HASH": secret_hash
            },
            "ClientId": Config.CLIENT_ID
        }
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"
        }
        response = requests.post(
            "https://cognito-idp.us-east-1.amazonaws.com/",
            headers=headers,
            data=json.dumps(payload)
        )
        if response.status_code != 200:
            return {"error": "Failed to get tokens", "details": response.json()}, response.status_code
        tokens = response.json()
        return tokens, 200

