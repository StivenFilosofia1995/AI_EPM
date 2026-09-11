"""Rutas de autenticación y gestión de cuentas."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import (
    get_current_user,
    limitar_login,
    limitar_registro,
    require_admin,
    require_supervision,
)
from app.domain.fields import LINEAS_ACCION, PROGRAMAS
from app.services import auth_service
from app.services.auth_service import AuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["autenticación"])


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    debe_cambiar_password: bool
    user: dict


@router.post("/login", response_model=LoginResponse,
             dependencies=[Depends(limitar_login)])
async def login(body: LoginBody):
    try:
        user = await auth_service.authenticate(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token, expires_in = auth_service.create_access_token(user)
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        debe_cambiar_password=bool(user.get("debe_cambiar_password")),
        user={
            "id": user["id"],
            "email": user["email"],
            "nombre": user["nombre"],
            "rol": user["rol"],
            "programa": user.get("programa"),
        },
    )


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


class CambioPasswordBody(BaseModel):
    password_actual: str
    password_nueva: str


@router.post("/cambiar-password")
async def cambiar_password(
    body: CambioPasswordBody, user: dict = Depends(get_current_user)
):
    completo = await auth_service.get_user_by_id(user["id"])
    if completo is None:
        raise HTTPException(status_code=404, detail="La cuenta no existe.")

    if not auth_service.verify_password(
        body.password_actual, completo.get("password_hash", "")
    ):
        raise HTTPException(status_code=401, detail="La contraseña actual no es correcta.")

    try:
        await auth_service.change_password(user["id"], body.password_nueva)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"ok": True}


# ─── Registro abierto ───────────────────────────────────────────────────────


@router.get("/registro/opciones")
async def opciones_registro():
    """Catálogos para pintar el formulario. Público, sin datos sensibles."""
    return {
        "programas": list(PROGRAMAS),
        "lineas_accion": list(LINEAS_ACCION),
    }


class RegistroBody(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    # A qué se dedica
    cargo: str = Field(min_length=3, max_length=120)
    programa: str | None = None
    telefono: str | None = Field(default=None, max_length=40)
    # Qué forma
    lineas_accion: list[str] = Field(default_factory=list)
    temas: str | None = Field(default=None, max_length=2000)


@router.post("/registro", status_code=201,
             dependencies=[Depends(limitar_registro)])
async def registro(body: RegistroBody):
    """
    Alta por iniciativa de la propia persona.

    El rol resultante es SIEMPRE 'facilitador': no se toma del cuerpo de la
    petición. Un administrador puede subirlo después desde el panel.
    """
    try:
        nuevo = await auth_service.registrar_usuario(
            email=str(body.email),
            nombre=body.nombre,
            password=body.password,
            cargo=body.cargo,
            programa=body.programa,
            lineas_accion=body.lineas_accion,
            temas=body.temas,
            telefono=body.telefono,
        )
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # Un fallo de base de datos aquí es casi siempre una migración sin
        # aplicar. El usuario merece saberlo, no un 500 mudo.
        logger.error("Fallo al registrar %s: %s", body.email, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo crear la cuenta por un problema de base de datos. "
                "Verifica que las migraciones estén aplicadas: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    # Se devuelve el token para que pueda entrar de una vez.
    token, expires_in = auth_service.create_access_token(nuevo)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "debe_cambiar_password": False,
        "user": {
            "id": nuevo["id"],
            "email": nuevo["email"],
            "nombre": nuevo["nombre"],
            "rol": nuevo["rol"],
            "programa": nuevo.get("programa"),
        },
    }


class PerfilBody(BaseModel):
    nombre: str | None = Field(default=None, min_length=3, max_length=120)
    cargo: str | None = Field(default=None, min_length=3, max_length=120)
    programa: str | None = None
    telefono: str | None = Field(default=None, max_length=40)
    lineas_accion: list[str] | None = None
    temas: str | None = Field(default=None, max_length=2000)


@router.patch("/perfil")
async def actualizar_perfil(body: PerfilBody, user: dict = Depends(get_current_user)):
    """Cada quien edita su propio perfil. Nunca su rol ni su estado."""
    cambios = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        await auth_service.actualizar_perfil(user["id"], cambios)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/perfil")
async def ver_perfil(user: dict = Depends(get_current_user)):
    completo = await auth_service.get_user_by_id(user["id"])
    if completo is None:
        raise HTTPException(status_code=404, detail="La cuenta no existe.")
    return {
        k: completo.get(k)
        for k in ("id", "nombre", "email", "rol", "cargo", "programa",
                  "lineas_accion", "temas", "telefono", "auto_registrado",
                  "created_at", "ultimo_acceso")
    }


# ─── Gestión de cuentas (solo administrador) ────────────────────────────────


class CrearUsuarioBody(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=3)
    password_temporal: str = Field(min_length=10)
    rol: str = "facilitador"
    programa: str | None = None
    cargo: str | None = None
    telefono: str | None = None
    lineas_accion: list[str] = Field(default_factory=list)
    temas: str | None = None


@router.post("/usuarios", status_code=201)
async def crear_usuario(
    body: CrearUsuarioBody, admin: dict = Depends(require_admin)
):
    """
    Crea una cuenta de facilitador. No hay auto-registro: las cuentas las
    crea un administrador y el titular debe cambiar la contraseña temporal
    en su primer ingreso.
    """
    try:
        nuevo = await auth_service.create_user(
            email=body.email,
            nombre=body.nombre,
            password=body.password_temporal,
            rol=body.rol,
            programa=body.programa,
            creado_por=admin["id"],
            perfil={
                "cargo": body.cargo,
                "telefono": body.telefono,
                "lineas_accion": body.lineas_accion,
                "temas": body.temas,
            },
        )
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "id": nuevo["id"],
        "email": nuevo["email"],
        "nombre": nuevo["nombre"],
        "rol": nuevo["rol"],
        "programa": nuevo.get("programa"),
    }


@router.get("/usuarios")
async def listar_usuarios(_: dict = Depends(require_supervision)):
    """Directorio: quién es cada quien, a qué se dedica y qué forma."""
    return {"usuarios": await auth_service.list_users()}


class ActivoBody(BaseModel):
    activo: bool


@router.patch("/usuarios/{user_id}/activo")
async def cambiar_activo(
    user_id: str, body: ActivoBody, admin: dict = Depends(require_admin)
):
    if user_id == admin["id"] and not body.activo:
        raise HTTPException(
            status_code=422, detail="No puedes desactivar tu propia cuenta."
        )
    await auth_service.set_activo(user_id, body.activo)
    return {"ok": True, "activo": body.activo}
