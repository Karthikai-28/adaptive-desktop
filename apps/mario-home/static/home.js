// Mario Home (live tiles) and the Mario panel: one page, two layouts (/ and /panel).
// Everything shown comes from Mario Hub over a WebSocket. A tile with more than one face turns
// on its own clock (flip for small tiles, peek-slide for wide ones), pauses while the pointer is
// on it, and keeps its face when new data arrives.
"use strict";

const PANEL = location.pathname === "/panel";
const state = { cards: {}, next: [], presence: { state: "ready" }, config: {} };
const cpuHistory = [];
const COLORS = ["#5E5CE6", "#64D2FF", "#30D158", "#FF9F0A", "#BF5AF2", "#FF6482"];

// ---------------------------------------------------------------- helpers
function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
  return node;
}
const svgEl = (tag, attrs) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};
const data = (name) => (state.cards[name] || {}).data || {};
const $ = (sel) => document.querySelector(sel);
const muted = (text, style) => el("span", { class: "muted", style }, text);

function ago(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return "today";
  if (now - d < 2 * 86400000) return "yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function shortTitle(text, max = 70) {
  const s = String(text || "").replace(/\s+/g, " ").trim();
  const cut = s.split(/(?<=[.!?])\s|\s[—–-]\s|\(Why/)[0];
  return (cut.length > max ? cut.slice(0, max - 1) + "…" : cut) || s.slice(0, max);
}
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  return Math.ceil(((t - Date.UTC(t.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
}
const fmtRate = (b) => (b == null ? "–" : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB/s` : `${Math.round(b / 1e3)} KB/s`);
const pct = (v) => (v == null ? "–" : `${Math.round(v)}%`);

async function post(url, payload) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  return res.json();
}
const act = (action) => post("/api/action", action);
const openUrl = (url) => url && act({ id: "url", arg: url });

// ------------------------------------------------------------- live tiles
const tiles = {};

function setupTiles() {
  document.querySelectorAll(".tile").forEach((node, idx) => {
    if (node.dataset.launch) {  // 1x1 launchers: a button, a name, a live badge; no faces
      node.querySelector(".launch").addEventListener("click", () => launch(node.dataset.launch));
      return;
    }
    const t = { name: node.dataset.tile, el: node, stage: node.querySelector(".stage"), faces: [], i: 0, hover: false, open: null };
    t.dots = el("span", { class: "dots", "aria-hidden": "true" });
    node.append(t.dots);
    node.addEventListener("mouseenter", () => { t.hover = true; });
    node.addEventListener("mouseleave", () => { t.hover = false; });
    node.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      const face = t.faces[t.i] || {};
      if (face.open) face.open(); else if (t.open) t.open();
    });
    tiles[t.name] = t;
    // each tile keeps its own beat so they never turn together
    const every = 6500 + ((idx * 1700) % 6000) + Math.random() * 1500;
    setTimeout(() => setInterval(() => turn(t), every), (idx * 830) % 5000);
  });
}

function setFaces(name, faces, opts = {}) {
  const t = tiles[name];
  if (!t) return;
  t.faces = faces.filter(Boolean).map((f) => (Array.isArray(f) || f instanceof Node ? { n: f } : f));
  if (t.i >= t.faces.length) t.i = 0;
  t.open = opts.open || null;
  t.el.classList.toggle("clickable", Boolean(t.open || t.faces.some((f) => f.open)));
  if (opts.badge !== undefined) { const b = t.el.querySelector(".badge"); if (b) b.textContent = opts.badge || ""; }
  draw(t);
}

function draw(t) {
  const face = t.faces[t.i] || { n: [] };
  t.stage.replaceChildren(...[].concat(face.n));
  t.dots.replaceChildren(...(t.faces.length > 1 ? t.faces.map((_, k) => el("i", { class: k === t.i ? "on" : "" })) : []));
}

function turn(t) {
  if (t.faces.length < 2 || t.hover || document.hidden || t.busy) return;
  const anim = t.el.dataset.anim || "slide";
  if (anim === "none" || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    t.i = (t.i + 1) % t.faces.length; draw(t); return;
  }
  t.busy = true;
  t.stage.classList.add(`${anim}-out`);
  setTimeout(() => {
    t.i = (t.i + 1) % t.faces.length;
    draw(t);
    t.stage.classList.remove(`${anim}-out`);
    t.stage.classList.add(`${anim}-in`);
    void t.stage.offsetWidth;  // apply the start position before animating back in
    t.stage.classList.remove(`${anim}-in`);
    t.busy = false;
  }, 420);
}

function summaryStrip() {
  const b = data("builds"), r = data("reels"), ts = data("thinking_space"), sys = data("system");
  const trackers = r.trackers || [];
  const done = trackers.reduce((s, t) => s + t.done, 0), total = trackers.reduce((s, t) => s + t.total, 0);
  const inbox = (ts.boards || []).reduce((s, x) => s + (x.inbox || []).length, 0);
  const cell = (v, k) => el("div", {}, el("div", { class: "mid" }, v), muted(k));
  return el("div", { class: "cols4" }, cell(b.week ?? "–", "commits this week"), cell(`${done}/${total}`, "reels done"),
    cell(inbox, "Inbox items"), cell(sys.battery ? `${sys.battery.percent}%` : pct(sys.cpu), sys.battery ? "battery" : "CPU"));
}

// --------------------------------------------------------------- renderers
const render = {
  next() {
    const items = state.next || [];
    setFaces("next", [[
      el("div", { class: "mid" }, items.length ? `${items.length} thing${items.length > 1 ? "s" : ""} worth doing` : "All clear"),
      el("ul", { class: "list grow", style: "gap:10px;font-size:13px" },
        (items.length ? items : [{ text: "Nothing needs you right now." }]).map((s) => el("li", {},
          el("span", { style: "white-space:normal" }, s.text),
          s.action ? el("button", { class: "btn", type: "button", onclick: () => act(s.action) }, s.action.label || "Open") : null))),
      summaryStrip(),
    ]]);
  },

  clock() {
    const now = new Date();
    const at = state.config.backup_at || "";
    const backup = data("thinking_space").last_backup || {};
    const faces = [[
      el("div", { class: "huge" }, now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })),
      el("div", { class: "t" }, now.toLocaleDateString(undefined, { weekday: "long" })),
      muted(now.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }), "font-size:13px"),
      el("div", { class: "between", style: "margin-top:auto" }, muted(`Week ${isoWeek(now)}`), muted(at ? `backup ${at}` : "")),
    ]];
    if (/^\d{1,2}:\d{2}$/.test(at)) {
      const [h, m] = at.split(":").map(Number);
      const next = new Date(now); next.setHours(h, m, 0, 0);
      if (next < now) next.setDate(next.getDate() + 1);
      const mins = Math.round((next - now) / 60000);
      faces.push([
        muted("Nightly backup", "font-size:12px"),
        el("div", { class: "big" }, mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins} min`),
        muted(`at ${at} · boards, trackers, history`, "font-size:12px"),
        backup.subject ? el("div", { class: "clamp2", style: "font-size:12px;margin-top:auto" }, `Last: ${backup.subject} (${ago(backup.when)})`) : null,
      ]);
    }
    setFaces("clock", faces);
  },

  builds() {
    const d = data("builds");
    const repos = d.repos || [];
    const list = el("div", { class: "repos grow" }, repos.slice(0, 4).map((r) => el("div", { class: "repo" },
      el("div", { class: "between" },
        el("span", {}, el("span", { class: `dot ${r.dirty || r.ahead ? "warn" : ""}`, style: "margin-right:8px" }), el("b", {}, r.name),
          muted(`  ${r.branch || ""}`)),
        muted(`${r.dirty ? `${r.dirty} changed · ` : ""}${r.ahead ? `${r.ahead} to push · ` : ""}${r.sha || ""} · ${ago(r.when)}`, "white-space:nowrap")),
      el("div", { class: "repo-sub" }, r.subject || ""))));
    const days = d.activity || [];
    const peak = Math.max(1, ...days);
    const busiest = repos.filter((r) => r.when && Date.now() / 1000 - r.when < 7 * 86400).map((r) => r.name);
    setFaces("builds", [
      [list.children.length ? list : muted("No git checkouts found. Set \"repos\" in mario.json.")],
      [el("div", { class: "between" }, el("div", {}, el("div", { class: "big" }, d.week || 0), muted("commits in the last 7 days")),
        muted(busiest.length ? `active: ${busiest.slice(0, 3).join(", ")}` : "quiet week")),
       el("div", { class: "heat" }, days.map((n) => el("i", { title: `${n} commits`, style: n ? `background:rgba(48,209,88,${0.25 + 0.75 * (n / peak)})` : "" }))),
       muted("last 14 days, all repos")],
    ], { badge: d.week ? `${d.week} this week` : "" });
  },

  weather() {
    const w = data("weather");
    if (w.off) return setFaces("weather", [[muted("Weather is off in mario.json")]]);
    if (w.error || w.temp == null) return setFaces("weather", [[el("div", { class: "t" }, w.place || "Weather"), muted("No forecast right now")]]);
    setFaces("weather", [
      [el("div", { class: "between" }, el("div", { class: "big" }, `${w.temp}°`),
        el("div", { style: "text-align:right" }, el("div", { class: "t" }, w.sky), muted(`${w.place} · feels ${w.feels}°`))),
       muted(`Today ${Math.round(w.low)}–${Math.round(w.high)}° · rain ${w.rain ?? 0}%`)],
      [el("div", { class: "hours" }, (w.hours || []).map((h) => el("div", {}, muted(h.h), el("div", { class: "t" }, `${h.t}°`), muted(`${h.rain || 0}%`)))),
       muted(`Today ${Math.round(w.low)}–${Math.round(w.high)}° · rain ${w.rain ?? 0}%`)],
    ]);
  },

  phone() {
    const p = data("phone"), b = data("system").battery;
    const faces = [[
      el("div", { class: "between" }, el("div", { class: "t" }, p.linked ? p.name || "Phone" : "Not linked"),
        el("span", { class: `dot ${p.linked ? (p.present ? "" : "warn") : "off"}` })),
      muted(p.linked ? (p.present ? "Here, connected" : "Linked, away") : p.error || "Pair it with Adaptive Link"),
    ]];
    if (b) faces.push([el("div", { class: "between" }, el("div", { class: "t" }, "Laptop battery"), el("div", { class: "mid" }, `${b.percent}%`)),
      el("div", { class: "bar" }, el("i", { style: `width:${b.percent}%;background:${b.percent < 20 ? "#FF453A" : "#30D158"}` })), muted(b.status)]);
    setFaces("phone", faces);
  },

  thinking() {
    const d = data("thinking_space");
    if (d.error) return setFaces("thinking", [[muted(d.error)]]);
    const boards = d.boards || [];
    const inbox = boards.flatMap((b) => (b.inbox || []).map((text) => ({ board: b.title, text, url: b.url })));
    const hubUrl = (d.hub || {}).url;
    setFaces("thinking", [
      [el("div", { class: "cols2 grow fill" }, boards.slice(0, 4).map((b) => el("div", { class: "boardbox" },
        el("div", { class: "between" }, el("span", { class: "t" }, b.title), muted(b.inbox && b.inbox.length ? `${b.inbox.length} in Inbox` : "Inbox clear")),
        el("ul", { class: "sections" }, (b.sections || []).slice(0, 3).map((x) => el("li", {}, x))))))],
      inbox.length ? [el("div", { class: "t" }, "Waiting in your Inboxes"),
       el("ul", { class: "list grow" }, inbox.slice(0, 5).map((x) => el("li", {}, el("span", {}, x.text), muted(x.board))))] : null,
      d.updated ? [el("div", { class: "mid clamp3" }, d.updated)] : null,
    ], { open: () => openUrl(hubUrl), badge: inbox.length ? `${inbox.length} new` : "" });
    render.map();
  },

  map() {
    const boards = data("thinking_space").boards || [];
    const svg = svgEl("svg", { class: "map", viewBox: "0 0 300 200", role: "img", "aria-label": "Ideas from all boards, grouped by board" });
    const cx = 150, cy = 92;
    boards.forEach((b, i) => {
      const a = (i / Math.max(boards.length, 1)) * Math.PI * 2 - Math.PI / 4;
      const bx = cx + Math.cos(a) * 92, by = cy + Math.sin(a) * 62;
      svg.append(svgEl("line", { x1: cx, y1: cy, x2: bx, y2: by, stroke: "rgba(255,255,255,.14)" }));
      const n = Math.min(9, Math.max(2, Math.round((b.elements || 0) / 5)));
      for (let k = 0; k < n; k++) {
        const t = (k / n) * Math.PI * 2 + i;
        svg.append(svgEl("circle", { cx: bx + Math.cos(t) * 20, cy: by + Math.sin(t) * 14, r: 2.6, fill: COLORS[i % COLORS.length] }));
      }
      const dot = svgEl("circle", { cx: bx, cy: by, r: 7, fill: COLORS[i % COLORS.length] });
      const title = svgEl("title", {}); title.textContent = b.title; dot.append(title);
      svg.append(dot);
    });
    svg.append(svgEl("circle", { cx, cy, r: 9, fill: "#F5F5F7" }));
    setFaces("map", [[svg]], { open: () => openUrl((data("thinking_space").hub || {}).url) });
  },

  reels() {
    const d = data("reels");
    if (d.error) return setFaces("reels", [[muted(d.error)]]);
    const trackers = d.trackers || [];
    const done = trackers.reduce((s, t) => s + t.done, 0), total = trackers.reduce((s, t) => s + t.total, 0);
    const bar = (t, i) => el("div", {}, el("div", { class: "between" }, el("span", {}, t.label), muted(`${t.done} of ${t.total} ${t.verb}`)),
      el("div", { class: "bar" }, el("i", { style: `width:${(100 * t.done) / Math.max(t.total, 1)}%;background:${COLORS[(i + 3) % COLORS.length]}` })));
    setFaces("reels", [
      [el("div", { class: "cols2 grow", style: "align-content:space-evenly" }, trackers.slice(0, 8).map(bar))],
      [el("div", { class: "between" }, el("div", { class: "row", style: "align-items:baseline" }, el("div", { class: "big" }, `${done}`), muted(`of ${total} tracked reels done`)),
        muted(`${d.total || 0} reels saved`)),
       el("div", { class: "t", style: "margin-top:4px" }, "Newest saves"),
       el("ul", { class: "list grow" }, (d.newest || []).map((r) => el("li", {}, el("span", {}, shortTitle(r.what, 80)), muted(`${r.category.split(",")[0]} · ${r.saved.slice(5)}`))))],
      [el("div", { class: "t" }, "Version history"),
       el("ul", { class: "list grow" }, (d.history || []).map((h) => el("li", {}, el("span", {}, `${h.Change}: ${h.Item}`), muted(h.Date))))],
    ], { open: () => openUrl(d.sheet), badge: `${done}/${total}` });
  },

  tonight() {
    const watch = data("reels").watch || [];
    setFaces("tonight", watch.length ? watch.slice(0, 5).map((m, k) => [
      muted(m.where, "font-size:12px"),
      el("div", { class: "mid clamp3", style: "font-size:22px" }, m.title),
      muted([m.type, m.year].filter(Boolean).join(" · ")),
      el("div", { style: "margin-top:auto;display:flex;flex-direction:column;gap:3px" }, muted("Also streaming"),
        watch.filter((_, j) => j !== k).slice(0, 3).map((o) => el("div", { style: "font-size:12px;color:var(--soft)" }, `${o.title} · ${o.where}`))),
    ]) : [[el("div", { class: "t" }, "Nothing queued"), muted("Mark films in the Movies tab")]]);
  },

  system() {
    const d = data("system");
    const label = tiles.system && tiles.system.el.querySelector("[data-k=host]");
    if (label) label.textContent = d.host || "This laptop";
    if (d.cpu != null) { cpuHistory.push(d.cpu); if (cpuHistory.length > 60) cpuHistory.shift(); }
    const spark = svgEl("svg", { class: "spark grow", viewBox: "0 0 300 36", preserveAspectRatio: "none", "aria-hidden": "true" });
    spark.append(svgEl("polyline", { points: cpuHistory.map((v, i) => `${(i / 59) * 300},${34 - (v / 100) * 30}`).join(" ") }));
    const gpu = d.gpu;
    const stat = (name, value, sub) => el("div", {}, muted(name), el("div", { class: "big", style: "font-size:30px" }, value), sub ? muted(sub) : null);
    setFaces("system", [
      [el("div", { class: "cols3" },
        stat("CPU", pct(d.cpu)),
        stat("RAM", d.mem ? `${d.mem.used_gb}` : "–", d.mem ? `of ${d.mem.total_gb} GB` : ""),
        stat(gpu ? gpu.name : "GPU", gpu ? pct(gpu.util) : "–", gpu ? `${gpu.vram_used_gb}/${gpu.vram_total_gb} GB VRAM` : "")),
       spark,
       el("div", { class: "between" }, muted(`Disk ${d.disk ? `${d.disk.used_gb}/${d.disk.total_gb} GB` : "–"}`),
         muted(`Net ${d.net ? `↓ ${fmtRate(d.net.down)} ↑ ${fmtRate(d.net.up)}` : "–"}`),
         muted(`Model ${(d.ollama && d.ollama.models && d.ollama.models[0]) || "none"}`))],
      [el("div", { class: "cols3" },
        stat("Disk", d.disk ? `${Math.round((100 * d.disk.used_gb) / d.disk.total_gb)}%` : "–", d.disk ? `${d.disk.used_gb} of ${d.disk.total_gb} GB` : ""),
        stat("Network", d.net ? fmtRate(d.net.down) : "–", d.net ? `up ${fmtRate(d.net.up)}` : ""),
        stat("Up", d.uptime_h != null ? (d.uptime_h >= 24 ? `${Math.floor(d.uptime_h / 24)}d` : `${Math.round(d.uptime_h)}h`) : "–", "since boot"))],
    ]);
    render.phone(); render.loom();
  },

  usage() {
    const providers = data("usage").providers || {};
    const names = Object.keys(providers);
    const title = (n) => n[0].toUpperCase() + n.slice(1);
    const line = (n) => {
      const p = providers[n];
      return el("div", {}, el("div", { class: "between" }, el("span", { class: "t" }, title(n)),
        muted(p.used == null ? "no data yet" : `${pct(p.used)} · ${p.window}`)),
        el("div", { class: "bar" }, el("i", { style: `width:${p.used || 0}%;background:${p.used > 80 ? "#FF453A" : n === "claude" ? "#D9A27A" : "#0A84FF"}` })));
    };
    const resets = names.flatMap((n) => (providers[n].windows || []).map((w) => el("li", {},
      el("span", {}, `${title(n)} ${w.label}`),
      muted(`${pct(w.used)}${w.resets ? ` · resets ${new Date(w.resets * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}` : ""}`))));
    setFaces("usage", [
      [el("div", { style: "display:flex;flex-direction:column;gap:12px" }, names.map(line)),
       resets.length ? el("ul", { class: "list", style: "margin-top:auto;gap:5px;font-size:12px" }, resets.slice(0, 4)) : muted("Mario answers locally first", "margin-top:auto")],
    ]);
  },

  office() {
    const d = data("agent_office");
    if (!d.running) {
      return setFaces("office", [[el("div", { class: "mid" }, "Stopped"), muted("Your AI company is off"),
        el("button", { class: "btn", type: "button", style: "margin-top:auto;align-self:flex-start", onclick: () => act({ id: "start_office" }) }, "Start")]]);
    }
    const busy = (d.agents || []).filter((a) => /work|busy|run/i.test(a.status)).length;
    setFaces("office", [
      [el("div", { class: "big" }, `${busy}`), muted(`of ${(d.agents || []).length} agents working`),
       el("ul", { class: "list" }, (d.agents || []).slice(0, 3).map((a) => el("li", {}, el("span", {}, a.name), muted(a.status))))],
      [el("div", { class: "t" }, d.missions && d.missions.length ? "On a mission" : d.paused ? "Paused" : "Free"),
       el("div", { class: "clamp3" }, d.missions && d.missions.length ? d.missions[0].title : "No mission running")],
    ], { open: () => openUrl("http://127.0.0.1:8790/") });
  },

  trynext() {
    const items = data("reels").try_next || [];
    setFaces("trynext", items.length ? items.map((x) => ({
      n: [muted(x.kind, "font-size:12px"), el("div", { class: "t clamp3", style: "font-size:16px" }, shortTitle(x.name, 80)),
        el("div", { class: "clamp2", style: "font-size:12px;color:var(--soft)" }, x.what)],
      open: () => openUrl(x.link),
    })) : [[el("div", { class: "t" }, "Everything tried"), muted("Nice.")]], { badge: items.length ? "tap to open" : "" });
  },

  cook() {
    const items = data("reels").cook || [];
    setFaces("cook", items.length ? items.map((x) => ({ n: [el("div", { class: "t clamp2" }, shortTitle(x.name, 60))], open: () => openUrl(x.link) }))
      : [[muted("No recipes waiting")]]);
  },

  loom() {
    const d = data("loom"), ollama = data("system").ollama || {};
    setFaces("loom", [
      [el("div", { class: "between" }, el("div", { class: "t" }, d.running ? (d.warming_up ? "Warming up" : "Ready") : "Off"),
        el("span", { class: `dot ${d.running ? "" : "off"}` })),
       muted(d.running ? `model ${d.model}${d.models ? ` · ${d.models} local` : ""}` : "Start LOOM's backend for memory")],
      [el("div", { class: "between" }, el("div", { class: "t" }, ollama.running ? "Ollama on" : "Ollama off"),
        el("span", { class: `dot ${ollama.running ? "" : "off"}` })),
       muted(ollama.models && ollama.models.length ? `loaded: ${ollama.models[0]}` : "no model loaded")],
    ]);
  },
};

