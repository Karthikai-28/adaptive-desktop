// The live office: camera, characters, movement, bubbles and input on the canvas.
import { T, W, H, objects, desks, meetingSeats, idleSpots, labels, spots, buildFloorLayer, findPath, isWalkable } from './map.js';
import { sprite } from './sprites.js';

const SPEED = 52;                       // px per second
const STATUS_COL = { idle: '#3ecf8e', working: '#f5a524', thinking: '#8b9cff', quota: '#ef4444', meeting: '#38bdf8', you: '#3ecf8e' };
const ICON = { write: '⌨', edit: '⌨', run: '▶', search: '🔍', web: '🌐', image: '🎨', read: '📄', think: '…', tool: '⚙', assign: '📋', error: '⚠', done: '✓', start: '…', info: '…' };

let cv, ctx, floorLayer, hooks;
let dpr = 1, scale = 1, offX = 0, offY = 0, zoom = 1, fitScale = 1;
const chars = new Map();
let meeting = null, ambient = true, you = null, hoverId = null, selectedId = null;
const keys = new Set();
const taken = new Map();                // idle spot index -> char id

export function initWorld(canvas, h) {
  cv = canvas; ctx = cv.getContext('2d'); hooks = h;
  floorLayer = buildFloorLayer();
  you = addChar({ id: 'you', name: 'You', look: h.youLook, kind: 'you' });
  const sp = spots.spawn; place(you, sp.x, sp.y, sp.dir);
  you.status = 'you';
  resize(); window.addEventListener('resize', resize);
  new ResizeObserver(resize).observe(cv.parentElement);
  bindInput();
  requestAnimationFrame(loop);
}

export function setAmbient(v) { ambient = v; for (const c of chars.values()) { c.wanderAt = 0; c.wander = null; } }
export function select(id) { selectedId = id; }
export function setZoom(cmd) {
  const cx = cv.clientWidth / 2, cy = cv.clientHeight / 2;
  if (cmd === 'fit') { zoom = 1; layout(); return zoom; }
  zoomAt(cx, cy, cmd === 'in' ? 1.25 : 0.8);
  return zoom;
}

// ------------------------------------------------------------------ people
function addChar(p) {
  const c = {
    id: p.id, name: p.name, look: p.look, kind: p.kind, desk: p.desk, role: p.role,
    x: 0, y: 0, tx: 0, ty: 0, path: [], dir: 'down', frame: 0, walkT: 0, sit: false, seatOff: 0,
    dest: null, status: 'idle', act: '', actKind: '', inMeeting: false, busy: false,
    bubble: null, speaking: false, wanderAt: performance.now() + 8000 + Math.random() * 30000, wander: null,
  };
  chars.set(c.id, c);
  return c;
}

function place(c, tx, ty, dir, sit = false) {
  c.tx = tx; c.ty = ty; c.x = tx * T + 8; c.y = ty * T + 14; c.dir = dir || 'down'; c.sit = sit; c.path = [];
  c.dest = { x: tx, y: ty, dir: c.dir, sit };
  c.seatOff = sit ? (c.dir === 'down' ? 5 : c.dir === 'up' ? 1 : 0) : 0;
}

export function syncPeople(roster) {
  for (const p of roster) {
    if (chars.has(p.id)) { Object.assign(chars.get(p.id), { name: p.name, look: p.look, desk: p.desk, role: p.role }); continue; }
    const c = addChar(p);
    const d = desks[p.desk];
    if (d) { d.owner = p.id; place(c, d.seat.x, d.seat.y, d.seat.dir, true); }
    else place(c, spots.spawn.x + 1, spots.spawn.y, 'down');
  }
}

export function updateAgent(st) {
  const c = chars.get(st.id); if (!c) return;
  c.status = st.status; c.inMeeting = st.in_meeting;
  c.busy = st.chatting || st.meeting_busy;
  c.act = st.activity || ''; c.task = st.task;
  decide(c);
}
export function activity(id, kind) { const c = chars.get(id); if (c) c.actKind = kind; }

export function setMeeting(m) {
  meeting = m;
  for (const c of chars.values()) if (c.kind !== 'you') { c.inMeeting = !!(m && m.attendees.includes(c.id)); decide(c); }
}
export function walkYouTo(where) {
  const s = where === 'meeting' ? spots.meetingHead : spots.spawn;
  goTo(you, { x: s.x, y: s.y, dir: s.dir, sit: false });
}

