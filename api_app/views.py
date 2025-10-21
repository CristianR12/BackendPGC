from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from firebase_admin import firestore
from .serializers import AsistenciaSerializer, UserSerializer
from firebase_admin.exceptions import FirebaseError
from google.api_core.exceptions import PermissionDenied, NotFound

db = firestore.client()

# ----- MANEJO DE ERRORES FIREBASE ----
def handle_firestore_error(e):
    if isinstance(e, PermissionDenied):
        return Response({"error": "Acceso denegado a Firestore"}, status=status.HTTP_403_FORBIDDEN)
    elif isinstance(e, NotFound):
        return Response({"error": "Documento no encontrado"}, status=status.HTTP_404_NOT_FOUND)
    elif isinstance(e, FirebaseError):
        return Response({"error": "Error interno del servicio Firebase"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    else:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ----- LISTAR TODAS -----
class AsistenciaList(APIView):
    def get(self, request):
        try:
            docs = db.collection("asistenciaReconocimiento").stream()
            data = [{**doc.to_dict(), "id": doc.id} for doc in docs]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return handle_firestore_error(e)


# ----- CREAR -----
class AsistenciaCreate(APIView):
    def post(self, request):
        try:
            serializer = AsistenciaSerializer(data=request.data)
            if serializer.is_valid():
                doc_ref = db.collection("asistenciaReconocimiento").add(serializer.validated_data)
                return Response(
                    {"id": doc_ref[1].id, **serializer.validated_data},
                    status=status.HTTP_201_CREATED
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied:
            return Response({"error": "No tienes permisos para crear registros"}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return handle_firestore_error(e)


# ----- OBTENER DETALLE -----
class AsistenciaRetrieve(APIView):
    def get(self, request, pk):
        try:
            doc = db.collection("asistenciaReconocimiento").document(pk).get()
            if not doc.exists:
                return Response({"error": "Asistencia no encontrada"}, status=status.HTTP_404_NOT_FOUND)
            return Response({**doc.to_dict(), "id": doc.id}, status=status.HTTP_200_OK)
        except Exception as e:
            return handle_firestore_error(e)

# ----- ACTUALIZAR -----
class AsistenciaUpdate(APIView):
    def put(self, request, pk):
        try:
            serializer = AsistenciaSerializer(data=request.data)
            if serializer.is_valid():
                db.collection("asistenciaReconocimiento").document(pk).set(serializer.validated_data)
                return Response({"id": pk, **serializer.validated_data}, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied:
            return Response({"error": "No tienes permisos para actualizar este registro"}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return handle_firestore_error(e)


# ----- ELIMINAR -----
class AsistenciaDelete(APIView):
    def delete(self, request, pk):
        try:
            db.collection("asistenciaReconocimiento").document(pk).delete()
            return Response(
                {'success': True, 'detail': 'Asistencia eliminada con éxito.'},
                status=status.HTTP_204_NO_CONTENT
            )
        except PermissionDenied:
            return Response({"error": "No tienes permisos para eliminar este registro"}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return handle_firestore_error(e)
            
    
# ------------------------------
# USERS
# ------------------------------
class UserListCreate(APIView):
    def get(self, request):
        try:
            docs = db.collection("users").stream()
            data = [{**doc.to_dict(), "id": doc.id} for doc in docs]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return handle_firestore_error(e)
            
    def post(self, request):
        try:
            serializer = UserSerializer(data=request.data)
            if serializer.is_valid():
                doc_ref = db.collection("users").add(serializer.validated_data)
                return Response(
                    {"id": doc_ref[1].id, **serializer.validated_data},
                    status=status.HTTP_201_CREATED
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied:
            return Response({"error": "No tienes permisos para crear usuarios"}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return handle_firestore_error(e)

class UserDetail(APIView):
    def get(self, request, pk):
        try:
            doc = db.collection("users").document(pk).get()
            if not doc.exists:
                return Response({"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND)
            return Response({**doc.to_dict(), "id": doc.id}, status=status.HTTP_200_OK)
        except Exception as e:
            return handle_firestore_error(e)

    def put(self, request, pk):
        try:
            serializer = UserSerializer(data=request.data)
            if serializer.is_valid():
                db.collection("users").document(pk).set(serializer.validated_data)
                return Response({"id": pk, **serializer.validated_data}, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied:
            return Response({"error": "No tienes permisos para actualizar este usuario"}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return handle_firestore_error(e)
            
    def delete(self, request, pk):
        try:
            db.collection("users").document(pk).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except PermissionDenied:
            return Response({"error": "No tienes permisos para eliminar este usuario"}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return handle_firestore_error(e)
