"""
Cuenta del estudiante: vincular su inicio de sesión con su cédula y editar sus datos de contacto y equipos.

Lógica pura (sin Firestore): las vistas leen y escriben. El rol nunca lo elige el usuario.

Vincular (mismo criterio que el registro de docentes, sin aprobación manual):
  1. Correo verificado y de un dominio permitido (el institucional).
  2. La cédula debe existir como `Estudiante` en `person`.
  3. Debe estar ACTIVO: inscrito en al menos un curso o subgrupo.
  4. No puede tener ya otra cuenta ligada, y esta cuenta no puede estar ligada a otra persona.

Modelo (documento person/{cédula} del estudiante):
  estudianteUID, email,                      -> los pone la vinculación
  telefono, emailPersonal,                   -> contacto
  contactoEmergencia: {nombre, telefono},
  equipos: [{marca, serial}]                 -> portátiles que ingresan a la universidad
"""
import re

from .estudiantes_import import normalizar_cedula
from .registro import dominio_de, normalizar_email

MAX_EQUIPOS = 5
_RE_TELEFONO = re.compile(r'[0-9+()\- ]{7,20}')
_RE_SERIAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9\-_/. ]{2,59}')

CAMPOS_EDITABLES = ('telefono', 'emailPersonal', 'contactoEmergencia', 'equipos')


def _texto(valor):
    return re.sub(r'\s+', ' ', str(valor or '')).strip()


def _resultado(estado, mensaje, accion=None):
    return {'estado': estado, 'mensaje': mensaje, 'accion': accion}


def decidir_vinculo(*, email, email_verificado, es_admin, dominios, persona_de_la_cuenta, cedula,
                    persona_cedula, inscripciones):
    """
    persona_de_la_cuenta: documento person ligado a ESTA cuenta (cualquier tipo), o None.
    cedula:               la que escribió el estudiante.
    persona_cedula:       documento person de esa cédula, o None.
    inscripciones:        en cuántos cursos o subgrupos está inscrita esa cédula.
    """
    if persona_de_la_cuenta is not None:
        if persona_de_la_cuenta.get('type') == 'Estudiante':
            return _resultado('activo', 'Tu cuenta está activa.')
        return _resultado('cuenta_docente', 'Esta cuenta ya pertenece a un docente.')

    if not email:
        return _resultado('sin_correo', 'Tu cuenta no tiene un correo asociado.')
    if not email_verificado:
        return _resultado('no_verificado', 'Verifica tu correo para continuar. Te enviamos un mensaje con el enlace.')
    if not es_admin and dominios and dominio_de(email) not in dominios:
        return _resultado('dominio_no_permitido', 'Usa tu correo institucional (@' + dominios[0] + ') para ingresar.')

    cedula = normalizar_cedula(cedula)
    if not cedula:
        return _resultado('requiere_datos', 'Escribe tu número de cédula para vincular tu cuenta.')

    if persona_cedula is None or persona_cedula.get('type') != 'Estudiante':
        return _resultado('cedula_no_encontrada', 'No encontramos un estudiante con esa cédula. Revisa el número o consulta con tu docente.')
    if persona_cedula.get('estudianteUID'):
        return _resultado('cedula_en_uso', 'Esa cédula ya está vinculada a otra cuenta. Contacta al administrador.')
    if inscripciones < 1:
        return _resultado('estudiante_inactivo', 'Esa cédula no está inscrita en ningún curso activo. Consulta con tu docente.')

    return _resultado('activo', 'Cuenta vinculada: ya puedes ver tu horario y tus asistencias.', 'vincular')


# ----- edición del perfil -----

def _validar_telefono(valor, etiqueta):
    v = _texto(valor)
    if v and not _RE_TELEFONO.fullmatch(v):
        return None, f'{etiqueta}: solo números, espacios, +, - y paréntesis (7 a 20 caracteres).'
    return v, None


def _validar_equipos(valor):
    if not isinstance(valor, list):
        return None, 'Los equipos deben ser una lista.'
    if len(valor) > MAX_EQUIPOS:
        return None, f'Puedes registrar hasta {MAX_EQUIPOS} equipos.'
    equipos, vistos = [], set()
    for i, e in enumerate(valor, start=1):
        if not isinstance(e, dict):
            return None, f'Equipo {i}: datos inválidos.'
        marca, serial = _texto(e.get('marca')), _texto(e.get('serial')).upper()
        if not marca and not serial:
            continue  # fila vacía: se ignora
        if not (1 <= len(marca) <= 40):
            return None, f'Equipo {i}: escribe la marca (hasta 40 caracteres).'
        if not _RE_SERIAL.fullmatch(serial):
            return None, f'Equipo {i}: el serial debe tener entre 3 y 60 caracteres (letras, números, - _ / .).'
        if serial in vistos:
            return None, f'El serial {serial} está repetido.'
        vistos.add(serial)
        equipos.append({'marca': marca, 'serial': serial})
    return equipos, None


def validar_perfil_estudiante(datos):
    """Valida lo que el estudiante envía. Devuelve (cambios normalizados, [errores]); solo trae lo enviado."""
    if not isinstance(datos, dict):
        return {}, ['Datos inválidos.']
    cambios, errores = {}, []

    if 'telefono' in datos:
        v, err = _validar_telefono(datos['telefono'], 'Teléfono')
        errores.append(err) if err else cambios.update(telefono=v)

    if 'emailPersonal' in datos:
        bruto = _texto(datos['emailPersonal'])
        if not bruto:
            cambios['emailPersonal'] = ''
        elif normalizar_email(bruto) and len(bruto) <= 120:
            cambios['emailPersonal'] = normalizar_email(bruto)
        else:
            errores.append('El correo personal no es válido.')

    if 'contactoEmergencia' in datos:
        c = datos['contactoEmergencia']
        if not isinstance(c, dict):
            errores.append('El contacto de emergencia es inválido.')
        else:
            nombre = _texto(c.get('nombre'))
            tel, err = _validar_telefono(c.get('telefono'), 'Teléfono de emergencia')
            if err:
                errores.append(err)
            elif len(nombre) > 100:
                errores.append('El nombre del contacto de emergencia es demasiado largo.')
            elif bool(nombre) != bool(tel):
                errores.append('El contacto de emergencia necesita nombre y teléfono.')
            else:
                cambios['contactoEmergencia'] = {'nombre': nombre, 'telefono': tel}

    if 'equipos' in datos:
        v, err = _validar_equipos(datos['equipos'])
        errores.append(err) if err else cambios.update(equipos=v)

    return cambios, errores


def _vacio(campo):
    return {'contactoEmergencia': {'nombre': '', 'telefono': ''}, 'equipos': []}.get(campo, '')


def valor_actual(persona, campo):
    return (persona or {}).get(campo) or _vacio(campo)


def diferencias(persona, cambios):
    """Solo lo que realmente cambia: [{campo, antes, despues}]. Si no cambió nada, lista vacía."""
    filas = []
    for campo in CAMPOS_EDITABLES:
        if campo not in cambios:
            continue
        antes, despues = valor_actual(persona, campo), cambios[campo] or _vacio(campo)
        if antes != despues:
            filas.append({'campo': campo, 'antes': antes, 'despues': despues})
    return filas


def perfil_publico(persona):
    """Lo que el estudiante ve de sí mismo."""
    return {
        'telefono': valor_actual(persona, 'telefono'),
        'emailPersonal': valor_actual(persona, 'emailPersonal'),
        'contactoEmergencia': valor_actual(persona, 'contactoEmergencia'),
        'equipos': valor_actual(persona, 'equipos'),
    }
