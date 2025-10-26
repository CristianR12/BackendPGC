from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from firebase_admin import firestore
from .serializers import (
    AsistenciaSerializer, 
    UserSerializer,
    CourseSerializer,
    PersonSerializer,
    ScheduleClassSerializer,
    UpdateScheduleSerializer
)
from firebase_admin.exceptions import FirebaseError
from google.api_core.exceptions import PermissionDenied, NotFound
import logging
from datetime import datetime
from .permissions import verificar_token

# Configurar logger
logger = logging.getLogger(__name__)
db = firestore.client()

# ----- MANEJO DE ERRORES FIREBASE ----
def handle_firestore_error(e):
    if isinstance(e, PermissionDenied):
        return Response({"error": "Acceso denegado a Firestore"}, status=status.HTTP_403_FORBIDDEN)
    elif isinstance(e, NotFound):
        return Response({"error": "Documento no encontrado"}, status=status.HTTP_404_NOT_FOUND)
    elif isinstance(e, FirebaseError):
        return Response({"error": "Error interno del servicio Firebase"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    else:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ============================================
# ASISTENCIAS - MODIFICADO PARA TODAS LAS SUBCOLECCIONES
# ============================================

class AsistenciaList(APIView):
    """
    GET /api/asistencias/
    Lista TODAS las asistencias de TODOS los cursos desde las subcolecciones
    """
    def get(self, request):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("=" * 60)
            logger.info("📥 [GET] /api/asistencias/ - Obtener TODAS las asistencias de TODOS los cursos")
            
            asistencias_list = []
            
            # ✅ OBTENER TODOS LOS CURSOS (sin filtrar por profesor)
            courses_ref = db.collection("courses")
            all_courses = courses_ref.stream()
            
            cursos_procesados = 0
            
            for course in all_courses:
                course_id = course.id
                course_data = course.to_dict()
                course_name = course_data.get('nameCourse', 'Sin nombre')
                
                logger.info(f"   📚 Procesando curso: {course_name} (ID: {course_id})")
                cursos_procesados += 1
                
                # Obtener la subcolección 'assistances' del curso
                assistances_ref = db.collection("courses").document(course_id).collection("assistances")
                assistances = assistances_ref.stream()
                
                asistencias_curso = 0
                
                for assistance_doc in assistances:
                    fecha_id = assistance_doc.id  # El ID es la fecha
                    assistance_data = assistance_doc.to_dict()
                    
                    # Cada documento de asistencia tiene campos con cédulas de estudiantes
                    for cedula, estudiante_data in assistance_data.items():
                        if isinstance(estudiante_data, dict):
                            asistencias_curso += 1
                            
                            # Crear objeto de asistencia
                            asistencia = {
                                'id': f"{course_id}_{fecha_id}_{cedula}",
                                'estudiante': cedula,
                                'asignatura': course_name,
                                'fechaYhora': fecha_id,
                                'estadoAsistencia': estudiante_data.get('estadoAsistencia', 'Presente'),
                                'horaRegistro': estudiante_data.get('horaRegistro', ''),
                                'late': estudiante_data.get('late', False),
                                'courseId': course_id,
                                'fechaDocId': fecha_id
                            }
                            asistencias_list.append(asistencia)
                
                logger.info(f"      ✅ {asistencias_curso} asistencias encontradas en este curso")
            
            logger.info(f"✅ [SUCCESS] Total cursos procesados: {cursos_procesados}")
            logger.info(f"✅ [SUCCESS] Total asistencias encontradas: {len(asistencias_list)}")
            logger.info("=" * 60)
            
            return Response(asistencias_list, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ [ERROR] Error en AsistenciaList: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response(
                {"error": "Error al obtener asistencias", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AsistenciaCreate(APIView):
    """
    POST /api/asistencias/crear/
    Crea una nueva asistencia en la subcolección del curso
    """
    def post(self, request):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("📥 [POST] /api/asistencias/crear/")
            
            # Validar datos requeridos
            estudiante_cedula = request.data.get('estudiante')
            estado_asistencia = request.data.get('estadoAsistencia')
            asignatura = request.data.get('asignatura')
            
            if not all([estudiante_cedula, estado_asistencia, asignatura]):
                return Response(
                    {"error": "Faltan campos requeridos: estudiante, estadoAsistencia, asignatura"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Buscar el curso por nombre
            courses_ref = db.collection("courses")
            course_query = courses_ref.where("nameCourse", "==", asignatura).limit(1).stream()
            
            course_doc = None
            for doc in course_query:
                course_doc = doc
                break
            
            if not course_doc:
                return Response(
                    {"error": f"No se encontró el curso: {asignatura}"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            course_id = course_doc.id
            
            # Fecha actual (formato: YYYY-MM-DD)
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            hora_actual = datetime.now().strftime("%H:%M:%S")
            
            # Referencia al documento de asistencia del día
            assistance_ref = db.collection("courses").document(course_id).collection("assistances").document(fecha_hoy)
            
            # Datos del estudiante
            estudiante_data = {
                'estadoAsistencia': estado_asistencia,
                'horaRegistro': hora_actual,
                'late': False
            }
            
            # Actualizar o crear el documento con la cédula del estudiante como campo
            assistance_ref.set({
                estudiante_cedula: estudiante_data
            }, merge=True)
            
            logger.info(f"✅ Asistencia creada: {estudiante_cedula} en {asignatura} - {fecha_hoy}")
            
            return Response(
                {
                    "id": f"{course_id}_{fecha_hoy}_{estudiante_cedula}",
                    "estudiante": estudiante_cedula,
                    "estadoAsistencia": estado_asistencia,
                    "asignatura": asignatura,
                    "fechaYhora": fecha_hoy,
                    "horaRegistro": hora_actual,
                    "late": False
                },
                status=status.HTTP_201_CREATED
            )
                
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaRetrieve(APIView):
    """
    GET /api/asistencias/<id>/
    Obtiene una asistencia específica
    El ID viene en formato: courseId_fechaId_cedula
    """
    def get(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            # Descomponer el ID
            parts = pk.split('_')
            if len(parts) < 3:
                return Response(
                    {"error": "ID de asistencia inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            course_id = parts[0]
            fecha_id = parts[1]
            cedula = '_'.join(parts[2:])
            
            # Obtener el documento de asistencia
            assistance_ref = db.collection("courses").document(course_id).collection("assistances").document(fecha_id)
            assistance_doc = assistance_ref.get()
            
            if not assistance_doc.exists:
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            assistance_data = assistance_doc.to_dict()
            
            if cedula not in assistance_data:
                return Response(
                    {"error": "Estudiante no encontrado en esta asistencia"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Obtener nombre del curso
            course_doc = db.collection("courses").document(course_id).get()
            course_name = course_doc.to_dict().get('nameCourse', 'Sin nombre') if course_doc.exists else 'Sin nombre'
            
            estudiante_data = assistance_data[cedula]
            
            data = {
                'id': pk,
                'estudiante': cedula,
                'asignatura': course_name,
                'fechaYhora': fecha_id,
                'estadoAsistencia': estudiante_data.get('estadoAsistencia', 'Presente'),
                'horaRegistro': estudiante_data.get('horaRegistro', ''),
                'late': estudiante_data.get('late', False),
                'courseId': course_id,
                'fechaDocId': fecha_id
            }
            
            return Response(data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaUpdate(APIView):
    """
    PUT /api/asistencias/<id>/update/
    Actualiza una asistencia específica
    """
    def put(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            # Descomponer el ID
            parts = pk.split('_')
            if len(parts) < 3:
                return Response(
                    {"error": "ID de asistencia inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            course_id = parts[0]
            fecha_id = parts[1]
            cedula = '_'.join(parts[2:])
            
            # Referencia al documento
            assistance_ref = db.collection("courses").document(course_id).collection("assistances").document(fecha_id)
            assistance_doc = assistance_ref.get()
            
            if not assistance_doc.exists:
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            assistance_data = assistance_doc.to_dict()
            
            if cedula not in assistance_data:
                return Response(
                    {"error": "Estudiante no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Actualizar datos del estudiante
            estudiante_data = assistance_data[cedula]
            
            if 'estadoAsistencia' in request.data:
                estudiante_data['estadoAsistencia'] = request.data['estadoAsistencia']
            
            # Actualizar en Firestore
            assistance_ref.update({
                cedula: estudiante_data
            })
            
            # Obtener nombre del curso
            course_doc = db.collection("courses").document(course_id).get()
            course_name = course_doc.to_dict().get('nameCourse', 'Sin nombre') if course_doc.exists else 'Sin nombre'
            
            updated_data = {
                'id': pk,
                'estudiante': cedula,
                'asignatura': course_name,
                'fechaYhora': fecha_id,
                'estadoAsistencia': estudiante_data.get('estadoAsistencia'),
                'horaRegistro': estudiante_data.get('horaRegistro', ''),
                'late': estudiante_data.get('late', False)
            }
            
            logger.info(f"✅ Asistencia actualizada: {pk}")
            
            return Response(updated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaDelete(APIView):
    """
    DELETE /api/asistencias/<id>/delete/
    Elimina una asistencia específica
    """
    def delete(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            # Descomponer el ID
            parts = pk.split('_')
            if len(parts) < 3:
                return Response(
                    {"error": "ID de asistencia inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            course_id = parts[0]
            fecha_id = parts[1]
            cedula = '_'.join(parts[2:])
            
            # Referencia al documento
            assistance_ref = db.collection("courses").document(course_id).collection("assistances").document(fecha_id)
            assistance_doc = assistance_ref.get()
            
            if not assistance_doc.exists:
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            assistance_data = assistance_doc.to_dict()
            
            if cedula not in assistance_data:
                return Response(
                    {"error": "Estudiante no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Eliminar el campo del estudiante
            assistance_ref.update({
                cedula: firestore.DELETE_FIELD
            })
            
            logger.info(f"✅ Asistencia eliminada: {pk}")
            
            return Response(
                {'success': True, 'message': 'Asistencia eliminada', 'id': pk},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================
# HORARIOS - ENDPOINTS EXISTENTES
# ============================================

class HorarioProfesorView(APIView):
    """
    GET /api/horarios/
    Obtiene todos los cursos del profesor autenticado
    
    POST /api/horarios/
    Crea o actualiza el horario completo del profesor
    """
    
    def get(self, request):
        """Obtener todos los cursos del profesor"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("=" * 60)
            logger.info("📅 [GET] /api/horarios/ - Obtener horario del profesor")
            
            # Obtener el UID del usuario autenticado
            user_uid = request.user_firebase.get('uid')
            logger.info(f"👤 Profesor UID: {user_uid}")
            
            # Buscar cursos donde el profesorID coincida
            courses_ref = db.collection("courses")
            query = courses_ref.where("profesorID", "==", user_uid)
            docs = query.stream()
            
            cursos = []
            for doc in docs:
                curso_data = doc.to_dict()
                curso_data['id'] = doc.id
                cursos.append(curso_data)
                logger.info(f"   📚 Curso encontrado: {curso_data.get('nameCourse')}")
            
            logger.info(f"✅ Total cursos encontrados: {len(cursos)}")
            logger.info("=" * 60)
            
            # Si no hay cursos, devolver estructura vacía
            if len(cursos) == 0:
                return Response({
                    "profesorEmail": request.user_firebase.get('email'),
                    "profesorNombre": request.user_firebase.get('name', ''),
                    "clases": [],
                    "message": "No hay cursos asignados"
                }, status=status.HTTP_200_OK)
            
            # Transformar a formato esperado por el frontend
            return Response({
                "profesorEmail": request.user_firebase.get('email'),
                "profesorNombre": request.user_firebase.get('name', ''),
                "clases": cursos
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error al obtener horario: {str(e)}")
            return Response(
                {"error": "Error al obtener horario", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Crear o actualizar horario del profesor"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("=" * 60)
            logger.info("📅 [POST] /api/horarios/ - Crear/Actualizar horario")
            logger.info(f"📦 Datos recibidos: {request.data}")
            
            user_uid = request.user_firebase.get('uid')
            
            clases = request.data.get('clases', [])
            
            if not clases:
                return Response(
                    {"error": "No se proporcionaron clases"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            cursos_guardados = []
            
            for clase in clases:
                serializer = CourseSerializer(data=clase)
                if serializer.is_valid():
                    curso_data = serializer.validated_data
                    curso_data['profesorID'] = user_uid
                    
                    if 'id' in clase and clase['id']:
                        doc_ref = db.collection("courses").document(clase['id'])
                        doc_ref.update(curso_data)
                        curso_data['id'] = clase['id']
                    else:
                        doc_ref = db.collection("courses").add(curso_data)
                        curso_data['id'] = doc_ref[1].id
                    
                    cursos_guardados.append(curso_data)
                else:
                    logger.warning(f"⚠️ Datos inválidos en clase: {serializer.errors}")
            
            logger.info(f"✅ Horario guardado: {len(cursos_guardados)} cursos")
            logger.info("=" * 60)
            
            return Response({
                "profesorEmail": request.user_firebase.get('email'),
                "clases": cursos_guardados
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"❌ Error al guardar horario: {str(e)}")
            return Response(
                {"error": "Error al guardar horario", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request):
        """Eliminar todo el horario del profesor"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("🗑️ [DELETE] /api/horarios/ - Eliminar horario completo")
            
            user_uid = request.user_firebase.get('uid')
            
            courses_ref = db.collection("courses")
            query = courses_ref.where("profesorID", "==", user_uid)
            docs = query.stream()
            
            deleted_count = 0
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1
            
            logger.info(f"✅ Eliminados {deleted_count} cursos")
            
            return Response({
                "success": True,
                "message": f"Horario eliminado ({deleted_count} cursos)"
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HorarioCursoView(APIView):
    """
    PUT /api/horarios/cursos/<course_id>/
    Actualiza el horario (schedule) de un curso específico
    
    GET /api/horarios/cursos/<course_id>/
    Obtiene los detalles de un curso específico
    """
    
    def get(self, request, course_id):
        """Obtener detalles de un curso"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            doc = db.collection("courses").document(course_id).get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            curso_data['id'] = doc.id
            
            return Response(curso_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def put(self, request, course_id):
        """Actualizar el horario de un curso"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"📝 [PUT] /api/horarios/cursos/{course_id}/ - Actualizar horario")
            
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            serializer = UpdateScheduleSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": "Datos inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            schedule = serializer.validated_data['schedule']
            doc_ref.update({"schedule": schedule})
            
            updated_doc = doc_ref.get()
            updated_data = updated_doc.to_dict()
            updated_data['id'] = course_id
            
            logger.info(f"✅ Horario actualizado: {len(schedule)} clases")
            
            return Response(updated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HorarioClaseView(APIView):
    """
    POST /api/horarios/clases/
    Agrega una clase al horario de un curso
    
    DELETE /api/horarios/clases/<clase_id>/
    Elimina una clase específica del horario
    """
    
    def post(self, request):
        """Agregar una clase a un curso"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("➕ [POST] /api/horarios/clases/ - Agregar clase")
            
            course_id = request.data.get('courseId')
            if not course_id:
                return Response(
                    {"error": "courseId es requerido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            serializer = ScheduleClassSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": "Datos inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            schedule = curso_data.get('schedule', [])
            schedule.append(serializer.validated_data)
            
            doc_ref.update({"schedule": schedule})
            
            logger.info(f"✅ Clase agregada al curso {course_id}")
            
            return Response(serializer.validated_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request, clase_id):
        """Eliminar una clase específica"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"🗑️ [DELETE] /api/horarios/clases/{clase_id}/")
            
            return Response(
                {"message": "Funcionalidad en desarrollo"},
                status=status.HTTP_501_NOT_IMPLEMENTED
            )
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================
# HEALTH CHECK
# ============================================
class DebugCursosView(APIView):
    """
    GET /api/debug/cursos/
    Endpoint de prueba para ver todos los cursos y sus subcolecciones
    """
    def get(self, request):
        try:
            logger.info("🐛 [DEBUG] Verificando estructura de cursos")
            
            courses_ref = db.collection("courses")
            all_courses = courses_ref.stream()
            
            cursos_info = []
            
            for course in all_courses:
                course_id = course.id
                course_data = course.to_dict()
                
                # Verificar si tiene subcolección assistances
                assistances_ref = db.collection("courses").document(course_id).collection("assistances")
                assistances_count = len(list(assistances_ref.stream()))
                
                curso_info = {
                    "id": course_id,
                    "nameCourse": course_data.get("nameCourse", "Sin nombre"),
                    "profesorID": course_data.get("profesorID", "N/A"),
                    "tiene_assistances": assistances_count > 0,
                    "num_assistances": assistances_count
                }
                
                cursos_info.append(curso_info)
                
                logger.info(f"📚 Curso: {curso_info['nameCourse']} - Assistances: {assistances_count}")
            
            return Response({
                "total_cursos": len(cursos_info),
                "cursos": cursos_info
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DebugAsistenciasPublicView(APIView):
    """
    GET /api/debug/asistencias/
    Endpoint PÚBLICO temporal para verificar que se obtienen TODAS las asistencias
    ⚠️ QUITAR EN PRODUCCIÓN
    """
    def get(self, request):
        try:
            logger.info("=" * 60)
            logger.info("🐛 [DEBUG PUBLIC] Obtener TODAS las asistencias SIN autenticación")
            
            asistencias_list = []
            
            # Obtener todos los cursos
            courses_ref = db.collection("courses")
            all_courses = courses_ref.stream()
            
            cursos_procesados = 0
            
            for course in all_courses:
                course_id = course.id
                course_data = course.to_dict()
                course_name = course_data.get('nameCourse', 'Sin nombre')
                
                logger.info(f"   📚 Procesando curso: {course_name} (ID: {course_id})")
                cursos_procesados += 1
                
                # Obtener la subcolección 'assistances' del curso
                assistances_ref = db.collection("courses").document(course_id).collection("assistances")
                assistances = assistances_ref.stream()
                
                asistencias_curso = 0
                
                for assistance_doc in assistances:
                    fecha_id = assistance_doc.id
                    assistance_data = assistance_doc.to_dict()
                    
                    for cedula, estudiante_data in assistance_data.items():
                        if isinstance(estudiante_data, dict):
                            asistencias_curso += 1
                            
                            asistencia = {
                                'id': f"{course_id}_{fecha_id}_{cedula}",
                                'estudiante': cedula,
                                'asignatura': course_name,
                                'fechaYhora': fecha_id,
                                'estadoAsistencia': estudiante_data.get('estadoAsistencia', 'Presente'),
                                'horaRegistro': estudiante_data.get('horaRegistro', ''),
                                'late': estudiante_data.get('late', False),
                                'courseId': course_id,
                                'fechaDocId': fecha_id
                            }
                            asistencias_list.append(asistencia)
                
                logger.info(f"      ✅ {asistencias_curso} asistencias encontradas en este curso")
            
            logger.info(f"✅ [SUCCESS] Total cursos procesados: {cursos_procesados}")
            logger.info(f"✅ [SUCCESS] Total asistencias encontradas: {len(asistencias_list)}")
            logger.info("=" * 60)
            
            return Response({
                "total": len(asistencias_list),
                "asistencias": asistencias_list
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ [ERROR] Error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response(
                {"error": "Error al obtener asistencias", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class HealthCheck(APIView):
    """GET /api/health/ - Verificar estado del servidor"""
    
    def get(self, request):
        logger.info("💚 [HEALTH CHECK] Servidor funcionando")
        
        try:
            # Verificar conexión a Firebase
            docs_count = len(list(db.collection("courses").limit(1).stream()))
            firebase_status = "✅ Conectado"
        except Exception as e:
            firebase_status = f"❌ Error: {str(e)}"
        
        return Response({
            "status": "OK",
            "timestamp": datetime.now().isoformat(),
            "firebase": firebase_status,
            "endpoints": {
                "asistencias": {
                    "list": "/api/asistencias/",
                    "create": "/api/asistencias/crear/",
                    "detail": "/api/asistencias/<id>/",
                    "update": "/api/asistencias/<id>/update/",
                    "delete": "/api/asistencias/<id>/delete/"
                },
                "horarios": {
                    "get_profesor": "/api/horarios/",
                    "update_profesor": "/api/horarios/",
                    "delete_profesor": "/api/horarios/",
                    "get_curso": "/api/horarios/cursos/<course_id>/",
                    "update_curso": "/api/horarios/cursos/<course_id>/",
                    "add_clase": "/api/horarios/clases/",
                    "delete_clase": "/api/horarios/clases/<clase_id>/"
                },
                "debug": {
                    "cursos": "/api/debug/cursos/"
                }
            }
        }, status=status.HTTP_200_OK)