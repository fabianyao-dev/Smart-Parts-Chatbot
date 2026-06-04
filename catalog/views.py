from rest_framework import viewsets, filters
import os
import requests
from .models import Producto, Lead
from .serializers import ProductoSerializer, LeadSerializer
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.conf import settings # <-- IMPORTANTE: Importamos settings

class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['marca', 'modelo', 'categoria', 'ciudad', 'estado']

class LeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer

def custom_404_view(request, exception=None):
    """
    Intercepta URLs no encontradas (Error 404).
    Si el usuario tiene sesión, lo manda al panel. Si no, al login.
    """
    if request.user.is_authenticated:
        return redirect('panel_index') 
    return redirect('login') 
    
@login_required
@never_cache 
def panel_view(request):
    if request.method == 'POST':
        action_type = request.POST.get('action_type')

        # --- CASO A: INGESTA EN PROSA ---
        if action_type == 'prosa':
            texto_masivo = request.POST.get('texto_masivo')
            if texto_masivo:
                # 1. Leemos la URL de forma segura a través de settings de Django
                webhook_url = getattr(settings, 'N8N_WEBHOOK_URL', os.getenv('N8N_WEBHOOK_URL'))
                
                # BALA DE PLATA: Si tu archivo .env sigue fallando en Windows, 
                # quítale el '#' a la siguiente línea temporalmente para poder avanzar hoy:
                # webhook_url = "https://fabianyao.app.n8n.cloud/webhook-test/ingesta-prosa"

                if not webhook_url:
                    messages.error(request, "Error de sistema: Falta configurar el webhook de n8n.")
                    return redirect('panel_index')
                
                try:
                    payload = {"texto_masivo": texto_masivo}
                    response = requests.post(webhook_url, json=payload, timeout=45)
                    if response.status_code == 200:
                        messages.success(request, "¡Catálogo procesado con IA e inyectado con éxito!")
                    else:
                        messages.warning(request, f"n8n respondió con error técnico: Código {response.status_code}")
                except requests.exceptions.RequestException as e:
                    messages.error(request, f"Fallo de conexión con la IA (n8n): {str(e)}")
            return redirect('panel_index')

        # --- CASO B: INGESTA ESTRUCTURADA DIRECTA ---
        elif action_type == 'directo':
            try:
                lista_compatibilidad = request.POST.getlist('compatibilidad')
                compatibilidad_limpia = [c.strip() for c in lista_compatibilidad if c.strip()]

                llaves = request.POST.getlist('especificacion_llave')
                valores = request.POST.getlist('especificacion_valor')
                
                diccionario_especificaciones = {}
                for llave, valor in zip(llaves, valores):
                    if llave.strip() and valor.strip():
                        diccionario_especificaciones[llave.strip()] = valor.strip()

                # RESTAURADO EL PATRÓN UPSERT (Para evitar registros duplicados)
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
                    messages.success(request, "¡Producto con especificaciones JSON guardado con éxito directamente!")
                else:
                    messages.success(request, f"¡Inventario actualizado para {producto.marca} en {producto.ciudad}!")
                    
            except Exception as e:
                messages.error(request, f"Error al guardar la estructura directa: {str(e)}")
            return redirect('panel_index')

    # --- PETICIÓN GET (LECTURA DEL CRUD) ---
    productos = Producto.objects.filter(is_active=True).order_by('-created_at')
    leads = Lead.objects.filter(is_active=True).order_by('-created_at')
    
    context = {
        'productos': productos,
        'leads': leads
    }
    
    return render(request, 'panel/index.html', context)