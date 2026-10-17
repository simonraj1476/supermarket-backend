from django.core.management.base import BaseCommand
from django.utils.text import slugify
from apps.catalog.models import Category, Product

class Command(BaseCommand):
    help = "Create or update clearly identified supermarket demo categories and products."

    def handle(self, *args, **options):
        samples = {
            "Fruits and Vegetables": [
                ("Bananas", "FRUIT-BANANA", "55.00", 38),
                ("Tomatoes", "VEG-TOMATO", "40.00", 26),
                ("Onions", "VEG-ONION", "35.00", 42),
            ],
            "Rice, Grains and Pulses": [
                ("Demo Rice (1 kg)", "GRAIN-RICE", "72.00", 25),
                ("Toor Dal (1 kg)", "PULSE-TOOR", "145.00", 19),
                ("Green Gram (1 kg)", "PULSE-GREEN", "128.00", 17),
            ],
            "Dairy and Eggs": [("Milk (1 L)", "DAIRY-MILK", "62.00", 24), ("Eggs (6 pack)", "EGG-6PK", "48.00", 30), ("Bread", "BAKERY-BREAD", "40.00", 15)],
            "Snacks and Packaged Foods": [("Demo Biscuits", "SNACK-BISCUIT", "30.00", 50)],
            "Household Essentials": [("Bath Soap", "HOME-SOAP", "42.00", 34), ("Cooking Oil (1 L)", "PANTRY-OIL", "165.00", 22)],
            "Beverages": [("Orange Drink (1 L)", "DRINK-ORANGE", "85.00", 16)],
            "Personal Care": [("Hand Wash", "CARE-HANDWASH", "99.00", 12)],
        }
        for category_name, products in samples.items():
            category, _ = Category.objects.update_or_create(name=category_name, defaults={"slug": slugify(category_name), "is_active": True})
            for name, sku, price, stock in products:
                Product.objects.update_or_create(
                    sku=sku,
                    defaults={"category": category, "name": name, "slug": slugify(name), "description": f"Demo product: {name}. Sample listing and stock for development only.", "price": price, "stock": stock, "is_active": True, "is_featured": sku in {"FRUIT-BANANA", "DAIRY-MILK", "GRAIN-RICE"}},
                )
        self.stdout.write(self.style.SUCCESS("Demo categories and products are ready. They are sample data, not live inventory."))
