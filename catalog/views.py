from rest_framework import viewsets, filters
import os
import requests
from .models import Producto, Lead
from .serializers import ProductoSerializer, LeadSerializer
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.shortcuts import redirect

class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    # Permite buscar por marca, modelo o categoria como pide la prueba
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
                webhook_url = os.getenv('N8N_WEBHOOK_URL')
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

                Producto.objects.create(
                    marca=request.POST.get('marca'),
                    modelo=request.POST.get('modelo'),
                    categoria=request.POST.get('categoria'),
                    precio=request.POST.get('precio'),
                    stock=request.POST.get('stock'),
                    ciudad=request.POST.get('ciudad'),
                    estado=request.POST.get('estado'),
                    moneda="MXN",
                    compatibilidad_general=compatibilidad_limpia,
                    especificaciones=diccionario_especificaciones
                )
                messages.success(request, "¡Producto con especificaciones JSON guardado con éxito directamente!")
            except Exception as e:
                messages.error(request, f"Error al guardar la estructura directa: {str(e)}")
            return redirect('panel_index')

    # --- PETICIÓN GET (LECTURA DEL CRUD) ---
    # Extraemos solo los registros activos y los ordenamos por los más recientes
    productos = Producto.objects.filter(is_active=True).order_by('-created_at')
    leads = Lead.objects.filter(is_active=True).order_by('-created_at')
    
    context = {
        'productos': productos,
        'leads': leads
    }
    
    return render(request, 'panel/index.html', context)