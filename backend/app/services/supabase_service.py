import asyncio
import logging
from typing import Optional

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def _get_client() -> Client:
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client


# ─── Sessions ────────────────────────────────────────────────────────────────

async def ensure_session(session_id: str) -> None:
    """Create session record if not exists (upsert)."""
    if not settings.USE_SUPABASE_MEMORY:
        return
    try:
        client = _get_client()
        await asyncio.to_thread(
            lambda: client.table("epm_sessions")
            .upsert({"session_id": session_id}, on_conflict="session_id")
            .execute()
        )
    except Exception as exc:
        logger.warning("Supabase ensure_session: %s", exc)


# ─── Messages ────────────────────────────────────────────────────────────────

async def append_message(session_id: str, role: str, content: str) -> None:
    """Persist a single chat message."""
    if not settings.USE_SUPABASE_MEMORY:
        return
    try:
        client = _get_client()
        await asyncio.to_thread(
            lambda: client.table("epm_messages")
            .insert({"session_id": session_id, "role": role, "content": content})
            .execute()
        )
    except Exception as exc:
        logger.warning("Supabase append_message: %s", exc)


async def load_history(session_id: str) -> list[dict]:
    """Load recent messages for a session ordered oldest→newest."""
    if not settings.USE_SUPABASE_MEMORY:
        return []
    try:
        client = _get_client()
        limit = settings.MEMORY_WINDOW_MESSAGES
        result = await asyncio.to_thread(
            lambda: client.table("epm_messages")
            .select("role,content")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return [{"role": r["role"], "content": r["content"]} for r in (result.data or [])]
    except Exception as exc:
        logger.warning("Supabase load_history: %s", exc)
        return []


# ─── Actividades ─────────────────────────────────────────────────────────────

async def save_actividad(session_id: str, form_data: dict) -> None:
    """Upsert completed activity form data keyed by session_id."""
    if not settings.USE_SUPABASE_MEMORY:
        return
    try:
        client = _get_client()
        record = {"session_id": session_id, **form_data}
        await asyncio.to_thread(
            lambda: client.table("epm_actividades")
            .upsert(record, on_conflict="session_id")
            .execute()
        )
    except Exception as exc:
        logger.warning("Supabase save_actividad: %s", exc)


async def load_actividades(limit: int = 100) -> list[dict]:
    """Return the most recent consolidated activities."""
    try:
        client = _get_client()
        result = await asyncio.to_thread(
            lambda: client.table("epm_actividades")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Supabase load_actividades: %s", exc)
        return []
