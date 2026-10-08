"""
Estadísticas, consejos y avisos de asistencia.

Lógica pura (sin Firestore): las vistas leen los datos y estas funciones los resumen. Entrada común:

  unidad = {'id', 'nombre', 'estudiantes': {cedula: nombre}, 'sesiones': {'AAAA-MM-DD': {cedula: {estado, hora, late}}}}

Reglas de los avisos (por defecto; ajustables aquí):
  - Recordatorio (estudiante y consejo al docente): 2 o más faltas seguidas, o asistencia por debajo de 80 %
    con al menos 4 clases.
  - Llegadas tarde: 3 o más veces.
  - Incentivo: racha de 5 clases seguidas sin faltar, o asistencia perfecta (sin faltas ni tardanzas, 4+ clases).
  - Aviso CRÍTICO al docente (campanita): 3 o más faltas en una misma semana, o 4 o más seguidas. Solo se avisa
    mientras sea reciente, para no saturar.
Una excusa no cuenta como falta ni como asistencia: no rompe ni alarga las rachas.
"""
from datetime import date, datetime, timedelta

DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
SIGLAS = {'Presente': 'P', 'Ausente': 'A', 'Tiene Excusa': 'E'}

UMBRAL_BAJA_ASISTENCIA = 80
MIN_CLASES_PARA_TASA = 4
FALTAS_SEGUIDAS_RECORDATORIO = 2
TARDES_PARA_CONSEJO = 3
RACHA_INCENTIVO = 5
CRITICA_FALTAS_EN_SEMANA = 3
CRITICA_FALTAS_SEGUIDAS = 4
VIGENCIA_CRITICA_DIAS = 14
MAX_POR_LISTA = 10


def _fecha(iso):
    return datetime.strptime(iso, '%Y-%m-%d').date()


def dia_nombre(iso):
    return DIAS[_fecha(iso).weekday()]


def _lunes(iso):
    f = _fecha(iso)
    return (f - timedelta(days=f.weekday())).isoformat()


def primer_nombre(nombre):
    """'ARDILA AMAYA DAYANNA VANESSA' -> 'Dayanna' (en Academusoft va apellido primero)."""
    partes = str(nombre or '').split()
    if len(partes) >= 3:
        return partes[2].capitalize()
    return partes[0].capitalize() if partes else 'estudiante'


# ----- secuencias por estudiante -----

def secuencia_de(unidad, cedula, desde=None, hasta=None):
    """[(fecha, estado, late)] de un estudiante, en orden, solo de las clases en que tiene registro."""
    filas = []
    for fecha in sorted(unidad['sesiones']):
        if (desde and fecha < desde) or (hasta and fecha > hasta):
            continue
        r = unidad['sesiones'][fecha].get(cedula)
        if isinstance(r, dict):
            filas.append((fecha, r.get('estado') or 'Presente', bool(r.get('late'))))
    return filas


def analizar(secuencia):
    """Métricas de un estudiante a partir de su secuencia [(fecha, estado, late)]."""
    presentes = sum(1 for _, e, _ in secuencia if e == 'Presente')
    ausentes = sum(1 for _, e, _ in secuencia if e == 'Ausente')
    excusas = sum(1 for _, e, _ in secuencia if e == 'Tiene Excusa')
    tardes = [f for f, e, late in secuencia if late and e == 'Presente']

    seguidas = 0
    for _, e, _ in reversed(secuencia):
        if e == 'Ausente':
            seguidas += 1
        elif e == 'Presente':
            break
    racha = 0
    for _, e, _ in reversed(secuencia):
        if e == 'Presente':
            racha += 1
        elif e == 'Ausente':
            break

    por_semana = {}
    for f, e, _ in secuencia:
        if e == 'Ausente':
            por_semana.setdefault(_lunes(f), []).append(f)
    peor_semana = max(por_semana.items(), key=lambda kv: (len(kv[1]), kv[0])) if por_semana else None

    dias_tarde = {}
    for f in tardes:
        dias_tarde[dia_nombre(f)] = dias_tarde.get(dia_nombre(f), 0) + 1
    dia_frecuente = max(dias_tarde.items(), key=lambda kv: kv[1]) if dias_tarde else None

    return {
        'sesiones': len(secuencia), 'presentes': presentes, 'ausentes': ausentes, 'excusas': excusas,
        'tardes': len(tardes), 'tasa': round(presentes * 100 / len(secuencia), 1) if secuencia else None,
        'faltasSeguidas': seguidas, 'rachaPresente': racha,
        'peorSemana': {'lunes': peor_semana[0], 'faltas': len(peor_semana[1]), 'ultima': max(peor_semana[1])} if peor_semana else None,
        'diaTarde': {'dia': dia_frecuente[0], 'veces': dia_frecuente[1]} if dia_frecuente and dia_frecuente[1] >= 2 else None,
        'ultimaFecha': secuencia[-1][0] if secuencia else None,
    }


