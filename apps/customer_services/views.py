from decimal import Decimal
import csv
import io
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.catalog.permissions import IsStoreAdmin
from apps.orders.models import Order
from .models import (
    Address, AdminAuditEntry, BlogCategory, BlogPost, CommissionRule, Coupon, HomepageBanner,
    CouponRedemption, CustomerQuestion,
    CustomerRequest, ResellerAttribution, ResellerCommission,
    ResellerPayoutAllocation, ResellerPayoutRequest, ResellerProfile,
    ReturnRequest, StoreInformation, SupportTicket, WishlistItem, SystemSettings,
    DeliveryArea, DeliveryPersonnel, DeliveryAssignment, PaymentTransaction,
    PaymentEvent, Refund, InventoryAdjustment,
)
from .serializers import (
    AddressSerializer, AdminCustomerQuestionSerializer,
    AdminCustomerRequestSerializer, AdminReturnRequestSerializer,
    AdminSupportTicketSerializer, BlogCategorySerializer, BlogPostSerializer,
    CommissionRuleSerializer, CustomerQuestionSerializer, CustomerRequestSerializer, PayoutRequestAdminSerializer,
    PayoutRequestSerializer, ResellerApplicationSerializer,
    ResellerCommissionSerializer, ResellerProfileAdminSerializer,
    PublicStoreInformationSerializer, ReturnRequestSerializer, StoreInformationSerializer,
    SupportTicketSerializer, WishlistItemSerializer, CouponSerializer,
    SystemSettingsSerializer, DeliveryAreaSerializer, DeliveryPersonnelSerializer,
    DeliveryAssignmentSerializer, PaymentTransactionSerializer, RefundSerializer, HomepageBannerSerializer,
)
from apps.catalog.models import Product


class CustomerModelViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return self.queryset.filter(customer=self.request.user)

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)


class AddressViewSet(CustomerModelViewSet):
    queryset = Address.objects.all()
    serializer_class = AddressSerializer

    def perform_create(self, serializer):
        with transaction.atomic():
            if serializer.validated_data.get("is_default"):
                Address.objects.filter(customer=self.request.user, is_default=True).update(is_default=False, default_for_customer=None)
            serializer.save(customer=self.request.user)

    def perform_update(self, serializer):
        with transaction.atomic():
            if serializer.validated_data.get("is_default", serializer.instance.is_default):
                Address.objects.filter(customer=self.request.user, is_default=True).exclude(pk=serializer.instance.pk).update(is_default=False, default_for_customer=None)
            serializer.save()


