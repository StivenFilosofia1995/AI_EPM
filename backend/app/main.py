import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app.config import settings
from app.domain.fields import assert_contract
from app.domain.tree_loader import get_tree
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.exports import router as exports_router
from app.routes.health import router as health_router
from app.routes.ideas import router as ideas_router
from app.routes.legacy import router as legacy_router
from app.routes.tree import router as tree_router
from app.services.bootstrap import asegurar_admin
from app.services.db import avisar_si_la_clave_es_publica, modo_demostracion
from app.services.schema_check import avisar_si_falta_esquema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Verifica el contrato de campos y el grafo del árbol al arrancar.

    Si algo está mal, la aplicación no levanta. Es preferible fallar en el
    despliegue que descubrirlo con un facilitador a medio diligenciar.
    """
    assert_contract()
    tree = get_tree()
    logger.info(
        "Árbol %s cargado y validado: %d nodos, checksum %s",
        tree.version,
        len(tree.nodes),
        tree.checksum[:12],
    )
    if settings.SECRET_KEY == "change-me-in-production":
        logger.warning(
            "SECRET_KEY tiene el valor por defecto. Configúrala antes de exponer "
            "la aplicación: los tokens de sesión son falsificables."
        )
    if modo_demostracion():
        logger.warning(
            "SUPABASE_URL no está configurada: se arranca en MODO DEMOSTRACIÓN. "
            "Los datos viven en memoria y se pierden en cada despliegue. "
            "Para uso real, configura Supabase y ejecuta sql/esquema_completo.sql."
        )

    if not modo_demostracion():
        avisar_si_la_clave_es_publica()

    # Un esquema desactualizado producía un error 500 sin explicación en
    # mitad de un formulario. Es mejor enterarse aquí.
    try:
        await avisar_si_falta_esquema()
    except Exception as exc:
        logger.warning("No se pudo verificar el esquema: %s", exc)

    # Decide por sí misma si corresponde crear la cuenta inicial.
    try:
        await asegurar_admin()
    except Exception as exc:
        logger.error("No se pudo preparar la cuenta inicial: %s", exc)

    yield


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Consolidación metodológica de actividades EPM mediante un motor "
        "determinista de árbol de decisiones."
    ),
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# No se configura CORS: el frontend se sirve desde este mismo origen, así que
# el navegador no emite peticiones de origen cruzado. Si algún día el frontend
# se publica en otro dominio, hay que añadir CORSMiddleware con la lista
# explícita de orígenes permitidos.

# ─── Errores de validación en español ───────────────────────────────────────
# Pydantic los emite en inglés y con jerga interna. El usuario final de esta
# aplicación es un facilitador, no un desarrollador.
#
# El mensaje debe decir QUÉ campo y CUÁL es la regla. Un "El texto es
# demasiado corto." a secas, en un formulario con tres campos que tienen
# longitud mínima, obliga a adivinar.

_ETIQUETAS = {
    "nombre": "El nombre completo",
    "email": "El correo",
    "password": "La contraseña",
    "password_actual": "La contraseña actual",
    "password_nueva": "La contraseña nueva",
    "password_temporal": "La contraseña temporal",
    "cargo": "El cargo o rol",
    "programa": "El programa",
    "telefono": "El teléfono",
    "temas": "Los temas o actividades",
    "lineas_accion": "Las líneas de acción",
    "to_email": "El correo de destino",
    "session_id": "La sesión",
    "node_id": "La pregunta",
    "borrador": "El borrador",
    "rol": "El rol",
}


def _etiqueta(campo: str) -> str:
    return _ETIQUETAS.get(campo, f"El campo {campo}" if campo else "El dato")


def _mensaje(campo: str, tipo: str, ctx: dict, original: str) -> str:
    et = _etiqueta(campo)

    if tipo == "missing":
        return f"{et} es obligatorio."
    if tipo == "string_too_short":
        minimo = ctx.get("min_length")
        return (f"{et} debe tener al menos {minimo} caracteres."
                if minimo else f"{et} es demasiado corto.")
    if tipo == "string_too_long":
        maximo = ctx.get("max_length")
        return (f"{et} no puede superar los {maximo} caracteres."
                if maximo else f"{et} es demasiado largo.")
    if tipo in ("int_parsing", "int_type"):
        return f"{et} debe ser un número entero."
    if tipo in ("greater_than_equal", "greater_than"):
        return f"{et} debe ser mayor o igual a {ctx.get('ge', ctx.get('gt', 0))}."
    if tipo in ("less_than_equal", "less_than"):
        return f"{et} debe ser menor o igual a {ctx.get('le', ctx.get('lt', 0))}."
    if tipo == "list_type":
        return f"{et} debe ser una lista de opciones."
    if "email" in tipo or "email" in original.lower():
        return f"{et} no tiene un formato válido."
    return f"{et} no es válido."


@app.exception_handler(RequestValidationError)
async def errores_de_validacion(_: Request, exc: RequestValidationError):
    detalles = []
    for e in exc.errors():
        partes = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
        campo = partes[-1] if partes else ""
        detalles.append({
            "field_key": campo or None,
            "code": e.get("type", "invalido"),
            "message": _mensaje(campo, e.get("type", ""), e.get("ctx") or {},
                                str(e.get("msg", ""))),
        })

    resumen = " ".join(d["message"] for d in detalles) or "Los datos enviados no son válidos."
    return JSONResponse(status_code=422, content={"detail": resumen, "errors": detalles})


@app.exception_handler(Exception)
async def error_no_controlado(request: Request, exc: Exception):
    """
    Ningún fallo debe llegar al usuario como un "Error 500." mudo.

    Se registra la traza completa con una referencia corta, y esa misma
    referencia se le muestra a quien usa la aplicación. Así, cuando alguien
    reporta un problema, se puede encontrar la traza exacta en los registros
    en vez de adivinar.
    """
    ref = uuid.uuid4().hex[:8]
    logger.exception(
        "Error no controlado [%s] en %s %s: %s",
        ref, request.method, request.url.path, exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "Ocurrió un error inesperado en el servidor. "
                f"Referencia para soporte: {ref}"
            ),
            "referencia": ref,
            "tipo": type(exc).__name__,
        },
    )


# ─── Rutas de API ───────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(tree_router)
app.include_router(exports_router)
app.include_router(ideas_router)
app.include_router(admin_router)
app.include_router(health_router)
# Obsoletos: se registran al final para que nunca ensombrezcan a los actuales.
app.include_router(legacy_router)

# ─── Frontend estático ──────────────────────────────────────────────────────


class EstaticosSinCache(StaticFiles):
    """
    Obliga a revalidar el JS y el CSS en cada carga.

    Sin esto, el navegador conserva la versión anterior de app.js después de
    un despliegue y el usuario ve una interfaz que ya no corresponde al
    backend, sin ningún error visible. Las imágenes y fuentes sí se cachean:
    cambian de nombre cuando cambian.
    """

    async def get_response(self, path: str, scope: Scope):
        respuesta = await super().get_response(path, scope)
        if path.endswith((".js", ".css", ".html")):
            respuesta.headers["Cache-Control"] = "no-cache, must-revalidate"
        return respuesta


STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", EstaticosSinCache(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=FileResponse, include_in_schema=False)
    async def root():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/admin", response_class=FileResponse, include_in_schema=False)
    async def admin_page():
        return FileResponse(STATIC_DIR / "admin.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # El catch-all anterior devolvía index.html para CUALQUIER GET no
        # resuelto, incluidos los /api mal escritos: un endpoint inexistente
        # respondía 200 con HTML en vez de 404 JSON, lo que rompe clientes y
        # esconde errores de integración.
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": f"El endpoint /{full_path} no existe."},
            )
        return FileResponse(STATIC_DIR / "index.html")
