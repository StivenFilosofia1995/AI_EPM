"""
Cliente único de Supabase.

A diferencia de supabase_service (legado), los módulos que usan este cliente
NO tragan las excepciones. Un fallo de base de datos debe ser visible: el
diseño anterior registraba un warning y devolvía vacío, con lo cual una caída
de Supabase se traducía en pérdida silenciosa de datos del facilitador.
"""

from __future__ import annotations

from supabase import Client, create_client

from app.config import settings

_client: Client | None = None


class DatabaseUnavailable(RuntimeError):
    """No hay configuración de base de datos, o la conexión falló."""


def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise DatabaseUnavailable(
                "SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY no están configurados."
            )
        _client = create_client(
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
        )
    return _client


def reset_client() -> None:
    """Solo para pruebas."""
    global _client
    _client = None