// ------------------------------------------------------------- launchers
const LAUNCH_URLS = {
  hub: () => (data("thinking_space").hub || {}).url,
  sheet: () => data("reels").sheet,
  claude: () => "https://claude.ai/",
  gemini: () => "https://gemini.google.com/app",
  office: () => "http://127.0.0.1:8790/",
};
function launch(key) {
  if (LAUNCH_URLS[key]) return openUrl(LAUNCH_URLS[key]());
  return act({ id: "launch", arg: key });
}
function renderLaunchers() {
  const usage = data("usage").providers || {};
  const reels = data("reels"), ts = data("thinking_space"), office = data("agent_office"), phone = data("phone");
  const trackers = reels.trackers || [];
  const inbox = (ts.boards || []).reduce((s, b) => s + (b.inbox || []).length, 0);
  const badges = {
    claude: usage.claude && usage.claude.used != null ? pct(usage.claude.used) : "",
    gemini: usage.gemini && usage.gemini.used != null ? pct(usage.gemini.used) : "",
    hub: inbox ? String(inbox) : "",
    sheet: trackers.reduce((s, t) => s + t.done, 0) ? `${trackers.reduce((s, t) => s + t.done, 0)} done` : "",
    office: office.running ? String((office.agents || []).filter((a) => /work|busy|run/i.test(a.status)).length || "") : "off",
    phone: phone.linked ? (phone.present ? "here" : "away") : "",
    downloads: data("downloads").count ? String(data("downloads").count) : "",
  };
  const available = state.config.launch || {};
  document.querySelectorAll("[data-launch]").forEach((node) => {
    const key = node.dataset.launch;
    node.querySelector(".badge").textContent = badges[key] || "";
    node.classList.toggle("off", !LAUNCH_URLS[key] && available[key] === false);
  });
}

