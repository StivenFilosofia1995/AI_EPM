"""
Panel de administrador: trazabilidad por usuario, por sesión y por campo.

Sustituye al mecanismo anterior de PIN en el parámetro de URL, que exponía el
secreto en los registros del servidor, en el historial del navegador y en las
cabeceras Referer. Ahora exige rol admin o coordinador.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import require_supervision
from app.domain.fields import FIELD_BY_KEY, FIELD_KEYS
from app.services import tree_engine as engine
from app.services.db import get_client

router = APIRouter(prefix="/api/admin", tags=["administración"])


async def _run(fn):
    return await asyncio.to_thread(fn)


@router.get("/sesiones")
async def listar_sesiones(
    _: dict = Depends(require_supervision),
    user_id: Optional[str] = Query(None),
    programa: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    desde: Optional[str] = Query(None, description="Fecha ISO AAAA-MM-DD"),
    hasta: Optional[str] = Query(None, description="Fecha ISO AAAA-MM-DD"),
    avance_minimo: Optional[float] = Query(None, ge=0, le=100),
    limit: int = Query(200, ge=1, le=1000),
):
    """Sesiones filtrables, con el consolidado en vivo de v_actividades_completas."""
    client = get_client()

    def _query():
        q = client.table("v_actividades_completas").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        if programa:
            q = q.eq("programa", programa)
        if estado:
            q = q.eq("estado", estado)
        if desde:
            q = q.gte("created_at", desde)
        if hasta:
            q = q.lte("created_at", hasta)
        if avance_minimo is not None:
            q = q.gte("porcentaje_avance", avance_minimo)
        return q.order("created_at", desc=True).limit(limit).execute()

    result = await _run(_query)
    filas = result.data or []
    return {"total": len(filas), "sesiones": filas}


@router.get("/sesion/{session_id}")
async def detalle_sesion(session_id: str, _: dict = Depends(require_supervision)):
    """
    Detalle completo: las 25 respuestas, quién respondió cada una, cuándo,
    cuántos intentos, el origen y el historial de correcciones.
    """
    client = get_client()

    respuestas = await _run(
        lambda: client.table("epm_respuestas")
        .select("*")
        .eq("session_id", session_id)
        .order("answered_at", desc=False)
        .execute()
    )
    historial = await _run(
        lambda: client.table("epm_respuestas_historial")
        .select("*")
        .eq("session_id", session_id)
        .order("archivado_at", desc=False)
        .execute()
    )
    sesion = await _run(
        lambda: client.table("v_actividades_completas")
        .select("*")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    analisis = await _run(
        lambda: client.table("epm_analisis_ia")
        .select("*")
        .eq("session_id", session_id)
        .order("generado_at", desc=True)
        .execute()
    )

    filas_sesion = sesion.data or []
    if not filas_sesion:
        raise HTTPException(status_code=404, detail="La sesión no existe.")

    correcciones: dict[str, list] = {}
    for h in historial.data or []:
        correcciones.setdefault(h["node_id"], []).append(h)

    detalle = []
    for r in respuestas.data or []:
        fk = r.get("field_key")
        detalle.append({
            **r,
            "header": FIELD_BY_KEY[fk].header if fk in FIELD_BY_KEY else None,
            "correcciones": correcciones.get(r["node_id"], []),
        })

    return {
        "session_id": session_id,
        "sesion": filas_sesion[0],
        "respuestas": detalle,
        "analisis": analisis.data or [],
        "orden_campos": FIELD_KEYS,
    }


@router.get("/avance-usuarios")
async def avance_usuarios(_: dict = Depends(require_supervision)):
    client = get_client()
    result = await _run(
        lambda: client.table("v_avance_por_usuario").select("*").execute()
    )
    return {"usuarios": result.data or []}


@router.get("/campos-problematicos")
async def campos_problematicos(_: dict = Depends(require_supervision)):
    """Qué preguntas concentran reintentos y validaciones fallidas."""
    client = get_client()
    result = await _run(
        lambda: client.table("v_campos_problematicos").select("*").execute()
    )
    return {"campos": result.data or []}


@router.get("/uso-sugerencias")
async def uso_sugerencias(_: dict = Depends(require_supervision)):
    """Cuánto del contenido consolidado nació de una sugerencia asistida."""
    client = get_client()
    result = await _run(
        lambda: client.table("v_uso_sugerencias").select("*").execute()
    )
    return {"campos": result.data or []}


@router.get("/resumen")
async def resumen_general(_: dict = Depends(require_supervision)):
    """Cifras de cabecera para el tablero."""
    client = get_client()

    sesiones = await _run(
        lambda: client.table("epm_sessions").select("estado").execute()
    )
    filas = sesiones.data or []
    por_estado: dict[str, int] = {}
    for s in filas:
        e = s.get("estado") or "desconocido"
        por_estado[e] = por_estado.get(e, 0) + 1

    usuarios = await _run(
        lambda: client.table("epm_users").select("id,activo").execute()
    )
    us = usuarios.data or []

    return {
        "total_sesiones": len(filas),
        "por_estado": por_estado,
        "total_usuarios": len(us),
        "usuarios_activos": sum(1 for u in us if u.get("activo")),
        "tree_version": engine.get_tree().version,
    }