# ----- estadísticas del conjunto -----

def _registros(unidad, desde=None, hasta=None):
    for fecha in sorted(unidad['sesiones']):
        if (desde and fecha < desde) or (hasta and fecha > hasta):
            continue
        for cedula, r in unidad['sesiones'][fecha].items():
            if isinstance(r, dict):
                yield fecha, cedula, r.get('estado') or 'Presente', bool(r.get('late'))


def resumen_general(unidades, desde=None, hasta=None):
    total = presentes = ausentes = excusas = tardes = 0
    sesiones, alumnos = set(), set()
    for u in unidades:
        for fecha, cedula, estado, late in _registros(u, desde, hasta):
            total += 1
            sesiones.add((u['id'], fecha))
            alumnos.add((u['id'], cedula))
            presentes += estado == 'Presente'
            ausentes += estado == 'Ausente'
            excusas += estado == 'Tiene Excusa'
            tardes += late and estado == 'Presente'
    return {
        'total': total, 'presentes': presentes, 'ausentes': ausentes, 'excusas': excusas, 'tardes': tardes,
        'tasa': round(presentes * 100 / total, 1) if total else None,
        'sesiones': len(sesiones), 'estudiantes': len({c for _, c in alumnos}),
    }


def tendencia(unidades, desde=None, hasta=None):
    """Una fila por fecha (suma de las unidades): presentes, ausentes, excusas y tasa."""
    por_fecha = {}
    for u in unidades:
        for fecha, _, estado, _ in _registros(u, desde, hasta):
            f = por_fecha.setdefault(fecha, {'fecha': fecha, 'presentes': 0, 'ausentes': 0, 'excusas': 0, 'total': 0})
            f['total'] += 1
            f['presentes'] += estado == 'Presente'
            f['ausentes'] += estado == 'Ausente'
            f['excusas'] += estado == 'Tiene Excusa'
    filas = []
    for fecha in sorted(por_fecha):
        f = por_fecha[fecha]
        f['tasa'] = round(f['presentes'] * 100 / f['total'], 1) if f['total'] else 0
        filas.append(f)
    return filas


def por_dia_semana(unidades, desde=None, hasta=None):
    acumulado = {d: {'dia': d, 'presentes': 0, 'ausentes': 0, 'excusas': 0, 'total': 0} for d in DIAS}
    for u in unidades:
        for fecha, _, estado, _ in _registros(u, desde, hasta):
            f = acumulado[dia_nombre(fecha)]
            f['total'] += 1
            f['presentes'] += estado == 'Presente'
            f['ausentes'] += estado == 'Ausente'
            f['excusas'] += estado == 'Tiene Excusa'
    filas = []
    for d in DIAS:
        f = acumulado[d]
        if f['total']:
            f['tasa'] = round(f['presentes'] * 100 / f['total'], 1)
            filas.append(f)
    return filas


def por_curso(unidades, desde=None, hasta=None):
    filas = []
    for u in unidades:
        r = resumen_general([u], desde, hasta)
        if r['total']:
            filas.append({'unidadId': u['id'], 'nombre': u['nombre'], **{k: r[k] for k in ('total', 'presentes', 'ausentes', 'excusas', 'tasa')}})
    return sorted(filas, key=lambda f: f['nombre'])


def mapa_de_calor(unidad, desde=None, hasta=None):
    """Estudiantes (filas) por clase (columnas): P, A, E o '-'. Los de más inasistencias, primero."""
    fechas = [f for f in sorted(unidad['sesiones']) if not ((desde and f < desde) or (hasta and f > hasta))]
    filas = []
    for cedula, nombre in unidad['estudiantes'].items():
        celdas = []
        for f in fechas:
            r = unidad['sesiones'][f].get(cedula)
            celdas.append(SIGLAS.get((r or {}).get('estado'), '-') if isinstance(r, dict) else '-')
        filas.append({'cedula': cedula, 'nombre': nombre, 'celdas': celdas, 'faltas': celdas.count('A')})
    filas.sort(key=lambda f: (-f['faltas'], f['nombre']))
    return {'fechas': fechas, 'filas': filas}


# ----- consejos -----

def _etiqueta_curso(unidad):
    return unidad['nombre']


