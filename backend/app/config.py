
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anclado al directorio backend/, no al directorio de trabajo. Con env_file=
# ".env" a secas, arrancar uvicorn desde la raiz del repositorio ignoraba
# el archivo en silencio y la aplicacion levantaba sin configuracion.
_BACKEND = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ── LLM — solo se usa en la etapa final de análisis e ideas ───────────────
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"
    ANTHROPIC_BASE_URL: str | None = None

    TEMPERATURE: float = 0.3
    MAX_TOKENS: int = 1500

    # ── Supabase ──────────────────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── Cuenta inicial (solo modo demostración, sin Supabase) ─────────────────
    # Si ADMIN_PASSWORD viene del entorno, la cuenta de administrador se crea
    # con esa contraseña y queda fija entre despliegues. Si no, se genera una
    # aleatoria y se anuncia en los registros de arranque.
    # NUNCA se escribe una contraseña por defecto aquí: el repositorio es
    # público y quedaría legible por cualquiera.
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None

    # ── Autenticación (JWT propio) ────────────────────────────────────────────
    # SECRET_KEY firma los tokens de acceso. Cambiarla invalida toda sesión
    # abierta. En producción debe venir del entorno, nunca del valor por defecto.
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    # Puerto primario. Si STARTTLS falla, el servicio reintenta en 465 con SSL.
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "EPM — Consolidación Metodológica"
    # Lista separada por comas. Prohibido "*" en producción.
    CORS_ORIGINS: str = "http://localhost:8000"
    PORT: int = 8000

    # ── Legado — flujo conversacional en retiro ───────────────────────────────
    # Solo alimentan /api/chat y /api/form/*, marcados como obsoletos.
    # Se eliminan cuando esos endpoints se retiren.
    USE_SUPABASE_MEMORY: bool = True
    MEMORY_WINDOW_MESSAGES: int = 100
    MAX_HISTORY: int = 20
    # TODO: eliminar junto con las rutas /api/admin/* basadas en PIN, una vez
    # que el panel de administrador use autenticación por rol.
    ADMIN_PIN: str = "epm2024"

    # extra="ignore" evita que una variable sobrante en .env tumbe el arranque.
    # Sin esto, copiar .env.example a .env con una variable de más provoca un
    # ValidationError de Pydantic y la aplicación no levanta.
    model_config = SettingsConfigDict(
        # El segundo tiene prioridad: permite un .env junto al CWD que
        # sobrescriba al del backend, útil en desarrollo.
        env_file=(_BACKEND / ".env", ".env"),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
