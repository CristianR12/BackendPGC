# api_app/permissions.py
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def verificar_token(request):
    """
    Extrae el UID del header sin verificar el token
    """
    try:
        # Buscar UID en headers personalizados
        uid = request.headers.get('X-User-UID')
        
        if not uid:
            logger.warning("⚠️ No se encontró UID en headers")
            return Response(
                {"Error": "No se encontró el UID del usuario."},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Guardar UID en el request (simulando estructura de Firebase)
        request.user_firebase = {
            'uid': uid,
            'email': request.headers.get('X-User-Email', 'N/A'),
            'name': request.headers.get('X-User-Name', 'Usuario')
        }
        
        logger.info(f"✅ UID recibido: {uid}")
        return None  # Acceso permitido
        
    except Exception as e:
        logger.error(f"❌ Error al extraer UID: {str(e)}")
        return Response(
            {"Error": "Error al procesar usuario"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )