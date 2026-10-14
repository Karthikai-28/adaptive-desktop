// Agent Office — app shell: live state, side panel, modals, voice.
import * as world from './world.js';
import { portrait } from './sprites.js';
import { speak, stopSpeaking, setMuted, onSpeak, isSpeaking, Mic, sttSupported } from './voice.js';
import { createTokens } from './tokens.js';

const MGR = 'claude';
const $ = (s, r = document) => r.querySelector(s);
// let optional children be written inline as `cond ? el : null`
for (const fn of ['append', 'replaceChildren', 'prepend', 'after']) {
  const orig = Element.prototype[fn];
  Element.prototype[fn] = function (...kids) { return orig.apply(this, kids.flat().filter(k => k != null && k !== false)); };
}

// ------------------------------------------------------------------ prefs (per browser)
const prefs = (() => {
  const d = { voice: true, lang: navigator.language || 'en-US', autoSend: true, ambient: true };
  try { return { ...d, ...JSON.parse(localStorage.getItem('office.prefs') || '{}') }; } catch { return d; }
})();
const savePrefs = () => { try { localStorage.setItem('office.prefs', JSON.stringify(prefs)); } catch { /* private mode */ } };

// ------------------------------------------------------------------ state
const S = {
  roster: {}, order: [], agents: {}, tasks: new Map(), meeting: null, settings: {}, usage: null, quotaUntil: 0,
  threads: {}, unread: {}, events: [], view: { kind: 'home' }, tab: 'chat', operator: 'You', company: '', model: '',
  ready: false, eventsLoaded: new Set(), studies: [],
};
const YOU_LOOK = { skin: '#c68a62', hair: '#1d1d1d', hairStyle: 'short', shirt: '#2fb67c', pants: '#2f3550' };

// ------------------------------------------------------------------ icons
const P = {
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8"/>',
  send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
  clip: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  vol: '<path d="M11 5 6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
  mute: '<path d="M11 5 6 9H2v6h4l5 4V5zM23 9l-6 6M17 9l6 6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  spark: '<path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/>',
  back: '<path d="M15 18l-6-6 6-6"/>',
  more: '<circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/>',
  ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  hf: '<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>',
  play: '<path d="M11 5 6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 0 1 0 7"/>',
  reset: '<path d="M1 4v6h6"/><path d="M3.5 15a9 9 0 1 0 2.1-9.4L1 10"/>',
  chart: '<path d="M3 3v18h18"/><path d="M7 16v-5M12 16V8M17 16v-8"/>',
};
const icon = (n) => `<svg class="i" viewBox="0 0 24 24">${P[n]}</svg>`;
const iconEl = (n) => { const s = document.createElement('span'); s.style.display = 'inline-flex'; s.innerHTML = icon(n); return s.firstChild; };

// ------------------------------------------------------------------ dom helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style') el.style.cssText = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'just now'; if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`; return new Date(ts * 1000).toLocaleDateString();
}
function dur(s) { s = Math.max(0, Math.floor(s)); const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(s % 60).padStart(2, '0')}`; }
const portraits = new Map();
function face(id, size = 48) {
  const p = id === 'operator' ? { look: YOU_LOOK, kind: 'you' } : S.roster[id];
  const c = h('canvas', { width: size, height: size });
  if (p) { const k = `${id}:${size}`; if (!portraits.has(k)) portraits.set(k, portrait(p.look, size, p.kind === 'claude')); c.getContext('2d').drawImage(portraits.get(k), 0, 0); }
  return c;
}
const nameOf = (id) => id === 'operator' ? 'You' : id === 'system' ? 'Office' : (S.roster[id]?.name || id);

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-Office': '1' }, body: body ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
  return d;
}

// ------------------------------------------------------------------ markdown (small, safe)
const COMPANY_RE = /^(?:file:\/\/)?\/.*?\/agent-office\/company\//;
function fileLink(path, label) {
  const p = path.replace(COMPANY_RE, '').replace(/^\.\//, '');
  return `<a class="file" data-path="${esc(p)}">${label}</a>`;
}
const looksLikePath = (s) => /^(?:\.\/)?(?:projects|meetings|company)\/\S+$/.test(s) || COMPANY_RE.test(s) || /^[\w\-./]+\/[\w\-.]+\.\w{1,6}$/.test(s);
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0001${codes.length - 1}\u0001`; });
  s = esc(s);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) => {
    const url = u.replace(/&amp;/g, '&');
    if (/^https?:\/\//.test(url)) return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${t}</a>`;
    if (url.startsWith('file://') || looksLikePath(url)) return fileLink(url, t);
    return t;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,!?:;]|$)/g, '$1<i>$2</i>');
  s = s.replace(/(^|\s)(https?:\/\/[^\s<]+[^\s<.,)])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
  return s.replace(/\u0001(\d+)\u0001/g, (_, i) => {
    const c = codes[+i];
    return looksLikePath(c) ? fileLink(c, `<code>${esc(c)}</code>`) : `<code>${esc(c)}</code>`;
  });
}
function md(src) {
  const blocks = [];
  src = String(src ?? '').replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, code) => { blocks.push(`<pre><code>${esc(code.replace(/\n$/, ''))}</code></pre>`); return `\n\u0000${blocks.length - 1}\u0000\n`; });
  let out = '', list = null, para = [];
  const flush = () => { if (para.length) { out += `<p>${para.map(inline).join('<br>')}</p>`; para = []; } };
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const raw of src.split('\n')) {
    const line = raw.trimEnd(); let m;
    if ((m = line.trim().match(/^\u0000(\d+)\u0000$/))) { flush(); close(); out += blocks[+m[1]]; continue; }
    if (!line.trim()) { flush(); close(); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { flush(); close(); const n = Math.min(4, m[1].length + 1); out += `<h${n}>${inline(m[2])}</h${n}>`; continue; }
    if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { flush(); if (list !== 'ul') { close(); out += '<ul>'; list = 'ul'; } out += `<li>${inline(m[1])}</li>`; continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { flush(); if (list !== 'ol') { close(); out += '<ol>'; list = 'ol'; } out += `<li>${inline(m[1])}</li>`; continue; }
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flush(); close(); out += '<hr>'; continue; }
    if (/^\s*\|[\s:|-]+\|\s*$/.test(line)) continue;                       // table separator rows
    close(); para.push(line.replace(/^\s*>\s?/, ''));
  }
  flush(); close();
  return out;
}
document.addEventListener('click', (e) => {
  const a = e.target.closest('a.file');
  if (a) { e.preventDefault(); openFiles(a.dataset.path); }
});

// ------------------------------------------------------------------ live connection
let ws, backoff = 500, pingTimer;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    backoff = 500; $('#conn').classList.add('hidden');
    clearInterval(pingTimer); pingTimer = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000);
  };
  ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  ws.onclose = () => { $('#conn').classList.remove('hidden'); clearInterval(pingTimer); setTimeout(connect, backoff); backoff = Math.min(8000, backoff * 2); };
}

function handle(m) {
  switch (m.type) {
    case 'state': return onState(m);
    case 'agent': {
      S.agents[m.agent.id] = m.agent; world.updateAgent(m.agent);
      refreshAgentBits(m.agent.id); return;
    }
    case 'event': {
      S.events.push(m.event); if (S.events.length > 400) S.events.shift();
      world.activity(m.event.agent, m.event.kind);
      appendEvent(m.event); return;
    }
    case 'message': return onMessage(m.message);
    case 'task': {
      S.tasks.set(m.task.id, m.task);
      if (S.view.kind === 'agent' && S.view.id === m.task.agent && S.tab === 'tasks') renderBody();
      if (S.view.kind === 'agent' && S.view.id === m.task.agent) renderAgentHeader();
      refreshBoard(); refreshTaskDetail(m.task.id); return;
    }
    case 'meeting': return onMeeting(m);
    case 'toast': return toast(m.text, m.level, m.agent);
    case 'settings': S.settings = m.settings; S.quotaUntil = m.quota_until; renderQuota(); return;
    case 'usage': S.usage = m; renderQuota(); return;
    case 'providers': S.providers = m.providers; renderQuota(); if (S.view.kind === 'home') renderPanel(); return;
    case 'study': S.studies = m.studies; if (S.view.kind === 'agent' && S.tab === 'learning') renderBody(); return;
    case 'tokens': tokens.changed(m); return;
  }
}

function onState(m) {
  const first = !S.ready;
  S.company = m.company; S.operator = m.operator; S.model = m.model;
  S.order = m.roster.map(p => p.id);
  S.roster = Object.fromEntries(m.roster.map(p => [p.id, p]));
  S.agents = Object.fromEntries(m.agents.map(a => [a.id, a]));
  S.tasks = new Map(m.tasks.map(t => [t.id, t]));
  S.settings = m.settings; S.quotaUntil = m.quota_until; S.studies = m.studies || []; S.providers = m.providers || [];
  document.title = `${m.company} · Agent Office`;
  $('#company').textContent = m.company;
  world.syncPeople(m.roster);
  for (const a of m.agents) world.updateAgent(a);
  const hadMeeting = S.meeting;
  S.meeting = m.meeting; world.setMeeting(m.meeting);
  S.ready = true;
  // catch up threads we already show (we may have missed messages while disconnected)
  for (const th of Object.keys(S.threads)) loadThread(th, true);
  if (first) { renderPanel(); loadFeed(); }
  else if (!!hadMeeting !== !!m.meeting && S.view.kind === 'meeting' && !m.meeting) setView({ kind: 'home' });
  else renderPanel();
  renderTop(); renderQuota(); renderMeetingBar();
}

