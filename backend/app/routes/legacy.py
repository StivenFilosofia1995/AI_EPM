"""
Endpoints del flujo conversacional anterior, marcados como obsoletos.

Se conservan temporalmente para no romper clientes que todavía los usen. No
reciben mantenimiento y se retirarán junto con chat_service.py.

Advertencia sobre su comportamiento: /api/form/* opera sobre la caché en
memoria del proceso, que se pierde al reiniciar y no se comparte entre
réplicas. Ese es precisamente el defecto que el motor de árbol corrige. Para
capturar datos, usa /api/tree/*.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_current_user, limitar_modelo
from app.models.schemas import ChatMessage
from app.services.chat_service import (
    get_session_form_data,
    process_message_stream,
    update_form_field,
)

router = APIRouter(prefix="/api", tags=["obsoletos"])

_AVISO = (
    "Endpoint obsoleto. El flujo de captura usa ahora el motor determinista "
    "en /api/tree/*."
)


@router.post("/chat", deprecated=True, summary="Obsoleto: flujo conversacional")
async def chat(body: ChatMessage, user: dict = Depends(limitar_modelo)):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    return StreamingResponse(
        process_message_stream(
            body.session_id, body.message.strip(), user_name=user["nombre"]
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Deprecated": _AVISO,
        },
    )


class FormFieldBody(BaseModel):
    session_id: str
    field: str
    value: str


@router.post("/form/update", deprecated=True, summary="Obsoleto: formulario en memoria")
async def form_update(body: FormFieldBody, _: dict = Depends(get_current_user)):
    update_form_field(body.session_id, body.field, body.value)
    return {"ok": True, "aviso": _AVISO}


@router.get("/form/{session_id}", deprecated=True, summary="Obsoleto: formulario en memoria")
async def form_get(session_id: str, _: dict = Depends(get_current_user)):
    return {"form_data": get_session_form_data(session_id), "aviso": _AVISO}
