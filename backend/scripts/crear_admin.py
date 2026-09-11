"""
Crea la primera cuenta de administrador.

No se incluye un INSERT con contraseña por defecto en las migraciones a
propósito: dejaría una credencial conocida escrita en un archivo versionado en
un repositorio público. El hash Argon2id se genera aquí.

Uso, desde el directorio backend/ y con el .env configurado:

    python -m scripts.crear_admin

La contraseña se pide de forma interactiva y no queda en el historial del
intérprete de comandos.
"""

from __future__ import annotations

import asyncio
import getpass
import sys

sys.path.insert(0, ".")

from app.services import auth_service  # noqa: E402
from app.services.auth_service import AuthError  # noqa: E402
from app.services.db import DatabaseUnavailable  # noqa: E402


async def main() -> int:
    print("Creación de la cuenta de administrador de EPM")
    print("-" * 46)

    email = input("Correo: ").strip().lower()
    if not email or "@" not in email:
        print("Error: el correo no es válido.")
        return 1

    nombre = input("Nombre completo: ").strip()
    if len(nombre) < 3:
        print("Error: el nombre es demasiado corto.")
        return 1

    password = getpass.getpass("Contraseña: ")
    confirmacion = getpass.getpass("Confirma la contraseña: ")

    if password != confirmacion:
        print("Error: las contraseñas no coinciden.")
        return 1

    problemas = auth_service.validar_fortaleza(password)
    if problemas:
        print("La contraseña no cumple los requisitos:")
        for p in problemas:
            print(f"  - {p}")
        return 1

    try:
        existente = await auth_service.get_user_by_email(email)
    except DatabaseUnavailable as exc:
        print(f"Error de conexión con la base de datos: {exc}")
        print("Verifica SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en backend/.env")
        return 1

    if existente:
        print(f"Error: ya existe una cuenta con el correo {email}.")
        return 1

    try:
        usuario = await auth_service.create_user(
            email=email, nombre=nombre, password=password, rol="admin"
        )
    except AuthError as exc:
        print(f"Error: {exc}")
        return 1

    # La cuenta se crea con debe_cambiar_password en TRUE por defecto. Para el
    # administrador inicial no aplica: la contraseña la eligió él mismo aquí.
    await auth_service.change_password(usuario["id"], password)

    print()
    print(f"Cuenta de administrador creada: {usuario['email']}")
    print("Ya puedes iniciar sesión y crear las cuentas de los facilitadores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
