from rest_framework import serializers
from .models import Producto, Lead


class ProductoSerializer(serializers.ModelSerializer):
    # Expone stock_disponible (property) como campo de solo lectura
    stock_disponible = serializers.ReadOnlyField()

    class Meta:
        model = Producto
        fields = '__all__'


class LeadSerializer(serializers.ModelSerializer):
    # Muestra nombre legible del producto además del ID
    producto_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = '__all__'

    def get_producto_nombre(self, obj):
        if obj.producto_interes:
            return (
                f"{obj.producto_interes.marca} "
                f"{obj.producto_interes.modelo}"
            )
        return None