Object.assign(render, {
  recent() {
    const files = data("recent").files || [];
    setFaces("recent", [[
      files.length ? el("ul", { class: "list grow" }, files.slice(0, 5).map((f) => el("li", {},
        el("span", {}, el("button", { class: "link", type: "button", onclick: () => act({ id: "open_file", arg: f.path }) }, f.name)),
        muted(`${f.app ? f.app + " · " : ""}${ago(f.when)}`))))
        : muted("Files you open show up here"),
    ]]);
  },

  downloads() {
    const d = data("downloads");
    const size = (b) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${Math.round(b / 1e6)} MB` : `${Math.round(b / 1e3)} KB`);
    const files = d.files || [];
    setFaces("downloads", files.length ? files.slice(0, 3).map((f) => ({
      n: [muted(ago(f.when)), el("div", { class: "t clamp3", style: "word-break:break-all" }, f.name), muted(size(f.size))],
      open: () => act({ id: "open_file", arg: f.path }),
    })) : [[muted(d.error || "Nothing downloaded")]], { badge: d.count ? String(d.count) : "" });
  },

  focus() {
    const f = data("focus");
    const left = Math.max(0, (f.until || 0) - Date.now() / 1000);
    if (left > 0) {
      const total = (f.minutes || 1) * 60, r = 26, c = 2 * Math.PI * r;
      const ring = svgEl("svg", { class: "ring", viewBox: "0 0 64 64", "aria-hidden": "true" });
      ring.append(svgEl("circle", { cx: 32, cy: 32, r, stroke: "rgba(255,255,255,.12)" }));
      ring.append(svgEl("circle", { cx: 32, cy: 32, r, stroke: "#FF453A", "stroke-dasharray": c,
        "stroke-dashoffset": c * (1 - left / total), transform: "rotate(-90 32 32)", "stroke-linecap": "round" }));
      const mm = Math.floor(left / 60), ss = String(Math.floor(left % 60)).padStart(2, "0");
      setFaces("focus", [[el("div", { class: "row", style: "flex-wrap:nowrap" }, ring,
        el("div", {}, el("div", { class: "big", style: "font-size:26px" }, `${mm}:${ss}`), muted(`of ${f.minutes} min`))),
        el("button", { class: "btn", type: "button", style: "margin-top:auto;align-self:flex-start", onclick: () => post("/api/focus", { minutes: 0 }) }, "Stop")]]);
    } else {
      setFaces("focus", [[el("div", { class: "t" }, "Start a focus block"), muted("Mario pings you when it ends"),
        el("div", { class: "row", style: "margin-top:auto" }, [25, 50, 90].map((m) =>
          el("button", { class: "btn", type: "button", onclick: () => post("/api/focus", { minutes: m }) }, `${m}m`)))]]);
    }
  },

  processes() {
    const top = data("processes").top || [];
    setFaces("processes", [[el("ul", { class: "list grow" }, top.slice(0, 5).map((p) => el("li", {},
      el("span", {}, p.name), muted(`${Math.round(p.cpu)}% · ${p.mem.toFixed(1)}% mem`))))]]);
  },

  notes() {
    const old = document.querySelector("#jot");
    const keep = old ? { value: old.value, focused: document.activeElement === old } : null;
    const items = data("notes").items || [];
    const input = el("input", { id: "jot", placeholder: "Jot something…", "aria-label": "Jot a note" });
    const form = el("form", { class: "field", onsubmit: async (e) => {
      e.preventDefault(); const text = input.value; input.value = ""; if (text.trim()) await post("/api/note", { text });
    } }, input, el("button", { class: "btn", type: "submit" }, "Add"));
    setFaces("notes", [[el("ul", { class: "list grow" }, items.slice(0, 3).map((n) => el("li", {}, el("span", { style: "white-space:normal" }, n)))), form]]);
    if (keep) { input.value = keep.value; if (keep.focused) input.focus(); }
  },
});

// card -> tiles that read it
const FEEDS = {
  builds: ["builds", "next"], thinking_space: ["thinking", "clock", "next", "launchers"],
  reels: ["reels", "tonight", "trynext", "cook", "launchers"], system: ["system"], phone: ["phone", "launchers"],
  usage: ["usage", "launchers"], agent_office: ["office", "launchers"], loom: ["loom"], weather: ["weather"],
  recent: ["recent"], downloads: ["downloads", "launchers"], processes: ["processes"], focus: ["focus"], notes: ["notes"],
};

function renderTile(name) {
  try { if (name === "launchers") renderLaunchers(); else render[name](); } catch (e) { console.error(name, e); }
}
function renderAll() {
  Object.keys(render).forEach(renderTile);
  renderLaunchers();
  renderPresence(); greet();
}

function renderPresence() {
  const p = state.presence || { state: "ready" };
  document.querySelectorAll(".mark").forEach((m) => m.setAttribute("data-state", p.state));
  const sub = $("#panel-sub");
  if (sub) sub.textContent = p.detail ? `${p.state.replace("_", " ")} · ${p.detail}` : "answers locally first";
}

function greet() {
  const now = new Date(), h = now.getHours();
  $("#greeting").textContent = `Good ${h < 5 ? "night" : h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"}, Karthi`;
  $("#date").textContent = now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

// -------------------------------------------------------------------- ask
function answerNode(res) {
  if (res.error) return el("div", { class: "mario" }, res.error);
  if (res.route === "claude") return planNode(res.handoff);
  const meta = el("div", { class: "row" });
  if (res.via) meta.append(el("span", { class: "pill mono" }, [res.model || res.via, res.via === "Mario" ? "instant" : "local", res.ms ? `${(res.ms / 1000).toFixed(1)} s` : ""].filter(Boolean).join(" · ")));
  return el("div", { class: "mario" }, res.answer || "", res.note ? muted(res.note) : null, meta);
}

function planNode(plan) {
  const out = el("pre", { hidden: true });
  return el("div", { class: "plan", "data-handoff": plan.id },
    el("div", { class: "between" }, el("b", {}, `Claude Code in ${plan.repo}`),
      el("span", { class: "pill", style: "color:#FF9F0A" }, plan.outward ? "you push or send yourself" : "edits files here")),
    el("ol", {}, plan.steps.map((s) => el("li", {}, s))),
    out,
    el("div", { class: "row" },
      el("button", { class: "btn primary", type: "button", onclick: async (e) => {
        e.target.closest(".row").remove(); out.hidden = false; out.textContent = "Starting…\n";
        await post(`/api/handoff/${plan.id}`, { decision: "run" });
      } }, "Run"),
      el("button", { class: "btn", type: "button", onclick: () => act({ id: "claude_session", arg: plan.cwd }) }, "Open in terminal instead"),
      el("button", { class: "btn", type: "button", onclick: async (e) => {
        await post(`/api/handoff/${plan.id}`, { decision: "cancel" }); e.target.closest(".plan").remove();
      } }, "Not now")));
}

function handoffEvent(msg) {
  document.querySelectorAll(`[data-handoff="${msg.id}"] pre`).forEach((pre) => {
    pre.hidden = false;
    if (msg.line) pre.textContent += msg.line + "\n";
    if (msg.status === "done" || msg.status === "failed") {
      pre.textContent += msg.status === "done" ? `\nDone.${msg.changed && msg.changed.length ? `\nChanged:\n${msg.changed.join("\n")}` : "\nNo files changed."}` : "\nStopped with an error.";
    }
    pre.scrollTop = pre.scrollHeight;
  });
}

async function ask(text, where) {
  text = text.trim();
  if (!text) return;
  const box = $("#answer");
  if (where === "panel") $("#log").append(el("div", { class: "me" }, text));
  else { box.hidden = false; box.replaceChildren(muted("…")); }
  let res;
  try { res = await post("/api/ask", { text }); } catch (e) { res = { error: "Mario Hub is not answering." }; }
  if (where === "panel") { $("#log").append(answerNode(res)); $("#log").scrollTop = $("#log").scrollHeight; }
  else box.replaceChildren(el("button", { class: "close", type: "button", "aria-label": "Close", onclick: () => { box.hidden = true; } }, "×"), answerNode(res));
}

// ------------------------------------------------------------------- live
function connect(delay = 500) {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { $("#offline").hidden = true; delay = 500; };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") { Object.assign(state, msg); if (!PANEL) renderAll(); else renderPresence(); }
    else if (msg.type === "card") {
      state.cards[msg.name] = { data: msg.data, at: msg.at };
      if (!PANEL) (FEEDS[msg.name] || []).forEach(renderTile);
    } else if (msg.type === "next") { state.next = msg.items; if (!PANEL) renderTile("next"); }
    else if (msg.type === "presence") { state.presence = msg; renderPresence(); }
    else if (msg.type === "handoff") handoffEvent(msg);
  };
  ws.onclose = () => { $("#offline").hidden = false; setTimeout(() => connect(Math.min(delay * 2, 10000)), delay); };
}

document.addEventListener("DOMContentLoaded", () => {
  if (PANEL) {
    document.body.classList.add("is-panel");
    $("#home").hidden = true; $("#panel").hidden = false;
    $("#panel-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#panel-input"); ask(i.value, "panel"); i.value = ""; });
    $("#panel-input").focus();
  } else {
    setupTiles();
    $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#ask"); ask(i.value, "home"); i.value = ""; });
    document.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.ask, "home")));
    // Voice is the listener's job (docs/MARIO.md, phase 3); until it runs, the button types.
    $("#talk").addEventListener("click", () => { const i = $("#ask"); i.placeholder = "Voice comes with the listener; type for now"; i.focus(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#answer").hidden = true; });
    setInterval(() => { greet(); renderTile("clock"); }, 30000);
    setInterval(() => { if ((data("focus").until || 0) > Date.now() / 1000 - 1) renderTile("focus"); }, 1000);
  }
  connect();
});
