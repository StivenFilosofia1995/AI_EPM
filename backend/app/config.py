from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── LLM — solo se usa en la etapa final de análisis e ideas ───────────────
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"
    ANTHROPIC_BASE_URL: Optional[str] = None

    TEMPERATURE: float = 0.3
    MAX_TOKENS: int = 1500

    # ── Supabase ──────────────────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── Autenticación (JWT propio) ────────────────────────────────────────────
    # SECRET_KEY firma los tokens de acceso. Cambiarla invalida toda sesión
    # abierta. En producción debe venir del entorno, nunca del valor por defecto.
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # ── Google Sheets ─────────────────────────────────────────────────────────
    GOOGLE_SHEETS_ID: str = ""
    GOOGLE_SHEETS_GID: str = "0"
    # Opción 1 — archivo local
    SERVICE_ACCOUNT_FILE: str = "service_account.json"
    # Opción 2 — JSON completo como string (Railway)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    # Puerto primario. Si STARTTLS falla, el servicio reintenta en 465 con SSL.
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

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
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
