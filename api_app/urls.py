# src/api_app/urls.py
from django.urls import path
from .views import (
    # Asistencias
    AsistenciaList,
    AsistenciaVistaInicio,
    AsistenciaPaginaView,
    AsistenciaTodasView,
    AsistenciaReporteView,
    EstadisticasView,
    LegalAceptacionView,
    LegalBiometricoView,
    LegalSolicitudView,
    AdminLegalView,
    AdminSolicitudDatosView,
    NotificacionesView,
    AsistenciaFechasView,
    AsistenciaCreate,
    AsistenciaRetrieve,
    AsistenciaUpdate,
    AsistenciaDelete,
    # Horarios
    HorarioProfesorView,
    HorarioCursoView,
    HorarioClaseView,
    HorarioImportarView,
    HorarioHistorialView,
    CursosView,
    CursoDetalleView,
    CursoEstudiantesView,
    CursoEstudianteDetalleView,
    PerfilView,
    RegistroView,
    EstudianteVincularView,
    AdminCambiosEstudiantesView,
    AdminSolicitudesView,
    AdminSolicitudAccionView,
    AdminAutorizadosView,
    AdminAutorizadoDetalleView,
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
    path("asistencias/vista-inicio/", AsistenciaVistaInicio.as_view(), name="asistencia-vista-inicio"),
    path("legal/aceptacion/", LegalAceptacionView.as_view(), name="legal-aceptacion"),
    path("legal/biometrico/", LegalBiometricoView.as_view(), name="legal-biometrico"),
    path("legal/solicitudes/", LegalSolicitudView.as_view(), name="legal-solicitudes"),
    path("admin/legal/", AdminLegalView.as_view(), name="admin-legal"),
    path("admin/legal/solicitudes/<str:solicitud_id>/atender/", AdminSolicitudDatosView.as_view(), name="admin-legal-atender"),
    path("estadisticas/", EstadisticasView.as_view(), name="estadisticas"),
    path("notificaciones/", NotificacionesView.as_view(), name="notificaciones"),
    path("asistencias/reporte/", AsistenciaReporteView.as_view(), name="asistencia-reporte"),
    path("asistencias/todas/", AsistenciaTodasView.as_view(), name="asistencia-todas"),
    path("asistencias/pagina/", AsistenciaPaginaView.as_view(), name="asistencia-pagina"),
    path("asistencias/fechas/", AsistenciaFechasView.as_view(), name="asistencia-fechas"),
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
    path("horarios/cursos/<str:course_id>/", HorarioCursoView.as_view(), name="horario-curso"),
    # Ruta anterior con mayúscula, se conserva por compatibilidad
    path("horarios/Cursos/<str:course_id>/", HorarioCursoView.as_view(), name="horario-curso-legacy"),
    path("horarios/importar/", HorarioImportarView.as_view(), name="horario-importar"),
    path("horarios/historial/", HorarioHistorialView.as_view(), name="horario-historial"),

    # ============================================
    # CURSOS, ESTUDIANTES Y PERFIL
    # ============================================
    path("cursos/", CursosView.as_view(), name="curso-crear"),
    path("cursos/<str:unidad_id>/", CursoDetalleView.as_view(), name="curso-detalle"),
    path("cursos/<str:unidad_id>/estudiantes/", CursoEstudiantesView.as_view(), name="curso-estudiantes"),
    path("cursos/<str:unidad_id>/estudiantes/<str:cedula>/", CursoEstudianteDetalleView.as_view(), name="curso-estudiante"),
    path("perfil/", PerfilView.as_view(), name="perfil"),

    # ============================================
    # REGISTRO AUTOMÁTICO Y ADMINISTRACIÓN
    # ============================================
    path("registro/", RegistroView.as_view(), name="registro"),
    path("registro/estudiante/", EstudianteVincularView.as_view(), name="registro-estudiante"),
    path("admin/cambios-estudiantes/", AdminCambiosEstudiantesView.as_view(), name="admin-cambios-estudiantes"),
    path("admin/solicitudes/", AdminSolicitudesView.as_view(), name="admin-solicitudes"),
    path("admin/solicitudes/<str:solicitud_uid>/<slug:accion>/", AdminSolicitudAccionView.as_view(), name="admin-solicitud-accion"),
    path("admin/autorizados/", AdminAutorizadosView.as_view(), name="admin-autorizados"),
    path("admin/autorizados/<str:email>/", AdminAutorizadoDetalleView.as_view(), name="admin-autorizado"),
    path("horarios/clases/", HorarioClaseView.as_view(), name="horario-clase-create"),
    path("horarios/clases/<str:clase_id>/", HorarioClaseView.as_view(), name="horario-clase-detail"),
]