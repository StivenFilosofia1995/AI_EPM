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

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services import auth_service
from app.services import tree_repository as repo

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
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
#
# Los limitadores son FUNCIONES, no instancias de clase. FastAPI resuelve las
# anotaciones de tipo con `__globals__` de lo que recibe; una instancia no
# tiene ese atributo, así que con `from __future__ import annotations` la
# anotación `Request` se queda como texto sin resolver y FastAPI la trata como
# un campo obligatorio del cuerpo. El síntoma era un 422 "field required" en
# el parámetro `request` de toda ruta limitada.

_buckets: dict[str, list[float]] = defaultdict(list)


def _espera_legible(segundos: int) -> str:
    """
    Decirle a alguien que vuelva en 3567 segundos no le sirve de nada.
    """
    if segundos < 60:
        return "en menos de un minuto"
    minutos = round(segundos / 60)
    if minutos < 60:
        return f"en {minutos} minuto{'s' if minutos != 1 else ''}"
    horas = round(minutos / 60)
    return f"en aproximadamente {horas} hora{'s' if horas != 1 else ''}"


def _consumir(clave: str, veces: int, por_segundos: int) -> None:
    ahora = time.monotonic()
    ventana = _buckets[clave]

    while ventana and ahora - ventana[0] > por_segundos:
        ventana.pop(0)

    if len(ventana) >= veces:
        espera = int(por_segundos - (ahora - ventana[0])) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiadas solicitudes seguidas. Intenta de nuevo {_espera_legible(espera)}.",
            headers={"Retry-After": str(espera)},
        )

    ventana.append(ahora)


def _ip_de(request: Request) -> str:
    """Detrás del proxy de Railway, la IP real viene en la cabecera."""
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "desconocida"


def limitador_por_usuario(veces: int, por_segundos: int, nombre: str):
    """Límite por cuenta autenticada. Devuelve el usuario, como get_current_user."""

    async def dependencia(user: dict = Depends(get_current_user)) -> dict:
        _consumir(f"{nombre}:{user['id']}", veces, por_segundos)
        return user

    dependencia.es_limitador = True
    dependencia.nombre_limite = nombre
    return dependencia


def limitador_por_ip(veces: int, por_segundos: int, nombre: str):
    """
    Límite por dirección IP, para rutas sin autenticación.

    El registro es público: sin esto, cualquiera podría crear cuentas en masa.
    """

    async def dependencia(request: Request) -> None:
        _consumir(f"{nombre}:{_ip_de(request)}", veces, por_segundos)

    dependencia.es_limitador = True
    dependencia.nombre_limite = nombre
    return dependencia


# Los límites protegen contra abuso, no contra el uso normal. Varias personas
# de una misma sede comparten IP pública, así que un límite estrecho por IP
# bloquea a gente legítima: 5 registros por hora dejaba fuera a un equipo
# entero inscribiéndose en la misma jornada.
limitar_modelo = limitador_por_usuario(veces=30, por_segundos=300, nombre="modelo")
limitar_correo = limitador_por_usuario(veces=15, por_segundos=600, nombre="correo")
limitar_registro = limitador_por_ip(veces=40, por_segundos=3600, nombre="registro")
limitar_login = limitador_por_ip(veces=40, por_segundos=600, nombre="login")


def es_limitador(call) -> bool:
    """Para las pruebas: identifica una dependencia de límite de tasa."""
    return bool(getattr(call, "es_limitador", False))
