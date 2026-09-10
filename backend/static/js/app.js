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
    // Lista estructurada {field_key, code, message}: permite señalar el
    // campo exacto en vez de mostrar un mensaje suelto al final del formulario.
    err.errores = (datos && datos.errors)
      || (datos && datos.detail && datos.detail.errors)
      || null;
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

// ── Registro ─────────────────────────────────────────────────────────────
let _opcionesRegistro = null;

async function irARegistro() {
  $('#pantallaAcceso').classList.add('oculto');
  $('#pantallaRegistro').classList.remove('oculto');
  $('#errorRegistro').classList.add('oculto');

  if (!_opcionesRegistro) {
    try {
      _opcionesRegistro = await api('/api/auth/registro/opciones');
    } catch {
      _opcionesRegistro = { programas: [], lineas_accion: [] };
    }
    pintarOpcionesRegistro();
  }
  $('#rNombre').focus();
}

function pintarOpcionesRegistro() {
  const sel = $('#rPrograma');
  sel.replaceChildren(el('option', { value: '' }, 'Sin programa asignado'));
  for (const p of _opcionesRegistro.programas) {
    sel.appendChild(el('option', { value: p }, p));
  }

  const caja = $('#rLineas');
  caja.replaceChildren();
  _opcionesRegistro.lineas_accion.forEach((linea, i) => {
    const id = `rLinea_${i}`;
    caja.appendChild(el('label', { class: 'opcion', for: id },
      el('input', { type: 'checkbox', id, value: linea, name: 'rLinea' }),
      el('span', { class: 'opcion-texto' }, el('b', { text: linea }))));
  });
}

function irAAcceso() {
  $('#pantallaRegistro').classList.add('oculto');
  $('#pantallaAcceso').classList.remove('oculto');
  $('#errorAcceso').classList.add('oculto');
  $('#email').focus();
}

$('#btnIrRegistro').addEventListener('click', irARegistro);
$('#btnIrAcceso').addEventListener('click', irAAcceso);

// Relación entre el campo que reporta el backend y su control en pantalla.
const CAMPOS_REGISTRO = {
  nombre: 'rNombre', email: 'rEmail', password: 'rPass', cargo: 'rCargo',
  programa: 'rPrograma', telefono: 'rTelefono', temas: 'rTemas',
  lineas_accion: 'rLineas',
};

function limpiarErroresRegistro() {
  for (const id of Object.values(CAMPOS_REGISTRO)) {
    const control = document.getElementById(id);
    if (!control) continue;
    control.closest('.campo')?.classList.remove('con-error');
    control.removeAttribute('aria-invalid');
  }
  document.querySelectorAll('#formRegistro .campo-error').forEach(n => n.remove());
}

function pintarErroresRegistro(errores) {
  limpiarErroresRegistro();
  const sueltos = [];
  let primero = null;

  for (const e of errores) {
    const id = CAMPOS_REGISTRO[e.field_key];
    const control = id && document.getElementById(id);
    if (!control) { sueltos.push(e.message); continue; }

    const campo = control.closest('.campo');
    campo?.classList.add('con-error');
    control.setAttribute('aria-invalid', 'true');
    campo?.appendChild(el('div', { class: 'campo-error', text: e.message }));
    if (!primero) primero = control;
  }

  if (primero) {
    primero.focus();
    primero.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  return sueltos;
}

$('#formRegistro').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('#errorRegistro');
  const btn = $('#btnRegistrar');
  err.classList.add('oculto');
  limpiarErroresRegistro();

  const pass = $('#rPass').value;
  if (pass !== $('#rPass2').value) {
    const campo = $('#rPass2').closest('.campo');
    campo.classList.add('con-error');
    campo.appendChild(el('div', { class: 'campo-error',
                                  text: 'Las contraseñas no coinciden.' }));
    $('#rPass2').focus();
    return;
  }

  const lineas = Array.from(document.querySelectorAll('input[name="rLinea"]:checked'))
                      .map(i => i.value);

  btn.disabled = true;
  btn.textContent = 'Creando cuenta…';

  try {
    const datos = await api('/api/auth/registro', {
      method: 'POST',
      body: {
        nombre: $('#rNombre').value.trim(),
        email: $('#rEmail').value.trim(),
        password: pass,
        cargo: $('#rCargo').value.trim(),
        programa: $('#rPrograma').value || null,
        telefono: $('#rTelefono').value.trim() || null,
        lineas_accion: lineas,
        temas: $('#rTemas').value.trim() || null,
      },
    });
    TOKEN = datos.access_token;
    localStorage.setItem(TOKEN_KEY, TOKEN);
    USUARIO = datos.user;
    $('#pantallaRegistro').classList.add('oculto');
    await iniciarApp();
    mostrarAviso(`Cuenta creada. Bienvenido, ${USUARIO.nombre}.`, 'ok');
  } catch (ex) {
    const sueltos = Array.isArray(ex.errores) ? pintarErroresRegistro(ex.errores) : null;
    // Solo se usa la caja general para lo que no pertenece a ningún campo.
    if (sueltos === null || sueltos.length) {
      err.textContent = sueltos && sueltos.length ? sueltos.join(' ') : ex.message;
      err.classList.remove('oculto');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = 'Crear cuenta y entrar';
  }
});

