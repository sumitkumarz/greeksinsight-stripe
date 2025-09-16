import time
import requests
from typing import Dict, Tuple, Optional
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from jose import JWTError
import base64
import jwt
from jose.utils import base64url_decode
import uuid
import bcrypt
import json
from app.config import Config

# Construct RSA public key from JWK
def construct_rsa_public_key(jwk):
    n_bytes = jwk['n'].encode('utf-8') if isinstance(jwk['n'], str) else jwk['n']
    e_bytes = jwk['e'].encode('utf-8') if isinstance(jwk['e'], str) else jwk['e']
    n_int = int.from_bytes(base64url_decode(n_bytes), 'big')
    e_int = int.from_bytes(base64url_decode(e_bytes), 'big')
    public_numbers = rsa.RSAPublicNumbers(e_int, n_int)
    return public_numbers.public_key(backend=default_backend())

# Verify Cognito ID token
def verify_cognito_id_token(id_token, jwks_url, client_id):
    header = jwt.get_unverified_header(id_token)
    kid = header['kid']
    jwks = requests.get(jwks_url).json()
    jwk = next((k for k in jwks['keys'] if k['kid'] == kid), None)
    if not jwk:
        return None, "Public key not found for kid"
    public_key = construct_rsa_public_key(jwk)
    claims = jwt.decode(
        id_token,
        public_key,
        algorithms=['RS256'],
        audience=client_id,
        leeway=10 
    )
    return claims, None

# App JWT issuance & verification
def create_access_token(jti: str ,sub: str, email: str,extra_claims: Dict) -> str:
    now = int(time.time())
    app_jwt_secret = Config.APP_JWT_SECRET
    app_jwt_alg = Config.APP_JWT_ALG
    app_jwt_ttl_seconds = Config.ACCESS_TOKEN_EXPIRES
    payload = {
        "iss": "greeksinsight.com",
        "jti": jti,
        "sub": sub,
        "email": email,
        "iat": now,
        "exp": now + app_jwt_ttl_seconds,
        "roles": extra_claims.get("roles", []),
        "perms": extra_claims.get("perms", []),
        "type": "access"
    }
    return jwt.encode(payload, app_jwt_secret, algorithm=app_jwt_alg)

def verify_app_jwt(token: str, app_jwt_secret, app_jwt_alg) -> Tuple[Optional[Dict], Optional[str]]:
    try:
        claims = jwt.decode(token, app_jwt_secret, algorithms=[app_jwt_alg])
        return claims, None
    except JWTError as e:
        return None, f"Invalid app token: {e}"
    except Exception as e:
        return None, str(e)

# Remove all existing Cognito groups for a user and add a new one
def update_cognito_user_groups(user_pool_id: str, username: str, new_group: str, region_name: str = "us-east-1"):
    import boto3
    cognito = boto3.client('cognito-idp', region_name=region_name)
    # List all groups for the user
    try:
        groups_resp = cognito.admin_list_groups_for_user(UserPoolId=user_pool_id, Username=username)
        current_groups = [g['GroupName'] for g in groups_resp.get('Groups', [])]
    except Exception as e:
        print(f"Error listing groups for user {username}: {e}")
        current_groups = []
    # Remove user from all current groups except the new one
    for group in current_groups:
        if group != new_group:
            try:
                cognito.admin_remove_user_from_group(UserPoolId=user_pool_id, Username=username, GroupName=group)
            except cognito.exceptions.UserNotFoundException:
                pass
            except cognito.exceptions.ResourceNotFoundException:
                pass
            except Exception as e:
                print(f"Error removing user {username} from group {group}: {e}")
    # Add user to the new group
    try:
        cognito.admin_add_user_to_group(UserPoolId=user_pool_id, Username=username, GroupName=new_group)
    except Exception as e:
        print(f"Error adding user {username} to group {new_group}: {e}")

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_refresh_token(jti, user_id, email, cognito_token):
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "exp": now + Config.REFRESH_TOKEN_EXPIRES,
        "iat": now,
        "type": "refresh"
    }
    token = jwt.encode(payload, Config.APP_JWT_SECRET, algorithm=Config.APP_JWT_ALG)
    # Store in Redis
    key = f"refresh:{user_id}:{jti}"
    #print(cognito_token)
    value = json.dumps({
        "user_id": user_id,
        "issuedAt": now,
        "expiresAt": now + Config.REFRESH_TOKEN_EXPIRES,
        "cognito_token": cognito_token   # <-- store Cognito ID token
    })
    #print(value)
    Config.REDIS_CLIENT.setex(key, Config.REFRESH_TOKEN_EXPIRES, value)
    return token

def revoke_refresh_token(user_id, jti):
    key = f"refresh:{user_id}:{jti}"
    Config.REDIS_CLIENT.delete(key)

def is_refresh_token_valid(user_id, jti):
    key = f"refresh:{user_id}:{jti}"
    return Config.REDIS_CLIENT.exists(key)

