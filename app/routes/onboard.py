import stripe
from flask import request
from flask_restx import Namespace, Resource, fields
from app.models.user import db, User
from app.config import Config

onboard_ns = Namespace('onboard', description='User onboarding and Stripe customer creation')

user_model = onboard_ns.model('User', {
    'user_id': fields.String(required=True, description='Unique user ID'),
    'name': fields.String(required=True, description='User name'),
    'email': fields.String(required=True, description='User email'),
})

    # Model for business account registration
business_account_model = onboard_ns.model('BusinessAccount', {
    'business_name': fields.String(required=True, description='Business name'),
    'email': fields.String(required=True, description='Business email'),
    'routing_number': fields.String(required=True, description='Bank routing number'),
    'account_number': fields.String(required=True, description='Bank account number'),
    'account_holder_name': fields.String(required=True, description='Account holder name'),
})


@onboard_ns.route('/register')
class UserOnboard(Resource):
    @onboard_ns.expect(user_model)
    def post(self):
        """Register a new user and create Stripe Customer"""
        data = request.json
        user_id = data.get('user_id')
        name = data.get('name')
        email = data.get('email')
        # if not user_id or not name or not email:
        #     return {'message': 'user_id, name, and email required'}, 400
        # if User.query.filter_by(email=email).first() or User.query.filter_by(user_id=user_id).first():
        #     return {'message': 'User already exists'}, 409
        # TODO: Save user in DB with user_id, name, email, and stripe_customer_id
        # For now, only create Stripe customer and return info
        stripe.api_key = Config.STRIPE_SECRET_KEY
        customer = stripe.Customer.create(email=email, name=name, metadata={'user_id': user_id})
        return {'message': 'User registered (DB save bypassed)', 'stripe_customer_id': customer['id']}, 201

