-- ═══════════════════════════════════════════════════════════════════════════
-- 005 — Estado de sesión y análisis generado por el modelo
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Estado de avance de la sesión ──────────────────────────────────────────
-- current_node_id es lo que permite retomar exactamente donde se quedó, sin
-- depender de la memoria del proceso.
ALTER TABLE public.epm_sessions
  ADD COLUMN IF NOT EXISTS estado          TEXT NOT NULL DEFAULT 'en_progreso',
  ADD COLUMN IF NOT EXISTS tree_version    TEXT,
  ADD COLUMN IF NOT EXISTS current_node_id TEXT,
  ADD COLUMN IF NOT EXISTS completed_at    TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_sessions_estado'
       AND conrelid = 'public.epm_sessions'::regclass
  ) THEN
    ALTER TABLE public.epm_sessions
      ADD CONSTRAINT chk_sessions_estado
      CHECK (estado IN ('en_progreso', 'planeada', 'completada', 'abandonada'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_sessions_estado ON public.epm_sessions (estado);
CREATE INDEX IF NOT EXISTS idx_sessions_user_estado
  ON public.epm_sessions (user_id, estado);

COMMENT ON COLUMN public.epm_sessions.estado IS
  'planeada: solo se recorrió el bloque 1, la actividad aún no se ejecuta. '
  'Se puede retomar después para completar los bloques 2 y 3.';

-- ─── Análisis e ideas generadas por el modelo ───────────────────────────────
-- El fallo de esta etapa no invalida la consolidación: la sesión queda válida
-- y el análisis se puede reintentar. Por eso vive en su propia tabla.
CREATE TABLE IF NOT EXISTS public.epm_analisis_ia (
  id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id     TEXT        NOT NULL,
  user_id        UUID        REFERENCES public.epm_users(id) ON DELETE SET NULL,
  tipo           TEXT        NOT NULL,
  contenido      TEXT        NOT NULL,
  modelo         TEXT        NOT NULL,
  -- Correlaciona cada salida con la versión exacta del prompt que la produjo.
  prompt_hash    TEXT,
  tokens_entrada INTEGER,
  tokens_salida  INTEGER,
  generado_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_analisis_tipo'
       AND conrelid = 'public.epm_analisis_ia'::regclass
  ) THEN
    ALTER TABLE public.epm_analisis_ia
      ADD CONSTRAINT chk_analisis_tipo
      CHECK (tipo IN ('resumen', 'analisis', 'recomendaciones', 'ideas'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_analisis_session_tipo
  ON public.epm_analisis_ia (session_id, tipo);
CREATE INDEX IF NOT EXISTS idx_analisis_generado
  ON public.epm_analisis_ia (generado_at DESC);

COMMENT ON TABLE public.epm_analisis_ia IS
  'Salidas del modelo. No se sobrescriben: regenerar añade una fila nueva, de '
  'modo que se puede comparar contra versiones anteriores del prompt.';
