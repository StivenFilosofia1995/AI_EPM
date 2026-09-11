-- ═══════════════════════════════════════════════════════════════════════════
-- 008 — Row Level Security
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente (DROP POLICY IF EXISTS antes de cada CREATE POLICY).
--
-- CONTEXTO IMPORTANTE — leer antes de modificar este archivo:
--
-- Se eligió autenticación con JWT propio, no Supabase Auth. El backend se
-- conecta con la clave service_role, que SALTA el RLS por diseño. Por lo tanto:
--
--   · La autorización real (qué facilitador ve qué sesión) la aplica el
--     backend, en una dependencia central de FastAPI cubierta por pruebas.
--   · El RLS de este archivo es una SEGUNDA línea de defensa: garantiza que
--     si la clave anónima se filtra, o si alguien alcanza la API REST de
--     PostgREST directamente, no pueda leer ni escribir absolutamente nada.
--
-- Con Supabase Auth, estas políticas habrían podido expresar "cada facilitador
-- solo ve lo suyo" usando auth.uid(). Con JWT propio no hay auth.uid() que
-- consultar, así que la política por usuario no es expresable aquí. Está
-- documentado como consecuencia asumida de la decisión, no como omisión.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.epm_sessions             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_messages             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_actividades          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_tree_versions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_tree_nodes           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_respuestas           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_respuestas_historial ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.epm_analisis_ia          ENABLE ROW LEVEL SECURITY;

-- ─── Políticas de service_role ──────────────────────────────────────────────
-- Permite: todas las operaciones sobre todas las filas.
-- A quién: únicamente al rol service_role, que es el que usa el backend.
-- Efecto sobre los demás roles (anon, authenticated): al estar el RLS activo
-- y no existir ninguna política que los cubra, el acceso queda denegado por
-- omisión. Es el comportamiento deseado.

DROP POLICY IF EXISTS service_role_full_sessions ON public.epm_sessions;
CREATE POLICY service_role_full_sessions
  ON public.epm_sessions FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_messages ON public.epm_messages;
CREATE POLICY service_role_full_messages
  ON public.epm_messages FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_actividades ON public.epm_actividades;
CREATE POLICY service_role_full_actividades
  ON public.epm_actividades FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_users ON public.epm_users;
CREATE POLICY service_role_full_users
  ON public.epm_users FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_tree_versions ON public.epm_tree_versions;
CREATE POLICY service_role_full_tree_versions
  ON public.epm_tree_versions FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_tree_nodes ON public.epm_tree_nodes;
CREATE POLICY service_role_full_tree_nodes
  ON public.epm_tree_nodes FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_respuestas ON public.epm_respuestas;
CREATE POLICY service_role_full_respuestas
  ON public.epm_respuestas FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_historial ON public.epm_respuestas_historial;
CREATE POLICY service_role_full_historial
  ON public.epm_respuestas_historial FOR ALL TO service_role
  USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS service_role_full_analisis ON public.epm_analisis_ia;
CREATE POLICY service_role_full_analisis
  ON public.epm_analisis_ia FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ─── Cierre explícito para los roles públicos ───────────────────────────────
-- Supabase concede permisos amplios a anon y authenticated por defecto en el
-- esquema public. El RLS ya bloquea las filas, pero revocar los privilegios de
-- tabla añade una barrera anterior: la consulta ni siquiera se planifica.
-- Especialmente relevante para epm_users, que contiene hashes de contraseña.

REVOKE ALL ON public.epm_users                FROM anon, authenticated;
REVOKE ALL ON public.epm_sessions             FROM anon, authenticated;
REVOKE ALL ON public.epm_messages             FROM anon, authenticated;
REVOKE ALL ON public.epm_actividades          FROM anon, authenticated;
REVOKE ALL ON public.epm_respuestas           FROM anon, authenticated;
REVOKE ALL ON public.epm_respuestas_historial FROM anon, authenticated;
REVOKE ALL ON public.epm_analisis_ia          FROM anon, authenticated;
REVOKE ALL ON public.epm_tree_versions        FROM anon, authenticated;
REVOKE ALL ON public.epm_tree_nodes           FROM anon, authenticated;

-- Las vistas heredan la seguridad de sus tablas base, pero se revocan también
-- para que no aparezcan siquiera listadas en la API REST autogenerada.
REVOKE ALL ON public.v_actividades_completas FROM anon, authenticated;
REVOKE ALL ON public.v_actividades_export    FROM anon, authenticated;
REVOKE ALL ON public.v_avance_por_usuario    FROM anon, authenticated;
REVOKE ALL ON public.v_campos_problematicos  FROM anon, authenticated;
