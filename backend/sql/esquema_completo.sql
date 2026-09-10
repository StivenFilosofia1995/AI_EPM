-- ═══════════════════════════════════════════════════════════════════════════
-- EPM — Consolidación Metodológica
-- ESQUEMA COMPLETO — script único para Supabase
-- ═══════════════════════════════════════════════════════════════════════════
--
-- CÓMO USARLO
--   1. Abre Supabase Dashboard → SQL Editor → New query
--   2. Pega TODO este archivo
--   3. Run
--
-- Es idempotente: puedes ejecutarlo varias veces sin error. Va dentro de una
-- transacción, así que si algo falla no queda el esquema a medias.
--
-- ARCHIVO GENERADO. No lo edites a mano: es la concatenación de los archivos
-- de migrations/ en orden. Para cambiar algo, edita la migración que
-- corresponda y regenera con:  python sql/generar_esquema_completo.py
--
-- Crea 9 tablas y 5 vistas:
--   epm_sessions, epm_messages, epm_actividades, epm_users,
--   epm_tree_versions, epm_tree_nodes, epm_respuestas,
--   epm_respuestas_historial, epm_analisis_ia
--   v_actividades_completas, v_actividades_export, v_avance_por_usuario,
--   v_campos_problematicos, v_uso_sugerencias
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;


-- ###########################################################################
-- ##  001_esquema_base.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  002_usuarios.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  003_arbol.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  004_respuestas.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  005_estado_y_analisis.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  006_actividades_restricciones.sql
-- ###########################################################################

-- ═══════════════════════════════════════════════════════════════════════════
-- 006 — Restricciones sobre epm_actividades
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
--
-- Lleva a la base de datos las reglas que hoy solo pedía el prompt en lenguaje
-- natural. Las opciones cerradas de la sección 3 del encargo pasan a ser
-- restricciones reales, no sugerencias.
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── Rangos numéricos ───────────────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_porcentaje_cumplimiento'
       AND conrelid = 'public.epm_actividades'::regclass
  ) THEN
    ALTER TABLE public.epm_actividades
      ADD CONSTRAINT chk_porcentaje_cumplimiento
      CHECK (porcentaje_cumplimiento IS NULL
             OR porcentaje_cumplimiento BETWEEN 0 AND 100);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_participantes_evaluados'
       AND conrelid = 'public.epm_actividades'::regclass
  ) THEN
    ALTER TABLE public.epm_actividades
      ADD CONSTRAINT chk_participantes_evaluados
      CHECK (participantes_evaluados IS NULL OR participantes_evaluados >= 0);
  END IF;
END $$;

-- ─── Opciones cerradas confirmadas (sección 3 del encargo) ──────────────────
-- Se permite NULL: una sesión en estado "planeada" puede no haber llegado a
-- todos los campos. La obligatoriedad la impone el motor de árbol, no la tabla.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_programa'
       AND conrelid = 'public.epm_actividades'::regclass
  ) THEN
    ALTER TABLE public.epm_actividades
      ADD CONSTRAINT chk_programa
      CHECK (programa IS NULL OR programa IN (
        'Biblioteca_EPM', 'Programa_UVA', 'Museo_del_Agua', 'Parque_de_los_deseos'
      ));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_linea_accion'
       AND conrelid = 'public.epm_actividades'::regclass
  ) THEN
    ALTER TABLE public.epm_actividades
      ADD CONSTRAINT chk_linea_accion
      CHECK (linea_accion IS NULL OR linea_accion IN (
        'Educación', 'Cultura', 'Gestión Social', 'Gestión ambiental'
      ));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_tipo_actividad'
       AND conrelid = 'public.epm_actividades'::regclass
  ) THEN
    ALTER TABLE public.epm_actividades
      ADD CONSTRAINT chk_tipo_actividad
      CHECK (tipo_actividad IS NULL OR tipo_actividad IN (
        'Actividad de sensibilización', 'Club', 'Curso',
        'Itinerancia', 'Semillero', 'Taller'
      ));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'chk_publico'
       AND conrelid = 'public.epm_actividades'::regclass
  ) THEN
    ALTER TABLE public.epm_actividades
      ADD CONSTRAINT chk_publico
      CHECK (publico IS NULL OR publico IN (
        'Primera infancia', 'Niños', 'Adolescentes',
        'Jóvenes', 'Adultos', 'Adultos mayores'
      ));
  END IF;
END $$;

-- TODO: `lugar` queda como texto libre. No hay catálogo institucional
-- confirmado de espacios por programa. Cuando se entregue, añadir aquí la
-- restricción correspondiente o una tabla de catálogo con clave foránea.

-- ─── Unicidad de id_actividad ───────────────────────────────────────────────
-- Hace cumplir en la base de datos la unicidad que antes solo pedía el prompt.
-- Parcial: varias sesiones sin id_actividad asignado pueden coexistir.
CREATE UNIQUE INDEX IF NOT EXISTS uq_actividades_id_actividad
  ON public.epm_actividades (id_actividad)
  WHERE id_actividad IS NOT NULL;