export function say(id, text, ms = 7000) {
  const c = chars.get(id); if (!c) return;
  c.bubble = { text: text.replace(/\s+/g, ' ').trim(), until: performance.now() + ms };
}
export function setSpeaking(id, on) { const c = chars.get(id); if (c) { c.speaking = on; if (!on && c.bubble) c.bubble.until = Math.min(c.bubble.until, performance.now() + 1500); } }

export function charPos(id) { const c = chars.get(id); return c ? { tx: c.tx, ty: c.ty } : null; }

function seatFor(c) {
  if (c.inMeeting && meeting) {
    if (c.kind === 'claude') return { ...spots.meetingChair, sit: false };
    const order = meeting.attendees.filter(a => chars.get(a)?.kind !== 'claude');
    const i = order.indexOf(c.id);
    const seats = [...meetingSeats].sort((a, b) => a.x - b.x || a.y - b.y);
    const s = seats[i % seats.length];
    return { x: s.x, y: s.y, dir: s.dir, sit: true };
  }
  const d = desks[c.desk];
  return d ? { x: d.seat.x, y: d.seat.y, dir: d.seat.dir, sit: true } : { ...spots.spawn, sit: false };
}

function decide(c) {
  if (c.kind === 'you') return;
  const now = performance.now();
  if (c.wander && (c.status !== 'idle' || c.inMeeting || c.busy || !ambient || now > c.wander.until)) {
    taken.delete(c.wander.idx); c.wander = null; c.wanderAt = now + 30000 + Math.random() * 60000;
  }
  const dest = c.wander ? c.wander.spot : seatFor(c);
  if (!c.dest || c.dest.x !== dest.x || c.dest.y !== dest.y) goTo(c, dest);
  const d = desks[c.desk];
  if (d) d.state = c.inMeeting ? 'meeting' : (c.status === 'working' || c.busy) && atSeat(c) ? 'working' : 'idle';
}

function atSeat(c) { const d = desks[c.desk]; return d && c.tx === d.seat.x && c.ty === d.seat.y && !c.path.length; }

function maybeWander(c, now) {
  if (!ambient || c.kind === 'you' || c.wander || c.status !== 'idle' || c.inMeeting || c.busy || now < c.wanderAt) return;
  c.wanderAt = now + 40000 + Math.random() * 80000;
  if (Math.random() < 0.45) return;
  const free = idleSpots.map((s, i) => [s, i]).filter(([, i]) => !taken.has(i));
  if (!free.length) return;
  const [s, idx] = free[Math.floor(Math.random() * free.length)];
  taken.set(idx, c.id);
  c.wander = { spot: { x: s.x, y: s.y, dir: s.dir, sit: s.sit }, idx, until: now + 15000 + Math.random() * 30000 };
  decide(c);
}

function goTo(c, dest) {
  c.dest = { ...dest };
  const path = findPath(c.tx, c.ty, dest.x, dest.y);
  if (path === null) { place(c, dest.x, dest.y, dest.dir, dest.sit); return; }   // unreachable: teleport
  c.path = path; c.sit = false; c.seatOff = 0;
  if (!path.length) arrive(c);
}

function arrive(c) {
  c.sit = !!c.dest.sit; c.dir = c.dest.dir || c.dir;
  c.seatOff = c.sit ? (c.dir === 'down' ? 5 : c.dir === 'up' ? 1 : 0) : 0;
  c.frame = 0;
  if (c.kind !== 'you') decide(c);
}

function step(c, dt) {
  if (c.kind === 'you' && keys.size) return moveYouByKeys(dt);
  if (!c.path.length) return;
  const n = c.path[0], gx = n.x * T + 8, gy = n.y * T + 14;
  const dx = gx - c.x, dy = gy - c.y, dist = Math.hypot(dx, dy), mv = SPEED * dt;
  if (Math.abs(dx) > Math.abs(dy)) c.dir = dx > 0 ? 'right' : 'left'; else if (dy) c.dir = dy > 0 ? 'down' : 'up';
  if (dist <= mv) { c.x = gx; c.y = gy; c.tx = n.x; c.ty = n.y; c.path.shift(); if (!c.path.length) arrive(c); }
  else { c.x += dx / dist * mv; c.y += dy / dist * mv; }
  c.walkT += dt; c.frame = c.path.length ? 1 + (Math.floor(c.walkT * 8) % 2) : 0;
}