// ------------------------------------------------------------------ threads
const threadOf = (id) => id === MGR ? 'manager' : `dm:${id}`;
async function loadThread(th, catchUp = false) {
  const have = S.threads[th];
  const after = catchUp && have?.length ? have[have.length - 1].id : 0;
  if (have && !catchUp) return have;
  const rows = await api('GET', `/api/messages?thread=${encodeURIComponent(th)}&after=${after}&limit=200`);
  if (!S.threads[th] || !catchUp) S.threads[th] = [];
  const ids = new Set(S.threads[th].map(x => x.id));
  for (const r of rows) if (!ids.has(r.id)) S.threads[th].push(r);
  if (visibleThread() === th) renderBody();
  return S.threads[th];
}
function visibleThread() {
  if (S.view.kind === 'meeting' && S.meeting) return `meeting:${S.meeting.id}`;
  if (S.view.kind === 'agent' && S.tab === 'chat') return threadOf(S.view.id);
  return null;
}

function onMessage(msg) {
  const th = msg.thread;
  if (S.threads[th] && !S.threads[th].some(x => x.id === msg.id)) S.threads[th].push(msg);
  const fromAgent = msg.sender !== 'operator' && msg.sender !== 'system';
  const willSpeak = prefs.voice && th.startsWith('meeting:');     // its bubble shows while it is spoken
  if (fromAgent && !willSpeak) {
    const short = msg.meta?.kind === 'report' ? `Done with #${msg.meta.task} ✓` : msg.meta?.kind === 'minutes' ? 'Minutes are ready' :
      msg.meta?.kind === 'learning' ? 'New learning report 📚' : msg.text;
    world.say(msg.sender, short, Math.min(14000, 4000 + short.length * 45));
  }
  const visible = visibleThread() === th;
  if (visible) appendMessage(msg);
  else if (fromAgent || msg.sender === 'system' && th.startsWith('meeting:')) { S.unread[th] = (S.unread[th] || 0) + 1; renderTop(); refreshMemberRow(th === 'manager' ? MGR : th.slice(3)); }
  if (fromAgent) maybeSpeak(msg, visible);
  if (th === 'manager' && fromAgent && msg.meta?.kind === 'report' && !visible) toast(`Claude: ${msg.text.slice(0, 120)}${msg.text.length > 120 ? '…' : ''}`, 'ok', MGR);
}

function maybeSpeak(msg, visible) {
  if (!prefs.voice) return;
  const th = msg.thread, kind = msg.meta?.kind;
  if (th.startsWith('meeting:')) return speak(msg.sender, msg.text);
  if (kind === 'report') { if (visible) speak(msg.sender, `I've finished task ${msg.meta.task}. The report is in our chat.`); return; }
  if (kind === 'minutes') return speak(MGR, 'The meeting minutes are ready in our chat.');
  if (kind === 'learning') { if (visible) speak(msg.sender, 'I finished a study session. My learning report is in our chat.'); return; }
  if (visible || (th === 'manager' && kind === 'report')) speak(msg.sender, msg.text);
}

