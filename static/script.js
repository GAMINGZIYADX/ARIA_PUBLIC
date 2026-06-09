/* ============================================================
   ARIA — script.js
   Core UI wiring: chat, STT, TTS, bash terminal, settings,
   camera modal, connection health, proactive messages.
   ============================================================ */
'use strict';

// ── CSRF token cache ──────────────────────────────────────────────────────────
let _csrfToken = null;

async function _fetchCsrfToken() {
  if (_csrfToken) return _csrfToken;
  const r = await fetch('/api/csrf-token', { credentials: 'same-origin' });
  const d = await r.json();
  _csrfToken = d.csrf_token || null;
  return _csrfToken;
}

/**
 * apiFetch — CSRF-aware fetch wrapper.
 * Adds X-CSRF-Token to all non-GET requests automatically.
 * Exposed as window.apiFetch so inline JS in index.html can call it.
 */
window.apiFetch = async function apiFetch(url, opts) {
  opts = opts || {};
  const method = (opts.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    const tok = await _fetchCsrfToken();
    opts.headers = Object.assign({ 'X-CSRF-Token': tok }, opts.headers || {});
  }
  opts.credentials = 'same-origin';
  return fetch(url, opts);
};

// ── Session ID ────────────────────────────────────────────────────────────────
function _sessionId() {
  let id = sessionStorage.getItem('aria_sid');
  if (!id) {
    id = 'ss' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
    sessionStorage.setItem('aria_sid', id);
  }
  return id;
}

// ── HTML escape ───────────────────────────────────────────────────────────────
function _esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Markdown renderer (no external deps) ─────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return '';

  // Preserve code blocks before escaping
  const blocks = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = blocks.length;
    blocks.push(`<pre><code>${_esc(code.replace(/^\n/, ''))}</code></pre>`);
    return '\x00BLOCK' + idx + '\x00';
  });

  let html = _esc(text);

  // Inline code
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  // Italic (single asterisk, no greedy)
  html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  // Headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm,  '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm,   '<h1>$1</h1>');
  // List items (collect consecutive li into ul)
  html = html.replace(/((?:^[*\-] .+\n?)+)/gm, match => {
    const items = match.split('\n').filter(Boolean).map(line =>
      '<li>' + line.replace(/^[*\-] /, '') + '</li>'
    ).join('');
    return '<ul>' + items + '</ul>';
  });
  // Paragraphs — double newline
  html = '<p>' + html.replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>') + '</p>';
  // Unwrap block-level elements that ended up inside <p>
  html = html
    .replace(/<p>\s*(<(?:pre|ul|ol|h[1-6])[^>]*>)/g, '$1')
    .replace(/(<\/(?:pre|ul|ol|h[1-6])>)\s*<\/p>/g, '$1')
    .replace(/<p>\s*<\/p>/g, '');

  // Restore code blocks
  html = html.replace(/\x00BLOCK(\d+)\x00/g, (_, i) => blocks[+i]);

  return html;
}

// ── Tab switching ─────────────────────────────────────────────────────────────
window.switchTab = function switchTab(tabName) {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-content').forEach(pane => {
    pane.classList.toggle('active', pane.id === tabName + '-tab');
  });
  if (tabName === 'settings') {
    _loadModels();
    _loadMemory();
    _loadPersona();
    _loadSelfModel();
    _loadWorldIntel();
  }
};

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ── Talking state ─────────────────────────────────────────────────────────────
// Minimal implementation — overridden by index.html after DOMContentLoaded
window.setAriaTalking = function setAriaTalking(on) {
  const hero = document.querySelector('.chat-hero');
  if (hero) hero.classList.toggle('aria-talking', on);
};

// ── Connection status ─────────────────────────────────────────────────────────
function _setStatus(connected, label) {
  const dot  = document.getElementById('_status-dot-compat');
  const text = document.getElementById('status-text');
  if (dot)  dot.classList.toggle('connected', connected);
  if (text) text.textContent = label;
}

// ── Token tracking ────────────────────────────────────────────────────────────
let _sessionTokens = 0;
let _alltimeTokens = parseInt(localStorage.getItem('aria_alltime_tokens') || '0', 10);

