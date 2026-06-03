from django.db import models

class Producto(models.Model):
    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    categoria = models.CharField(max_length=100)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.CharField(max_length=10, default="MXN")
    ciudad = models.CharField(max_length=100)
    estado = models.CharField(max_length=100)
    stock = models.IntegerField()
    compatibilidad_general = models.JSONField() # Lista de autos compatible
    especificaciones = models.JSONField()       # Pares clave-valor técnicos
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    # Cómo se verá el producto en el Panel y la Consola
    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.categoria})"

class Lead(models.Model):
    nombre = models.CharField(max_length=255, null=True, blank=True)
    ciudad = models.CharField(max_length=100, null=True, blank=True)
    estado = models.CharField(max_length=100, null=True, blank=True)
    
    # Clave foránea: Enlaza directamente al modelo Producto
    producto_interes = models.ForeignKey(
        Producto, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="leads"
    )
    
    vehiculo = models.CharField(max_length=100, null=True, blank=True)
    anio_vehiculo = models.CharField(max_length=50, null=True, blank=True)
    direccion_envio = models.TextField(null=True, blank=True)
    lead_completo = models.BooleanField(default=False)
    aprobado_por_asesor = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    # Cómo se verá el Lead en el Panel y la Consola
    def __str__(self):
        nombre_display = self.nombre if self.nombre else 'Anónimo'
        ciudad_display = self.ciudad if self.ciudad else 'Sin Ciudad'
        return f"Lead: {nombre_display} - {ciudad_display}"