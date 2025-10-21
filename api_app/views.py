from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from firebase_admin import firestore
from .serializers import AsistenciaSerializer, UserSerializer
import logging
from datetime import datetime

# Configurar logger
logger = logging.getLogger(__name__)
db = firestore.client()

# ============================================
# LISTAR TODAS LAS ASISTENCIAS
# ============================================
class AsistenciaList(APIView):
    """
    GET /api/asistencias/
    Lista todas las asistencias registradas
    """
    def get(self, request):
        try:
            logger.info("=" * 60)
            logger.info("📥 [GET] /api/asistencias/ - Petición recibida")
            logger.info(f"🌐 Origen: {request.META.get('HTTP_ORIGIN', 'Desconocido')}")
            logger.info(f"🕐 Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Obtener documentos de Firebase
            docs = db.collection("asistenciaReconocimiento").stream()
            data = []
            
            for doc in docs:
                doc_data = doc.to_dict()
                doc_data['id'] = doc.id
                data.append(doc_data)
                logger.debug(f"   📄 Documento: {doc.id}")
            
            logger.info(f"✅ [SUCCESS] Devolviendo {len(data)} asistencias")
            
            if len(data) > 0:
                logger.info(f"📊 Primeros registros:")
                for item in data[:3]:
                    logger.info(f"   - {item.get('estudiante', 'N/A')}: {item.get('estadoAsistencia', 'N/A')}")
            else:
                logger.warning("⚠️  No hay asistencias registradas en Firebase")
            
            logger.info("=" * 60)
            
            return Response(data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ [ERROR] Error en AsistenciaList.get()")
            logger.error(f"❌ Tipo de error: {type(e).__name__}")
            logger.error(f"❌ Mensaje: {str(e)}")
            logger.error(f"❌ Detalles: {repr(e)}")
            logger.error("=" * 60)
            
            return Response(
                {
                    "error": "Error al obtener asistencias",
                    "detail": str(e),
                    "type": type(e).__name__
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# CREAR NUEVA ASISTENCIA
# ============================================
class AsistenciaCreate(APIView):
    """
    POST /api/asistencias/crear/
    Crea una nueva asistencia
    """
    def post(self, request):
        try:
            logger.info("=" * 60)
            logger.info("📥 [POST] /api/asistencias/crear/ - Petición recibida")
            logger.info(f"📦 Datos recibidos: {request.data}")
            
            serializer = AsistenciaSerializer(data=request.data)
            
            if serializer.is_valid():
                # Agregar timestamp si no viene
                validated_data = serializer.validated_data
                if 'fechaYhora' not in validated_data or not validated_data['fechaYhora']:
                    validated_data['fechaYhora'] = datetime.now().isoformat()
                    logger.info(f"🕐 Timestamp agregado automáticamente: {validated_data['fechaYhora']}")
                
                # Guardar en Firebase
                doc_ref = db.collection("asistenciaReconocimiento").add(validated_data)
                doc_id = doc_ref[1].id
                
                logger.info(f"✅ [SUCCESS] Asistencia creada con ID: {doc_id}")
                logger.info(f"👤 Estudiante: {validated_data.get('estudiante')}")
                logger.info(f"📊 Estado: {validated_data.get('estadoAsistencia')}")
                logger.info("=" * 60)
                
                return Response(
                    {
                        "id": doc_id,
                        **validated_data
                    },
                    status=status.HTTP_201_CREATED
                )
            else:
                logger.warning("⚠️  [WARNING] Datos inválidos")
                logger.warning(f"❌ Errores: {serializer.errors}")
                logger.info("=" * 60)
                
                return Response(
                    {
                        "error": "Datos inválidos",
                        "details": serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ [ERROR] Error en AsistenciaCreate.post()")
            logger.error(f"❌ Error: {str(e)}")
            logger.error("=" * 60)
            
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# OBTENER DETALLE DE UNA ASISTENCIA
# ============================================
class AsistenciaRetrieve(APIView):
    """
    GET /api/asistencias/<id>/
    Obtiene los detalles de una asistencia específica
    """
    def get(self, request, pk):
        try:
            logger.info("=" * 60)
            logger.info(f"📥 [GET] /api/asistencias/{pk}/ - Petición recibida")
            
            doc = db.collection("asistenciaReconocimiento").document(pk).get()
            
            if not doc.exists:
                logger.warning(f"⚠️  [NOT FOUND] Asistencia con ID {pk} no existe")
                logger.info("=" * 60)
                
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            data = doc.to_dict()
            data['id'] = doc.id
            
            logger.info(f"✅ [SUCCESS] Asistencia encontrada")
            logger.info(f"👤 Estudiante: {data.get('estudiante')}")
            logger.info("=" * 60)
            
            return Response(data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ [ERROR] Error en AsistenciaRetrieve.get({pk})")
            logger.error(f"❌ Error: {str(e)}")
            logger.error("=" * 60)
            
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# ACTUALIZAR ASISTENCIA
# ============================================
class AsistenciaUpdate(APIView):
    """
    PUT /api/asistencias/<id>/update/
    Actualiza una asistencia existente
    """
    def put(self, request, pk):
        try:
            logger.info("=" * 60)
            logger.info(f"📥 [PUT] /api/asistencias/{pk}/update/ - Petición recibida")
            logger.info(f"📦 Datos a actualizar: {request.data}")
            
            # Verificar que existe
            doc_ref = db.collection("asistenciaReconocimiento").document(pk)
            doc = doc_ref.get()
            
            if not doc.exists:
                logger.warning(f"⚠️  [NOT FOUND] Asistencia con ID {pk} no existe")
                logger.info("=" * 60)
                
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Actualizar solo los campos enviados (PUT parcial)
            update_data = {}
            if 'estudiante' in request.data:
                update_data['estudiante'] = request.data['estudiante']
            if 'estadoAsistencia' in request.data:
                update_data['estadoAsistencia'] = request.data['estadoAsistencia']
            if 'asignatura' in request.data:
                update_data['asignatura'] = request.data['asignatura']
            
            # Actualizar en Firebase
            doc_ref.update(update_data)
            
            # Obtener documento actualizado
            updated_doc = doc_ref.get()
            updated_data = updated_doc.to_dict()
            updated_data['id'] = pk
            
            logger.info(f"✅ [SUCCESS] Asistencia {pk} actualizada")
            logger.info(f"📝 Campos actualizados: {list(update_data.keys())}")
            logger.info("=" * 60)
            
            return Response(updated_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ [ERROR] Error en AsistenciaUpdate.put({pk})")
            logger.error(f"❌ Error: {str(e)}")
            logger.error("=" * 60)
            
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# ELIMINAR ASISTENCIA
# ============================================
class AsistenciaDelete(APIView):
    """
    DELETE /api/asistencias/<id>/delete/
    Elimina una asistencia
    """
    def delete(self, request, pk):
        try:
            logger.info("=" * 60)
            logger.info(f"📥 [DELETE] /api/asistencias/{pk}/delete/ - Petición recibida")
            
            # Verificar que existe antes de eliminar
            doc_ref = db.collection("asistenciaReconocimiento").document(pk)
            doc = doc_ref.get()
            
            if not doc.exists:
                logger.warning(f"⚠️  [NOT FOUND] Asistencia con ID {pk} no existe")
                logger.info("=" * 60)
                
                return Response(
                    {"error": "Asistencia no encontrada"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Obtener datos antes de eliminar para el log
            data = doc.to_dict()
            estudiante = data.get('estudiante', 'N/A')
            
            # Eliminar
            doc_ref.delete()
            
            logger.info(f"✅ [SUCCESS] Asistencia {pk} eliminada")
            logger.info(f"👤 Estudiante eliminado: {estudiante}")
            logger.info("=" * 60)
            
            return Response(
                {
                    'success': True,
                    'message': 'Asistencia eliminada exitosamente',
                    'id': pk
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ [ERROR] Error en AsistenciaDelete.delete({pk})")
            logger.error(f"❌ Error: {str(e)}")
            logger.error("=" * 60)
            
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# HEALTH CHECK (NUEVO)
# ============================================
class HealthCheck(APIView):
    """
    GET /api/health/
    Verifica que el servidor esté funcionando
    """
    def get(self, request):
        logger.info("💚 [HEALTH CHECK] Servidor funcionando correctamente")
        
        # Verificar conexión a Firebase
        try:
            # Intentar leer la colección
            docs_count = len(list(db.collection("asistenciaReconocimiento").limit(1).stream()))
            firebase_status = "✅ Conectado"
        except Exception as e:
            firebase_status = f"❌ Error: {str(e)}"
            logger.error(f"❌ Firebase error: {str(e)}")
        
        return Response({
            "status": "OK",
            "timestamp": datetime.now().isoformat(),
            "firebase": firebase_status,
            "endpoints": {
                "list": "/api/asistencias/",
                "create": "/api/asistencias/crear/",
                "detail": "/api/asistencias/<id>/",
                "update": "/api/asistencias/<id>/update/",
                "delete": "/api/asistencias/<id>/delete/"
            }
        }, status=status.HTTP_200_OK)