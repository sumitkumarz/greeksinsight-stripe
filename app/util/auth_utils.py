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
        audience=client_id
    )
    return claims, None

# App roles/claims enrichment (stub)
def get_app_claims_from_db(cognito_sub: str) -> Dict:
    roles = ["user"]
    perms = ["read:dashboard"]
    if cognito_sub.endswith("admin"):
        roles.append("admin")
        perms.extend(["write:dashboard", "manage:users"])
    return {
        "roles": roles,
        "perms": perms
    }

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
