"""
Historial de horarios por semestre.

Cada cambio al horario de un profesor (importación, edición manual, clase agregada o
eliminada, curso borrado) deja una entrada en la colección `horarioHistorial` con:
  - periodo:  '2026-1' / '2026-2'
  - cambios:  qué se agregó, quitó o cambió de salón, por curso
  - horario:  foto completa del horario del profesor DESPUÉS del cambio

La vista por semestre es la foto de la última entrada de ese período. Este módulo no toca
Firestore: son funciones puras para poder probarlas.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo('America/Bogota')

TIPOS = (
    'importacion', 'edicion_horario_curso', 'curso_guardado', 'clase_agregada', 'clase_editada',
    'clase_eliminada', 'curso_eliminado', 'horario_eliminado', 'curso_archivado', 'horario_archivado',
    'respaldo_automatico',
)

_ROMANO = {'1': '1', '2': '2', 'i': '1', 'ii': '2'}
_RE_ANIO_PRIMERO = re.compile(r'^(20\d{2})\s*[-/ ]?\s*(1|2|ii|i)$', re.I)
_RE_SEM_PRIMERO = re.compile(r'^(1|2|ii|i)\s*[-/ ]\s*(20\d{2})$', re.I)


def ahora():
    return datetime.now(ZONA)


def periodo_actual(momento=None):
    """Enero-junio = semestre 1, julio-diciembre = semestre 2."""
    momento = momento or ahora()
    return f"{momento.year}-{1 if momento.month <= 6 else 2}"


def periodo_anterior(periodo):
    """'2026-2' -> '2026-1';  '2026-1' -> '2025-2'."""
    anio, sem = (int(x) for x in periodo.split('-'))
    return f"{anio}-1" if sem == 2 else f"{anio - 1}-2"


def periodo_de_respaldo(periodo_nuevo, periodos_con_historial, se_quitan_clases):
    """
    Al importar un horario que QUITA clases, lo que había hasta ahora se guarda solo en el historial.
    Devuelve el período al que pertenece ese horario anterior, o None si no hace falta respaldo:
    el período nuevo ya tiene historial (el horario anterior es de ese mismo semestre y ya quedó registrado),
    o el semestre anterior ya tiene historial (el horario actual ya está en su última entrada).
    """
    if not se_quitan_clases:
        return None
    anterior = periodo_anterior(periodo_nuevo)
    if periodo_nuevo in periodos_con_historial or anterior in periodos_con_historial:
        return None
    return anterior


def normalizar_periodo(valor):
    """'2026-2', '2026 2', '2026/II', '2 - 2026', '20262' -> '2026-2'. None si no es válido."""
    s = str(valor or '').strip()
    m = _RE_ANIO_PRIMERO.match(s)
    if m:
        return f"{m.group(1)}-{_ROMANO[m.group(2).lower()]}"
    m = _RE_SEM_PRIMERO.match(s)
    if m:
        return f"{m.group(2)}-{_ROMANO[m.group(1).lower()]}"
    return None


def resumen_curso(course_id, data):
    """Forma resumida de un curso para fotos y comparaciones."""
    data = data or {}
    return {
        'courseId': course_id,
        'nameCourse': data.get('nameCourse'),
        'group': data.get('group'),
        'schedule': [dict(c) for c in (data.get('schedule') or [])],
    }


def _llave(c):
    return (c.get('day'), c.get('iniTime'), c.get('endTime'))


def _ordenar(clases):
    orden = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return sorted(clases, key=lambda c: (orden.index(c.get('day')) if c.get('day') in orden else 99, c.get('iniTime') or ''))


def calcular_cambios(antes, despues):
    """
    antes / despues: listas de resumen_curso(). Devuelve los cambios por curso:
    {courseId, nameCourse, group, accion: 'creado'|'modificado'|'eliminado',
     agregadas, quitadas, cambiosSalon}
    Los cursos sin diferencias no aparecen.
    """
    a = {c['courseId']: c for c in antes}
    d = {c['courseId']: c for c in despues}
    cambios = []

    for cid, c in d.items():
        if cid not in a:
            cambios.append({
                'courseId': cid, 'nameCourse': c.get('nameCourse'), 'group': c.get('group'), 'accion': 'creado',
                'agregadas': _ordenar(c['schedule']), 'quitadas': [], 'cambiosSalon': [],
            })
            continue
        previas = {_llave(x): x for x in a[cid]['schedule']}
        nuevas = {_llave(x): x for x in c['schedule']}
        agregadas = [x for k, x in nuevas.items() if k not in previas]
        quitadas = [x for k, x in previas.items() if k not in nuevas]
        cambio_salon = [
            {**x, 'salonAnterior': previas[k].get('classroom')}
            for k, x in nuevas.items() if k in previas and previas[k].get('classroom') != x.get('classroom')
        ]
        if agregadas or quitadas or cambio_salon:
            cambios.append({
                'courseId': cid, 'nameCourse': c.get('nameCourse'), 'group': c.get('group'), 'accion': 'modificado',
                'agregadas': _ordenar(agregadas), 'quitadas': _ordenar(quitadas), 'cambiosSalon': _ordenar(cambio_salon),
            })

    for cid, c in a.items():
        if cid not in d:
            cambios.append({
                'courseId': cid, 'nameCourse': c.get('nameCourse'), 'group': c.get('group'), 'accion': 'eliminado',
                'agregadas': [], 'quitadas': _ordenar(c['schedule']), 'cambiosSalon': [],
            })
    return cambios


def resumir_cambios(cambios):
    return {
        'clasesAgregadas': sum(len(c['agregadas']) for c in cambios),
        'clasesQuitadas': sum(len(c['quitadas']) for c in cambios),
        'cambiosSalon': sum(len(c['cambiosSalon']) for c in cambios),
        'cursosCreados': sum(1 for c in cambios if c['accion'] == 'creado'),
        'cursosEliminados': sum(1 for c in cambios if c['accion'] == 'eliminado'),
    }


def construir_entrada(uid, tipo, periodo, cambios, horario, detalle=None, momento=None):
    """Documento listo para guardar en `horarioHistorial`."""
    if tipo not in TIPOS:
        raise ValueError(f'Tipo de historial desconocido: {tipo}')
    periodo = normalizar_periodo(periodo) or periodo_actual(momento)
    return {
        'profesorID': uid,
        'periodo': periodo,
        'tipo': tipo,
        'fecha': (momento or ahora()).isoformat(),
        'detalle': detalle or {},
        'cambios': cambios,
        'resumen': resumir_cambios(cambios),
        'horario': horario,
    }


def aplicar_plan_a_cursos(cursos, plan, ids_creados=None):
    """
    Foto del horario del profesor DESPUÉS de aplicar un plan de importación, sin volver a leer Firestore.
    cursos: resumen_curso() actuales; ids_creados: {(nombre, grupo): id} de los cursos nuevos.
    """
    por_id = {c['courseId']: dict(c, schedule=[dict(x) for x in c['schedule']]) for c in cursos}
    for p in plan['cursos']:
        if p['accion'] in ('actualizar', 'archivar') and p['courseId'] in por_id:
            por_id[p['courseId']]['schedule'] = [dict(x) for x in p['resultado']]
        elif p['accion'] in ('crear', 'subgrupo'):
            nuevo_id = (ids_creados or {}).get((p['nameCourse'], p['group']))
            if nuevo_id:
                por_id[nuevo_id] = {
                    'courseId': nuevo_id, 'nameCourse': p['nameCourse'], 'group': p['group'],
                    'schedule': [dict(x) for x in p['resultado']],
                }
    return list(por_id.values())
