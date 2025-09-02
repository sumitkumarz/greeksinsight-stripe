import stripe
from flask import request
from flask_restx import Namespace, Resource, fields
from app.config import Config
from datetime import datetime

membership_ns = Namespace('membership', description='Membership and subscription operations')

subscription_model = membership_ns.model('Subscription', {
    'stripe_customer_id': fields.String(required=True, description='Stripe customer ID'),
    'price_id': fields.String(required=True, description='Stripe Price ID for the plan'),
    'trial_period_days': fields.Integer(required=False, description='Free trial period in days'),
})

product_model = membership_ns.model('Product', {
    'name': fields.String(required=True, description='Product name'),
    'description': fields.String(required=False, description='Product description'),
})

price_model = membership_ns.model('Price', {
    'product_id': fields.String(required=True, description='Stripe Product ID'),
    'unit_amount': fields.Integer(required=True, description='Amount in cents'),
    'currency': fields.String(required=True, description='Currency, e.g. usd'),
    'recurring_interval': fields.String(required=True, description='Interval, e.g. month'),
})

checkout_session_model = membership_ns.model('CheckoutSession', {
    'stripe_customer_id': fields.String(required=True, description='Stripe customer ID'),
    'price_id': fields.String(required=True, description='Stripe Price ID for the plan'),
    'success_url': fields.String(required=True, description='URL to redirect after success'),
    'cancel_url': fields.String(required=True, description='URL to redirect after cancel'),
})

customer_id_model = membership_ns.model('CustomerIdQuery', {
    'username': fields.String(required=False, description='User ID (metadata)'),
    'email': fields.String(required=False, description='User email'),
})

update_price_model = membership_ns.model('UpdatePrice', {
    'nickname': fields.String(required=False, description='Price nickname'),
    'active': fields.Boolean(required=False, description='Active status'),
})

update_product_model = membership_ns.model('UpdateProduct', {
    'name': fields.String(required=False, description='Product name'),
    'description': fields.String(required=False, description='Product description'),
    'active': fields.Boolean(required=False, description='Active status'),
})

manage_subscription_model = membership_ns.model('ManageSubscription', {
    'cancel_at_period_end': fields.Boolean(required=False, description='Cancel at end of billing period (grace period)'),
    'pause': fields.Boolean(required=False, description='Pause subscription'),
    'resume': fields.Boolean(required=False, description='Resume subscription'),
})

refund_model = membership_ns.model('Refund', {
    'charge_id': fields.String(required=True, description='Stripe Charge ID to refund'),
    'amount': fields.Integer(required=False, description='Amount to refund in cents (optional, defaults to full)'),
    'reason': fields.String(required=False, description='Reason for refund'),
})

bank_account_model = membership_ns.model('BankAccount', {
    'customer_id': fields.String(required=True, description='Stripe Customer ID'),
    'account_number': fields.String(required=True, description='Bank account number'),
    'routing_number': fields.String(required=True, description='Bank routing number'),
    'account_holder_name': fields.String(required=True, description='Account holder name'),
    'account_holder_type': fields.String(required=True, description='Account holder type (individual/company)'),
})

business_bank_model = membership_ns.model('BusinessBankAccount', {
    'account_number': fields.String(required=True, description='Bank account number'),
    'routing_number': fields.String(required=True, description='Bank routing number'),
    'account_holder_name': fields.String(required=True, description='Account holder name'),
    'account_holder_type': fields.String(required=True, description='Account holder type (individual/company)'),
})

@membership_ns.route('/plans')
class MembershipPlans(Resource):
    def get(self):
        """List all membership plans (define in Stripe dashboard)"""
        return {'plans': []}  # TODO: Optionally fetch from Stripe API

