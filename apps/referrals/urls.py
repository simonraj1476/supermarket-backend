from django.urls import path
from .views import (
    AdminReferralNetworkDetailView,
    AdminReferralNetworkView,
    AdminReferralProgramView,
    AdminReferralStatsView,
    AdminReferralsView,
    AdminRewardsView,
    AdminWalletAdjustmentView,
    ReferralMeView,
    ReferralRewardsView,
    ReferralValidateView,
    ReferralWalletView,
)

urlpatterns = [
    path("referrals/validate/", ReferralValidateView.as_view()),
    path("referrals/me/", ReferralMeView.as_view()),
    path("referrals/me/rewards/", ReferralRewardsView.as_view()),
    path("referrals/me/wallet/", ReferralWalletView.as_view()),
    path("admin/referrals/", AdminReferralsView.as_view()),
    path("admin/referrals/stats/", AdminReferralStatsView.as_view()),
    path("admin/referrals/network/", AdminReferralNetworkView.as_view()),
    path("admin/referrals/network/<int:customer_id>/", AdminReferralNetworkDetailView.as_view()),
    path("admin/rewards/", AdminRewardsView.as_view()),
    path("admin/referral-settings/", AdminReferralProgramView.as_view()),
    path("admin/referrals/wallet-adjustments/", AdminWalletAdjustmentView.as_view()),
]
