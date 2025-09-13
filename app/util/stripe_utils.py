
from app.util.cognito_utils import add_user_to_group, remove_user_from_group
from decimal import Decimal
import os
import stripe
from app.config import Config
import boto3
import json
import logging
from app.util.plan_groups import SUBSCRIPTION_GROUPS, UNSUBSCRIBED_GROUP
from boto3.dynamodb.conditions import Attr
from app.config import Config
# Utility: Calculate next renewal date from Stripe subscription id
def get_next_renewal_date(stripe_subscription_id):
    if not stripe_subscription_id:
        return ''
    try:
        sub_obj = stripe.Subscription.retrieve(stripe_subscription_id)
        period_end = sub_obj.get('current_period_end')
        if period_end:
            import datetime
            return datetime.datetime.utcfromtimestamp(period_end).strftime('%Y-%m-%d')
    except Exception as e:
        print(f"Error fetching subscription for next renewal: {e}")
    return ''
# Utility: Get dashboard link for user
def get_dashboard_link(user_id=None):
    # Optionally use user_id for personalized dashboard
    return "https://greeksinsight.com/dashboard"

# Utility: Get invoice link for a given invoice id
def get_invoice_link(invoice_id):
    if not invoice_id:
        return None
    try:
        invoice_obj = stripe.Invoice.retrieve(invoice_id)
        return invoice_obj.get('invoice_pdf')
    except Exception as e:
        print(f"Error retrieving invoice PDF: {e}")
        return None

# Utility: Send SES templated email
def send_subscription_confirmation_email(to_email, user_name, plan_name, amount, currency, next_renewal, dashboard_link, invoice_link):
    import boto3
    ses_client = boto3.client('ses')
    template_data = {
        "userName": user_name,
        "planName": plan_name,
        "amount": str(amount),
        "currency": currency,
        "nextRenewal": next_renewal,
        "dashboardLink": dashboard_link,
        "invoiceLink": invoice_link
    }
    try:
        ses_client.send_templated_email(
            Source="no-reply@greeksinsight.com",
            Destination={"ToAddresses": [to_email]},
            Template="subscription_confirmation",
            TemplateData=json.dumps(template_data)
        )
        print(f"Subscription confirmation email sent to {to_email}")
    except Exception as e:
        print(f"Error sending subscription confirmation email: {e}")
# Utility: Get invoice PDF link from Stripe
def get_invoice_pdf_link(invoice_id):
    if not invoice_id:
        return None
    try:
        invoice_obj = stripe.Invoice.retrieve(invoice_id)
        return invoice_obj.get('invoice_pdf')
    except Exception as e:
        print(f"Error retrieving invoice PDF: {e}")
        return None
# Utility: Find user by email (case-insensitive)
def find_user_by_email_case_insensitive(email):
    user_resp = Config.USERS_TABLE.scan()
    for item in user_resp.get("Items", []):
        if item.get("email", "").lower() == email.lower():
            return item
    return None
# Utility: Convert unix epoch time to ISO 8601 timestamp string
def epoch_to_timestamp(epoch):
    if not epoch:
        return None
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(int(epoch)).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        print(f"Error converting epoch to timestamp: {e}")
        return None

# Utility: Find plan by id (case-insensitive)
def find_plan_by_id_case_insensitive(plan_id):
    scan_resp = Config.PLANS_TABLE.scan()
    for item in scan_resp.get("Items", []):
        if item.get("planId", "").lower() == plan_id.lower():
            return item
    return None

# Utility: Ensure Stripe customer exists for user
def ensure_stripe_customer(user_item, email, user_id):
    stripe_customer_id = user_item.get("stripeCustomerId") if user_item else None
    print("Existing stripe_customer_id:", stripe_customer_id)
    if not stripe_customer_id:
        try:
            customer = stripe.Customer.create(
                email=email,
                metadata={"user_id": user_id}
            )
            stripe_customer_id = customer["id"]
            if user_item:
                Config.USERS_TABLE.update_item(
                    Key={"userId": user_item["userId"]},
                    UpdateExpression="SET stripeCustomerId=:cid",
                    ExpressionAttributeValues={":cid": stripe_customer_id}
                )
        except Exception as e:
            raise Exception(f"Failed to create Stripe customer: {str(e)}")
    return stripe_customer_id

