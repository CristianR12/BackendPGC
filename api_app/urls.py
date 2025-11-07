# src/api_app/urls.py
from django.urls import path
from .views import (
    # Asistencias
    AsistenciaList,
    AsistenciaCreate,
    AsistenciaRetrieve,
    AsistenciaUpdate,
    AsistenciaDelete,
    # Horarios
    HorarioProfesorView,
    HorarioCursoView,
    HorarioClaseView,
    # Health Check
    HealthCheck,
    EstudianteNombreView,
)

urlpatterns = [
    # ============================================
    # HEALTH CHECK
    # ============================================
    path("health/", HealthCheck.as_view(), name="health-check"),
    
    # ============================================
    # ASISTENCIAS
    # ============================================
    path("asistencias/", AsistenciaList.as_view(), name="asistencia-list"),
    path("asistencias/crear/", AsistenciaCreate.as_view(), name="asistencia-create"),
    path("asistencias/<str:pk>/", AsistenciaRetrieve.as_view(), name="asistencia-detail"),
    path("asistencias/<str:pk>/update/", AsistenciaUpdate.as_view(), name="asistencia-update"),
    path("asistencias/<str:pk>/delete/", AsistenciaDelete.as_view(), name="asistencia-delete"),
    path('estudiantes/nombre/<str:cedula>/', EstudianteNombreView.as_view(), name='estudiante-nombre'),

    
    # ============================================
    # HORARIOS
    # ============================================
    path("horarios/", HorarioProfesorView.as_view(), name="horario-profesor"),
    path("horarios/Cursos/<str:course_id>/", HorarioCursoView.as_view(), name="horario-curso"),
    path("horarios/clases/", HorarioClaseView.as_view(), name="horario-clase-create"),
    path("horarios/clases/<str:clase_id>/", HorarioClaseView.as_view(), name="horario-clase-detail"),
]