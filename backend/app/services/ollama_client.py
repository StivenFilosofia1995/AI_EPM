import logging
from typing import AsyncGenerator

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def _make_client(engine: str) -> tuple[AsyncOpenAI, str]:
    """Return (AsyncOpenAI client, model_name) for the given engine."""
    if engine == "ollama":
        client = AsyncOpenAI(
            api_key="ollama",
            base_url=settings.OLLAMA_BASE_URL,
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(60.0)),
        )
        return client, settings.OLLAMA_MODEL

    if engine == "groq":
        client = AsyncOpenAI(
            api_key=settings.GROQ_API_KEY or "",
            base_url=settings.GROQ_BASE_URL,
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(60.0)),
        )
        return client, settings.GROQ_MODEL

    raise ValueError(f"Unknown engine: {engine!r}")


def _engine_order() -> list[str]:
    """Return engines to try in order, with fallback."""
    primary = settings.PRIMARY_ENGINE
    engines = [primary]
    if primary == "ollama" and settings.GROQ_API_KEY:
        engines.append("groq")
    elif primary == "groq" and not settings.GROQ_API_KEY:
        # No key → fall back to ollama
        engines = ["ollama"]
    return engines


async def stream_chat(
    messages: list[dict],
    engine: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream chat completions, falling back through available engines."""
    engines = [engine] if engine else _engine_order()
    last_error: Exception | None = None

    for eng in engines:
        try:
            client, model = _make_client(eng)
            async with client:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=settings.MAX_TOKENS,
                    temperature=settings.TEMPERATURE,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
            return  # success — stop trying other engines
        except Exception as exc:
            last_error = exc
            logger.warning("Engine %s failed: %s", eng, exc)
            continue

    err_text = f"Todos los motores fallaron. Último error: {last_error}"
    logger.error(err_text)
    yield err_text


async def ollama_health() -> dict:
    """Return status for the primary engine; falls back to available alternative."""
    primary = settings.PRIMARY_ENGINE

    if primary == "groq":
        if settings.GROQ_API_KEY:
            return {"status": "healthy", "engine": "groq", "model": settings.GROQ_MODEL}
        # Key missing — try Ollama
        primary = "ollama"

    # Check Ollama
    try:
        base = settings.OLLAMA_BASE_URL.replace("/v1", "")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/api/tags")
            if resp.status_code == 200:
                return {
                    "status": "healthy",
                    "engine": "ollama",
                    "model": settings.OLLAMA_MODEL,
                }
    except Exception as exc:
        logger.warning("Ollama health check failed: %s", exc)

    # Fallback to Groq
    if settings.GROQ_API_KEY:
        return {"status": "healthy", "engine": "groq", "model": settings.GROQ_MODEL}

    return {"status": "degraded", "engine": "none", "model": "unavailable"}
