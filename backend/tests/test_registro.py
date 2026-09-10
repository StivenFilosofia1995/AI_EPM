"""
Registro abierto y perfil profesional.

La prueba central es la de escalada de privilegios: el registro es público,
así que si el rol se tomara del cuerpo de la petición, cualquiera se haría
administrador desde el formulario.
"""

from __future__ import annotations

import pytest

from app.domain.fields import LINEAS_ACCION, PROGRAMAS
from app.services import auth_service
from app.services.auth_service import AuthError

pytestmark = pytest.mark.asyncio

BASE = {
    "email": "Ana.Restrepo@example.com",
    "nombre": "Ana Restrepo",
    "password": "consolidacion2026",
    "cargo": "Mediadora de lectura",
}


async def registrar(cliente, **cambios):
    datos = {**BASE, **cambios}
    return await auth_service.registrar_usuario(**datos)


# ─── Alta correcta ──────────────────────────────────────────────────────────


async def test_registro_crea_la_cuenta(cliente):
    u = await registrar(cliente)
    assert u["nombre"] == "Ana Restrepo"
    assert u["activo"] is True
    assert u["auto_registrado"] is True


async def test_el_correo_se_normaliza_a_minusculas(cliente):
    u = await registrar(cliente)
    assert u["email"] == "ana.restrepo@example.com"


async def test_quien_se_registra_no_debe_cambiar_la_contrasena(cliente):
    """La eligió esa persona: no hay contraseña temporal que reemplazar."""
    u = await registrar(cliente)
    assert u["debe_cambiar_password"] is False


async def test_el_perfil_profesional_se_guarda(cliente):
    u = await registrar(
        cliente,
        programa=PROGRAMAS[0],
        lineas_accion=[LINEAS_ACCION[0], LINEAS_ACCION[3]],
        temas="Cuidado del agua con primera infancia",
        telefono="3001234567",
    )
    assert u["cargo"] == "Mediadora de lectura"
    assert u["programa"] == PROGRAMAS[0]
    assert u["lineas_accion"] == [LINEAS_ACCION[0], LINEAS_ACCION[3]]
    assert u["temas"] == "Cuidado del agua con primera infancia"
    assert u["telefono"] == "3001234567"


async def test_la_contrasena_se_guarda_como_hash(cliente):
    u = await registrar(cliente)
    assert u["password_hash"] != BASE["password"]
    assert u["password_hash"].startswith("$argon2")
    assert auth_service.verify_password(BASE["password"], u["password_hash"])


async def test_puede_autenticarse_despues_de_registrarse(cliente):
    await registrar(cliente)
    u = await auth_service.authenticate("ana.restrepo@example.com", BASE["password"])
    assert u["nombre"] == "Ana Restrepo"


# ─── Escalada de privilegios ────────────────────────────────────────────────


async def test_el_registro_siempre_produce_rol_facilitador(cliente):
    u = await registrar(cliente)
    assert u["rol"] == "facilitador"


async def test_no_se_puede_pedir_otro_rol_al_registrarse(cliente):
    """
    registrar_usuario no acepta el parámetro `rol`: el rol lo fija ella misma.
    Si alguien lo añadiera a la firma, esta prueba lo detecta.
    """
    import inspect

    firma = inspect.signature(auth_service.registrar_usuario)
    assert "rol" not in firma.parameters, (
        "registrar_usuario no debe aceptar el rol: el registro es público."
    )


async def test_el_token_del_registro_lleva_rol_facilitador(cliente):
    u = await registrar(cliente)
    token, _ = auth_service.create_access_token(u)
    assert auth_service.decode_token(token)["rol"] == "facilitador"


# ─── Validaciones ───────────────────────────────────────────────────────────


async def test_correo_duplicado_se_rechaza(cliente):
    await registrar(cliente)
    with pytest.raises(AuthError, match="Ya existe una cuenta"):
        await registrar(cliente)


async def test_correo_duplicado_ignorando_mayusculas(cliente):
    await registrar(cliente)
    with pytest.raises(AuthError, match="Ya existe una cuenta"):
        await registrar(cliente, email="ANA.RESTREPO@example.com")


@pytest.mark.parametrize("password", ["corta", "sinnumeros", "1234567890", "abc123"])
async def test_contrasena_debil_se_rechaza(cliente, password):
    with pytest.raises(AuthError):
        await registrar(cliente, password=password)


async def test_programa_inventado_se_rechaza(cliente):
    with pytest.raises(AuthError, match="Programa no válido"):
        await registrar(cliente, programa="Biblioteca Municipal")


async def test_linea_de_accion_inventada_se_rechaza(cliente):
    with pytest.raises(AuthError, match="Líneas de acción no válidas"):
        await registrar(cliente, lineas_accion=["Innovación digital"])


async def test_cargo_demasiado_corto_se_rechaza(cliente):
    with pytest.raises(AuthError, match="a qué te dedicas"):
        await registrar(cliente, cargo="X")


async def test_sin_programa_es_valido(cliente):
    u = await registrar(cliente, programa=None)
    assert u["programa"] is None


# ─── Perfil ─────────────────────────────────────────────────────────────────


async def test_actualizar_perfil_cambia_los_campos(cliente):
    u = await registrar(cliente)
    await auth_service.actualizar_perfil(u["id"], {
        "cargo": "Coordinadora de semilleros",
        "temas": "Semilleros de ciencia",
    })
    actual = await auth_service.get_user_by_id(u["id"])
    assert actual["cargo"] == "Coordinadora de semilleros"
    assert actual["temas"] == "Semilleros de ciencia"


async def test_actualizar_perfil_no_puede_cambiar_el_rol(cliente):
    u = await registrar(cliente)
    await auth_service.actualizar_perfil(u["id"], {
        "cargo": "Coordinadora", "rol": "admin", "activo": False,
    })
    actual = await auth_service.get_user_by_id(u["id"])
    assert actual["rol"] == "facilitador", "El perfil no debe permitir subir de rol."
    assert actual["activo"] is True, "El perfil no debe permitir cambiar el estado."


async def test_actualizar_perfil_valida_los_catalogos(cliente):
    u = await registrar(cliente)
    with pytest.raises(AuthError, match="Líneas de acción no válidas"):
        await auth_service.actualizar_perfil(u["id"], {"lineas_accion": ["Otra cosa"]})


async def test_actualizar_perfil_sin_cambios_falla(cliente):
    u = await registrar(cliente)
    with pytest.raises(AuthError, match="nada que actualizar"):
        await auth_service.actualizar_perfil(u["id"], {"password_hash": "intento"})


# ─── Convivencia con el alta desde el panel ─────────────────────────────────


async def test_la_cuenta_creada_por_admin_no_queda_auto_registrada(cliente):
    u = await auth_service.create_user(
        email="creada@example.com", nombre="Persona Creada",
        password="temporal2026x", rol="facilitador", creado_por="admin-id",
    )
    assert u["auto_registrado"] is False
    assert u["debe_cambiar_password"] is True, (
        "Quien recibe una contraseña temporal debe cambiarla."
    )


async def test_un_admin_si_puede_crear_otro_admin(cliente):
    u = await auth_service.create_user(
        email="coordina@example.com", nombre="Coordinadora General",
        password="coordinacion2026", rol="coordinador", creado_por="admin-id",
    )
    assert u["rol"] == "coordinador"


async def test_create_user_rechaza_un_rol_inventado(cliente):
    with pytest.raises(AuthError, match="Rol inválido"):
        await auth_service.create_user(
            email="x@example.com", nombre="Alguien", password="password2026",
            rol="superusuario",
        )
