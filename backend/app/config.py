from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"
    ANTHROPIC_BASE_URL: Optional[str] = None

    TEMPERATURE: float = 0.4
    MAX_TOKENS: int = 1500
    MAX_HISTORY: int = 20

    # ── Supabase ──────────────────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    DATABASE_URL: Optional[str] = None

    # Memoria conversacional
    USE_SUPABASE_MEMORY: bool = True
    MEMORY_WINDOW_MESSAGES: int = 100
    SUMMARY_MAX_CHARS: int = 6000

    # ── Google Sheets ─────────────────────────────────────────────────────────
    GOOGLE_SHEETS_ID: str = ""
    GOOGLE_SHEETS_GID: str = "0"
    # Opción 1 — archivo local
    SERVICE_ACCOUNT_FILE: str = "service_account.json"
    # Opción 2 — JSON completo como string (Railway)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None

    # ── Google Drive ──────────────────────────────────────────────────────────
    GOOGLE_DRIVE_FOLDER_ID: Optional[str] = None

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "EPM — Consolidación Metodológica"
    SECRET_KEY: str = "change-me-in-production"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "*"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
