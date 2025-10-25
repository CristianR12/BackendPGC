# src/api_app/urls.py - URLS COMPLETAS Y MEJORADAS
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
    ObtenerEstudiantesView,
    ConflictosHorarioView,
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
    # HORARIOS (Endpoints completos y mejorados)
    # ============================================
    
    # -------- GESTIÓN DE HORARIO DEL PROFESOR --------
    # Obtener todos los cursos del profesor
    # POST: Crear/actualizar horario completo
    # DELETE: Eliminar todo el horario
    path("horarios/", HorarioProfesorView.as_view(), name="horario-profesor"),
    
    # -------- GESTIÓN DE CURSO ESPECÍFICO --------
    # Obtener detalles de un curso
    # PUT: Actualizar el schedule de un curso
    # DELETE: Eliminar un curso completo
    path("horarios/cursos/<str:course_id>/", HorarioCursoView.as_view(), name="horario-curso"),
    
    # -------- GESTIÓN DE CLASES INDIVIDUALES --------
    # POST: Agregar una clase al horario de un curso
    # PUT: Actualizar una clase específica
    # DELETE: Eliminar una clase específica
    path("horarios/clases/", HorarioClaseView.as_view(), name="horario-clase-create"),
    path("horarios/clases/<str:clase_id>/", HorarioClaseView.as_view(), name="horario-clase-detail"),
    
    # -------- GESTIÓN DE ESTUDIANTES --------
    # Obtener lista de estudiantes de un curso
    path("horarios/cursos/<str:course_id>/estudiantes/", ObtenerEstudiantesView.as_view(), name="horario-estudiantes"),
    
    # -------- VALIDACIONES --------
    # Validar conflictos de horario sin guardar
    path("horarios/validar-conflictos/", ConflictosHorarioView.as_view(), name="validar-conflictos"),
]