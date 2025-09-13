from flask import Flask
from flask_restx import Api
from app.routes.membership import membership_ns
from flask_sqlalchemy import SQLAlchemy
from app.models.user import db
from flask_cors import CORS
api = Api(title='Stripe Membership API', version='1.0', description='API for membership management with Stripe integration')

def create_app():
    from app.routes.auth import auth_ns
    from app.routes.api import api_ns
    from app.routes.stripe_webhook import webhook_bp
    from app.routes.admin import admin_ns
    api.add_namespace(auth_ns)
    api.add_namespace(api_ns)
    app = Flask(__name__)
    CORS(app, origins="*", supports_credentials=True, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    app.config.from_object('app.config.Config')
    db.init_app(app)
    api.init_app(app)
    api.add_namespace(membership_ns)
    api.add_namespace(admin_ns)
    app.register_blueprint(webhook_bp)
    return app