function cerrarSesion(expirada = false) {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SESSION_KEY);
  TOKEN = ''; SESSION = ''; USUARIO = null;
  $('#app').classList.add('oculto');
  $('#pantallaCambio').classList.add('oculto');
  $('#pantallaRegistro').classList.add('oculto');
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

  // Quien supervisa necesita poder llegar al panel sin escribir la URL.
  const enlace = $('#enlaceAdmin');
  if (['admin', 'coordinador'].includes(USUARIO.rol)) {
    enlace.classList.remove('oculto');
    enlace.style.display = 'block';
  }

  $('#pantallaAcceso').classList.add('oculto');
  $('#pantallaRegistro').classList.add('oculto');
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
  conversacionCargando('Creando consolidación…');
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
        el('th', { text: 'Última actividad' }), el('th', { text: '' }), el('th', { text: '' }))));
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
          el('td', {}, el('button', {
            class: 'btn',
            onclick: () => descargarSesion(s.session_id),
            text: 'Excel',
          })),
        ));
      }
      tabla.appendChild(tbody);
      cont.appendChild(tabla);
    }

    cont.appendChild(el('div', { class: 'acciones' },
      el('button', { class: 'btn btn-primario', onclick: nuevaSesion, text: 'Nueva actividad' }),
      el('div', { class: 'espaciador' }),
      sessions.length
        ? el('button', { class: 'btn', onclick: descargarTodas,
                         text: 'Descargar todas en Excel' })
        : null));
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
  conversacionCargando('Cargando tu conversación…');
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

// ── Conversación ─────────────────────────────────────────────────────────
// El hilo se reconstruye SIEMPRE desde lo que devuelve el backend, nunca
// desde memoria del navegador: al recargar, la conversación reaparece igual.

function asegurarConversacion() {
  // vistaNodo debe conservar #hilo y #dock: escribir innerHTML sobre la
  // sección los destruía y el siguiente pintado fallaba con null.
  const seccion = $('#vistaNodo');
  if (!$('#hilo')) {
    seccion.className = 'conversacion';
    seccion.replaceChildren(
      el('div', { class: 'hilo', id: 'hilo', 'aria-live': 'polite',
                  'aria-label': 'Conversación' }),
      el('div', { class: 'dock', id: 'dock' }));
  }
  return { hilo: $('#hilo'), dock: $('#dock') };
}

function conversacionCargando(texto) {
  const { hilo, dock } = asegurarConversacion();
  dock.replaceChildren();
  hilo.replaceChildren(el('div', { class: 'cargando', text: texto }));
}

function burbuja(rol, contenido, ayuda) {
  const texto = el('div', { class: 'texto' }, contenido);
  if (ayuda) texto.appendChild(el('span', { class: 'ayuda', text: ayuda }));
  return el('div', { class: `burbuja ${rol}` },
    el('div', { class: 'avatar', text: rol === 'bot' ? 'EPM' : 'TÚ' }),
    texto);
}

function pintarHilo(historial, nodo) {
  const { hilo } = asegurarConversacion();
  hilo.replaceChildren();

  hilo.appendChild(burbuja('bot',
    `Hola, ${USUARIO?.nombre?.split(' ')[0] || 'bienvenido'}. Vamos a consolidar tu actividad paso a paso. Puedes devolverte cuando quieras y todo se guarda solo.`));

  let bloqueActual = null;
  for (const paso of historial || []) {
    if (paso.block && paso.block !== bloqueActual) {
      bloqueActual = paso.block;
      hilo.appendChild(el('div', { class: 'separador-bloque',
        text: `Bloque ${paso.block} · ${paso.block_name}` }));
    }
    hilo.appendChild(burbuja('bot', paso.label));
    if (paso.valor) hilo.appendChild(burbuja('persona', paso.valor));
  }

  if (nodo.block && nodo.block !== bloqueActual) {
    hilo.appendChild(el('div', { class: 'separador-bloque',
      text: `Bloque ${nodo.block} · ${nodo.block_name}` }));
  }

  // Resumen de coherencia, si el nodo lo trae.
  if (nodo.resumen && nodo.resumen.length) {
    const caja = el('div', { class: 'resumen-caja' });
    for (const r of nodo.resumen) {
      const vacio = !r.valor;
      caja.appendChild(el('div', { class: 'resumen-item' },
        el('div', { class: 'clave', text: r.header }),
        el('div', { class: `valor ${vacio ? 'vacio' : ''}`,
                    text: vacio ? 'Sin diligenciar' : r.valor })));
    }
    hilo.appendChild(burbuja('bot', el('div', {}, el('div', { text: nodo.label }), caja), nodo.help));
  } else {
    hilo.appendChild(burbuja('bot', nodo.label, nodo.help));
  }

  hilo.scrollTop = hilo.scrollHeight;
}

