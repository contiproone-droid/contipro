from django.urls import path

from . import views

app_name = 'profiles'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('perfis/', views.profile_list, name='profile_list'),
    path('perfis/novo/', views.profile_create, name='profile_create'),
    path('perfis/<int:pk>/', views.profile_detail, name='profile_detail'),
    path('perfis/<int:pk>/editar/', views.profile_update, name='profile_update'),
    path('perfis/<int:pk>/avancar-fase/', views.profile_advance_phase, name='profile_advance_phase'),
    path('pipeline/', views.pipeline_configure, name='pipeline_configure'),
    path('pipeline/criar/', views.pipeline_stage_create, name='pipeline_stage_create'),
    path('pipeline/<int:pk>/renomear/', views.pipeline_stage_rename, name='pipeline_stage_rename'),
    path('pipeline/<int:pk>/apagar/', views.pipeline_stage_delete, name='pipeline_stage_delete'),
    path('pipeline/reordenar/', views.pipeline_stage_reorder, name='pipeline_stage_reorder'),
    path('api/dashboard-data/', views.api_dashboard_data, name='api_dashboard_data'),
]
