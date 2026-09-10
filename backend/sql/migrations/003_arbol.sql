-- ═══════════════════════════════════════════════════════════════════════════
-- 003 — Definición versionada del árbol de decisiones
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
--
-- El árbol se edita como YAML en backend/app/domain/tree/. Al arrancar, la
-- aplicación lo carga, valida el grafo y publica aquí el JSONB resultante.
-- Esta tabla es el registro autoritativo de qué árbol estuvo activo y cuándo:
-- cada respuesta guardada anota con qué versión fue capturada.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.epm_tree_versions (
  id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  version    TEXT        UNIQUE NOT NULL,
  definition JSONB       NOT NULL,
  checksum   TEXT        NOT NULL,
  activa     BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Solo puede haber una versión activa a la vez. El índice único parcial lo
-- hace cumplir en la base de datos, no en el código.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tree_version_activa
  ON public.epm_tree_versions (activa)
  WHERE activa IS TRUE;

COMMENT ON COLUMN public.epm_tree_versions.checksum IS
  'SHA-256 del YAML fuente. Detecta que el archivo cambió sin subir la versión.';

-- ─── Proyección consultable de los nodos ────────────────────────────────────
-- Permite que el panel de administrador filtre y ordene sin parsear el JSONB.
CREATE TABLE IF NOT EXISTS public.epm_tree_nodes (
  id          UUID     PRIMARY KEY DEFAULT uuid_generate_v4(),
  version_id  UUID     NOT NULL REFERENCES public.epm_tree_versions(id) ON DELETE CASCADE,
  node_id     TEXT     NOT NULL,
  field_key   TEXT,
  block       SMALLINT,
  order_index INTEGER,
  label       TEXT     NOT NULL,
  input_type  TEXT     NOT NULL,
  required    BOOLEAN  NOT NULL DEFAULT TRUE,
  options     JSONB,

  CONSTRAINT uq_tree_nodes_version_node UNIQUE (version_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_tree_nodes_version   ON public.epm_tree_nodes (version_id);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_field_key ON public.epm_tree_nodes (field_key);
CREATE INDEX IF NOT EXISTS idx_tree_nodes_order     ON public.epm_tree_nodes (version_id, block, order_index);

COMMENT ON COLUMN public.epm_tree_nodes.field_key IS
  'NULL en nodos informativos (mensajes de bloque, confirmaciones de resumen) '
  'que no producen ninguna de las 25 columnas exportables.';
