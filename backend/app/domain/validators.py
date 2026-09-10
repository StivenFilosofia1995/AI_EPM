"""
Validación estructurada de respuestas.

Los errores se devuelven como estructura ({field_key, code, message}), nunca
como texto libre, para que el frontend pueda mostrarlos junto al campo y las
pruebas puedan afirmar sobre el código y no sobre la redacción.

Las validaciones que necesitan consultar la base de datos (unicidad de
id_actividad) no viven aquí: las aplica el motor, que sí tiene acceso al
repositorio.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.domain.fields import ID_ACTIVIDAD_MIN_LEN, InputType
from app.domain.tree_loader import Node


class AnswerError(BaseModel):
    field_key: str | None
    code: str
    message: str


class ValidationResult(BaseModel):
    ok: bool
    value: Any = None
    errors: list[AnswerError] = []


_DURATION_RE = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*(hora|horas|h|minuto|minutos|min|m)\b.*$",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _err(node: Node, code: str, message: str) -> AnswerError:
    target = node.field_key or (node.compose.target if node.compose else None)
    return AnswerError(field_key=target, code=code, message=message)


def validate_answer(
    node: Node,
    value: Any,
    answers: dict[str, Any] | None = None,
) -> ValidationResult:
    """
    Valida y normaliza el valor de un nodo.

    Devuelve el valor ya normalizado (entero como int, selección múltiple como
    lista, texto con espacios recortados) para que el motor persista siempre
    la misma forma.
    """
    answers = answers or {}
    errors: list[AnswerError] = []

    # ─── Obligatoriedad ─────────────────────────────────────────────────────
    empty = value is None or (isinstance(value, str) and not value.strip()) or (
        isinstance(value, list) and not value
    )
    if empty:
        if node.required:
            return ValidationResult(
                ok=False,
                errors=[_err(node, "requerido", "Este campo es obligatorio.")],
            )
        return ValidationResult(ok=True, value=None)

    it = node.input_type
    normalized: Any = value

    # ─── Normalización por tipo ─────────────────────────────────────────────
    if it in (InputType.TEXT, InputType.TEXTAREA, InputType.DURATION):
        normalized = str(value).strip()

    elif it == InputType.SINGLE_SELECT:
        normalized = str(value).strip()

    elif it == InputType.MULTI_SELECT:
        if not isinstance(value, list):
            return ValidationResult(
                ok=False,
                errors=[_err(node, "tipo_invalido",
                             "Se esperaba una lista de opciones seleccionadas.")],
            )
        normalized = [str(v).strip() for v in value if str(v).strip()]

    elif it in (InputType.INTEGER, InputType.PERCENT):
        try:
            normalized = int(str(value).strip())
        except (TypeError, ValueError):
            return ValidationResult(
                ok=False,
                errors=[_err(node, "no_entero", "Debe ser un número entero.")],
            )

    elif it == InputType.DATE:
        raw = str(value).strip()
        if not _DATE_RE.match(raw):
            return ValidationResult(
                ok=False,
                errors=[_err(node, "fecha_invalida",
                             "La fecha debe tener el formato AAAA-MM-DD.")],
            )
        try:
            date.fromisoformat(raw)
        except ValueError:
            return ValidationResult(
                ok=False,
                errors=[_err(node, "fecha_invalida", "La fecha no existe en el calendario.")],
            )
        normalized = raw

    # ─── Porcentaje: rango duro, independiente de las validaciones del YAML ──
    if it == InputType.PERCENT and not (0 <= normalized <= 100):
        errors.append(
            _err(node, "fuera_de_rango", "El porcentaje debe estar entre 0 y 100.")
        )

    # ─── Opciones cerradas ──────────────────────────────────────────────────
    valid_values = {o.value for o in node.resolved_options}
    if valid_values:
        if it == InputType.MULTI_SELECT:
            invalid = [v for v in normalized if v not in valid_values]
            if invalid:
                errors.append(
                    _err(node, "opcion_invalida",
                         f"Estas opciones no son válidas: {', '.join(invalid)}.")
                )
        elif it == InputType.SINGLE_SELECT and normalized not in valid_values:
            errors.append(
                _err(node, "opcion_invalida",
                     "Debes elegir una de las opciones disponibles.")
            )

    # ─── Validaciones declaradas en el YAML ─────────────────────────────────
    for v in node.validations:
        code = v.type

        if code == "min_length" and len(str(normalized)) < int(v.value):
            errors.append(_err(node, "muy_corto",
                               f"Debe tener al menos {v.value} caracteres."))

        elif code == "min_value" and isinstance(normalized, int) and normalized < int(v.value):
            errors.append(_err(node, "muy_pequeno",
                               f"El valor mínimo es {v.value}."))

        elif code == "max_value" and isinstance(normalized, int) and normalized > int(v.value):
            errors.append(_err(node, "muy_grande",
                               f"El valor máximo es {v.value}."))

        elif code == "min_selected" and isinstance(normalized, list) and len(normalized) < int(v.value):
            errors.append(_err(node, "seleccion_insuficiente",
                               f"Debes seleccionar al menos {v.value} opción."))

        elif code == "duration_format" and not _DURATION_RE.match(str(normalized)):
            errors.append(_err(node, "duracion_invalida",
                               "Indica la duración en horas o minutos. "
                               "Por ejemplo: 2 horas, 90 minutos."))

        elif code == "unique_id_actividad":
            # La verifica el motor contra la base de datos. Aquí solo el mínimo.
            if len(str(normalized)) < ID_ACTIVIDAD_MIN_LEN:
                errors.append(_err(node, "muy_corto",
                                   f"El identificador debe tener al menos "
                                   f"{ID_ACTIVIDAD_MIN_LEN} caracteres."))

        elif code == "not_greater_than_node":
            other = answers.get(v.node)
            if other is not None and isinstance(normalized, int):
                try:
                    limit = int(other)
                except (TypeError, ValueError):
                    limit = None
                if limit is not None and normalized > limit:
                    errors.append(
                        _err(node, "excede_total",
                             f"No puede superar el total de participantes ({limit}).")
                    )

    if errors:
        return ValidationResult(ok=False, errors=errors)
    return ValidationResult(ok=True, value=normalized)