// ------------------------------------------------------------------ meetings
let meetingTimer;
function onMeeting(m) {
  const was = S.meeting;
  S.meeting = m.meeting; world.setMeeting(m.meeting);
  if (m.meeting && !was) {
    if (S.view.kind !== 'meeting') setView({ kind: 'meeting' });
    world.walkYouTo('meeting');
  } else if (!m.meeting && was) {
    stopHandsFree(); stopSpeaking();
    if (m.ended?.minutes_path) toast(`Meeting ended — notes saved to ${m.ended.minutes_path}`, 'ok');
    if (S.view.kind === 'meeting') setView({ kind: 'home' });
  } else if (S.view.kind === 'meeting') renderPanel();
  renderMeetingBar(); renderTop();
}
function renderMeetingBar() {
  const bar = $('#meetingBar');
  clearInterval(meetingTimer);
  if (!S.meeting || S.view.kind === 'meeting') { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  const t = h('span');
  const tick = () => { t.textContent = dur(Date.now() / 1000 - S.meeting.started_at); };
  tick(); meetingTimer = setInterval(tick, 1000);
  bar.replaceChildren(h('span', { class: 'live' }), h('b', null, S.meeting.topic), t,
    h('button', { onclick: () => setView({ kind: 'meeting' }) }, 'Open'),
  );
}

// ------------------------------------------------------------------ top bar
function renderTop() {
  const counts = { working: 0, thinking: 0, idle: 0, quota: 0 };
  for (const id of S.order) { const a = S.agents[id]; if (a) counts[a.status] = (counts[a.status] || 0) + 1; }
  const parts = [];
  if (counts.working) parts.push(`${counts.working} working`);
  if (counts.thinking) parts.push(`${counts.thinking} replying`);
  if (counts.idle) parts.push(`${counts.idle} free`);
  if (counts.quota) parts.push(`${counts.quota} waiting on quota`);
  const queued = [...S.tasks.values()].filter(t => t.status === 'queued').length;
  if (queued) parts.push(`${queued} queued`);
  $('#summary').textContent = parts.join(' · ');
  const mu = S.unread.manager || 0;
  $('#btnClaude').innerHTML = `${icon('spark')}<span class="lbl">Ask Claude</span>${mu ? `<span class="badge">${mu}</span>` : ''}`;
  $('#btnMeeting').innerHTML = `${icon(S.meeting ? 'users' : 'phone')}<span class="lbl">${S.meeting ? 'In meeting' : 'Call meeting'}</span>`;
  $('#btnTasks').innerHTML = `${icon('clip')}<span class="lbl">Tasks</span>${queued ? `<span class="badge" style="background:#5865f2">${queued}</span>` : ''}`;
  $('#btnFiles').innerHTML = `${icon('folder')}<span class="lbl">Files</span>`;
  $('#btnTokens').innerHTML = `${icon('chart')}<span class="lbl">Tokens</span>`;
  $('#btnVoice').innerHTML = icon(prefs.voice ? 'vol' : 'mute');
  $('#btnVoice').classList.toggle('on', prefs.voice);
  $('#btnVoice').title = prefs.voice ? 'Replies are read aloud (click to mute)' : 'Replies are muted (click to read aloud)';
  $('#btnSettings').innerHTML = icon('gear');
}
function renderQuota() {
  const q = $('#quota'); q.replaceChildren();
  if (S.quotaUntil > Date.now() / 1000) {
    const at = new Date(S.quotaUntil * 1000).toLocaleString([], S.quotaUntil - Date.now() / 1000 > 72000 ? { weekday: 'short', hour: '2-digit', minute: '2-digit' } : { hour: '2-digit', minute: '2-digit' });
    const fb = provider(S.settings?.fallback);
    q.append(fb && fb.engine !== 'agy'
      ? h('span', { class: 'q low', title: `Gemini quota is used up. Agents work on ${provLabel(fb.id)} until it resets.` }, `Gemini out · on ${fb.label} until ${at}`)
      : h('span', { class: 'q out', title: 'Gemini quota is used up. Work resumes by itself at the reset (or earlier if it comes back).' }, `Quota out · resumes ${at}`));
  }
  for (const p of S.providers || []) {
    if (p.engine !== 'ollama') continue;
    const state = !p.up ? ['out', 'Ollama is not running'] : !p.pulled ? ['out', `the model is not pulled: ollama pull ${p.model}`] : ['', p.loaded ? 'model loaded in memory' : 'ready (loads on first use)'];
    q.append(h('span', { class: `q ${state[0]}`, title: `${p.label}: ${p.model} on Ollama ${p.version || ''} · ${state[1]}` },
      h('span', { class: `dot ${state[0] ? 'quota' : ''}` }), `${p.label} · ${p.model}`));
  }
  if (S.settings?.paused) q.append(h('span', { class: 'q out' }, 'Work paused'));
  for (const r of S.usage?.rows || []) {
    // Older servers only sent `remaining`; keep those payloads working while preferring the parsed number.
    const parsed = Number.parseInt(r.remaining, 10);
    const pct = Number.isFinite(r.percent) ? r.percent : Number.isNaN(parsed) ? null : parsed;
    const disabled = pct == null && String(r.remaining).toLowerCase() === 'disabled';
    const cls = disabled ? 'disabled' : pct == null ? '' : pct < 10 ? 'out' : pct < 30 ? 'low' : '';
    const date = r.resets ? new Date(r.resets) : null;
    const reset = date && !Number.isNaN(date.getTime()) ? ` · resets ${date.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })}` : '';
    const label = r.label || (r.family === 'claude-gpt' ? 'Claude + GPT' : 'Gemini');
    const limit = r.window === 'week' ? 'weekly' : r.window === '5h' ? '5-hour' : r.window;
    const title = disabled ? `${label} ${limit} limit is disabled` : `${label} ${limit} limit remaining${reset}`;
    q.append(h('span', { class: `q ${cls}`, title }, `${label} ${r.window}`,
      disabled ? h('span', { class: 'limit-off' }, 'off')
        : h('span', { class: 'bar' }, h('i', { style: `width:${pct == null ? 0 : pct}%` })),
      disabled ? null : r.remaining));
  }
}

// ------------------------------------------------------------------ panel
const panel = $('#panel');
let V = {};
function setView(v, tab) {
  if (S.view.kind === 'meeting' && v.kind !== 'meeting') stopHandsFree();
  S.view = v;
  if (tab) S.tab = tab; else if (v.kind === 'agent') S.tab = 'chat';
  world.select(v.kind === 'agent' ? v.id : null);
  renderPanel(); renderMeetingBar();
}
function renderPanel() {
  if (!S.ready) { panel.replaceChildren(h('div', { class: 'empty' }, 'Connecting to the office…')); return; }
  V = {};
  if (S.view.kind === 'agent' && S.roster[S.view.id]) return renderAgent();
  if (S.view.kind === 'meeting' && S.meeting) return renderMeeting();
  S.view = { kind: 'home' };
  renderHome();
}

// ---- home
function renderHome() {
  const team = h('div');
  for (const id of [MGR, ...S.order.filter(x => x !== MGR)]) team.append(memberRow(id));
  V.feed = h('div', { class: 'feed' });
  panel.replaceChildren(
    h('div', { class: 'ph' },
      h('div', { class: 'who' }, h('div', { class: 'meta' },
        h('div', { class: 'name' }, S.company),
        h('div', { class: 'role' }, `${S.order.length - 1} agents on ${provLabel(S.settings?.provider)}` +
          (S.settings?.fallback ? ` (${provider(S.settings.fallback)?.label || S.settings.fallback} when out of quota)` : '') + ' · managed by Claude'))),
      h('div', { class: 'actions' },
        h('button', { class: 'act primary', onclick: () => setView({ kind: 'agent', id: MGR }) }, iconEl('spark'), 'Ask Claude'),
        h('button', { class: 'act', onclick: () => S.meeting ? setView({ kind: 'meeting' }) : openMeetingSetup() }, iconEl('phone'), S.meeting ? 'Join meeting' : 'Meeting'),
        h('button', { class: 'act', onclick: () => openAssign() }, iconEl('plus'), 'Task'))),
    h('div', { class: 'pb' }, h('div', { class: 'section' }, 'Team'), team, h('div', { class: 'section' }, 'Live activity'), V.feed));
  V.team = team;
  fillFeed();
}
const provider = (id) => (S.providers || []).find(p => p.id === id);
// "Gemini 3.8 Flash (High)" for agy, "Local (granite4:3b)" for anything else
const provLabel = (id) => { const p = provider(id); return !p ? prettyModel(S.model) : p.engine === 'agy' ? prettyModel(p.model) : `${p.label} (${p.model})`; };
const prettyModel = (m) => (m || '').replace(/^gemini-/, 'Gemini ').replace(/-(high|medium|low)$/, (_, e) => ` (${e[0].toUpperCase() + e.slice(1)})`).replace(/-/g, ' ').replace(/(\d) (\d)/g, '$1.$2').replace(/ flash/i, ' Flash');

function statusText(a, id) {
  if (!a) return ['idle', 'Free'];
  if (a.in_meeting && a.status !== 'working') return ['meeting', 'In meeting'];
  return ({ working: ['working', 'Working'], thinking: ['thinking', id === MGR ? 'Thinking' : 'Replying'], quota: ['quota', 'Out of quota'], idle: ['idle', 'Free'] })[a.status] || ['idle', a.status];
}
function memberRow(id) {
  const p = S.roster[id], a = S.agents[id];
  const [cls, label] = statusText(a, id);
  const unread = S.unread[threadOf(id)] || 0;
  let line = '';
  if (a?.task) line = `#${a.task.id} ${a.task.title}`;
  else if (a && a.status !== 'idle' && a.activity) line = a.activity;
  else if (a?.queued) line = `${a.queued} queued`;
  return h('div', { class: 'member', 'data-id': id, onclick: () => setView({ kind: 'agent', id }) },
    face(id, 38),
    h('div', { class: 'm' },
      h('div', { class: 'n' }, p.name, h('span', { class: `pill ${cls}` }, label), unread ? h('span', { class: 'pill failed' }, `${unread} new`) : null),
      h('div', { class: 'r' }, p.role),
      line ? h('div', { class: 'a' }, line) : null));
}
function refreshMemberRow(id) {
  if (!V.team) return;
  const old = V.team.querySelector(`.member[data-id="${CSS.escape(id)}"]`);
  if (old) old.replaceWith(memberRow(id));
}
function refreshAgentBits(id) {
  renderTop();
  refreshMemberRow(id);
  if (S.view.kind === 'agent' && S.view.id === id) { renderAgentHeader(); updateTyping(); }
  if (S.view.kind === 'meeting') renderAttendees();
}

async function loadFeed() {
  try { S.events = await api('GET', '/api/events?limit=80'); } catch { S.events = []; }
  fillFeed();
}
function evRow(e, showWho = true) {
  return h('div', { class: `ev ${e.kind}` }, h('span', { class: 't' }, clock(e.ts)),
    showWho ? h('span', { class: 'w', style: `color:${S.roster[e.agent]?.look.shirt || '#555'}` }, nameOf(e.agent)) : null,
    h('span', { class: 'x' }, e.text));
}
const feedWorthy = (e) => e.kind !== 'think' && e.kind !== 'start';
function fillFeed() {
  if (!V.feed) return;
  const rows = S.events.filter(feedWorthy).slice(-60).reverse();
  V.feed.replaceChildren(...(rows.length ? rows.map(e => evRow(e)) : [h('div', { class: 'empty' }, 'Nothing yet. Ask Claude for something, assign a task, or call a meeting.')]));
}
function appendEvent(e) {
  if (V.feed && feedWorthy(e)) { V.feed.querySelector('.empty')?.remove(); V.feed.prepend(evRow(e)); while (V.feed.children.length > 80) V.feed.lastChild.remove(); }
  if (V.actFeed && S.view.id === e.agent) {
    V.actFeed.querySelector('.empty')?.remove();
    const nearBottom = V.body.scrollHeight - V.body.scrollTop - V.body.clientHeight < 60;
    V.actFeed.append(evRow(e, false));
    if (nearBottom) V.body.scrollTop = V.body.scrollHeight;
  }
}

// ---- agent / Claude
function renderAgent() {
  const id = S.view.id;
  V.header = h('div', { class: 'ph' });
  V.tabs = h('div', { class: 'tabs' });
  V.body = h('div', { class: 'pb' });
  V.composer = null;
  panel.replaceChildren(V.header, V.tabs, V.body);
  if (S.tab === 'chat') {
    V.composer = composer({
      placeholder: id === MGR ? 'Tell Claude what you need…' : `Message ${S.roster[id].name}…`,
      onSend: (text) => api('POST', '/api/chat', { to: id, text }),
    });
    panel.append(V.composer.el);
  }
  renderAgentHeader(); renderTabs(); renderBody();
  if (S.tab === 'chat') setTimeout(() => V.composer?.focus(), 30);
}

document.addEventListener('click', () => document.querySelectorAll('.menu .pop').forEach(p => p.classList.add('hidden')));
function renderAgentHeader() {
  if (!V.header || V.header.querySelector('.pop:not(.hidden)')) return;
  const id = S.view.id, p = S.roster[id], a = S.agents[id] || {};
  const [cls, label] = statusText(a, id);
  const isMgr = id === MGR;
  let doing = null;
  if (a.task) doing = h('div', { class: 'doing' }, h('b', null, `Working on #${a.task.id}: `), a.task.title,
    a.activity ? h('div', { class: 'muted' }, `${a.activity} · ${ago(a.activity_ts)}`) : null,
    a.queued ? h('div', { class: 'muted' }, `${a.queued} more queued`) : null);
  else if (a.status !== 'idle' && a.activity) doing = h('div', { class: 'doing' }, a.activity, h('div', { class: 'muted' }, ago(a.activity_ts)));
  else if (a.queued) doing = h('div', { class: 'doing' }, `${a.queued} task(s) queued`);
  else if (isMgr && !S.settings.autopilot) doing = h('div', { class: 'doing' }, 'Autopilot is off: Claude only reviews work when you ask.');

  const menu = h('div', { class: 'menu' });
  const pop = h('div', { class: 'pop hidden' });
  const item = (ic, text, fn) => h('button', { onclick: (e) => { e.stopPropagation(); pop.classList.add('hidden'); fn(); } }, iconEl(ic), text);
  pop.append(
    item('stop', isMgr ? 'Stop what Claude is doing' : 'Stop current work', () => api('POST', `/api/agents/${id}/stop`).then(() => toast('Stopped', 'ok')).catch(e => toast(e.message, 'error'))),
    item('reset', 'Reset memory (fresh conversation)', () => { if (confirm(`Reset ${p.name}'s memory? Their past conversations are forgotten (files stay).`)) api('POST', `/api/agents/${id}/reset`).then(() => toast('Memory reset', 'ok')); }),
    isMgr ? item('spark', S.settings.autopilot ? 'Turn autopilot off' : 'Turn autopilot on', () => api('POST', '/api/settings', { autopilot: !S.settings.autopilot }).then(s => { S.settings = s; renderAgentHeader(); })) : null,
    item('clip', 'Show tasks on the board', () => openBoard(isMgr ? '' : id)),
  );
  menu.append(h('button', { class: 'act square', title: 'More', onclick: (e) => { e.stopPropagation(); pop.classList.toggle('hidden'); } }, iconEl('more')), pop);

  V.header.replaceChildren(
    h('button', { class: 'back', onclick: () => setView({ kind: 'home' }) }, iconEl('back'), 'Team'),
    h('div', { class: 'who' }, face(id, 56), h('div', { class: 'meta' },
      h('div', { class: 'name' }, p.name, h('span', { class: `status` }, h('span', { class: `dot ${cls}` }), label)),
      h('div', { class: 'role' }, isMgr ? 'Manager · Claude · your point of contact' : `${p.role} · ${p.team} · ${provLabel(S.agents[id]?.provider || S.settings?.provider)}`))),
    doing,
    h('div', { class: 'actions' },
      h('button', { class: 'act primary', onclick: () => { if (S.tab !== 'chat') setView(S.view, 'chat'); else V.composer?.focus(); } }, iconEl('chat'), 'Message'),
      isMgr ? null : h('button', { class: 'act', onclick: () => openAssign(id) }, iconEl('clip'), 'Assign'),
      h('button', { class: 'act', onclick: () => callAgent(id) }, iconEl('phone'), S.meeting ? (S.meeting.attendees.includes(id) ? 'In meeting' : 'Invite') : 'Call'),
      menu));
}

function renderTabs() {
  const id = S.view.id, th = threadOf(id);
  const unread = S.unread[th] || 0;
  const n = [...S.tasks.values()].filter(t => t.agent === id && (t.status === 'queued' || t.status === 'running')).length;
  const tab = (key, label, extra) => h('button', { class: `tab ${S.tab === key ? 'on' : ''}`, onclick: () => setView(S.view, key) }, label, extra);
  V.tabs.replaceChildren(
    tab('chat', 'Chat', unread && S.tab !== 'chat' ? h('span', { class: 'badge' }, unread) : null),
    studyOf(id) ? tab('learning', 'Learning') : null,
    tab('activity', 'Activity'),
    tab('tokens', 'Tokens'),
    id === MGR ? null : tab('tasks', 'Tasks', n ? h('span', { class: 'pill running' }, n) : null));
}

async function renderBody() {
  if (!V.body) return;
  if (S.view.kind === 'meeting') return renderTranscript();
  const id = S.view.id;
  if (S.tab === 'chat') {
    const th = threadOf(id);
    S.unread[th] = 0; renderTop(); refreshMemberRow(id);
    if (!S.threads[th]) { V.body.replaceChildren(h('div', { class: 'empty' }, 'Loading…')); await loadThread(th); return; }
    V.chat = h('div', { class: 'chat' });
    const msgs = S.threads[th];
    if (!msgs.length) V.chat.append(h('div', { class: 'empty' }, id === MGR
      ? `Claude runs the company for you. Tell it what you want built, researched or written — it plans the work, assigns the team and reports back.`
      : `Say hi to ${S.roster[id].name}. Messages are answered right away, even while they work on tasks.`));
    for (const m of msgs) V.chat.append(msgEl(m, false));
    V.typing = h('div', { class: 'typing hidden' }, h('i'), h('i'), h('i'));
    V.chat.append(V.typing);
    V.body.replaceChildren(V.chat);
    updateTyping();
    V.body.scrollTop = V.body.scrollHeight;
    V.actFeed = null;
  } else if (S.tab === 'learning') {
    V.actFeed = null;
    renderLearning(id);
  } else if (S.tab === 'tokens') {
    V.actFeed = null;
    const el = h('div');
    V.body.replaceChildren(el);
    tokens.panelTab(el, id);
  } else if (S.tab === 'activity') {
    V.actFeed = h('div', { class: 'feed' });
    V.body.replaceChildren(V.actFeed);
    let rows = S.events.filter(e => e.agent === id);
    if (!S.eventsLoaded.has(id)) {
      try { rows = await api('GET', `/api/events?agent=${id}&limit=200`); S.eventsLoaded.add(id); } catch { /* keep cached */ }
      const known = new Set(S.events.map(e => e.id));
      S.events = [...rows.filter(e => !known.has(e.id)), ...S.events].sort((a, b) => a.id - b.id);
      rows = S.events.filter(e => e.agent === id);
    }
    V.actFeed.replaceChildren(...(rows.length ? rows.slice(-200).map(e => evRow(e, false)) : [h('div', { class: 'empty' }, 'No activity yet.')]));
    V.body.scrollTop = V.body.scrollHeight;
  } else {
    V.actFeed = null;
    const list = [...S.tasks.values()].filter(t => t.agent === id).sort((a, b) => b.id - a.id);
    V.body.replaceChildren(
      h('div', { class: 'toolbar', style: 'margin-bottom:10px' }, h('button', { class: 'act', onclick: () => openAssign(id) }, iconEl('plus'), 'New task')),
      ...(list.length ? list.map(taskCard) : [h('div', { class: 'empty' }, 'No tasks yet.')]));
  }
}

// ---- learning (study programs)
const studyOf = (id) => S.studies.find(p => p.agent === id);
function askInChat(id, text) {
  setView({ kind: 'agent', id }, 'chat');
  setTimeout(() => V.composer?.setText(text), 40);
}
function renderLearning(id) {
  const p = studyOf(id);
  if (!p) { V.body.replaceChildren(h('div', { class: 'empty' }, 'No study program.')); return; }
  const pr = p.progress || {};
  const topics = [...(pr.topics || [])].sort((a, b) => (a.repo || '').localeCompare(b.repo || '') || (b.mastery || 0) - (a.mastery || 0));
  const avg = topics.length ? topics.reduce((n, t) => n + (t.mastery || 0), 0) / topics.length : 0;
  const q = pr.questions || {};
  const ctl = (action, label, cls = 'act') => h('button', { class: cls, style: 'flex:none;padding:0 12px', onclick: () =>
    api('POST', `/api/study/${p.id}/${action}`).then(st => { const i = S.studies.findIndex(x => x.id === p.id); if (i >= 0) S.studies[i] = st; renderBody(); toast(action === 'now' ? 'Starting a study session' : action === 'pause' ? 'Study paused' : 'Study resumed', 'ok'); })
      .catch(e => toast(e.message, 'error')) }, label);
  let when = '';
  if (p.current) when = `In session now: ${p.current.title}`;
  else if (!p.active) when = 'Paused';
  else if (p.today >= p.max_per_day) when = `Done for today (${p.today}/${p.max_per_day} sessions)`;
  else if (p.next_at) { const m = Math.ceil((p.next_at - Date.now() / 1000) / 60); when = m <= 0 ? 'Next session starting shortly' : `Next session in ${m} min`; }
  const bar = (v) => h('span', { class: 'mbar' }, ...[1, 2, 3, 4, 5].map(i => h('i', { class: i <= v ? 'on' : '' })));
  const file = (path, label) => h('a', { class: 'file', 'data-path': `${p.kb}/${path}` }, label);
  const repos = {};
  for (const r of p.repos) (repos[r.phase] = repos[r.phase] || []).push(r);
  const byRepo = {};
  for (const t of topics) (byRepo[t.repo || 'other'] = byRepo[t.repo || 'other'] || []).push(t);
  V.body.replaceChildren(
    h('div', { class: 'box' },
      h('div', { style: 'display:flex;justify-content:space-between;align-items:center;gap:8px' },
        h('b', null, p.title), h('span', { class: `pill ${p.current ? 'running' : p.active ? 'idle' : 'cancelled'}` }, p.current ? 'studying' : p.active ? 'active' : 'paused')),
      h('div', { class: 'hintline' }, `${p.sessions} session(s) done · ${p.today}/${p.max_per_day} today · every ${p.gap_min} min`),
      h('div', { class: 'hintline' }, when),
      h('div', { class: 'toolbar', style: 'margin-top:10px;flex-wrap:wrap' },
        p.active ? ctl('pause', 'Pause') : ctl('resume', 'Resume', 'act primary'),
        p.current ? null : ctl('now', 'Study now'),
        p.latest_report ? h('button', { class: 'act', style: 'flex:none;padding:0 12px', onclick: () => openFiles(p.latest_report) }, 'Latest report') : null,
        h('button', { class: 'act', style: 'flex:none;padding:0 12px', onclick: () => openFiles(p.kb) }, 'Knowledge base'))),
    h('div', { class: 'section' }, 'Mastery'),
    topics.length ? h('div', { class: 'box' },
      h('div', { style: 'display:flex;gap:16px;flex-wrap:wrap' },
        h('div', null, h('b', { style: 'font-size:20px' }, avg.toFixed(1)), ' / 5 average'),
        h('div', null, h('b', { style: 'font-size:20px' }, topics.length), ' topics'),
        h('div', null, h('b', { style: 'font-size:20px' }, q.answered ?? 0), ' answered · ', h('b', null, q.open ?? 0), ' open')),
      (pr.selftest || []).length ? h('div', { class: 'hintline' }, 'Self-tests: ' + pr.selftest.map(x => `session ${x.session}: ${x.score}`).join(' · ')) : null)
      : h('div', { class: 'empty' }, p.progress_error || (p.sessions || p.current ? 'The first survey is building the curriculum…' : 'Nothing learned yet. The first session surveys every codebase.')),
    ...Object.entries(byRepo).map(([repo, list]) => [
      h('div', { class: 'section' }, repo),
      ...list.map(t => h('div', { class: 'topic' },
        h('div', { class: 'tt' }, h('span', null, t.title || t.id), bar(t.mastery || 0)),
        h('div', { class: 'tl' },
          t.notes ? file(t.notes, 'Notes') : null, t.lesson ? file(t.lesson, 'Lesson') : null,
          h('a', { onclick: () => askInChat(id, `Teach me "${t.title || t.id}" from the very beginning: explain it simply, show me where it lives in the code, then quiz me.`) }, 'Teach me'),
          h('a', { onclick: () => askInChat(id, `About "${t.title || t.id}": `) }, 'Ask'))))]).flat(),
    (pr.questions_for_owner || []).length ? [h('div', { class: 'section' }, `${nameOf(id)} asks you`),
      ...pr.questions_for_owner.map(qq => h('div', { class: 'topic' }, h('div', null, qq),
        h('div', { class: 'tl' }, h('a', { onclick: () => askInChat(id, `Answer to your question "${qq}": `) }, 'Answer'))))] : null,
    h('div', { class: 'section' }, 'Codebases'),
    ...Object.entries(repos).map(([ph, list]) => h('div', { class: 'hintline', style: 'margin-bottom:6px' },
      h('b', null, `Phase ${ph}: `), list.map(r => r.path.split('/').pop() + (r.present ? '' : ' (missing)')).join(', '))),
    h('div', { class: 'hintline', style: 'margin-top:10px' }, 'Code is learned only from the local copies (read-only); Bitbucket and the internal git server are blocked. The web is used only for research.'));
}

function updateTyping() {
  if (!V.typing || S.view.kind !== 'agent') return;
  const id = S.view.id, a = S.agents[id] || {};
  const th = S.threads[threadOf(id)] || [];
  const last = th[th.length - 1];
  const waiting = id === MGR ? a.status === 'working' && last && last.sender === 'operator' : a.chatting;
  V.typing.classList.toggle('hidden', !waiting);
  if (waiting) V.body.scrollTop = V.body.scrollHeight;
}

function msgEl(m, showFrom) {
  if (m.sender === 'system') return h('div', { class: 'msg sys' }, m.text);
  const mine = m.sender === 'operator';
  const kind = m.meta?.kind;
  const body = h('div', { class: 'body md', html: md(m.text) });
  const el = h('div', { class: `msg ${mine ? 'me' : 'them'} ${kind === 'report' || kind === 'learning' ? 'report' : ''} ${kind === 'failure' ? 'failure' : ''}` });
  if (!mine && (showFrom || m.sender !== S.view.id || kind)) {
    el.append(h('div', { class: 'from' }, showFrom ? face(m.sender, 18) : null, nameOf(m.sender),
      kind === 'report' ? h('span', { class: 'pill done' }, `task #${m.meta.task}`) : null,
      kind === 'minutes' ? h('span', { class: 'pill meeting' }, 'minutes') : null,
      kind === 'learning' ? h('span', { class: 'pill thinking' }, 'learning report') : null,
      h('button', { class: 'say', title: 'Read aloud', onclick: () => speak(m.sender, m.text) }, iconEl('play'))));
  } else if (!mine) {
    el.append(h('div', { class: 'from' }, h('button', { class: 'say', title: 'Read aloud', onclick: () => speak(m.sender, m.text) }, iconEl('play'))));
  }
  el.append(body);
  if (m.text.length > 900) {
    el.classList.add('long');
    el.append(h('button', { class: 'more', onclick: (e) => { el.classList.toggle('long'); e.target.textContent = el.classList.contains('long') ? 'Show more' : 'Show less'; } }, 'Show more'));
  }
  el.append(h('div', { class: 'when' }, clock(m.ts)));
  return el;
}
function appendMessage(m) {
  if (!V.chat) return;
  V.chat.querySelector('.empty')?.remove();
  const near = V.body.scrollHeight - V.body.scrollTop - V.body.clientHeight < 120;
  const el = msgEl(m, S.view.kind === 'meeting');
  V.typing ? V.chat.insertBefore(el, V.typing) : V.chat.append(el);
  updateTyping();
  if (near || m.sender === 'operator') V.body.scrollTop = V.body.scrollHeight;
}

// ---- meeting
function renderMeeting() {
  const m = S.meeting;
  V.header = h('div', { class: 'ph' });
  V.body = h('div', { class: 'pb' });
  V.composer = composer({
    placeholder: 'Talk to the room…',
    onSend: (text) => api('POST', '/api/meeting/say', { text }),
    meeting: true,
  });
  const timer = h('span', { class: 'status' });
  const tick = () => { if (S.meeting) timer.textContent = dur(Date.now() / 1000 - S.meeting.started_at); };
  tick(); V.timer = setInterval(() => { if (!document.body.contains(timer)) clearInterval(V.timer); else tick(); }, 1000);
  V.attendees = h('div', { class: 'attendees' });
  V.header.replaceChildren(
    h('button', { class: 'back', onclick: () => setView({ kind: 'home' }) }, iconEl('back'), 'Team (meeting keeps running)'),
    h('div', { class: 'who' }, h('div', { class: 'meta' },
      h('div', { class: 'name' }, h('span', { class: 'dot meeting' }), m.topic),
      h('div', { class: 'role' }, 'Meeting room · ', timer))),
    V.attendees,
    h('div', { class: 'actions' },
      h('button', { class: 'act', onclick: openInvite }, iconEl('plus'), 'Invite'),
      h('button', { class: 'act', onclick: () => stopSpeaking() }, iconEl('mute'), 'Skip speech'),
      h('button', { class: 'act danger', onclick: endMeeting }, iconEl('x'), 'End meeting')));
  panel.replaceChildren(V.header, V.body, V.composer.el);
  renderAttendees(); renderTranscript();
  setTimeout(() => V.composer?.focus(), 30);
}
function renderAttendees() {
  if (!V.attendees || !S.meeting) return;
  const chip = (id) => {
    const a = S.agents[id] || {};
    const speakingNow = speakingId === id;
    return h('span', { class: `chip ${speakingNow ? 'speaking' : ''} ${a.meeting_busy || (id === MGR && a.status === 'working') ? 'thinking' : ''}`, title: a.meeting_busy ? 'thinking…' : '' },
      face(id, 22), nameOf(id), a.meeting_busy || (id === MGR && a.status === 'working') ? ' …' : '');
  };
  V.attendees.replaceChildren(chip('operator'), ...S.meeting.attendees.map(chip));
}
async function renderTranscript() {
  const th = `meeting:${S.meeting.id}`;
  S.unread[th] = 0;
  if (!S.threads[th]) { V.body.replaceChildren(h('div', { class: 'empty' }, 'Loading…')); await loadThread(th); return; }
  V.chat = h('div', { class: 'chat' });
  for (const m of S.threads[th]) V.chat.append(msgEl(m, true));
  V.typing = null;
  V.body.replaceChildren(V.chat);
  V.body.scrollTop = V.body.scrollHeight;
}
async function endMeeting() {
  if (!confirm('End the meeting? Notes are saved, and Claude writes minutes and assigns the agreed action items.')) return;
  try { await api('POST', '/api/meeting/end'); } catch (e) { toast(e.message, 'error'); }
}
async function callAgent(id) {
  if (S.meeting) {
    if (S.meeting.attendees.includes(id)) return setView({ kind: 'meeting' });
    try { await api('POST', '/api/meeting/invite', { attendees: [id] }); toast(`${nameOf(id)} is joining the meeting`, 'ok'); setView({ kind: 'meeting' }); }
    catch (e) { toast(e.message, 'error'); }
    return;
  }
  try { await api('POST', '/api/meeting/start', { topic: `Call with ${nameOf(id)}`, attendees: [id] }); }
  catch (e) { toast(e.message, 'error'); }
}

// ------------------------------------------------------------------ composer + mic
let mic = null, micOwner = null, handsFree = false, speakingId = null;
function composer({ placeholder, onSend, meeting }) {
  const ta = h('textarea', { rows: 1, placeholder });
  const idleNote = meeting ? 'Say a name to ask one person, or talk to everyone.' : '';
  const note = h('div', { class: 'note' }, idleNote);
  const micBtn = h('button', { class: 'roundbtn', title: sttSupported ? 'Speak (click, talk, it sends when you pause)' : 'Voice input needs Chrome' }, iconEl('mic'));
  const hfBtn = meeting ? h('button', { class: `roundbtn ${handsFree ? 'hf' : ''}`, title: 'Hands-free: keep listening, send each sentence' }, iconEl('hf')) : null;
  const sendBtn = h('button', { class: 'roundbtn send', title: 'Send (Enter)' }, iconEl('send'));
  let base = '';
  const grow = () => { ta.style.height = 'auto'; ta.style.height = Math.min(140, ta.scrollHeight) + 'px'; };
  const send = async (text) => {
    text = (text ?? ta.value).trim(); if (!text) return;
    ta.value = ''; grow(); note.textContent = idleNote;
    try { await onSend(text); } catch (e) { toast(e.message, 'error'); ta.value = text; grow(); }
  };
  ta.addEventListener('input', grow);
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  sendBtn.onclick = () => send();

  const setState = (st) => {
    micBtn.classList.toggle('rec', st === 'listening');
    if (hfBtn) hfBtn.classList.toggle('hf', handsFree);
    note.textContent = st === 'listening' ? 'Listening… pause to send' : st === 'handsfree' ? 'Hands-free: listening — just talk' :
      st === 'paused' ? 'Hands-free: waiting while someone speaks…' : st === 'denied' ? 'Microphone permission was blocked — allow it in the address bar.' :
      st === 'unsupported' ? 'Voice input needs Chrome or Edge.' : st.startsWith?.('error:') ? `Mic problem (${st.slice(6)}) — try again.` : '';
  };
  const ensureMic = () => {
    if (mic && micOwner === ta) return mic;
    mic?.stop();
    micOwner = ta;
    mic = new Mic({
      lang: prefs.lang,
      onInterim: (t) => { if (!handsFree) { ta.value = (base ? base + ' ' : '') + t; grow(); } else note.textContent = `“${t}”`; },
      onFinal: (t) => { const full = handsFree ? t : ((base ? base + ' ' : '') + t); if (handsFree || prefs.autoSend) send(full); else { ta.value = full; grow(); } },
      onState: setState,
    });
    return mic;
  };
  micBtn.onclick = () => {
    if (!sttSupported) return setState('unsupported');
    stopSpeaking();
    const m = ensureMic();
    if (m.active && !handsFree) { m.stop(); return; }
    if (handsFree) { handsFree = false; m.stop(); }
    base = ta.value.trim();
    m.start(false);
  };
  if (hfBtn) hfBtn.onclick = () => {
    if (!sttSupported) return setState('unsupported');
    const m = ensureMic();
    if (handsFree) { handsFree = false; m.stop(); setState('idle'); return; }
    handsFree = true; m.stop(); m.start(true);
    if (isSpeaking()) m.pause();
  };
  const el = h('div', { class: 'composer' }, h('div', { class: 'row' }, ta, micBtn, hfBtn, sendBtn), note);
  if (handsFree && meeting) setTimeout(() => { const m = ensureMic(); m.start(true); }, 50);
  return { el, focus: () => ta.focus(), setText: (t) => { ta.value = t; grow(); ta.focus(); ta.setSelectionRange(t.length, t.length); } };
}
function stopHandsFree() { if (handsFree) { handsFree = false; mic?.stop(); } }

onSpeak('start', (who, text) => {
  speakingId = who; world.setSpeaking(who, true); world.say(who, text, 60000);
  if (handsFree) mic?.pause();
  renderAttendees();
});
onSpeak('end', (who) => {
  speakingId = null; world.setSpeaking(who, false);
  if (handsFree) setTimeout(() => { if (!isSpeaking()) mic?.resume(); }, 300);
  renderAttendees();
});

// ------------------------------------------------------------------ toasts
function toast(text, level = 'info', agent) {
  const t = h('div', { class: `toast ${level}`, onclick: () => { t.remove(); if (agent && S.roster[agent]) setView({ kind: 'agent', id: agent }); } }, text);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), level === 'error' ? 9000 : 6000);
  while ($('#toasts').children.length > 4) $('#toasts').firstChild.remove();
}

