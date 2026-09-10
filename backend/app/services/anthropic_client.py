import logging
from typing import AsyncGenerator

import httpx
from anthropic import AsyncAnthropic

from app.config import settings

logger = logging.getLogger(__name__)


def _make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=20.0, read=120.0, write=20.0, pool=20.0),
        follow_redirects=True,
        verify=True,
    )


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


async def stream_chat(
    messages: list[dict],
    engine: str | None = None,
) -> AsyncGenerator[str, None]:
    if not settings.ANTHROPIC_API_KEY:
        yield (
            "❌ **ANTHROPIC_API_KEY no configurado.**\n\n"
            "Agrega la variable en Railway Dashboard → Variables:\n"
            "- `ANTHROPIC_API_KEY`\n- `ANTHROPIC_MODEL=claude-haiku-4-5-20251001`"
        )
        return

    system_text, chat_messages = _anthropic_payload(messages)
    if not chat_messages:
        chat_messages = [{"role": "user", "content": "Hola"}]

    client = AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        base_url=settings.ANTHROPIC_BASE_URL or None,
        http_client=_make_http_client(),
    )

    try:
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
    except Exception as exc:
        logger.error("Anthropic stream failed: %s", exc)
        yield (
            f"❌ **Error al conectar con Claude.**\n\n"
            f"Verifica que `ANTHROPIC_API_KEY` sea válida en Railway.\n\n"
            f"_(Detalle: {type(exc).__name__}: {exc})_"
        )


async def complete(
    system: str,
    prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, int, int]:
    """
    Llamada sin streaming para la etapa de análisis e ideas.

    Devuelve (texto, tokens_entrada, tokens_salida). Propaga la excepción:
    a diferencia de stream_chat, aquí un fallo NO se disfraza de respuesta,
    porque quien llama necesita distinguir un análisis real de un error.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY no está configurada.")

    client = AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        base_url=settings.ANTHROPIC_BASE_URL or None,
        http_client=_make_http_client(),
    )

    respuesta = await client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens or settings.MAX_TOKENS,
        temperature=settings.TEMPERATURE if temperature is None else temperature,
    )

    texto = "".join(
        bloque.text for bloque in respuesta.content if getattr(bloque, "type", "") == "text"
    )
    uso = getattr(respuesta, "usage", None)
    return (
        texto,
        getattr(uso, "input_tokens", 0) or 0,
        getattr(uso, "output_tokens", 0) or 0,
    )
