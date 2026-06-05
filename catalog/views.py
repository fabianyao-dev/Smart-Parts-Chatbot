from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db import transaction
import os
import unicodedata
import requests
from .models import Producto, Lead, Reserva,NumeroAutorizado
from .serializers import ProductoSerializer, LeadSerializer
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.conf import settings
from django.utils import timezone
from .webhooks import enviar_mensaje_estado_lead_por_evolution 
from django.db.models import  Q


 

class ProductoViewSet(viewsets.ModelViewSet):
    serializer_class = ProductoSerializer

    @staticmethod
    def _normalize_search_text(value):
        if value is None:
            return ""
        texto = str(value).strip().lower()
        return ''.join(
            c for c in unicodedata.normalize('NFKD', texto)
            if not unicodedata.combining(c)
        )

    def get_queryset(self):
        queryset = Producto.objects.filter(is_active=True)
        search = self.request.query_params.get('search', None)

        if search:
            queryset_db = queryset.filter(
                Q(marca__icontains=search) |
                Q(modelo__icontains=search) |
                Q(categoria__icontains=search) |
                Q(ciudad__icontains=search) |
                Q(estado__icontains=search) |
                Q(compatibilidad_general__icontains=search) |
                Q(especificaciones__icontains=search)
            )

            # Fallback para tolerar acentos cuando el motor no hace matching
            # acento-insensible (ej. "bateria" vs "Batería").
            if queryset_db.exists():
                queryset = queryset_db
            else:
                termino = self._normalize_search_text(search)
                ids = []
                for producto in queryset:
                    bloque = " ".join([
                        producto.marca or "",
                        producto.modelo or "",
                        producto.categoria or "",
                        producto.ciudad or "",
                        producto.estado or "",
                        str(producto.compatibilidad_general or ""),
                        str(producto.especificaciones or ""),
                    ])
                    if termino in self._normalize_search_text(bloque):
                        ids.append(producto.id)
                queryset = queryset.filter(id__in=ids)

        return queryset

class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer

    def get_queryset(self):
        return Lead.objects.filter(is_active=True)


def calcular_lead_completo(lead):
    """
    Lead completo en negocio de venta:
    - Si la venta ya fue aprobada: completo.
    - Si desea comprar, hay producto y existe disponibilidad para su cantidad: completo.
    """
    if lead.aprobado_por_asesor is True:
        return True

    if lead.desea_comprar is not True:
        return False

    if not lead.producto_interes_id:
        return False

    cantidad = max(lead.cantidad_solicitada or 1, 1)
    tiene_reserva_activa = Reserva.objects.filter(
        lead=lead,
        activa=True,
        expira_en__gt=timezone.now(),
        cantidad__gte=cantidad
    ).exists()

    if tiene_reserva_activa:
        return True

    return lead.producto_interes.stock_disponible >= cantidad

  
