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

async def ensure_session(session_id: str, user_name: str = "") -> None:
    """Create or update session record. Saves user_name when provided."""
    if not settings.USE_SUPABASE_MEMORY:
        return
    try:
        client = _get_client()
        record: dict = {"session_id": session_id}
        if user_name:
            record["user_name"] = user_name
        await asyncio.to_thread(
            lambda: client.table("epm_sessions")
            .upsert(record, on_conflict="session_id")
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


# ─── Admin ────────────────────────────────────────────────────────────────────

async def get_all_sessions(limit: int = 500) -> list[dict]:
    """Return all sessions with user_name ordered by most recent."""
    try:
        client = _get_client()
        result = await asyncio.to_thread(
            lambda: client.table("epm_sessions")
            .select("session_id,user_name,created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Supabase get_all_sessions: %s", exc)
        return []


async def get_session_messages_all(session_id: str) -> list[dict]:
    """Return full message history for a session (admin use)."""
    try:
        client = _get_client()
        result = await asyncio.to_thread(
            lambda: client.table("epm_messages")
            .select("role,content,created_at")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Supabase get_session_messages_all: %s", exc)
        return []


async def get_actividad_by_session(session_id: str) -> dict:
    """Return activity form data for a specific session."""
    try:
        client = _get_client()
        result = await asyncio.to_thread(
            lambda: client.table("epm_actividades")
            .select("*")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else {}
    except Exception as exc:
        logger.warning("Supabase get_actividad_by_session: %s", exc)
        return {}
