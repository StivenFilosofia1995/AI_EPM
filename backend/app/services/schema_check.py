"""
Verificación del esquema al arrancar.

Existe porque el síntoma de una migración sin aplicar era un error 500 sin
explicación en mitad de un formulario. El esquema evoluciona con el código,
y quien despliega necesita enterarse en el arranque —no cuando un facilitador
intenta registrarse— de que falta ejecutar una migración.

No bloquea el arranque: registra qué falta y qué archivo lo corrige.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.db import get_client, modo_demostracion

logger = logging.getLogger(__name__)

# Columnas que el código escribe o lee, y la migración que las crea.
# Al añadir una migración que toque estas tablas, actualiza este mapa.
REQUISITOS: dict[str, dict[str, str]] = {
    "epm_users": {
        "password_hash": "002_usuarios.sql",
        "cargo": "010_perfil_y_registro.sql",
        "lineas_accion": "010_perfil_y_registro.sql",
        "temas": "010_perfil_y_registro.sql",
        "telefono": "010_perfil_y_registro.sql",
        "auto_registrado": "010_perfil_y_registro.sql",
    },
    "epm_respuestas": {
        "node_id": "004_respuestas.sql",
        "stale": "004_respuestas.sql",
        "origen": "009_origen_y_estimado.sql",
    },
    "epm_sessions": {
        "estado": "005_estado_y_analisis.sql",
        "current_node_id": "005_estado_y_analisis.sql",
        "user_id": "002_usuarios.sql",
    },
}


class EsquemaDesactualizado(RuntimeError):
    """Falta ejecutar una o más migraciones."""


async def _columnas_faltantes(tabla: str, columnas: dict[str, str]) -> list[str]:
    """
    Pregunta por las columnas concretas. PostgREST responde con un error que
    nombra la columna inexistente, así que basta con pedirlas todas de una vez
    y, si falla, ir una por una para saber cuál es.
    """
    client = get_client()

    def _pedir(cols: str):
        return client.table(tabla).select(cols).limit(1).execute()

    try:
        await asyncio.to_thread(_pedir, ",".join(columnas))
        return []
    except Exception:
        pass

    faltantes = []
    for columna in columnas:
        try:
            await asyncio.to_thread(_pedir, columna)
        except Exception:
            faltantes.append(columna)
    return faltantes


async def verificar_esquema() -> dict[str, list[str]]:
    """
    Devuelve {tabla: [columnas faltantes]}. Vacío si todo está al día.
    En modo demostración no aplica: el almacenamiento no tiene esquema.
    """
    if modo_demostracion():
        return {}

    problemas: dict[str, list[str]] = {}
    for tabla, columnas in REQUISITOS.items():
        try:
            faltantes = await _columnas_faltantes(tabla, columnas)
        except Exception as exc:
            logger.error("No se pudo verificar la tabla %s: %s", tabla, exc)
            continue
        if faltantes:
            problemas[tabla] = faltantes
    return problemas


def migraciones_pendientes(problemas: dict[str, list[str]]) -> list[str]:
    """Archivos de migración que hay que ejecutar, en orden."""
    archivos = set()
    for tabla, columnas in problemas.items():
        for columna in columnas:
            archivo = REQUISITOS.get(tabla, {}).get(columna)
            if archivo:
                archivos.add(archivo)
    return sorted(archivos)


async def avisar_si_falta_esquema() -> dict[str, list[str]]:
    """Verifica y deja constancia en los registros. No interrumpe el arranque."""
    problemas = await verificar_esquema()
    if not problemas:
        return {}

    pendientes = migraciones_pendientes(problemas)
    linea = "=" * 68
    logger.error("\n%s", linea)
    logger.error("  LA BASE DE DATOS ESTÁ DESACTUALIZADA")
    logger.error("%s", linea)
    for tabla, columnas in problemas.items():
        logger.error("  %s: faltan %s", tabla, ", ".join(columnas))
    logger.error("")
    logger.error("  Ejecuta en el SQL Editor de Supabase, en orden:")
    for archivo in pendientes:
        logger.error("      backend/sql/migrations/%s", archivo)
    logger.error("")
    logger.error("  O vuelve a pegar backend/sql/esquema_completo.sql entero:")
    logger.error("  es idempotente y deja el esquema al día.")
    logger.error("%s\n", linea)
    return problemas
