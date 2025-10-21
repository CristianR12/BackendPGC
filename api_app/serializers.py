from rest_framework import serializers
from datetime import datetime
import locale

# Configurar idioma español
try:
    locale.setlocale(locale.LC_TIME, "es_ES.utf8")  # Linux/Mac
except:
    locale.setlocale(locale.LC_TIME, "Spanish_Spain.1252")  # Windows

class AsistenciaSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    asignatura = serializers.CharField(max_length=200)
    estadoAsistencia = serializers.CharField(max_length=200)
    estudiante = serializers.CharField(max_length=200)
    fechaYhora = serializers.CharField()

    def create(self, validated_data):
        fecha_str = validated_data.get("fechaYhora")

        # 🔹 Guardar como string directo en Firebase
        # (Opción 1: no parseamos, se manda tal cual)
        return {
            "estudiante": validated_data.get("estudiante"),
            "fechaYhora": fecha_str
        }

class UserSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    nombre = serializers.CharField(max_length=200)
    correo = serializers.EmailField()
    rol = serializers.CharField(max_length=100, required=False)
