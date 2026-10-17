from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from .models import CommissionRule, ResellerAttribution, ResellerCommission, ResellerProfile


@transaction.atomic
def issue_reseller_commission(order):
    if hasattr(order, "reseller_commission") or order.status != "delivered":
        return None
    attribution = ResellerAttribution.objects.select_related("reseller").filter(customer=order.customer).first()
    if not attribution or attribution.customer_id == attribution.reseller.customer_id:
        return None
    reseller = attribution.reseller
    if reseller.status != ResellerProfile.Status.APPROVED:
        return None
    rule = CommissionRule.current()
    if order.total < rule.minimum_order_amount:
        return None
    amount = (order.total * rule.commission_percent / Decimal("100") + rule.fixed_commission).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        return None
    commission, _ = ResellerCommission.objects.get_or_create(
        order=order,
        defaults={"reseller": reseller, "order_amount": order.total, "amount": amount},
    )
    return commission
