// Mario Home ("Your day") and the Mario panel: one page, two layouts (/ and /panel).
// Everything shown comes from Mario Hub over a WebSocket and updates live; cards render from
// state only, so a reconnect redraws the whole day.
"use strict";

const PANEL = location.pathname === "/panel";
const state = { cards: {}, next: [], presence: { state: "ready" }, config: {} };
const HUES = ["#5E5CE6", "#0A84FF", "#30D158", "#FF9F0A", "#BF5AF2", "#FF375F", "#64D2FF"];

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
function icon(id, cls) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (cls) s.setAttribute("class", cls);
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#${id}`);
  s.append(u);
  return s;
}
const data = (name) => (state.cards[name] || {}).data || {};
const $ = (sel) => document.querySelector(sel);
const body = (card) => $(`#c-${card} .body`);
// replaceChildren would print a null as the text "null"; cards leave out what they have not got
const fill = (node, ...kids) => node.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
const count = (card, n) => { const c = $(`#c-${card} .count`); if (c) c.textContent = n ? String(n) : ""; };
const hue = (text) => HUES[[...String(text)].reduce((a, ch) => a + ch.charCodeAt(0), 0) % HUES.length];
const pct = (v) => (v == null ? "–" : `${Math.round(v)}%`);
const empty = (...parts) => el("div", { class: "empty" }, ...parts);
const code = (text) => el("code", {}, text);

function when(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), now = new Date();
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  if (d.toDateString() === now.toDateString()) return hm;
  if (now - d < 2 * 86400000 && now.getDate() !== d.getDate()) return `yesterday`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