function _updateTokenDisplay(usage) {
  if (!usage || typeof usage !== 'object') return;
  const prompt     = usage.prompt_tokens     || usage.input_tokens    || 0;
  const completion = usage.completion_tokens || usage.output_tokens   || 0;
  const total      = prompt + completion;
  if (!total) return;

  _sessionTokens += total;
  _alltimeTokens += total;
  localStorage.setItem('aria_alltime_tokens', String(_alltimeTokens));

  const $ = id => document.getElementById(id);
  if ($('session-tokens'))         $('session-tokens').textContent         = _sessionTokens.toLocaleString();
  if ($('alltime-tokens'))         $('alltime-tokens').textContent         = _alltimeTokens.toLocaleString();
  if ($('last-prompt-tokens'))     $('last-prompt-tokens').textContent     = prompt      || '—';
  if ($('last-completion-tokens')) $('last-completion-tokens').textContent = completion  || '—';

  const ctxMax = usage.context_window || 32768;
  const pct    = Math.min(100, Math.round((_sessionTokens / ctxMax) * 100));
  if ($('context-pct'))  $('context-pct').textContent   = pct + '%';
  if ($('context-bar'))  $('context-bar').style.width   = pct + '%';
  if ($('context-sub'))  $('context-sub').textContent   =
    `${_sessionTokens.toLocaleString()} / ${ctxMax.toLocaleString()} tokens this session`;
}

// ── Messages ──────────────────────────────────────────────────────────────────
const _msgList  = document.getElementById('messages');
let   _typingEl = null;

/**
 * addMessage(role, text, opts)
 *   role: 'user' | 'aria'
 *   opts: { thinking, bash_results }
 */
function addMessage(role, text, opts) {
  opts = opts || {};
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row--' + role;

  // Thinking block (monologue)
  if (role === 'aria' && opts.thinking) {
    const tb  = document.createElement('div');
    tb.className = 'thinking-block';
    const tog = document.createElement('button');
    tog.className   = 'thinking-toggle';
    tog.textContent = '▸ INTERNAL MONOLOGUE';
    const body = document.createElement('div');
    body.className     = 'thinking-body';
    body.textContent   = opts.thinking;
    body.style.display = 'none';
    tog.onclick = () => {
      const open      = body.style.display !== 'none';
      body.style.display = open ? 'none' : 'block';
      tog.textContent    = (open ? '▸ ' : '▾ ') + 'INTERNAL MONOLOGUE';
    };
    tb.appendChild(tog);
    tb.appendChild(body);
    row.appendChild(tb);
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble--' + role;

  const inner = document.createElement('div');
  inner.className = 'bubble-text';
  inner.innerHTML = (role === 'aria') ? renderMarkdown(text) : _esc(text);
  bubble.appendChild(inner);

  // Bash results
  const results = opts.bash_results || {};
  for (const [key, res] of Object.entries(results)) {
    const ok  = res.success !== false;
    const br  = document.createElement('div');
    br.className = 'bash-result';
    br.innerHTML =
      `<div class="bash-result-header${ok ? '' : ' err'}">` +
        `<span class="dot"></span>${_esc(key.toUpperCase())} · exit ${res.status_code ?? 0}` +
      `</div>` +
      `<div class="bash-result-body">${_esc(res.output || res.error || '(no output)')}</div>`;
    bubble.appendChild(br);
  }

  row.appendChild(bubble);
  if (_msgList) {
    _msgList.appendChild(row);
    _msgList.scrollTop = _msgList.scrollHeight;
  }
  return row;
}

function showTyping() {
  if (_typingEl) return;
  _typingEl = document.createElement('div');
  _typingEl.className = 'bubble-row bubble-row--aria';
  _typingEl.innerHTML =
    `<div class="bubble bubble--aria">` +
    `<div class="tts-wave tts-wave--active">` +
    `<span></span><span style="animation-delay:.12s"></span>` +
    `<span style="animation-delay:.24s"></span></div></div>`;
  if (_msgList) {
    _msgList.appendChild(_typingEl);
    _msgList.scrollTop = _msgList.scrollHeight;
  }
}

function hideTyping() {
  if (_typingEl) { _typingEl.remove(); _typingEl = null; }
}

// ── Tool confirmation bubble ──────────────────────────────────────────────────
function _showConfirmBubble(prompt, pendingTool, sid) {
  hideTyping();
  const row = document.createElement('div');
  row.className = 'bubble-row bubble-row--aria';
  const bub = document.createElement('div');
  bub.className = 'bubble bubble--aria';
  const conf = document.createElement('div');
  conf.className = 'confirm-bubble';

  const p = document.createElement('div');
  p.className   = 'confirm-prompt';
  p.textContent = prompt;

  const actions = document.createElement('div');
  actions.className = 'confirm-actions';

  const yes = document.createElement('button');
  yes.className   = 'confirm-yes';
  yes.textContent = 'YES, DO IT';

  const no = document.createElement('button');
  no.className   = 'confirm-no';
  no.textContent = 'CANCEL';

  yes.onclick = async () => {
    conf.remove();
    showTyping();
    try {
      const r = await apiFetch('/api/tools/confirm', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ pending_tool: pendingTool, session_id: sid })
      });
      const d = await r.json();
      hideTyping();
      addMessage('aria', d.response || 'Done.', { bash_results: d.bash_results });
    } catch (_) {
      hideTyping();
      addMessage('aria', 'Error confirming tool action.');
    }
  };

  no.onclick = () => {
    row.remove();
    addMessage('aria', 'Action cancelled.');
  };

  actions.appendChild(yes);
  actions.appendChild(no);
  conf.appendChild(p);
  conf.appendChild(actions);
  bub.appendChild(conf);
  row.appendChild(bub);
  if (_msgList) {
    _msgList.appendChild(row);
    _msgList.scrollTop = _msgList.scrollHeight;
  }
}

