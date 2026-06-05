import json
import logging
import re
from typing import AsyncGenerator

from app.config import settings
from app.services import supabase_service
from app.services.ollama_client import stream_chat
from app.services.system_prompt import SYSTEM_PROMPT

# Ordered field keys matching google_sheets_service.FIELD_KEYS
_FIELD_KEYS = [
    "id_actividad", "programa", "linea_accion", "tipo_actividad", "nombre",
    "publico", "publico_especifico", "lugar", "responsable", "duracion",
    "pregunta_problematizadora", "ods", "metodologia", "descripcion_sesion",
    "recursos", "fecha", "logros", "retos", "observaciones", "comentarios",
    "instrumento_evaluativo", "participantes_evaluados", "cumplimiento_objetivos",
    "acciones_mejora", "porcentaje_cumplimiento",
]

_EXTRACTION_PROMPT = """Eres un extractor de datos. Analiza la conversación y extrae los valores de los 25 campos del formulario EPM.

Devuelve ÚNICAMENTE un objeto JSON válido con exactamente estas claves (usa "" si no se mencionó el campo):
{
  "id_actividad": "",
  "programa": "",
  "linea_accion": "",
  "tipo_actividad": "",
  "nombre": "",
  "publico": "",
  "publico_especifico": "",
  "lugar": "",
  "responsable": "",
  "duracion": "",
  "pregunta_problematizadora": "",
  "ods": "",
  "metodologia": "",
  "descripcion_sesion": "",
  "recursos": "",
  "fecha": "",
  "logros": "",
  "retos": "",
  "observaciones": "",
  "comentarios": "",
  "instrumento_evaluativo": "",
  "participantes_evaluados": "",
  "cumplimiento_objetivos": "",
  "acciones_mejora": "",
  "porcentaje_cumplimiento": ""
}

CONVERSACIÓN:
{history}

Responde SOLO con el JSON. Sin texto adicional."""

logger = logging.getLogger(__name__)

# In-memory session cache: { session_id: { messages, form_data, step, loaded } }
_sessions: dict[str, dict] = {}


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "messages": [],
            "form_data": {},
            "step": 0,
            "loaded": False,
        }
    return _sessions[session_id]


async def _ensure_loaded(session_id: str, user_name: str = "") -> bool:
    """
    Load conversation history from Supabase on first access.
    Returns True if history was restored (session existed).
    """
    session = _get_session(session_id)
    if session["loaded"]:
        return False

    await supabase_service.ensure_session(session_id, user_name=user_name)
    history = await supabase_service.load_history(session_id)
    session["messages"] = history
    session["loaded"] = True
    return len(history) > 0


async def _append(session_id: str, role: str, content: str) -> None:
    session = _get_session(session_id)
    session["messages"].append({"role": role, "content": content})
    # Bound in-memory history
    if len(session["messages"]) > settings.MAX_HISTORY:
        session["messages"] = session["messages"][-settings.MAX_HISTORY:]
    # Persist (fire & forget — errors logged but don't block)
    await supabase_service.append_message(session_id, role, content)


async def process_message_stream(
    session_id: str,
    user_message: str,
    user_name: str | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE chunks; persist every message to Supabase."""
    restored = await _ensure_loaded(session_id, user_name=user_name or "")
    if restored:
        yield (
            f"data: {json.dumps({'meta': 'history_restored'}, ensure_ascii=False)}\n\n"
        )

    await _append(session_id, "user", user_message)

    # Store user name in session if provided
    session = _get_session(session_id)
    if user_name and not session.get("user_name"):
        session["user_name"] = user_name

    name = session.get("user_name") or user_name or ""
    name_line = f"\n\nFacilitador/a activo/a: **{name}**. Dirígete a él/ella por su nombre." if name else ""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + name_line},
        *session["messages"],
    ]

    full_response = ""
    try:
        async for chunk in stream_chat(messages):
            full_response += chunk
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
    except Exception as exc:
        error_msg = (
            "Lo siento, ocurrió un error al procesar tu mensaje. "
            "Por favor intenta de nuevo."
        )
        logger.error("Streaming error for session %s: %s", session_id, exc)
        yield f"data: {json.dumps({'content': error_msg}, ensure_ascii=False)}\n\n"
        full_response = error_msg

    await _append(session_id, "assistant", full_response)
    yield "data: [DONE]\n\n"


def get_session_form_data(session_id: str) -> dict:
    return _get_session(session_id).get("form_data", {})


def update_form_field(session_id: str, field: str, value: str) -> None:
    """Update a single form field in memory."""
    _get_session(session_id)["form_data"][field] = value


def get_step(session_id: str) -> int:
    return _get_session(session_id).get("step", 0)


def set_step(session_id: str, step: int) -> None:
    _get_session(session_id)["step"] = step


def clear_session(session_id: str) -> None:
    _sessions.pop(session_id, None)


async def extract_fields_from_history(session_id: str) -> dict:
    """
    Use the LLM to extract all 25 form fields from the conversation history.
    Falls back to whatever is already in form_data for non-empty fields.
    """
    session = _get_session(session_id)
    messages = session.get("messages", [])

    # Build a condensed transcript (last 60 messages max)
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content'][:800]}"
        for m in messages[-60:]
    )
    if not history_text.strip():
        return session.get("form_data", {})

    prompt = _EXTRACTION_PROMPT.replace("{history}", history_text)

    full_response = ""
    async for chunk in stream_chat([{"role": "user", "content": prompt}]):
        full_response += chunk

    # Extract JSON from response (model may wrap it in markdown)
    json_match = re.search(r"\{[\s\S]*\}", full_response)
    if not json_match:
        logger.warning("extract_fields: no JSON found in LLM response")
        return session.get("form_data", {})

    try:
        extracted = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning("extract_fields: JSON parse error: %s", exc)
        return session.get("form_data", {})

    # Merge: prefer extracted non-empty values, keep existing form_data as fallback
    existing = session.get("form_data", {})
    merged = {k: (extracted.get(k) or existing.get(k, "")) for k in _FIELD_KEYS}

    # Persist merged data back into session
    session["form_data"] = merged
    logger.info("extract_fields: extracted %d non-empty fields for session %s",
                sum(1 for v in merged.values() if v), session_id)
    return merged
