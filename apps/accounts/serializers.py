from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.models import Permission
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from apps.referrals.models import Referral, ReferralProgram
from apps.catalog.permissions import role_has_admin_module
from apps.customer_services.models import ResellerAttribution, ResellerProfile
from .models import User

class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "phone", "role", "referral_code"]
        read_only_fields = ["id", "role", "referral_code"]

    def get_full_name(self, obj) -> str:
        return obj.get_full_name()

class RegistrationSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    referral_code = serializers.CharField(required=False, allow_blank=True, max_length=8)
    reseller_code = serializers.CharField(required=False, allow_blank=True, max_length=14)

    def validate_email(self, value):
        normalized = User.objects.normalize_email(value).lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return normalized

    def validate_phone(self, value):
        normalized = "".join(ch for ch in value if ch.isdigit() or ch == "+")
        if len(normalized) < 7 or len(normalized) > 16 or normalized.count("+") > 1 or ("+" in normalized and not normalized.startswith("+")):
            raise serializers.ValidationError("Enter a valid phone number.")
        if User.objects.filter(phone=normalized).exists():
            raise serializers.ValidationError("An account with this phone number already exists.")
        return normalized

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        password_validation.validate_password(attrs["password"])
        code = attrs.get("referral_code", "").strip().upper()
        if code:
            if not ReferralProgram.current().active:
                raise serializers.ValidationError({"referral_code": "The referral program is not currently active."})
            referrer = User.objects.filter(referral_code=code, is_active=True).first()
            if not referrer:
                raise serializers.ValidationError({"referral_code": "This referral code is not valid."})
            if referrer.email.lower() == attrs["email"].lower():
                raise serializers.ValidationError({"referral_code": "You cannot refer yourself."})
            attrs["referrer"] = referrer
        reseller_code = attrs.get("reseller_code", "").strip().upper()
        if reseller_code:
            reseller = ResellerProfile.objects.filter(
                reseller_code=reseller_code, status=ResellerProfile.Status.APPROVED
            ).select_related("customer").first()
            if not reseller:
                raise serializers.ValidationError({"reseller_code": "This reseller link is not active."})
            if reseller.customer.email.lower() == attrs["email"].lower():
                raise serializers.ValidationError({"reseller_code": "You cannot use your own reseller link."})
            attrs["reseller"] = reseller
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        full_name = validated_data["full_name"].strip().split(maxsplit=1)
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=full_name[0],
            last_name=full_name[1] if len(full_name) > 1 else "",
            phone=validated_data["phone"],
        )
        referrer = validated_data.get("referrer")
        if referrer:
            Referral.objects.create(referrer=referrer, referred=user)
        reseller = validated_data.get("reseller")
        if reseller:
            ResellerAttribution.objects.create(customer=user, reseller=reseller)
        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(request=self.context.get("request"), username=attrs["email"].lower(), password=attrs["password"])
        if not user:
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("This account is inactive.")
        attrs["user"] = user
        return attrs

    def create(self, validated_data):
        user = validated_data["user"]
        refresh = RefreshToken.for_user(user)
        return {"user": UserSerializer(user).data, "access": str(refresh.access_token), "refresh": str(refresh)}

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

class AdminCustomerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    full_name = serializers.CharField(allow_blank=True)
    phone = serializers.CharField()
    is_active = serializers.BooleanField()
    joined_at = serializers.DateTimeField()
    orders_count = serializers.IntegerField()
    referrals_count = serializers.IntegerField()


class AdminStaffSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=12)
    can_manage_referral_settings = serializers.SerializerMethodField()
    grant_referral_settings = serializers.BooleanField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name", "phone",
            "role", "is_active", "password", "can_manage_referral_settings",
            "grant_referral_settings",
        ]
        read_only_fields = ["id", "full_name"]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_can_manage_referral_settings(self, obj):
        return bool(
            obj.role in {User.Role.ADMIN, User.Role.SUPER_ADMIN}
            or obj.has_perm("referrals.change_referralprogram")
        )

    def validate_role(self, value):
        if value == User.Role.CUSTOMER:
            raise serializers.ValidationError("Staff accounts must have an administrator role.")
        return value

    def validate(self, attrs):
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "A temporary password of at least 12 characters is required."})
        if attrs.get("password"):
            password_validation.validate_password(attrs["password"], user=self.instance)
        actor = self.context["request"].user
        if attrs.get("role", getattr(self.instance, "role", None)) == User.Role.SUPER_ADMIN and actor.role != User.Role.SUPER_ADMIN and not actor.is_superuser:
            raise serializers.ValidationError({"role": "Only a super admin can create or assign the super admin role."})
        if self.instance and self.instance.pk == self.context["request"].user.pk:
            if attrs.get("role", self.instance.role) != self.instance.role or attrs.get("is_active", self.instance.is_active) != self.instance.is_active:
                raise serializers.ValidationError("You cannot change your own role or deactivate your own account.")
        if self.instance and self.instance.is_superuser and not self.context["request"].user.is_superuser:
            raise serializers.ValidationError("Only a superuser can modify a superuser account.")
        role = attrs.get("role", getattr(self.instance, "role", None))
        grant_permission = attrs.get("grant_referral_settings", False)
        if grant_permission and not role_has_admin_module(role, "referrals"):
            raise serializers.ValidationError({
                "grant_referral_settings": "Only staff with referral access can manage referral settings."
            })
        if grant_permission and not Permission.objects.filter(
            content_type__app_label="referrals",
            codename="change_referralprogram",
        ).exists():
            raise serializers.ValidationError({
                "grant_referral_settings": "Referral permissions are unavailable; apply database migrations first."
            })
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        is_staff = validated_data.pop("is_staff", True)
        grant_referral_settings = validated_data.pop("grant_referral_settings", False)
        user = User(**validated_data, is_staff=is_staff)
        user.set_password(password)
        user.save()
        if grant_referral_settings:
            self._set_referral_settings_permission(user, True)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        grant_referral_settings = validated_data.pop("grant_referral_settings", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.is_staff = True
        if password:
            instance.set_password(password)
        instance.save()
        if grant_referral_settings is not None:
            self._set_referral_settings_permission(instance, grant_referral_settings)
        elif not role_has_admin_module(instance.role, "referrals"):
            self._set_referral_settings_permission(instance, False)
        return instance

    @staticmethod
    def _set_referral_settings_permission(user, granted):
        permission = Permission.objects.get(
            content_type__app_label="referrals",
            codename="change_referralprogram",
        )
        if granted:
            user.user_permissions.add(permission)
        else:
            user.user_permissions.remove(permission)
        for cache in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(cache, None)
