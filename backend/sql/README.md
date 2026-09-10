# Migraciones de base de datos

Esquema PostgreSQL del proyecto, en Supabase.

## Camino rápido: un solo script

Si vas a crear el esquema desde cero, pega **`esquema_completo.sql`** entero en el SQL Editor de Supabase y ejecútalo. Es la concatenación de todas las migraciones en orden, dentro de una transacción: si algo falla, no queda el esquema a medias.

Ese archivo es **generado**. No lo edites a mano: cambia la migración correspondiente y regenera con `python sql/generar_esquema_completo.py`.

## Camino por migraciones

Abre **Supabase Dashboard → SQL Editor** y ejecuta los archivos de `migrations/` **en orden numérico estricto**. Cada uno pega completo en el editor y se corre de una vez.

Todas las migraciones son **idempotentes**: puedes ejecutarlas dos veces sin error. Si una falla a la mitad, corrígela y vuelve a ejecutar el archivo entero.

```
001_esquema_base.sql
002_usuarios.sql
003_arbol.sql
004_respuestas.sql
005_estado_y_analisis.sql
006_actividades_restricciones.sql
007_vistas.sql
008_rls.sql
```

El orden importa: 002 añade claves foráneas hacia tablas de 001, 004 referencia a 002, y 007 y 008 dependen de todas las anteriores.

## Qué hace cada una

| # | Archivo | Qué crea | Depende de |
|---|---|---|---|
| 001 | `esquema_base` | `epm_sessions`, `epm_messages`, `epm_actividades`, función `update_updated_at()` | — |
| 002 | `usuarios` | `epm_users`; añade `user_id` a sesiones y actividades | 001 |
| 003 | `arbol` | `epm_tree_versions`, `epm_tree_nodes` | 001 |
| 004 | `respuestas` | `epm_respuestas`, `epm_respuestas_historial`, trigger de archivado | 002 |
| 005 | `estado_y_analisis` | Estado en `epm_sessions`; `epm_analisis_ia` | 002 |
| 006 | `actividades_restricciones` | CHECKs de rango y de opciones cerradas; unicidad de `id_actividad` | 001 |
| 007 | `vistas` | `v_actividades_completas`, `v_actividades_export`, `v_avance_por_usuario`, `v_campos_problematicos` | 001–005 |
| 008 | `rls` | RLS activo, políticas de `service_role`, revocación a `anon` y `authenticated` | 001–007 |

## Decisiones que están incorporadas en este esquema

**Base de datos nueva, sin datos heredados.** Por eso `fecha` es `DATE`, `participantes_evaluados` es `INTEGER` y `porcentaje_cumplimiento` es `SMALLINT`, en lugar del `TEXT` del esquema anterior. La vista `v_actividades_export` los devuelve como texto para que Google Sheets y Excel no noten la diferencia.

**Autenticación con JWT propio, no Supabase Auth.** `epm_users` guarda `password_hash` y no referencia a `auth.users`. La consecuencia está documentada en la cabecera de `008_rls.sql`: el RLS no puede expresar "cada facilitador ve solo lo suyo" porque no hay `auth.uid()`; esa regla la aplica el backend y el RLS queda como segunda barrera.

**Las cuentas las crea un administrador.** No hay auto-registro. La primera cuenta de administrador se crea con un script del backend, no con un `INSERT` en estas migraciones: poner una contraseña por defecto en un archivo versionado en un repositorio público sería repetir el incidente del `service_account.json`.

## Contrato de los 25 campos

`epm_actividades` conserva exactamente los nombres de `FIELD_KEYS`, en el mismo orden. Ese orden es el del Excel institucional y la hoja de Google, y **no se modifica**. Cualquier cambio en las columnas debe reflejarse en `backend/app/domain/fields.py`, que es la fuente de verdad única, y la prueba de sincronía debe fallar si se desincronizan.

## Cómo revertir

No hay archivos de reversión automática. Al ser una base nueva, la vía más limpia ante un problema es recrear el proyecto de Supabase y volver a ejecutar de 001 a 008.

Si necesitas revertir a mano, este es el orden inverso. **Estos comandos destruyen datos**: ejecútalos solo con conocimiento de causa.

```sql
-- 008: desactivar RLS (las políticas caen con las tablas)
ALTER TABLE public.epm_respuestas DISABLE ROW LEVEL SECURITY;
-- ... repetir por tabla

-- 007: vistas
DROP VIEW IF EXISTS public.v_campos_problematicos;
DROP VIEW IF EXISTS public.v_avance_por_usuario;
DROP VIEW IF EXISTS public.v_actividades_export;
DROP VIEW IF EXISTS public.v_actividades_completas;

-- 006: restricciones
ALTER TABLE public.epm_actividades DROP CONSTRAINT IF EXISTS chk_porcentaje_cumplimiento;
ALTER TABLE public.epm_actividades DROP CONSTRAINT IF EXISTS chk_participantes_evaluados;
ALTER TABLE public.epm_actividades DROP CONSTRAINT IF EXISTS chk_programa;
ALTER TABLE public.epm_actividades DROP CONSTRAINT IF EXISTS chk_linea_accion;
ALTER TABLE public.epm_actividades DROP CONSTRAINT IF EXISTS chk_tipo_actividad;
ALTER TABLE public.epm_actividades DROP CONSTRAINT IF EXISTS chk_publico;
DROP INDEX IF EXISTS public.uq_actividades_id_actividad;

-- 005
DROP TABLE IF EXISTS public.epm_analisis_ia;
ALTER TABLE public.epm_sessions DROP CONSTRAINT IF EXISTS chk_sessions_estado;
ALTER TABLE public.epm_sessions
  DROP COLUMN IF EXISTS estado,
  DROP COLUMN IF EXISTS tree_version,
  DROP COLUMN IF EXISTS current_node_id,
  DROP COLUMN IF EXISTS completed_at;

-- 004
DROP TABLE IF EXISTS public.epm_respuestas_historial;
DROP TABLE IF EXISTS public.epm_respuestas;
DROP FUNCTION IF EXISTS public.archivar_respuesta();

-- 003
DROP TABLE IF EXISTS public.epm_tree_nodes;
DROP TABLE IF EXISTS public.epm_tree_versions;

-- 002
ALTER TABLE public.epm_actividades DROP COLUMN IF EXISTS user_id;
ALTER TABLE public.epm_sessions    DROP COLUMN IF EXISTS user_id;
DROP TABLE IF EXISTS public.epm_users;

-- 001
DROP TABLE IF EXISTS public.epm_messages;
DROP TABLE IF EXISTS public.epm_actividades;
DROP TABLE IF EXISTS public.epm_sessions;
DROP FUNCTION IF EXISTS public.update_updated_at();
```

## Verificación después de ejecutar

Las tablas creadas deben ser nueve:

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name LIKE 'epm_%'
ORDER BY table_name;
```

Las vistas, cuatro:

```sql
SELECT table_name FROM information_schema.views
WHERE table_schema = 'public' AND table_name LIKE 'v_%'
ORDER BY table_name;
```

RLS activo en las nueve tablas (`rowsecurity` debe ser `true` en todas):

```sql
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' AND tablename LIKE 'epm_%'
ORDER BY tablename;
```

## Estado de verificación

Estas migraciones **no se han ejecutado contra una base de datos real**. Están escritas y revisadas, pero no probadas en Supabase. Repórtame cualquier error que arroje el SQL Editor y lo corrijo.
