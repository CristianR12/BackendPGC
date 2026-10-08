"""
Importación de horarios (Excel / PDF de Academusoft).

El navegador lee el archivo y envía filas ya estructuradas. Este módulo valida las filas,
las empareja con los cursos del profesor y calcula un plan (vista previa). No toca Firestore:
las funciones son puras para poder probarlas; la escritura la hace la vista.

Fila de entrada:   {curso, grupo, day, iniTime, endTime, classroom}
Clase guardada:    {classroom, day, iniTime, endTime}   (mismo formato que usa el módulo de reconocimiento)
"""
import re
import unicodedata

from .horario_unidades import id_unidad

MODOS = ('combinar', 'reemplazar')
MAX_FILAS = 500
SIN_SALON = 'NREF'  # convención de Academusoft: el grupo no tiene recurso físico asignado

_DIAS = {
    'lunes': 'Lunes', 'lun': 'Lunes',
    'martes': 'Martes', 'mar': 'Martes',
    'miercoles': 'Miércoles', 'mie': 'Miércoles',
    'jueves': 'Jueves', 'jue': 'Jueves',
    'viernes': 'Viernes', 'vie': 'Viernes',
    'sabado': 'Sábado', 'sab': 'Sábado',
    'domingo': 'Domingo', 'dom': 'Domingo',
}
_ORDEN_DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

_CODIGO_CURSO = re.compile(r'^[A-Za-z]{2,5}\d{5,}[A-Za-z0-9]*\s*-\s*')


def normalizar_texto(valor):
    """Minúsculas, sin tildes ni signos, espacios colapsados. Sirve para comparar nombres."""
    if valor is None:
        return ''
    s = unicodedata.normalize('NFKD', str(valor))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return s.strip()


def limpiar_nombre_curso(valor):
    """Quita el código de Academusoft: 'CAD612021520 - SISTEMAS OPERATIVOS' -> 'SISTEMAS OPERATIVOS'."""
    s = re.sub(r'\s+', ' ', str(valor or '')).strip()
    return _CODIGO_CURSO.sub('', s).strip()


def normalizar_dia(valor):
    return _DIAS.get(normalizar_texto(valor))


def normalizar_hora(valor):
    """Acepta '7:00', '07:00', '07:00:00'. Devuelve 'HH:MM' o None."""
    m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*', str(valor or ''))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f'{h:02d}:{mi:02d}'


def _minutos(hhmm):
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def validar_fila(fila):
    """Devuelve (fila_normalizada | None, [errores])."""
    errores = []
    if not isinstance(fila, dict):
        return None, ['La fila no es válida.']

    curso = limpiar_nombre_curso(fila.get('curso'))
    grupo = re.sub(r'\s+', ' ', str(fila.get('grupo') or '')).strip()
    dia = normalizar_dia(fila.get('day'))
    ini = normalizar_hora(fila.get('iniTime'))
    fin = normalizar_hora(fila.get('endTime'))
    salon = re.sub(r'\s+', ' ', str(fila.get('classroom') or '')).strip() or SIN_SALON
    # Código de Academusoft (opcional): si es inválido simplemente se ignora
    codigo = str(fila.get('codigo') or '').strip()
    codigo = codigo if re.fullmatch(r'[A-Za-z0-9_-]{3,40}', codigo) else None

    if not curso:
        errores.append('Falta el nombre del curso.')
    if not grupo:
        errores.append('Falta el grupo.')
    if not dia:
        errores.append(f"Día no reconocido: '{fila.get('day')}'.")
    if not ini:
        errores.append(f"Hora de inicio inválida: '{fila.get('iniTime')}'.")
    if not fin:
        errores.append(f"Hora de fin inválida: '{fila.get('endTime')}'.")
    if ini and fin and _minutos(ini) >= _minutos(fin):
        errores.append('La hora de inicio debe ser anterior a la hora de fin.')
    if len(curso) > 200 or len(grupo) > 100 or len(salon) > 100:
        errores.append('Algún texto es demasiado largo.')

    if errores:
        return None, errores
    return {'curso': curso, 'grupo': grupo, 'day': dia, 'iniTime': ini, 'endTime': fin, 'classroom': salon, 'codigo': codigo}, []


