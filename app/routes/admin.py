
import uuid
import time
from flask_restx import Namespace, Resource, fields
from flask import request, g
from app.decorators.token_required import token_required
import stripe
from app.config import Config

# Stripe + DynamoDB clients
stripe.api_key = Config.STRIPE_SECRET_KEY
plans_table = Config.DYNAMODB_RESOURCE.Table("Plans")
coupons_table = Config.DYNAMODB_RESOURCE.Table("Coupons")

admin_ns = Namespace("admin", description="Admin operations")

from app.decorators.requires_role import admin_required

# -------------------------
# Link or Unlink Coupon to Plan (Merged)
# -------------------------
link_or_unlink_coupon_model = admin_ns.model("LinkOrUnlinkCoupon", {
    "planId": fields.String(required=True),
    "couponId": fields.String(required=False, description="If provided, link coupon; if omitted or null, unlink coupon."),
})

add_coupon_model = admin_ns.model("AddCoupon", {
    "couponCode": fields.String(required=True),
    "discountType": fields.String(required=True, enum=["percentage", "amount"]),
    "percentOff": fields.Integer(required=False),
    "duration": fields.String(required=True, enum=["once", "repeating", "forever"]),
    "applicablePlans": fields.List(fields.String, required=False),
})


# -------------------------
# Add Plan Endpoint
# -------------------------
add_plan_model = admin_ns.model("AddPlan", {
    "productName": fields.String(required=True),
    "productDescription": fields.String(required=True),
    "planGroup": fields.String(required=False, description="Optional grouping for plans", enum=["pro", "premium"]),
    "priceNickname": fields.String(required=True),
    "amount": fields.Integer(required=True, description="Price in cents"),
    "currency": fields.String(required=True, default="usd"),
    "frequency": fields.String(required=True, enum=["month"]),
    "couponId": fields.String(required=False, description="Optional couponId to link"),
})

update_plan_model = admin_ns.model("UpdatePlan", {
    "planId": fields.String(required=True),
    "productName": fields.String(required=False),
    "productDescription": fields.String(required=False),
    "priceNickname": fields.String(required=False),
    "amount": fields.Integer(required=False),
    "currency": fields.String(required=False),
    "frequency": fields.String(required=False, enum=["month"]),
    "active": fields.Boolean(required=False),
    "couponId": fields.String(required=False),
})

update_coupon_model = admin_ns.model("UpdateCoupon", {
    "couponId": fields.String(required=True),
    "couponCode": fields.String(required=False),
    "discountType": fields.String(required=False, enum=["percentage"]),
    "percentOff": fields.Integer(required=False),
    "duration": fields.String(required=False, enum=["once"]),
    "active": fields.Boolean(required=False),
    "applicablePlans": fields.List(fields.String, required=False)
})


@admin_ns.route("/update-plan")
class UpdatePlan(Resource):
    @admin_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @admin_ns.expect(update_plan_model)
    @admin_required
    def post(self):
        data = request.json
        plan_id = data.get("planId")
        if not plan_id:
            return {"error": "planId is required"}, 400

        try:
            plan_resp = plans_table.get_item(Key={"planId": plan_id})
            if "Item" not in plan_resp:
                return {"error": "Plan not found"}, 404

            update_expr = []
            expr_values = {}
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            # Optional fields to update
            for key in ["productName", "productDescription", "priceNickname", "amount", "currency", "frequency", "active", "couponId"]:
                if key in data:
                    update_expr.append(f"{key} = :{key}")
                    expr_values[f":{key}"] = data[key]

            update_expr.append("updatedBy = :user")
            expr_values[":user"] = g.user if hasattr(g, "user") else "system"
            update_expr.append("updatedDate = :ts")
            expr_values[":ts"] = timestamp

            plans_table.update_item(
                Key={"planId": plan_id},
                UpdateExpression="SET " + ", ".join(update_expr),
                ExpressionAttributeValues=expr_values
            )

            return {"message": f"Plan {plan_id} updated successfully"}, 200

        except Exception as e:
            return {"error": str(e)}, 400


@admin_ns.route("/add-plan")
class AddPlan(Resource):
    @admin_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @admin_ns.expect(add_plan_model)
    @admin_required
    def post(self):
        data = request.json
        # Determine tax exclusion (default to tax exclusive if not provided)
        plan_id = (
            f"{data['productName'].lower().replace(' ', '-')}"
            f"-{data['priceNickname'].lower().replace(' ', '-')}"
            f"-{data['amount']}"
            f"-{data['currency'].lower()}"
            f"-{data['frequency'].lower()}"
            f"-{uuid.uuid4().hex[:6]}"
        )
        planGroup = data.get("planGroup", "pro").lower()
        try:
            # 1. Create Stripe Product
            product = stripe.Product.create(
                name=data["productName"],
                description=data["productDescription"]
            )

            # 2. Create Stripe Price
            price = stripe.Price.create(
                unit_amount=data["amount"],
                currency=data["currency"],
                recurring={"interval": data["frequency"]},
                nickname=data["priceNickname"],
                product=product.id,
                tax_behavior="exclusive"
            )

            # 3. Validate optional couponId
            coupon_id = data.get("couponId")
            if coupon_id:
                coupon_resp = coupons_table.get_item(Key={"couponId": coupon_id})
                if "Item" not in coupon_resp:
                    return {"error": f"Coupon {coupon_id} does not exist"}, 400

            # 4. Save to DynamoDB
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            plans_table.put_item(Item={
                "planId": plan_id,
                "stripeProductId": product.id,
                "productName": data["productName"],
                "productDescription": data["productDescription"],
                "stripePriceId": price.id,
                "planGroup": planGroup,
                "priceNickname": data["priceNickname"],
                "amount": data["amount"],
                "currency": data["currency"],
                "frequency": data["frequency"],
                "taxBehavior": "exclusive",
                "active": True,
                "couponId": coupon_id if coupon_id else None,
                "createdBy": g.user if hasattr(g, "user") else "system",
                "createdDate": timestamp,
                "updatedBy": g.user if hasattr(g, "user") else "system",
                "updatedDate": timestamp
            })

            return {"message": "Plan created successfully", "planId": plan_id}, 201

        except Exception as e:
            return {"error": str(e)}, 400



