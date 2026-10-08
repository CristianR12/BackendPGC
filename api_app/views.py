# ESTA ES LA BUENA
# src/api_app/views.py - SIN VERIFICACIÓN DE TOKEN, CON FILTRADO POR UID
from rest_framework.views import APIView
from datetime import datetime, time, timezone, timedelta
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
from google.api_core.exceptions import PermissionDenied, NotFound, AlreadyExists
from django.conf import settings
import logging
import unicodedata
import copy
import re
from .horario_unidades import id_unidad, separar_id_unidad
from .horario_import import normalizar_texto
from .registro import (
    decidir_registro, preparar_aprobacion, validar_docente, normalizar_email,
)
from .estudiantes_import import (
    planificar_inscripcion, validar_curso, normalizar_cedula, MAX_FILAS as MAX_FILAS_ESTUDIANTES,
)
from .horario_import import planificar, MODOS, MAX_FILAS
from . import asistencia_pagina as pagina_asist
from . import estadisticas as estad
from . import legal
from .estudiante_cuenta import (
    decidir_vinculo, validar_perfil_estudiante, diferencias, perfil_publico,
)
from .horario_historial import (
    resumen_curso, calcular_cambios, construir_entrada, aplicar_plan_a_cursos,
    normalizar_periodo, periodo_actual, periodo_de_respaldo,
)
from django.utils import timezone as django_timezone

# Configurar logger
logger = logging.getLogger(__name__)
db = firestore.client()
def obtener_fecha_colombia():
    zona_colombia = timezone(timedelta(hours=-5))
    ahora_colombia = datetime.now(zona_colombia)
    fecha_str = ahora_colombia.strftime("%Y-%m-%d")
    hora_str = ahora_colombia.strftime("%H:%M:%S")
    return fecha_str, hora_str

# ----- FUNCIONES AUXILIARES -----
def es_profesor(person_data):
    """True si el documento 'person' corresponde a un profesor."""
    return bool(person_data) and person_data.get('type') == 'Profesor'


def ref_unidad(unidad_id):
    """Referencia al documento de una unidad de horario: un curso, o un subgrupo ('cursoId::grupoId')."""
    curso_id, grupo_id = separar_id_unidad(unidad_id)
    ref = db.collection("courses").document(curso_id)
    return ref.collection("groups").document(grupo_id) if grupo_id else ref


def _ids_del_profesor(uid, person_data):
    # En los subgrupos, profesorID suele ser el id del documento 'person' y no el UID de inicio de sesión
    return {x for x in (uid, (person_data or {}).get('id')) if x}


def usuario_puede_editar_curso(uid, course_id, curso_data, person_data=None):
    """
    Un horario solo lo puede modificar su profesor. Para un curso: su profesorID es el usuario, o el usuario
    es profesor y el curso está en su lista person->courses, o tiene un subgrupo del curso a su nombre.
    Para un subgrupo ('cursoId::grupoId'): el profesorID del subgrupo es el usuario.
    Un estudiante (o cualquier otra cuenta) nunca puede.
    """
    curso_id, grupo_id = separar_id_unidad(course_id)
    if not grupo_id and (curso_data or {}).get('profesorID') == uid:
        return True
    if person_data is None:
        person_data = buscar_persona_por_uid(uid)
    if not es_profesor(person_data):
        return False
    ids = _ids_del_profesor(uid, person_data)
    if grupo_id:
        return (curso_data or {}).get('profesorID') in ids
    if (curso_data or {}).get('profesorID') in ids or curso_id in (person_data.get('courses') or []):
        return True
    try:
        for g in db.collection("courses").document(curso_id).collection("groups").stream():
            if (g.to_dict() or {}).get('profesorID') in ids:
                return True
    except Exception as e:
        logger.error(f"Error al verificar subgrupos del curso {curso_id}: {e}")
    return False


def listar_unidades_horario(uid, person_data):
    """
    Todas las unidades de horario del profesor: cursos propios y subgrupos propios, cada una
    como {id, courseId, groupId, nameCourse, group, profesorID, estudianteID, schedule}.
    """
    ids = _ids_del_profesor(uid, person_data)
    de_la_persona = set((person_data or {}).get('courses') or [])
    unidades = []
    for d in db.collection("courses").stream():
        c = d.to_dict() or {}
        grupos = list(d.reference.collection("groups").stream())
        propios = [g for g in grupos if (g.to_dict() or {}).get('profesorID') in ids]
        es_dueno = c.get('profesorID') in ids or d.id in de_la_persona
        # Un curso que solo funciona por subgrupos no aporta una unidad propia (su horario está en los grupos)
        if es_dueno and (c.get('group') or c.get('schedule') or not grupos):
            unidades.append({
                'id': d.id, 'courseId': d.id, 'groupId': None,
                'nameCourse': c.get('nameCourse'), 'group': c.get('group'),
                'profesorID': c.get('profesorID'), 'estudianteID': c.get('estudianteID') or [],
                'schedule': list(c.get('schedule') or []),
            })
        for g in propios:
            gd = g.to_dict() or {}
            unidades.append({
                'id': id_unidad(d.id, g.id), 'courseId': d.id, 'groupId': g.id,
                'nameCourse': c.get('nameCourse'), 'group': gd.get('group', g.id),
                'profesorID': gd.get('profesorID'), 'estudianteID': gd.get('estudianteID') or [],
                'schedule': list(gd.get('schedule') or []),
            })
    return unidades


def resumen_unidad(unidad_id, data):
    """resumen_curso con nombre y grupo, aunque 'data' sea de un subgrupo (no trae el nombre del curso)."""
    curso_id, grupo_id = separar_id_unidad(unidad_id)
    data = dict(data or {})
    if grupo_id:
        padre = db.collection("courses").document(curso_id).get()
        data['nameCourse'] = (padre.to_dict() or {}).get('nameCourse') if padre.exists else None
        data['group'] = data.get('group', grupo_id)
    return resumen_curso(unidad_id, data)


def respuesta_sin_permiso():
    return Response(
        {"error": "No tienes permiso para modificar este curso."},
        status=status.HTTP_403_FORBIDDEN
    )


def es_docente_de(user_uid, course_id, group_id, person=None):
    """¿Es el docente dueño de ese curso (o subgrupo)? Un estudiante o una cuenta sin perfil, nunca."""
    person = person if person is not None else buscar_persona_por_uid(user_uid)
    if not es_profesor(person):
        return False
    unidad = id_unidad(course_id, group_id) if group_id else course_id
    doc = ref_unidad(unidad).get()
    return doc.exists and usuario_puede_editar_curso(user_uid, unidad, doc.to_dict() or {}, person)


def puede_ver_asistencia(user_uid, course_id, group_id, cedula):
    """El docente dueño del curso, o el propio estudiante (solo su registro)."""
    person = buscar_persona_por_uid(user_uid)
    if person and person.get('type') == 'Estudiante':
        return person.get('id') == str(cedula)
    return es_docente_de(user_uid, course_id, group_id, person)


def respuesta_asistencia_sin_permiso():
    return Response({"error": "No tienes permiso sobre las asistencias de este curso."}, status=status.HTTP_403_FORBIDDEN)


def snapshot_horario_profesor(uid, person_data):
    """Foto de todos los horarios del profesor (cursos y subgrupos) en forma resumida."""
    return [resumen_curso(u['id'], u) for u in listar_unidades_horario(uid, person_data)]


def registrar_historial(uid, tipo, cambios, periodo=None, detalle=None, person_data=None):
    """
    Deja constancia de un cambio de horario en `horarioHistorial`. Si falla, se registra el error
    pero la operación principal ya hecha NO se revierte ni se rompe.
    """
    try:
        if not cambios and tipo != 'foto_manual':
            return
        if person_data is None:
            person_data = buscar_persona_por_uid(uid)
        entrada = construir_entrada(uid, tipo, periodo, cambios, snapshot_horario_profesor(uid, person_data), detalle)
        db.collection("horarioHistorial").add(entrada)
    except Exception as e:
        logger.error(f"No se pudo registrar el historial ({tipo}): {e}")