// ------------------------------------------------------------------ modals
let modalKind = null;
function openModal(kind, title, body, footer = [], wide = false) {
  modalKind = kind;
  const m = $('#modal');
  m.className = wide ? 'wide' : '';
  m.replaceChildren(
    h('div', { class: 'mh' }, h('h2', null, title), h('button', { class: 'x', title: 'Close', onclick: closeModal }, iconEl('x'))),
    h('div', { class: 'mb' }, body),
    footer.length ? h('div', { class: 'mf' }, ...footer) : null);
  $('#modalWrap').classList.remove('hidden');
  setTimeout(() => m.querySelector('input, textarea')?.focus(), 30);
}
function closeModal() { $('#modalWrap').classList.add('hidden'); $('#modal').replaceChildren(); modalKind = null; boardFilter = null; detailId = null; }
$('#modalWrap').addEventListener('mousedown', (e) => { if (e.target.id === 'modalWrap') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && modalKind) closeModal(); });

// ---- assign
function openAssign(agent) {
  const sel = h('select', { class: 'in' }, ...S.order.filter(id => id !== MGR).map(id => h('option', { value: id, selected: id === agent }, `${S.roster[id].name} — ${S.roster[id].role}`)));
  const title = h('input', { class: 'in', placeholder: 'e.g. Research the top 5 competitors' });
  const body = h('textarea', { class: 'in', placeholder: 'What you want, the deliverable, and what “done” looks like.' });
  const projects = [...new Set([...S.tasks.values()].map(t => t.project).filter(Boolean))];
  const project = h('input', { class: 'in', list: 'projlist', placeholder: 'optional, e.g. landing-page' });
  const repo = h('input', { class: 'in', list: 'repolist', placeholder: 'optional: a repo this task may change (path or name)' });
  const repolist = h('datalist', { id: 'repolist' });
  api('GET', '/api/repos').then(r => repolist.replaceChildren(...r.repos.map(p => h('option', { value: p })))).catch(() => {});
  const open = [...S.tasks.values()].filter(t => ['queued', 'running', 'done'].includes(t.status)).sort((a, b) => b.id - a.id).slice(0, 40);
  const after = h('select', { class: 'in' }, h('option', { value: '' }, 'Start right away'),
    ...open.map(t => h('option', { value: t.id }, `After #${t.id} ${nameOf(t.agent)}: ${t.title.slice(0, 60)} (${t.status})`)));
  const go = h('button', { class: 'act primary', style: 'flex:none;padding:0 16px' }, 'Assign task');
  const submit = async () => {
    if (!title.value.trim()) return title.focus();
    go.disabled = true;
    try {
      const t = await api('POST', '/api/tasks', { agent: sel.value, title: title.value, body: body.value, project: project.value, after: after.value ? +after.value : null, repo: repo.value });
      toast(`Assigned #${t.id} to ${nameOf(t.agent)}`, 'ok', t.agent); closeModal();
    } catch (e) { toast(e.message, 'error'); go.disabled = false; }
  };
  go.onclick = submit;
  title.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  openModal('assign', 'Assign a task', h('div', null,
    h('label', { class: 'f' }, 'Who'), sel,
    h('label', { class: 'f' }, 'Task'), title,
    h('label', { class: 'f' }, 'Details'), body,
    h('label', { class: 'f' }, 'Project'), project, h('datalist', { id: 'projlist' }, ...projects.map(p => h('option', { value: p }))),
    h('label', { class: 'f' }, 'Writable repo'), repo, repolist,
    h('label', { class: 'f' }, 'When'), after,
    h('div', { class: 'hintline' }, 'Every agent can read every repo on the laptop; only the repo named here can be changed, and nobody pushes. Tip: you can also just tell Claude what you want — it splits the work and assigns the right people.')),
  [h('button', { class: 'act', style: 'flex:none;padding:0 16px', onclick: closeModal }, 'Cancel'), go]);
}

