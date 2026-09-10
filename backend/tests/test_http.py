"""
Peticiones HTTP reales contra la aplicación.

Existen por una razón concreta: las pruebas que solo inspeccionan las
dependencias de cada ruta no detectaron que FastAPI no lograba resolver la
anotación `Request` de los limitadores de tasa, y toda ruta limitada
respondía 422 pidiendo un campo llamado "request". Solo una petición de
verdad lo saca a la luz.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.fields import LINEAS_ACCION, PROGRAMAS


@pytest.fixture(autouse=True)
def _sin_limite_de_tasa():
    """
    Los contadores viven en memoria del módulo y las pruebas comparten IP.
    Sin esto, a partir del sexto registro todas responderían 429 y el fallo
    parecería del endpoint.
    """
    from app.dependencies import _buckets

    _buckets.clear()
    yield
    _buckets.clear()


@pytest.fixture
def app_cliente(cliente, monkeypatch):
    """TestClient con la base de datos simulada y el arranque completo."""
    monkeypatch.setattr("app.services.bootstrap.modo_demostracion", lambda: False)
    from app.main import app

    with TestClient(app) as c:
        yield c


REGISTRO = {
    "nombre": "Ana Restrepo",
    "email": "ana.restrepo@example.com",
    "password": "consolidacion2026",
    "cargo": "Mediadora de lectura",
    "programa": PROGRAMAS[0],
    "lineas_accion": [LINEAS_ACCION[0]],
    "temas": "Clubes de lectura juvenil",
}


# ─── Rutas limitadas por tasa ───────────────────────────────────────────────


def test_el_registro_no_pide_un_campo_llamado_request(app_cliente):
    """
    Regresión: los limitadores eran instancias de clase y FastAPI no podía
    resolver su anotación `Request`, así que la trataba como campo del cuerpo.
    """
    r = app_cliente.post("/api/auth/registro", json=REGISTRO)
    assert r.status_code != 422 or "request" not in r.text, (
        f"La ruta pide un campo 'request': {r.text}"
    )


def test_el_registro_crea_la_cuenta_y_devuelve_token(app_cliente):
    r = app_cliente.post("/api/auth/registro", json=REGISTRO)
    assert r.status_code == 201, r.text
    datos = r.json()
    assert datos["user"]["rol"] == "facilitador"
    assert datos["access_token"]
    assert datos["debe_cambiar_password"] is False


def test_el_registro_ignora_el_rol_que_venga_en_el_cuerpo(app_cliente):
    """Escalada de privilegios: el cuerpo no decide el rol."""
    r = app_cliente.post("/api/auth/registro", json={**REGISTRO, "rol": "admin"})
    assert r.status_code == 201, r.text
    assert r.json()["user"]["rol"] == "facilitador"


def test_el_login_responde_sin_pedir_request(app_cliente):
    app_cliente.post("/api/auth/registro", json=REGISTRO)
    r = app_cliente.post(
        "/api/auth/login",
        json={"email": REGISTRO["email"], "password": REGISTRO["password"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == REGISTRO["email"]


def test_credenciales_incorrectas_devuelven_401_con_mensaje_en_espanol(app_cliente):
    app_cliente.post("/api/auth/registro", json=REGISTRO)
    r = app_cliente.post(
        "/api/auth/login",
        json={"email": REGISTRO["email"], "password": "otraCosa12345"},
    )
    assert r.status_code == 401
    assert "incorrect" in r.json()["detail"].lower()


# ─── Catálogos públicos ─────────────────────────────────────────────────────


def test_las_opciones_de_registro_son_publicas(app_cliente):
    r = app_cliente.get("/api/auth/registro/opciones")
    assert r.status_code == 200
    datos = r.json()
    assert datos["programas"] == list(PROGRAMAS)
    assert datos["lineas_accion"] == list(LINEAS_ACCION)


# ─── Autenticación obligatoria ──────────────────────────────────────────────


@pytest.mark.parametrize("metodo,ruta", [
    ("post", "/api/tree/session"),
    ("get", "/api/tree/sessions"),
    ("get", "/api/admin/sesiones"),
    ("get", "/api/auth/me"),
    ("post", "/api/excel/generate"),
])
def test_las_rutas_de_datos_exigen_token(app_cliente, metodo, ruta):
    kwargs = {"json": {}} if metodo == "post" else {}
    r = getattr(app_cliente, metodo)(ruta, **kwargs)
    assert r.status_code == 401, f"{ruta} respondió {r.status_code}"


def test_un_facilitador_no_entra_a_administracion(app_cliente):
    registro = app_cliente.post("/api/auth/registro", json=REGISTRO).json()
    cabeceras = {"Authorization": f"Bearer {registro['access_token']}"}
    r = app_cliente.get("/api/admin/sesiones", headers=cabeceras)
    assert r.status_code == 403


# ─── Errores en español ─────────────────────────────────────────────────────


def test_los_errores_de_validacion_salen_en_espanol(app_cliente):
    r = app_cliente.post("/api/auth/registro", json={"nombre": "A"})
    assert r.status_code == 422
    texto = r.json()["detail"]
    assert "obligatorio" in texto or "corto" in texto, texto


def test_un_endpoint_inexistente_responde_404_json(app_cliente):
    """El catch-all ya no devuelve 200 con HTML para rutas /api mal escritas."""
    r = app_cliente.get("/api/no-existe")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


# ─── Recorrido mínimo del árbol ─────────────────────────────────────────────


def test_recorrido_basico_del_arbol(app_cliente):
    registro = app_cliente.post("/api/auth/registro", json=REGISTRO).json()
    cabeceras = {"Authorization": f"Bearer {registro['access_token']}"}

    sesion = app_cliente.post("/api/tree/session", headers=cabeceras)
    assert sesion.status_code == 201, sesion.text
    datos = sesion.json()
    session_id = datos["session_id"]
    assert datos["node"]["node_id"] == "q00_intencion"

    r = app_cliente.post(
        f"/api/tree/session/{session_id}/answer",
        headers=cabeceras,
        json={"node_id": "q00_intencion", "value": "Consolidar una actividad que ya realicé"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["node"]["node_id"] == "q02_programa"


def test_una_respuesta_invalida_devuelve_errores_estructurados(app_cliente):
    registro = app_cliente.post("/api/auth/registro", json=REGISTRO).json()
    cabeceras = {"Authorization": f"Bearer {registro['access_token']}"}
    session_id = app_cliente.post("/api/tree/session", headers=cabeceras).json()["session_id"]

    r = app_cliente.post(
        f"/api/tree/session/{session_id}/answer",
        headers=cabeceras,
        json={"node_id": "q00_intencion", "value": "Etapa inventada"},
    )
    assert r.status_code == 422
    errores = r.json()["detail"]["errors"]
    assert errores[0]["code"] == "opcion_invalida"


def test_no_se_puede_ver_la_sesion_de_otra_persona(app_cliente):
    primera = app_cliente.post("/api/auth/registro", json=REGISTRO).json()
    cab1 = {"Authorization": f"Bearer {primera['access_token']}"}
    session_id = app_cliente.post("/api/tree/session", headers=cab1).json()["session_id"]

    segunda = app_cliente.post("/api/auth/registro", json={
        **REGISTRO, "email": "otra.persona@example.com", "nombre": "Otra Persona",
    }).json()
    cab2 = {"Authorization": f"Bearer {segunda['access_token']}"}

    r = app_cliente.get(f"/api/tree/session/{session_id}/current", headers=cab2)
    # 404, no 403: no se revela que la sesión existe.
    assert r.status_code == 404


# ─── Los errores deben decir QUÉ campo y CUÁL es la regla ───────────────────
# Regresión: un formulario con tres campos de longitud mínima devolvía
# "El texto es demasiado corto." sin decir cuál, obligando a adivinar.


@pytest.mark.parametrize("campo,valor,esperado", [
    ("cargo", "X", "cargo"),
    ("nombre", "A", "nombre"),
    ("password", "corta", "contraseña"),
])
def test_el_error_nombra_el_campo_corto(app_cliente, campo, valor, esperado):
    r = app_cliente.post("/api/auth/registro", json={**REGISTRO, campo: valor})
    assert r.status_code == 422
    texto = r.json()["detail"].lower()
    assert esperado in texto, f"El mensaje no nombra el campo: {texto}"
    assert "caracteres" in texto, f"El mensaje no dice el mínimo: {texto}"


def test_el_error_indica_el_minimo_exacto(app_cliente):
    r = app_cliente.post("/api/auth/registro", json={**REGISTRO, "password": "corta"})
    assert "10 caracteres" in r.json()["detail"]


def test_el_error_de_campo_faltante_lo_nombra(app_cliente):
    cuerpo = {k: v for k, v in REGISTRO.items() if k != "cargo"}
    r = app_cliente.post("/api/auth/registro", json=cuerpo)
    assert r.status_code == 422
    assert "cargo" in r.json()["detail"].lower()
    assert "obligatorio" in r.json()["detail"].lower()


def test_el_error_de_correo_invalido_lo_nombra(app_cliente):
    r = app_cliente.post("/api/auth/registro", json={**REGISTRO, "email": "no-es-correo"})
    assert r.status_code == 422
    assert "correo" in r.json()["detail"].lower()


def test_los_errores_vienen_por_campo_no_solo_como_resumen(app_cliente):
    """El frontend los pinta junto al control que los causa."""
    r = app_cliente.post("/api/auth/registro",
                         json={**REGISTRO, "cargo": "X", "password": "corta"})
    errores = r.json()["errors"]
    campos = {e["field_key"] for e in errores}
    assert {"cargo", "password"} <= campos
    for e in errores:
        assert set(e) == {"field_key", "code", "message"}


def test_ningun_mensaje_queda_en_ingles(app_cliente):
    r = app_cliente.post("/api/auth/registro", json={"nombre": "A", "email": "x"})
    texto = r.json()["detail"].lower()
    for palabra in ("string", "should", "field required", "value is not"):
        assert palabra not in texto, f"Quedó jerga en inglés: {texto}"
