import asyncio
import json
import logging
import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Ordered list of field keys — matches the Excel / Google Sheet column order
FIELD_KEYS = [
    "id_actividad",
    "programa",
    "linea_accion",
    "tipo_actividad",
    "nombre",
    "publico",
    "publico_especifico",
    "lugar",
    "responsable",
    "duracion",
    "pregunta_problematizadora",
    "ods",
    "metodologia",
    "descripcion_sesion",
    "recursos",
    "fecha",
    "logros",
    "retos",
    "observaciones",
    "comentarios",
    "instrumento_evaluativo",
    "participantes_evaluados",
    "cumplimiento_objetivos",
    "acciones_mejora",
    "porcentaje_cumplimiento",
]

# Human-readable headers (one-to-one with FIELD_KEYS)
FIELD_HEADERS = [
    "ID Actividad",
    "Programa / Proyecto",
    "Línea de Acción",
    "Tipo de Actividad",
    "Nombre de la Actividad",
    "Público",
    "Público Específico",
    "Lugar",
    "Responsable",
    "Duración Total Sesión",
    "Pregunta Problematizadora",
    "ODS",
    "Metodología",
    "Descripción de la Sesión",
    "Recursos y/o Materiales",
    "Fecha",
    "Logros",
    "Retos / Dificultades",
    "Observaciones a Destacar",
    "Comentarios de Participantes",
    "Instrumento Evaluativo",
    "# Participantes Evaluados",
    "Cumplimiento de Objetivos",
    "Acciones de Mejora",
    "% Cumplimiento Evaluación",
]


def _build_credentials() -> Credentials:
    """Build Google credentials from JSON string (Railway) or file (local)."""
    json_str = settings.GOOGLE_CREDENTIALS_JSON
    if json_str:
        info = json.loads(json_str)
        return Credentials.from_service_account_info(info, scopes=_SCOPES)

    path = settings.SERVICE_ACCOUNT_FILE
    if not os.path.isabs(path):
        # Resolve relative to backend root (parent of app/)
        path = os.path.join(os.path.dirname(__file__), "..", "..", path)
    return Credentials.from_service_account_file(path, scopes=_SCOPES)


def _open_worksheet() -> gspread.Worksheet:
    """Return the target worksheet (sync — run inside asyncio.to_thread)."""
    creds = _build_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(settings.GOOGLE_SHEETS_ID)
    gid = int(settings.GOOGLE_SHEETS_GID)
    try:
        ws = sh.get_worksheet_by_id(gid)
    except Exception:
        ws = sh.sheet1
    return ws


# The real sheet has notes in rows 1-3; column headers live in row 4.
_HEADER_ROW = 4

def _ensure_headers(ws: gspread.Worksheet) -> None:
    """Write headers in row 4 if that row is empty (first-time setup)."""
    header_row = ws.row_values(_HEADER_ROW)
    if not any(header_row):
        ws.insert_row(FIELD_HEADERS, index=_HEADER_ROW)


# ─── Public async API ────────────────────────────────────────────────────────

async def read_sheet_structure() -> list[str]:
    """Return the header row of the target sheet."""
    try:
        def _read():
            ws = _open_worksheet()
            return ws.row_values(_HEADER_ROW)

        headers = await asyncio.to_thread(_read)
        return headers
    except Exception as exc:
        logger.warning("Google Sheets read_structure: %s", exc)
        return FIELD_HEADERS


async def read_all_rows() -> list[dict]:
    """Return all data rows as list of dicts keyed by header."""
    try:
        def _read():
            ws = _open_worksheet()
            _ensure_headers(ws)
            return ws.get_all_records(head=_HEADER_ROW)

        rows = await asyncio.to_thread(_read)
        return rows
    except Exception as exc:
        logger.warning("Google Sheets read_all_rows: %s", exc)
        return []


async def append_actividad(form_data: dict) -> int:
    """
    Append a new row to the Google Sheet.
    Returns the row index written (1-based), or -1 on failure.
    """
    def _write():
        ws = _open_worksheet()
        _ensure_headers(ws)
        row = [str(form_data.get(k, "") or "") for k in FIELD_KEYS]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return ws.row_count

    try:
        row_num = await asyncio.to_thread(_write)
        logger.info("Google Sheets: row appended (%s)", row_num)
        return row_num
    except Exception as exc:
        logger.warning("Google Sheets append_actividad: %s", exc)
        return -1
