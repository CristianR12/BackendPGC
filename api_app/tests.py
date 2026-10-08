from django.test import SimpleTestCase

from .horario_unidades import id_unidad
from .horario_import import (
    limpiar_nombre_curso,
    normalizar_dia,
    normalizar_hora,
    normalizar_texto,
    planificar,
    validar_fila,
)


def fila(curso='SISTEMAS OPERATIVOS', grupo='501 ISC UBT', day='Lunes', ini='10:00', fin='11:59', salon='C-105'):
    return {'curso': curso, 'grupo': grupo, 'day': day, 'iniTime': ini, 'endTime': fin, 'classroom': salon}


def curso(cid, nombre, grupo, schedule=()):
    return {'id': cid, 'nameCourse': nombre, 'group': grupo, 'schedule': list(schedule)}


def clase(day, ini, fin, salon='C-101'):
    return {'classroom': salon, 'day': day, 'iniTime': ini, 'endTime': fin}


class NormalizacionTests(SimpleTestCase):
    def test_texto_sin_tildes_ni_mayusculas(self):
        self.assertEqual(normalizar_texto('PENSAMIENTO SISTÉMICO Y  AUTOMATIZACIÓN'), 'pensamiento sistemico y automatizacion')

    def test_quita_codigo_academusoft(self):
        self.assertEqual(limpiar_nombre_curso('CAD612021520 - SISTEMAS OPERATIVOS'), 'SISTEMAS OPERATIVOS')
        self.assertEqual(limpiar_nombre_curso('GERENCIA INFORMATICA'), 'GERENCIA INFORMATICA')

    def test_dias(self):
        self.assertEqual(normalizar_dia('miércoles'), 'Miércoles')
        self.assertEqual(normalizar_dia('MIE'), 'Miércoles')
        self.assertEqual(normalizar_dia('Sabado'), 'Sábado')
        self.assertIsNone(normalizar_dia('Lunez'))

    def test_horas(self):
        self.assertEqual(normalizar_hora('7:00'), '07:00')
        self.assertEqual(normalizar_hora('11:59'), '11:59')
        self.assertEqual(normalizar_hora('15:00:00'), '15:00')
        self.assertIsNone(normalizar_hora('25:00'))
        self.assertIsNone(normalizar_hora('abc'))


class ValidacionFilaTests(SimpleTestCase):
    def test_fila_valida_se_normaliza(self):
        f, errores = validar_fila(fila(curso='CAD612021520 - SISTEMAS OPERATIVOS', day='lunes', ini='9:00', fin='10:59'))
        self.assertEqual(errores, [])
        self.assertEqual(f['curso'], 'SISTEMAS OPERATIVOS')
        self.assertEqual((f['day'], f['iniTime'], f['endTime']), ('Lunes', '09:00', '10:59'))

    def test_salon_vacio_usa_nref(self):
        f, _ = validar_fila(fila(salon=''))
        self.assertEqual(f['classroom'], 'NREF')

    def test_errores(self):
        _, errores = validar_fila(fila(day='Xday', ini='12:00', fin='11:00', curso=''))
        self.assertTrue(any('curso' in e for e in errores))
        self.assertTrue(any('Día' in e for e in errores))
        _, errores = validar_fila(fila(ini='12:00', fin='11:00'))
        self.assertTrue(any('anterior' in e for e in errores))


