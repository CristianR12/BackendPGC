"""
Registro automático de docentes.

Quien inicia sesión por primera vez no tiene documento en `person`. Este módulo decide qué pasa con
esa cuenta SIN tocar Firestore (la vista lee y escribe). El rol nunca lo elige el usuario:

  1. Correo verificado obligatorio (con Google ya lo está; con contraseña, tras confirmar el correo).
  2. Solo dominios permitidos (por defecto, el institucional), salvo los administradores.
  3. Si el correo está en `profesoresAutorizados` -> se crea (o vincula) su `person` automáticamente.
  4. Si no -> solicitud pendiente, que aprueba o rechaza un administrador.

Modelo de datos (el mismo que usa el resto del sistema):
  person/{cédula} -> {namePerson, type: 'Profesor', profesorUID, courses: [], email}
"""
import re

from .estudiantes_import import limpiar_nombre, normalizar_cedula

_RE_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

ESTADOS_FINALES = ('activo', 'pendiente', 'rechazada')


def normalizar_email(valor):
    s = str(valor or '').strip().lower()
    return s if _RE_EMAIL.match(s) else None


def dominio_de(email):
    return email.rsplit('@', 1)[1]


def lista_de_emails(valor):
    """'a@x.com, B@x.com ;;' -> {'a@x.com', 'b@x.com'} (ignora lo que no sea un correo)."""
    partes = re.split(r'[,;\s]+', str(valor or ''))
    return {e for e in (normalizar_email(p) for p in partes) if e}


def lista_de_dominios(valor):
    return [d.strip().lower().lstrip('@') for d in str(valor or '').split(',') if d.strip()]


def validar_docente(fila):
    """Valida una fila de la lista de docentes autorizados. Devuelve (fila | None, [errores])."""
    if not isinstance(fila, dict):
        return None, ['La fila no es válida.']
    email = normalizar_email(fila.get('email'))
    cedula = normalizar_cedula(fila.get('cedula'))
    nombre = limpiar_nombre(fila.get('nombre'))
    errores = []
    if not email:
        errores.append(f"Correo inválido: '{fila.get('email') or ''}'.")
    if not cedula:
        errores.append(f"Cédula inválida: '{fila.get('cedula') or ''}'.")
    if not (3 <= len(nombre) <= 120):
        errores.append('El nombre debe tener entre 3 y 120 caracteres.')
    if errores:
        return None, errores
    return {'email': email, 'cedula': cedula, 'nombre': nombre}, []


def _resultado(estado, mensaje, accion=None, cedula=None, nombre=None):
    return {'estado': estado, 'mensaje': mensaje, 'accion': accion, 'cedula': cedula, 'nombre': nombre}


def _persona_para(cedula, nombre, buscar_persona, mensaje_activo):
    """Crear la persona si la cédula está libre; vincularla si es un docente sin cuenta; si no, conflicto."""
    existente = buscar_persona(cedula)
    if existente is None:
        return _resultado('activo', mensaje_activo, 'crear_persona', cedula, nombre)
    if existente.get('type') == 'Profesor' and not existente.get('profesorUID'):
        return _resultado('activo', mensaje_activo, 'vincular_persona', cedula, nombre)
    return _resultado(
        'cedula_en_uso',
        'Esa identificación ya está registrada con otra cuenta. Contacta al administrador.',
    )


def decidir_registro(*, email, email_verificado, es_admin, dominios, persona_vinculada, autorizado,
                     solicitud, datos, buscar_persona):
    """
    persona_vinculada: documento person de ESTA cuenta (profesorUID == uid), o None.
    autorizado:        documento de profesoresAutorizados para este correo, o None.
    solicitud:         documento de solicitudesRegistro de esta cuenta, o None.
    datos:             {cedula, nombre} que el usuario envió (o None).
    buscar_persona:    función cédula -> documento person existente o None.
    """
    if persona_vinculada is not None and persona_vinculada.get('type') == 'Profesor':
        return _resultado('activo', 'Tu cuenta está activa.')

    if not email:
        return _resultado('sin_correo', 'Tu cuenta no tiene un correo asociado.')
    if not email_verificado:
        return _resultado('no_verificado', 'Verifica tu correo para continuar. Te enviamos un mensaje con el enlace.')
    if not es_admin and dominios and dominio_de(email) not in dominios:
        return _resultado(
            'dominio_no_permitido',
            'Usa tu correo institucional (@' + dominios[0] + ') para registrarte.',
        )

    if autorizado is not None:
        cedula = normalizar_cedula(autorizado.get('cedula'))
        nombre = limpiar_nombre(autorizado.get('nombre'))
        if not cedula or len(nombre) < 3:
            return _resultado('cedula_en_uso', 'Tu autorización tiene datos incompletos. Contacta al administrador.')
        return _persona_para(cedula, nombre, buscar_persona, 'Bienvenido: tu cuenta quedó activa.')

    if solicitud is not None:
        if solicitud.get('estado') == 'rechazada':
            return _resultado('rechazada', 'Tu solicitud fue rechazada. Contacta al administrador.')
        if solicitud.get('estado') == 'pendiente':
            return _resultado('pendiente', 'Tu solicitud está pendiente de aprobación.')

    fila, _ = validar_docente({'email': email, **(datos or {})})
    if fila is None:
        return _resultado('requiere_datos', 'Para solicitar acceso escribe tu cédula y tu nombre completo.')
    if buscar_persona(fila['cedula']) is not None:
        return _resultado(
            'cedula_en_uso',
            'Esa identificación ya está registrada con otra cuenta. Contacta al administrador.',
        )
    return _resultado('pendiente', 'Solicitud enviada: un administrador la revisará.', 'crear_solicitud', fila['cedula'], fila['nombre'])


def preparar_aprobacion(solicitud, buscar_persona):
    """Qué hacer al aprobar una solicitud: crear la persona, vincular un docente sin cuenta, o conflicto."""
    cedula = normalizar_cedula(solicitud.get('cedula'))
    nombre = limpiar_nombre(solicitud.get('nombre'))
    if not cedula or len(nombre) < 3:
        return _resultado('cedula_en_uso', 'La solicitud tiene datos incompletos.')
    return _persona_para(cedula, nombre, buscar_persona, 'Docente aprobado.')
