"""
Carga y validación del árbol de decisiones.

El árbol se define en YAML (ver consolidacion_epm_v1.yaml). Este módulo lo
carga una vez al arrancar, valida el grafo y lo mantiene inmutable en memoria.

El validador se ejecuta al arrancar la aplicación y en las pruebas. Si el
grafo está mal formado, la aplicación no levanta: es preferible fallar en el
despliegue que descubrirlo con un facilitador a medio camino.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field as PField, model_validator

from app.domain.fields import CLOSED_OPTIONS, FIELD_KEYS, InputType

TREE_DIR = Path(__file__).parent / "tree"
DEFAULT_TREE_FILE = TREE_DIR / "consolidacion_epm_v1.yaml"


class TreeError(Exception):
    """El árbol está mal formado. Impide el arranque."""


# ─── Expresiones de condición ───────────────────────────────────────────────
# Lenguaje deliberadamente mínimo: <node_id> <op> <literal>.
# No se usa eval() ni nada equivalente: solo esta expresión regular.

_CONDITION_RE = re.compile(
    r"""^\s*
    (?P<node>[A-Za-z_][A-Za-z0-9_]*)\s*
    (?P<op><=|>=|==|!=|<|>)\s*
    (?:'(?P<sq>[^']*)'|"(?P<dq>[^"]*)"|(?P<num>-?\d+(?:\.\d+)?))
    \s*$""",
    re.VERBOSE,
)


class Condition(BaseModel):
    raw: str
    node: str
    op: str
    value: str | float

    @classmethod
    def parse(cls, raw: str) -> "Condition":
        m = _CONDITION_RE.match(raw)
        if not m:
            raise TreeError(
                f"Condición no reconocida: {raw!r}. "
                "Formato admitido: node_id == 'valor' | node_id < 60"
            )
        if m.group("num") is not None:
            value: str | float = float(m.group("num"))
        else:
            value = m.group("sq") if m.group("sq") is not None else m.group("dq") or ""
        return cls(raw=raw, node=m.group("node"), op=m.group("op"), value=value)

    def evaluate(self, answers: dict[str, Any]) -> bool:
        """Evalúa la condición contra las respuestas ya dadas."""
        if self.node not in answers:
            return False
        actual = answers[self.node]

        if isinstance(self.value, float):
            try:
                actual_num = float(actual)
            except (TypeError, ValueError):
                return False
            return {
                "==": actual_num == self.value,
                "!=": actual_num != self.value,
                "<": actual_num < self.value,
                "<=": actual_num <= self.value,
                ">": actual_num > self.value,
                ">=": actual_num >= self.value,
            }[self.op]

        actual_str = "" if actual is None else str(actual)
        if self.op == "==":
            return actual_str == self.value
        if self.op == "!=":
            return actual_str != self.value
        raise TreeError(
            f"El operador {self.op!r} no aplica a un valor de texto en {self.raw!r}."
        )


# ─── Modelos del árbol ──────────────────────────────────────────────────────


class Option(BaseModel):
    value: str
    next: Optional[str] = None
    help: Optional[str] = None
    # Arista de corrección: excluida de la detección de ciclos.
    revisit: bool = False


class Compose(BaseModel):
    target: str
    order: int
    prefix: str = ""


class Validation(BaseModel):
    type: str
    value: Optional[Any] = None
    node: Optional[str] = None


class NextWhen(BaseModel):
    condition: Condition
    goto: str

    @classmethod
    def from_raw(cls, raw: dict) -> "NextWhen":
        if "if" not in raw or "goto" not in raw:
            raise TreeError(f"next_when requiere 'if' y 'goto': {raw!r}")
        return cls(condition=Condition.parse(str(raw["if"])), goto=str(raw["goto"]))


class HelpByAnswer(BaseModel):
    node: str
    variants: dict[str, str]


class Node(BaseModel):
    node_id: str
    kind: Literal["question", "info", "confirm"] = "question"
    label: str
    help: Optional[str] = None
    help_by_answer: Optional[HelpByAnswer] = None
    input_type: InputType
    required: bool = True
    persist: bool = True
    terminal: bool = False

    block: Optional[int] = None
    order: Optional[int] = None

    field_key: Optional[str] = None
    compose: Optional[Compose] = None

    options: list[Option] = PField(default_factory=list)
    options_from: Optional[str] = None
    autocomplete_from: Optional[str] = None

    next_when: list[NextWhen] = PField(default_factory=list)
    default_next: Optional[str] = None

    validations: list[Validation] = PField(default_factory=list)
    summary_fields: list[str] = PField(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Node":
        if self.field_key and self.compose:
            raise TreeError(
                f"{self.node_id}: no puede tener field_key y compose a la vez."
            )
        if self.field_key and self.field_key not in FIELD_KEYS:
            raise TreeError(
                f"{self.node_id}: field_key {self.field_key!r} no está en los 25 campos."
            )
        if self.compose and self.compose.target not in FIELD_KEYS:
            raise TreeError(
                f"{self.node_id}: compose.target {self.compose.target!r} "
                "no está en los 25 campos."
            )
        if self.options_from and self.options_from not in CLOSED_OPTIONS:
            raise TreeError(
                f"{self.node_id}: options_from {self.options_from!r} no es un "
                f"catálogo cerrado conocido. Disponibles: {sorted(CLOSED_OPTIONS)}"
            )
        if not self.terminal and not self.default_next and not self.options:
            raise TreeError(
                f"{self.node_id}: nodo no terminal sin default_next ni opciones."
            )
        return self

    @property
    def resolved_options(self) -> list[Option]:
        """Opciones explícitas, o las del catálogo cerrado si usa options_from."""
        if self.options_from:
            return [Option(value=v) for v in CLOSED_OPTIONS[self.options_from]]
        return self.options

    def help_for(self, answers: dict[str, Any]) -> Optional[str]:
        """Ayuda contextual según una respuesta previa; si no aplica, la genérica."""
        if self.help_by_answer:
            prev = answers.get(self.help_by_answer.node)
            if prev is not None:
                variant = self.help_by_answer.variants.get(str(prev))
                if variant:
                    return variant
        return self.help

    def resolve_next(self, answers: dict[str, Any]) -> Optional[str]:
        """
        Decide el siguiente nodo. Prioridad:
          1. La opción elegida, si trae `next`.
          2. La primera condición de next_when que se cumpla.
          3. default_next.
        """
        if self.terminal:
            return None

        own = answers.get(self.node_id)
        if own is not None:
            for opt in self.options:
                if opt.value == str(own) and opt.next:
                    return opt.next

        for nw in self.next_when:
            if nw.condition.evaluate(answers):
                return nw.goto

        return self.default_next


class Tree(BaseModel):
    version: str
    nombre: str
    root: str
    nodes: list[Node]
    checksum: str = ""

    @property
    def by_id(self) -> dict[str, Node]:
        return {n.node_id: n for n in self.nodes}

    def node(self, node_id: str) -> Node:
        n = self.by_id.get(node_id)
        if n is None:
            raise TreeError(f"El nodo {node_id!r} no existe en el árbol {self.version}.")
        return n

    def edges(self, node: Node, include_revisit: bool = True) -> list[str]:
        """Todos los destinos posibles desde un nodo."""
        out: list[str] = []
        for opt in node.options:
            if opt.next and (include_revisit or not opt.revisit):
                out.append(opt.next)
        for nw in node.next_when:
            out.append(nw.goto)
        if node.default_next:
            out.append(node.default_next)
        return out


# ─── Validación del grafo ───────────────────────────────────────────────────


def validate_tree(tree: Tree) -> None:
    """
    Recorre el grafo desde la raíz y verifica:
      · que todo destino apunte a un node_id existente;
      · que no haya nodos huérfanos (inalcanzables desde la raíz);
      · que el grafo hacia adelante sea acíclico (las aristas `revisit`,
        que son correcciones deliberadas, quedan excluidas);
      · que los 25 field_key sean alcanzables, sea como field_key directo
        o como compose.target;
      · que las condiciones referencien nodos existentes.

    Lanza TreeError con un mensaje accionable a la primera violación.
    """
    ids = {n.node_id for n in tree.nodes}

    if len(ids) != len(tree.nodes):
        seen: set[str] = set()
        dupes = {n.node_id for n in tree.nodes if n.node_id in seen or seen.add(n.node_id)}  # type: ignore[func-returns-value]
        raise TreeError(f"node_id duplicados: {sorted(dupes)}")

    if tree.root not in ids:
        raise TreeError(f"La raíz {tree.root!r} no existe entre los nodos.")

    # 1. Destinos existentes y condiciones bien formadas.
    for n in tree.nodes:
        for target in tree.edges(n):
            if target not in ids:
                raise TreeError(
                    f"{n.node_id}: apunta a {target!r}, que no existe en el árbol."
                )
        for nw in n.next_when:
            if nw.condition.node not in ids:
                raise TreeError(
                    f"{n.node_id}: la condición {nw.condition.raw!r} referencia "
                    f"el nodo {nw.condition.node!r}, que no existe."
                )
        for fk in n.summary_fields:
            if fk not in FIELD_KEYS:
                raise TreeError(
                    f"{n.node_id}: summary_fields incluye {fk!r}, que no es "
                    "uno de los 25 campos."
                )

    # 2. Alcanzabilidad desde la raíz.
    reachable: set[str] = set()
    stack = [tree.root]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(tree.edges(tree.node(current)))

    orphans = ids - reachable
    if orphans:
        raise TreeError(
            f"Nodos huérfanos, inalcanzables desde la raíz: {sorted(orphans)}"
        )

    # 3. Aciclicidad del grafo hacia adelante.
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(ids, WHITE)

    def visit(node_id: str, path: list[str]) -> None:
        color[node_id] = GREY
        for target in tree.edges(tree.node(node_id), include_revisit=False):
            if color[target] == GREY:
                cycle = " -> ".join(path + [node_id, target])
                raise TreeError(
                    f"Ciclo detectado en el grafo hacia adelante: {cycle}. "
                    "Si es una corrección deliberada, marca la arista con revisit: true."
                )
            if color[target] == WHITE:
                visit(target, path + [node_id])
        color[node_id] = BLACK

    visit(tree.root, [])

    # 4. Los 25 campos deben ser alcanzables.
    produced: set[str] = set()
    for node_id in reachable:
        n = tree.node(node_id)
        if n.field_key:
            produced.add(n.field_key)
        if n.compose:
            produced.add(n.compose.target)

    missing = set(FIELD_KEYS) - produced
    if missing:
        raise TreeError(
            "Estos campos del contrato no son alcanzables en el árbol: "
            f"{sorted(missing)}"
        )

    extra = produced - set(FIELD_KEYS)
    if extra:
        raise TreeError(f"El árbol produce campos fuera del contrato: {sorted(extra)}")

    # 5. Cada campo compuesto debe tener órdenes de composición distintos.
    for target in {n.compose.target for n in tree.nodes if n.compose}:
        orders = [n.compose.order for n in tree.nodes if n.compose and n.compose.target == target]
        if len(orders) != len(set(orders)):
            raise TreeError(
                f"El campo compuesto {target!r} tiene nodos con el mismo "
                "compose.order; el resultado sería no determinista."
            )


# ─── Carga ──────────────────────────────────────────────────────────────────


def load_tree(path: Path | None = None) -> Tree:
    """Carga y valida el árbol desde YAML. Lanza TreeError si está mal formado."""
    path = path or DEFAULT_TREE_FILE
    if not path.exists():
        raise TreeError(f"No se encontró la definición del árbol en {path}.")

    raw_text = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    data = yaml.safe_load(raw_text)
    if not isinstance(data, dict):
        raise TreeError(f"{path.name}: la raíz del YAML debe ser un mapa.")

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise TreeError(f"{path.name}: falta la lista 'nodes' o está vacía.")

    nodes: list[Node] = []
    for raw in raw_nodes:
        raw = dict(raw)
        raw["next_when"] = [NextWhen.from_raw(nw) for nw in raw.get("next_when", [])]
        try:
            nodes.append(Node(**raw))
        except TreeError:
            raise
        except Exception as exc:
            raise TreeError(
                f"Nodo {raw.get('node_id', '(sin node_id)')!r} mal formado: {exc}"
            ) from exc

    tree = Tree(
        version=str(data.get("version", "")),
        nombre=str(data.get("nombre", "")),
        root=str(data.get("root", "")),
        nodes=nodes,
        checksum=checksum,
    )
    if not tree.version:
        raise TreeError(f"{path.name}: falta el campo 'version' en la raíz.")

    validate_tree(tree)
    return tree


@lru_cache(maxsize=1)
def get_tree() -> Tree:
    """Árbol activo, cargado una sola vez y mantenido inmutable en memoria."""
    return load_tree()