@membership_ns.route('/subscribe')
class StartSubscription(Resource):
    @membership_ns.expect(subscription_model)
    def post(self):
        """Start a subscription for a user"""
        data = request.json
        stripe.api_key = Config.STRIPE_SECRET_KEY
        customer_id = data.get('stripe_customer_id')
        price_id = data.get('price_id')
        trial_days = data.get('trial_period_days')
        if not customer_id or not price_id:
            return {'message': 'stripe_customer_id and price_id required'}, 400
        params = {
            'customer': customer_id,
            'items': [{'price': price_id}],
            'expand': ['latest_invoice.payment_intent']
        }
        if trial_days:
            params['trial_period_days'] = trial_days
        subscription = stripe.Subscription.create(**params)
        # TODO: Save subscription['id'] in DB linked to user
        return {
            'message': 'Subscription started',
            'subscription_id': subscription['id'],
            'status': subscription['status']
        }, 201

@membership_ns.route('/status')
class MembershipStatus(Resource):
    def get(self):
        """Get user membership status (stub)"""
        return {'status': 'active'}

@membership_ns.route('/create-product')
class CreateProduct(Resource):
    @membership_ns.expect(product_model)
    def post(self):
        """Create a Stripe Product (admin only)"""
        data = request.json
        stripe.api_key = Config.STRIPE_SECRET_KEY
        product = stripe.Product.create(
            name=data['name'],
            description=data.get('description', '')
        )
        return {'product_id': product['id'], 'name': product['name']}, 201

@membership_ns.route('/create-price')
class CreatePrice(Resource):
    @membership_ns.expect(price_model)
    def post(self):
        """Create a Stripe Price for a Product (admin only)"""
        data = request.json
        stripe.api_key = Config.STRIPE_SECRET_KEY
        price = stripe.Price.create(
            product=data['product_id'],
            unit_amount=data['unit_amount'],
            currency=data['currency'],
            recurring={'interval': data['recurring_interval']}
        )
        return {'price_id': price['id'], 'unit_amount': price['unit_amount'], 'currency': price['currency']}, 201

@membership_ns.route('/create-checkout-session')
class CreateCheckoutSession(Resource):
    @membership_ns.expect(checkout_session_model)
    def post(self):
        """Create a Stripe Checkout Session for subscription payment"""
        data = request.json
        stripe.api_key = Config.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            customer=data['stripe_customer_id'],
            line_items=[{
                'price': data['price_id'],
                'quantity': 1
            }],
            mode='subscription',
            success_url=data['success_url'],
            cancel_url=data['cancel_url']
        )
        return {'checkout_session_id': session['id'], 'url': session['url']}

# New endpoint for checkout session with trial and optional fields
@membership_ns.route('/create-checkout-session-with-trial')
class CreateCheckoutSessionWithTrial(Resource):
    @membership_ns.expect(checkout_session_model)
    def post(self):
        """Create a Stripe Checkout Session for subscription with trial and optional fields"""
        data = request.json
        stripe.api_key = Config.STRIPE_SECRET_KEY
        line_items = [{
            'price': data['price_id'],
            'quantity': data.get('quantity', 1)
        }]
        subscription_data = {}
        # Optional trial period days
        if 'trial_period_days' in data:
            subscription_data['trial_period_days'] = data['trial_period_days']
        # Optional trial settings end behavior
        if 'trial_settings_end_behavior_missing_payment_method' in data:
            subscription_data['trial_settings'] = {
                'end_behavior': {
                    'missing_payment_method': data['trial_settings_end_behavior_missing_payment_method']
                }
            }
        session_params = {
            'mode': 'subscription',
            'line_items': line_items,
            'success_url': data['success_url'],
            'cancel_url': data['cancel_url'],
            'subscription_data': subscription_data
        }
        # Optional payment_method_collection
        if 'payment_method_collection' in data:
            session_params['payment_method_collection'] = data['payment_method_collection']
        # Optional customer
        if 'stripe_customer_id' in data:
            session_params['customer'] = data['stripe_customer_id']
        session = stripe.checkout.Session.create(**session_params)
        return {'checkout_session_id': session['id'], 'url': session['url']}

@membership_ns.route('/products')
class ListProducts(Resource):
    def get(self):
        """List all Stripe products"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        products = stripe.Product.list(limit=100)
        return {'products': products['data']}

@membership_ns.route('/prices')
class ListPrices(Resource):
    def get(self):
        """List all Stripe prices"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        prices = stripe.Price.list(limit=100)
        return {'prices': prices['data']}

