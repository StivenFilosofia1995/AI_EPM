"""
Escritura en Google Sheets.

FIELD_KEYS y FIELD_HEADERS ya NO se definen aquí: se importan de
app.domain.fields, que es la fuente de verdad única. Se reexportan para no
romper a quien todavía los importe desde este módulo (email_service).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings
from app.domain.fields import FIELD_HEADERS, FIELD_KEYS

logger = logging.getLogger(__name__)

__all__ = [
    "FIELD_KEYS",
    "FIELD_HEADERS",
    "append_actividad",
    "read_sheet_structure",
    "read_all_rows",
    "sanitizar_celda",
    "sheet_url",
]

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# La hoja real tiene notas en las filas 1 a 3; los encabezados van en la 4.
_HEADER_ROW = 4

# gspread devuelve el rango escrito como "Hoja!A123:Y123". De ahí se extrae la
# fila realmente escrita, en lugar de usar ws.row_count, que es el total de
# filas del grid (incluidas las vacías) y no dice nada sobre dónde se escribió.
_RANGE_ROW_RE = re.compile(r"![A-Z]+(\d+)(?::|$)")

# Prefijos que Google Sheets interpreta como fórmula.
_PELIGROSOS = ("=", "+", "-", "@")


def sanitizar_celda(valor: object) -> str:
    """
    Evita la inyección de fórmulas.

    La hoja se escribe con USER_ENTERED para que las fechas y los números
    conserven su tipo, lo que significa que Sheets interpreta el contenido.
    Un valor que empiece por =, +, - o @ se ejecutaría como fórmula. Se le
    antepone un apóstrofo, que Sheets usa para forzar texto literal y que no
    aparece en la celda renderizada.
    """
    texto = "" if valor is None else str(valor)
    if texto[:1] in _PELIGROSOS:
        return "'" + texto
    return texto


def sheet_url() -> str:
    """Enlace a la hoja usando el GID configurado, no uno fijo en el código."""
    gid = settings.GOOGLE_SHEETS_GID or "0"
    return (
        f"https://docs.google.com/spreadsheets/d/{settings.GOOGLE_SHEETS_ID}"
        f"/edit?gid={gid}#gid={gid}"
    )


def _build_credentials() -> Credentials:
    """Credenciales desde el JSON completo (Railway) o desde archivo (local)."""
    json_str = settings.GOOGLE_CREDENTIALS_JSON
    if json_str:
        info = json.loads(json_str)
        return Credentials.from_service_account_info(info, scopes=_SCOPES)

    path = settings.SERVICE_ACCOUNT_FILE
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), "..", "..", path)
    return Credentials.from_service_account_file(path, scopes=_SCOPES)


def _open_worksheet() -> gspread.Worksheet:
    """Hoja destino. Síncrono: ejecutar dentro de asyncio.to_thread."""
    creds = _build_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(settings.GOOGLE_SHEETS_ID)
    try:
        ws = sh.get_worksheet_by_id(int(settings.GOOGLE_SHEETS_GID))
    except Exception:
        logger.warning(
            "No se encontró la hoja con GID %s; se usa la primera.",
            settings.GOOGLE_SHEETS_GID,
        )
        ws = sh.sheet1
    return ws


def _ensure_headers(ws: gspread.Worksheet) -> None:
    """Escribe los encabezados en la fila 4 si está vacía (primera vez)."""
    header_row = ws.row_values(_HEADER_ROW)
    if not any(header_row):
        ws.insert_row(list(FIELD_HEADERS), index=_HEADER_ROW)


# ─── API asíncrona ──────────────────────────────────────────────────────────


async def read_sheet_structure() -> list[str]:
    try:
        def _read():
            ws = _open_worksheet()
            return ws.row_values(_HEADER_ROW)

        return await asyncio.to_thread(_read)
    except Exception as exc:
        logger.warning("Google Sheets read_structure: %s", exc)
        return list(FIELD_HEADERS)


async def read_all_rows() -> list[dict]:
    try:
        def _read():
            ws = _open_worksheet()
            _ensure_headers(ws)
            return ws.get_all_records(head=_HEADER_ROW)

        return await asyncio.to_thread(_read)
    except Exception as exc:
        logger.warning("Google Sheets read_all_rows: %s", exc)
        return []


def _extraer_fila(respuesta: dict) -> Optional[int]:
    """Fila realmente escrita, tomada del rango que devuelve la operación."""
    rango = (respuesta or {}).get("updates", {}).get("updatedRange", "")
    m = _RANGE_ROW_RE.search(rango)
    return int(m.group(1)) if m else None


async def append_actividad(form_data: dict) -> int:
    """
    Añade una fila con los 25 campos en el orden del contrato.

    Devuelve la fila realmente escrita, o -1 si falló. Antes devolvía
    ws.row_count, que es el total de filas del grid y se mostraba al usuario
    como si fuera la fila de su actividad.
    """
    def _write() -> int:
        ws = _open_worksheet()
        _ensure_headers(ws)
        row = [sanitizar_celda(form_data.get(k, "")) for k in FIELD_KEYS]
        respuesta = ws.append_row(row, value_input_option="USER_ENTERED")
        fila = _extraer_fila(respuesta)
        if fila is None:
            logger.warning(
                "No se pudo determinar la fila escrita a partir del rango devuelto."
            )
            return -1
        return fila

    try:
        fila = await asyncio.to_thread(_write)
        logger.info("Google Sheets: fila %s escrita", fila)
        return fila
    except Exception as exc:
        logger.warning("Google Sheets append_actividad: %s", exc)
        return -1
