"""
Convierte el logotipo institucional a base64 y regenera static/js/logo.js.

El logo va incrustado en base64 para que no dependa de ninguna petición
externa: se ve igual sin conexión y no se puede romper por una ruta mal
resuelta.

Uso, desde el directorio backend/:

    # Regenerar con el archivo actual
    python scripts/generar_logo_base64.py

    # Sustituir por el archivo oficial de marca
    python scripts/generar_logo_base64.py ruta/al/logo-oficial.svg
    python scripts/generar_logo_base64.py ruta/al/logo-oficial.png

Admite SVG, PNG, JPG y WEBP.
"""

from __future__ import annotations

import base64
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DESTINO_ASSET = BACKEND / "static" / "assets" / "logo-fundacion-epm.svg"
DESTINO_JS = BACKEND / "static" / "js" / "logo.js"

TIPOS = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

PLANTILLA = '''/* ─────────────────────────────────────────────
   Logotipo institucional — Fundación Grupo EPM

   ARCHIVO GENERADO. No lo edites a mano.
   Regenera con:  python scripts/generar_logo_base64.py [archivo]

   Va en base64 a propósito: sin petición externa, sin ruta que se pueda
   romper, idéntico sin conexión.
───────────────────────────────────────────── */

'use strict';

const LOGO_EPM = '{data_uri}';

/** Inserta el logo en todos los elementos con [data-logo-epm]. */
function pintarLogos() {{
  for (const nodo of document.querySelectorAll('[data-logo-epm]')) {{
    const img = document.createElement('img');
    img.src = LOGO_EPM;
    img.alt = 'Fundación Grupo EPM';
    img.className = 'logo-epm';
    const alto = nodo.getAttribute('data-logo-epm');
    if (alto) img.style.height = alto;
    nodo.replaceChildren(img);
  }}
}}

if (document.readyState === 'loading') {{
  document.addEventListener('DOMContentLoaded', pintarLogos);
}} else {{
  pintarLogos();
}}
'''


def main() -> int:
    if len(sys.argv) > 1:
        origen = Path(sys.argv[1]).expanduser().resolve()
        if not origen.exists():
            print(f"Error: no existe {origen}")
            return 1
        if origen.suffix.lower() not in TIPOS:
            print(f"Error: extensión no admitida ({origen.suffix}). "
                  f"Admitidas: {', '.join(sorted(TIPOS))}")
            return 1
        # Conserva una copia del oficial junto a los demás recursos.
        copia = DESTINO_ASSET.with_suffix(origen.suffix.lower())
        if copia.resolve() != origen:
            shutil.copyfile(origen, copia)
        fuente = copia
    else:
        fuente = DESTINO_ASSET
        if not fuente.exists():
            print(f"Error: no existe {fuente}")
            return 1

    mime = TIPOS[fuente.suffix.lower()]
    datos = base64.b64encode(fuente.read_bytes()).decode("ascii")
    data_uri = f"data:{mime};base64,{datos}"

    DESTINO_JS.write_text(PLANTILLA.format(data_uri=data_uri), encoding="utf-8")

    print(f"Origen : {fuente.relative_to(BACKEND)}")
    print(f"Tipo   : {mime}")
    print(f"Tamaño : {len(datos) / 1024:.1f} KB en base64")
    print(f"Escrito: {DESTINO_JS.relative_to(BACKEND)}")
    if len(datos) > 300_000:
        print("Aviso: el archivo supera los 300 KB en base64. Considera "
              "optimizarlo para que la página no cargue lento.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