@membership_ns.route('/product/<string:product_id>')
class ProductDetail(Resource):
    def get(self, product_id):
        """Get details of a specific Stripe product"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        product = stripe.Product.retrieve(product_id)
        return product
    @membership_ns.expect(update_product_model)
    def put(self, product_id):
        """Update a Stripe product's name, description, and active status"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        data = request.json
        update_fields = {}
        if 'name' in data:
            update_fields['name'] = data['name']
        if 'description' in data:
            update_fields['description'] = data['description']
        if 'active' in data:
            update_fields['active'] = data['active']
        updated = stripe.Product.modify(product_id, **update_fields)
        return {
            'product_id': updated['id'],
            'name': updated.get('name'),
            'description': updated.get('description'),
            'active': updated.get('active')
        }
    def delete(self, product_id):
        """Deactivate (soft-delete) a Stripe product"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        deleted = stripe.Product.modify(product_id, active=False)
        return {'deleted': deleted['id'], 'active': deleted['active']}

@membership_ns.route('/price/<string:price_id>')
class PriceDetail(Resource):
    def get(self, price_id):
        """Get details of a specific Stripe price"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        price = stripe.Price.retrieve(price_id)
        return price
    @membership_ns.expect(update_price_model)
    def put(self, price_id):
        """Update a Stripe price's nickname and active status (other fields cannot be changed)"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        data = request.json
        update_fields = {}
        if 'nickname' in data:
            update_fields['nickname'] = data['nickname']
        if 'active' in data:
            update_fields['active'] = data['active']
        updated = stripe.Price.modify(price_id, **update_fields)
        return {
            'price_id': updated['id'],
            'nickname': updated.get('nickname'),
            'active': updated.get('active')
        }
    def delete(self, price_id):
        """Deactivate a Stripe price (cannot delete, only deactivate)"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        deactivated = stripe.Price.modify(price_id, active=False)
        return {'price_id': deactivated['id'], 'active': deactivated['active']}

@membership_ns.route('/customer-id')
class GetCustomerId(Resource):
    @membership_ns.doc(params={
        'username': {'description': 'User ID (metadata)', 'in': 'query', 'type': 'string'},
        'email': {'description': 'User email', 'in': 'query', 'type': 'string'}
    })
    def get(self):
        """Get Stripe customer ID from username or email"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        username = request.args.get('username')
        email = request.args.get('email')
        query = {}
        if email:
            query['email'] = email
        customers = stripe.Customer.list(limit=100, **query)
        if username:
            filtered = [c for c in customers['data'] if c.get('metadata', {}).get('user_id') == username]
        else:
            filtered = customers['data']
        if filtered:
            return {'stripe_customer_id': filtered[0]['id']}
        return {'message': 'Customer not found'}, 404

@membership_ns.route('/membership-stats')
class MembershipStats(Resource):
    def get(self):
        """Get count of users by Stripe subscription status (all statuses, paginated)"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        status_counts = {}
        has_more = True
        starting_after = None
        while has_more:
            params = {'limit': 100}
            if starting_after:
                params['starting_after'] = starting_after
            subs = stripe.Subscription.list(**params)
            for sub in subs['data']:
                status = sub['status']
                status_counts[status] = status_counts.get(status, 0) + 1
            has_more = subs['has_more']
            if has_more:
                starting_after = subs['data'][-1]['id']
        return status_counts

@membership_ns.route('/checkout-session/<string:session_id>')
class CheckoutSessionStatus(Resource):
    def get(self, session_id):
        """Retrieve Stripe Checkout Session and payment status"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            'id': session['id'],
            'payment_status': session['payment_status'],
            'status': session['status'],
            'customer': session.get('customer'),
            'subscription': session.get('subscription'),
            'amount_total': session.get('amount_total'),
            'currency': session.get('currency')
        }
@membership_ns.route('/subscription/<string:subscription_id>/manage')
class ManageSubscription(Resource):
    @membership_ns.expect(manage_subscription_model)
    def post(self, subscription_id):
        """Cancel, pause, or resume a Stripe subscription"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        data = request.json
        result = {}
        if data.get('pause'):
            updated = stripe.Subscription.modify(subscription_id, pause_collection={'behavior': 'keep_as_draft'})
            result['paused'] = True
        elif data.get('resume'):
            updated = stripe.Subscription.modify(subscription_id, pause_collection='')
            result['resumed'] = True
        elif 'cancel_at_period_end' in data:
            updated = stripe.Subscription.modify(subscription_id, cancel_at_period_end=data['cancel_at_period_end'])
            result['cancel_at_period_end'] = data['cancel_at_period_end']
        else:
            updated = stripe.Subscription.delete(subscription_id)
            result['canceled'] = True
        result['subscription'] = updated
        return result

