"""Correos transaccionales (desde @lemartek.com)."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

from cuentas.models import Usuario


def _enviar(destinatario: str, asunto: str, cuerpo: str) -> None:
    send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])


def enviar_cuenta_creada(usuario: Usuario, creada_por: Usuario | None) -> None:
    """Avisa que la cuenta existe. La contraseña temporal NO viaja por correo:
    la entrega en persona quien creó la cuenta."""
    quien = creada_por.nombre_completo if creada_por else "El administrador"
    donde = f" de {usuario.entidad.nombre}" if usuario.entidad else ""
    _enviar(
        usuario.email,
        f"Su cuenta de MiEvaluador{donde}",
        f"Hola {usuario.nombre_completo},\n\n"
        f"{quien} le creó una cuenta en MiEvaluador{donde} como {usuario.get_rol_display().lower()}.\n\n"
        f"Ingrese en {settings.FRONTEND_URL} con este correo y la contraseña temporal que {quien} le entregó.\n"
        f"Por seguridad, el sistema le pedirá cambiarla la primera vez que entre.\n\n"
        f"Si no esperaba este correo, avísele a quien administra su entidad.\n\n— MiEvaluador by LeMarTek",
    )


def enviar_clave_reiniciada(usuario: Usuario, reiniciada_por: Usuario | None) -> None:
    """Avisa que un administrador le puso una contraseña temporal nueva."""
    quien = reiniciada_por.nombre_completo if reiniciada_por else "Un administrador"
    _enviar(
        usuario.email,
        "Su contraseña de MiEvaluador fue reiniciada",
        f"Hola {usuario.nombre_completo},\n\n"
        f"{quien} reinició su contraseña. Entre con la contraseña temporal que le entregó y elija una nueva.\n\n"
        f"{settings.FRONTEND_URL}\n\n"
        f"Si no pidió este cambio, avísele de inmediato a quien administra su entidad.\n\n— MiEvaluador by LeMarTek",
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


def enviar_asignacion(evaluacion, responsable: Usuario, asignada_por: Usuario) -> None:
    proceso = evaluacion.proceso
    enlace = f"{settings.FRONTEND_URL}/evaluaciones/{evaluacion.id}"
    _enviar(
        responsable.email,
        f"Nueva evaluación asignada: {proceso.codigo}",
        f"Hola {responsable.nombre_completo},\n\n"
        f"{asignada_por.nombre_completo} le asignó la evaluación {evaluacion.get_tipo_display().lower()} del proceso "
        f"{proceso.codigo} (cierre: {proceso.fecha_cierre:%d/%m/%Y}).\n\n"
        f"Ábrala aquí:\n{enlace}\n\n— MiEvaluador by LeMarTek",
    )


def enviar_evaluacion_terminada(evaluacion, destinatario: Usuario, avance) -> None:
    proceso = evaluacion.proceso
    enlace = f"{settings.FRONTEND_URL}/evaluaciones/{evaluacion.id}"
    partes = [f"{avance.evaluados} de {avance.proponentes} proponentes evaluados"]
    if avance.pendientes:
        partes.append(f"{avance.pendientes} requisitos por revisar")
    if avance.con_error:
        partes.append(f"{avance.con_error} proponentes con error (puede reintentarlos)")
    _enviar(
        destinatario.email,
        f"Evaluación terminada: {proceso.codigo}",
        f"Hola {destinatario.nombre_completo},\n\n"
        f"Terminó la evaluación {evaluacion.get_tipo_display().lower()} del proceso {proceso.codigo}: "
        f"{', '.join(partes)}.\n\nRevísela aquí:\n{enlace}\n\n— MiEvaluador by LeMarTek",
    )


def enviar_acceso_soporte(acceso, soporte: Usuario) -> None:
    _enviar(
        soporte.email,
        f"Acceso de soporte a {acceso.entidad.nombre}",
        f"Hola {soporte.nombre_completo},\n\n"
        f"{acceso.otorgado_por.nombre_completo if acceso.otorgado_por else 'La entidad'} le dio acceso de solo lectura a "
        f"{acceso.entidad.nombre} hasta el {acceso.expira_en:%d/%m/%Y %H:%M} (UTC).\n"
        f"Motivo: {acceso.motivo}\n\nIngrese a {settings.FRONTEND_URL} y elija la entidad.\n\n— MiEvaluador by LeMarTek",
    )
