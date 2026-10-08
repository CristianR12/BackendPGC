"""
Unidades de horario.

Un horario vive en un documento de Firestore que puede ser de dos tipos:
  - un curso:      courses/{cursoId}                    (schedule en el curso)
  - un subgrupo:   courses/{cursoId}/groups/{grupoId}   (schedule en el subgrupo)

Para tratarlos igual, cada uno es una "unidad de horario" con un id único: el del curso, o
'cursoId::grupoId' para un subgrupo. Este módulo solo define el formato del id.
"""

SEP = '::'


def id_unidad(course_id, group_id=None):
    return f'{course_id}{SEP}{group_id}' if group_id else course_id


def separar_id_unidad(unidad_id):
    """'c1' -> ('c1', None);  'c1::101 ISC UBT' -> ('c1', '101 ISC UBT')."""
    unidad_id = str(unidad_id or '')
    if SEP in unidad_id:
        curso, grupo = unidad_id.split(SEP, 1)
        return curso, grupo or None
    return unidad_id, None