@membership_ns.route('/invoices')
class UserInvoices(Resource):
    @membership_ns.doc(params={
        'stripe_customer_id': {'description': 'Stripe customer ID', 'in': 'query', 'type': 'string'}
    })
    def get(self):
        """Get invoice details for a Stripe customer"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        customer_id = request.args.get('stripe_customer_id')
        if not customer_id:
            return {'message': 'stripe_customer_id required'}, 400
        invoices = stripe.Invoice.list(customer=customer_id, limit=100)
        return {'invoices': invoices['data']}

@membership_ns.route('/invoice/<string:invoice_id>/pdf')
class DownloadInvoicePDF(Resource):
    def get(self, invoice_id):
        """Download Stripe invoice as PDF by invoice ID"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        invoice = stripe.Invoice.retrieve(invoice_id)
        pdf_url = invoice.get('invoice_pdf')
        if not pdf_url:
            return {'message': 'PDF not available for this invoice'}, 404
        return {'invoice_id': invoice_id, 'pdf_url': pdf_url}

@membership_ns.route('/account/balance')
class AccountBalance(Resource):
    def get(self):
        """Retrieve Stripe account balance (available vs pending)"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        balance = stripe.Balance.retrieve()
        return {
            'available': balance['available'],
            'pending': balance['pending']
        }

@membership_ns.route('/account/balance/total')
class AccountTotalBalance(Resource):
    @membership_ns.doc(params={
        'currency': {'description': 'Currency code (e.g. usd, eur)', 'in': 'query', 'type': 'string'}
    })
    def get(self):
        """Show total Stripe account balance in selected currency"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        currency = request.args.get('currency', 'usd').lower()
        balance = stripe.Balance.retrieve()
        total = 0
        for entry in balance['available']:
            if entry['currency'] == currency:
                total += entry['amount']
        for entry in balance['pending']:
            if entry['currency'] == currency:
                total += entry['amount']
        return {
            'currency': currency,
            'total_balance': total / 100  # convert cents to major unit
        }

@membership_ns.route('/account/payouts')
class AccountPayouts(Resource):
    def get(self):
        """List Stripe account payouts"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        payouts = stripe.Payout.list(limit=100)
        return {'payouts': payouts['data']}

@membership_ns.route('/account/transactions')
class AccountTransactions(Resource):
    def get(self):
        """List Stripe account transactions (charges, refunds, payouts)"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        charges = stripe.Charge.list(limit=100)
        refunds = stripe.Refund.list(limit=100)
        payouts = stripe.Payout.list(limit=100)
        return {
            'charges': charges['data'],
            'refunds': refunds['data'],
            'payouts': payouts['data']
        }

@membership_ns.route('/account/pending-availability')
class PendingAvailability(Resource):
    def get(self):
        """Show estimated availability dates for pending funds"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        balance = stripe.Balance.retrieve()
        pending_info = []
        for entry in balance['pending']:
            pending_info.append({
                'amount': entry['amount'] / 100,
                'currency': entry['currency'],
                'source_types': entry.get('source_types'),
                'available_on': entry.get('available_on')  # Unix timestamp
            })
        return {'pending_funds': pending_info}

@membership_ns.route('/account/payout-schedule')
class PayoutSchedule(Resource):
    def get(self):
        """Show Stripe account payout schedule settings"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        account = stripe.Account.retrieve()
        payout_schedule = account.get('settings', {}).get('payouts', {})
        return {'payout_schedule': payout_schedule}

