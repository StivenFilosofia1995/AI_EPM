import logging
from typing import AsyncGenerator

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def _make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=20.0, read=120.0, write=20.0, pool=20.0),
        follow_redirects=True,
        verify=True,
    )


def _make_openai_client(engine: str) -> tuple[AsyncOpenAI, str]:
    if engine == "ollama":
        return AsyncOpenAI(
            api_key="ollama",
            base_url=settings.OLLAMA_BASE_URL,
            http_client=_make_http_client(),
        ), settings.OLLAMA_MODEL

    if engine == "groq":
        return AsyncOpenAI(
            api_key=settings.GROQ_API_KEY or "",
            base_url=settings.GROQ_BASE_URL,
            http_client=_make_http_client(),
        ), settings.GROQ_MODEL

    raise ValueError(f"Unknown engine: {engine!r}")


def _anthropic_payload(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts: list[str] = []
    chat_messages: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = str(msg.get("content", ""))
        if role == "system":
            system_parts.append(content)
        elif role in {"user", "assistant"}:
            chat_messages.append({"role": role, "content": content})
    return "\n\n".join(system_parts).strip(), chat_messages


def _is_engine_available(engine: str) -> bool:
    if engine == "anthropic":
        return bool(settings.ANTHROPIC_API_KEY)
    if engine == "groq":
        return bool(settings.GROQ_API_KEY)
    if engine == "ollama":
        return True
    return False


def _engine_order() -> list[str]:
    primary = (settings.PRIMARY_ENGINE or "").strip().lower()
    preference = {
        "anthropic": ["anthropic", "groq", "ollama"],
        "groq":      ["groq", "anthropic", "ollama"],
        "ollama":    ["ollama", "groq", "anthropic"],
    }
    ordered = preference.get(primary, ["anthropic", "groq", "ollama"])
    engines = [e for e in ordered if _is_engine_available(e)]
    return engines or ["ollama"]


async def _stream_anthropic(messages: list[dict]) -> AsyncGenerator[str, None]:
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY no está configurado")

    system_text, chat_messages = _anthropic_payload(messages)
    if not chat_messages:
        chat_messages = [{"role": "user", "content": "Hola"}]

    client = AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        base_url=settings.ANTHROPIC_BASE_URL or None,
        http_client=_make_http_client(),
    )

    async with client.messages.stream(
        model=settings.ANTHROPIC_MODEL,
        system=system_text,
        messages=chat_messages,
        max_tokens=settings.MAX_TOKENS,
        temperature=settings.TEMPERATURE,
    ) as stream:
        async for text in stream.text_stream:
            if text:
                yield text


async def _stream_openai_compatible(engine: str, messages: list[dict]) -> AsyncGenerator[str, None]:
    client, model = _make_openai_client(engine)
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


async def stream_chat(
    messages: list[dict],
    engine: str | None = None,
) -> AsyncGenerator[str, None]:
    engines = [engine] if engine else _engine_order()
    errors: dict[str, str] = {}

    for eng in engines:
        try:
            if eng == "anthropic":
                async for delta in _stream_anthropic(messages):
                    yield delta
            else:
                async for delta in _stream_openai_compatible(eng, messages):
                    yield delta
            return  # success
        except Exception as exc:
            errors[eng] = f"{type(exc).__name__}: {exc}"
            logger.warning("Engine %s failed: %s", eng, errors[eng])
            continue

    details = " | ".join(f"{e}: {m}" for e, m in errors.items())
    logger.error("All engines failed: %s", details)
    yield (
        f"❌ **Error de conexión con la IA.**\n\n"
        f"Verifica en Railway que estén configuradas las variables:\n"
        f"- `ANTHROPIC_API_KEY`\n- `PRIMARY_ENGINE=anthropic`\n\n"
        f"_(Detalle: {details})_"
    )


async def ollama_health() -> dict:
    primary = (settings.PRIMARY_ENGINE or "").strip().lower()

    if primary == "anthropic" and settings.ANTHROPIC_API_KEY:
        return {"status": "healthy", "engine": "anthropic", "model": settings.ANTHROPIC_MODEL}

    if primary == "groq" and settings.GROQ_API_KEY:
        return {"status": "healthy", "engine": "groq", "model": settings.GROQ_MODEL}

    try:
        base = settings.OLLAMA_BASE_URL.replace("/v1", "")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/api/tags")
            if resp.status_code == 200:
                return {"status": "healthy", "engine": "ollama", "model": settings.OLLAMA_MODEL}
    except Exception as exc:
        logger.warning("Ollama health check failed: %s", exc)

    if settings.GROQ_API_KEY:
        return {"status": "healthy", "engine": "groq", "model": settings.GROQ_MODEL}
    if settings.ANTHROPIC_API_KEY:
        return {"status": "healthy", "engine": "anthropic", "model": settings.ANTHROPIC_MODEL}

    return {"status": "degraded", "engine": "none", "model": "unavailable"}
