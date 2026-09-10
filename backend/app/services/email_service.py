"""
email_service.py — Envío de resumen de actividad por correo HTML (SMTP/TLS).
Usa smtplib estándar de Python con STARTTLS en puerto 587.
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.domain.fields import FIELD_HEADERS, FIELD_KEYS

logger = logging.getLogger(__name__)

# ── Secciones para el correo ────────────────────────────────────────────────
_SECTIONS = [
    (
        "Bloque 1 — Identificación y Planeación Metodológica",
        FIELD_KEYS[:16],
    ),
    (
        "Bloque 2 — Informe de Ejecución",
        FIELD_KEYS[16:20],
    ),
    (
        "Bloque 3 — Evaluación y Análisis IA",
        FIELD_KEYS[20:],
    ),
]

_KEY_TO_HEADER = dict(zip(FIELD_KEYS, FIELD_HEADERS, strict=True))


# ── HTML builder ─────────────────────────────────────────────────────────────

def _build_html(
    form_data: dict,
    facilitador: str,
) -> str:
    nombre_actividad = form_data.get("nombre") or form_data.get("id_actividad") or "Actividad EPM"
    nombre_display = facilitador or "Facilitador/a"

    # Build section blocks
    sections_html = ""
    for section_title, keys in _SECTIONS:
        rows = ""
        for i, key in enumerate(keys):
            val = form_data.get(key) or "—"
            bg = "#1e2a1e" if i % 2 == 0 else "#182418"
            label = _KEY_TO_HEADER.get(key, key)
            rows += f"""
              <tr>
                <td style="padding:9px 14px;color:#7ecf7e;font-size:13px;
                           font-weight:600;width:42%;vertical-align:top;
                           background:{bg};border-bottom:1px solid #2a3d2a;">{label}</td>
                <td style="padding:9px 14px;color:#d4f0d4;font-size:13px;
                           vertical-align:top;background:{bg};
                           border-bottom:1px solid #2a3d2a;">{val}</td>
              </tr>"""

        sections_html += f"""
        <!-- section: {section_title} -->
        <tr>
          <td colspan="2" style="padding:18px 14px 6px;
                                  background:#0d1a0d;
                                  color:#4ade80;
                                  font-size:15px;
                                  font-weight:700;
                                  letter-spacing:.5px;
                                  border-top:2px solid #2a5c2a;">
            {section_title}
          </td>
        </tr>
        {rows}"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Consolidación Metodológica — {nombre_actividad}</title>
</head>
<body style="margin:0;padding:0;background:#0a120a;font-family:
             'Segoe UI',Arial,sans-serif;">

  <!-- wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#0a120a;padding:32px 0;">
    <tr><td align="center">
      <table width="640" cellpadding="0" cellspacing="0"
             style="background:#111b11;border-radius:12px;
                    border:1px solid #2a4a2a;overflow:hidden;
                    max-width:640px;width:100%;">

        <!-- ── HEADER ── -->
        <tr>
          <td style="background:linear-gradient(135deg,#0d2a0d 0%,#1a4a1a 100%);
                     padding:32px 36px;text-align:center;
                     border-bottom:2px solid #3a7a3a;">

            <!-- Logo EPM text badge -->
            <div style="display:inline-block;
                        background:#4ade80;
                        color:#0a120a;
                        font-size:26px;
                        font-weight:900;
                        letter-spacing:3px;
                        padding:6px 20px;
                        border-radius:6px;
                        margin-bottom:14px;">epm</div>

            <h1 style="margin:0 0 6px;color:#e0ffe0;font-size:20px;
                       font-weight:700;letter-spacing:.3px;">
              Consolidación Metodológica
            </h1>
            <p style="margin:0;color:#7ecf7e;font-size:13px;">
              Fundación Grupo EPM &nbsp;·&nbsp; Herramienta IA
            </p>
          </td>
        </tr>

        <!-- ── INTRO ── -->
        <tr>
          <td style="padding:24px 36px 0;color:#c8e8c8;font-size:14px;
                     line-height:1.6;">
            Hola <strong style="color:#4ade80;">{nombre_display}</strong>,<br/><br/>
            A continuación encontrarás el resumen de la actividad
            <strong style="color:#e0ffe0;">«{nombre_actividad}»</strong>
            que fue registrada exitosamente en el sistema de consolidación EPM
            de Google Sheets.
          </td>
        </tr>

        <!-- ── TABLE ── -->
        <tr>
          <td style="padding:20px 36px;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border-radius:8px;overflow:hidden;
                          border:1px solid #2a3d2a;">
              {sections_html}
            </table>
          </td>
        </tr>

        <!-- ── CTA ── -->
        <tr>
          <td style="padding:0 36px 28px;text-align:center;">
               style="display:inline-block;
                      background:linear-gradient(135deg,#16a34a,#4ade80);
                      color:#0a120a;
                      font-weight:700;
                      font-size:14px;
                      text-decoration:none;
                      padding:12px 28px;
                      border-radius:8px;
                      letter-spacing:.5px;">
              Ver en Google Sheets →
            </a>
          </td>
        </tr>

        <!-- ── FOOTER ── -->
        <tr>
          <td style="background:#0d1a0d;padding:18px 36px;
                     border-top:1px solid #2a3d2a;text-align:center;
                     color:#4a6a4a;font-size:11px;line-height:1.7;">
            Este mensaje fue generado automáticamente por el Asistente IA de
            <strong style="color:#5a8a5a;">Fundación Grupo EPM</strong>.<br/>
            Por favor no respondas a este correo.
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Send (blocking, runs in thread) ─────────────────────────────────────────

def _build_mime(to_email: str, form_data: dict, facilitador: str,
) -> MIMEMultipart:
    nombre_actividad = (
        form_data.get("nombre") or form_data.get("id_actividad") or "Actividad EPM"
    )
    html_body = _build_html(form_data, facilitador)
    plain = (
        f"Hola {facilitador},\n\n"
        f"La actividad '{nombre_actividad}' quedó consolidada.\n\n"
        "— Asistente IA Fundación Grupo EPM"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Consolidación EPM — {nombre_actividad}"
    msg["From"] = f"Asistente EPM <{settings.SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _send_sync(
    to_email: str,
    form_data: dict,
    facilitador: str,
) -> None:
    nombre_actividad = (
        form_data.get("nombre") or form_data.get("id_actividad") or "Actividad EPM"
    )
    msg = _build_mime(to_email, form_data, facilitador)

    last_exc: Exception | None = None

    # Try STARTTLS (port 587) first, then SSL (port 465) as fallback
    try:
        with smtplib.SMTP(settings.SMTP_HOST, 587, timeout=25) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
        logger.info("Email enviado (STARTTLS) a %s (actividad=%s)", to_email, nombre_actividad)
        return
    except Exception as exc:
        last_exc = exc
        logger.warning("STARTTLS falló (%s), intentando SSL 465…", exc)

    try:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, 465, timeout=25) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
        logger.info("Email enviado (SSL) a %s (actividad=%s)", to_email, nombre_actividad)
        return
    except Exception as exc:
        last_exc = exc
        logger.error("SSL también falló: %s", exc)

    raise RuntimeError(f"No se pudo enviar el correo: {last_exc}")


async def send_consolidation_email(
    to_email: str,
    form_data: dict,
    facilitador: str,
) -> None:
    """Async wrapper — runs SMTP in a thread pool so it doesn't block the event loop."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD no configurados en .env")
    await asyncio.to_thread(
        _send_sync, to_email, form_data, facilitador
    )
