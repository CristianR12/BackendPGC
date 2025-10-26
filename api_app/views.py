# src/api_app/views.py - BACKEND COMPLETO MEJORADO
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from firebase_admin import firestore, auth as firebase_auth
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
from datetime import datetime, time
from .permissions import verificar_token

# Configurar logger
logger = logging.getLogger(__name__)
db = firestore.client()

# ----- FUNCIONES AUXILIARES -----
def validar_conflicto_horario(profesor_id, new_class, exclude_course_id=None, exclude_class_index=None):
    """
    Valida si hay conflicto de horario para el profesor
    
    Args:
        profesor_id: UID del profesor
        new_class: Dict con {day, iniTime, endTime}
        exclude_course_id: ID del curso a excluir (para ediciones)
        exclude_class_index: Índice de la clase a excluir
    
    Returns:
        Tuple (bool, str) - (hay_conflicto, mensaje_error)
    """
    try:
        # Obtener todos los cursos del profesor
        courses_ref = db.collection("courses")
        query = courses_ref.where("profesorID", "==", profesor_id)
        docs = query.stream()
        
        new_day = new_class.get('day')
        new_ini = new_class.get('iniTime')
        new_fin = new_class.get('endTime')
        
        # Convertir tiempos a minutos para comparación
        new_ini_min = int(new_ini.split(':')[0]) * 60 + int(new_ini.split(':')[1])
        new_fin_min = int(new_fin.split(':')[0]) * 60 + int(new_fin.split(':')[1])
        
        for doc in docs:
            curso_id = doc.id
            
            # Saltar el curso excluido (para ediciones)
            if exclude_course_id and curso_id == exclude_course_id:
                continue
            
            curso_data = doc.to_dict()
            schedule = curso_data.get('schedule', [])
            
            for idx, clase in enumerate(schedule):
                # Saltar la clase excluida (para ediciones)
                if exclude_course_id == curso_id and exclude_class_index == idx:
                    continue
                
                # Solo verificar si es el mismo día
                if clase.get('day') != new_day:
                    continue
                
                clase_ini = clase.get('iniTime')
                clase_fin = clase.get('endTime')
                
                clase_ini_min = int(clase_ini.split(':')[0]) * 60 + int(clase_ini.split(':')[1])
                clase_fin_min = int(clase_fin.split(':')[0]) * 60 + int(clase_fin.split(':')[1])
                
                # Verificar solapamiento
                # Hay conflicto si: new_ini < clase_fin AND new_fin > clase_ini
                if new_ini_min < clase_fin_min and new_fin_min > clase_ini_min:
                    return True, f"Conflicto de horario: ya tiene clase de {clase_ini} a {clase_fin} el {new_day}"
        
        return False, None
        
    except Exception as e:
        logger.error(f"❌ Error al validar conflicto: {str(e)}")
        return False, str(e)


