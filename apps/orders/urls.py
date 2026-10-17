from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import AdminOrderViewSet, CustomerCancelOrderView, OrderDetailView, OrderListCreateView

router = DefaultRouter()
router.register("admin/orders", AdminOrderViewSet, basename="admin-order")
urlpatterns = [
    path("orders/", OrderListCreateView.as_view()),
    path("orders/<uuid:pk>/", OrderDetailView.as_view()),
    path("orders/<uuid:pk>/cancel/", CustomerCancelOrderView.as_view()),
    path("", include(router.urls)),
]
