"""
Preparación de la primera cuenta al arrancar.

Existe para que la aplicación sea usable sin configuración previa: en modo
demostración crea una cuenta de administrador y anuncia sus credenciales en
los registros de arranque.

Por qué la contraseña NO está escrita en el código: este repositorio es
público. Una contraseña fija en el código sería legible por cualquiera y le
daría acceso al panel de administración. En su lugar:

  1. Si ADMIN_PASSWORD está en el entorno, se usa esa. Es la vía recomendada
     en Railway: Variables → New Variable, y queda fija entre despliegues.
  2. Si no, se genera una aleatoria y se imprime en los registros de arranque.
     Funciona sin configurar nada, pero cambia en cada despliegue.
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
    logger.warning("\n%s", linea)
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
    logger.warning("%s\n", linea)


async def asegurar_admin() -> None:
    """
    Crea la cuenta de administrador si no existe. No hace nada cuando hay
    Supabase configurado: allí la cuenta se crea con scripts/crear_admin.py.
    """
    if not modo_demostracion():
        return

    correo = (settings.ADMIN_EMAIL or CORREO_POR_DEFECTO).strip().lower()

    try:
        existente = await auth_service.get_user_by_email(correo)
    except Exception as exc:
        logger.error("No se pudo verificar la cuenta de administrador: %s", exc)
        return

    if existente:
        _anunciar(correo, None, "")
        return

    if settings.ADMIN_PASSWORD:
        password = settings.ADMIN_PASSWORD
        origen = "Definida en la variable de entorno ADMIN_PASSWORD."
    else:
        password = _generar_password()
        origen = (
            "Generada al arrancar. Cambiará en el próximo despliegue.\n"
            "  Para fijarla: define ADMIN_PASSWORD en las variables de entorno."
        )

    try:
        usuario = await auth_service.create_user(
            email=correo,
            nombre="Administrador de la demostración",
            password=password,
            rol="admin",
        )
        # No se le exige cambiarla: en demostración no hay a quién entregarla.
        await auth_service.change_password(usuario["id"], password)
    except Exception as exc:
        logger.error("No se pudo crear la cuenta de administrador: %s", exc)
        return

    _anunciar(correo, password, origen)