class PlanificarTests(SimpleTestCase):
    def test_empareja_curso_existente_y_agrega_clase(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT')]
        plan = planificar([fila()], cursos)
        p = plan['cursos'][0]
        self.assertEqual((p['accion'], p['courseId']), ('actualizar', 'c1'))
        self.assertEqual(len(p['nuevas']), 1)
        self.assertEqual(p['resultado'], [clase('Lunes', '10:00', '11:59', 'C-105')])
        self.assertTrue(plan['resumen']['hayCambios'])
        self.assertEqual(plan['conflictos'], [])

    def test_emparejamiento_ignora_tildes_y_mayusculas(self):
        cursos = [curso('c1', 'Pensamiento Sistémico', '901 IS UBT')]
        plan = planificar([fila(curso='PENSAMIENTO SISTEMICO', grupo='901 is ubt')], cursos)
        self.assertEqual(plan['cursos'][0]['courseId'], 'c1')

    def test_grupo_aproximado_inequivoco(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT')]
        plan = planificar([fila(grupo='501')], cursos)
        p = plan['cursos'][0]
        self.assertEqual(p['courseId'], 'c1')
        self.assertTrue(p['aproximado'])

    def test_grupo_distinto_no_se_empareja_y_sugiere_similares(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '502 ISC UBT')]
        plan = planificar([fila()], cursos)
        p = plan['cursos'][0]
        self.assertEqual(p['accion'], 'omitir')
        self.assertEqual([s['id'] for s in p['similares']], ['c1'])

    def test_crear_faltantes(self):
        plan = planificar([fila()], [], crear_faltantes=True)
        p = plan['cursos'][0]
        self.assertEqual((p['accion'], p['courseId']), ('crear', None))
        self.assertEqual(plan['resumen']['cursosNuevos'], 1)
        self.assertEqual(len(p['resultado']), 1)

    def test_sin_crear_se_omite(self):
        plan = planificar([fila()], [], crear_faltantes=False)
        self.assertEqual(plan['cursos'][0]['accion'], 'omitir')
        self.assertFalse(plan['resumen']['hayCambios'])

    def test_clase_igual_no_genera_cambios(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT', [clase('Lunes', '10:00', '11:59', 'C-105')])]
        plan = planificar([fila()], cursos)
        p = plan['cursos'][0]
        self.assertEqual((len(p['iguales']), len(p['nuevas'])), (1, 0))
        self.assertFalse(plan['resumen']['hayCambios'])

    def test_cambio_de_salon_en_combinar(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT', [clase('Lunes', '10:00', '11:59', 'A-101')])]
        plan = planificar([fila(salon='C-105')], cursos, modo='combinar')
        p = plan['cursos'][0]
        self.assertEqual(p['cambiosSalon'][0]['salonAnterior'], 'A-101')
        self.assertEqual(p['resultado'][0]['classroom'], 'C-105')

    def test_combinar_conserva_lo_que_no_esta_en_el_archivo(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT', [clase('Viernes', '07:00', '09:59')])]
        plan = planificar([fila()], cursos, modo='combinar')
        p = plan['cursos'][0]
        self.assertEqual(len(p['resultado']), 2)
        self.assertEqual(len(p['soloEnSistema']), 1)

    def test_reemplazar_deja_solo_lo_del_archivo(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT', [clase('Viernes', '07:00', '09:59')])]
        plan = planificar([fila()], cursos, modo='reemplazar')
        p = plan['cursos'][0]
        self.assertEqual(p['resultado'], [clase('Lunes', '10:00', '11:59', 'C-105')])
        self.assertEqual(len(p['soloEnSistema']), 1)  # se informa lo que se va a quitar

    def test_filas_invalidas_se_reportan_y_no_bloquean_las_validas(self):
        plan = planificar([fila(), fila(day='Lunez')], [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT')])
        self.assertEqual(plan['resumen']['filasInvalidas'], 1)
        self.assertEqual(plan['filasInvalidas'][0]['fila'], 2)
        self.assertEqual(len(plan['cursos'][0]['nuevas']), 1)

    def test_filas_repetidas_se_deduplican(self):
        plan = planificar([fila(), fila()], [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT')])
        self.assertEqual(len(plan['cursos'][0]['nuevas']), 1)

    def test_conflicto_con_otro_curso_del_profesor(self):
        cursos = [
            curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT'),
            curso('c2', 'GERENCIA INFORMATICA', '901 IS UBT', [clase('Lunes', '11:00', '12:59')]),
        ]
        plan = planificar([fila(ini='10:00', fin='11:59')], cursos)
        self.assertEqual(len(plan['conflictos']), 1)
        self.assertEqual(plan['conflictos'][0]['dia'], 'Lunes')

    def test_clases_pegadas_sin_solape_no_son_conflicto(self):
        cursos = [
            curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT'),
            curso('c2', 'GERENCIA INFORMATICA', '901 IS UBT', [clase('Lunes', '12:00', '13:59')]),
        ]
        plan = planificar([fila(ini='10:00', fin='11:59')], cursos)
        self.assertEqual(plan['conflictos'], [])

    def test_conflicto_preexistente_no_se_atribuye_a_la_importacion(self):
        cursos = [
            curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT'),
            curso('c2', 'A', 'g', [clase('Martes', '08:00', '10:00')]),
            curso('c3', 'B', 'g', [clase('Martes', '09:00', '11:00')]),
        ]
        plan = planificar([fila()], cursos)
        self.assertEqual(plan['conflictos'], [])

    def test_conflicto_entre_filas_del_mismo_archivo(self):
        cursos = [curso('c1', 'A', '1'), curso('c2', 'B', '1')]
        plan = planificar([
            fila(curso='A', grupo='1', ini='10:00', fin='11:59'),
            fila(curso='B', grupo='1', ini='11:00', fin='12:59'),
        ], cursos)
        self.assertEqual(len(plan['conflictos']), 1)


# ============================================================
# Vistas (Firestore simulado): permisos e importación
# ============================================================
from unittest.mock import MagicMock, patch

from rest_framework.test import APIClient

PROFESOR = {'id': 'person1', 'type': 'Profesor', 'namePerson': 'Profe', 'courses': ['c1']}
ESTUDIANTE = {'id': 'person2', 'type': 'Estudiante', 'namePerson': 'Est', 'courses': ['c1']}
CURSO_C1 = {'id': 'c1', 'nameCourse': 'SISTEMAS OPERATIVOS', 'group': '501 ISC UBT',
            'profesorID': 'uid_prof', 'estudianteID': ['e1'], 'schedule': []}


def _doc(data):
    d = MagicMock()
    d.exists = True
    d.to_dict.return_value = dict(data)
    return d


class MontajeVistas(SimpleTestCase):
    """Montaje común de las pruebas de vistas (Firestore simulado). No define tests."""
    def setUp(self):
        self.client = APIClient()
        self.db = MagicMock()
        self.patches = [
            patch('api_app.views.db', self.db),
            patch('api_app.views.firestore.ArrayUnion', lambda ids: ('ArrayUnion', ids)),
            patch('api_app.views.firestore.ArrayRemove', lambda ids: ('ArrayRemove', ids)),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def como(self, uid, person, cursos=(CURSO_C1,), email='x@x.com', verificado=True):
        """Simula al usuario autenticado (uid), su documento person y sus cursos."""
        def fake_auth(request):
            request.user_firebase = {'uid': uid, 'email': email, 'name': 'X', 'email_verified': verificado}
            return uid, None

        p = patch('api_app.views.obtener_uid_usuario', side_effect=fake_auth)
        p.start()
        self.addCleanup(p.stop)
        for target, rv in (
            ('api_app.views.buscar_persona_por_uid', person),
            ('api_app.views.listar_unidades_horario', [dict(c, courseId=c['id'], groupId=None) for c in cursos]),
        ):
            p = patch(target, return_value=rv)
            p.start()
            self.addCleanup(p.stop)

    def importar(self, filas, **extra):
        return self.client.post('/api/horarios/importar/', {'filas': filas, **extra}, format='json')

    def _curso_en_db(self, data):
        self.db.collection.return_value.document.return_value.get.return_value = _doc(data)


class VistasHorarioTests(MontajeVistas):
    # --- importación ---
    def test_estudiante_no_puede_importar(self):
        self.como('uid_est', ESTUDIANTE)
        r = self.importar([fila()])
        self.assertEqual(r.status_code, 403)
        self.db.batch.assert_not_called()

    def test_vista_previa_no_escribe(self):
        self.como('uid_prof', PROFESOR)
        r = self.importar([fila()])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['aplicado'])
        self.assertEqual(r.json()['plan']['cursos'][0]['courseId'], 'c1')
        self.db.batch.assert_not_called()

    def test_confirmar_aplica_en_un_lote(self):
        self.como('uid_prof', PROFESOR)
        r = self.importar([fila()], confirmar=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['aplicado'])
        batch = self.db.batch.return_value
        batch.update.assert_called_once()
        self.assertEqual(batch.update.call_args[0][1], {'schedule': [clase('Lunes', '10:00', '11:59', 'C-105')]})
        batch.commit.assert_called_once()

    def test_confirmar_con_conflicto_devuelve_409_y_no_escribe(self):
        otro = {**CURSO_C1, 'id': 'c2', 'nameCourse': 'OTRO', 'schedule': [clase('Lunes', '11:00', '12:59')]}
        self.como('uid_prof', PROFESOR, cursos=(CURSO_C1, otro))
        r = self.importar([fila()], confirmar=True)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(r.json()['plan']['conflictos']), 1)
        self.db.batch.assert_not_called()

    def test_confirmar_sin_cambios_devuelve_400(self):
        c = {**CURSO_C1, 'schedule': [clase('Lunes', '10:00', '11:59', 'C-105')]}
        self.como('uid_prof', PROFESOR, cursos=(c,))
        r = self.importar([fila()], confirmar=True)
        self.assertEqual(r.status_code, 400)
        self.db.batch.assert_not_called()

    def test_crear_faltantes_crea_curso_sin_estudiantes_y_lo_enlaza_al_profesor(self):
        self.como('uid_prof', PROFESOR, cursos=())
        ref = MagicMock()
        ref.id = 'nuevo1'
        self.db.collection.return_value.document.return_value = ref
        r = self.importar([fila()], confirmar=True, crearFaltantes=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['cursosCreados'][0]['id'], 'nuevo1')
        batch = self.db.batch.return_value
        datos = batch.set.call_args_list[0][0][1]  # la 2.ª llamada a set es la entrada del historial
        self.assertEqual((datos['profesorID'], datos['estudianteID']), ('uid_prof', []))
        self.assertEqual(batch.update.call_args[0][1], {'courses': ('ArrayUnion', ['nuevo1'])})

    def test_entradas_invalidas(self):
        self.como('uid_prof', PROFESOR)
        self.assertEqual(self.importar([]).status_code, 400)
        self.assertEqual(self.importar([fila()], modo='borrar_todo').status_code, 400)
        self.assertEqual(self.importar([fila()] * 501).status_code, 400)

    # --- permisos de las rutas por curso ---
    def test_estudiante_no_puede_cambiar_horario_de_curso(self):
        self.como('uid_est', ESTUDIANTE)
        self._curso_en_db(CURSO_C1)
        r = self.client.put('/api/horarios/cursos/c1/', {'schedule': []}, format='json')
        self.assertEqual(r.status_code, 403)
        self.db.collection.return_value.document.return_value.update.assert_not_called()

    def test_estudiante_no_puede_borrar_curso(self):
        self.como('uid_est', ESTUDIANTE)
        self._curso_en_db(CURSO_C1)
        r = self.client.delete('/api/horarios/cursos/c1/')
        self.assertEqual(r.status_code, 403)
        self.db.collection.return_value.document.return_value.delete.assert_not_called()

    def test_otro_profesor_no_puede_agregar_clase(self):
        otro = {'id': 'p9', 'type': 'Profesor', 'courses': []}
        self.como('uid_otro', otro)
        self._curso_en_db(CURSO_C1)
        body = {'courseId': 'c1', 'classroom': 'A-1', 'day': 'Lunes', 'iniTime': '08:00', 'endTime': '09:00'}
        self.assertEqual(self.client.post('/api/horarios/clases/', body, format='json').status_code, 403)
        self.assertEqual(self.client.put('/api/horarios/clases/', {**body, 'classIndex': 0}, format='json').status_code, 403)
        self.assertEqual(self.client.delete('/api/horarios/clases/', {'courseId': 'c1', 'classIndex': 0}, format='json').status_code, 403)

    def test_dueno_si_puede_actualizar_horario(self):
        self.como('uid_prof', PROFESOR)
        self._curso_en_db(CURSO_C1)
        with patch('api_app.views.validar_conflicto_horario', return_value=(False, None)):
            r = self.client.put('/api/horarios/cursos/c1/', {'schedule': [clase('Lunes', '08:00', '09:00')]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.db.collection.return_value.document.return_value.update.assert_called_once()

    def test_post_horarios_no_puede_sobrescribir_curso_ajeno_ni_pisar_estudiantes(self):
        otro = {'id': 'p9', 'type': 'Profesor', 'courses': []}
        self.como('uid_otro', otro)
        self._curso_en_db(CURSO_C1)
        body = {'clases': [{'id': 'c1', 'nameCourse': 'X', 'group': 'Y', 'profesorID': 'uid_otro'}]}
        r = self.client.post('/api/horarios/', body, format='json')
        self.assertEqual(r.status_code, 403)
        self.db.collection.return_value.document.return_value.update.assert_not_called()

    def test_post_horarios_dueno_no_borra_estudiantes_ni_horario_si_no_se_envian(self):
        self.como('uid_prof', PROFESOR)
        self._curso_en_db(CURSO_C1)
        body = {'clases': [{'id': 'c1', 'nameCourse': 'SISTEMAS OPERATIVOS', 'group': '501 ISC UBT', 'profesorID': 'uid_prof'}]}
        r = self.client.post('/api/horarios/', body, format='json')
        self.assertEqual(r.status_code, 201)
        enviado = self.db.collection.return_value.document.return_value.update.call_args[0][0]
        self.assertNotIn('estudianteID', enviado)
        self.assertNotIn('schedule', enviado)


# ============================================================
# Historial por semestre
# ============================================================
from datetime import datetime

from .horario_historial import (
    aplicar_plan_a_cursos,
    calcular_cambios,
    construir_entrada,
    normalizar_periodo,
    periodo_actual,
    resumen_curso,
)


def rc(cid, nombre, grupo, schedule=()):
    return resumen_curso(cid, {'nameCourse': nombre, 'group': grupo, 'schedule': list(schedule)})


class PeriodoTests(SimpleTestCase):
    def test_normalizar_periodo(self):
        for entrada in ('2026-2', '2026 2', '2026/2', '2026-II', '2026 ii', '2 - 2026', 'II-2026', '20262'):
            self.assertEqual(normalizar_periodo(entrada), '2026-2', entrada)
        self.assertEqual(normalizar_periodo('2026-I'), '2026-1')
        for malo in ('', None, '2026-3', '1999-1', 'abc', '2026-'):
            self.assertIsNone(normalizar_periodo(malo), malo)

    def test_periodo_actual_por_fecha(self):
        self.assertEqual(periodo_actual(datetime(2026, 1, 15)), '2026-1')
        self.assertEqual(periodo_actual(datetime(2026, 6, 30)), '2026-1')
        self.assertEqual(periodo_actual(datetime(2026, 7, 1)), '2026-2')
        self.assertEqual(periodo_actual(datetime(2026, 12, 31)), '2026-2')


class CalcularCambiosTests(SimpleTestCase):
    def test_sin_diferencias_no_hay_cambios(self):
        a = [rc('c1', 'A', '1', [clase('Lunes', '08:00', '09:59')])]
        self.assertEqual(calcular_cambios(a, a), [])

    def test_agregada_quitada_y_cambio_de_salon(self):
        antes = [rc('c1', 'A', '1', [clase('Lunes', '08:00', '09:59', 'A-1'), clase('Martes', '08:00', '09:59', 'A-1')])]
        despues = [rc('c1', 'A', '1', [clase('Lunes', '08:00', '09:59', 'B-2'), clase('Viernes', '10:00', '11:59', 'A-1')])]
        (c,) = calcular_cambios(antes, despues)
        self.assertEqual(c['accion'], 'modificado')
        self.assertEqual([x['day'] for x in c['agregadas']], ['Viernes'])
        self.assertEqual([x['day'] for x in c['quitadas']], ['Martes'])
        self.assertEqual((c['cambiosSalon'][0]['salonAnterior'], c['cambiosSalon'][0]['classroom']), ('A-1', 'B-2'))

    def test_curso_creado_y_eliminado(self):
        cs = calcular_cambios([rc('c1', 'A', '1', [clase('Lunes', '08:00', '09:59')])], [rc('c2', 'B', '1', [clase('Martes', '08:00', '09:59')])])
        por_accion = {c['accion']: c for c in cs}
        self.assertEqual(len(por_accion['creado']['agregadas']), 1)
        self.assertEqual(len(por_accion['eliminado']['quitadas']), 1)

    def test_aplicar_plan_a_cursos(self):
        existentes = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT', [clase('Viernes', '07:00', '09:59')])]
        plan = planificar([fila(), fila(curso='NUEVO', grupo='1', day='Martes')], existentes, modo='reemplazar', crear_faltantes=True)
        cursos = [rc(c['id'], c['nameCourse'], c['group'], c['schedule']) for c in existentes]
        despues = aplicar_plan_a_cursos(cursos, plan, {('NUEVO', '1'): 'nuevo9'})
        por_id = {c['courseId']: c for c in despues}
        self.assertEqual(por_id['c1']['schedule'], [clase('Lunes', '10:00', '11:59', 'C-105')])
        self.assertEqual(por_id['nuevo9']['nameCourse'], 'NUEVO')

    def test_construir_entrada(self):
        e = construir_entrada('u1', 'importacion', '2026 II', [], [], momento=datetime(2026, 10, 3))
        self.assertEqual((e['periodo'], e['tipo'], e['profesorID']), ('2026-2', 'importacion', 'u1'))
        self.assertEqual(e['fecha'][:10], '2026-10-03')
        with self.assertRaises(ValueError):
            construir_entrada('u1', 'inventado', '2026-1', [], [])


class VistasHistorialTests(MontajeVistas):
    """Reutiliza el montaje de VistasHorarioTests (mismos mocks)."""

    def historial_guardado(self):
        """Entradas enviadas a la colección horarioHistorial (por .add o por batch.set)."""
        entradas = [c[0][0] for c in self.db.collection.return_value.add.call_args_list if isinstance(c[0][0], dict) and 'periodo' in c[0][0]]
        entradas += [c[0][1] for c in self.db.batch.return_value.set.call_args_list if isinstance(c[0][1], dict) and 'periodo' in c[0][1]]
        return entradas

    def test_importar_registra_historial_en_el_mismo_lote(self):
        self.como('uid_prof', PROFESOR)
        r = self.importar([fila()], confirmar=True, periodo='2026 II', archivo='Horario_Docente.pdf')
        self.assertEqual(r.status_code, 200)
        (entrada,) = self.historial_guardado()
        self.assertEqual((entrada['tipo'], entrada['periodo']), ('importacion', '2026-2'))
        self.assertEqual(entrada['detalle']['archivo'], 'Horario_Docente.pdf')
        self.assertEqual(entrada['resumen']['clasesAgregadas'], 1)
        self.assertEqual(entrada['horario'][0]['schedule'], [clase('Lunes', '10:00', '11:59', 'C-105')])
        self.db.batch.return_value.commit.assert_called_once()

    def test_importar_en_reemplazar_deja_constancia_de_lo_quitado(self):
        c = {**CURSO_C1, 'schedule': [clase('Viernes', '07:00', '09:59', 'A-1')]}
        self.como('uid_prof', PROFESOR, cursos=(c,))
        self.importar([fila()], confirmar=True, modo='reemplazar')
        respaldo, entrada = self.historial_guardado()   # primero la copia automática del horario anterior
        self.assertEqual(respaldo['tipo'], 'respaldo_automatico')
        self.assertEqual(entrada['tipo'], 'importacion')
        self.assertEqual(entrada['resumen']['clasesQuitadas'], 1)
        self.assertEqual(entrada['cambios'][0]['quitadas'][0]['day'], 'Viernes')

    def test_importar_periodo_invalido(self):
        self.como('uid_prof', PROFESOR)
        self.assertEqual(self.importar([fila()], confirmar=True, periodo='2026-9').status_code, 400)
        self.db.batch.assert_not_called()

    def test_vista_previa_no_registra_historial(self):
        self.como('uid_prof', PROFESOR)
        self.importar([fila()])
        self.assertEqual(self.historial_guardado(), [])

    def test_edicion_manual_registra_historial(self):
        self.como('uid_prof', PROFESOR)
        self.db.collection.return_value.document.return_value.get.return_value = _doc(CURSO_C1)
        with patch('api_app.views.validar_conflicto_horario', return_value=(False, None)):
            r = self.client.put('/api/horarios/cursos/c1/', {'schedule': [clase('Lunes', '08:00', '09:00')]}, format='json')
        self.assertEqual(r.status_code, 200)
        (entrada,) = self.historial_guardado()
        self.assertEqual(entrada['tipo'], 'edicion_horario_curso')
        self.assertEqual(entrada['resumen']['clasesAgregadas'], 1)

    def test_eliminar_clase_registra_lo_que_se_quito(self):
        c = {**CURSO_C1, 'schedule': [clase('Lunes', '08:00', '09:00'), clase('Martes', '08:00', '09:00')]}
        self.como('uid_prof', PROFESOR)
        self.db.collection.return_value.document.return_value.get.return_value = _doc(c)
        r = self.client.delete('/api/horarios/clases/', {'courseId': 'c1', 'classIndex': 1}, format='json')
        self.assertEqual(r.status_code, 200)
        (entrada,) = self.historial_guardado()
        self.assertEqual((entrada['tipo'], entrada['resumen']['clasesQuitadas']), ('clase_eliminada', 1))
        self.assertEqual(entrada['cambios'][0]['quitadas'][0]['day'], 'Martes')

    def test_borrar_curso_en_realidad_lo_archiva_y_conserva_el_documento(self):
        self.como('uid_prof', PROFESOR)
        ref = self.db.collection.return_value.document.return_value
        ref.get.return_value = _doc({**CURSO_C1, 'schedule': [clase('Lunes', '08:00', '09:00')]})
        r = self.client.delete('/api/horarios/cursos/c1/')
        self.assertEqual(r.status_code, 200)
        ref.delete.assert_not_called()                         # el curso (y sus asistencias) no se borra
        ref.update.assert_called_once_with({'schedule': []})   # solo pierde el horario
        (entrada,) = self.historial_guardado()
        self.assertEqual((entrada['tipo'], entrada['resumen']['clasesQuitadas']), ('curso_archivado', 1))

    def test_si_falla_el_historial_la_operacion_igual_se_hace(self):
        self.como('uid_prof', PROFESOR)
        self.db.collection.return_value.document.return_value.get.return_value = _doc(CURSO_C1)
        with patch('api_app.views.validar_conflicto_horario', return_value=(False, None)), \
             patch('api_app.views.construir_entrada', side_effect=RuntimeError('boom')):
            r = self.client.put('/api/horarios/cursos/c1/', {'schedule': [clase('Lunes', '08:00', '09:00')]}, format='json')
        self.assertEqual(r.status_code, 200)

    # --- consulta ---
    def _entradas(self, *entradas):
        docs = []
        for i, e in enumerate(entradas):
            d = MagicMock()
            d.id = f'h{i}'
            d.to_dict.return_value = e
            docs.append(d)
        self.db.collection.return_value.where.return_value.stream.return_value = docs

    def test_consulta_historial_por_periodo(self):
        self.como('uid_prof', PROFESOR)
        base = {'detalle': {}, 'cambios': [], 'resumen': {}}
        self._entradas(
            {**base, 'periodo': '2026-1', 'tipo': 'importacion', 'fecha': '2026-02-10T08:00:00', 'horario': [rc('c1', 'A', '1', [clase('Lunes', '08:00', '09:00')])]},
            {**base, 'periodo': '2026-1', 'tipo': 'clase_agregada', 'fecha': '2026-03-01T08:00:00', 'horario': [rc('c1', 'A', '1', [clase('Lunes', '08:00', '09:00'), clase('Martes', '08:00', '09:00')])]},
            {**base, 'periodo': '2026-2', 'tipo': 'importacion', 'fecha': '2026-08-05T08:00:00', 'horario': [rc('c1', 'A', '1', [clase('Jueves', '08:00', '09:00')])]},
        )
        r = self.client.get('/api/horarios/historial/?periodo=2026-1').json()
        self.assertEqual([p['periodo'] for p in r['periodos']], ['2026-2', '2026-1'])
        self.assertEqual([p['cambios'] for p in r['periodos']], [1, 2])
        self.assertEqual(r['periodo'], '2026-1')
        self.assertEqual(len(r['horario'][0]['schedule']), 2)  # foto de la ÚLTIMA entrada del semestre
        self.assertEqual([e['tipo'] for e in r['entradas']], ['clase_agregada', 'importacion'])  # más reciente primero
        self.assertNotIn('horario', r['entradas'][0])
        # sin pedir período: el más reciente
        self.assertEqual(self.client.get('/api/horarios/historial/').json()['periodo'], '2026-2')
        self.assertEqual(self.client.get('/api/horarios/historial/?periodo=xx').status_code, 400)

    def test_consulta_sin_historial(self):
        self.como('uid_prof', PROFESOR)
        self._entradas()
        r = self.client.get('/api/horarios/historial/').json()
        self.assertEqual((r['periodos'], r['horario'], r['entradas']), ([], None, []))

    def test_estudiante_no_ve_historial(self):
        self.como('uid_est', ESTUDIANTE)
        self.assertEqual(self.client.get('/api/horarios/historial/').status_code, 403)


# ============================================================
# Archivar, avisos y subgrupos
# ============================================================
from api_app import views as vistas
from api_app.horario_unidades import id_unidad, separar_id_unidad


class PlanArchivarTests(SimpleTestCase):
    def test_archivar_otros_quita_el_horario_de_lo_que_no_viene_en_el_archivo(self):
        cursos = [
            curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT'),
            curso('c2', 'SEMESTRE ANTERIOR', '1', [clase('Viernes', '07:00', '09:59')]),
            curso('c3', 'YA SIN CLASES', '1'),
        ]
        plan = planificar([fila()], cursos, archivar_otros=True)
        acciones = {p['courseId']: p['accion'] for p in plan['cursos']}
        self.assertEqual(acciones, {'c1': 'actualizar', 'c2': 'archivar'})   # c3 no tenía clases: no se toca
        p2 = next(p for p in plan['cursos'] if p['courseId'] == 'c2')
        self.assertEqual((p2['resultado'], len(p2['soloEnSistema'])), ([], 1))
        self.assertEqual(plan['resumen']['cursosArchivados'], 1)

    def test_sin_archivar_otros_no_se_toca_lo_demas(self):
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT'), curso('c2', 'OTRO', '1', [clase('Viernes', '07:00', '09:59')])]
        plan = planificar([fila()], cursos)
        self.assertEqual([p['courseId'] for p in plan['cursos']], ['c1'])

    def test_archivar_cuenta_como_cambio_y_libera_el_horario(self):
        # el curso archivado ocupaba el lunes 10:00-11:59: al archivarse ya no genera cruce con la clase nueva
        cursos = [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT'), curso('c2', 'VIEJO', '1', [clase('Lunes', '10:00', '11:59')])]
        plan = planificar([fila()], cursos, archivar_otros=True)
        self.assertEqual(plan['conflictos'], [])
        solo_archivo = planificar([], [curso('c2', 'VIEJO', '1', [clase('Lunes', '10:00', '11:59')])], archivar_otros=True)
        self.assertTrue(solo_archivo['resumen']['hayCambios'])

    def test_advierte_clases_sin_salon(self):
        plan = planificar([fila(salon='')], [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT')])
        self.assertEqual(len(plan['advertencias']), 1)
        self.assertEqual(plan['advertencias'][0]['tipo'], 'sin_salon')
        self.assertEqual(planificar([fila()], [curso('c1', 'SISTEMAS OPERATIVOS', '501 ISC UBT')])['advertencias'], [])

    def test_archivar_deja_constancia_en_el_historial(self):
        plan = planificar([fila(curso='A', grupo='1')], [curso('c1', 'A', '1'), curso('c2', 'B', '1', [clase('Martes', '08:00', '09:59')])], archivar_otros=True)
        antes = [rc('c1', 'A', '1'), rc('c2', 'B', '1', [clase('Martes', '08:00', '09:59')])]
        despues = aplicar_plan_a_cursos(antes, plan)
        cambios = {c['courseId']: c for c in calcular_cambios(antes, despues)}
        self.assertEqual(len(cambios['c2']['quitadas']), 1)


class IdUnidadTests(SimpleTestCase):
    def test_ids(self):
        self.assertEqual(id_unidad('c1'), 'c1')
        self.assertEqual(id_unidad('c1', '101 ISC UBT'), 'c1::101 ISC UBT')
        self.assertEqual(separar_id_unidad('c1::101 ISC UBT'), ('c1', '101 ISC UBT'))
        self.assertEqual(separar_id_unidad('c1'), ('c1', None))
        self.assertEqual(separar_id_unidad('c1::'), ('c1', None))


def _doc_curso(cid, data, grupos=()):
    d = MagicMock()
    d.id = cid
    d.to_dict.return_value = dict(data)
    gdocs = []
    for gid, gdata in grupos:
        g = MagicMock()
        g.id = gid
        g.to_dict.return_value = dict(gdata)
        gdocs.append(g)
    d.reference.collection.return_value.stream.return_value = gdocs
    return d


class ListarUnidadesTests(SimpleTestCase):
    def setUp(self):
        self.db = MagicMock()
        p = patch('api_app.views.db', self.db)
        p.start()
        self.addCleanup(p.stop)

    def test_cursos_y_subgrupos_propios_y_nada_de_otros(self):
        persona = {'id': 'person_doc_1', 'type': 'Profesor', 'courses': []}
        self.db.collection.return_value.stream.return_value = [
            _doc_curso('a', {'nameCourse': 'LINEA', 'group': '901 IS UBT', 'profesorID': 'uid1', 'schedule': [clase('Lunes', '08:00', '09:59')]}),
            _doc_curso('b', {'nameCourse': 'PENSAMIENTO', 'group': None, 'schedule': []}, grupos=[
                ('101 ISC UBT', {'profesorID': 'person_doc_1', 'schedule': [clase('Martes', '10:00', '11:59')]}),   # id de la persona, no el UID
                ('102 ISC UBT', {'profesorID': 'otra_persona', 'schedule': [clase('Jueves', '10:00', '11:59')]}),
            ]),
            _doc_curso('c', {'nameCourse': 'AJENO', 'group': '1', 'profesorID': 'otro_uid', 'schedule': [clase('Viernes', '08:00', '09:59')]}),
        ]
        unidades = vistas.listar_unidades_horario('uid1', persona)
        self.assertEqual([u['id'] for u in unidades], ['a', 'b::101 ISC UBT'])
        sub = unidades[1]
        self.assertEqual((sub['nameCourse'], sub['group'], sub['courseId'], sub['groupId']), ('PENSAMIENTO', '101 ISC UBT', 'b', '101 ISC UBT'))
        self.assertEqual(sub['schedule'][0]['day'], 'Martes')   # el horario es el del SUBGRUPO

    def test_curso_en_person_courses_cuenta_como_propio(self):
        persona = {'id': 'p1', 'type': 'Profesor', 'courses': ['x']}
        self.db.collection.return_value.stream.return_value = [_doc_curso('x', {'nameCourse': 'X', 'group': 'g', 'schedule': []})]
        self.assertEqual([u['id'] for u in vistas.listar_unidades_horario('uid1', persona)], ['x'])

    def test_ref_unidad_apunta_al_subgrupo(self):
        vistas.ref_unidad('b::101 ISC UBT')
        self.db.collection.assert_called_with('courses')
        self.db.collection.return_value.document.assert_called_with('b')
        self.db.collection.return_value.document.return_value.collection.assert_called_with('groups')
        self.db.collection.return_value.document.return_value.collection.return_value.document.assert_called_with('101 ISC UBT')

    def test_permiso_sobre_subgrupo(self):
        persona = {'id': 'person_doc_1', 'type': 'Profesor', 'courses': []}
        self.assertTrue(vistas.usuario_puede_editar_curso('uid1', 'b::101', {'profesorID': 'person_doc_1'}, persona))
        self.assertFalse(vistas.usuario_puede_editar_curso('uid1', 'b::102', {'profesorID': 'otra_persona'}, persona))
        estudiante = {'id': 'person_doc_1', 'type': 'Estudiante', 'courses': []}
        self.assertFalse(vistas.usuario_puede_editar_curso('uid1', 'b::101', {'profesorID': 'person_doc_1'}, estudiante))


class VistasSubgrupoYArchivoTests(MontajeVistas):
    def test_importar_con_archivar_otros_aplica_y_registra(self):
        c2 = {**CURSO_C1, 'id': 'c2', 'nameCourse': 'SEMESTRE ANTERIOR', 'schedule': [clase('Viernes', '07:00', '09:59')]}
        self.como('uid_prof', PROFESOR, cursos=(CURSO_C1, c2))
        r = self.importar([fila()], confirmar=True, archivarOtros=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['plan']['resumen']['cursosArchivados'], 1)
        llamadas = [c[0][1] for c in self.db.batch.return_value.update.call_args_list]
        self.assertIn({'schedule': []}, llamadas)
        entrada = next(c[0][1] for c in self.db.batch.return_value.set.call_args_list
                       if 'periodo' in c[0][1] and c[0][1]['tipo'] == 'importacion')
        self.assertEqual(entrada['resumen']['clasesQuitadas'], 1)

    def test_vista_previa_incluye_advertencia_sin_salon(self):
        self.como('uid_prof', PROFESOR)
        r = self.importar([fila(salon='')])
        self.assertEqual(r.json()['plan']['advertencias'][0]['tipo'], 'sin_salon')

    def test_archivar_todo_el_horario_no_borra_nada(self):
        c = {**CURSO_C1, 'schedule': [clase('Lunes', '08:00', '09:00')]}
        self.como('uid_prof', PROFESOR, cursos=(c,))
        ref = self.db.collection.return_value.document.return_value
        r = self.client.delete('/api/horarios/')
        self.assertEqual(r.status_code, 200)
        ref.delete.assert_not_called()
        ref.update.assert_called_once_with({'schedule': []})

    def test_estudiante_no_puede_archivar_el_horario(self):
        self.como('uid_est', ESTUDIANTE)
        self.assertEqual(self.client.delete('/api/horarios/').status_code, 403)

    def test_editar_clases_de_un_subgrupo_escribe_en_el_subgrupo(self):
        persona = {'id': 'person_doc_1', 'type': 'Profesor', 'courses': []}
        self.como('uid_prof', persona)
        grupo_doc = _doc({'profesorID': 'person_doc_1', 'schedule': []})
        self.db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value = grupo_doc
        with patch('api_app.views.validar_conflicto_horario', return_value=(False, None)):
            r = self.client.put('/api/horarios/cursos/b%3A%3A101%20ISC%20UBT/', {'schedule': [clase('Martes', '10:00', '11:59')]}, format='json')
        self.assertEqual(r.status_code, 200)
        destino = self.db.collection.return_value.document.return_value.collection.return_value.document.return_value
        destino.update.assert_called_once()   # se actualizó el documento del SUBGRUPO, no el del curso



# ============================================================
# Estudiantes y cursos
# ============================================================
from .estudiantes_import import (
    normalizar_cedula,
    planificar_inscripcion,
    validar_curso,
    validar_fila as validar_fila_estudiante,
)


class CedulaTests(SimpleTestCase):
    def test_normalizar_cedula(self):
        self.assertEqual(normalizar_cedula('1.234.567.890'), '1234567890')
        self.assertEqual(normalizar_cedula(1234567890.0), '1234567890')
        self.assertEqual(normalizar_cedula(' 1234567890 '), '1234567890')
        for malo in ('', None, 'abc123', '12', '1234567890123456', 'CC1234567'):
            self.assertIsNone(normalizar_cedula(malo), malo)

    def test_validar_fila(self):
        f, e = validar_fila_estudiante({'cedula': '1.234.567', 'nombre': '  ARDILA   AMAYA '})
        self.assertEqual((f, e), ({'cedula': '1234567', 'nombre': 'ARDILA AMAYA'}, []))
        _, e = validar_fila_estudiante({'cedula': '', 'nombre': 'X'})
        self.assertEqual(len(e), 2)


class PlanInscripcionTests(SimpleTestCase):
    def test_crear_inscribir_y_ya_inscrito(self):
        personas = {
            '2222222222': {'type': 'Estudiante', 'namePerson': 'DOS'},
            '3333333333': {'type': 'Estudiante', 'namePerson': 'TRES'},
        }
        plan = planificar_inscripcion(
            [{'cedula': '1111111111', 'nombre': 'UNO'}, {'cedula': '2222222222', 'nombre': 'DOS'}, {'cedula': '3333333333', 'nombre': 'TRES'}],
            inscritos={'3333333333'}, personas=personas)
        acciones = {e['cedula']: e['accion'] for e in plan['estudiantes']}
        self.assertEqual(acciones, {'1111111111': 'crear', '2222222222': 'inscribir', '3333333333': 'ya_inscrito'})
        self.assertEqual((plan['resumen']['porCrear'], plan['resumen']['porInscribir'], plan['resumen']['yaInscritos']), (1, 1, 1))
        self.assertTrue(plan['resumen']['hayCambios'])

    def test_no_toca_a_quien_no_es_estudiante(self):
        plan = planificar_inscripcion([{'cedula': '1111111111', 'nombre': 'PROFE'}], set(), {'1111111111': {'type': 'Profesor', 'namePerson': 'PROFE'}})
        self.assertEqual(plan['estudiantes'][0]['accion'], 'conflicto')
        self.assertFalse(plan['resumen']['hayCambios'])

    def test_conserva_el_nombre_del_sistema_y_avisa(self):
        plan = planificar_inscripcion([{'cedula': '1111111111', 'nombre': 'NOMBRE NUEVO'}], set(), {'1111111111': {'type': 'Estudiante', 'namePerson': 'NOMBRE VIEJO'}})
        e = plan['estudiantes'][0]
        self.assertEqual((e['accion'], e['nombreActual']), ('inscribir', 'NOMBRE VIEJO'))
        self.assertIn('distinto', e['motivo'])

    def test_nombre_igual_sin_tildes_no_avisa(self):
        plan = planificar_inscripcion([{'cedula': '1111111111', 'nombre': 'PEÑA GÓMEZ'}], set(), {'1111111111': {'type': 'Estudiante', 'namePerson': 'Pena Gomez'}})
        self.assertIsNone(plan['estudiantes'][0]['motivo'])

    def test_filas_invalidas_y_repetidas(self):
        plan = planificar_inscripcion(
            [{'cedula': '1111111111', 'nombre': 'UNO'}, {'cedula': '1111111111', 'nombre': 'UNO'}, {'cedula': '', 'nombre': 'SIN ID'}],
            set(), {})
        self.assertEqual(len(plan['estudiantes']), 1)
        self.assertEqual(plan['filasInvalidas'][0]['fila'], 3)

    def test_sincronizar_quita_a_los_que_no_estan_en_la_lista(self):
        personas = {'9999999999': {'type': 'Estudiante', 'namePerson': 'SALIENTE'}}
        plan = planificar_inscripcion([{'cedula': '1111111111', 'nombre': 'UNO'}], {'9999999999'}, personas, sincronizar=True)
        self.assertEqual(plan['quitar'], [{'cedula': '9999999999', 'nombre': 'SALIENTE'}])
        self.assertEqual(planificar_inscripcion([{'cedula': '1111111111', 'nombre': 'UNO'}], {'9999999999'}, personas)['quitar'], [])


class ValidarCursoTests(SimpleTestCase):
    def test_validos_e_invalidos(self):
        d, e = validar_curso('  linea  de profundizacion III ', '901 IS UBT', 'CAD612021104')
        self.assertEqual((e, d['nombre'], d['codigo']), ([], 'linea de profundizacion III', 'CAD612021104'))
        self.assertIsNone(validar_curso('Redes', '1')[0]['codigo'])
        for args in (('', '1'), ('Redes', ''), ('Redes', '1', 'mal codigo!'), ('x' * 201, '1')):
            self.assertIsNotNone(validar_curso(*args)[1] or None, args)


class VistasCursosTests(MontajeVistas):
    def ref(self):
        return self.db.collection.return_value.document.return_value

    # ---------- crear curso ----------
    def test_crear_curso(self):
        self.como('uid_prof', PROFESOR, cursos=())
        self.ref().get.return_value = MagicMock(exists=False)
        self.ref().id = 'nuevo7'
        r = self.client.post('/api/cursos/', {'nameCourse': ' Redes  de datos ', 'group': '501 ISC UBT'}, format='json')
        self.assertEqual(r.status_code, 201)
        batch = self.db.batch.return_value
        datos = batch.set.call_args[0][1]
        self.assertEqual(datos, {'nameCourse': 'Redes de datos', 'group': '501 ISC UBT', 'profesorID': 'uid_prof', 'estudianteID': [], 'schedule': []})
        self.assertEqual(batch.update.call_args[0][1], {'courses': ('ArrayUnion', ['nuevo7'])})
        batch.commit.assert_called_once()

    def test_crear_curso_con_codigo_usa_el_codigo_como_id(self):
        self.como('uid_prof', PROFESOR, cursos=())
        self.ref().get.return_value = MagicMock(exists=False)
        self.ref().id = 'CAD612021520'
        r = self.client.post('/api/cursos/', {'nameCourse': 'Redes', 'group': '1', 'codigo': 'CAD612021520'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['curso']['id'], 'CAD612021520')
        self.db.collection.return_value.document.assert_any_call('CAD612021520')

    def test_crear_curso_rechazos(self):
        self.como('uid_prof', PROFESOR)  # ya tiene SISTEMAS OPERATIVOS / 501 ISC UBT
        self.ref().get.return_value = MagicMock(exists=True)
        post = lambda body: self.client.post('/api/cursos/', body, format='json')
        self.assertEqual(post({'nameCourse': 'sistemas operativos', 'group': '501 isc ubt'}).status_code, 409)     # duplicado (sin tildes/mayúsculas)
        self.assertEqual(post({'nameCourse': 'Otro', 'group': '1', 'codigo': 'AB'}).status_code, 400)                    # código demasiado corto
        self.assertEqual(post({'nameCourse': 'Otro', 'group': '1', 'codigo': 'CAD612021520'}).status_code, 409)    # el código ya existe
        self.assertEqual(post({'nameCourse': '', 'group': '1'}).status_code, 400)
        self.assertEqual(post({'nameCourse': 'Otro', 'group': ''}).status_code, 400)
        self.db.batch.assert_not_called()

    def test_estudiante_no_puede_crear_cursos(self):
        self.como('uid_est', ESTUDIANTE)
        self.assertEqual(self.client.post('/api/cursos/', {'nameCourse': 'Redes', 'group': '1'}, format='json').status_code, 403)

    # ---------- editar curso ----------
    def test_editar_curso(self):
        self.como('uid_prof', PROFESOR)
        self.ref().get.return_value = _doc(CURSO_C1)
        r = self.client.patch('/api/cursos/c1/', {'nameCourse': 'SISTEMAS OPERATIVOS II'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.ref().update.assert_called_once_with({'nameCourse': 'SISTEMAS OPERATIVOS II', 'group': '501 ISC UBT'})

    def test_editar_no_permite_duplicar_ni_tocar_ajenos_ni_subgrupos(self):
        otro = {**CURSO_C1, 'id': 'c2', 'nameCourse': 'REDES', 'group': '1'}
        self.como('uid_prof', PROFESOR, cursos=(CURSO_C1, otro))
        self.ref().get.return_value = _doc(CURSO_C1)
        self.assertEqual(self.client.patch('/api/cursos/c1/', {'nameCourse': 'redes', 'group': '1'}, format='json').status_code, 409)
        self.assertEqual(self.client.patch('/api/cursos/c1::101/', {'nameCourse': 'X'}, format='json').status_code, 400)
        self.ref().update.assert_not_called()
        # otro profesor
        self.como('uid_otro', {'id': 'p9', 'type': 'Profesor', 'courses': []})
        self.assertEqual(self.client.patch('/api/cursos/c1/', {'nameCourse': 'HACKEADO'}, format='json').status_code, 403)

    # ---------- estudiantes ----------
    def _curso_con_estudiantes(self, ids):
        self.ref().get.return_value = _doc({**CURSO_C1, 'estudianteID': list(ids)})

    def test_listar_estudiantes_ordenados_por_nombre(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes(['2222222222', '1111111111', '3333333333'])
        with patch('api_app.views._leer_personas', return_value={'1111111111': {'namePerson': 'ZAPATA'}, '2222222222': {'namePerson': 'ÁLVAREZ'}}):
            r = self.client.get('/api/cursos/c1/estudiantes/').json()
        self.assertEqual([e['nombre'] for e in r['estudiantes']], ['ÁLVAREZ', 'Sin registro', 'ZAPATA'])
        self.assertEqual(r['total'], 3)
        self.assertFalse(next(e for e in r['estudiantes'] if e['cedula'] == '3333333333')['registrado'])

    def inscribir(self, filas, personas=None, **extra):
        with patch('api_app.views._leer_personas', return_value=personas or {}):
            return self.client.post('/api/cursos/c1/estudiantes/', {'estudiantes': filas, **extra}, format='json')

    def test_vista_previa_no_escribe(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes([])
        r = self.inscribir([{'cedula': '1111111111', 'nombre': 'UNO'}])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['aplicado'])
        self.assertEqual(r.json()['plan']['resumen']['porCrear'], 1)
        self.db.batch.assert_not_called()

    def test_confirmar_crea_personas_nuevas_e_inscribe(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes([])
        personas = {'2222222222': {'type': 'Estudiante', 'namePerson': 'DOS'}}
        r = self.inscribir([{'cedula': '1.111.111.111', 'nombre': 'UNO'}, {'cedula': '2222222222', 'nombre': 'DOS'}], personas, confirmar=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['resultado'], {'inscritos': 2, 'creados': 1, 'quitados': 0})
        batch = self.db.batch.return_value
        self.assertEqual(batch.set.call_args[0][1], {'namePerson': 'UNO', 'type': 'Estudiante', 'courses': ['c1']})
        llamadas = [c[0][1] for c in batch.update.call_args_list]
        self.assertIn({'courses': ('ArrayUnion', ['c1'])}, llamadas)                                  # persona existente
        self.assertIn({'estudianteID': ('ArrayUnion', ['1111111111', '2222222222'])}, llamadas)       # el curso

    def test_confirmar_sin_cambios_y_conflictos(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes(['2222222222'])
        r = self.inscribir([{'cedula': '2222222222', 'nombre': 'DOS'}], {'2222222222': {'type': 'Estudiante', 'namePerson': 'DOS'}}, confirmar=True)
        self.assertEqual(r.status_code, 400)
        r = self.inscribir([{'cedula': '5555555555', 'nombre': 'PROFE'}], {'5555555555': {'type': 'Profesor', 'namePerson': 'PROFE'}}, confirmar=True)
        self.assertEqual(r.status_code, 400)
        self.db.batch.assert_not_called()

    def test_sincronizar_quita_a_los_que_ya_no_estan(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes(['9999999999'])
        personas = {'9999999999': {'type': 'Estudiante', 'namePerson': 'SALIENTE'}}
        r = self.inscribir([{'cedula': '1111111111', 'nombre': 'UNO'}], personas, sincronizar=True, confirmar=True)
        self.assertEqual(r.json()['resultado'], {'inscritos': 1, 'creados': 1, 'quitados': 1})
        self.assertEqual(self.db.batch.return_value.commit.call_count, 2)   # primero agrega, luego quita
        llamadas = [c[0][1] for c in self.db.batch.return_value.update.call_args_list]
        self.assertIn({'estudianteID': ('ArrayRemove', ['9999999999'])}, llamadas)          # sale del curso
        self.assertIn({'courses': ('ArrayRemove', ['c1'])}, llamadas)                       # y el curso sale de su persona

    def test_limites_y_permisos(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes([])
        filas = [{'cedula': str(1000000000 + i), 'nombre': f'EST {i}'} for i in range(201)]
        self.assertEqual(self.inscribir(filas).status_code, 400)
        self.assertEqual(self.inscribir([]).status_code, 400)
        self.como('uid_est', ESTUDIANTE)
        self.assertEqual(self.inscribir([{'cedula': '1111111111', 'nombre': 'UNO'}], confirmar=True).status_code, 403)
        self.como('uid_otro', {'id': 'p9', 'type': 'Profesor', 'courses': []})
        self.assertEqual(self.inscribir([{'cedula': '1111111111', 'nombre': 'UNO'}], confirmar=True).status_code, 403)

    def test_quitar_un_estudiante(self):
        self.como('uid_prof', PROFESOR)
        self._curso_con_estudiantes(['1111111111'])
        r = self.client.delete('/api/cursos/c1/estudiantes/1111111111/')
        self.assertEqual(r.status_code, 200)
        llamadas = [c[0][1] for c in self.db.batch.return_value.update.call_args_list]
        self.assertIn({'estudianteID': ('ArrayRemove', ['1111111111'])}, llamadas)
        self.assertIn({'courses': ('ArrayRemove', ['c1'])}, llamadas)
        self.assertEqual(self.client.delete('/api/cursos/c1/estudiantes/7777777777/').status_code, 404)

    def test_subgrupo_inscribe_en_el_subgrupo(self):
        persona = {'id': 'person_doc_1', 'type': 'Profesor', 'courses': []}
        self.como('uid_prof', persona)
        grupo = self.db.collection.return_value.document.return_value.collection.return_value.document.return_value
        grupo.get.return_value = _doc({'profesorID': 'person_doc_1', 'estudianteID': [], 'schedule': []})
        with patch('api_app.views._leer_personas', return_value={}):
            r = self.client.post('/api/cursos/b%3A%3A101%20ISC%20UBT/estudiantes/', {'estudiantes': [{'cedula': '1111111111', 'nombre': 'UNO'}], 'confirmar': True}, format='json')
        self.assertEqual(r.status_code, 200)
        destino = [c[0][0] for c in self.db.batch.return_value.update.call_args_list]
        self.assertIn(grupo, destino)                                                            # actualizó el SUBGRUPO
        self.assertEqual(self.db.batch.return_value.set.call_args[0][1]['courses'], ['b'])      # y la persona guarda el id del CURSO principal


class VistasPerfilTests(MontajeVistas):
    def test_ver_perfil(self):
        self.como('uid_prof', {**PROFESOR, 'telefono': '3001234567', 'programa': 'Ingeniería de Sistemas'})
        r = self.client.get('/api/perfil/').json()
        self.assertEqual((r['nombre'], r['tipo'], r['telefono'], r['programa'], r['facultad'], r['totalCursos']),
                         ('Profe', 'Profesor', '3001234567', 'Ingeniería de Sistemas', '', 1))
        self.assertEqual(r['email'], 'x@x.com')

    def test_perfil_inexistente(self):
        self.como('uid_nuevo', None)
        self.assertEqual(self.client.get('/api/perfil/').status_code, 404)
        self.assertEqual(self.client.patch('/api/perfil/', {'nombre': 'Alguien'}, format='json').status_code, 404)

    def test_editar_perfil(self):
        self.como('uid_prof', PROFESOR)
        r = self.client.patch('/api/perfil/', {'nombre': '  Ana   María  Pérez ', 'telefono': '+57 300 123 4567', 'programa': 'Sistemas', 'facultad': ''}, format='json')
        self.assertEqual(r.status_code, 200)
        self.db.collection.return_value.document.assert_called_with('person1')
        self.db.collection.return_value.document.return_value.update.assert_called_once_with(
            {'namePerson': 'Ana María Pérez', 'telefono': '+57 300 123 4567', 'programa': 'Sistemas', 'facultad': ''})

    def test_editar_perfil_validaciones_y_no_toca_campos_ajenos(self):
        self.como('uid_prof', PROFESOR)
        for body in ({'nombre': 'ab'}, {'telefono': 'llámame'}, {'programa': 'x' * 101}, {}):
            self.assertEqual(self.client.patch('/api/perfil/', body, format='json').status_code, 400, body)
        # solo se escriben los campos permitidos: 'type' o 'courses' no se pueden cambiar por aquí
        self.client.patch('/api/perfil/', {'nombre': 'Ana Pérez', 'type': 'Profesor', 'courses': []}, format='json')
        self.assertEqual(set(self.db.collection.return_value.document.return_value.update.call_args[0][0]), {'namePerson'})



# ============================================================
# Registro automático de docentes
# ============================================================
from .registro import (
    decidir_registro,
    lista_de_dominios,
    lista_de_emails,
    normalizar_email,
    preparar_aprobacion,
    validar_docente,
)

DOM = ['ucundinamarca.edu.co']


def decidir(**kw):
    base = dict(email='profe@ucundinamarca.edu.co', email_verificado=True, es_admin=False, dominios=DOM,
                persona_vinculada=None, autorizado=None, solicitud=None, datos=None, buscar_persona=lambda c: None)
    base.update(kw)
    return decidir_registro(**base)


class RegistroPuroTests(SimpleTestCase):
    def test_utilidades(self):
        self.assertEqual(normalizar_email('  Ana@UCundinamarca.edu.co '), 'ana@ucundinamarca.edu.co')
        self.assertIsNone(normalizar_email('sin-arroba'))
        self.assertEqual(lista_de_emails('a@x.co, B@x.co ;; mal, c@x.co'), {'a@x.co', 'b@x.co', 'c@x.co'})
        self.assertEqual(lista_de_dominios('ucundinamarca.edu.co, @otro.co '), ['ucundinamarca.edu.co', 'otro.co'])

    def test_validar_docente(self):
        f, e = validar_docente({'email': 'A@x.co', 'cedula': '1.234.567.890', 'nombre': ' ana  maría '})
        self.assertEqual((f, e), ({'email': 'a@x.co', 'cedula': '1234567890', 'nombre': 'ana maría'}, []))
        self.assertEqual(len(validar_docente({'email': 'x', 'cedula': '12', 'nombre': ''})[1]), 3)

    def test_ya_activo(self):
        self.assertEqual(decidir(persona_vinculada={'type': 'Profesor'})['estado'], 'activo')
        # una cuenta ligada a una persona que NO es profesor no cuenta como activa
        self.assertNotEqual(decidir(persona_vinculada={'type': 'Estudiante'})['estado'], 'activo')

    def test_exige_correo_verificado_y_dominio(self):
        self.assertEqual(decidir(email_verificado=False)['estado'], 'no_verificado')
        self.assertEqual(decidir(email=None)['estado'], 'sin_correo')
        self.assertEqual(decidir(email='alguien@gmail.com')['estado'], 'dominio_no_permitido')
        # un admin puede registrarse con cualquier dominio, pero igualmente con correo verificado
        self.assertNotEqual(decidir(email='admin@gmail.com', es_admin=True)['estado'], 'dominio_no_permitido')
        self.assertEqual(decidir(email='admin@gmail.com', es_admin=True, email_verificado=False)['estado'], 'no_verificado')

    def test_autorizado_se_crea_solo(self):
        r = decidir(autorizado={'cedula': '1111111111', 'nombre': 'ANA PEREZ'})
        self.assertEqual((r['estado'], r['accion'], r['cedula'], r['nombre']), ('activo', 'crear_persona', '1111111111', 'ANA PEREZ'))

    def test_autorizado_vincula_docente_existente_sin_cuenta(self):
        r = decidir(autorizado={'cedula': '1111111111', 'nombre': 'ANA'}, buscar_persona=lambda c: {'type': 'Profesor'})
        self.assertEqual((r['estado'], r['accion']), ('activo', 'vincular_persona'))

    def test_autorizado_con_cedula_de_otro_no_pasa(self):
        for existente in ({'type': 'Estudiante'}, {'type': 'Profesor', 'profesorUID': 'otro_uid'}):
            r = decidir(autorizado={'cedula': '1111111111', 'nombre': 'ANA'}, buscar_persona=lambda c, e=existente: e)
            self.assertEqual((r['estado'], r['accion']), ('cedula_en_uso', None))

    def test_no_autorizado_pide_datos_y_crea_solicitud(self):
        self.assertEqual(decidir()['estado'], 'requiere_datos')
        self.assertEqual(decidir(datos={'cedula': '12', 'nombre': 'X'})['estado'], 'requiere_datos')
        r = decidir(datos={'cedula': '1.111.111.111', 'nombre': 'Ana Pérez'})
        self.assertEqual((r['estado'], r['accion'], r['cedula']), ('pendiente', 'crear_solicitud', '1111111111'))

    def test_solicitud_con_cedula_ya_registrada_se_rechaza(self):
        r = decidir(datos={'cedula': '1111111111', 'nombre': 'Ana Pérez'}, buscar_persona=lambda c: {'type': 'Estudiante'})
        self.assertEqual((r['estado'], r['accion']), ('cedula_en_uso', None))

    def test_solicitud_existente(self):
        self.assertEqual(decidir(solicitud={'estado': 'pendiente'})['estado'], 'pendiente')
        self.assertEqual(decidir(solicitud={'estado': 'rechazada'})['estado'], 'rechazada')
        self.assertIsNone(decidir(solicitud={'estado': 'pendiente'})['accion'])   # no se vuelve a crear

    def test_autorizacion_posterior_gana_sobre_una_solicitud_pendiente(self):
        r = decidir(solicitud={'estado': 'pendiente'}, autorizado={'cedula': '1111111111', 'nombre': 'ANA'})
        self.assertEqual((r['estado'], r['accion']), ('activo', 'crear_persona'))

    def test_aprobacion(self):
        sol = {'cedula': '1111111111', 'nombre': 'ANA PEREZ'}
        self.assertEqual(preparar_aprobacion(sol, lambda c: None)['accion'], 'crear_persona')
        self.assertEqual(preparar_aprobacion(sol, lambda c: {'type': 'Estudiante'})['estado'], 'cedula_en_uso')
        self.assertEqual(preparar_aprobacion({'cedula': '', 'nombre': ''}, lambda c: None)['estado'], 'cedula_en_uso')



# ============================================================
# Registro y administración (Firestore en memoria)
# ============================================================
from django.test import override_settings
from google.api_core.exceptions import AlreadyExists


def _aplicar_valores(actual, data):
    """Simula ArrayUnion / ArrayRemove (los tests los representan como tuplas) al actualizar un documento."""
    nuevo = dict(actual)
    for campo, valor in data.items():
        if isinstance(valor, tuple) and valor and valor[0] == 'ArrayUnion':
            nuevo[campo] = list(nuevo.get(campo, [])) + [v for v in valor[1] if v not in nuevo.get(campo, [])]
        elif isinstance(valor, tuple) and valor and valor[0] == 'ArrayRemove':
            nuevo[campo] = [v for v in nuevo.get(campo, []) if v not in valor[1]]
        else:
            nuevo[campo] = valor
    return nuevo


class FakeDoc:
    def __init__(self, fs, col, key):
        self.fs, self.col, self.id = fs, col, key

    @property
    def reference(self):
        return self

    def collection(self, name):
        return FakeCol(self.fs, f"{self.col}/{self.id}/{name}")

    @property
    def exists(self):
        return (self.col, self.id) in self.fs.datos

    def get(self):
        return self

    def to_dict(self):
        return dict(self.fs.datos.get((self.col, self.id), {}))

    def create(self, data):
        if self.exists:
            raise AlreadyExists('ya existe')
        self.fs.datos[(self.col, self.id)] = dict(data)
        self.fs.escrituras.append(('create', self.col, self.id))

    def set(self, data, merge=False):
        self.fs.datos[(self.col, self.id)] = dict(data)
        self.fs.escrituras.append(('set', self.col, self.id))

    def update(self, data):
        self.fs.datos[(self.col, self.id)] = _aplicar_valores(self.fs.datos.get((self.col, self.id), {}), data)
        self.fs.escrituras.append(('update', self.col, self.id))

    def delete(self):
        self.fs.datos.pop((self.col, self.id), None)
        self.fs.escrituras.append(('delete', self.col, self.id))


class FakeCol:
    def __init__(self, fs, name):
        self.fs, self.name = fs, name

    def document(self, key=None):
        if key is None:
            self.fs.contador = getattr(self.fs, 'contador', 0) + 1
            key = f'auto{self.fs.contador}'
        return FakeDoc(self.fs, self.name, key)

    def stream(self):
        docs = [FakeDoc(self.fs, c, k) for (c, k) in list(self.fs.datos) if c == self.name]
        f = getattr(self, '_filtro', None)
        if f is not None:
            docs = [d for d in docs if d.to_dict().get(f.field_path) == f.value]
        campo = getattr(self, '_orden', None)
        if campo:
            docs.sort(key=lambda d: d.to_dict().get(campo) or '', reverse=getattr(self, '_desc', False))
        limite = getattr(self, '_limite', None)
        return docs[:limite] if limite else docs

    def select(self, campos):
        return self

    def where(self, filter=None):
        self._filtro = filter
        return self

    def order_by(self, campo, direction=None):
        self._orden, self._desc = campo, direction == 'DESCENDING'
        return self

    def limit(self, n):
        self._limite = n
        return self


class FakeBatch:
    def __init__(self, fs):
        self.fs, self.ops = fs, []

    def set(self, ref, data):
        self.ops.append(('set', ref, data))

    def update(self, ref, data):
        self.ops.append(('update', ref, data))

    def commit(self):
        for tipo, ref, data in self.ops:
            getattr(ref, tipo)(data)


class FakeFirestore:
    def __init__(self, datos=None):
        self.datos = dict(datos or {})
        self.escrituras = []

    def collection(self, name):
        return FakeCol(self, name)

    def batch(self):
        return FakeBatch(self)


ADMIN = 'admin@ucundinamarca.edu.co'


@override_settings(ADMIN_EMAILS={ADMIN}, REGISTRO_DOMINIOS=['ucundinamarca.edu.co'])
class VistasRegistroTests(MontajeVistas):
    def montar(self, datos=None):
        self.fs = FakeFirestore(datos)
        p = patch('api_app.views.db', self.fs)
        p.start()
        self.addCleanup(p.stop)

    def registrar(self, body=None, **como):
        self.como(como.pop('uid', 'uid_nuevo'), como.pop('person', None), **como)
        return self.client.post('/api/registro/', body or {}, format='json').json()

    def test_docente_autorizado_queda_activo_y_se_crea_su_perfil(self):
        self.montar({('profesoresAutorizados', 'ana@ucundinamarca.edu.co'): {'email': 'ana@ucundinamarca.edu.co', 'cedula': '1111111111', 'nombre': 'ANA PEREZ'}})
        r = self.registrar(email='ana@ucundinamarca.edu.co')
        self.assertEqual(r['estado'], 'activo')
        persona = self.fs.datos[('person', '1111111111')]
        self.assertEqual((persona['type'], persona['profesorUID'], persona['namePerson'], persona['courses'], persona['email']),
                         ('Profesor', 'uid_nuevo', 'ANA PEREZ', [], 'ana@ucundinamarca.edu.co'))

    def test_correo_con_mayusculas_igual_se_reconoce(self):
        self.montar({('profesoresAutorizados', 'ana@ucundinamarca.edu.co'): {'cedula': '1111111111', 'nombre': 'ANA PEREZ'}})
        self.assertEqual(self.registrar(email='Ana@UCundinamarca.edu.co')['estado'], 'activo')

    def test_no_autorizado_pide_datos_y_luego_queda_pendiente(self):
        self.montar()
        self.assertEqual(self.registrar(email='nuevo@ucundinamarca.edu.co')['estado'], 'requiere_datos')
        self.assertEqual(self.fs.escrituras, [])
        r = self.registrar({'cedula': '1.222.222.222', 'nombre': 'Luis  Gómez'}, email='nuevo@ucundinamarca.edu.co')
        self.assertEqual(r['estado'], 'pendiente')
        sol = self.fs.datos[('solicitudesRegistro', 'uid_nuevo')]
        self.assertEqual((sol['estado'], sol['cedula'], sol['nombre'], sol['email']), ('pendiente', '1222222222', 'Luis Gómez', 'nuevo@ucundinamarca.edu.co'))
        self.assertNotIn(('person', '1222222222'), self.fs.datos)          # todavía NO es docente
        n = len(self.fs.escrituras)
        self.assertEqual(self.registrar(email='nuevo@ucundinamarca.edu.co')['estado'], 'pendiente')   # idempotente
        self.assertEqual(len(self.fs.escrituras), n)

    def test_correo_sin_verificar_o_de_otro_dominio_no_pasa(self):
        self.montar({('profesoresAutorizados', 'ana@ucundinamarca.edu.co'): {'cedula': '1111111111', 'nombre': 'ANA PEREZ'}})
        self.assertEqual(self.registrar(email='ana@ucundinamarca.edu.co', verificado=False)['estado'], 'no_verificado')   # suplantar un correo autorizado
        self.assertEqual(self.registrar({'cedula': '1222222222', 'nombre': 'Luis Gómez'}, email='luis@gmail.com')['estado'], 'dominio_no_permitido')
        self.assertEqual(self.fs.escrituras, [])

    def test_cedula_ya_registrada_no_se_puede_tomar(self):
        self.montar({('person', '1222222222'): {'type': 'Estudiante', 'namePerson': 'EST'}})
        r = self.registrar({'cedula': '1222222222', 'nombre': 'Luis Gómez'}, email='luis@ucundinamarca.edu.co')
        self.assertEqual(r['estado'], 'cedula_en_uso')
        self.assertEqual(self.fs.datos[('person', '1222222222')]['type'], 'Estudiante')   # intacto
        self.assertEqual(self.fs.escrituras, [])

    def test_docente_existente_sin_cuenta_se_vincula(self):
        self.montar({
            ('profesoresAutorizados', 'ana@ucundinamarca.edu.co'): {'cedula': '1111111111', 'nombre': 'ANA'},
            ('person', '1111111111'): {'type': 'Profesor', 'namePerson': 'ANA PEREZ', 'courses': ['c1']},
        })
        self.assertEqual(self.registrar(email='ana@ucundinamarca.edu.co')['estado'], 'activo')
        p = self.fs.datos[('person', '1111111111')]
        self.assertEqual((p['profesorUID'], p['courses'], p['namePerson']), ('uid_nuevo', ['c1'], 'ANA PEREZ'))   # conserva sus cursos y su nombre

    def test_cuenta_ya_activa(self):
        self.montar()
        self.assertEqual(self.registrar(person={'type': 'Profesor', 'id': '1'}, email='ana@ucundinamarca.edu.co')['estado'], 'activo')
        self.assertEqual(self.fs.escrituras, [])

    def test_autorizar_despues_activa_una_solicitud_pendiente(self):
        self.montar({
            ('solicitudesRegistro', 'uid_nuevo'): {'estado': 'pendiente', 'email': 'ana@ucundinamarca.edu.co', 'cedula': '1111111111', 'nombre': 'ANA'},
            ('profesoresAutorizados', 'ana@ucundinamarca.edu.co'): {'cedula': '1111111111', 'nombre': 'ANA PEREZ'},
        })
        self.assertEqual(self.registrar(email='ana@ucundinamarca.edu.co')['estado'], 'activo')
        self.assertEqual(self.fs.datos[('solicitudesRegistro', 'uid_nuevo')]['estado'], 'aprobada')

    def test_es_admin_solo_con_correo_verificado_en_la_lista(self):
        self.montar()
        self.assertTrue(self.registrar(email=ADMIN)['esAdmin'])
        self.assertFalse(self.registrar(email=ADMIN, verificado=False)['esAdmin'])
        self.assertFalse(self.registrar(email='otro@ucundinamarca.edu.co')['esAdmin'])

    # ---------- administración ----------
    def test_los_endpoints_admin_exigen_ser_admin(self):
        self.montar()
        for email, verificado in (('docente@ucundinamarca.edu.co', True), (ADMIN, False)):
            self.como('u', PROFESOR, email=email, verificado=verificado)
            self.assertEqual(self.client.get('/api/admin/solicitudes/').status_code, 403, (email, verificado))
            self.assertEqual(self.client.post('/api/admin/solicitudes/x/aprobar/').status_code, 403)
            self.assertEqual(self.client.get('/api/admin/autorizados/').status_code, 403)
            self.assertEqual(self.client.post('/api/admin/autorizados/', {'docentes': [{}]}, format='json').status_code, 403)
            self.assertEqual(self.client.delete('/api/admin/autorizados/a@x.co/').status_code, 403)

    def solicitud(self, uid='uid_sol', cedula='1333333333', estado='pendiente'):
        return {('solicitudesRegistro', uid): {'uid': uid, 'email': 'sol@ucundinamarca.edu.co', 'nombre': 'SOL ICITANTE', 'cedula': cedula, 'estado': estado, 'fecha': '2026-10-04T10:00:00'}}

    def test_admin_lista_solicitudes_con_las_pendientes_primero(self):
        self.montar({**self.solicitud('u1', estado='aprobada'), **self.solicitud('u2')})
        self.como('adm', None, email=ADMIN)
        filas = self.client.get('/api/admin/solicitudes/').json()['solicitudes']
        self.assertEqual([f['uid'] for f in filas], ['u2', 'u1'])

    def test_admin_aprueba_y_se_crea_el_docente(self):
        self.montar(self.solicitud())
        self.como('adm', None, email=ADMIN)
        r = self.client.post('/api/admin/solicitudes/uid_sol/aprobar/')
        self.assertEqual(r.status_code, 200)
        p = self.fs.datos[('person', '1333333333')]
        self.assertEqual((p['type'], p['profesorUID'], p['email'], p['origenRegistro']), ('Profesor', 'uid_sol', 'sol@ucundinamarca.edu.co', 'aprobacion'))
        sol = self.fs.datos[('solicitudesRegistro', 'uid_sol')]
        self.assertEqual((sol['estado'], sol['resueltaPor']), ('aprobada', ADMIN))
        self.assertEqual(self.client.post('/api/admin/solicitudes/uid_sol/aprobar/').status_code, 400)   # ya resuelta

    def test_aprobar_con_cedula_ocupada_da_conflicto(self):
        self.montar({**self.solicitud(), ('person', '1333333333'): {'type': 'Estudiante'}})
        self.como('adm', None, email=ADMIN)
        self.assertEqual(self.client.post('/api/admin/solicitudes/uid_sol/aprobar/').status_code, 409)
        self.assertEqual(self.fs.datos[('solicitudesRegistro', 'uid_sol')]['estado'], 'pendiente')

    def test_admin_rechaza_con_nota(self):
        self.montar(self.solicitud())
        self.como('adm', None, email=ADMIN)
        self.assertEqual(self.client.post('/api/admin/solicitudes/uid_sol/rechazar/', {'nota': 'No es docente'}, format='json').status_code, 200)
        sol = self.fs.datos[('solicitudesRegistro', 'uid_sol')]
        self.assertEqual((sol['estado'], sol['nota']), ('rechazada', 'No es docente'))
        self.assertNotIn(('person', '1333333333'), self.fs.datos)
        self.assertEqual(self.client.post('/api/admin/solicitudes/uid_sol/archivar/').status_code, 400)
        self.assertEqual(self.client.post('/api/admin/solicitudes/no_existe/aprobar/').status_code, 404)

    def test_admin_autoriza_docentes_todo_o_nada(self):
        self.montar()
        self.como('adm', None, email=ADMIN)
        malos = [{'email': 'a@ucundinamarca.edu.co', 'cedula': '1111111111', 'nombre': 'ANA PEREZ'}, {'email': 'sin-arroba', 'cedula': '12', 'nombre': ''}]
        r = self.client.post('/api/admin/autorizados/', {'docentes': malos}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['invalidos'][0]['fila'], 2)
        self.assertEqual(self.fs.escrituras, [])                                        # nada se guardó
        buenos = [{'email': 'A@ucundinamarca.edu.co', 'cedula': '1.111.111.111', 'nombre': 'ana  perez'}, {'email': 'b@ucundinamarca.edu.co', 'cedula': '2222222222', 'nombre': 'BEA RUIZ'}]
        r = self.client.post('/api/admin/autorizados/', {'docentes': buenos}, format='json')
        self.assertEqual((r.status_code, r.json()['guardados']), (200, 2))
        self.assertEqual(self.fs.datos[('profesoresAutorizados', 'a@ucundinamarca.edu.co')]['cedula'], '1111111111')
        lista = self.client.get('/api/admin/autorizados/').json()['docentes']
        self.assertEqual([d['email'] for d in lista], ['a@ucundinamarca.edu.co', 'b@ucundinamarca.edu.co'])
        self.assertEqual(self.client.delete('/api/admin/autorizados/b@ucundinamarca.edu.co/').status_code, 200)
        self.assertNotIn(('profesoresAutorizados', 'b@ucundinamarca.edu.co'), self.fs.datos)
        self.assertEqual(self.client.post('/api/admin/autorizados/', {'docentes': []}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/admin/autorizados/', {'docentes': [buenos[0]] * 201}, format='json').status_code, 400)

    def test_perfil_informa_si_es_admin(self):
        self.montar()
        self.como('adm', PROFESOR, email=ADMIN)
        self.assertTrue(self.client.get('/api/perfil/').json()['esAdmin'])
        self.como('u', PROFESOR, email='docente@ucundinamarca.edu.co')
        self.assertFalse(self.client.get('/api/perfil/').json()['esAdmin'])



# ============================================================
# Crear cursos nuevos al importar un horario (código de Academusoft)
# ============================================================
class CursosNuevosAlImportarTests(SimpleTestCase):
    def test_el_codigo_se_valida_y_se_conserva(self):
        f, _ = validar_fila(fila() | {'codigo': ' CAD612021520 '})
        self.assertEqual(f['codigo'], 'CAD612021520')
        self.assertIsNone(validar_fila(fila() | {'codigo': 'mal codigo!'})[0]['codigo'])   # inválido: se ignora, no rompe
        self.assertIsNone(validar_fila(fila())[0]['codigo'])

    def test_curso_nuevo_lleva_el_codigo_en_el_plan(self):
        plan = planificar([fila() | {'codigo': 'CAD612021520'}], [], crear_faltantes=True)
        self.assertEqual((plan['cursos'][0]['accion'], plan['cursos'][0]['codigo']), ('crear', 'CAD612021520'))

    def test_empareja_por_codigo_aunque_el_nombre_sea_distinto(self):
        existente = {'id': 'CAD612021520', 'courseId': 'CAD612021520', 'nameCourse': 'SIST. OPERATIVOS', 'group': '501 ISC UBT', 'schedule': []}
        plan = planificar([fila(curso='SISTEMAS OPERATIVOS') | {'codigo': 'CAD612021520'}], [existente], crear_faltantes=True)
        self.assertEqual((plan['cursos'][0]['accion'], plan['cursos'][0]['courseId']), ('actualizar', 'CAD612021520'))

    def test_mismo_codigo_con_otro_grupo_es_un_subgrupo_del_mismo_curso(self):
        existente = {'id': 'CAD612021520', 'courseId': 'CAD612021520', 'groupId': None, 'nameCourse': 'SISTEMAS OPERATIVOS',
                     'group': '502 ISC UBT', 'schedule': [clase('Viernes', '07:00', '09:59')], 'estudianteID': ['111']}
        plan = planificar([fila() | {'codigo': 'CAD612021520'}], [existente], crear_faltantes=True)
        p = plan['cursos'][0]
        self.assertEqual((p['accion'], p['cursoPadre'], p['groupId']), ('subgrupo', 'CAD612021520', '501 ISC UBT'))
        # el grupo que ya existía (502) pasa a ser subgrupo del mismo curso
        self.assertEqual(plan['conversiones'], [{
            'desde': 'CAD612021520', 'hacia': 'CAD612021520::502 ISC UBT', 'courseId': 'CAD612021520', 'groupId': '502 ISC UBT',
            'nameCourse': 'SISTEMAS OPERATIVOS', 'group': '502 ISC UBT', 'clases': 1, 'estudiantes': 1}])
        self.assertEqual((plan['resumen']['subgruposNuevos'], plan['resumen']['cursosConvertidos'], plan['resumen']['hayCambios']), (1, 1, True))


class SubgruposPuroTests(SimpleTestCase):
    def unidad(self, cid, grupo, schedule=(), gid=None, nombre='SISTEMAS OPERATIVOS'):
        return {'id': id_unidad(cid, gid), 'courseId': cid, 'groupId': gid, 'nameCourse': nombre, 'group': grupo,
                'schedule': list(schedule), 'estudianteID': []}

    def test_curso_que_ya_usa_subgrupos_no_se_convierte(self):
        u = self.unidad('c1', '501 ISC UBT', gid='501 ISC UBT')
        plan = planificar([fila(grupo='502 ISC UBT')], [u], crear_faltantes=True)
        self.assertEqual((plan['cursos'][0]['accion'], plan['cursos'][0]['cursoPadre']), ('subgrupo', 'c1'))
        self.assertEqual(plan['conversiones'], [])

    def test_sin_crear_faltantes_no_se_convierte_ni_se_crea_nada(self):
        plan = planificar([fila(grupo='502 ISC UBT')], [self.unidad('c1', '501 ISC UBT')], crear_faltantes=False)
        self.assertEqual((plan['cursos'][0]['accion'], plan['conversiones']), ('omitir', []))

    def test_si_el_archivo_trae_el_grupo_existente_y_uno_nuevo_se_actualiza_el_convertido(self):
        u = self.unidad('c1', '501 ISC UBT', [clase('Lunes', '10:00', '11:59', 'C-105')])
        plan = planificar([fila(grupo='501 ISC UBT', day='Miércoles'), fila(grupo='502 ISC UBT', day='Jueves')], [u], crear_faltantes=True)
        por_accion = {p['accion']: p for p in plan['cursos']}
        self.assertEqual(por_accion['actualizar']['courseId'], 'c1::501 ISC UBT')      # ya apunta a la unidad convertida
        self.assertEqual([c['day'] for c in por_accion['actualizar']['resultado']], ['Lunes', 'Miércoles'])
        self.assertEqual(por_accion['subgrupo']['groupId'], '502 ISC UBT')
        self.assertEqual(len(plan['conversiones']), 1)

    def test_curso_ambiguo_o_de_otro_nombre_se_crea_aparte(self):
        dos = [self.unidad('c1', '501 ISC UBT'), self.unidad('c2', '502 ISC UBT')]            # mismo nombre, dos cursos distintos
        plan = planificar([fila(grupo='503 ISC UBT')], dos, crear_faltantes=True)
        self.assertEqual((plan['cursos'][0]['accion'], plan['conversiones']), ('crear', []))
        plan = planificar([fila(curso='OTRA MATERIA', grupo='1')], [self.unidad('c1', '501 ISC UBT')], crear_faltantes=True)
        self.assertEqual((plan['cursos'][0]['accion'], plan['conversiones']), ('crear', []))

    def test_dos_grupos_nuevos_convierten_una_sola_vez(self):
        plan = planificar([fila(grupo='502 ISC UBT'), fila(grupo='503 ISC UBT')], [self.unidad('c1', '501 ISC UBT')], crear_faltantes=True)
        self.assertEqual(len(plan['conversiones']), 1)
        self.assertEqual(sorted(p['groupId'] for p in plan['cursos']), ['502 ISC UBT', '503 ISC UBT'])

    def test_el_id_del_subgrupo_se_sanea(self):
        plan = planificar([fila(grupo='A/B ISC')], [self.unidad('c1', '501 ISC UBT')], crear_faltantes=True)
        self.assertEqual(plan['cursos'][0]['groupId'], 'A-B ISC')

    def test_el_archivado_ve_la_unidad_convertida_con_su_id_nuevo(self):
        u = self.unidad('c1', '501 ISC UBT', [clase('Viernes', '07:00', '09:59')])
        plan = planificar([fila(grupo='502 ISC UBT')], [u], crear_faltantes=True, archivar_otros=True)
        archivadas = [p['courseId'] for p in plan['cursos'] if p['accion'] == 'archivar']
        self.assertEqual(archivadas, ['c1::501 ISC UBT'])


class VistasCursosNuevosTests(MontajeVistas):
    def ref(self):
        return self.db.collection.return_value.document.return_value

    def test_usa_el_codigo_como_id_si_esta_libre(self):
        self.como('uid_prof', PROFESOR, cursos=())
        self.ref().get.return_value = MagicMock(exists=False)
        self.ref().id = 'CAD612021520'
        r = self.importar([fila() | {'codigo': 'CAD612021520'}], confirmar=True, crearFaltantes=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['cursosCreados'][0]['id'], 'CAD612021520')
        self.db.collection.return_value.document.assert_any_call('CAD612021520')
        self.assertEqual(self.db.collection.return_value.document.call_args_list[0][0], ('CAD612021520',))

    def test_si_el_codigo_esta_ocupado_genera_un_id_automatico(self):
        self.como('uid_prof', PROFESOR, cursos=())
        self.ref().get.return_value = MagicMock(exists=True)
        self.ref().id = 'auto1'
        r = self.importar([fila() | {'codigo': 'CAD612021520'}], confirmar=True, crearFaltantes=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['cursosCreados'][0]['id'], 'auto1')
        self.assertIn(((), {}), [(c[0], c[1]) for c in self.db.collection.return_value.document.call_args_list])   # document() sin argumentos



# ============================================================
# Subgrupos al importar: flujo completo con Firestore en memoria
# ============================================================
PROF_REAL = {'id': '1000000001', 'type': 'Profesor', 'courses': ['CAD612021520']}
ASIST_1 = {'111': {'estadoAsistencia': 'Presente'}, '222': {'estadoAsistencia': 'Ausente'}}
ASIST_2 = {'111': {'estadoAsistencia': 'Presente'}, '222': {'estadoAsistencia': 'Presente'}}


def datos_curso_unico():
    return {
        ('person', '1000000001'): {'type': 'Profesor', 'namePerson': 'PROFE', 'profesorUID': 'uid_prof', 'courses': ['CAD612021520']},
        ('courses', 'CAD612021520'): {'nameCourse': 'SISTEMAS OPERATIVOS', 'group': '501 ISC UBT', 'profesorID': 'uid_prof',
                                      'estudianteID': ['111', '222'], 'schedule': [clase('Lunes', '10:00', '11:59', 'C-105')]},
        ('courses/CAD612021520/assistances', '2026-08-17'): dict(ASIST_1),
        ('courses/CAD612021520/assistances', '2026-08-24'): dict(ASIST_2),
    }


class VistasSubgruposFlujoTests(MontajeVistas):
    def montar(self, datos):
        self.fs = FakeFirestore(datos)
        for destino, valor in (('api_app.views.db', self.fs),):
            p = patch(destino, valor)
            p.start()
            self.addCleanup(p.stop)
        # sin simular listar_unidades_horario: se usa la lectura real sobre el Firestore en memoria
        def fake_auth(request):
            request.user_firebase = {'uid': 'uid_prof', 'email': 'profe@ucundinamarca.edu.co', 'name': 'X', 'email_verified': True}
            return 'uid_prof', None
        for target, kw in (('api_app.views.obtener_uid_usuario', {'side_effect': fake_auth}),
                           ('api_app.views.buscar_persona_por_uid', {'return_value': PROF_REAL})):
            q = patch(target, **kw)
            q.start()
            self.addCleanup(q.stop)

    def subir(self, filas, **extra):
        return self.client.post('/api/horarios/importar/', {'filas': filas, 'crearFaltantes': True, **extra}, format='json')

    def test_un_grupo_nuevo_convierte_el_curso_y_crea_el_subgrupo(self):
        self.montar(datos_curso_unico())
        r = self.subir([fila(grupo='502 ISC UBT', day='Martes', ini='09:00', fin='10:59', salon='C-106') | {'codigo': 'CAD612021520'}], confirmar=True)
        self.assertEqual(r.status_code, 200, r.content)
        out = r.json()
        self.assertEqual((out['cursosConvertidos'], out['subgruposCreados'][0]['id'], out['cursosCreados']), (1, 'CAD612021520::502 ISC UBT', []))
        d = self.fs.datos
        # 1) el grupo que ya existía es ahora un subgrupo, con sus estudiantes y su horario
        g501 = d[('courses/CAD612021520/groups', '501 ISC UBT')]
        self.assertEqual((g501['profesorID'], g501['estudianteID'], g501['schedule']),
                         ('1000000001', ['111', '222'], [clase('Lunes', '10:00', '11:59', 'C-105')]))
        # 2) sus asistencias se COPIARON al subgrupo y las originales siguen ahí
        for fecha, asist in (('2026-08-17', ASIST_1), ('2026-08-24', ASIST_2)):
            self.assertEqual(d[('courses/CAD612021520/groups/501 ISC UBT/assistances', fecha)], asist)
            self.assertEqual(d[('courses/CAD612021520/assistances', fecha)], asist)
        # 3) el curso principal quedó sin grupo propio, con respaldo de lo que tenía
        top = d[('courses', 'CAD612021520')]
        self.assertEqual((top['group'], top['schedule'], top['estudianteID']), (None, [], []))
        self.assertEqual((top['convertidoASubgrupos']['grupo'], top['convertidoASubgrupos']['estudianteID']), ('501 ISC UBT', ['111', '222']))
        # 4) el grupo nuevo es otro subgrupo del MISMO curso (no un curso aparte)
        self.assertEqual(d[('courses/CAD612021520/groups', '502 ISC UBT')]['schedule'], [clase('Martes', '09:00', '10:59', 'C-106')])
        self.assertEqual([k for k in d if k[0] == 'courses'], [('courses', 'CAD612021520')])
        # 5) y desde el punto de vista del profesor, dos unidades de horario (ninguna es el curso principal)
        unidades = vistas.listar_unidades_horario('uid_prof', PROF_REAL)
        self.assertEqual(sorted(u['id'] for u in unidades), ['CAD612021520::501 ISC UBT', 'CAD612021520::502 ISC UBT'])
        # 6) el historial no lo cuenta como borrado + creado
        entrada = next(v for (c, _), v in d.items() if c == 'horarioHistorial')
        self.assertEqual((entrada['resumen']['cursosEliminados'], entrada['resumen']['clasesAgregadas']), (0, 1))

    def test_la_vista_previa_describe_la_conversion_y_no_escribe_nada(self):
        self.montar(datos_curso_unico())
        r = self.subir([fila(grupo='502 ISC UBT') | {'codigo': 'CAD612021520'}])
        plan = r.json()['plan']
        self.assertEqual((plan['conversiones'][0]['groupId'], plan['conversiones'][0]['clases'], plan['conversiones'][0]['estudiantes']), ('501 ISC UBT', 1, 2))
        self.assertEqual(plan['cursos'][0]['accion'], 'subgrupo')
        self.assertEqual(self.fs.escrituras, [])

    def test_el_archivo_con_el_grupo_existente_y_uno_nuevo_actualiza_ambos(self):
        self.montar(datos_curso_unico())
        r = self.subir([fila(grupo='501 ISC UBT', day='Miércoles', ini='08:00', fin='09:59'), fila(grupo='502 ISC UBT', day='Jueves', ini='14:00', fin='15:59')], confirmar=True)
        self.assertEqual(r.status_code, 200, r.content)
        g501 = self.fs.datos[('courses/CAD612021520/groups', '501 ISC UBT')]
        self.assertEqual([c['day'] for c in g501['schedule']], ['Lunes', 'Miércoles'])
        self.assertIn(('courses/CAD612021520/groups', '502 ISC UBT'), self.fs.datos)

    def test_un_curso_que_ya_usa_subgrupos_solo_recibe_el_nuevo(self):
        datos = datos_curso_unico()
        datos[('courses', 'CAD612021520')] = {'nameCourse': 'SISTEMAS OPERATIVOS', 'group': None, 'schedule': []}
        datos[('courses/CAD612021520/groups', '501 ISC UBT')] = {'profesorID': '1000000001', 'estudianteID': ['111'], 'schedule': [clase('Lunes', '10:00', '11:59', 'C-105')]}
        self.montar(datos)
        r = self.subir([fila(grupo='502 ISC UBT', day='Martes')], confirmar=True)
        self.assertEqual((r.status_code, r.json()['cursosConvertidos']), (200, 0))
        self.assertIn(('courses/CAD612021520/groups', '502 ISC UBT'), self.fs.datos)
        self.assertNotIn('convertidoASubgrupos', self.fs.datos[('courses', 'CAD612021520')])
        self.assertEqual(self.fs.datos[('courses/CAD612021520/groups', '501 ISC UBT')]['estudianteID'], ['111'])   # intacto

    def test_el_curso_de_otro_profesor_no_se_toca_se_crea_aparte(self):
        datos = datos_curso_unico()
        datos[('courses', 'REDES01')] = {'nameCourse': 'REDES', 'group': '1', 'profesorID': 'otro_uid', 'estudianteID': [], 'schedule': []}
        self.montar(datos)
        r = self.subir([fila(curso='REDES', grupo='2', day='Jueves')], confirmar=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['cursosCreados']), 1)
        self.assertEqual(self.fs.datos[('courses', 'REDES01')]['group'], '1')          # el del otro profesor, intacto

    def test_si_el_subgrupo_destino_ya_existe_no_se_escribe_nada(self):
        datos = datos_curso_unico()
        datos[('courses/CAD612021520/groups', '501 ISC UBT')] = {'profesorID': 'otra_persona', 'estudianteID': ['999'], 'schedule': []}   # de otro, no es unidad del profesor
        self.montar(datos)
        antes = dict(self.fs.datos)
        r = self.subir([fila(grupo='502 ISC UBT', day='Martes')], confirmar=True)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.fs.escrituras, [])
        self.assertEqual(self.fs.datos, antes)


# ============================================
# MÓDULO DE ESTUDIANTES
# ============================================
from .estudiante_cuenta import decidir_vinculo, diferencias, validar_perfil_estudiante


def vinculo(**kw):
    base = dict(email='e@ucundinamarca.edu.co', email_verificado=True, es_admin=False, dominios=['ucundinamarca.edu.co'],
                persona_de_la_cuenta=None, cedula='1.000.000', persona_cedula={'type': 'Estudiante', 'namePerson': 'E'},
                inscripciones=1)
    base.update(kw)
    return decidir_vinculo(**base)


class VinculoEstudiantePuroTests(SimpleTestCase):
    def test_estudiante_activo_sin_cuenta_se_vincula(self):
        r = vinculo()
        self.assertEqual((r['estado'], r['accion']), ('activo', 'vincular'))

    def test_cedula_inexistente_o_de_docente(self):
        self.assertEqual(vinculo(persona_cedula=None)['estado'], 'cedula_no_encontrada')
        self.assertEqual(vinculo(persona_cedula={'type': 'Profesor'})['estado'], 'cedula_no_encontrada')

    def test_sin_inscripciones_no_es_activo(self):
        self.assertEqual(vinculo(inscripciones=0)['estado'], 'estudiante_inactivo')

    def test_cedula_con_otra_cuenta(self):
        r = vinculo(persona_cedula={'type': 'Estudiante', 'estudianteUID': 'otro'})
        self.assertEqual((r['estado'], r['accion']), ('cedula_en_uso', None))

    def test_correo_y_dominio(self):
        self.assertEqual(vinculo(email_verificado=False)['estado'], 'no_verificado')
        self.assertEqual(vinculo(email='x@gmail.com')['estado'], 'dominio_no_permitido')
        self.assertEqual(vinculo(email=None)['estado'], 'sin_correo')

    def test_sin_cedula_pide_datos(self):
        self.assertEqual(vinculo(cedula='abc')['estado'], 'requiere_datos')

    def test_cuenta_ya_ligada(self):
        self.assertEqual(vinculo(persona_de_la_cuenta={'type': 'Estudiante'})['estado'], 'activo')
        self.assertEqual(vinculo(persona_de_la_cuenta={'type': 'Profesor'})['estado'], 'cuenta_docente')


class PerfilEstudiantePuroTests(SimpleTestCase):
    def test_normaliza_y_valida(self):
        c, e = validar_perfil_estudiante({
            'telefono': ' 300 123  4567 ', 'emailPersonal': 'Yo@Gmail.COM',
            'contactoEmergencia': {'nombre': 'Ana  Pérez', 'telefono': '3001112233'},
            'equipos': [{'marca': 'Lenovo', 'serial': 'pf2abc 123'}, {'marca': '', 'serial': ''}],
        })
        self.assertEqual(e, [])
        self.assertEqual(c['telefono'], '300 123 4567')
        self.assertEqual(c['emailPersonal'], 'yo@gmail.com')
        self.assertEqual(c['contactoEmergencia'], {'nombre': 'Ana Pérez', 'telefono': '3001112233'})
        self.assertEqual(c['equipos'], [{'marca': 'Lenovo', 'serial': 'PF2ABC 123'}])

    def test_errores(self):
        for datos in (
            {'telefono': 'abc'}, {'emailPersonal': 'no-es-correo'},
            {'contactoEmergencia': {'nombre': 'Ana', 'telefono': ''}},
            {'equipos': [{'marca': 'HP', 'serial': 'x'}]},
            {'equipos': [{'marca': '', 'serial': 'ABC123'}]},
            {'equipos': [{'marca': 'HP', 'serial': 'ABC123'}, {'marca': 'Dell', 'serial': 'abc123'}]},
            {'equipos': [{'marca': 'HP', 'serial': 'ABC123'}] * 6},
        ):
            self.assertTrue(validar_perfil_estudiante(datos)[1], datos)

    def test_solo_trae_lo_enviado_y_no_acepta_nombre_ni_cedula(self):
        c, _ = validar_perfil_estudiante({'telefono': '3001112233', 'nombre': 'X', 'cedula': '1', 'namePerson': 'Y'})
        self.assertEqual(list(c), ['telefono'])

    def test_diferencias_solo_de_lo_que_cambia(self):
        persona = {'telefono': '300 111 2233', 'equipos': [{'marca': 'HP', 'serial': 'ABC123'}]}
        filas = diferencias(persona, {'telefono': '300 111 2233', 'equipos': [{'marca': 'HP', 'serial': 'ZZZ999'}], 'emailPersonal': ''})
        self.assertEqual([f['campo'] for f in filas], ['equipos'])
        self.assertEqual(filas[0]['antes'], [{'marca': 'HP', 'serial': 'ABC123'}])
        self.assertEqual(filas[0]['despues'], [{'marca': 'HP', 'serial': 'ZZZ999'}])
        self.assertEqual(diferencias({}, {'telefono': '', 'equipos': []}), [])


ESTUDIANTE = {'id': '1000001', 'type': 'Estudiante', 'namePerson': 'EVA RUIZ', 'estudianteUID': 'uid_eva'}
DOCENTE = {'id': '9', 'type': 'Profesor', 'namePerson': 'DOC', 'profesorUID': 'uid_doc', 'courses': ['c1']}


@override_settings(ADMIN_EMAILS={ADMIN}, REGISTRO_DOMINIOS=['ucundinamarca.edu.co'])
class VistasEstudianteTests(MontajeVistas):
    def montar(self, datos=None):
        base = {
            ('courses', 'c1'): {'nameCourse': 'REDES', 'group': '501', 'profesorID': 'uid_doc', 'estudianteID': ['1000001', '2000002'],
                                 'schedule': [clase('Lunes', '07:00', '08:59')]},
            ('courses', 'c2'): {'nameCourse': 'BD', 'group': '502', 'profesorID': 'uid_doc', 'estudianteID': ['2000002'],
                                 'schedule': [clase('Martes', '07:00', '08:59')]},
            ('courses', 'c3'): {'nameCourse': 'SO', 'profesorID': 'uid_doc', 'estudianteID': [], 'schedule': []},
            ('courses/c3/groups', 'g1'): {'group': '601', 'profesorID': '9', 'estudianteID': ['1000001'], 'schedule': [clase('Jueves', '10:00', '11:59')]},
            ('courses/c1/assistances', '2026-03-02'): {'1000001': {'estadoAsistencia': 'Presente', 'horaRegistro': '07:01:00'},
                                                       '2000002': {'estadoAsistencia': 'Ausente', 'horaRegistro': 'None'}},
            ('person', '1000001'): {'type': 'Estudiante', 'namePerson': 'EVA RUIZ', 'estudianteUID': 'uid_eva'},
            ('person', '3000003'): {'type': 'Estudiante', 'namePerson': 'SIN CURSO'},
            ('person', '2000002'): {'type': 'Estudiante', 'namePerson': 'OTRO'},
        }
        base.update(datos or {})
        self.fs = FakeFirestore(base)
        p = patch('api_app.views.db', self.fs)
        p.start()
        self.addCleanup(p.stop)

    def como_persona(self, uid, person, email='eva@ucundinamarca.edu.co'):
        def fake_auth(request):
            request.user_firebase = {'uid': uid, 'email': email, 'name': 'X', 'email_verified': True}
            return uid, None
        for p in (patch('api_app.views.obtener_uid_usuario', side_effect=fake_auth),
                  patch('api_app.views.buscar_persona_por_uid', return_value=person)):
            p.start()
            self.addCleanup(p.stop)

    # ----- vincular -----
    def test_vincula_cuenta_con_cedula_activa_y_deja_constancia(self):
        self.montar()
        self.como_persona('uid_nuevo', None, 'eva2@ucundinamarca.edu.co')
        r = self.client.post('/api/registro/estudiante/', {'cedula': '3000003'}, format='json').json()
        self.assertEqual(r['estado'], 'estudiante_inactivo')            # sin cursos: no se vincula
        self.assertNotIn('estudianteUID', self.fs.datos[('person', '3000003')])
        r = self.client.post('/api/registro/estudiante/', {'cedula': '2000002'}, format='json').json()
        self.assertEqual((r['estado'], r['rol']), ('activo', 'Estudiante'))
        self.assertEqual(self.fs.datos[('person', '2000002')]['estudianteUID'], 'uid_nuevo')
        constancia = [v for (c, _), v in self.fs.datos.items() if c == 'cambiosEstudiantes']
        self.assertEqual([x['tipo'] for x in constancia], ['vinculacion'])

    def test_no_vincula_cedula_con_otra_cuenta_ni_docente(self):
        self.montar()
        self.como_persona('uid_nuevo', None, 'otra@ucundinamarca.edu.co')
        self.assertEqual(self.client.post('/api/registro/estudiante/', {'cedula': '1000001'}, format='json').json()['estado'], 'cedula_en_uso')
        self.assertEqual(self.client.post('/api/registro/estudiante/', {'cedula': '9999999'}, format='json').json()['estado'], 'cedula_no_encontrada')
        self.assertEqual(self.fs.datos[('person', '1000001')]['estudianteUID'], 'uid_eva')

    def test_registro_de_estudiante_ligado_devuelve_rol(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.client.post('/api/registro/', {}, format='json').json()
        self.assertEqual((r['estado'], r['rol'], r['nombre'], r['esAdmin']), ('activo', 'Estudiante', 'EVA RUIZ', False))

    # ----- horario y asistencias propias -----
    def test_horario_solo_de_sus_cursos_y_sin_datos_de_otros(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.client.get('/api/horarios/').json()
        ids = sorted(c['id'] for c in r['clases'])
        self.assertEqual(ids, ['c1', 'c3::g1'])
        for c in r['clases']:
            self.assertEqual(c['estudianteID'], ['1000001'])
            self.assertIsNone(c['profesorID'])

    def test_asistencias_solo_las_suyas(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        filas = self.client.get('/api/asistencias/').json()
        self.assertEqual([a['estudiante'] for a in filas], ['1000001'])

    def test_no_ve_el_nombre_de_otro_estudiante(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.get('/api/estudiantes/nombre/2000002/').status_code, 403)
        self.assertEqual(self.client.get('/api/estudiantes/nombre/1000001/').status_code, 200)

    # ----- un estudiante no puede tocar asistencias -----
    def test_estudiante_no_crea_edita_ni_borra_asistencias(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        antes = dict(self.fs.datos[('courses/c1/assistances', '2026-03-02')])
        r = self.client.post('/api/asistencias/crear/', {'estudiante': '1000001', 'estadoAsistencia': 'Presente', 'asignatura': 'REDES'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.client.put('/api/asistencias/c1_2026-03-02_1000001/update/', {'estadoAsistencia': 'Presente'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.client.delete('/api/asistencias/c1_2026-03-02_2000002/delete/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.fs.datos[('courses/c1/assistances', '2026-03-02')], antes)

    def test_estudiante_solo_lee_su_propio_registro(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.get('/api/asistencias/c1_2026-03-02_1000001/').status_code, 200)
        self.assertEqual(self.client.get('/api/asistencias/c1_2026-03-02_2000002/').status_code, 403)

    def test_cuenta_sin_perfil_no_toca_asistencias(self):
        self.montar()
        self.como_persona('uid_x', None)
        r = self.client.put('/api/asistencias/c1_2026-03-02_1000001/update/', {'estadoAsistencia': 'Ausente'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_docente_dueno_si_puede_pero_otro_docente_no(self):
        self.montar()
        self.como_persona('uid_doc', DOCENTE)
        r = self.client.put('/api/asistencias/c1_2026-03-02_1000001/update/', {'estadoAsistencia': 'Tiene Excusa'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.fs.datos[('courses/c1/assistances', '2026-03-02')]['1000001']['estadoAsistencia'], 'Tiene Excusa')

    def test_otro_docente_no_edita(self):
        self.montar()
        self.como_persona('uid_otro', {'id': '8', 'type': 'Profesor', 'namePerson': 'OTRO DOC', 'profesorUID': 'uid_otro', 'courses': []})
        r = self.client.delete('/api/asistencias/c1_2026-03-02_1000001/delete/')
        self.assertEqual(r.status_code, 403)
        self.assertIn('1000001', self.fs.datos[('courses/c1/assistances', '2026-03-02')])

    # ----- perfil del estudiante -----
    def test_perfil_get_y_guardar_con_trazabilidad(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        g = self.client.get('/api/perfil/').json()
        self.assertEqual((g['tipo'], g['cedula'], g['equipos'], g['totalCursos']), ('Estudiante', '1000001', [], 2))
        r = self.client.patch('/api/perfil/', {'telefono': '300 111 2233', 'equipos': [{'marca': 'HP', 'serial': 'abc123'}]}, format='json')
        self.assertEqual(r.status_code, 200)
        persona = self.fs.datos[('person', '1000001')]
        self.assertEqual((persona['telefono'], persona['equipos']), ('300 111 2233', [{'marca': 'HP', 'serial': 'ABC123'}]))
        self.assertEqual(persona['namePerson'], 'EVA RUIZ')
        # segundo cambio: el registro guarda lo de antes y lo de después
        self.como_persona('uid_eva', {**ESTUDIANTE, **persona})
        self.client.patch('/api/perfil/', {'equipos': [{'marca': 'HP', 'serial': 'ZZZ999'}]}, format='json')
        registros = sorted((v for (c, _), v in self.fs.datos.items() if c == 'cambiosEstudiantes'), key=lambda x: x['fecha'])
        self.assertEqual(len(registros), 2)
        ultimo = registros[-1]
        self.assertEqual((ultimo['tipo'], ultimo['cedula'], ultimo['uid']), ('perfil', '1000001', 'uid_eva'))
        self.assertEqual(ultimo['cambios'], [{'campo': 'equipos', 'antes': [{'marca': 'HP', 'serial': 'ABC123'}], 'despues': [{'marca': 'HP', 'serial': 'ZZZ999'}]}])

    def test_perfil_sin_cambios_reales_no_deja_registro(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.client.patch('/api/perfil/', {'telefono': ''}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse([1 for (c, _) in self.fs.datos if c == 'cambiosEstudiantes'])

    def test_perfil_estudiante_ignora_nombre_y_rechaza_datos_malos(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.patch('/api/perfil/', {'nombre': 'HACKER'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch('/api/perfil/', {'telefono': 'xx'}, format='json').status_code, 400)
        self.assertEqual(self.fs.datos[('person', '1000001')]['namePerson'], 'EVA RUIZ')

    # ----- administrador -----
    def test_admin_ve_los_cambios_recientes_y_otros_no(self):
        self.montar({
            ('cambiosEstudiantes', 'a'): {'tipo': 'perfil', 'cedula': '1000001', 'nombre': 'EVA', 'fecha': '2026-03-01T10:00:00', 'cambios': []},
            ('cambiosEstudiantes', 'b'): {'tipo': 'perfil', 'cedula': '2000002', 'nombre': 'OTRO', 'fecha': '2026-03-02T10:00:00', 'cambios': []},
        })
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.get('/api/admin/cambios-estudiantes/').status_code, 403)
        self.como_persona('uid_admin', DOCENTE, email=ADMIN)
        r = self.client.get('/api/admin/cambios-estudiantes/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c['id'] for c in r.json()['cambios']], ['b', 'a'])


# ============================================
# ASISTENCIAS POR PÁGINAS
# ============================================
from . import asistencia_pagina as ap


class AsistenciaPaginaPuroTests(SimpleTestCase):
    FECHAS = ['2026-03-02', '2026-03-09', '2026-03-10', '2026-03-16']   # lunes, lunes, martes, lunes

    def test_resolver_fecha(self):
        r = ap.resolver_fecha
        self.assertEqual(r(self.FECHAS, '2026-03-20'), '2026-03-16')                       # la última
        self.assertEqual(r(self.FECHAS, '2026-03-20', fecha='2026-03-09'), '2026-03-09')   # la pedida
        self.assertEqual(r(self.FECHAS, '2026-03-20', dia='Martes'), '2026-03-10')         # último martes
        self.assertEqual(r(self.FECHAS, '2026-03-12', dia='Lunes'), '2026-03-09')          # sin pasar de hoy
        self.assertIsNone(r(self.FECHAS, '2026-03-20', dia='Viernes'))
        self.assertEqual(r(self.FECHAS, '2026-03-20', en_ventana=True), '2026-03-20')      # clase en curso: hoy
        self.assertIsNone(r([], '2026-03-20'))

    def test_dia_de_fecha(self):
        self.assertEqual(ap.dia_de_fecha('2026-03-02'), 'Lunes')
        self.assertEqual(ap.dia_de_fecha('2026-03-08'), 'Domingo')

    def test_paginar(self):
        items = list(range(25))
        self.assertEqual(ap.paginar(items, 1, 10), (list(range(10)), 1, 3))
        self.assertEqual(ap.paginar(items, 3, 10), ([20, 21, 22, 23, 24], 3, 3))
        self.assertEqual(ap.paginar(items, 9, 10)[1:], (3, 3))     # fuera de rango: se acota
        self.assertEqual(ap.paginar([], 1, 10), ([], 1, 1))

    def test_numero_positivo(self):
        self.assertEqual(ap.numero_positivo('3', 1), 3)
        self.assertEqual(ap.numero_positivo('x', 1), 1)
        self.assertEqual(ap.numero_positivo('0', 7), 7)
        self.assertEqual(ap.numero_positivo('500', 10, 50), 50)

    def test_franja_conserva_ausentes_y_filtra_por_hora(self):
        horario = [clase('Lunes', '07:00', '08:59'), clase('Lunes', '10:00', '11:59')]
        filas = [
            {'estudiante': 'a', 'horaRegistro': '07:05:00'},
            {'estudiante': 'b', 'horaRegistro': '10:03:00'},
            {'estudiante': 'c', 'horaRegistro': 'None'},       # ausente: sin hora
        ]
        dentro, fuera = ap.filtrar_por_franja(filas, horario, '2026-03-02', '07:00-08:59')
        self.assertEqual([f['estudiante'] for f in dentro], ['a', 'c'])
        self.assertEqual(fuera, 1)
        self.assertEqual(ap.filtrar_por_franja(filas, horario, '2026-03-02', None), (filas, 0))

    def test_resumen(self):
        filas = [{'estadoAsistencia': e} for e in ('Presente', 'Presente', 'Ausente', 'Tiene Excusa')]
        self.assertEqual(ap.resumen(filas), {'total': 4, 'presentes': 2, 'ausentes': 1, 'conExcusa': 1})


class VistasAsistenciaPaginaTests(VistasEstudianteTests):
    """Reutiliza el montaje de la base simulada de los estudiantes."""

    def montar_muchos(self, n=25):
        sesion = {f'{2000000 + i}': {'estadoAsistencia': 'Presente' if i % 5 else 'Ausente', 'horaRegistro': '07:01:00' if i % 5 else 'None'} for i in range(n)}
        sesion['1000001'] = {'estadoAsistencia': 'Presente', 'horaRegistro': '07:02:00'}
        extra = {('courses/c1/assistances', '2026-03-02'): sesion,
                 ('courses/c1/assistances', '2026-03-09'): {'1000001': {'estadoAsistencia': 'Ausente', 'horaRegistro': 'None'}}}
        for i in range(n):
            extra[('person', f'{2000000 + i}')] = {'type': 'Estudiante', 'namePerson': f'ALUMNO {i}'}
        self.montar(extra)

    def get(self, **params):
        return self.client.get('/api/asistencias/pagina/', {'unidad': 'c1', **params})

    def test_docente_pagina_y_resumen_de_toda_la_sesion(self):
        self.montar_muchos()
        self.como_persona('uid_doc', DOCENTE)
        r1 = self.get(fecha='2026-03-02', page=1, size=10).json()
        self.assertEqual((r1['fecha'], r1['page'], r1['totalPaginas'], len(r1['filas'])), ('2026-03-02', 1, 3, 10))
        self.assertEqual(r1['resumen']['total'], 26)                      # el resumen es de toda la sesión
        self.assertEqual(len(r1['nombres']), 10)                          # nombres solo de la página
        r3 = self.get(fecha='2026-03-02', page=3, size=10).json()
        self.assertEqual(len(r3['filas']), 6)
        vistos = [f['estudiante'] for p in (r1, self.get(fecha='2026-03-02', page=2, size=10).json(), r3) for f in p['filas']]
        self.assertEqual(len(vistos), len(set(vistos)))                   # sin repetidos entre páginas

    def test_sin_filtro_muestra_la_ultima_sesion(self):
        self.montar_muchos()
        self.como_persona('uid_doc', DOCENTE)
        r = self.get().json()
        self.assertEqual(r['fecha'], '2026-03-09')
        self.assertEqual(r['resumen']['total'], 1)

    def test_por_dia_y_por_hora(self):
        self.montar_muchos()
        self.como_persona('uid_doc', DOCENTE)
        self.assertEqual(self.get(dia='Lunes').json()['fecha'], '2026-03-09')
        self.assertEqual(self.get(dia='Viernes').json()['filas'], [])
        r = self.get(fecha='2026-03-02', hora='10:00-11:59')
        self.assertEqual(r.status_code, 200)

    def test_estudiante_solo_ve_su_fila_y_otros_no_entran(self):
        self.montar_muchos()
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.get(fecha='2026-03-02').json()
        self.assertEqual([f['estudiante'] for f in r['filas']], ['1000001'])
        self.assertEqual(r['resumen']['total'], 1)
        self.assertEqual(self.client.get('/api/asistencias/pagina/', {'unidad': 'c2'}).status_code, 403)   # no está inscrita

    def test_otro_docente_y_cuenta_sin_perfil_no_entran(self):
        self.montar_muchos()
        self.como_persona('uid_otro', {'id': '8', 'type': 'Profesor', 'namePerson': 'X', 'profesorUID': 'uid_otro', 'courses': []})
        self.assertEqual(self.get().status_code, 403)
        self.como_persona('uid_x', None)
        self.assertEqual(self.get().status_code, 403)

    def test_parametros_invalidos(self):
        self.montar_muchos()
        self.como_persona('uid_doc', DOCENTE)
        self.assertEqual(self.get(fecha='ayer').status_code, 400)
        self.assertEqual(self.get(dia='Lunez').status_code, 400)
        self.assertEqual(self.get(page='-4', size='abc').status_code, 200)

    def test_fechas_de_la_unidad(self):
        self.montar_muchos()
        self.como_persona('uid_doc', DOCENTE)
        r = self.client.get('/api/asistencias/fechas/', {'unidad': 'c1'}).json()
        self.assertEqual(r['fechas'], ['2026-03-02', '2026-03-09'])

    def test_subgrupo(self):
        self.montar({('courses/c3/groups/g1/assistances', '2026-03-05'): {'1000001': {'estadoAsistencia': 'Presente', 'horaRegistro': '10:01:00'}}})
        self.como_persona('uid_doc', DOCENTE)
        r = self.client.get('/api/asistencias/pagina/', {'unidad': 'c3::g1'}).json()
        self.assertEqual((r['fecha'], [f['id'] for f in r['filas']]), ('2026-03-05', ['c3_g1_2026-03-05_1000001']))
        self.assertEqual(r['filas'][0]['asignatura'], 'SO - Grupo 601')


class VistasEquiposDocenteTests(VistasEstudianteTests):
    def test_docente_guarda_sus_equipos(self):
        self.montar({('person', '9'): {'type': 'Profesor', 'namePerson': 'DOC', 'profesorUID': 'uid_doc', 'courses': ['c1']}})
        self.como_persona('uid_doc', DOCENTE)
        r = self.client.patch('/api/perfil/', {'equipos': [{'marca': 'Dell', 'serial': 'sn-001'}]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.fs.datos[('person', '9')]['equipos'], [{'marca': 'Dell', 'serial': 'SN-001'}])
        self.assertEqual(self.client.patch('/api/perfil/', {'equipos': [{'marca': '', 'serial': 'x'}]}, format='json').status_code, 400)
        self.assertEqual(self.client.get('/api/perfil/').json()['equipos'], [])   # (buscar_persona_por_uid está fijo en el montaje)


# ============================================
# RESPALDO AUTOMÁTICO DEL HORARIO ANTERIOR
# ============================================
from .horario_historial import periodo_anterior, periodo_de_respaldo


class RespaldoAutomaticoPuroTests(SimpleTestCase):
    def test_periodo_anterior(self):
        self.assertEqual(periodo_anterior('2026-2'), '2026-1')
        self.assertEqual(periodo_anterior('2026-1'), '2025-2')

    def test_cuando_hace_falta(self):
        self.assertEqual(periodo_de_respaldo('2026-2', set(), True), '2026-1')
        self.assertEqual(periodo_de_respaldo('2027-1', set(), True), '2026-2')

    def test_cuando_no_hace_falta(self):
        self.assertIsNone(periodo_de_respaldo('2026-2', set(), False))             # no se quita nada
        self.assertIsNone(periodo_de_respaldo('2026-2', {'2026-2'}, True))         # el período ya tiene historial
        self.assertIsNone(periodo_de_respaldo('2026-2', {'2026-1'}, True))         # el anterior ya está guardado


@override_settings(ADMIN_EMAILS=set(), REGISTRO_DOMINIOS=[])
class VistasRespaldoAutomaticoTests(MontajeVistas):
    def montar(self, datos=None):
        base = {
            ('courses', 'c1'): {'nameCourse': 'REDES', 'group': '501', 'profesorID': 'uid_prof', 'estudianteID': [],
                                 'schedule': [clase('Lunes', '07:00', '08:59', 'C-1')]},
            ('person', '9'): {'type': 'Profesor', 'namePerson': 'DOC', 'profesorUID': 'uid_prof', 'courses': ['c1']},
        }
        base.update(datos or {})
        self.fs = FakeFirestore(base)
        p = patch('api_app.views.db', self.fs)
        p.start()
        self.addCleanup(p.stop)
        c = {**base[('courses', 'c1')], 'id': 'c1', 'courseId': 'c1', 'groupId': None}
        persona = {**base[('person', '9')], 'id': '9'}
        for target, rv in (('api_app.views.buscar_persona_por_uid', persona), ('api_app.views.listar_unidades_horario', [c])):
            q = patch(target, return_value=rv)
            q.start()
            self.addCleanup(q.stop)

        def fake_auth(request):
            request.user_firebase = {'uid': 'uid_prof', 'email': 'p@x.com', 'name': 'P', 'email_verified': True}
            return 'uid_prof', None
        q = patch('api_app.views.obtener_uid_usuario', side_effect=fake_auth)
        q.start()
        self.addCleanup(q.stop)

    def importar_nuevo(self, periodo='2026-2'):
        fila = {'curso': 'REDES', 'grupo': '501', 'day': 'Jueves', 'iniTime': '10:00', 'endTime': '11:59', 'classroom': 'C-2'}
        return self.client.post('/api/horarios/importar/', {
            'filas': [fila], 'modo': 'reemplazar', 'confirmar': True, 'periodo': periodo}, format='json')

    def entradas(self):
        return sorted((v for (c, _), v in self.fs.datos.items() if c == 'horarioHistorial'), key=lambda e: e['tipo'])

    def test_al_reemplazar_se_guarda_solo_el_horario_anterior(self):
        self.montar()
        r = self.importar_nuevo('2026-2')
        self.assertEqual(r.status_code, 200, r.content)
        importacion, respaldo = self.entradas()   # ordenadas por tipo
        self.assertEqual((respaldo['tipo'], respaldo['periodo'], respaldo['cambios']), ('respaldo_automatico', '2026-1', []))
        self.assertEqual([(c['day'], c['iniTime']) for c in respaldo['horario'][0]['schedule']], [('Lunes', '07:00')])   # lo que había
        self.assertEqual((importacion['tipo'], importacion['periodo']), ('importacion', '2026-2'))
        self.assertEqual([(c['day'], c['iniTime']) for c in importacion['horario'][0]['schedule']], [('Jueves', '10:00')])  # lo nuevo

    def test_no_se_repite_el_respaldo(self):
        self.montar({('horarioHistorial', 'previo'): {'profesorID': 'uid_prof', 'periodo': '2026-1', 'tipo': 'importacion', 'fecha': '2026-03-01T08:00:00', 'cambios': [], 'horario': []}})
        self.assertEqual(self.importar_nuevo('2026-2').status_code, 200)
        self.assertEqual([e['tipo'] for e in self.entradas() if e['periodo'] != '2026-1'], ['importacion'])

    def test_el_endpoint_de_foto_manual_ya_no_existe(self):
        self.montar()
        self.assertEqual(self.client.post('/api/horarios/historial/foto/', {'periodo': '2026-1'}, format='json').status_code, 404)


# ============================================
# TODAS LAS ASISTENCIAS, POR PÁGINAS
# ============================================
class TodasPuroTests(SimpleTestCase):
    FILAS = [
        {'estudiante': '111', 'asignatura': 'REDES', 'estadoAsistencia': 'Presente', 'fechaDocId': '2026-03-02'},
        {'estudiante': '222', 'asignatura': 'REDES', 'estadoAsistencia': 'Ausente', 'fechaDocId': '2026-03-09'},
        {'estudiante': '111', 'asignatura': 'BD', 'estadoAsistencia': 'Tiene Excusa', 'fechaDocId': '2026-03-09'},
    ]

    def test_orden_mas_recientes_primero_y_estable(self):
        orden = ap.ordenar_recientes(self.FILAS)
        self.assertEqual([(f['fechaDocId'], f['asignatura']) for f in orden],
                         [('2026-03-09', 'BD'), ('2026-03-09', 'REDES'), ('2026-03-02', 'REDES')])

    def test_filtros(self):
        nombres = {'111': 'Eva Ruiz', '222': 'Luis Gómez'}
        self.assertEqual(len(ap.filtrar(self.FILAS, asignatura='REDES')), 2)
        self.assertEqual(len(ap.filtrar(self.FILAS, estado='Ausente')), 1)
        self.assertEqual(len(ap.filtrar(self.FILAS, texto='eva', nombres=nombres)), 2)       # por nombre
        self.assertEqual(len(ap.filtrar(self.FILAS, texto='22', nombres=nombres)), 1)        # por cédula
        self.assertEqual(len(ap.filtrar(self.FILAS, asignatura='REDES', estado='Presente', texto='111')), 1)
        self.assertEqual(len(ap.filtrar(self.FILAS)), 3)

    def test_conteos(self):
        c = ap.conteos(self.FILAS)
        self.assertEqual(c['asignaturas'], [{'nombre': 'BD', 'total': 1}, {'nombre': 'REDES', 'total': 2}])
        self.assertEqual(c['estados'], {'Presente': 1, 'Ausente': 1, 'Tiene Excusa': 1})


class VistasTodasTests(VistasEstudianteTests):
    def montar_historial(self, n=25):
        datos = {}
        for d in range(n):
            datos[('courses/c1/assistances', f'2026-03-{d + 1:02d}')] = {'1000001': {'estadoAsistencia': 'Presente' if d % 3 else 'Ausente', 'horaRegistro': '07:01:00'},
                                                                        '2000002': {'estadoAsistencia': 'Presente', 'horaRegistro': '07:02:00'}}
        self.montar(datos)

    def get(self, **params):
        return self.client.get('/api/asistencias/todas/', params)

    def docente(self):
        p = patch('api_app.views.obtener_cursos_profesor', return_value=[
            {'id': 'c1', 'nameCourse': 'REDES', 'group': '501'}])
        p.start()
        self.addCleanup(p.stop)
        self.como_persona('uid_doc', DOCENTE)

    def test_pagina_total_y_conteos(self):
        self.montar_historial(25)
        self.docente()
        r = self.get(page=1, size=10).json()
        self.assertEqual((len(r['filas']), r['totalPaginas'], r['totalGeneral']), (10, 5, 50))
        self.assertEqual(r['resumen']['total'], 50)
        self.assertEqual(r['asignaturas'], [{'nombre': 'REDES', 'total': 50}])
        self.assertEqual(sum(r['estados'].values()), 50)
        self.assertEqual(r['filas'][0]['fechaDocId'], '2026-03-25')            # lo más reciente primero
        self.assertEqual(len(r['nombres']), len({f['estudiante'] for f in r['filas']}))
        ultima = self.get(page=5, size=10).json()
        self.assertEqual(len(ultima['filas']), 10)
        self.assertEqual(self.get(page=99, size=10).json()['page'], 5)           # acotada

    def test_filtros_de_estado_y_busqueda_por_nombre(self):
        self.montar_historial(10)
        self.docente()
        r = self.get(estado='Ausente').json()
        self.assertTrue(r['filas'] and all(f['estadoAsistencia'] == 'Ausente' for f in r['filas']))
        self.assertEqual(r['resumen']['ausentes'], r['resumen']['total'])
        self.assertEqual(r['totalGeneral'], 20)                                    # los conteos no se achican con el filtro
        por_nombre = self.get(q='eva').json()
        self.assertEqual({f['estudiante'] for f in por_nombre['filas']}, {'1000001'})
        self.assertEqual(self.get(estado='Raro').status_code, 400)

    def test_estudiante_solo_ve_lo_suyo(self):
        self.montar_historial(5)
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.get().json()
        self.assertEqual({f['estudiante'] for f in r['filas']}, {'1000001'})
        self.assertEqual(r['totalGeneral'], 5)

    def test_cuenta_sin_perfil(self):
        self.montar_historial(2)
        self.como_persona('uid_x', None)
        self.assertEqual(self.get().status_code, 403)


# ============================================
# DATOS PARA EL REPORTE DE ASISTENCIA
# ============================================
class VistasReporteTests(VistasEstudianteTests):
    def get(self, **params):
        return self.client.get('/api/asistencias/reporte/', {'unidad': 'c1', **params})

    def test_trae_inscritos_fechas_y_registros(self):
        self.montar({('courses/c1/assistances', '2026-03-09'): {'1000001': {'estadoAsistencia': 'Ausente', 'horaRegistro': 'None'}}})
        self.como_persona('uid_doc', DOCENTE)
        r = self.get().json()
        self.assertEqual((r['unidad']['nameCourse'], r['unidad']['group'], r['unidad']['docente']), ('REDES', '501', 'DOC'))
        self.assertEqual(r['fechas'], ['2026-03-02', '2026-03-09'])
        self.assertEqual({e['cedula'] for e in r['estudiantes']}, {'1000001', '2000002'})          # inscritos del curso
        self.assertEqual(r['registros']['1000001']['2026-03-02']['estado'], 'Presente')
        self.assertEqual(r['registros']['1000001']['2026-03-09']['estado'], 'Ausente')

    def test_con_fecha_solo_esa_sesion(self):
        self.montar()
        self.como_persona('uid_doc', DOCENTE)
        r = self.get(fecha='2026-03-02').json()
        self.assertEqual(r['fechas'], ['2026-03-02'])
        self.assertEqual(self.get(fecha='mal').status_code, 400)

    def test_inscritos_sin_registro_aparecen(self):
        self.montar()
        self.como_persona('uid_doc', DOCENTE)
        r = self.get(fecha='2026-03-02').json()
        self.assertIn('2000002', {e['cedula'] for e in r['estudiantes']})
        self.assertIn('2000002', r['registros'])

    def test_estudiante_solo_su_fila_y_otros_cursos_no(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.get().json()
        self.assertEqual([e['cedula'] for e in r['estudiantes']], ['1000001'])
        self.assertEqual(list(r['registros']), ['1000001'])
        self.assertEqual(self.client.get('/api/asistencias/reporte/', {'unidad': 'c2'}).status_code, 403)

    def test_otro_docente_no(self):
        self.montar()
        self.como_persona('uid_otro', {'id': '8', 'type': 'Profesor', 'namePerson': 'X', 'profesorUID': 'uid_otro', 'courses': []})
        self.assertEqual(self.get().status_code, 403)


# ============================================
# ESTADÍSTICAS, CONSEJOS Y AVISOS
# ============================================
from . import estadisticas as est


def u_est(sesiones, estudiantes=None, nombre='REDES - Grupo 501', uid='c1'):
    """Unidad de prueba. sesiones: {fecha: {cedula: 'P'|'A'|'E'|'T'}} (T = presente que llegó tarde)."""
    estado = {'P': 'Presente', 'A': 'Ausente', 'E': 'Tiene Excusa', 'T': 'Presente'}
    ses = {f: {c: {'estado': estado[v], 'hora': '07:01:00', 'late': v == 'T'} for c, v in reg.items()} for f, reg in sesiones.items()}
    cedulas = estudiantes or sorted({c for r in sesiones.values() for c in r})
    return {'id': uid, 'nombre': nombre, 'estudiantes': {c: f'NOMBRE {c}' for c in cedulas}, 'sesiones': ses}


class EstadisticasPuroTests(SimpleTestCase):
    def seq(self, texto, inicio='2026-03-02'):
        """'PPAA' -> [(fecha, estado, late)] una clase por semana desde `inicio`."""
        from datetime import date, timedelta
        d0 = date.fromisoformat(inicio)
        est_ = {'P': 'Presente', 'A': 'Ausente', 'E': 'Tiene Excusa', 'T': 'Presente'}
        return [((d0 + timedelta(days=7 * i)).isoformat(), est_[c], c == 'T') for i, c in enumerate(texto)]

    def test_metricas(self):
        a = est.analizar(self.seq('PPTAAE'))
        self.assertEqual((a['sesiones'], a['presentes'], a['ausentes'], a['excusas'], a['tardes']), (6, 3, 2, 1, 1))
        self.assertEqual(a['tasa'], 50.0)
        self.assertEqual(a['faltasSeguidas'], 2)           # la excusa final no rompe la racha de faltas
        self.assertEqual(est.analizar(self.seq('AAPP'))['faltasSeguidas'], 0)
        self.assertEqual(est.analizar(self.seq('APPPP'))['rachaPresente'], 4)
        self.assertEqual(est.analizar(self.seq('PPEPP'))['rachaPresente'], 4)  # la excusa no rompe la racha de asistencia
        self.assertIsNone(est.analizar([])['tasa'])

    def test_peor_semana_y_dia_de_tardanza(self):
        sec = [('2026-03-02', 'Ausente', False), ('2026-03-04', 'Ausente', False), ('2026-03-06', 'Ausente', False), ('2026-03-09', 'Presente', True), ('2026-03-16', 'Presente', True)]
        a = est.analizar(sec)
        self.assertEqual(a['peorSemana'], {'lunes': '2026-03-02', 'faltas': 3, 'ultima': '2026-03-06'})
        self.assertEqual(a['diaTarde'], {'dia': 'Lunes', 'veces': 2})

    def test_resumen_tendencia_dia_curso(self):
        u1 = u_est({'2026-03-02': {'1': 'P', '2': 'A'}, '2026-03-09': {'1': 'P', '2': 'T'}})
        u2 = u_est({'2026-03-03': {'3': 'E'}}, nombre='BD - Grupo 1', uid='c2')
        r = est.resumen_general([u1, u2])
        self.assertEqual((r['total'], r['presentes'], r['ausentes'], r['excusas'], r['tardes'], r['sesiones'], r['estudiantes']), (5, 3, 1, 1, 1, 3, 3))
        self.assertEqual(r['tasa'], 60.0)
        self.assertEqual([t['fecha'] for t in est.tendencia([u1, u2])], ['2026-03-02', '2026-03-03', '2026-03-09'])
        self.assertEqual({d['dia'] for d in est.por_dia_semana([u1, u2])}, {'Lunes', 'Martes'})
        self.assertEqual([c['nombre'] for c in est.por_curso([u1, u2])], ['BD - Grupo 1', 'REDES - Grupo 501'])
        self.assertEqual(est.resumen_general([u1], desde='2026-03-05')['total'], 2)       # rango de fechas

    def test_mapa_de_calor_ordena_por_faltas(self):
        u = u_est({'2026-03-02': {'1': 'P', '2': 'A'}, '2026-03-09': {'1': 'P', '2': 'A'}}, estudiantes=['1', '2', '3'])
        m = est.mapa_de_calor(u)
        self.assertEqual(m['fechas'], ['2026-03-02', '2026-03-09'])
        self.assertEqual([f['cedula'] for f in m['filas']], ['2', '1', '3'])
        self.assertEqual(m['filas'][0]['celdas'], ['A', 'A'])
        self.assertEqual(m['filas'][2]['celdas'], ['-', '-'])                          # inscrito sin registros

    def test_consejos_docente(self):
        fechas = [f'2026-03-{d:02d}' for d in (2, 9, 16, 23, 30)]
        ses = {f: {'ausente': 'A' if i >= 3 else 'P', 'tarde': 'T' if i != 1 else 'P', 'ejemplar': 'P', 'regular': 'P'} for i, f in enumerate(fechas)}
        ses['2026-03-09']['tarde'], ses['2026-03-16']['tarde'], ses['2026-03-23']['tarde'] = 'T', 'T', 'T'
        r = est.consejos_docente([u_est(ses)])
        self.assertEqual([x['cedula'] for x in r['recordatorios']], ['ausente'])
        self.assertIn('2 faltas seguidas', r['recordatorios'][0]['motivo'])
        self.assertTrue(r['recordatorios'][0]['mensaje'].startswith('Hola '))
        self.assertEqual([x['cedula'] for x in r['tardanzas']], ['tarde'])
        self.assertIn('Lunes', r['tardanzas'][0]['detalle'])
        self.assertEqual({x['cedula'] for x in r['incentivos']}, {'ejemplar', 'regular'})
        self.assertEqual(next(x for x in r['incentivos'] if x['cedula'] == 'ejemplar')['tipo'], 'perfecta')

    def test_baja_asistencia_sin_faltas_seguidas(self):
        ses = {f: {'x': e} for f, e in zip(['2026-03-02', '2026-03-09', '2026-03-16', '2026-03-23', '2026-03-30'], 'AAPAP')}
        # termina en P: sin faltas seguidas, pero 60 % < 80 %
        r = est.consejos_docente([u_est(ses)])
        self.assertEqual(r['recordatorios'][0]['motivo'], 'Asistencia de 40.0 %')

    def test_pocas_clases_no_dispara_baja_asistencia(self):
        r = est.consejos_docente([u_est({'2026-03-02': {'x': 'A'}, '2026-03-09': {'x': 'P'}})])
        self.assertEqual(r['recordatorios'], [])

    def test_alertas_criticas_solo_graves_y_recientes(self):
        u = u_est({
            '2026-03-02': {'a': 'A', 'b': 'A'}, '2026-03-04': {'a': 'A', 'b': 'P'}, '2026-03-06': {'a': 'A', 'b': 'A'},
        })
        av = est.alertas_criticas_docente([u], hoy='2026-03-10')
        self.assertEqual([x['cedula'] for x in av], ['a'])                 # 'b' solo faltó 2 veces en la semana
        self.assertTrue(av[0]['id'].startswith('semana:c1:a:2026-03-02:3'))
        self.assertEqual(est.alertas_criticas_docente([u], hoy='2026-05-01'), [])   # ya no es reciente

    def test_alerta_por_faltas_seguidas_en_semanas_distintas(self):
        u = u_est({f'2026-03-{d:02d}': {'a': 'A'} for d in (2, 9, 16, 23)})
        av = est.alertas_criticas_docente([u], hoy='2026-03-25')
        self.assertEqual(len(av), 1)
        self.assertTrue(av[0]['id'].startswith('seguidas:'))

    def test_avisos_del_estudiante(self):
        u = u_est({f'2026-03-{d:02d}': {'yo': e} for d, e in zip((2, 9, 16, 23, 30), 'PPPPP')})
        tipos = [a['tipo'] for a in est.avisos_estudiante([u], 'yo', '2026-04-01')]
        self.assertEqual(tipos, ['incentivo'])
        u = u_est({f'2026-03-{d:02d}': {'yo': e} for d, e in zip((2, 9, 16), 'PAA')})
        av = est.avisos_estudiante([u], 'yo', '2026-04-01')
        self.assertEqual((av[0]['tipo'], 'faltas seguidas' in av[0]['titulo']), ('recordatorio', True))
        self.assertEqual(est.avisos_estudiante([u], 'otro', '2026-04-01'), [])        # sin datos propios, sin avisos


class VistasEstadisticasTests(VistasEstudianteTests):
    def datos_semana_critica(self):
        return {
            ('courses/c1/assistances', '2026-03-02'): {'1000001': {'estadoAsistencia': 'Ausente', 'horaRegistro': 'None'}, '2000002': {'estadoAsistencia': 'Presente', 'horaRegistro': '07:00:00'}},
            ('courses/c1/assistances', '2026-03-04'): {'1000001': {'estadoAsistencia': 'Ausente', 'horaRegistro': 'None'}, '2000002': {'estadoAsistencia': 'Presente', 'horaRegistro': '07:00:00'}},
            ('courses/c1/assistances', '2026-03-06'): {'1000001': {'estadoAsistencia': 'Ausente', 'horaRegistro': 'None'}, '2000002': {'estadoAsistencia': 'Presente', 'horaRegistro': '07:00:00'}},
        }

    def docente(self):
        unidades = [{'id': 'c1', 'courseId': 'c1', 'groupId': None, 'nameCourse': 'REDES', 'group': '501', 'estudianteID': ['1000001', '2000002'], 'schedule': []}]
        p = patch('api_app.views.listar_unidades_horario', return_value=unidades)
        p.start()
        self.addCleanup(p.stop)
        self.como_persona('uid_doc', DOCENTE)

    def test_estadisticas_del_docente(self):
        self.montar(self.datos_semana_critica())
        self.docente()
        r = self.client.get('/api/estadisticas/', {'unidad': 'c1'}).json()
        self.assertEqual((r['resumen']['total'], r['resumen']['ausentes'], r['resumen']['presentes']), (6, 3, 3))
        self.assertEqual([t['fecha'] for t in r['tendencia']], ['2026-03-02', '2026-03-04', '2026-03-06'])
        self.assertEqual(r['mapa']['filas'][0]['cedula'], '1000001')                      # el que más falta, primero
        self.assertEqual(r['mapa']['filas'][0]['nombre'], 'EVA RUIZ')                     # con nombre real
        self.assertEqual([x['cedula'] for x in r['consejos']['recordatorios']], ['1000001'])
        self.assertEqual(r['unidades'], [{'id': 'c1', 'nombre': 'REDES - Grupo 501'}])

    def test_sin_filtro_no_hay_mapa_y_unidad_ajena_se_rechaza(self):
        self.montar(self.datos_semana_critica())
        self.docente()
        self.assertEqual(self.client.get('/api/estadisticas/', {'unidad': 'c9'}).status_code, 403)
        otra = [{'id': 'c1', 'courseId': 'c1', 'groupId': None, 'nameCourse': 'REDES', 'group': '501', 'estudianteID': ['1000001'], 'schedule': []},
                {'id': 'c2', 'courseId': 'c2', 'groupId': None, 'nameCourse': 'BD', 'group': '502', 'estudianteID': [], 'schedule': []}]
        with patch('api_app.views.listar_unidades_horario', return_value=otra):
            r = self.client.get('/api/estadisticas/').json()
        self.assertIsNone(r['mapa'])
        self.assertEqual(len(r['unidades']), 2)

    def test_el_estudiante_no_ve_estadisticas_del_docente(self):
        self.montar(self.datos_semana_critica())
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.get('/api/estadisticas/').status_code, 403)
        self.assertEqual(self.client.get('/api/estadisticas/', {'desde': 'mal'}).status_code, 400)

    def test_campanita_del_docente_solo_casos_criticos(self):
        self.montar(self.datos_semana_critica())
        self.docente()
        with patch('django.utils.timezone.now', return_value=__import__('datetime').datetime(2026, 3, 10, 12, 0, tzinfo=__import__('datetime').timezone.utc)):
            r = self.client.get('/api/notificaciones/').json()
        self.assertEqual(len(r['avisos']), 1)
        self.assertIn('EVA RUIZ', r['avisos'][0]['titulo'])
        self.assertEqual(r['avisos'][0]['tipo'], 'critica')

    def test_campanita_del_estudiante_solo_lo_suyo(self):
        self.montar(self.datos_semana_critica())
        self.como_persona('uid_eva', ESTUDIANTE)
        with patch('django.utils.timezone.now', return_value=__import__('datetime').datetime(2026, 3, 10, 12, 0, tzinfo=__import__('datetime').timezone.utc)):
            r = self.client.get('/api/notificaciones/').json()
        self.assertEqual([a['tipo'] for a in r['avisos']], ['recordatorio'])
        self.assertIn('faltas seguidas', r['avisos'][0]['titulo'])
        self.assertNotIn('2000002', str(r))


# ============================================
# TÉRMINOS, DATOS PERSONALES Y BIOMETRÍA
# ============================================
from . import legal as lg


class LegalPuroTests(SimpleTestCase):
    def test_aceptar_exige_terminos_y_datos_pero_no_biometria(self):
        self.assertEqual(lg.validar_aceptacion({'terminos': True, 'datosPersonales': True})[0], {'biometrico': False})
        self.assertEqual(lg.validar_aceptacion({'terminos': True, 'datosPersonales': True, 'biometrico': True})[0], {'biometrico': True})
        for datos in ({}, {'terminos': True}, {'datosPersonales': True}, {'terminos': 'si', 'datosPersonales': True}, 'x'):
            self.assertTrue(lg.validar_aceptacion(datos)[1], datos)

    def test_vigencia_por_version(self):
        a = lg.construir_aceptacion(False)
        self.assertTrue(lg.esta_vigente(a))
        self.assertFalse(lg.esta_vigente({**a, 'version': '2000-01-01'}))   # texto nuevo: hay que aceptar de nuevo
        self.assertFalse(lg.esta_vigente(None))

    def test_solicitud(self):
        self.assertEqual(lg.validar_solicitud({'tipo': 'supresion', 'detalle': '  Quiero que borren   mis datos  '})[0],
                         {'tipo': 'supresion', 'detalle': 'Quiero que borren mis datos'})
        for datos in ({'tipo': 'x', 'detalle': 'Quiero que borren mis datos'}, {'tipo': 'supresion', 'detalle': 'corto'},
                      {'tipo': 'consulta', 'detalle': 'a' * 700}):
            self.assertTrue(lg.validar_solicitud(datos)[1])


@override_settings(ADMIN_EMAILS={ADMIN}, REGISTRO_DOMINIOS=['ucundinamarca.edu.co'])
class VistasLegalTests(VistasEstudianteTests):
    def test_sin_aceptar_no_esta_vigente_y_luego_si(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        g = self.client.get('/api/legal/aceptacion/').json()
        self.assertEqual((g['vigente'], g['aplica'], g['version']), (False, True, lg.VERSION))
        r = self.client.post('/api/legal/aceptacion/', {'terminos': True, 'datosPersonales': True, 'biometrico': False}, format='json')
        self.assertEqual(r.status_code, 200)
        guardada = self.fs.datos[('person', '1000001')]['aceptacionLegal']
        self.assertEqual((guardada['version'], guardada['biometrico']), (lg.VERSION, False))
        constancias = [v for (c, _), v in self.fs.datos.items() if c == 'aceptacionesLegales']
        self.assertEqual([(c['evento'], c['cedula']) for c in constancias], [('aceptacion', '1000001')])

    def test_no_se_puede_aceptar_a_medias(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.post('/api/legal/aceptacion/', {'terminos': True}, format='json').status_code, 400)
        self.assertNotIn('aceptacionLegal', self.fs.datos[('person', '1000001')])

    def test_cuenta_sin_persona_no_aplica(self):
        self.montar()
        self.como_persona('uid_x', None)
        self.assertEqual(self.client.get('/api/legal/aceptacion/').json()['aplica'], False)
        self.assertEqual(self.client.post('/api/legal/aceptacion/', {'terminos': True, 'datosPersonales': True}, format='json').status_code, 403)

    def test_otorgar_y_revocar_biometria_deja_constancia(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.client.post('/api/legal/aceptacion/', {'terminos': True, 'datosPersonales': True}, format='json')
        persona = {**ESTUDIANTE, **self.fs.datos[('person', '1000001')]}
        self.como_persona('uid_eva', persona)
        self.assertEqual(self.client.post('/api/legal/biometrico/', {'autoriza': True}, format='json').status_code, 200)
        self.assertTrue(self.fs.datos[('person', '1000001')]['aceptacionLegal']['biometrico'])
        persona = {**ESTUDIANTE, **self.fs.datos[('person', '1000001')]}
        self.como_persona('uid_eva', persona)
        self.client.post('/api/legal/biometrico/', {'autoriza': False}, format='json')
        self.assertFalse(self.fs.datos[('person', '1000001')]['aceptacionLegal']['biometrico'])
        eventos = sorted(v['evento'] for (c, _), v in self.fs.datos.items() if c == 'aceptacionesLegales')
        self.assertEqual(eventos, ['aceptacion', 'biometrico_otorgado', 'biometrico_revocado'])
        self.assertEqual(self.client.post('/api/legal/biometrico/', {'autoriza': 'si'}, format='json').status_code, 400)

    def test_biometria_exige_haber_aceptado_la_version_vigente(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.post('/api/legal/biometrico/', {'autoriza': True}, format='json').status_code, 409)

    def test_solicitud_de_supresion_y_atencion_por_el_admin(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        r = self.client.post('/api/legal/solicitudes/', {'tipo': 'supresion', 'detalle': 'Quiero que eliminen mis datos'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.client.post('/api/legal/solicitudes/', {'tipo': 'supresion', 'detalle': 'Quiero que eliminen mis datos'}, format='json').status_code, 409)
        mias = self.client.get('/api/legal/solicitudes/').json()['solicitudes']
        self.assertEqual([(m['tipo'], m['estado']) for m in mias], [('supresion', 'pendiente')])
        sid = mias[0]['id']
        self.assertEqual(self.client.post(f'/api/admin/legal/solicitudes/{sid}/atender/', {'respuesta': 'Hecho'}, format='json').status_code, 403)
        self.como_persona('uid_admin', DOCENTE, email=ADMIN)
        self.assertEqual(self.client.post(f'/api/admin/legal/solicitudes/{sid}/atender/', {'respuesta': 'Tus datos fueron eliminados.'}, format='json').status_code, 200)
        self.assertEqual(self.client.post(f'/api/admin/legal/solicitudes/{sid}/atender/', {'respuesta': 'otra vez'}, format='json').status_code, 400)
        listado = self.client.get('/api/admin/legal/').json()
        self.assertEqual([(x['tipo'], x['estado']) for x in listado['solicitudes']], [('supresion', 'atendida')])

    def test_un_estudiante_no_ve_el_panel_legal_del_admin(self):
        self.montar()
        self.como_persona('uid_eva', ESTUDIANTE)
        self.assertEqual(self.client.get('/api/admin/legal/').status_code, 403)
