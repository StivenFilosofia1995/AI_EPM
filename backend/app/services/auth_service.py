"""
Autenticación con JWT propio.

Decisión tomada explícitamente frente a Supabase Auth. La consecuencia
asumida: el RLS no puede expresar "cada facilitador ve solo lo suyo", porque
no hay auth.uid() que consultar. Por eso la verificación de propiedad de
sesión se centraliza en app/dependencies.py y está cubierta por pruebas.

Las cuentas las crea un administrador. No hay auto-registro.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings
from app.services.db import get_client

logger = logging.getLogger(__name__)

USERS = "epm_users"

_hasher = PasswordHasher()

ROLES = ("facilitador", "coordinador", "admin")

# Bloqueo por intentos fallidos.
MAX_INTENTOS = 5
BLOQUEO_MINUTOS = 15


class AuthError(Exception):
    """Credenciales inválidas, cuenta inactiva o bloqueada."""


# ─── Contraseñas ────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def validar_fortaleza(password: str) -> list[str]:
    """Reglas mínimas. Devuelve la lista de incumplimientos, vacía si pasa."""
    problemas: list[str] = []
    if len(password) < 10:
        problemas.append("Debe tener al menos 10 caracteres.")
    if not any(c.isalpha() for c in password):
        problemas.append("Debe incluir al menos una letra.")
    if not any(c.isdigit() for c in password):
        problemas.append("Debe incluir al menos un número.")
    return problemas


# ─── Tokens ─────────────────────────────────────────────────────────────────


def create_access_token(user: dict) -> tuple[str, int]:
    """Devuelve (token, segundos_de_vigencia)."""
    if settings.SECRET_KEY == "change-me-in-production":
        logger.warning(
            "SECRET_KEY tiene el valor por defecto. Configúrala en el entorno "
            "antes de exponer la aplicación."
        )
    expira_en = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "nombre": user["nombre"],
        "rol": user["rol"],
        "programa": user.get("programa"),
        "exp": datetime.now(UTC) + timedelta(seconds=expira_en),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expira_en


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("La sesión expiró. Inicia sesión de nuevo.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Token inválido.") from exc


# ─── Acceso a usuarios ──────────────────────────────────────────────────────


async def _run(fn):
    return await asyncio.to_thread(fn)


async def get_user_by_email(email: str) -> dict | None:
    client = get_client()
    normalizado = email.strip().lower()
    result = await _run(
        lambda: client.table(USERS).select("*").eq("email", normalizado).limit(1).execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def get_user_by_id(user_id: str) -> dict | None:
    client = get_client()
    result = await _run(
        lambda: client.table(USERS).select("*").eq("id", user_id).limit(1).execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def list_users(limit: int = 500) -> list[dict]:
    client = get_client()
    result = await _run(
        lambda: client.table(USERS)
        .select("id,email,nombre,programa,rol,activo,debe_cambiar_password,"
                "ultimo_acceso,created_at,cargo,telefono,lineas_accion,temas,"
                "auto_registrado")
        .order("nombre", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data or []


async def create_user(
    email: str,
    nombre: str,
    password: str,
    rol: str = "facilitador",
    programa: str | None = None,
    creado_por: str | None = None,
    perfil: dict | None = None,
    auto_registrado: bool = False,
    debe_cambiar_password: bool = True,
) -> dict:
    if rol not in ROLES:
        raise AuthError(f"Rol inválido: {rol}. Debe ser uno de {ROLES}.")

    problemas = validar_fortaleza(password)
    if problemas:
        raise AuthError(" ".join(problemas))

    normalizado = email.strip().lower()
    if await get_user_by_email(normalizado):
        raise AuthError(f"Ya existe una cuenta con el correo {normalizado}.")

    client = get_client()
    record = {
        "email": normalizado,
        "nombre": nombre.strip(),
        "password_hash": hash_password(password),
        "rol": rol,
        "programa": programa,
        "activo": True,
        # Quien se registra solo elige su contraseña: no hay nada que cambiar.
        "debe_cambiar_password": debe_cambiar_password,
        "creado_por": creado_por,
        "auto_registrado": auto_registrado,
        **(perfil or {}),
    }
    try:
        result = await _run(lambda: client.table(USERS).insert(record).execute())
    except Exception as exc:
        mensaje = str(exc)
        # PostgREST nombra la columna inexistente. Traducirlo evita que el
        # usuario vea un 500 sin explicación cuando falta una migración.
        if "42501" in mensaje or "permission denied" in mensaje.lower():
            logger.error("Permiso denegado sobre epm_users: %s", mensaje)
            raise AuthError(
                "La clave de Supabase configurada no tiene permisos sobre la "
                "tabla de usuarios. Revisa que SUPABASE_SERVICE_ROLE_KEY sea la "
                "clave `service_role` (secret) y no la `anon public`. No "
                "concedas permisos a `anon`: esa tabla guarda contraseñas."
            ) from exc

        if "column" in mensaje.lower() or "PGRST204" in mensaje:
            logger.error("Esquema desactualizado al crear la cuenta: %s", mensaje)
            raise AuthError(
                "La base de datos no tiene las columnas de perfil. Ejecuta la "
                "migración backend/sql/migrations/010_perfil_y_registro.sql en "
                "Supabase, o vuelve a pegar esquema_completo.sql."
            ) from exc
        raise

    rows = result.data or []
    if not rows:
        raise AuthError("No se pudo crear la cuenta.")
    return rows[0]


async def _registrar_intento_fallido(user: dict) -> None:
    client = get_client()
    intentos = int(user.get("intentos_fallidos") or 0) + 1
    cambios: dict[str, Any] = {"intentos_fallidos": intentos}
    if intentos >= MAX_INTENTOS:
        cambios["bloqueado_hasta"] = (
            datetime.now(UTC) + timedelta(minutes=BLOQUEO_MINUTOS)
        ).isoformat()
    await _run(
        lambda: client.table(USERS).update(cambios).eq("id", user["id"]).execute()
    )


async def _registrar_acceso(user: dict) -> None:
    client = get_client()
    await _run(
        lambda: client.table(USERS)
        .update({
            "intentos_fallidos": 0,
            "bloqueado_hasta": None,
            "ultimo_acceso": datetime.now(UTC).isoformat(),
        })
        .eq("id", user["id"])
        .execute()
    )


async def authenticate(email: str, password: str) -> dict:
    """
    Verifica credenciales. Lanza AuthError con un mensaje genérico cuando
    fallan, para no revelar si el correo existe.
    """
    generico = "Correo o contraseña incorrectos."
    user = await get_user_by_email(email)

    if user is None:
        # Se calcula un hash igualmente para que el tiempo de respuesta no
        # revele si el correo está registrado.
        hash_password(password)
        raise AuthError(generico)

    if not user.get("activo", True):
        raise AuthError("Esta cuenta está desactivada. Contacta al administrador.")

    bloqueado = user.get("bloqueado_hasta")
    if bloqueado:
        try:
            hasta = datetime.fromisoformat(str(bloqueado).replace("Z", "+00:00"))
            if hasta > datetime.now(UTC):
                raise AuthError(
                    "Cuenta bloqueada temporalmente por intentos fallidos. "
                    "Vuelve a intentar en unos minutos."
                )
        except ValueError:
            pass

    if not verify_password(password, user.get("password_hash", "")):
        await _registrar_intento_fallido(user)
        raise AuthError(generico)

    await _registrar_acceso(user)
    return user


async def change_password(user_id: str, nueva: str) -> None:
    problemas = validar_fortaleza(nueva)
    if problemas:
        raise AuthError(" ".join(problemas))
    client = get_client()
    await _run(
        lambda: client.table(USERS)
        .update({
            "password_hash": hash_password(nueva),
            "debe_cambiar_password": False,
        })
        .eq("id", user_id)
        .execute()
    )


async def set_activo(user_id: str, activo: bool) -> None:
    client = get_client()
    await _run(
        lambda: client.table(USERS).update({"activo": activo}).eq("id", user_id).execute()
    )


# ─── Registro abierto ───────────────────────────────────────────────────────


async def registrar_usuario(
    email: str,
    nombre: str,
    password: str,
    cargo: str,
    programa: str | None = None,
    lineas_accion: list[str] | None = None,
    temas: str | None = None,
    telefono: str | None = None,
) -> dict:
    """
    Alta por iniciativa de la propia persona.

    SALVAGUARDA: el rol es SIEMPRE 'facilitador' y no se toma del formulario.
    Si se aceptara del cliente, cualquiera se haría administrador desde la
    pantalla de registro. Subir de rol solo puede hacerlo un administrador
    desde el panel.
    """
    from app.domain.fields import LINEAS_ACCION, PROGRAMAS

    if programa and programa not in PROGRAMAS:
        raise AuthError(f"Programa no válido: {programa}.")

    lineas = [x for x in (lineas_accion or []) if x]
    invalidas = [x for x in lineas if x not in LINEAS_ACCION]
    if invalidas:
        raise AuthError(f"Líneas de acción no válidas: {', '.join(invalidas)}.")

    if len(cargo.strip()) < 3:
        raise AuthError("Indica a qué te dedicas, con al menos 3 caracteres.")

    return await create_user(
        email=email,
        nombre=nombre,
        password=password,
        rol="facilitador",          # nunca se toma del formulario
        programa=programa,
        perfil={
            "cargo": cargo.strip(),
            "lineas_accion": lineas,
            "temas": (temas or "").strip() or None,
            "telefono": (telefono or "").strip() or None,
            "registrado_at": datetime.now(UTC).isoformat(),
        },
        auto_registrado=True,
        debe_cambiar_password=False,
    )


async def actualizar_perfil(user_id: str, perfil: dict) -> dict:
    """Actualiza los campos de perfil. Nunca toca rol, activo ni contraseña."""
    from app.domain.fields import LINEAS_ACCION, PROGRAMAS

    permitidos = {"nombre", "cargo", "programa", "lineas_accion", "temas", "telefono"}
    cambios = {k: v for k, v in perfil.items() if k in permitidos}

    if cambios.get("programa") and cambios["programa"] not in PROGRAMAS:
        raise AuthError(f"Programa no válido: {cambios['programa']}.")

    lineas = cambios.get("lineas_accion")
    if lineas is not None:
        invalidas = [x for x in lineas if x not in LINEAS_ACCION]
        if invalidas:
            raise AuthError(f"Líneas de acción no válidas: {', '.join(invalidas)}.")

    if not cambios:
        raise AuthError("No hay nada que actualizar.")

    client = get_client()
    result = await _run(
        lambda: client.table(USERS).update(cambios).eq("id", user_id).execute()
    )
    filas = result.data or []
    return filas[0] if filas else {}
