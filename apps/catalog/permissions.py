from rest_framework.permissions import BasePermission

ROLE_MODULES = {
    "product_manager": {"products"},
    "inventory_manager": {"products", "inventory"},
    "order_manager": {"orders", "delivery"},
    "customer_support": {"customers", "support", "returns"},
    "marketing_manager": {"blogs", "referrals", "coupons", "promotions"},
    "finance_manager": {"payments", "refunds", "reports", "reseller-finance"},
}


def allowed_admin_module(user, module):
    return role_has_admin_module(user.role, module)


def role_has_admin_module(role, module):
    if role in {"admin", "super_admin"}:
        return True
    return module in ROLE_MODULES.get(role, set())


class IsStoreAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active and user.is_staff):
            return False
        path = request.path.lower()
        if "/dashboard/" in path:
            return user.role in {"admin", "super_admin", "product_manager", "order_manager", "inventory_manager", "customer_support", "marketing_manager", "finance_manager"}
        if "/admin/products" in path or "/admin/categories" in path:
            module = "inventory" if "inventory" in path else "products"
        elif "/admin/orders" in path:
            module = "orders"
        elif "/admin/support-agents" in path:
            module = "support"
        elif "/admin/customers" in path or "/admin/customer-questions" in path or "/admin/customer-requests" in path:
            module = "customers" if "customers" in path else "support"
        elif any(token in path for token in ("support-ticket", "returns")):
            module = "returns" if "returns" in path else "support"
        elif "homepage-banner" in path or "promotion" in path:
            module = "promotions"
        elif any(token in path for token in ("referral", "reward", "blog", "coupon")):
            module = "referrals" if "referral" in path or "reward" in path else "blogs" if "blog" in path else "coupons"
        elif any(token in path for token in ("payout", "commission")):
            module = "reseller-finance"
        elif "reseller" in path:
            module = "customers"
        elif "inventory" in path:
            module = "inventory"
        elif any(token in path for token in ("payment", "refund")):
            module = "payments" if "payment" in path else "refunds"
        elif any(token in path for token in ("delivery", "fulfilment")):
            module = "delivery"
        elif any(token in path for token in ("report", "export")):
            module = "reports"
        elif "system-settings" in path:
            return user.role in {"admin", "super_admin"}
        elif any(token in path for token in ("store-information", "services")):
            module = "blogs"
        elif "/admin/staff" in path:
            return user.role in {"admin", "super_admin"}
        else:
            return user.role in {"admin", "super_admin"}
        return allowed_admin_module(user, module)
