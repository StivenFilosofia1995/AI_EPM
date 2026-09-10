"""
Persistencia del motor de árbol.

Todo el estado de avance vive en Supabase, no en memoria del proceso: el
sistema sobrevive un reinicio y funciona con varias réplicas.

Los errores se propagan. Si una respuesta no se pudo guardar, el facilitador
tiene que enterarse en ese momento, no al final.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from app.services.db import get_client

RESPUESTAS = "epm_respuestas"
SESSIONS = "epm_sessions"
ACTIVIDADES = "epm_actividades"


async def _run(fn):
    return await asyncio.to_thread(fn)


# ─── Sesiones ───────────────────────────────────────────────────────────────


async def create_session(
    session_id: str,
    user_id: str,
    user_name: str,
    tree_version: str,
    current_node_id: str,
) -> dict:
    client = get_client()
    record = {
        "session_id": session_id,
        "user_id": user_id,
        "user_name": user_name,
        "tree_version": tree_version,
        "current_node_id": current_node_id,
        "estado": "en_progreso",
    }
    result = await _run(
        lambda: client.table(SESSIONS).upsert(record, on_conflict="session_id").execute()
    )
    rows = result.data or []
    return rows[0] if rows else record


async def get_session(session_id: str) -> Optional[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table(SESSIONS)
        .select("*")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def update_session(session_id: str, **fields: Any) -> None:
    if not fields:
        return
    client = get_client()
    await _run(
        lambda: client.table(SESSIONS)
        .update(fields)
        .eq("session_id", session_id)
        .execute()
    )


async def list_sessions(user_id: str, limit: int = 100) -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table(SESSIONS)
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


# ─── Respuestas ─────────────────────────────────────────────────────────────


async def get_respuestas(session_id: str) -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table(RESPUESTAS)
        .select("*")
        .eq("session_id", session_id)
        .order("answered_at", desc=False)
        .execute()
    )
    return result.data or []


async def upsert_respuesta(
    session_id: str,
    user_id: str,
    tree_version: str,
    node_id: str,
    field_key: Optional[str],
    valor: Optional[str],
    valor_json: Any = None,
    es_valida: bool = True,
    origen: str = "propio",
    intentos: int = 1,
) -> dict:
    """
    Idempotente por (session_id, node_id): reenviar la misma respuesta
    actualiza la fila, nunca duplica ni avanza dos veces.
    """
    client = get_client()
    record: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "tree_version": tree_version,
        "node_id": node_id,
        "field_key": field_key,
        "valor": valor,
        "valor_json": valor_json,
        "es_valida": es_valida,
        "stale": False,
        "intentos": intentos,
        "origen": origen,
    }
    result = await _run(
        lambda: client.table(RESPUESTAS)
        .upsert(record, on_conflict="session_id,node_id")
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else record


async def bump_intentos(session_id: str, node_id: str) -> None:
    """Registra un intento fallido de validación, para v_campos_problematicos."""
    client = get_client()
    current = await _run(
        lambda: client.table(RESPUESTAS)
        .select("intentos")
        .eq("session_id", session_id)
        .eq("node_id", node_id)
        .limit(1)
        .execute()
    )
    rows = current.data or []
    if rows:
        n = int(rows[0].get("intentos") or 1) + 1
        await _run(
            lambda: client.table(RESPUESTAS)
            .update({"intentos": n, "es_valida": False})
            .eq("session_id", session_id)
            .eq("node_id", node_id)
            .execute()
        )


async def set_stale(session_id: str, node_ids: list[str], stale: bool) -> None:
    """
    Marca o desmarca respuestas como fuera de la ruta actual.
    No se borran nunca: se conservan para auditoría.
    """
    if not node_ids:
        return
    client = get_client()
    await _run(
        lambda: client.table(RESPUESTAS)
        .update({"stale": stale})
        .eq("session_id", session_id)
        .in_("node_id", node_ids)
        .execute()
    )


async def delete_respuestas(session_id: str, node_ids: list[str]) -> None:
    """
    Borra respuestas concretas. Solo se usa en la corrección explícita
    (aristas revisit), donde el facilitador va a volver a responder ese nodo.
    El trigger de historial ya conservó las versiones anteriores.
    """
    if not node_ids:
        return
    client = get_client()
    await _run(
        lambda: client.table(RESPUESTAS)
        .delete()
        .eq("session_id", session_id)
        .in_("node_id", node_ids)
        .execute()
    )


# ─── Consultas de apoyo ─────────────────────────────────────────────────────


async def id_actividad_existe(id_actividad: str, excluir_session: str) -> bool:
    """Unicidad de id_actividad entre sesiones distintas."""
    client = get_client()
    result = await _run(
        lambda: client.table(RESPUESTAS)
        .select("session_id")
        .eq("field_key", "id_actividad")
        .eq("valor", id_actividad)
        .eq("stale", False)
        .execute()
    )
    return any(r.get("session_id") != excluir_session for r in (result.data or []))


async def valores_distintos(field_key: str, limit: int = 200) -> list[str]:
    """
    Valores ya registrados para un campo, para alimentar el autocompletado
    determinista (lugar, responsable). Sin modelo de lenguaje de por medio.
    """
    client = get_client()
    result = await _run(
        lambda: client.table(RESPUESTAS)
        .select("valor")
        .eq("field_key", field_key)
        .eq("stale", False)
        .eq("es_valida", True)
        .limit(limit * 5)
        .execute()
    )
    vistos: list[str] = []
    for row in result.data or []:
        v = (row.get("valor") or "").strip()
        if v and v not in vistos:
            vistos.append(v)
        if len(vistos) >= limit:
            break
    return sorted(vistos, key=str.casefold)


# ─── Proyección a epm_actividades ───────────────────────────────────────────


async def project_actividad(session_id: str, user_id: str, campos: dict[str, Any]) -> dict:
    """
    Escribe la proyección consolidada de las 25 columnas.
    Idempotente por session_id.
    """
    client = get_client()
    record = {"session_id": session_id, "user_id": user_id, **campos}
    result = await _run(
        lambda: client.table(ACTIVIDADES)
        .upsert(record, on_conflict="session_id")
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else record


async def get_actividad(session_id: str) -> Optional[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table("v_actividades_export")
        .select("*")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None
