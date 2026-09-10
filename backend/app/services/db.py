"""
Cliente de base de datos.

Si SUPABASE_URL está configurada, usa Supabase. Si no, entra en **modo
demostración** con almacenamiento en memoria, de forma que la aplicación
funciona completa sin ninguna configuración: árbol, autenticación,
exportaciones y panel de administración.

A diferencia de supabase_service (legado), los módulos que usan este cliente
NO tragan las excepciones. Un fallo de base de datos debe ser visible: el
diseño anterior registraba un warning y devolvía vacío, con lo cual una caída
de Supabase se traducía en pérdida silenciosa de datos del facilitador.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client: Any = None


class DatabaseUnavailable(RuntimeError):
    """No hay configuración de base de datos, o la conexión falló."""


# Valores de .env.example. Si siguen puestos, la variable no está configurada
# de verdad: conviene entrar en modo demostración en vez de intentar conectarse
# a una URL inexistente y fallar con un error de red confuso.
_MARCADORES = ("tu-proyecto", "coloca-aqui", "genera-una", "el-id-de", "cambiame")


def _configurada(valor: str | None) -> bool:
    if not valor or not valor.strip():
        return False
    return not any(m in valor for m in _MARCADORES)


def modo_demostracion() -> bool:
    """True cuando no hay Supabase configurado y se usa memoria."""
    return not (
        _configurada(settings.SUPABASE_URL)
        and _configurada(settings.SUPABASE_SERVICE_ROLE_KEY)
    )


def get_client() -> Any:
    global _client
    if _client is not None:
        return _client

    if modo_demostracion():
        from app.services.memory_db import MemoryDB

        _client = MemoryDB()
        return _client

    from supabase import create_client

    _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client


def reset_client() -> None:
    """Solo para pruebas."""
    global _client
    _client = None


# ─── Verificación de la clave ───────────────────────────────────────────────
# Las claves de Supabase son JWT cuyo payload declara el rol. Confundir la
# clave `anon` con la `service_role` produce un "permission denied" en mitad
# de una operación, y el hint de Postgres sugiere justo lo que NO hay que
# hacer: conceder permisos a `anon` sobre tablas con hashes de contraseña.


def rol_de_la_clave() -> str | None:
    """
    Rol declarado por SUPABASE_SERVICE_ROLE_KEY, sin verificar la firma.

    Devuelve 'service_role', 'anon', otro rol, o None si no se puede leer
    (por ejemplo con los formatos sb_secret_ / sb_publishable_, que no son JWT).
    """
    clave = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not clave:
        return None

    if clave.startswith("sb_secret_"):
        return "service_role"
    if clave.startswith("sb_publishable_"):
        return "anon"

    try:
        import jwt

        payload = jwt.decode(clave, options={"verify_signature": False})
        return payload.get("role")
    except Exception:
        return None


def avisar_si_la_clave_es_publica() -> str | None:
    """
    Deja constancia si la clave configurada no es la de servicio.
    Devuelve el rol detectado.
    """
    rol = rol_de_la_clave()
    if rol in (None, "service_role"):
        return rol

    linea = "=" * 68
    logger.error("%s", linea)
    logger.error("  LA CLAVE DE SUPABASE NO ES LA CORRECTA")
    logger.error("%s", linea)
    logger.error("  SUPABASE_SERVICE_ROLE_KEY contiene una clave de rol '%s'.", rol)
    logger.error("  Se necesita la clave `service_role`, no la `anon public`.")
    logger.error("")
    logger.error("  Supabase → Project Settings → API → service_role (secret)")
    logger.error("")
    logger.error("  NO concedas permisos a `anon` para sortear el error: esa")
    logger.error("  clave viaja en el navegador y epm_users guarda los hashes")
    logger.error("  de contraseña.")
    logger.error("%s", linea)
    return rol