// ---- meeting setup / invite
function pickList(ids, checked) {
  const wrap = h('div', { class: 'picks' });
  for (const id of ids) {
    const cb = h('input', { type: 'checkbox', checked: checked.includes(id) });
    const row = h('label', { class: `pick ${checked.includes(id) ? 'on' : ''}` }, face(id, 30), h('div', null, h('div', null, h('b', null, S.roster[id].name)), h('div', { class: 'r' }, S.roster[id].role)), cb);
    cb.onchange = () => row.classList.toggle('on', cb.checked);
    row.dataset.id = id; wrap.append(row);
  }
  wrap.value = () => [...wrap.querySelectorAll('.pick')].filter(r => r.querySelector('input').checked).map(r => r.dataset.id);
  return wrap;
}
function openMeetingSetup(preselect) {
  if (S.meeting) return setView({ kind: 'meeting' });
  const ids = [MGR, ...S.order.filter(x => x !== MGR)];
  const topic = h('input', { class: 'in', placeholder: 'e.g. Plan the launch of our first product' });
  const picks = pickList(ids, preselect || ids);
  const go = h('button', { class: 'act primary', style: 'flex:none;padding:0 16px' }, iconEl('phone'), 'Start meeting');
  go.onclick = async () => {
    const who = picks.value(); if (!who.length) return toast('Invite at least one person', 'warn');
    go.disabled = true;
    try { await api('POST', '/api/meeting/start', { topic: topic.value, attendees: who }); closeModal(); }
    catch (e) { toast(e.message, 'error'); go.disabled = false; }
  };
  openModal('meeting', 'Call a meeting', h('div', null,
    h('label', { class: 'f' }, 'Topic'), topic,
    h('label', { class: 'f' }, 'Who should come'), picks,
    h('div', { class: 'hintline' }, 'Everyone walks to the meeting room. Talk or type; agents answer out loud in their own voices. With Claude in the room, it chairs, writes minutes at the end and assigns the agreed action items.')),
  [h('button', { class: 'act', style: 'flex:none;padding:0 16px', onclick: closeModal }, 'Cancel'), go]);
}
function openInvite() {
  const ids = [MGR, ...S.order.filter(x => x !== MGR)].filter(id => !S.meeting.attendees.includes(id));
  if (!ids.length) return toast('Everyone is already here', 'info');
  const picks = pickList(ids, []);
  const go = h('button', { class: 'act primary', style: 'flex:none;padding:0 16px' }, 'Invite');
  go.onclick = async () => { const who = picks.value(); if (!who.length) return; try { await api('POST', '/api/meeting/invite', { attendees: who }); closeModal(); } catch (e) { toast(e.message, 'error'); } };
  openModal('invite', 'Invite to the meeting', picks, [go]);
}

