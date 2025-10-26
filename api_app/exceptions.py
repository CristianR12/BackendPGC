from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

def custom_exception_handler(exc, context):
    """
    Intercepta errores de permisos y autenticación para devolver mensajes personalizados.
    """
    # Primero, deja que DRF maneje la excepción
    response = exception_handler(exc, context)

    # Si ya hay una respuesta generada por DRF
    if response is not None:
        # Si la excepción tiene un atributo 'detail' que es un string (mensaje genérico)
        if isinstance(response.data.get("detail"), str):
            # Verificamos si en la vista o permiso hay un mensaje personalizado
            view = context.get("view")
            if hasattr(view, "permission_classes"):
                # Busca si alguno de los permisos tiene .message
                for permission_class in view.permission_classes:
                    perm_instance = permission_class()
                    if hasattr(perm_instance, "message"):
                        custom_msg = getattr(perm_instance, "message", None)
                        if custom_msg:
                            response.data["detail"] = custom_msg
                            break

    else:
        # Si DRF no manejó la excepción, la capturamos manualmente
        response = Response(
            {"detail": str(exc)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
