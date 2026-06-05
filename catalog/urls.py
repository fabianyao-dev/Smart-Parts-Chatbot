from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductoViewSet, LeadViewSet, confirmar_compra
from .webhooks import n8n_catalog_webhook, evolution_whatsapp_webhook

router = DefaultRouter()
router.register(r'productos', ProductoViewSet, basename='producto')
router.register(r'leads', LeadViewSet, basename='lead')

urlpatterns = [
    path('', include(router.urls)),
    path('webhook/n8n-catalog/', n8n_catalog_webhook, name='webhook_n8n_catalog'),
    path('webhook/evolution/', evolution_whatsapp_webhook, name='webhook_evolution'),
    path('confirmar-compra/', confirmar_compra, name='confirmar_compra'),
]   