# Utility: Build Stripe checkout session params
def build_checkout_session_params(stripe_customer_id, price_id, user_id, allowed_countries):
    return {
        "payment_method_types": ["card"],
        "mode": "subscription",
        "customer": stripe_customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": Config.STRIPE_SUCCESS_URL,
        "cancel_url": Config.STRIPE_CANCEL_URL,
        "metadata": {"userId": user_id, "planId": price_id},
        "billing_address_collection": "required",
        "shipping_address_collection": {
            "allowed_countries": allowed_countries
        },
        "automatic_tax": {"enabled": True},
        "customer_update":{"shipping": "auto"}
    }

# Utility: Get Stripe customer id by email
def get_stripe_customer_id_by_email(users_table, email):
    from boto3.dynamodb.conditions import Attr
    response = users_table.scan(
        FilterExpression=Attr("email").eq(email)
    )
    items = response.get("Items", [])
    if not items:
        return None
    return items[0].get("stripeCustomerId")

# Utility: Send failure SNS notification
def send_failure_sns(subject, message):
    Config.SNS_CLIENT.publish(TopicArn=Config.FAILURE_TOPIC_ARN, Subject=subject, Message=message)

# General SNS notification for Stripe events
def send_sns_notification(subject, message):
    Config.SNS_CLIENT.publish(TopicArn=Config.CHECKOUT_STARTED_SNS, Subject=subject, Message=message)

# Extract product_id, price_id, and payment_id from a Stripe subscription object
def extract_subscription_details(subscription):
    product_id = None
    price_id = None
    payment_id = None
    items = subscription.get('items', {}).get('data', [])
    default_payment_method = subscription.get('default_payment_method', None)
    if items:
        price = items[0].get('price') or items[0].get('plan')
        if price:
            price_id = price.get('id')
            product_id = price.get('product')
    return product_id, price_id, default_payment_method

