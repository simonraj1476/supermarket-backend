from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def default_qualifying_order_statuses():
    return ["delivered"]


class ReferralProgram(models.Model):
    active = models.BooleanField(default=True)
    reward_type = models.CharField(max_length=12, choices=[("wallet", "Wallet credit")], default="wallet")
    referrer_reward = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("100.00"), validators=[MinValueValidator(0)])
    customer_reward = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("50.00"), validators=[MinValueValidator(0)])
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("500.00"), validators=[MinValueValidator(0)])
    max_reward_per_referral = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    max_depth = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(6)])
    qualifying_order_statuses = models.JSONField(default=default_qualifying_order_statuses)
    reward_on_first_qualifying_order_only = models.BooleanField(default=True)
    reward_referrer = models.BooleanField(default=True)
    reward_ancestors = models.BooleanField(default=True)
    reward_referred_customer = models.BooleanField(default=True)
    reverse_on_full_refund = models.BooleanField(default=True)
    reverse_on_cancellation = models.BooleanField(default=True)
    wallet_spending_enabled = models.BooleanField(default=False)
    wallet_expiry_days = models.PositiveIntegerField(null=True, blank=True)
    configuration_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        program = cls.objects.get_or_create(pk=1)[0]
        ReferralLevelRule.objects.get_or_create(
            program=program,
            level=1,
            defaults={"amount": program.referrer_reward},
        )
        return program


class ReferralLevelRule(models.Model):
    class RewardType(models.TextChoices):
        FIXED = "fixed", "Fixed wallet credit"
        PERCENTAGE = "percentage", "Percentage of qualifying order"

    program = models.ForeignKey(ReferralProgram, related_name="level_rules", on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(6)])
    reward_type = models.CharField(max_length=12, choices=RewardType.choices, default=RewardType.FIXED)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["level"]
        constraints = [
            models.UniqueConstraint(fields=["program", "level"], name="unique_referral_program_level"),
            models.CheckConstraint(condition=models.Q(level__gte=1, level__lte=6), name="referral_rule_level_range"),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="referral_rule_amount_nonnegative"),
            models.CheckConstraint(
                condition=~models.Q(reward_type="percentage") | models.Q(amount__lte=100),
                name="referral_percentage_max_100",
            ),
        ]


class Referral(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending first qualifying order"
        COMPLETED = "completed", "Reward issued"
        INACTIVE = "inactive", "Program inactive"

    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="sent_referrals", on_delete=models.PROTECT)
    referred = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="referral_attribution", on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    qualifying_order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="qualified_referrals", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["referrer", "status"])]
        constraints = [models.CheckConstraint(condition=~models.Q(referrer=models.F("referred")), name="referral_not_self")]

class ReferralReward(models.Model):
    class RecipientType(models.TextChoices):
        REFERRER = "referrer", "Referrer"
        CUSTOMER = "customer", "Referred customer"
        ANCESTOR = "ancestor", "Downline ancestor"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CREDITED = "credited", "Credited"
        REVERSED = "reversed", "Reversed"
        INELIGIBLE = "ineligible", "Ineligible"

    referral = models.ForeignKey(Referral, related_name="rewards", on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="referral_rewards", on_delete=models.PROTECT)
    recipient_type = models.CharField(max_length=12, choices=RecipientType.choices)
    order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="referral_rewards", on_delete=models.PROTECT)
    level = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(0), MaxValueValidator(6)])
    reward_type = models.CharField(max_length=12, default="wallet")
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CREDITED)
    eligible_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    configuration_version = models.PositiveIntegerField(default=1)
    configuration_snapshot = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "recipient", "level"], name="unique_referral_order_reward_level")]
        ordering = ["-created_at"]


class WalletLedger(models.Model):
    class TransactionType(models.TextChoices):
        CREDIT = "credit", "Credit"
        REVERSAL = "reversal", "Reversal"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    class Status(models.TextChoices):
        CREDITED = "credited", "Credited"
        REVERSED = "reversed", "Reversed"

    reward = models.ForeignKey(ReferralReward, related_name="ledger_entries", null=True, blank=True, on_delete=models.PROTECT)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="wallet_entries", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=200)
    transaction_type = models.CharField(max_length=12, choices=TransactionType.choices, default=TransactionType.CREDIT)
    currency = models.CharField(max_length=3, default="INR")
    order = models.ForeignKey("orders.Order", null=True, blank=True, related_name="wallet_entries", on_delete=models.PROTECT)
    referral = models.ForeignKey(Referral, null=True, blank=True, related_name="wallet_entries", on_delete=models.PROTECT)
    level = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(6)])
    configuration_version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CREDITED)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    reversal_of = models.OneToOneField("self", related_name="reversal", null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="wallet_ledger_amount_nonzero"),
            models.CheckConstraint(
                condition=(
                    models.Q(transaction_type="credit", amount__gt=0)
                    | models.Q(transaction_type="reversal", amount__lt=0)
                    | models.Q(transaction_type="adjustment")
                ),
                name="wallet_ledger_signed_transaction",
            ),
        ]
