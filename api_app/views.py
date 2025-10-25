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
# ASISTENCIAS (Código existente)
# ============================================

class AsistenciaList(APIView):
    """
    GET /api/asistencias/
    Lista todas las asistencias registradas
    """
    def get(self, request):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("=" * 60)
            logger.info("📥 [GET] /api/asistencias/ - Petición recibida")
            
            docs = db.collection("asistenciaReconocimiento").stream()
            data = []
            
            for doc in docs:
                doc_data = doc.to_dict()
                doc_data['id'] = doc.id
                data.append(doc_data)
            
            logger.info(f"✅ [SUCCESS] Devolviendo {len(data)} asistencias")
            logger.info("=" * 60)
            
            return Response(data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ [ERROR] Error en AsistenciaList: {str(e)}")
            return Response(
                {"error": "Error al obtener asistencias", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AsistenciaCreate(APIView):
    def post(self, request):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("📥 [POST] /api/asistencias/crear/")
            serializer = AsistenciaSerializer(data=request.data)
            
            if serializer.is_valid():
                validated_data = serializer.validated_data
                if 'fechaYhora' not in validated_data or not validated_data['fechaYhora']:
                    validated_data['fechaYhora'] = datetime.now().isoformat()
                
                doc_ref = db.collection("asistenciaReconocimiento").add(validated_data)
                doc_id = doc_ref[1].id
                
                logger.info(f"✅ Asistencia creada: {doc_id}")
                
                return Response(
                    {"id": doc_id, **validated_data},
                    status=status.HTTP_201_CREATED
                )
            else:
                return Response(
                    {"error": "Datos inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaRetrieve(APIView):
    def get(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            doc = db.collection("asistenciaReconocimiento").document(pk).get()
            
            if not doc.exists:
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            data = doc.to_dict()
            data['id'] = doc.id
            return Response(data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaUpdate(APIView):
    def put(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            doc_ref = db.collection("asistenciaReconocimiento").document(pk)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            update_data = {}
            if 'estudiante' in request.data:
                update_data['estudiante'] = request.data['estudiante']
            if 'estadoAsistencia' in request.data:
                update_data['estadoAsistencia'] = request.data['estadoAsistencia']
            if 'asignatura' in request.data:
                update_data['asignatura'] = request.data['asignatura']
            
            doc_ref.update(update_data)
            
            updated_doc = doc_ref.get()
            updated_data = updated_doc.to_dict()
            updated_data['id'] = pk
            
            return Response(updated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaDelete(APIView):
    def delete(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            doc_ref = db.collection("asistenciaReconocimiento").document(pk)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            doc_ref.delete()
            
            return Response(
                {'success': True, 'message': 'Asistencia eliminada', 'id': pk},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================
# HORARIOS - NUEVOS ENDPOINTS
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
            # El frontend espera un array de cursos con schedule
            return Response({
                "profesorEmail": request.user_firebase.get('email'),
                "profesorNombre": request.user_firebase.get('name', ''),
                "clases": cursos  # Devuelve los cursos completos
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
            
            # El frontend envía un objeto con 'clases' que es un array
            clases = request.data.get('clases', [])
            
            if not clases:
                return Response(
                    {"error": "No se proporcionaron clases"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Guardar cada curso (esto asume que vienen cursos completos)
            # Si el frontend envía solo clases individuales, ajustar lógica
            cursos_guardados = []
            
            for clase in clases:
                serializer = CourseSerializer(data=clase)
                if serializer.is_valid():
                    curso_data = serializer.validated_data
                    curso_data['profesorID'] = user_uid
                    
                    # Si tiene ID, actualizar; si no, crear nuevo
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
            
            # Buscar todos los cursos del profesor
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
            
            # Verificar que el curso existe
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Validar datos
            serializer = UpdateScheduleSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": "Datos inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Actualizar solo el schedule
            schedule = serializer.validated_data['schedule']
            doc_ref.update({"schedule": schedule})
            
            # Obtener documento actualizado
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
            
            # Validar datos de la clase
            serializer = ScheduleClassSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": "Datos inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener curso actual
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Agregar nueva clase al schedule
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
            # Nota: Esta implementación asume que clase_id es un identificador
            # único dentro del schedule. Ajustar según tu lógica.
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
class HealthCheck(APIView):
    """GET /api/health/ - Verificar estado del servidor"""
    
    def get(self, request):
        logger.info("💚 [HEALTH CHECK] Servidor funcionando")
        
        try:
            # Verificar conexión a Firebase
            docs_count = len(list(db.collection("asistenciaReconocimiento").limit(1).stream()))
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
                }
            }
        }, status=status.HTTP_200_OK)