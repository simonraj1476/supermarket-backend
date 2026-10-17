from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    AddressViewSet, AdminBlogCategoryViewSet, AdminBlogPostViewSet,
    AdminCommissionRuleView, AdminCommissionViewSet, AdminPayoutViewSet,
    AdminQuestionViewSet, AdminRequestViewSet, AdminResellerViewSet,
    AdminReturnRequestViewSet, AdminStoreInformationView,
    AdminSupportTicketViewSet, AdminRewardOverviewView, BlogCategoryViewSet,
    BlogPostViewSet, CustomerQuestionViewSet, CustomerRequestViewSet,
    CustomerRewardsView, ResellerMeView, ResellerPayoutViewSet,
    ReturnRequestViewSet, StoreInformationView, SupportTicketViewSet,
    WishlistViewSet, AdminCouponViewSet, AdminSystemSettingsView,
    PublicOperationalSettingsView, AdminDeliveryAreaViewSet,
    AdminDeliveryPersonnelViewSet, AdminDeliveryAssignmentViewSet,
    AdminPaymentViewSet, AdminRefundViewSet, AdminInventoryView,
    AdminInventoryImportView, AdminReportView, PublicHomepageBannerView,
    AdminHomepageBannerViewSet,
    AdminAuditLogView,
    AdminSupportAgentsView,
)

router = DefaultRouter()
router.register("account/addresses", AddressViewSet, basename="account-address")
router.register("account/wishlist", WishlistViewSet, basename="account-wishlist")
router.register("account/questions", CustomerQuestionViewSet, basename="account-question")
router.register("account/requests", CustomerRequestViewSet, basename="account-request")
router.register("account/support-tickets", SupportTicketViewSet, basename="account-support")
router.register("account/returns", ReturnRequestViewSet, basename="account-return")
router.register("account/reseller/payouts", ResellerPayoutViewSet, basename="account-reseller-payout")
router.register("blogs", BlogPostViewSet, basename="blog-post")
router.register("blog-categories", BlogCategoryViewSet, basename="blog-category")
router.register("admin/customer-questions", AdminQuestionViewSet, basename="admin-question")
router.register("admin/customer-requests", AdminRequestViewSet, basename="admin-request")
router.register("admin/support-tickets", AdminSupportTicketViewSet, basename="admin-support")
router.register("admin/returns", AdminReturnRequestViewSet, basename="admin-return")
router.register("admin/blogs", AdminBlogPostViewSet, basename="admin-blog")
router.register("admin/blog-categories", AdminBlogCategoryViewSet, basename="admin-blog-category")
router.register("admin/resellers", AdminResellerViewSet, basename="admin-reseller")
router.register("admin/reseller-commissions", AdminCommissionViewSet, basename="admin-commission")
router.register("admin/reseller-payouts", AdminPayoutViewSet, basename="admin-payout")
router.register("admin/coupons", AdminCouponViewSet, basename="admin-coupon")
router.register("admin/delivery-areas", AdminDeliveryAreaViewSet, basename="admin-delivery-area")
router.register("admin/delivery-personnel", AdminDeliveryPersonnelViewSet, basename="admin-delivery-personnel")
router.register("admin/delivery-assignments", AdminDeliveryAssignmentViewSet, basename="admin-delivery-assignment")
router.register("admin/payments", AdminPaymentViewSet, basename="admin-payment")
router.register("admin/refunds", AdminRefundViewSet, basename="admin-refund")
router.register("admin/homepage-banners", AdminHomepageBannerViewSet, basename="admin-homepage-banner")

urlpatterns = [
    path("", include(router.urls)),
    path("account/rewards/", CustomerRewardsView.as_view()),
    path("account/reseller/", ResellerMeView.as_view()),
    path("store-information/", StoreInformationView.as_view()),
    path("admin/store-information/", AdminStoreInformationView.as_view()),
    path("admin/reseller-commission-rule/", AdminCommissionRuleView.as_view()),
    path("admin/reward-overview/", AdminRewardOverviewView.as_view()),
    path("admin/system-settings/", AdminSystemSettingsView.as_view()),
    path("admin/audit-log/", AdminAuditLogView.as_view()),
    path("admin/support-agents/", AdminSupportAgentsView.as_view()),
    path("system-settings/public/", PublicOperationalSettingsView.as_view()),
    path("homepage-banners/", PublicHomepageBannerView.as_view()),
    path("admin/inventory/adjustments/", AdminInventoryView.as_view()),
    path("admin/inventory/import/", AdminInventoryImportView.as_view()),
    path("admin/reports/<str:report>/", AdminReportView.as_view()),
]