function pintarNodo(datos) {
  NODO = datos.node;
  pintarProgreso(datos.progress);
  vista('vistaNodo');
  pintarHilo(datos.historial, NODO);
  pintarDock(datos);
}

function pintarDock(datos) {
  const { dock } = asegurarConversacion();
  dock.replaceChildren();

  if (NODO.terminal) {
    dock.appendChild(el('div', { class: 'chips' },
      el('button', { class: 'chip elegido', onclick: verResumen,
                     text: 'Revisar los 25 campos' }),
      el('button', { class: 'chip', onclick: retroceder, text: 'Volver atrás' })));
    return;
  }

  // Selección única: una pulsación responde y avanza, como en un chat.
  if (NODO.input_type === 'single_select') {
    const chips = el('div', { class: 'chips' });
    for (const o of NODO.options) {
      const b = el('button', {
        class: 'chip' + (NODO.previous_value === o.value ? ' elegido' : ''),
        type: 'button',
        onclick: () => enviarRespuesta(0, o.value),
      }, el('span', {}, o.value));
      if (o.help) b.appendChild(el('small', { text: o.help }));
      chips.appendChild(b);
    }
    dock.appendChild(chips);
    dock.appendChild(pieDock(datos));
    return;
  }

  // Sugerencia de código, cuando el backend la calcula.
  if (NODO.sugerencia) {
    dock.appendChild(el('div', { class: 'sugerencia-codigo' },
      el('span', { text: 'Te propongo:' }),
      el('code', { text: NODO.sugerencia }),
      el('button', { class: 'chip', type: 'button',
        onclick: () => { const i = $('#entrada'); i.value = NODO.sugerencia; i.focus(); },
        text: 'Usar este' }),
      el('span', { class: 'nota-prov',
        text: 'Código provisional generado por el sistema. Si la Fundación ya tiene una nomenclatura oficial, escríbela en su lugar.' })));
  }

  dock.appendChild(construirEntrada(NODO));

  // Sugerencia asistida de redacción.
  if (CAMPOS_SUGERIBLES.has(NODO.field_key) &&
      ['text', 'textarea'].includes(NODO.input_type)) {
    dock.appendChild(el('div', { class: 'sugerir-barra' },
      el('button', { class: 'btn-sugerir', id: 'btnSugerir', type: 'button',
                     onclick: pedirSugerencia, text: 'Ayúdame a redactarlo' }),
      el('span', { class: 'sugerir-nota',
                   text: 'Reformula lo que ya escribiste. Nunca lo rellena solo.' })));
    dock.appendChild(el('div', { id: 'zonaSugerencias', class: 'sugerencias' }));
  }

  dock.appendChild(el('div', { id: 'errorCampo', role: 'alert', 'aria-live': 'assertive' }));
  dock.appendChild(pieDock(datos, true));

  const primero = dock.querySelector('input:not([type=checkbox]), textarea');
  if (primero) primero.focus();
}

function pieDock(datos, conEnviar = false) {
  const fila = el('div', { class: 'acciones' },
    el('button', { class: 'btn', id: 'btnAtras', onclick: retroceder,
                   disabled: !datos.can_go_back, text: 'Atrás' }));
  if (conEnviar) {
    fila.appendChild(el('button', { class: 'btn btn-primario', id: 'btnContinuar',
                                    onclick: () => enviarRespuesta(), text: 'Responder' }));
  }
  fila.appendChild(el('div', { class: 'espaciador' }));
  fila.appendChild(el('span', { class: 'guardado', id: 'indicadorGuardado',
                                text: 'Guardado automático' }));
  return fila;
}

