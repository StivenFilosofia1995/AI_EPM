"""
Validación del grafo del árbol y recorridos por rama.

Cubre lo que pide la sección 11: nodos alcanzables, ausencia de ciclos en el
grafo hacia adelante, los 25 campos presentes, y un recorrido completo por
cada ramificación declarada en la sección 4.2.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from app.domain import fields as F
from app.domain.tree_loader import (
    Condition,
    Tree,
    TreeError,
    load_tree,
    validate_tree,
)

MAX_PASOS = 300


# ─── Estructura ─────────────────────────────────────────────────────────────


def test_el_arbol_carga_y_valida(arbol):
    assert arbol.version
    assert arbol.checksum
    assert len(arbol.nodes) > 25


def test_todos_los_nodos_son_alcanzables(arbol):
    alcanzables, pila = set(), [arbol.root]
    while pila:
        actual = pila.pop()
        if actual in alcanzables:
            continue
        alcanzables.add(actual)
        pila.extend(arbol.edges(arbol.node(actual)))
    assert alcanzables == {n.node_id for n in arbol.nodes}


def test_los_25_campos_son_alcanzables(arbol):
    producidos = set()
    for n in arbol.nodes:
        if n.field_key:
            producidos.add(n.field_key)
        if n.compose:
            producidos.add(n.compose.target)
    assert producidos == set(F.FIELD_KEYS)


def test_ningun_destino_apunta_a_un_nodo_inexistente(arbol):
    ids = {n.node_id for n in arbol.nodes}
    for n in arbol.nodes:
        for destino in arbol.edges(n):
            assert destino in ids, f"{n.node_id} apunta a {destino}, que no existe"


def test_los_campos_compuestos_tienen_ordenes_distintos(arbol):
    for objetivo in {n.compose.target for n in arbol.nodes if n.compose}:
        ordenes = [n.compose.order for n in arbol.nodes if n.compose and n.compose.target == objetivo]
        assert len(ordenes) == len(set(ordenes)), f"{objetivo} tiene órdenes repetidos"


def test_solo_las_aristas_de_correccion_son_revisit(arbol):
    """El único bucle deliberado es la corrección del resumen del bloque 1."""
    revisit = [
        (n.node_id, o.next) for n in arbol.nodes for o in n.options if o.revisit
    ]
    assert revisit, "Se esperaba al menos una arista de corrección."
    assert all(origen == "n17_resumen_bloque1" for origen, _ in revisit)


# ─── El validador detecta grafos mal formados ───────────────────────────────


def _arbol_desde(datos: dict) -> Tree:
    from app.domain.tree_loader import NextWhen, Node

    nodos = []
    for raw in datos["nodes"]:
        raw = dict(raw)
        raw["next_when"] = [NextWhen.from_raw(nw) for nw in raw.get("next_when", [])]
        nodos.append(Node(**raw))
    return Tree(
        version=datos["version"], nombre=datos.get("nombre", ""),
        root=datos["root"], nodes=nodos, checksum="x",
    )


@pytest.fixture
def datos_yaml():
    from app.domain.tree_loader import DEFAULT_TREE_FILE

    return yaml.safe_load(DEFAULT_TREE_FILE.read_text(encoding="utf-8"))


def test_detecta_destino_inexistente(datos_yaml):
    d = copy.deepcopy(datos_yaml)
    for n in d["nodes"]:
        if n["node_id"] == "q05_nombre":
            n["default_next"] = "q99_no_existe"
    with pytest.raises(TreeError, match="no existe"):
        validate_tree(_arbol_desde(d))


def test_detecta_nodo_huerfano(datos_yaml):
    d = copy.deepcopy(datos_yaml)
    d["nodes"].append({
        "node_id": "q_huerfano", "label": "Nadie llega aquí",
        "input_type": "text", "terminal": True,
    })
    with pytest.raises(TreeError, match="huérfanos"):
        validate_tree(_arbol_desde(d))


def test_detecta_ciclo_no_marcado_como_revisit(datos_yaml):
    """
    Se inserta un nodo intermedio que además regresa al anterior. La ruta
    hacia adelante sigue completa (nada queda huérfano), así que lo único
    que debe fallar es la detección de ciclos.
    """
    d = copy.deepcopy(datos_yaml)
    for n in d["nodes"]:
        if n["node_id"] == "q05_nombre":
            n["default_next"] = "q05b_bucle"
    d["nodes"].append({
        "node_id": "q05b_bucle",
        "label": "Nodo que regresa al anterior",
        "input_type": "text",
        "required": False,
        "next_when": [{"if": "q05b_bucle == 'volver'", "goto": "q05_nombre"}],
        "default_next": "q06_publico",
    })
    with pytest.raises(TreeError, match="Ciclo detectado"):
        validate_tree(_arbol_desde(d))


def test_detecta_campo_faltante(datos_yaml):
    d = copy.deepcopy(datos_yaml)
    for n in d["nodes"]:
        if n["node_id"] == "q15_recursos":
            n.pop("field_key")
    with pytest.raises(TreeError, match="no son alcanzables"):
        validate_tree(_arbol_desde(d))


def test_rechaza_field_key_fuera_del_contrato(datos_yaml):
    d = copy.deepcopy(datos_yaml)
    for n in d["nodes"]:
        if n["node_id"] == "q15_recursos":
            n["field_key"] = "campo_inventado"
    with pytest.raises(TreeError, match="no está en los 25 campos"):
        _arbol_desde(d)


# ─── Condiciones ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expresion,respuestas,esperado",
    [
        ("q00_etapa == 'En planeación'", {"q00_etapa": "En planeación"}, True),
        ("q00_etapa == 'En planeación'", {"q00_etapa": "Ya ejecutada"}, False),
        ("q27_porcentaje_cumplimiento < 60", {"q27_porcentaje_cumplimiento": 59}, True),
        ("q27_porcentaje_cumplimiento < 60", {"q27_porcentaje_cumplimiento": 60}, False),
        ("q27_porcentaje_cumplimiento < 60", {}, False),
        ("q00_etapa != 'Ya ejecutada'", {"q00_etapa": "En planeación"}, True),
    ],
)
def test_evaluacion_de_condiciones(expresion, respuestas, esperado):
    assert Condition.parse(expresion).evaluate(respuestas) is esperado


def test_condicion_mal_formada_es_rechazada():
    with pytest.raises(TreeError, match="no reconocida"):
        Condition.parse("import os; os.system('rm -rf /')")


def test_condicion_no_evalua_codigo():
    """El lenguaje de condiciones no usa eval: solo una expresión regular."""
    with pytest.raises(TreeError):
        Condition.parse("__import__('os').getcwd() == 'x'")


# ─── Recorridos por rama (sección 4.2) ──────────────────────────────────────


def _recorrer(arbol, respuestas: dict) -> list[str]:
    ruta, actual = [], arbol.root
    for _ in range(MAX_PASOS):
        ruta.append(actual)
        nodo = arbol.node(actual)
        if nodo.terminal:
            return ruta
        siguiente = nodo.resolve_next(respuestas)
        if siguiente is None:
            return ruta
        actual = siguiente
    raise AssertionError("El recorrido no terminó: posible bucle infinito.")


def _campos(arbol, ruta: list[str]) -> set[str]:
    salida = set()
    for nid in ruta:
        n = arbol.node(nid)
        if n.field_key:
            salida.add(n.field_key)
        if n.compose:
            salida.add(n.compose.target)
    return salida


BASE_EJECUTADA = {
    "q00_etapa": "Ya ejecutada",
    "q06_publico": "Adultos",
    "n17_resumen_bloque1": "Sí, el diseño es coherente",
    "q23_instrumento_evaluativo": "Encuesta",
    "q27_porcentaje_cumplimiento": 85,
}


def test_rama_planeacion_solo_recorre_el_bloque_1(arbol):
    ruta = _recorrer(arbol, {
        **BASE_EJECUTADA,
        "q00_etapa": "En planeación",
        "q04_tipo_actividad": "Taller",
    })
    assert ruta[-1] == "n18_fin_planeada"
    campos = _campos(arbol, ruta)
    assert campos == {f.key for f in F.FIELDS if f.block == 1}
    assert not any(f.key in campos for f in F.FIELDS if f.block in (2, 3))


@pytest.mark.parametrize("tipo", ["Taller", "Club", "Actividad de sensibilización"])
def test_ramas_de_una_sola_sesion_no_preguntan_periodicidad(arbol, tipo):
    ruta = _recorrer(arbol, {**BASE_EJECUTADA, "q04_tipo_actividad": tipo})
    assert "q04a_num_sesiones" not in ruta
    assert "q04b_periodicidad" not in ruta
    assert _campos(arbol, ruta) == set(F.FIELD_KEYS)


@pytest.mark.parametrize("tipo", ["Curso", "Semillero"])
def test_ramas_de_varias_sesiones_preguntan_numero_y_periodicidad(arbol, tipo):
    ruta = _recorrer(arbol, {**BASE_EJECUTADA, "q04_tipo_actividad": tipo})
    assert "q04a_num_sesiones" in ruta
    assert "q04b_periodicidad" in ruta
    assert "q04c_espacios_itinerancia" not in ruta


def test_rama_itinerancia_pregunta_espacios(arbol):
    ruta = _recorrer(arbol, {**BASE_EJECUTADA, "q04_tipo_actividad": "Itinerancia"})
    assert "q04c_espacios_itinerancia" in ruta
    assert "q04a_num_sesiones" not in ruta


def test_primera_infancia_pregunta_acompanamiento(arbol):
    ruta = _recorrer(arbol, {
        **BASE_EJECUTADA, "q04_tipo_actividad": "Taller",
        "q06_publico": "Primera infancia",
    })
    assert "q06a_acompanamiento_cuidadores" in ruta


@pytest.mark.parametrize("publico", ["Niños", "Adolescentes", "Jóvenes", "Adultos", "Adultos mayores"])
def test_otros_publicos_no_preguntan_acompanamiento(arbol, publico):
    ruta = _recorrer(arbol, {
        **BASE_EJECUTADA, "q04_tipo_actividad": "Taller", "q06_publico": publico,
    })
    assert "q06a_acompanamiento_cuidadores" not in ruta


def test_cumplimiento_bajo_exige_justificacion(arbol):
    ruta = _recorrer(arbol, {
        **BASE_EJECUTADA, "q04_tipo_actividad": "Taller",
        "q27_porcentaje_cumplimiento": 45,
    })
    assert "q27a_justificacion_bajo_cumplimiento" in ruta


@pytest.mark.parametrize("pct", [60, 61, 100])
def test_cumplimiento_suficiente_no_exige_justificacion(arbol, pct):
    ruta = _recorrer(arbol, {
        **BASE_EJECUTADA, "q04_tipo_actividad": "Taller",
        "q27_porcentaje_cumplimiento": pct,
    })
    assert "q27a_justificacion_bajo_cumplimiento" not in ruta


def test_la_justificacion_se_anexa_a_acciones_de_mejora(arbol):
    nodo = arbol.node("q27a_justificacion_bajo_cumplimiento")
    assert nodo.compose is not None
    assert nodo.compose.target == "acciones_mejora"
    assert nodo.compose.order > arbol.node("q26_acciones_mejora").compose.order


def test_la_descripcion_se_divide_en_tres_momentos(arbol):
    momentos = [
        n for n in arbol.nodes
        if n.compose and n.compose.target == "descripcion_sesion"
        and n.node_id.startswith("q14")
    ]
    assert len(momentos) == 3
    assert {n.node_id for n in momentos} == {
        "q14a_descripcion_apertura",
        "q14b_descripcion_desarrollo",
        "q14c_descripcion_cierre",
    }


def test_ningun_nodo_tiene_field_key_descripcion_sesion(arbol):
    """La descripción es compuesta: ningún nodo la escribe directamente."""
    assert not any(n.field_key == "descripcion_sesion" for n in arbol.nodes)


def test_el_resumen_de_coherencia_muestra_los_tres_campos(arbol):
    nodo = arbol.node("n17_resumen_bloque1")
    assert nodo.kind == "confirm"
    assert set(nodo.summary_fields) == {"pregunta_problematizadora", "metodologia", "ods"}


def test_la_correccion_devuelve_al_nodo_correspondiente(arbol):
    nodo = arbol.node("n17_resumen_bloque1")
    destinos = {o.value: o.next for o in nodo.options if o.next}
    assert destinos["Quiero corregir la pregunta problematizadora"] == "q11_pregunta_problematizadora"
    assert destinos["Quiero corregir la metodología"] == "q13_metodologia"
    assert destinos["Quiero corregir los ODS"] == "q12_ods"


def test_ayuda_contextual_por_publico(arbol):
    nodo = arbol.node("q07_publico_especifico")
    generica = nodo.help_for({})
    infancia = nodo.help_for({"q06_publico": "Primera infancia"})
    mayores = nodo.help_for({"q06_publico": "Adultos mayores"})
    assert infancia != generica
    assert mayores != infancia


def test_recarga_del_arbol_da_el_mismo_checksum():
    assert load_tree().checksum == load_tree().checksum
