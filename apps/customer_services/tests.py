from decimal import Decimal
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase
from apps.catalog.models import Category, Product
from apps.orders.models import Order
from apps.orders.services import change_order_status
from .models import (
    Address, AdminAuditEntry, BlogPost, CommissionRule, CustomerQuestion,
    CustomerRequest, ResellerAttribution, ResellerCommission, ResellerProfile,
    ResellerPayoutAllocation, StoreInformation, SupportTicket, WishlistItem,
    Coupon, CouponRedemption, PaymentTransaction, Refund, SecurityEvent,
    DeliveryArea, DeliveryAssignment, SystemSettings, HomepageBanner,
)

User = get_user_model()


class CustomerServicesApiTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(email="customer@example.test", password="Test-password-123", phone="+911234567890")
        self.other = User.objects.create_user(email="other@example.test", password="Test-password-123", phone="+911234567891")
        self.admin = User.objects.create_superuser(email="admin@example.test", password="Test-password-123", phone="+911234567892")
        category = Category.objects.create(name="Fruit", slug="fruit")
        self.product = Product.objects.create(category=category, name="Apple", slug="apple", sku="APP-1", price=Decimal("100"), stock=4)

    def test_address_pin_validation_and_customer_isolation(self):
        self.client.force_authenticate(self.customer)
        payload = {
            "recipient_name": "Customer", "mobile_number": "+911234567890", "address_line1": "12 Main Road",
            "address_line2": "", "locality": "Central", "city": "Pune", "state": "Maharashtra",
            "pin_code": "411001", "delivery_instructions": "", "is_default": True,
        }
        created = self.client.post("/api/v1/account/addresses/", payload, format="json")
        self.assertEqual(created.status_code, 201)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get("/api/v1/account/addresses/").data["results"], [])
        self.client.force_authenticate(self.customer)
        payload["pin_code"] = "04110"
        self.assertEqual(self.client.post("/api/v1/account/addresses/", payload, format="json").status_code, 400)

    def test_address_update_and_delete(self):
        address = Address.objects.create(
            customer=self.customer, recipient_name="Customer", mobile_number="+911234567890",
            address_line1="Old Road", locality="Central", city="Pune", state="Maharashtra", pin_code="411001",
        )
        self.client.force_authenticate(self.customer)
        changed = self.client.patch(f"/api/v1/account/addresses/{address.id}/", {"address_line1": "New Road"}, format="json")
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data["address_line1"], "New Road")
        self.assertEqual(self.client.delete(f"/api/v1/account/addresses/{address.id}/").status_code, 204)

    def test_wishlist_creation_is_idempotent_and_private(self):
        self.client.force_authenticate(self.customer)
        path = "/api/v1/account/wishlist/"
        first = self.client.post(path, {"product_id": self.product.id}, format="json")
        second = self.client.post(path, {"product_id": self.product.id}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WishlistItem.objects.count(), 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(path).data["results"], [])

    def test_questions_requests_and_tickets_are_customer_scoped(self):
        question = CustomerQuestion.objects.create(customer=self.customer, subject="Delivery", question="When?")
        request = CustomerRequest.objects.create(customer=self.customer, subject="Feedback", message="Thanks")
        ticket = SupportTicket.objects.create(customer=self.customer, subject="Help", message="Need help")
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/v1/account/questions/{question.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/account/requests/{request.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/account/support-tickets/{ticket.id}/").status_code, 404)

    def test_admin_can_answer_question_but_customer_cannot_change_response(self):
        question = CustomerQuestion.objects.create(customer=self.customer, subject="Delivery", question="When?")
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.patch(f"/api/v1/account/questions/{question.id}/", {"answer": "Soon"}, format="json").status_code, 405)
        self.client.force_authenticate(self.admin)
        response = self.client.patch(f"/api/v1/admin/customer-questions/{question.id}/", {"answer": "Tomorrow", "status": "answered"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["answer"], "Tomorrow")

    def test_customer_can_submit_requests_and_support_tickets(self):
        self.client.force_authenticate(self.customer)
        request = self.client.post("/api/v1/account/requests/", {"kind": "feedback", "subject": "Thanks", "message": "Great service"}, format="json")
        ticket = self.client.post("/api/v1/account/support-tickets/", {"subject": "Help", "message": "Please help"}, format="json")
        self.assertEqual(request.status_code, 201)
        self.assertTrue(request.data["request_number"].startswith("REQ-"))
        self.assertEqual(ticket.status_code, 201)
        self.assertTrue(ticket.data["ticket_number"].startswith("SUP-"))

    def test_unpublished_blogs_are_hidden_and_admin_can_publish(self):
        post = BlogPost.objects.create(title="Draft", slug="draft", content="Plain text")
        self.assertEqual(self.client.get("/api/v1/blogs/draft/").status_code, 404)
        self.client.force_authenticate(self.admin)
        response = self.client.patch(f"/api/v1/admin/blogs/{post.id}/", {"is_published": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/blogs/draft/").status_code, 200)

    def test_reseller_commission_is_created_only_once_for_delivered_attributed_order(self):
        reseller = ResellerProfile.objects.create(customer=self.other, status=ResellerProfile.Status.APPROVED)
        ResellerAttribution.objects.create(customer=self.customer, reseller=reseller)
        CommissionRule.objects.create(pk=1, commission_percent=Decimal("10"), minimum_order_amount=Decimal("50"))
        order = Order.objects.create(
            customer=self.customer, customer_name="Customer", phone="+911234567890", address="address",
            subtotal=Decimal("100"), delivery_fee=Decimal("0"), total=Decimal("100"),
        )
        change_order_status(order=order, new_status=Order.Status.CONFIRMED)
        change_order_status(order=order, new_status=Order.Status.PROCESSING)
        change_order_status(order=order, new_status=Order.Status.PACKED)
        change_order_status(order=order, new_status=Order.Status.OUT_FOR_DELIVERY)
        change_order_status(order=order, new_status=Order.Status.DELIVERED)
        self.assertEqual(ResellerCommission.objects.filter(order=order).count(), 1)
        self.assertEqual(ResellerCommission.objects.get(order=order).amount, Decimal("10.00"))

    def test_reseller_application_requires_admin_approval(self):
        self.client.force_authenticate(self.customer)
        submitted = self.client.post("/api/v1/account/reseller/", {"application_note": "I would like to apply"}, format="json")
        self.assertEqual(submitted.status_code, 201)
        self.assertEqual(submitted.data["status"], "pending")
        self.client.force_authenticate(self.admin)
        approved = self.client.patch(f"/api/v1/admin/resellers/{submitted.data['id']}/", {"status": "approved", "admin_note": "Approved"}, format="json")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data["status"], "approved")
        self.assertEqual(AdminAuditEntry.objects.filter(actor=self.admin, resource="customer_services.resellerprofile").count(), 1)

    def test_payout_requests_reserve_commissions_and_record_allocations(self):
        reseller = ResellerProfile.objects.create(customer=self.customer, status=ResellerProfile.Status.APPROVED)
        CommissionRule.objects.create(pk=1, commission_percent=Decimal("10"), minimum_payout=Decimal("5"))
        order = Order.objects.create(customer=self.other, customer_name="Other", phone="1234567890", address="address", subtotal=Decimal("100"), delivery_fee=Decimal("0"), total=Decimal("100"))
        commission = ResellerCommission.objects.create(reseller=reseller, order=order, order_amount=Decimal("100"), amount=Decimal("10"), status=ResellerCommission.Status.APPROVED)
        self.client.force_authenticate(self.customer)
        payout = self.client.post("/api/v1/account/reseller/payouts/", {"amount": "8.00"}, format="json")
        self.assertEqual(payout.status_code, 201)
        self.client.force_authenticate(self.admin)
        payout_url = f"/api/v1/admin/reseller-payouts/{payout.data['id']}/"
        self.assertEqual(self.client.patch(payout_url, {"status": "approved"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(payout_url, {"status": "paid"}, format="json").status_code, 200)
        self.assertEqual(ResellerPayoutAllocation.objects.filter(payout_request_id=payout.data["id"], commission=commission).first().amount, Decimal("8.00"))
        self.assertEqual(ResellerCommission.objects.get(pk=commission.pk).status, ResellerCommission.Status.APPROVED)

    def test_public_store_information_filters_unapproved_data_keys(self):
        StoreInformation.objects.create(details={"about": "About text", "internal_secret": "must not leak"}, policies={"terms": "Published terms", "bank_token": "must not leak"})
        response = self.client.get("/api/v1/store-information/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("internal_secret", response.data["details"])
        self.assertNotIn("bank_token", response.data["policies"])
        self.assertEqual(response.data["details"]["about"], "About text")

    def test_non_admin_cannot_access_admin_service_endpoints(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.get("/api/v1/admin/customer-requests/").status_code, 403)

    def test_staff_roles_are_restricted_to_their_api_modules(self):
        product_manager = User.objects.create_user(email="product.manager@example.test", password="TempPassword!815", phone="+911234567893", role=User.Role.PRODUCT_MANAGER, is_staff=True)
        self.client.force_authenticate(product_manager)
        self.assertEqual(self.client.get("/api/v1/admin/products/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/customers/").status_code, 403)
        order_manager = User.objects.create_user(email="order.manager@example.test", password="TempPassword!816", phone="+911234567894", role=User.Role.ORDER_MANAGER, is_staff=True)
        self.client.force_authenticate(order_manager)
        self.assertEqual(self.client.get("/api/v1/admin/orders/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/payments/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/admin/dashboard/?period=today").status_code, 200)
        dashboard = self.client.get("/api/v1/admin/dashboard/?period=custom&start=2025-10-02&end=2025-10-01")
        self.assertEqual(dashboard.status_code, 400)

    def test_admin_dashboard_all_time_metrics_include_older_orders(self):
        historical_order = Order.objects.create(
            customer=self.customer,
            customer_name=self.customer.get_full_name(),
            phone=self.customer.phone,
            address="12 Market Road",
            status=Order.Status.DELIVERED,
            subtotal=Decimal("240.00"),
            total=Decimal("240.00"),
        )
        Order.objects.filter(pk=historical_order.pk).update(created_at=timezone.now() - timedelta(days=60))
        self.client.force_authenticate(self.admin)

        all_time = self.client.get("/api/v1/admin/dashboard/?period=all_time")
        today = self.client.get("/api/v1/admin/dashboard/?period=today")

        self.assertEqual(all_time.status_code, 200)
        self.assertEqual(all_time.data["period"], "all_time")
        self.assertEqual(all_time.data["range"], {"start": None, "end": None})
        self.assertEqual(all_time.data["orders"], 1)
        self.assertEqual(Decimal(all_time.data["gross_sales"]), Decimal("240.00"))
        self.assertEqual(today.data["orders"], 0)
        self.assertEqual(Decimal(today.data["gross_sales"]), Decimal("0.00"))

    def test_staff_creation_hashes_password_and_prevents_role_escalation(self):
        ordinary_admin = User.objects.create_user(email="staff.admin@example.test", password="TempPassword!817", phone="+911234567896", role=User.Role.ADMIN, is_staff=True)
        self.client.force_authenticate(ordinary_admin)
        payload = {
            "email": "support.agent@example.test",
            "first_name": "Support",
            "last_name": "Agent",
            "phone": "+911234567895",
            "role": User.Role.CUSTOMER_SUPPORT,
            "password": "TemporaryPass!5932",
        }
        response = self.client.post("/api/v1/admin/staff/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        staff = User.objects.get(email=payload["email"])
        self.assertTrue(staff.is_staff)
        self.assertTrue(staff.check_password(payload["password"]))
        self.assertNotIn("password", response.data)
        self.assertEqual(self.client.patch(f"/api/v1/admin/staff/{staff.pk}/", {"role": User.Role.SUPER_ADMIN}, format="json").status_code, 400)

    def test_checkout_coupon_and_cod_payment_records_are_database_backed(self):
        coupon = Coupon.objects.create(
            code="SAVE20", discount_type=Coupon.DiscountType.PERCENT, value=Decimal("20"),
            starts_at=timezone.now() - timedelta(days=1), expires_at=timezone.now() + timedelta(days=1),
            minimum_purchase=Decimal("50"),
        )
        self.client.force_authenticate(self.customer)
        order_response = self.client.post("/api/v1/orders/", {
            "customer_name": "Customer", "phone": self.customer.phone, "address": "12 Market Road",
            "coupon_code": coupon.code, "items": [{"product_id": self.product.pk, "quantity": 1}],
        }, format="json")
        self.assertEqual(order_response.status_code, 201)
        self.assertEqual(Decimal(order_response.data["discount_amount"]), Decimal("20.00"))
        self.assertEqual(Decimal(order_response.data["total"]), Decimal("80.00"))
        payment = PaymentTransaction.objects.get(order_id=order_response.data["id"])
        self.assertEqual(payment.status, PaymentTransaction.Status.PENDING)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(f"/api/v1/admin/payments/{payment.pk}/", {"cod_collected": False}, format="json").status_code, 400)
        payment.order.status = Order.Status.CANCELLED
        payment.order.save(update_fields=["status"])
        self.assertEqual(self.client.patch(f"/api/v1/admin/payments/{payment.pk}/", {"cod_collected": True}, format="json").status_code, 400)
        payment.order.status = Order.Status.PENDING
        payment.order.save(update_fields=["status"])
        response = self.client.patch(f"/api/v1/admin/payments/{payment.pk}/", {"cod_collected": True}, format="json")
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertTrue(payment.cod_collected)
        self.assertEqual(payment.events.count(), 1)

    def test_cod_refunds_require_approval_and_manual_transfer_reference(self):
        unpaid_order = Order.objects.create(
            customer=self.customer, customer_name="Customer", phone=self.customer.phone,
            address="Market Road", subtotal=Decimal("100"), delivery_fee=0, total=Decimal("100"),
        )
        order = Order.objects.create(
            customer=self.customer, customer_name="Customer", phone=self.customer.phone,
            address="Market Road", subtotal=Decimal("100"), delivery_fee=0, total=Decimal("100"),
            payment_status=Order.PaymentStatus.PAID,
        )
        self.client.force_authenticate(self.admin)
        unpaid_refund = self.client.post("/api/v1/admin/refunds/", {"order": str(unpaid_order.pk), "amount": "100", "reason": "Unpaid order"}, format="json")
        self.assertEqual(unpaid_refund.status_code, 400)
        created = self.client.post("/api/v1/admin/refunds/", {"order": str(order.pk), "amount": "100", "reason": "Returned goods"}, format="json")
        self.assertEqual(created.status_code, 201)
        refund_url = f"/api/v1/admin/refunds/{created.data['id']}/"
        self.assertEqual(self.client.patch(refund_url, {"status": "recorded"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(refund_url, {"status": "approved"}, format="json").status_code, 200)
        recorded = self.client.patch(refund_url, {"status": "recorded", "transaction_reference": "BANK-REF-73"}, format="json")
        self.assertEqual(recorded.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.REFUNDED)

    def test_delivery_areas_and_scheduled_banners_are_public_only_when_active(self):
        self.client.force_authenticate(self.admin)
        area = self.client.post("/api/v1/admin/delivery-areas/", {"name": "Central", "pin_code": "411001", "is_active": True}, format="json")
        self.assertEqual(area.status_code, 201)
        self.assertEqual(DeliveryArea.objects.count(), 1)
        banner = HomepageBanner.objects.create(
            title="Fresh offer", starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1), is_active=True,
        )
        self.assertEqual(self.client.get("/api/v1/homepage-banners/").data[0]["id"], banner.pk)
        banner.is_active = False
        banner.save()
        self.assertEqual(self.client.get("/api/v1/homepage-banners/").data, [])

    def test_login_failure_creates_security_event(self):
        response = self.client.post("/api/v1/auth/login/", {"email": self.customer.email, "password": "incorrect-password"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(SecurityEvent.objects.filter(event_type="failed_login", email=self.customer.email).exists())

    def test_support_assignment_and_internal_notes_are_not_customer_visible(self):
        ticket = SupportTicket.objects.create(customer=self.customer, subject="Delivery", message="Where is my order?")
        agent = User.objects.create_user(email="support.team@example.test", password="TempPassword!818", phone="+911234567897", role=User.Role.CUSTOMER_SUPPORT, is_staff=True)
        self.client.force_authenticate(self.admin)
        response = self.client.patch(f"/api/v1/admin/support-tickets/{ticket.pk}/", {
            "assigned_to": agent.pk, "priority": "urgent", "internal_notes": "Call customer before dispatch.", "response": "We are checking.",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["first_response_at"])
        self.client.force_authenticate(self.customer)
        customer_ticket = self.client.get("/api/v1/account/support-tickets/").data["results"][0]
        self.assertNotIn("internal_notes", customer_ticket)
        self.assertNotIn("assigned_to", customer_ticket)

    def test_coupon_admin_settings_inventory_adjustment_and_csv_report_endpoints(self):
        self.client.force_authenticate(self.admin)
        now = timezone.now()
        coupon = self.client.post("/api/v1/admin/coupons/", {
            "code": "summer10", "discount_type": "percent", "value": "10",
            "minimum_purchase": "0", "starts_at": now.isoformat(),
            "expires_at": (now + timedelta(days=3)).isoformat(), "per_customer_limit": 1,
        }, format="json")
        self.assertEqual(coupon.status_code, 201)
        self.assertEqual(coupon.data["code"], "SUMMER10")
        settings = self.client.patch("/api/v1/admin/system-settings/", {
            "delivery_fee": "25.00", "minimum_order_value": "50.00", "free_delivery_threshold": "500.00",
        }, format="json")
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(Decimal(settings.data["delivery_fee"]), Decimal("25.00"))
        adjusted = self.client.post("/api/v1/admin/inventory/adjustments/", {
            "product_id": self.product.pk, "quantity_delta": 3, "reason": "Received supplier shipment",
        }, format="json")
        self.assertEqual(adjusted.status_code, 201)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 7)
        csv_file = SimpleUploadedFile("stock.csv", b"sku,stock,reason\nAPP-1,2,cycle count\n", content_type="text/csv")
        imported = self.client.post("/api/v1/admin/inventory/import/", {"file": csv_file}, format="multipart")
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(len(imported.data["updated"]), 1)
        report = self.client.get("/api/v1/admin/reports/inventory/")
        self.assertEqual(report.status_code, 200)
        self.assertIn("APP-1", report.content.decode("utf-8"))
