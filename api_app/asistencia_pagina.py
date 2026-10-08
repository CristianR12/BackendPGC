"""
Asistencias de una sesión, por páginas.

Lógica pura (sin Firestore) para que el Inicio cargue una sección a la vez en lugar de todo el historial.
Una "sesión" es un día de clase de una unidad (curso o subgrupo): `assistances/{AAAA-MM-DD}` con una
cédula por campo. La sesión se elige así:
  1. Si se pide una fecha, esa.
  2. Si se pide solo un día de la semana, la más reciente de ese día (sin pasar de hoy).
  3. Si no se pide nada: la de hoy cuando hay una clase en curso o por empezar; si no, la última.
"""
from datetime import datetime

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
TAMANO_POR_DEFECTO = 10
TAMANO_MAXIMO = 50
# El reconocimiento facial admite llegadas desde unos minutos antes de la clase
MARGEN_ANTES_MIN = 15


def dia_de_fecha(iso):
    """'2026-03-02' -> 'Lunes' (sin depender de la zona horaria)."""
    return DIAS[datetime.strptime(iso, '%Y-%m-%d').weekday()]


def fecha_valida(valor):
    try:
        datetime.strptime(str(valor), '%Y-%m-%d')
        return True
    except ValueError:
        return False


def resolver_fecha(fechas, hoy, fecha=None, dia=None, en_ventana=False):
    """Fecha de la sesión a mostrar, o None si no hay ninguna."""
    if fecha:
        return fecha
    candidatas = sorted(f for f in fechas if f and fecha_valida(f))
    if dia:
        previas = [f for f in candidatas if f <= hoy and dia_de_fecha(f) == dia]
        return previas[-1] if previas else None
    if en_ventana:
        return hoy
    return candidatas[-1] if candidatas else None


def _minutos(hm):
    try:
        h, m = str(hm or '').strip().split(':')[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def filtrar_por_franja(filas, schedule, fecha, franja):
    """
    Deja a quienes se registraron durante la clase 'HH:MM-HH:MM' y a quienes no tienen hora de registro
    (ausentes y con excusa: su asistencia es de la fecha completa). Devuelve (filas, fuera_de_franja).
    """
    if not franja:
        return filas, 0
    dia = dia_de_fecha(fecha)
    clase = next((c for c in schedule or [] if c.get('day') == dia and f"{c.get('iniTime')}-{c.get('endTime')}" == franja), None)
    if clase is None:
        return filas, 0
    desde = (_minutos(clase.get('iniTime')) or 0) - MARGEN_ANTES_MIN
    hasta = _minutos(clase.get('endTime'))
    hasta = 24 * 60 if hasta is None else hasta
    dentro = []
    for f in filas:
        m = _minutos(f.get('horaRegistro'))
        if m is None or desde <= m <= hasta:
            dentro.append(f)
    return dentro, len(filas) - len(dentro)


def resumen(filas):
    return {
        'total': len(filas),
        'presentes': sum(1 for f in filas if f.get('estadoAsistencia') == 'Presente'),
        'ausentes': sum(1 for f in filas if f.get('estadoAsistencia') == 'Ausente'),
        'conExcusa': sum(1 for f in filas if f.get('estadoAsistencia') == 'Tiene Excusa'),
    }


def numero_positivo(valor, defecto, maximo=None):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return defecto
    if n < 1:
        return defecto
    return min(n, maximo) if maximo else n


def paginar(items, pagina, tamano):
    """(items de la página, página real, total de páginas). Una página fuera de rango se acota."""
    total_paginas = max(1, -(-len(items) // tamano))
    pagina = min(max(1, pagina), total_paginas)
    inicio = (pagina - 1) * tamano
    return items[inicio:inicio + tamano], pagina, total_paginas


# ----- "Todas las asistencias": filtros, conteos y orden sobre todo el historial del usuario -----

ESTADOS = ('Presente', 'Ausente', 'Tiene Excusa')


def ordenar_recientes(filas):
    """Más recientes primero; dentro de un mismo día, por asignatura y cédula (orden estable entre páginas)."""
    por_nombre = sorted(filas, key=lambda f: (f.get('asignatura') or '', f.get('estudiante') or ''))
    return sorted(por_nombre, key=lambda f: f.get('fechaDocId') or '', reverse=True)


def filtrar(filas, asignatura=None, estado=None, texto=None, nombres=None):
    """Filtra por asignatura, estado y texto (parte del nombre o de la cédula, sin importar mayúsculas)."""
    nombres = nombres or {}
    buscado = str(texto or '').strip().lower()
    salida = []
    for f in filas:
        if asignatura and f.get('asignatura') != asignatura:
            continue
        if estado and f.get('estadoAsistencia') != estado:
            continue
        if buscado and buscado not in str(f.get('estudiante') or '').lower() \
                and buscado not in str(nombres.get(f.get('estudiante'), '')).lower():
            continue
        salida.append(f)
    return salida


def conteos(filas):
    """Cuántas filas hay por asignatura y por estado (para los botones de filtro)."""
    por_asignatura = {}
    for f in filas:
        nombre = f.get('asignatura')
        if nombre:
            por_asignatura[nombre] = por_asignatura.get(nombre, 0) + 1
    return {
        'asignaturas': [{'nombre': n, 'total': t} for n, t in sorted(por_asignatura.items())],
        'estados': {e: sum(1 for f in filas if f.get('estadoAsistencia') == e) for e in ESTADOS},
    }