// ── Send chat message ─────────────────────────────────────────────────────────
const _input   = document.getElementById('message-input');
const _sendBtn = document.getElementById('send-btn');
let _capturedImage = null;

async function sendMessage(text, image) {
  text  = (text  || '').trim();
  image = image  || _capturedImage || null;
  if (!text) return;

  // Consume the pending camera image
  _capturedImage = null;
  document.getElementById('cam-btn')?.classList.remove('active');

  addMessage('user', text);
  _histPush(text);
  if (_input) _input.value = '';

  showTyping();
  _setBusy(true);

  const ttsOn  = document.getElementById('tts-toggle')?.checked      ?? false;
  const bashOn = document.getElementById('bash-toggle')?.checked     ?? false;
  const monOn  = document.getElementById('monologue-toggle')?.checked ?? false;

  try {
    const r = await apiFetch('/api/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message:      text,
        session_id:   _sessionId(),
        execute_bash: bashOn,
        image:        image
      })
    });

    const d = await r.json();
    hideTyping();
    _setBusy(false);

    if (!r.ok || d.error) {
      addMessage('aria', d.error || 'Something went wrong. Please try again.');
      return;
    }

    // Destructive tool needs explicit confirmation
    if (d.needs_confirmation) {
      _showConfirmBubble(d.confirm_prompt, d.pending_tool, _sessionId());
      return;
    }

    const thinking = monOn ? (d.thinking || null) : null;
    addMessage('aria', d.response || '(no response)', {
      thinking,
      bash_results: d.bash_results || {}
    });

    // Proactive hint (delayed so it doesn't overlay the primary response)
    if (d.proactive?.message) {
      setTimeout(() => addMessage('aria', '💡 ' + d.proactive.message), 700);
    }

    if (d.usage) _updateTokenDisplay(d.usage);
    if (ttsOn && d.response) _playTts(d.response);

  } catch (_err) {
    hideTyping();
    _setBusy(false);
    addMessage('aria', 'Connection error — is the ARIA server running?');
    _setStatus(false, 'Disconnected');
  }
}

function _setBusy(on) {
  if (_sendBtn) _sendBtn.disabled = on;
  if (_input)   _input.disabled   = on;
}

// ── Input event wiring ────────────────────────────────────────────────────────
if (_input) {
  _input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(_input.value);
    } else if (e.key === 'ArrowUp')   { e.preventDefault(); _histPrev(); }
    else if (e.key === 'ArrowDown')  { e.preventDefault(); _histNext(); }
  });
}
if (_sendBtn) _sendBtn.addEventListener('click', () => sendMessage(_input?.value));

