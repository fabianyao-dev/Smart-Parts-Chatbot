from django.contrib import admin
from django.urls import path, include

from catalog.views import panel_view # Importamos tu nueva vista
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('catalog.urls')),
    
    # Ruta del Panel protegida
    path('panel/', panel_view, name='panel_index'),

    # 1. PRIMERO: Nuestra regla específica para sobreescribir el login
    path('auth/login/', auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    
    # 2. DESPUÉS: El resto de las rutas nativas de Django (logout, password reset, etc.)
    path('auth/', include('django.contrib.auth.urls')), 
]

handler404 = 'catalog.views.custom_404_view'