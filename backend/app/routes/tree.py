"""
Rutas del motor de árbol de decisiones.

Todas exigen autenticación y verifican propiedad de la sesión a través de
app.dependencies. Ninguna llama al modelo de lenguaje.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_current_user, verify_session_ownership
from app.domain.tree_loader import get_tree
from app.services import tree_engine as engine
from app.services import tree_repository as repo

router = APIRouter(prefix="/api/tree", tags=["árbol"])


@router.post("/session", status_code=201)
async def crear_sesion(user: dict = Depends(get_current_user)):
    """Crea una sesión y devuelve el primer nodo."""
    session_id = str(_uuid.uuid4())
    return await engine.start_session(
        session_id=session_id, user_id=user["id"], user_name=user["nombre"]
    )


@router.get("/sessions")
async def mis_sesiones(user: dict = Depends(get_current_user)):
    """Sesiones del usuario autenticado, para retomar una en curso."""
    sesiones = await repo.list_sessions(user["id"])
    return {
        "sessions": [
            {
                "session_id": s["session_id"],
                "estado": s.get("estado"),
                "current_node_id": s.get("current_node_id"),
                "tree_version": s.get("tree_version"),
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
                "completed_at": s.get("completed_at"),
            }
            for s in sesiones
        ]
    }


@router.get("/session/{session_id}/current")
async def nodo_actual(session_id: str, user: dict = Depends(get_current_user)):
    await verify_session_ownership(session_id, user)
    try:
        return await engine.get_current_node(session_id)
    except engine.EngineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class AnswerBody(BaseModel):
    node_id: str
    value: Any = None
    # propio | sugerencia_ia | sugerencia_editada
    origen: str = "propio"


@router.post("/session/{session_id}/answer")
async def responder(
    session_id: str, body: AnswerBody, user: dict = Depends(get_current_user)
):
    """
    Valida la respuesta, la persiste y devuelve el siguiente nodo.

    Los errores de validación se devuelven con código 422 y estructura
    {errors: [{field_key, code, message}]}, nunca como texto libre.
    """
    session = await verify_session_ownership(session_id, user)

    if session.get("estado") == "completada":
        raise HTTPException(
            status_code=409,
            detail="Esta consolidación ya fue finalizada y no admite cambios.",
        )

    if body.origen not in ("propio", "sugerencia_ia", "sugerencia_editada"):
        raise HTTPException(status_code=422, detail="Origen de respuesta inválido.")

    try:
        return await engine.submit_answer(
            session_id=session_id,
            node_id=body.node_id,
            value=body.value,
            user_id=str(session.get("user_id") or user["id"]),
            origen=body.origen,
        )
    except engine.ValidationFailed as exc:
        raise HTTPException(
            status_code=422,
            detail={"errors": [e.model_dump() for e in exc.errors]},
        ) from exc
    except engine.EngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/{session_id}/back")
async def retroceder(session_id: str, user: dict = Depends(get_current_user)):
    await verify_session_ownership(session_id, user)
    try:
        return await engine.go_back(session_id)
    except engine.EngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/session/{session_id}/summary")
async def resumen(session_id: str, user: dict = Depends(get_current_user)):
    """Las 25 respuestas consolidadas, con los campos no alcanzables marcados."""
    await verify_session_ownership(session_id, user)
    try:
        return await engine.get_summary(session_id)
    except engine.EngineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/session/{session_id}/finalize")
async def finalizar(session_id: str, user: dict = Depends(get_current_user)):
    """
    Cierra la sesión y proyecta las 25 columnas a epm_actividades.

    No dispara el análisis de forma síncrona: la etapa de ideas se pide
    aparte, para que su fallo no invalide una consolidación válida.
    """
    session = await verify_session_ownership(session_id, user)
    try:
        return await engine.finalize(
            session_id, str(session.get("user_id") or user["id"])
        )
    except engine.EngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/definicion")
async def definicion_arbol(_: dict = Depends(get_current_user)):
    """Metadatos del árbol activo. Útil para el panel de administrador."""
    tree = get_tree()
    return {
        "version": tree.version,
        "nombre": tree.nombre,
        "checksum": tree.checksum,
        "total_nodos": len(tree.nodes),
        "root": tree.root,
    }
