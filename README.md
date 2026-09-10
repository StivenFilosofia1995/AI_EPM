# AI_EPM — Consolidación Metodológica

Sistema de consolidación metodológica de actividades de la Fundación EPM. Un facilitador diligencia los 25 campos del instrumento institucional guiado por un **motor determinista de árbol de decisiones**, y un administrador consulta el avance con trazabilidad por usuario, por sesión y por campo.

## Principio rector

**El modelo de lenguaje no captura datos; solo interpreta datos ya capturados.**

El flujo de preguntas, las ramificaciones y las validaciones son deterministas y viven en el backend. Si el motor necesitara al modelo para avanzar una pregunta, el diseño estaría mal. El modelo interviene en dos lugares, ambos opcionales y ninguno bloqueante:

1. **Análisis e ideas**, al final, alimentado por las respuestas ya guardadas en base de datos.
2. **Sugerencias de redacción**, durante la captura, que reformulan lo que el facilitador ya escribió. Nunca rellenan un campo solas.

Si el modelo falla, se puede consolidar igual.

## Arquitectura

```
Navegador (sin framework, sin build)
   │  index.html + app.js   → vista de facilitador
   │  admin.html            → vista de administrador
   ▼
FastAPI
   │  routes/tree.py        → motor de árbol (sin modelo)
   │  routes/auth.py        → JWT propio, Argon2id
   │  routes/exports.py     → Excel, Sheets, correo
   │  routes/admin.py       → trazabilidad, por rol
   │  routes/ideas.py       → único punto que llama al modelo
   ▼
Supabase (PostgreSQL)
   epm_respuestas           → una fila por respuesta, guardada al responderse
   epm_actividades          → proyección consolidada de 25 columnas
   epm_respuestas_historial → versiones anteriores, por trigger
```

### Piezas clave

| Módulo | Qué hace |
|---|---|
| `app/domain/fields.py` | Fuente de verdad única de los 25 campos, enumeraciones y ODS |
| `app/domain/tree/consolidacion_epm_v1.yaml` | Definición declarativa del árbol: 37 nodos |
| `app/domain/tree_loader.py` | Carga, checksum y validación del grafo |
| `app/domain/validators.py` | Validación estructurada: `{field_key, code, message}` |
| `app/services/tree_engine.py` | Motor determinista. No importa Anthropic |
| `app/services/tree_repository.py` | Persistencia. Propaga errores, no los traga |
| `app/dependencies.py` | Identidad, rol y propiedad de sesión, centralizados |

El estado de avance vive en Supabase, no en memoria del proceso: el sistema sobrevive un reinicio y funciona con varias réplicas.

## Arranque inmediato: modo demostración

Si **no** configuras Supabase, la aplicación arranca igual en modo demostración: los datos viven en memoria y se crea sola una cuenta de administrador.

```bash
cd backend && python -m uvicorn app.main:app --port 8000
```

La contraseña aparece en los registros de arranque, en un bloque destacado. Para fijarla entre despliegues, define `ADMIN_EMAIL` y `ADMIN_PASSWORD` como variables de entorno (en Railway: **Variables → New Variable**).

**Por qué no hay una contraseña escrita en el código:** este repositorio es público. Una contraseña fija en el código sería legible por cualquiera y le daría acceso al panel de administración.

Límites del modo demostración, que la aplicación advierte al arrancar:

- Los datos se pierden en cada despliegue.
- No hay `CHECK`, ni índices únicos, ni triggers: las garantías las da el backend, no Postgres.
- No sirve con varias réplicas.

Sirve para demostrar y desarrollar. Para uso institucional, configura Supabase.

## Puesta en marcha

### 1. Base de datos

Ejecuta en el SQL Editor de Supabase, **en orden numérico**, los archivos de `backend/sql/migrations/` (001 a 009). Son idempotentes. Ver [backend/sql/README.md](backend/sql/README.md).

### 2. Variables de entorno

```bash
cp backend/.env.example backend/.env
```

`backend/.env.example` **se versiona y el repositorio es público**: solo contiene marcadores de posición. Los valores reales van en `backend/.env`, que sí está ignorado, o en las variables de Railway.

Genera la clave de firma de tokens:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3. Primera cuenta de administrador

No hay auto-registro. La primera cuenta se crea con un script que pide la contraseña de forma interactiva:

```bash
cd backend && python -m scripts.crear_admin
```

Desde el panel, ese administrador crea las cuentas de los facilitadores con una contraseña temporal que deben cambiar en su primer ingreso.

### 4. Ejecución

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

Facilitador en `/`, administrador en `/admin`, documentación de la API en `/api/docs`.

Al arrancar se valida el contrato de 25 campos y el grafo del árbol. Si algo está mal, la aplicación **no levanta**: es preferible fallar en el despliegue que a medio diligenciar.

## Variables de entorno