@membership_ns.route('/refund')
class Refund(Resource):
    @membership_ns.expect(refund_model)
    def post(self):
        """Refund money to a customer for a charge"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        data = request.json
        refund_params = {
            'charge': data['charge_id']
        }
        if 'amount' in data and data['amount']:
            refund_params['amount'] = data['amount']
        if 'reason' in data and data['reason']:
            refund_params['reason'] = data['reason']
        refund = stripe.Refund.create(**refund_params)
        return {'refund_id': refund['id'], 'status': refund['status'], 'amount': refund['amount']}

@membership_ns.route('/charges')
class ListCharges(Resource):
    @membership_ns.doc(params={
        'stripe_customer_id': {'description': 'Stripe customer ID', 'in': 'query', 'type': 'string'}
    })
    def get(self):
        """List charges for a Stripe customer to get charge IDs"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        customer_id = request.args.get('stripe_customer_id')
        if not customer_id:
            return {'message': 'stripe_customer_id required'}, 400
        charges = stripe.Charge.list(customer=customer_id, limit=100)
        return {'charges': charges['data']}

@membership_ns.route('/customer/<string:customer_id>/transactions')
class CustomerTransactions(Resource):
    @membership_ns.doc(params={
        'start_date': {'description': 'Start date (YYYY-MM-DD)', 'in': 'query', 'type': 'string'},
        'end_date': {'description': 'End date (YYYY-MM-DD)', 'in': 'query', 'type': 'string'},
        'type': {'description': 'Transaction type (charge, refund)', 'in': 'query', 'type': 'string'}
    })
    def get(self, customer_id):
        """Get last 10 transactions for a customer, filter by date or type"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        tx_type = request.args.get('type')
        charges = stripe.Charge.list(customer=customer_id, limit=100)
        refunds = stripe.Refund.list(limit=100)
        filtered_charges = charges['data']
        filtered_refunds = refunds['data']
        if start_date:
            start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp())
            filtered_charges = [c for c in filtered_charges if c['created'] >= start_ts]
            filtered_refunds = [r for r in filtered_refunds if r['created'] >= start_ts]
        if end_date:
            end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp())
            filtered_charges = [c for c in filtered_charges if c['created'] <= end_ts]
            filtered_refunds = [r for r in filtered_refunds if r['created'] <= end_ts]
        if tx_type == 'charge':
            return {'charges': filtered_charges[:10]}
        elif tx_type == 'refund':
            customer_refunds = [r for r in filtered_refunds if r.get('charge') in [c['id'] for c in filtered_charges]]
            return {'refunds': customer_refunds[:10]}
        else:
            customer_refunds = [r for r in filtered_refunds if r.get('charge') in [c['id'] for c in filtered_charges]]
            return {
                'charges': filtered_charges[:10],
                'refunds': customer_refunds[:10]
            }

@membership_ns.route('/refund-summary')
class RefundSummary(Resource):
    @membership_ns.doc(params={
        'stripe_customer_id': {'description': 'Stripe customer ID', 'in': 'query', 'type': 'string'},
        'start_date': {'description': 'Start date (YYYY-MM-DD)', 'in': 'query', 'type': 'string'},
        'end_date': {'description': 'End date (YYYY-MM-DD)', 'in': 'query', 'type': 'string'}
    })
    def get(self):
        """Display refund summary and balance changes for a customer, filter by date"""
        stripe.api_key = Config.STRIPE_SECRET_KEY
        customer_id = request.args.get('stripe_customer_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        if not customer_id:
            return {'message': 'stripe_customer_id required'}, 400
        refunds = stripe.Refund.list(limit=100)
        filtered_refunds = refunds['data']
        if start_date:
            start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp())
            filtered_refunds = [r for r in filtered_refunds if r['created'] >= start_ts]
        if end_date:
            end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp())
            filtered_refunds = [r for r in filtered_refunds if r['created'] <= end_ts]
        customer_refunds = [r for r in filtered_refunds if r.get('charge') and stripe.Charge.retrieve(r['charge'])['customer'] == customer_id]
        total_refunded = sum(r['amount'] for r in customer_refunds)
        return {
            'total_refunded': total_refunded / 100,
            'refund_count': len(customer_refunds),
            'refunds': customer_refunds
        }

