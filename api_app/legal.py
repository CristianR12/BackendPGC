"""
Aceptación de términos, tratamiento de datos y autorización biométrica; solicitudes sobre los datos.

Lógica pura (sin Firestore). La versión vigente de los textos vive aquí: al cambiarla, todos deben aceptar de nuevo.
La autorización de datos biométricos es OPCIONAL y se guarda aparte: negarla no impide usar el sistema
(la asistencia se registra a mano). Marco: Ley 1581 de 2012 y Decreto 1377 de 2013.
"""
from datetime import datetime

# Debe coincidir con VERSION_LEGAL de FrontendPGC/src/legal/contenido.ts
VERSION = '2026-10-04'

TIPOS_SOLICITUD = ('consulta', 'rectificacion', 'supresion', 'revocatoria')
ESTADOS_SOLICITUD = ('pendiente', 'atendida')
MAX_DETALLE = 600


def validar_aceptacion(datos):
    """Aceptar términos y tratamiento de datos es obligatorio para usar el sistema; la biometría no."""
    if not isinstance(datos, dict):
        return None, ['Datos inválidos.']
    errores = []
    if datos.get('terminos') is not True:
        errores.append('Debes aceptar los términos y condiciones para continuar.')
    if datos.get('datosPersonales') is not True:
        errores.append('Debes autorizar el tratamiento de tus datos personales para continuar.')
    if errores:
        return None, errores
    return {'biometrico': datos.get('biometrico') is True}, []


def construir_aceptacion(biometrico, momento=None, version=VERSION):
    return {
        'version': version,
        'fecha': (momento or datetime.now()).isoformat(),
        'terminos': True,
        'datosPersonales': True,
        'biometrico': bool(biometrico),
    }


def esta_vigente(aceptacion, version=VERSION):
    return bool(aceptacion) and aceptacion.get('version') == version and aceptacion.get('terminos') is True \
        and aceptacion.get('datosPersonales') is True


def validar_solicitud(datos):
    if not isinstance(datos, dict):
        return None, ['Datos inválidos.']
    tipo = str(datos.get('tipo') or '')
    detalle = ' '.join(str(datos.get('detalle') or '').split())
    errores = []
    if tipo not in TIPOS_SOLICITUD:
        errores.append('Tipo de solicitud inválido.')
    if len(detalle) < 10:
        errores.append('Cuéntanos con un poco más de detalle qué necesitas (mínimo 10 caracteres).')
    if len(detalle) > MAX_DETALLE:
        errores.append(f'El detalle es demasiado largo (máximo {MAX_DETALLE} caracteres).')
    if errores:
        return None, errores
    return {'tipo': tipo, 'detalle': detalle}, []
