import re
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from apps.catalog.models import Product
from apps.orders.models import Order
from .models import (
    Address, BlogCategory, BlogPost, CommissionRule, Coupon, CustomerQuestion,
    CustomerRequest, ResellerAttribution, ResellerCommission,
    ResellerPayoutRequest, ResellerProfile, ReturnRequest, StoreInformation,
    SupportTicket, WishlistItem, SystemSettings, DeliveryArea,
    DeliveryPersonnel, DeliveryAssignment, PaymentTransaction, Refund, HomepageBanner,
)


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        exclude = ["customer", "default_for_customer"]
        read_only_fields = ["created_at"]

    def validate_pin_code(self, value):
        if not re.fullmatch(r"[1-9][0-9]{5}", value):
            raise serializers.ValidationError("Enter a valid 6-digit Indian PIN code.")
        return value

    def validate_delivery_fee(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Delivery fee cannot be negative.")
        return value

    def validate_mobile_number(self, value):
        if not re.fullmatch(r"\+?[0-9]{7,15}", value):
            raise serializers.ValidationError("Enter a valid mobile number.")
        return value


class ProductSummarySerializer(serializers.ModelSerializer):
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "price", "mrp", "stock", "image_url", "in_stock"]

    def get_in_stock(self, obj):
        return obj.is_active and obj.stock > 0


class WishlistItemSerializer(serializers.ModelSerializer):
    product = ProductSummarySerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(source="product", queryset=Product.objects.filter(is_active=True), write_only=True)

    class Meta:
        model = WishlistItem
        fields = ["id", "product", "product_id", "created_at"]
        read_only_fields = ["id", "created_at"]


class CustomerQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerQuestion
        fields = ["id", "order", "subject", "question", "answer", "status", "created_at", "updated_at"]
        read_only_fields = ["answer", "status", "created_at", "updated_at"]

    def validate_order(self, order):
        if order and order.customer_id != self.context["request"].user.id:
            raise serializers.ValidationError("Select one of your own orders.")
        return order


class AdminCustomerQuestionSerializer(CustomerQuestionSerializer):
    customer_id = serializers.IntegerField(read_only=True)

    class Meta(CustomerQuestionSerializer.Meta):
        fields = CustomerQuestionSerializer.Meta.fields + ["customer_id"]
        read_only_fields = ["order", "created_at", "updated_at"]


class CustomerRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerRequest
        fields = ["id", "request_number", "kind", "subject", "message", "response", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "request_number", "response", "status", "created_at", "updated_at"]


class AdminCustomerRequestSerializer(CustomerRequestSerializer):
    customer_id = serializers.IntegerField(read_only=True)

    class Meta(CustomerRequestSerializer.Meta):
        fields = CustomerRequestSerializer.Meta.fields + ["customer_id"]
        read_only_fields = ["id", "request_number", "created_at", "updated_at"]


class SupportTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = ["id", "ticket_number", "subject", "message", "response", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "ticket_number", "response", "status", "created_at", "updated_at"]


class AdminSupportTicketSerializer(SupportTicketSerializer):
    customer_id = serializers.IntegerField(read_only=True)

    class Meta(SupportTicketSerializer.Meta):
        fields = SupportTicketSerializer.Meta.fields + ["customer_id", "internal_notes", "assigned_to", "priority", "first_response_at", "resolved_at"]
        read_only_fields = ["id", "ticket_number", "created_at", "updated_at"]

    def validate_assigned_to(self, user):
        if user and (not user.is_staff or not user.is_active or user.role not in {"admin", "super_admin", "customer_support"}):
            raise serializers.ValidationError("Assign tickets to active customer support staff only.")
        return user


class ReturnRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnRequest
        fields = ["id", "order", "reason", "status", "response", "created_at"]
        read_only_fields = ["id", "status", "response", "created_at"]

    def validate_order(self, order):
        user = self.context["request"].user
        if order.customer_id != user.id:
            raise serializers.ValidationError("Select one of your own orders.")
        if order.status != Order.Status.DELIVERED:
            raise serializers.ValidationError("Returns can only be requested for delivered orders.")
        from .models import SystemSettings
        settings = SystemSettings.current()
        if not settings.allow_returns:
            raise serializers.ValidationError("Returns are currently unavailable.")
        if timezone.now() - order.updated_at > timedelta(days=settings.return_window_days):
            raise serializers.ValidationError("The return window for this order has closed.")
        return order


class AdminReturnRequestSerializer(ReturnRequestSerializer):
    customer_id = serializers.IntegerField(read_only=True)

    class Meta(ReturnRequestSerializer.Meta):
        fields = ReturnRequestSerializer.Meta.fields + ["customer_id"]
        read_only_fields = ["id", "order", "reason", "created_at"]


class BlogCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogCategory
        fields = ["id", "name", "slug"]


class BlogPostSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = BlogPost
        fields = ["id", "title", "slug", "category", "category_name", "cover_image_url", "author", "excerpt", "content", "is_published", "published_at", "created_at"]
        read_only_fields = ["id", "created_at"]


class StoreInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreInformation
        fields = ["details", "policies", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        for key in ("delivery_fee", "free_delivery_threshold", "minimum_order_value"):
            value = attrs.get(key, getattr(self.instance, key, None) if self.instance else None)
            if value is not None and value < 0:
                raise serializers.ValidationError({key: "This amount cannot be negative."})
        return attrs


class PublicStoreInformationSerializer(StoreInformationSerializer):
    safe_detail_keys = {"about", "email", "phone", "address", "delivery_information"}
    safe_policy_keys = {"shipping_policy", "return_policy", "refund_policy", "privacy_policy", "terms", "faq"}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["details"] = {key: value for key, value in instance.details.items() if key in self.safe_detail_keys}
        data["policies"] = {key: value for key, value in instance.policies.items() if key in self.safe_policy_keys}
        return data


class ResellerApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResellerProfile
        fields = ["id", "status", "reseller_code", "application_note", "admin_note", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "reseller_code", "admin_note", "created_at", "updated_at"]


class ResellerProfileAdminSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="customer.email", read_only=True)

    class Meta:
        model = ResellerProfile
        fields = ["id", "customer", "email", "status", "reseller_code", "application_note", "admin_note", "created_at", "updated_at"]
        read_only_fields = ["customer", "reseller_code", "created_at", "updated_at"]