// ── Chat input history ────────────────────────────────────────────────────────
const _hist    = [];
let   _histIdx = -1;
let   _histDraft = '';

function _histPush(msg) {
  if (_hist[_hist.length - 1] !== msg) _hist.push(msg);
  if (_hist.length > 60) _hist.shift();
  _histIdx = -1;
}

function _histPrev() {
  if (!_hist.length) return;
  if (_histIdx === -1) _histDraft = _input?.value || '';
  _histIdx = Math.min(_histIdx + 1, _hist.length - 1);
  if (_input) _input.value = _hist[_hist.length - 1 - _histIdx];
}

function _histNext() {
  if (_histIdx <= 0) { _histIdx = -1; if (_input) _input.value = _histDraft; return; }
  _histIdx--;
  if (_input) _input.value = _hist[_hist.length - 1 - _histIdx];
}

// ── TTS playback ──────────────────────────────────────────────────────────────
let _ttsAudio = null;

async function _playTts(text) {
  // Cap length to keep latency reasonable
  text = text.slice(0, 500);
  try {
    setAriaTalking(true);
    const r = await apiFetch('/api/tts', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ text })
    });
    if (!r.ok) { setAriaTalking(false); return; }
    const blob = await r.blob();
    const url  = URL.createObjectURL(blob);
    if (_ttsAudio) {
      _ttsAudio.pause();
      try { URL.revokeObjectURL(_ttsAudio.src); } catch (_) {}
    }
    _ttsAudio = new Audio(url);
    _ttsAudio.onended = () => { setAriaTalking(false); URL.revokeObjectURL(url); };
    _ttsAudio.onerror = () => { setAriaTalking(false); };
    await _ttsAudio.play();
  } catch (_) {
    setAriaTalking(false);
  }
}

// ── STT (MediaRecorder → /api/stt) ───────────────────────────────────────────
let _recorder  = null;
let _sttChunks = [];
let _listening = false;
const _micBtn  = document.getElementById('mic-btn');

async function _startListening() {
  if (_listening) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _sttChunks = [];
    _recorder  = new MediaRecorder(stream);
    _recorder.ondataavailable = e => { if (e.data.size > 0) _sttChunks.push(e.data); };
    _recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_sttChunks, { type: 'audio/webm' });
      _sttChunks = [];
      await _transcribeBlob(blob);
    };
    _recorder.start();
    _listening = true;
    if (_micBtn) _micBtn.classList.add('listening');
  } catch (e) {
    console.warn('[ARIA STT] Microphone access denied:', e.message);
  }
}

function _stopListening() {
  if (!_listening || !_recorder) return;
  _listening = false;
  if (_micBtn) _micBtn.classList.remove('listening');
  try { _recorder.stop(); } catch (_) {}
  _recorder = null;
}

async function _transcribeBlob(blob) {
  try {
    const form = new FormData();
    form.append('audio', blob, 'audio.webm');
    const tok = await _fetchCsrfToken();
    const r = await fetch('/api/stt', {
      method:      'POST',
      headers:     { 'X-CSRF-Token': tok },
      credentials: 'same-origin',
      body:        form
    });
    const d = await r.json();
    if (d.transcript) {
      if (_input) _input.value = d.transcript;
      sendMessage(d.transcript);
    }
  } catch (e) {
    console.warn('[ARIA STT] Transcription error:', e.message);
  }
}

// Mic button — click to toggle
if (_micBtn) {
  _micBtn.addEventListener('click', () => {
    if (_listening) _stopListening();
    else _startListening();
  });
}

// Space hold-to-talk — only when text input not focused
document.addEventListener('keydown', e => {
  if (e.code !== 'Space' || e.repeat) return;
  const active = document.activeElement;
  const isInput = active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA');
  if (!isInput) { e.preventDefault(); _startListening(); }
});
document.addEventListener('keyup', e => {
  if (e.code === 'Space' && _listening) {
    e.preventDefault();
    _stopListening();
  }
});

