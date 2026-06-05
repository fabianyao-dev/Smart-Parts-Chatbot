import json
import os
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import Producto, Lead, Reserva

@csrf_exempt
def procesar_webhook_catalogo_n8n(request):
    """
    Recibe el JSON estructurado desde n8n después de que la IA procesó el texto en prosa.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            productos_extraidos = data.get('productos', [])
            
            for item in productos_extraidos:
                Producto.objects.update_or_create(
                    marca=item.get('marca'),
                    modelo=item.get('modelo'),
                    ciudad=item.get('ciudad', 'Desconocida'),
                    estado=item.get('estado', 'Desconocido'),
                    defaults={
                        'categoria': item.get('categoria', 'General'),
                        'precio': item.get('precio', 0.0),
                        'stock': item.get('stock', 0),
                        'compatibilidad_general': item.get('compatibilidad', []),
                        'especificaciones': item.get('especificaciones', {}),
                        'is_active': True
                    }
                )
            return JsonResponse({'status': 'success', 'message': f'{len(productos_extraidos)} productos procesados.'}, status=200)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)


def obtener_configuracion_evolution():
    return {
        'send_message_url': getattr(settings, 'EVOLUTION_SEND_MESSAGE_URL', os.getenv('EVOLUTION_SEND_MESSAGE_URL')),
        'api_key': getattr(settings, 'EVOLUTION_API_KEY', os.getenv('EVOLUTION_API_KEY')),
        'country_code': getattr(settings, 'EVOLUTION_COUNTRY_CODE', os.getenv('EVOLUTION_COUNTRY_CODE', '52')),
    }


def normalizar_telefono_para_evolution(telefono, country_code='52'):
    if not telefono:
        return ''

    digitos = ''.join(ch for ch in str(telefono) if ch.isdigit())
    if not digitos:
        return ''

    if country_code and not digitos.startswith(country_code):
        if len(digitos) == 10:
            digitos = f'{country_code}{digitos}'

    return digitos


def construir_mensaje_estado_lead(lead, aprobado):
    nombre = lead.nombre or 'cliente'
    if aprobado:
        url_simulacion = getattr(
            settings,
            'STRIPE_SIMULACION_URL',
            os.getenv('STRIPE_SIMULACION_URL', 'https://buy.stripe.com/test_simulacion_smartparts')
        )

        cantidad = max(lead.cantidad_solicitada or 1, 1)
        ultima_reserva = Reserva.objects.filter(lead=lead).order_by('-created_at').first()
        if ultima_reserva and ultima_reserva.cantidad:
            cantidad = ultima_reserva.cantidad

        producto = lead.producto_interes
        if producto:
            descripcion_producto = f'{producto.marca} {producto.modelo}'
            total = producto.precio * cantidad
            total_formateado = f'{total:.2f}'
            monto_linea = f'Monto a pagar: ${total_formateado} {producto.moneda}'
            producto_linea = f'Producto: {descripcion_producto}'
        else:
            monto_linea = 'Monto a pagar: por confirmar con asesor.'
            producto_linea = 'Producto: por confirmar con asesor.'

        return (
            f'Hola {nombre}, tu solicitud de venta fue aprobada. '
            f'Cantidad: {cantidad}. '
            f'{producto_linea}. '
            f'{monto_linea}. '
            f'Puedes revisar esta simulacion de pago: {url_simulacion}. '
            f'Si necesitas apoyo adicional, responde a este mensaje.'
        )

    return (
        f'Hola {nombre}, te informamos que tu solicitud de venta fue rechazada. '
        f'Si necesitas apoyo adicional, responde a este mensaje.'
    )


def extraer_datos_mensaje_evolution(payload):
    data = payload.get('data', {}) if isinstance(payload, dict) else {}
    mensaje = data.get('message', {}) if isinstance(data, dict) else {}
    key = data.get('key', {}) if isinstance(data, dict) else {}

    telefono = (
        key.get('remoteJid')
        or data.get('remoteJid')
        or data.get('from')
        or mensaje.get('from')
        or ''
    )
    nombre = (
        data.get('pushName')
        or data.get('senderName')
        or data.get('participantName')
        or ''
    )
    texto = (
        mensaje.get('conversation')
        or mensaje.get('extendedTextMessage', {}).get('text')
        or data.get('text')
        or ''
    )

    telefono = str(telefono).split('@')[0].strip()
    return telefono, nombre.strip(), texto.strip()


def crear_o_actualizar_lead_pendiente_desde_evolution(payload):
    """
    Crea un lead nuevo con estado pendiente (aprobado_por_asesor=None).

    Si el lead ya existe y fue revisado (True o False), NO se resetea
    automáticamente. El reingreso manual se hace desde el panel con "Reabrir".
    Solo se actualizan campos de contacto (nombre) si cambiaron.
    """
    telefono, nombre, texto = extraer_datos_mensaje_evolution(payload)
    if not telefono:
        raise ValueError('No se pudo extraer un teléfono válido desde Evolution')

    nombre_base = nombre or telefono

    lead, created = Lead.objects.get_or_create(
        telefono=telefono,
        defaults={
            'nombre': nombre_base,
            'desea_comprar': None,
            'lead_completo': False,
            'aprobado_por_asesor': None,  # None = pendiente (sin revisar)
            'notificado': False,
            'is_active': True,
        }
    )

    campos_actualizados = []

    # Actualizar nombre si cambió
    if lead.nombre != nombre_base and nombre:
        lead.nombre = nombre_base
        campos_actualizados.append('nombre')

    # Reactivar si estaba inactivo (eliminado del panel)
    if not lead.is_active:
        lead.is_active = True
        campos_actualizados.append('is_active')

    # IMPORTANTE: NO resetear aprobado_por_asesor si el lead ya fue revisado.
    # Un mensaje nuevo de un cliente ya aprobado o rechazado no debe sacarlo
    # del historial automáticamente. El asesor decide si reabrir desde el panel.
    # Solo se resetea si el lead es nuevo (created=True, ya manejado por defaults).

    if campos_actualizados:
        lead.save(update_fields=campos_actualizados)

    return lead, created


def enviar_mensaje_estado_lead_por_evolution(lead, aprobado):
    configuracion = obtener_configuracion_evolution()
    send_message_url = configuracion['send_message_url']
    api_key = configuracion['api_key']
    country_code = configuracion['country_code'] or '52'

    if not send_message_url:
        raise ValueError('Falta configurar EVOLUTION_SEND_MESSAGE_URL en el .env')

    telefono_normalizado = normalizar_telefono_para_evolution(lead.telefono, country_code=country_code)
    if not telefono_normalizado:
        raise ValueError('El lead no tiene teléfono válido para enviar el mensaje')

    payload = {
        'number': telefono_normalizado,
        'text': construir_mensaje_estado_lead(lead, aprobado),
    }

    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['apikey'] = api_key

    response = requests.post(send_message_url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response


@csrf_exempt
def procesar_webhook_mensajes_evolution(request):
    """
    Recibe eventos de Evolution API y registra leads nuevos como pendientes.
    Leads ya revisados NO se resetean automáticamente.
    """
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            
            event_type = payload.get('event')
            
            if event_type == 'messages.upsert':
                lead, created = crear_o_actualizar_lead_pendiente_desde_evolution(payload)
                return JsonResponse({
                    'status': 'success',
                    'message': 'Lead registrado' if created else 'Lead existente, sin cambios de estado',
                    'lead_id': lead.id,
                    'created': created,
                    'aprobado_por_asesor': lead.aprobado_por_asesor,
                }, status=200)
                
            return JsonResponse({'status': 'ignored', 'message': 'Evento no procesado'}, status=200)
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)