// ---- task board
let boardFilter = null, detailId = null;
function taskCard(t) {
  const evs = S.agents[t.agent]?.task?.id === t.id ? S.agents[t.agent].activity : '';
  return h('div', { class: 'card', onclick: () => openTask(t.id) },
    h('div', { class: 'tt' }, `#${t.id} ${t.title}`),
    h('div', { class: 'mm' }, face(t.agent, 18), nameOf(t.agent), h('span', { class: `pill ${t.status}` }, t.status),
      t.project ? h('span', { class: 'pill' }, t.project) : null, t.depends_on ? h('span', null, `after #${t.depends_on}`) : null,
      h('span', null, `· ${t.created_by === 'operator' ? 'you' : t.created_by === 'manager' ? 'Claude' : t.created_by}`), h('span', null, `· ${ago(t.finished_at || t.started_at || t.created_at)}`)),
    evs ? h('div', { class: 'last' }, evs) : t.status === 'failed' && t.error ? h('div', { class: 'last', style: 'color:#c03' }, t.error) : null);
}
function openBoard(agent = '') {
  boardFilter = agent;
  const sel = h('select', { onchange: (e) => { boardFilter = e.target.value; refreshBoard(); } },
    h('option', { value: '' }, 'Everyone'), ...S.order.filter(id => id !== MGR).map(id => h('option', { value: id, selected: id === agent }, S.roster[id].name)));
  const body = h('div', { class: 'board', id: 'board' });
  openModal('board', 'Tasks', body, [], true);
  $('#modal .mh h2').after(h('div', { class: 'toolbar' }, sel, h('button', { class: 'act', style: 'flex:none;padding:0 12px', onclick: () => openAssign(boardFilter || undefined) }, iconEl('plus'), 'New task')));
  $('#modal .mb').style.overflow = 'hidden';
  refreshBoard();
}
function refreshBoard() {
  const b = document.getElementById('board'); if (!b || modalKind !== 'board') return;
  const all = [...S.tasks.values()].filter(t => !boardFilter || t.agent === boardFilter).sort((a, b) => b.id - a.id);
  const cols = [['Queued', ['queued']], ['In progress', ['running']], ['Done', ['done']], ['Failed / cancelled', ['failed', 'cancelled']]];
  b.replaceChildren(...cols.map(([name, st]) => {
    const list = all.filter(t => st.includes(t.status));
    if (name === 'Queued') list.reverse();
    return h('div', { class: 'col' }, h('h3', null, name, h('span', null, list.length)),
      h('div', { class: 'cards' }, ...(list.length ? list.slice(0, 80).map(taskCard) : [h('div', { class: 'empty' }, '—')])));
  }));
}
async function openTask(id) {
  detailId = id;
  let t;
  try { t = await api('GET', `/api/tasks/${id}`); } catch (e) { return toast(e.message, 'error'); }
  if (detailId !== id) return;
  const kv = (k, v) => v || v === 0 ? [h('div', null, k), h('div', null, v)] : [];
  const when = (ts) => ts ? new Date(ts * 1000).toLocaleString() : '';
  const body = h('div', null,
    h('div', { class: 'kv' },
      ...kv('Agent', nameOf(t.agent)), ...kv('Status', h('span', { class: `pill ${t.status}` }, t.status)),
      ...kv('Assigned by', t.created_by === 'operator' ? 'You' : t.created_by === 'manager' ? 'Claude' : t.created_by),
      ...kv('Project', t.project), ...kv('Repo', t.repo), ...kv('After', t.depends_on ? `#${t.depends_on}` : ''),
      ...kv('Created', when(t.created_at)), ...kv('Started', when(t.started_at)), ...kv('Finished', when(t.finished_at)),
      ...kv('Steps', t.steps || ''), ...kv('Tokens', t.tokens ? t.tokens.toLocaleString() : '')),
    t.body ? [h('div', { class: 'section' }, 'Details'), h('div', { class: 'box md', html: md(t.body) })] : null,
    t.error ? [h('div', { class: 'section' }, 'Problem'), h('div', { class: 'box err' }, t.error)] : null,
    t.result ? [h('div', { class: 'section' }, 'Report'), h('div', { class: 'box md', html: md(t.result) })] : null,
    t.events?.length ? [h('div', { class: 'section' }, 'Activity'), h('div', { class: 'feed' }, ...t.events.filter(feedWorthy).map(e => evRow(e, false)))] : null);
  const foot = [];
  if (['queued', 'running'].includes(t.status)) foot.push(h('button', { class: 'act danger', style: 'flex:none;padding:0 14px', onclick: () => api('POST', `/api/tasks/${id}/cancel`).catch(e => toast(e.message, 'error')) }, 'Cancel task'));
  if (['failed', 'cancelled'].includes(t.status)) foot.push(h('button', { class: 'act', style: 'flex:none;padding:0 14px', onclick: () => api('POST', `/api/tasks/${id}/retry`).then(() => toast('Queued again', 'ok')).catch(e => toast(e.message, 'error')) }, 'Retry'));
  foot.push(h('button', { class: 'act', style: 'flex:none;padding:0 14px', onclick: () => { closeModal(); setView({ kind: 'agent', id: t.agent }); } }, iconEl('chat'), `Talk to ${nameOf(t.agent)}`));
  foot.push(h('button', { class: 'act primary', style: 'flex:none;padding:0 14px', onclick: () => openBoard() }, 'All tasks'));
  openModal('task', `#${t.id} ${t.title}`, body, foot);
  detailId = id;
}
function refreshTaskDetail(id) { if (modalKind === 'task' && detailId === id) openTask(id); }

