import secrets
import string
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


def _code(prefix="", length=10):
    alphabet = string.ascii_uppercase + string.digits
    return f"{prefix}{''.join(secrets.choice(alphabet) for _ in range(length))}"


def reseller_code():
    return _code("RS", 10)


class Address(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="saved_addresses", on_delete=models.CASCADE)
    default_for_customer = models.PositiveBigIntegerField(null=True, blank=True, unique=True, editable=False)
    recipient_name = models.CharField(max_length=150)
    mobile_number = models.CharField(max_length=16)
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    locality = models.CharField(max_length=120)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=6)
    delivery_instructions = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]

    def save(self, *args, **kwargs):
        self.default_for_customer = self.customer_id if self.is_default else None
        super().save(*args, **kwargs)


class WishlistItem(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="wishlist_items", on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", related_name="wishlisted_by", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["customer", "product"], name="unique_customer_wishlist_product")]


class CustomerQuestion(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ANSWERED = "answered", "Answered"
        CLOSED = "closed", "Closed"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="customer_questions", on_delete=models.CASCADE)
    order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="customer_questions", on_delete=models.CASCADE)
    subject = models.CharField(max_length=160)
    question = models.TextField(max_length=5000)
    answer = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class CustomerRequest(models.Model):
    class Kind(models.TextChoices):
        REQUEST = "request", "Request"
        COMPLAINT = "complaint", "Complaint"
        FEEDBACK = "feedback", "Feedback"
        GENERAL = "general", "General query"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="service_requests", on_delete=models.CASCADE)
    request_number = models.CharField(max_length=18, unique=True, editable=False)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.GENERAL)
    subject = models.CharField(max_length=160)
    message = models.TextField(max_length=5000)
    response = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUBMITTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.request_number:
            self.request_number = _code("REQ-", 12)
        super().save(*args, **kwargs)


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="support_tickets", on_delete=models.CASCADE)
    ticket_number = models.CharField(max_length=18, unique=True, editable=False)
    subject = models.CharField(max_length=160)
    message = models.TextField(max_length=5000)
    response = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name="assigned_support_tickets", on_delete=models.SET_NULL)
    priority = models.CharField(max_length=10, choices=[("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")], default="normal")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            self.ticket_number = _code("SUP-", 12)
        super().save(*args, **kwargs)


class ReturnRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="return_requests", on_delete=models.CASCADE)
    order = models.ForeignKey("orders.Order", related_name="return_requests", on_delete=models.CASCADE)
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["customer", "order"], name="one_return_request_per_order_customer")]


class BlogCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BlogPost(models.Model):
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    category = models.ForeignKey(BlogCategory, null=True, blank=True, related_name="posts", on_delete=models.SET_NULL)
    cover_image_url = models.URLField(blank=True)
    author = models.CharField(max_length=120, blank=True)
    excerpt = models.CharField(max_length=400, blank=True)
    content = models.TextField()
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]


class StoreInformation(models.Model):
    details = models.JSONField(default=dict, blank=True)
    policies = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]


class AdminAuditEntry(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="customer_service_audit_entries", on_delete=models.PROTECT)
    action = models.CharField(max_length=20)
    resource = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SecurityEvent(models.Model):
    event_type = models.CharField(max_length=40, db_index=True)
    email = models.EmailField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class SystemSettings(models.Model):
    store_name = models.CharField(max_length=120, default="SUPER MARKET")
    currency = models.CharField(max_length=3, default="INR")
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    free_delivery_threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    minimum_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    default_low_stock_threshold = models.PositiveIntegerField(default=5)
    return_window_days = models.PositiveSmallIntegerField(default=7)
    allow_returns = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]


class HomepageBanner(models.Model):
    title = models.CharField(max_length=140)
    subtitle = models.CharField(max_length=300, blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    target_url = models.CharField(max_length=300, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "starts_at"]
        constraints = [models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="homepage_banner_expiry_after_start")]


