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
    updated_at = models.DateTimeField(auto_now=True) # Registro automático de cambios [cite: 641]

class Lead(models.Model):
    nombre = models.CharField(max_length=255, null=True, blank=True)
    ciudad = models.CharField(max_length=100, null=True, blank=True)
    estado = models.CharField(max_length=100, null=True, blank=True)
    producto_interes = models.CharField(max_length=255, null=True, blank=True)
    vehiculo = models.CharField(max_length=100, null=True, blank=True)
    anio_vehiculo = models.CharField(max_length=50, null=True, blank=True) # Se mantiene como CharField [cite: 630]
    direccion_envio = models.TextField(null=True, blank=True)
    lead_completo = models.BooleanField(default=False)
    aprobado_por_asesor = models.BooleanField(default=False) # Para el visto bueno humano
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True) # Para medir tiempos de respuesta