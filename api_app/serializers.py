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


# ============================================
# NUEVOS SERIALIZERS PARA HORARIOS
# ============================================

class ScheduleClassSerializer(serializers.Serializer):
    """Serializer para una clase individual en el horario"""
    classroom = serializers.CharField(max_length=100)
    day = serializers.CharField(max_length=20)
    iniTime = serializers.CharField(max_length=10)  # Formato "HH:MM"
    endTime = serializers.CharField(max_length=10)  # Formato "HH:MM"

    def validate_day(self, value):
        """Validar que el día sea válido"""
        dias_validos = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        if value not in dias_validos:
            raise serializers.ValidationError(
                f"Día inválido. Debe ser uno de: {', '.join(dias_validos)}"
            )
        return value

    def validate_iniTime(self, value):
        """Validar formato de hora de inicio"""
        try:
            datetime.strptime(value, "%H:%M")
            return value
        except ValueError:
            raise serializers.ValidationError("Formato de hora inválido. Use HH:MM")

    def validate_endTime(self, value):
        """Validar formato de hora de fin"""
        try:
            datetime.strptime(value, "%H:%M")
            return value
        except ValueError:
            raise serializers.ValidationError("Formato de hora inválido. Use HH:MM")

    def validate(self, data):
        """Validar que la hora de fin sea después de la hora de inicio"""
        if 'iniTime' in data and 'endTime' in data:
            inicio = datetime.strptime(data['iniTime'], "%H:%M")
            fin = datetime.strptime(data['endTime'], "%H:%M")
            if fin <= inicio:
                raise serializers.ValidationError(
                    "La hora de fin debe ser posterior a la hora de inicio"
                )
        return data


class CourseSerializer(serializers.Serializer):
    """Serializer para un curso completo"""
    id = serializers.CharField(read_only=True)
    nameCourse = serializers.CharField(max_length=200)
    group = serializers.CharField(max_length=100)
    profesorID = serializers.CharField(max_length=100)
    estudianteID = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list
    )
    schedule = serializers.ListField(
        child=ScheduleClassSerializer(),
        required=False,
        default=list
    )

    def validate_estudianteID(self, value):
        """Asegurar que estudianteID sea una lista"""
        if value is None:
            return []
        return value

    def validate_schedule(self, value):
        """Asegurar que schedule sea una lista"""
        if value is None:
            return []
        return value


class PersonSerializer(serializers.Serializer):
    """Serializer para información de persona (estudiante/profesor)"""
    id = serializers.CharField(read_only=True)
    namePerson = serializers.CharField(max_length=200)
    type = serializers.CharField(max_length=50)
    courses = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list
    )

    def validate_type(self, value):
        """Validar tipo de persona"""
        tipos_validos = ["Estudiante", "Profesor"]
        if value not in tipos_validos:
            raise serializers.ValidationError(
                f"Tipo inválido. Debe ser uno de: {', '.join(tipos_validos)}"
            )
        return value

    def validate_courses(self, value):
        """Asegurar que courses sea una lista"""
        if value is None:
            return []
        return value


class HorarioRequestSerializer(serializers.Serializer):
    """Serializer para peticiones de horario"""
    profesorID = serializers.CharField(max_length=100, required=False)
    estudianteID = serializers.CharField(max_length=100, required=False)

    def validate(self, data):
        """Validar que se proporcione al menos un ID"""
        if not data.get('profesorID') and not data.get('estudianteID'):
            raise serializers.ValidationError(
                "Debe proporcionar profesorID o estudianteID"
            )
        return data


class UpdateScheduleSerializer(serializers.Serializer):
    """Serializer para actualizar el horario de un curso"""
    schedule = serializers.ListField(
        child=ScheduleClassSerializer(),
        required=True
    )

    def validate_schedule(self, value):
        """Validar que schedule no esté vacío si se proporciona"""
        if value is None:
            return []
        return value