function moveYouByKeys(dt) {
  const c = you; let dx = 0, dy = 0;
  if (keys.has('arrowleft') || keys.has('a')) dx -= 1;
  if (keys.has('arrowright') || keys.has('d')) dx += 1;
  if (keys.has('arrowup') || keys.has('w')) dy -= 1;
  if (keys.has('arrowdown') || keys.has('s')) dy += 1;
  if (!dx && !dy) return;
  c.path = []; c.sit = false; c.seatOff = 0;
  const len = Math.hypot(dx, dy), mv = SPEED * 1.25 * dt;
  const nx = c.x + dx / len * mv, ny = c.y + dy / len * mv;
  const ok = (x, y) => isWalkable(Math.floor(x / T), Math.floor((y - 2) / T));
  if (ok(nx, c.y)) c.x = nx;
  if (ok(c.x, ny)) c.y = ny;
  c.tx = Math.floor(c.x / T); c.ty = Math.floor((c.y - 2) / T);
  c.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
  c.walkT += dt; c.frame = 1 + (Math.floor(c.walkT * 8) % 2);
  c.dest = { x: c.tx, y: c.ty, dir: c.dir };
}

export function nearestAgent(maxTiles = 1.9) {
  let best = null, bd = maxTiles * T;
  for (const c of chars.values()) {
    if (c.kind === 'you') continue;
    const d = Math.hypot(c.x - you.x, c.y - you.y);
    if (d < bd) { bd = d; best = c; }
  }
  return best;
}

// ------------------------------------------------------------------ camera
function resize() {
  const r = cv.parentElement.getBoundingClientRect();
  dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
  cv.style.width = r.width + 'px'; cv.style.height = r.height + 'px';
  layout();
}
function layout() {
  const w = cv.clientWidth, h = cv.clientHeight;
  fitScale = Math.min(w / (W * T), h / (H * T));
  scale = fitScale * zoom;
  offX = (w - W * T * scale) / 2; offY = (h - H * T * scale) / 2;
}
function zoomAt(sx, sy, f) {
  const wx = (sx - offX) / scale, wy = (sy - offY) / scale;
  zoom = Math.max(1, Math.min(4, zoom * f));
  scale = fitScale * zoom;
  offX = sx - wx * scale; offY = sy - wy * scale;
  clampPan();
}
function clampPan() {
  const w = cv.clientWidth, h = cv.clientHeight, mw = W * T * scale, mh = H * T * scale;
  offX = mw <= w ? (w - mw) / 2 : Math.min(0, Math.max(w - mw, offX));
  offY = mh <= h ? (h - mh) / 2 : Math.min(0, Math.max(h - mh, offY));
}
const toWorld = (sx, sy) => ({ x: (sx - offX) / scale, y: (sy - offY) / scale });

// ------------------------------------------------------------------ input
function hit(sx, sy) {
  const { x, y } = toWorld(sx, sy);
  let best = null;
  for (const c of chars.values()) {
    const top = c.y + c.seatOff - 22, left = c.x - 8;
    if (x >= left - 2 && x <= left + 18 && y >= top - 4 && y <= c.y + c.seatOff + 2) if (!best || c.y > best.y) best = c;
  }
  return best;
}

