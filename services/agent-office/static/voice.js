// Voice: speech-to-text with the browser (Chrome's Web Speech API) and agent voices via /api/tts.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
export const sttSupported = !!SR;

// ------------------------------------------------------------------ text to speech (queue)
const queue = [];
let playing = null;
let muted = false;
const listeners = { start: [], end: [] };
export const onSpeak = (ev, fn) => listeners[ev].push(fn);
export const isSpeaking = () => !!playing;

export function setMuted(v) {
  muted = v;
  if (v) stopSpeaking();
}

export function speak(who, text) {
  if (muted || !text || !text.trim()) return;
  queue.push({ who, text });
  if (!playing) next();
}

export function stopSpeaking() {
  queue.length = 0;
  if (playing) {
    try { playing.audio ? playing.audio.pause() : speechSynthesis.cancel(); } catch { /* already stopped */ }
    const p = playing; playing = null;
    listeners.end.forEach(f => f(p.who));
  }
}

function next() {
  const item = queue.shift();
  if (!item) { playing = null; return; }
  playing = item;
  listeners.start.forEach(f => f(item.who, item.text));
  const done = () => {
    if (playing !== item) return;
    playing = null;
    listeners.end.forEach(f => f(item.who));
    setTimeout(next, 250);
  };
  const audio = new Audio(`/api/tts?who=${encodeURIComponent(item.who)}&text=${encodeURIComponent(item.text.slice(0, 1500))}`);
  item.audio = audio;
  audio.onended = done;
  audio.onerror = () => { item.audio = null; browserSpeak(item, done); };
  audio.play().catch(() => { item.audio = null; browserSpeak(item, done); });
}

function browserSpeak(item, done) {
  if (!('speechSynthesis' in window)) return done();
  const u = new SpeechSynthesisUtterance(item.text.slice(0, 600));
  u.onend = done; u.onerror = done;
  speechSynthesis.speak(u);
}

// ------------------------------------------------------------------ speech to text
// Mic(onInterim, onFinal, onState). `continuous` keeps listening (hands-free meetings).
export class Mic {
  constructor({ onInterim, onFinal, onState, lang }) {
    this.onInterim = onInterim; this.onFinal = onFinal; this.onState = onState;
    this.lang = lang || navigator.language || 'en-US';
    this.rec = null; this.active = false; this.continuous = false; this.paused = false;
  }

  start(continuous = false) {
    if (!SR) { this.onState?.('unsupported'); return false; }
    this.continuous = continuous;
    this.active = true; this.paused = false;
    this._open();
    return true;
  }

  _open() {
    if (this.rec) return;
    const r = new SR();
    r.lang = this.lang; r.interimResults = true; r.continuous = this.continuous; r.maxAlternatives = 1;
    let finalText = '';
    r.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) {
          finalText += t;
          if (this.continuous) { const f = finalText.trim(); finalText = ''; if (f) this.onFinal?.(f); }
        } else interim += t;
      }
      this.onInterim?.((finalText + interim).trim());
    };
    r.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { this.active = false; this.onState?.('denied'); }
      else if (e.error !== 'no-speech' && e.error !== 'aborted') this.onState?.('error:' + e.error);
    };
    r.onend = () => {
      this.rec = null;
      if (!this.continuous) {
        const f = finalText.trim(); finalText = '';
        this.active = false; this.onState?.('idle');
        if (f) this.onFinal?.(f);
        return;
      }
      if (this.active && !this.paused) setTimeout(() => this.active && !this.paused && this._open(), 200);  // keep listening
      else this.onState?.(this.active ? 'paused' : 'idle');
    };
    try { r.start(); this.rec = r; this.onState?.(this.continuous ? 'handsfree' : 'listening'); }
    catch { this.rec = null; }
  }

  // stop listening while agents speak so the mic doesn't hear them
  pause() { if (!this.active || this.paused) return; this.paused = true; try { this.rec?.abort(); } catch { /* not running */ } this.onState?.('paused'); }
  resume() { if (!this.active || !this.paused) return; this.paused = false; this._open(); }

  stop() {
    this.active = false; this.paused = false;
    const r = this.rec;
    if (r) { try { this.continuous ? r.abort() : r.stop(); } catch { /* already stopped */ } }
    if (this.continuous || !r) this.onState?.('idle');
  }
}
