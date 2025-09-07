import traceback

from flask_restx import Namespace, Resource, fields
from flask import request, jsonify, g
from app.decorators.token_required import token_required
import boto3
import os
import json
from boto3.dynamodb.conditions import Attr

lambda_client = boto3.client('lambda')
plans_table = boto3.resource('dynamodb', region_name="us-east-1").Table(os.environ.get('PLANS_TABLE', 'Plans'))
users_table = boto3.resource('dynamodb', region_name="us-east-1").Table('Users')

import stripe
import os
from botocore.exceptions import ClientError
from app.config import Config

stripe.api_key = Config.STRIPE_SECRET_KEY
SNS_TOPIC_ARN = os.environ.get("CHECKOUT_STARTED_SNS", "arn:aws:sns:us-east-1:609717032481:StripeCheckoutStarted")
sns_client = boto3.client("sns", region_name="us-east-1")


api_ns = Namespace('api', description='General user APIs')

# --- Model for create_checkout ---
create_checkout_model = api_ns.model('CreateCheckout', {
    'userId': fields.String(required=True, description='User ID'),
    'email': fields.String(required=True, description='User email'),
    'planId': fields.String(required=True, description='UI-friendly plan name'),
})

def get_stripe_customer_id_by_email(email):
    table = users_table
    response = table.scan(
        FilterExpression=Attr("email").eq(email)
    )
    items = response.get("Items", [])
    if not items:
        return None
    return items[0].get("stripeCustomerId")

def create_checkout_session(email, price_id, user_id):
    try:
        stripe_customer_id = get_stripe_customer_id_by_email(email)
        print(f"Stripe customer id: {stripe_customer_id}")
        # Create Stripe Checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer=stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=Config.STRIPE_SUCCESS_URL,
            cancel_url=Config.STRIPE_CANCEL_URL,
            metadata={"userId": user_id, "planId": price_id}
        )
        return {"sessionId": session.id, "url": session.url}
    except Exception as e:
        print(f"❌ Failed to create checkout session for user {user_id}: {str(e)}")
        raise

def send_failure_sns(subject, message):
    import boto3
    topic_arn = os.environ.get("FAILURE_TOPIC_ARN", "arn:aws:sns:us-east-1:609717032481:CognitoLambdaFailures")
    boto3.client('sns').publish(TopicArn=topic_arn, Subject=subject, Message=message)

@api_ns.route('/create-checkout')
class CreateCheckout(Resource):
    @api_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <appToken>', 'required': True}})
    @api_ns.expect(create_checkout_model)
    @token_required
    def post(self):
        try:
            data = request.json
            print("CreateCheckout called with data:", data)  # Debugging line
            claims = getattr(g, 'user_claims', {})
            user_id = claims.get("user_id") or claims.get("sub")
            email = claims.get("email")
            plan_id = data.get("planId")
            print("CreateCheckout called with user_id:", user_id, "email:", email, "plan_id:", plan_id)  # Debugging line
            if not (user_id and email and plan_id):
                return jsonify({"error": "Missing parameters"}), 400
            resp = plans_table.get_item(Key={"planId": plan_id})
            print("DynamoDB response for planId:", resp)  # Debugging line
            if "Item" not in resp:
                return jsonify({"error": "Invalid planId"}), 404
            price_id = resp["Item"]["stripePriceId"]
            result = create_checkout_session(email=email, price_id=price_id, user_id=user_id)
            return result, 200
        except Exception as e:
            tb = traceback.format_exc()
            send_failure_sns("CreateCheckout Failure", f"{str(e)}\n{tb}")
            return jsonify({"error": "Internal server error"}), 500

@api_ns.route('/user-details')
class UserDetails(Resource):
    @api_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @token_required
    def get(self):
        claims = getattr(g, 'user_claims', {})
        print("User Claims:", claims)  # Debugging line
        email = claims.get('email')
        if not email:
            return {'error': 'Email or username not found in token'}, 400
        # Example: Fetch user details from database using email and username
        # Replace this with actual DB query logic
        user_details = {
            'name': 'John Doe',           # Replace with actual value from DB
            'phone_number': '+123456789', # Replace with actual value from DB
            'email': email,
            'plan_opted': 'Premium'       # Replace with actual value from DB
        }
        return {'user_details': user_details}, 200

@api_ns.route('/user-fruits')
class UserFruits(Resource):
    @api_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @token_required
    def get(self):
        claims = getattr(g, 'user_claims', {})
        email = claims.get('email')
        if not email:
            return {'error': 'Email or username not found in token'}, 400
        # Example: Fetch user's chosen fruits from database using email and username
        # Replace this with actual DB query logic
        fruits = ['Apple', 'Banana', 'Mango']  # Replace with actual value from DB
        return {'fruits': fruits}, 200
