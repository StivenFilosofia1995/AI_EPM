"""
Preparación de la cuenta de administración al arrancar.

Regla de oro: **las variables de entorno mandan.** Si ADMIN_EMAIL y
ADMIN_PASSWORD están definidas, esa cuenta existe con esa contraseña, punto.
Quien controla el panel de despliegue es el dueño del sistema.

La versión anterior solo creaba la cuenta cuando no existía y nunca
sincronizaba la contraseña. El resultado era una trampa: cambiar
ADMIN_PASSWORD en Railway no surtía ningún efecto, para siempre, y no había
forma de recuperar el acceso sin entrar a la base de datos a mano.

Por qué la contraseña NO se escribe en el código: este repositorio es
público. En modo demostración, si no hay ADMIN_PASSWORD se genera una y se
anuncia en los registros de arranque.
"""

from __future__ import annotations

import logging
import secrets

from app.config import settings
from app.services import auth_service
from app.services.db import modo_demostracion

logger = logging.getLogger(__name__)

# No usar dominios reservados (.local, .test, .invalid): email-validator
# los rechaza y el login falla con un error confuso. example.com es el
# dominio de documentación de la RFC 2606 y sí valida.
CORREO_POR_DEFECTO = "admin@example.com"


def _generar_password() -> str:
    """Legible al copiarla de los registros, y con suficiente entropía."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    bloques = ["".join(secrets.choice(alfabeto) for _ in range(5)) for _ in range(3)]
    return "-".join(bloques) + str(secrets.randbelow(10))


def _anunciar(correo: str, password: str | None, origen: str) -> None:
    linea = "=" * 68
    logger.warning("%s", linea)
    logger.warning("  MODO DEMOSTRACIÓN — sin Supabase, los datos viven en memoria")
    logger.warning("%s", linea)
    logger.warning("  Cuenta de administrador:")
    logger.warning("      Correo     : %s", correo)
    if password:
        logger.warning("      Contraseña : %s", password)
        logger.warning("")
        logger.warning("  %s", origen)
    else:
        logger.warning("      Contraseña : la que ya definiste (no se muestra)")
    logger.warning("%s", linea)


def _avisar_si_es_debil(password: str) -> None:
    """
    Advierte, pero no bloquea. Bloquear aquí dejaba la aplicación sin ninguna
    cuenta con la que entrar, y el síntoma era un fallo de acceso que no
    apuntaba a la causa.
    """
    problemas = auth_service.validar_fortaleza(password)
    if not problemas:
        return
    logger.warning(
        "ADMIN_PASSWORD es débil (%s). La cuenta se crea igual, pero conviene "
        "cambiarla: da acceso a todas las consolidaciones.",
        "; ".join(problemas),
    )


async def asegurar_admin() -> None:
    """
    Garantiza que la cuenta de administración exista y responda a la
    contraseña de las variables de entorno.

    Actúa en dos situaciones:

      · Modo demostración: siempre, para que la aplicación sea usable sin
        configurar nada.
      · Con Supabase: cuando ADMIN_EMAIL y ADMIN_PASSWORD están definidas.
        Es la vía para administrar en Railway, donde no hay una terminal a
        mano para ejecutar scripts/crear_admin.py.
    """
    demo = modo_demostracion()
    con_variables = bool(settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD)

    if not demo and not con_variables:
        return

    correo = (settings.ADMIN_EMAIL or CORREO_POR_DEFECTO).strip().lower()

    # ── Qué contraseña debe quedar ──
    if settings.ADMIN_PASSWORD:
        password = settings.ADMIN_PASSWORD
        origen = "Definida en la variable de entorno ADMIN_PASSWORD."
        _avisar_si_es_debil(password)
    elif demo:
        password = _generar_password()
        origen = (
            "Generada al arrancar. Cambiará en el próximo despliegue.\n"
            "  Para fijarla: define ADMIN_PASSWORD en las variables de entorno."
        )
    else:
        logger.warning(
            "ADMIN_EMAIL está definido pero ADMIN_PASSWORD no. No se puede "
            "preparar la cuenta: define ambas o usa scripts/crear_admin.py."
        )
        return

    try:
        existente = await auth_service.get_user_by_email(correo)
    except Exception as exc:
        logger.error("No se pudo consultar la cuenta de administración: %s", exc)
        return

    # ── La cuenta ya existe: se sincroniza con las variables ──
    if existente:
        try:
            coincide = auth_service.verify_password(
                password, existente.get("password_hash", "")
            )
            necesita_arreglo = (
                not coincide
                or not existente.get("activo", True)
                or existente.get("rol") != "admin"
            )

            if necesita_arreglo:
                await auth_service.fijar_password(existente["id"], password)
                if existente.get("rol") != "admin":
                    await auth_service.set_rol(existente["id"], "admin")
                logger.warning(
                    "Cuenta de administración %s sincronizada con las variables "
                    "de entorno: contraseña, estado activo y rol admin.",
                    correo,
                )
            else:
                logger.info("Cuenta de administración %s lista.", correo)
        except Exception as exc:
            logger.error("No se pudo sincronizar la cuenta %s: %s", correo, exc)
            return

        if demo:
            _anunciar(correo, password if settings.ADMIN_PASSWORD else password, origen)
        return

    # ── No existe: se crea ──
    try:
        usuario = await auth_service.create_user(
            email=correo,
            nombre="Administración",
            password=password,
            rol="admin",
            exigir_fortaleza=False,
            debe_cambiar_password=False,
        )
        await auth_service.fijar_password(usuario["id"], password)
    except Exception as exc:
        logger.error("No se pudo crear la cuenta de administración: %s", exc)
        return

    if demo:
        _anunciar(correo, password, origen)
    else:
        logger.warning("Cuenta de administración creada: %s", correo)