def consejos_docente(unidades, desde=None, hasta=None):
    """Tres listas para el docente: recordatorios, consejos por tardanzas e incentivos."""
    recordatorios, tardanzas, incentivos = [], [], []
    for u in unidades:
        for cedula, nombre in u['estudiantes'].items():
            a = analizar(secuencia_de(u, cedula, desde, hasta))
            if a['sesiones'] == 0:
                continue
            base = {'cedula': cedula, 'nombre': nombre, 'curso': _etiqueta_curso(u), 'unidadId': u['id']}
            nom = primer_nombre(nombre)

            if a['faltasSeguidas'] >= FALTAS_SEGUIDAS_RECORDATORIO:
                recordatorios.append({**base, 'motivo': f"{a['faltasSeguidas']} faltas seguidas", 'prioridad': 1000 + a['faltasSeguidas'],
                                      'detalle': f"Su última asistencia fue antes de {a['faltasSeguidas']} clases; lleva {a['ausentes']} faltas en total ({a['tasa']} % de asistencia).",
                                      'mensaje': f"Hola {nom}, notamos que has faltado a las últimas {a['faltasSeguidas']} clases de {u['nombre']}. ¿Todo bien? Si necesitas ayuda para ponerte al día, escríbeme y lo resolvemos."})
            elif a['tasa'] is not None and a['sesiones'] >= MIN_CLASES_PARA_TASA and a['tasa'] < UMBRAL_BAJA_ASISTENCIA:
                recordatorios.append({**base, 'motivo': f"Asistencia de {a['tasa']} %", 'prioridad': 100 - a['tasa'],
                                      'detalle': f"Ha asistido a {a['presentes']} de {a['sesiones']} clases.",
                                      'mensaje': f"Hola {nom}, vas con {a['tasa']} % de asistencia en {u['nombre']}. Quiero ayudarte a recuperar el ritmo: cuéntame si hay algo que te impida venir."})

            if a['tardes'] >= TARDES_PARA_CONSEJO:
                patron = f" Suele ocurrir los {a['diaTarde']['dia']}." if a['diaTarde'] else ''
                tardanzas.append({**base, 'veces': a['tardes'], 'dia': a['diaTarde']['dia'] if a['diaTarde'] else None,
                                  'detalle': f"Llegó tarde {a['tardes']} veces en {a['sesiones']} clases.{patron}",
                                  'consejo': ('Conversa con la persona para entender la causa (transporte, horario de trabajo u otra clase). '
                                              'Si es recurrente, acuerden un margen: avisar al llegar o entrar en silencio sin perder la sesión.'),
                                  'mensaje': f"Hola {nom}, he visto que has llegado tarde a varias clases de {u['nombre']}. Salir 10 minutos antes te ayudaría a no perderte el inicio. ¿Te puedo ayudar en algo?"})

            if a['ausentes'] == 0 and a['tardes'] == 0 and a['sesiones'] >= MIN_CLASES_PARA_TASA:
                incentivos.append({**base, 'racha': a['rachaPresente'], 'tipo': 'perfecta', 'insignia': 'Asistencia perfecta',
                                   'detalle': f"{a['presentes']} clases sin una sola falta ni tardanza.",
                                   'mensaje': f"¡Felicitaciones {nom}! Vas con asistencia perfecta en {u['nombre']}: {a['presentes']} clases sin faltar ni llegar tarde. ¡Sigue así!"})
            elif a['rachaPresente'] >= RACHA_INCENTIVO and a['ausentes'] == 0 and a['tardes'] < TARDES_PARA_CONSEJO:
                incentivos.append({**base, 'racha': a['rachaPresente'], 'tipo': 'racha', 'insignia': 'Racha de asistencia',
                                   'detalle': f"{a['rachaPresente']} clases seguidas sin faltar.",
                                   'mensaje': f"¡Muy bien {nom}! Llevas {a['rachaPresente']} clases seguidas asistiendo a {u['nombre']}. ¡Gracias por tu constancia!"})
    recordatorios.sort(key=lambda r: -r['prioridad'])
    tardanzas.sort(key=lambda r: -r['veces'])
    incentivos.sort(key=lambda r: -r['racha'])
    for lista in (recordatorios, tardanzas, incentivos):
        del lista[MAX_POR_LISTA:]
    return {'recordatorios': recordatorios, 'tardanzas': tardanzas, 'incentivos': incentivos}


# ----- avisos de la campanita -----

