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
)

urlpatterns = [
    # ============================================
    # HEALTH CHECK
    # ============================================
    path("health/", HealthCheck.as_view(), name="health-check"),
    
    # ============================================
    # ASISTENCIAS (Endpoints existentes)
    # ============================================
    path("asistencias/", AsistenciaList.as_view(), name="asistencia-list"),
    path("asistencias/crear/", AsistenciaCreate.as_view(), name="asistencia-create"),
    path("asistencias/<str:pk>/", AsistenciaRetrieve.as_view(), name="asistencia-detail"),
    path("asistencias/<str:pk>/update/", AsistenciaUpdate.as_view(), name="asistencia-update"),
    path("asistencias/<str:pk>/delete/", AsistenciaDelete.as_view(), name="asistencia-delete"),
    
    # ============================================
    # HORARIOS (Nuevos endpoints)
    # ============================================
    
    # Gestión de horario del profesor
    # GET: Obtener todos los cursos del profesor autenticado
    # POST: Crear/actualizar horario completo
    # DELETE: Eliminar todo el horario
    path("horarios/", HorarioProfesorView.as_view(), name="horario-profesor"),
    
    # Gestión de curso específico
    # GET: Obtener detalles de un curso
    # PUT: Actualizar el schedule de un curso
    path("horarios/cursos/<str:course_id>/", HorarioCursoView.as_view(), name="horario-curso"),
    
    # Gestión de clases individuales
    # POST: Agregar una clase al horario de un curso
    path("horarios/clases/", HorarioClaseView.as_view(), name="horario-clase-create"),
    
    # DELETE: Eliminar una clase específica
    path("horarios/clases/<str:clase_id>/", HorarioClaseView.as_view(), name="horario-clase-delete"),
]