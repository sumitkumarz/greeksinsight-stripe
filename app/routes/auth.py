from flask_restx import Namespace, Resource, fields
import os
from app.config import Config
from flask import request, jsonify, g
import jwt
import time
import requests
import hmac
import hashlib
import base64
import json
import boto3
import uuid
import stripe
from app.util.auth_utils import verify_app_jwt
from app.util.cognito_logout import cognito_global_logout


from app.util.auth_utils import create_access_token, create_refresh_token, verify_cognito_id_token
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
    'AccessToken': fields.String(required=False, description='Cognito Access token'),
})

verify_access_token_model = auth_ns.model('VerifyAccessTokenRequest', {
    'appToken': fields.String(required=True, description='App JWT token'),
})

JWKS_URL = Config.JWKS_URL  # If you want to add JWKS_URL to config.py, do so
CLIENT_ID = Config.CLIENT_ID
APP_JWT_SECRET = Config.APP_JWT_SECRET or Config.SECRET_KEY
REFRESH_TOKEN_EXPIRES = Config.REFRESH_TOKEN_EXPIRES
REFRESH_TOKEN_TTL_SECONDS = Config.REFRESH_TOKEN_EXPIRES
APP_JWT_ALG = Config.APP_JWT_ALG or 'HS256'
APP_JWT_TTL_SECONDS = Config.ACCESS_TOKEN_EXPIRES


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

from flask import jsonify, request

@auth_ns.route('/login')
class Login(Resource):
    @auth_ns.expect(verify_id_token_model)
    def post(self):
        print("--- /auth/login POST called ---")
        data = request.get_json(force=True, silent=True)
        print("Request JSON:", data)
        if not data:
            print("No JSON body received.")
            return jsonify({"error": "Missing JSON body"}), 400

        cognito_id_token = data.get("IdToken")
        cognito_access_token = data.get("AccessToken")
        print("IdToken:", cognito_id_token)
        print("AccessToken:", cognito_access_token)

        if not cognito_id_token:
            print("IdToken missing from request.")
            return jsonify({"error": "IdToken required"}), 400

        # --- Verify Cognito ID token ---
        try:
            claims, error = verify_cognito_id_token(cognito_id_token, JWKS_URL, CLIENT_ID)
            print("verify_cognito_id_token claims:", claims)
            print("verify_cognito_id_token error:", error)
        except Exception as e:
            print("Exception during verify_cognito_id_token:", e)
            return jsonify({"error": f"Exception during token verification: {str(e)}"}), 500

        if error or not claims:
            print("ID token verification failed:", error)
            return jsonify({"error": f"ID token verification failed: {error}"}), 401

        # Extract user info
        user_id = claims.get("sub")
        email = claims.get("email")
        name = claims.get("name")
        phone = claims.get("phone_number")
        groups = claims.get("cognito:groups", [])
        print("User groups:", groups)
        print("User email:", email)
        print("User ID:", user_id)
        # --- Stripe customer check/create ---
        users_table = Config.USERS_TABLE
        user_item = users_table.get_item(Key={"userId": user_id}).get("Item")
        stripe_customer_id = user_item.get("stripeCustomerId") if user_item else None

        if not stripe_customer_id:
            stripe.api_key = Config.STRIPE_SECRET_KEY
            stripe_customer = stripe.Customer.create(
                email=email,
                name=name if name else None,
                phone=phone if phone else None,
                metadata={"cognitoUserId": user_id}
            )
            stripe_customer_id = stripe_customer["id"]
            # Store in DynamoDB
            users_table.update_item(
                Key={"userId": user_id},
                UpdateExpression="SET stripeCustomerId=:c",
                ExpressionAttributeValues={":c": stripe_customer_id}
            )
        print("Stripe customer ID:", stripe_customer_id)
        # --- Issue app tokens ---
        extra = {"roles": groups}
        jti = str(uuid.uuid4())
        access_token = create_access_token(jti,user_id, email, extra)
        refresh_token = create_refresh_token(jti,user_id, email, cognito_token=cognito_access_token)
        print("Access Token:", access_token)
        print("Refresh Token:", refresh_token)
        # --- Build response ---
        resp = jsonify({
            "access_token": access_token
        })
        resp.set_cookie(
                "refresh_token", refresh_token,
                httponly=True,
                secure=True,          # False in dev, True in production with HTTPS
                samesite="Strict",        # Lax is enough for local cross-origin requests
                max_age=Config.REFRESH_TOKEN_EXPIRES
        )

        return resp


