"""
Etapa final: análisis, recomendaciones e ideas derivadas, y sugerencias de
redacción durante la captura.

Único grupo de rutas que llama al modelo. Ambas están limitadas por tasa.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_current_user, limitar_modelo, verify_session_ownership
from app.services import ideas_service
from app.services.ideas_service import IdeasError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ideas", tags=["análisis e ideas"])


# Ruta explícita, no "/{session_id}": con un parámetro de ruta aquí, una
# petición a /api/ideas/sugerir se resolvería como session_id="sugerir".
@router.post("/analisis/{session_id}")
async def generar(session_id: str, user: dict = Depends(limitar_modelo)):
    """
    Genera resumen, análisis, recomendaciones e ideas a partir de los datos
    ya consolidados.

    Si falla, la consolidación sigue siendo válida: se responde con error y
    el facilitador puede reintentar sin perder nada.
    """
    session = await verify_session_ownership(session_id, user)
    try:
        return await ideas_service.generar_analisis(
            session_id, str(session.get("user_id") or user["id"])
        )
    except IdeasError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Fallo del análisis para %s: %s", session_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo generar el análisis: {exc}",
        ) from exc


class SugerenciaBody(BaseModel):
    session_id: str
    node_id: str
    borrador: str = Field(min_length=1, max_length=8000)


@router.post("/sugerir", status_code=200)
async def sugerir(body: SugerenciaBody, user: dict = Depends(limitar_modelo)):
    """
    Sugerencias de redacción sobre lo que el facilitador ya escribió.

    No captura datos, no decide el valor del campo y no avanza el árbol. Si
    falla, el flujo de captura continúa sin cambios.
    """
    await verify_session_ownership(body.session_id, user)
    try:
        sugerencias = await ideas_service.sugerir_redaccion(
            body.session_id, body.node_id, body.borrador
        )
    except IdeasError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Sugerencia no disponible: %s", exc)
        raise HTTPException(
            status_code=502, detail="El servicio de sugerencias no está disponible."
        ) from exc

    return {"sugerencias": sugerencias}
