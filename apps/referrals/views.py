from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.catalog.permissions import IsStoreAdmin, allowed_admin_module
from apps.customer_services.models import AdminAuditEntry
from .models import Referral, ReferralProgram, ReferralReward, WalletLedger
from .serializers import (
    AdminWalletAdjustmentSerializer,
    AdminWalletLedgerSerializer,
    CustomerReferralRewardSerializer,
    ReferralDashboardSerializer,
    ReferralProgramSerializer,
    ReferralSerializer,
    ReferralValidationSerializer,
    WalletLedgerSerializer,
)


def referral_level_counts(root_id, max_depth):
    frontier = {root_id}
    seen = {root_id}
    levels = []
    for level in range(1, max_depth + 1):
        children = list(
            Referral.objects.filter(referrer_id__in=frontier)
            .values_list("referred_id", flat=True)
            .order_by()
        )
        children = [customer_id for customer_id in children if customer_id not in seen]
        levels.append({"level": level, "count": len(children)})
        seen.update(children)
        frontier = set(children)
        if not frontier:
            levels.extend({"level": remaining, "count": 0} for remaining in range(level + 1, max_depth + 1))
            break
    return levels


def referral_level_map(root_id, max_depth):
    frontier = {root_id}
    seen = {root_id}
    levels = {}
    for level in range(1, max_depth + 1):
        children = Referral.objects.filter(referrer_id__in=frontier).values_list("referred_id", flat=True)
        next_frontier = set()
        for customer_id in children:
            if customer_id not in seen:
                levels[customer_id] = level
                seen.add(customer_id)
                next_frontier.add(customer_id)
        frontier = next_frontier
        if not frontier:
            break
    return levels


class ReferralAdminPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.is_staff
            and allowed_admin_module(user, "referrals")
        )


class ReferralSettingsPermission(ReferralAdminPermission):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        return bool(
            user.role in {User.Role.ADMIN, User.Role.SUPER_ADMIN}
            or user.has_perm("referrals.change_referralprogram")
        )


