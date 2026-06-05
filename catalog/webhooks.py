import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import Producto, Lead

@csrf_exempt
def n8n_catalog_webhook(request):
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


@csrf_exempt
def evolution_whatsapp_webhook(request):
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