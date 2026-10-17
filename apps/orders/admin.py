from django.contrib import admin
from .models import InventoryMovement, Order, OrderItem

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ["product", "product_name", "sku", "unit_price", "quantity", "line_total"]

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_number", "customer", "status", "total", "payment_method", "created_at"]
    list_filter = ["status", "payment_method", "created_at"]
    search_fields = ["order_number", "customer__email", "customer_name"]
    inlines = [OrderItemInline]
    readonly_fields = ["order_number", "customer", "status", "subtotal", "delivery_fee", "total", "created_at"]

@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ["order", "product", "kind", "quantity", "created_at"]
    readonly_fields = ["order", "product", "kind", "quantity", "created_at"]
