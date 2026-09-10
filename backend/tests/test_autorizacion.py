"""
Ninguna ruta de datos puede saltarse la autenticación.

Esta prueba es la compensación por haber elegido JWT propio en lugar de
Supabase Auth: como el RLS no puede filtrar por usuario, la autorización
depende enteramente de que cada ruta declare la dependencia. Si alguien
añade un endpoint y olvida el Depends, esto falla.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.dependencies import (
    es_limitador,
    get_current_user,
)
from app.main import app

# Rutas públicas por diseño. Cualquier adición aquí es una decisión explícita.
PUBLICAS = {
    ("/api/health", "GET"),
    ("/api/auth/login", "POST"),
    # El registro es abierto por decisión de producto. El rol resultante
    # siempre es 'facilitador': lo fuerza auth_service, no el formulario.
    ("/api/auth/registro", "POST"),
    ("/api/auth/registro/opciones", "GET"),
    ("/api/docs", "GET"),
    ("/api/redoc", "GET"),
    ("/api/openapi.json", "GET"),
}


def _rutas_api():
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        if not r.path.startswith("/api"):
            continue
        for metodo in r.methods - {"HEAD", "OPTIONS"}:
            yield r, metodo


def _protege(ruta: APIRoute) -> bool:
    """La ruta exige identidad, por dependencia directa o por una derivada."""
    for dep in ruta.dependant.dependencies:
        call = dep.call
        if call is get_current_user:
            return True
        if es_limitador(call):
            return True
        # require_role devuelve una closure con get_current_user dentro.
        for sub in dep.dependencies:
            if sub.call is get_current_user:
                return True
    return False


def test_toda_ruta_de_datos_exige_autenticacion():
    desprotegidas = [
        f"{metodo} {r.path}"
        for r, metodo in _rutas_api()
        if (r.path, metodo) not in PUBLICAS and not _protege(r)
    ]
    assert not desprotegidas, (
        "Estas rutas no verifican identidad: " + ", ".join(sorted(desprotegidas))
    )


def test_las_rutas_de_administracion_exigen_rol():
    sin_rol = []
    for r, metodo in _rutas_api():
        if not r.path.startswith("/api/admin"):
            continue
        nombres = {getattr(d.call, "__qualname__", "") for d in r.dependant.dependencies}
        if not any("_check" in n for n in nombres):
            sin_rol.append(f"{metodo} {r.path}")
    assert not sin_rol, (
        "Estas rutas de administración no exigen rol: " + ", ".join(sorted(sin_rol))
    )


def test_las_rutas_que_llaman_al_modelo_estan_limitadas_por_tasa():
    sin_limite = []
    for r, metodo in _rutas_api():
        if not r.path.startswith("/api/ideas"):
            continue
        if not any(es_limitador(d.call) for d in r.dependant.dependencies):
            sin_limite.append(f"{metodo} {r.path}")
    assert not sin_limite, (
        "Estas rutas llaman al modelo sin límite de tasa: " + ", ".join(sorted(sin_limite))
    )


def test_el_envio_de_correo_esta_limitado_por_tasa():
    ruta = next(r for r, m in _rutas_api() if r.path == "/api/email/send" and m == "POST")
    assert any(es_limitador(d.call) for d in ruta.dependant.dependencies)


def test_los_endpoints_obsoletos_estan_marcados():
    obsoletos = {"/api/chat", "/api/form/update", "/api/form/{session_id}"}
    for r, _ in _rutas_api():
        if r.path in obsoletos:
            assert r.deprecated, f"{r.path} debería estar marcado como deprecated."


def test_no_quedan_rutas_de_administracion_por_pin():
    """El PIN en el parámetro de URL fue eliminado."""
    for r, _ in _rutas_api():
        nombres = {p.name for p in r.dependant.query_params}
        assert "pin" not in nombres, f"{r.path} todavía recibe un PIN por query."


def test_cors_no_admite_comodin():
    from app.main import _origins

    assert "*" not in _origins


@pytest.mark.parametrize("ruta_esperada", [
    "/api/tree/session",
    "/api/tree/session/{session_id}/current",
    "/api/tree/session/{session_id}/answer",
    "/api/tree/session/{session_id}/back",
    "/api/tree/session/{session_id}/summary",
    "/api/tree/session/{session_id}/finalize",
    "/api/tree/sessions",
])
def test_los_endpoints_del_arbol_existen(ruta_esperada):
    assert ruta_esperada in {r.path for r, _ in _rutas_api()}


@pytest.mark.parametrize("ruta_esperada", [
    "/api/excel/generate",
    "/api/excel/lote",
    "/api/email/send",
    "/api/health",
])
def test_los_endpoints_conservados_siguen_existiendo(ruta_esperada):
    assert ruta_esperada in {r.path for r, _ in _rutas_api()}


def test_ya_no_hay_rutas_de_google_sheets():
    """La integración con Sheets se retiró por completo."""
    rutas = {r.path for r, _ in _rutas_api()}
    assert not [r for r in rutas if "sheets" in r]
