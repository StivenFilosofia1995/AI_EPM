"""
Preparación de la cuenta de administración al arrancar.

Regresión que motivó estas pruebas: la versión anterior solo creaba la cuenta
cuando no existía y nunca sincronizaba la contraseña. Cambiar ADMIN_PASSWORD
en el panel de despliegue no surtía ningún efecto, y no había forma de
recuperar el acceso sin entrar a la base de datos a mano.

La regla que verifican: las variables de entorno mandan.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import auth_service, bootstrap

pytestmark = pytest.mark.asyncio

CORREO = "administracion@example.com"


@pytest.fixture
def con_variables(monkeypatch):
    """Simula Supabase configurado con ADMIN_EMAIL y ADMIN_PASSWORD."""
    monkeypatch.setattr("app.services.bootstrap.modo_demostracion", lambda: False)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", CORREO)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "consolidacion2026")
    return settings


# ─── Creación ───────────────────────────────────────────────────────────────


async def test_crea_la_cuenta_si_no_existe(cliente, con_variables):
    await bootstrap.asegurar_admin()

    usuario = await auth_service.get_user_by_email(CORREO)
    assert usuario is not None
    assert usuario["rol"] == "admin"
    assert usuario["activo"] is True


async def test_se_puede_entrar_con_la_contrasena_de_la_variable(cliente, con_variables):
    await bootstrap.asegurar_admin()

    usuario = await auth_service.authenticate(CORREO, "consolidacion2026")
    assert usuario["rol"] == "admin"


async def test_no_exige_cambiar_la_contrasena_al_entrar(cliente, con_variables):
    """La definió el dueño del sistema: no hay contraseña temporal."""
    await bootstrap.asegurar_admin()

    usuario = await auth_service.get_user_by_email(CORREO)
    assert usuario["debe_cambiar_password"] is False


async def test_una_contrasena_debil_no_impide_crear_la_cuenta(cliente, con_variables, monkeypatch):
    """
    Bloquear aquí dejaba la aplicación sin ninguna cuenta con la que entrar,
    y el síntoma era un fallo de acceso que no apuntaba a la causa.
    """
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "123456789")
    await bootstrap.asegurar_admin()

    usuario = await auth_service.authenticate(CORREO, "123456789")
    assert usuario["rol"] == "admin"


# ─── Sincronización: la variable manda ──────────────────────────────────────


async def test_cambiar_la_variable_cambia_la_contrasena(cliente, con_variables, monkeypatch):
    """El fallo original: la cuenta existía y la variable se ignoraba."""
    await bootstrap.asegurar_admin()
    await auth_service.authenticate(CORREO, "consolidacion2026")

    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "otraClave2026")
    await bootstrap.asegurar_admin()

    usuario = await auth_service.authenticate(CORREO, "otraClave2026")
    assert usuario["rol"] == "admin"

    with pytest.raises(auth_service.AuthError):
        await auth_service.authenticate(CORREO, "consolidacion2026")


async def test_no_se_duplica_la_cuenta_al_sincronizar(cliente, con_variables, monkeypatch):
    await bootstrap.asegurar_admin()
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "otraClave2026")
    await bootstrap.asegurar_admin()
    await bootstrap.asegurar_admin()

    cuentas = [u for u in cliente.filas("epm_users") if u["email"] == CORREO]
    assert len(cuentas) == 1


async def test_reactiva_una_cuenta_desactivada(cliente, con_variables):
    await bootstrap.asegurar_admin()
    usuario = await auth_service.get_user_by_email(CORREO)
    await auth_service.set_activo(usuario["id"], False)

    await bootstrap.asegurar_admin()

    actual = await auth_service.get_user_by_email(CORREO)
    assert actual["activo"] is True


async def test_devuelve_el_rol_admin_si_alguien_lo_bajo(cliente, con_variables):
    await bootstrap.asegurar_admin()
    usuario = await auth_service.get_user_by_email(CORREO)
    await auth_service.set_rol(usuario["id"], "facilitador")

    await bootstrap.asegurar_admin()

    actual = await auth_service.get_user_by_email(CORREO)
    assert actual["rol"] == "admin"


async def test_desbloquea_la_cuenta_al_sincronizar(cliente, con_variables, monkeypatch):
    """Cinco intentos fallidos no deben dejar al dueño fuera de su sistema."""
    await bootstrap.asegurar_admin()
    for _ in range(6):
        with pytest.raises(auth_service.AuthError):
            await auth_service.authenticate(CORREO, "equivocada123")

    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "otraClave2026")
    await bootstrap.asegurar_admin()

    usuario = await auth_service.authenticate(CORREO, "otraClave2026")
    assert usuario["rol"] == "admin"


async def test_si_la_contrasena_ya_coincide_no_se_toca_nada(cliente, con_variables):
    await bootstrap.asegurar_admin()
    antes = await auth_service.get_user_by_email(CORREO)

    await bootstrap.asegurar_admin()
    despues = await auth_service.get_user_by_email(CORREO)

    assert antes["password_hash"] == despues["password_hash"], (
        "Rehashear en cada arranque invalidaría sesiones sin motivo."
    )


# ─── Cuándo NO debe actuar ──────────────────────────────────────────────────


async def test_sin_variables_no_hace_nada(cliente, monkeypatch):
    monkeypatch.setattr("app.services.bootstrap.modo_demostracion", lambda: False)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", None)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)

    await bootstrap.asegurar_admin()
    assert cliente.filas("epm_users") == []


async def test_con_correo_pero_sin_contrasena_no_crea_nada(cliente, monkeypatch):
    monkeypatch.setattr("app.services.bootstrap.modo_demostracion", lambda: False)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", CORREO)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)

    await bootstrap.asegurar_admin()
    assert cliente.filas("epm_users") == []


async def test_el_correo_se_normaliza(cliente, con_variables, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "  ADMINISTRACION@Example.COM  ")
    await bootstrap.asegurar_admin()

    assert await auth_service.get_user_by_email(CORREO) is not None