function bindInput() {
  let down = null, panned = false;
  cv.addEventListener('mousedown', e => { down = { x: e.offsetX, y: e.offsetY, ox: offX, oy: offY }; panned = false; });
  window.addEventListener('mouseup', () => { down = null; });
  cv.addEventListener('mousemove', e => {
    if (down && (Math.abs(e.offsetX - down.x) + Math.abs(e.offsetY - down.y) > 6) && zoom > 1) {
      panned = true; offX = down.ox + e.offsetX - down.x; offY = down.oy + e.offsetY - down.y; clampPan();
    }
    const c = hit(e.offsetX, e.offsetY);
    hoverId = c ? c.id : null;
    cv.style.cursor = c ? 'pointer' : (zoom > 1 && down ? 'grabbing' : 'default');
    hooks.onHover?.(c ? c.id : null, e.offsetX, e.offsetY);
  });
  cv.addEventListener('mouseleave', () => { hoverId = null; hooks.onHover?.(null); });
  cv.addEventListener('click', e => {
    if (panned) return;
    const c = hit(e.offsetX, e.offsetY);
    if (c && c.kind !== 'you') { hooks.onSelect?.(c.id); return; }
    const { x, y } = toWorld(e.offsetX, e.offsetY);
    let tx = Math.floor(x / T), ty = Math.floor(y / T);
    if (!isWalkable(tx, ty)) {
      const n = [[0, 1], [1, 0], [-1, 0], [0, -1], [1, 1], [-1, 1]].map(([a, b]) => [tx + a, ty + b]).find(([a, b]) => isWalkable(a, b));
      if (!n) return; [tx, ty] = n;
    }
    goTo(you, { x: tx, y: ty, dir: 'down', sit: false });
  });
  cv.addEventListener('wheel', e => { e.preventDefault(); zoomAt(e.offsetX, e.offsetY, e.deltaY < 0 ? 1.12 : 0.89); }, { passive: false });
  window.addEventListener('keydown', e => {
    if (e.target.closest('input, textarea, select, [contenteditable]')) return;
    const k = e.key.toLowerCase();
    if (['arrowleft', 'arrowright', 'arrowup', 'arrowdown', 'w', 'a', 's', 'd'].includes(k)) { keys.add(k); e.preventDefault(); }
    if (k === 'e' || k === 'enter') { const n = nearestAgent(); if (n) { hooks.onTalk?.(n.id); e.preventDefault(); } }
  });
  window.addEventListener('keyup', e => keys.delete(e.key.toLowerCase()));
  window.addEventListener('blur', () => keys.clear());
}

// ------------------------------------------------------------------ render
let last = performance.now();
function loop(now) {
  const dt = Math.min(0.05, (now - last) / 1000); last = now;
  for (const c of chars.values()) { maybeWander(c, now); step(c, dt); if (c.wander && now > c.wander.until) decide(c); }
  for (const d of Object.values(desks)) if (!d.owner) d.state = 'off';
  draw(now);
  hooks.onFrame?.(nearestAgent());
  requestAnimationFrame(loop);
}

