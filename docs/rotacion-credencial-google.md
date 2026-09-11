# Rotación de la credencial de Google expuesta

**Estado:** pendiente de ejecución por el propietario del repositorio.
**Severidad:** alta. Clave privada de cuenta de servicio publicada en un repositorio público.

## Qué pasó

El archivo `backend/service_account.json` fue añadido al repositorio en el commit `98621bc` del **6 de mayo de 2026** y permaneció versionado hasta hoy. El repositorio `StivenFilosofia1995/AI_EPM` es **público**. El archivo contiene la clave privada de una cuenta de servicio de Google Cloud con alcance sobre Google Sheets y Google Drive.

Debes asumir que la credencial está comprometida. No importa que no haya evidencia de uso indebido: los repositorios públicos son rastreados de forma automatizada y continua en busca de credenciales, y el archivo estuvo expuesto durante meses.

## Qué ya está hecho en la rama `feat/arbol-decisiones`

- `backend/service_account.json` dejó de estar rastreado por git (`git rm --cached`). El archivo sigue en tu disco, porque la aplicación local lo necesita hasta que lo reemplaces.
- `.gitignore` ahora excluye ese archivo y otros patrones de credenciales.
- Se añadió `.dockerignore` para que la credencial tampoco entre a la imagen de Docker.

**Esto no basta.** Dejar de rastrear un archivo no lo borra del historial. Cualquiera puede recuperarlo con `git log` sobre cualquier commit anterior. La credencial sigue expuesta hasta que completes los pasos 1 y 2.

---

## Paso 1 — Revocar y rotar en Google Cloud (hazlo primero)

El orden importa: **revoca antes de purgar el historial**. Si purgas primero, la clave sigue siendo válida y ya circuló.

1. Entra a [console.cloud.google.com](https://console.cloud.google.com) y selecciona el proyecto que contiene la cuenta de servicio.
2. Ve a **IAM y administración → Cuentas de servicio**.
3. Identifica la cuenta usada por esta aplicación. Si no recuerdas cuál es, ábrela desde el archivo local `backend/service_account.json` y busca el campo `client_email`. No copies ese archivo a ningún lado ni lo pegues en un chat.
4. Entra a la cuenta → pestaña **Claves**.
5. Localiza la clave cuyo identificador coincida con el campo `private_key_id` del archivo local. **Elimínala.** Desde ese momento la clave filtrada deja de funcionar.
6. En la misma pestaña: **Agregar clave → Crear clave nueva → JSON**. Se descarga un archivo nuevo.
7. Guarda ese archivo como `backend/service_account.json`, reemplazando el anterior. Ya está en `.gitignore`, así que no se volverá a versionar.
8. Para Railway, no subas el archivo: abre el JSON nuevo, copia su contenido completo en una sola línea y pégalo en la variable de entorno `GOOGLE_CREDENTIALS_JSON`.

### Verificación posterior

- **Cuentas de servicio → la cuenta → Permisos**: confirma que solo tenga los roles mínimos necesarios. Si tiene `Editor` o `Propietario` a nivel de proyecto, redúcelo. Para esta aplicación basta con compartir la hoja de cálculo específica con el correo de la cuenta de servicio y no otorgarle roles amplios sobre el proyecto.
- **Registros → Explorador de registros**: filtra por la cuenta de servicio en el rango del 6 de mayo de 2026 a hoy, buscando accesos que no reconozcas. Si aparece actividad ajena, escala el incidente.
- Revisa el historial de versiones de la hoja de Google por si hubo modificaciones no autorizadas.

---

## Paso 2 — Purgar el archivo del historial de git

**No voy a ejecutar esto. Los comandos son para que los corras tú**, porque reescriben el historial completo y requieren un `push --force` que puede afectar a cualquier copia del repositorio que exista.

### Antes de empezar

- Avisa a cualquier persona que tenga el repositorio clonado. Después de la reescritura, sus copias quedan divergentes y tendrán que volver a clonar.
- Haz una copia de seguridad completa:

```bash
git clone --mirror https://github.com/StivenFilosofia1995/AI_EPM.git AI_EPM-backup.git
```

- Instala la herramienta:

```bash
pip install git-filter-repo
```

### La purga

`git filter-repo` exige un clon fresco. Trabaja en una carpeta aparte, no sobre tu copia de trabajo actual:

```bash
git clone https://github.com/StivenFilosofia1995/AI_EPM.git AI_EPM-purga
```

```bash
cd AI_EPM-purga && git filter-repo --path backend/service_account.json --invert-paths --force
```

Verifica que ya no aparezca en ningún commit. Este comando no debe devolver nada:

```bash
git log --all --oneline -- backend/service_account.json
```

`git filter-repo` elimina el remoto por seguridad. Vuelve a añadirlo:

```bash
git remote add origin https://github.com/StivenFilosofia1995/AI_EPM.git
```

Y reescribe el remoto. Este es el comando destructivo:

```bash
git push origin --force --all
```

```bash
git push origin --force --tags
```

### Después de la purga

1. **GitHub conserva los commits huérfanos en su caché.** Aunque ya no estén en ninguna rama, siguen siendo accesibles por su hash durante un tiempo. Abre un ticket en [support.github.com](https://support.github.com) pidiendo la purga de la caché de commits huérfanos del repositorio, citando la remediación de una credencial expuesta.
2. Si el repositorio tiene forks, cada fork conserva su propia copia del historial. Revisa la pestaña de forks y pide su eliminación si los hay.
3. Todas las copias locales deben volver a clonarse. Un `git pull` sobre una copia vieja reintroduce el historial antiguo.

---

## Paso 3 — Considera si el repositorio debe seguir siendo público

Tienes permiso de administrador sobre él. Un repositorio institucional que gestiona datos de facilitadores y actividades de la Fundación EPM no gana nada con ser público, y cada credencial o dato que se filtre por descuido queda expuesto de inmediato.

**Configuración → General → Zona de peligro → Cambiar visibilidad.** Es reversible y no rompe el despliegue en Railway.

## Paso 4 — Prevención

- Activa **Configuración → Seguridad y análisis del código → Escaneo de secretos** y **Protección contra envío de secretos**. Esta última bloquea el `push` cuando detecta una credencial, antes de que llegue al servidor. Es gratuito en repositorios públicos.
- Considera un hook de pre-commit con `gitleaks` o `detect-secrets` para atajarlo en tu máquina.

---

## Lista de verificación

- [ ] Clave antigua eliminada en Google Cloud
- [ ] Clave nueva generada y guardada en `backend/.env` / `GOOGLE_CREDENTIALS_JSON` de Railway
- [ ] Permisos de la cuenta de servicio reducidos al mínimo
- [ ] Registros de acceso revisados desde el 6 de mayo de 2026
- [ ] Historial purgado con `git filter-repo`
- [ ] `push --force` completado
- [ ] Caché de commits huérfanos purgada por el soporte de GitHub
- [ ] Forks revisados
- [ ] Decisión tomada sobre la visibilidad del repositorio
- [ ] Escaneo de secretos y protección contra envío activados
