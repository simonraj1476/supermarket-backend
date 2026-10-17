from rest_framework import serializers
from .models import Order, OrderItem

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product_name", "sku", "unit_price", "quantity", "line_total"]

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["id", "order_number", "status", "payment_method", "payment_status", "customer_name", "phone", "address", "instructions", "subtotal", "discount_amount", "delivery_fee", "total", "delivery_pin_code", "items", "created_at", "updated_at"]

class CreateOrderSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField(), allow_empty=False)
    customer_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    address = serializers.CharField()
    instructions = serializers.CharField(required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(choices=["cod"], default="cod")
    coupon_code = serializers.CharField(required=False, allow_blank=True, max_length=40)
    delivery_pin_code = serializers.RegexField(r"^[1-9][0-9]{5}$", required=False, allow_blank=True)

    def validate(self, attrs):
        for field in ["customer_name", "phone", "address"]:
            if not attrs[field].strip():
                raise serializers.ValidationError({field: "This field cannot be blank."})
        return attrs