// ── Clear session ─────────────────────────────────────────────────────────────
document.getElementById('clear-btn')?.addEventListener('click', async () => {
  try {
    await apiFetch('/api/clear', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ session_id: _sessionId() })
    });
  } catch (_) {}
  if (_msgList) _msgList.innerHTML = '';
  sessionStorage.removeItem('aria_sid');
  _sessionTokens = 0;
  const $ = id => document.getElementById(id);
  if ($('session-tokens')) $('session-tokens').textContent = '0';
  if ($('context-pct'))    $('context-pct').textContent    = '—';
  if ($('context-bar'))    $('context-bar').style.width    = '0%';
  if ($('context-sub'))    $('context-sub').textContent    = 'waiting for first message…';
});

// ── Health polling ────────────────────────────────────────────────────────────
async function _healthCheck() {
  try {
    const r = await fetch('/api/health', { credentials: 'same-origin' });
    if (!r.ok) throw new Error('non-ok');
    const d = await r.json();
    const ok = (d.status === 'ok' || d.status === 'degraded');
    _setStatus(ok, ok ? 'Connected' : 'Degraded');
  } catch (_) {
    _setStatus(false, 'Disconnected');
  }
}

// ── Proactive message polling ─────────────────────────────────────────────────
async function _proactiveCheck() {
  try {
    const r = await fetch('/api/proactive/check', { credentials: 'same-origin' });
    const d = await r.json();
    if (d.message) addMessage('aria', '💡 ' + d.message);
  } catch (_) {}
}

// ── Camera modal ──────────────────────────────────────────────────────────────
const _camModal  = document.getElementById('cam-modal');
const _camVideo  = document.getElementById('cam-video');
const _camCanvas = document.getElementById('cam-canvas');
let   _camStream = null;

document.getElementById('cam-btn')?.addEventListener('click', async () => {
  if (_camStream) { _closeCam(); return; }
  try {
    _camStream = await navigator.mediaDevices.getUserMedia({ video: true });
    if (_camVideo) {
      _camVideo.srcObject = _camStream;
      _camVideo.onloadedmetadata = () => {
        const res = document.getElementById('cam-res');
        if (res) res.textContent = `${_camVideo.videoWidth}×${_camVideo.videoHeight}`;
      };
    }
    if (_camModal) _camModal.style.display = 'flex';
    document.getElementById('cam-btn')?.classList.add('active');
  } catch (e) {
    console.warn('[ARIA CAM] Camera denied:', e.message);
  }
});

document.getElementById('cam-close-btn')?.addEventListener('click', _closeCam);

document.getElementById('cam-snap-btn')?.addEventListener('click', () => {
  if (!_camStream || !_camVideo || !_camCanvas) return;
  _camCanvas.width  = _camVideo.videoWidth;
  _camCanvas.height = _camVideo.videoHeight;
  _camCanvas.getContext('2d').drawImage(_camVideo, 0, 0);
  const dataUrl = _camCanvas.toDataURL('image/jpeg', 0.85);
  const b64     = dataUrl.split(',')[1];
  const prompt  = document.getElementById('cam-prompt')?.value || 'What do you see?';
  _capturedImage = b64;
  _closeCam();
  sendMessage(prompt, b64);
});

function _closeCam() {
  if (_camStream) {
    _camStream.getTracks().forEach(t => t.stop());
    _camStream = null;
  }
  if (_camModal) _camModal.style.display = 'none';
  document.getElementById('cam-btn')?.classList.remove('active');
}

// Close on backdrop click
if (_camModal) {
  _camModal.addEventListener('click', e => {
    if (e.target === _camModal) _closeCam();
  });
}

// ── Bash terminal ─────────────────────────────────────────────────────────────
const _bashInput   = document.getElementById('bash-input');
const _bashExecBtn = document.getElementById('bash-execute-btn');
const _termOut     = document.getElementById('terminal-output');
const _bashHist    = [];
let   _bashHistIdx = -1;
let   _bashDraft   = '';

