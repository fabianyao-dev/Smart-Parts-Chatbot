from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Q
import os
import requests
from .models import Producto, Lead, Reserva
from .serializers import ProductoSerializer, LeadSerializer
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.conf import settings
from .webhooks import enviar_mensaje_estado_lead_por_evolution


# ==========================================
# VIEWSETS DE DRF
# ==========================================

class ProductoViewSet(viewsets.ModelViewSet):
    serializer_class = ProductoSerializer

    def get_queryset(self):
        queryset = Producto.objects.filter(is_active=True)
        search = self.request.query_params.get('search', None)

        if search:
            queryset = queryset.filter(
                Q(marca__icontains=search) |
                Q(modelo__icontains=search) |
                Q(categoria__icontains=search) |
                Q(ciudad__icontains=search) |
                Q(estado__icontains=search) |
                Q(compatibilidad_general__icontains=search)
            )

        return queryset


class LeadViewSet(viewsets.ModelViewSet):
    serializer_class = LeadSerializer

    def get_queryset(self):
        return Lead.objects.filter(is_active=True)


# ==========================================
# ENDPOINT: CONFIRMAR COMPRA
# ==========================================

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

    if not lead_id or not producto_id:
        return Response(
            {"error": "Se requieren lead_id y producto_id"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        lead = Lead.objects.get(id=lead_id, is_active=True)
        producto = Producto.objects.get(id=producto_id, is_active=True)

        reserva = Reserva.crear_reserva(
            producto=producto,
            lead=lead,
            cantidad=1,
            minutos=15
        )

        lead.desea_comprar = True
        lead.save(update_fields=['desea_comprar', 'updated_at'])

        return Response({
            "mensaje": "Reserva creada. Un asesor validará la compatibilidad.",
            "reserva_id": reserva.id,
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


# ==========================================
# MÓDULOS DE ACCIÓN (Lógica de Negocio)
# ==========================================

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
            timeout=45
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
        lead = Lead.objects.get(id=request.POST.get('lead_id'))
        estado_aprobacion_anterior = lead.aprobado_por_asesor
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

        # aprobado_por_asesor: True = aprobado, False = rechazado, None = pendiente
        # Desde el formulario: checkbox "on" = True, ausente/off = False
        lead.aprobado_por_asesor = True if aprobacion_recibida else False

        lead.lead_completo = bool(
            lead.nombre and
            lead.ciudad and
            lead.direccion_envio and
            lead.aprobado_por_asesor is True
        )
        lead.save()

        # Notificar al cliente solo si cambió el estado de aprobación
        if estado_aprobacion_anterior != lead.aprobado_por_asesor:
            try:
                enviar_mensaje_estado_lead_por_evolution(lead, lead.aprobado_por_asesor)
                lead.notificado = True
                lead.save(update_fields=['notificado'])
                estado_texto = 'aprobado' if lead.aprobado_por_asesor else 'rechazado'
                messages.success(
                    request,
                    f"¡Prospecto '{lead.nombre}' actualizado y mensaje de "
                    f"{estado_texto} enviado por WhatsApp!"
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
        lead = Lead.objects.get(id=request.POST.get('lead_id'))
        campos = []

        # Resetear a None = pendiente sin revisar (única semántica válida para cola)
        if lead.aprobado_por_asesor is not None:
            lead.aprobado_por_asesor = None
            campos.append('aprobado_por_asesor')

        if lead.notificado:
            lead.notificado = False
            campos.append('notificado')

        if lead.lead_completo:
            lead.lead_completo = False
            campos.append('lead_completo')

        if campos:
            # No incluir updated_at manualmente si el modelo usa auto_now=True
            lead.save(update_fields=campos)

        messages.success(request, f"Lead '{lead.nombre or lead.telefono or lead.id}' reabierto y enviado a la cola de pendientes.")
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


# ==========================================
# VISTA PRINCIPAL (Orquestador)
# ==========================================

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
        }

        ejecutar_accion = acciones.get(action_type)
        if ejecutar_accion:
            return ejecutar_accion(request)
        else:
            messages.error(request, "Acción no reconocida.")
            return redirect('panel_index')

    # GET: lectura filtrada
    # Semántica canónica:
    #   aprobado_por_asesor = None  → pendiente (cola)
    #   aprobado_por_asesor = True  → aprobado (historial)
    #   aprobado_por_asesor = False → rechazado (historial)
    productos = Producto.objects.filter(is_active=True).order_by('-created_at')

    leads_pendientes = Lead.objects.filter(
        is_active=True,
        aprobado_por_asesor__isnull=True   # None = sin revisar = cola
    ).order_by('created_at')

    leads_historial = Lead.objects.filter(
        is_active=True,
        aprobado_por_asesor__isnull=False  # True o False = revisados = historial
    ).order_by('-updated_at')

    productos_criticos = productos.filter(stock__lte=5)
    alertas_leads = leads_pendientes.count() > 0
    alertas_stock = productos_criticos.count() > 0

    total_alertas = 0
    if alertas_leads:
        total_alertas += 1
    if alertas_stock:
        total_alertas += 1

    context = {
        'productos': productos,
        'leads_pendientes': leads_pendientes,
        'leads_historial': leads_historial,
        'productos_criticos': productos_criticos,
        'alertas_leads': alertas_leads,
        'alertas_stock': alertas_stock,
        'total_alertas': total_alertas,
    }
    return render(request, 'panel/index.html', context)


def custom_404_view(request, exception):
    if request.user.is_authenticated:
        return redirect('panel_index')
    return redirect('login')