@api_view(['POST'])
def confirmar_compra(request):
    """
    Llamado por n8n cuando el cliente confirma intención de compra.
    Crea una reserva temporal de 15 minutos con protección anti-concurrencia.

    Body esperado:
    {
        "lead_id": 1,
        "producto_id": 2
    }

    Respuestas:
    - 201: Reserva creada exitosamente
    - 400: Faltan campos requeridos
    - 404: Lead o Producto no encontrado
    - 409: Stock insuficiente (otro cliente se adelantó)
    """
    lead_id = request.data.get('lead_id')
    producto_id = request.data.get('producto_id')
    cantidad_raw = request.data.get('cantidad', 1)

    if not lead_id or not producto_id:
        return Response(
            {"error": "Se requieren lead_id y producto_id"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        cantidad = int(cantidad_raw)
        if cantidad <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return Response(
            {"error": "cantidad debe ser un entero mayor a 0"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            lead = Lead.objects.select_for_update().get(id=lead_id, is_active=True)
            producto = Producto.objects.select_for_update().get(id=producto_id, is_active=True)
 
            reserva = Reserva.objects.select_for_update().filter(
                lead=lead,
                producto=producto,
                activa=True,
                expira_en__gt=timezone.now(),
            ).order_by('-created_at').first()

            if reserva:
                cantidad_actual = max(reserva.cantidad or 1, 1)
                if cantidad > cantidad_actual:
                    adicional = cantidad - cantidad_actual
                    if producto.stock_disponible < adicional:
                        raise ValueError(
                            f"Stock insuficiente. Disponible: {producto.stock_disponible}, "
                            f"adicional solicitado: {adicional}."
                        )

                reserva.cantidad = cantidad
                reserva.expira_en = timezone.now() + timezone.timedelta(minutes=15)
                reserva.activa = True
                reserva.save(update_fields=['cantidad', 'expira_en', 'activa'])
                mensaje = "Reserva actualizada. Un asesor validará la compatibilidad."
            else:
                reserva = Reserva.crear_reserva(
                    producto=producto,
                    lead=lead,
                    cantidad=cantidad,
                    minutos=15
                )
                mensaje = "Reserva creada. Un asesor validará la compatibilidad."
 
            Reserva.objects.filter(
                lead=lead,
                activa=True,
                expira_en__gt=timezone.now()
            ).exclude(id=reserva.id).update(activa=False)

            lead.desea_comprar = True
            lead.producto_interes = producto
            lead.cantidad_solicitada = cantidad
            lead.lead_completo = calcular_lead_completo(lead)
            lead.save(update_fields=['desea_comprar', 'producto_interes', 'cantidad_solicitada', 'lead_completo', 'updated_at'])

        return Response({
            "mensaje": mensaje,
            "reserva_id": reserva.id,
            "cantidad": cantidad,
            "expira_en": reserva.expira_en,
            "stock_disponible": producto.stock_disponible,
            "lead_id": lead.id,
            "producto": f"{producto.marca} {producto.modelo}"
        }, status=status.HTTP_201_CREATED)

    except Lead.DoesNotExist:
        return Response(
            {"error": "Lead no encontrado"},
            status=status.HTTP_404_NOT_FOUND
        )
    except Producto.DoesNotExist:
        return Response(
            {"error": "Producto no encontrado"},
            status=status.HTTP_404_NOT_FOUND
        )
    except ValueError as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_409_CONFLICT
        )

 
def procesar_ingesta_prosa(request):
    texto_masivo = request.POST.get('texto_masivo')
    if not texto_masivo:
        return redirect('panel_index')

    webhook_url = getattr(settings, 'N8N_WEBHOOK_URL', os.getenv('N8N_WEBHOOK_URL'))
    if not webhook_url:
        messages.error(request, "Error de sistema: Falta configurar el webhook de n8n.")
        return redirect('panel_index')

    try:
        response = requests.post(
            webhook_url,
            json={"texto_masivo": texto_masivo},
            timeout=300
        )
        if response.status_code == 200:
            messages.success(request, "¡Catálogo procesado con IA e inyectado con éxito!")
        else:
            messages.warning(request, f"n8n respondió con error: Código {response.status_code}")
    except requests.exceptions.RequestException as e:
        messages.error(request, f"Fallo de conexión con n8n: {str(e)}")
    return redirect('panel_index')


def procesar_ingesta_directa(request):
    try:
        lista_compatibilidad = request.POST.getlist('compatibilidad')
        compatibilidad_limpia = [c.strip() for c in lista_compatibilidad if c.strip()]
        llaves = request.POST.getlist('especificacion_llave')
        valores = request.POST.getlist('especificacion_valor')
        diccionario_especificaciones = {
            k.strip(): v.strip()
            for k, v in zip(llaves, valores)
            if k.strip() and v.strip()
        }

        producto, created = Producto.objects.update_or_create(
            marca=request.POST.get('marca'),
            modelo=request.POST.get('modelo'),
            ciudad=request.POST.get('ciudad'),
            estado=request.POST.get('estado'),
            defaults={
                'categoria': request.POST.get('categoria'),
                'precio': request.POST.get('precio'),
                'stock': request.POST.get('stock'),
                'moneda': "MXN",
                'compatibilidad_general': compatibilidad_limpia,
                'especificaciones': diccionario_especificaciones,
                'is_active': True
            }
        )
        if created:
            messages.success(request, "¡Producto guardado con éxito!")
        else:
            messages.success(request, f"¡Inventario actualizado para {producto.marca}!")
    except Exception as e:
        messages.error(request, f"Error al guardar: {str(e)}")
    return redirect('panel_index')


def procesar_actualizacion_lead_desde_panel(request):
    try:
        with transaction.atomic():
            lead = Lead.objects.select_for_update().get(id=request.POST.get('lead_id'))
            estado_aprobacion_anterior = lead.aprobado_por_asesor
            forzar_estado_venta = request.POST.get('forzar_estado_venta', '0') == '1'
            aprobacion_recibida = request.POST.get('aprobado_por_asesor', 'off') == 'on'

            # Solo actualiza campos enviados para evitar borrar datos en formularios parciales
            if 'nombre' in request.POST:
                lead.nombre = request.POST.get('nombre')
            if 'ciudad' in request.POST:
                lead.ciudad = request.POST.get('ciudad')
            if 'estado' in request.POST:
                lead.estado = request.POST.get('estado')
            if 'vehiculo' in request.POST:
                lead.vehiculo = request.POST.get('vehiculo')
            if 'anio_vehiculo' in request.POST:
                lead.anio_vehiculo = request.POST.get('anio_vehiculo')
            if 'direccion_envio' in request.POST:
                lead.direccion_envio = request.POST.get('direccion_envio')
            if 'cantidad_solicitada' in request.POST:
                cantidad_solicitada_raw = request.POST.get('cantidad_solicitada')
                try:
                    cantidad_solicitada = int(cantidad_solicitada_raw)
                    if cantidad_solicitada <= 0:
                        raise ValueError
                    lead.cantidad_solicitada = cantidad_solicitada
                except (TypeError, ValueError):
                    raise ValueError("cantidad_solicitada debe ser un entero mayor a 0")

            # Solo cambiar estatus cuando se indique explícitamente.
            # Esto evita que una edición de campos (ej. cantidad) rechace el lead por accidente.
            if forzar_estado_venta:
                nuevo_estado_venta = True if aprobacion_recibida else False

                # Candado 3: evitar ciclos de descuento inconsistentes.
                if estado_aprobacion_anterior is False and nuevo_estado_venta is True:
                    raise ValueError("Para aprobar nuevamente una venta rechazada, primero debes reabrirla.")
                if estado_aprobacion_anterior is True and nuevo_estado_venta is False:
                    raise ValueError("Para rechazar una venta ya aprobada, primero reabre la venta.")

                lead.aprobado_por_asesor = nuevo_estado_venta
 
            if estado_aprobacion_anterior != lead.aprobado_por_asesor:
                if lead.aprobado_por_asesor is True:
                    reserva_activa = Reserva.objects.filter(
                        lead=lead,
                        activa=True,
                        expira_en__gt=timezone.now()
                    ).order_by('-created_at').first()

                    if reserva_activa:
                        reserva_activa.confirmar()
                    elif lead.producto_interes:
                        producto = Producto.objects.select_for_update().get(id=lead.producto_interes_id)
                        cantidad_a_descontar = max(lead.cantidad_solicitada or 1, 1)
                        if producto.stock < cantidad_a_descontar:
                            raise ValueError(
                                f"No hay stock suficiente para aprobar la venta de {producto.marca} {producto.modelo}. "
                                f"Solicitado: {cantidad_a_descontar}, disponible: {producto.stock}."
                            )
                        producto.stock -= cantidad_a_descontar
                        producto.save(update_fields=['stock', 'updated_at'])

                if lead.aprobado_por_asesor is False:
                    Reserva.objects.filter(
                        lead=lead,
                        activa=True,
                        expira_en__gt=timezone.now()
                    ).update(activa=False)

            lead.lead_completo = calcular_lead_completo(lead)
            lead.save()
 
        if estado_aprobacion_anterior != lead.aprobado_por_asesor:
            try:
                enviar_mensaje_estado_lead_por_evolution(lead, lead.aprobado_por_asesor)
                lead.notificado = True
                lead.save(update_fields=['notificado'])
                estado_texto = 'aprobada' if lead.aprobado_por_asesor else 'rechazada'
                messages.success(
                    request,
                    f"¡Prospecto '{lead.nombre}' actualizado y mensaje de "
                    f"venta {estado_texto} enviado por WhatsApp!"
                )
                return redirect('panel_index')
            except Exception as error_envio:
                lead.notificado = False
                lead.save(update_fields=['notificado'])
                messages.warning(
                    request,
                    f"¡Prospecto '{lead.nombre}' actualizado, pero no se pudo "
                    f"enviar el mensaje por WhatsApp: {str(error_envio)}"
                )
                return redirect('panel_index')

        messages.success(request, f"¡Prospecto '{lead.nombre}' actualizado!")
    except Exception as e:
        messages.error(request, f"Error al actualizar Lead: {str(e)}")
    return redirect('panel_index')


def procesar_reabrir_lead(request):
    """
    Reabre un lead para que vuelva a la cola operativa.
    Semántica: aprobado_por_asesor = None → pendiente (sin revisar).
    """
    try:
        with transaction.atomic():
            lead = Lead.objects.select_for_update().get(id=request.POST.get('lead_id'))
            estado_anterior = lead.aprobado_por_asesor
            campos = []
 
            if estado_anterior is True and lead.producto_interes_id:
                producto = Producto.objects.select_for_update().get(id=lead.producto_interes_id)
                cantidad_a_reponer = max(lead.cantidad_solicitada or 1, 1)
                producto.stock += cantidad_a_reponer
                producto.save(update_fields=['stock', 'updated_at'])

            # Resetear a None = pendiente sin revisar (única semántica válida para cola)
            if lead.aprobado_por_asesor is not None:
                lead.aprobado_por_asesor = None
                campos.append('aprobado_por_asesor')

            if lead.notificado:
                lead.notificado = False
                campos.append('notificado')

            nuevo_estado_completo = calcular_lead_completo(lead)
            if lead.lead_completo != nuevo_estado_completo:
                lead.lead_completo = nuevo_estado_completo
                campos.append('lead_completo')

            if campos:
                # No incluir updated_at manualmente si el modelo usa auto_now=True
                lead.save(update_fields=campos)

        messages.success(request, f"Lead '{lead.nombre or lead.telefono or lead.id}' reabierto y enviado a la cola de venta.")
    except Exception as e:
        messages.error(request, f"Error al reabrir Lead: {str(e)}")
    return redirect('panel_index')


def procesar_eliminar_lead(request):
    try:
        lead = Lead.objects.get(id=request.POST.get('lead_id'))
        lead.is_active = False
        lead.save()
        messages.success(request, "¡Prospecto eliminado del Panel!")
    except Exception as e:
        messages.error(request, f"Error al eliminar Lead: {str(e)}")
    return redirect('panel_index')


def procesar_actualizar_producto(request):
    try:
        producto_id = request.POST.get('producto_id')
        producto = Producto.objects.get(id=producto_id)

        producto.categoria = request.POST.get('categoria')
        producto.precio = request.POST.get('precio')
        producto.stock = request.POST.get('stock')
        producto.ciudad = request.POST.get('ciudad')
        producto.estado = request.POST.get('estado')

        lista_compatibilidad = request.POST.getlist('compatibilidad')
        producto.compatibilidad_general = [
            c.strip() for c in lista_compatibilidad if c.strip()
        ]

        llaves = request.POST.getlist('especificacion_llave')
        valores = request.POST.getlist('especificacion_valor')
        producto.especificaciones = {
            k.strip(): v.strip()
            for k, v in zip(llaves, valores)
            if k.strip() and v.strip()
        }

        producto.save()
        messages.success(
            request,
            f"¡Producto '{producto.marca} {producto.modelo}' actualizado!"
        )
    except Producto.DoesNotExist:
        messages.error(request, "Error: El producto ya no existe.")
    except Exception as e:
        messages.error(request, f"Error crítico al actualizar Producto: {str(e)}")
    return redirect('panel_index')


def procesar_eliminar_producto(request):
    try:
        producto = Producto.objects.get(id=request.POST.get('producto_id'))
        producto.is_active = False
        producto.save()
        messages.success(request, "¡Producto retirado del catálogo!")
    except Exception as e:
        messages.error(request, f"Error al eliminar Producto: {str(e)}")
    return redirect('panel_index')

 

@login_required
@never_cache
def panel_view(request):
    if request.method == 'POST':
        action_type = request.POST.get('action_type')

        acciones = {
            'prosa': procesar_ingesta_prosa,
            'directo': procesar_ingesta_directa,
            'actualizar_lead': procesar_actualizacion_lead_desde_panel,
            'reabrir_lead': procesar_reabrir_lead,
            'eliminar_lead': procesar_eliminar_lead,
            'actualizar_producto': procesar_actualizar_producto,
            'eliminar_producto': procesar_eliminar_producto,
            'agregar_numero': procesar_agregar_numero,    
            'eliminar_numero': procesar_eliminar_numero,
        }

        ejecutar_accion = acciones.get(action_type)
        if ejecutar_accion:
            return ejecutar_accion(request)
        else:
            messages.error(request, "Acción no reconocida.")
            return redirect('panel_index')

    # GET: lectura filtrada
    # Semántica operativa:
    #   Cola de pendientes: desea_comprar=True y aprobado_por_asesor=None
    #   Gestion: todos los leads activos (incluye cola)
    productos = Producto.objects.filter(is_active=True).order_by('-created_at')

    leads_historial = list(
        Lead.objects.filter(is_active=True)
        .select_related('producto_interes')
        .order_by('-updated_at')
    )
    for lead in leads_historial:
        nuevo_completo = calcular_lead_completo(lead)
        if lead.lead_completo != nuevo_completo:
            lead.lead_completo = nuevo_completo
            lead.save(update_fields=['lead_completo'])
        else:
            lead.lead_completo = nuevo_completo

    leads_pendientes = [
        lead for lead in leads_historial
        if lead.desea_comprar is True and lead.aprobado_por_asesor is None
    ]
    leads_pendientes.sort(key=lambda lead: lead.created_at)

    productos_criticos = productos.filter(stock__lte=5)
    alertas_leads = len(leads_pendientes) > 0
    alertas_stock = productos_criticos.count() > 0

    total_alertas = 0
    if alertas_leads:
        total_alertas += 1
    if alertas_stock:
        total_alertas += 1
        numeros_autorizados = NumeroAutorizado.objects.all().order_by('-agregado_en')

    context = {
        'productos': productos,
        'leads_pendientes': leads_pendientes,
        'leads_historial': leads_historial,
        'productos_criticos': productos_criticos,
        'alertas_leads': alertas_leads,
        'alertas_stock': alertas_stock,
        'total_alertas': total_alertas,
        'numeros_autorizados': numeros_autorizados,
    }
    return render(request, 'panel/index.html', context)


def custom_404_view(request, exception):
    if request.user.is_authenticated:
        return redirect('panel_index')
    return redirect('login')

def procesar_agregar_numero(request):
    telefono = request.POST.get('telefono', '').strip()
    if telefono:
        NumeroAutorizado.objects.get_or_create(telefono=telefono)
        messages.success(request, f"¡Número {telefono} autorizado con éxito!")
    else:
        messages.error(request, "El número no puede estar vacío.")
    return redirect('panel_index')

def procesar_eliminar_numero(request):
    numero_id = request.POST.get('numero_id')
    if numero_id:
        NumeroAutorizado.objects.filter(id=numero_id).delete()
        messages.success(request, "Número eliminado de la lista de acceso.")
    return redirect('panel_index')