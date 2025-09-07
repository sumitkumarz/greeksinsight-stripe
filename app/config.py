
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    COGNITO_DOMAIN = os.environ.get('COGNITO_DOMAIN')
    CLIENT_ID = os.environ.get('CLIENT_ID')
    JWKS_URL = f"https://cognito-idp.{os.environ.get('COGNITO_REGION')}.amazonaws.com/{os.environ.get('USER_POOL_ID')}/.well-known/jwks.json"
    CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
    REDIRECT_URI = os.environ.get('REDIRECT_URI')
    USER_POOL_ID = os.environ.get('USER_POOL_ID')
    APP_JWT_SECRET = os.environ.get('APP_JWT_SECRET')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    SWAGGER_UI_DOC_EXPANSION = 'list'
    RESTX_MASK_SWAGGER = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS') == 'True'
    FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
    STRIPE_SUCCESS_URL = os.environ.get('STRIPE_SUCCESS_URL', f"{FRONTEND_URL}/dashboard")
    STRIPE_CANCEL_URL = os.environ.get('STRIPE_CANCEL_URL', f"{FRONTEND_URL}")
