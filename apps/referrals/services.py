from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from .models import Referral, ReferralLevelRule, ReferralProgram, ReferralReward, WalletLedger

CENT = Decimal("0.01")


def _reward_amount(rule, eligible_amount):
    if rule.reward_type == ReferralLevelRule.RewardType.PERCENTAGE:
        return (eligible_amount * rule.amount / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    return rule.amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _create_reward(*, referral, order, recipient, recipient_type, level, amount, eligible_amount, program, rule):
    amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if program.max_reward_per_referral is not None:
        amount = min(amount, program.max_reward_per_referral)
    if amount <= Decimal("0.00"):
        return False
    reward_key = f"referral:{order.pk}:{recipient.pk}:{level}"
    snapshot = {
        "program_version": program.configuration_version,
        "level": level,
        "reward_type": rule.reward_type if rule else "fixed",
        "configured_amount": str(rule.amount if rule else amount),
        "minimum_order_amount": str(program.minimum_order_amount),
        "max_depth": program.max_depth,
    }
    reward, created = ReferralReward.objects.get_or_create(
        idempotency_key=reward_key,
        defaults={
            "referral": referral,
            "recipient": recipient,
            "recipient_type": recipient_type,
            "order": order,
            "level": level,
            "reward_type": program.reward_type,
            "amount": amount,
            "status": ReferralReward.Status.CREDITED,
            "eligible_order_amount": eligible_amount,
            "configuration_version": program.configuration_version,
            "configuration_snapshot": snapshot,
        },
    )
    if not created:
        return False
    WalletLedger.objects.create(
        reward=reward,
        customer=recipient,
        amount=amount,
        description=f"Referral level {level} reward for order {order.order_number}",
        transaction_type=WalletLedger.TransactionType.CREDIT,
        currency="INR",
        order=order,
        referral=referral,
        level=level,
        configuration_version=program.configuration_version,
        idempotency_key=f"wallet:{reward_key}",
    )
    return True


@transaction.atomic
def award_referral_for_order(order):
    program = ReferralProgram.objects.select_for_update().filter(pk=1).first()
    if not program:
        return False
    if not program.active or order.status not in program.qualifying_order_statuses:
        return False
    eligible_amount = max(order.subtotal - order.discount_amount, Decimal("0.00"))
    if eligible_amount < program.minimum_order_amount:
        return False

    purchaser = User.objects.select_for_update().filter(pk=order.customer_id).first()
    if not purchaser:
        return False
    referral = Referral.objects.select_for_update().filter(referred=purchaser).select_related("referrer").first()
    if not referral:
        return False

    if program.reward_on_first_qualifying_order_only and ReferralReward.objects.filter(referral=referral).exists():
        return False

    rules = {
        rule.level: rule
        for rule in ReferralLevelRule.objects.filter(program=program, active=True, level__lte=program.max_depth)
    }
    issued = False

    if program.reward_referred_customer and program.customer_reward > 0:
        customer_rule = ReferralLevelRule(
            program=program,
            level=1,
            reward_type=ReferralLevelRule.RewardType.FIXED,
            amount=program.customer_reward,
        )
        issued |= _create_reward(
            referral=referral,
            order=order,
            recipient=referral.referred,
            recipient_type=ReferralReward.RecipientType.CUSTOMER,
            level=0,
            amount=program.customer_reward,
            eligible_amount=eligible_amount,
            program=program,
            rule=customer_rule,
        )

    ancestor = referral.referrer
    seen = {purchaser.pk}
    for level in range(1, program.max_depth + 1):
        if not ancestor or ancestor.pk in seen:
            break
        seen.add(ancestor.pk)
        rule = rules.get(level)
        should_reward = program.reward_referrer if level == 1 else program.reward_ancestors
        if should_reward and rule:
            amount = _reward_amount(rule, eligible_amount)
            if level == 1 and program.referrer_reward != rule.amount and rule.reward_type == ReferralLevelRule.RewardType.FIXED:
                amount = _reward_amount(
                    ReferralLevelRule(
                        program=program,
                        level=level,
                        reward_type=rule.reward_type,
                        amount=program.referrer_reward,
                    ),
                    eligible_amount,
                )
            recipient_type = ReferralReward.RecipientType.REFERRER if level == 1 else ReferralReward.RecipientType.ANCESTOR
            issued |= _create_reward(
                referral=referral,
                order=order,
                recipient=ancestor,
                recipient_type=recipient_type,
                level=level,
                amount=amount,
                eligible_amount=eligible_amount,
                program=program,
                rule=rule,
            )
        ancestor_referral = Referral.objects.filter(referred=ancestor).select_related("referrer").first()
        ancestor = ancestor_referral.referrer if ancestor_referral else None

    if issued:
        referral.status = Referral.Status.COMPLETED
        if referral.qualifying_order_id is None:
            referral.qualifying_order = order
        referral.completed_at = referral.completed_at or timezone.now()
        referral.save(update_fields=["status", "qualifying_order", "completed_at"])
    return issued


@transaction.atomic
def reverse_referral_rewards_for_order(order, *, reason):
    rewards = ReferralReward.objects.select_for_update().filter(order=order, status=ReferralReward.Status.CREDITED)
    reversed_count = 0
    for reward in rewards:
        entries = WalletLedger.objects.select_for_update().filter(
            reward=reward,
            transaction_type=WalletLedger.TransactionType.CREDIT,
            amount__gt=0,
        )
        for entry in entries:
            WalletLedger.objects.get_or_create(
                idempotency_key=f"reversal:{entry.idempotency_key}",
                defaults={
                    "reward": reward,
                    "customer": entry.customer,
                    "amount": -entry.amount,
                    "description": f"Referral reward reversed for order {order.order_number}: {reason}"[:200],
                    "transaction_type": WalletLedger.TransactionType.REVERSAL,
                    "currency": entry.currency,
                    "order": order,
                    "referral": reward.referral,
                    "level": reward.level,
                    "configuration_version": reward.configuration_version,
                    "reversal_of": entry,
                },
            )
            if entry.status != WalletLedger.Status.REVERSED:
                entry.status = WalletLedger.Status.REVERSED
                entry.save(update_fields=["status"])
        reward.status = ReferralReward.Status.REVERSED
        reward.save(update_fields=["status"])
        reversed_count += 1
    return reversed_count
