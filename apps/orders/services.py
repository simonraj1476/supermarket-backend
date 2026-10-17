from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.catalog.models import Product
from .models import InventoryMovement, Order, OrderItem

@transaction.atomic
def place_order(*, customer, payload):
    if payload.get("payment_method", "cod") != "cod":
        raise ValidationError({"payment_method": "Only Cash on Delivery is currently available."})
    lines = payload.get("items", [])
    if not lines:
        raise ValidationError({"items": "Add at least one item to your cart."})
    if len(lines) > 100:
        raise ValidationError({"items": "An order cannot contain more than 100 line items."})
    product_ids = [line.get("product_id") for line in lines]
    if None in product_ids or len(product_ids) != len(set(product_ids)):
        raise ValidationError({"items": "Each product must appear once with a valid product ID."})
    products = {product.id: product for product in Product.objects.select_for_update().filter(id__in=product_ids, is_active=True)}
    if len(products) != len(product_ids):
        raise ValidationError({"items": "One or more products are unavailable."})
    order_lines = []
    subtotal = Decimal("0.00")
    for line in lines:
        quantity = line.get("quantity")
        product = products[line["product_id"]]
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1 or quantity > 99:
            raise ValidationError({"items": f"Quantity for {product.name} must be between 1 and 99."})
        if product.stock < quantity:
            raise ValidationError({"items": f"Not enough stock for {product.name}."})
        amount = product.price * quantity
        subtotal += amount
        order_lines.append((product, quantity, amount))
    from apps.customer_services.models import (
        Coupon, CouponRedemption, DeliveryArea, PaymentTransaction, SystemSettings,
    )
    settings = SystemSettings.current()
    if subtotal < settings.minimum_order_value:
        raise ValidationError({"items": f"The minimum order value is ₹{settings.minimum_order_value}."})
    pin_code = payload.get("delivery_pin_code", "").strip()
    areas_configured = DeliveryArea.objects.exists()
    delivery_area = DeliveryArea.objects.filter(pin_code=pin_code, is_active=True).first() if pin_code else None
    if areas_configured and not delivery_area:
        raise ValidationError({"delivery_pin_code": "Delivery is not available for this PIN code."})
    if delivery_area and delivery_area.delivery_fee is not None:
        delivery_fee = delivery_area.delivery_fee
    else:
        delivery_fee = settings.delivery_fee
    if settings.free_delivery_threshold is not None and subtotal >= settings.free_delivery_threshold:
        delivery_fee = Decimal("0.00")

    coupon = None
    discount = Decimal("0.00")
    code = payload.get("coupon_code", "").strip().upper()
    if code:
        now = timezone.now()
        coupon = Coupon.objects.select_for_update().filter(code__iexact=code, is_active=True, starts_at__lte=now, expires_at__gt=now).first()
        if not coupon:
            raise ValidationError({"coupon_code": "This coupon is not currently available."})
        if subtotal < coupon.minimum_purchase:
            raise ValidationError({"coupon_code": f"This coupon requires a minimum purchase of ₹{coupon.minimum_purchase}."})
        if coupon.usage_limit is not None and coupon.redemptions.count() >= coupon.usage_limit:
            raise ValidationError({"coupon_code": "This coupon has reached its usage limit."})
        customer_uses = coupon.redemptions.filter(customer=customer).count()
        if customer_uses >= coupon.per_customer_limit:
            raise ValidationError({"coupon_code": "You have reached the usage limit for this coupon."})
        if coupon.new_customer_only and Order.objects.filter(customer=customer).exists():
            raise ValidationError({"coupon_code": "This coupon is available to new customers only."})
        eligible_total = Decimal("0.00")
        restrictions = coupon.products.exists() or coupon.categories.exists()
        for product, quantity, amount in order_lines:
            if not restrictions or coupon.products.filter(pk=product.pk).exists() or coupon.categories.filter(pk=product.category_id).exists():
                eligible_total += amount
        if eligible_total <= 0:
            raise ValidationError({"coupon_code": "This coupon does not apply to items in your basket."})
        if coupon.discount_type == Coupon.DiscountType.PERCENT:
            discount = eligible_total * coupon.value / Decimal("100")
        else:
            discount = coupon.value
        if coupon.maximum_discount is not None:
            discount = min(discount, coupon.maximum_discount)
        discount = min(discount.quantize(Decimal("0.01")), eligible_total)
    total = subtotal - discount + delivery_fee
    order = Order.objects.create(
        customer=customer,
        customer_name=payload["customer_name"].strip(),
        phone=payload["phone"].strip(),
        address=payload["address"].strip(),
        instructions=payload.get("instructions", "").strip(),
        subtotal=subtotal,
        coupon=coupon,
        discount_amount=discount,
        delivery_pin_code=pin_code,
        delivery_fee=delivery_fee,
        total=total,
    )
    for product, quantity, amount in order_lines:
        product.stock -= quantity
        product.save(update_fields=["stock"])
        OrderItem.objects.create(order=order, product=product, product_name=product.name, sku=product.sku, unit_price=product.price, quantity=quantity, line_total=amount)
        InventoryMovement.objects.create(order=order, product=product, kind=InventoryMovement.Kind.SALE, quantity=quantity)
    if coupon:
        CouponRedemption.objects.create(coupon=coupon, customer=customer, order=order, discount_amount=discount)
    PaymentTransaction.objects.create(order=order, method=PaymentTransaction.Method.COD, status=PaymentTransaction.Status.PENDING, amount=total)
    from apps.referrals.models import ReferralProgram
    referral_program = ReferralProgram.objects.filter(pk=1).first()
    if referral_program and order.status in referral_program.qualifying_order_statuses:
        from apps.referrals.services import award_referral_for_order
        award_referral_for_order(order)
    return order