function construirEntrada(nodo) {
  const previo = nodo.previous_value;

  if (nodo.input_type === 'multi_select') {
    const previos = Array.isArray(previo) ? previo : [];
    const caja = el('div', { class: 'opciones opciones-multi', role: 'group',
                             'aria-label': nodo.label });
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
    const ta = el('textarea', { class: 'respuesta', id: 'entrada', rows: 4,
                                'aria-label': nodo.label,
                                placeholder: 'Escribe tu respuesta…' });
    ta.value = previo || '';
    const contador = el('div', { class: 'contador', id: 'contador' });
    const actualizar = () => {
      const n = ta.value.trim().length;
      contador.textContent = `${n} caracteres`;
      contador.classList.toggle('corto', n > 0 && n < 15);
    };
    ta.addEventListener('input', actualizar);
    // Ctrl+Enter envía, como en cualquier chat.
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enviarRespuesta(); }
    });
    const envoltorio = el('div', { class: 'campo' }, ta, contador);
    actualizar();
    return envoltorio;
  }

  let inp;
  if (nodo.input_type === 'date') {
    inp = el('input', { type: 'date', class: 'respuesta', id: 'entrada',
                        'aria-label': nodo.label });
  } else if (nodo.input_type === 'integer' || nodo.input_type === 'percent') {
    inp = el('input', { type: 'number', class: 'respuesta', id: 'entrada',
                        inputmode: 'numeric', 'aria-label': nodo.label, min: 0,
                        max: nodo.input_type === 'percent' ? 100 : null });
  } else {
    inp = el('input', { type: 'text', class: 'respuesta', id: 'entrada',
                        'aria-label': nodo.label, autocomplete: 'off',
                        placeholder: 'Escribe tu respuesta…' });
  }
  if (previo !== null && previo !== undefined) inp.value = previo;
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); enviarRespuesta(); }
  });

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

async function enviarRespuesta(reintento = 0, valorDirecto = undefined) {
  if (ENVIANDO) return;
  ENVIANDO = true;

  const btn = $('#btnContinuar');
  if (btn) btn.disabled = true;
  const caja = $('#errorCampo');
  if (caja) caja.innerHTML = '';
  indicador('enviando', 'Guardando…');

  const origen = window.__origenSugerencia || 'propio';
  const valor = valorDirecto !== undefined ? valorDirecto : leerValor();

  // La respuesta aparece de inmediato en el hilo; si el backend la
  // rechaza, se repinta desde lo que él diga y la burbuja desaparece.
  const textoPropio = Array.isArray(valor) ? valor.join('; ') : String(valor ?? '');
  if (textoPropio.trim()) {
    const hilo = $('#hilo');
    hilo.appendChild(burbuja('persona', textoPropio));
    hilo.appendChild(el('div', { class: 'burbuja bot', id: 'pensando' },
      el('div', { class: 'avatar', text: 'EPM' }),
      el('div', { class: 'escribiendo' }, el('span'), el('span'), el('span'))));
    hilo.scrollTop = hilo.scrollHeight;
  }

  try {
    const datos = await api(`/api/tree/session/${SESSION}/answer`, {
      method: 'POST',
      body: { node_id: NODO.node_id, value: valor, origen },
    });
    window.__origenSugerencia = null;
    indicador('ok', 'Guardado');
    limpiarAvisos();
    pintarNodo(datos);
  } catch (ex) {
    document.getElementById('pensando')?.remove();
    if (ex.status === 422 && ex.detalle && Array.isArray(ex.detalle.errors)) {
      indicador('error', 'No guardado');
      const hilo = $('#hilo');
      // Se retira la burbuja optimista: esa respuesta no quedó guardada.
      hilo.querySelectorAll('.burbuja.persona')[hilo.querySelectorAll('.burbuja.persona').length - 1]?.remove();
      for (const e of ex.detalle.errors) {
        hilo.appendChild(burbuja('bot', e.message));
      }
      hilo.scrollTop = hilo.scrollHeight;
      const caja = $('#errorCampo');
      if (caja) for (const e of ex.detalle.errors) {
        caja.appendChild(el('div', { class: 'campo-error', text: e.message }));
      }
    } else if (!ex.status && reintento < 2) {
      // Fallo de red: reintento con espera creciente.
      indicador('enviando', `Sin conexión. Reintentando (${reintento + 1}/2)…`);
      ENVIANDO = false;
      if (btn) btn.disabled = false;
      setTimeout(() => enviarRespuesta(reintento + 1, valorDirecto), 1500 * (reintento + 1));
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

async function descargarArchivo(ruta, cuerpo, nombre) {
  const r = await api(ruta, { method: 'POST', body: cuerpo, raw: true });
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: nombre });
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

async function descargarSesion(sessionId, etiqueta) {
  try {
    await descargarArchivo('/api/excel/generate', { session_id: sessionId },
                           `consolidacion_epm_${etiqueta || sessionId.slice(0, 8)}.xlsx`);
    mostrarAviso('Excel descargado.', 'ok');
  } catch (ex) {
    mostrarAviso(`No se pudo generar el Excel: ${ex.message}`, 'error');
  }
}

async function descargarTodas() {
  try {
    await descargarArchivo('/api/excel/lote', {}, 'mis_consolidaciones_epm.xlsx');
    mostrarAviso('Excel con todas tus consolidaciones descargado.', 'ok');
  } catch (ex) {
    mostrarAviso(ex.status === 404
      ? 'Todavía no tienes consolidaciones para exportar.'
      : `No se pudo generar el Excel: ${ex.message}`, 'error');
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
