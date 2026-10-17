from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from rest_framework.test import APIClient
from apps.catalog.models import Category, Product
from apps.referrals.models import Referral, ReferralProgram, ReferralReward, WalletLedger
from apps.referrals.services import award_referral_for_order
from .models import InventoryMovement, Order
from .services import change_order_status, place_order

User = get_user_model()

class StoreWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name="Test pantry", slug="test-pantry")
        self.product = Product.objects.create(category=self.category, name="Test rice", slug="test-rice", sku="TEST-RICE", price=Decimal("600.00"), stock=5)

    def create_customer(self, email, phone):
        return User.objects.create_user(email=email, password="S0mething-Strong!987", phone=phone, first_name=email.split("@")[0])

    def test_registration_and_duplicate_email(self):
        response = self.client.post("/api/v1/auth/register/", {"full_name": "A Customer", "email": "A@Example.com", "phone": "9876543210", "password": "S0mething-Strong!987", "confirm_password": "S0mething-Strong!987"})
        self.assertEqual(response.status_code, 201)
        customer = User.objects.get(email="a@example.com")
        self.assertTrue(customer.check_password("S0mething-Strong!987"))
        duplicate = self.client.post("/api/v1/auth/register/", {"full_name": "Another", "email": "a@example.com", "phone": "9876543211", "password": "S0mething-Strong!987", "confirm_password": "S0mething-Strong!987"})
        self.assertEqual(duplicate.status_code, 400)

    def test_products_are_listed_and_searchable(self):
        response = self.client.get("/api/v1/products/?search=rice")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["sku"], "TEST-RICE")
        filtered = self.client.get(f"/api/v1/products/?category={self.category.pk}")
        self.assertEqual(filtered.data["count"], 1)

    def test_server_calculates_totals_and_prevents_overselling(self):
        customer = self.create_customer("buyer@example.com", "9876543210")
        self.client.force_authenticate(customer)
        response = self.client.post("/api/v1/orders/", {"customer_name": "Buyer", "phone": customer.phone, "address": "1 Market Road", "payment_method": "cod", "items": [{"product_id": self.product.pk, "quantity": 2, "price": "1.00"}]}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data["total"]), Decimal("1200.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        too_many = self.client.post("/api/v1/orders/", {"customer_name": "Buyer", "phone": customer.phone, "address": "1 Market Road", "items": [{"product_id": self.product.pk, "quantity": 4}]}, format="json")
        self.assertEqual(too_many.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_orders_are_private_and_unauthenticated_order_api_is_protected(self):
        first = self.create_customer("first@example.com", "9876543210")
        second = self.create_customer("second@example.com", "9876543211")
        order = place_order(customer=first, payload={"customer_name": "First", "phone": first.phone, "address": "Address", "items": [{"product_id": self.product.pk, "quantity": 1}]})
        response = self.client.get(f"/api/v1/orders/{order.pk}/")
        self.assertEqual(response.status_code, 401)
        self.client.force_authenticate(second)
        self.assertEqual(self.client.get(f"/api/v1/orders/{order.pk}/").status_code, 404)

    def test_referral_attribution_rewards_only_once_after_qualifying_delivery(self):
        referrer = self.create_customer("referrer@example.com", "9876543210")
        self.client.force_authenticate(None)
        response = self.client.post("/api/v1/auth/register/", {"full_name": "New Customer", "email": "new@example.com", "phone": "9876543211", "password": "S0mething-Strong!987", "confirm_password": "S0mething-Strong!987", "referral_code": referrer.referral_code})
        self.assertEqual(response.status_code, 201)
        referred = User.objects.get(email="new@example.com")
        referral = Referral.objects.get(referred=referred)
        self.assertEqual(referral.referrer, referrer)
        program = ReferralProgram.current()
        program.minimum_order_amount = Decimal("500.00")
        program.save()
        order = place_order(customer=referred, payload={"customer_name": "New Customer", "phone": referred.phone, "address": "Address", "items": [{"product_id": self.product.pk, "quantity": 1}]})
        for status in [Order.Status.CONFIRMED, Order.Status.PROCESSING, Order.Status.PACKED, Order.Status.OUT_FOR_DELIVERY, Order.Status.DELIVERED]:
            change_order_status(order=order, new_status=status)
        self.assertEqual(ReferralReward.objects.filter(referral=referral).count(), 2)
        self.assertEqual(WalletLedger.objects.filter(customer=referrer).aggregate(total=Sum("amount"))["total"], Decimal("100.00"))
        self.assertFalse(award_referral_for_order(order))

    def test_self_referral_validation_and_cancel_restore_stock_once(self):
        customer = self.create_customer("self@example.com", "9876543210")
        response = self.client.post("/api/v1/auth/register/", {"full_name": "Self Referral", "email": "new-self@example.com", "phone": "9876543212", "password": "S0mething-Strong!987", "confirm_password": "S0mething-Strong!987", "referral_code": customer.referral_code})
        self.assertEqual(response.status_code, 201)
        referred = User.objects.get(email="new-self@example.com")
        self.assertEqual(Referral.objects.get(referred=referred).referrer, customer)
        self.client.force_authenticate(referred)
        self_referral = self.client.post("/api/v1/referrals/validate/", {"referral_code": referred.referral_code}, format="json")
        self.assertEqual(self_referral.status_code, 400)
        self.assertIn("You cannot refer yourself.", str(self_referral.data))
        order = place_order(customer=customer, payload={"customer_name": "Self", "phone": customer.phone, "address": "Address", "items": [{"product_id": self.product.pk, "quantity": 2}]})
        change_order_status(order=order, new_status=Order.Status.CANCELLED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(InventoryMovement.objects.filter(order=order, kind=InventoryMovement.Kind.RESTOCK).count(), 1)

    def test_admin_endpoints_require_store_admin_and_referral_settings_are_editable(self):
        customer = self.create_customer("customer@example.com", "9876543210")
        self.client.force_authenticate(customer)
        self.assertEqual(self.client.get("/api/v1/admin/dashboard/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/admin/products/").status_code, 403)
        admin = User.objects.create_user(email="admin@example.com", password="S0mething-Strong!987", phone="9876543211", first_name="Store", is_staff=True, role=User.Role.ADMIN)
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get("/api/v1/admin/dashboard/").status_code, 200)
        response = self.client.patch("/api/v1/admin/referral-settings/", {"minimum_order_amount": "750.00"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["minimum_order_amount"]), Decimal("750.00"))
