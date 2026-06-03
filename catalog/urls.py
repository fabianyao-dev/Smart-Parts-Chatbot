from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductoViewSet, LeadViewSet

router = DefaultRouter()
router.register(r'productos', ProductoViewSet)
router.register(r'leads', LeadViewSet)

urlpatterns = [
    path('', include(router.urls)),
]