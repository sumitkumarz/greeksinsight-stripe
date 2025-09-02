from flask import Flask
from flask_restx import Api
from app.routes.membership import membership_ns
from app.routes.onboard import onboard_ns
from flask_sqlalchemy import SQLAlchemy
from app.models.user import db

api = Api(title='Stripe Membership API', version='1.0', description='API for membership management with Stripe integration')

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')
    db.init_app(app)
    api.init_app(app)
    api.add_namespace(membership_ns)
    api.add_namespace(onboard_ns)
    return app