async function _execBash(cmd) {
  cmd = (cmd || '').trim();
  if (!cmd) return;

  _bashHist.push(cmd);
  if (_bashHist.length > 60) _bashHist.shift();
  _bashHistIdx = -1;
  if (_bashInput) _bashInput.value = '';

  // Show command entry immediately
  const entry = document.createElement('div');
  entry.className = 'term-entry';
  const cmdEl = document.createElement('div');
  cmdEl.className   = 'term-cmd';
  cmdEl.textContent = cmd;
  entry.appendChild(cmdEl);
  _termOut?.appendChild(entry);
  if (_termOut) _termOut.scrollTop = _termOut.scrollHeight;

  try {
    const r = await apiFetch('/api/bash', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ command: cmd })
    });
    const d = await r.json();
    const outEl = document.createElement('div');
    outEl.className   = d.success ? 'term-out' : 'term-err';
    outEl.textContent = d.output || d.error || '(no output)';
    entry.appendChild(outEl);
  } catch (_) {
    const errEl = document.createElement('div');
    errEl.className   = 'term-err';
    errEl.textContent = 'Connection error';
    entry.appendChild(errEl);
  }
  if (_termOut) _termOut.scrollTop = _termOut.scrollHeight;
}

if (_bashInput) {
  _bashInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      _execBash(_bashInput.value);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (_bashHistIdx === -1) _bashDraft = _bashInput.value;
      _bashHistIdx = Math.min(_bashHistIdx + 1, _bashHist.length - 1);
      if (_bashHist.length) _bashInput.value = _bashHist[_bashHist.length - 1 - _bashHistIdx];
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (_bashHistIdx <= 0) { _bashHistIdx = -1; _bashInput.value = _bashDraft; return; }
      _bashHistIdx--;
      _bashInput.value = _bashHist[_bashHist.length - 1 - _bashHistIdx];
    }
  });
}
if (_bashExecBtn) _bashExecBtn.addEventListener('click', () => _execBash(_bashInput?.value));

// ── Settings: models ──────────────────────────────────────────────────────────
async function _loadModels() {
  try {
    const r = await fetch('/api/models', { credentials: 'same-origin' });
    const d = await r.json();
    const sel = document.getElementById('model-select');
    if (sel && Array.isArray(d.available_models) && d.available_models.length) {
      sel.innerHTML = '';
      d.available_models.forEach(m => {
        const opt = document.createElement('option');
        opt.value       = m;
        opt.textContent = m.toUpperCase();
        opt.selected    = (m === d.current_model);
        sel.appendChild(opt);
      });
    }
  } catch (_) {}
}

document.getElementById('model-select')?.addEventListener('change', async function () {
  try {
    await apiFetch('/api/models/set', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ model: this.value })
    });
    const stat = document.getElementById('model-stat');
    if (stat) stat.textContent = this.value.toUpperCase() + ' ● ACTIVE';
  } catch (_) {}
});

// ── Settings: memory ──────────────────────────────────────────────────────────
async function _loadMemory() {
  try {
    const r = await fetch('/api/memory', { credentials: 'same-origin' });
    const d = await r.json();
    const grid  = document.getElementById('memory-grid');
    if (!grid) return;
    const facts = d.facts || d.memory || [];
    if (!facts.length) {
      grid.innerHTML = '<span class="memory-empty">No memory recorded yet — start chatting.</span>';
      return;
    }
    grid.innerHTML = '';
    facts.forEach(f => {
      const el  = document.createElement('div');
      el.className = 'memory-fact';
      const key = typeof f === 'object' ? (f.key   || f.type    || '—') : '—';
      const val = typeof f === 'object' ? (f.value || f.content || JSON.stringify(f)) : String(f);
      el.innerHTML =
        `<span class="memory-fact-key">${_esc(key)}</span>` +
        `<span class="memory-fact-val">${_esc(val)}</span>`;
      grid.appendChild(el);
    });
  } catch (_) {}
}

document.getElementById('clear-memory-btn')?.addEventListener('click', async () => {
  try { await apiFetch('/api/memory', { method: 'DELETE' }); } catch (_) {}
  _loadMemory();
});

// ── Settings: persona ─────────────────────────────────────────────────────────
async function _loadPersona() {
  try {
    const r = await fetch('/api/persona', { credentials: 'same-origin' });
    const d = await r.json();
    const grid  = document.getElementById('persona-grid');
    if (!grid) return;
    const facts = d.observations || d.patterns || d.facts || [];
    if (!facts.length) {
      grid.innerHTML = '<span class="memory-empty">No patterns observed yet — start chatting.</span>';
      return;
    }
    grid.innerHTML = '';
    facts.slice(0, 30).forEach(f => {
      const el  = document.createElement('div');
      el.className = 'memory-fact';
      const key = typeof f === 'object' ? (f.type  || f.key    || '—') : '—';
      const val = typeof f === 'object' ? (f.value || f.content|| JSON.stringify(f)) : String(f);
      el.innerHTML =
        `<span class="memory-fact-key">${_esc(key)}</span>` +
        `<span class="memory-fact-val">${_esc(val)}</span>`;
      grid.appendChild(el);
    });
  } catch (_) {}
}