function whenLong(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), now = new Date();
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  if (d.toDateString() === now.toDateString()) return `today, ${hm}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `yesterday, ${hm}`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
const size = (b) => (b == null ? "" : b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);
const KIND = { ipynb: "Notebook", py: "Python", md: "Markdown", js: "JavaScript", ts: "TypeScript", json: "JSON", yaml: "YAML",
  yml: "YAML", sh: "Shell", pdf: "PDF", docx: "Document", xlsx: "Spreadsheet", csv: "CSV", pptx: "Slides", png: "Image",
  jpg: "Image", jpeg: "Image", mp4: "Video", cpp: "C++", hpp: "C++", c: "C", h: "C", txt: "Text", html: "HTML", css: "CSS" };
const kindOf = (name) => { const ext = (name.split(".").pop() || "").toLowerCase(); return KIND[ext] || ext.toUpperCase() || "File"; };

async function post(url, payload) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  return res.json();
}
const act = (action) => post("/api/action", action);
const openUrl = (url) => url && act({ id: "url", arg: url });

// ----------------------------------------------------------------- cards
const render = {
  mail() {
    const m = data("mail");
    count("mail", m.unread || "");
    if (m.unread == null) {
      return fill(body("mail"), empty(m.setup ? "Connect Gmail once on this laptop: " : (m.error || "Checking mail…"),
        m.setup ? code("scripts/install-mario.sh --mail") : null, m.setup ? el("br") : null,
        m.setup ? "It reads unread headers only and never marks anything read." : null));
    }
    const items = m.items || [];
    fill(body("mail"), 
      items.length ? el("ul", { class: "rows" }, items.slice(0, 5).map((i) => el("li", {},
        el("span", { class: "avatar", style: `background:${hue(i.from)}33;color:${hue(i.from)}` }, (i.from || "?").trim()[0].toUpperCase()),
        el("div", { class: "grow" }, el("div", { class: "ttl" }, i.from), el("div", { class: "sub" }, i.subject)),
        el("span", { class: "time" }, when(i.when)))))
        : empty("Inbox zero. Nothing unread."),
      el("div", { class: "foot" }, el("button", { class: "link", type: "button", onclick: () => openUrl("https://mail.google.com/") }, "Open Mail", icon("i-chev"))));
  },

  today() {
    const c = data("calendar");
    const now = new Date();
    const hm = now.toTimeString().slice(0, 5);
    const head = el("div", { class: "dateline" }, el("b", {}, now.getDate()), el("span", {}, now.toLocaleDateString(undefined, { weekday: "short" })));
    const events = c.events || [];
    count("today", events.length || "");
    if (!c.events) {
      return fill(body("today"), head, empty(c.setup ? "Show today's events: " : (c.error || "Loading your calendar…"),
        c.setup ? code("scripts/install-mario.sh --calendar") : null, c.setup ? el("br") : null,
        c.setup ? "It reads your calendar's private iCal address, read-only." : null));
    }
    const nowIndex = events.findIndex((e) => e.start && e.start > hm) - 1;
    fill(body("today"), head, events.length ? el("ul", { class: "timeline" }, events.slice(0, 5).map((e, i) => {
      const end = e.start && e.minutes ? (() => { const [h, m] = e.start.split(":").map(Number); const t = h * 60 + m + e.minutes; return `${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; })() : "";
      const past = e.start && (end ? end <= hm : e.start < hm && i < nowIndex);
      const live = e.start && e.start <= hm && end && end > hm;
      return el("li", { class: live ? "now" : past ? "past" : "" },
        el("span", { class: "at" }, e.all_day ? "All day" : e.start),
        el("span", { class: "rail" }, el("i")),
        el("div", { style: "min-width:0;padding-bottom:6px" }, el("div", { class: "ttl" }, e.title),
          el("div", { class: "sub" }, [e.minutes ? `${e.minutes} min` : "", e.where].filter(Boolean).join(" · "))));
    })) : empty("Nothing on the calendar today. A good day for deep work."));
  },

  tasks() {
    const t = data("tasks");
    const open = t.open || [];
    count("tasks", t.count || "");
    const input = el("input", { placeholder: "Add task", "aria-label": "Add a task" });
    const add = el("form", { class: "add", onsubmit: async (e) => {
      e.preventDefault(); const text = input.value; input.value = ""; if (text.trim()) await post("/api/task", { text });
    } }, icon("i-plus"), input);
    // six rows in all: your tasks first, then Mario's suggestions in whatever room is left
    const shown = open.slice(0, open.length > 4 ? 6 : 4);
    const suggestions = (state.next || []).filter((s) => s.action).slice(0, Math.max(0, Math.min(2, 6 - shown.length - (open.length ? 0 : 1))));
    fill(body("tasks"), 
      open.length ? el("ul", { class: "rows" }, shown.map((x) => el("li", {},
        el("button", { class: "tick", type: "button", "aria-label": `Done: ${x.text}`, onclick: () => post("/api/task/done", { path: x.path, line: x.line }) }),
        el("div", { class: "grow" }, el("div", { class: "ttl", style: "font-weight:500" }, x.text)),
        el("span", { class: "dot", title: x.project, style: `background:${hue(x.project)}` }))))
        : empty("No open tasks. Super+Alt+N or the box below adds one."),
      suggestions.length ? el("div", { class: "sugg" }, icon("i-spark"), "Mario suggests") : null,
      suggestions.length ? el("ul", { class: "rows" }, suggestions.map((s) => el("li", { style: "padding:6px 0" },
        el("div", { class: "grow sub", style: "color:var(--soft)" }, s.text),
        el("button", { class: "mini", type: "button", onclick: () => act(s.action) }, s.action.label || "Open"),
        el("button", { class: "mini", type: "button", "aria-label": "Add as a task", onclick: () => post("/api/task", { text: s.text }) }, icon("i-plus"))))) : null,
      el("div", { style: "margin-top:auto" }, add));
  },

  projects() {
    // half-height card: the two most recent repos on one line each; agents in the header
    const repos = (data("builds").repos || []).slice(0, 2);
    const sessions = data("agent_sessions").sessions || [];
    const office = data("agent_office");
    const busy = (office.agents || []).filter((a) => /work|busy|run/i.test(a.status)).length;
    const meta = $("#agents");
    meta.className = `meta ${sessions.length || busy ? "on" : ""}`;
    fill(meta, icon("i-bot"), sessions.length
      ? `${sessions.length} agent${sessions.length > 1 ? "s" : ""}: ${sessions.slice(0, 2).map((x) => `${x.agent} · ${x.folder}`).join(", ")}`
      : office.running ? `Agent Office ${busy ? `${busy} working` : "idle"}` : "No agents running");
    fill(body("projects"), repos.length ? el("ul", { class: "rows" }, repos.map((r) => el("li", {},
      el("span", { class: `dot ${r.dirty || r.ahead ? "warn" : ""}` }),
      el("div", { class: "grow", style: "display:flex;align-items:baseline;gap:8px;min-width:0" },
        el("span", { class: "ttl", style: "flex:none" }, r.name), el("span", { class: "sub" }, r.subject || "")),
      el("span", { class: "chipi" }, icon("i-branch"), r.branch || "–"),
      r.dirty ? el("span", { class: "chipi warn" }, `${r.dirty} changes`) : r.ahead ? el("span", { class: "chipi warn" }, `${r.ahead} to push`)
        : el("span", { class: "chipi ok" }, "Up to date"),
      el("button", { class: "mini", type: "button", "aria-label": `Open ${r.name} in Code`, onclick: () => act({ id: "code", arg: r.path }) }, icon("i-code"), "Code"))))
      : empty("No git checkouts found. Set ", code("repos"), " in ~/.config/adaptive-desktop/mario.json."));
  },

  thinking() {
    const d = data("thinking_space");
    const boards = d.boards || [];
    const inbox = boards.reduce((s, b) => s + (b.inbox || []).length, 0);
    count("thinking", inbox ? `${inbox} new` : "");
    if (d.error) return fill(body("thinking"), empty(d.error));
    const ICON = { "builds-tech": ["i-code", "#0A84FF"], "career-learning": ["i-cap", "#BF5AF2"], "business-income": ["i-chart", "#30D158"], "life-family": ["i-home", "#FF9F0A"] };
    fill(body("thinking"), el("div", { class: "boards" }, boards.slice(0, 4).map((b) => {
      const [ic, col] = ICON[b.slug] || ["i-layers", hue(b.slug)];
      return el("button", { class: "board", type: "button", onclick: () => openUrl(b.url) },
        el("div", { class: "board-head" }, el("span", { class: "bi", style: `background:${col}26;color:${col}` }, icon(ic)),
          el("div", { class: "grow" }, el("div", { class: "ttl" }, b.title),
            el("div", { class: "sub" }, b.inbox && b.inbox.length ? `${b.inbox.length} waiting in Inbox` : "Inbox clear"))),
        el("ul", { class: "sections" }, [...(b.inbox || []).slice(0, 2).map((x) => el("li", { class: "new" }, x)),
          ...(b.sections || []).slice(0, 4 - Math.min(2, (b.inbox || []).length)).map((x) => el("li", {}, x))]));
    })));
  },

  recent() {
    // half-height card: the two newest files on one line each
    const files = data("recent").files || [];
    fill(body("recent"), files.length ? el("ul", { class: "rows" }, files.slice(0, 2).map((f) => {
      const kind = kindOf(f.name);
      const ic = /Python|JavaScript|TypeScript|C\+\+|^C$|Shell|JSON|YAML|HTML|CSS/.test(kind) ? "i-code" : "i-file";
      return el("li", { style: "cursor:pointer", onclick: () => act({ id: "open_file", arg: f.path }) },
        el("span", { class: "bi", style: `width:26px;height:26px;border-radius:8px;background:${hue(kind)}26;color:${hue(kind)}` }, icon(ic)),
        el("div", { class: "grow", style: "display:flex;align-items:baseline;gap:8px;min-width:0" },
          el("span", { class: "ttl", style: "font-weight:500;flex:none;max-width:60%" }, f.name), el("span", { class: "sub" }, [kind, size(f.size)].filter(Boolean).join(" · "))),
        el("span", { class: "time" }, whenLong(f.when)));
    })) : empty("Files you open in any app show up here."));
  },

  note() {
    // half-height card: the capture box and the latest note
    const old = $("#note-in");
    const keep = old ? { value: old.value, focused: document.activeElement === old } : null;
    const items = data("notes").items || [];
    const input = el("input", { id: "note-in", class: "note-in", placeholder: "Capture a thought…", "aria-label": "Capture a thought" });
    const form = el("form", { class: "note-box", style: "padding:6px 8px 6px 12px", onsubmit: async (e) => {
      e.preventDefault(); const text = input.value; input.value = ""; if (text.trim()) await post("/api/note", { text });
    } }, input, el("button", { class: "mini", type: "submit" }, "Save"));
    const last = items[0] ? items[0].split(" · ") : null;
    fill(body("note"), form, last ? el("div", { class: "between", style: "min-width:0" },
      el("span", { class: "sub", style: "color:var(--soft)" }, last.slice(1).join(" · ")), el("span", { class: "time" }, last[0]))
      : el("div", { class: "sub" }, "Kept on this laptop"));
    if (keep) { input.value = keep.value; if (keep.focused) input.focus(); }
  },

  weather() {
    const w = data("weather");
    if (w.off || w.error || w.temp == null) {
      return fill(body("weather"), el("div", { class: "weather" }, icon("i-cloud", "wi"),
        el("div", { class: "grow" }, el("div", { class: "ttl" }, w.place || "Weather"), el("div", { class: "sub" }, w.off ? "Off in mario.json" : "No forecast right now"))));
    }
    const sky = (w.sky || "").toLowerCase();
    const ic = /rain|drizzle|shower|thunder/.test(sky) ? "i-rain" : /clear/.test(sky) ? "i-sun" : "i-cloud";
    fill(body("weather"), el("div", { class: "weather" }, icon(ic, "wi"),
      el("div", {}, el("b", {}, `${w.temp}°`), el("div", { class: "sub" }, w.place)),
      el("div", { style: "margin-left:auto;text-align:right" }, el("div", { style: "font-size:13px;font-weight:600" }, w.sky),
        el("div", { class: "sub" }, `Feels ${w.feels}° · rain ${w.rain ?? 0}%`))));
  },

  ai() {
    const providers = data("usage").providers || {};
    const LINKS = { claude: "https://claude.ai/", gemini: "https://gemini.google.com/app" };
    const GLYPH = { claude: "M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4", gemini: "M12 2c1 5 5 9 10 10-5 1-9 5-10 10-1-5-5-9-10-10 5-1 9-5 10-10z" };
    fill(body("ai"), ...Object.keys(providers).map((name) => {
      const p = providers[name];
      const glyph = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      glyph.setAttribute("viewBox", "0 0 24 24"); glyph.setAttribute("aria-hidden", "true");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", GLYPH[name] || ""); glyph.append(path);
      return el("button", { class: "ai", type: "button", onclick: () => openUrl(LINKS[name]) },
        el("span", { class: "ab" }, glyph),
        el("div", { class: "grow" },
          el("div", { class: "between" }, el("span", { style: "font-size:14px;font-weight:600" }, name[0].toUpperCase() + name.slice(1)),
            el("span", { class: "sub" }, p.used == null ? "no data yet" : `${pct(p.used)} ${String(p.window || "").toLowerCase()}`)),
          el("div", { class: "bar" }, el("i", { style: `width:${p.used || 0}%;${p.used > 80 ? "background:#FF453A" : ""}` })),
          el("div", { class: "sub", style: "margin-top:5px" }, (p.windows || []).map((w) => `${w.label} ${pct(w.used)}${w.resets ? `, resets ${new Date(w.resets * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}` : ""}`).join(" · "))));
    }));
  },

  phone() {
    const p = data("phone");
    fill($("#c-phone .body"), el("span", { style: "font-size:14px;font-weight:600" }, "Phone"),
      el("span", { class: "sub", style: "display:flex;align-items:center;gap:6px;color:var(--soft)" },
        el("span", { class: `dot ${p.linked ? (p.present ? "" : "warn") : "off"}` }),
        p.linked ? `${p.name || "Phone"} · ${p.present ? "Connected" : "Away"}` : "Not linked"));
  },

  quick() {
    const h = data("health");
    const available = state.config.launch || {};
    document.querySelectorAll("[data-launch]").forEach((b) => b.classList.toggle("off", available[b.dataset.launch] === false));
    const node = $("#status");
    node.className = `status ${h.ok === false ? "warn" : "ok"}`;
    fill(node, icon(h.ok === false ? "i-warn" : "i-ok"),
      el("span", {}, h.ok === false ? (h.issues || []).join(" · ") : h.ok ? "All systems up to date" : "Checking the system…"));
  },

  brain() {
    const l = data("loom"), o = (data("system").ollama || {});
    const pill = $("#brain");
    pill.className = `pill ${l.running ? "ok" : o.running ? "warn" : "warn"}`;
    pill.textContent = l.running ? "LOOM ready" : o.running ? "Ollama only" : "Local brain off";
  },

  daysum() {
    const events = (data("calendar").events || []).length, tasks = data("tasks").count || 0, unread = data("mail").unread || 0;
    const bits = [];
    if (data("calendar").events) bits.push(`${events} event${events === 1 ? "" : "s"}`);
    bits.push(`${tasks} open task${tasks === 1 ? "" : "s"}`);
    if (data("mail").unread != null) bits.push(`${unread} unread`);
    $("#daysum").textContent = bits.join(" · ");
  },
};

