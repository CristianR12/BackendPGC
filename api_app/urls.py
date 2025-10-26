# src/api_app/urls.py
from django.urls import path
from .views import (
    # Asistencias antiguas (compatibilidad)
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
    # Debug
    DebugCursosView,
    DebugAsistenciasPublicView,
)

urlpatterns = [
    # ============================================
    # HEALTH CHECK
    # ============================================
    path("health/", HealthCheck.as_view(), name="health-check"),
    
    # ============================================
    # DEBUG - QUITAR EN PRODUCCIÓN
    # ============================================
    path("debug/cursos/", DebugCursosView.as_view(), name="debug-cursos"),
    path("debug/asistencias/", DebugAsistenciasPublicView.as_view(), name="debug-asistencias-public"),
    
    # ============================================
    # ASISTENCIAS ANTIGUAS (Mantener por compatibilidad)
    # ============================================
    path("asistencias/", AsistenciaList.as_view(), name="asistencia-list"),
    path("asistencias/crear/", AsistenciaCreate.as_view(), name="asistencia-create"),
    path("asistencias/<str:pk>/", AsistenciaRetrieve.as_view(), name="asistencia-detail"),
    path("asistencias/<str:pk>/update/", AsistenciaUpdate.as_view(), name="asistencia-update"),
    path("asistencias/<str:pk>/delete/", AsistenciaDelete.as_view(), name="asistencia-delete"),
    
    # ============================================
    # HORARIOS
    # ============================================
    path("horarios/", HorarioProfesorView.as_view(), name="horario-profesor"),
    path("horarios/cursos/<str:course_id>/", HorarioCursoView.as_view(), name="horario-curso"),
    path("horarios/clases/", HorarioClaseView.as_view(), name="horario-clase-create"),
    path("horarios/clases/<str:clase_id>/", HorarioClaseView.as_view(), name="horario-clase-detail"),
]