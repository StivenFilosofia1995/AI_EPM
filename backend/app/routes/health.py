"""
Comprobación de salud.

El health check anterior no hacía ninguna llamada: devolvía "healthy" si la
variable ANTHROPIC_API_KEY tenía algún valor. Railway lo usa como
healthcheckPath, así que un despliegue con una clave inválida se reportaba
como sano. Este comprueba lo que de verdad tiene que estar en pie para que la
aplicación funcione.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from app.config import settings
from app.domain.tree_loader import TreeError, get_tree
from app.services.db import DatabaseUnavailable, get_client, rol_de_la_clave
from app.services.schema_check import migraciones_pendientes, verificar_esquema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["salud"])


async def _check_db() -> dict:
    try:
        client = get_client()
        await asyncio.wait_for(
            asyncio.to_thread(
                lambda: client.table("epm_sessions").select("session_id").limit(1).execute()
            ),
            timeout=5.0,
        )
        return {"estado": "ok"}
    except DatabaseUnavailable as exc:
        return {"estado": "sin_configurar", "detalle": str(exc)}
    except TimeoutError:
        return {"estado": "lento", "detalle": "La consulta superó los 5 segundos."}
    except Exception as exc:
        return {"estado": "error", "detalle": f"{type(exc).__name__}: {exc}"}


def _check_tree() -> dict:
    try:
        tree = get_tree()
        return {
            "estado": "ok",
            "version": tree.version,
            "nodos": len(tree.nodes),
            "checksum": tree.checksum[:12],
        }
    except TreeError as exc:
        return {"estado": "error", "detalle": str(exc)}


@router.get("/health")
async def health():
    """
    La captura de datos NO depende del modelo de lenguaje. Por eso el estado
    general solo se degrada si falla la base de datos o el árbol: sin modelo
    se puede consolidar igual, solo no se genera el análisis final.
    """
    db = await _check_db()
    tree = _check_tree()

    rol = rol_de_la_clave()
    clave = {
        "rol_detectado": rol,
        "estado": "ok" if rol in (None, "service_role") else "incorrecta",
    }
    if clave["estado"] == "incorrecta":
        clave["detalle"] = (
            f"SUPABASE_SERVICE_ROLE_KEY tiene rol '{rol}'. Se necesita la clave "
            "service_role (secret), no la anon public."
        )

    esquema: dict = {"estado": "ok"}
    if db["estado"] == "ok":
        try:
            problemas = await verificar_esquema()
            if problemas:
                esquema = {
                    "estado": "desactualizado",
                    "faltantes": problemas,
                    "ejecutar": migraciones_pendientes(problemas),
                }
        except Exception as exc:
            esquema = {"estado": "desconocido", "detalle": str(exc)}
    modelo = {
        "estado": "ok" if settings.ANTHROPIC_API_KEY else "sin_configurar",
        "modelo": settings.ANTHROPIC_MODEL if settings.ANTHROPIC_API_KEY else None,
        "nota": "Solo se usa en la etapa de análisis e ideas.",
    }

    critico_ok = (
        db["estado"] == "ok"
        and tree["estado"] == "ok"
        and esquema["estado"] in ("ok", "desconocido")
        and clave["estado"] == "ok"
    )

    return {
        "status": "healthy" if critico_ok else "degraded",
        "base_datos": db,
        "clave_supabase": clave,
        "esquema": esquema,
        "arbol": tree,
        "modelo": modelo,
    }
