/* ─────────────────────────────────────────────
   EPM — Consolidación Metodológica
   Flujo de árbol de decisiones. Un nodo a la vez.

   Sin framework y sin build. El flujo lo decide el backend: este archivo
   solo pinta el nodo que le devuelve la API y envía la respuesta. No hay
   lógica de ramificación aquí, a propósito: duplicarla sería garantizar
   que el frontend y el motor se desincronicen.
───────────────────────────────────────────── */

'use strict';

const TOKEN_KEY   = 'epm_token';
const SESSION_KEY = 'epm_session_id';

let TOKEN     = localStorage.getItem(TOKEN_KEY) || '';
let SESSION   = localStorage.getItem(SESSION_KEY) || '';
let USUARIO   = null;
let NODO      = null;
let ENVIANDO  = false;

// Campos largos donde tiene sentido ofrecer una sugerencia asistida.
const CAMPOS_SUGERIBLES = new Set([
  'pregunta_problematizadora', 'metodologia', 'descripcion_sesion',
  'publico_especifico', 'logros', 'retos', 'observaciones',
  'cumplimiento_objetivos', 'acciones_mejora', 'recursos',
]);

// ── Utilidades ───────────────────────────────────────────────────────────
const $  = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...hijos) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const h of hijos) {
    if (h == null) continue;
    n.appendChild(typeof h === 'string' ? document.createTextNode(h) : h);
  }
  return n;
};

function mostrarAviso(texto, tipo = 'info') {
  const caja = $('#avisos');
  caja.innerHTML = '';
  caja.appendChild(el('div', { class: `aviso aviso-${tipo}`, text: texto }));
  if (tipo === 'ok') setTimeout(() => { caja.innerHTML = ''; }, 5000);
}

function limpiarAvisos() { $('#avisos').innerHTML = ''; }

// ── Cliente de API ───────────────────────────────────────────────────────
async function api(ruta, opciones = {}) {
  const cfg = {
    method: opciones.method || 'GET',
    headers: { 'Content-Type': 'application/json', ...(opciones.headers || {}) },
  };
  if (TOKEN) cfg.headers['Authorization'] = `Bearer ${TOKEN}`;
  if (opciones.body !== undefined) cfg.body = JSON.stringify(opciones.body);

  const r = await fetch(ruta, cfg);

  // Un 401 en el propio login son credenciales incorrectas, no una sesión
  // expirada: cerrar sesión ahí ocultaba el mensaje real del servidor.
  if (r.status === 401 && !ruta.startsWith('/api/auth/login')) {
    cerrarSesion(true);
    throw new Error('La sesión expiró. Ingresa de nuevo.');
  }

  if (opciones.raw) {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r;
  }

  let datos = null;
  try { datos = await r.json(); } catch { datos = null; }

  if (!r.ok) {
    const err = new Error(mensajeDeError(datos, r.status));
    err.status = r.status;
    err.detalle = datos && datos.detail;
    throw err;
  }
  return datos;
}

function mensajeDeError(datos, status) {
  if (!datos) return `Error ${status}.`;
  const d = datos.detail;
  if (typeof d === 'string') return d;
  if (d && Array.isArray(d.errors)) return d.errors.map(e => e.message).join(' ');
  if (Array.isArray(d) && d.length && d[0].msg) return d[0].msg;
  return `Error ${status}.`;
}

// ── Acceso ───────────────────────────────────────────────────────────────
$('#formAcceso').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('#btnAcceder');
  const err = $('#errorAcceso');
  err.classList.add('oculto');
  btn.disabled = true;
  btn.textContent = 'Verificando…';

  try {
    const datos = await api('/api/auth/login', {
      method: 'POST',
      body: { email: $('#email').value.trim(), password: $('#password').value },
    });
    TOKEN = datos.access_token;
    localStorage.setItem(TOKEN_KEY, TOKEN);
    USUARIO = datos.user;

    if (datos.debe_cambiar_password) {
      $('#pantallaAcceso').classList.add('oculto');
      $('#pantallaCambio').classList.remove('oculto');
      $('#passActual').focus();
      return;
    }
    await iniciarApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove('oculto');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Ingresar';
  }
});