# -------------------------
# Add Coupon Endpoint
# -------------------------
@admin_ns.route("/add-coupon")
class AddCoupon(Resource):
    @admin_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @admin_ns.expect(add_coupon_model)
    @admin_required
    def post(self):
        data = request.json
        coupon_id = f"coupon-{uuid.uuid4().hex[:6]}"
        stripe_coupon_id = None
        try:
            # 1. Create Stripe Coupon
            if data["discountType"] == "percentage":
                coupon = stripe.Coupon.create(
                    percent_off=data["percentOff"],
                    duration=data["duration"]
                )
                stripe_coupon_id = coupon.id
            else:
                return {"error": "Only percentage coupons are supported at this time."}, 400

            # 2. Save to DynamoDB
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            coupons_table.put_item(Item={
                "couponId": coupon_id,
                "couponCode": data["couponCode"],
                "discountType": data["discountType"],
                "stripeCouponId": stripe_coupon_id,
                "percentOff": data.get("percentOff"),
                "duration": data["duration"],
                "active": True,
                "applicablePlans": data.get("applicablePlans", []),
                "createdBy": g.user if hasattr(g, "user") else "system",
                "createdDate": timestamp,
                "updatedBy": g.user if hasattr(g, "user") else "system",
                "updatedDate": timestamp
            })

            return {"message": "Coupon created successfully", "couponId": coupon_id}, 201

        except Exception as e:
            return {"error": str(e)}, 400




@admin_ns.route("/set-coupon")
class SetCoupon(Resource):
    @admin_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @admin_ns.expect(link_or_unlink_coupon_model)
    @admin_required
    def post(self):
        data = request.json
        plan_id = data["planId"]
        coupon_id = data.get("couponId")

        try:
            # Check if plan exists
            plan = plans_table.get_item(Key={"planId": plan_id})
            if "Item" not in plan:
                return {"error": "Plan not found"}, 404

            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if coupon_id:
                # Check if coupon exists
                coupon = coupons_table.get_item(Key={"couponId": coupon_id})
                if "Item" not in coupon:
                    return {"error": "Coupon not found"}, 404
                # Link coupon
                plans_table.update_item(
                    Key={"planId": plan_id},
                    UpdateExpression="SET couponId = :couponId, updatedBy = :user, updatedDate = :ts",
                    ExpressionAttributeValues={
                        ":couponId": coupon_id,
                        ":user": g.user if hasattr(g, "user") else "system",
                        ":ts": timestamp
                    }
                )
                return {"message": f"Coupon {coupon_id} linked to Plan {plan_id}"}, 200
            else:
                # Unlink coupon
                plans_table.update_item(
                    Key={"planId": plan_id},
                    UpdateExpression="SET couponId = :null, updatedBy = :user, updatedDate = :ts",
                    ExpressionAttributeValues={
                        ":null": None,
                        ":user": g.user if hasattr(g, "user") else "system",
                        ":ts": timestamp
                    }
                )
                return {"message": f"Coupon unlinked from Plan {plan_id}"}, 200

        except Exception as e:
            return {"error": str(e)}, 400

@admin_ns.route("/plans-with-coupons")
class PlansWithCoupons(Resource):
    @admin_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @admin_required
    def get(self):
        try:
            # 1. Scan all plans
            plans_response = plans_table.scan()
            plans = plans_response.get("Items", [])

            # 2. For each plan, fetch coupon details if couponId exists
            for plan in plans:
                coupon_id = plan.get("couponId")
                if coupon_id:
                    coupon_response = coupons_table.get_item(Key={"couponId": coupon_id})
                    plan["couponDetails"] = coupon_response.get("Item", {})
                else:
                    plan["couponDetails"] = None

            return {"plans": plans}, 200

        except Exception as e:
            return {"error": str(e)}, 400


@admin_ns.route("/update-coupon")
class UpdateCoupon(Resource):
    @admin_ns.doc(params={'Authorization': {'in': 'header', 'description': 'Bearer <JWT>', 'required': True}})
    @admin_ns.expect(update_coupon_model)
    @admin_required
    def post(self):
        data = request.json
        coupon_id = data.get("couponId")
        if not coupon_id:
            return {"error": "couponId is required"}, 400

        try:
            coupon_resp = coupons_table.get_item(Key={"couponId": coupon_id})
            if "Item" not in coupon_resp:
                return {"error": "Coupon not found"}, 404

            update_expr = []
            expr_values = {}
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            for key in ["couponCode", "discountType", "percentOff", "duration", "active", "applicablePlans"]:
                if key in data:
                    update_expr.append(f"{key} = :{key}")
                    expr_values[f":{key}"] = data[key]

            update_expr.append("updatedBy = :user")
            expr_values[":user"] = g.user if hasattr(g, "user") else "system"
            update_expr.append("updatedDate = :ts")
            expr_values[":ts"] = timestamp

            coupons_table.update_item(
                Key={"couponId": coupon_id},
                UpdateExpression="SET " + ", ".join(update_expr),
                ExpressionAttributeValues=expr_values
            )

            return {"message": f"Coupon {coupon_id} updated successfully"}, 200

        except Exception as e:
            return {"error": str(e)}, 400