// ---- files
let fileDir = '';
async function openFiles(path = '') {
  const list = h('div', { class: 'flist' }), view = h('div', { class: 'fview' }, h('div', { class: 'empty' }, 'Pick a file to view it.'));
  openModal('files', 'Company files', h('div', { class: 'files' }, list, view), [], true);
  $('#modal .mb').style.padding = '0';
  let dir = path, file = null;
  try {
    const d = await api('GET', `/api/files?path=${encodeURIComponent(path)}`);
    if (d.type !== 'dir') { file = d; dir = path.split('/').slice(0, -1).join('/'); }
  } catch (e) { dir = ''; toast(e.message, 'warn'); }
  await showDir(list, view, dir);
  if (file) showFile(view, list, file.path);
}
async function showDir(list, view, dir) {
  fileDir = dir;
  let d;
  try { d = await api('GET', `/api/files?path=${encodeURIComponent(dir)}`); } catch (e) { list.replaceChildren(h('div', { class: 'empty' }, e.message)); return; }
  const crumbs = h('div', { class: 'crumbs' }, h('a', { onclick: () => showDir(list, view, '') }, 'company'));
  let acc = '';
  for (const part of (d.path || '').split('/').filter(Boolean)) { acc = acc ? `${acc}/${part}` : part; const p = acc; crumbs.append(' / ', h('a', { onclick: () => showDir(list, view, p) }, part)); }
  list.replaceChildren(crumbs, ...(d.entries.length ? d.entries.map(e => h('div', { class: 'fitem', 'data-path': e.path, onclick: () => e.dir ? showDir(list, view, e.path) : showFile(view, list, e.path) },
    iconEl(e.dir ? 'folder' : 'file'), e.name, h('span', { class: 's' }, e.dir ? '' : size(e.size)))) : [h('div', { class: 'empty' }, 'Empty folder')]));
}
const size = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
async function showFile(view, list, path) {
  list.querySelectorAll('.fitem').forEach(el => el.classList.toggle('on', el.dataset.path === path));
  let d;
  try { d = await api('GET', `/api/files?path=${encodeURIComponent(path)}`); } catch (e) { view.replaceChildren(h('div', { class: 'empty' }, e.message)); return; }
  const raw = `/api/raw?path=${encodeURIComponent(path)}`;
  const head = h('div', { class: 'toolbar', style: 'margin-bottom:12px' }, h('b', { style: 'flex:1;word-break:break-all' }, path),
    h('a', { class: 'act', style: 'flex:none;padding:0 12px;text-decoration:none', href: raw, target: '_blank', rel: 'noopener' }, iconEl('ext'), 'Open'));
  if (d.type === 'media') {
    const m = d.mime.startsWith('image/') ? h('img', { src: raw, alt: path }) : d.mime.startsWith('video/') ? h('video', { src: raw, controls: true }) :
      d.mime.startsWith('audio/') ? h('audio', { src: raw, controls: true }) : h('iframe', { src: raw, sandbox: '' });
    view.replaceChildren(head, m);
  } else if (d.type === 'binary') view.replaceChildren(head, h('div', { class: 'empty' }, `Binary file (${size(d.size)}).`));
  else if (/\.md$|\.markdown$/i.test(path)) view.replaceChildren(head, h('div', { class: 'md', html: md(d.text) }));
  else if (/\.html?$/i.test(path)) view.replaceChildren(head, h('iframe', { src: raw, sandbox: 'allow-scripts' }), h('pre', { class: 'code', style: 'margin-top:12px;max-height:40vh' }, d.text));
  else view.replaceChildren(head, h('pre', { class: 'code' }, d.text + (d.truncated ? '\n… (truncated)' : '')));
}