// card -> renderers that read it
const FEEDS = {
  mail: ["mail", "daysum"], calendar: ["today", "daysum"], tasks: ["tasks", "daysum"],
  builds: ["projects"], agent_sessions: ["projects"], agent_office: ["projects"], thinking_space: ["thinking"],
  recent: ["recent"], notes: ["note"], weather: ["weather"], usage: ["ai"], phone: ["phone"], health: ["quick"],
  loom: ["brain"], system: ["brain"],
};
function draw(name) { try { render[name](); } catch (e) { console.error(name, e); } }
function renderAll() { Object.keys(render).forEach(draw); renderPresence(); greet(); }

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
  const meta = el("div", {});
  if (res.via) meta.append(el("span", { class: "pill" }, [res.model || res.via, res.via === "Mario" ? "instant" : "local", res.ms ? `${(res.ms / 1000).toFixed(1)} s` : ""].filter(Boolean).join(" · ")));
  return el("div", { class: "mario" }, res.answer || "", res.note ? el("span", { class: "muted" }, res.note) : null, meta);
}

function planNode(plan) {
  const out = el("pre", { hidden: true });
  return el("div", { class: "plan", "data-handoff": plan.id },
    el("div", { class: "between" }, el("b", {}, `Claude Code in ${plan.repo}`),
      el("span", { class: "pill warn" }, plan.outward ? "you push or send yourself" : "edits files here")),
    el("ol", {}, plan.steps.map((s) => el("li", {}, s))),
    out,
    el("div", { style: "display:flex;gap:8px;flex-wrap:wrap" },
      el("button", { class: "btn primary", type: "button", onclick: async (e) => {
        e.target.parentElement.remove(); out.hidden = false; out.textContent = "Starting…\n";
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
  else { box.hidden = false; box.replaceChildren(el("span", { class: "muted" }, "…")); }
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
      if (!PANEL) (FEEDS[msg.name] || []).forEach(draw);
    } else if (msg.type === "next") { state.next = msg.items; if (!PANEL) draw("tasks"); }
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
    $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#ask"); ask(i.value, "home"); i.value = ""; });
    document.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.ask, "home")));
    document.querySelectorAll("[data-launch]").forEach((b) => b.addEventListener("click", () => act({ id: "launch", arg: b.dataset.launch })));
    document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openUrl(b.dataset.open)));
    $("[data-open-hub]").addEventListener("click", () => openUrl((data("thinking_space").hub || {}).url));
    $("#c-phone").addEventListener("click", () => act({ id: "launch", arg: "phone" }));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#answer").hidden = true; });
    setInterval(() => { greet(); draw("today"); }, 60000);
  }
  connect();
});
