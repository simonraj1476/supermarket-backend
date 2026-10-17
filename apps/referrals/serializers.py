from decimal import Decimal

from rest_framework import serializers

from apps.accounts.models import User
from .models import Referral, ReferralLevelRule, ReferralProgram, ReferralReward, WalletLedger


class ReferralLevelRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralLevelRule
        fields = ["level", "reward_type", "amount", "active"]

    def validate(self, attrs):
        reward_type = attrs.get("reward_type", getattr(self.instance, "reward_type", None))
        amount = attrs.get("amount", getattr(self.instance, "amount", Decimal("0")))
        if reward_type == ReferralLevelRule.RewardType.PERCENTAGE and amount > Decimal("100"):
            raise serializers.ValidationError("Percentage rewards cannot exceed 100%.")
        return attrs


class ReferralProgramSerializer(serializers.ModelSerializer):
    level_rules = ReferralLevelRuleSerializer(many=True, required=False)

    class Meta:
        model = ReferralProgram
        fields = [
            "active", "reward_type", "referrer_reward", "customer_reward",
            "minimum_order_amount", "max_reward_per_referral", "max_depth",
            "qualifying_order_statuses", "reward_on_first_qualifying_order_only",
            "reward_referrer", "reward_ancestors", "reward_referred_customer",
            "reverse_on_full_refund", "reverse_on_cancellation",
            "wallet_spending_enabled", "wallet_expiry_days",
            "configuration_version", "level_rules", "updated_at",
        ]
        read_only_fields = ["configuration_version", "updated_at"]

    def validate_max_depth(self, value):
        if value < 1 or value > 6:
            raise serializers.ValidationError("Referral depth must be between 1 and 6.")
        return value

    def validate_qualifying_order_statuses(self, value):
        supported = {"pending", "confirmed", "processing", "packed", "out_for_delivery", "delivered"}
        if not isinstance(value, list) or not value or any(item not in supported for item in value):
            raise serializers.ValidationError("Choose one or more supported order statuses.")
        return list(dict.fromkeys(value))

    def validate(self, attrs):
        max_depth = attrs.get("max_depth", getattr(self.instance, "max_depth", 1))
        rules = attrs.get("level_rules")
        if rules is not None:
            levels = [rule["level"] for rule in rules]
            if len(levels) != len(set(levels)):
                raise serializers.ValidationError({"level_rules": "Each referral level can only have one reward rule."})
            if any(level > max_depth for level in levels):
                raise serializers.ValidationError({"level_rules": "A reward rule cannot be configured beyond the maximum referral depth."})
            for rule in rules:
                if rule["reward_type"] == ReferralLevelRule.RewardType.PERCENTAGE and rule["amount"] > Decimal("100"):
                    raise serializers.ValidationError({"level_rules": "Percentage rewards cannot exceed 100%."})
        return attrs

    def update(self, instance, validated_data):
        level_rules = validated_data.pop("level_rules", None)
        legacy_referrer_reward = validated_data.get("referrer_reward")
        instance = super().update(instance, validated_data)
        if level_rules is not None:
            existing = {rule.level: rule for rule in instance.level_rules.all()}
            received_levels = set()
            for rule_data in level_rules:
                level = rule_data["level"]
                received_levels.add(level)
                rule = existing.get(level)
                if rule:
                    for field, value in rule_data.items():
                        setattr(rule, field, value)
                    rule.save()
                else:
                    ReferralLevelRule.objects.create(program=instance, **rule_data)
            instance.level_rules.exclude(level__in=received_levels).delete()
        elif legacy_referrer_reward is not None:
            ReferralLevelRule.objects.update_or_create(
                program=instance,
                level=1,
                defaults={"reward_type": ReferralLevelRule.RewardType.FIXED, "amount": legacy_referrer_reward, "active": True},
            )
        level_one = instance.level_rules.filter(level=1).first()
        if level_rules is not None and level_one and level_one.reward_type == ReferralLevelRule.RewardType.FIXED:
            instance.referrer_reward = level_one.amount
            instance.save(update_fields=["referrer_reward"])
        return instance


class ReferralRewardSerializer(serializers.ModelSerializer):
    recipient_email = serializers.EmailField(source="recipient.email", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True, allow_null=True)

    class Meta:
        model = ReferralReward
        fields = [
            "id", "recipient_email", "recipient_type", "order_number", "level",
            "reward_type", "amount", "status", "eligible_order_amount",
            "configuration_version", "created_at",
        ]


class CustomerReferralRewardSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True, allow_null=True)

    class Meta:
        model = ReferralReward
        fields = ["id", "recipient_type", "order_number", "level", "amount", "status", "created_at"]


class WalletLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletLedger
        fields = [
            "id", "amount", "description", "transaction_type", "currency",
            "order", "level", "status", "created_at",
        ]


class AdminWalletLedgerSerializer(WalletLedgerSerializer):
    customer_email = serializers.EmailField(source="customer.email", read_only=True)

    class Meta(WalletLedgerSerializer.Meta):
        fields = WalletLedgerSerializer.Meta.fields + ["customer_email", "idempotency_key"]


class ReferralValidationSerializer(serializers.Serializer):
    referral_code = serializers.CharField(max_length=8)


class ReferralValidationResultSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    detail = serializers.CharField(required=False)


class ReferralSerializer(serializers.ModelSerializer):
    referrer_email = serializers.EmailField(source="referrer.email", read_only=True)
    referred_email = serializers.EmailField(source="referred.email", read_only=True)
    rewards = ReferralRewardSerializer(many=True, read_only=True)
    order_number = serializers.CharField(source="qualifying_order.order_number", read_only=True, allow_null=True)

    class Meta:
        model = Referral
        fields = ["id", "referrer_email", "referred_email", "status", "order_number", "created_at", "completed_at", "rewards"]


class CustomerReferralSerializer(serializers.ModelSerializer):
    level = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = ["id", "level", "status", "created_at"]

    def get_level(self, obj):
        return 1


class ReferralDashboardSerializer(serializers.Serializer):
    referral_code = serializers.CharField()
    referral_url = serializers.CharField()


class AdminWalletAdjustmentSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    transaction_type = serializers.ChoiceField(choices=["credit", "debit"])
    reason = serializers.CharField(max_length=180)
    idempotency_key = serializers.CharField(max_length=100)

    def validate_customer_id(self, value):
        if not User.objects.filter(pk=value, role=User.Role.CUSTOMER).exists():
            raise serializers.ValidationError("Customer account was not found.")
        return value
