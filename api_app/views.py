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
# FUNCIONES AUXILIARES PARA MANEJAR AMBAS ESTRUCTURAS
# ============================================

def obtener_asistencias_curso(course_id, course_data, course_name):
    """
    Obtiene asistencias de un curso, manejando ambas estructuras:
    1. courses/{courseId}/assistances/{fecha}
    2. courses/{courseId}/groups/{groupId}/assistances/{fecha}
    
    Returns:
        list: Lista de asistencias encontradas
    """
    asistencias_list = []
    
    # ✅ CASO 1: Verificar si tiene subcolección 'groups'
    groups_ref = db.collection("courses").document(course_id).collection("groups")
    groups = list(groups_ref.stream())
    
    if groups:
        # Tiene grupos - buscar en courses/{courseId}/groups/{groupId}/assistances/{fecha}
        logger.info(f"   📁 Curso con GRUPOS detectado: {course_name}")
        
        for group_doc in groups:
            group_id = group_doc.id
            group_data = group_doc.to_dict()
            group_name = group_data.get('group', group_id)
            
            logger.info(f"      📂 Procesando grupo: {group_name} (ID: {group_id})")
            
            # Obtener asistencias del grupo
            assistances_ref = db.collection("courses").document(course_id).collection("groups").document(group_id).collection("assistances")
            assistances = assistances_ref.stream()
            
            asistencias_grupo = 0
            
            for assistance_doc in assistances:
                fecha_id = assistance_doc.id
                assistance_data = assistance_doc.to_dict()
                
                # Cada documento tiene cédulas como campos
                for cedula, estudiante_data in assistance_data.items():
                    if isinstance(estudiante_data, dict):
                        asistencias_grupo += 1
                        
                        # Crear objeto de asistencia con información del grupo
                        asistencia = {
                            'id': f"{course_id}_{group_id}_{fecha_id}_{cedula}",
                            'estudiante': cedula,
                            'asignatura': f"{course_name} - Grupo {group_name}",
                            'fechaYhora': fecha_id,
                            'estadoAsistencia': estudiante_data.get('estadoAsistencia', 'Presente'),
                            'horaRegistro': estudiante_data.get('horaRegistro', ''),
                            'late': estudiante_data.get('late', False),
                            'courseId': course_id,
                            'groupId': group_id,
                            'fechaDocId': fecha_id,
                            'hasGroups': True  # Flag para identificar estructura
                        }
                        asistencias_list.append(asistencia)
            
            logger.info(f"         ✅ {asistencias_grupo} asistencias en grupo {group_name}")
    
    else:
        # ✅ CASO 2: No tiene grupos - estructura simple
        logger.info(f"   📚 Curso SIN grupos: {course_name}")
        
        # Obtener asistencias directamente
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
                        'fechaDocId': fecha_id,
                        'hasGroups': False
                    }
                    asistencias_list.append(asistencia)
        
        logger.info(f"      ✅ {asistencias_curso} asistencias encontradas")
    
    return asistencias_list


# ============================================
# ASISTENCIAS - MODIFICADO PARA AMBAS ESTRUCTURAS
# ============================================