def handle_firestore_error(e):
    """Manejo centralizado de errores Firestore"""
    if isinstance(e, PermissionDenied):
        return Response(
            {"error": "Acceso denegado a Firestore"},
            status=status.HTTP_403_FORBIDDEN
        )
    elif isinstance(e, NotFound):
        return Response(
            {"error": "Documento no encontrado"},
            status=status.HTTP_404_NOT_FOUND
        )
    elif isinstance(e, FirebaseError):
        return Response(
            {"error": "Error interno del servicio Firebase"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    else:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================
# ASISTENCIAS (Código existente mejorado)
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
    """POST /api/asistencias/crear/ - Crear nueva asistencia"""
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
    """GET /api/asistencias/<id>/ - Obtener asistencia por ID"""
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
    """PUT /api/asistencias/<id>/update/ - Actualizar asistencia"""
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
    """DELETE /api/asistencias/<id>/delete/ - Eliminar asistencia"""
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
# HORARIOS - ENDPOINTS COMPLETOS Y MEJORADOS
# ============================================

class HorarioProfesorView(APIView):
    """
    GET /api/horarios/ - Obtener cursos del profesor
    POST /api/horarios/ - Crear/Actualizar horarios
    DELETE /api/horarios/ - Eliminar horarios
    """
    
    def get(self, request):
        """Obtener todos los cursos del profesor autenticado"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("=" * 60)
            logger.info("📅 [GET] /api/horarios/ - Obtener horario del profesor")
            
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
                    
                    # Validar conflictos en el schedule
                    schedule = curso_data.get('schedule', [])
                    for idx, clase_item in enumerate(schedule):
                        hay_conflicto, mensaje = validar_conflicto_horario(
                            user_uid,
                            clase_item,
                            exclude_course_id=clase.get('id')
                        )
                        if hay_conflicto:
                            return Response(
                                {"error": mensaje},
                                status=status.HTTP_409_CONFLICT
                            )
                    
                    # Si tiene ID, actualizar; si no, crear nuevo
                    if 'id' in clase and clase['id']:
                        doc_ref = db.collection("courses").document(clase['id'])
                        doc_ref.update(curso_data)
                        curso_data['id'] = clase['id']
                        logger.info(f"✏️ Curso actualizado: {clase['id']}")
                    else:
                        doc_ref = db.collection("courses").add(curso_data)
                        curso_data['id'] = doc_ref[1].id
                        logger.info(f"✅ Curso creado: {curso_data['id']}")
                    
                    cursos_guardados.append(curso_data)
                else:
                    logger.warning(f"⚠️ Datos inválidos: {serializer.errors}")
                    return Response(
                        {"error": "Datos inválidos", "details": serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
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
                logger.info(f"   🗑️ Curso eliminado: {doc.id}")
            
            logger.info(f"✅ Eliminados {deleted_count} cursos")
            
            return Response({
                "success": True,
                "message": f"Horario eliminado ({deleted_count} cursos)",
                "deletedCount": deleted_count
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HorarioCursoView(APIView):
    """
    GET /api/horarios/cursos/<course_id>/ - Obtener curso específico
    PUT /api/horarios/cursos/<course_id>/ - Actualizar schedule del curso
    DELETE /api/horarios/cursos/<course_id>/ - Eliminar curso
    """
    
    def get(self, request, course_id):
        """Obtener detalles de un curso"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"📖 [GET] /api/horarios/cursos/{course_id}/")
            
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
        """Actualizar el horario (schedule) de un curso"""
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
            
            # Obtener profesor para validar conflictos
            curso_actual = doc.to_dict()
            profesor_id = curso_actual.get('profesorID')
            
            # Validar conflictos en el nuevo schedule
            schedule = serializer.validated_data['schedule']
            for idx, clase in enumerate(schedule):
                hay_conflicto, mensaje = validar_conflicto_horario(
                    profesor_id,
                    clase,
                    exclude_course_id=course_id,
                    exclude_class_index=idx
                )
                if hay_conflicto:
                    return Response(
                        {"error": mensaje},
                        status=status.HTTP_409_CONFLICT
                    )
            
            # Actualizar schedule
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
    
    def delete(self, request, course_id):
        """Eliminar un curso completo"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"🗑️ [DELETE] /api/horarios/cursos/{course_id}/ - Eliminar curso")
            
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            doc_ref.delete()
            logger.info(f"✅ Curso eliminado: {course_id}")
            
            return Response({
                "success": True,
                "message": "Curso eliminado correctamente",
                "courseId": course_id
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HorarioClaseView(APIView):
    """
    POST /api/horarios/clases/ - Agregar clase a un curso
    PUT /api/horarios/clases/<clase_id>/ - Actualizar una clase
    DELETE /api/horarios/clases/<clase_id>/ - Eliminar una clase
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
            
            curso_data = doc.to_dict()
            profesor_id = curso_data.get('profesorID')
            
            # Validar conflicto
            new_class = serializer.validated_data
            hay_conflicto, mensaje = validar_conflicto_horario(profesor_id, new_class)
            if hay_conflicto:
                return Response(
                    {"error": mensaje},
                    status=status.HTTP_409_CONFLICT
                )
            
            # Agregar nueva clase al schedule
            schedule = curso_data.get('schedule', [])
            schedule.append(new_class)
            
            doc_ref.update({"schedule": schedule})
            
            logger.info(f"✅ Clase agregada al curso {course_id}")
            
            return Response({
                **new_class,
                "index": len(schedule) - 1
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def put(self, request, clase_id):
        """Actualizar una clase específica"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"✏️ [PUT] /api/horarios/clases/{clase_id}/ - Actualizar clase")
            
            course_id = request.data.get('courseId')
            class_index = request.data.get('classIndex')
            
            if not course_id or class_index is None:
                return Response(
                    {"error": "courseId y classIndex son requeridos"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar datos
            serializer = ScheduleClassSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": "Datos inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener curso
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            schedule = curso_data.get('schedule', [])
            
            if class_index >= len(schedule):
                return Response(
                    {"error": "Índice de clase fuera de rango"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            profesor_id = curso_data.get('profesorID')
            
            # Validar conflicto (excluyendo esta clase)
            new_class = serializer.validated_data
            hay_conflicto, mensaje = validar_conflicto_horario(
                profesor_id,
                new_class,
                exclude_course_id=course_id,
                exclude_class_index=class_index
            )
            if hay_conflicto:
                return Response(
                    {"error": mensaje},
                    status=status.HTTP_409_CONFLICT
                )
            
            # Actualizar clase
            schedule[class_index] = new_class
            doc_ref.update({"schedule": schedule})
            
            logger.info(f"✅ Clase actualizada en curso {course_id}")
            
            return Response(new_class, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request, clase_id):
        """Eliminar una clase específica"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"🗑️ [DELETE] /api/horarios/clases/{clase_id}/ - Eliminar clase")
            
            course_id = request.data.get('courseId')
            class_index = request.data.get('classIndex')
            
            if not course_id or class_index is None:
                return Response(
                    {"error": "courseId y classIndex son requeridos"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener curso
            doc_ref = db.collection("courses").document(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            schedule = curso_data.get('schedule', [])
            
            if class_index >= len(schedule):
                return Response(
                    {"error": "Índice de clase fuera de rango"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Eliminar clase del schedule
            deleted_class = schedule.pop(class_index)
            doc_ref.update({"schedule": schedule})
            
            logger.info(f"✅ Clase eliminada del curso {course_id}")
            
            return Response({
                "success": True,
                "message": "Clase eliminada correctamente",
                "deletedClass": deleted_class,
                "courseId": course_id
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ObtenerEstudiantesView(APIView):
    """
    GET /api/horarios/cursos/<course_id>/estudiantes/
    Obtiene la lista de estudiantes de un curso
    """
    
    def get(self, request, course_id):
        """Obtener estudiantes de un curso"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info(f"👥 [GET] /api/horarios/cursos/{course_id}/estudiantes/")
            
            doc = db.collection("courses").document(course_id).get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            estudiante_ids = curso_data.get('estudianteID', [])
            
            # Obtener datos de los estudiantes
            estudiantes = []
            for est_id in estudiante_ids:
                try:
                    person_doc = db.collection("person").document(est_id).get()
                    if person_doc.exists:
                        est_data = person_doc.to_dict()
                        est_data['uid'] = est_id
                        estudiantes.append(est_data)
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo obtener datos del estudiante {est_id}: {str(e)}")
            
            logger.info(f"✅ Devolviendo {len(estudiantes)} estudiantes")
            
            return Response({
                "courseId": course_id,
                "courseName": curso_data.get('nameCourse'),
                "estudiantes": estudiantes,
                "totalEstudiantes": len(estudiantes)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConflictosHorarioView(APIView):
    """
    POST /api/horarios/validar-conflictos/
    Valida conflictos de horario sin guardar
    """
    
    def post(self, request):
        """Validar conflictos de horario"""
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("⚠️ [POST] /api/horarios/validar-conflictos/")
            
            profesor_id = request.data.get('profesorId')
            new_class = request.data.get('clase')
            exclude_course_id = request.data.get('excludeCourseId')
            exclude_class_index = request.data.get('excludeClassIndex')
            
            if not profesor_id or not new_class:
                return Response(
                    {"error": "profesorId y clase son requeridos"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar estructura de la clase
            serializer = ScheduleClassSerializer(data=new_class)
            if not serializer.is_valid():
                return Response(
                    {"error": "Datos de clase inválidos", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validar conflicto
            hay_conflicto, mensaje = validar_conflicto_horario(
                profesor_id,
                serializer.validated_data,
                exclude_course_id=exclude_course_id,
                exclude_class_index=exclude_class_index
            )
            
            return Response({
                "hasConflict": hay_conflicto,
                "message": mensaje,
                "clase": serializer.validated_data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
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
                    "list": "GET /api/asistencias/",
                    "create": "POST /api/asistencias/crear/",
                    "detail": "GET /api/asistencias/<id>/",
                    "update": "PUT /api/asistencias/<id>/update/",
                    "delete": "DELETE /api/asistencias/<id>/delete/"
                },
                "horarios": {
                    "get_profesor": "GET /api/horarios/",
                    "create_horario": "POST /api/horarios/",
                    "delete_horario": "DELETE /api/horarios/",
                    "get_curso": "GET /api/horarios/cursos/<course_id>/",
                    "update_curso": "PUT /api/horarios/cursos/<course_id>/",
                    "delete_curso": "DELETE /api/horarios/cursos/<course_id>/",
                    "add_clase": "POST /api/horarios/clases/",
                    "update_clase": "PUT /api/horarios/clases/<clase_id>/",
                    "delete_clase": "DELETE /api/horarios/clases/<clase_id>/",
                    "get_estudiantes": "GET /api/horarios/cursos/<course_id>/estudiantes/",
                    "validar_conflictos": "POST /api/horarios/validar-conflictos/"
                }
            }
        }, status=status.HTTP_200_OK)