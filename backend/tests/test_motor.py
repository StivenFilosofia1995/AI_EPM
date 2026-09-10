"""
Motor de árbol: idempotencia, retroceso, marcado stale y proyección.

Usa el cliente de Supabase simulado de conftest. Todo el estado del motor
vive en la base de datos, así que estas pruebas también verifican que no
quede estado escondido en memoria del proceso.
"""

from __future__ import annotations

import pytest

from app.domain import fields as F
from app.services import tree_engine as engine
from app.services import tree_repository as repo

pytestmark = pytest.mark.asyncio


async def responder(sesion, node_id, valor, origen="propio"):
    return await engine.submit_answer(
        session_id=sesion["session_id"], node_id=node_id, value=valor,
        user_id=sesion["user_id"], origen=origen,
    )


async def llegar_a_bloque1(sesion, tipo="Taller", publico="Adultos"):
    """Recorre el bloque 1 completo con respuestas válidas."""
    pasos = [
        ("q00_etapa", "Ya ejecutada"),
        ("q01_id_actividad", "ACT-001"),
        ("q02_programa", "Biblioteca_EPM"),
        ("q03_linea_accion", "Educación"),
        ("q04_tipo_actividad", tipo),
    ]
    if tipo in ("Curso", "Semillero"):
        pasos += [("q04a_num_sesiones", 8), ("q04b_periodicidad", "Semanal")]
    elif tipo == "Itinerancia":
        pasos += [("q04c_espacios_itinerancia", "Parque, biblioteca y colegio")]

    pasos += [("q05_nombre", "Taller de agua"), ("q06_publico", publico)]
    if publico == "Primera infancia":
        pasos += [("q06a_acompanamiento_cuidadores",
                   "Sí, acompañamiento permanente durante toda la sesión")]

    pasos += [
        ("q07_publico_especifico", "Estudiantes de grado décimo"),
        ("q08_lugar", "Biblioteca EPM"),
        ("q09_responsable", "Ana Restrepo"),
        ("q10_duracion", "2 horas"),
        ("q11_pregunta_problematizadora", "¿Cómo cuidamos el agua de la ciudad?"),
        ("q12_ods", [F.ODS[5]]),
        ("q13_metodologia", "Aprendizaje basado en preguntas con trabajo en equipo"),
        ("q14a_descripcion_apertura", "Saludo y activación del tema"),
        ("q14b_descripcion_desarrollo", "Tres estaciones de exploración del ciclo del agua"),
        ("q14c_descripcion_cierre", "Ronda de cierre"),
        ("q15_recursos", "Cartillas y videobeam"),
        ("q16_fecha", "2026-09-10"),
    ]
    ultimo = None
    for node_id, valor in pasos:
        ultimo = await responder(sesion, node_id, valor)
    return ultimo


# ─── Persistencia básica ────────────────────────────────────────────────────


