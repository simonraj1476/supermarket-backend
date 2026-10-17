from django.contrib import admin
from .models import (
    Address, AdminAuditEntry, BlogCategory, BlogPost, CommissionRule, Coupon, CouponRedemption, CustomerQuestion,
    CustomerRequest, ResellerAttribution, ResellerCommission,
    ResellerPayoutAllocation, ResellerPayoutRequest, ResellerProfile, ReturnRequest, SecurityEvent, StoreInformation,
    SupportTicket, WishlistItem, SystemSettings, DeliveryArea, DeliveryPersonnel,
    DeliveryAssignment, PaymentTransaction, PaymentEvent, Refund, InventoryAdjustment, HomepageBanner,
)

@admin.register(AdminAuditEntry)
class AdminAuditEntryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "resource", "object_id"]
    list_filter = ["action", "resource"]
    search_fields = ["actor__email", "resource", "object_id"]
    readonly_fields = ["actor", "action", "resource", "object_id", "changes", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([
    Address, WishlistItem, CustomerQuestion, CustomerRequest, SupportTicket,
    ReturnRequest, BlogCategory, BlogPost, StoreInformation, ResellerProfile,
    ResellerAttribution, CommissionRule, ResellerCommission, ResellerPayoutRequest,
    ResellerPayoutAllocation,
    Coupon, CouponRedemption, SystemSettings, DeliveryArea, DeliveryPersonnel,
    DeliveryAssignment, PaymentTransaction, PaymentEvent, Refund,
    InventoryAdjustment, HomepageBanner,
])

@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ["event_type", "email", "ip_address", "created_at"]
    list_filter = ["event_type", "created_at"]
    search_fields = ["email", "ip_address"]
    readonly_fields = ["event_type", "email", "ip_address", "details", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