$('#formCambio').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('#errorCambio');
  err.classList.add('oculto');

  const nueva = $('#passNueva').value;
  if (nueva !== $('#passConfirma').value) {
    err.textContent = 'Las contraseñas nuevas no coinciden.';
    err.classList.remove('oculto');
    return;
  }

  try {
    await api('/api/auth/cambiar-password', {
      method: 'POST',
      body: { password_actual: $('#passActual').value, password_nueva: nueva },
    });
    $('#pantallaCambio').classList.add('oculto');
    await iniciarApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove('oculto');
  }
});

function cerrarSesion(expirada = false) {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SESSION_KEY);
  TOKEN = ''; SESSION = ''; USUARIO = null;
  $('#app').classList.add('oculto');
  $('#pantallaCambio').classList.add('oculto');
  $('#pantallaAcceso').classList.remove('oculto');
  if (expirada) {
    const err = $('#errorAcceso');
    err.textContent = 'La sesión expiró. Ingresa de nuevo.';
    err.classList.remove('oculto');
  }
}

$('#btnSalir').addEventListener('click', () => cerrarSesion());

// ── Arranque ─────────────────────────────────────────────────────────────
async function iniciarApp() {
  if (!USUARIO) USUARIO = await api('/api/auth/me');

  $('#usuarioNombre').textContent = USUARIO.nombre;
  $('#usuarioEmail').textContent  = USUARIO.email;
  $('#usuarioRol').textContent    = USUARIO.rol;

  $('#pantallaAcceso').classList.add('oculto');
  $('#app').classList.remove('oculto');

  if (SESSION) {
    try { await cargarNodoActual(); return; }
    catch { localStorage.removeItem(SESSION_KEY); SESSION = ''; }
  }
  await verSesiones();
}

// ── Sesiones ─────────────────────────────────────────────────────────────
$('#btnNueva').addEventListener('click', nuevaSesion);
$('#btnMisSesiones').addEventListener('click', verSesiones);

async function nuevaSesion() {
  limpiarAvisos();
  vista('vistaNodo');
  $('#vistaNodo').innerHTML = '<div class="cargando">Creando consolidación…</div>';
  try {
    const datos = await api('/api/tree/session', { method: 'POST' });
    SESSION = datos.session_id;
    localStorage.setItem(SESSION_KEY, SESSION);
    pintarNodo(datos);
  } catch (ex) {
    mostrarAviso(ex.message, 'error');
  }
}

async function verSesiones() {
  limpiarAvisos();
  vista('vistaSesiones');
  const cont = $('#vistaSesiones');
  cont.innerHTML = '<div class="cargando">Cargando tus consolidaciones…</div>';

  try {
    const { sessions } = await api('/api/tree/sessions');
    cont.innerHTML = '';
    cont.appendChild(el('h2', { class: 'nodo-pregunta', text: 'Mis consolidaciones' }));

    if (!sessions.length) {
      cont.appendChild(el('p', {
        class: 'nodo-ayuda',
        text: 'Todavía no tienes consolidaciones. Empieza una nueva actividad.',
      }));
    } else {
      const tabla = el('table', { class: 'tabla-resumen' });
      tabla.appendChild(el('thead', {}, el('tr', {},
        el('th', { text: 'Iniciada' }), el('th', { text: 'Estado' }),
        el('th', { text: 'Última actividad' }), el('th', { text: '' }))));
      const tbody = el('tbody');
      for (const s of sessions) {
        tbody.appendChild(el('tr', {},
          el('td', { text: fecha(s.created_at) }),
          el('td', {}, el('span', { class: 'etiqueta-bloque', text: s.estado || '—' })),
          el('td', { text: fecha(s.updated_at) }),
          el('td', {}, el('button', {
            class: 'btn',
            onclick: () => { SESSION = s.session_id; localStorage.setItem(SESSION_KEY, SESSION); cargarNodoActual(); },
            text: s.estado === 'completada' ? 'Ver' : 'Retomar',
          })),
        ));
      }
      tabla.appendChild(tbody);
      cont.appendChild(tabla);
    }

    cont.appendChild(el('div', { class: 'acciones' },
      el('button', { class: 'btn btn-primario', onclick: nuevaSesion, text: 'Nueva actividad' })));
  } catch (ex) {
    cont.innerHTML = '';
    mostrarAviso(ex.message, 'error');
  }
}