@transaction.atomic
def change_order_status(*, order, new_status):
    order = Order.objects.select_for_update().get(pk=order.pk)
    allowed = {
        "pending": {"confirmed", "cancelled"},
        "confirmed": {"processing", "cancelled"},
        "processing": {"packed", "cancelled"},
        "packed": {"out_for_delivery", "cancelled"},
        "out_for_delivery": {"delivered"},
        "delivered": set(),
        "cancelled": set(),
    }
    if new_status not in Order.Status.values:
        raise ValidationError({"status": "Unknown order status."})
    if new_status not in allowed[order.status]:
        raise ValidationError({"status": f"Cannot move an order from {order.status} to {new_status}."})
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    if new_status == Order.Status.OUT_FOR_DELIVERY:
        from apps.customer_services.models import DeliveryAssignment
        DeliveryAssignment.objects.get_or_create(order=order)
    if new_status == Order.Status.CANCELLED:
        for movement in order.inventory_movements.filter(kind=InventoryMovement.Kind.SALE).select_related("product"):
            if not order.inventory_movements.filter(product=movement.product, kind=InventoryMovement.Kind.RESTOCK).exists():
                product = Product.objects.select_for_update().get(pk=movement.product_id)
                product.stock += movement.quantity
                product.save(update_fields=["stock"])
                InventoryMovement.objects.create(order=order, product=product, kind=InventoryMovement.Kind.RESTOCK, quantity=movement.quantity)
    from apps.referrals.models import ReferralProgram
    referral_program = ReferralProgram.objects.filter(pk=1).first()
    if referral_program and new_status in referral_program.qualifying_order_statuses:
        from apps.referrals.services import award_referral_for_order
        award_referral_for_order(order)
    if referral_program and new_status == Order.Status.CANCELLED and referral_program.reverse_on_cancellation:
        from apps.referrals.services import reverse_referral_rewards_for_order
        reverse_referral_rewards_for_order(order, reason="qualifying order cancelled")
    if new_status == Order.Status.DELIVERED:
        from apps.customer_services.services import issue_reseller_commission
        issue_reseller_commission(order)
    return order
