# api_app/permissions.py
from firebase_admin import auth
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def verificar_token(request):
    """
    Verifica el token de Firebase ID en el header Authorization
    
    Returns:
        Response | None: 
            - None si el token es válido
            - Response con error si hay algún problema
    """
    try:
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            logger.warning("⚠️ No se encontró header de autorización")
            return Response(
                {"Error": "No se encontró el token de autorización."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        parts = auth_header.split(' ')
        
        if len(parts) != 2 or parts[0] != 'Bearer':
            logger.warning(f"⚠️ Formato de token inválido")
            return Response(
                {"Error": "Formato de token inválido. Usa 'Bearer <token>'"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        id_token = parts[1]

        try:
            # Verificar el token con Firebase Admin (con verificación de revocación)
            decoded_token = auth.verify_id_token(id_token, check_revoked=True)
            
            # Guardar información del usuario en el request
            request.user_firebase = decoded_token
            
            logger.info(f"✅ Token válido - Usuario: {decoded_token.get('email', 'N/A')}")
            
            return None  # Token válido

        except auth.InvalidIdTokenError:
            logger.error("❌ Token inválido")
            return Response(
                {"Error": "Token inválido. Por favor, inicia sesión nuevamente."},
                status=status.HTTP_401_UNAUTHORIZED
            )
            
        except auth.ExpiredIdTokenError:
            logger.error("❌ Token expirado")
            return Response(
                {"Error": "Tu sesión ha expirado. Por favor, inicia sesión nuevamente."},
                status=status.HTTP_401_UNAUTHORIZED
            )
            
        except auth.RevokedIdTokenError:
            logger.error("❌ Token revocado")
            return Response(
                {"Error": "Tu sesión ha sido revocada. Por favor, inicia sesión nuevamente."},
                status=status.HTTP_401_UNAUTHORIZED
            )
            
        except Exception as e:
            logger.error(f"❌ Error verificando token: {str(e)}")
            return Response(
                {"Error": "Error verificando token. Intenta iniciar sesión nuevamente."},
                status=status.HTTP_401_UNAUTHORIZED
            )
            
    except Exception as e:
        logger.error(f"❌ Error general en verificar_token: {str(e)}")
        return Response(
            {"Error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )