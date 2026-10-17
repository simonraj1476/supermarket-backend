from rest_framework import filters, permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from datetime import datetime, time, timedelta
from django.db.models import Sum, Avg, F
from django.utils import timezone
from django.utils.dateparse import parse_date
from .models import Category, Product
from .permissions import IsStoreAdmin
from .serializers import AdminProductSerializer, CategorySerializer, ProductSerializer

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.filter(is_active=True, category__is_active=True).select_related("category")
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description", "category__name"]
    ordering_fields = ["name", "price"]
    ordering = ["name"]
    filterset_fields = ["category", "is_featured"]

class AdminProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related("category").all()
    serializer_class = AdminProductSerializer
    permission_classes = [IsStoreAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "sku"]

    def destroy(self, request, *args, **kwargs):
        product = self.get_object()
        product.is_active = False
        product.save(update_fields=["is_active"])
        from apps.customer_services.views import audit_admin_change
        audit_admin_change(request, product, "deactivate", {"sku": product.sku})
        return Response(status=204)

    def perform_create(self, serializer):
        product = serializer.save()
        from apps.customer_services.views import audit_admin_change
        audit_admin_change(self.request, product, "create", {"sku": product.sku})

    def perform_update(self, serializer):
        product = serializer.save()
        from apps.customer_services.views import audit_admin_change
        audit_admin_change(self.request, product, "update", {key: str(value.pk) if hasattr(value, "pk") else str(value) for key, value in serializer.validated_data.items()})

class AdminCategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsStoreAdmin]

    def perform_create(self, serializer):
        category = serializer.save()
        from apps.customer_services.views import audit_admin_change
        audit_admin_change(self.request, category, "create", {"name": category.name})

    def perform_update(self, serializer):
        category = serializer.save()
        from apps.customer_services.views import audit_admin_change
        audit_admin_change(self.request, category, "update", {"name": category.name})

@extend_schema(responses={
    "200": {
        "type": "object",
        "properties": {
            "orders": {"type": "integer"},
            "pending_orders": {"type": "integer"},
            "delivered_orders": {"type": "integer"},
            "customers": {"type": "integer"},
            "active_products": {"type": "integer"},
            "low_stock_products": {"type": "integer"},
            "sales_total": {"type": "number"},
            "referrals": {"type": "integer"},
            "rewards_issued": {"type": "integer"},
            "recent_orders": {"type": "array", "items": {"type": "object"}},
        },
    },
})
@api_view(["GET"])
@permission_classes([IsStoreAdmin])
def dashboard(request):
    from apps.orders.models import Order
    from apps.accounts.models import User
    from apps.referrals.models import Referral, ReferralReward
    from apps.customer_services.models import CustomerRequest, ResellerCommission, ResellerPayoutRequest, ReturnRequest, SupportTicket, Refund
    from apps.orders.models import OrderItem

    now = timezone.localtime()
    period = request.query_params.get("period", "last_30_days")
    if period == "all_time":
        start, end = None, None
    elif period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "last_7_days":
        start, end = now - timedelta(days=7), now
    elif period == "this_month":
        start, end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    elif period == "custom":
        start_date = parse_date(request.query_params.get("start", ""))
        end_date = parse_date(request.query_params.get("end", ""))
        if not start_date or not end_date or start_date > end_date:
            return Response({"detail": "Custom date range requires valid start and end dates."}, status=400)
        start, end = timezone.make_aware(datetime.combine(start_date, time.min)), timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min))
    else:
        period = "last_30_days"
        start, end = now - timedelta(days=30), now
    period_orders = Order.objects.all() if period == "all_time" else Order.objects.filter(created_at__gte=start, created_at__lt=end)
    active_orders = period_orders.exclude(status=Order.Status.CANCELLED)
    gross_sales = active_orders.aggregate(total=Sum("total"))["total"] or 0
    product_sales = OrderItem.objects.all() if period == "all_time" else OrderItem.objects.filter(
        order__created_at__gte=start, order__created_at__lt=end,
    )
    product_sales = product_sales.exclude(order__status=Order.Status.CANCELLED).values("product_name").annotate(
        quantity=Sum("quantity"),
    ).order_by("-quantity")[:5]
    top_products = list(product_sales)
    financial_allowed = request.user.role in {"admin", "super_admin", "finance_manager"}
    response = {
        "period": period,
        "range": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "orders": period_orders.count(),
        "awaiting_confirmation": period_orders.filter(status=Order.Status.PENDING).count(),
        "processing_orders": period_orders.filter(status__in=[Order.Status.PROCESSING, Order.Status.PACKED]).count(),
        "out_for_delivery": period_orders.filter(status=Order.Status.OUT_FOR_DELIVERY).count(),
        "delivered_orders": period_orders.filter(status=Order.Status.DELIVERED).count(),
        "cancelled_orders": period_orders.filter(status=Order.Status.CANCELLED).count(),
        "customers": User.objects.filter(role="customer").count(),
        "new_customers": (
            User.objects.filter(role="customer").count()
            if period == "all_time"
            else User.objects.filter(role="customer", date_joined__gte=start, date_joined__lt=end).count()
        ),
        "active_products": Product.objects.filter(is_active=True).count(),
        "low_stock_products": Product.objects.filter(is_active=True, stock__gt=0, stock__lte=F("low_stock_threshold")).count(),
        "out_of_stock_products": Product.objects.filter(is_active=True, stock=0).count(),
        "pending_support_tickets": SupportTicket.objects.filter(status__in=["open", "in_progress"]).count(),
        "pending_requests": CustomerRequest.objects.filter(status__in=["submitted", "in_progress"]).count(),
        "pending_returns": ReturnRequest.objects.filter(status="submitted").count(),
        "referrals": Referral.objects.count(),
        "rewards_issued": ReferralReward.objects.count(),
        "top_products": top_products,
        "recent_orders": list(period_orders.order_by("-created_at").values("id", "order_number", "status", "created_at")[:8]),
        "financials_available": financial_allowed,
    }
    if financial_allowed:
        financial_product_sales = OrderItem.objects.all() if period == "all_time" else OrderItem.objects.filter(
            order__created_at__gte=start, order__created_at__lt=end,
        )
        top_products = list(
            financial_product_sales.exclude(order__status=Order.Status.CANCELLED)
            .values("product_name").annotate(quantity=Sum("quantity"), revenue=Sum("line_total"))
            .order_by("-quantity")[:5]
        )
        response["top_products"] = top_products
        response.update({
            "gross_sales": gross_sales,
            "refund_total": (
                Refund.objects.filter(status=Refund.Status.RECORDED).aggregate(total=Sum("amount"))["total"] or 0
                if period == "all_time"
                else Refund.objects.filter(created_at__gte=start, created_at__lt=end, status=Refund.Status.RECORDED).aggregate(total=Sum("amount"))["total"] or 0
            ),
            "average_order_value": active_orders.aggregate(value=Avg("total"))["value"] or 0,
            "pending_commissions": ResellerCommission.objects.filter(status="pending").aggregate(total=Sum("amount"))["total"] or 0,
            "approved_commissions": ResellerCommission.objects.filter(status="approved").aggregate(total=Sum("amount"))["total"] or 0,
            "pending_payouts": ResellerPayoutRequest.objects.filter(status="pending").aggregate(total=Sum("amount"))["total"] or 0,
        })
        response["net_sales"] = gross_sales - response["refund_total"]
        response["recent_orders"] = list(period_orders.order_by("-created_at").values("id", "order_number", "status", "total", "created_at")[:8])
    response["sales_total"] = response.get("gross_sales", 0)
    return Response(response)
