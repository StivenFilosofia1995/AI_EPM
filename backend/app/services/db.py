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
