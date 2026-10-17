from django.contrib import admin
from .models import Referral, ReferralLevelRule, ReferralProgram, ReferralReward, WalletLedger

@admin.register(ReferralProgram)
class ReferralProgramAdmin(admin.ModelAdmin):
    list_display = ["active", "max_depth", "reward_type", "referrer_reward", "customer_reward", "minimum_order_amount", "configuration_version"]
    readonly_fields = ["configuration_version", "updated_at"]


@admin.register(ReferralLevelRule)
class ReferralLevelRuleAdmin(admin.ModelAdmin):
    list_display = ["program", "level", "reward_type", "amount", "active"]
    list_filter = ["program", "reward_type", "active", "level"]

@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ["referrer", "referred", "status", "qualifying_order", "created_at"]
    list_filter = ["status"]
    search_fields = ["referrer__email", "referred__email"]
    readonly_fields = ["referrer", "referred", "qualifying_order", "created_at", "completed_at"]

@admin.register(ReferralReward)
class ReferralRewardAdmin(admin.ModelAdmin):
    list_display = ["recipient", "recipient_type", "level", "order", "amount", "status", "created_at"]
    list_filter = ["status", "recipient_type", "level"]
    readonly_fields = ["referral", "recipient", "recipient_type", "order", "level", "reward_type", "amount", "status", "configuration_snapshot", "created_at"]

@admin.register(WalletLedger)
class WalletLedgerAdmin(admin.ModelAdmin):
    list_display = ["customer", "transaction_type", "amount", "currency", "order", "level", "created_at"]
    list_filter = ["transaction_type", "status", "level"]
    search_fields = ["customer__email", "idempotency_key"]
    readonly_fields = ["reward", "customer", "amount", "description", "transaction_type", "currency", "order", "referral", "level", "configuration_version", "status", "idempotency_key", "reversal_of", "created_at"]
