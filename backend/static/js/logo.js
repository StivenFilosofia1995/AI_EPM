/* ─────────────────────────────────────────────
   Logotipo institucional — Fundación Grupo EPM

   ARCHIVO GENERADO. No lo edites a mano.
   Regenera con:  python scripts/generar_logo_base64.py [archivo]

   Va en base64 a propósito: sin petición externa, sin ruta que se pueda
   romper, idéntico sin conexión.
───────────────────────────────────────────── */

'use strict';

const LOGO_EPM = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyMTAgNjAiIHdpZHRoPSIyMTAiIGhlaWdodD0iNjAiCiAgICAgcm9sZT0iaW1nIiBhcmlhLWxhYmVsPSJGdW5kYWNpw7NuIEdydXBvIEVQTSI+CiAgPHRpdGxlPkZ1bmRhY2nDs24gR3J1cG8gRVBNPC90aXRsZT4KICA8IS0tCiAgICBSZWNvbnN0cnVjY2nDs24gdGlwb2dyw6FmaWNhIGRlbCBsb2dvdGlwbyBpbnN0aXR1Y2lvbmFsLCBwZW5zYWRhIHBhcmEgZm9uZG8KICAgIG9zY3Vyby4gTk8gZXMgZWwgYXJjaGl2byBvZmljaWFsIGRlIG1hcmNhLgoKICAgIEN1YW5kbyB0ZW5nYXMgZWwgU1ZHIG8gUE5HIG9maWNpYWwgZGUgbGEgRnVuZGFjacOzbiBHcnVwbyBFUE0sIHN1c3RpdMO6eWVsbwogICAgY29uOiAgcHl0aG9uIHNjcmlwdHMvZ2VuZXJhcl9sb2dvX2Jhc2U2NC5weSBydXRhL2FsL2xvZ28tb2ZpY2lhbC5zdmcKICAgIEVzbyByZWdlbmVyYSBzdGF0aWMvanMvbG9nby5qcyB5IGVsIGxvZ28gY2FtYmlhIGVuIGxhcyBkb3MgdmlzdGFzLgogIC0tPgogIDxnIGZvbnQtZmFtaWx5PSInSW50ZXInLCAnU2Vnb2UgVUknLCBBcmlhbCwgSGVsdmV0aWNhLCBzYW5zLXNlcmlmIiBmb250LXNpemU9IjIzIj4KICAgIDx0ZXh0IHg9IjAiIHk9IjI0IiBmaWxsPSIjRDVEN0UwIiBmb250LXdlaWdodD0iNDAwIiBsZXR0ZXItc3BhY2luZz0iLTAuNCI+RnVuZGFjacOzbjwvdGV4dD4KICAgIDx0ZXh0IHg9IjAiIHk9IjUxIiBmaWxsPSIjRDVEN0UwIiBmb250LXdlaWdodD0iNDAwIiBsZXR0ZXItc3BhY2luZz0iLTAuNCI+R3J1cG88L3RleHQ+CiAgICA8Y2lyY2xlIGN4PSI3OCIgY3k9IjQzLjUiIHI9IjQuNiIgZmlsbD0iIzAwQTY1MCIvPgogICAgPHRleHQgeD0iODgiIHk9IjUxIiBmaWxsPSIjMDBBNjUwIiBmb250LXdlaWdodD0iNzAwIiBsZXR0ZXItc3BhY2luZz0iLTAuNiI+ZXBtPC90ZXh0PgogIDwvZz4KPC9zdmc+Cg==';

/** Inserta el logo en todos los elementos con [data-logo-epm]. */
function pintarLogos() {
  for (const nodo of document.querySelectorAll('[data-logo-epm]')) {
    const img = document.createElement('img');
    img.src = LOGO_EPM;
    img.alt = 'Fundación Grupo EPM';
    img.className = 'logo-epm';
    const alto = nodo.getAttribute('data-logo-epm');
    if (alto) img.style.height = alto;
    nodo.replaceChildren(img);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', pintarLogos);
} else {
  pintarLogos();
}
