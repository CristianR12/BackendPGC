from rest_framework import serializers
from datetime import datetime

class AsistenciaSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    asignatura = serializers.CharField(max_length=200, required=False, allow_blank=True)
    estadoAsistencia = serializers.CharField(max_length=200)
    estudiante = serializers.CharField(max_length=200)
    fechaYhora = serializers.CharField(required=False)

    def validate_estadoAsistencia(self, value):
        """Validar que el estado sea uno de los permitidos"""
        estados_validos = ["Presente", "Ausente", "Tiene Excusa"]
        if value not in estados_validos:
            raise serializers.ValidationError(
                f"Estado inválido. Debe ser uno de: {', '.join(estados_validos)}"
            )
        return value

    def validate_fechaYhora(self, value):
        """Validar formato de fecha"""
        if not value:
            return datetime.now().isoformat()
        
        try:
            # Intentar parsear la fecha para validarla
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return value
        except ValueError:
            raise serializers.ValidationError("Formato de fecha inválido. Use ISO 8601")

    def create(self, validated_data):
        """Preparar datos para crear en Firebase"""
        if 'fechaYhora' not in validated_data or not validated_data['fechaYhora']:
            validated_data['fechaYhora'] = datetime.now().isoformat()
        
        return validated_data

    def update(self, instance, validated_data):
        """Actualizar instancia (para Firebase se sobrescribe en la vista)"""
        return validated_data


class UserSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    nombre = serializers.CharField(max_length=200)
    correo = serializers.EmailField()
    rol = serializers.CharField(max_length=100, required=False)