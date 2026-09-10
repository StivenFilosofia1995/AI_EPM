"""
Fuente de verdad única de los 25 campos de la consolidación metodológica EPM.

CONTRATO INMUTABLE. El orden, las claves y los encabezados de este módulo son
los que ya usa el Excel institucional. No se modifican.

`excel_service` y `email_service` importan de aquí y no definen sus propias
listas. La prueba `tests/test_fields.py` falla si las
listas se desincronizan o si dejan de ser 25.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InputType(str, Enum):
    """Tipos de entrada admitidos por el motor de árbol y por el frontend."""

    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    TEXT = "text"
    TEXTAREA = "textarea"
    INTEGER = "integer"
    PERCENT = "percent"
    DATE = "date"
    DURATION = "duration"


@dataclass(frozen=True)
class Field:
    key: str
    header: str
    block: int
    input_type: InputType


# ─── Los 25 campos, en orden de contrato ────────────────────────────────────
# Bloque 1 = Identificación y diseño metodológico (16)
# Bloque 2 = Informe de ejecución (4)
# Bloque 3 = Evaluación (5)

FIELDS: tuple[Field, ...] = (
    # ── Bloque 1 ──
    Field("id_actividad", "ID Actividad", 1, InputType.TEXT),
    Field("programa", "Programa / Proyecto", 1, InputType.SINGLE_SELECT),
    Field("linea_accion", "Línea de Acción", 1, InputType.SINGLE_SELECT),
    Field("tipo_actividad", "Tipo de Actividad", 1, InputType.SINGLE_SELECT),
    Field("nombre", "Nombre de la Actividad", 1, InputType.TEXT),
    Field("publico", "Público", 1, InputType.SINGLE_SELECT),
    Field("publico_especifico", "Público Específico", 1, InputType.TEXTAREA),
    Field("lugar", "Lugar", 1, InputType.TEXT),
    Field("responsable", "Responsable", 1, InputType.TEXT),
    Field("duracion", "Duración Total Sesión", 1, InputType.DURATION),
    Field("pregunta_problematizadora", "Pregunta Problematizadora", 1, InputType.TEXTAREA),
    Field("ods", "ODS", 1, InputType.MULTI_SELECT),
    Field("metodologia", "Metodología", 1, InputType.TEXTAREA),
    Field("descripcion_sesion", "Descripción de la Sesión", 1, InputType.TEXTAREA),
    Field("recursos", "Recursos y/o Materiales", 1, InputType.TEXTAREA),
    Field("fecha", "Fecha", 1, InputType.DATE),
    # ── Bloque 2 ──
    Field("logros", "Logros", 2, InputType.TEXTAREA),
    Field("retos", "Retos / Dificultades", 2, InputType.TEXTAREA),
    Field("observaciones", "Observaciones a Destacar", 2, InputType.TEXTAREA),
    Field("comentarios", "Comentarios de Participantes", 2, InputType.TEXTAREA),
    # ── Bloque 3 ──
    Field("instrumento_evaluativo", "Instrumento Evaluativo", 3, InputType.SINGLE_SELECT),
    Field("participantes_evaluados", "# Participantes Evaluados", 3, InputType.INTEGER),
    Field("cumplimiento_objetivos", "Cumplimiento de Objetivos", 3, InputType.TEXTAREA),
    Field("acciones_mejora", "Acciones de Mejora", 3, InputType.TEXTAREA),
    Field("porcentaje_cumplimiento", "% Cumplimiento Evaluación", 3, InputType.PERCENT),
)

FIELD_KEYS: list[str] = [f.key for f in FIELDS]
FIELD_HEADERS: list[str] = [f.header for f in FIELDS]
FIELD_BLOCKS: dict[str, int] = {f.key: f.block for f in FIELDS}
FIELD_TYPES: dict[str, InputType] = {f.key: f.input_type for f in FIELDS}
FIELD_BY_KEY: dict[str, Field] = {f.key: f for f in FIELDS}

BLOCK_NAMES: dict[int, str] = {
    1: "Identificación y diseño metodológico",
    2: "Informe de ejecución",
    3: "Evaluación",
}

BLOCK_FIELD_COUNTS: dict[int, int] = {
    b: sum(1 for f in FIELDS if f.block == b) for b in (1, 2, 3)
}


# ─── Opciones cerradas confirmadas ──────────────────────────────────────────
# Estas listas están replicadas como CHECK en backend/sql/migrations/006.
# Si cambian aquí, deben cambiar allá.

PROGRAMAS: tuple[str, ...] = (
    "Biblioteca_EPM",
    "Programa_UVA",
    "Museo_del_Agua",
    "Parque_de_los_deseos",
)

LINEAS_ACCION: tuple[str, ...] = (
    "Educación",
    "Cultura",
    "Gestión Social",
    "Gestión ambiental",
)

TIPOS_ACTIVIDAD: tuple[str, ...] = (
    "Actividad de sensibilización",
    "Club",
    "Curso",
    "Itinerancia",
    "Semillero",
    "Taller",
)

PUBLICOS: tuple[str, ...] = (
    "Primera infancia",
    "Niños",
    "Adolescentes",
    "Jóvenes",
    "Adultos",
    "Adultos mayores",
)

# Los 17 Objetivos de Desarrollo Sostenible de Naciones Unidas.
ODS: tuple[str, ...] = (
    "1. Fin de la pobreza",
    "2. Hambre cero",
    "3. Salud y bienestar",
    "4. Educación de calidad",
    "5. Igualdad de género",
    "6. Agua limpia y saneamiento",
    "7. Energía asequible y no contaminante",
    "8. Trabajo decente y crecimiento económico",
    "9. Industria, innovación e infraestructura",
    "10. Reducción de las desigualdades",
    "11. Ciudades y comunidades sostenibles",
    "12. Producción y consumo responsables",
    "13. Acción por el clima",
    "14. Vida submarina",
    "15. Vida de ecosistemas terrestres",
    "16. Paz, justicia e instituciones sólidas",
    "17. Alianzas para lograr los objetivos",
)

# Separador de serialización para selección múltiple en Sheets y Excel.
MULTI_SEPARATOR = "; "

# Catálogos cerrados indexados por campo, para validación genérica.
CLOSED_OPTIONS: dict[str, tuple[str, ...]] = {
    "programa": PROGRAMAS,
    "linea_accion": LINEAS_ACCION,
    "tipo_actividad": TIPOS_ACTIVIDAD,
    "publico": PUBLICOS,
    "ods": ODS,
}

# TODO: `lugar` no tiene catálogo institucional confirmado. Se implementa como
# texto libre con autocompletado alimentado por los valores ya registrados en
# base de datos. Cuando la Fundación EPM entregue el catálogo oficial de
# espacios por programa, añadirlo aquí y añadir el CHECK en la migración 006.

# TODO: PROVISIONAL. Estos prefijos NO son institucionales: los definimos para
# poder proponerle al facilitador un código con sentido en vez de pedírselo en
# frío. Cuando la Fundación entregue la nomenclatura oficial, reemplazarlos.
PROGRAMA_PREFIJOS: dict[str, str] = {
    "Biblioteca_EPM": "BIB",
    "Programa_UVA": "UVA",
    "Museo_del_Agua": "MDA",
    "Parque_de_los_deseos": "PDD",
}
PREFIJO_POR_DEFECTO = "ACT"

# TODO: `id_actividad` no tiene patrón institucional confirmado. Se valida solo
# unicidad y longitud mínima (ver ID_ACTIVIDAD_MIN_LEN). Cuando se entregue el
# patrón real, añadir aquí la expresión regular y el CHECK correspondiente.
ID_ACTIVIDAD_MIN_LEN = 3


def serialize_multi(values: list[str]) -> str:
    """Serializa una selección múltiple para Sheets y Excel."""
    return MULTI_SEPARATOR.join(values)


def deserialize_multi(value: str) -> list[str]:
    """Inversa de serialize_multi. Tolera espacios sobrantes."""
    if not value:
        return []
    return [v.strip() for v in value.split(MULTI_SEPARATOR.strip()) if v.strip()]


def assert_contract() -> None:
    """
    Verifica el contrato de 25 campos. Se ejecuta al arrancar la aplicación
    para que una desincronización falle de inmediato y no en producción.
    """
    if len(FIELDS) != 25:
        raise ValueError(f"El contrato exige 25 campos, hay {len(FIELDS)}.")
    if len(FIELD_KEYS) != len(set(FIELD_KEYS)):
        raise ValueError("Hay claves de campo duplicadas en FIELDS.")
    if len(FIELD_HEADERS) != len(set(FIELD_HEADERS)):
        raise ValueError("Hay encabezados duplicados en FIELDS.")
    if BLOCK_FIELD_COUNTS != {1: 16, 2: 4, 3: 5}:
        raise ValueError(
            f"Distribución de bloques incorrecta: {BLOCK_FIELD_COUNTS}. "
            "Se esperaba {1: 16, 2: 4, 3: 5}."
        )
