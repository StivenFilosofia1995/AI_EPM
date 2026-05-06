-- ═══════════════════════════════════════════════════════════════════════════
-- EPM — Consolidación Metodológica · Schema Supabase (PostgreSQL)
-- Ejecutar en: Supabase Dashboard → SQL Editor
-- ═══════════════════════════════════════════════════════════════════════════

-- Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- para búsqueda de texto

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. SESIONES DE CONVERSACIÓN
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS epm_sessions (
  id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id     TEXT        UNIQUE NOT NULL,
  user_agent     TEXT,
  ip_address     INET,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger: actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sessions_updated
  BEFORE UPDATE ON epm_sessions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. HISTORIAL DE MENSAJES (memoria conversacional)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS epm_messages (
  id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id  TEXT        NOT NULL,
  role        TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
  content     TEXT        NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW(),

  CONSTRAINT fk_messages_session
    FOREIGN KEY (session_id) REFERENCES epm_sessions(session_id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_time
  ON epm_messages (session_id, created_at ASC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. ACTIVIDADES CONSOLIDADAS (formulario completo)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS epm_actividades (
  id                       UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id               TEXT,

  -- ── Bloque 1: Identificación y diseño metodológico ──
  id_actividad             TEXT,
  programa                 TEXT,
  linea_accion             TEXT,
  tipo_actividad           TEXT,
  nombre                   TEXT,
  publico                  TEXT,
  publico_especifico       TEXT,
  lugar                    TEXT,
  responsable              TEXT,
  duracion                 TEXT,
  pregunta_problematizadora TEXT,
  ods                      TEXT,
  metodologia              TEXT,
  descripcion_sesion       TEXT,
  recursos                 TEXT,
  fecha                    TEXT,

  -- ── Bloque 2: Informe de ejecución ──
  logros                   TEXT,
  retos                    TEXT,
  observaciones            TEXT,
  comentarios              TEXT,

  -- ── Bloque 3: Evaluación ──
  instrumento_evaluativo   TEXT,
  participantes_evaluados  TEXT,
  cumplimiento_objetivos   TEXT,
  acciones_mejora          TEXT,
  porcentaje_cumplimiento  TEXT,

  -- ── Metadatos ──
  analysis_ia              TEXT,
  sheets_row               INTEGER,
  created_at               TIMESTAMPTZ DEFAULT NOW(),
  updated_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER trg_actividades_updated
  BEFORE UPDATE ON epm_actividades
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_actividades_session   ON epm_actividades (session_id);
CREATE INDEX IF NOT EXISTS idx_actividades_id_act    ON epm_actividades (id_actividad);
CREATE INDEX IF NOT EXISTS idx_actividades_programa  ON epm_actividades (programa);
CREATE INDEX IF NOT EXISTS idx_actividades_fecha     ON epm_actividades (fecha);

-- Búsqueda de texto completo en nombre/descripción
CREATE INDEX IF NOT EXISTS idx_actividades_nombre_trgm
  ON epm_actividades USING GIN (nombre gin_trgm_ops);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. ROW LEVEL SECURITY
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE epm_sessions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE epm_messages    ENABLE ROW LEVEL SECURITY;
ALTER TABLE epm_actividades ENABLE ROW LEVEL SECURITY;

-- El backend usa service_role → acceso total
CREATE POLICY "service_role_full_sessions"
  ON epm_sessions FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_messages"
  ON epm_messages FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_actividades"
  ON epm_actividades FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. VISTA RESUMEN (útil para dashboards)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW epm_resumen AS
SELECT
  a.id_actividad,
  a.nombre,
  a.programa,
  a.linea_accion,
  a.tipo_actividad,
  a.responsable,
  a.fecha,
  a.participantes_evaluados,
  a.porcentaje_cumplimiento,
  a.created_at,
  count(m.id) AS total_mensajes
FROM epm_actividades a
LEFT JOIN epm_messages m ON m.session_id = a.session_id
GROUP BY a.id;
