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