document.getElementById('reset-persona-btn')?.addEventListener('click', async () => {
  try { await apiFetch('/api/persona', { method: 'DELETE' }); } catch (_) {}
  _loadPersona();
});

// ── Settings: self-model ──────────────────────────────────────────────────────
async function _loadSelfModel() {
  try {
    const r = await fetch('/api/self-model', { credentials: 'same-origin' });
    const d = await r.json();
    const panel = document.getElementById('self-model-panel');
    if (!panel) return;
    const sm = d.self_model || d;
    const keys = Object.keys(sm).filter(k => k !== 'error');
    if (!keys.length) {
      panel.innerHTML = '<span class="memory-empty">No self-model yet — start chatting.</span>';
      return;
    }
    panel.innerHTML = '';
    for (const key of keys) {
      const val = sm[key];
      if (!val || (Array.isArray(val) && !val.length)) continue;
      const sec = document.createElement('div');
      sec.className = 'sm-section';
      const lbl = document.createElement('div');
      lbl.className   = 'sm-label';
      lbl.textContent = key.toUpperCase().replace(/_/g, ' ');
      sec.appendChild(lbl);
      if (Array.isArray(val)) {
        const chips = document.createElement('div');
        chips.className = 'sm-chips';
        val.forEach(item => {
          const chip = document.createElement('span');
          chip.className   = 'sm-chip';
          chip.textContent = typeof item === 'string' ? item : JSON.stringify(item);
          chips.appendChild(chip);
        });
        sec.appendChild(chips);
      } else {
        const v = document.createElement('div');
        v.className   = 'sm-value';
        v.textContent = typeof val === 'string' ? val : JSON.stringify(val);
        sec.appendChild(v);
      }
      panel.appendChild(sec);
    }
  } catch (_) {}
}

document.getElementById('reset-self-model-btn')?.addEventListener('click', async () => {
  try { await apiFetch('/api/self-model', { method: 'DELETE' }); } catch (_) {}
  _loadSelfModel();
});

// ── Settings: token counter reset ────────────────────────────────────────────
document.getElementById('reset-tokens-btn')?.addEventListener('click', () => {
  _sessionTokens = 0;
  _alltimeTokens = 0;
  localStorage.removeItem('aria_alltime_tokens');
  const $ = id => document.getElementById(id);
  if ($('session-tokens'))         $('session-tokens').textContent         = '0';
  if ($('alltime-tokens'))         $('alltime-tokens').textContent         = '0';
  if ($('last-prompt-tokens'))     $('last-prompt-tokens').textContent     = '—';
  if ($('last-completion-tokens')) $('last-completion-tokens').textContent = '—';
  if ($('context-pct'))            $('context-pct').textContent            = '—';
  if ($('context-bar'))            $('context-bar').style.width            = '0%';
  if ($('context-sub'))            $('context-sub').textContent            = 'waiting for first message…';
});

// ── Settings: world intel ─────────────────────────────────────────────────────
let _wiEnabled = true;

async function _loadWorldIntel() {
  try {
    const r = await fetch('/api/world-intel', { credentials: 'same-origin' });
    const d = await r.json();
    _wiEnabled = d.enabled !== false;
    _renderWorldIntel(d);
  } catch (_) {}
}