def validar_conflicto_horario(profesor_id, new_class, exclude_course_id=None, exclude_class_index=None, unidades=None):
    """
    Valida si hay conflicto de horario para el profesor, sobre todas sus unidades (cursos y subgrupos).

    Args:
        profesor_id: UID del profesor
        new_class: Dict con {day, iniTime, endTime}
        exclude_course_id: id de la unidad a excluir (para ediciones)
        unidades: unidades ya calculadas (evita volver a leer Firestore dentro de un bucle)

    Returns:
        Tuple (bool, str) - (hay_conflicto, mensaje_error)
    """
    try:
        if unidades is None:
            unidades = listar_unidades_horario(profesor_id, buscar_persona_por_uid(profesor_id))

        new_day = new_class.get('day')
        new_ini = new_class.get('iniTime')
        new_fin = new_class.get('endTime')

        # Convertir tiempos a minutos para comparación
        new_ini_min = int(new_ini.split(':')[0]) * 60 + int(new_ini.split(':')[1])
        new_fin_min = int(new_fin.split(':')[0]) * 60 + int(new_fin.split(':')[1])

        for unidad in unidades:
            # Saltar la unidad excluida (para ediciones)
            if exclude_course_id and unidad['id'] == exclude_course_id:
                continue

            for clase in (unidad.get('schedule') or []):
                # Solo verificar si es el mismo día
                if clase.get('day') != new_day:
                    continue

                clase_ini = clase.get('iniTime')
                clase_fin = clase.get('endTime')

                clase_ini_min = int(clase_ini.split(':')[0]) * 60 + int(clase_ini.split(':')[1])
                clase_fin_min = int(clase_fin.split(':')[0]) * 60 + int(clase_fin.split(':')[1])

                # Hay conflicto si: new_ini < clase_fin AND new_fin > clase_ini
                if new_ini_min < clase_fin_min and new_fin_min > clase_ini_min:
                    return True, f"Conflicto de horario: ya tiene clase de {clase_ini} a {clase_fin} el {new_day}"

        return False, None

    except Exception as e:
        logger.error(f"Error al validar conflicto: {str(e)}")
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
# FUNCIÓN PARA VERIFICAR EL ID TOKEN Y EXTRAER EL UID
# ============================================
def obtener_uid_usuario(request):
    """
    Verifica el ID token de Firebase enviado en el header Authorization
    y extrae el UID del token ya verificado (no del header, que puede
    ser falsificado por el cliente).

    Returns:
        tuple: (uid, error_response)
            - Si todo OK: (uid_string, None)
            - Si error: (None, Response_con_error)
    """
    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith('Bearer '):
        logger.warning("No se encontró token Bearer en el header Authorization")
        return None, Response(
            {"Error": "No se encontró el token de autenticación."},
            status=status.HTTP_401_UNAUTHORIZED
        )

    id_token = auth_header.split('Bearer ', 1)[1].strip()

    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
    except FirebaseError as e:
        logger.warning(f"Token inválido o expirado: {str(e)}")
        return None, Response(
            {"Error": "Token de autenticación inválido o expirado."},
            status=status.HTTP_401_UNAUTHORIZED
        )
    except Exception as e:
        logger.error(f"Error al verificar token: {str(e)}")
        return None, Response(
            {"Error": "Error al procesar usuario"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    uid = decoded_token['uid']

    # Guardar info del usuario verificada (nunca desde headers del cliente)
    request.user_firebase = {
        'uid': uid,
        'email': decoded_token.get('email', 'N/A'),
        'name': decoded_token.get('name', 'Usuario'),
        # Con Google siempre es True; con contraseña solo después de confirmar el correo
        'email_verified': bool(decoded_token.get('email_verified', False)),
    }

    logger.info(f"Token verificado para UID: {uid}")
    return uid, None


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
        logger.info(f"Buscando persona con UID: {uid}")
        
        # Query a la colección 'person' buscando por el campo 'profesorUID'
        persons_ref = db.collection('person')
        query = persons_ref.where(filter=firestore.FieldFilter('profesorUID', '==', uid)).limit(1)
        docs = list(query.stream())
        if not docs:  # los estudiantes guardan su cuenta en estudianteUID
            query = persons_ref.where(filter=firestore.FieldFilter('estudianteUID', '==', uid)).limit(1)
            docs = list(query.stream())

        if not docs:
            logger.warning(f"No se encontró documento en 'person' para UID: {uid}")
            return None
        
        # Obtener el primer (y único) documento
        person_doc = docs[0]
        person_data = person_doc.to_dict()
        person_data['id'] = person_doc.id  # Agregar el ID del documento
        
        logger.info(f"Persona encontrada: {person_data.get('namePerson', 'Sin nombre')} (DocID: {person_doc.id})")
        logger.info(f"Cursos en person: {person_data.get('courses', [])}")
        
        return person_data
        
    except Exception as e:
        logger.error(f"Error al buscar persona por UID: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def buscar_nombre_estudiante(cedula, buscar_en_db=False):
    """
    Busca el nombre de un estudiante por su cédula en la colección 'person'.
    OPTIMIZADO: Solo busca en DB si se solicita explícitamente

    Args:
        cedula (str): Cédula del estudiante
        buscar_en_db (bool): Si False, retorna solo la cédula sin buscar
        
    Returns:
        str: Nombre del estudiante, cédula, o texto genérico si no se encuentra
    """
    # Si no se solicita búsqueda, retornar solo la cédula
    if not buscar_en_db:
        return str(cedula)
    
    try:
        doc_ref = db.collection('person').document(str(cedula))
        doc = doc_ref.get()

        if doc.exists:
            person_data = doc.to_dict()
            nombre = person_data.get('namePerson', f"Estudiante {cedula}")
            logger.info(f"Nombre encontrado para {cedula}: {nombre}")
            return nombre
        else:
            logger.warning(f"No se encontró documento para cédula: {cedula}")
            return f"Estudiante {cedula}"

    except Exception as e:
        logger.error(f"Error al buscar nombre de estudiante: {str(e)}")
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
        logger.info(f"Método 1: Buscando {len(courses_array)} cursos desde person->courses")
        
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
                        logger.info(f"   Curso encontrado: {curso_data.get('nameCourse')} (ID: {course_doc.id})")
                else:
                    logger.warning(f"   Curso {course_id} no existe en Firestore")
                    
            except Exception as e:
                logger.error(f"   Error al obtener curso {course_id}: {str(e)}")
        
        # ============================================
        # MÉTODO 2: Buscar en courses donde profesorID == user_uid
        # ============================================
        logger.info(f"Método 2: Buscando cursos donde profesorID == {user_uid}")
        
        courses_ref = db.collection("courses")
        query = courses_ref.where(filter=firestore.FieldFilter('profesorID', '==', user_uid))
        docs = query.stream()
        
        for doc in docs:
            if doc.id not in course_ids_found:
                curso_data = doc.to_dict()
                curso_data['id'] = doc.id
                cursos.append(curso_data)
                course_ids_found.add(doc.id)
                logger.info(f"   Curso encontrado: {curso_data.get('nameCourse')} (ID: {doc.id})")
        
        # ============================================
        # MÉTODO 3: Buscar en courses->groups donde profesorID == user_uid
        # ============================================
        logger.info(f"Método 3: Buscando en groups donde profesorID == {user_uid}")
        
        all_courses = db.collection("courses").stream()
        
        for course_doc in all_courses:
            course_id = course_doc.id
            
            # Ya lo tenemos? Saltar
            if course_id in course_ids_found:
                continue
            
            # Buscar en subcolección groups
            groups_ref = db.collection("courses").document(course_id).collection("groups")
            group_query = groups_ref.where(filter=firestore.FieldFilter('profesorID', 'in', sorted(_ids_del_profesor(user_uid, person_data))))
            group_docs = list(group_query.stream())
            
            if group_docs:
                # Encontramos al menos un grupo con este profesor
                curso_data = course_doc.to_dict()
                curso_data['id'] = course_id
                cursos.append(curso_data)
                course_ids_found.add(course_id)
                logger.info(f"   Curso encontrado en groups: {curso_data.get('nameCourse')} (ID: {course_id})")
        
        logger.info(f"Total de cursos encontrados: {len(cursos)}")
        
    except Exception as e:
        logger.error(f"Error al obtener cursos del profesor: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    return cursos


# ============================================
# FUNCIÓN PARA OBTENER CURSOS DEL ESTUDIANTE
# ============================================
def unidades_de_estudiante(cedula):
    """
    Cursos y subgrupos en los que la cédula está inscrita, con la misma forma que listar_unidades_horario
    pero SIN datos de otras personas: estudianteID solo trae la cédula propia y no se envía el profesor.
    """
    unidades = []
    for d in db.collection("courses").stream():
        c = d.to_dict() or {}
        grupos = list(d.reference.collection("groups").stream())
        if cedula in (c.get('estudianteID') or []) and (c.get('group') or c.get('schedule') or not grupos):
            unidades.append({
                'id': d.id, 'courseId': d.id, 'groupId': None,
                'nameCourse': c.get('nameCourse'), 'group': c.get('group'),
                'profesorID': None, 'estudianteID': [cedula],
                'schedule': list(c.get('schedule') or []),
            })
        for g in grupos:
            gd = g.to_dict() or {}
            if cedula in (gd.get('estudianteID') or []):
                unidades.append({
                    'id': id_unidad(d.id, g.id), 'courseId': d.id, 'groupId': g.id,
                    'nameCourse': c.get('nameCourse'), 'group': gd.get('group', g.id),
                    'profesorID': None, 'estudianteID': [cedula],
                    'schedule': list(gd.get('schedule') or []),
                })
    return unidades


def obtener_cursos_estudiante(person_data, user_uid):
    """
    Cursos (documentos completos, con 'id') donde está inscrito el estudiante, ya sea en el curso o en alguno
    de sus subgrupos. La inscripción se busca por la cédula (id del documento person), no por el UID.
    """
    cedula = (person_data or {}).get('id')
    if not cedula:
        return []
    ids = []
    for u in unidades_de_estudiante(cedula):
        if u['courseId'] not in ids:
            ids.append(u['courseId'])
    cursos = []
    for cid in ids:
        doc = db.collection("courses").document(cid).get()
        if doc.exists:
            cursos.append({**(doc.to_dict() or {}), 'id': cid})
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
    
    # CASO 1: Verificar si tiene subcolección 'groups'
    groups_ref = db.collection("courses").document(course_id).collection("groups")
    groups = list(groups_ref.stream())
    
    if groups:
        # Tiene grupos - buscar en courses/{courseId}/groups/{groupId}/assistances/{fecha}
        logger.info(f"   Curso con GRUPOS detectado: {course_name}")
        
        for group_doc in groups:
            group_id = group_doc.id
            group_data = group_doc.to_dict()
            group_name = group_data.get('group', group_id)
            
            logger.info(f"      Procesando grupo: {group_name} (ID: {group_id})")
            
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
                            'estudiante': str(cedula),  # Solo cédula
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
            
            logger.info(f"         {asistencias_grupo} asistencias en grupo {group_name}")
    
    else:
        # CASO 2: No tiene grupos - estructura simple
        logger.info(f"   Curso SIN grupos: {course_name}")
        
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
                        'estudiante': str(cedula),  # Solo cédula
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
        
        logger.info(f"      {asistencias_curso} asistencias encontradas")
    
    return asistencias_list


# --- Vista Inicio (U1/U2): misma ventana temporal que TrialREC/recFacial verificar_horario_salon, sin salón ---
DIAS_INGLES_A_ESPANOL_VISTA = {
    "Monday": "Lunes",
    "Tuesday": "Martes",
    "Wednesday": "Miércoles",
    "Thursday": "Jueves",
    "Friday": "Viernes",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}

# Mapa manual opcional: etiqueta normalizada (alias) → etiqueta normalizada canónica (como en asistencias)
MANUAL_ASIGNATURA_ALIAS_A_ETIQUETA_CANONICA = {}


def _normalizar_etiqueta_asignatura(s):
    if s is None:
        return ""
    t = " ".join(str(s).strip().split())
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower()


def _resolver_curso_y_grupo_por_etiqueta(cursos_usuario, etiqueta_raw):
    """
    Devuelve (curso_dict, group_id|None) autorizado para el usuario, o (None, None).
    Etiquetas posibles: nameCourse o f"{nameCourse} - Grupo {nombreGrupo}" como en obtener_asistencias_curso.
    """
    key = _normalizar_etiqueta_asignatura(etiqueta_raw)
    key = MANUAL_ASIGNATURA_ALIAS_A_ETIQUETA_CANONICA.get(key, key)

    for curso in cursos_usuario:
        course_id = curso.get("id")
        name = curso.get("nameCourse") or ""
        if _normalizar_etiqueta_asignatura(name) != key:
            continue
        if not course_id:
            return curso, None
        try:
            groups_ref = db.collection("courses").document(course_id).collection("groups")
            if list(groups_ref.limit(1).stream()):
                continue
        except Exception as e:
            logger.warning(f"Error comprobando grupos de {course_id}: {e}")
        return curso, None

    for curso in cursos_usuario:
        course_id = curso.get("id")
        if not course_id:
            continue
        name = curso.get("nameCourse") or ""
        try:
            groups_ref = db.collection("courses").document(course_id).collection("groups")
            for gdoc in groups_ref.stream():
                group_id = gdoc.id
                group_data = gdoc.to_dict() or {}
                group_name = group_data.get("group", group_id)
                label = f"{name} - Grupo {group_name}"
                if _normalizar_etiqueta_asignatura(label) == key:
                    return curso, group_id
        except Exception as e:
            logger.warning(f"Error listando grupos de {course_id}: {e}")

    return None, None


def _schedule_curso_o_grupo(course_id, curso_dict, group_id):
    if group_id:
        gref = db.collection("courses").document(course_id).collection("groups").document(group_id)
        gdoc = gref.get()
        if gdoc.exists:
            return (gdoc.to_dict() or {}).get("schedule", []) or []
    return curso_dict.get("schedule", []) or []


def _ventana_trialec_sin_salon(schedule, dia_espanol, dia_ingles, hora_actual_str):
    """True si la hora actual cae en [iniTime-5, iniTime+30] para alguna franja del día (sin filtrar por salón)."""
    if not schedule:
        return False
    for horario in schedule:
        dia_horario = horario.get("day", "")
        if dia_horario != dia_espanol and dia_horario != dia_ingles:
            continue
        hora_inicio_str = horario.get("iniTime", "00:00")
        try:
            hora_inicio = datetime.strptime(hora_inicio_str, "%H:%M")
            hora_actual = datetime.strptime(hora_actual_str, "%H:%M")
        except ValueError:
            continue
        ventana_inicio = hora_inicio - timedelta(minutes=5)
        ventana_fin = hora_inicio + timedelta(minutes=30)
        if ventana_inicio <= hora_actual <= ventana_fin:
            return True
    return False


def _max_fecha_doc_ids(fechas):
    """Última sesión: fechaDocId es id del doc en assistances (convención YYYY-MM-DD)."""
    valid = [f for f in fechas if f]
    if not valid:
        return None
    return max(valid)


class AsistenciaVistaInicio(APIView):
    """
    GET /api/asistencias/vista-inicio/?asignatura=...
    Listado filtrado para Inicio (U1 clase en ventana → sesión de hoy; U2 → última sesión por fechaDocId).
    Misma autorización y cursos que GET /api/asistencias/.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        etiqueta = request.query_params.get("asignatura")
        if not etiqueta or not str(etiqueta).strip():
            return Response(
                {"error": "Parámetro 'asignatura' es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        etiqueta = str(etiqueta).strip()

        try:
            person_data = buscar_persona_por_uid(user_uid)
            if not person_data:
                return Response([], status=status.HTTP_200_OK)

            user_type = person_data.get("type", "")
            if user_type == "Profesor":
                cursos_usuario = obtener_cursos_profesor(person_data, user_uid)
            elif user_type == "Estudiante":
                cursos_usuario = obtener_cursos_estudiante(person_data, user_uid)
            else:
                return Response(
                    {"error": f"Tipo de usuario no válido: {user_type}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            curso, group_id = _resolver_curso_y_grupo_por_etiqueta(cursos_usuario, etiqueta)
            if not curso:
                return Response(
                    {"error": "No se encontró un curso autorizado para esa asignatura"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            course_id = curso.get("id")
            course_name = curso.get("nameCourse", "Sin nombre")
            todas = obtener_asistencias_curso(course_id, curso, course_name)
            nk_user = _normalizar_etiqueta_asignatura(etiqueta)
            canon = MANUAL_ASIGNATURA_ALIAS_A_ETIQUETA_CANONICA.get(nk_user, nk_user)
            filtro_label = [
                a for a in todas if _normalizar_etiqueta_asignatura(a.get("asignatura")) == canon
            ]
            if group_id is not None:
                filtro_label = [a for a in filtro_label if a.get("groupId") == group_id]
            if user_type == "Estudiante":  # un estudiante solo ve sus propias asistencias
                filtro_label = [a for a in filtro_label if a.get("estudiante") == person_data.get("id")]

            now_local = django_timezone.localtime(django_timezone.now())
            dia_ingles = now_local.strftime("%A")
            dia_espanol = DIAS_INGLES_A_ESPANOL_VISTA.get(dia_ingles, dia_ingles)
            hora_actual_str = now_local.strftime("%H:%M")
            schedule = _schedule_curso_o_grupo(course_id, curso, group_id)
            en_ventana = _ventana_trialec_sin_salon(schedule, dia_espanol, dia_ingles, hora_actual_str)

            if en_ventana:
                today_str = now_local.strftime("%Y-%m-%d")
                out = [a for a in filtro_label if (a.get("fechaDocId") or "") == today_str]
            else:
                fechas = [a.get("fechaDocId") for a in filtro_label]
                ultima = _max_fecha_doc_ids(fechas)
                if ultima is None:
                    out = []
                else:
                    out = [a for a in filtro_label if (a.get("fechaDocId") or "") == ultima]

            return Response(out, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"AsistenciaVistaInicio: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return Response(
                {"error": "Error al obtener vista inicio", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


def _unidad_para_asistencias(user_uid, unidad_id):
    """
    (person, doc de la unidad, error). Docente: debe ser el dueño del curso o subgrupo. Estudiante: debe estar
    inscrito en esa unidad (y solo verá sus propias filas).
    """
    person = buscar_persona_por_uid(user_uid)
    curso_id, grupo_id = separar_id_unidad(unidad_id)
    if not person or not curso_id:
        return None, None, respuesta_asistencia_sin_permiso()
    if person.get('type') == 'Estudiante':
        if unidad_id not in {u['id'] for u in unidades_de_estudiante(person.get('id'))}:
            return None, None, respuesta_asistencia_sin_permiso()
    elif not es_docente_de(user_uid, curso_id, grupo_id, person):
        return None, None, respuesta_asistencia_sin_permiso()
    doc = ref_unidad(unidad_id).get()
    if not doc.exists:
        return None, None, Response({"error": "Curso no encontrado."}, status=status.HTTP_404_NOT_FOUND)
    return person, doc, None


def _fechas_de_unidad(unidad_id):
    """Fechas con asistencia de una unidad: solo los ids de los documentos, sin traer su contenido."""
    return [d.id for d in ref_unidad(unidad_id).collection("assistances").select([]).stream()]


class AsistenciaFechasView(APIView):
    """GET /api/asistencias/fechas/?unidad=<id>   Fechas (AAAA-MM-DD) con asistencias de esa unidad."""

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        unidad_id = str(request.query_params.get("unidad") or "").strip()
        try:
            _, _, error = _unidad_para_asistencias(user_uid, unidad_id)
            if error:
                return error
            return Response({"fechas": sorted(_fechas_de_unidad(unidad_id))}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"AsistenciaFechasView: {e}")
            return Response({"error": "Error al obtener las fechas."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaPaginaView(APIView):
    """
    GET /api/asistencias/pagina/?unidad=<id>[&fecha=AAAA-MM-DD][&dia=Lunes][&hora=HH:MM-HH:MM][&page=1][&size=10]
    Una página de las asistencias de una sesión, con el resumen de TODA la sesión (no solo de la página)
    y los nombres de quienes salen en la página. Así el Inicio no descarga todo el historial.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        q = request.query_params
        unidad_id = str(q.get("unidad") or "").strip()
        fecha = str(q.get("fecha") or "").strip() or None
        dia = str(q.get("dia") or "").strip() or None
        hora = str(q.get("hora") or "").strip() or None
        if fecha and not pagina_asist.fecha_valida(fecha):
            return Response({"error": "Fecha inválida."}, status=status.HTTP_400_BAD_REQUEST)
        if dia and dia not in pagina_asist.DIAS:
            return Response({"error": "Día inválido."}, status=status.HTTP_400_BAD_REQUEST)
        pagina = pagina_asist.numero_positivo(q.get("page"), 1)
        tamano = pagina_asist.numero_positivo(q.get("size"), pagina_asist.TAMANO_POR_DEFECTO, pagina_asist.TAMANO_MAXIMO)

        try:
            person, doc, error = _unidad_para_asistencias(user_uid, unidad_id)
            if error:
                return error
            curso_id, grupo_id = separar_id_unidad(unidad_id)
            unidad = doc.to_dict() or {}
            schedule = list(unidad.get("schedule") or [])

            ahora = django_timezone.localtime(django_timezone.now())
            hoy = ahora.strftime("%Y-%m-%d")
            en_ventana = False
            if not fecha and not dia:
                en_ventana = _ventana_trialec_sin_salon(
                    schedule, DIAS_INGLES_A_ESPANOL_VISTA.get(ahora.strftime("%A")), ahora.strftime("%A"), ahora.strftime("%H:%M"))
            fechas = [] if fecha else _fechas_de_unidad(unidad_id)
            elegida = pagina_asist.resolver_fecha(fechas, hoy, fecha=fecha, dia=dia, en_ventana=en_ventana)

            vacio = {"fecha": elegida, "resumen": pagina_asist.resumen([]), "page": 1, "size": tamano,
                     "totalPaginas": 1, "filas": [], "nombres": {}, "fueraDeFranja": 0}
            if not elegida:
                return Response(vacio, status=status.HTTP_200_OK)

            sesion = ref_unidad(unidad_id).collection("assistances").document(elegida).get()
            datos = (sesion.to_dict() or {}) if sesion.exists else {}
            if grupo_id:
                padre = db.collection("courses").document(curso_id).get()
                nombre_curso = (padre.to_dict() or {}).get("nameCourse", "Sin nombre") if padre.exists else "Sin nombre"
                etiqueta = f"{nombre_curso} - Grupo {unidad.get('group', grupo_id)}"
            else:
                nombre_curso = unidad.get("nameCourse", "Sin nombre")
                etiqueta = nombre_curso

            filas = []
            for cedula, e in sorted(datos.items()):
                if not isinstance(e, dict):
                    continue
                if person.get("type") == "Estudiante" and str(cedula) != person.get("id"):
                    continue  # un estudiante solo ve lo suyo
                filas.append({
                    "id": f"{curso_id}_{grupo_id}_{elegida}_{cedula}" if grupo_id else f"{curso_id}_{elegida}_{cedula}",
                    "estudiante": str(cedula), "asignatura": etiqueta, "fechaYhora": elegida,
                    "estadoAsistencia": e.get("estadoAsistencia", "Presente"), "horaRegistro": e.get("horaRegistro", ""),
                    "late": e.get("late", False), "courseId": curso_id, "groupId": grupo_id,
                    "fechaDocId": elegida, "hasGroups": bool(grupo_id),
                })
            filas, fuera = pagina_asist.filtrar_por_franja(filas, schedule, elegida, hora)
            items, pagina, total_paginas = pagina_asist.paginar(filas, pagina, tamano)

            nombres = {}
            for f in items:
                nombres[f["estudiante"]] = buscar_nombre_estudiante(f["estudiante"], buscar_en_db=True)
            return Response({
                "fecha": elegida, "resumen": pagina_asist.resumen(filas), "page": pagina, "size": tamano,
                "totalPaginas": total_paginas, "filas": items, "nombres": nombres, "fueraDeFranja": fuera,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"AsistenciaPaginaView: {e}")
            return Response({"error": "Error al obtener las asistencias."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaTodasView(APIView):
    """
    GET /api/asistencias/todas/?page=1&size=10[&asignatura=..][&estado=..][&q=..]
    "Todas las asistencias": una página del historial del usuario (docente: sus cursos; estudiante: solo lo suyo),
    con los conteos de los botones de filtro y el resumen de TODO lo que coincide con los filtros.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        q = request.query_params
        asignatura = str(q.get("asignatura") or "").strip() or None
        estado = str(q.get("estado") or "").strip() or None
        texto = str(q.get("q") or "").strip()[:80] or None
        if estado and estado not in pagina_asist.ESTADOS:
            return Response({"error": "Estado inválido."}, status=status.HTTP_400_BAD_REQUEST)
        pagina = pagina_asist.numero_positivo(q.get("page"), 1)
        tamano = pagina_asist.numero_positivo(q.get("size"), pagina_asist.TAMANO_POR_DEFECTO, pagina_asist.TAMANO_MAXIMO)

        try:
            person = buscar_persona_por_uid(user_uid)
            if not person:
                return respuesta_asistencia_sin_permiso()
            if person.get('type') == 'Profesor':
                cursos = obtener_cursos_profesor(person, user_uid)
            elif person.get('type') == 'Estudiante':
                cursos = obtener_cursos_estudiante(person, user_uid)
            else:
                return respuesta_asistencia_sin_permiso()

            filas = []
            for curso in cursos:
                filas.extend(obtener_asistencias_curso(curso['id'], curso, curso.get('nameCourse', 'Sin nombre')))
            if person.get('type') == 'Estudiante':
                filas = [a for a in filas if a.get('estudiante') == person.get('id')]

            # Los nombres solo hacen falta para buscar por nombre; la página siempre trae los suyos
            nombres = {}
            if texto:
                for cedula in {f['estudiante'] for f in filas}:
                    nombres[cedula] = buscar_nombre_estudiante(cedula, buscar_en_db=True)

            filtradas = pagina_asist.ordenar_recientes(pagina_asist.filtrar(filas, asignatura, estado, texto, nombres))
            items, pagina, total_paginas = pagina_asist.paginar(filtradas, pagina, tamano)
            for f in items:
                if f['estudiante'] not in nombres:
                    nombres[f['estudiante']] = buscar_nombre_estudiante(f['estudiante'], buscar_en_db=True)

            return Response({
                "filas": items, "page": pagina, "size": tamano, "totalPaginas": total_paginas,
                "totalGeneral": len(filas), "resumen": pagina_asist.resumen(filtradas),
                **pagina_asist.conteos(filas),
                "nombres": {f['estudiante']: nombres[f['estudiante']] for f in items},
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"AsistenciaTodasView: {e}")
            return Response({"error": "Error al obtener las asistencias."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AsistenciaReporteView(APIView):
    """
    GET /api/asistencias/reporte/?unidad=<id>[&fecha=AAAA-MM-DD][&hora=HH:MM-HH:MM]
    Datos para el reporte de asistencia de un curso o subgrupo: la lista de inscritos (aunque no tengan
    registros), las fechas con asistencia y el registro de cada estudiante en cada fecha. Con 'fecha' solo
    trae esa sesión. Un estudiante solo recibe su propia fila.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        q = request.query_params
        unidad_id = str(q.get("unidad") or "").strip()
        fecha = str(q.get("fecha") or "").strip() or None
        hora = str(q.get("hora") or "").strip() or None
        if fecha and not pagina_asist.fecha_valida(fecha):
            return Response({"error": "Fecha inválida."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            person, doc, error = _unidad_para_asistencias(user_uid, unidad_id)
            if error:
                return error
            curso_id, grupo_id = separar_id_unidad(unidad_id)
            unidad = doc.to_dict() or {}
            schedule = list(unidad.get("schedule") or [])
            propio = person.get("id") if person.get("type") == "Estudiante" else None

            if fecha:
                fechas = [fecha]
            else:
                fechas = sorted(f for f in _fechas_de_unidad(unidad_id) if pagina_asist.fecha_valida(f))

            registros, cedulas = {}, set(unidad.get("estudianteID") or [])
            fuera = 0
            for f in fechas:
                sesion = ref_unidad(unidad_id).collection("assistances").document(f).get()
                datos = (sesion.to_dict() or {}) if sesion.exists else {}
                filas = [{"estudiante": str(c), "horaRegistro": e.get("horaRegistro", ""), "e": e}
                         for c, e in datos.items() if isinstance(e, dict)]
                if hora and fecha:
                    filas, fuera = pagina_asist.filtrar_por_franja(filas, schedule, f, hora)
                for fila in filas:
                    c = fila["estudiante"]
                    if propio and c != propio:
                        continue
                    cedulas.add(c)
                    registros.setdefault(c, {})[f] = {
                        "estado": fila["e"].get("estadoAsistencia", "Presente"),
                        "hora": fila["e"].get("horaRegistro", ""), "late": bool(fila["e"].get("late", False)),
                    }
            if propio:
                cedulas = {propio}

            estudiantes = sorted(
                ({"cedula": c, "nombre": buscar_nombre_estudiante(c, buscar_en_db=True)} for c in cedulas),
                key=lambda e: (e["nombre"] or "").lower())

            nombre_curso = unidad.get("nameCourse")
            if grupo_id:
                padre = db.collection("courses").document(curso_id).get()
                nombre_curso = (padre.to_dict() or {}).get("nameCourse") if padre.exists else None
            grupo = unidad.get("group", grupo_id) if grupo_id else unidad.get("group")
            docente = person.get("namePerson", "") if person.get("type") == "Profesor" else ""
            docente_id = person.get("id", "") if person.get("type") == "Profesor" else ""
            return Response({
                "unidad": {"id": unidad_id, "courseId": curso_id, "nameCourse": nombre_curso, "group": grupo,
                           "docente": docente, "docenteId": docente_id},
                "fechas": fechas, "estudiantes": estudiantes, "registros": registros, "hora": hora, "fueraDeFranja": fuera,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"AsistenciaReporteView: {e}")
            return Response({"error": "Error al preparar el reporte."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _unidades_con_asistencias(unidades, filtro_id=None):
    """
    Lee las asistencias de las unidades (curso o subgrupo) y las deja en la forma que usa `estadisticas`:
    {id, nombre, estudiantes: {cédula: nombre}, sesiones: {fecha: {cédula: {estado, hora, late}}}}.
    Los nombres se completan después, solo de quienes los necesiten.
    """
    resultado = []
    for u in unidades:
        if filtro_id and u['id'] != filtro_id:
            continue
        etiqueta = f"{u['nameCourse']} - Grupo {u.get('group')}" if u.get('group') else u['nameCourse']
        sesiones = {}
        for d in ref_unidad(u['id']).collection("assistances").stream():
            datos = d.to_dict() or {}
            sesiones[d.id] = {
                str(c): {"estado": e.get("estadoAsistencia", "Presente"), "hora": e.get("horaRegistro", ""), "late": bool(e.get("late", False))}
                for c, e in datos.items() if isinstance(e, dict)
            }
        cedulas = {str(c) for c in (u.get('estudianteID') or [])} | {c for s_ in sesiones.values() for c in s_}
        resultado.append({"id": u['id'], "nombre": etiqueta, "estudiantes": {c: c for c in cedulas}, "sesiones": sesiones})
    return resultado


def _poner_nombres(unidades, cedulas=None):
    """Reemplaza la cédula por el nombre real (solo de las cédulas pedidas, o de todas si no se indica)."""
    cache = {}
    for u in unidades:
        for c in list(u["estudiantes"]):
            if cedulas is not None and c not in cedulas:
                continue
            if c not in cache:
                cache[c] = buscar_nombre_estudiante(c, buscar_en_db=True)
            u["estudiantes"][c] = cache[c]


class EstadisticasView(APIView):
    """
    GET /api/estadisticas/?unidad=<id>[&desde=AAAA-MM-DD][&hasta=AAAA-MM-DD]
    Para el docente: resumen, tendencia, día de la semana, comparación entre cursos, mapa de calor (con un solo
    curso elegido) y consejos (recordatorios, tardanzas, incentivos). Se calcula aquí; no se envían todas las filas.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        q = request.query_params
        unidad_id = str(q.get("unidad") or "").strip() or None
        desde = str(q.get("desde") or "").strip() or None
        hasta = str(q.get("hasta") or "").strip() or None
        if any(f and not pagina_asist.fecha_valida(f) for f in (desde, hasta)):
            return Response({"error": "Fecha inválida."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los docentes ven las estadísticas."}, status=status.HTTP_403_FORBIDDEN)
            disponibles = listar_unidades_horario(user_uid, person)
            if unidad_id and unidad_id not in {u['id'] for u in disponibles}:
                return respuesta_asistencia_sin_permiso()
            unidades = _unidades_con_asistencias(disponibles, unidad_id)

            consejos = estad.consejos_docente(unidades, desde, hasta)
            necesarios = {x['cedula'] for lista in consejos.values() for x in lista}
            _poner_nombres(unidades, necesarios)
            consejos = estad.consejos_docente(unidades, desde, hasta)   # ya con nombres
            mapa = None
            if len(unidades) == 1:
                _poner_nombres(unidades)
                mapa = estad.mapa_de_calor(unidades[0], desde, hasta)
            return Response({
                "unidades": [{"id": u['id'], "nombre": u['nombre']} for u in _unidades_con_nombre(disponibles)],
                "resumen": estad.resumen_general(unidades, desde, hasta),
                "tendencia": estad.tendencia(unidades, desde, hasta),
                "porDia": estad.por_dia_semana(unidades, desde, hasta),
                "porCurso": estad.por_curso(unidades, desde, hasta),
                "mapa": mapa,
                "consejos": consejos,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"EstadisticasView: {e}")
            return Response({"error": "Error al calcular las estadísticas."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _unidades_con_nombre(unidades):
    return [{"id": u['id'], "nombre": f"{u['nameCourse']} - Grupo {u.get('group')}" if u.get('group') else u['nameCourse']} for u in unidades]


class NotificacionesView(APIView):
    """
    GET /api/notificaciones/
    La campanita. Estudiante: recordatorios, consejos e incentivos sobre su propia asistencia. Docente: solo los
    casos críticos (3 o más faltas en una misma semana, o 4 o más seguidas) para no saturarlo.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            hoy = django_timezone.localtime(django_timezone.now()).strftime("%Y-%m-%d")
            if not person:
                return Response({"avisos": []}, status=status.HTTP_200_OK)
            if person.get('type') == 'Estudiante':
                cedula = person.get('id')
                unidades = _unidades_con_asistencias(unidades_de_estudiante(cedula))
                return Response({"avisos": estad.avisos_estudiante(unidades, cedula, hoy)}, status=status.HTTP_200_OK)
            if es_profesor(person):
                unidades = _unidades_con_asistencias(listar_unidades_horario(user_uid, person))
                avisos = estad.alertas_criticas_docente(unidades, hoy)
                nombres = {}
                for a in avisos:
                    nombres.setdefault(a['cedula'], buscar_nombre_estudiante(a['cedula'], buscar_en_db=True))
                    a['titulo'] = a['titulo'].replace(a['cedula'], nombres[a['cedula']], 1)
                return Response({"avisos": avisos}, status=status.HTTP_200_OK)
            return Response({"avisos": []}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"NotificacionesView: {e}")
            return Response({"error": "Error al cargar las notificaciones."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
            logger.info("[GET] /api/asistencias/ - Obtener asistencias filtradas")
            
            user_email = request.user_firebase.get('email', 'N/A')
            logger.info(f"Usuario UID: {user_uid}")
            logger.info(f"Email: {user_email}")
            
            # Buscar información del usuario en la colección 'person'
            person_data = buscar_persona_por_uid(user_uid)
            
            if not person_data:
                logger.warning(f"Usuario {user_uid} no encontrado en 'person'")
                return Response({
                    "message": "Usuario no registrado en el sistema",
                    "asistencias": []
                }, status=status.HTTP_200_OK)
            
            user_type = person_data.get('type', '')
            user_name = person_data.get('namePerson', 'Usuario')
            logger.info(f"Usuario encontrado: {user_name} - Tipo: {user_type}")
            
            # ============================================
            # OBTENER CURSOS SEGÚN EL TIPO DE USUARIO
            # ============================================
            if user_type == 'Profesor':
                logger.info(f"Obteniendo cursos del profesor {user_name}")
                cursos_usuario = obtener_cursos_profesor(person_data, user_uid)
            elif user_type == 'Estudiante':
                logger.info(f"Obteniendo cursos del estudiante {user_name}")
                cursos_usuario = obtener_cursos_estudiante(person_data, user_uid)
            else:
                logger.warning(f"Tipo de usuario no reconocido: {user_type}")
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
                
                logger.info(f"Procesando curso: {course_name} (ID: {course_id})")
                
                # Usar función auxiliar para obtener asistencias
                asistencias_curso = obtener_asistencias_curso(course_id, curso, course_name)
                asistencias_list.extend(asistencias_curso)
            
            if user_type == 'Estudiante':  # un estudiante solo ve sus propias asistencias
                asistencias_list = [a for a in asistencias_list if a.get('estudiante') == person_data.get('id')]

            logger.info(f"[SUCCESS] Total cursos del usuario: {len(cursos_usuario)}")
            logger.info(f"[SUCCESS] Total asistencias encontradas: {len(asistencias_list)}")
            logger.info("=" * 60)
            
            return Response(asistencias_list, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"[ERROR] Error en AsistenciaList: {str(e)}")
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
            logger.info("[POST] /api/asistencias/crear/")
            
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
            
            # Buscar el curso por nombre entre los que existen con ese nombre: solo vale uno del que sea docente
            courses_ref = db.collection("courses")
            candidatos = list(courses_ref.where(filter=firestore.FieldFilter("nameCourse", "==", asignatura)).stream())
            if not candidatos:
                return Response(
                    {"error": f"No se encontró el curso: {asignatura}"},
                    status=status.HTTP_404_NOT_FOUND
                )
            person_docente = buscar_persona_por_uid(user_uid)
            course_doc = next((d for d in candidatos if es_docente_de(user_uid, d.id, group_id, person_docente)), None)
            if course_doc is None:
                return respuesta_asistencia_sin_permiso()
            
            course_id = course_doc.id
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            hora_actual = datetime.now().strftime("%H:%M:%S")
            
            # Datos del estudiante
            estudiante_data = {
                'estadoAsistencia': estado_asistencia,
                'horaRegistro': hora_actual,
                'late': False
            }
            
            # Determinar la ruta correcta según si tiene grupos
            if group_id:
                # Ruta con grupos
                assistance_ref = (db.collection("courses")
                                 .document(course_id)
                                 .collection("groups")
                                 .document(group_id)
                                 .collection("assistances")
                                 .document(fecha_hoy))
                logger.info(f"Guardando en curso con grupos: {course_id}/groups/{group_id}")
            else:
                # Ruta simple
                assistance_ref = (db.collection("courses")
                                 .document(course_id)
                                 .collection("assistances")
                                 .document(fecha_hoy))
                logger.info(f"Guardando en curso sin grupos: {course_id}")
            
            # Actualizar o crear el documento
            assistance_ref.set({
                estudiante_cedula: estudiante_data
            }, merge=True)
            
            logger.info(f"Asistencia creada: {estudiante_cedula} en {asignatura}")
            
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
            logger.error(f"Error: {str(e)}")
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
            if not puede_ver_asistencia(user_uid, course_id, group_id, cedula):
                return respuesta_asistencia_sin_permiso()

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
            
            # OBTENER NOMBRE DEL ESTUDIANTE DESDE LA CÉDULA
            nombre_estudiante = buscar_nombre_estudiante(cedula)
            
            data = {
                'id': pk,
                'estudiante': nombre_estudiante,  # NOMBRE DEL ESTUDIANTE
                'estudianteCedula': cedula,       # CÉDULA COMO REFERENCIA
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
            logger.error(f"Error: {str(e)}")
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
            
            if not es_docente_de(user_uid, course_id, group_id):
                return respuesta_asistencia_sin_permiso()

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
            
            # SOLO ACTUALIZAR EL ESTADO DE ASISTENCIA
            if 'estadoAsistencia' in request.data:
                estudiante_data['estadoAsistencia'] = request.data['estadoAsistencia']
            
            assistance_ref.update({
                cedula: estudiante_data
            })
            
            course_doc = db.collection("courses").document(course_id).get()
            course_name = course_doc.to_dict().get('nameCourse', 'Sin nombre') if course_doc.exists else 'Sin nombre'
            
            # OBTENER NOMBRE DEL ESTUDIANTE
            nombre_estudiante = buscar_nombre_estudiante(cedula)
            
            updated_data = {
                'id': pk,
                'estudiante': nombre_estudiante,  # NOMBRE DEL ESTUDIANTE
                'estudianteCedula': cedula,       # CÉDULA COMO REFERENCIA
                'asignatura': course_name,
                'fechaYhora': fecha_id,
                'estadoAsistencia': estudiante_data.get('estadoAsistencia'),
                'horaRegistro': estudiante_data.get('horaRegistro', ''),
                'late': estudiante_data.get('late', False),
                'groupId': group_id if has_groups else None
            }
            
            logger.info(f"Asistencia actualizada: {pk}")
            
            return Response(updated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
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
            
            if not es_docente_de(user_uid, course_id, group_id):
                return respuesta_asistencia_sin_permiso()

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
            
            logger.info(f"Asistencia eliminada: {pk}")
            
            return Response(
                {'success': True, 'message': 'Asistencia eliminada', 'id': pk},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
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
            logger.info("[GET] /api/horarios/ - Obtener horario del usuario")
            
            logger.info(f"Usuario UID: {user_uid}")
            
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
            logger.info(f"Tipo de usuario: {user_type}")
            
            # ============================================
            # OBTENER CURSOS SEGÚN EL TIPO DE USUARIO
            # ============================================
            if user_type == 'Profesor':
                logger.info(f"Obteniendo cursos del profesor {user_name}")
                cursos = listar_unidades_horario(user_uid, person_data)
            elif user_type == 'Estudiante':
                logger.info(f"Obteniendo cursos del estudiante {user_name}")
                cursos = unidades_de_estudiante(person_data.get('id'))
            else:
                logger.warning(f"Tipo de usuario no reconocido: {user_type}")
                return Response({
                    "error": f"Tipo de usuario no válido: {user_type}",
                    "clases": []
                }, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"Total cursos del usuario: {len(cursos)}")
            logger.info("=" * 60)
            
            return Response({
                "profesorEmail": request.user_firebase.get('email'),
                "profesorNombre": person_data.get('namePerson', request.user_firebase.get('name', '')),
                "clases": cursos,
                "userType": user_type
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error al obtener horario: {str(e)}")
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
            logger.info("[POST] /api/horarios/ - Crear/Actualizar horario")
            
            clases = request.data.get('clases', [])
            person_data = buscar_persona_por_uid(user_uid)
            if not es_profesor(person_data):
                return Response(
                    {"error": "Solo los profesores pueden guardar horarios."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if not clases:
                return Response(
                    {"error": "No se proporcionaron clases"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            cursos_guardados = []
            antes_lista, despues_lista = [], []
            
            for clase in clases:
                serializer = CourseSerializer(data=clase)
                if serializer.is_valid():
                    curso_data = serializer.validated_data
                    curso_data['profesorID'] = user_uid
                    
                    if 'id' in clase and clase['id']:
                        doc_ref = db.collection("courses").document(clase['id'])
                        actual = doc_ref.get()
                        if not actual.exists:
                            return Response({"error": "Curso no encontrado"}, status=status.HTTP_404_NOT_FOUND)
                        if not usuario_puede_editar_curso(user_uid, clase['id'], actual.to_dict(), person_data):
                            return respuesta_sin_permiso()
                        # Solo se actualizan los campos enviados (el serializer rellena
                        # estudianteID/schedule con [] y pisaría los datos existentes)
                        datos_update = {k: v for k, v in curso_data.items() if k in clase or k == 'profesorID'}
                        datos_previos = actual.to_dict()
                        doc_ref.update(datos_update)
                        antes_lista.append(resumen_curso(clase['id'], datos_previos))
                        despues_lista.append(resumen_curso(clase['id'], {**datos_previos, **datos_update}))
                        curso_data['id'] = clase['id']
                        logger.info(f"Curso actualizado: {clase['id']}")
                    else:
                        doc_ref = db.collection("courses").add(curso_data)
                        curso_data['id'] = doc_ref[1].id
                        despues_lista.append(resumen_curso(curso_data['id'], curso_data))
                        logger.info(f"Curso creado: {curso_data['id']}")
                    
                    cursos_guardados.append(curso_data)
                else:
                    logger.warning(f"Datos inválidos: {serializer.errors}")
                    return Response(
                        {"error": "Datos inválidos", "details": serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            registrar_historial(
                user_uid, 'curso_guardado', calcular_cambios(antes_lista, despues_lista),
                periodo=request.data.get('periodo'), person_data=person_data
            )
            logger.info(f"Horario guardado: {len(cursos_guardados)} cursos")
            logger.info("=" * 60)
            
            return Response({
                "profesorEmail": request.user_firebase.get('email'),
                "clases": cursos_guardados
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error al guardar horario: {str(e)}")
            return Response(
                {"error": "Error al guardar horario", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request):
        """Archivar todo el horario del profesor (no se borra ningún curso ni asistencia)"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("[DELETE] /api/horarios/ - Archivar horario completo")

            person_data = buscar_persona_por_uid(user_uid)
            if not es_profesor(person_data):
                return Response(
                    {"error": "Solo los profesores pueden archivar su horario."},
                    status=status.HTTP_403_FORBIDDEN
                )

            unidades = [u for u in listar_unidades_horario(user_uid, person_data) if u['schedule']]
            antes_lista = [resumen_curso(u['id'], u) for u in unidades]
            for u in unidades:
                ref_unidad(u['id']).update({"schedule": []})
                logger.info(f"   Curso archivado: {u['id']}")

            registrar_historial(
                user_uid, 'horario_archivado',
                calcular_cambios(antes_lista, [{**a, 'schedule': []} for a in antes_lista]),
                person_data=person_data
            )

            return Response({
                "success": True,
                "message": f"Horario archivado ({len(unidades)} cursos). Se conservan sus asistencias y estudiantes.",
                "deletedCount": len(unidades)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error: {str(e)}")
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
            logger.info(f"[GET] /api/horarios/cursos/{course_id}/")
            
            doc = ref_unidad(course_id).get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            curso_data['id'] = doc.id
            
            return Response(curso_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def put(self, request, course_id):
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info(f"[PUT] /api/horarios/cursos/{course_id}/ - Actualizar horario")
            
            doc_ref = ref_unidad(course_id)
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
            if not usuario_puede_editar_curso(user_uid, course_id, curso_actual):
                return respuesta_sin_permiso()
            schedule = serializer.validated_data['schedule']
            unidades = listar_unidades_horario(user_uid, buscar_persona_por_uid(user_uid))
            for idx, clase in enumerate(schedule):
                hay_conflicto, mensaje = validar_conflicto_horario(
                    user_uid,
                    clase,
                    exclude_course_id=course_id,
                    exclude_class_index=idx,
                    unidades=unidades
                )
                if hay_conflicto:
                    return Response(
                        {"error": mensaje},
                        status=status.HTTP_409_CONFLICT
                    )
            
            doc_ref.update({"schedule": schedule})
            registrar_historial(
                user_uid, 'edicion_horario_curso',
                calcular_cambios(
                    [resumen_unidad(course_id, curso_actual)],
                    [resumen_unidad(course_id, {**curso_actual, 'schedule': schedule})]
                ),
                periodo=request.data.get('periodo')
            )
            
            updated_doc = doc_ref.get()
            updated_data = updated_doc.to_dict()
            updated_data['id'] = course_id
            
            logger.info(f"Horario actualizado: {len(schedule)} clases")
            
            return Response(updated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request, course_id):
        """Eliminar un curso completo"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info(f"[DELETE] /api/horarios/cursos/{course_id}/ - Eliminar curso")
            
            doc_ref = ref_unidad(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            if not usuario_puede_editar_curso(user_uid, course_id, doc.to_dict()):
                return respuesta_sin_permiso()

            antes_res = resumen_unidad(course_id, doc.to_dict())
            # No se borra el documento: así se conservan estudiantes y asistencias. Archivar es quitarle
            # el horario, y sin horario ya no se puede tomar asistencia en ese curso.
            doc_ref.update({"schedule": []})
            registrar_historial(
                user_uid, 'curso_archivado',
                calcular_cambios([antes_res], [{**antes_res, 'schedule': []}])
            )
            logger.info(f"Curso archivado: {course_id}")
            
            return Response({
                "success": True,
                "message": "Curso archivado: se conservan sus asistencias y estudiantes, pero ya no tiene horario.",
                "courseId": course_id
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
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
            logger.info("[POST] /api/horarios/clases/ - Agregar clase")
            
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
            
            doc_ref = ref_unidad(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            if not usuario_puede_editar_curso(user_uid, course_id, curso_data):
                return respuesta_sin_permiso()

            new_class = serializer.validated_data
            hay_conflicto, mensaje = validar_conflicto_horario(user_uid, new_class)
            if hay_conflicto:
                return Response(
                    {"error": mensaje},
                    status=status.HTTP_409_CONFLICT
                )
            
            schedule = curso_data.get('schedule', [])
            antes = copy.deepcopy(schedule)
            schedule.append(new_class)
            
            doc_ref.update({"schedule": schedule})
            registrar_historial(
                user_uid, 'clase_agregada',
                calcular_cambios(
                    [resumen_unidad(course_id, {**curso_data, 'schedule': antes})],
                    [resumen_unidad(course_id, {**curso_data, 'schedule': schedule})]
                )
            )
            
            logger.info(f"Clase agregada al curso {course_id}")
            
            return Response({
                **new_class,
                "index": len(schedule) - 1
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def put(self, request):
        """Actualizar una clase específica"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("[PUT] /api/horarios/clases/ - Actualizar clase")
            
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
            
            doc_ref = ref_unidad(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            if not usuario_puede_editar_curso(user_uid, course_id, curso_data):
                return respuesta_sin_permiso()
            schedule = curso_data.get('schedule', [])
            
            if class_index < 0 or class_index >= len(schedule):
                return Response(
                    {"error": "Índice de clase inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            antes = copy.deepcopy(schedule)
            schedule[class_index] = serializer.validated_data
            doc_ref.update({"schedule": schedule})
            registrar_historial(
                user_uid, 'clase_editada',
                calcular_cambios(
                    [resumen_unidad(course_id, {**curso_data, 'schedule': antes})],
                    [resumen_unidad(course_id, {**curso_data, 'schedule': schedule})]
                )
            )
            
            logger.info(f"Clase actualizada en curso {course_id}")
            
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request):
        """Eliminar una clase específica"""
        # Obtener UID sin verificar token
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            logger.info("[DELETE] /api/horarios/clases/ - Eliminar clase")
            
            course_id = request.data.get('courseId')
            class_index = request.data.get('classIndex')
            
            if course_id is None or class_index is None:
                return Response(
                    {"error": "courseId y classIndex son requeridos"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            doc_ref = ref_unidad(course_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                return Response(
                    {"error": "Curso no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            curso_data = doc.to_dict()
            if not usuario_puede_editar_curso(user_uid, course_id, curso_data):
                return respuesta_sin_permiso()
            schedule = curso_data.get('schedule', [])
            
            if class_index < 0 or class_index >= len(schedule):
                return Response(
                    {"error": "Índice de clase inválido"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            antes = copy.deepcopy(schedule)
            deleted_class = schedule.pop(class_index)
            doc_ref.update({"schedule": schedule})
            registrar_historial(
                user_uid, 'clase_eliminada',
                calcular_cambios(
                    [resumen_unidad(course_id, {**curso_data, 'schedule': antes})],
                    [resumen_unidad(course_id, {**curso_data, 'schedule': schedule})]
                )
            )
            
            logger.info(f"Clase eliminada del curso {course_id}")
            
            return Response({
                "success": True,
                "message": "Clase eliminada correctamente",
                "deleted_class": deleted_class
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ============================================
# IMPORTAR HORARIO (Excel / CSV / PDF leídos en el navegador)
# ============================================

def _comprobar_conversion(conv):
    """Falla ANTES de escribir nada si el subgrupo destino ya existe (no se pisa ningún dato)."""
    gref = db.collection("courses").document(conv['courseId']).collection("groups").document(conv['groupId'])
    if gref.get().exists:
        raise ValueError(f"El subgrupo {conv['groupId']} ya existe en el curso {conv['courseId']}")


def _convertir_a_subgrupos(conv, unidad, person):
    """
    Un curso con un solo grupo pasa a ser un curso con subgrupos (la estructura que ya usan los cursos con
    varios grupos): su grupo actual se vuelve el subgrupo `conv['groupId']`. No se borra nada:
      1. se crea el subgrupo con los estudiantes y el horario del grupo,
      2. se COPIAN sus asistencias al subgrupo (las originales se dejan intactas),
      3. el curso principal queda sin grupo propio y guarda un respaldo de lo que tenía.
    """
    curso_ref = db.collection("courses").document(conv['courseId'])
    gref = curso_ref.collection("groups").document(conv['groupId'])
    datos = curso_ref.get().to_dict() or {}

    gref.set({
        "profesorID": person.get('id') or datos.get('profesorID'),   # en los subgrupos, el id del documento 'person'
        "estudianteID": list(datos.get('estudianteID') or []),
        "schedule": list(datos.get('schedule') or []),
    })

    asistencias = list(curso_ref.collection("assistances").stream())
    for i in range(0, len(asistencias), 400):
        lote = db.batch()
        for d in asistencias[i:i + 400]:
            lote.set(gref.collection("assistances").document(d.id), d.to_dict() or {})
        lote.commit()

    curso_ref.update({
        "group": None,
        "schedule": [],
        "estudianteID": [],
        "convertidoASubgrupos": {
            "fecha": _ahora_iso(),
            "grupo": datos.get('group'),
            "profesorID": datos.get('profesorID'),
            "estudianteID": list(datos.get('estudianteID') or []),
            "schedule": list(datos.get('schedule') or []),
        },
    })
    logger.info(f"Curso {conv['courseId']} convertido a subgrupos (grupo {conv['groupId']}, {len(asistencias)} asistencias copiadas)")


def _aplicar_plan_importacion(plan, user_uid, person, cursos_actuales, periodo, archivo):
    """
    Escribe el plan en Firestore. Primero las conversiones de curso a subgrupos (si las hay) y después todo
    lo demás en un solo lote (todo o nada). Devuelve (cursos creados, subgrupos creados).
    """
    por_id_actual = {c['id']: c for c in cursos_actuales}
    conversiones = plan.get('conversiones') or []
    for conv in conversiones:
        _comprobar_conversion(conv)
    for conv in conversiones:
        _convertir_a_subgrupos(conv, por_id_actual[conv['desde']], person)

    batch = db.batch()
    creados = []
    subgrupos = []
    ids_creados = {}
    for p in plan['cursos']:
        if p['accion'] == 'archivar':
            batch.update(ref_unidad(p['courseId']), {"schedule": []})
        elif p['accion'] == 'actualizar':
            hay_cambio = p['nuevas'] or p['cambiosSalon'] or (plan['modo'] == 'reemplazar' and p['soloEnSistema'])
            if hay_cambio:
                batch.update(ref_unidad(p['courseId']), {"schedule": p['resultado']})
        elif p['accion'] == 'crear':
            # Con código de Academusoft, el curso usa ese código como id (como los demás); si ya está
            # ocupado (por ejemplo, otro grupo del mismo curso) se genera uno automático y no se pisa nada.
            codigo = p.get('codigo')
            ref = db.collection("courses").document(codigo) if codigo else None
            if ref is None or ref.get().exists:
                ref = db.collection("courses").document()
            batch.set(ref, {
                "nameCourse": p['nameCourse'],
                "group": p['group'],
                "profesorID": user_uid,
                "estudianteID": [],
                "schedule": p['resultado'],
            })
            creados.append({"id": ref.id, "nameCourse": p['nameCourse'], "group": p['group']})
            ids_creados[(p['nameCourse'], p['group'])] = ref.id
        elif p['accion'] == 'subgrupo':
            gref = db.collection("courses").document(p['cursoPadre']).collection("groups").document(p['groupId'])
            batch.set(gref, {
                "profesorID": person.get('id') or user_uid,   # convención de los subgrupos: id del documento 'person'
                "estudianteID": [],
                "schedule": p['resultado'],
            })
            nuevo_id = id_unidad(p['cursoPadre'], p['groupId'])
            subgrupos.append({"id": nuevo_id, "nameCourse": p['nameCourse'], "group": p['group']})
            ids_creados[(p['nameCourse'], p['group'])] = nuevo_id
    if creados and person.get('id'):
        batch.update(db.collection("person").document(person['id']),
                     {"courses": firestore.ArrayUnion([c['id'] for c in creados])})

    # Historial: queda en el mismo lote, así que se guarda junto con el cambio o no se guarda nada
    # Un curso convertido a subgrupo conserva su identidad en el historial (no cuenta como borrado + creado)
    nuevo_id_de = {conv['desde']: conv['hacia'] for conv in conversiones}
    antes = [resumen_curso(nuevo_id_de.get(c['id'], c['id']), c) for c in cursos_actuales]
    despues = aplicar_plan_a_cursos(antes, plan, ids_creados)
    cambios = calcular_cambios(antes, despues)
    if cambios:
        # Si se quitan clases y el semestre anterior no está en el historial, se guarda solo una copia de lo que había
        quitan = any(c['quitadas'] for c in cambios)
        existentes = {d.to_dict().get('periodo') for d in
                      db.collection("horarioHistorial").where(filter=firestore.FieldFilter('profesorID', '==', user_uid)).stream()}
        respaldo = periodo_de_respaldo(periodo, existentes, quitan)
        if respaldo:
            batch.set(db.collection("horarioHistorial").document(), construir_entrada(
                user_uid, 'respaldo_automatico', respaldo, [], antes,
                detalle={'nota': f'Copia automática del horario anterior, guardada antes de importar el de {periodo}'},
            ))
        entrada = construir_entrada(
            user_uid, 'importacion', periodo, cambios, despues,
            detalle={'modo': plan['modo'], 'archivo': archivo, 'filas': plan['resumen']['filasValidas']}
        )
        batch.set(db.collection("horarioHistorial").document(), entrada)
    batch.commit()
    return creados, subgrupos


class HorarioImportarView(APIView):
    """
    POST /api/horarios/importar/
    Body: { filas: [{curso, grupo, day, iniTime, endTime, classroom}], modo: 'combinar'|'reemplazar',
            crearFaltantes: bool, confirmar: bool }
    Sin confirmar devuelve solo la vista previa; con confirmar aplica exactamente ese mismo plan.
    """

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error

        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response(
                    {"error": "Solo los profesores pueden importar horarios."},
                    status=status.HTTP_403_FORBIDDEN
                )

            filas = request.data.get('filas')
            if not isinstance(filas, list) or not filas:
                return Response({"error": "No se enviaron filas para importar."}, status=status.HTTP_400_BAD_REQUEST)
            if len(filas) > MAX_FILAS:
                return Response(
                    {"error": f"Demasiadas filas (máximo {MAX_FILAS})."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            modo = request.data.get('modo', 'combinar')
            if modo not in MODOS:
                return Response({"error": "Modo de importación inválido."}, status=status.HTTP_400_BAD_REQUEST)
            crear_faltantes = bool(request.data.get('crearFaltantes', False))
            confirmar = bool(request.data.get('confirmar', False))
            periodo_recibido = request.data.get('periodo')
            periodo = normalizar_periodo(periodo_recibido) if periodo_recibido else periodo_actual()
            if not periodo:
                return Response(
                    {"error": "Período inválido. Usa el formato 2026-1 o 2026-2."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            archivo = str(request.data.get('archivo') or '')[:120] or None

            archivar_otros = bool(request.data.get('archivarOtros', False))
            cursos = listar_unidades_horario(user_uid, person)
            plan = planificar(filas, cursos, modo=modo, crear_faltantes=crear_faltantes, archivar_otros=archivar_otros)

            if not confirmar:
                return Response({"plan": plan, "aplicado": False}, status=status.HTTP_200_OK)

            if plan['conflictos']:
                return Response(
                    {"error": "Hay cruces de horario. Corrígelos antes de guardar.", "plan": plan, "aplicado": False},
                    status=status.HTTP_409_CONFLICT
                )
            if not plan['resumen']['hayCambios']:
                return Response(
                    {"error": "No hay cambios para aplicar.", "plan": plan, "aplicado": False},
                    status=status.HTTP_400_BAD_REQUEST
                )

            creados, subgrupos = _aplicar_plan_importacion(plan, user_uid, person, cursos, periodo, archivo)
            logger.info(f"Horario importado: {plan['resumen']}")
            return Response({
                "plan": plan, "aplicado": True, "cursosCreados": creados, "subgruposCreados": subgrupos,
                "cursosConvertidos": len(plan.get('conversiones') or []),
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error al importar horario: {e}")
            return Response({"error": "Error al importar el horario."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================
# HISTORIAL DE HORARIOS POR SEMESTRE
# ============================================

class HorarioHistorialView(APIView):
    """
    GET /api/horarios/historial/?periodo=2026-1
    Lista los períodos con cambios registrados y, para el período pedido (o el más reciente),
    el horario con el que quedó y la lista de cambios.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los profesores tienen historial de horarios."}, status=status.HTTP_403_FORBIDDEN)

            # Sin order_by para no exigir un índice compuesto en Firestore; el volumen por profesor es pequeño
            docs = db.collection("horarioHistorial").where(filter=firestore.FieldFilter('profesorID', '==', user_uid)).stream()
            entradas = sorted(
                [{**d.to_dict(), 'id': d.id} for d in docs],
                key=lambda e: e.get('fecha', ''),
                reverse=True
            )

            resumen_periodos = {}
            for e in entradas:
                r = resumen_periodos.setdefault(e['periodo'], {'periodo': e['periodo'], 'cambios': 0, 'ultimaFecha': e['fecha']})
                r['cambios'] += 1
            periodos = sorted(resumen_periodos.values(), key=lambda r: r['periodo'], reverse=True)

            pedido = request.query_params.get('periodo')
            seleccionado = normalizar_periodo(pedido) if pedido else (periodos[0]['periodo'] if periodos else periodo_actual())
            if not seleccionado:
                return Response({"error": "Período inválido."}, status=status.HTTP_400_BAD_REQUEST)

            del_periodo = [e for e in entradas if e['periodo'] == seleccionado]
            return Response({
                "periodos": periodos,
                "periodo": seleccionado,
                "periodoActual": periodo_actual(),
                "horario": del_periodo[0]['horario'] if del_periodo else None,
                "entradas": [
                    {k: e.get(k) for k in ('id', 'fecha', 'tipo', 'detalle', 'cambios', 'resumen')}
                    for e in del_periodo
                ],
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al consultar historial: {e}")
            return Response({"error": "Error al consultar el historial."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================
# CURSOS, ESTUDIANTES Y PERFIL
# ============================================

def _unidad_editable(user_uid, unidad_id, person):
    """Devuelve (ref, datos, error_response) de una unidad de horario que el usuario puede modificar."""
    ref = ref_unidad(unidad_id)
    doc = ref.get()
    if not doc.exists:
        return None, None, Response({"error": "Curso no encontrado"}, status=status.HTTP_404_NOT_FOUND)
    datos = doc.to_dict() or {}
    if not usuario_puede_editar_curso(user_uid, unidad_id, datos, person):
        return None, None, respuesta_sin_permiso()
    return ref, datos, None


def _leer_personas(cedulas):
    """{cédula: datos} de las cédulas que existen en `person` (lecturas en bloque)."""
    cedulas = sorted({c for c in cedulas if c})
    encontradas = {}
    for i in range(0, len(cedulas), 100):
        refs = [db.collection("person").document(c) for c in cedulas[i:i + 100]]
        for d in db.get_all(refs):
            if d.exists:
                encontradas[d.id] = d.to_dict() or {}
    return encontradas


def _cedulas_en_otros_grupos(curso_id, grupo_id):
    """Cédulas inscritas en el curso por otra vía (curso principal u otros subgrupos)."""
    curso_ref = db.collection("courses").document(curso_id)
    otras = set((curso_ref.get().to_dict() or {}).get('estudianteID') or [])
    for g in curso_ref.collection("groups").stream():
        if g.id != grupo_id:
            otras |= set((g.to_dict() or {}).get('estudianteID') or [])
    return otras


def _aplicar_inscripcion(ref, unidad_id, plan):
    """
    Escribe el plan: crea personas nuevas, las agrega al curso y quita a quien corresponda.
    Primero se agrega (un lote) y luego se quita (otro lote): cada lote es atómico.
    """
    curso_id, grupo_id = separar_id_unidad(unidad_id)

    a_inscribir = [e['cedula'] for e in plan['estudiantes'] if e['accion'] in ('crear', 'inscribir')]
    if a_inscribir:
        batch = db.batch()
        for e in plan['estudiantes']:
            pref = db.collection("person").document(e['cedula'])
            if e['accion'] == 'crear':
                batch.set(pref, {"namePerson": e['nombre'], "type": "Estudiante", "courses": [curso_id]})
            elif e['accion'] == 'inscribir':
                batch.update(pref, {"courses": firestore.ArrayUnion([curso_id])})
        batch.update(ref, {"estudianteID": firestore.ArrayUnion(a_inscribir)})
        batch.commit()

    a_quitar = [q['cedula'] for q in plan['quitar']]
    if a_quitar:
        # Si el curso tiene subgrupos, el estudiante puede seguir inscrito por otro: no se le quita el curso
        siguen = _cedulas_en_otros_grupos(curso_id, grupo_id) if grupo_id else set()
        batch = db.batch()
        batch.update(ref, {"estudianteID": firestore.ArrayRemove(a_quitar)})
        for c in a_quitar:
            if c not in siguen:
                batch.update(db.collection("person").document(c), {"courses": firestore.ArrayRemove([curso_id])})
        batch.commit()
    return {"inscritos": len(a_inscribir), "creados": sum(1 for e in plan['estudiantes'] if e['accion'] == 'crear'), "quitados": len(a_quitar)}


class CursosView(APIView):
    """POST /api/cursos/  Body: {nameCourse, group, codigo?}  Crea un curso (sin estudiantes ni horario)."""

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los profesores pueden crear cursos."}, status=status.HTTP_403_FORBIDDEN)

            datos, errores = validar_curso(request.data.get('nameCourse'), request.data.get('group'), request.data.get('codigo'))
            if errores:
                return Response({"error": errores[0], "details": errores}, status=status.HTTP_400_BAD_REQUEST)

            clave = (normalizar_texto(datos['nombre']), normalizar_texto(datos['grupo']))
            for u in listar_unidades_horario(user_uid, person):
                if (normalizar_texto(u['nameCourse']), normalizar_texto(u['group'])) == clave:
                    return Response({"error": "Ya tienes un curso con ese nombre y grupo."}, status=status.HTTP_409_CONFLICT)

            if datos['codigo']:
                ref = db.collection("courses").document(datos['codigo'])
                if ref.get().exists:
                    return Response({"error": "Ya existe un curso con ese código."}, status=status.HTTP_409_CONFLICT)
            else:
                ref = db.collection("courses").document()

            nuevo = {"nameCourse": datos['nombre'], "group": datos['grupo'], "profesorID": user_uid, "estudianteID": [], "schedule": []}
            batch = db.batch()
            batch.set(ref, nuevo)
            if person.get('id'):
                batch.update(db.collection("person").document(person['id']), {"courses": firestore.ArrayUnion([ref.id])})
            batch.commit()
            logger.info(f"Curso creado: {ref.id}")
            return Response({"curso": {**nuevo, "id": ref.id, "courseId": ref.id, "groupId": None}}, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Error al crear curso: {e}")
            return Response({"error": "Error al crear el curso."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CursoDetalleView(APIView):
    """PATCH /api/cursos/<unidad_id>/  Body: {nameCourse?, group?}  Edita el nombre o el grupo de un curso."""

    def patch(self, request, unidad_id):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los profesores pueden editar cursos."}, status=status.HTTP_403_FORBIDDEN)
            _, grupo_id = separar_id_unidad(unidad_id)
            if grupo_id:
                return Response(
                    {"error": "Este es un subgrupo: su nombre y grupo los define el curso principal y no se editan aquí."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            ref, actual, err = _unidad_editable(user_uid, unidad_id, person)
            if err:
                return err

            datos, errores = validar_curso(
                request.data.get('nameCourse', actual.get('nameCourse')),
                request.data.get('group', actual.get('group')),
            )
            if errores:
                return Response({"error": errores[0], "details": errores}, status=status.HTTP_400_BAD_REQUEST)

            clave = (normalizar_texto(datos['nombre']), normalizar_texto(datos['grupo']))
            for u in listar_unidades_horario(user_uid, person):
                if u['id'] != unidad_id and (normalizar_texto(u['nameCourse']), normalizar_texto(u['group'])) == clave:
                    return Response({"error": "Ya tienes un curso con ese nombre y grupo."}, status=status.HTTP_409_CONFLICT)

            ref.update({"nameCourse": datos['nombre'], "group": datos['grupo']})
            return Response({"id": unidad_id, "nameCourse": datos['nombre'], "group": datos['grupo']}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al editar curso: {e}")
            return Response({"error": "Error al editar el curso."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CursoEstudiantesView(APIView):
    """
    GET  /api/cursos/<unidad_id>/estudiantes/   Lista los estudiantes inscritos.
    POST /api/cursos/<unidad_id>/estudiantes/   Body: {estudiantes: [{cedula, nombre}], sincronizar?, confirmar?}
         Sin confirmar devuelve la vista previa; con confirmar aplica el mismo plan.
    """

    def get(self, request, unidad_id):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los profesores pueden ver la lista del curso."}, status=status.HTTP_403_FORBIDDEN)
            _, datos, err = _unidad_editable(user_uid, unidad_id, person)
            if err:
                return err
            ids = [str(c) for c in (datos.get('estudianteID') or [])]
            personas = _leer_personas(ids)
            lista = sorted(
                [{"cedula": c, "nombre": (personas.get(c) or {}).get('namePerson') or 'Sin registro', "registrado": c in personas} for c in ids],
                key=lambda e: normalizar_texto(e['nombre'])
            )
            return Response({"estudiantes": lista, "total": len(lista)}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al listar estudiantes: {e}")
            return Response({"error": "Error al cargar los estudiantes."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, unidad_id):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los profesores pueden inscribir estudiantes."}, status=status.HTTP_403_FORBIDDEN)
            ref, datos, err = _unidad_editable(user_uid, unidad_id, person)
            if err:
                return err

            filas = request.data.get('estudiantes')
            sincronizar = bool(request.data.get('sincronizar', False))
            if not isinstance(filas, list) or (not filas and not sincronizar):
                return Response({"error": "No se enviaron estudiantes."}, status=status.HTTP_400_BAD_REQUEST)
            if len(filas) > MAX_FILAS_ESTUDIANTES:
                return Response({"error": f"Demasiados estudiantes (máximo {MAX_FILAS_ESTUDIANTES} por carga)."}, status=status.HTTP_400_BAD_REQUEST)

            inscritos = {str(c) for c in (datos.get('estudianteID') or [])}
            en_archivo = {normalizar_cedula(f.get('cedula')) for f in filas if isinstance(f, dict)} - {None}
            personas = _leer_personas(en_archivo | inscritos)
            plan = planificar_inscripcion(filas, inscritos, personas, sincronizar=sincronizar)

            if not bool(request.data.get('confirmar', False)):
                return Response({"plan": plan, "aplicado": False}, status=status.HTTP_200_OK)
            if not plan['resumen']['hayCambios']:
                return Response({"error": "No hay cambios para aplicar.", "plan": plan, "aplicado": False}, status=status.HTTP_400_BAD_REQUEST)

            resultado = _aplicar_inscripcion(ref, unidad_id, plan)
            logger.info(f"Inscripción aplicada en {unidad_id}: {resultado}")
            return Response({"plan": plan, "aplicado": True, "resultado": resultado}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al inscribir estudiantes: {e}")
            return Response({"error": "Error al inscribir los estudiantes."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CursoEstudianteDetalleView(APIView):
    """DELETE /api/cursos/<unidad_id>/estudiantes/<cedula>/  Quita a un estudiante del curso (no borra su historial)."""

    def delete(self, request, unidad_id, cedula):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not es_profesor(person):
                return Response({"error": "Solo los profesores pueden quitar estudiantes."}, status=status.HTTP_403_FORBIDDEN)
            ref, datos, err = _unidad_editable(user_uid, unidad_id, person)
            if err:
                return err
            cedula = str(cedula)
            if cedula not in {str(c) for c in (datos.get('estudianteID') or [])}:
                return Response({"error": "Ese estudiante no está inscrito en el curso."}, status=status.HTTP_404_NOT_FOUND)
            plan = {"estudiantes": [], "quitar": [{"cedula": cedula, "nombre": ""}]}
            _aplicar_inscripcion(ref, unidad_id, plan)
            return Response({"success": True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al quitar estudiante: {e}")
            return Response({"error": "Error al quitar al estudiante."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


CAMPOS_PERFIL = ('telefono', 'programa', 'facultad')


class PerfilView(APIView):
    """
    GET   /api/perfil/   Datos del usuario (el correo viene de su cuenta, no se edita).
    PATCH /api/perfil/   Body: {nombre?, telefono?, programa?, facultad?}
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not person:
                return Response({"error": "No tienes un perfil registrado en el sistema."}, status=status.HTTP_404_NOT_FOUND)
            if person.get('type') == 'Estudiante':
                return Response({
                    "nombre": person.get('namePerson', ''),
                    "cedula": person.get('id'),
                    "email": request.user_firebase.get('email'),
                    "tipo": 'Estudiante',
                    "totalCursos": len({u['courseId'] for u in unidades_de_estudiante(person.get('id'))}),
                    "esAdmin": False,
                    **perfil_publico(person),
                }, status=status.HTTP_200_OK)
            return Response({
                "nombre": person.get('namePerson', ''),
                "email": request.user_firebase.get('email'),
                "tipo": person.get('type', ''),
                "telefono": person.get('telefono', ''),
                "programa": person.get('programa', ''),
                "facultad": person.get('facultad', ''),
                "totalCursos": len(person.get('courses') or []),
                "equipos": perfil_publico(person)['equipos'],
                "esAdmin": _email_y_admin(request)[2],
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al cargar perfil: {e}")
            return Response({"error": "Error al cargar el perfil."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def patch(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            person = buscar_persona_por_uid(user_uid)
            if not person or not person.get('id'):
                return Response({"error": "No tienes un perfil registrado en el sistema."}, status=status.HTTP_404_NOT_FOUND)

            if person.get('type') == 'Estudiante':
                return self._guardar_estudiante(request, user_uid, person)

            cambios, errores = {}, []
            if 'nombre' in request.data:
                nombre = re.sub(r'\s+', ' ', str(request.data.get('nombre') or '')).strip()
                if not (3 <= len(nombre) <= 120):
                    errores.append('El nombre debe tener entre 3 y 120 caracteres.')
                else:
                    cambios['namePerson'] = nombre
            for campo in CAMPOS_PERFIL:
                if campo not in request.data:
                    continue
                valor = re.sub(r'\s+', ' ', str(request.data.get(campo) or '')).strip()
                if campo == 'telefono' and valor and not re.fullmatch(r'[0-9+()\- ]{7,20}', valor):
                    errores.append('El teléfono solo puede tener números, espacios, +, - y paréntesis (7 a 20 caracteres).')
                elif len(valor) > 100:
                    errores.append(f'El campo {campo} es demasiado largo.')
                else:
                    cambios[campo] = valor
            if 'equipos' in request.data:  # el docente también registra los equipos con que ingresa
                validados, errores_equipos = validar_perfil_estudiante({'equipos': request.data.get('equipos')})
                errores.extend(errores_equipos)
                if not errores_equipos:
                    cambios['equipos'] = validados['equipos']
            if errores:
                return Response({"error": errores[0], "details": errores}, status=status.HTTP_400_BAD_REQUEST)
            if not cambios:
                return Response({"error": "No se enviaron cambios."}, status=status.HTTP_400_BAD_REQUEST)

            db.collection("person").document(person['id']).update(cambios)
            return Response({"success": True, "cambios": cambios}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al guardar perfil: {e}")
            return Response({"error": "Error al guardar el perfil."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _guardar_estudiante(self, request, user_uid, person):
        """El estudiante solo edita contacto y equipos (nunca nombre ni cédula). Cada cambio queda registrado."""
        cambios, errores = validar_perfil_estudiante(request.data)
        if errores:
            return Response({"error": errores[0], "details": errores}, status=status.HTTP_400_BAD_REQUEST)
        if not cambios:
            return Response({"error": "No se enviaron cambios."}, status=status.HTTP_400_BAD_REQUEST)
        filas = diferencias(person, cambios)
        if not filas:
            return Response({"success": True, "cambios": {}, "sinCambios": True}, status=status.HTTP_200_OK)
        db.collection("person").document(person['id']).update({f['campo']: f['despues'] for f in filas})
        registrar_cambio_estudiante('perfil', user_uid, person, request.user_firebase.get('email'), filas)
        return Response({"success": True, "cambios": {f['campo']: f['despues'] for f in filas}}, status=status.HTTP_200_OK)


# ============================================
# REGISTRO AUTOMÁTICO DE DOCENTES Y ADMINISTRACIÓN
# ============================================

def _email_y_admin(request):
    """(email normalizado, correo verificado, es administrador). Un admin SIEMPRE necesita correo verificado."""
    email = normalizar_email(request.user_firebase.get('email'))
    verificado = bool(request.user_firebase.get('email_verified'))
    es_admin = bool(email) and verificado and email in settings.ADMIN_EMAILS
    return email, verificado, es_admin


def _buscar_persona_por_cedula(cedula):
    d = db.collection("person").document(cedula).get()
    return (d.to_dict() or {}) if d.exists else None


def _ahora_iso():
    return django_timezone.localtime(django_timezone.now()).isoformat()


def _crear_o_vincular_docente(accion, cedula, nombre, uid, email, origen):
    """Escribe el documento person del docente. Devuelve False si la cédula quedó ocupada en el último momento."""
    ref = db.collection("person").document(cedula)
    if accion == 'crear_persona':
        try:
            ref.create({
                "namePerson": nombre, "type": "Profesor", "profesorUID": uid, "email": email,
                "courses": [], "origenRegistro": origen, "fechaRegistro": _ahora_iso(),
            })
        except AlreadyExists:
            return False
    else:  # vincular_persona: un docente que ya estaba en la base pero sin cuenta
        ref.update({"profesorUID": uid, "email": email})
    return True


class RegistroView(APIView):
    """
    POST /api/registro/   Body (opcional): {cedula, nombre}
    Se llama al iniciar sesión. Es idempotente: si la cuenta ya está activa solo lo informa; si su correo
    está autorizado crea su perfil de docente; si no, registra una solicitud para un administrador.
    El rol lo decide el servidor: nunca viene del navegador.
    """

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            email, verificado, es_admin = _email_y_admin(request)
            person = buscar_persona_por_uid(user_uid)

            if person and person.get('type') == 'Estudiante':  # cuenta de estudiante ya vinculada
                return Response({"estado": "activo", "mensaje": "Tu cuenta está activa.", "esAdmin": False,
                                 "rol": "Estudiante", "nombre": person.get('namePerson', '')}, status=status.HTTP_200_OK)

            autorizado = solicitud = None
            if email and verificado and not (person and person.get('type') == 'Profesor'):
                a = db.collection("profesoresAutorizados").document(email).get()
                autorizado = (a.to_dict() or {}) if a.exists else None
                s = db.collection("solicitudesRegistro").document(user_uid).get()
                solicitud = (s.to_dict() or {}) if s.exists else None

            datos = None
            if request.data.get('cedula') is not None or request.data.get('nombre') is not None:
                datos = {"cedula": request.data.get('cedula'), "nombre": request.data.get('nombre')}

            decision = decidir_registro(
                email=email, email_verificado=verificado, es_admin=es_admin, dominios=settings.REGISTRO_DOMINIOS,
                persona_vinculada=person, autorizado=autorizado, solicitud=solicitud, datos=datos,
                buscar_persona=_buscar_persona_por_cedula,
            )

            accion = decision['accion']
            if accion in ('crear_persona', 'vincular_persona'):
                if _crear_o_vincular_docente(accion, decision['cedula'], decision['nombre'], user_uid, email, 'automatico'):
                    if solicitud is not None:
                        db.collection("solicitudesRegistro").document(user_uid).update({"estado": "aprobada", "fechaResolucion": _ahora_iso()})
                    logger.info(f"Docente registrado automáticamente ({accion})")
                else:
                    decision = {**decision, "estado": "cedula_en_uso", "mensaje": "Esa identificación ya está registrada con otra cuenta. Contacta al administrador."}
            elif accion == 'crear_solicitud':
                db.collection("solicitudesRegistro").document(user_uid).set({
                    "uid": user_uid, "email": email, "nombre": decision['nombre'], "cedula": decision['cedula'],
                    "estado": "pendiente", "fecha": _ahora_iso(),
                })
                logger.info("Solicitud de registro creada")

            activo = decision['estado'] == 'activo'
            nombre = (person or {}).get('namePerson') or decision.get('nombre') or ''
            return Response({"estado": decision['estado'], "mensaje": decision['mensaje'], "esAdmin": es_admin,
                             "rol": 'Profesor' if activo else None, "nombre": nombre if activo else ''}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en el registro: {e}")
            return Response({"error": "Error al verificar tu cuenta."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def registrar_cambio_estudiante(tipo, uid, person, email, filas):
    """Deja constancia de lo que hizo un estudiante: quién, cuándo, y el valor de antes y de después."""
    db.collection("cambiosEstudiantes").document().set({
        "tipo": tipo, "uid": uid, "cedula": person.get('id'), "nombre": person.get('namePerson', ''),
        "email": email, "fecha": _ahora_iso(), "cambios": filas,
    })


class EstudianteVincularView(APIView):
    """
    POST /api/registro/estudiante/   Body: {cedula}
    Liga la cuenta con la cédula si existe como estudiante ACTIVO (inscrito en algún curso) y sin otra cuenta.
    """

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            email, verificado, es_admin = _email_y_admin(request)
            cuenta = buscar_persona_por_uid(user_uid)
            cedula = normalizar_cedula(request.data.get('cedula'))
            persona_cedula, inscripciones = None, 0
            if cuenta is None and email and verificado and cedula:
                persona_cedula = _buscar_persona_por_cedula(cedula)
                if persona_cedula and persona_cedula.get('type') == 'Estudiante':
                    inscripciones = len(unidades_de_estudiante(cedula))

            decision = decidir_vinculo(
                email=email, email_verificado=verificado, es_admin=es_admin, dominios=settings.REGISTRO_DOMINIOS,
                persona_de_la_cuenta=cuenta, cedula=cedula, persona_cedula=persona_cedula, inscripciones=inscripciones,
            )
            nombre = (cuenta or persona_cedula or {}).get('namePerson', '')
            if decision['accion'] == 'vincular':
                db.collection("person").document(cedula).update({"estudianteUID": user_uid, "email": email})
                registrar_cambio_estudiante('vinculacion', user_uid, {'id': cedula, 'namePerson': nombre}, email, [
                    {"campo": "cuenta", "antes": "", "despues": email},
                ])
                logger.info("Cuenta de estudiante vinculada")
            activo = decision['estado'] == 'activo'
            return Response({"estado": decision['estado'], "mensaje": decision['mensaje'], "esAdmin": False,
                             "rol": 'Estudiante' if activo else None, "nombre": nombre if activo else ''}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al vincular estudiante: {e}")
            return Response({"error": "Error al vincular tu cuenta."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _persona_de_la_cuenta(user_uid):
    persona = buscar_persona_por_uid(user_uid)
    return persona if persona and persona.get('id') and persona.get('type') in ('Profesor', 'Estudiante') else None


class LegalAceptacionView(APIView):
    """
    GET  /api/legal/aceptacion/   ¿La cuenta aceptó la versión vigente? Devuelve también lo que aceptó.
    POST /api/legal/aceptacion/   Body: {terminos: true, datosPersonales: true, biometrico?: bool}
    Se guarda en la persona y, como constancia que no se sobrescribe, en `aceptacionesLegales`.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            persona = _persona_de_la_cuenta(user_uid)
            if persona is None:
                return Response({"version": legal.VERSION, "vigente": True, "aceptacion": None, "aplica": False}, status=status.HTTP_200_OK)
            aceptacion = persona.get('aceptacionLegal')
            return Response({"version": legal.VERSION, "vigente": legal.esta_vigente(aceptacion), "aceptacion": aceptacion, "aplica": True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"LegalAceptacionView.get: {e}")
            return Response({"error": "Error al consultar la aceptación."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            persona = _persona_de_la_cuenta(user_uid)
            if persona is None:
                return Response({"error": "Tu cuenta aún no está vinculada a una persona del sistema."}, status=status.HTTP_403_FORBIDDEN)
            datos, errores = legal.validar_aceptacion(request.data)
            if errores:
                return Response({"error": errores[0], "details": errores}, status=status.HTTP_400_BAD_REQUEST)
            aceptacion = legal.construir_aceptacion(datos['biometrico'], momento=django_timezone.localtime(django_timezone.now()))
            db.collection("person").document(persona['id']).update({"aceptacionLegal": aceptacion})
            db.collection("aceptacionesLegales").document().set({
                **aceptacion, "evento": "aceptacion", "uid": user_uid, "cedula": persona['id'],
                "nombre": persona.get('namePerson', ''), "rol": persona.get('type'),
            })
            return Response({"version": legal.VERSION, "vigente": True, "aceptacion": aceptacion, "aplica": True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"LegalAceptacionView.post: {e}")
            return Response({"error": "Error al guardar tu aceptación."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LegalBiometricoView(APIView):
    """POST /api/legal/biometrico/  Body: {autoriza: bool}. Otorgar o revocar la autorización de datos biométricos."""

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            persona = _persona_de_la_cuenta(user_uid)
            if persona is None:
                return Response({"error": "Tu cuenta aún no está vinculada a una persona del sistema."}, status=status.HTTP_403_FORBIDDEN)
            autoriza = request.data.get('autoriza')
            if not isinstance(autoriza, bool):
                return Response({"error": "Indica si autorizas o no el uso de datos biométricos."}, status=status.HTTP_400_BAD_REQUEST)
            aceptacion = dict(persona.get('aceptacionLegal') or {})
            if not legal.esta_vigente(aceptacion):
                return Response({"error": "Primero debes aceptar los términos vigentes."}, status=status.HTTP_409_CONFLICT)
            if aceptacion.get('biometrico') == autoriza:
                return Response({"aceptacion": aceptacion}, status=status.HTTP_200_OK)
            aceptacion['biometrico'] = autoriza
            db.collection("person").document(persona['id']).update({"aceptacionLegal": aceptacion})
            db.collection("aceptacionesLegales").document().set({
                **aceptacion, "evento": "biometrico_otorgado" if autoriza else "biometrico_revocado",
                "fecha": _ahora_iso(), "uid": user_uid, "cedula": persona['id'],
                "nombre": persona.get('namePerson', ''), "rol": persona.get('type'),
            })
            return Response({"aceptacion": aceptacion}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"LegalBiometricoView: {e}")
            return Response({"error": "Error al guardar tu decisión."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LegalSolicitudView(APIView):
    """
    GET  /api/legal/solicitudes/   Tus solicitudes sobre tus datos y su estado.
    POST /api/legal/solicitudes/   Body: {tipo: consulta|rectificacion|supresion|revocatoria, detalle}
    Derechos del titular (Ley 1581 de 2012): un administrador las atiende.
    """

    def get(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            persona = _persona_de_la_cuenta(user_uid)
            if persona is None:
                return Response({"solicitudes": []}, status=status.HTTP_200_OK)
            filas = [{**{k: d.to_dict().get(k) for k in ('tipo', 'detalle', 'estado', 'fecha', 'respuesta', 'fechaRespuesta')}, 'id': d.id}
                     for d in db.collection("solicitudesDatos").stream() if (d.to_dict() or {}).get('cedula') == persona['id']]
            filas.sort(key=lambda f: f.get('fecha') or '', reverse=True)
            return Response({"solicitudes": filas}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"LegalSolicitudView.get: {e}")
            return Response({"error": "Error al cargar tus solicitudes."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        try:
            persona = _persona_de_la_cuenta(user_uid)
            if persona is None:
                return Response({"error": "Tu cuenta aún no está vinculada a una persona del sistema."}, status=status.HTTP_403_FORBIDDEN)
            datos, errores = legal.validar_solicitud(request.data)
            if errores:
                return Response({"error": errores[0], "details": errores}, status=status.HTTP_400_BAD_REQUEST)
            ya = any((d.to_dict() or {}).get('cedula') == persona['id'] and (d.to_dict() or {}).get('tipo') == datos['tipo']
                     and (d.to_dict() or {}).get('estado') == 'pendiente' for d in db.collection("solicitudesDatos").stream())
            if ya:
                return Response({"error": "Ya tienes una solicitud pendiente de ese tipo. Espera su respuesta."}, status=status.HTTP_409_CONFLICT)
            db.collection("solicitudesDatos").document().set({
                **datos, "estado": "pendiente", "fecha": _ahora_iso(), "uid": user_uid, "cedula": persona['id'],
                "nombre": persona.get('namePerson', ''), "rol": persona.get('type'), "email": normalizar_email(request.user_firebase.get('email')),
            })
            return Response({"success": True}, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"LegalSolicitudView.post: {e}")
            return Response({"error": "Error al enviar tu solicitud."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _exigir_admin(request):
    uid, error = obtener_uid_usuario(request)
    if error:
        return None, error
    if not _email_y_admin(request)[2]:
        return None, Response({"error": "Solo los administradores pueden hacer esto."}, status=status.HTTP_403_FORBIDDEN)
    return uid, None


class AdminSolicitudesView(APIView):
    """GET /api/admin/solicitudes/  Solicitudes de registro (las pendientes primero)."""

    def get(self, request):
        _, error = _exigir_admin(request)
        if error:
            return error
        try:
            filas = [
                {k: d.to_dict().get(k) for k in ('uid', 'email', 'nombre', 'cedula', 'estado', 'fecha', 'nota')}
                for d in db.collection("solicitudesRegistro").stream()
            ]
            filas.sort(key=lambda f: (f.get('estado') != 'pendiente', f.get('fecha') or ''), reverse=False)
            return Response({"solicitudes": filas}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al listar solicitudes: {e}")
            return Response({"error": "Error al cargar las solicitudes."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminSolicitudAccionView(APIView):
    """POST /api/admin/solicitudes/<uid>/aprobar|rechazar/   (rechazar admite {nota})."""

    def post(self, request, solicitud_uid, accion):
        admin_uid, error = _exigir_admin(request)
        if error:
            return error
        if accion not in ('aprobar', 'rechazar'):
            return Response({"error": "Acción inválida."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ref = db.collection("solicitudesRegistro").document(solicitud_uid)
            doc = ref.get()
            if not doc.exists:
                return Response({"error": "Solicitud no encontrada."}, status=status.HTTP_404_NOT_FOUND)
            solicitud = doc.to_dict() or {}
            if solicitud.get('estado') != 'pendiente':
                return Response({"error": "Esta solicitud ya fue resuelta."}, status=status.HTTP_400_BAD_REQUEST)
            admin_email = normalizar_email(request.user_firebase.get('email'))

            if accion == 'rechazar':
                nota = str(request.data.get('nota') or '').strip()[:200]
                ref.update({"estado": "rechazada", "nota": nota, "resueltaPor": admin_email, "fechaResolucion": _ahora_iso()})
                return Response({"estado": "rechazada"}, status=status.HTTP_200_OK)

            decision = preparar_aprobacion(solicitud, _buscar_persona_por_cedula)
            if decision['accion'] is None:
                return Response({"error": decision['mensaje']}, status=status.HTTP_409_CONFLICT)
            if not _crear_o_vincular_docente(decision['accion'], decision['cedula'], decision['nombre'], solicitud_uid, solicitud.get('email'), 'aprobacion'):
                return Response({"error": "Esa cédula ya fue registrada por otra cuenta."}, status=status.HTTP_409_CONFLICT)
            ref.update({"estado": "aprobada", "resueltaPor": admin_email, "fechaResolucion": _ahora_iso()})
            return Response({"estado": "aprobada"}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al resolver solicitud: {e}")
            return Response({"error": "Error al resolver la solicitud."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminCambiosEstudiantesView(APIView):
    """GET /api/admin/cambios-estudiantes/  Últimos cambios hechos por estudiantes (más recientes primero)."""

    def get(self, request):
        _, error = _exigir_admin(request)
        if error:
            return error
        try:
            docs = db.collection("cambiosEstudiantes").order_by("fecha", direction=firestore.Query.DESCENDING).limit(100).stream()
            claves = ('id', 'tipo', 'cedula', 'nombre', 'email', 'fecha', 'cambios')
            filas = [{**{k: d.to_dict().get(k) for k in claves if k != 'id'}, 'id': d.id} for d in docs]
            return Response({"cambios": filas}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al listar cambios de estudiantes: {e}")
            return Response({"error": "Error al cargar los cambios."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminLegalView(APIView):
    """GET /api/admin/legal/  Constancias de aceptación recientes y solicitudes de datos (las pendientes primero)."""

    def get(self, request):
        _, error = _exigir_admin(request)
        if error:
            return error
        try:
            acept = db.collection("aceptacionesLegales").order_by("fecha", direction=firestore.Query.DESCENDING).limit(100).stream()
            claves = ('evento', 'version', 'fecha', 'cedula', 'nombre', 'rol', 'biometrico')
            aceptaciones = [{k: d.to_dict().get(k) for k in claves} for d in acept]
            sol = [{**{k: d.to_dict().get(k) for k in ('tipo', 'detalle', 'estado', 'fecha', 'cedula', 'nombre', 'rol', 'email', 'respuesta')}, 'id': d.id}
                   for d in db.collection("solicitudesDatos").stream()]
            sol.sort(key=lambda f: (f.get('estado') != 'pendiente', f.get('fecha') or ''), reverse=False)
            return Response({"aceptaciones": aceptaciones, "solicitudes": sol}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"AdminLegalView: {e}")
            return Response({"error": "Error al cargar la información legal."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminSolicitudDatosView(APIView):
    """POST /api/admin/legal/solicitudes/<id>/atender/  Body: {respuesta}. Marca la solicitud como atendida."""

    def post(self, request, solicitud_id):
        _, error = _exigir_admin(request)
        if error:
            return error
        respuesta = ' '.join(str(request.data.get('respuesta') or '').split())[:600]
        if len(respuesta) < 3:
            return Response({"error": "Escribe la respuesta para el titular."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ref = db.collection("solicitudesDatos").document(solicitud_id)
            doc = ref.get()
            if not doc.exists:
                return Response({"error": "Solicitud no encontrada."}, status=status.HTTP_404_NOT_FOUND)
            if (doc.to_dict() or {}).get('estado') != 'pendiente':
                return Response({"error": "Esta solicitud ya fue atendida."}, status=status.HTTP_400_BAD_REQUEST)
            ref.update({"estado": "atendida", "respuesta": respuesta, "fechaRespuesta": _ahora_iso(),
                        "atendidaPor": normalizar_email(request.user_firebase.get('email'))})
            return Response({"estado": "atendida"}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"AdminSolicitudDatosView: {e}")
            return Response({"error": "Error al atender la solicitud."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminAutorizadosView(APIView):
    """
    GET  /api/admin/autorizados/   Lista de docentes autorizados.
    POST /api/admin/autorizados/   Body: {docentes: [{email, cedula, nombre}]} (máx. 200). Todo o nada.
    """

    def get(self, request):
        _, error = _exigir_admin(request)
        if error:
            return error
        try:
            filas = sorted(
                [{k: d.to_dict().get(k) for k in ('email', 'cedula', 'nombre')} for d in db.collection("profesoresAutorizados").stream()],
                key=lambda f: f.get('email') or ''
            )
            return Response({"docentes": filas}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al listar autorizados: {e}")
            return Response({"error": "Error al cargar la lista."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        admin_uid, error = _exigir_admin(request)
        if error:
            return error
        try:
            docentes = request.data.get('docentes')
            if not isinstance(docentes, list) or not docentes:
                return Response({"error": "No se enviaron docentes."}, status=status.HTTP_400_BAD_REQUEST)
            if len(docentes) > 200:
                return Response({"error": "Máximo 200 docentes por carga."}, status=status.HTTP_400_BAD_REQUEST)

            validos, invalidos = {}, []
            for i, fila in enumerate(docentes):
                f, errores = validar_docente(fila)
                if errores:
                    invalidos.append({"fila": i + 1, "errores": errores})
                else:
                    validos[f['email']] = f
            if invalidos:
                return Response({"error": "Hay filas con errores; no se guardó nada.", "invalidos": invalidos}, status=status.HTTP_400_BAD_REQUEST)

            admin_email = normalizar_email(request.user_firebase.get('email'))
            batch = db.batch()
            for email, f in validos.items():
                batch.set(db.collection("profesoresAutorizados").document(email), {**f, "creadoPor": admin_email, "fecha": _ahora_iso()})
            batch.commit()
            return Response({"guardados": len(validos)}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al guardar autorizados: {e}")
            return Response({"error": "Error al guardar la lista."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminAutorizadoDetalleView(APIView):
    """DELETE /api/admin/autorizados/<email>/  Quita una autorización (no borra a quien ya se registró)."""

    def delete(self, request, email):
        _, error = _exigir_admin(request)
        if error:
            return error
        email = normalizar_email(email)
        if not email:
            return Response({"error": "Correo inválido."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            db.collection("profesoresAutorizados").document(email).delete()
            return Response({"success": True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error al quitar autorización: {e}")
            return Response({"error": "Error al quitar la autorización."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================
# NUEVO ENDPOINT PARA BUSCAR NOMBRE DE ESTUDIANTE
# ============================================

class EstudianteNombreView(APIView):
    """
    GET /api/estudiantes/nombre/<cedula>/
    Busca el nombre de un estudiante por su cédula
    """
    
    def get(self, request, cedula):
        user_uid, error = obtener_uid_usuario(request)
        if error:
            return error
        
        try:
            logger.info(f"[GET] /api/estudiantes/nombre/{cedula}/")

            persona = buscar_persona_por_uid(user_uid)
            if not persona or (persona.get('type') == 'Estudiante' and persona.get('id') != str(cedula)):
                return Response({"error": "No tienes permiso para consultar este nombre."}, status=status.HTTP_403_FORBIDDEN)

            # Buscar en la base de datos
            nombre = buscar_nombre_estudiante(cedula, buscar_en_db=True)
            
            return Response({
                "cedula": cedula,
                "nombre": nombre
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
# ============================================
# HEALTH CHECK
# ============================================
class HealthCheck(APIView):
    """GET /api/health/ - Verificar estado del servidor"""
    
    def get(self, request):
        logger.info("[HEALTH CHECK] Servidor funcionando")
        
        try:
            list(db.collection("courses").limit(1).stream())
            firebase_status = "Conectado"
        except Exception as e:
            # El detalle solo va al log del servidor; este endpoint es público
            logger.error(f"[HEALTH CHECK] Error de Firebase: {e}")
            firebase_status = "Sin conexión"
        
        return Response({
            "status": "OK",
            "timestamp": datetime.now().isoformat(),
            "firebase": firebase_status,
            "authentication": "Firebase ID token (Bearer, verified server-side)",
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
                },
                "estudiantes": {  # NUEVO
                    "get_nombre": "GET /api/estudiantes/nombre/<cedula>/"
                }
            }
        }, status=status.HTTP_200_OK)