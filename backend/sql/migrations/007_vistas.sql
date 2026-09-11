-- ═══════════════════════════════════════════════════════════════════════════
-- 007 — Vistas de consulta y compatibilidad de exportación
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente (CREATE OR REPLACE VIEW).
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── 1. Consolidado en vivo desde epm_respuestas ────────────────────────────
-- Una fila por sesión, con los 25 campos pivotados en el orden exacto de
-- FIELD_KEYS. Se alimenta de las respuestas vigentes: ignora las marcadas
-- como stale (quedaron fuera de la ruta tras un retroceso) y las inválidas.
CREATE OR REPLACE VIEW public.v_actividades_completas AS
WITH vigentes AS (
  SELECT session_id, field_key, valor
    FROM public.epm_respuestas
   WHERE field_key IS NOT NULL
     AND stale IS FALSE
     AND es_valida IS TRUE
)
SELECT
  s.session_id,
  s.user_id,
  u.nombre  AS facilitador,
  u.email   AS facilitador_email,
  u.programa AS facilitador_programa,
  s.estado,
  s.tree_version,
  s.current_node_id,
  s.created_at,
  s.completed_at,

  -- ── Bloque 1 ──
  max(v.valor) FILTER (WHERE v.field_key = 'id_actividad')              AS id_actividad,
  max(v.valor) FILTER (WHERE v.field_key = 'programa')                  AS programa,
  max(v.valor) FILTER (WHERE v.field_key = 'linea_accion')              AS linea_accion,
  max(v.valor) FILTER (WHERE v.field_key = 'tipo_actividad')            AS tipo_actividad,
  max(v.valor) FILTER (WHERE v.field_key = 'nombre')                    AS nombre,
  max(v.valor) FILTER (WHERE v.field_key = 'publico')                   AS publico,
  max(v.valor) FILTER (WHERE v.field_key = 'publico_especifico')        AS publico_especifico,
  max(v.valor) FILTER (WHERE v.field_key = 'lugar')                     AS lugar,
  max(v.valor) FILTER (WHERE v.field_key = 'responsable')               AS responsable,
  max(v.valor) FILTER (WHERE v.field_key = 'duracion')                  AS duracion,
  max(v.valor) FILTER (WHERE v.field_key = 'pregunta_problematizadora') AS pregunta_problematizadora,
  max(v.valor) FILTER (WHERE v.field_key = 'ods')                       AS ods,
  max(v.valor) FILTER (WHERE v.field_key = 'metodologia')               AS metodologia,
  max(v.valor) FILTER (WHERE v.field_key = 'descripcion_sesion')        AS descripcion_sesion,
  max(v.valor) FILTER (WHERE v.field_key = 'recursos')                  AS recursos,
  max(v.valor) FILTER (WHERE v.field_key = 'fecha')                     AS fecha,

  -- ── Bloque 2 ──
  max(v.valor) FILTER (WHERE v.field_key = 'logros')                    AS logros,
  max(v.valor) FILTER (WHERE v.field_key = 'retos')                     AS retos,
  max(v.valor) FILTER (WHERE v.field_key = 'observaciones')             AS observaciones,
  max(v.valor) FILTER (WHERE v.field_key = 'comentarios')               AS comentarios,

  -- ── Bloque 3 ──
  max(v.valor) FILTER (WHERE v.field_key = 'instrumento_evaluativo')    AS instrumento_evaluativo,
  max(v.valor) FILTER (WHERE v.field_key = 'participantes_evaluados')   AS participantes_evaluados,
  max(v.valor) FILTER (WHERE v.field_key = 'cumplimiento_objetivos')    AS cumplimiento_objetivos,
  max(v.valor) FILTER (WHERE v.field_key = 'acciones_mejora')           AS acciones_mejora,
  max(v.valor) FILTER (WHERE v.field_key = 'porcentaje_cumplimiento')   AS porcentaje_cumplimiento,

  count(DISTINCT v.field_key)                                  AS campos_diligenciados,
  round(count(DISTINCT v.field_key) * 100.0 / 25, 1)           AS porcentaje_avance
FROM public.epm_sessions s
LEFT JOIN vigentes  v ON v.session_id = s.session_id
LEFT JOIN public.epm_users u ON u.id = s.user_id
GROUP BY s.session_id, s.user_id, u.nombre, u.email, u.programa,
         s.estado, s.tree_version, s.current_node_id, s.created_at, s.completed_at;

