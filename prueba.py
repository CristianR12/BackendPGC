#!/usr/bin/env python
"""
Script de prueba directa para verificar lectura de Firebase
Ejecutar con: python test_firebase.py
"""

import firebase_admin
from firebase_admin import credentials, firestore

# Inicializar Firebase
cred = credentials.Certificate("CredencialesFirebase/asistenciaconreconocimiento-firebase-adminsdk.json")
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)

db = firestore.client()

print("=" * 80)
print("🔥 PRUEBA DIRECTA DE FIREBASE - LECTURA DE ASISTENCIAS")
print("=" * 80)

# Obtener todos los cursos
courses_ref = db.collection("courses")
all_courses = list(courses_ref.stream())

print(f"\n📚 TOTAL DE CURSOS ENCONTRADOS: {len(all_courses)}\n")

asistencias_totales = 0

for course in all_courses:
    course_id = course.id
    course_data = course.to_dict()
    course_name = course_data.get('nameCourse', 'Sin nombre')
    
    print(f"{'='*80}")
    print(f"📖 CURSO: {course_name}")
    print(f"   ID: {course_id}")
    print(f"   Profesor ID: {course_data.get('profesorID', 'N/A')}")
    
    # Obtener subcolección assistances
    assistances_ref = db.collection("courses").document(course_id).collection("assistances")
    assistances_docs = list(assistances_ref.stream())
    
    print(f"   📅 Documentos de asistencia (fechas): {len(assistances_docs)}")
    
    if len(assistances_docs) == 0:
        print(f"   ⚠️  Sin asistencias registradas")
    else:
        for assistance_doc in assistances_docs:
            fecha_id = assistance_doc.id
            assistance_data = assistance_doc.to_dict()
            
            print(f"\n   📆 FECHA: {fecha_id}")
            print(f"      Campos en el documento: {list(assistance_data.keys())}")
            
            estudiantes_count = 0
            for cedula, estudiante_data in assistance_data.items():
                # 🔍 DIAGNÓSTICO: Ver qué tipo de dato es
                tipo_dato = type(estudiante_data).__name__
                print(f"      🔍 Campo '{cedula}' es de tipo: {tipo_dato}")
                print(f"         Valor: {estudiante_data}")
                
                # ✅ Manejar tanto dict como string
                if isinstance(estudiante_data, dict):
                    estudiantes_count += 1
                    asistencias_totales += 1
                    
                    estado = estudiante_data.get('estadoAsistencia', 'N/A')
                    hora = estudiante_data.get('horaRegistro', 'N/A')
                    
                    print(f"      👤 Estudiante: {cedula} (DICT)")
                    print(f"         Estado: {estado}")
                    print(f"         Hora: {hora}")
                
                elif isinstance(estudiante_data, str):
                    # Es un string, probablemente solo el estado
                    estudiantes_count += 1
                    asistencias_totales += 1
                    
                    print(f"      👤 Estudiante: {cedula} (STRING)")
                    print(f"         Estado: {estudiante_data}")
                
                else:
                    print(f"      ⚠️  Tipo de dato no reconocido: {tipo_dato}")
            
            print(f"      ✅ Total estudiantes en esta fecha: {estudiantes_count}")
    
    print()

print("=" * 80)
print(f"✅ RESUMEN FINAL:")
print(f"   📚 Total cursos procesados: {len(all_courses)}")
print(f"   👥 Total asistencias encontradas: {asistencias_totales}")
print("=" * 80)