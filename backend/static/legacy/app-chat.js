/* ─────────────────────────────────────────
   EPM — Consolidación Metodológica
   Frontend Application
───────────────────────────────────────── */

'use strict';

// ── Persistent user name ──────────────────────────────────────────────────
const USER_NAME_KEY = 'epm_user_name';
let USER_NAME = localStorage.getItem(USER_NAME_KEY) || '';

// ── Persistent session ID (scoped per user) ────────────────────────────────
const SESSION_KEY = 'epm_session_id';
let SESSION_ID = localStorage.getItem(SESSION_KEY);
if (!SESSION_ID) {
  SESSION_ID = generateUUID();
  localStorage.setItem(SESSION_KEY, SESSION_ID);
}

let isStreaming  = false;
let currentStep  = 0;

// ── DOM refs ───────────────────────────────────────────────────────────────
const chatEl       = document.getElementById('chat');
const inputEl      = document.getElementById('input');
const sendBtnEl    = document.getElementById('sendBtn');
const statusDotEl  = document.getElementById('statusDot');
const statusTxtEl  = document.getElementById('statusText');
const downloadBtn  = document.getElementById('btnDownload');
const sheetsBtn    = document.getElementById('btnSheets');
const newBtn       = document.getElementById('btnNew');
const resetBtn     = document.getElementById('btnReset');
const logoutBtn    = document.getElementById('btnLogout');
const emailBtn     = document.getElementById('btnEmail');
const sidebar      = document.getElementById('sidebar');
const menuBtn      = document.getElementById('menuBtn');
const progressFill = document.getElementById('progressFill');
const progressLbl  = document.getElementById('progressLabel');
const memoryBadge  = document.getElementById('memoryBadge');
const toastEl      = document.getElementById('toast');
const userBadgeEl  = document.getElementById('userBadge');
const userTextEl   = document.getElementById('userText');

// ── Overlay (mobile) ───────────────────────────────────────────────────────
const overlay = document.createElement('div');
overlay.className = 'overlay';
document.body.appendChild(overlay);

menuBtn.addEventListener('click', () => {
  sidebar.classList.toggle('open');
  // Only show overlay on mobile
  if (window.innerWidth <= 900) {
    overlay.classList.toggle('visible');
  }
});
overlay.addEventListener('click', () => {
  sidebar.classList.remove('open');
  overlay.classList.remove('visible');
});
// Hide overlay when resizing to desktop
window.addEventListener('resize', () => {
  if (window.innerWidth > 900) {
    overlay.classList.remove('visible');
  }
});

// ── Utilities ──────────────────────────────────────────────────────────────
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function getTime() {
  return new Date().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });
}

// ── Toast ─────────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = '') {
  toastEl.textContent = msg;
  toastEl.className   = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.className = 'toast'; }, 3800);
}

