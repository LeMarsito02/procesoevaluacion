"""Correos transaccionales (desde @lemartek.com)."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

from cuentas.models import Invitacion, Usuario


def _enviar(destinatario: str, asunto: str, cuerpo: str) -> None:
    send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])


def enviar_invitacion(invitacion: Invitacion, token: str) -> None:
    enlace = f"{settings.FRONTEND_URL}/invitacion/{token}"
    _enviar(
        invitacion.email,
        f"Invitación a MiEvaluador · {invitacion.entidad.nombre}",
        f"Hola,\n\n"
        f"Te invitaron a MiEvaluador como {invitacion.get_rol_display().lower()} de {invitacion.entidad.nombre}.\n\n"
        f"Crea tu contraseña aquí (el enlace vence el {invitacion.expira_en:%d/%m/%Y}):\n{enlace}\n\n"
        f"Si no esperabas este correo, ignóralo.\n\n— MiEvaluador by LeMarTek",
    )


def enviar_recuperacion(usuario: Usuario, uid: str, token: str) -> None:
    enlace = f"{settings.FRONTEND_URL}/restablecer/{uid}/{token}"
    horas = settings.PASSWORD_RESET_TIMEOUT // 3600
    _enviar(
        usuario.email,
        "Restablecer tu contraseña de MiEvaluador",
        f"Hola {usuario.nombre_completo},\n\n"
        f"Recibimos una solicitud para restablecer tu contraseña. Usa este enlace (vale {horas} horas):\n{enlace}\n\n"
        f"Si no la solicitaste, ignora este correo: tu contraseña no cambia.\n\n— MiEvaluador by LeMarTek",
    )
