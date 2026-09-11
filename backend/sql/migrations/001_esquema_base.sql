-- ═══════════════════════════════════════════════════════════════════════════
-- 001 — Esquema base: sesiones, mensajes y actividades consolidadas
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente: puede ejecutarse varias veces sin error.
--
-- Reemplaza a init.sql corrigiendo tres defectos del esquema anterior:
--   1. epm_sessions no tenía la columna user_name que el servicio intentaba escribir.
--   2. epm_actividades no tenía índice único sobre session_id, pese a que
--      save_actividad() hacía upsert con on_conflict="session_id" (error 42P10).
--   3. Los campos numéricos y de fecha eran TEXT. Al partir de una base limpia
--      se crean con su tipo real. La vista de compatibilidad de la migración 007
--      los devuelve como texto para Google Sheets y Excel.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ─── Función compartida de updated_at ───────────────────────────────────────
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── 1. Sesiones ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.epm_sessions (
  id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id  TEXT        UNIQUE NOT NULL,
  user_name   TEXT,
  user_agent  TEXT,
  ip_address  INET,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Por si la tabla ya existía sin la columna (esquema anterior).
ALTER TABLE public.epm_sessions ADD COLUMN IF NOT EXISTS user_name TEXT;

COMMENT ON COLUMN public.epm_sessions.user_name IS
  'Nombre denormalizado del facilitador. Se conserva para exportaciones '
  'históricas; la identidad autenticada vive en user_id (migración 002).';

DROP TRIGGER IF EXISTS trg_sessions_updated ON public.epm_sessions;
CREATE TRIGGER trg_sessions_updated
  BEFORE UPDATE ON public.epm_sessions
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- ─── 2. Mensajes (memoria del flujo conversacional, en retiro) ──────────────
CREATE TABLE IF NOT EXISTS public.epm_messages (
  id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id  TEXT        NOT NULL,
  role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
  content     TEXT        NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT fk_messages_session
    FOREIGN KEY (session_id) REFERENCES public.epm_sessions(session_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_time
  ON public.epm_messages (session_id, created_at ASC);

COMMENT ON TABLE public.epm_messages IS
  'Historial del chat. Queda como archivo histórico: el motor de árbol de '
  'decisiones no lo usa. No se elimina para no perder trazabilidad previa.';

-- ─── 3. Actividades consolidadas (proyección de epm_respuestas) ─────────────
-- Las 25 columnas conservan exactamente los nombres de FIELD_KEYS. El orden
-- de esta tabla es el orden del contrato de exportación.
CREATE TABLE IF NOT EXISTS public.epm_actividades (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id  TEXT NOT NULL,

  -- ── Bloque 1: Identificación y diseño metodológico (16 campos) ──
  id_actividad              TEXT,
  programa                  TEXT,
  linea_accion              TEXT,
  tipo_actividad            TEXT,
  nombre                    TEXT,
  publico                   TEXT,
  publico_especifico        TEXT,
  lugar                     TEXT,
  responsable               TEXT,
  duracion                  TEXT,
  pregunta_problematizadora TEXT,
  ods                       TEXT,   -- selección múltiple serializada con "; "
  metodologia               TEXT,
  descripcion_sesion        TEXT,
  recursos                  TEXT,
  fecha                     DATE,

  -- ── Bloque 2: Informe de ejecución (4 campos) ──
  logros                    TEXT,
  retos                     TEXT,
  observaciones             TEXT,
  comentarios               TEXT,

  -- ── Bloque 3: Evaluación (5 campos) ──
  instrumento_evaluativo    TEXT,
  participantes_evaluados   INTEGER,
  cumplimiento_objetivos    TEXT,
  acciones_mejora           TEXT,
  porcentaje_cumplimiento   SMALLINT,

  -- ── Metadatos ──
  analysis_ia  TEXT,        -- legado; el análisis vive en epm_analisis_ia (005)
  sheets_row   INTEGER,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Necesario para que el upsert con on_conflict="session_id" funcione.
CREATE UNIQUE INDEX IF NOT EXISTS uq_epm_actividades_session_id
  ON public.epm_actividades (session_id);

CREATE INDEX IF NOT EXISTS idx_actividades_id_act   ON public.epm_actividades (id_actividad);
CREATE INDEX IF NOT EXISTS idx_actividades_programa ON public.epm_actividades (programa);
CREATE INDEX IF NOT EXISTS idx_actividades_fecha    ON public.epm_actividades (fecha);

CREATE INDEX IF NOT EXISTS idx_actividades_nombre_trgm
  ON public.epm_actividades USING GIN (nombre gin_trgm_ops);

DROP TRIGGER IF EXISTS trg_actividades_updated ON public.epm_actividades;
CREATE TRIGGER trg_actividades_updated
  BEFORE UPDATE ON public.epm_actividades
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

COMMENT ON TABLE public.epm_actividades IS
  'Proyección consolidada de epm_respuestas, una fila por sesión. Dejó de ser '
  'estado vivo: se escribe al finalizar la sesión. Fuente de las exportaciones.';
