from rest_framework import viewsets, filters
from .models import Producto, Lead
from .serializers import ProductoSerializer, LeadSerializer

class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    # Permite buscar por marca, modelo o categoria como pide la prueba
    filter_backends = [filters.SearchFilter]
    search_fields = ['marca', 'modelo', 'categoria', 'ciudad', 'estado']

class LeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer