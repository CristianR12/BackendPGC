"""
Inscripción de estudiantes en un curso (a mano o desde la "Lista de Alumnos por Grupo" de Academusoft).

Modelo de datos (el mismo que usa el módulo de reconocimiento):
  person/{cédula}   -> {namePerson, type: 'Estudiante', courses: [ids de curso]}
  courses/{id}      -> {estudianteID: [cédulas], ...}              (o courses/{id}/groups/{g} en subgrupos)

Este módulo no toca Firestore: valida las filas y calcula el plan. La vista lee/escribe.
"""
import re

from .horario_import import normalizar_texto

MAX_FILAS = 200
LARGO_CEDULA = (5, 12)


def normalizar_cedula(valor):
    """'1.234.567.890', 1234567890.0 o ' 1234567890 ' -> '1234567890'. None si no es una cédula válida."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    s = re.sub(r'[.\s,]', '', str(valor if valor is not None else ''))
    if not s.isdigit() or not (LARGO_CEDULA[0] <= len(s) <= LARGO_CEDULA[1]):
        return None
    return s


def limpiar_nombre(valor):
    return re.sub(r'\s+', ' ', str(valor or '')).strip()


def validar_fila(fila):
    """Devuelve (fila_normalizada | None, [errores])."""
    if not isinstance(fila, dict):
        return None, ['La fila no es válida.']
    errores = []
    cedula = normalizar_cedula(fila.get('cedula'))
    nombre = limpiar_nombre(fila.get('nombre'))
    if not cedula:
        errores.append(f"Identificación inválida o vacía: '{fila.get('cedula') or ''}'.")
    if len(nombre) < 3:
        errores.append('Falta el nombre.')
    if len(nombre) > 120:
        errores.append('El nombre es demasiado largo.')
    if errores:
        return None, errores
    return {'cedula': cedula, 'nombre': nombre}, []


def planificar_inscripcion(filas, inscritos, personas, sincronizar=False):
    """
    filas:     filas crudas {cedula, nombre}.
    inscritos: cédulas que YA están en el curso.
    personas:  {cédula: {'type', 'namePerson'}} de las cédulas que existen en `person`
               (las del archivo y las ya inscritas).
    """
    invalidas, validas, vistas = [], [], set()
    for i, cruda in enumerate(filas):
        fila, errores = validar_fila(cruda)
        if errores:
            invalidas.append({'fila': i + 1, 'datos': {'nombre': (cruda or {}).get('nombre') if isinstance(cruda, dict) else None}, 'errores': errores})
            continue
        if fila['cedula'] in vistas:
            continue  # repetida en el archivo
        vistas.add(fila['cedula'])
        validas.append(fila)

    estudiantes = []
    for f in validas:
        existente = personas.get(f['cedula'])
        item = {'cedula': f['cedula'], 'nombre': f['nombre'], 'nombreActual': None, 'motivo': None}
        if existente is None:
            item['accion'] = 'crear'
        elif existente.get('type') != 'Estudiante':
            item['accion'] = 'conflicto'
            item['motivo'] = 'Esa identificación pertenece a un usuario que no es estudiante; no se modifica.'
        else:
            item['nombreActual'] = existente.get('namePerson')
            item['accion'] = 'ya_inscrito' if f['cedula'] in inscritos else 'inscribir'
            if normalizar_texto(existente.get('namePerson')) != normalizar_texto(f['nombre']):
                item['motivo'] = 'El nombre en el sistema es distinto; se conserva el del sistema.'
        estudiantes.append(item)

    quitar = []
    if sincronizar:
        en_archivo = {f['cedula'] for f in validas}
        for c in sorted(inscritos - en_archivo):
            quitar.append({'cedula': c, 'nombre': (personas.get(c) or {}).get('namePerson') or 'Sin registro'})

    resumen = {
        'filasLeidas': len(filas),
        'filasInvalidas': len(invalidas),
        'porCrear': sum(1 for e in estudiantes if e['accion'] == 'crear'),
        'porInscribir': sum(1 for e in estudiantes if e['accion'] == 'inscribir'),
        'yaInscritos': sum(1 for e in estudiantes if e['accion'] == 'ya_inscrito'),
        'conflictos': sum(1 for e in estudiantes if e['accion'] == 'conflicto'),
        'porQuitar': len(quitar),
    }
    resumen['hayCambios'] = bool(resumen['porCrear'] or resumen['porInscribir'] or resumen['porQuitar'])
    return {'estudiantes': estudiantes, 'quitar': quitar, 'filasInvalidas': invalidas, 'resumen': resumen}


def validar_curso(nombre, grupo, codigo=None):
    """Devuelve (datos | None, [errores]) para crear/editar un curso."""
    errores = []
    nombre = re.sub(r'\s+', ' ', str(nombre or '')).strip()
    grupo = re.sub(r'\s+', ' ', str(grupo or '')).strip()
    codigo = str(codigo or '').strip()
    if not (3 <= len(nombre) <= 200):
        errores.append('El nombre del curso debe tener entre 3 y 200 caracteres.')
    if not (1 <= len(grupo) <= 100):
        errores.append('El grupo es obligatorio (máximo 100 caracteres).')
    if codigo and not re.fullmatch(r'[A-Za-z0-9_-]{3,40}', codigo):
        errores.append('El código solo puede tener letras, números, guion y guion bajo (3 a 40 caracteres).')
    if errores:
        return None, errores
    return {'nombre': nombre, 'grupo': grupo, 'codigo': codigo or None}, []
