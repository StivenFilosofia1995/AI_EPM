"""
Etapa de análisis e ideas: validación estricta del JSON.

La sección 11 pide cubrir la validación del esquema con una respuesta
malformada simulada. Aquí se simulan varias, incluyendo el caso en que el
modelo inventa valores que no están en las enumeraciones institucionales.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain import fields as F
from app.services import ideas_service as srv
from app.services.ideas_service import Ideas, IdeasError, Sugerencias, _extraer_json

# Solo las pruebas de comportamiento son asincronas; las de esquema no.


def idea_valida(**cambios):
    base = {
        "nombre": "Ruta del agua en el barrio",
        "publico_sugerido": "Jóvenes",
        "tipo_actividad": "Taller",
        "pregunta_problematizadora": "¿De dónde viene el agua que tomamos?",
        "ods": [F.ODS[5]],
        "justificacion": "Se deriva de la metodología registrada.",
    }
    base.update(cambios)
    return base


# ─── Extracción del JSON ────────────────────────────────────────────────────


def test_json_limpio():
    assert _extraer_json('{"a": 1}') == {"a": 1}


def test_json_envuelto_en_markdown():
    assert _extraer_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_con_texto_alrededor():
    texto = 'Claro, aquí tienes:\n{"a": 1}\nEspero que sirva.'
    assert _extraer_json(texto) == {"a": 1}


def test_sin_json_lanza_error():
    with pytest.raises(IdeasError, match="no contiene un objeto JSON"):
        _extraer_json("No puedo generar eso.")


def test_json_mal_formado_lanza_error():
    with pytest.raises(IdeasError, match="mal formado"):
        _extraer_json('{"a": 1,, }')


# ─── Esquema de ideas ───────────────────────────────────────────────────────


def test_ideas_validas():
    modelo = Ideas(ideas=[idea_valida() for _ in range(3)])
    assert len(modelo.ideas) == 3


def test_rechaza_publico_inventado():
    with pytest.raises(ValidationError, match="publico_sugerido"):
        Ideas(ideas=[idea_valida(publico_sugerido="Estudiantes universitarios")] * 3)


def test_rechaza_tipo_de_actividad_inventado():
    with pytest.raises(ValidationError, match="tipo_actividad"):
        Ideas(ideas=[idea_valida(tipo_actividad="Conversatorio")] * 3)


def test_rechaza_ods_inventado():
    with pytest.raises(ValidationError, match="ODS"):
        Ideas(ideas=[idea_valida(ods=["18. Turismo sostenible"])] * 3)


@pytest.mark.parametrize("cantidad", [0, 1, 2, 6, 10])
def test_rechaza_cantidad_de_ideas_fuera_de_rango(cantidad):
    with pytest.raises(ValidationError):
        Ideas(ideas=[idea_valida() for _ in range(cantidad)])


def test_rechaza_idea_sin_campos_obligatorios():
    with pytest.raises(ValidationError):
        Ideas(ideas=[{"nombre": "Solo el nombre"}] * 3)


# ─── Esquema de sugerencias ─────────────────────────────────────────────────


def test_sugerencias_validas():
    s = Sugerencias(sugerencias=["Primera versión", "Segunda versión"])
    assert len(s.sugerencias) == 2


def test_sugerencias_recorta_a_tres():
    s = Sugerencias(sugerencias=[f"v{i}" for i in range(8)])
    assert len(s.sugerencias) == 3


def test_sugerencias_descarta_vacias():
    s = Sugerencias(sugerencias=["  ", "", "Una útil"])
    assert s.sugerencias == ["Una útil"]


def test_sugerencias_todas_vacias_falla():
    with pytest.raises(ValidationError):
        Sugerencias(sugerencias=["", "   "])


# ─── Comportamiento ante fallos del modelo ──────────────────────────────────


async def _preparar_sesion(cliente, monkeypatch):
    """Sesión mínima con datos, para que el análisis tenga de dónde partir."""
    cliente.table("epm_respuestas").filas.extend([
        {"id": "1", "session_id": "s1", "node_id": "q05_nombre", "field_key": "nombre",
         "valor": "Taller de agua", "stale": False, "es_valida": True, "tree_version": "1.1.0"},
        {"id": "2", "session_id": "s1", "node_id": "q13_metodologia", "field_key": "metodologia",
         "valor": "Aprendizaje basado en preguntas", "stale": False, "es_valida": True,
         "tree_version": "1.1.0"},
    ])


@pytest.mark.asyncio
async def test_ideas_malformadas_reintentan_y_luego_fallan_explicitamente(
    cliente, monkeypatch
):
    await _preparar_sesion(cliente, monkeypatch)
    llamadas = []

    async def falso_complete(system, prompt, temperature=None, max_tokens=None):
        llamadas.append(prompt)
        if "IDEAS" in prompt:
            return ('{"ideas": [{"nombre": "x", "publico_sugerido": "Marcianos", '
                    '"tipo_actividad": "Taller", "pregunta_problematizadora": "¿?", '
                    '"ods": []}]}', 10, 10)
        return ("Texto de la pieza.", 10, 10)

    monkeypatch.setattr(srv, "complete", falso_complete)

    r = await srv.generar_analisis("s1", "u1")

    ideas_pedidas = [p for p in llamadas if "IDEAS" in p]
    assert len(ideas_pedidas) == 2, "Debe reintentar exactamente una vez."
    assert "descartada" in ideas_pedidas[1], "El reintento debe indicar el motivo."
    assert r["ideas"] == []
    assert any("ideas:" in e for e in r["errores"])
    # Las piezas de texto sí se conservan: el fallo de las ideas no las anula.
    assert r["resumen"] == "Texto de la pieza."


@pytest.mark.asyncio
async def test_el_fallo_de_una_pieza_no_tumba_las_demas(cliente, monkeypatch):
    await _preparar_sesion(cliente, monkeypatch)

    async def falso_complete(system, prompt, temperature=None, max_tokens=None):
        if "ANALISIS" in prompt:
            raise RuntimeError("El modelo no respondió.")
        if "IDEAS" in prompt:
            import json
            return (json.dumps({"ideas": [idea_valida() for _ in range(3)]}), 10, 10)
        return ("Contenido.", 10, 10)

    monkeypatch.setattr(srv, "complete", falso_complete)

    r = await srv.generar_analisis("s1", "u1")
    assert r["analisis"] is None
    assert r["resumen"] == "Contenido."
    assert r["recomendaciones"] == "Contenido."
    assert len(r["ideas"]) == 3


@pytest.mark.asyncio
async def test_sin_datos_no_se_llama_al_modelo(cliente, monkeypatch):
    async def no_debe_llamarse(*a, **k):
        raise AssertionError("No debía llamarse al modelo sin datos.")

    monkeypatch.setattr(srv, "complete", no_debe_llamarse)

    with pytest.raises(IdeasError, match="no tiene datos consolidados"):
        await srv.generar_analisis("sesion-vacia", "u1")


@pytest.mark.asyncio
async def test_sugerencia_con_borrador_muy_corto_no_llama_al_modelo(cliente, monkeypatch):
    async def no_debe_llamarse(*a, **k):
        raise AssertionError("No debía llamarse al modelo.")

    monkeypatch.setattr(srv, "complete", no_debe_llamarse)
    assert await srv.sugerir_redaccion("s1", "q13_metodologia", "corto") == []


@pytest.mark.asyncio
async def test_sugerencia_malformada_devuelve_lista_vacia(cliente, monkeypatch):
    await _preparar_sesion(cliente, monkeypatch)

    async def falso_complete(system, prompt, temperature=None, max_tokens=None):
        return ("No sé qué responder.", 5, 5)

    monkeypatch.setattr(srv, "complete", falso_complete)

    # No lanza: la sugerencia nunca debe bloquear la captura.
    assert await srv.sugerir_redaccion(
        "s1", "q13_metodologia", "Un borrador suficientemente largo para procesar"
    ) == []


@pytest.mark.asyncio
async def test_el_prompt_incluye_las_enumeraciones_validas(cliente, monkeypatch):
    await _preparar_sesion(cliente, monkeypatch)
    capturados = []

    async def falso_complete(system, prompt, temperature=None, max_tokens=None):
        capturados.append(prompt)
        import json
        if "IDEAS" in prompt:
            return (json.dumps({"ideas": [idea_valida() for _ in range(3)]}), 10, 10)
        return ("Contenido.", 10, 10)

    monkeypatch.setattr(srv, "complete", falso_complete)
    await srv.generar_analisis("s1", "u1")

    prompt_ideas = next(p for p in capturados if "IDEAS" in p)
    assert "PUBLICOS válidos" in prompt_ideas
    assert "Taller" in prompt_ideas
    assert F.ODS[0] in prompt_ideas


@pytest.mark.asyncio
async def test_los_campos_vacios_se_marcan_en_el_contexto(cliente, monkeypatch):
    await _preparar_sesion(cliente, monkeypatch)
    capturados = []

    async def falso_complete(system, prompt, temperature=None, max_tokens=None):
        capturados.append(prompt)
        return ("Contenido.", 10, 10)

    monkeypatch.setattr(srv, "complete", falso_complete)
    await srv.generar_analisis("s1", "u1")

    assert "(SIN DILIGENCIAR)" in capturados[0], (
        "El contexto debe declarar los campos vacíos en vez de omitirlos."
    )


def test_los_prompts_estan_versionados_en_archivos():
    assert srv.PROMPT_ANALISIS.exists()
    assert srv.PROMPT_SUGERENCIA.exists()
    _, hash_a = srv._leer_prompt(srv.PROMPT_ANALISIS)
    _, hash_b = srv._leer_prompt(srv.PROMPT_SUGERENCIA)
    assert hash_a != hash_b
    assert len(hash_a) == 16


def test_el_prompt_prohibe_inventar():
    texto = srv.PROMPT_ANALISIS.read_text(encoding="utf-8")
    assert "No inventes" in texto
    assert "cita el campo de origen" in texto.lower() or "campo de origen" in texto