def _clase(fila):
    return {'classroom': fila['classroom'], 'day': fila['day'], 'iniTime': fila['iniTime'], 'endTime': fila['endTime']}


def _llave(clase):
    return (clase['day'], clase['iniTime'], clase['endTime'])


def _ordenar(clases):
    return sorted(clases, key=lambda c: (_ORDEN_DIAS.index(c['day']) if c['day'] in _ORDEN_DIAS else 99, c['iniTime']))


def _solapan(a, b):
    return a['day'] == b['day'] and _minutos(a['iniTime']) < _minutos(b['endTime']) and _minutos(a['endTime']) > _minutos(b['iniTime'])


def _buscar_curso(fila, cursos):
    """Devuelve (curso | None, aproximado: bool, similares: [cursos con igual nombre y otro grupo])."""
    nombre, grupo = normalizar_texto(fila['curso']), normalizar_texto(fila['grupo'])
    # Con código de Academusoft el emparejamiento es exacto, aunque el nombre se escriba distinto
    if fila.get('codigo'):
        for c in cursos:
            if (c.get('courseId') or c['id']) == fila['codigo'] and normalizar_texto(c.get('group')) == grupo:
                return c, False, []
    mismos = [c for c in cursos if normalizar_texto(c.get('nameCourse')) == nombre]
    for c in mismos:
        if normalizar_texto(c.get('group')) == grupo:
            return c, False, []
    # grupo aproximado: '501' contra '501 ISC UBT' (o al revés), solo si es inequívoco
    parecidos = []
    for c in mismos:
        g = normalizar_texto(c.get('group'))
        if g and grupo and (g.startswith(grupo + ' ') or grupo.startswith(g + ' ')):
            parecidos.append(c)
    if len(parecidos) == 1:
        return parecidos[0], True, []
    return None, False, mismos


def _gid(grupo):
    """Id de documento válido para un subgrupo (Firestore no admite '/', '.', '..' ni '__x__'). None si no sirve."""
    g = re.sub(r'\s+', ' ', str(grupo or '')).replace('/', '-').strip()
    if not g or g in ('.', '..') or (g.startswith('__') and g.endswith('__')) or len(g) > 100:
        return None
    return g


def _curso_padre(fila, cursos):
    """
    Curso al que pertenecería un grupo nuevo: aquel del que el profesor YA tiene otro grupo (mismo código de
    Academusoft o mismo nombre). Devuelve (id del curso | None, hermanos). Es None si no hay hermanos o si
    son de varios cursos distintos (ambiguo).
    """
    codigo = fila.get('codigo')
    nombre = normalizar_texto(fila['curso'])
    hermanos = [
        c for c in cursos
        if (codigo and (c.get('courseId') or c['id']) == codigo) or normalizar_texto(c.get('nameCourse')) == nombre
    ]
    padres = {(c.get('courseId') or c['id']) for c in hermanos}
    return (next(iter(padres)) if len(padres) == 1 else None), hermanos


