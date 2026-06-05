import json
import os
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import Producto, Lead

@csrf_exempt
def procesar_webhook_catalogo_n8n(request):
    """
    Recibe el JSON estructurado desde n8n después de que la IA procesó el texto en prosa.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Asumimos que n8n nos manda una lista de productos extraídos
            productos_extraidos = data.get('productos', [])
            
            for item in productos_extraidos:
                # Reutilizamos tu excelente lógica de Upsert
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
    estado_texto = 'aprobado' if aprobado else 'rechazado'
    return (
        f'Hola {nombre}, te informamos que tu lead fue {estado_texto}. '
        f'Si necesitas apoyo adicional, responde a este mensaje.'
    )


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
    Envía mensajes de estatus de leads de WhatsApp desde Evolution API.
    """
    if request.method == 'POST':
        try:
            payload = json.loads(request.body)
            
            # Evolution API envía diferentes tipos de eventos. Nos interesa "messages.upsert"
            event_type = payload.get('event')
            
            if event_type == 'messages.upsert':
                mensaje_data = payload.get('data', {})
                
                # Aquí extraes el número y el texto del mensaje
                # (La estructura exacta dependerá de la versión de Evolution API)
                
                # TODO: 1. Guardar el Lead si es nuevo.
                # TODO: 2. Reenviar el mensaje a tu Flujo de Conversación en n8n.
                
                # Por ahora solo respondemos 200 OK para que Evolution no reintente
                return JsonResponse({'status': 'success', 'message': 'Mensaje recibido'}, status=200)
                
            return JsonResponse({'status': 'ignored', 'message': 'Evento no procesado'}, status=200)
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)