class AsistenciaList(APIView):
    """
    GET /api/asistencias/
    Lista TODAS las asistencias de TODOS los cursos
    Maneja ambas estructuras:
    - courses/{courseId}/assistances/{fecha}
    - courses/{courseId}/groups/{groupId}/assistances/{fecha}
    """
    def get(self, request):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            logger.info("=" * 60)
            logger.info("📥 [GET] /api/asistencias/ - Obtener TODAS las asistencias")
            
            asistencias_list = []
            
            # Obtener todos los cursos
            courses_ref = db.collection("courses")
            all_courses = courses_ref.stream()
            
            cursos_procesados = 0
            
            for course in all_courses:
                course_id = course.id
                course_data = course.to_dict()
                course_name = course_data.get('nameCourse', 'Sin nombre')
                
                logger.info(f"📚 Procesando curso: {course_name} (ID: {course_id})")
                cursos_procesados += 1
                
                # Usar función auxiliar para obtener asistencias
                asistencias_curso = obtener_asistencias_curso(course_id, course_data, course_name)
                asistencias_list.extend(asistencias_curso)
            
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
    Crea una nueva asistencia en la subcolección correcta del curso
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
            group_id = request.data.get('groupId')  # Opcional
            
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
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            hora_actual = datetime.now().strftime("%H:%M:%S")
            
            # Datos del estudiante
            estudiante_data = {
                'estadoAsistencia': estado_asistencia,
                'horaRegistro': hora_actual,
                'late': False
            }
            
            # ✅ Determinar la ruta correcta según si tiene grupos
            if group_id:
                # Ruta con grupos
                assistance_ref = (db.collection("courses")
                                 .document(course_id)
                                 .collection("groups")
                                 .document(group_id)
                                 .collection("assistances")
                                 .document(fecha_hoy))
                logger.info(f"📁 Guardando en curso con grupos: {course_id}/groups/{group_id}")
            else:
                # Ruta simple
                assistance_ref = (db.collection("courses")
                                 .document(course_id)
                                 .collection("assistances")
                                 .document(fecha_hoy))
                logger.info(f"📚 Guardando en curso sin grupos: {course_id}")
            
            # Actualizar o crear el documento
            assistance_ref.set({
                estudiante_cedula: estudiante_data
            }, merge=True)
            
            logger.info(f"✅ Asistencia creada: {estudiante_cedula} en {asignatura}")
            
            response_id = f"{course_id}_{group_id}_{fecha_hoy}_{estudiante_cedula}" if group_id else f"{course_id}_{fecha_hoy}_{estudiante_cedula}"
            
            return Response(
                {
                    "id": response_id,
                    "estudiante": estudiante_cedula,
                    "estadoAsistencia": estado_asistencia,
                    "asignatura": asignatura,
                    "fechaYhora": fecha_hoy,
                    "horaRegistro": hora_actual,
                    "late": False,
                    "groupId": group_id if group_id else None
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
    ID puede ser:
    - courseId_fechaId_cedula (sin grupos)
    - courseId_groupId_fechaId_cedula (con grupos)
    """
    def get(self, request, pk):
        token_error = verificar_token(request)
        if token_error:
            return token_error

        try:
            parts = pk.split('_')
            
            # Determinar si tiene grupos según el número de partes
            if len(parts) == 4:
                # Con grupos: courseId_groupId_fechaId_cedula
                course_id = parts[0]
                group_id = parts[1]
                fecha_id = parts[2]
                cedula = parts[3]
                has_groups = True
            elif len(parts) == 3:
                # Sin grupos: courseId_fechaId_cedula
                course_id = parts[0]
                fecha_id = parts[1]
                cedula = parts[2]
                group_id = None
                has_groups = False
            else:
                return Response(
                    {"error": "ID de asistencia inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Obtener documento según la estructura
            if has_groups:
                assistance_ref = (db.collection("courses")
                                .document(course_id)
                                .collection("groups")
                                .document(group_id)
                                .collection("assistances")
                                .document(fecha_id))
            else:
                assistance_ref = (db.collection("courses")
                                .document(course_id)
                                .collection("assistances")
                                .document(fecha_id))
            
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
                'groupId': group_id if has_groups else None,
                'fechaDocId': fecha_id,
                'hasGroups': has_groups
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
            parts = pk.split('_')
            
            # Determinar estructura
            if len(parts) == 4:
                course_id, group_id, fecha_id, cedula = parts
                has_groups = True
            elif len(parts) == 3:
                course_id, fecha_id, cedula = parts
                group_id = None
                has_groups = False
            else:
                return Response(
                    {"error": "ID de asistencia inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Referencia al documento
            if has_groups:
                assistance_ref = (db.collection("courses")
                                .document(course_id)
                                .collection("groups")
                                .document(group_id)
                                .collection("assistances")
                                .document(fecha_id))
            else:
                assistance_ref = (db.collection("courses")
                                .document(course_id)
                                .collection("assistances")
                                .document(fecha_id))
            
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
            
            # Actualizar datos
            estudiante_data = assistance_data[cedula]
            
            if 'estadoAsistencia' in request.data:
                estudiante_data['estadoAsistencia'] = request.data['estadoAsistencia']
            
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
                'late': estudiante_data.get('late', False),
                'groupId': group_id if has_groups else None
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
            parts = pk.split('_')
            
            # Determinar estructura
            if len(parts) == 4:
                course_id, group_id, fecha_id, cedula = parts
                has_groups = True
            elif len(parts) == 3:
                course_id, fecha_id, cedula = parts
                group_id = None
                has_groups = False
            else:
                return Response(
                    {"error": "ID de asistencia inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Referencia al documento
            if has_groups:
                assistance_ref = (db.collection("courses")
                                .document(course_id)
                                .collection("groups")
                                .document(group_id)
                                .collection("assistances")
                                .document(fecha_id))
            else:
                assistance_ref = (db.collection("courses")
                                .document(course_id)
                                .collection("assistances")
                                .document(fecha_id))
            
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
# HORARIOS - ENDPOINTS EXISTENTES (sin cambios)
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
            
            user_uid = request.user_firebase.get('uid')
            logger.info(f"👤 Profesor UID: {user_uid}")
            
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
            
            if len(cursos) == 0:
                return Response({
                    "profesorEmail": request.user_firebase.get('email'),
                    "profesorNombre": request.user_firebase.get('name', ''),
                    "clases": [],
                    "message": "No hay cursos asignados"
                }, status=status.HTTP_200_OK)
            
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
# HEALTH CHECK Y DEBUG
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
                
                # Verificar estructura simple (assistances directas)
                assistances_ref = db.collection("courses").document(course_id).collection("assistances")
                assistances_count = len(list(assistances_ref.stream()))
                
                # Verificar estructura con grupos
                groups_ref = db.collection("courses").document(course_id).collection("groups")
                groups = list(groups_ref.stream())
                
                groups_info = []
                total_assistances_groups = 0
                
                if groups:
                    for group_doc in groups:
                        group_id = group_doc.id
                        group_data = group_doc.to_dict()
                        
                        # Contar asistencias del grupo
                        group_assistances_ref = (db.collection("courses")
                                                .document(course_id)
                                                .collection("groups")
                                                .document(group_id)
                                                .collection("assistances"))
                        group_assistances_count = len(list(group_assistances_ref.stream()))
                        total_assistances_groups += group_assistances_count
                        
                        groups_info.append({
                            "groupId": group_id,
                            "groupName": group_data.get('group', group_id),
                            "assistances": group_assistances_count
                        })
                
                curso_info = {
                    "id": course_id,
                    "nameCourse": course_data.get("nameCourse", "Sin nombre"),
                    "profesorID": course_data.get("profesorID", "N/A"),
                    "estructura": "CON_GRUPOS" if groups else "SIMPLE",
                    "assistances_directas": assistances_count,
                    "grupos": groups_info,
                    "total_assistances_grupos": total_assistances_groups
                }
                
                cursos_info.append(curso_info)
                
                logger.info(f"📚 Curso: {curso_info['nameCourse']} - Estructura: {curso_info['estructura']}")
            
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
                
                logger.info(f"📚 Procesando curso: {course_name} (ID: {course_id})")
                cursos_procesados += 1
                
                # Usar función auxiliar
                asistencias_curso = obtener_asistencias_curso(course_id, course_data, course_name)
                asistencias_list.extend(asistencias_curso)
            
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


class TestTokenView(APIView):
    """
    GET /api/test-token/
    Endpoint de prueba para verificar el token de Firebase
    ⚠️ TEMPORAL - Solo para debugging
    """
    def get(self, request):
        try:
            logger.info("🔐 [TEST TOKEN] Verificando token")
            
            # Obtener header de autorización
            auth_header = request.headers.get('Authorization')
            logger.info(f"📋 Authorization Header: {auth_header[:50] if auth_header else 'NO ENCONTRADO'}...")
            
            if not auth_header:
                return Response({
                    "error": "No authorization header",
                    "headers_received": list(request.headers.keys())
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Verificar formato
            parts = auth_header.split(' ')
            logger.info(f"📋 Parts: {len(parts)}")
            
            if len(parts) != 2 or parts[0] != 'Bearer':
                return Response({
                    "error": "Invalid format",
                    "expected": "Bearer <token>",
                    "received": auth_header[:50]
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            id_token = parts[1]
            logger.info(f"📋 Token length: {len(id_token)}")
            logger.info(f"📋 Token first 20 chars: {id_token[:20]}")
            
            # Intentar verificar con Firebase Admin
            from firebase_admin import auth as firebase_auth
            
            try:
                decoded_token = firebase_auth.verify_id_token(id_token, check_revoked=True)
                logger.info(f"✅ Token válido!")
                logger.info(f"👤 User: {decoded_token.get('email')}")
                logger.info(f"👤 UID: {decoded_token.get('uid')}")
                
                return Response({
                    "success": True,
                    "message": "Token válido",
                    "user": {
                        "email": decoded_token.get('email'),
                        "uid": decoded_token.get('uid'),
                        "name": decoded_token.get('name', 'N/A')
                    },
                    "token_info": {
                        "iss": decoded_token.get('iss'),
                        "aud": decoded_token.get('aud'),
                        "exp": decoded_token.get('exp'),
                        "iat": decoded_token.get('iat')
                    }
                }, status=status.HTTP_200_OK)
                
            except firebase_auth.InvalidIdTokenError as e:
                logger.error(f"❌ Token inválido: {str(e)}")
                return Response({
                    "error": "Invalid token",
                    "detail": str(e),
                    "type": "InvalidIdTokenError"
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            except firebase_auth.ExpiredIdTokenError as e:
                logger.error(f"❌ Token expirado: {str(e)}")
                return Response({
                    "error": "Token expired",
                    "detail": str(e),
                    "type": "ExpiredIdTokenError"
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            except firebase_auth.RevokedIdTokenError as e:
                logger.error(f"❌ Token revocado: {str(e)}")
                return Response({
                    "error": "Token revoked",
                    "detail": str(e),
                    "type": "RevokedIdTokenError"
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            except Exception as e:
                logger.error(f"❌ Error verificando token: {str(e)}")
                logger.error(f"Tipo: {type(e).__name__}")
                import traceback
                logger.error(traceback.format_exc())
                return Response({
                    "error": "Verification error",
                    "detail": str(e),
                    "type": type(e).__name__
                }, status=status.HTTP_401_UNAUTHORIZED)
                
        except Exception as e:
            logger.error(f"❌ Error general: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({
                "error": "Server error",
                "detail": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
                "test": {
                    "test_token": "/api/test-token/"
                },
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
                    "cursos": "/api/debug/cursos/",
                    "asistencias_public": "/api/debug/asistencias/"
                }
            }
        }, status=status.HTTP_200_OK)