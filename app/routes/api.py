# Protected test endpoints (after api_ns is defined)
from app.decorators.token_required import token_required


import traceback
from app.util.auth_utils import update_cognito_user_groups
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
from app.util.stripe_utils import (
    find_user_by_email_case_insensitive,
    find_plan_by_id_case_insensitive,
    ensure_stripe_customer,
    build_checkout_session_params,
    get_stripe_customer_id_by_email,
    send_failure_sns
)
create_checkout_model = api_ns.model('CreateCheckout', {
    'planId': fields.String(required=True, description='UI-friendly plan name'),
})

@api_ns.route('/create-checkout')
class CreateCheckout(Resource):
    @api_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <appToken>', 'required': True}})
    @api_ns.expect(create_checkout_model)
    @token_required
    def post(self):
        try:
            data = request.json
            claims = getattr(g, 'user_claims', {})
            user_id = claims.get("user_id") or claims.get("sub")
            email = claims.get("email")
            plan_id = data.get("planId")
            if not (user_id and email and plan_id):
                return {"error": "Missing parameters"}, 400
            user_item = find_user_by_email_case_insensitive(email)
            if user_item:
                payment_status = str(user_item.get("paymentStatus", "")).lower()
                subscription_status = str(user_item.get("subscriptionStatus", "")).lower()
                if payment_status == "paid" and subscription_status == "complete":
                    return {"error": "User already has an active subscription."}, 400
            plan_item = find_plan_by_id_case_insensitive(plan_id)
            print(plan_item)
            if not plan_item:
                return {"error": "Invalid planId"}, 404
            price_id = plan_item["stripePriceId"]
            print(price_id)
            try:
                stripe_customer_id = ensure_stripe_customer(user_item, email, user_id)
            except Exception as e:
                return {"error": str(e)}, 500
            print(f"Creating checkout session for user {email} with plan {plan_id} (price {price_id}), stripe customer {stripe_customer_id}")
            allowed_countries_env = Config.STRIPE_ALLOWED_COUNTRIES
            allowed_countries = [c.strip() for c in allowed_countries_env.split(',') if c.strip()]
            session_params = build_checkout_session_params(stripe_customer_id, price_id, user_id, allowed_countries)
            session_params["customer_update"] = {"shipping": "auto"}
            print("Checkout session params:", session_params)
            try:
                session = stripe.checkout.Session.create(**session_params)
                print("Created checkout session:", session)
                return {"sessionId": session.id, "url": session.url, "stripeCustomerId": stripe_customer_id}, 200
            except Exception as e:
                print("Stripe checkout error:", str(e))
                return {"error": f"Failed to create checkout session: {str(e)}"}, 500
        except Exception as e:
            tb = traceback.format_exc()
            send_failure_sns("CreateCheckout Failure", f"{str(e)}\n{tb}")
            print("Stripe checkout error:", str(e))
            return {"error": "Internal server error"}, 500


@api_ns.route('/user-details')
class UserDetails(Resource):
    @token_required
    def get(self):
        claims = getattr(g, 'user_claims', {})
        print(claims)
        print("User Claims:", claims)  # Debugging line
        email = claims.get('email')
        if not email:
            return {'error': 'Email or username not found in token'}, 400
        # Fetch user details from DynamoDB Users table using email
        response = users_table.scan(
            FilterExpression=Attr("email").eq(email)
        )
        items = response.get("Items", [])
        if not items:
            return {'error': 'User not found'}, 404
        user = items[0]
        user_details = {
            'name': user.get('name'),
            'email': user.get('email'),
            'planOpted': user.get('planOpted'),
            'cancelAt' : user.get('cancelAt'),
        }
        return {'user_details': user_details}, 200


@api_ns.route('/cancel-subscription')
class CancelSubscription(Resource):
    @api_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <appToken>', 'required': True}})
    @token_required
    def post(self):
        claims = getattr(g, 'user_claims', {})
        email = claims.get('email')
        if not email:
            return {"error": "Email not found in token"}, 400
        # Find user by case-insensitive email
        user_resp = users_table.scan()
        user_item = None
        for item in user_resp.get("Items", []):
            if item.get("email", "").lower() == email.lower():
                user_item = item
                break
        if not user_item:
            return {"error": "User not found"}, 404
        stripe_subscription_id = user_item.get("stripeSubscriptionId")
        if not stripe_subscription_id:
            return {"error": "No Stripe subscription found for user"}, 404
        try:
            # Cancel the subscription at Stripe
            cancel_resp = stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=True
            )
            

            return {"message": "Subscription canceled"}, 200
        except Exception as e:
            print("Stripe cancel error:", str(e))
            return {"error": str(e)}, 500

@api_ns.route('/data1')
class Data1(Resource):
    @token_required
    def get(self):
        return {"data": "This is data1", "user": getattr(g, 'user_claims', {})}, 200

@api_ns.route('/data2')
class Data2(Resource):
    @token_required
    def get(self):
        return {"data": "This is data2", "user": getattr(g, 'user_claims', {})}, 200

@api_ns.route('/data3')
class Data3(Resource):
    @token_required
    def get(self):
        return {"data": "This is data3", "user": getattr(g, 'user_claims', {})}, 200

@api_ns.route('/data4')
class Data4(Resource):
    @token_required
    def get(self):
        return {"data": "This is data4", "user": getattr(g, 'user_claims', {})}, 200

