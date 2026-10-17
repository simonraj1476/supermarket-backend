from rest_framework import serializers
from .models import Category, Product

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "is_active"]

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "name", "slug", "sku", "description", "price", "mrp", "stock", "in_stock", "image_url", "is_active", "is_featured", "category", "category_name"]

    def validate(self, attrs):
        price = attrs.get("price", getattr(self.instance, "price", None))
        mrp = attrs.get("mrp", getattr(self.instance, "mrp", None))
        if mrp is not None and price is not None and mrp < price:
            raise serializers.ValidationError({"mrp": "MRP must be greater than or equal to the selling price."})
        return attrs

    def get_in_stock(self, obj) -> bool:
        return obj.stock > 0 and obj.is_active


class AdminProductSerializer(ProductSerializer):
    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + ["barcode", "low_stock_threshold"]
