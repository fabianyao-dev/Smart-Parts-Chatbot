from rest_framework import viewsets, filters
import os
import requests
from .models import Producto, Lead
from .serializers import ProductoSerializer, LeadSerializer
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.conf import settings

# --- VIEWSETS DE DRF ---
class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['marca', 'modelo', 'categoria', 'ciudad', 'estado']

class LeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer

def custom_404_view(request, exception=None):
    if request.user.is_authenticated:
        return redirect('panel_index') 
    return redirect('login') 

# ==========================================
# MÓDULOS DE ACCIÓN (Lógica de Negocio Separada)
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
        response = requests.post(webhook_url, json={"texto_masivo": texto_masivo}, timeout=45)
        if response.status_code == 200:
            messages.success(request, "¡Catálogo procesado con IA e inyectado con éxito!")
        else:
            messages.warning(request, f"n8n respondió con error técnico: Código {response.status_code}")
    except requests.exceptions.RequestException as e:
        messages.error(request, f"Fallo de conexión con la IA (n8n): {str(e)}")
    return redirect('panel_index')

def procesar_ingesta_directa(request):
    try:
        lista_compatibilidad = request.POST.getlist('compatibilidad')
        compatibilidad_limpia = [c.strip() for c in lista_compatibilidad if c.strip()]
        llaves = request.POST.getlist('especificacion_llave')
        valores = request.POST.getlist('especificacion_valor')
        
        diccionario_especificaciones = {k.strip(): v.strip() for k, v in zip(llaves, valores) if k.strip() and v.strip()}

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
            messages.success(request, "¡Producto guardado con éxito directamente!")
        else:
            messages.success(request, f"¡Inventario actualizado para {producto.marca}!")
    except Exception as e:
        messages.error(request, f"Error al guardar: {str(e)}")
    return redirect('panel_index')

def procesar_actualizar_lead(request):
    try:
        lead = Lead.objects.get(id=request.POST.get('lead_id'))
        lead.nombre = request.POST.get('nombre')
        lead.ciudad = request.POST.get('ciudad')
        lead.estado = request.POST.get('estado')
        lead.vehiculo = request.POST.get('vehiculo')
        lead.anio_vehiculo = request.POST.get('anio_vehiculo')
        lead.direccion_envio = request.POST.get('direccion_envio')
        aprobado = request.POST.get('aprobado_por_asesor') == 'on'
        lead.aprobado_por_asesor = aprobado
        lead.lead_completo = bool(lead.nombre and lead.ciudad and lead.direccion_envio and aprobado)
        lead.save()
        messages.success(request, f"¡Prospecto '{lead.nombre}' actualizado!")
    except Exception as e:
        messages.error(request, f"Error al actualizar Lead: {str(e)}")
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
    """
    Recibe el formulario completo de edición y actualiza el producto en la DB.
    Utiliza un patrón Upsert inteligente para stock y precio.
    """
    try:
        producto_id = request.POST.get('producto_id')
        producto = Producto.objects.get(id=producto_id)
        
        # Leemos los campos básicos
        producto.categoria = request.POST.get('categoria')
        producto.precio = request.POST.get('precio')
        producto.stock = request.POST.get('stock')
        producto.ciudad = request.POST.get('ciudad')
        producto.estado = request.POST.get('estado')
        
        # Procesamos las compatibilidades (Lista JSON)
        lista_compatibilidad = request.POST.getlist('compatibilidad')
        producto.compatibilidad_general = [c.strip() for c in lista_compatibilidad if c.strip()]

        # Procesamos las especificaciones (Diccionario JSON)
        llaves = request.POST.getlist('especificacion_llave')
        valores = request.POST.getlist('especificacion_valor')
        diccionario_especificaciones = {}
        for llave, valor in zip(llaves, valores):
            if llave.strip() and valor.strip():
                diccionario_especificaciones[llave.strip()] = valor.strip()
        producto.especificaciones = diccionario_especificaciones
        
        producto.save()
        messages.success(request, f"¡Producto '{producto.marca} {producto.modelo}' actualizado correctamente!")
        
    except Producto.DoesNotExist:
        messages.error(request, "Error: El producto a actualizar ya no existe.")
    except Exception as e:
        messages.error(request, f"Error crítico al actualizar el Producto: {str(e)}")
        
    return redirect('panel_index')

def procesar_eliminar_producto(request):
    try:
        producto = Producto.objects.get(id=request.POST.get('producto_id'))
        producto.is_active = False # Soft delete igual que leads
        producto.save()
        messages.success(request, "¡Producto retirado del catálogo!")
    except Exception as e:
        messages.error(request, f"Error al eliminar Producto: {str(e)}")
    return redirect('panel_index')


# ==========================================
# VISTA PRINCIPAL (Orquestador Limpio)
# ==========================================
@login_required
@never_cache 
def panel_view(request):
    if request.method == 'POST':
        action_type = request.POST.get('action_type')
        
        # Diccionario de enrutamiento (El Patrón de Despacho)
        acciones = {
            'prosa': procesar_ingesta_prosa,
            'directo': procesar_ingesta_directa,
            'actualizar_lead': procesar_actualizar_lead,
            'eliminar_lead': procesar_eliminar_lead,
            'actualizar_producto': procesar_actualizar_producto,
            'eliminar_producto': procesar_eliminar_producto,
        }
        
        ejecutar_accion = acciones.get(action_type)
        if ejecutar_accion:
            return ejecutar_accion(request)
        else:
            messages.error(request, "Acción no reconocida por el sistema.")
            return redirect('panel_index')

    # --- PETICIÓN GET (LECTURA FILTRADA) ---
    productos = Producto.objects.filter(is_active=True).order_by('-created_at')
    leads_pendientes = Lead.objects.filter(is_active=True, aprobado_por_asesor=False).order_by('created_at')
    leads_historial = Lead.objects.filter(is_active=True, aprobado_por_asesor=True).order_by('-updated_at')
    
    # ==================================================
    # NUEVO: LÓGICA DE NOTIFICACIONES (CEREBRO DE LA CAMPANA)
    # ==================================================
    # Filtramos stock menor a 6 (Es decir, 5 o menos)
    productos_criticos = productos.filter(stock__lte=5) 
    
    alertas_leads = leads_pendientes.count() > 0
    alertas_stock = productos_criticos.count() > 0
    
    # Sumamos cuántas alertas tenemos para pintar el "globo rojo"
    total_alertas = 0
    if alertas_leads: total_alertas += 1
    if alertas_stock: total_alertas += 1

    context = {
        'productos': productos,
        'leads_pendientes': leads_pendientes,
        'leads_historial': leads_historial,
        # Inyectamos las variables de alerta al template
        'productos_criticos': productos_criticos,
        'alertas_leads': alertas_leads,
        'alertas_stock': alertas_stock,
        'total_alertas': total_alertas,
    }
    return render(request, 'panel/index.html', context)