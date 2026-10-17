from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import AdminCategoryViewSet, AdminProductViewSet, CategoryViewSet, ProductViewSet, dashboard

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("products", ProductViewSet, basename="product")
admin_router = DefaultRouter()
admin_router.register("products", AdminProductViewSet, basename="admin-product")
admin_router.register("categories", AdminCategoryViewSet, basename="admin-category")

urlpatterns = [
    path("", include(router.urls)),
    path("admin/", include(admin_router.urls)),
    path("admin/dashboard/", dashboard),
]
