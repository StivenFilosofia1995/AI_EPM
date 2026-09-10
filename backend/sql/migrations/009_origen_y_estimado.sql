-- ═══════════════════════════════════════════════════════════════════════════
-- 009 — Trazabilidad del origen de la respuesta y marca de estimado
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
--
-- Dos cosas:
--
-- 1. `origen` registra si el facilitador escribió la respuesta por su cuenta o
--    si partió de una sugerencia asistida. En datos institucionales importa
--    poder distinguirlo: el panel de administrador lo muestra, y permite medir
--    cuánto del contenido consolidado nació de una sugerencia automática.
--
-- 2. La marca "(estimado)" de participantes_evaluados se DERIVA del
--    instrumento evaluativo en lugar de almacenarse. Cuando el instrumento es
--    observación directa, el conteo es por definición un estimado. Derivarlo
--    evita duplicar un dato que ya está en la fila y mantiene la columna
--    participantes_evaluados como INTEGER limpio.
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── 1. Origen de la respuesta ──────────────────────────────────────────────
ALTER TABLE public.epm_respuestas
  ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'propio';

ALTER TABLE public.epm_respuestas_historial
  ADD COLUMN IF NOT EXISTS origen TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_respuestas_origen'
       AND conrelid = 'public.epm_respuestas'::regclass
  ) THEN
    ALTER TABLE public.epm_respuestas
      ADD CONSTRAINT chk_respuestas_origen
      CHECK (origen IN ('propio', 'sugerencia_ia', 'sugerencia_editada'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_respuestas_origen
  ON public.epm_respuestas (origen)
  WHERE origen <> 'propio';

COMMENT ON COLUMN public.epm_respuestas.origen IS
  'propio: el facilitador lo escribió. sugerencia_ia: aceptó una sugerencia '
  'tal cual. sugerencia_editada: partió de una sugerencia y la modificó.';

-- El trigger de historial debe arrastrar también la columna nueva.
CREATE OR REPLACE FUNCTION public.archivar_respuesta()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.valor IS DISTINCT FROM NEW.valor
     OR OLD.valor_json IS DISTINCT FROM NEW.valor_json THEN

    INSERT INTO public.epm_respuestas_historial (
      respuesta_id, version_num, session_id, user_id, tree_version, node_id,
      field_key, valor, valor_json, es_valida, stale, intentos, origen, answered_at
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
      OLD.intentos, OLD.origen, OLD.answered_at
    );
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── 2. participantes_evaluados con marca de estimado derivada ──────────────
CREATE OR REPLACE VIEW public.v_actividades_export AS
SELECT
  a.session_id,
  a.user_id,
  coalesce(a.id_actividad, '')                                  AS id_actividad,
  coalesce(a.programa, '')                                      AS programa,
  coalesce(a.linea_accion, '')                                  AS linea_accion,
  coalesce(a.tipo_actividad, '')                                AS tipo_actividad,
  coalesce(a.nombre, '')                                        AS nombre,
  coalesce(a.publico, '')                                       AS publico,
  coalesce(a.publico_especifico, '')                            AS publico_especifico,
  coalesce(a.lugar, '')                                         AS lugar,
  coalesce(a.responsable, '')                                   AS responsable,
  coalesce(a.duracion, '')                                      AS duracion,
  coalesce(a.pregunta_problematizadora, '')                     AS pregunta_problematizadora,
  coalesce(a.ods, '')                                           AS ods,
  coalesce(a.metodologia, '')                                   AS metodologia,
  coalesce(a.descripcion_sesion, '')                            AS descripcion_sesion,
  coalesce(a.recursos, '')                                      AS recursos,
  coalesce(to_char(a.fecha, 'YYYY-MM-DD'), '')                  AS fecha,
  coalesce(a.logros, '')                                        AS logros,
  coalesce(a.retos, '')                                         AS retos,
  coalesce(a.observaciones, '')                                 AS observaciones,
  coalesce(a.comentarios, '')                                   AS comentarios,
  coalesce(a.instrumento_evaluativo, '')                        AS instrumento_evaluativo,
  CASE
    WHEN a.participantes_evaluados IS NULL THEN ''
    WHEN a.instrumento_evaluativo = 'Observación directa'
      THEN a.participantes_evaluados::text || ' (estimado)'
    ELSE a.participantes_evaluados::text
  END                                                           AS participantes_evaluados,
  coalesce(a.cumplimiento_objetivos, '')                        AS cumplimiento_objetivos,
  coalesce(a.acciones_mejora, '')                               AS acciones_mejora,
  coalesce(a.porcentaje_cumplimiento::text, '')                 AS porcentaje_cumplimiento,
  a.sheets_row,
  a.created_at,
  a.updated_at
FROM public.epm_actividades a;

COMMENT ON VIEW public.v_actividades_export IS
  'Las 25 columnas como texto, en el orden de FIELD_KEYS. NULL se devuelve '
  'como cadena vacía. participantes_evaluados se marca como estimado cuando '
  'el instrumento fue observación directa.';

REVOKE ALL ON public.v_actividades_export FROM anon, authenticated;

-- ─── 3. Origen en la vista de campos problemáticos ──────────────────────────
CREATE OR REPLACE VIEW public.v_uso_sugerencias AS
SELECT
  r.field_key,
  count(*)                                                        AS respuestas,
  count(*) FILTER (WHERE r.origen = 'sugerencia_ia')              AS aceptadas_tal_cual,
  count(*) FILTER (WHERE r.origen = 'sugerencia_editada')         AS aceptadas_y_editadas,
  count(*) FILTER (WHERE r.origen = 'propio')                     AS escritas_a_mano,
  round(
    count(*) FILTER (WHERE r.origen <> 'propio') * 100.0 / nullif(count(*), 0),
    1
  )                                                               AS porcentaje_asistido
FROM public.epm_respuestas r
WHERE r.field_key IS NOT NULL
  AND r.stale IS FALSE
GROUP BY r.field_key
ORDER BY porcentaje_asistido DESC NULLS LAST;

COMMENT ON VIEW public.v_uso_sugerencias IS
  'Cuánto del contenido consolidado nació de una sugerencia asistida, por campo.';

REVOKE ALL ON public.v_uso_sugerencias FROM anon, authenticated;