// ── Markdown renderer (XSS-safe) ──────────────────────────────────────────
function renderMarkdown(raw) {
  let txt = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  txt = txt
    .replace(/^(\*{3,}|-{3,})$/gm, '<hr>')
    .replace(/^### (.+)$/gm,  '<h3>$1</h3>')
    .replace(/^## (.+)$/gm,   '<h2>$1</h2>')
    .replace(/^# (.+)$/gm,    '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,      '<em>$1</em>')
    .replace(/`([^`]+)`/g,     '<code>$1</code>')
    .replace(/^[-*•] (.+)$/gm, '<li>$1</li>');

  txt = txt.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
  txt = txt.replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>');
  return `<p>${txt}</p>`;
}

// ── User display ──────────────────────────────────────────────────────────
function updateUserDisplay() {
  if (!userTextEl || !USER_NAME) return;
  userTextEl.textContent = USER_NAME;
  userBadgeEl.classList.add('active');
}

// ── Status indicator ───────────────────────────────────────────────────────
function setStatus(state, text) {
  statusDotEl.className = 'status-dot ' + (state || '');
  statusTxtEl.textContent = text;
}

async function checkHealth() {
  try {
    const r = await fetch('/api/health');
    if (!r.ok) throw new Error('unhealthy');
    const data = await r.json();
    const engine = data.engine || 'desconocido';
    setStatus('online', `${engine} · activo`);
    memoryBadge.classList.add('active');
    document.getElementById('memoryText').textContent = 'Memoria activa';
  } catch {
    setStatus('error', 'Sin conexión');
  }
}

// ── Progress ───────────────────────────────────────────────────────────────
let _finaleShown = false;

function showFinaleActions() {
  if (_finaleShown) return;
  _finaleShown = true;

  const bar = document.createElement('div');
  bar.className = 'finale-actions';
  bar.id = 'finaleBar';
  bar.innerHTML = `
    <div class="finale-title">🎉 ¡Consolidación completa! ¿Qué deseas hacer?</div>
    <div class="finale-btns">
      <button class="finale-btn finale-sheets" id="finaleSheets">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10 9 9 9 8 9"/>
        </svg>
        Guardar en Sheets
      </button>
      <button class="finale-btn finale-email" id="finaleEmail">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
          <polyline points="22,6 12,13 2,6"/>
        </svg>
        Enviar por correo
      </button>
    </div>`;
  chatEl.appendChild(bar);
  scrollToBottom();

  bar.querySelector('#finaleSheets').addEventListener('click', submitToSheets);
  bar.querySelector('#finaleEmail').addEventListener('click', showEmailModal);
}
function advanceStep(n) {
  if (n <= 0 || n > 25) return;
  currentStep = n;

  const pct = Math.round((n / 25) * 100);
  progressFill.style.width = pct + '%';
  progressLbl.textContent  = `${n} / 25`;

  document.querySelectorAll('.step-item').forEach(el => {
    const s = parseInt(el.dataset.step, 10);
    el.classList.remove('done', 'active');
    if (s < n)  el.classList.add('done');
    if (s === n) {
      el.classList.add('active');
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  });
}

function detectStep(text) {
  const m = text.match(/[Pp]regunta\s+\*{0,2}(\d+)\*{0,2}\s+de\s+25/);
  if (m) {
    const step = parseInt(m[1], 10);
    if (step > currentStep) advanceStep(step);
  }
  // Detect completion: step 25 done, or bot summarises all fields
  const done = currentStep >= 25 ||
    /todos los campos.*complet|consolidaci[oó]n.*complet|25\s*\/\s*25 campos/i.test(text);
  if (done) showFinaleActions();
}

// ── Messages ───────────────────────────────────────────────────────────────
function appendMessage(role, content, streaming = false) {
  const msgEl    = document.createElement('div');
  msgEl.className = `message ${role}`;

  const avatarEl = document.createElement('div');
  avatarEl.className = 'avatar';
  avatarEl.textContent = role === 'bot' ? 'IA' : 'TÚ';

  const bubbleEl = document.createElement('div');
  bubbleEl.className = 'bubble';
  if (streaming) {
    bubbleEl.id = 'streaming-bubble';
  } else {
    bubbleEl.innerHTML = renderMarkdown(content);
  }

  const tsEl = document.createElement('div');
  tsEl.className   = 'timestamp';
  tsEl.textContent = getTime();

  const innerEl = document.createElement('div');
  innerEl.className = 'msg-inner';
  innerEl.appendChild(bubbleEl);
  innerEl.appendChild(tsEl);

  msgEl.appendChild(avatarEl);
  msgEl.appendChild(innerEl);
  chatEl.appendChild(msgEl);
  scrollToBottom();
  return bubbleEl;
}

function appendSystemNotice(html) {
  const el = document.createElement('div');
  el.className = 'system-notice';
  el.innerHTML = html;
  chatEl.appendChild(el);
  scrollToBottom();
}

// ── Typing indicator ───────────────────────────────────────────────────────
function showTyping() {
  const wrap = document.createElement('div');
  wrap.className = 'typing-wrap';
  wrap.id = 'typing-indicator';

  const avatarEl = document.createElement('div');
  avatarEl.className = 'avatar';
  avatarEl.textContent = 'IA';

  const typingEl = document.createElement('div');
  typingEl.className = 'typing';
  typingEl.innerHTML = '<span></span><span></span><span></span>';

  wrap.appendChild(avatarEl);
  wrap.appendChild(typingEl);
  chatEl.appendChild(wrap);
  scrollToBottom();
}

function hideTyping() {
  document.getElementById('typing-indicator')?.remove();
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

// ── Loading state ──────────────────────────────────────────────────────────
function setLoading(v) {
  isStreaming        = v;
  sendBtnEl.disabled = v;
  inputEl.disabled   = v;
}

// ── SSE stream reader ──────────────────────────────────────────────────────
async function readStream(reader, onChunk, onMeta, onDone) {
  const decoder = new TextDecoder();
  let   buffer  = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') { onDone(); return; }
      if (!data) continue;
      try {
        const parsed = JSON.parse(data);
        if (parsed.content) onChunk(parsed.content);
        if (parsed.meta)    onMeta(parsed.meta);
      } catch {
        // Ignore malformed fragments
      }
    }
  }
  onDone();
}

// ── Send message ───────────────────────────────────────────────────────────
async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || isStreaming) return;

  inputEl.value = '';
  autoResize();

  appendMessage('user', text);
  setLoading(true);
  showTyping();

  try {
    const response = await fetch('/api/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text, session_id: SESSION_ID, user_name: USER_NAME }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    hideTyping();
    const bubbleEl = appendMessage('bot', '', true);
    let   fullText = '';

    await readStream(
      response.body.getReader(),
      chunk => {
        fullText += chunk;
        bubbleEl.innerHTML = renderMarkdown(fullText);
        scrollToBottom();
      },
      meta => {
        if (meta === 'history_restored') {
          appendSystemNotice(
            '🔄 <strong>Sesión restaurada</strong> — se recuperó el historial de conversación desde Supabase.'
          );
        }
      },
      () => {
        bubbleEl.removeAttribute('id');
        detectStep(fullText);
      },
    );
  } catch (err) {
    hideTyping();
    appendMessage('bot', `**Error de conexión:** ${err.message}. Por favor intenta de nuevo.`);
  } finally {
    setLoading(false);
    inputEl.focus();
  }
}

// ── Excel download ─────────────────────────────────────────────────────────
async function downloadExcel() {
  downloadBtn.disabled = true;
  downloadBtn.textContent = 'Generando…';
  try {
    const r = await fetch('/api/excel/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: SESSION_ID }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);

    const blob = await r.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'consolidacion_metodologica_epm.xlsx';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Excel descargado correctamente', 'success');
  } catch (err) {
    showToast('Error al generar Excel: ' + err.message, 'error');
  } finally {
    downloadBtn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      Descargar Excel`;
    downloadBtn.disabled = false;
  }
}

// ── Google Sheets submit ───────────────────────────────────────────────────
async function submitToSheets() {
  sheetsBtn.disabled = true;
  sheetsBtn.textContent = 'Guardando…';
  try {
    const r = await fetch('/api/sheets/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: SESSION_ID }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);

    showToast('✓ Guardado en Google Sheets', 'success');
    _lastSheetsUrl = data.sheets_url || '';
    _lastSheetsRow = data.sheets_row || 0;
    appendSystemNotice(
      `✅ <strong>Datos guardados en Google Sheets</strong> — fila ${data.sheets_row}. ` +
      `<a href="${data.sheets_url}" target="_blank" rel="noopener noreferrer">Abrir hoja →</a>`
    );
  } catch (err) {
    showToast('Error al guardar en Sheets: ' + err.message, 'error');
  } finally {
    sheetsBtn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
      Guardar en Sheets`;
    sheetsBtn.disabled = false;
  }
}

// ── New session ────────────────────────────────────────────────────────────
async function newSession() {
  if (!confirm('¿Iniciar una nueva actividad? La sesión anterior quedará guardada en Supabase.')) return;

  try {
    const r = await fetch('/api/session/new', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ user_name: USER_NAME }),
    });
    if (r.ok) {
      const data = await r.json();
      SESSION_ID = data.session_id;
    } else {
      SESSION_ID = generateUUID();
    }
  } catch {
    SESSION_ID = generateUUID();
  }

  localStorage.setItem(SESSION_KEY, SESSION_ID);
  chatEl.innerHTML = '';
  currentStep  = 0;
  _finaleShown = false;
  progressFill.style.width = '0%';
  progressLbl.textContent  = '0 / 25';
  document.querySelectorAll('.step-item').forEach(el => el.classList.remove('done', 'active'));
  showToast('Nueva actividad iniciada', 'success');
  setTimeout(() => bootWelcome(), 200);
}

// ── Logout / switch user ──────────────────────────────────────────────────
function logoutUser() {
  if (!confirm(`¿Cerrar sesión de "${USER_NAME || 'este usuario'}"?\nPodrás iniciar sesión con otro nombre.`)) return;
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(USER_NAME_KEY);
  location.reload();
}

// ── Email modal ────────────────────────────────────────────────────────────
// State carried from the last successful sheets submit:
let _lastSheetsUrl = '';
let _lastSheetsRow = 0;

function showEmailModal() {
  const backdrop = document.createElement('div');
  backdrop.className = 'email-modal-backdrop';
  const prefill = USER_NAME ? '' : '';
  backdrop.innerHTML = `
    <div class="email-modal">
      <div class="epm-modal-logo">epm</div>
      <h2>Enviar resumen por correo</h2>
      <p>Se enviará un correo HTML con todos los campos consolidados de esta actividad.</p>
      <input type="email" id="emailInput"
             placeholder="correo@ejemplo.com"
             value="${prefill}" autocomplete="email" maxlength="120" />
      <div class="modal-actions">
        <button class="modal-cancel" id="emailCancel">Cancelar</button>
        <button class="modal-send"   id="emailSend">Enviar ✉</button>
      </div>
    </div>`;
  document.body.appendChild(backdrop);

  const inputEl2 = backdrop.querySelector('#emailInput');
  const sendEl   = backdrop.querySelector('#emailSend');
  const cancelEl = backdrop.querySelector('#emailCancel');
  inputEl2.focus();

  cancelEl.addEventListener('click', () => backdrop.remove());
  backdrop.addEventListener('click', e => { if (e.target === backdrop) backdrop.remove(); });

  async function doSend() {
    const email = inputEl2.value.trim();
    if (!email || !email.includes('@')) {
      inputEl2.focus();
      inputEl2.style.borderColor = '#ef4444';
      return;
    }
    sendEl.disabled = true;
    sendEl.textContent = 'Enviando…';
    try {
      const r = await fetch('/api/email/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: SESSION_ID,
          to_email:   email,
          facilitador: USER_NAME || '',
          sheets_url:  _lastSheetsUrl,
          sheets_row:  _lastSheetsRow,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      backdrop.remove();
      showToast(`✓ Correo enviado a ${email}`, 'success');
    } catch (err) {
      showToast('Error al enviar: ' + err.message, 'error');
      sendEl.disabled = false;
      sendEl.textContent = 'Enviar ✉';
    }
  }

  sendEl.addEventListener('click', doSend);
  inputEl2.addEventListener('keydown', e => { if (e.key === 'Enter') doSend(); });
}

// ── Textarea auto-resize ───────────────────────────────────────────────────
function autoResize() {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 128) + 'px';
}

// ── Events ────────────────────────────────────────────────────────────────
inputEl.addEventListener('input', autoResize);

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtnEl.addEventListener('click',  sendMessage);
downloadBtn.addEventListener('click', downloadExcel);
sheetsBtn.addEventListener('click',   submitToSheets);
newBtn.addEventListener('click',      newSession);
resetBtn?.addEventListener('click',   newSession);
logoutBtn?.addEventListener('click',  logoutUser);
emailBtn.addEventListener('click',    showEmailModal);

// ── Name modal ─────────────────────────────────────────────────────────────
function showNameModal() {
  return new Promise(resolve => {
    const backdrop = document.createElement('div');
    backdrop.className = 'name-modal-backdrop';
    backdrop.innerHTML = `
      <div class="name-modal">
        <div class="epm-modal-logo">epm</div>
        <h2>¡Bienvenido/a!</h2>
        <p>Antes de comenzar, ¿cuál es tu nombre?<br>
           <small style="color:var(--text-muted)">Se usará para personalizar tu sesión y memoria en Supabase.</small>
        </p>
        <input id="nameInput" type="text" placeholder="Tu nombre completo" autocomplete="name" maxlength="80" />
        <button id="nameSubmit">Comenzar</button>
      </div>`;
    document.body.appendChild(backdrop);

    const input  = backdrop.querySelector('#nameInput');
    const submit = backdrop.querySelector('#nameSubmit');
    input.focus();

    async function doSubmitName() {
      const val = input.value.trim();
      if (!val) { input.focus(); return; }
      submit.disabled = true;
      submit.textContent = 'Iniciando…';
      try {
        const r = await fetch('/api/session/new', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ user_name: val }),
        });
        if (r.ok) {
          const data = await r.json();
          SESSION_ID = data.session_id;
          localStorage.setItem(SESSION_KEY, SESSION_ID);
        }
      } catch { /* keep existing SESSION_ID */ }
      USER_NAME = val;
      localStorage.setItem(USER_NAME_KEY, val);
      updateUserDisplay();
      backdrop.remove();
      resolve(val);
    }
    submit.addEventListener('click', doSubmitName);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doSubmitName(); });
  });
}

// ── Boot ───────────────────────────────────────────────────────────────────
function bootWelcome() {
  const greeting = USER_NAME ? `**${USER_NAME}**` : '**facilitador/a**';
  appendMessage('bot', [
    `## ¡Hola, ${greeting}! Bienvenido/a al Asistente de Consolidación Metodológica`,
    '',
    'Soy el asistente IA de **Fundación Grupo EPM**. Te guiaré paso a paso para diligenciar el diseño metodológico de tu actividad.',
    '',
    '**Flujo de trabajo:**',
    '- **Bloque 1** — Identificación y planeación metodológica (16 campos)',
    '- **Bloque 2** — Informe de ejecución (4 campos)',
    '- **Bloque 3** — Evaluación y análisis IA (5 campos)',
    '',
    'Tu historial queda guardado en **Supabase** y tus respuestas se escriben en **Google Sheets** al finalizar.',
    '',
    '---',
    '¿Empezamos? **¿Cuál es el ID único de la actividad** que vas a registrar?',
  ].join('\n'));
}

window.addEventListener('DOMContentLoaded', async () => {
  checkHealth();
  if (!USER_NAME) {
    await showNameModal();
  } else {
    updateUserDisplay();
  }
  setTimeout(bootWelcome, 200);
});
