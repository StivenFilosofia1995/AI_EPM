-- ═══════════════════════════════════════════════════════════════════════════
-- 002 — Usuarios y vinculación de sesiones
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
--
-- Decisión tomada: autenticación con JWT propio, no Supabase Auth.
-- Consecuencia asumida: el RLS de la migración 008 queda como segunda línea de
-- defensa. La verificación de propiedad de sesión la aplica el backend en una
-- dependencia central de FastAPI, cubierta por pruebas.
--
-- Las cuentas las crea un administrador. No hay auto-registro.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.epm_users (
  id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  email          TEXT        NOT NULL,
  nombre         TEXT        NOT NULL,
  password_hash  TEXT        NOT NULL,
  programa       TEXT,
  rol            TEXT        NOT NULL DEFAULT 'facilitador'
                             CHECK (rol IN ('facilitador', 'coordinador', 'admin')),
  activo         BOOLEAN     NOT NULL DEFAULT TRUE,

  -- Obliga a cambiar la contraseña temporal que asignó el administrador.
  debe_cambiar_password BOOLEAN NOT NULL DEFAULT TRUE,

  -- Límite de intentos (sección 9 del encargo).
  intentos_fallidos SMALLINT    NOT NULL DEFAULT 0,
  bloqueado_hasta   TIMESTAMPTZ,
  ultimo_acceso     TIMESTAMPTZ,

  creado_por     UUID        REFERENCES public.epm_users(id) ON DELETE SET NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unicidad insensible a mayúsculas: evita que "Juan@epm.com" y "juan@epm.com"
-- convivan como dos cuentas distintas. El backend normaliza a minúsculas al
-- crear y al autenticar; este índice lo hace cumplir en la base de datos.
CREATE UNIQUE INDEX IF NOT EXISTS uq_epm_users_email_lower
  ON public.epm_users (lower(email));

CREATE INDEX IF NOT EXISTS idx_users_rol      ON public.epm_users (rol);
CREATE INDEX IF NOT EXISTS idx_users_programa ON public.epm_users (programa);
CREATE INDEX IF NOT EXISTS idx_users_activo   ON public.epm_users (activo) WHERE activo IS TRUE;

DROP TRIGGER IF EXISTS trg_users_updated ON public.epm_users;
CREATE TRIGGER trg_users_updated
  BEFORE UPDATE ON public.epm_users
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

COMMENT ON TABLE public.epm_users IS
  'Facilitadores, coordinadores y administradores. Las cuentas las crea un '
  'administrador; no hay auto-registro.';
COMMENT ON COLUMN public.epm_users.password_hash IS
  'Hash Argon2id calculado por el backend. Nunca almacenar la contraseña.';
COMMENT ON COLUMN public.epm_users.bloqueado_hasta IS
  'Bloqueo temporal por intentos fallidos. NULL cuando la cuenta no está bloqueada.';

-- ─── Vinculación con sesiones y actividades ─────────────────────────────────
ALTER TABLE public.epm_sessions
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES public.epm_users(id) ON DELETE SET NULL;

ALTER TABLE public.epm_actividades
  ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES public.epm_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_user    ON public.epm_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_actividades_user ON public.epm_actividades (user_id);

COMMENT ON COLUMN public.epm_sessions.user_id IS
  'Identidad autenticada del facilitador. Sustituye a user_name, que se '
  'conserva denormalizado solo para exportaciones históricas.';

-- ═══════════════════════════════════════════════════════════════════════════
-- TODO: crear la primera cuenta de administrador.
--
-- NO se incluye aquí un INSERT con contraseña por defecto a propósito: dejaría
-- una credencial conocida escrita en un archivo versionado en un repositorio
-- público. El hash Argon2id debe generarlo el backend.
--
-- Usa el script:  python -m backend.scripts.crear_admin
-- (se entrega junto con la capa de autenticación)
-- ═══════════════════════════════════════════════════════════════════════════
