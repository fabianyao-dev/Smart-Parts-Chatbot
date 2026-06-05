from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductoViewSet, LeadViewSet, confirmar_compra
from .webhooks import procesar_webhook_catalogo_n8n, procesar_webhook_mensajes_evolution

router = DefaultRouter()
router.register(r'productos', ProductoViewSet, basename='producto')
router.register(r'leads', LeadViewSet, basename='lead')

urlpatterns = [
    path('', include(router.urls)),
    path('webhook/n8n-catalog/', procesar_webhook_catalogo_n8n, name='webhook_n8n_catalog'),
    path('webhook/evolution/', procesar_webhook_mensajes_evolution, name='webhook_evolution'),
    path('confirmar-compra/', confirmar_compra, name='confirmar_compra'),
]   