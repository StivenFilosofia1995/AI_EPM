-- ═══════════════════════════════════════════════════════════════════════════
-- 004 — Respuestas campo por campo, con historial de correcciones
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
--
-- Esta es la tabla que resuelve la pérdida de datos del diseño anterior. Cada
-- respuesta se persiste en el momento en que se responde, no al final. El
-- estado de avance se lee de aquí, no de la memoria del proceso: el sistema
-- sobrevive un reinicio y funciona con varias réplicas.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.epm_respuestas (
  id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id   TEXT        NOT NULL,
  user_id      UUID        REFERENCES public.epm_users(id) ON DELETE SET NULL,
  tree_version TEXT        NOT NULL,
  node_id      TEXT        NOT NULL,
  field_key    TEXT,

  -- valor: representación textual, siempre presente.
  -- valor_json: estructura original en selección múltiple (ODS) y compuestos.
  valor        TEXT,
  valor_json   JSONB,

  es_valida    BOOLEAN     NOT NULL DEFAULT TRUE,
  -- stale marca respuestas que dejaron de estar en la ruta tras un retroceso
  -- que cambió una ramificación. No se borran: se conservan para auditoría.
  stale        BOOLEAN     NOT NULL DEFAULT FALSE,
  intentos     SMALLINT    NOT NULL DEFAULT 1,

  answered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Hace que submit_answer sea idempotente por (session_id, node_id):
  -- reenviar la misma respuesta actualiza, nunca duplica.
  CONSTRAINT uq_respuestas_session_node UNIQUE (session_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_respuestas_session   ON public.epm_respuestas (session_id);
CREATE INDEX IF NOT EXISTS idx_respuestas_user      ON public.epm_respuestas (user_id);
CREATE INDEX IF NOT EXISTS idx_respuestas_field_key ON public.epm_respuestas (field_key);
CREATE INDEX IF NOT EXISTS idx_respuestas_activas
  ON public.epm_respuestas (session_id, field_key)
  WHERE stale IS FALSE AND es_valida IS TRUE;

DROP TRIGGER IF EXISTS trg_respuestas_updated ON public.epm_respuestas;
CREATE TRIGGER trg_respuestas_updated
  BEFORE UPDATE ON public.epm_respuestas
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- ─── Historial de correcciones ──────────────────────────────────────────────
-- Esto es lo que hace auditable el sistema: cada corrección deja rastro de
-- cuál era el valor anterior, quién lo tenía y cuándo se cambió.
CREATE TABLE IF NOT EXISTS public.epm_respuestas_historial (
  id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  respuesta_id  UUID        NOT NULL REFERENCES public.epm_respuestas(id) ON DELETE CASCADE,
  version_num   INTEGER     NOT NULL,

  session_id    TEXT        NOT NULL,
  user_id       UUID,
  tree_version  TEXT        NOT NULL,
  node_id       TEXT        NOT NULL,
  field_key     TEXT,
  valor         TEXT,
  valor_json    JSONB,
  es_valida     BOOLEAN,
  stale         BOOLEAN,
  intentos      SMALLINT,
  answered_at   TIMESTAMPTZ,
  archivado_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT uq_historial_respuesta_version UNIQUE (respuesta_id, version_num)
);

CREATE INDEX IF NOT EXISTS idx_historial_session   ON public.epm_respuestas_historial (session_id);
CREATE INDEX IF NOT EXISTS idx_historial_respuesta ON public.epm_respuestas_historial (respuesta_id);

-- Archiva el valor ANTERIOR cada vez que una respuesta cambia de contenido.
-- Solo dispara si valor o valor_json cambiaron: marcar stale o revalidar no
-- genera una entrada de historial.
CREATE OR REPLACE FUNCTION public.archivar_respuesta()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.valor IS DISTINCT FROM NEW.valor
     OR OLD.valor_json IS DISTINCT FROM NEW.valor_json THEN

    INSERT INTO public.epm_respuestas_historial (
      respuesta_id, version_num, session_id, user_id, tree_version, node_id,
      field_key, valor, valor_json, es_valida, stale, intentos, answered_at
    )
    VALUES (
      OLD.id,
      COALESCE(
        (SELECT max(h.version_num)
           FROM public.epm_respuestas_historial h
          WHERE h.respuesta_id = OLD.id),
        0
      ) + 1,
      OLD.session_id, OLD.user_id, OLD.tree_version, OLD.node_id,
      OLD.field_key, OLD.valor, OLD.valor_json, OLD.es_valida, OLD.stale,
      OLD.intentos, OLD.answered_at
    );
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_respuestas_historial ON public.epm_respuestas;
CREATE TRIGGER trg_respuestas_historial
  AFTER UPDATE ON public.epm_respuestas
  FOR EACH ROW EXECUTE FUNCTION public.archivar_respuesta();

COMMENT ON TABLE public.epm_respuestas_historial IS
  'Versiones anteriores de cada respuesta, pobladas por trigger AFTER UPDATE. '
  'version_num empieza en 1 para la primera corrección.';
