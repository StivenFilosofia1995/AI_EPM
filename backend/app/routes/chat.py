from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.models.schemas import ChatMessage, ExcelDownloadRequest
from app.services.chat_service import (
    get_session_form_data,
    process_message_stream,
    update_form_field,
    extract_fields_from_history,
)
from app.services.excel_service import generate_excel
from app.services import supabase_service
from app.services.google_sheets_service import append_actividad, read_sheet_structure
from app.services.email_service import send_consolidation_email

router = APIRouter(prefix="/api", tags=["chat"])


# ── Chat ─────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(body: ChatMessage):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    return StreamingResponse(
        process_message_stream(body.session_id, body.message.strip(), user_name=body.user_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Form data ────────────────────────────────────────────────────────────────

class FormFieldBody(BaseModel):
    session_id: str
    field: str
    value: str


@router.post("/form/update")
async def form_update(body: FormFieldBody):
    """Update a single form field for a session."""
    update_form_field(body.session_id, body.field, body.value)
    return {"ok": True}


@router.get("/form/{session_id}")
async def form_get(session_id: str):
    """Return the current form data for a session."""
    return get_session_form_data(session_id)


# ── Excel download ────────────────────────────────────────────────────────────

@router.post("/excel/generate")
async def excel_generate(body: ExcelDownloadRequest):
    form_data = get_session_form_data(body.session_id)
    excel_bytes = generate_excel(form_data)
    return Response(
        content=excel_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                "attachment; filename=consolidacion_metodologica_epm.xlsx"
            )
        },
    )


# ── Google Sheets submit ──────────────────────────────────────────────────────

class SheetsSubmitBody(BaseModel):
    session_id: str


@router.post("/sheets/submit")
async def sheets_submit(body: SheetsSubmitBody):
    """Extract form fields from conversation, write to Google Sheets, persist to Supabase."""
    # Always extract from conversation history — this is the source of truth
    form_data = await extract_fields_from_history(body.session_id)

    if not form_data or not any(form_data.values()):
        raise HTTPException(
            status_code=400,
            detail="No se encontraron datos en la conversación para guardar. "
                   "Completa al menos el Bloque 1 antes de guardar.",
        )

    # Write to Google Sheets
    row_num = await append_actividad(form_data)
    if row_num == -1:
        raise HTTPException(
            status_code=502,
            detail="Error al escribir en Google Sheets. Verifica los permisos.",
        )

    # Persist to Supabase with the sheets row reference
    await supabase_service.save_actividad(
        body.session_id, {**form_data, "sheets_row": row_num}
    )

    from app.config import settings as _s
    return {
        "ok": True,
        "sheets_row": row_num,
        "fields_saved": sum(1 for v in form_data.values() if v),
        "sheets_url": (
            f"https://docs.google.com/spreadsheets/d/{_s.GOOGLE_SHEETS_ID}"
            f"/edit?gid=800700165#gid=800700165"
        ),
    }


@router.get("/sheets/structure")
async def sheets_structure():
    """Return the header row of the Google Sheet (for debugging / AI context)."""
    headers = await read_sheet_structure()
    return {"headers": headers}


# ── Session history ───────────────────────────────────────────────────────────

@router.get("/session/{session_id}/history")
async def session_history(session_id: str):
    """Return persisted message history for a session."""
    messages = await supabase_service.load_history(session_id)
    return {"session_id": session_id, "messages": messages}


# ── Email send ────────────────────────────────────────────────────────────────

class EmailSendBody(BaseModel):
    session_id: str
    to_email: str
    facilitador: str = ""
    sheets_url: str = ""
    sheets_row: int = 0


@router.post("/email/send")
async def email_send(body: EmailSendBody):
    """Extract form data from conversation and send HTML summary to facilitator."""
    import re
    # Basic email validation
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", body.to_email):
        raise HTTPException(status_code=422, detail="Dirección de correo inválida.")

    form_data = await extract_fields_from_history(body.session_id)
    if not form_data or not any(form_data.values()):
        raise HTTPException(
            status_code=400,
            detail="No hay datos de actividad para enviar. Completa la consolidación primero.",
        )

    # If caller didn't provide a sheets_url, build it from settings
    from app.config import settings as _s
    sheets_url = body.sheets_url or (
        f"https://docs.google.com/spreadsheets/d/{_s.GOOGLE_SHEETS_ID}"
        f"/edit?gid=800700165#gid=800700165"
    )

    try:
        await send_consolidation_email(
            to_email=body.to_email,
            form_data=form_data,
            facilitador=body.facilitador,
            sheets_url=sheets_url,
            sheets_row=body.sheets_row,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error al enviar el correo: {exc}",
        )

    return {"ok": True, "to": body.to_email}

