"""
Exportación a Excel.

Es la única vía de salida del sistema. Se retiraron Google Sheets y el envío
por correo: la consolidación vive en la base de datos y se descarga en Excel,
que es el formato institucional. Eso eliminó la dependencia de una cuenta de
servicio de Google y de un servidor SMTP.

Leen de epm_respuestas o de la proyección consolidada, nunca de la caché en
memoria del proceso. Exigen autenticación y verifican propiedad de la sesión;
la exportación por lote limita el alcance según el rol.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.dependencies import get_current_user, verify_session_ownership
from app.domain.fields import FIELD_KEYS
from app.services import tree_engine as engine
from app.services import tree_repository as repo
from app.services.db import get_client
from app.services.excel_service import generate_excel, generate_excel_lote

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




# ─── Exportación por lote ───────────────────────────────────────────────────


class LoteBody(BaseModel):
    """
    Filtros de la exportación.

    Un facilitador solo puede exportar lo suyo: `user_id` se ignora y se
    reemplaza por su propia identidad. Coordinadores y administradores sí
    pueden filtrar por persona.
    """

    user_id: str | None = None
    programa: str | None = None
    estado: str | None = None
    desde: str | None = None
    hasta: str | None = None


@router.post("/excel/lote")
async def excel_lote(body: LoteBody, user: dict = Depends(get_current_user)):
    """Un libro con una fila por consolidación, para seguimiento."""
    supervisa = user["rol"] in ("admin", "coordinador")
    user_id = body.user_id if supervisa else user["id"]

    client = get_client()

    def _consultar():
        q = client.table("v_actividades_completas").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        if body.programa:
            q = q.eq("programa", body.programa)
        if body.estado:
            q = q.eq("estado", body.estado)
        if body.desde:
            q = q.gte("created_at", body.desde)
        if body.hasta:
            q = q.lte("created_at", body.hasta)
        return q.order("created_at", desc=True).limit(2000).execute()

    resultado = await asyncio.to_thread(_consultar)
    filas = resultado.data or []

    if not filas:
        raise HTTPException(
            status_code=404,
            detail="No hay consolidaciones que coincidan con el filtro.",
        )

    contenido = generate_excel_lote(filas)
    marca = datetime.now(UTC).strftime("%Y%m%d")
    ambito = "equipo" if supervisa and not body.user_id else "mis_consolidaciones"

    return Response(
        content=contenido,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f"attachment; filename=consolidaciones_epm_{ambito}_{marca}.xlsx"
            ),
            "X-Total-Filas": str(len(filas)),
        },
    )
