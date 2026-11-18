/* The Kinect app's runtime: the live connection, the router, smooth bodies, sound, the hand
   cursor, keyboard navigation, toasts, sheets and settings. Every section (home.js, fitness.js,
   games.js, camera.js, room.js, scan.js, history.js) registers with K.section().

   Drawing and deciding are kept apart: bodies are drawn between the last two real observations
   (interpolated, never extrapolated: what is on screen is always something the camera saw a
   moment ago), while every count and score comes from the server, decided on fresh frames. */
"use strict";

const K = (() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = getComputedStyle(document.documentElement);
  const colour = (name) => css.getPropertyValue(`--${name}`).trim();
  const playerColour = (slot) => colour(`p${((slot ?? 5) % 6) + 1}`);
  const playerRGBA = (slot, a = 1) => GL3.rgba(`p${((slot ?? 5) % 6) + 1}`, a);
  const local = {
    get(k, d) { try { const v = localStorage.getItem(`kinect.${k}`); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(`kinect.${k}`, JSON.stringify(v)); } catch (e) { /* private window */ } },
  };

  // -- the live state ------------------------------------------------------------------------
  const listeners = {};
  const on = (name, fn) => { (listeners[name] = listeners[name] || []).push(fn); return () => { listeners[name] = listeners[name].filter((f) => f !== fn); }; };
  const emit = (name, ...args) => (listeners[name] || []).forEach((fn) => { try { fn(...args); } catch (e) { console.error(e); } });
  const live = { state: { people: [], players: [], workout: { mode: "idle" } }, connected: false, everConnected: false, offset: null, rate: 15 };
  const tracks = {};       // person id -> {a, b}: the last two observations {t, joints, skeleton}

  function connect() {
    let ws, retry = 400;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { retry = 400; live.connected = live.everConnected = true; emit("connection", true); };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        const arrived = performance.now() / 1000;
        const st = msg.state;
        if (st.t) {
          const off = arrived - st.t;              // the smallest is the best clock offset
          live.offset = live.offset === null ? off : Math.min(live.offset + 0.002, off);
        }
        if (st.hub && st.latency && st.tracking) live.rate = Math.max(5, Math.min(30, live.rate));
        observe(st);
        live.state = st;
        emit("state", st);
        for (const e of msg.events || []) emit("event", e);
      };
      ws.onclose = () => { live.connected = false; emit("connection", false); setTimeout(open, retry); retry = Math.min(retry * 2, 4000); };
    };
    open();
  }
  const serverNow = () => performance.now() / 1000 - (live.offset || 0);

  function observe(st) {
    const t = st.t || serverNow();
    const seen = new Set();
    for (const p of st.people || []) {
      if (!p.joints) continue;
      seen.add(p.id);
      const tr = tracks[p.id] || (tracks[p.id] = { a: null, b: null });
      if (tr.b && tr.b.frame === st.tracking?.frame) continue;
      tr.a = tr.b; tr.b = { t, joints: p.joints, skeleton: p.skeleton, frame: st.tracking?.frame };
    }
    for (const id of Object.keys(tracks)) if (!seen.has(+id)) delete tracks[id];   // gone: never drawn from memory
    if (st.tracking && st.tracking.frame) {
      const now = performance.now();
      live._frames = (live._frames || []).filter((x) => now - x < 2000); live._frames.push(now);
      live.rate = live._frames.length / 2;
    }
  }

  // People as they should be drawn now: each joint between its last two observations.
  function people(delay) {
    const d = delay ?? Math.min(0.12, 1.1 / Math.max(5, live.rate));
    const at = serverNow() - d;
    return (live.state.people || []).map((p) => {
      const tr = tracks[p.id];
      if (!tr || !tr.b || !tr.a || !p.joints) return p;
      const span = tr.b.t - tr.a.t;
      const k = span > 0 ? Math.max(0, Math.min(1, (at - tr.a.t) / span)) : 1;
      const joints = tr.b.joints.map((jb, i) => {
        const ja = tr.a.joints[i];
        if (!jb) return null;
        if (!ja) return jb;
        return [ja[0] + (jb[0] - ja[0]) * k, ja[1] + (jb[1] - ja[1]) * k, ja[2] + (jb[2] - ja[2]) * k, jb[3]];
      });
      return { ...p, joints };
    });
  }

  async function api(path, body, method) {
    const opts = body === undefined && !method ? {} : {
      method: method || "POST", headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body) };
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    const type = r.headers.get("Content-Type") || "";
    return type.includes("json") ? r.json() : r;
  }
  const hub = (name, value) => api(`/hub/api/${name}`, { value });

  // -- shared lookups ------------------------------------------------------------------------
  const cache = {};
  async function catalog() { return cache.catalog || (cache.catalog = await api("/api/catalog")); }
  async function users(fresh) { if (fresh || !cache.users) cache.users = await api("/api/users"); return cache.users; }
  async function demo(key, height) {
    const k = `${key}|${height || ""}`;
    return cache[k] || (cache[k] = api(`/api/demo/${key}${height ? `?height=${height}` : ""}`).catch(() => null));
  }
  function fit(key) {
    const sp = live.state.space;
    if (!sp) return null;
    return (sp.activities || []).find((a) => a.activity === key) || null;
  }

  // -- the router ----------------------------------------------------------------------------
  const sections = {};
  const ORDER = ["home", "fitness", "games", "camera", "room", "scan", "history"];
  let current = null, currentName = null;
  const section = (name, def) => { sections[name] = def; };
  function route() {
    const [name, ...rest] = (location.hash.replace(/^#\/?/, "") || "home").split("/");
    const want = sections[name] ? name : "home";
    for (const a of document.querySelectorAll(".tabs a")) a.classList.toggle("on", a.dataset.s === want);
    if (want !== currentName) {
      if (current && current.unmount) current.unmount();
      const el = $("#view");
      el.innerHTML = "";
      const host = document.createElement("div");
      host.className = "section";
      el.appendChild(host);
      current = sections[want]; currentName = want;
      document.title = want === "home" ? "Kinect" : `Kinect · ${current.title || want}`;
      current.mount(host, rest);
    } else if (current.route) current.route(rest);
    emit("route", want, rest);
  }
  const go = (path) => { location.hash = `#/${path}`; };

  // -- sound: synthesized, short, quiet -------------------------------------------------------
  let audio = null;
  function sound(kind) {
    if (!local.get("sound", true)) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const notes = { tick: [[660, 0.06]], go: [[880, 0.12], [1320, 0.18]], rep: [[740, 0.07]], pass: [[784, 0.08], [1175, 0.14]],
        hit: [[180, 0.22, "sawtooth"]], coin: [[1318, 0.06], [1760, 0.09]], bump: [[120, 0.2, "square"]], match: [[523, 0.08], [784, 0.08], [1046, 0.16]],
        done: [[523, 0.12], [659, 0.12], [784, 0.24]], select: [[990, 0.05]], lost: [[330, 0.18, "triangle"]], back: [[520, 0.12, "triangle"]] }[kind];
      if (!notes) return;
      let t = audio.currentTime;
      for (const [f, d, type] of notes) {
        const o = audio.createOscillator(), g = audio.createGain();
        o.type = type || "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.12, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + d);
        o.connect(g).connect(audio.destination); o.start(t); o.stop(t + d + 0.02);
        t += d * 0.8;
      }
    } catch (e) { /* no audio device */ }
  }

  // -- toasts, modals, sheets ----------------------------------------------------------------
  function toast(text, kind, ms = 2600) {
    const box = $("#toasts"), el = document.createElement("div");
    el.className = `toast ${kind || ""}`; el.textContent = text;
    box.appendChild(el);
    while (box.children.length > 3) box.firstChild.remove();
    setTimeout(() => el.remove(), ms);
  }
  function modal(html, onClose) {
    const m = document.createElement("div");
    m.className = "modal"; m.innerHTML = `<div class="card">${html}</div>`;
    const close = () => { m.remove(); if (onClose) onClose(); };
    m.addEventListener("click", (e) => { if (e.target === m || e.target.closest("[data-close]")) close(); });
    document.body.appendChild(m);
    const first = m.querySelector("button.primary, button");
    if (first) first.focus();
    return { el: m, close };
  }
  let sheetEl = null;
  function sheet(html) {
    closeSheet();
    sheetEl = document.createElement("aside");
    sheetEl.className = "sheet"; sheetEl.innerHTML = html;
    sheetEl.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closeSheet(); });
    document.body.appendChild(sheetEl);
    return sheetEl;
  }
  function closeSheet() { if (sheetEl) { sheetEl.remove(); sheetEl = null; } }

  // -- the bar: connection, players, settings ------------------------------------------------
  function bar() {
    const st = live.state, hubst = st.hub || {}, pill = $("#status"), mark = $("#mark");
    const err = st.hub_error;
    let cls = "live", text;
    if (!live.connected) { cls = "bad"; text = live.everConnected ? "Reconnecting…" : "Connecting…"; }
    else if (err) { cls = "bad"; text = err.length > 60 ? `${err.slice(0, 57)}…` : err; }
    else if (st.fresh === false) { cls = "warn"; text = "Waiting for the Kinect…"; }
    else {
      const src = hubst.source === "demo" ? "Demo" : hubst.mode === "ir" ? "Infrared" : "Colour";
      const t = st.tracking || {};
      text = `${src} · ${t.visible ?? (st.people || []).length} in view${t.hidden ? ` · ${t.hidden} hidden` : ""}${st.latency ? ` · ${st.latency.p50} ms` : ""}`;
    }
    pill.className = `pill ${cls}`;
    pill.innerHTML = `<span class="dot"></span>${esc(text)}`;
    pill.title = st.latency ? `Camera to screen: median ${st.latency.p50} ms, 95% under ${st.latency.p95} ms. ${Math.round(live.rate)} updates a second.` : "";
    mark.className = `mark ${cls === "live" ? "" : cls === "bad" ? "off" : "warn"}`;
    $("#chips").innerHTML = (st.players || []).map((p) => `<span class="chip ${p.lost ? "lost" : ""}" title="${esc(statusWords(p))}">
      <i style="background:${playerColour(p.slot)}"></i>P${p.slot + 1}${p.lost ? " · lost" : ""}</span>`).join("");
    // Reconnecting / hub problems: one overlay above everything, with what to do.
    const ov = $("#overlay");
    const problem = !live.connected ? { b: live.everConnected ? "Reconnecting to Kinect Motion…" : "Starting Kinect Motion…",
      p: "The service starts by itself; this takes a few seconds.", spin: true } : null;
    ov.hidden = !problem;
    if (problem) ov.innerHTML = `<div class="card">${problem.spin ? '<div class="spinner"></div>' : ""}<b>${esc(problem.b)}</b><p class="soft">${esc(problem.p)}</p></div>`;
  }
  function statusWords(p) {
    return { active: "Seen now", unsure: "Crossing someone: not counting until I'm sure who is who",
      hidden: "Hidden behind someone", away: "Out of view", rejoin: "Raise a hand to rejoin" }[p.status] || p.status;
  }

  // -- the hand cursor (Kinect's hover-to-select) -------------------------------------------
  const hand = { on: false, x: 0.5, y: 0.5, el: null, target: null, since: 0, cool: 0, ring: null };
  function handCursor() {
    const enabled = local.get("hand", true);
    const st = live.state, w = st.workout || {}, busy = (w.mode && w.mode !== "idle") || (st.game && !st.game.over);
    let found = null;
    if (enabled && !busy && live.connected) {
      const ps = people(0.05);
      const order = [...ps].sort((a, b) => (a.slot ?? 9) - (b.slot ?? 9));
      for (const p of order) {
        const J = p.joints; if (!J) continue;
        for (const [wr, sh, hp, side] of [[16, 12, 24, 1], [15, 11, 23, -1]]) {
          const W = J[wr], S = J[sh], H = J[hp];
          if (!W || !S || !H || W[3] !== 2) continue;
          const forward = S[2] - W[2];
          if (forward < 0.22 || W[1] < H[1] + 0.05) continue;
          // Mirror: their right hand moves the cursor right. Room x grows to the picture's right
          // (their left), so screen x follows -x.
          const dx = -(W[0] - S[0]) * side, dy = S[1] + 0.12 - W[1];
          found = { x: Math.max(0, Math.min(1, side > 0 ? (dx + 0.12) / 0.55 : 1 - (0.43 - dx) / 0.55)),
            y: Math.max(0, Math.min(1, dy / 0.5)) };
          break;
        }
        if (found) break;
      }
    }
    if (!hand.el) { hand.el = $("#hand"); hand.ring = hand.el.querySelector("circle"); }
    if (!found) { if (hand.on) { hand.on = false; hand.el.hidden = true; setHot(null); } return; }
    if (!hand.on) { hand.on = true; hand.el.hidden = false; hand.x = found.x; hand.y = found.y; }
    hand.x += (found.x - hand.x) * 0.35; hand.y += (found.y - hand.y) * 0.35;
    const px = hand.x * innerWidth, py = hand.y * innerHeight;
    hand.el.style.left = `${px}px`; hand.el.style.top = `${py}px`;
    hand.el.style.visibility = "hidden";
    const under = document.elementFromPoint(px, py);
    hand.el.style.visibility = "";
    const t = under && under.closest(".tile, .btn, .tabs a, .subtabs button, .seg button, .person, [data-dwell]");
    const now = performance.now();
    if (t !== hand.target) { hand.target = t; hand.since = now; setHot(t); }
    const k = t && now > hand.cool ? Math.min(1, (now - hand.since) / 1300) : 0;
    hand.ring.style.strokeDashoffset = String(207 * (1 - k));
    if (k >= 1) { hand.cool = now + 1200; hand.since = now + 1200; sound("select"); t.click(); }
  }
  function setHot(el) { for (const x of document.querySelectorAll(".hot")) x.classList.remove("hot"); if (el) el.classList.add("hot"); }

  // -- keyboard ------------------------------------------------------------------------------
  function focusables() {
    return [...document.querySelectorAll("#view .tile, #view .btn, #view .subtabs button, #view .seg button, #view .person, .tabs a")]
      .filter((e) => e.offsetParent !== null && !e.disabled);
  }
  function move(dir) {
    const list = focusables();
    const cur = document.activeElement && list.includes(document.activeElement) ? document.activeElement : null;
    if (!cur) { const first = list.find((e) => e.closest("#view")) || list[0]; if (first) first.focus(); return; }
    const a = cur.getBoundingClientRect(), ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, bd = Infinity;
    for (const e of list) {
      if (e === cur) continue;
      const b = e.getBoundingClientRect(), bx = b.left + b.width / 2, by = b.top + b.height / 2;
      const dx = bx - ax, dy = by - ay;
      const ok = { left: dx < -4, right: dx > 4, up: dy < -4, down: dy > 4 }[dir];
      if (!ok) continue;
      const along = dir === "left" || dir === "right" ? Math.abs(dx) : Math.abs(dy);
      const across = dir === "left" || dir === "right" ? Math.abs(dy) : Math.abs(dx);
      const d = along + across * 2.2;
      if (d < bd) { bd = d; best = e; }
    }
    if (best) { best.focus(); best.scrollIntoView({ block: "nearest" }); }
  }
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) return;
    const arrows = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
    if (arrows[e.key]) { e.preventDefault(); move(arrows[e.key]); return; }
    if (e.key === "Escape") {
      if (document.querySelector(".modal")) { document.querySelector(".modal").remove(); return; }
      if (sheetEl) { closeSheet(); return; }
      if (current && current.back && current.back()) return;
      if (currentName !== "home") go("home");
      return;
    }
    if (/^[1-7]$/.test(e.key) && !e.ctrlKey && !e.altKey) { go(ORDER[+e.key - 1]); return; }
    if (current && current.key) current.key(e);
  });

  // -- settings and calibration --------------------------------------------------------------
  async function settings() {
    const cfg = await api("/api/settings").catch(() => ({}));
    const sp = live.state.space;
    const el = sheet(`<div class="row"><h1>Settings</h1><span class="spacer"></span><button class="btn small" data-close>Close</button></div>
      <div class="card"><h2>Coaching</h2>
        <label class="switch"><input type="checkbox" id="set-voice" ${live.state.voice ? "checked" : ""}>Voice: cues spoken aloud</label>
        <div class="row"><label class="switch"><input type="checkbox" id="set-sound" ${local.get("sound", true) ? "checked" : ""}>Sounds</label></div>
        <div class="row"><label class="switch"><input type="checkbox" id="set-hand" ${local.get("hand", true) ? "checked" : ""}>Hand cursor: hold a hand out to point, hover to choose</label></div>
      </div>
      <div class="card"><h2>Your space</h2>
        <div class="row"><label class="field">Floor in front of the Kinect <input type="number" id="set-space" min="1" max="6" step="0.1" value="${cfg.space_m ?? ""}" placeholder="none"> m</label></div>
        <p class="note">How far from the Kinect you can stand. With a number, only places within it count; empty uses the room's own end (${sp && sp.room_end ? `${sp.room_end} m here` : "measured from depth"}).</p>
        <div class="row" style="margin-top:12px"><label class="switch"><input type="checkbox" id="set-room" ${cfg.room_always ? "checked" : ""}>Keep watching the room with the app closed</label></div>
      </div>
      <div class="card" id="cal">${calibrationHTML(sp)}</div>`);
    el.querySelector("#set-voice").onchange = (e) => api("/api/settings", { voice: e.target.checked });
    el.querySelector("#set-sound").onchange = (e) => local.set("sound", e.target.checked);
    el.querySelector("#set-hand").onchange = (e) => local.set("hand", e.target.checked);
    el.querySelector("#set-space").onchange = (e) => api("/api/settings", { space_m: e.target.value ? +e.target.value : null }).then(() => toast("Saved: the activities are being re-checked"));
    el.querySelector("#set-room").onchange = (e) => api("/api/settings", { room_always: e.target.checked });
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("[data-tilt-by]");
      if (!t) return;
      t.disabled = true;
      try { const r = await api("/api/calibration", { tilt_by: +t.dataset.tiltBy }); toast(`Tilting the Kinect to ${r.tilt}°`); }
      catch (err) { toast(`Could not tilt: ${err.message}`, "warn"); }
      setTimeout(() => { t.disabled = false; const c = el.querySelector("#cal"); if (c) c.innerHTML = calibrationHTML(live.state.space); }, 3500);
    });
  }
  function activityName(key) {
    const ex = cache.catalog && cache.catalog.exercises.find((e) => e.key === key);
    return ex ? ex.name : { walls: "Wall Dodge", pose: "Pose Match", race: "Body Racer" }[key] || key;
  }
  function calibrationHTML(sp) {
    if (!sp) return `<h2>Where things fit</h2><p class="soft">The Kinect has not seen the floor yet. Clear the floor in front of it, or tilt it down a little.</p>`;
    const n = sp.activities.filter((a) => a.fits).length;
    const hint = sp.tilt_hint;
    const better = hint && hint.by && hint.fits.length > hint.now.length;
    return `<h2>Where things fit</h2>
      <p class="soft">The Kinect is <b>${sp.camera_height} m</b> up, pointing ${sp.tilt >= 0 ? `${sp.tilt}° down` : `${-sp.tilt}° up`}.
      Usable floor: <b>${sp.usable[0]}–${sp.usable[1]} m</b> from it${sp.limit ? ` (your ${sp.limit} m)` : ""}. ${n} of ${sp.activities.length} activities fit, for someone ${Math.round(sp.height * 100)} cm tall.</p>
      ${better ? `<div class="item" style="margin-top:12px"><b>Tilt it ${hint.by > 0 ? "up" : "down"} ${Math.abs(hint.by)}°</b> and ${hint.fits.length} of ${sp.activities.length} fit
        (${hint.fits.filter((k) => !hint.now.includes(k)).map(activityName).join(", ")} too${hint.now.filter((k) => !hint.fits.includes(k)).length ? `, but not ${hint.now.filter((k) => !hint.fits.includes(k)).map(activityName).join(", ")}` : ""}).
        <div class="row" style="margin-top:8px"><button class="btn small primary" data-tilt-by="${hint.by}">Tilt ${hint.by > 0 ? "up" : "down"} ${Math.abs(hint.by)}°</button></div></div>` : ""}
      <h3>What the picture covers</h3>
      <table class="grid"><tr><th>From the Kinect</th><th>Heights</th><th>Width</th></tr>
        ${sp.view.map((v) => `<tr><td>${v.z} m</td><td>${v.bottom ?? "–"} to ${v.top ?? "–"} m</td><td>${v.width ?? "–"} m</td></tr>`).join("")}</table>
      <h3>Activities</h3>
      ${sp.activities.map((a) => `<div class="fit-row"><b>${esc(activityName(a.activity))}</b>
        <span class="badge ${a.fits ? "ok" : "no"}">${a.fits ? `${a.band[0]}–${a.band[1]} m` : "Doesn't fit"}</span>
        ${a.why ? `<p>${esc(a.why)}</p>` : ""}</div>`).join("")}`;
  }

  // -- start -----------------------------------------------------------------------------------
  function start() {
    $("#settings").onclick = settings;
    $("#full").onclick = () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => {}); };
    window.addEventListener("hashchange", route);
    on("connection", bar);
    connect();
    catalog().catch(() => {});
    setInterval(bar, 300);
    const loop = () => { handCursor(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    route();
    // Render-rate figures for the checks (and the curious): window.__kinect.
    window.__kinect = { live, serverNow, rate: () => live.rate };
  }

  return { $, esc, colour, playerColour, playerRGBA, local, on, emit, live, people, serverNow, api, hub, catalog, users, demo,
    fit, section, go, sound, toast, modal, sheet, closeSheet, settings, calibrationHTML, activityName, statusWords, start, ORDER };
})();