def planificar(filas, cursos, modo='combinar', crear_faltantes=False, archivar_otros=False):
    """
    filas:   lista de dicts crudos enviados por el navegador.
    cursos:  unidades de horario EDITABLES del profesor [{id, nameCourse, group, schedule}].
    archivar_otros: las unidades que NO aparecen en el archivo y tienen clases se archivan
             (se les quita el horario, así ya no se toma asistencia; sus asistencias no se tocan).
    Devuelve el plan completo (se usa tanto para la vista previa como para aplicar).
    """
    if modo not in MODOS:
        modo = 'combinar'

    invalidas, validas, vistos = [], [], set()
    for i, cruda in enumerate(filas):
        fila, errores = validar_fila(cruda)
        if errores:
            invalidas.append({'fila': i + 1, 'datos': cruda if isinstance(cruda, dict) else {}, 'errores': errores})
            continue
        clave = (normalizar_texto(fila['curso']), normalizar_texto(fila['grupo']), *_llave(fila))
        if clave in vistos:
            continue  # fila repetida en el archivo
        vistos.add(clave)
        validas.append(fila)

    # agrupar por (curso, grupo)
    grupos = {}
    for f in validas:
        grupos.setdefault((normalizar_texto(f['curso']), normalizar_texto(f['grupo'])), []).append(f)

    # Un grupo nuevo de un curso que el profesor ya tiene NO es un curso aparte: es un subgrupo de ese curso.
    # Si el curso tiene un solo grupo, primero hay que convertirlo en curso con subgrupos (su grupo actual
    # pasa a ser un subgrupo). Desde aquí se trabaja con la unidad ya convertida.
    convertir = {}
    if crear_faltantes:
        for filas_grupo in grupos.values():
            base = filas_grupo[0]
            if _buscar_curso(base, cursos)[0] is not None or not _gid(base['grupo']):
                continue
            padre, hermanos = _curso_padre(base, cursos)
            if padre is None:
                continue
            for h in hermanos:
                if (h.get('courseId') or h['id']) == padre and not h.get('groupId') and _gid(h.get('group')):
                    convertir[h['id']] = h
    ids_existentes = {c['id'] for c in cursos}
    cursos_t, conversiones = [], []
    for c in cursos:
        curso_id = c.get('courseId') or c['id']
        nuevo_id = id_unidad(curso_id, _gid(c.get('group'))) if c['id'] in convertir else None
        if nuevo_id and nuevo_id not in ids_existentes:
            cursos_t.append({**c, 'id': nuevo_id, 'courseId': curso_id, 'groupId': _gid(c.get('group'))})
            conversiones.append({
                'desde': c['id'], 'hacia': nuevo_id, 'courseId': curso_id, 'groupId': _gid(c.get('group')),
                'nameCourse': c.get('nameCourse'), 'group': c.get('group'),
                'clases': len(c.get('schedule') or []), 'estudiantes': len(c.get('estudianteID') or []),
            })
        else:
            cursos_t.append(c)
    cursos = cursos_t

    planes = []
    for filas_grupo in grupos.values():
        base = filas_grupo[0]
        curso, aproximado, similares = _buscar_curso(base, cursos)
        entrantes = _ordenar([_clase(f) for f in filas_grupo])

        if curso is None and crear_faltantes:
            padre, hermanos = _curso_padre(base, cursos)
            if padre is not None and _gid(base['grupo']):
                planes.append({
                    'accion': 'subgrupo',
                    'courseId': None,
                    'cursoPadre': padre,
                    'groupId': _gid(base['grupo']),
                    'codigo': None,
                    'nameCourse': next((h.get('nameCourse') for h in hermanos if (h.get('courseId') or h['id']) == padre), base['curso']),
                    'group': base['grupo'],
                    'aproximado': False,
                    'motivo': None,
                    'similares': [],
                    'nuevas': entrantes, 'iguales': [], 'cambiosSalon': [], 'soloEnSistema': [],
                    'resultado': entrantes,
                })
                continue

        if curso is None:
            planes.append({
                'accion': 'crear' if crear_faltantes else 'omitir',
                'courseId': None,
                'codigo': base.get('codigo'),
                'nameCourse': base['curso'],
                'group': base['grupo'],
                'aproximado': False,
                'motivo': None if crear_faltantes else 'No existe un curso con ese nombre y grupo.',
                'similares': [{'id': c['id'], 'nameCourse': c.get('nameCourse'), 'group': c.get('group')} for c in similares],
                'nuevas': entrantes if crear_faltantes else [],
                'iguales': [], 'cambiosSalon': [], 'soloEnSistema': [],
                'resultado': entrantes if crear_faltantes else [],
            })
            continue

        existentes = list(curso.get('schedule') or [])
        por_llave = {_llave(c): c for c in existentes}
        nuevas, iguales, cambios = [], [], []
        for c in entrantes:
            actual = por_llave.get(_llave(c))
            if actual is None:
                nuevas.append(c)
            elif actual.get('classroom') == c['classroom']:
                iguales.append(c)
            else:
                cambios.append({**c, 'salonAnterior': actual.get('classroom')})
        llaves_archivo = {_llave(c) for c in entrantes}
        solo_sistema = [c for c in existentes if _llave(c) not in llaves_archivo]

        if modo == 'reemplazar':
            resultado = entrantes
        else:
            cambios_por_llave = {_llave(c): c for c in cambios}
            resultado = []
            for c in existentes:
                cambio = cambios_por_llave.get(_llave(c))
                resultado.append({**c, 'classroom': cambio['classroom']} if cambio else dict(c))
            resultado.extend(nuevas)

        planes.append({
            'accion': 'actualizar',
            'courseId': curso['id'],
            'nameCourse': curso.get('nameCourse'),
            'group': curso.get('group'),
            'aproximado': aproximado,
            'motivo': None,
            'similares': [],
            'nuevas': nuevas, 'iguales': iguales, 'cambiosSalon': cambios, 'soloEnSistema': solo_sistema,
            'resultado': _ordenar(resultado),
        })

    if archivar_otros:
        usados = {p['courseId'] for p in planes if p['courseId']}
        for c in cursos:
            if c['id'] in usados or not (c.get('schedule') or []):
                continue
            planes.append({
                'accion': 'archivar',
                'courseId': c['id'],
                'nameCourse': c.get('nameCourse'),
                'group': c.get('group'),
                'aproximado': False,
                'motivo': None,
                'similares': [],
                'nuevas': [], 'iguales': [], 'cambiosSalon': [],
                'soloEnSistema': _ordenar(list(c.get('schedule') or [])),
                'resultado': [],
            })

    conflictos = _detectar_conflictos(planes, cursos)

    advertencias = []
    for p in planes:
        if p['accion'] in ('actualizar', 'crear'):
            for c in p['resultado']:
                if c.get('classroom') == SIN_SALON:
                    advertencias.append({
                        'tipo': 'sin_salon', 'curso': p['nameCourse'], 'group': p['group'],
                        'day': c['day'], 'iniTime': c['iniTime'], 'endTime': c['endTime'],
                    })

    return {
        'modo': modo,
        'cursos': planes,
        'filasInvalidas': invalidas,
        'conflictos': conflictos,
        'advertencias': advertencias,
        'conversiones': conversiones,
        'resumen': {
            'filasLeidas': len(filas),
            'filasValidas': len(validas),
            'filasInvalidas': len(invalidas),
            'cursosActualizados': sum(1 for p in planes if p['accion'] == 'actualizar'),
            'cursosNuevos': sum(1 for p in planes if p['accion'] == 'crear'),
            'cursosOmitidos': sum(1 for p in planes if p['accion'] == 'omitir'),
            'cursosArchivados': sum(1 for p in planes if p['accion'] == 'archivar'),
            'subgruposNuevos': sum(1 for p in planes if p['accion'] == 'subgrupo'),
            'cursosConvertidos': len(conversiones),
            'clasesNuevas': sum(len(p['nuevas']) for p in planes if p['accion'] != 'omitir'),
            'hayCambios': any(
                p['accion'] in ('crear', 'archivar', 'subgrupo') or p['nuevas'] or p['cambiosSalon']
                or (modo == 'reemplazar' and p['soloEnSistema'])
                for p in planes if p['accion'] != 'omitir'
            ),
        },
    }


