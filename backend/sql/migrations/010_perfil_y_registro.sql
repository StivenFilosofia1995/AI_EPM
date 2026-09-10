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