function _renderWorldIntel(d) {
  const btn      = document.getElementById('wi-toggle-btn');
  const meta     = document.getElementById('wi-meta');
  const topics   = document.getElementById('wi-topics');
  const hlines   = document.getElementById('wi-headlines');

  if (btn) {
    btn.textContent = _wiEnabled ? 'ENABLED' : 'DISABLED';
    btn.classList.toggle('disabled', !_wiEnabled);
  }
  if (meta) {
    meta.textContent = d.last_check
      ? 'Last checked: ' + new Date(d.last_check).toLocaleTimeString()
      : 'Not checked yet';
  }
  if (topics) {
    topics.innerHTML = '';
    (d.topics || []).forEach(t => {
      const chip = document.createElement('span');
      chip.className   = 'wi-topic-chip';
      chip.textContent = t;
      topics.appendChild(chip);
    });
  }
  if (hlines) {
    const items = d.headlines || d.alerts || [];
    if (!items.length) {
      hlines.innerHTML = '<span class="memory-empty">No headlines yet — polling every 15 min.</span>';
    } else {
      hlines.innerHTML = '';
      items.slice(0, 12).forEach(h => {
        const el   = document.createElement('div');
        el.className = 'wi-headline';
        const src  = typeof h === 'object' ? (h.source || '') : '';
        const txt  = typeof h === 'object' ? (h.title  || h.text || JSON.stringify(h)) : String(h);
        el.innerHTML = src
          ? `<span class="wi-headline-src">${_esc(src)}</span><span>${_esc(txt)}</span>`
          : `<span>${_esc(txt)}</span>`;
        hlines.appendChild(el);
      });
    }
  }
}

document.getElementById('wi-toggle-btn')?.addEventListener('click', async () => {
  _wiEnabled = !_wiEnabled;
  try {
    await apiFetch('/api/world-intel/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ enabled: _wiEnabled })
    });
  } catch (_) {}
  _loadWorldIntel();
});

document.getElementById('wi-refresh-btn')?.addEventListener('click', _loadWorldIntel);

document.getElementById('wi-sensitivity')?.addEventListener('change', async function () {
  try {
    await apiFetch('/api/world-intel/settings', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ sensitivity: this.value })
    });
  } catch (_) {}
});

// ── Settings: diagnostics ─────────────────────────────────────────────────────
async function _loadLatestDiag() {
  try {
    const r = await fetch('/api/diagnostic/latest', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    _renderDiag(d);
  } catch (_) {}
}

function _renderDiag(d) {
  const grid = document.getElementById('diag-grid');
  const meta = document.getElementById('diag-meta');
  if (!grid) return;

  const checks = d.checks || d.results || {};
  if (!Object.keys(checks).length) {
    grid.innerHTML = '<span class="memory-empty">Click RUN DIAGNOSTICS to check system status.</span>';
    return;
  }
  grid.innerHTML = '';
  for (const [name, info] of Object.entries(checks)) {
    const item    = document.createElement('div');
    item.className = 'diag-item';
    const ok      = typeof info === 'object' ? !!info.ok : !!info;
    const detail  = typeof info === 'object' ? (info.detail || info.message || '') : '';
    const dotCls  = ok ? 'ok' : (info?.warn ? 'warn' : 'err');
    item.innerHTML =
      `<span class="diag-item-dot ${dotCls}"></span>` +
      `<span class="diag-item-name">${_esc(name.toUpperCase().replace(/_/g, ' '))}</span>` +
      `<span class="diag-item-detail">${_esc(detail)}</span>`;
    grid.appendChild(item);
  }
  if (meta && d.timestamp) {
    meta.textContent = 'Last run: ' + new Date(d.timestamp).toLocaleString();
  }
}

document.getElementById('run-diag-btn')?.addEventListener('click', async () => {
  const btn = document.getElementById('run-diag-btn');
  if (btn) btn.textContent = '// RUNNING…';
  try {
    // Kick off async scan, then poll after 35 s
    await apiFetch('/api/diagnostic/run', { method: 'POST' });
    setTimeout(_loadLatestDiag, 35_000);
  } catch (_) {}
  // Re-enable button after a short delay regardless
  setTimeout(() => { if (btn) btn.textContent = '// RUN DIAGNOSTICS'; }, 5_000);
});

// ── Initialisation ────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  // Pre-warm CSRF token so first POST is instant
  _fetchCsrfToken().catch(() => {});

  // Connection check + repeat
  _healthCheck();
  setInterval(_healthCheck,    15_000);
  setInterval(_proactiveCheck, 30_000);

  // Welcome message
  addMessage('aria',
    'Hello! I\'m ARIA — your local AI assistant. ' +
    'Type a message below, or hold **Space** to talk. ' +
    'Use the **TERMINAL** tab for bash access and **CONFIG** for settings.'
  );
});
