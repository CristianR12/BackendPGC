from firebase_admin import auth
from rest_framework.response import Response
from rest_framework import status

def verificar_token(request):
    auth_header = request.headers.get('Authorization')
    
    if not auth_header:
        return Response(
            {"Error": "No se encontró el token de autorización."},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # El token viene como: "Bearer <token>"
    parts = auth_header.split(' ')
    if len(parts) != 2 or parts[0] != 'Bearer':
        return Response(
            {"Error": "Formato de token inválido. Usa 'Bearer <token>'"},
            status=status.HTTP_401_UNAUTHORIZED
        )

    id_token = parts[1]

    try:
        decoded_token = auth.verify_id_token(id_token)
        request.user_firebase = decoded_token  # Puedes accederlo luego en la vista
        return None  # Ningún error → token válido

    except auth.InvalidIdTokenError:
        return Response({"Error": "Token inválido."}, status=status.HTTP_401_UNAUTHORIZED)
    except auth.ExpiredIdTokenError:
        return Response({"Error": "Token expirado."}, status=status.HTTP_401_UNAUTHORIZED)
    except auth.RevokedIdTokenError:
        return Response({"Error": "Token revocado."}, status=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
        return Response({"Error": f"Error verificando token: {str(e)}"}, status=status.HTTP_401_UNAUTHORIZED)
