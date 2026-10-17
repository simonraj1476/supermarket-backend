from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.catalog.permissions import IsStoreAdmin
from apps.customer_services.models import AdminAuditEntry
from .models import Order
from .serializers import CreateOrderSerializer, OrderSerializer
from .services import change_order_status, place_order

class OrderListCreateView(generics.ListAPIView):
    queryset = Order.objects.none()
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user).prefetch_related("items")

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = place_order(customer=request.user, payload=serializer.validated_data)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user).prefetch_related("items")


class CustomerCancelOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        order = Order.objects.filter(customer=request.user).filter(pk=pk).first()
        if not order:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        order = change_order_status(order=order, new_status=Order.Status.CANCELLED)
        return Response(OrderSerializer(order).data)


class AdminOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = Order.objects.select_related("customer").prefetch_related("items")
    serializer_class = OrderSerializer
    permission_classes = [IsStoreAdmin]
    filterset_fields = ["status"]
    search_fields = ["order_number", "customer__email", "customer_name"]
    http_method_names = ["get", "patch", "head", "options"]

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        old_status = order.status
        order = change_order_status(order=order, new_status=request.data.get("status", ""))
        AdminAuditEntry.objects.create(
            actor=request.user, action="status_change", resource="orders.order",
            object_id=str(order.pk), changes={"before": old_status, "after": order.status},
        )
        return Response(self.get_serializer(order).data)
