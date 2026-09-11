"""
Validación estructurada de respuestas.

Incluye explícitamente los límites 0, 100 y 101 del porcentaje, que la
sección 11 pide cubrir.
"""

from __future__ import annotations

import pytest

from app.domain.tree_loader import get_tree
from app.domain.validators import validate_answer


@pytest.fixture
def nodo():
    tree = get_tree()
    return tree.node


def codigos(resultado) -> set[str]:
    return {e.code for e in resultado.errors}


# ─── Porcentaje ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("valor", [0, 1, 50, 99, 100, "0", "100"])
def test_porcentaje_valido(nodo, valor):
    r = validate_answer(nodo("q27_porcentaje_cumplimiento"), valor)
    assert r.ok, r.errors
    assert isinstance(r.value, int)


@pytest.mark.parametrize("valor", [101, 150, -1, 1000])
def test_porcentaje_fuera_de_rango(nodo, valor):
    r = validate_answer(nodo("q27_porcentaje_cumplimiento"), valor)
    assert not r.ok
    assert codigos(r) & {"fuera_de_rango", "muy_grande", "muy_pequeno"}


@pytest.mark.parametrize("valor", ["ochenta", "85%", "", "  "])
def test_porcentaje_no_numerico(nodo, valor):
    r = validate_answer(nodo("q27_porcentaje_cumplimiento"), valor)
    assert not r.ok


def test_el_porcentaje_devuelve_el_campo_correcto(nodo):
    r = validate_answer(nodo("q27_porcentaje_cumplimiento"), 200)
    assert all(e.field_key == "porcentaje_cumplimiento" for e in r.errors)


# ─── Enteros ────────────────────────────────────────────────────────────────


def test_entero_valido(nodo):
    r = validate_answer(nodo("q23a_total_participantes"), "30")
    assert r.ok and r.value == 30


def test_entero_negativo_rechazado(nodo):
    r = validate_answer(nodo("q23a_total_participantes"), -5)
    assert not r.ok and "muy_pequeno" in codigos(r)


def test_entero_no_numerico_rechazado(nodo):
    r = validate_answer(nodo("q23a_total_participantes"), "muchos")
    assert not r.ok and "no_entero" in codigos(r)


def test_participantes_evaluados_no_supera_el_total(nodo):
    r = validate_answer(
        nodo("q24_participantes_evaluados"), 40,
        answers={"q23a_total_participantes": 30},
    )
    assert not r.ok and "excede_total" in codigos(r)


def test_participantes_evaluados_igual_al_total_es_valido(nodo):
    r = validate_answer(
        nodo("q24_participantes_evaluados"), 30,
        answers={"q23a_total_participantes": 30},
    )
    assert r.ok, r.errors


def test_sin_total_no_se_valida_el_tope(nodo):
    r = validate_answer(nodo("q24_participantes_evaluados"), 999, answers={})
    assert r.ok


# ─── Fecha ──────────────────────────────────────────────────────────────────


def test_fecha_valida(nodo):
    r = validate_answer(nodo("q16_fecha"), "2026-09-10")
    assert r.ok and r.value == "2026-09-10"


@pytest.mark.parametrize("valor", ["10/09/2026", "2026-9-10", "10-09-2026", "ayer"])
def test_fecha_con_formato_invalido(nodo, valor):
    r = validate_answer(nodo("q16_fecha"), valor)
    assert not r.ok and "fecha_invalida" in codigos(r)


def test_fecha_inexistente_en_el_calendario(nodo):
    r = validate_answer(nodo("q16_fecha"), "2026-02-30")
    assert not r.ok and "fecha_invalida" in codigos(r)


# ─── Duración ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("valor", ["2 horas", "90 minutos", "1 hora", "45 min", "1.5 horas"])
def test_duracion_valida(nodo, valor):
    assert validate_answer(nodo("q10_duracion"), valor).ok


@pytest.mark.parametrize("valor", ["larga", "toda la mañana", "dos horas"])
def test_duracion_sin_numero_rechazada(nodo, valor):
    r = validate_answer(nodo("q10_duracion"), valor)
    assert not r.ok and "duracion_invalida" in codigos(r)


# ─── Opciones cerradas ──────────────────────────────────────────────────────


def test_opcion_valida(nodo):
    assert validate_answer(nodo("q02_programa"), "Biblioteca_EPM").ok


def test_opcion_inventada_rechazada(nodo):
    r = validate_answer(nodo("q02_programa"), "Biblioteca Municipal")
    assert not r.ok and "opcion_invalida" in codigos(r)


def test_seleccion_multiple_valida(nodo):
    from app.domain.fields import ODS

    r = validate_answer(nodo("q12_ods"), [ODS[3], ODS[5]])
    assert r.ok and r.value == [ODS[3], ODS[5]]


def test_seleccion_multiple_con_valor_invalido(nodo):
    from app.domain.fields import ODS

    r = validate_answer(nodo("q12_ods"), [ODS[0], "ODS 18. Inventado"])
    assert not r.ok and "opcion_invalida" in codigos(r)


def test_seleccion_multiple_vacia_es_obligatoria(nodo):
    r = validate_answer(nodo("q12_ods"), [])
    assert not r.ok and "requerido" in codigos(r)


def test_seleccion_multiple_no_acepta_texto(nodo):
    r = validate_answer(nodo("q12_ods"), "1. Fin de la pobreza")
    assert not r.ok and "tipo_invalido" in codigos(r)


# ─── Texto ──────────────────────────────────────────────────────────────────


def test_texto_demasiado_corto(nodo):
    r = validate_answer(nodo("q11_pregunta_problematizadora"), "corto")
    assert not r.ok and "muy_corto" in codigos(r)


def test_texto_suficiente(nodo):
    r = validate_answer(
        nodo("q11_pregunta_problematizadora"),
        "¿Cómo cuidamos el agua que llega a nuestra casa?",
    )
    assert r.ok


def test_campo_obligatorio_vacio(nodo):
    r = validate_answer(nodo("q05_nombre"), "   ")
    assert not r.ok and "requerido" in codigos(r)


def test_el_texto_se_recorta(nodo):
    r = validate_answer(nodo("q09_responsable"), "  Ana Restrepo  ")
    assert r.ok and r.value == "Ana Restrepo"


def test_id_actividad_muy_corto(nodo):
    r = validate_answer(nodo("q01_id_actividad"), "AB")
    assert not r.ok and "muy_corto" in codigos(r)


def test_los_errores_son_estructura_no_texto(nodo):
    r = validate_answer(nodo("q27_porcentaje_cumplimiento"), 500)
    assert not r.ok
    for e in r.errors:
        assert set(e.model_dump()) == {"field_key", "code", "message"}
        assert e.code and e.message