class ResellerCommissionSerializer(serializers.ModelSerializer):
    reseller_code = serializers.CharField(source="reseller.reseller_code", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = ResellerCommission
        fields = ["id", "reseller_code", "order_number", "order_amount", "amount", "status", "created_at"]


class PayoutRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResellerPayoutRequest
        fields = ["id", "request_number", "amount", "status", "admin_note", "created_at", "updated_at"]
        read_only_fields = ["id", "request_number", "status", "admin_note", "created_at", "updated_at"]

    def validate_amount(self, value):
        from django.db.models import Q, Sum
        from .models import ResellerCommission
        profile = ResellerProfile.objects.filter(customer=self.context["request"].user, status=ResellerProfile.Status.APPROVED).first()
        if not profile:
            raise serializers.ValidationError("An approved reseller account is required.")
        threshold = CommissionRule.current().minimum_payout
        commissions = ResellerCommission.objects.filter(
            reseller=profile, status=ResellerCommission.Status.APPROVED
        ).annotate(paid_allocations=Sum(
            "payout_allocations__amount",
            filter=Q(payout_allocations__payout_request__status=ResellerPayoutRequest.Status.PAID),
        ))
        available = sum(
            (commission.amount - (commission.paid_allocations or 0) for commission in commissions),
            Decimal("0.00"),
        )
        pending = ResellerPayoutRequest.objects.filter(reseller=profile, status__in=["pending", "approved"]).aggregate(total=Sum("amount"))["total"] or 0
        if value < threshold or value > available - pending:
            raise serializers.ValidationError("The payout must meet the minimum threshold and not exceed your available approved balance.")
        return value


class PayoutRequestAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResellerPayoutRequest
        fields = ["id", "request_number", "reseller", "amount", "status", "admin_note", "created_at", "updated_at"]
        read_only_fields = ["reseller", "amount", "request_number", "created_at", "updated_at"]


class CommissionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionRule
        fields = ["commission_percent", "fixed_commission", "minimum_order_amount", "minimum_payout", "updated_at"]
        read_only_fields = ["updated_at"]


class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = ["id", "code", "discount_type", "value", "minimum_purchase", "maximum_discount", "starts_at", "expires_at", "usage_limit", "per_customer_limit", "new_customer_only", "products", "categories", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        return value.strip().upper()

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        expires_at = attrs.get("expires_at", getattr(self.instance, "expires_at", None))
        if starts_at and expires_at and expires_at <= starts_at:
            raise serializers.ValidationError({"expires_at": "Expiry must be after the start date."})
        discount_type = attrs.get("discount_type", getattr(self.instance, "discount_type", None))
        value = attrs.get("value", getattr(self.instance, "value", None))
        if discount_type == Coupon.DiscountType.PERCENT and value is not None and value > 100:
            raise serializers.ValidationError({"value": "Percentage discounts cannot exceed 100%."})
        if attrs.get("per_customer_limit", getattr(self.instance, "per_customer_limit", 1)) < 1:
            raise serializers.ValidationError({"per_customer_limit": "Limit must be at least 1."})
        return attrs


class HomepageBannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = HomepageBanner
        fields = ["id", "title", "subtitle", "image_url", "target_url", "starts_at", "ends_at", "sort_order", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": "Expiry must be after the start date."})
        target = attrs.get("target_url", getattr(self.instance, "target_url", ""))
        if target and (not target.startswith("/") or target.startswith("//")):
            raise serializers.ValidationError({"target_url": "Use an internal store path beginning with a single slash."})
        return attrs


class SystemSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSettings
        fields = ["store_name", "currency", "delivery_fee", "free_delivery_threshold", "minimum_order_value", "default_low_stock_threshold", "return_window_days", "allow_returns", "updated_at"]
        read_only_fields = ["updated_at"]


class DeliveryAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryArea
        fields = ["id", "name", "pin_code", "delivery_fee", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_pin_code(self, value):
        if not re.fullmatch(r"[1-9][0-9]{5}", value):
            raise serializers.ValidationError("Enter a valid 6-digit Indian PIN code.")
        return value


class DeliveryPersonnelSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryPersonnel
        fields = ["id", "name", "phone", "is_available", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class DeliveryAssignmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_name = serializers.CharField(source="order.customer_name", read_only=True)
    address = serializers.CharField(source="order.address", read_only=True)

    class Meta:
        model = DeliveryAssignment
        fields = ["id", "order", "order_number", "customer_name", "address", "personnel", "status", "scheduled_at", "dispatched_at", "delivered_at", "failed_at", "delivery_note", "proof_reference", "updated_at"]
        read_only_fields = ["id", "order", "order_number", "customer_name", "address", "updated_at"]

    def validate_personnel(self, personnel):
        if personnel and not personnel.is_active:
            raise serializers.ValidationError("Assign deliveries only to active personnel.")
        if personnel and not personnel.is_available:
            raise serializers.ValidationError("This delivery person is currently unavailable.")
        return personnel

    def validate_status(self, value):
        if not self.instance:
            return value
        allowed = {
            DeliveryAssignment.Status.ASSIGNED: {DeliveryAssignment.Status.DISPATCHED, DeliveryAssignment.Status.FAILED, DeliveryAssignment.Status.RESCHEDULED},
            DeliveryAssignment.Status.DISPATCHED: {DeliveryAssignment.Status.FAILED, DeliveryAssignment.Status.RESCHEDULED, DeliveryAssignment.Status.DELIVERED},
            DeliveryAssignment.Status.FAILED: {DeliveryAssignment.Status.RESCHEDULED},
            DeliveryAssignment.Status.RESCHEDULED: {DeliveryAssignment.Status.DISPATCHED, DeliveryAssignment.Status.FAILED},
            DeliveryAssignment.Status.DELIVERED: set(),
        }
        if value != self.instance.status and value not in allowed[self.instance.status]:
            raise serializers.ValidationError(f"Cannot move a delivery assignment from {self.instance.status} to {value}.")
        return value


class PaymentTransactionSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_email = serializers.EmailField(source="order.customer.email", read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = ["id", "order", "order_number", "customer_email", "method", "status", "amount", "transaction_reference", "cod_collected", "created_at", "updated_at"]
        read_only_fields = ["id", "order", "order_number", "customer_email", "method", "status", "amount", "transaction_reference", "created_at", "updated_at"]


class RefundSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_email = serializers.EmailField(source="order.customer.email", read_only=True)

    class Meta:
        model = Refund
        fields = ["id", "order", "order_number", "customer_email", "amount", "reason", "status", "transaction_reference", "created_at", "updated_at"]
        read_only_fields = ["id", "order_number", "customer_email", "created_by", "updated_by", "created_at", "updated_at"]

    def validate(self, attrs):
        from django.db.models import Sum
        status_value = attrs.get("status", Refund.Status.REQUESTED)
        if not self.instance and status_value != Refund.Status.REQUESTED:
            raise serializers.ValidationError({"status": "New refunds must begin in requested status."})
        if status_value == Refund.Status.RECORDED:
            order = attrs.get("order", getattr(self.instance, "order", None))
            reference = attrs.get("transaction_reference", getattr(self.instance, "transaction_reference", ""))
            if order and order.payment_method != "cod":
                raise serializers.ValidationError({"status": "Manual refund recording is only available for Cash on Delivery orders."})
            if not reference:
                raise serializers.ValidationError({"transaction_reference": "Enter the verified manual transfer reference before recording the refund."})
        order = attrs.get("order", getattr(self.instance, "order", None))
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        if order and order.payment_status != Order.PaymentStatus.PAID:
            raise serializers.ValidationError({"order": "A refund can only be reviewed for an order with a recorded payment."})
        if order and amount is not None:
            already_refunded = Refund.objects.filter(order=order).exclude(status=Refund.Status.REJECTED)
            if self.instance:
                already_refunded = already_refunded.exclude(pk=self.instance.pk)
            total = already_refunded.aggregate(amount=Sum("amount"))["amount"] or Decimal("0")
            if total + amount > order.total:
                raise serializers.ValidationError({"amount": "Refunds cannot exceed the order total."})
        return attrs
