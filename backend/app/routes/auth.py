"""Rutas de autenticación y gestión de cuentas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.dependencies import get_current_user, require_admin, require_supervision
from app.services import auth_service
from app.services.auth_service import AuthError

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


@router.post("/login", response_model=LoginResponse)
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


# ─── Gestión de cuentas (solo administrador) ────────────────────────────────


class CrearUsuarioBody(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=3)
    password_temporal: str = Field(min_length=10)
    rol: str = "facilitador"
    programa: str | None = None


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