COMMENT ON VIEW public.v_actividades_completas IS
  'Consolidado en vivo por sesión, 25 columnas en el orden de FIELD_KEYS. '
  'porcentaje_avance se calcula sobre 25 fijo y es solo indicativo: el avance '
  'autoritativo lo calcula el motor sobre los campos alcanzables en la ruta real.';

-- ─── 2. Compatibilidad de exportación ───────────────────────────────────────
-- epm_actividades guarda fecha como DATE y los numéricos como enteros. Google
-- Sheets y Excel esperan texto en las 25 columnas. Esta vista hace la
-- conversión en un solo lugar, para que los servicios de exportación no tengan
-- que conocer los tipos de la tabla.
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
  coalesce(a.participantes_evaluados::text, '')                 AS participantes_evaluados,
  coalesce(a.cumplimiento_objetivos, '')                        AS cumplimiento_objetivos,
  coalesce(a.acciones_mejora, '')                               AS acciones_mejora,
  coalesce(a.porcentaje_cumplimiento::text, '')                 AS porcentaje_cumplimiento,
  a.sheets_row,
  a.created_at,
  a.updated_at
FROM public.epm_actividades a;

COMMENT ON VIEW public.v_actividades_export IS
  'Las 25 columnas como texto, en el orden de FIELD_KEYS. Fuente única para '
  'Google Sheets, Excel y correo. NULL se devuelve como cadena vacía.';

-- ─── 3. Avance por usuario ──────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_avance_por_usuario AS
SELECT
  u.id            AS user_id,
  u.nombre,
  u.email,
  u.programa,
  u.rol,
  count(s.session_id)                                              AS sesiones_iniciadas,
  count(s.session_id) FILTER (WHERE s.estado = 'completada')       AS sesiones_completadas,
  count(s.session_id) FILTER (WHERE s.estado = 'planeada')         AS sesiones_planeadas,
  count(s.session_id) FILTER (WHERE s.estado = 'en_progreso')      AS sesiones_en_progreso,
  count(s.session_id) FILTER (WHERE s.estado = 'abandonada')       AS sesiones_abandonadas,
  coalesce(round(avg(c.campos_diligenciados), 1), 0)               AS campos_promedio,
  max(s.created_at)                                                AS ultima_sesion
FROM public.epm_users u
LEFT JOIN public.epm_sessions s ON s.user_id = u.id
LEFT JOIN public.v_actividades_completas c ON c.session_id = s.session_id
GROUP BY u.id, u.nombre, u.email, u.programa, u.rol;

COMMENT ON VIEW public.v_avance_por_usuario IS
  'Tablero de avance por facilitador. Incluye usuarios sin sesiones, en cero.';

-- ─── 4. Campos problemáticos ────────────────────────────────────────────────
-- Sirve para saber qué preguntas están mal formuladas: si un campo concentra
-- reintentos y validaciones fallidas, el problema es del enunciado, no del
-- facilitador.
CREATE OR REPLACE VIEW public.v_campos_problematicos AS
SELECT
  r.field_key,
  r.node_id,
  count(*)                                        AS veces_respondido,
  sum(r.intentos)                                 AS intentos_totales,
  round(avg(r.intentos), 2)                       AS intentos_promedio,
  count(*) FILTER (WHERE r.es_valida IS FALSE)    AS validaciones_fallidas,
  count(*) FILTER (WHERE r.stale IS TRUE)         AS marcadas_stale,
  coalesce(h.correcciones, 0)                     AS correcciones_posteriores
FROM public.epm_respuestas r
LEFT JOIN (
  SELECT node_id, count(*) AS correcciones
    FROM public.epm_respuestas_historial
   GROUP BY node_id
) h ON h.node_id = r.node_id
WHERE r.field_key IS NOT NULL
GROUP BY r.field_key, r.node_id, h.correcciones
ORDER BY sum(r.intentos) DESC, count(*) FILTER (WHERE r.es_valida IS FALSE) DESC;

COMMENT ON VIEW public.v_campos_problematicos IS
  'Diagnóstico de calidad de las preguntas: reintentos, validaciones fallidas '
  'y correcciones posteriores por campo.';
