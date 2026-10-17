import secrets
import string

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

def referral_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))

class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        ADMIN = "admin", "Administrator"
        SUPER_ADMIN = "super_admin", "Super Admin"
        PRODUCT_MANAGER = "product_manager", "Product Manager"
        ORDER_MANAGER = "order_manager", "Order Manager"
        INVENTORY_MANAGER = "inventory_manager", "Inventory Manager"
        CUSTOMER_SUPPORT = "customer_support", "Customer Support"
        MARKETING_MANAGER = "marketing_manager", "Marketing Manager"
        FINANCE_MANAGER = "finance_manager", "Finance Manager"

    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, unique=True)
    role = models.CharField(max_length=24, choices=Role.choices, default=Role.CUSTOMER)
    referral_code = models.CharField(max_length=8, unique=True, default=referral_code)
    is_active = models.BooleanField(default=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone", "first_name"]
    objects = UserManager()

    class Meta:
        constraints = [models.UniqueConstraint(Lower("email"), name="unique_user_email_case_insensitive")]

    def __str__(self):
        return self.email