class DeliveryArea(models.Model):
    name = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=6, unique=True)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DeliveryPersonnel(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    is_available = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DeliveryAssignment(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        DISPATCHED = "dispatched", "Dispatched"
        FAILED = "failed", "Failed"
        RESCHEDULED = "rescheduled", "Rescheduled"
        DELIVERED = "delivered", "Delivered"

    order = models.OneToOneField("orders.Order", related_name="delivery_assignment", on_delete=models.PROTECT)
    personnel = models.ForeignKey(DeliveryPersonnel, null=True, blank=True, related_name="assignments", on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ASSIGNED)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    delivery_note = models.TextField(blank=True)
    proof_reference = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESSFUL = "successful", "Successful"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    class Method(models.TextChoices):
        COD = "cod", "Cash on Delivery"
        ONLINE = "online", "Online"

    order = models.ForeignKey("orders.Order", related_name="payment_transactions", on_delete=models.PROTECT)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.COD)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    transaction_reference = models.CharField(max_length=160, blank=True, unique=True, null=True)
    cod_collected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class PaymentEvent(models.Model):
    transaction = models.ForeignKey(PaymentTransaction, related_name="events", on_delete=models.PROTECT)
    event_type = models.CharField(max_length=30)
    reference = models.CharField(max_length=160, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Refund(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        RECORDED = "recorded", "Recorded (manual)"
        PROCESSED = "processed", "Processed"
        REJECTED = "rejected", "Rejected"

    order = models.ForeignKey("orders.Order", related_name="refunds", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    transaction_reference = models.CharField(max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="created_refunds", on_delete=models.PROTECT)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name="updated_refunds", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class Coupon(models.Model):
    class DiscountType(models.TextChoices):
        FIXED = "fixed", "Fixed amount"
        PERCENT = "percent", "Percentage"

    code = models.CharField(max_length=40, unique=True)
    discount_type = models.CharField(max_length=8, choices=DiscountType.choices)
    value = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    minimum_purchase = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    maximum_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    per_customer_limit = models.PositiveIntegerField(default=1)
    new_customer_only = models.BooleanField(default=False)
    products = models.ManyToManyField("catalog.Product", blank=True, related_name="coupons")
    categories = models.ManyToManyField("catalog.Category", blank=True, related_name="coupons")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(expires_at__gt=models.F("starts_at")), name="coupon_expiry_after_start")]


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, related_name="redemptions", on_delete=models.PROTECT)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="coupon_redemptions", on_delete=models.PROTECT)
    order = models.OneToOneField("orders.Order", related_name="coupon_redemption", on_delete=models.PROTECT)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["coupon", "order"], name="unique_coupon_redemption_per_order")]


class InventoryAdjustment(models.Model):
    product = models.ForeignKey("catalog.Product", related_name="adjustments", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="inventory_adjustments", on_delete=models.PROTECT)
    quantity_delta = models.IntegerField()
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)


class ResellerProfile(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    customer = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="reseller_profile", on_delete=models.CASCADE)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reseller_code = models.CharField(max_length=14, unique=True, default=reseller_code)
    application_note = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ResellerAttribution(models.Model):
    customer = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="reseller_attribution", on_delete=models.CASCADE)
    reseller = models.ForeignKey(ResellerProfile, related_name="attributed_customers", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class CommissionRule(models.Model):
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    fixed_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    minimum_payout = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]


class ResellerCommission(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"
        REVERSED = "reversed", "Reversed"

    reseller = models.ForeignKey(ResellerProfile, related_name="commissions", on_delete=models.PROTECT)
    order = models.OneToOneField("orders.Order", related_name="reseller_commission", on_delete=models.PROTECT)
    order_amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class ResellerPayoutRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Recorded as paid"
        REJECTED = "rejected", "Rejected"

    reseller = models.ForeignKey(ResellerProfile, related_name="payout_requests", on_delete=models.PROTECT)
    request_number = models.CharField(max_length=18, unique=True, editable=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.request_number:
            self.request_number = _code("PAY-", 12)
        super().save(*args, **kwargs)


class ResellerPayoutAllocation(models.Model):
    payout_request = models.ForeignKey(ResellerPayoutRequest, related_name="allocations", on_delete=models.PROTECT)
    commission = models.ForeignKey(ResellerCommission, related_name="payout_allocations", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["payout_request", "commission"], name="unique_commission_allocation_per_payout")]
