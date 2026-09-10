"""
Motor determinista del árbol de decisiones.

Sin ninguna dependencia de Anthropic. El modelo de lenguaje NO interviene en
la captura: si este módulo necesitara al modelo para avanzar una pregunta, el
diseño estaría mal.

El estado de avance se lee siempre de Supabase. La ruta se recalcula desde las
respuestas guardadas en cada operación, de modo que el sistema sobrevive un
reinicio y funciona con varias réplicas sin estado compartido en memoria.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.domain import fields as F
from app.domain.tree_loader import Node, Tree, get_tree
from app.domain.validators import AnswerError, validate_answer
from app.services import tree_repository as repo

logger = logging.getLogger(__name__)

COMPOSE_SEPARATOR = "\n"
MAX_WALK = 500


class EngineError(Exception):
    """Error de uso del motor (nodo inexistente, sesión ajena, etc.)."""


class ValidationFailed(Exception):
    def __init__(self, errors: list[AnswerError]):
        self.errors = errors
        super().__init__("La respuesta no pasó la validación.")


# ─── Lectura del estado ─────────────────────────────────────────────────────


def _typed(node: Node, row: dict) -> Any:
    """Devuelve el valor de una fila de epm_respuestas con su tipo real."""
    if node.input_type == F.InputType.MULTI_SELECT:
        vj = row.get("valor_json")
        if isinstance(vj, list):
            return vj
        return F.deserialize_multi(row.get("valor") or "")
    if node.input_type in (F.InputType.INTEGER, F.InputType.PERCENT):
        try:
            return int(row.get("valor") or 0)
        except (TypeError, ValueError):
            return None
    return row.get("valor")


def _answers(tree: Tree, rows: list[dict]) -> dict[str, Any]:
    """Mapa node_id -> valor tipado, considerando solo respuestas vigentes."""
    out: dict[str, Any] = {}
    for row in rows:
        node_id = row.get("node_id")
        if not node_id or node_id not in tree.by_id:
            continue
        if row.get("stale") or not row.get("es_valida", True):
            continue
        out[node_id] = _typed(tree.node(node_id), row)
    return out


def compute_route(tree: Tree, answers: dict[str, Any]) -> list[str]:
    """
    Ruta recorrida hasta ahora. Termina en el primer nodo sin responder
    (el nodo actual) o en un nodo terminal.
    """
    route: list[str] = []
    seen: set[str] = set()
    node_id: str | None = tree.root

    while node_id and len(route) < MAX_WALK:
        if node_id in seen:
            break
        seen.add(node_id)
        route.append(node_id)

        node = tree.node(node_id)
        if node.terminal:
            break
        if node_id not in answers:
            break
        node_id = node.resolve_next(answers)

    return route


def project_full_path(tree: Tree, answers: dict[str, Any]) -> list[str]:
    """
    Ruta completa estimada: sigue las respuestas donde existen y default_next
    donde todavía no. Sirve para calcular el progreso sobre los campos
    realmente alcanzables, no sobre un 25 fijo.
    """
    path: list[str] = []
    seen: set[str] = set()
    node_id: str | None = tree.root

    while node_id and len(path) < MAX_WALK:
        if node_id in seen:
            break
        seen.add(node_id)
        path.append(node_id)

        node = tree.node(node_id)
        if node.terminal:
            break

        # resolve_next se llama SIEMPRE, también en nodos sin responder: las
        # condiciones next_when dependen de las respuestas de OTROS nodos
        # (por ejemplo, la etapa declarada al inicio decide si el resumen del
        # bloque 1 cierra la sesión o continúa al bloque 2). Usar default_next
        # aquí proyectaba los bloques 2 y 3 en sesiones de solo planeación, e
        # inflaba el denominador del progreso.
        node_id = node.resolve_next(answers)

    return path


def _field_nodes(tree: Tree, path: list[str]) -> list[str]:
    """Nodos de la ruta que producen o componen alguno de los 25 campos."""
    return [
        n for n in path
        if tree.node(n).field_key or tree.node(n).compose
    ]


def compute_progress(tree: Tree, answers: dict[str, Any]) -> dict:
    path = project_full_path(tree, answers)
    total_nodes = _field_nodes(tree, path)
    answered = [n for n in total_nodes if n in answers]

    por_bloque: dict[int, dict[str, int]] = {}
    for n in total_nodes:
        b = tree.node(n).block or 0
        slot = por_bloque.setdefault(b, {"total": 0, "respondidos": 0})
        slot["total"] += 1
        if n in answers:
            slot["respondidos"] += 1

    total = len(total_nodes)
    return {
        "respondidos": len(answered),
        "total": total,
        "porcentaje": round(len(answered) * 100 / total, 1) if total else 0.0,
        "por_bloque": [
            {
                "bloque": b,
                "nombre": F.BLOCK_NAMES.get(b, ""),
                "respondidos": v["respondidos"],
                "total": v["total"],
            }
            for b, v in sorted(por_bloque.items())
        ],
    }


# ─── Serialización de un nodo para el frontend ──────────────────────────────


async def _node_payload(
    tree: Tree,
    node: Node,
    answers: dict[str, Any],
    previous_value: Any = None,
) -> dict:
    options = [
        {"value": o.value, "help": o.help} for o in node.resolved_options
    ]

    autocomplete: list[str] = []
    if node.autocomplete_from:
        try:
            autocomplete = await repo.valores_distintos(node.autocomplete_from)
        except Exception as exc:  # el autocompletado nunca debe bloquear
            logger.warning("Autocompletado no disponible para %s: %s", node.node_id, exc)

    resumen = None
    if node.summary_fields:
        compuesto = compose_fields(tree, answers)
        resumen = [
            {
                "field_key": fk,
                "header": F.FIELD_BY_KEY[fk].header,
                "valor": compuesto.get(fk) or "",
            }
            for fk in node.summary_fields
        ]

    return {
        "node_id": node.node_id,
        "kind": node.kind,
        "label": node.label,
        "help": node.help_for(answers),
        "input_type": node.input_type.value,
        "required": node.required,
        "terminal": node.terminal,
        "block": node.block,
        "block_name": F.BLOCK_NAMES.get(node.block or 0, ""),
        "field_key": node.field_key or (node.compose.target if node.compose else None),
        "options": options,
        "autocomplete": autocomplete,
        "resumen": resumen,
        "previous_value": previous_value,
    }


# ─── Composición de los 25 campos ───────────────────────────────────────────


def compose_fields(tree: Tree, answers: dict[str, Any]) -> dict[str, Any]:
    """
    Ensambla los 25 campos a partir de las respuestas vigentes.

    Los campos compuestos (descripcion_sesion, publico_especifico,
    acciones_mejora) se arman concatenando las contribuciones en el orden
    declarado por compose.order, cada una con su prefijo legible.
    """
    directos: dict[str, Any] = {}
    partes: dict[str, list[tuple[int, str]]] = {}

    for node_id, value in answers.items():
        node = tree.by_id.get(node_id)
        if node is None or value is None:
            continue

        if node.field_key:
            if node.input_type == F.InputType.MULTI_SELECT and isinstance(value, list):
                directos[node.field_key] = F.serialize_multi(value)
            else:
                directos[node.field_key] = value

        elif node.compose:
            texto = (
                F.serialize_multi(value) if isinstance(value, list) else str(value)
            )
            partes.setdefault(node.compose.target, []).append(
                (node.compose.order, f"{node.compose.prefix}{texto}")
            )

    for target, items in partes.items():
        items.sort(key=lambda x: x[0])
        directos[target] = COMPOSE_SEPARATOR.join(t for _, t in items)

    return {k: directos.get(k) for k in F.FIELD_KEYS}


# ─── Operaciones públicas ───────────────────────────────────────────────────


async def start_session(session_id: str, user_id: str, user_name: str) -> dict:
    tree = get_tree()
    root = tree.node(tree.root)
    await repo.create_session(
        session_id=session_id,
        user_id=user_id,
        user_name=user_name,
        tree_version=tree.version,
        current_node_id=tree.root,
    )
    return {
        "session_id": session_id,
        "tree_version": tree.version,
        "node": await _node_payload(tree, root, {}),
        "progress": compute_progress(tree, {}),
        "can_go_back": False,
        "estado": "en_progreso",
    }


async def get_current_node(session_id: str) -> dict:
    tree = get_tree()
    session = await repo.get_session(session_id)
    if session is None:
        raise EngineError(f"La sesión {session_id} no existe.")

    rows = await repo.get_respuestas(session_id)
    answers = _answers(tree, rows)
    route = compute_route(tree, answers)
    current_id = route[-1] if route else tree.root
    node = tree.node(current_id)

    previous = answers.get(current_id)

    await repo.update_session(session_id, current_node_id=current_id)

    return {
        "session_id": session_id,
        "tree_version": session.get("tree_version") or tree.version,
        "node": await _node_payload(tree, node, answers, previous),
        "progress": compute_progress(tree, answers),
        "can_go_back": len(route) > 1,
        "estado": session.get("estado", "en_progreso"),
    }


async def submit_answer(
    session_id: str,
    node_id: str,
    value: Any,
    user_id: str,
    origen: str = "propio",
) -> dict:
    """
    Valida, persiste y devuelve el siguiente nodo.

    Idempotente por (session_id, node_id): reenviar la misma respuesta
    actualiza la fila y recalcula la ruta, no duplica ni avanza dos veces.
    """
    tree = get_tree()
    session = await repo.get_session(session_id)
    if session is None:
        raise EngineError(f"La sesión {session_id} no existe.")
    if node_id not in tree.by_id:
        raise EngineError(f"El nodo {node_id} no existe en el árbol {tree.version}.")

    node = tree.node(node_id)
    rows = await repo.get_respuestas(session_id)
    answers = _answers(tree, rows)

    # ── Validación estructurada ──
    result = validate_answer(node, value, answers)
    if not result.ok:
        await repo.bump_intentos(session_id, node_id)
        raise ValidationFailed(result.errors)

    # ── Unicidad de id_actividad, que necesita la base de datos ──
    if node.field_key == "id_actividad":
        if await repo.id_actividad_existe(str(result.value), session_id):
            await repo.bump_intentos(session_id, node_id)
            raise ValidationFailed([
                AnswerError(
                    field_key="id_actividad",
                    code="id_duplicado",
                    message="Ya existe otra actividad registrada con este identificador.",
                )
            ])

    # ── Persistencia ──
    is_multi = node.input_type == F.InputType.MULTI_SELECT
    if node.persist:
        await repo.upsert_respuesta(
            session_id=session_id,
            user_id=user_id,
            tree_version=tree.version,
            node_id=node_id,
            field_key=node.field_key or (node.compose.target if node.compose else None),
            valor=F.serialize_multi(result.value) if is_multi else (
                None if result.value is None else str(result.value)
            ),
            valor_json=result.value if is_multi else None,
            origen=origen,
        )

    answers[node_id] = result.value

    # ── Aristas de corrección: volver atrás sin perder el resto ──
    chosen = next(
        (o for o in node.options if o.value == str(result.value) and o.revisit),
        None,
    )
    if chosen and chosen.next:
        await repo.delete_respuestas(session_id, [chosen.next, node_id])
        answers.pop(chosen.next, None)
        answers.pop(node_id, None)

    # ── Recálculo de ruta y marcado stale ──
    path = set(project_full_path(tree, answers))
    answered_ids = {r["node_id"] for r in rows if r.get("node_id")} | {node_id}
    fuera = sorted(answered_ids - path)
    dentro = sorted(answered_ids & path)
    if fuera:
        await repo.set_stale(session_id, fuera, True)
    if dentro:
        await repo.set_stale(session_id, dentro, False)

    return await get_current_node(session_id)


async def go_back(session_id: str) -> dict:
    """
    Retrocede un nodo. No borra respuestas posteriores: el motor recalcula la
    ruta, y si la ramificación cambia las marca como stale.
    """
    tree = get_tree()
    rows = await repo.get_respuestas(session_id)
    answers = _answers(tree, rows)
    route = compute_route(tree, answers)

    if len(route) < 2:
        return await get_current_node(session_id)

    objetivo = route[-2]
    await repo.delete_respuestas(session_id, [objetivo])
    await repo.update_session(session_id, current_node_id=objetivo)
    return await get_current_node(session_id)


async def get_summary(session_id: str) -> dict:
    """Las 25 respuestas consolidadas, con los campos no alcanzables marcados."""
    tree = get_tree()
    session = await repo.get_session(session_id)
    if session is None:
        raise EngineError(f"La sesión {session_id} no existe.")

    rows = await repo.get_respuestas(session_id)
    answers = _answers(tree, rows)
    compuesto = compose_fields(tree, answers)

    path = set(project_full_path(tree, answers))
    alcanzables: set[str] = set()
    for node_id in path:
        n = tree.node(node_id)
        if n.field_key:
            alcanzables.add(n.field_key)
        if n.compose:
            alcanzables.add(n.compose.target)

    campos = []
    for key in F.FIELD_KEYS:
        f = F.FIELD_BY_KEY[key]
        campos.append({
            "field_key": key,
            "header": f.header,
            "block": f.block,
            "block_name": F.BLOCK_NAMES[f.block],
            "input_type": f.input_type.value,
            "valor": compuesto.get(key),
            "alcanzable": key in alcanzables,
        })

    return {
        "session_id": session_id,
        "estado": session.get("estado", "en_progreso"),
        "tree_version": session.get("tree_version") or tree.version,
        "campos": campos,
        "progress": compute_progress(tree, answers),
    }


def _coerce_for_db(compuesto: dict[str, Any]) -> dict[str, Any]:
    """
    Adapta los valores compuestos a los tipos reales de epm_actividades:
    fecha DATE, participantes_evaluados INTEGER, porcentaje_cumplimiento SMALLINT.
    """
    out: dict[str, Any] = {}
    for key in F.FIELD_KEYS:
        v = compuesto.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            out[key] = None
            continue
        if key in ("participantes_evaluados", "porcentaje_cumplimiento"):
            try:
                out[key] = int(v)
            except (TypeError, ValueError):
                out[key] = None
        else:
            out[key] = str(v)
    return out


async def finalize(session_id: str, user_id: str) -> dict:
    """
    Cierra la sesión y proyecta las 25 columnas a epm_actividades.

    El estado depende de la etapa declarada al inicio: una actividad en
    planeación queda como `planeada` y puede retomarse; una ejecutada queda
    como `completada`.
    """
    tree = get_tree()
    rows = await repo.get_respuestas(session_id)
    answers = _answers(tree, rows)
    compuesto = compose_fields(tree, answers)

    etapa = answers.get("q00_etapa")
    estado = "planeada" if etapa == "En planeación" else "completada"

    await repo.project_actividad(session_id, user_id, _coerce_for_db(compuesto))
    await repo.update_session(
        session_id,
        estado=estado,
        # PostgREST no evalúa SQL: hay que enviar la marca de tiempo ya resuelta.
        completed_at=datetime.now(UTC).isoformat(),
    )

    return {
        "session_id": session_id,
        "estado": estado,
        "campos_diligenciados": sum(1 for v in compuesto.values() if v),
        "progress": compute_progress(tree, answers),
    }