function draw(now) {
  const w = cv.width, h = cv.height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = '#2a2e45'; ctx.fillRect(0, 0, w, h);
  ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * offX, dpr * offY);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(floorLayer, 0, 0);

  // selection ring under the selected character
  const sel = chars.get(selectedId);
  if (sel) {
    ctx.fillStyle = 'rgba(88,101,242,0.35)';
    ctx.beginPath(); ctx.ellipse(sel.x, sel.y + sel.seatOff + 1, 9, 4, 0, 0, Math.PI * 2); ctx.fill();
  }

  const items = objects.map(o => ({ o, k: o.sortY }));
  for (const c of chars.values()) items.push({ c, k: c.y + c.seatOff });
  items.sort((a, b) => a.k - b.k);
  for (const it of items) {
    if (it.o) { ctx.drawImage(it.o.img, it.o.x, it.o.y); it.o.anim?.(ctx, now); }
    else {
      const c = it.c;
      const img = sprite(c.look, c.dir, c.frame, c.sit, c.kind === 'claude');
      const bob = c.speaking ? (Math.floor(now / 160) % 2) : 0;
      ctx.drawImage(img, Math.round(c.x - 8), Math.round(c.y + c.seatOff - 21 - bob));
    }
  }

  // ---- screen-space overlays (crisp text)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const S = (x, y) => [offX + x * scale, offY + y * scale];
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const lf = Math.max(10, Math.min(13, 5.2 * scale));
  ctx.font = `600 ${lf}px system-ui, -apple-system, Segoe UI, sans-serif`;
  for (const l of labels) {
    const [x, y] = S(l.x * T, l.y * T + 4);
    const tw = ctx.measureText(l.text).width + 16;
    ctx.fillStyle = 'rgba(255,255,255,0.78)'; pill(x - tw / 2, y - lf * 0.8, tw, lf * 1.6, lf * 0.8); ctx.fill();
    ctx.fillStyle = '#5b6079'; ctx.fillText(l.text, x, y + 0.5);
  }

  const nf = Math.max(10, Math.min(13, 4.6 * scale));
  const sorted = [...chars.values()].sort((a, b) => a.y - b.y);
  for (const c of sorted) {
    const [x, y] = S(c.x, c.y + c.seatOff - 25);
    // name tag
    ctx.font = `600 ${nf}px system-ui, -apple-system, Segoe UI, sans-serif`;
    const label = c.kind === 'you' ? 'You' : c.name;
    const tw = ctx.measureText(label).width + nf * 1.9;
    const th = nf * 1.65;
    ctx.fillStyle = c.id === hoverId || c.id === selectedId ? 'rgba(48,56,140,0.92)' : 'rgba(22,24,38,0.78)';
    pill(x - tw / 2, y - th / 2, tw, th, th / 2); ctx.fill();
    const st = c.inMeeting ? 'meeting' : c.status;
    ctx.fillStyle = STATUS_COL[st] || STATUS_COL.idle;
    ctx.beginPath(); ctx.arc(x - tw / 2 + nf * 0.8, y, nf * 0.3, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.fillText(label, x - tw / 2 + nf * 1.35, y + 0.5); ctx.textAlign = 'center';

    // speech bubble, or a small activity bubble
    if (c.bubble && (now < c.bubble.until || c.speaking)) speech(x, y - th / 2 - 4, c.bubble.text, nf);
    else if (c.kind !== 'you' && (c.status === 'working' || c.busy || c.status === 'quota')) {
      const icon = c.status === 'quota' ? 'z' : c.busy && c.status !== 'working' ? '•••' : (ICON[c.actKind] || '…');
      const bx = x + tw / 2 + 2, by = y - th * 0.9;
      const dots = icon === '•••' || icon === '…';
      const txt = dots ? '•••'.slice(0, 1 + Math.floor(now / 350) % 3).padEnd(3, ' ') : icon;
      ctx.font = `${nf}px system-ui, sans-serif`;
      const bw = Math.max(th * 1.25, ctx.measureText(txt).width + 10);
      ctx.fillStyle = '#ffffff'; pill(bx - 2, by - th / 2, bw, th, th / 2); ctx.fill();
      ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.moveTo(bx + 1, by + th / 2 - 2); ctx.lineTo(bx - 4, by + th / 2 + 3); ctx.lineTo(bx + 6, by + th / 2 - 1); ctx.fill();
      ctx.fillStyle = '#3a3f5a'; ctx.fillText(txt, bx - 2 + bw / 2, by + 0.5);
    }
  }
}

function pill(x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function speech(x, bottom, text, nf) {
  const f = Math.max(11, nf); ctx.font = `${f}px system-ui, -apple-system, Segoe UI, sans-serif`;
  const maxW = Math.max(160, f * 16), lines = [];
  let line = '';
  for (const word of text.split(' ')) {
    const t = line ? line + ' ' + word : word;
    if (ctx.measureText(t).width > maxW && line) { lines.push(line); line = word; if (lines.length === 3) break; } else line = t;
  }
  if (lines.length < 3 && line) lines.push(line);
  if (lines.length === 3 && text.length > lines.join(' ').length + 1) lines[2] = lines[2].replace(/\s*\S*$/, '') + ' …';
  const lh = f * 1.3, bw = Math.max(...lines.map(l => ctx.measureText(l).width)) + 18, bh = lines.length * lh + 12;
  const bx = x - bw / 2, by = bottom - bh - 6;
  ctx.shadowColor = 'rgba(0,0,0,.25)'; ctx.shadowBlur = 6;
  ctx.fillStyle = '#fff'; pill(bx, by, bw, bh, 10); ctx.fill(); ctx.shadowBlur = 0;
  ctx.beginPath(); ctx.moveTo(x - 6, by + bh - 1); ctx.lineTo(x, by + bh + 6); ctx.lineTo(x + 6, by + bh - 1); ctx.fill();
  ctx.fillStyle = '#22253a'; ctx.textAlign = 'left';
  lines.forEach((l, i) => ctx.fillText(l, bx + 9, by + 6 + lh * (i + 0.5)));
  ctx.textAlign = 'center';
}