def alertas_criticas_docente(unidades, hoy):
    """
    Solo casos críticos y recientes: 3 o más faltas en una misma semana, o 4 o más seguidas. Cada aviso tiene
    un id estable (cambia cuando el caso se agrava) para que no se repita ni se pierda al leerlo.
    """
    limite = (_fecha(hoy) - timedelta(days=VIGENCIA_CRITICA_DIAS)).isoformat()
    avisos = []
    for u in unidades:
        for cedula, nombre in u['estudiantes'].items():
            a = analizar(secuencia_de(u, cedula, hasta=hoy))
            if a['sesiones'] == 0:
                continue
            semana = a['peorSemana']
            if semana and semana['faltas'] >= CRITICA_FALTAS_EN_SEMANA and semana['ultima'] >= limite:
                avisos.append({
                    'id': f"semana:{u['id']}:{cedula}:{semana['lunes']}:{semana['faltas']}", 'tipo': 'critica',
                    'titulo': f"{nombre}: {semana['faltas']} faltas en una semana",
                    'texto': f"En {u['nombre']}, la semana del {semana['lunes']}. Conviene contactarle pronto.",
                    'fecha': semana['ultima'], 'cedula': cedula, 'unidadId': u['id'],
                })
            elif a['faltasSeguidas'] >= CRITICA_FALTAS_SEGUIDAS and a['ultimaFecha'] >= limite:
                avisos.append({
                    'id': f"seguidas:{u['id']}:{cedula}:{a['ultimaFecha']}:{a['faltasSeguidas']}", 'tipo': 'critica',
                    'titulo': f"{nombre}: {a['faltasSeguidas']} faltas seguidas",
                    'texto': f"En {u['nombre']}. Podría estar en riesgo de abandonar el curso.",
                    'fecha': a['ultimaFecha'], 'cedula': cedula, 'unidadId': u['id'],
                })
    avisos.sort(key=lambda x: x['fecha'], reverse=True)
    return avisos


def avisos_estudiante(unidades, cedula, hoy):
    """Recordatorios, consejos e incentivos para el propio estudiante (solo ve lo suyo)."""
    avisos = []
    for u in unidades:
        a = analizar(secuencia_de(u, cedula, hasta=hoy))
        if a['sesiones'] == 0:
            continue
        curso, ultima = u['nombre'], a['ultimaFecha']
        if a['faltasSeguidas'] >= FALTAS_SEGUIDAS_RECORDATORIO:
            avisos.append({'id': f"seguidas:{u['id']}:{ultima}:{a['faltasSeguidas']}", 'tipo': 'recordatorio', 'fecha': ultima,
                           'titulo': f"Llevas {a['faltasSeguidas']} faltas seguidas en {curso}",
                           'texto': 'No te quedes atrás: habla con tu docente para ponerte al día y justifica la ausencia si tuviste un motivo.'})
        elif a['tasa'] is not None and a['sesiones'] >= MIN_CLASES_PARA_TASA and a['tasa'] < UMBRAL_BAJA_ASISTENCIA:
            avisos.append({'id': f"baja:{u['id']}:{ultima}:{int(a['tasa'])}", 'tipo': 'recordatorio', 'fecha': ultima,
                           'titulo': f"Tu asistencia en {curso} es de {a['tasa']} %",
                           'texto': f"Has asistido a {a['presentes']} de {a['sesiones']} clases. Recuperar el ritmo todavía está en tus manos."})
        if a['tardes'] >= TARDES_PARA_CONSEJO:
            dia = f" sobre todo los {a['diaTarde']['dia']}" if a['diaTarde'] else ''
            avisos.append({'id': f"tarde:{u['id']}:{a['tardes']}", 'tipo': 'consejo', 'fecha': ultima,
                           'titulo': f"Has llegado tarde {a['tardes']} veces a {curso}",
                           'texto': f"Te pasa{dia}. Intenta salir 10 minutos antes para no perderte el inicio de la clase."})
        if a['ausentes'] == 0 and a['tardes'] == 0 and a['sesiones'] >= MIN_CLASES_PARA_TASA:
            avisos.append({'id': f"perfecta:{u['id']}:{a['sesiones']}", 'tipo': 'incentivo', 'fecha': ultima,
                           'titulo': f"¡Asistencia perfecta en {curso}!",
                           'texto': f"{a['presentes']} clases sin faltar ni llegar tarde. Gracias por tu constancia."})
        elif a['rachaPresente'] >= RACHA_INCENTIVO and a['ausentes'] == 0 and a['tardes'] < TARDES_PARA_CONSEJO:
            avisos.append({'id': f"racha:{u['id']}:{a['rachaPresente']}", 'tipo': 'incentivo', 'fecha': ultima,
                           'titulo': f"¡{a['rachaPresente']} clases seguidas en {curso}!",
                           'texto': 'Llevas una racha sin faltar. ¡Sigue así!'})
    avisos.sort(key=lambda x: x['fecha'], reverse=True)
    return avisos