def handle_checkout_session_completed(event, users_table, plans_table):
    session = event['data']['object']
    stripe_customer_id = session.get('customer')
    stripe_subscription_id = session.get('subscription')
    customer_email = session.get('customer_details').get('email') if session.get('customer_details') else None
    invoice = session.get('invoice')
    invoice_pdf = get_invoice_pdf_link(invoice)
    amount_total = session.get('amount_total')
    if amount_total is not None:
        amount_total = Decimal(str(amount_total)) / Decimal('100')
    currency = session.get('currency')
    payment_status = session.get('payment_status')
    subscription_status = session.get('status')
    print(f"Processing checkout.session.completed for customer_id: {stripe_customer_id}, subscription_id: {stripe_subscription_id}, subscription_status: {subscription_status}, email: {customer_email} ")
    print(f"Amount total: {amount_total}, Currency: {currency}, Payment status: {payment_status}, Invoice: {invoice}")
    # Fetch productId, priceId, and default_payment_method from Stripe subscription
    productId = priceId = default_payment_method = payment_method_details = plan_name = None
    plan_id = None
    plan_name = "unsubscribed"
    if stripe_subscription_id:
        try:
            subscription_obj = stripe.Subscription.retrieve(stripe_subscription_id)
            productId, priceId, default_payment_method = extract_subscription_details(subscription_obj)
            # Fetch payment method details if available
            if default_payment_method:
                try:
                    payment_method_details = stripe.PaymentMethod.retrieve(default_payment_method)
                except Exception as e:
                    print(f"Error retrieving payment method details: {e}")
            # Fetch plan_name from Plans table using priceId
            if priceId:
                plan_resp = plans_table.scan()
                for item in plan_resp.get("Items", []):
                    if item.get("stripePriceId", "") == priceId:
                        plan_id = item.get("planId")
                        plan_name = item.get("planGroup", "unsubscribed")
                        break
                if not plan_name:
                    plan_name = "unsubscribed"
        except Exception as e:
            print(f"Error retrieving subscription details: {e}")
    # Try to fetch by case-insensitive email, fallback to stripeCustomerId if not found
    items = []
    if customer_email:
        scan_resp = users_table.scan()
        for item in scan_resp.get("Items", []):
            if item.get("email", "").lower() == customer_email.lower():
                items = [item]
                break
    if not items and stripe_customer_id:
        response = users_table.scan(
            FilterExpression=Attr("stripeCustomerId").eq(stripe_customer_id)
        )
        items = response.get("Items", [])
    if items:
        user_item = items[0]
        user_id = user_item["userId"]  # assumes userId is the partition key
        # Extract selected payment method fields
        payment_method_summary = None
        if payment_method_details:
            try:
                card = payment_method_details.get('card', {})
                billing = payment_method_details.get('billing_details', {})
                payment_method_summary = {
                    'country': card.get('country'),
                    'postal_code': billing.get('address', {}).get('postal_code'),
                    'brand': card.get('brand'),
                    'funding': card.get('funding'),
                    'last4': card.get('last4'),
                    'exp_month': card.get('exp_month'),
                    'exp_year': card.get('exp_year'),
                    'type': payment_method_details.get('type'),
                }
            except Exception as e:
                print(f"Error extracting payment method summary: {e}")
        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET stripeSubscriptionId = :s, subscriptionStatus = :st, invoice = :i, invoicePdf = :ipdf, amountTotal = :a, currency = :c, paymentStatus = :p, productId = :prod, priceId = :price, paymentId = :pay, paymentMethodSummary = :pms, planOpted = :plan, planId = :plan_id, groups = :grps",
            ExpressionAttributeValues={
                ":s": stripe_subscription_id,
                ":st": subscription_status,
                ":i": invoice,
                ":ipdf": invoice_pdf,
                ":a": amount_total,
                ":c": currency,
                ":p": payment_status,
                ":prod": productId,
                ":price": priceId,
                ":pay": default_payment_method,
                ":pms": payment_method_summary,
                ":plan": plan_name,
                ":plan_id": plan_id,
                ":grps": [plan_name]
            },
        )
        print(f"Updated subscription for userId={user_id} with invoice, amount, currency, payment status, subscription id, planOpted={plan_name}, and invoicePdf={invoice_pdf}.")
        # Update Cognito groups
        try:
            user_name = user_item.get('userName') or user_item.get('username') or user_item.get('email')
            remove_user_from_group(user_name, 'unsubscribed')
            print(f"Adding user {user_name} to Cognito group {plan_name}")
            add_user_to_group(user_name, plan_name)
        except Exception as e:
            print(f"Error updating Cognito groups: {e}")
        send_sns_notification(
            subject="✅ Stripe Webhook Success",
            message=f"checkout.session.completed processed for userId={user_id}, customerId={stripe_customer_id}, subscriptionId={stripe_subscription_id}, planOpted={plan_name}"
        )
        # Send SES subscription confirmation email
        try:
            next_renewal = get_next_renewal_date(stripe_subscription_id)
            send_subscription_confirmation_email(
                to_email=customer_email,
                user_name=user_item.get('userName') or user_item.get('username') or customer_email,
                plan_name=plan_name,
                amount=amount_total,
                currency=currency,
                next_renewal=next_renewal,
                dashboard_link=get_dashboard_link(user_id),
                invoice_link=get_invoice_link(invoice)
            )
        except Exception as e:
            print(f"Error in SES email logic: {e}")

