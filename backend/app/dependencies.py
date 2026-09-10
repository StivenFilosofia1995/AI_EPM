"""
Dependencias transversales de FastAPI: identidad, rol y propiedad de sesión.

Este módulo es la razón por la que la decisión de usar JWT propio en lugar de
Supabase Auth sigue siendo segura. Como el RLS no puede filtrar por usuario,
la verificación de propiedad se centraliza AQUÍ y no se reparte a mano por
endpoint. La prueba tests/test_autorizacion.py falla si alguna ruta de datos
se salta esta dependencia.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services import auth_service, tree_repository as repo

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = auth_service.decode_token(creds.credentials)
    except auth_service.AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return {
        "id": payload["sub"],
        "email": payload.get("email", ""),
        "nombre": payload.get("nombre", ""),
        "rol": payload.get("rol", "facilitador"),
        "programa": payload.get("programa"),
    }


def require_role(*roles: str):
    """Exige que el usuario tenga uno de los roles indicados."""

    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if user["rol"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para acceder a este recurso.",
            )
        return user

    return _check


require_admin = require_role("admin")
require_supervision = require_role("admin", "coordinador")


async def verify_session_ownership(session_id: str, user: dict) -> dict:
    """
    Confirma que la sesión existe y pertenece al usuario.
    Coordinadores y administradores pueden acceder a cualquier sesión.

    Devuelve la fila de la sesión para que quien llama no la vuelva a pedir.
    """
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="La sesión no existe.")

    if user["rol"] in ("admin", "coordinador"):
        return session

    if str(session.get("user_id")) != str(user["id"]):
        # 404 en lugar de 403: no revela que la sesión existe.
        raise HTTPException(status_code=404, detail="La sesión no existe.")

    return session


# ─── Límite de tasa ─────────────────────────────────────────────────────────
# Implementación en memoria del proceso. Con varias réplicas el límite es por
# réplica, no global. Es una limitación conocida y documentada: para un límite
# realmente global haría falta Redis o una tabla de contadores en Postgres.

_buckets: dict[str, list[float]] = defaultdict(list)


class RateLimit:
    def __init__(self, veces: int, por_segundos: int, nombre: str = "recurso"):
        self.veces = veces
        self.por_segundos = por_segundos
        self.nombre = nombre

    async def __call__(
        self, request: Request, user: dict = Depends(get_current_user)
    ) -> dict:
        ahora = time.monotonic()
        clave = f"{self.nombre}:{user['id']}"
        ventana = _buckets[clave]

        while ventana and ahora - ventana[0] > self.por_segundos:
            ventana.pop(0)

        if len(ventana) >= self.veces:
            espera = int(self.por_segundos - (ahora - ventana[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiadas solicitudes. Intenta de nuevo en {espera} segundos.",
                headers={"Retry-After": str(espera)},
            )

        ventana.append(ahora)
        return user


limitar_modelo = RateLimit(veces=20, por_segundos=300, nombre="modelo")
limitar_correo = RateLimit(veces=5, por_segundos=600, nombre="correo")