class WishlistViewSet(CustomerModelViewSet):
    queryset = WishlistItem.objects.select_related("product")
    serializer_class = WishlistItemSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, created = WishlistItem.objects.get_or_create(customer=request.user, product=serializer.validated_data["product"])
        result = self.get_serializer(item)
        return Response(result.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CustomerQuestionViewSet(CustomerModelViewSet):
    queryset = CustomerQuestion.objects.select_related("order")
    serializer_class = CustomerQuestionSerializer
    http_method_names = ["get", "post", "head", "options"]


class CustomerRequestViewSet(CustomerModelViewSet):
    queryset = CustomerRequest.objects.all()
    serializer_class = CustomerRequestSerializer
    http_method_names = ["get", "post", "head", "options"]


class SupportTicketViewSet(CustomerModelViewSet):
    queryset = SupportTicket.objects.all()
    serializer_class = SupportTicketSerializer
    http_method_names = ["get", "post", "head", "options"]


class ReturnRequestViewSet(CustomerModelViewSet):
    queryset = ReturnRequest.objects.select_related("order")
    serializer_class = ReturnRequestSerializer
    http_method_names = ["get", "post", "head", "options"]


class AdminCustomerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStoreAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        changes = {key: value.pk if hasattr(value, "pk") else value for key, value in serializer.validated_data.items()}
        instance = serializer.save()
        if isinstance(instance, SupportTicket):
            if "response" in serializer.validated_data and serializer.validated_data["response"] and not instance.first_response_at:
                instance.first_response_at = timezone.now()
            if instance.status == SupportTicket.Status.RESOLVED and not instance.resolved_at:
                instance.resolved_at = timezone.now()
            elif instance.status != SupportTicket.Status.RESOLVED:
                instance.resolved_at = None
            instance.save(update_fields=["first_response_at", "resolved_at", "updated_at"])
        audit_admin_change(self.request, instance, "update", changes)


class AdminQuestionViewSet(AdminCustomerViewSet):
    queryset = CustomerQuestion.objects.select_related("customer", "order")
    serializer_class = AdminCustomerQuestionSerializer


class AdminRequestViewSet(AdminCustomerViewSet):
    queryset = CustomerRequest.objects.select_related("customer")
    serializer_class = AdminCustomerRequestSerializer


class AdminSupportTicketViewSet(AdminCustomerViewSet):
    queryset = SupportTicket.objects.select_related("customer")
    serializer_class = AdminSupportTicketSerializer


class AdminSupportAgentsView(APIView):
    permission_classes = [IsStoreAdmin]

    def get(self, request):
        from apps.accounts.models import User
        agents = User.objects.filter(
            is_staff=True, is_active=True,
            role__in=["admin", "super_admin", "customer_support"],
        ).order_by("first_name", "email").values("id", "email", "first_name", "last_name", "role")
        return Response(list(agents))


class AdminReturnRequestViewSet(AdminCustomerViewSet):
    queryset = ReturnRequest.objects.select_related("customer", "order")
    serializer_class = AdminReturnRequestSerializer


class BlogCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BlogCategory.objects.all()
    serializer_class = BlogCategorySerializer
    permission_classes = [permissions.AllowAny]


class BlogPostViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BlogPostSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        posts = BlogPost.objects.select_related("category")
        if self.request.user.is_authenticated and self.request.user.role == "admin":
            queryset = posts
        else:
            queryset = posts.filter(is_published=True)
        category_slug = self.request.query_params.get("category", "").strip()
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset


class AdminBlogPostViewSet(viewsets.ModelViewSet):
    queryset = BlogPost.objects.select_related("category")
    serializer_class = BlogPostSerializer
    permission_classes = [IsStoreAdmin]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        instance = serializer.save()
        audit_admin_change(self.request, instance, "create", {"title": instance.title, "slug": instance.slug})

    def perform_update(self, serializer):
        instance = serializer.save()
        audit_admin_change(self.request, instance, "update", dict(serializer.validated_data))


class AdminBlogCategoryViewSet(viewsets.ModelViewSet):
    queryset = BlogCategory.objects.all()
    serializer_class = BlogCategorySerializer
    permission_classes = [IsStoreAdmin]


class StoreInformationView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = StoreInformationSerializer

    def get(self, request):
        return Response(PublicStoreInformationSerializer(StoreInformation.current()).data)


class AdminStoreInformationView(APIView):
    permission_classes = [IsStoreAdmin]
    serializer_class = StoreInformationSerializer

    def get(self, request):
        return Response(StoreInformationSerializer(StoreInformation.current()).data)

    def patch(self, request):
        info = StoreInformation.current()
        serializer = StoreInformationSerializer(info, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_admin_change(request, info, "update", dict(serializer.validated_data))
        return Response(serializer.data)


class ResellerMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = ResellerProfile.objects.filter(customer=request.user).first()
        if not profile:
            return Response({"application": None})
        commissions = profile.commissions.all()
        payouts = profile.payout_requests.all()
        totals = commissions.values("status").annotate(total=Sum("amount"))
        return Response({
            "application": ResellerApplicationSerializer(profile).data,
            "share_url": f"/register?reseller={profile.reseller_code}" if profile.status == ResellerProfile.Status.APPROVED else None,
            "commission_totals": {item["status"]: item["total"] for item in totals},
            "commissions": ResellerCommissionSerializer(commissions, many=True).data,
            "payouts": PayoutRequestSerializer(payouts, many=True).data,
        })

    def post(self, request):
        if ResellerProfile.objects.filter(customer=request.user).exists():
            raise ValidationError({"detail": "A reseller application already exists for this account."})
        serializer = ResellerApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save(customer=request.user)
        return Response(ResellerApplicationSerializer(profile).data, status=status.HTTP_201_CREATED)


class ResellerPayoutViewSet(CustomerModelViewSet):
    serializer_class = PayoutRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return ResellerPayoutRequest.objects.filter(reseller__customer=self.request.user)

    def perform_create(self, serializer):
        profile = ResellerProfile.objects.filter(customer=self.request.user, status=ResellerProfile.Status.APPROVED).first()
        if not profile:
            raise ValidationError({"detail": "An approved reseller account is required."})
        serializer.save(reseller=profile)


class AdminResellerViewSet(AdminCustomerViewSet):
    queryset = ResellerProfile.objects.select_related("customer")
    serializer_class = ResellerProfileAdminSerializer
    http_method_names = ["get", "patch", "head", "options"]


class AdminCommissionViewSet(AdminCustomerViewSet):
    queryset = ResellerCommission.objects.select_related("reseller", "order")
    serializer_class = ResellerCommissionSerializer
    http_method_names = ["get", "patch", "head", "options"]


class AdminCommissionRuleView(APIView):
    permission_classes = [IsStoreAdmin]
    serializer_class = CommissionRuleSerializer

    def get(self, request):
        return Response(CommissionRuleSerializer(CommissionRule.current()).data)

    def patch(self, request):
        rule = CommissionRule.current()
        serializer = CommissionRuleSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_admin_change(request, rule, "update", dict(serializer.validated_data))
        return Response(serializer.data)


class AdminPayoutViewSet(viewsets.ModelViewSet):
    queryset = ResellerPayoutRequest.objects.select_related("reseller", "reseller__customer")
    serializer_class = PayoutRequestAdminSerializer
    permission_classes = [IsStoreAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        payout = self.get_object()
        old_status = payout.status
        requested_status = request.data.get("status", old_status)
        allowed_transitions = {
            "pending": {"approved", "rejected"},
            "approved": {"paid", "rejected"},
            "paid": set(),
            "rejected": set(),
        }
        if requested_status != old_status and requested_status not in allowed_transitions[old_status]:
            raise ValidationError({"status": f"Cannot move a payout from {old_status} to {requested_status}."})
        serializer = self.get_serializer(payout, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        payout = serializer.save()
        if old_status != "paid" and payout.status == "paid":
            remaining = payout.amount
            commissions = ResellerCommission.objects.select_for_update().filter(
                reseller=payout.reseller, status=ResellerCommission.Status.APPROVED
            ).order_by("created_at")
            for commission in commissions:
                already_paid = commission.payout_allocations.filter(payout_request__status="paid").aggregate(total=Sum("amount"))["total"] or Decimal("0")
                available = commission.amount - already_paid
                if available <= 0:
                    continue
                allocation = min(available, remaining)
                ResellerPayoutAllocation.objects.create(payout_request=payout, commission=commission, amount=allocation)
                if allocation == available:
                    commission.status = ResellerCommission.Status.PAID
                    commission.save(update_fields=["status", "updated_at"])
                remaining -= allocation
                if remaining <= 0:
                    break
            if remaining > 0:
                raise ValidationError({"status": "Available approved commission changed; this payout cannot be recorded."})
        audit_admin_change(request, payout, "update", dict(serializer.validated_data))
        return Response(self.get_serializer(payout).data)


class AdminCouponViewSet(viewsets.ModelViewSet):
    queryset = Coupon.objects.prefetch_related("products", "categories")
    serializer_class = CouponSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["is_active", "discount_type"]
    search_fields = ["code"]

    def perform_create(self, serializer):
        coupon = serializer.save()
        audit_admin_change(self.request, coupon, "create", {"code": coupon.code})

    def perform_update(self, serializer):
        coupon = serializer.save()
        audit_admin_change(self.request, coupon, "update", {key: str(value.pk) if hasattr(value, "pk") else str(value) for key, value in serializer.validated_data.items()})

    @action(detail=True, methods=["get"])
    def redemptions(self, request, pk=None):
        coupon = self.get_object()
        data = coupon.redemptions.select_related("customer", "order").order_by("-created_at").values(
            "customer__email", "order__order_number", "discount_amount", "created_at"
        )
        return Response(list(data))


class AdminSystemSettingsView(APIView):
    permission_classes = [IsStoreAdmin]
    serializer_class = SystemSettingsSerializer

    def get(self, request):
        return Response(SystemSettingsSerializer(SystemSettings.current()).data)

    def patch(self, request):
        settings = SystemSettings.current()
        serializer = SystemSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_admin_change(request, settings, "update", dict(serializer.validated_data))
        return Response(serializer.data)


class PublicOperationalSettingsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        settings = SystemSettings.current()
        return Response({
            "store_name": settings.store_name,
            "currency": settings.currency,
            "delivery_fee": settings.delivery_fee,
            "free_delivery_threshold": settings.free_delivery_threshold,
            "minimum_order_value": settings.minimum_order_value,
        })


class PublicHomepageBannerView(generics.ListAPIView):
    serializer_class = HomepageBannerSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        now = timezone.now()
        return HomepageBanner.objects.filter(is_active=True, starts_at__lte=now, ends_at__gt=now)


class AdminAuditLogView(APIView):
    permission_classes = [IsStoreAdmin]

    def get(self, request):
        rows = AdminAuditEntry.objects.select_related("actor").order_by("-created_at").values(
            "id", "created_at", "actor__email", "action", "resource", "object_id", "changes"
        )[:200]
        return Response(list(rows))


class AdminHomepageBannerViewSet(viewsets.ModelViewSet):
    queryset = HomepageBanner.objects.all()
    serializer_class = HomepageBannerSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["is_active"]
    search_fields = ["title", "subtitle"]

    def perform_create(self, serializer):
        banner = serializer.save()
        audit_admin_change(self.request, banner, "create", {"title": banner.title})

    def perform_update(self, serializer):
        banner = serializer.save()
        audit_admin_change(self.request, banner, "update", serializer.validated_data)


class AdminDeliveryAreaViewSet(viewsets.ModelViewSet):
    queryset = DeliveryArea.objects.all()
    serializer_class = DeliveryAreaSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["is_active"]
    search_fields = ["name", "pin_code"]

    def perform_create(self, serializer):
        area = serializer.save()
        audit_admin_change(self.request, area, "create", {"pin_code": area.pin_code})


class AdminDeliveryPersonnelViewSet(viewsets.ModelViewSet):
    queryset = DeliveryPersonnel.objects.all()
    serializer_class = DeliveryPersonnelSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["is_active", "is_available"]
    search_fields = ["name", "phone"]


class AdminDeliveryAssignmentViewSet(viewsets.ModelViewSet):
    queryset = DeliveryAssignment.objects.select_related("order", "personnel")
    serializer_class = DeliveryAssignmentSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["status", "personnel"]
    search_fields = ["order__order_number", "order__customer_name", "order__delivery_pin_code"]

    @transaction.atomic
    def perform_update(self, serializer):
        assignment = DeliveryAssignment.objects.select_for_update().get(pk=serializer.instance.pk)
        previous_status = assignment.status
        assignment = serializer.save()
        now = timezone.now()
        if assignment.status == DeliveryAssignment.Status.DISPATCHED and not assignment.dispatched_at:
            assignment.dispatched_at = now
        elif assignment.status == DeliveryAssignment.Status.FAILED:
            assignment.failed_at = now
        elif assignment.status == DeliveryAssignment.Status.DELIVERED:
            assignment.delivered_at = now
            if assignment.order.status == Order.Status.OUT_FOR_DELIVERY:
                from apps.orders.services import change_order_status
                change_order_status(order=assignment.order, new_status=Order.Status.DELIVERED)
        assignment.save()
        audit_admin_change(self.request, assignment, "update", {"before_status": previous_status, "after_status": assignment.status})


class AdminPaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = PaymentTransaction.objects.select_related("order", "order__customer")
    serializer_class = PaymentTransactionSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["method", "status", "cod_collected"]
    search_fields = ["order__order_number", "transaction_reference", "order__customer__email"]
    http_method_names = ["get", "patch", "head", "options"]

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        payment = PaymentTransaction.objects.select_for_update().get(pk=self.get_object().pk)
        if payment.method != PaymentTransaction.Method.COD:
            raise ValidationError({"detail": "Online payment state is immutable until a verified gateway integration is configured."})
        collected = request.data.get("cod_collected")
        if collected is not True:
            raise ValidationError({"cod_collected": "Only a verified COD collection can be recorded."})
        if payment.order.status == Order.Status.CANCELLED:
            raise ValidationError({"cod_collected": "Payment cannot be collected for a cancelled order."})
        if payment.cod_collected and not collected:
            raise ValidationError({"cod_collected": "A completed COD collection cannot be reversed here."})
        before = payment.cod_collected
        payment.cod_collected = collected
        if collected:
            payment.status = PaymentTransaction.Status.SUCCESSFUL
            payment.order.payment_status = Order.PaymentStatus.PAID
            payment.order.save(update_fields=["payment_status", "updated_at"])
        payment.save(update_fields=["cod_collected", "status", "updated_at"])
        PaymentEvent.objects.create(transaction=payment, event_type="cod_collected" if collected else "cod_collection_unconfirmed", details={"actor_id": request.user.pk})
        audit_admin_change(request, payment, "update", {"cod_collected_before": before, "cod_collected_after": collected})
        return Response(self.get_serializer(payment).data)


class AdminRefundViewSet(viewsets.ModelViewSet):
    queryset = Refund.objects.select_related("order", "order__customer", "created_by", "updated_by")
    serializer_class = RefundSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["status"]
    search_fields = ["order__order_number", "order__customer__email"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    @transaction.atomic
    def perform_create(self, serializer):
        order = Order.objects.select_for_update().get(pk=serializer.validated_data["order"].pk)
        refund = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        audit_admin_change(self.request, refund, "create", {"order": order.order_number, "amount": refund.amount, "status": refund.status})

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        refund = Refund.objects.select_for_update().get(pk=self.get_object().pk)
        status_value = request.data.get("status")
        transitions = {
            "requested": {"approved", "rejected"},
            "approved": {"recorded", "processed", "rejected"},
            "recorded": set(), "processed": set(), "rejected": set(),
        }
        if status_value and status_value not in transitions[refund.status]:
            raise ValidationError({"status": f"Cannot move a refund from {refund.status} to {status_value}."})
        if status_value == Refund.Status.PROCESSED:
            raise ValidationError({"status": "Refund transfer cannot be marked processed until a payment gateway or verified transfer integration is configured. For COD, record manual processing instead."})
        old_status = refund.status
        serializer = self.get_serializer(refund, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        refund = serializer.save(updated_by=request.user)
        if refund.status == Refund.Status.RECORDED and refund.order.payment_method != "cod":
            raise ValidationError({"status": "Manual refund recording is only available for Cash on Delivery orders."})
        audit_admin_change(request, refund, "update", {"before_status": old_status, "after_status": refund.status, "reference": refund.transaction_reference})
        if refund.status == Refund.Status.RECORDED:
            recorded_total = refund.order.refunds.filter(status=Refund.Status.RECORDED).aggregate(amount=Sum("amount"))["amount"] or Decimal("0")
            if recorded_total >= refund.order.total and refund.order.payment_status == Order.PaymentStatus.PAID:
                refund.order.payment_status = Order.PaymentStatus.REFUNDED
                refund.order.save(update_fields=["payment_status", "updated_at"])
            from apps.referrals.models import ReferralProgram
            program = ReferralProgram.objects.filter(pk=1).first()
            if program and program.reverse_on_full_refund and recorded_total >= refund.order.total:
                from apps.referrals.services import reverse_referral_rewards_for_order
                reverse_referral_rewards_for_order(refund.order, reason="full refund recorded")
        return Response(self.get_serializer(refund).data)


class AdminInventoryView(APIView):
    permission_classes = [IsStoreAdmin]

    def post(self, request):
        product_id = request.data.get("product_id")
        try:
            quantity_delta = int(request.data.get("quantity_delta"))
        except (TypeError, ValueError):
            raise ValidationError({"quantity_delta": "Enter an integer stock adjustment."})
        reason = str(request.data.get("reason", "")).strip()
        if not reason or len(reason) > 500:
            raise ValidationError({"reason": "A reason of up to 500 characters is required."})
        with transaction.atomic():
            product = Product.objects.select_for_update().filter(pk=product_id).first()
            if not product:
                raise ValidationError({"product_id": "Product not found."})
            if product.stock + quantity_delta < 0:
                raise ValidationError({"quantity_delta": "Stock cannot be reduced below zero."})
            product.stock += quantity_delta
            product.save(update_fields=["stock"])
            adjustment = InventoryAdjustment.objects.create(product=product, actor=request.user, quantity_delta=quantity_delta, reason=reason)
            audit_admin_change(request, adjustment, "stock_adjustment", {"product": product.sku, "delta": quantity_delta, "reason": reason})
        return Response({"id": adjustment.pk, "sku": product.sku, "stock": product.stock}, status=status.HTTP_201_CREATED)


class AdminInventoryImportView(APIView):
    permission_classes = [IsStoreAdmin]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload or upload.size > 5 * 1024 * 1024:
            raise ValidationError({"file": "Upload a CSV file no larger than 5 MB."})
        try:
            text = upload.read().decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
        except (UnicodeDecodeError, csv.Error):
            raise ValidationError({"file": "The upload must be a valid UTF-8 CSV file."})
        required = {"sku", "stock", "reason"}
        if not rows or not required.issubset(rows[0].keys()):
            raise ValidationError({"file": f"CSV headers must include {', '.join(sorted(required))}."})
        errors = []
        successes = []
        with transaction.atomic():
            for index, row in enumerate(rows, start=2):
                try:
                    delta = int(row["stock"])
                    product = Product.objects.select_for_update().get(sku=row["sku"].strip())
                    reason = row["reason"].strip()
                    if not reason or product.stock + delta < 0:
                        raise ValueError("A reason is required and stock cannot be negative.")
                    product.stock += delta
                    product.save(update_fields=["stock"])
                    adjustment = InventoryAdjustment.objects.create(product=product, actor=request.user, quantity_delta=delta, reason=reason[:500])
                    successes.append({"row": index, "sku": product.sku, "stock": product.stock})
                    audit_admin_change(request, adjustment, "stock_adjustment", {"product": product.sku, "delta": delta, "reason": reason[:500]})
                except (Product.DoesNotExist, ValueError) as error:
                    errors.append({"row": index, "error": str(error)})
        return Response({"updated": successes, "errors": errors})


def _csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([f"'{value}" if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value for value in row])
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    response["Cache-Control"] = "no-store"
    return response


class AdminReportView(APIView):
    permission_classes = [IsStoreAdmin]

    def get(self, request, report):
        if report in {"sales", "payments", "refunds", "reseller_commissions", "payouts"} and request.user.role not in {"admin", "super_admin", "finance_manager"}:
            return Response({"detail": "Financial report access is restricted."}, status=403)
        start_date = request.query_params.get("start")
        end_date = request.query_params.get("end")
        start = parse_date(start_date) if start_date else None
        end = parse_date(end_date) if end_date else None
        if (start_date and not start) or (end_date and not end) or (start and end and start > end):
            raise ValidationError({"date_range": "Use valid start and end dates with start on or before end."})
        orders = Order.objects.select_related("customer").all()
        def by_date(queryset, field="created_at"):
            if start:
                queryset = queryset.filter(**{f"{field}__date__gte": start})
            if end:
                queryset = queryset.filter(**{f"{field}__date__lte": end})
            return queryset

        orders = by_date(orders)
        if report in {"orders", "sales"}:
            return _csv_response(report, ["order_number", "customer_email", "status", "payment_method", "payment_status", "subtotal", "discount_amount", "delivery_fee", "total", "created_at"], orders.values_list("order_number", "customer__email", "status", "payment_method", "payment_status", "subtotal", "discount_amount", "delivery_fee", "total", "created_at"))
        if report == "products":
            from apps.orders.models import OrderItem
            data = by_date(OrderItem.objects.exclude(order__status=Order.Status.CANCELLED), "order__created_at").values("product_name").annotate(quantity=Sum("quantity"), revenue=Sum("line_total")).order_by("-quantity")
            return _csv_response(report, ["product", "quantity", "revenue"], [(row["product_name"], row["quantity"], row["revenue"]) for row in data])
        if report == "inventory":
            products = Product.objects.select_related("category").all()
            return _csv_response(report, ["sku", "barcode", "name", "category", "stock", "low_stock_threshold", "active"], products.values_list("sku", "barcode", "name", "category__name", "stock", "low_stock_threshold", "is_active"))
        if report == "customers":
            from apps.accounts.models import User
            customers = by_date(User.objects.filter(role="customer"), "date_joined").values_list("email", "first_name", "last_name", "phone", "is_active", "date_joined")
            return _csv_response(report, ["email", "first_name", "last_name", "phone", "active", "joined"], customers)
        if report == "payments":
            data = by_date(PaymentTransaction.objects.select_related("order")).values_list("order__order_number", "method", "status", "amount", "transaction_reference", "cod_collected", "created_at")
            return _csv_response(report, ["order", "method", "status", "amount", "reference", "cod_collected", "created"], data)
        if report == "refunds":
            data = by_date(Refund.objects.select_related("order")).values_list("order__order_number", "amount", "reason", "status", "transaction_reference", "created_at")
            return _csv_response(report, ["order", "amount", "reason", "status", "reference", "created"], data)
        if report == "coupons":
            data = by_date(CouponRedemption.objects.select_related("coupon", "order", "customer")).values_list("coupon__code", "customer__email", "order__order_number", "discount_amount", "created_at")
            return _csv_response(report, ["coupon", "customer", "order", "discount", "created"], data)
        if report == "referrals":
            from apps.referrals.models import ReferralReward
            data = by_date(ReferralReward.objects.select_related("recipient", "referral")).values_list("recipient__email", "recipient_type", "amount", "created_at")
            return _csv_response(report, ["customer", "type", "amount", "created"], data)
        if report == "reseller_commissions":
            data = by_date(ResellerCommission.objects.select_related("reseller", "order")).values_list("reseller__reseller_code", "order__order_number", "order_amount", "amount", "status", "created_at")
            return _csv_response(report, ["reseller_code", "order", "order_amount", "commission", "status", "created"], data)
        if report == "payouts":
            data = by_date(ResellerPayoutRequest.objects.select_related("reseller")).values_list("request_number", "reseller__reseller_code", "amount", "status", "created_at")
            return _csv_response(report, ["request", "reseller_code", "amount", "status", "created"], data)
        if report == "support":
            data = by_date(SupportTicket.objects.all()).values_list("ticket_number", "subject", "status", "priority", "created_at", "first_response_at", "resolved_at")
            return _csv_response(report, ["ticket", "subject", "status", "priority", "created", "first_response", "resolved"], data)
        raise ValidationError({"report": "Unknown report. Supported reports: sales, orders, products, inventory, customers, payments, refunds, coupons, referrals, reseller_commissions, payouts, support."})


class CustomerRewardsView(APIView):
    permission_classes = [IsStoreAdmin]

    def get(self, request):
        from apps.referrals.models import ReferralReward, WalletLedger
        from apps.referrals.serializers import ReferralRewardSerializer
        wallet = WalletLedger.objects.filter(customer=request.user).aggregate(balance=Sum("amount"))["balance"] or Decimal("0")
        rewards = ReferralReward.objects.filter(recipient=request.user)
        return Response({"wallet_balance": wallet, "referral_rewards": ReferralRewardSerializer(rewards, many=True).data, "coupons": []})


class AdminRewardOverviewView(APIView):
    permission_classes = [IsStoreAdmin]

    def get(self, request):
        from apps.referrals.models import ReferralReward
        from apps.referrals.serializers import ReferralRewardSerializer
        return Response({"referral_rewards": ReferralRewardSerializer(ReferralReward.objects.select_related("recipient"), many=True).data, "coupons": []})


def audit_admin_change(request, instance, action, changes):
    AdminAuditEntry.objects.create(
        actor=request.user,
        action=action,
        resource=instance._meta.label_lower,
        object_id=str(instance.pk),
        changes={key: str(value) for key, value in changes.items()},
    )