from flask_cors import cross_origin
from flask import make_response, jsonify

@auth_ns.route('/logout')
class Logout(Resource):
    def post(self):
        refresh_token = request.cookies.get("refresh_token")
        print("Logout called")
        print("Refresh Token from cookie:", refresh_token)

        if not refresh_token:
            return {"error": "Missing refresh token"}, 401

        # Safe JWT verification
        try:
            claims, error = verify_app_jwt(refresh_token, APP_JWT_SECRET, APP_JWT_ALG)
        except Exception as e:
            print("JWT error:", e)
            return {"error": "Invalid token"}, 401

        if error or not claims:
            return {"error": "Invalid or expired refresh token"}, 401

        user_id = claims.get("sub")
        jti = claims.get("jti")

        # Delete token from Redis safely
        if user_id and jti:
            try:
                redis_key = f"refresh:{user_id}:{jti}"
                Config.REDIS_CLIENT.delete(redis_key)
            except Exception as e:
                print("Redis deletion error:", e)

        # Clear cookies using make_response
        response = make_response({"message": "Logged out successfully"})
        response.set_cookie("refresh_token", "", max_age=0, httponly=True, secure=True, samesite="Strict")
        return response




@auth_ns.route('/refresh')
class Refresh(Resource):
    @auth_ns.doc(description="Obtain a new access token and refresh token using the HttpOnly refresh token cookie. No Bearer token required.")
    def post(self):
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            return {"error": "Missing refresh token"}, 401

        try:
            # Decode and validate refresh token
            payload = jwt.decode(
                refresh_token,
                Config.APP_JWT_SECRET,
                algorithms=[Config.APP_JWT_ALG]
            )
            if payload.get("type") != "refresh":
                return {"error": "Invalid token type"}, 400

            user_id = payload.get("sub")
            email = payload.get("email")

            jti = payload.get("jti")

            if not user_id or not jti:
                return {"error": "Invalid token payload"}, 400

            # Check Redis to ensure token is still valid
            redis_key = f"refresh:{user_id}:{jti}"
            value = Config.REDIS_CLIENT.get(redis_key)
            if not value:
                return {"error": "Refresh token revoked or expired"}, 401

            # Revoke old token
            Config.REDIS_CLIENT.delete(redis_key)

            # Preserve Cognito token if present
            cognito_token = json.loads(value).get("cognito_token")

            # Get user roles/groups from DynamoDB
            user_item = Config.USERS_TABLE.get_item(Key={"userId": user_id}).get("Item")
            groups = user_item.get("groups", []) if user_item else []
            extra = {"roles": groups}

            # Issue new tokens
            new_access_token = create_access_token(jti,user_id, email, extra)
            new_refresh_token = create_refresh_token(jti,user_id, email, cognito_token=cognito_token)

            # Prepare response with rotated tokens
            resp = jsonify({"access_token": new_access_token})
            resp.set_cookie(
                "refresh_token", new_refresh_token,
                httponly=True,
                secure=True,          # False in dev, True in production with HTTPS
                samesite="Strict",        # Lax is enough for local cross-origin requests
                max_age=Config.REFRESH_TOKEN_EXPIRES
            )
            
            return resp

        except jwt.ExpiredSignatureError:
            return {"error": "Refresh token expired"}, 401
        except jwt.InvalidTokenError:
            return {"error": "Invalid refresh token"}, 401
        except Exception as e: 
            return {"error": str(e)}, 400