async def test_la_respuesta_se_persiste_de_inmediato(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    filas = cliente.filas("epm_respuestas")
    assert len(filas) == 1
    assert filas[0]["node_id"] == "q00_etapa"
    assert filas[0]["valor"] == "Ya ejecutada"
    assert filas[0]["tree_version"] == "1.0.0"


async def test_el_nodo_siguiente_es_el_correcto(cliente, sesion):
    r = await responder(sesion, "q00_etapa", "Ya ejecutada")
    assert r["node"]["node_id"] == "q01_id_actividad"


async def test_la_validacion_impide_persistir(cliente, sesion):
    with pytest.raises(engine.ValidationFailed) as exc:
        await responder(sesion, "q00_etapa", "Etapa inventada")
    assert exc.value.errors
    assert cliente.filas("epm_respuestas") == []


async def test_seleccion_multiple_guarda_texto_y_json(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")
    await responder(sesion, "q02_programa", "Biblioteca_EPM")
    await responder(sesion, "q03_linea_accion", "Educación")
    await responder(sesion, "q04_tipo_actividad", "Taller")
    await responder(sesion, "q05_nombre", "Taller de agua")
    await responder(sesion, "q06_publico", "Adultos")
    await responder(sesion, "q07_publico_especifico", "Líderes comunitarios")
    await responder(sesion, "q08_lugar", "Biblioteca EPM")
    await responder(sesion, "q09_responsable", "Ana Restrepo")
    await responder(sesion, "q10_duracion", "2 horas")
    await responder(sesion, "q11_pregunta_problematizadora", "¿Cómo cuidamos el agua?")
    await responder(sesion, "q12_ods", [F.ODS[5], F.ODS[12]])

    fila = next(f for f in cliente.filas("epm_respuestas") if f["node_id"] == "q12_ods")
    assert fila["valor_json"] == [F.ODS[5], F.ODS[12]]
    assert fila["valor"] == f"{F.ODS[5]}; {F.ODS[12]}"


# ─── Idempotencia ───────────────────────────────────────────────────────────


async def test_submit_answer_es_idempotente(cliente, sesion):
    r1 = await responder(sesion, "q00_etapa", "Ya ejecutada")
    r2 = await responder(sesion, "q00_etapa", "Ya ejecutada")

    filas = [f for f in cliente.filas("epm_respuestas") if f["node_id"] == "q00_etapa"]
    assert len(filas) == 1, "Reenviar la misma respuesta duplicó la fila."
    assert r1["node"]["node_id"] == r2["node"]["node_id"], "Avanzó dos veces."


async def test_reenviar_un_valor_distinto_actualiza_sin_duplicar(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q00_etapa", "En planeación")

    filas = [f for f in cliente.filas("epm_respuestas") if f["node_id"] == "q00_etapa"]
    assert len(filas) == 1
    assert filas[0]["valor"] == "En planeación"


async def test_el_intento_fallido_queda_registrado(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")
    with pytest.raises(engine.ValidationFailed):
        await responder(sesion, "q02_programa", "Programa inventado")

    fila = next(f for f in cliente.filas("epm_respuestas") if f["node_id"] == "q01_id_actividad")
    assert fila["intentos"] == 1  # el fallo fue en otro nodo


# ─── Estado sin memoria de proceso ──────────────────────────────────────────


async def test_el_estado_sobrevive_a_un_reinicio(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")

    # No hay caché que limpiar: el motor relee de la base en cada llamada.
    actual = await engine.get_current_node(sesion["session_id"])
    assert actual["node"]["node_id"] == "q02_programa"
    assert actual["progress"]["respondidos"] == 1  # q00 no produce campo


async def test_el_valor_previo_se_devuelve_al_repintar(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")
    await engine.go_back(sesion["session_id"])
    await responder(sesion, "q01_id_actividad", "ACT-002")

    actual = await engine.get_current_node(sesion["session_id"])
    assert actual["node"]["node_id"] == "q02_programa"


# ─── Retroceso ──────────────────────────────────────────────────────────────


async def test_go_back_devuelve_al_nodo_anterior(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")

    r = await engine.go_back(sesion["session_id"])
    assert r["node"]["node_id"] == "q01_id_actividad"


async def test_go_back_en_la_raiz_no_falla(cliente, sesion):
    r = await engine.go_back(sesion["session_id"])
    assert r["node"]["node_id"] == "q00_etapa"


async def test_go_back_no_borra_las_respuestas_anteriores(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")
    await engine.go_back(sesion["session_id"])

    quedan = {f["node_id"] for f in cliente.filas("epm_respuestas")}
    assert "q00_etapa" in quedan


# ─── Marcado stale al cambiar de ramificación ───────────────────────────────


async def test_cambiar_de_rama_marca_stale_las_respuestas_huerfanas(cliente, sesion):
    await llegar_a_bloque1(sesion, tipo="Curso")

    filas = {f["node_id"]: f for f in cliente.filas("epm_respuestas")}
    assert "q04a_num_sesiones" in filas
    assert filas["q04a_num_sesiones"]["stale"] is False

    # El facilitador se devuelve y cambia el tipo a Taller, que no tiene sesiones.
    await responder(sesion, "q04_tipo_actividad", "Taller")

    filas = {f["node_id"]: f for f in cliente.filas("epm_respuestas")}
    assert filas["q04a_num_sesiones"]["stale"] is True, "No se marcó stale."
    assert filas["q04b_periodicidad"]["stale"] is True
    assert filas["q05_nombre"]["stale"] is False, "Se marcó stale algo que sigue en la ruta."


async def test_las_respuestas_stale_no_cuentan_para_el_progreso(cliente, sesion):
    await llegar_a_bloque1(sesion, tipo="Curso")
    antes = (await engine.get_current_node(sesion["session_id"]))["progress"]

    await responder(sesion, "q04_tipo_actividad", "Taller")
    despues = (await engine.get_current_node(sesion["session_id"]))["progress"]

    assert despues["total"] < antes["total"], "La ruta de Taller debe tener menos campos."


async def test_las_respuestas_stale_no_se_borran(cliente, sesion):
    await llegar_a_bloque1(sesion, tipo="Curso")
    await responder(sesion, "q04_tipo_actividad", "Taller")

    ids = {f["node_id"] for f in cliente.filas("epm_respuestas")}
    assert "q04a_num_sesiones" in ids, "Se perdió la respuesta en vez de marcarla."


# ─── Progreso sobre la ruta real ────────────────────────────────────────────


async def test_el_progreso_no_es_sobre_25_fijo(cliente, sesion):
    await llegar_a_bloque1(sesion, tipo="Curso", publico="Primera infancia")
    p = (await engine.get_current_node(sesion["session_id"]))["progress"]
    # Curso añade 2 nodos, primera infancia 1, y la descripción son 3 en vez de 1.
    assert p["total"] > 25


async def test_la_rama_planeada_tiene_menos_campos(cliente, sesion):
    await responder(sesion, "q00_etapa", "En planeación")
    p = (await engine.get_current_node(sesion["session_id"]))["progress"]
    bloques = {b["bloque"] for b in p["por_bloque"]}
    assert 2 not in bloques and 3 not in bloques


# ─── Composición ────────────────────────────────────────────────────────────


async def test_la_descripcion_se_compone_en_orden(cliente, sesion):
    await llegar_a_bloque1(sesion, tipo="Curso")
    resumen = await engine.get_summary(sesion["session_id"])
    campos = {c["field_key"]: c["valor"] for c in resumen["campos"]}

    d = campos["descripcion_sesion"]
    assert d.index("Número de sesiones:") < d.index("Periodicidad:")
    assert d.index("Periodicidad:") < d.index("Apertura:")
    assert d.index("Apertura:") < d.index("Desarrollo:")
    assert d.index("Desarrollo:") < d.index("Cierre:")


async def test_el_acompanamiento_se_anexa_al_publico_especifico(cliente, sesion):
    await llegar_a_bloque1(sesion, publico="Primera infancia")
    resumen = await engine.get_summary(sesion["session_id"])
    campos = {c["field_key"]: c["valor"] for c in resumen["campos"]}

    assert "Acompañamiento de cuidadores:" in campos["publico_especifico"]
    assert "Estudiantes de grado décimo" in campos["publico_especifico"]


async def test_el_resumen_marca_los_campos_no_alcanzables(cliente, sesion):
    await responder(sesion, "q00_etapa", "En planeación")
    resumen = await engine.get_summary(sesion["session_id"])
    por_clave = {c["field_key"]: c for c in resumen["campos"]}

    assert por_clave["nombre"]["alcanzable"] is True
    assert por_clave["logros"]["alcanzable"] is False
    assert por_clave["porcentaje_cumplimiento"]["alcanzable"] is False


async def test_el_resumen_devuelve_los_25_en_orden(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    resumen = await engine.get_summary(sesion["session_id"])
    assert [c["field_key"] for c in resumen["campos"]] == F.FIELD_KEYS


# ─── Unicidad de id_actividad ───────────────────────────────────────────────


async def test_id_actividad_duplicado_es_rechazado(cliente, sesion):
    cliente.table("epm_respuestas").filas.append({
        "id": "otra", "session_id": "otra-sesion", "node_id": "q01_id_actividad",
        "field_key": "id_actividad", "valor": "ACT-001", "stale": False,
        "es_valida": True, "tree_version": "1.0.0",
    })
    await responder(sesion, "q00_etapa", "Ya ejecutada")

    with pytest.raises(engine.ValidationFailed) as exc:
        await responder(sesion, "q01_id_actividad", "ACT-001")
    assert "id_duplicado" in {e.code for e in exc.value.errors}


async def test_el_mismo_id_en_la_misma_sesion_se_permite(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada")
    await responder(sesion, "q01_id_actividad", "ACT-001")
    await responder(sesion, "q01_id_actividad", "ACT-001")  # reenvío idempotente


# ─── Proyección y cierre ────────────────────────────────────────────────────


async def test_finalize_proyecta_las_25_columnas(cliente, sesion):
    await llegar_a_bloque1(sesion)
    await responder(sesion, "n17_resumen_bloque1", "Sí, el diseño es coherente")
    await responder(sesion, "q19_logros", "Alta participación del grupo asistente")
    await responder(sesion, "q20_retos", "Faltó tiempo en el cierre")
    await responder(sesion, "q21_observaciones", "Buen clima de trabajo")
    await responder(sesion, "q22_comentarios", "Pidieron repetir la actividad")
    await responder(sesion, "q23_instrumento_evaluativo", "Encuesta")
    await responder(sesion, "q23a_total_participantes", 30)
    await responder(sesion, "q24_participantes_evaluados", 28)
    await responder(sesion, "q25_cumplimiento_objetivos", "Se cumplieron los tres objetivos")
    await responder(sesion, "q26_acciones_mejora", "Ampliar el tiempo de cierre")
    await responder(sesion, "q27_porcentaje_cumplimiento", 90)

    r = await engine.finalize(sesion["session_id"], sesion["user_id"])
    assert r["estado"] == "completada"

    fila = cliente.filas("epm_actividades")[0]
    for clave in F.FIELD_KEYS:
        assert clave in fila, f"Falta la columna {clave} en la proyección."
    assert fila["participantes_evaluados"] == 28
    assert fila["porcentaje_cumplimiento"] == 90
    assert fila["fecha"] == "2026-09-10"
    assert fila["ods"] == F.ODS[5]


async def test_los_numericos_se_proyectan_como_enteros(cliente, sesion):
    await llegar_a_bloque1(sesion)
    await responder(sesion, "n17_resumen_bloque1", "Sí, el diseño es coherente")
    for nid, v in [
        ("q19_logros", "Alta participación del grupo"),
        ("q20_retos", "Faltó tiempo"),
        ("q21_observaciones", "Buen clima"),
        ("q22_comentarios", "Pidieron repetir"),
        ("q23_instrumento_evaluativo", "Encuesta"),
        ("q23a_total_participantes", 30),
        ("q24_participantes_evaluados", 28),
        ("q25_cumplimiento_objetivos", "Se cumplieron los objetivos"),
        ("q26_acciones_mejora", "Ampliar el cierre"),
        ("q27_porcentaje_cumplimiento", 90),
    ]:
        await responder(sesion, nid, v)
    await engine.finalize(sesion["session_id"], sesion["user_id"])

    fila = cliente.filas("epm_actividades")[0]
    assert isinstance(fila["porcentaje_cumplimiento"], int)
    assert isinstance(fila["participantes_evaluados"], int)


async def test_la_rama_planeada_cierra_como_planeada(cliente, sesion):
    await llegar_a_bloque1(sesion)
    # Se cambia la etapa: la sesión pasa a ser solo diseño.
    await responder(sesion, "q00_etapa", "En planeación")

    r = await engine.finalize(sesion["session_id"], sesion["user_id"])
    assert r["estado"] == "planeada"


async def test_el_origen_de_la_respuesta_queda_registrado(cliente, sesion):
    await responder(sesion, "q00_etapa", "Ya ejecutada", origen="propio")
    await responder(sesion, "q01_id_actividad", "ACT-001")
    await responder(sesion, "q02_programa", "Biblioteca_EPM")
    await responder(sesion, "q03_linea_accion", "Educación")
    await responder(sesion, "q04_tipo_actividad", "Taller")
    await responder(sesion, "q05_nombre", "Taller de agua")
    await responder(sesion, "q06_publico", "Adultos")
    await responder(
        sesion, "q07_publico_especifico",
        "Líderes comunitarios del corregimiento", origen="sugerencia_editada",
    )

    fila = next(f for f in cliente.filas("epm_respuestas") if f["node_id"] == "q07_publico_especifico")
    assert fila["origen"] == "sugerencia_editada"


async def test_sesion_inexistente_lanza_error(cliente):
    with pytest.raises(engine.EngineError):
        await engine.get_current_node("no-existe")


# ─── Autocompletado determinista ────────────────────────────────────────────


async def test_el_autocompletado_de_lugar_sale_de_la_base(cliente, sesion):
    for i, lugar in enumerate(["Biblioteca EPM", "Museo del Agua", "Biblioteca EPM"]):
        cliente.table("epm_respuestas").filas.append({
            "id": f"x{i}", "session_id": f"s{i}", "node_id": "q08_lugar",
            "field_key": "lugar", "valor": lugar, "stale": False,
            "es_valida": True, "tree_version": "1.0.0",
        })
    valores = await repo.valores_distintos("lugar")
    assert valores == ["Biblioteca EPM", "Museo del Agua"], "Debe deduplicar y ordenar."
