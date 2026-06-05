from django.db import models
from django.utils import timezone
from datetime import timedelta


class Producto(models.Model):
    marca = models.CharField(max_length=100)
    modelo = models.CharField(max_length=100)
    categoria = models.CharField(max_length=100)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.CharField(max_length=10, default="MXN")
    ciudad = models.CharField(max_length=100)
    estado = models.CharField(max_length=100)
    stock = models.IntegerField()
    compatibilidad_general = models.JSONField()
    especificaciones = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    @property
    def stock_disponible(self):
        """
        Stock real = stock total - unidades reservadas activas y no expiradas.
        Las reservas expiradas se ignoran automáticamente sin borrarlas.
        """
        reservas_activas = self.reservas.filter(
            activa=True,
            expira_en__gt=timezone.now()
        ).aggregate(
            total=models.Sum('cantidad')
        )['total'] or 0
        return self.stock - reservas_activas

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.categoria})"

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ['marca', 'modelo']


class Lead(models.Model):
    # Datos del cliente
    nombre = models.CharField(max_length=255, null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    ciudad = models.CharField(max_length=100, null=True, blank=True)
    estado = models.CharField(max_length=100, null=True, blank=True)

    # Datos del vehículo y producto
    producto_interes = models.ForeignKey(
        'Producto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads"
    )
    vehiculo = models.CharField(max_length=100, null=True, blank=True)
    anio_vehiculo = models.CharField(max_length=50, null=True, blank=True)
    direccion_envio = models.TextField(null=True, blank=True)

    # Estado del lead
    desea_comprar = models.BooleanField(null=True, default=None)
    cantidad_solicitada = models.PositiveIntegerField(default=1)
    lead_completo = models.BooleanField(default=False)

    # Gestión del asesor
    # null=pendiente, True=aprobado, False=rechazado
    aprobado_por_asesor = models.BooleanField(null=True, default=None)

    # Notificación al cliente
    notificado = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        nombre_display = self.nombre or 'Anónimo'
        ciudad_display = self.ciudad or 'Sin Ciudad'
        return f"Lead: {nombre_display} - {ciudad_display}"

    class Meta:
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ['-created_at']


class Reserva(models.Model):
    producto = models.ForeignKey(
        Producto,
        on_delete=models.CASCADE,
        related_name="reservas"
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="reservas",
        null=True,
        blank=True
    )
    cantidad = models.IntegerField(default=1)
    expira_en = models.DateTimeField()
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def crear_reserva(cls, producto, lead, cantidad=1, minutos=15):
        """
        Crea una reserva temporal con protección contra concurrencia.
        Bloquea la fila del producto hasta terminar la transacción.
        """
        from django.db import transaction
        with transaction.atomic():
            producto = Producto.objects.select_for_update().get(pk=producto.pk)
            if producto.stock_disponible < cantidad:
                raise ValueError(
                    f"Stock insuficiente. "
                    f"Disponible: {producto.stock_disponible}, "
                    f"Solicitado: {cantidad}"
                )
            return cls.objects.create(
                producto=producto,
                lead=lead,
                cantidad=cantidad,
                expira_en=timezone.now() + timedelta(minutes=minutos),
                activa=True
            )

    def confirmar(self):
        """
        Asesor aprueba: descuenta stock real y desactiva la reserva.
        """
        from django.db import transaction
        with transaction.atomic():
            self.producto.stock -= self.cantidad
            self.producto.save(update_fields=['stock', 'updated_at'])
            self.activa = False
            self.save(update_fields=['activa'])

    def liberar(self):
        """
        Asesor rechaza o TTL expiró: desactiva la reserva sin tocar el stock.
        """
        self.activa = False
        self.save(update_fields=['activa'])

    def __str__(self):
        estado = 'Activa' if self.activa else 'Inactiva'
        return (
            f"Reserva {self.producto} - "
            f"{estado} - "
            f"expira {self.expira_en.strftime('%d/%m/%Y %H:%M:%S')}"
        )

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"
        ordering = ['-created_at']