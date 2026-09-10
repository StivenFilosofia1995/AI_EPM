"""
Etapa final: análisis e ideas derivadas.

Único punto donde interviene el modelo de lenguaje. Recibe DATOS
ESTRUCTURADOS desde epm_respuestas, nunca un historial de chat.

Regla operativa: el fallo de esta etapa no invalida nada. La consolidación
queda válida y el análisis se puede reintentar. Por eso las excepciones se
propagan hacia la ruta, que responde con un código de error, en lugar de
guardar un texto de disculpa como si fuera un análisis.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ValidationError, field_validator

from app.config import settings
from app.domain import fields as F
from app.domain.tree_loader import get_tree
from app.services import tree_repository as repo
from app.services.anthropic_client import complete
from app.services.db import get_client

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_ANALISIS = PROMPTS_DIR / "analisis_v1.txt"
PROMPT_SUGERENCIA = PROMPTS_DIR / "sugerencia_v1.txt"

# Temperatura baja: esta etapa interpreta, no imagina.
TEMPERATURA = 0.3

TIPOS = ("resumen", "analisis", "recomendaciones", "ideas")


class IdeasError(Exception):
    """El modelo falló o devolvió algo que no cumple el esquema."""


def _leer_prompt(path: Path) -> tuple[str, str]:
    texto = path.read_text(encoding="utf-8")
    return texto, hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


# ─── Esquema estricto de las ideas ──────────────────────────────────────────


class Idea(BaseModel):
    nombre: str
    publico_sugerido: str
    tipo_actividad: str
    pregunta_problematizadora: str
    ods: list[str]
    justificacion: str = ""

    @field_validator("publico_sugerido")
    @classmethod
    def _publico(cls, v: str) -> str:
        if v not in F.PUBLICOS:
            raise ValueError(f"publico_sugerido inválido: {v!r}")
        return v

    @field_validator("tipo_actividad")
    @classmethod
    def _tipo(cls, v: str) -> str:
        if v not in F.TIPOS_ACTIVIDAD:
            raise ValueError(f"tipo_actividad inválido: {v!r}")
        return v

    @field_validator("ods")
    @classmethod
    def _ods(cls, v: list[str]) -> list[str]:
        invalidos = [o for o in v if o not in F.ODS]
        if invalidos:
            raise ValueError(f"ODS inválidos: {invalidos}")
        return v


class Ideas(BaseModel):
    ideas: list[Idea]

    @field_validator("ideas")
    @classmethod
    def _cantidad(cls, v: list[Idea]) -> list[Idea]:
        if not 3 <= len(v) <= 5:
            raise ValueError(f"Se esperaban entre 3 y 5 ideas, llegaron {len(v)}.")
        return v


class Sugerencias(BaseModel):
    sugerencias: list[str]

    @field_validator("sugerencias")
    @classmethod
    def _limpiar(cls, v: list[str]) -> list[str]:
        limpias = [s.strip() for s in v if s and s.strip()]
        if not limpias:
            raise ValueError("No llegó ninguna sugerencia utilizable.")
        return limpias[:3]


def _extraer_json(texto: str) -> dict:
    """El modelo puede envolver el JSON en markdown pese a la instrucción."""
    limpio = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(limpio)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", limpio)
    if not m:
        raise IdeasError("La respuesta del modelo no contiene un objeto JSON.")
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as exc:
        raise IdeasError(f"El JSON de la respuesta está mal formado: {exc}") from exc


# ─── Contexto estructurado ──────────────────────────────────────────────────


async def _contexto(session_id: str) -> tuple[str, dict[str, Any]]:
    """Los 25 campos como texto etiquetado. Nunca un historial de chat."""
    tree = get_tree()
    rows = await repo.get_respuestas(session_id)

    from app.services.tree_engine import _answers, compose_fields

    campos = compose_fields(tree, _answers(tree, rows))

    lineas = []
    for key in F.FIELD_KEYS:
        v = campos.get(key)
        header = F.FIELD_BY_KEY[key].header
        lineas.append(f"{header}: {v if v else '(SIN DILIGENCIAR)'}")

    return "\n".join(lineas), campos


def _listas_validas() -> str:
    return (
        f"PUBLICOS válidos: {', '.join(F.PUBLICOS)}\n"
        f"TIPOS_ACTIVIDAD válidos: {', '.join(F.TIPOS_ACTIVIDAD)}\n"
        f"ODS válidos: {', '.join(F.ODS)}"
    )


async def _guardar(
    session_id: str,
    user_id: Optional[str],
    tipo: str,
    contenido: str,
    prompt_hash: str,
    entrada: int,
    salida: int,
) -> None:
    client = get_client()
    import asyncio

    await asyncio.to_thread(
        lambda: client.table("epm_analisis_ia").insert({
            "session_id": session_id,
            "user_id": user_id,
            "tipo": tipo,
            "contenido": contenido,
            "modelo": settings.ANTHROPIC_MODEL,
            "prompt_hash": prompt_hash,
            "tokens_entrada": entrada,
            "tokens_salida": salida,
        }).execute()
    )


# ─── Generación ─────────────────────────────────────────────────────────────


async def generar_analisis(session_id: str, user_id: Optional[str]) -> dict:
    """
    Genera las cuatro piezas y las guarda en epm_analisis_ia.

    Las tres piezas de texto se generan de forma independiente: si una falla,
    las demás se conservan. Las ideas exigen JSON estricto validado con
    Pydantic, con un reintento y luego fallo explícito.
    """
    sistema, prompt_hash = _leer_prompt(PROMPT_ANALISIS)
    datos, campos = await _contexto(session_id)

    if not any(campos.values()):
        raise IdeasError(
            "La sesión no tiene datos consolidados. Diligencia la actividad "
            "antes de generar el análisis."
        )

    salida: dict[str, Any] = {"session_id": session_id}

    for tipo in ("resumen", "analisis", "recomendaciones"):
        prompt = (
            f"Pieza solicitada: {tipo.upper()}\n\n"
            f"DATOS CONSOLIDADOS DE LA ACTIVIDAD:\n{datos}"
        )
        try:
            texto, tin, tout = await complete(
                system=sistema, prompt=prompt, temperature=TEMPERATURA, max_tokens=1200
            )
            salida[tipo] = texto.strip()
            await _guardar(session_id, user_id, tipo, texto.strip(), prompt_hash, tin, tout)
        except Exception as exc:
            logger.error("Fallo generando %s para %s: %s", tipo, session_id, exc)
            salida[tipo] = None
            salida.setdefault("errores", []).append(f"{tipo}: {exc}")

    # ── Ideas: JSON estricto, un reintento, luego fallo explícito ──
    prompt_ideas = (
        f"Pieza solicitada: IDEAS\n\n{_listas_validas()}\n\n"
        f"DATOS CONSOLIDADOS DE LA ACTIVIDAD:\n{datos}"
    )
    ideas: Optional[Ideas] = None
    ultimo_error = ""

    for intento in (1, 2):
        try:
            texto, tin, tout = await complete(
                system=sistema, prompt=prompt_ideas,
                temperature=TEMPERATURA, max_tokens=1600,
            )
            ideas = Ideas(**_extraer_json(texto))
            await _guardar(session_id, user_id, "ideas", texto.strip(), prompt_hash, tin, tout)
            break
        except (IdeasError, ValidationError) as exc:
            ultimo_error = str(exc)
            logger.warning(
                "Ideas no cumplen el esquema (intento %d/2) en %s: %s",
                intento, session_id, exc,
            )
            prompt_ideas += (
                f"\n\nTu respuesta anterior fue descartada por este motivo: "
                f"{exc}\nCorrígelo y devuelve solo el JSON válido."
            )
        except Exception as exc:
            ultimo_error = str(exc)
            logger.error("Fallo generando ideas para %s: %s", session_id, exc)
            break

    if ideas is None:
        salida["ideas"] = []
        salida.setdefault("errores", []).append(f"ideas: {ultimo_error}")
    else:
        salida["ideas"] = [i.model_dump() for i in ideas.ideas]

    salida["modelo"] = settings.ANTHROPIC_MODEL
    salida["prompt_hash"] = prompt_hash
    return salida


async def sugerir_redaccion(session_id: str, node_id: str, borrador: str) -> list[str]:
    """
    Sugerencias de redacción para un campo de texto largo.

    Reformula lo que el facilitador YA escribió. No captura datos, no decide
    el valor y no avanza el árbol: si esta función falla, el motor sigue
    funcionando igual. Es asistencia, no dependencia.
    """
    borrador = (borrador or "").strip()
    if len(borrador) < 10:
        return []

    tree = get_tree()
    if node_id not in tree.by_id:
        raise IdeasError(f"El nodo {node_id} no existe.")
    nodo = tree.node(node_id)

    datos, _ = await _contexto(session_id)
    sistema, _ = _leer_prompt(PROMPT_SUGERENCIA)

    prompt = (
        f"CAMPO QUE SE ESTÁ DILIGENCIANDO: {nodo.label}\n"
        f"{('AYUDA DEL CAMPO: ' + nodo.help) if nodo.help else ''}\n\n"
        f"BORRADOR DEL FACILITADOR (esto es lo que debes reformular):\n"
        f"{borrador}\n\n"
        f"CONTEXTO YA CAPTURADO DE LA ACTIVIDAD (solo para dar coherencia; "
        f"no incorpores datos nuevos desde aquí):\n{datos}"
    )

    texto, _, _ = await complete(
        system=sistema, prompt=prompt, temperature=0.4, max_tokens=900
    )
    try:
        return Sugerencias(**_extraer_json(texto)).sugerencias
    except (IdeasError, ValidationError) as exc:
        logger.warning("Sugerencias mal formadas para %s: %s", node_id, exc)
        return []
