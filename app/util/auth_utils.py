
import time
import requests
from typing import Dict, Tuple, Optional
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from jose import JWTError
import base64
import jwt
from jose.utils import base64url_decode

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

# # App roles/claims enrichment (stub)
# def get_app_claims_from_db(claims: str) -> Dict:
#     # cognito_sub is actually the claims dict, not just the sub string
#     print("---",claims)
#     roles = claims.get("cognito:groups", [])
#     perms = []
#     # Add admin perms if user is in admin group
#     if any(str(role).lower() == "admin" for role in roles):
#         perms.extend(["write:dashboard", "manage:users"])
#     return {
#         "roles": roles,
#         "perms": perms
#     }

# App JWT issuance & verification
def issue_app_jwt(cognito_claims: Dict, extra_claims: Dict, app_jwt_secret, app_jwt_alg, app_jwt_ttl_seconds) -> str:
    now = int(time.time())
    payload = {
        "iss": "your-backend-service",
        "sub": cognito_claims["sub"],
        "email": cognito_claims.get("email"),
        "iat": now,
        "exp": now + app_jwt_ttl_seconds,
        "roles": extra_claims.get("roles", []),
        "perms": extra_claims.get("perms", []),
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