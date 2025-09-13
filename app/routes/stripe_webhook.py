
import os
import json
import boto3
import stripe
import logging
import traceback
from flask import Blueprint, request, Response
from app.config import Config
from boto3.dynamodb.conditions import Attr
from decimal import Decimal
stripe.api_key = Config.STRIPE_SECRET_KEY
from boto3.dynamodb.conditions import Key

webhook_bp = Blueprint('stripe_webhook', __name__)


# Use Users and Plans tables from Config
users_table = Config.DYNAMODB_RESOURCE.Table('Users')
plans_table = Config.DYNAMODB_RESOURCE.Table(os.environ.get('PLANS_TABLE', 'Plans'))


# Import utility functions from stripe_utils
from app.util.stripe_utils import send_sns_notification, extract_subscription_details, handle_checkout_session_completed, handle_customer_subscription_deleted, handle_customer_subscription_updated


@webhook_bp.route('/payment/webhook', methods=['POST'])
def stripe_webhook():
    endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET') or getattr(Config, 'STRIPE_WEBHOOK_SECRET', None)
    payload = request.data
    print(f"Payload: {payload}")
    sig_header = request.headers.get('Stripe-Signature')
    print(f"Signature Header: {sig_header}")
    event = None
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except Exception as e:
        print(f"Webhook signature verification failed: {e}")
        send_sns_notification('Stripe Webhook Signature Error', f"{e}\n{traceback.format_exc()}")
        return Response('Webhook signature verification failed', status=400)

    print(f"Received Stripe event: {event['type']}")
    try:
        if event['type'] == 'checkout.session.completed':
            handle_checkout_session_completed(event, users_table, plans_table)
        elif event['type'] == 'customer.subscription.deleted':
            handle_customer_subscription_deleted(event, users_table)
        elif event['type'] == 'invoice.payment_failed':
            # TODO: Implement logic for payment failure (e.g., notify user, update status)
            logging.info(f"Handled invoice.payment_failed for event: {event}")
        elif event['type'] == 'customer.subscription.updated':
            handle_customer_subscription_updated(event, users_table, plans_table)
        logging.info(f"Processed Stripe event: {event['type']} for user(s)")
    except Exception as e:
        logging.error(f"Exception in webhook handler: {e}\n{traceback.format_exc()}")
        send_sns_notification(
            subject='❌ Stripe Webhook Exception',
            message=f"{e}\n{traceback.format_exc()}"
        )
        return Response('Webhook handler exception', status=400)
    return Response('Webhook received', status=200)
