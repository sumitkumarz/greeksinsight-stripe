import os
import json
import boto3
import stripe
import logging
import traceback
from flask import Blueprint, request, Response
from app.config import Config
from boto3.dynamodb.conditions import Attr
stripe.api_key = Config.STRIPE_SECRET_KEY

webhook_bp = Blueprint('stripe_webhook', __name__)

def get_dynamodb_table():
    dynamodb = boto3.resource('dynamodb', region_name="us-east-1")
    return dynamodb.Table('Users')

def send_sns_notification(subject, message):
    sns = boto3.client('sns')
    topic_arn = os.environ.get('SNS_TOPIC_ARN') or getattr(Config, 'SNS_TOPIC_ARN', None)
    if topic_arn:
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=message)

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
        table = get_dynamodb_table()
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            session_data = event['data']
            stripe_customer_id = session.get('customer')
            stripe_subscription_id = session.get('subscription')
            invoice = session_data.get('invoice')
            amount_total = session.get('amount_total')
            currency = session.get('currency')
            subscription_id = session_data.get('subscription')
            payment_status = session_data.get('payment_status')
            subscription_status = session_data.get('status')
            print(f"Processing checkout.session.completed for customer_id: {stripe_customer_id}, subscription_id: {stripe_subscription_id}")
            response = table.scan(
                FilterExpression=Attr("stripeCustomerId").eq(stripe_customer_id)
            )
            items = response.get("Items", [])

            if items:
                user_item = items[0]
                user_id = user_item["userId"]  # assumes userId is the partition key

                # ✅ Update with all relevant Stripe session data
                table.update_item(
                    Key={"userId": user_id},
                    UpdateExpression="SET stripeSubscriptionId = :s, subscriptionStatus = :st, invoice = :i, amountTotal = :a, currency = :c, paymentStatus = :p, subscriptionId = :subid",
                    ExpressionAttributeValues={
                        ":s": stripe_subscription_id,
                        ":st": "active",
                        ":i": invoice,
                        ":a": amount_total,
                        ":c": currency,
                        ":p": payment_status,
                        ":subid": subscription_id,
                    },
                )
                print(f"Updated subscription for userId={user_id} with invoice, amount, currency, payment status, and subscription id.")
            else:
                print(f"No user found for stripeCustomerId={stripe_customer_id}")
        elif event['type'] == 'invoice.payment_failed':
            invoice = event['data']['object']
            stripe_customer_id = invoice.get('customer')
            # Find user by stripeCustomerId
            response = table.scan(
                FilterExpression='stripeCustomerId = :c',
                ExpressionAttributeValues={':c': stripe_customer_id}
            )
            for item in response.get('Items', []):
                table.update_item(
                    Key={'userId': item['userId']},
                    UpdateExpression="SET subscriptionStatus=:st",
                    ExpressionAttributeValues={':st': 'past_due'}
                )
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            stripe_customer_id = subscription.get('customer')
            response = table.scan(
                FilterExpression='stripeCustomerId = :c',
                ExpressionAttributeValues={':c': stripe_customer_id}
            )
            for item in response.get('Items', []):
                table.update_item(
                    Key={'userId': item['userId']},
                    UpdateExpression="SET subscriptionStatus=:st",
                    ExpressionAttributeValues={':st': 'canceled'}
                )
        # Log all events
        logging.info(f"Processed Stripe event: {event['type']} for user(s)")
    except Exception as e:
        logging.error(f"Exception in webhook handler: {e}\n{traceback.format_exc()}")
        send_sns_notification('Stripe Webhook Exception', f"{e}\n{traceback.format_exc()}")
        return Response('Webhook handler exception', status=400)
    return Response('Webhook received', status=200)