def _detectar_conflictos(planes, cursos):
    """
    Cruces entre clases del profesor en el horario RESULTANTE. Solo se reportan los que
    involucran alguna clase nueva o modificada por la importación (no los que ya existían).
    """
    aplicados = {p['courseId']: p for p in planes if p['accion'] in ('actualizar', 'archivar')}
    todas = []  # (etiqueta, clase, es_cambio)
    for p in planes:
        if p['accion'] == 'omitir':
            continue
        nuevas = {_llave(c) for c in p['nuevas']} | {_llave(c) for c in p['cambiosSalon']}
        for c in p['resultado']:
            todas.append((f"{p['nameCourse']} ({p['group']})", c, _llave(c) in nuevas))
    for c in cursos:
        if c['id'] in aplicados:
            continue
        for cl in (c.get('schedule') or []):
            try:
                todas.append((f"{c.get('nameCourse')} ({c.get('group')})", cl, False))
            except Exception:
                continue

    conflictos = []
    for i in range(len(todas)):
        for j in range(i + 1, len(todas)):
            (ea, a, ca), (eb, b, cb) = todas[i], todas[j]
            if not (ca or cb):
                continue
            try:
                if _solapan(a, b):
                    conflictos.append({
                        'dia': a['day'],
                        'a': {'curso': ea, 'iniTime': a['iniTime'], 'endTime': a['endTime']},
                        'b': {'curso': eb, 'iniTime': b['iniTime'], 'endTime': b['endTime']},
                    })
            except (KeyError, ValueError):
                continue
    return conflictos
