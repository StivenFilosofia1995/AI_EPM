"""
Exportaciones: Excel, Google Sheets y correo.

Conservan el contrato de sus endpoints, pero ahora leen de epm_respuestas /
v_actividades_export, nunca de la caché en memoria del proceso. Antes,
descargar el Excel sin haber guardado primero en Sheets producía un archivo
con las 25 etiquetas y todos los valores vacíos.

Todas exigen autenticación y verifican propiedad de la sesión.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr

from app.dependencies import get_current_user, limitar_correo, verify_session_ownership
from app.domain.fields import FIELD_KEYS
from app.services import tree_engine as engine
from app.services import tree_repository as repo
from app.services.email_service import send_consolidation_email
from app.services.excel_service import generate_excel
from app.services.google_sheets_service import (
    append_actividad,
    read_sheet_structure,
    sheet_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["exportaciones"])


async def _campos_de_sesion(session_id: str) -> dict[str, str]:
    """
    Los 25 campos como texto, listos para exportar.

    Prefiere la proyección consolidada (v_actividades_export) si la sesión ya
    se finalizó; si no, los compone en vivo desde epm_respuestas para que se
    pueda exportar un avance parcial.
    """
    proyectada = await repo.get_actividad(session_id)
    if proyectada:
        return {k: str(proyectada.get(k) or "") for k in FIELD_KEYS}

    resumen = await engine.get_summary(session_id)
    return {
        c["field_key"]: ("" if c["valor"] is None else str(c["valor"]))
        for c in resumen["campos"]
    }


class SessionBody(BaseModel):
    session_id: str


@router.post("/excel/generate")
async def excel_generate(body: SessionBody, user: dict = Depends(get_current_user)):
    await verify_session_ownership(body.session_id, user)
    campos = await _campos_de_sesion(body.session_id)

    excel_bytes = generate_excel(campos)
    nombre = re.sub(r"[^A-Za-z0-9_-]+", "_", campos.get("id_actividad") or "sin_id")

    return Response(
        content=excel_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f"attachment; filename=consolidacion_epm_{nombre}.xlsx"
            )
        },
    )


@router.post("/sheets/submit")
async def sheets_submit(body: SessionBody, user: dict = Depends(get_current_user)):
    """
    Escribe la fila en Google Sheets a partir de los datos ya capturados.
    Ya no reconstruye los campos con un segundo llamado al modelo.
    """
    await verify_session_ownership(body.session_id, user)
    campos = await _campos_de_sesion(body.session_id)

    if not any(campos.values()):
        raise HTTPException(
            status_code=400,
            detail=(
                "No hay datos para guardar. Diligencia al menos el bloque 1 "
                "antes de exportar."
            ),
        )

    fila = await append_actividad(campos)
    if fila == -1:
        raise HTTPException(
            status_code=502,
            detail="No se pudo escribir en Google Sheets. Verifica los permisos.",
        )

    await repo.project_actividad(
        body.session_id,
        user["id"],
        {"sheets_row": fila},
    )

    return {
        "ok": True,
        "sheets_row": fila,
        "campos_guardados": sum(1 for v in campos.values() if v),
        "sheets_url": sheet_url(),
    }


@router.get("/sheets/structure")
async def sheets_structure(_: dict = Depends(get_current_user)):
    return {"headers": await read_sheet_structure()}


class EmailBody(BaseModel):
    session_id: str
    to_email: EmailStr
    sheets_row: int = 0


@router.post("/email/send")
async def email_send(body: EmailBody, user: dict = Depends(limitar_correo)):
    await verify_session_ownership(body.session_id, user)
    campos = await _campos_de_sesion(body.session_id)

    if not any(campos.values()):
        raise HTTPException(
            status_code=400,
            detail="No hay datos de actividad para enviar.",
        )

    try:
        await send_consolidation_email(
            to_email=str(body.to_email),
            form_data=campos,
            facilitador=user["nombre"],
            sheets_url=sheet_url(),
            sheets_row=body.sheets_row,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Fallo al enviar correo: %s", exc)
        raise HTTPException(
            status_code=502, detail=f"No se pudo enviar el correo: {exc}"
        ) from exc

    return {"ok": True, "to": str(body.to_email)}
