"""
Genera sql/esquema_completo.sql concatenando las migraciones en orden.

El archivo resultante es para pegar de una sola vez en el SQL Editor de
Supabase. Las migraciones numeradas siguen siendo la fuente de verdad: este
script solo las junta.

Uso, desde el directorio backend/:

    python sql/generar_esquema_completo.py
"""

from __future__ import annotations

from pathlib import Path

SQL_DIR = Path(__file__).parent
MIGRACIONES = SQL_DIR / "migrations"
SALIDA = SQL_DIR / "esquema_completo.sql"

CABECERA = """-- ═══════════════════════════════════════════════════════════════════════════
-- EPM — Consolidación Metodológica
-- ESQUEMA COMPLETO — script único para Supabase
-- ═══════════════════════════════════════════════════════════════════════════
--
-- CÓMO USARLO
--   1. Abre Supabase Dashboard → SQL Editor → New query
--   2. Pega TODO este archivo
--   3. Run
--
-- Es idempotente: puedes ejecutarlo varias veces sin error. Va dentro de una
-- transacción, así que si algo falla no queda el esquema a medias.
--
-- ARCHIVO GENERADO. No lo edites a mano: es la concatenación de los archivos
-- de migrations/ en orden. Para cambiar algo, edita la migración que
-- corresponda y regenera con:  python sql/generar_esquema_completo.py
--
-- Crea 9 tablas y 5 vistas:
--   epm_sessions, epm_messages, epm_actividades, epm_users,
--   epm_tree_versions, epm_tree_nodes, epm_respuestas,
--   epm_respuestas_historial, epm_analisis_ia
--   v_actividades_completas, v_actividades_export, v_avance_por_usuario,
--   v_campos_problematicos, v_uso_sugerencias
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;
"""

PIE = """

COMMIT;

-- ═══════════════════════════════════════════════════════════════════════════
-- VERIFICACIÓN — ejecuta esto después, en una consulta aparte
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Deben aparecer 9 tablas:
--   SELECT table_name FROM information_schema.tables
--    WHERE table_schema = 'public' AND table_name LIKE 'epm_%' ORDER BY 1;
--
-- Deben aparecer 5 vistas:
--   SELECT table_name FROM information_schema.views
--    WHERE table_schema = 'public' AND table_name LIKE 'v_%' ORDER BY 1;
--
-- rowsecurity debe ser true en las 9:
--   SELECT tablename, rowsecurity FROM pg_tables
--    WHERE schemaname = 'public' AND tablename LIKE 'epm_%' ORDER BY 1;
--
-- SIGUIENTE PASO: crear la primera cuenta de administrador. NO se hace con
-- SQL a propósito: el hash Argon2id lo genera el backend.
--   cd backend && python -m scripts.crear_admin
-- ═══════════════════════════════════════════════════════════════════════════
"""


def generar() -> Path:
    migraciones = sorted(MIGRACIONES.glob("0*.sql"))
    if not migraciones:
        raise SystemExit(f"No se encontraron migraciones en {MIGRACIONES}")

    partes = [CABECERA]
    for m in migraciones:
        partes.append(
            "\n\n-- #########################################################"
            "##################\n"
            f"-- ##  {m.name}\n"
            "-- #########################################################"
            "##################\n\n"
            + m.read_text(encoding="utf-8").rstrip()
        )
    partes.append(PIE)

    SALIDA.write_text("".join(partes), encoding="utf-8")
    return SALIDA


if __name__ == "__main__":
    salida = generar()
    lineas = len(salida.read_text(encoding="utf-8").splitlines())
    print(f"Generado {salida.name}: {lineas} líneas")
