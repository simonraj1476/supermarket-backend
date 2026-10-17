from django.urls import path
from rest_framework.views import APIView
from rest_framework import mixins, viewsets
from rest_framework.response import Response
from apps.catalog.permissions import IsStoreAdmin
from .models import User
from .serializers import AdminCustomerSerializer, AdminStaffSerializer
from rest_framework_simplejwt.views import TokenRefreshView
from .views import LoginView, LogoutView, MeView, RegisterView
from apps.customer_services.models import AdminAuditEntry

class AdminCustomersView(APIView):
    permission_classes = [IsStoreAdmin]
    serializer_class = AdminCustomerSerializer

    def get(self, request):
        customers = User.objects.filter(role=User.Role.CUSTOMER).order_by("-date_joined")
        if request.query_params.get("active") in {"true", "false"}:
            customers = customers.filter(is_active=request.query_params["active"] == "true")
        search = request.query_params.get("search", "").strip()
        if search:
            from django.db.models import Q
            customers = customers.filter(Q(email__icontains=search) | Q(phone__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
        return Response([{
            "id": customer.pk,
            "email": customer.email,
            "full_name": customer.get_full_name(),
            "phone": customer.phone,
            "is_active": customer.is_active,
            "joined_at": customer.date_joined,
            "orders_count": customer.orders.count(),
            "referrals_count": customer.sent_referrals.count(),
        } for customer in customers[:100]])

    def patch(self, request, pk=None):
        from rest_framework.exceptions import ValidationError
        from django.shortcuts import get_object_or_404
        customer = get_object_or_404(User, pk=pk or request.data.get("id"), role=User.Role.CUSTOMER)
        is_active = request.data.get("is_active")
        if not isinstance(is_active, bool):
            raise ValidationError({"is_active": "Provide true or false."})
        before = {"is_active": customer.is_active}
        customer.is_active = is_active
        customer.save(update_fields=["is_active"])
        AdminAuditEntry.objects.create(
            actor=request.user, action="update", resource="accounts.user",
            object_id=str(customer.pk), changes={"before": before, "after": {"is_active": is_active}},
        )
        return Response({"id": customer.pk, "is_active": customer.is_active})


class AdminStaffViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.filter(is_staff=True).order_by("email")
    serializer_class = AdminStaffSerializer
    permission_classes = [IsStoreAdmin]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_update(self, serializer):
        staff = serializer.save()
        AdminAuditEntry.objects.create(
            actor=self.request.user, action="update", resource="accounts.staff",
            object_id=str(staff.pk),
            changes={key: str(value) for key, value in serializer.validated_data.items() if key != "password"},
        )

    def perform_create(self, serializer):
        staff = serializer.save()
        AdminAuditEntry.objects.create(
            actor=self.request.user, action="create", resource="accounts.staff",
            object_id=str(staff.pk), changes={"email": staff.email, "role": staff.role},
        )

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/login/", LoginView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("auth/logout/", LogoutView.as_view()),
    path("auth/me/", MeView.as_view()),
    path("admin/customers/", AdminCustomersView.as_view()),
    path("admin/customers/<int:pk>/", AdminCustomersView.as_view()),
    path("admin/staff/", AdminStaffViewSet.as_view({"get": "list", "post": "create"})),
    path("admin/staff/<int:pk>/", AdminStaffViewSet.as_view({"patch": "partial_update"})),
]
