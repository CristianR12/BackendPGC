from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from firebase_admin import firestore
from .serializers import AsistenciaSerializer, UserSerializer

db = firestore.client()

# ----- LISTAR TODAS -----
class AsistenciaList(APIView):
    def get(self, request):
        docs = db.collection("asistenciaReconocimiento").stream()
        data = [{**doc.to_dict(), "id": doc.id} for doc in docs]
        return Response(data)


# ----- CREAR -----
class AsistenciaCreate(APIView):
    def post(self, request):
        serializer = AsistenciaSerializer(data=request.data)
        if serializer.is_valid():
            doc_ref = db.collection("asistenciaReconocimiento").add(serializer.validated_data)
            return Response(
                {"id": doc_ref[1].id, **serializer.validated_data}, 
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ----- OBTENER DETALLE -----
class AsistenciaRetrieve(APIView):
    def get(self, request, pk):
        doc = db.collection("asistenciaReconocimiento").document(pk).get()
        if not doc.exists:
            return Response({"error": "Asistencia no encontrada"}, status=status.HTTP_404_NOT_FOUND)
        return Response({**doc.to_dict(), "id": doc.id})


# ----- ACTUALIZAR -----
class AsistenciaUpdate(APIView):
    def put(self, request, pk):
        serializer = AsistenciaSerializer(data=request.data)
        if serializer.is_valid():
            db.collection("asistenciaReconocimiento").document(pk).set(serializer.validated_data)
            return Response({"id": pk, **serializer.validated_data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ----- ELIMINAR -----
class AsistenciaDelete(APIView):
    def delete(self, request, pk):
        db.collection("asistenciaReconocimiento").document(pk).delete()
        return Response(
            {
                'success': True,
                'detail': 'Asistencia eliminada con exito.'
            },
            status=status.HTTP_204_NO_CONTENT
        )
    
    
# ------------------------------
# USERS
# ------------------------------
class UserListCreate(APIView):
    def get(self, request):
        docs = db.collection("users").stream()
        data = [{**doc.to_dict(), "id": doc.id} for doc in docs]
        return Response(data)

    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            doc_ref = db.collection("users").add(serializer.validated_data)
            return Response({"id": doc_ref[1].id, **serializer.validated_data}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserDetail(APIView):
    def get(self, request, pk):
        doc = db.collection("users").document(pk).get()
        if not doc.exists:
            return Response({"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND)
        return Response({**doc.to_dict(), "id": doc.id})

    def put(self, request, pk):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            db.collection("users").document(pk).set(serializer.validated_data)
            return Response({"id": pk, **serializer.validated_data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        db.collection("users").document(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