function fecha(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('es-CO',
      { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

function vista(id) {
  for (const v of ['vistaNodo', 'vistaResumen', 'vistaSesiones', 'vistaAnalisis']) {
    $('#' + v).classList.toggle('oculto', v !== id);
  }
}

// ── Nodo actual ──────────────────────────────────────────────────────────
async function cargarNodoActual() {
  vista('vistaNodo');
  $('#vistaNodo').innerHTML = '<div class="cargando">Cargando…</div>';
  const datos = await api(`/api/tree/session/${SESSION}/current`);
  pintarNodo(datos);
}

function pintarProgreso(progress) {
  const cont = $('#progresoBloques');
  cont.innerHTML = '';
  for (const b of progress.por_bloque) {
    if (!b.bloque) continue;
    const pct = b.total ? Math.round(b.respondidos * 100 / b.total) : 0;
    const completo = b.total > 0 && b.respondidos === b.total;
    cont.appendChild(el('div', { class: `bloque-progreso ${completo ? 'completo' : 'activo'}` },
      el('div', { class: 'titulo' },
        el('b', { text: `Bloque ${b.bloque}` }),
        el('span', { text: `${b.respondidos}/${b.total}` })),
      el('div', { class: 'barra' }, el('i', { style: `width:${pct}%` })),
    ));
  }
}

function pintarNodo(datos) {
  NODO = datos.node;
  pintarProgreso(datos.progress);
  vista('vistaNodo');

  const cont = $('#vistaNodo');
  cont.innerHTML = '';

  // Cabecera
  const cab = el('div', { class: 'nodo-cabecera' });
  if (NODO.block) {
    cab.appendChild(el('span', { class: 'pastilla', text: `Bloque ${NODO.block}` }));
    cab.appendChild(el('span', { text: NODO.block_name }));
  }
  cab.appendChild(el('span', { text: `· ${datos.progress.respondidos} de ${datos.progress.total}` }));
  cont.appendChild(cab);

  cont.appendChild(el('h1', { class: 'nodo-pregunta', id: 'etiquetaNodo', text: NODO.label }));
  if (NODO.help) cont.appendChild(el('p', { class: 'nodo-ayuda', text: NODO.help }));

  // Resumen de coherencia, si el nodo lo trae
  if (NODO.resumen && NODO.resumen.length) {
    const caja = el('div', { class: 'resumen-caja' });
    for (const r of NODO.resumen) {
      const vacio = !r.valor;
      caja.appendChild(el('div', { class: 'resumen-item' },
        el('div', { class: 'clave', text: r.header }),
        el('div', { class: `valor ${vacio ? 'vacio' : ''}`,
                    text: vacio ? 'Sin diligenciar' : r.valor })));
    }
    cont.appendChild(caja);
  }

  // Nodo terminal
  if (NODO.terminal) {
    cont.appendChild(el('div', { class: 'acciones' },
      el('button', { class: 'btn btn-primario', onclick: verResumen, text: 'Revisar los 25 campos' }),
      el('div', { class: 'espaciador' }),
      el('button', { class: 'btn', onclick: retroceder, text: 'Volver atrás' })));
    return;
  }

  // Control de entrada
  const zona = el('div', { id: 'zonaEntrada' });
  zona.appendChild(construirEntrada(NODO));
  cont.appendChild(zona);

  cont.appendChild(el('div', { id: 'errorCampo', role: 'alert', 'aria-live': 'assertive' }));

  // Sugerencia asistida
  if (CAMPOS_SUGERIBLES.has(NODO.field_key) &&
      ['text', 'textarea'].includes(NODO.input_type)) {
    cont.appendChild(el('div', { class: 'sugerir-barra' },
      el('button', { class: 'btn-sugerir', id: 'btnSugerir', type: 'button',
                     onclick: pedirSugerencia, text: 'Sugerir mejora' }),
      el('span', { class: 'sugerir-nota',
                   text: 'Opcional. Reformula lo que ya escribiste; nunca rellena solo.' })));
    cont.appendChild(el('div', { id: 'zonaSugerencias', class: 'sugerencias' }));
  }

  // Acciones
  cont.appendChild(el('div', { class: 'acciones' },
    el('button', { class: 'btn', id: 'btnAtras', onclick: retroceder,
                   disabled: !datos.can_go_back, text: 'Atrás' }),
    el('button', { class: 'btn btn-primario', id: 'btnContinuar',
                   onclick: enviarRespuesta, text: 'Continuar' }),
    el('div', { class: 'espaciador' }),
    el('span', { class: 'guardado', id: 'indicadorGuardado', text: 'Guardado automático' }),
  ));

  const primero = cont.querySelector('input, textarea, select');
  if (primero) primero.focus();
}

function construirEntrada(nodo) {
  const previo = nodo.previous_value;

  if (nodo.input_type === 'single_select') {
    const caja = el('div', { class: 'opciones', role: 'radiogroup',
                             'aria-labelledby': 'etiquetaNodo' });
    nodo.options.forEach((o, i) => {
      const id = `op_${i}`;
      caja.appendChild(el('label', { class: 'opcion', for: id },
        el('input', { type: 'radio', name: 'respuesta', id, value: o.value,
                      checked: previo === o.value }),
        el('span', { class: 'opcion-texto' },
          el('b', { text: o.value }),
          o.help ? el('small', { text: o.help }) : null)));
    });
    return caja;
  }

  if (nodo.input_type === 'multi_select') {
    const previos = Array.isArray(previo) ? previo : [];
    const caja = el('div', { class: 'opciones opciones-multi', role: 'group',
                             'aria-labelledby': 'etiquetaNodo' });
    nodo.options.forEach((o, i) => {
      const id = `op_${i}`;
      caja.appendChild(el('label', { class: 'opcion', for: id },
        el('input', { type: 'checkbox', name: 'respuesta', id, value: o.value,
                      checked: previos.includes(o.value) }),
        el('span', { class: 'opcion-texto' }, el('b', { text: o.value }))));
    });
    return caja;
  }

  if (nodo.input_type === 'textarea') {
    const ta = el('textarea', { class: 'respuesta', id: 'entrada',
                                'aria-labelledby': 'etiquetaNodo', rows: 6 });
    ta.value = previo || '';
    const contador = el('div', { class: 'contador', id: 'contador' });
    const actualizar = () => {
      const n = ta.value.trim().length;
      contador.textContent = `${n} caracteres`;
      contador.classList.toggle('corto', n > 0 && n < 15);
    };
    ta.addEventListener('input', actualizar);
    const envoltorio = el('div', {}, ta, contador);
    actualizar();
    return envoltorio;
  }

  if (nodo.input_type === 'date') {
    const inp = el('input', { type: 'date', class: 'respuesta', id: 'entrada',
                              'aria-labelledby': 'etiquetaNodo' });
    inp.value = previo || '';
    return el('div', { class: 'campo' }, inp);
  }

  if (nodo.input_type === 'integer' || nodo.input_type === 'percent') {
    const inp = el('input', {
      type: 'number', class: 'respuesta', id: 'entrada', inputmode: 'numeric',
      'aria-labelledby': 'etiquetaNodo',
      min: nodo.input_type === 'percent' ? 0 : 0,
      max: nodo.input_type === 'percent' ? 100 : null,
    });
    if (previo !== null && previo !== undefined) inp.value = previo;
    return el('div', { class: 'campo' }, inp);
  }

  // text y duration
  const inp = el('input', { type: 'text', class: 'respuesta', id: 'entrada',
                            'aria-labelledby': 'etiquetaNodo', autocomplete: 'off' });
  inp.value = previo || '';
  const envoltorio = el('div', { class: 'campo' }, inp);

  if (nodo.autocomplete && nodo.autocomplete.length) {
    const listaId = 'sugerencias_' + nodo.node_id;
    inp.setAttribute('list', listaId);
    const dl = el('datalist', { id: listaId });
    for (const v of nodo.autocomplete) dl.appendChild(el('option', { value: v }));
    envoltorio.appendChild(dl);
  }
  return envoltorio;
}

function leerValor() {
  if (!NODO) return null;
  if (NODO.input_type === 'single_select') {
    const sel = document.querySelector('input[name="respuesta"]:checked');
    return sel ? sel.value : null;
  }
  if (NODO.input_type === 'multi_select') {
    return Array.from(document.querySelectorAll('input[name="respuesta"]:checked'))
                .map(i => i.value);
  }
  const inp = $('#entrada');
  return inp ? inp.value : null;
}

function indicador(estado, texto) {
  const n = $('#indicadorGuardado');
  if (!n) return;
  n.className = `guardado ${estado}`;
  n.textContent = texto;
}

async function enviarRespuesta(reintento = 0) {
  if (ENVIANDO) return;
  ENVIANDO = true;

  const btn = $('#btnContinuar');
  if (btn) btn.disabled = true;
  $('#errorCampo').innerHTML = '';
  indicador('enviando', 'Guardando…');

  const origen = window.__origenSugerencia || 'propio';

  try {
    const datos = await api(`/api/tree/session/${SESSION}/answer`, {
      method: 'POST',
      body: { node_id: NODO.node_id, value: leerValor(), origen },
    });
    window.__origenSugerencia = null;
    indicador('ok', 'Guardado');
    limpiarAvisos();
    pintarNodo(datos);
  } catch (ex) {
    if (ex.status === 422 && ex.detalle && Array.isArray(ex.detalle.errors)) {
      indicador('error', 'No guardado');
      const caja = $('#errorCampo');
      for (const e of ex.detalle.errors) {
        caja.appendChild(el('div', { class: 'campo-error', text: e.message }));
      }
    } else if (!ex.status && reintento < 2) {
      // Fallo de red: reintento con espera creciente.
      indicador('enviando', `Sin conexión. Reintentando (${reintento + 1}/2)…`);
      ENVIANDO = false;
      if (btn) btn.disabled = false;
      setTimeout(() => enviarRespuesta(reintento + 1), 1500 * (reintento + 1));
      return;
    } else {
      indicador('error', 'No guardado');
      mostrarAviso(ex.message, 'error');
    }
  } finally {
    ENVIANDO = false;
    if (btn) btn.disabled = false;
  }
}

async function retroceder() {
  try {
    const datos = await api(`/api/tree/session/${SESSION}/back`, { method: 'POST' });
    limpiarAvisos();
    pintarNodo(datos);
  } catch (ex) {
    mostrarAviso(ex.message, 'error');
  }
}

// ── Sugerencia asistida ──────────────────────────────────────────────────
async function pedirSugerencia() {
  const btn = $('#btnSugerir');
  const zona = $('#zonaSugerencias');
  const borrador = (leerValor() || '').toString().trim();

  if (borrador.length < 10) {
    zona.innerHTML = '';
    zona.appendChild(el('div', { class: 'aviso aviso-info',
      text: 'Escribe primero una idea, aunque sea breve. La sugerencia parte de lo que tú redactes; no inventa el contenido por ti.' }));
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Pensando…';
  zona.innerHTML = '';

  try {
    const datos = await api('/api/ideas/sugerir', {
      method: 'POST',
      body: { session_id: SESSION, node_id: NODO.node_id, borrador },
    });
    if (!datos.sugerencias || !datos.sugerencias.length) {
      zona.appendChild(el('div', { class: 'aviso aviso-info',
        text: 'No se obtuvieron sugerencias. Tu texto se guarda igual.' }));
      return;
    }
    for (const s of datos.sugerencias) {
      zona.appendChild(el('div', { class: 'sugerencia' },
        el('p', { text: s }),
        el('button', {
          class: 'btn', type: 'button',
          onclick: () => aplicarSugerencia(s),
          text: 'Usar esta redacción',
        })));
    }
  } catch (ex) {
    // La sugerencia nunca bloquea: el motor no la necesita para avanzar.
    zona.appendChild(el('div', { class: 'aviso aviso-info',
      text: `La sugerencia no está disponible ahora (${ex.message}). Puedes continuar normalmente.` }));
  } finally {
    btn.disabled = false;
    btn.textContent = 'Sugerir mejora';
  }
}

function aplicarSugerencia(texto) {
  const inp = $('#entrada');
  if (!inp) return;
  inp.value = texto;
  inp.dispatchEvent(new Event('input'));
  inp.focus();
  window.__origenSugerencia = 'sugerencia_ia';
  // Si el facilitador la edita después, queda registrado como editada.
  inp.addEventListener('input', function marcar() {
    window.__origenSugerencia = 'sugerencia_editada';
    inp.removeEventListener('input', marcar);
  });
  $('#zonaSugerencias').innerHTML = '';
}

// ── Resumen ──────────────────────────────────────────────────────────────
async function verResumen() {
  vista('vistaResumen');
  const cont = $('#vistaResumen');
  cont.innerHTML = '<div class="cargando">Cargando resumen…</div>';

  try {
    const datos = await api(`/api/tree/session/${SESSION}/summary`);
    cont.innerHTML = '';
    cont.appendChild(el('h1', { class: 'nodo-pregunta', text: 'Resumen de la consolidación' }));
    cont.appendChild(el('p', { class: 'nodo-ayuda',
      text: 'Revisa los campos antes de finalizar. Los que aparecen atenuados no forman parte de la ruta de esta actividad.' }));

    const tabla = el('table', { class: 'tabla-resumen' });
    tabla.appendChild(el('thead', {}, el('tr', {},
      el('th', { text: 'Bloque' }), el('th', { text: 'Campo' }), el('th', { text: 'Valor' }))));
    const tbody = el('tbody');
    for (const c of datos.campos) {
      const vacio = !c.valor;
      tbody.appendChild(el('tr', { class: c.alcanzable ? '' : 'no-alcanzable' },
        el('td', {}, el('span', { class: 'etiqueta-bloque', text: c.block })),
        el('td', { text: c.header }),
        el('td', { class: 'campo-valor' },
          el('span', { class: vacio ? 'valor vacio' : 'valor',
                       text: vacio ? (c.alcanzable ? 'Sin diligenciar' : 'No aplica') : String(c.valor) })),
      ));
    }
    tabla.appendChild(tbody);
    cont.appendChild(tabla);

    cont.appendChild(el('div', { class: 'acciones' },
      el('button', { class: 'btn', onclick: cargarNodoActual, text: 'Seguir editando' }),
      el('button', { class: 'btn btn-primario', onclick: finalizar, text: 'Finalizar consolidación' }),
      el('div', { class: 'espaciador' }),
      el('button', { class: 'btn', onclick: descargarExcel, text: 'Descargar Excel' }),
      el('button', { class: 'btn', onclick: guardarEnSheets, text: 'Guardar en Sheets' }),
    ));
  } catch (ex) {
    cont.innerHTML = '';
    mostrarAviso(ex.message, 'error');
  }
}

async function finalizar() {
  try {
    const datos = await api(`/api/tree/session/${SESSION}/finalize`, { method: 'POST' });
    mostrarAviso(
      datos.estado === 'planeada'
        ? 'Diseño metodológico guardado. La actividad queda como planeada; retómala cuando la ejecutes.'
        : `Consolidación finalizada con ${datos.campos_diligenciados} campos diligenciados.`,
      'ok');
    await verAnalisis();
  } catch (ex) {
    mostrarAviso(ex.message, 'error');
  }
}

async function descargarExcel() {
  try {
    const r = await api('/api/excel/generate', {
      method: 'POST', body: { session_id: SESSION }, raw: true,
    });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = el('a', { href: url, download: 'consolidacion_epm.xlsx' });
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    mostrarAviso('Excel descargado.', 'ok');
  } catch (ex) {
    mostrarAviso(`No se pudo generar el Excel: ${ex.message}`, 'error');
  }
}

async function guardarEnSheets() {
  try {
    const datos = await api('/api/sheets/submit', {
      method: 'POST', body: { session_id: SESSION },
    });
    mostrarAviso(`Guardado en Google Sheets, fila ${datos.sheets_row}.`, 'ok');
  } catch (ex) {
    mostrarAviso(`No se pudo guardar en Sheets: ${ex.message}`, 'error');
  }
}

// ── Análisis ─────────────────────────────────────────────────────────────
async function verAnalisis() {
  vista('vistaAnalisis');
  const cont = $('#vistaAnalisis');
  cont.innerHTML = '<div class="cargando">Generando análisis…</div>';

  try {
    const datos = await api(`/api/ideas/analisis/${SESSION}`, { method: 'POST' });
    cont.innerHTML = '';
    cont.appendChild(el('h1', { class: 'nodo-pregunta', text: 'Análisis e ideas derivadas' }));

    for (const [clave, titulo] of [
      ['resumen', 'Resumen ejecutivo'],
      ['analisis', 'Análisis metodológico'],
      ['recomendaciones', 'Recomendaciones'],
    ]) {
      if (!datos[clave]) continue;
      cont.appendChild(el('div', { class: 'pieza-analisis' },
        el('h3', { text: titulo }),
        el('div', { class: 'cuerpo', text: datos[clave] })));
    }

    if (datos.ideas && datos.ideas.length) {
      const caja = el('div', { class: 'pieza-analisis' }, el('h3', { text: 'Ideas de actividades derivadas' }));
      for (const idea of datos.ideas) {
        const dl = el('dl');
        dl.appendChild(el('dt', { text: 'Público' }));       dl.appendChild(el('dd', { text: idea.publico_sugerido || '—' }));
        dl.appendChild(el('dt', { text: 'Tipo' }));          dl.appendChild(el('dd', { text: idea.tipo_actividad || '—' }));
        dl.appendChild(el('dt', { text: 'Pregunta' }));      dl.appendChild(el('dd', { text: idea.pregunta_problematizadora || '—' }));
        dl.appendChild(el('dt', { text: 'ODS' }));           dl.appendChild(el('dd', { text: (idea.ods || []).join('; ') || '—' }));
        caja.appendChild(el('div', { class: 'idea' }, el('h4', { text: idea.nombre || 'Idea' }), dl));
      }
      cont.appendChild(caja);
    }

    cont.appendChild(el('div', { class: 'acciones' },
      el('button', { class: 'btn', onclick: verResumen, text: 'Volver al resumen' }),
      el('button', { class: 'btn', onclick: verAnalisis, text: 'Regenerar análisis' }),
      el('div', { class: 'espaciador' }),
      el('button', { class: 'btn btn-primario', onclick: verSesiones, text: 'Mis consolidaciones' })));
  } catch (ex) {
    cont.innerHTML = '';
    cont.appendChild(el('h1', { class: 'nodo-pregunta', text: 'Análisis e ideas derivadas' }));
    cont.appendChild(el('div', { class: 'aviso aviso-info',
      text: `La consolidación quedó guardada correctamente. El análisis no se pudo generar ahora (${ex.message}); puedes reintentarlo sin perder nada.` }));
    cont.appendChild(el('div', { class: 'acciones' },
      el('button', { class: 'btn', onclick: verAnalisis, text: 'Reintentar' }),
      el('button', { class: 'btn', onclick: verResumen, text: 'Volver al resumen' })));
  }
}

// ── Inicio ───────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  if (!TOKEN) { $('#pantallaAcceso').classList.remove('oculto'); return; }
  try { await iniciarApp(); }
  catch { cerrarSesion(); }
});
