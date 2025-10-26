# ESTA ES LA BUENA
# src/api_app/views.py - SIN VERIFICACIÓN DE TOKEN, CON FILTRADO POR UID
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
# FUNCIÓN PARA EXTRAER UID (SIN VERIFICAR TOKEN)
# ============================================
def obtener_uid_usuario(request):
    """
    Extrae el UID del usuario desde los headers personalizados
    NO verifica token, solo extrae el UID
    
    Returns:
        tuple: (uid, error_response)
            - Si todo OK: (uid_string, None)
            - Si error: (None, Response_con_error)
    """
    try:
        uid = request.headers.get('X-User-UID')
        
        if not uid:
            logger.warning("⚠️ No se encontró UID en headers")
            return None, Response(
                {"Error": "No se encontró el UID del usuario."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Guardar info del usuario en request (simulando estructura de Firebase)
        request.user_firebase = {
            'uid': uid,
            'email': request.headers.get('X-User-Email', 'N/A'),
            'name': request.headers.get('X-User-Name', 'Usuario')
        }
        
        logger.info(f"✅ UID recibido: {uid}")
        return uid, None
        
    except Exception as e:
        logger.error(f"❌ Error al extraer UID: {str(e)}")
        return None, Response(
            {"Error": "Error al procesar usuario"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================
# FUNCIÓN AUXILIAR PARA BUSCAR PERSONA POR UID
# ============================================
def buscar_persona_por_uid(uid):
    """
    Busca un documento en la colección 'person' donde el campo 'profesorUID' 
    coincida con el UID proporcionado.
    
    Args:
        uid (str): UID del usuario de Firebase Auth
        
    Returns:
        dict | None: Datos del documento si se encuentra, None si no existe
    """
    try:
        logger.info(f"🔍 Buscando persona con UID: {uid}")
        
        # Query a la colección 'person' buscando por el campo 'profesorUID'
        persons_ref = db.collection('person')
        query = persons_ref.where(filter=firestore.FieldFilter('profesorUID', '==', uid)).limit(1)
        docs = list(query.stream())
        
        if not docs:
            logger.warning(f"⚠️ No se encontró documento en 'person' para UID: {uid}")
            return None
        
        # Obtener el primer (y único) documento
        person_doc = docs[0]
        person_data = person_doc.to_dict()
        person_data['id'] = person_doc.id  # Agregar el ID del documento
        
        logger.info(f"✅ Persona encontrada: {person_data.get('namePerson', 'Sin nombre')} (DocID: {person_doc.id})")
        logger.info(f"📚 Cursos en person: {person_data.get('courses', [])}")
        
        return person_data
        
    except Exception as e:
        logger.error(f"❌ Error al buscar persona por UID: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def buscar_nombre_estudiante(cedula):
    """
    Busca el nombre de un estudiante por su cédula en la colección 'person'.

    Args:
        cedula (str): Cédula del estudiante
        
    Returns:
        str: Nombre del estudiante o texto genérico si no se encuentra
    """
    try:
        doc_ref = db.collection('person').document(str(cedula))
        doc = doc_ref.get()

        if doc.exists:
            person_data = doc.to_dict()
            nombre = person_data.get('namePerson', f"Estudiante {cedula}")
            print(f"✅ Nombre encontrado para {cedula}: {nombre}")
            return nombre
        else:
            print(f"⚠️ No se encontró documento para cédula: {cedula}")
            return f"Estudiante {cedula}"

    except Exception as e:
        print(f"❌ Error al buscar nombre de estudiante: {str(e)}")
        return f"Estudiante {cedula}"


# ============================================
# FUNCIÓN PARA OBTENER CURSOS DEL PROFESOR
# ============================================
def obtener_cursos_profesor(person_data, user_uid):
    """
    Obtiene los cursos de un profesor buscando en:
    1. person->courses (array con IDs de cursos)
    2. courses->profesorID (coincide con UID)
    3. courses->groups->profesorID (coincide con UID)
    
    Args:
        person_data: Datos del documento person
        user_uid: UID del usuario
        
    Returns:
        list: Lista de cursos encontrados
    """
    cursos = []
    course_ids_found = set()  # Para evitar duplicados
    
    try:
        # ============================================
        # MÉTODO 1: Obtener cursos desde person->courses
        # ============================================
        courses_array = person_data.get('courses', [])
        logger.info(f"📋 Método 1: Buscando {len(courses_array)} cursos desde person->courses")
        
        for course_id in courses_array:
            try:
                course_ref = db.collection("courses").document(course_id)
                course_doc = course_ref.get()
                
                if course_doc.exists:
                    curso_data = course_doc.to_dict()
                    curso_data['id'] = course_doc.id
                    
                    # Verificar que no sea duplicado
                    if course_doc.id not in course_ids_found:
                        cursos.append(curso_data)
                        course_ids_found.add(course_doc.id)
                        logger.info(f"   ✅ Curso encontrado: {curso_data.get('nameCourse')} (ID: {course_doc.id})")
                else:
                    logger.warning(f"   ⚠️ Curso {course_id} no existe en Firestore")
                    
            except Exception as e:
                logger.error(f"   ❌ Error al obtener curso {course_id}: {str(e)}")
        
        # ============================================
        # MÉTODO 2: Buscar en courses donde profesorID == user_uid
        # ============================================
        logger.info(f"📋 Método 2: Buscando cursos donde profesorID == {user_uid}")
        
        courses_ref = db.collection("courses")
        query = courses_ref.where(filter=firestore.FieldFilter('profesorID', '==', user_uid))
        docs = query.stream()
        
        for doc in docs:
            if doc.id not in course_ids_found:
                curso_data = doc.to_dict()
                curso_data['id'] = doc.id
                cursos.append(curso_data)
                course_ids_found.add(doc.id)
                logger.info(f"   ✅ Curso encontrado: {curso_data.get('nameCourse')} (ID: {doc.id})")
        
        # ============================================
        # MÉTODO 3: Buscar en courses->groups donde profesorID == user_uid
        # ============================================
        logger.info(f"📋 Método 3: Buscando en groups donde profesorID == {user_uid}")
        
        all_courses = db.collection("courses").stream()
        
        for course_doc in all_courses:
            course_id = course_doc.id
            
            # Ya lo tenemos? Saltar
            if course_id in course_ids_found:
                continue
            
            # Buscar en subcolección groups
            groups_ref = db.collection("courses").document(course_id).collection("groups")
            group_query = groups_ref.where(filter=firestore.FieldFilter('profesorID', '==', user_uid))
            group_docs = list(group_query.stream())
            
            if group_docs:
                # Encontramos al menos un grupo con este profesor
                curso_data = course_doc.to_dict()
                curso_data['id'] = course_id
                cursos.append(curso_data)
                course_ids_found.add(course_id)
                logger.info(f"   ✅ Curso encontrado en groups: {curso_data.get('nameCourse')} (ID: {course_id})")
        
        logger.info(f"📊 Total de cursos encontrados: {len(cursos)}")
        
    except Exception as e:
        logger.error(f"❌ Error al obtener cursos del profesor: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    return cursos


# ============================================
# FUNCIÓN PARA OBTENER CURSOS DEL ESTUDIANTE
# ============================================
def obtener_cursos_estudiante(person_data, user_uid):
    """
    Obtiene los cursos de un estudiante buscando en:
    1. person->courses (array con IDs de cursos)
    2. courses->estudianteID (array que contiene el UID)
    
    Args:
        person_data: Datos del documento person
        user_uid: UID del usuario
        
    Returns:
        list: Lista de cursos encontrados
    """
    cursos = []
    course_ids_found = set()
    
    try:
        # ============================================
        # MÉTODO 1: Obtener cursos desde person->courses
        # ============================================
        courses_array = person_data.get('courses', [])
        logger.info(f"📋 Método 1: Buscando {len(courses_array)} cursos desde person->courses")
        
        for course_id in courses_array:
            try:
                course_ref = db.collection("courses").document(course_id)
                course_doc = course_ref.get()
                
                if course_doc.exists:
                    curso_data = course_doc.to_dict()
                    curso_data['id'] = course_doc.id
                    
                    if course_doc.id not in course_ids_found:
                        cursos.append(curso_data)
                        course_ids_found.add(course_doc.id)
                        logger.info(f"   ✅ Curso encontrado: {curso_data.get('nameCourse')} (ID: {course_doc.id})")
                else:
                    logger.warning(f"   ⚠️ Curso {course_id} no existe en Firestore")
                    
            except Exception as e:
                logger.error(f"   ❌ Error al obtener curso {course_id}: {str(e)}")
        
        # ============================================
        # MÉTODO 2: Buscar en courses donde estudianteID contiene user_uid
        # ============================================
        logger.info(f"📋 Método 2: Buscando cursos donde estudianteID contiene {user_uid}")
        
        courses_ref = db.collection("courses")
        query = courses_ref.where(filter=firestore.FieldFilter('estudianteID', 'array_contains', user_uid))
        docs = query.stream()
        
        for doc in docs:
            if doc.id not in course_ids_found:
                curso_data = doc.to_dict()
                curso_data['id'] = doc.id
                cursos.append(curso_data)
                course_ids_found.add(doc.id)
                logger.info(f"   ✅ Curso encontrado: {curso_data.get('nameCourse')} (ID: {doc.id})")
        
        logger.info(f"📊 Total de cursos encontrados: {len(cursos)}")
        
    except Exception as e:
        logger.error(f"❌ Error al obtener cursos del estudiante: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    return cursos


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
                            'estudiante': buscar_nombre_estudiante(cedula),
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
                        'estudiante': buscar_nombre_estudiante(cedula),
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
# ASISTENCIAS - MODIFICADO PARA FILTRAR POR PROFESOR
# ============================================

class AsistenciaList(APIView):
    """
    GET /api/asistencias/
    Lista las asistencias filtradas según el usuario:
    - Profesor: Solo asistencias de SUS cursos
    - Estudiante: Solo asistencias de SUS cursos
    """
    def get(self, request):
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("=" * 60)
            logger.info("📥 [GET] /api/asistencias/ - Obtener asistencias filtradas")
            
            user_email = request.user_firebase.get('email', 'N/A')
            logger.info(f"👤 Usuario UID: {user_uid}")
            logger.info(f"📧 Email: {user_email}")
            
            # Buscar información del usuario en la colección 'person'
            person_data = buscar_persona_por_uid(user_uid)
            
            if not person_data:
                logger.warning(f"⚠️ Usuario {user_uid} no encontrado en 'person'")
                return Response({
                    "message": "Usuario no registrado en el sistema",
                    "asistencias": []
                }, status=status.HTTP_200_OK)
            
            user_type = person_data.get('type', '')
            user_name = person_data.get('namePerson', 'Usuario')
            logger.info(f"✅ Usuario encontrado: {user_name} - Tipo: {user_type}")
            
            # ============================================
            # OBTENER CURSOS SEGÚN EL TIPO DE USUARIO
            # ============================================
            if user_type == 'Profesor':
                logger.info(f"👨‍🏫 Obteniendo cursos del profesor {user_name}")
                cursos_usuario = obtener_cursos_profesor(person_data, user_uid)
            elif user_type == 'Estudiante':
                logger.info(f"👨‍🎓 Obteniendo cursos del estudiante {user_name}")
                cursos_usuario = obtener_cursos_estudiante(person_data, user_uid)
            else:
                logger.warning(f"⚠️ Tipo de usuario no reconocido: {user_type}")
                return Response({
                    "error": f"Tipo de usuario no válido: {user_type}",
                    "asistencias": []
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # ============================================
            # OBTENER ASISTENCIAS DE LOS CURSOS
            # ============================================
            asistencias_list = []
            
            for curso in cursos_usuario:
                course_id = curso['id']
                course_name = curso.get('nameCourse', 'Sin nombre')
                
                logger.info(f"📚 Procesando curso: {course_name} (ID: {course_id})")
                
                # Usar función auxiliar para obtener asistencias
                asistencias_curso = obtener_asistencias_curso(course_id, curso, course_name)
                asistencias_list.extend(asistencias_curso)
            
            logger.info(f"✅ [SUCCESS] Total cursos del usuario: {len(cursos_usuario)}")
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
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

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
            course_query = courses_ref.where(filter=firestore.FieldFilter("nameCourse", "==", asignatura)).limit(1).stream()
            
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
    """
    def get(self, request, pk):
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            parts = pk.split('_')
            
            # Determinar si tiene grupos según el número de partes
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
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            parts = pk.split('_')
            
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
            
            estudiante_data = assistance_data[cedula]
            
            if 'estadoAsistencia' in request.data:
                estudiante_data['estadoAsistencia'] = request.data['estadoAsistencia']
            
            assistance_ref.update({
                cedula: estudiante_data
            })
            
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
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            parts = pk.split('_')
            
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
# HORARIOS - MODIFICADO PARA USAR UID SIN TOKEN
# ============================================

class HorarioProfesorView(APIView):
    """
    GET /api/horarios/
    Obtiene todos los cursos del profesor o estudiante autenticado
    """
    
    def get(self, request):
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("=" * 60)
            logger.info("📅 [GET] /api/horarios/ - Obtener horario del usuario")
            
            logger.info(f"👤 Usuario UID: {user_uid}")
            
            person_data = buscar_persona_por_uid(user_uid)
            
            if not person_data:
                return Response({
                    "error": f"No se encontró usuario en 'person' con UID: {user_uid}",
                    "profesorEmail": request.user_firebase.get('email'),
                    "profesorNombre": request.user_firebase.get('name', ''),
                    "clases": [],
                    "message": "Usuario no registrado en el sistema"
                }, status=status.HTTP_404_NOT_FOUND)
            
            user_type = person_data.get('type', '')
            user_name = person_data.get('namePerson', 'Usuario')
            logger.info(f"👤 Tipo de usuario: {user_type}")
            
            # ============================================
            # OBTENER CURSOS SEGÚN EL TIPO DE USUARIO
            # ============================================
            if user_type == 'Profesor':
                logger.info(f"👨‍🏫 Obteniendo cursos del profesor {user_name}")
                cursos = obtener_cursos_profesor(person_data, user_uid)
            elif user_type == 'Estudiante':
                logger.info(f"👨‍🎓 Obteniendo cursos del estudiante {user_name}")
                cursos = obtener_cursos_estudiante(person_data, user_uid)
            else:
                logger.warning(f"⚠️ Tipo de usuario no reconocido: {user_type}")
                return Response({
                    "error": f"Tipo de usuario no válido: {user_type}",
                    "clases": []
                }, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"✅ Total cursos del usuario: {len(cursos)}")
            logger.info("=" * 60)
            
            return Response({
                "profesorEmail": request.user_firebase.get('email'),
                "profesorNombre": person_data.get('namePerson', request.user_firebase.get('name', '')),
                "clases": cursos,
                "userType": user_type
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error al obtener horario: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return Response(
                {"error": "Error al obtener horario", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Crear o actualizar horario del profesor"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("=" * 60)
            logger.info("📅 [POST] /api/horarios/ - Crear/Actualizar horario")
            
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
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("🗑️ [DELETE] /api/horarios/ - Eliminar horario completo")
            
            courses_ref = db.collection("courses")
            query = courses_ref.where(filter=firestore.FieldFilter('profesorID', '==', user_uid))
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
    GET /api/horarios/cursos/<course_id>/
    Obtiene los detalles de un curso específico
    
    PUT /api/horarios/cursos/<course_id>/
    Actualiza el horario (schedule) de un curso específico
    """
    
    def get(self, request, course_id):
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

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
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

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
            
            curso_actual = doc.to_dict()
            profesor_id = curso_actual.get('profesorID')
            
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
            
            doc_ref.update({"schedule": schedule})
            
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
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

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
    POST /api/horarios/clases/
    Agrega una clase al horario de un curso
    
    PUT /api/horarios/clases/
    Actualiza una clase específica
    
    DELETE /api/horarios/clases/
    Elimina una clase específica del horario
    """
    
    def post(self, request):
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

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
            profesor_id = curso_data.get('profesorID')
            
            new_class = serializer.validated_data
            hay_conflicto, mensaje = validar_conflicto_horario(profesor_id, new_class)
            if hay_conflicto:
                return Response(
                    {"error": mensaje},
                    status=status.HTTP_409_CONFLICT
                )
            
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
    
    def put(self, request):
        """Actualizar una clase específica"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("✏️ [PUT] /api/horarios/clases/ - Actualizar clase")
            
            course_id = request.data.get('courseId')
            class_index = request.data.get('classIndex')
            
            if course_id is None or class_index is None:
                return Response(
                    {"error": "courseId y classIndex son requeridos"},
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
            
            if class_index < 0 or class_index >= len(schedule):
                return Response(
                    {"error": "Índice de clase inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            schedule[class_index] = serializer.validated_data
            doc_ref.update({"schedule": schedule})
            
            logger.info(f"✅ Clase actualizada en curso {course_id}")
            
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request):
        """Eliminar una clase específica"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("🗑️ [DELETE] /api/horarios/clases/ - Eliminar clase")
            
            course_id = request.data.get('courseId')
            class_index = request.data.get('classIndex')
            
            if course_id is None or class_index is None:
                return Response(
                    {"error": "courseId y classIndex son requeridos"},
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
            
            if class_index < 0 or class_index >= len(schedule):
                return Response(
                    {"error": "Índice de clase inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            deleted_class = schedule.pop(class_index)
            doc_ref.update({"schedule": schedule})
            
            logger.info(f"✅ Clase eliminada del curso {course_id}")
            
            return Response({
                "success": True,
                "message": "Clase eliminada correctamente",
                "deleted_class": deleted_class
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
            docs_count = len(list(db.collection("courses").limit(1).stream()))
            firebase_status = "✅ Conectado"
        except Exception as e:
            firebase_status = f"❌ Error: {str(e)}"
        
        return Response({
            "status": "OK",
            "timestamp": datetime.now().isoformat(),
            "firebase": firebase_status,
            "authentication": "UID-based (no token verification)",
            "endpoints": {
                "asistencias": {
                    "list": "GET /api/asistencias/",
                    "create": "POST /api/asistencias/crear/",
                    "detail": "GET /api/asistencias/<id>/",
                    "update": "PUT /api/asistencias/<id>/update/",
                    "delete": "DELETE /api/asistencias/<id>/delete/"
                },
                "horarios": {
                    "get_profesor": "/api/horarios/",
                    "update_profesor": "/api/horarios/",
                    "delete_profesor": "/api/horarios/",
                    "get_curso": "/api/horarios/cursos/<course_id>/",
                    "update_curso": "/api/horarios/cursos/<course_id>/",
                    "add_clase": "/api/horarios/clases/",
                    "update_clase": "/api/horarios/clases/ (PUT)",
                    "delete_clase": "/api/horarios/clases/ (DELETE)"
                }
            }
        }, status=status.HTTP_200_OK)