class ReferralValidateView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "referral_validation"
    serializer_class = ReferralValidationSerializer

    def post(self, request):
        serializer = ReferralValidationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data["referral_code"].strip().upper()
        if code and not ReferralProgram.current().active:
            return Response({"valid": False, "detail": "The referral program is not currently active."}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(referral_code=code, is_active=True).first()
        if not user:
            return Response({"valid": False, "detail": "This referral code is not valid."}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.is_authenticated and user.pk == request.user.pk:
            return Response({"valid": False, "detail": "You cannot refer yourself."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"valid": True})


class ReferralMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReferralDashboardSerializer

    def get(self, request):
        payload = {
            "referral_code": request.user.referral_code,
            "referral_url": f"/register?ref={request.user.referral_code}",
        }
        return Response(ReferralDashboardSerializer(payload).data)


class ReferralRewardsView(APIView):
    permission_classes = [ReferralAdminPermission]
    serializer_class = CustomerReferralRewardSerializer

    def get(self, request):
        rewards = ReferralReward.objects.filter(recipient=request.user).select_related("order").order_by("-created_at")
        return Response(CustomerReferralRewardSerializer(rewards, many=True).data)


class ReferralWalletView(APIView):
    permission_classes = [ReferralAdminPermission]

    def get(self, request):
        entries = WalletLedger.objects.filter(customer=request.user).order_by("-created_at")
        balance = entries.aggregate(balance=Sum("amount"))["balance"] or Decimal("0.00")
        return Response({
            "balance": balance,
            "currency": "INR",
            "transactions": WalletLedgerSerializer(entries[:100], many=True).data,
        })


class ReferralPagePagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class AdminReferralsView(APIView):
    permission_classes = [ReferralAdminPermission]
    serializer_class = ReferralSerializer

    def get(self, request):
        referrals = Referral.objects.select_related(
            "referrer", "referred", "qualifying_order",
        ).prefetch_related("rewards").order_by("-created_at")
        search = request.query_params.get("search", "").strip()
        if search:
            referrals = referrals.filter(
                Q(referrer__first_name__icontains=search)
                | Q(referrer__last_name__icontains=search)
                | Q(referrer__email__icontains=search)
                | Q(referrer__phone__icontains=search)
                | Q(referrer__referral_code__icontains=search)
                | Q(referred__first_name__icontains=search)
                | Q(referred__last_name__icontains=search)
                | Q(referred__email__icontains=search)
                | Q(referred__phone__icontains=search)
                | Q(referred__referral_code__icontains=search)
            )
        if request.query_params.get("status"):
            referrals = referrals.filter(status=request.query_params["status"])
        if request.query_params.get("reward_status"):
            referrals = referrals.filter(rewards__status=request.query_params["reward_status"]).distinct()
        if request.query_params.get("date_from"):
            referrals = referrals.filter(created_at__date__gte=request.query_params["date_from"])
        if request.query_params.get("date_to"):
            referrals = referrals.filter(created_at__date__lte=request.query_params["date_to"])
        paginator = ReferralPagePagination()
        page = paginator.paginate_queryset(referrals, request, view=self)
        return paginator.get_paginated_response(ReferralSerializer(page, many=True).data)


class AdminReferralNetworkView(APIView):
    permission_classes = [ReferralAdminPermission]

    def get(self, request):
        program = ReferralProgram.current()
        customers = User.objects.filter(role=User.Role.CUSTOMER).order_by("-date_joined")
        search = request.query_params.get("search", "").strip()
        if search:
            customers = customers.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(referral_code__icontains=search)
            )
        if request.query_params.get("status") == "active":
            customers = customers.filter(is_active=True)
        elif request.query_params.get("status") == "inactive":
            customers = customers.filter(is_active=False)
        referral_status = request.query_params.get("referral_status")
        if referral_status == "unreferred":
            customers = customers.exclude(pk__in=Referral.objects.values_list("referred_id", flat=True))
        elif referral_status:
            customers = customers.filter(pk__in=Referral.objects.filter(status=referral_status).values_list("referred_id", flat=True))
        if request.query_params.get("date_from"):
            customers = customers.filter(date_joined__date__gte=request.query_params["date_from"])
        if request.query_params.get("date_to"):
            customers = customers.filter(date_joined__date__lte=request.query_params["date_to"])

        ancestor_id = request.query_params.get("ancestor_id")
        selected_level = request.query_params.get("level")
        level_map = None
        if ancestor_id:
            try:
                ancestor_id = int(ancestor_id)
            except (TypeError, ValueError):
                return Response({"detail": "ancestor_id must be a valid customer ID."}, status=status.HTTP_400_BAD_REQUEST)
            if not User.objects.filter(pk=ancestor_id, role=User.Role.CUSTOMER).exists():
                raise NotFound("Customer not found.")
            level_map = referral_level_map(ancestor_id, program.max_depth)
            customers = customers.filter(pk__in=level_map)
            if selected_level:
                try:
                    selected_level = int(selected_level)
                except (TypeError, ValueError):
                    return Response({"detail": "level must be an integer between 1 and 6."}, status=status.HTTP_400_BAD_REQUEST)
                if selected_level < 1 or selected_level > program.max_depth:
                    return Response({"detail": "level is outside the configured referral depth."}, status=status.HTTP_400_BAD_REQUEST)
                ids = [customer_id for customer_id, level in level_map.items() if level == selected_level]
                customers = customers.filter(pk__in=ids)
        elif selected_level:
            return Response({"detail": "Select an ancestor_id when filtering the network by level."}, status=status.HTTP_400_BAD_REQUEST)

        paginator = ReferralPagePagination()
        page = paginator.paginate_queryset(customers, request, view=self)
        ids = [customer.pk for customer in page]
        attributions = {
            referral.referred_id: referral
            for referral in Referral.objects.filter(referred_id__in=ids).select_related("referrer")
        }
        direct_counts = dict(
            Referral.objects.filter(referrer_id__in=ids)
            .values("referrer_id")
            .annotate(total=Count("pk"))
            .values_list("referrer_id", "total")
        )
        results = []
        for customer in page:
            attribution = attributions.get(customer.pk)
            results.append({
                "id": customer.pk,
                "email": customer.email,
                "full_name": customer.get_full_name(),
                "phone": customer.phone,
                "referral_code": customer.referral_code,
                "is_active": customer.is_active,
                "date_joined": customer.date_joined,
                "direct_referrer": ({
                    "id": attribution.referrer_id,
                    "name": attribution.referrer.get_full_name(),
                    "email": attribution.referrer.email,
                } if attribution else None),
                "referral_status": attribution.status if attribution else "unreferred",
                "level": level_map.get(customer.pk) if level_map is not None else None,
                "direct_referrals": direct_counts.get(customer.pk, 0),
            })
        return paginator.get_paginated_response(results)


class AdminReferralNetworkDetailView(APIView):
    permission_classes = [ReferralAdminPermission]

    def get(self, request, customer_id):
        customer = User.objects.filter(pk=customer_id, role=User.Role.CUSTOMER).first()
        if not customer:
            raise NotFound("Customer not found.")
        program = ReferralProgram.current()
        attribution = Referral.objects.filter(referred=customer).select_related("referrer").first()
        direct_referrals = Referral.objects.filter(referrer=customer).select_related("referred").order_by("-created_at")
        level_counts = referral_level_counts(customer.pk, program.max_depth)
        rewards = ReferralReward.objects.filter(
            Q(recipient=customer) | Q(referral__referred=customer)
        ).select_related("recipient", "order").order_by("-created_at")[:100]
        wallet_entries = WalletLedger.objects.filter(customer=customer).order_by("-created_at")[:100]
        return Response({
            "customer": {
                "id": customer.pk,
                "full_name": customer.get_full_name(),
                "email": customer.email,
                "phone": customer.phone,
                "referral_code": customer.referral_code,
                "is_active": customer.is_active,
                "date_joined": customer.date_joined,
            },
            "direct_referrer": ({
                "id": attribution.referrer_id,
                "full_name": attribution.referrer.get_full_name(),
                "email": attribution.referrer.email,
            } if attribution else None),
            "level_counts": level_counts,
            "direct_referrals": [{
                "id": item.referred_id,
                "full_name": item.referred.get_full_name(),
                "email": item.referred.email,
                "referral_code": item.referred.referral_code,
                "status": item.status,
                "created_at": item.created_at,
            } for item in direct_referrals[:100]],
            "direct_referral_count": direct_referrals.count(),
            "rewards": [{
                **{
                    "id": reward.pk,
                    "recipient_email": reward.recipient.email,
                    "order_number": reward.order.order_number if reward.order_id else None,
                    "level": reward.level,
                    "amount": reward.amount,
                    "status": reward.status,
                    "created_at": reward.created_at,
                }
            } for reward in rewards],
            "wallet_transactions": AdminWalletLedgerSerializer(
                WalletLedger.objects.filter(customer=customer).order_by("-created_at")[:100], many=True,
            ).data,
            "wallet_balance": WalletLedger.objects.filter(customer=customer).aggregate(balance=Sum("amount"))["balance"] or Decimal("0.00"),
        })


class AdminReferralStatsView(APIView):
    permission_classes = [ReferralAdminPermission]

    def get(self, request):
        program = ReferralProgram.current()
        referrals = list(Referral.objects.values_list("referrer_id", "referred_id", "status"))
        parent = {referred_id: referrer_id for referrer_id, referred_id, _ in referrals}
        level_counts = defaultdict(int)
        for _, referred_id, _ in referrals:
            ancestor_id = parent.get(referred_id)
            level = 1
            seen = {referred_id}
            while ancestor_id and ancestor_id not in seen and level <= program.max_depth:
                level_counts[level] += 1
                seen.add(ancestor_id)
                ancestor_id = parent.get(ancestor_id)
                level += 1
        reward_counts = dict(
            ReferralReward.objects.values("status").annotate(total=Count("pk")).values_list("status", "total")
        )
        active_customer_ids = set(User.objects.filter(role=User.Role.CUSTOMER, is_active=True).values_list("pk", flat=True))
        active_referrals = sum(
            1 for _, referred_id, state in referrals
            if state != Referral.Status.INACTIVE and referred_id in active_customer_ids
        )
        inactive_referrals = len(referrals) - active_referrals
        return Response({
            "total_customers": User.objects.filter(role=User.Role.CUSTOMER).count(),
            "customers_with_referrer": Referral.objects.values("referred_id").distinct().count(),
            "total_direct_referrals": len(referrals),
            "total_downline_members": sum(level_counts.values()),
            "members_by_level": [{"level": level, "count": level_counts[level]} for level in range(1, program.max_depth + 1)],
            "active_referrals": active_referrals,
            "inactive_referrals": inactive_referrals,
            "pending_rewards": reward_counts.get(ReferralReward.Status.PENDING, 0) + Referral.objects.filter(status=Referral.Status.PENDING).count(),
            "credited_rewards": reward_counts.get(ReferralReward.Status.CREDITED, 0),
            "reversed_rewards": reward_counts.get(ReferralReward.Status.REVERSED, 0),
            "ineligible_rewards": reward_counts.get(ReferralReward.Status.INELIGIBLE, 0),
            "wallet_credits_issued": WalletLedger.objects.filter(transaction_type=WalletLedger.TransactionType.CREDIT, amount__gt=0).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
            "reward_liability": ReferralReward.objects.filter(status=ReferralReward.Status.PENDING).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        })


class AdminRewardsView(APIView):
    permission_classes = [ReferralAdminPermission]
    serializer_class = AdminWalletLedgerSerializer

    def get(self, request):
        entries = WalletLedger.objects.select_related("customer", "order").order_by("-created_at")
        if request.query_params.get("status"):
            entries = entries.filter(status=request.query_params["status"])
        if request.query_params.get("search"):
            search = request.query_params["search"].strip()
            entries = entries.filter(
                Q(customer__email__icontains=search)
                | Q(customer__first_name__icontains=search)
                | Q(customer__last_name__icontains=search)
                | Q(customer__phone__icontains=search)
                | Q(customer__referral_code__icontains=search)
            )
        paginator = ReferralPagePagination()
        page = paginator.paginate_queryset(entries, request, view=self)
        return paginator.get_paginated_response(AdminWalletLedgerSerializer(page, many=True).data)


class AdminReferralProgramView(APIView):
    permission_classes = [ReferralSettingsPermission]
    serializer_class = ReferralProgramSerializer

    def get(self, request):
        program = ReferralProgram.current()
        return Response(self._settings_payload(program, request.user))

    @transaction.atomic
    def patch(self, request):
        program = ReferralProgram.objects.select_for_update().filter(pk=1).first()
        if program is None:
            program = ReferralProgram.current()
            program = ReferralProgram.objects.select_for_update().get(pk=program.pk)
        before = ReferralProgramSerializer(program).data
        serializer = ReferralProgramSerializer(program, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        program = serializer.save(configuration_version=program.configuration_version + 1)
        AdminAuditEntry.objects.create(
            actor=request.user,
            action="update",
            resource="referrals.referralprogram",
            object_id=str(program.pk),
            changes={"before": before, "after": ReferralProgramSerializer(program).data},
        )
        return Response(self._settings_payload(program, request.user))

    @staticmethod
    def _settings_payload(program, user):
        payload = ReferralProgramSerializer(program).data
        payload["can_manage_settings"] = bool(
            user.role in {User.Role.ADMIN, User.Role.SUPER_ADMIN}
            or user.has_perm("referrals.change_referralprogram")
        )
        return payload


class AdminWalletAdjustmentView(APIView):
    permission_classes = [IsStoreAdmin]

    @transaction.atomic
    def post(self, request):
        if request.user.role not in {User.Role.ADMIN, User.Role.SUPER_ADMIN}:
            return Response({"detail": "Only administrators can adjust wallet balances."}, status=status.HTTP_403_FORBIDDEN)
        serializer = AdminWalletAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        key = values["idempotency_key"]
        customer = User.objects.select_for_update().get(pk=values["customer_id"])
        amount = values["amount"] if values["transaction_type"] == "credit" else -values["amount"]
        entry = WalletLedger.objects.select_for_update().filter(idempotency_key=key).first()
        if entry is None:
            if amount < 0:
                balance = WalletLedger.objects.filter(customer=customer).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
                if balance + amount < 0:
                    return Response({"amount": "A wallet debit cannot make the available balance negative."}, status=status.HTTP_400_BAD_REQUEST)
            entry, created = WalletLedger.objects.get_or_create(
                idempotency_key=key,
                defaults={
                    "customer": customer,
                    "amount": amount,
                    "description": values["reason"],
                    "transaction_type": WalletLedger.TransactionType.ADJUSTMENT,
                    "currency": "INR",
                    "idempotency_key": key,
                },
            )
        else:
            created = False
        if (
            entry.customer_id != customer.pk
            or entry.amount != amount
            or entry.description != values["reason"]
            or entry.transaction_type != WalletLedger.TransactionType.ADJUSTMENT
        ):
            return Response({"idempotency_key": "This key was already used for a different adjustment."}, status=status.HTTP_409_CONFLICT)
        AdminAuditEntry.objects.create(
            actor=request.user,
            action="create" if created else "retry",
            resource="referrals.walletledger",
            object_id=str(entry.pk),
            changes={"customer_id": customer.pk, "amount": str(entry.amount), "reason": values["reason"], "idempotency_key": key},
        )
        return Response(AdminWalletLedgerSerializer(entry).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