// ---- settings
function openSettings() {
  const sw = (title, sub, checked, fn) => {
    const cb = h('input', { type: 'checkbox', checked });
    cb.onchange = () => fn(cb.checked);
    return h('label', { class: 'switch' }, h('div', null, title, h('small', null, sub)), cb);
  };
  const par = h('select', { class: 'in', style: 'width:auto' }, ...[1, 2, 3, 4, 5, 6].map(n => h('option', { value: n, selected: n === S.settings.max_parallel }, n)));
  par.onchange = () => api('POST', '/api/settings', { max_parallel: +par.value }).then(s => { S.settings = s; toast('Saved', 'ok'); });
  const provOpts = (sel, none) => [...(none ? [h('option', { value: '', selected: !sel }, none)] : []),
    ...(S.providers || []).map(p => h('option', { value: p.id, selected: p.id === sel }, p.engine === 'agy' ? prettyModel(p.model) : `${p.label} · ${p.model}`))];
  const prov = h('select', { class: 'in', style: 'width:auto' }, ...provOpts(S.settings.provider));
  prov.onchange = () => api('POST', '/api/settings', { provider: prov.value }).then(s => { S.settings = s; renderQuota(); renderPanel(); toast('Saved', 'ok'); }).catch(e => toast(e.message, 'error'));
  const fall = h('select', { class: 'in', style: 'width:auto' }, ...provOpts(S.settings.fallback, 'Pause'));
  fall.onchange = () => api('POST', '/api/settings', { fallback: fall.value }).then(s => { S.settings = s; renderQuota(); renderPanel(); toast('Saved', 'ok'); }).catch(e => toast(e.message, 'error'));
  const lang = h('select', { class: 'in', style: 'width:auto' }, ...['en-US', 'en-IN', 'en-GB', 'en-AU', 'ta-IN', 'hi-IN'].map(l => h('option', { value: l, selected: l === prefs.lang }, l)));
  lang.onchange = () => { prefs.lang = lang.value; savePrefs(); mic?.stop(); mic = null; micOwner = null; };
  const body = h('div', null,
    h('div', { class: 'section' }, 'Company'),
    sw('Autopilot', 'Claude reviews finished work by itself, assigns follow-ups and reports back.', S.settings.autopilot, v => api('POST', '/api/settings', { autopilot: v }).then(s => { S.settings = s; })),
    sw('Pause all work', 'Queued tasks and study sessions wait; running tasks finish. Chats and meetings still work.', S.settings.paused, v => api('POST', '/api/settings', { paused: v }).then(s => { S.settings = s; renderQuota(); })),
    h('label', { class: 'switch' }, h('div', null, 'Agents working at the same time', h('small', null, 'More is faster but spends Gemini quota quicker.')), par),
    h('label', { class: 'switch' }, h('div', null, 'Agents run on', h('small', null, 'Gemini on your AI Pro plan, or a local model through Ollama (private, free, much slower and weaker).')), prov),
    h('label', { class: 'switch' }, h('div', null, 'When Gemini runs out', h('small', null, 'Carry on with this provider until the quota resets, or pause.')), fall),
    S.quotaUntil > Date.now() / 1000 ? h('label', { class: 'switch' }, h('div', null, 'Quota pause active', h('small', null, 'Resume now if the Gemini limit has reset.')),
      h('button', { class: 'act', style: 'flex:none;padding:0 12px', onclick: () => api('POST', '/api/settings', { clear_quota: true }).then(() => toast('Resumed', 'ok')) }, 'Resume')) : null,
    h('div', { class: 'section' }, 'Voice (this browser)'),
    sw('Read replies aloud', 'Meeting replies always; chat replies when that chat is open.', prefs.voice, v => { prefs.voice = v; savePrefs(); setMuted(!v); renderTop(); }),
    sw('Send when I stop talking', 'Otherwise the words land in the box for you to edit.', prefs.autoSend, v => { prefs.autoSend = v; savePrefs(); }),
    h('label', { class: 'switch' }, h('div', null, 'Speech language', h('small', null, sttSupported ? 'For the microphone.' : 'Voice input needs Chrome or Edge.')), lang),
    h('div', { class: 'section' }, 'Office'),
    sw('Office life', 'Free agents wander to the kitchen and lounge.', prefs.ambient, v => { prefs.ambient = v; savePrefs(); world.setAmbient(v); }),
    h('div', { class: 'hintline', style: 'margin-top:14px;line-height:1.6' },
      `Gemini runs through agy on your Google AI Pro plan; local models through Ollama on this computer. Claude manages through the `, h('code', null, 'office'),
      ` command — you can use it too: `, h('code', null, 'office status'), ', ', h('code', null, 'office assign maya "…"'), ', ', h('code', null, 'office ask claude "…"'), '.'));
  openModal('settings', 'Settings', body);
}

// ------------------------------------------------------------------ world hooks
const tip = $('#tip'), hint = $('#hint');
let lastNear = null;
world.initWorld($('#map'), {
  youLook: YOU_LOOK,
  onSelect: (id) => setView({ kind: 'agent', id }),
  onTalk: (id) => setView({ kind: 'agent', id }, 'chat'),
  onHover: (id, x, y) => {
    if (!id || id === 'you' || !S.roster[id]) { tip.classList.add('hidden'); return; }
    const p = S.roster[id], a = S.agents[id] || {};
    const [, label] = statusText(a, id);
    tip.replaceChildren(h('b', null, `${p.name} · ${label}`), h('div', { class: 'muted' }, p.role),
      a.task ? h('div', null, `#${a.task.id} ${a.task.title}`) : null, a.activity && a.status !== 'idle' ? h('div', { class: 'muted' }, a.activity) : null);
    tip.classList.remove('hidden');
    const w = $('#world').clientWidth;
    tip.style.left = Math.min(x + 16, w - 310) + 'px'; tip.style.top = (y + 14) + 'px';
  },
  onFrame: (near) => {
    const id = near ? near.id : null;
    if (id === lastNear) return;
    lastNear = id;
    if (!id || !S.roster[id]) { hint.classList.add('hidden'); return; }
    hint.innerHTML = `Press <kbd>E</kbd> to talk to ${esc(S.roster[id].name)}`;
    hint.classList.remove('hidden');
  },
});
world.setAmbient(prefs.ambient);
setMuted(!prefs.voice);
document.querySelectorAll('#zoomCtl button').forEach(b => b.onclick = () => world.setZoom(b.dataset.z));

// ------------------------------------------------------------------ token usage
const tokens = createTokens({ h, api, face, iconEl, S, MGR, openModal, modalKind: () => modalKind, openTask });

// ------------------------------------------------------------------ top bar buttons
$('#btnClaude').onclick = () => setView({ kind: 'agent', id: MGR }, 'chat');
$('#btnMeeting').onclick = () => S.meeting ? setView({ kind: 'meeting' }) : openMeetingSetup();
$('#btnTasks').onclick = () => openBoard();
$('#btnFiles').onclick = () => openFiles('');
$('#btnTokens').onclick = () => tokens.open();
$('#btnVoice').onclick = () => { prefs.voice = !prefs.voice; savePrefs(); setMuted(!prefs.voice); renderTop(); toast(prefs.voice ? 'Replies will be read aloud' : 'Muted', 'info'); };
$('#btnSettings').onclick = openSettings;
setInterval(() => { renderQuota(); if (S.view.kind === 'agent') renderAgentHeader(); }, 30000);

renderTop(); renderPanel(); connect();
