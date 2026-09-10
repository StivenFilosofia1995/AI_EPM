import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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
from app.services.db import modo_demostracion

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
    if settings.CORS_ORIGINS.strip() == "*":
        logger.warning("CORS_ORIGINS está en '*'. Restringe los orígenes en producción.")

    if modo_demostracion():
        logger.warning(
            "SUPABASE_URL no está configurada: se arranca en MODO DEMOSTRACIÓN. "
            "Los datos viven en memoria y se pierden en cada despliegue. "
            "Para uso real, configura Supabase y ejecuta sql/esquema_completo.sql."
        )
        await asegurar_admin()

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

# ─── CORS ───────────────────────────────────────────────────────────────────
# Prohibido "*": con allow_credentials=True los navegadores rechazan el
# comodín, así que la configuración anterior ni siquiera hacía lo que aparentaba.
_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip() and o.strip() != "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ─── Errores de validación en español ───────────────────────────────────────
# Pydantic los emite en inglés y con jerga interna. El usuario final de esta
# aplicación es un facilitador, no un desarrollador.
_TRADUCCIONES = {
    "value is not a valid email address": "El correo no tiene un formato válido.",
    "field required": "Este dato es obligatorio.",
    "Field required": "Este dato es obligatorio.",
    "String should have at least": "El texto es demasiado corto.",
    "Input should be a valid integer": "Debe ser un número entero.",
    "Input should be a valid": "El valor no tiene el formato esperado.",
}


def _traducir(mensaje: str) -> str:
    for clave, es in _TRADUCCIONES.items():
        if mensaje.startswith(clave) or clave in mensaje:
            return es
    return mensaje


@app.exception_handler(RequestValidationError)
async def errores_de_validacion(_: Request, exc: RequestValidationError):
    detalles = []
    for e in exc.errors():
        campo = ".".join(str(p) for p in e.get("loc", ()) if p not in ("body", "query"))
        detalles.append({
            "field_key": campo or None,
            "code": e.get("type", "invalido"),
            "message": _traducir(str(e.get("msg", ""))),
        })
    resumen = " ".join(d["message"] for d in detalles) or "Los datos enviados no son válidos."
    return JSONResponse(status_code=422, content={"detail": resumen, "errors": detalles})


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
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
