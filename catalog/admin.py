from django.contrib import admin
from .models import Producto, Lead

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    # Añadimos los métodos personalizados a las columnas de visualización
    list_display = (
        'marca', 
        'modelo', 
        'categoria', 
        'ciudad', 
        'estado', 
        'stock', 
        'precio', 
        'mostrar_compatibilidad', 
        'mostrar_especificaciones', 
        'is_active'
    )
    
    search_fields = ('marca', 'modelo', 'ciudad', 'estado', 'categoria')
    list_filter = ('is_active', 'categoria', 'estado')
    readonly_fields = ('created_at', 'updated_at')

    # Método personalizado para aplanar el Array en el Admin table
    def mostrar_compatibilidad(self, obj):
        if obj.compatibilidad_general:
            return ", ".join(obj.compatibilidad_general)
        return "Sin especificar"
    mostrar_compatibilidad.short_description = "Compatibilidad (Lista)"

    # Método personalizado para aplanar el Diccionario en el Admin table
    def mostrar_especificaciones(self, obj):
        if obj.especificaciones:
            # Crea una lista de strings "Llave: Valor" y las une con comas
            lineas = [f"{llave}: {valor}" for llave, valor in obj.especificaciones.items()]
            return ", ".join(lineas)
        return "Sin especificaciones"
    mostrar_especificaciones.short_description = "Especificaciones (Dict)"

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'ciudad', 'producto_interes', 'aprobado_por_asesor', 'is_active', 'created_at')
    search_fields = ('nombre', 'ciudad', 'vehiculo')
    list_filter = ('aprobado_por_asesor', 'is_active', 'lead_completo')
    readonly_fields = ('created_at', 'updated_at')