-- TODO: no se valida ningún patrón de formato para `id_actividad`. No hay
-- patrón institucional confirmado. El backend valida solo unicidad y longitud
-- mínima. Cuando se entregue el patrón real, añadir aquí el CHECK.

-- ###########################################################################
-- ##  007_vistas.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  008_rls.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  009_origen_y_estimado.sql
-- ###########################################################################

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

-- ###########################################################################
-- ##  010_perfil_y_registro.sql
-- ###########################################################################

-- ═══════════════════════════════════════════════════════════════════════════
-- 010 — Perfil profesional y registro abierto
-- ═══════════════════════════════════════════════════════════════════════════
-- Idempotente.
--
-- Convive con la creación de cuentas desde el panel: un administrador sigue
-- pudiendo dar de alta a alguien, y además cualquier persona puede registrarse
-- por su cuenta.
--
-- SALVAGUARDA: el rol de una cuenta auto-registrada SIEMPRE es 'facilitador'.
-- El backend lo fuerza y no lo toma del formulario; de lo contrario cualquiera
-- se haría administrador desde la pantalla de registro. Subir a 'coordinador'
-- o 'admin' solo puede hacerlo un administrador desde el panel.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.epm_users
  -- Quién es y a qué se dedica
  ADD COLUMN IF NOT EXISTS cargo           TEXT,
  ADD COLUMN IF NOT EXISTS telefono        TEXT,
  -- Qué forma
  ADD COLUMN IF NOT EXISTS lineas_accion   JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS temas           TEXT,
  -- Trazabilidad del origen de la cuenta
  ADD COLUMN IF NOT EXISTS auto_registrado BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS registrado_at   TIMESTAMPTZ;

COMMENT ON COLUMN public.epm_users.cargo IS
  'A qué se dedica la persona. Por ejemplo: mediadora de lectura, '
  'tallerista ambiental, coordinadora de semilleros.';
COMMENT ON COLUMN public.epm_users.lineas_accion IS
  'Líneas de acción en las que forma. Arreglo de valores de LINEAS_ACCION.';
COMMENT ON COLUMN public.epm_users.temas IS
  'Qué forma: temas, públicos y tipos de actividad que facilita.';
COMMENT ON COLUMN public.epm_users.auto_registrado IS
  'TRUE si la persona se registró por su cuenta; FALSE si la creó un '
  'administrador desde el panel.';

CREATE INDEX IF NOT EXISTS idx_users_auto_registrado
  ON public.epm_users (auto_registrado, created_at DESC)
  WHERE auto_registrado IS TRUE;

-- ─── Vista de directorio para el panel ──────────────────────────────────────
-- Quién es cada quien, a qué se dedica y qué forma, junto a su actividad real
-- en el sistema. Sin exponer nunca password_hash.
CREATE OR REPLACE VIEW public.v_directorio_facilitadores AS
SELECT
  u.id                AS user_id,
  u.nombre,
  u.email,
  u.rol,
  u.cargo,
  u.programa,
  u.lineas_accion,
  u.temas,
  u.telefono,
  u.activo,
  u.auto_registrado,
  u.created_at        AS registrado_el,
  u.ultimo_acceso,
  count(s.session_id)                                         AS sesiones,
  count(s.session_id) FILTER (WHERE s.estado = 'completada')   AS completadas
FROM public.epm_users u
LEFT JOIN public.epm_sessions s ON s.user_id = u.id
GROUP BY u.id, u.nombre, u.email, u.rol, u.cargo, u.programa,
         u.lineas_accion, u.temas, u.telefono, u.activo,
         u.auto_registrado, u.created_at, u.ultimo_acceso;

COMMENT ON VIEW public.v_directorio_facilitadores IS
  'Directorio de personas registradas con su perfil profesional y su '
  'actividad. No expone el hash de contraseña.';

REVOKE ALL ON public.v_directorio_facilitadores FROM anon, authenticated;

COMMIT;

-- ═══════════════════════════════════════════════════════════════════════════
-- VERIFICACIÓN — ejecuta esto después, en una consulta aparte
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Deben aparecer 9 tablas:
--   SELECT table_name FROM information_schema.tables
--    WHERE table_schema = 'public' AND table_name LIKE 'epm_%' ORDER BY 1;
--
-- Deben aparecer 5 vistas:
--   SELECT table_name FROM information_schema.views
--    WHERE table_schema = 'public' AND table_name LIKE 'v_%' ORDER BY 1;
--
-- rowsecurity debe ser true en las 9:
--   SELECT tablename, rowsecurity FROM pg_tables
--    WHERE schemaname = 'public' AND tablename LIKE 'epm_%' ORDER BY 1;
--
-- SIGUIENTE PASO: crear la primera cuenta de administrador. NO se hace con
-- SQL a propósito: el hash Argon2id lo genera el backend.
--   cd backend && python -m scripts.crear_admin
-- ═══════════════════════════════════════════════════════════════════════════