def handle_customer_subscription_deleted(event, users_table):
    subscription = event['data']['object']
    stripe_customer_id = subscription.get('customer')
    subscription_status = subscription.get('status', 'canceled')
    cancelAtPeriodEnd = subscription.get('cancel_at_period_end')
    cancelAt = epoch_to_timestamp(subscription.get('cancel_at'))
    canceledAt = epoch_to_timestamp(subscription.get('canceled_at'))
    
    response = users_table.scan(
        FilterExpression=Attr("stripeCustomerId").eq(stripe_customer_id)
    )
    for item in response.get('Items', []):
        # Only set unsubscribed if not (active and cancel_at_period_end==True)
        if not (subscription_status == 'active' and cancelAtPeriodEnd):
            users_table.update_item(
                Key={'userId': item['userId']},
                UpdateExpression="SET subscriptionStatus=:st, #groups=:g, cancelAtPeriodEnd=:cape, cancelAt=:ca, canceledAt=:cat",
                ExpressionAttributeNames={"#groups": "groups"},
                ExpressionAttributeValues={
                    ':st': subscription_status,
                    ':g': [UNSUBSCRIBED_GROUP],
                    ':cape': cancelAtPeriodEnd,
                    ':ca': cancelAt,
                    ':cat': canceledAt
                }
            )
            # Remove user from all groups and add to 'unsubscribed'
            user_name = item.get('userName') or item.get('username') or item.get('email')
            try:
                # Remove from all known plan groups except 'unsubscribed'
                for group in SUBSCRIPTION_GROUPS:
                    remove_user_from_group(user_name, group)
                # Add to 'unsubscribed' group
                add_user_to_group(user_name, UNSUBSCRIBED_GROUP)
            except Exception as e:
                print(f"Error updating Cognito groups on subscription deleted: {e}")
    send_sns_notification(
        subject="⚠️ Stripe Subscription Deleted",
        message=f"customer.subscription.deleted for customerId={stripe_customer_id}, userIds={[item['userId'] for item in response.get('Items', [])]}"
    )



def handle_customer_subscription_updated(event, users_table, plans_table):
    """
    Handles the Stripe event 'customer.subscription.updated'.
    Updates user's plan, subscription status, and Cognito group in users_table.
    """
    from boto3.dynamodb.conditions import Attr
    subscription = event['data']['object']
    stripe_customer_id = subscription.get('customer')
    subscription_status = subscription.get('status')
    cancelAtPeriodEnd = subscription.get('cancel_at_period_end')
    canceledAt = epoch_to_timestamp(subscription.get('canceled_at'))
    cancelAt = epoch_to_timestamp(subscription.get('cancel_at'))
    endedAt = epoch_to_timestamp(subscription.get('ended_at'))
    
    response = users_table.scan(
        FilterExpression=Attr("stripeCustomerId").eq(stripe_customer_id)
    )
    for item in response.get('Items', []):
        user_id = item['userId']
        update_expr = "SET subscriptionStatus=:st, planOpted=:plan, cancelAtPeriodEnd=:cape, endedAt=:ea, cancelAt=:cat, canceledAt=:cdat"
        expr_attr_vals = {
            ':st': subscription_status,
            ':plan': UNSUBSCRIBED_GROUP,
            ':cape': cancelAtPeriodEnd,
            ':cdat': canceledAt,
            ':cat': cancelAt,
            ':ea': endedAt
        }
        # If status=active and cancelAtPeriodEnd=true, mark user as scheduled_cancel
        scheduled_cancel = False
        if subscription_status == 'active' and cancelAtPeriodEnd:
            update_expr += ", scheduledCancel=:sc"
            expr_attr_vals[':sc'] = True
            scheduled_cancel = True
        else:
            update_expr += ", scheduledCancel=:sc"
            expr_attr_vals[':sc'] = False
        users_table.update_item(
            Key={'userId': user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attr_vals
        )
        # Only update Cognito groups if not scheduled_cancel
        if not scheduled_cancel:
            user_name = item.get('userName') or item.get('username') or item.get('email')
            try:
                
                for group in SUBSCRIPTION_GROUPS:
                    remove_user_from_group(user_name, group)
                add_user_to_group(user_name, UNSUBSCRIBED_GROUP)
            except Exception as e:
                logging.error(f"Error updating Cognito groups on subscription updated: {e}")
   
    logging.info(f"Handled customer.subscription.updated for event: {event}")