| Variable | Obligatoria | Para qué |
|---|---|---|
| `SUPABASE_URL` | Sí | Proyecto de Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Sí | Salta el RLS. Trátala como contraseña de administrador de base de datos |
| `SECRET_KEY` | Sí | Firma los tokens. Cambiarla invalida toda sesión abierta |
| `CORS_ORIGINS` | Sí | Lista separada por comas. Prohibido `*` |
| `ANTHROPIC_API_KEY` | No | Solo análisis e ideas. Sin ella se consolida igual |
| `GOOGLE_SHEETS_ID`, `GOOGLE_SHEETS_GID` | No | Exportación a Sheets |
| `SERVICE_ACCOUNT_FILE` o `GOOGLE_CREDENTIALS_JSON` | No | Credenciales de Google. Una de las dos |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | No | Envío de correo |
| `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Valores por defecto razonables |

## Pruebas

```bash
cd backend && pytest -q
```

184 pruebas: contrato de campos, validación del grafo, recorridos por cada rama, validaciones con sus límites, idempotencia del motor, retroceso, marcado `stale`, composición, proyección, esquema de ideas y cobertura de autenticación en todas las rutas.

Usan un cliente de Supabase simulado: no necesitan red ni credenciales.

```bash
cd backend && ruff check app tests scripts
```

CI en `.github/workflows/ci.yml`: ruff, mypy permisivo, pytest, y una comprobación que falla si se versiona una credencial o un `.pyc`.

## Seguridad

- Autenticación JWT propia con Argon2id. Bloqueo temporal tras cinco intentos fallidos.
- Toda ruta de datos exige identidad y verifica propiedad de sesión en `app/dependencies.py`.
- Panel de administrador por rol. **Se eliminó el PIN en el parámetro de URL.**
- Límite de tasa en las rutas que llaman al modelo y al envío de correo.
- Los valores escritos en Google Sheets se sanean contra inyección de fórmulas.
- RLS activo en las nueve tablas, con `anon` y `authenticated` revocados.

### Pendiente y urgente

`backend/service_account.json` estuvo versionado en este repositorio público desde el 6 de mayo de 2026. Ya no se rastrea, pero **sigue en el historial de git**. Los pasos de revocación y purga están en [docs/rotacion-credencial-google.md](docs/rotacion-credencial-google.md) y **no se han ejecutado**.

## Estado de verificación

Distinguir lo probado de lo que solo compila:

**Verificado en local**
- El árbol carga, valida el grafo y los 25 campos son alcanzables.
- Los recorridos de planeación, curso, semillero, itinerancia, primera infancia y cumplimiento bajo terminan correctamente.
- Idempotencia, retroceso, marcado `stale`, composición y proyección, contra el cliente simulado.
- Validaciones, incluidos los límites 0, 100 y 101.
- Esquema de ideas frente a respuestas malformadas.
- La aplicación importa y registra sus 31 rutas.
- Ruff sin hallazgos.

**Verificado en navegador**
- Modo demostración completo: acceso, creación de sesión y avance por el árbol, con las respuestas persistidas.
- Las dos vistas cargan con sus hojas de estilo y el logotipo institucional.

**No verificado**
- **Las migraciones SQL no se han ejecutado contra ninguna base de datos.** Están escritas y revisadas, no probadas.
- No se ha hecho ningún recorrido end-to-end contra un Supabase real.
- No se ha probado la escritura en Google Sheets ni el envío de correo.
- No se ha llamado a la API de Anthropic: la etapa de análisis solo se probó con el cliente simulado.
- El despliegue en Railway no se ha reintentado tras estos cambios.

## Limitaciones conocidas

- **El RLS no filtra por usuario.** Se eligió JWT propio en lugar de Supabase Auth, así que no hay `auth.uid()`. La autorización real la aplica el backend; el RLS es una segunda barrera. Está documentado en la cabecera de `sql/migrations/008_rls.sql`.
- **El límite de tasa es por réplica**, no global: vive en memoria del proceso. Un límite realmente global necesitaría Redis o contadores en Postgres.
- **`lugar` no tiene catálogo institucional.** Es texto libre con autocompletado alimentado por lo ya registrado. Marcado como `TODO` en `fields.py` y en la migración 006.
- **`id_actividad` no tiene patrón institucional.** Solo se valida unicidad y longitud mínima.
- **`total_participantes` no se exporta.** La sección 4.2.5 del encargo pide validar `participantes_evaluados` contra un total que no existe entre los 25 campos. Se añadió como nodo de control que se guarda pero no llega a las columnas, para no romper el contrato. Pendiente de confirmación.
- Los endpoints `/api/chat` y `/api/form/*` siguen existiendo marcados como obsoletos, junto con `chat_service.py`. Operan sobre memoria del proceso y se retirarán.
- El frontend anterior se conserva en `backend/static/legacy/` como referencia.

## Contrato de los 25 campos

El orden, las claves y los encabezados están en `app/domain/fields.py` y **no se modifican**: el Excel institucional y la hoja de Google dependen de ellos. Bloque 1 identificación y diseño (16 campos), bloque 2 informe de ejecución (4), bloque 3 evaluación (5).

Cualquier cambio debe hacerse en `fields.py`; `google_sheets_service`, `excel_service` y `email_service` importan de ahí. La prueba `tests/test_fields.py` falla si se desincronizan o si dejan de ser 25.
