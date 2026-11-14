// Mario Home ("Your day") and the Mario panel: one page, two layouts (/ and /panel).
// Everything shown comes from Mario Hub over a WebSocket and updates live; cards render from
// state only, so a reconnect redraws the whole day.
"use strict";

const PANEL = location.pathname === "/panel";
const state = { cards: {}, next: [], presence: { state: "ready" }, config: {} };
// Colours are the stylesheet's chart series (tokens); the script never spells one out.
const HUES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];

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

// --------------------------------------------------------------- live tiles
// A card with faces turns to its next face on its own clock, like a live tile: it pauses while the
// pointer is over it or the screen is hidden, and new data redraws the face in place without turning.
const LIVE = {};
function setFaces(card, faces, { every = 9000, offset = 0, keep } = {}) {
  const node = body(card);
  let t = LIVE[card];
  if (!t) t = LIVE[card] = { i: 0, left: every + offset, every };
  t.every = every;
  if (keep != null) { const j = faces.findIndex((f) => f.key === keep); if (j >= 0) t.i = j; }
  t.faces = faces;
  if (t.i >= faces.length) t.i = 0;
  fill(node, faces.length ? el("div", { class: "face" }, faces[t.i]()) : []);
  liveControls(card);
}
function liveControls(card) {
  const t = LIVE[card], tile = $(`#c-${card}`);
  let nav = tile.querySelector(".tile-nav");
  if (!nav) {
    nav = el("nav", { class: "tile-nav", "aria-label": `${card} slides` },
      el("button", { type: "button", "aria-label": "Previous slide", onclick: () => turn(card, -1, true) }, "‹"),
      el("span", { class: "slide-count", "aria-live": "polite" }),
      el("button", { type: "button", "aria-label": "Next slide", onclick: () => turn(card, 1, true) }, "›"),
      el("button", { type: "button", class: "pause", onclick: () => { t.paused = !t.paused; liveControls(card); } }, "Pause"));
    tile.append(nav);
    tile.tabIndex = 0;
    tile.addEventListener("keydown", (e) => {
      if (e.target.matches("input, textarea, select")) return;
      if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault(); turn(card, e.key === "ArrowLeft" ? -1 : 1, true);
      }
    });
    let touch;
    tile.addEventListener("touchstart", (e) => { touch = e.touches[0]; }, { passive: true });
    tile.addEventListener("touchend", (e) => {
      if (!touch || e.target.closest("button, input, textarea, a")) return;
      const dx = e.changedTouches[0].clientX - touch.clientX, dy = e.changedTouches[0].clientY - touch.clientY;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) turn(card, dx < 0 ? 1 : -1, true);
      touch = null;
    });
  }
  nav.hidden = t.faces.length < 2;
  nav.querySelector(".slide-count").textContent = `${t.i + 1} / ${t.faces.length}`;
  const pause = nav.querySelector(".pause");
  pause.textContent = t.paused ? "Play" : "Pause";
  pause.setAttribute("aria-label", t.paused ? "Resume automatic slides" : "Pause automatic slides");
  pause.setAttribute("aria-pressed", String(!!t.paused));
  tile.classList.toggle("paused", !!t.paused);
}
function turn(card, direction = 1, manual = false) {
  const t = LIVE[card], node = body(card);
  if (!t || t.faces.length < 2) return;
  t.i = (t.i + direction + t.faces.length) % t.faces.length;
  t.left = t.every;
  if (manual) t.paused = true;
  // Replace immediately: rapid repeated Next clicks must never replay an older animation timer.
  fill(node, el("div", { class: "face in" }, t.faces[t.i]()));
  liveControls(card);
  if (TURNED[card]) TURNED[card](t, true);
}
const TURNED = {  // card -> called after each turn
  news(t, restart = true) {
    $("#news-src").textContent = t.faces.length > 1 ? `${t.i + 1} / ${t.faces.length}` : "";
    const bar = $("#c-news .roll");
    if (!restart && bar.classList.contains("go")) return;
    bar.classList.remove("go"); void bar.offsetWidth; bar.style.setProperty("--roll", `${t.every / 1000}s`); bar.classList.add("go");
  },
};
setInterval(() => {
  if (document.hidden) return;
  for (const [card, t] of Object.entries(LIVE)) {
    if (t.paused || matchMedia("(prefers-reduced-motion: reduce)").matches || $(`#c-${card}`).matches(":hover, :focus-within") || !t.faces || t.faces.length < 2) continue;
    if ((t.left -= 500) <= 0) { t.left = t.every; turn(card); }
  }
}, 500);

async function post(url, payload) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  return res.json();
}
async function act(action) {
  try {
    const result = await post("/api/action", action);
    if (result.error) showAnswer(result, PANEL ? "panel" : "home");
    return result;
  } catch (_) { showAnswer({ error: "Mario Hub is not answering. Try again." }, PANEL ? "panel" : "home"); return { ok: false }; }
}
const openUrl = (url) => url && act({ id: "url", arg: url });

// ----------------------------------------------------------------- cards
let mailAccount = null;  // the account Mail shows: the main one until you pick another
const newsMedia = (it) => (data("news_media").media || {})[it.link] || {};
// a headline's picture, cover-fitted; without one, the outlet's initial on its own colour
function newsPic(it, cls) {
  const m = newsMedia(it), letter = (it.source || "?").trim()[0].toUpperCase();
  const blank = () => el("span", { class: `${cls} none`, style: `--h:${hue(it.source)}` }, cls === "hero" ? it.source : letter);
  if (!m.image) return blank();
  return el("span", { class: cls }, el("img", { src: `/news-img/${m.image}`, alt: "", decoding: "async", draggable: "false",
    onerror: (e) => e.target.parentElement.replaceWith(blank()) }));
}

const render = {
  mail() {
    const m = data("mail");
    count("mail", m.unread || "");
    // every account is a tab; the main one (first) shows unless you picked another
    const accounts = m.accounts || [];
    const a = accounts.find((x) => x.user === mailAccount) || accounts[0] || m;
    const inbox = a.inbox || "https://mail.google.com/";
    $("#c-mail .open").dataset.open = inbox;
    const tabs = accounts.length > 1 ? el("div", { class: "accts", role: "tablist" }, accounts.map((x, j) =>
      el("button", { class: `acct${x === a ? " on" : ""}`, type: "button", role: "tab", "aria-selected": String(x === a),
        title: `${x.user}${j === 0 ? " (main)" : ""}${x.error ? `: ${x.error}` : ""}`,
        onclick: () => { mailAccount = x.user; draw("mail"); } },
        el("span", { class: "nm" }, x.user.split("@")[0]), j === 0 ? el("small", {}, "main") : null,
        x.unread ? el("span", { class: "n" }, x.unread > 999 ? "999+" : String(x.unread))
          : x.unread == null && !x.waiting ? el("i", { class: "dot warn" }) : null))) : null;
    if (a.unread == null && a.fix) {
      // the login was refused: say why and how to put it right
      return fill(body("mail"), tabs,
        empty(a.error, el("br"), a.fix === "app_password"
          ? "Make one named Mario (needs 2-Step Verification), then save it with "
          : "Make a new app password, then save it again with ", code("scripts/install-mario.sh --mail")),
        el("div", { class: "foot" }, el("button", { class: "btn primary", type: "button",
          onclick: () => openUrl("https://myaccount.google.com/apppasswords") }, "Create an app password")));
    }
    if (a.unread == null) {
      return fill(body("mail"), tabs, empty(a.setup ? "Connect Gmail once on this laptop: " : (a.error || "Checking mail…"),
        a.setup ? code("scripts/install-mario.sh --mail") : null, a.setup ? el("br") : null,
        a.setup ? "It reads unread headers only and never marks anything read." : null));
    }
    // a message opens that very conversation in Gmail, in its own account
    const items = a.items || [];
    fill(body("mail"), tabs,
      items.length ? el("ul", { class: "rows" }, items.slice(0, 5).map((i) => el("li", {},
        el("button", { class: "mrow", type: "button", title: "Open this mail in Gmail", onclick: () => openUrl(i.link || inbox) },
          el("span", { class: "avatar", style: `--h:${hue(i.from)}` }, (i.from || "?").trim()[0].toUpperCase()),
          el("div", { class: "grow" }, el("div", { class: "ttl" }, i.from), el("div", { class: "sub" }, i.subject)),
          el("span", { class: "time" }, when(i.when))))))
        : empty("Inbox zero. Nothing unread."),
      el("div", { class: "foot" }, el("button", { class: "link", type: "button", onclick: () => openUrl(inbox) },
        accounts.length > 1 ? `Open ${a.user.split("@")[0]}` : "Open Mail", icon("i-chev"))));
  },

  today() {
    const c = data("calendar");
    const now = new Date();
    const hm = now.toTimeString().slice(0, 5);
    $("#today-date").textContent = now.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    const events = c.events || [];
    count("today", events.length || "");
    if (!c.events) {
      return fill(body("today"), empty(c.setup ? "Show today's events: " : (c.error || "Loading your calendar…"),
        c.fix ? el("br") : null, c.fix ? "Save the right one with " : null,
        c.setup || c.fix ? code("scripts/install-mario.sh --calendar") : null, c.setup ? el("br") : null,
        c.setup ? "It reads your calendar's private iCal address, read-only." : null));
    }
    const nowIndex = events.findIndex((e) => e.start && e.start > hm) - 1;
    const rows = events.map((e, i) => {
      const end = e.start && e.minutes ? (() => { const [h, m] = e.start.split(":").map(Number); const t = Math.min(h * 60 + m + e.minutes, 24 * 60); return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; })() : "";
      return { e, past: e.start && (end ? end <= hm : e.start < hm && i < nowIndex), live: e.start && e.start <= hm && end && end > hm };
    });
    // the tile is small: start at the first event still to come (all-day ones stay), not at this morning's
    const ahead = rows.filter((r) => !r.past);
    fill(body("today"), events.length ? el("ul", { class: "timeline" }, (ahead.length ? ahead : rows).map(({ e, past, live }) => {
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
      e.preventDefault(); const text = input.value;
      if (!text.trim()) return;
      try {
        const result = await post("/api/task", { text });
        if (result.ok) { const current = body("tasks").querySelector("input"); if (current && current.value === text) current.value = ""; }
        else if (result.error) showAnswer(result, "home");
      } catch (_) { showAnswer({ error: "Task not saved. Your draft is still here; try again." }, "home"); }
    } }, icon("i-plus"), input);
    const keep = body("tasks").querySelector("input");
    if (keep) input.value = keep.value;
    const focused = keep === document.activeElement;
    const selection = focused ? [keep.selectionStart, keep.selectionEnd] : null;
    fill(body("tasks"),
      open.length ? el("ul", { class: "rows task-list" }, open.map((x) => el("li", {},
        el("button", { class: "tick", type: "button", "aria-label": `Done: ${x.text}`, onclick: () => post("/api/task/done", { path: x.path, line: x.line }) }),
        el("div", { class: "grow" }, el("div", { class: "ttl", style: "font-weight:500" }, x.text)),
        el("span", { class: "dot", title: x.project, style: `background:${hue(x.project)}` }))))
        : empty("Nothing pending. Add a task or dictate one to Mario."), add);
    if (focused) { input.focus(); input.setSelectionRange(...selection); }
  },

  next() {
    const suggestions = (state.next || []).filter((s) => s.action);
    setFaces("next", suggestions.length ? suggestions.map((s) => () => [
      el("div", { class: "next-text" }, s.text),
      el("div", { class: "tile-actions" },
        el("button", { class: "btn primary", type: "button", onclick: () => act(s.action) }, s.action.label || "Open"),
        el("button", { class: "btn", type: "button", onclick: async (e) => {
          const res = await post("/api/task", { text: s.text });
          if (res.ok) { e.target.textContent = "Added"; e.target.disabled = true; }
        } }, "Add task"))]) : [() => empty("No loose ends right now.")]);
  },

  projects() {
    // one repo per face, newest first, then what the agents are doing
    const repos = (data("builds").repos || []).slice(0, 3);
    const sessions = data("agent_sessions").sessions || [];
    const office = data("agent_office");
    const busy = (office.agents || []).filter((a) => /work|busy|run/i.test(a.status)).length;
    if (!repos.length) {
      return setFaces("projects", [() => empty("No git checkouts found. Set ", code("repos"), " in ~/.config/adaptive-desktop/mario.json.")]);
    }
    const repoFace = (r) => Object.assign(() => [
      el("div", { class: "between" }, el("span", { class: "big", style: "font-size:20px" }, r.name),
        el("span", { class: "chipi" }, icon("i-branch"), r.branch || "–")),
      el("div", { class: "sub", style: "-webkit-line-clamp:2;display:-webkit-box;-webkit-box-orient:vertical;white-space:normal" }, r.subject || "No commits yet"),
      el("div", { class: "kv" }, el("span", {}, whenLong(r.when)),
        r.dirty ? el("b", { style: "color:var(--warn)" }, `${r.dirty} changes`) : r.ahead ? el("b", { style: "color:var(--warn)" }, `${r.ahead} to push`)
          : r.behind ? el("b", { style: "color:var(--cyan)" }, `${r.behind} to pull`) : el("b", { style: "color:var(--ok)" }, "Up to date")),
      el("div", { style: "margin-top:auto;display:flex;gap:6px" },
        el("button", { class: "mini", type: "button", onclick: () => act({ id: "code", arg: r.path }) }, icon("i-code"), "Code"),
        el("button", { class: "mini", type: "button", onclick: () => act({ id: "terminal", arg: r.path }) }, icon("i-term"), "Terminal"))], { key: r.name });
    const agents = Object.assign(() => [
      el("div", { class: "between" }, el("span", { class: "big", style: "font-size:20px" }, "Agents"),
        el("span", { class: `meta ${sessions.length || busy ? "on" : ""}`, style: "margin:0" }, icon("i-bot"), sessions.length ? `${sessions.length} running` : "quiet")),
      sessions.length ? el("ul", { class: "rows" }, sessions.slice(0, 3).map((x) => el("li", {},
        el("span", { class: "dot" }), el("span", { class: "ttl grow" }, x.agent), el("span", { class: "sub" }, x.folder))))
        : el("div", { class: "sub" }, "No agent sessions open."),
      el("div", { class: "kv", style: "margin-top:auto" }, el("span", {}, "Agent Office"),
        el("b", {}, office.running ? (busy ? `${busy} working` : "idle") : "stopped"))], { key: "agents" });
    setFaces("projects", [...repos.map(repoFace), agents], { every: 8000, offset: 0 });
  },

  thinking() {
    const d = data("thinking_space");
    const boards = d.boards || [];
    const inbox = boards.reduce((s, b) => s + (b.inbox || []).length, 0);
    count("thinking", inbox ? `${inbox} new` : "");
    if (d.error) return fill(body("thinking"), empty(d.error));
    const ICON = { "builds-tech": ["i-code", "var(--s1)"], "career-learning": ["i-cap", "var(--s2)"], "business-income": ["i-chart", "var(--s3)"], "life-family": ["i-home", "var(--s4)"] };
    fill(body("thinking"), el("div", { class: "boards" }, boards.slice(0, 4).map((b) => {
      const [ic, col] = ICON[b.slug] || ["i-layers", hue(b.slug)];
      return el("button", { class: "board", type: "button", onclick: () => openUrl(b.url) },
        el("div", { class: "board-head" }, el("span", { class: "bi", style: `--h:${col}` }, icon(ic)),
          el("div", { class: "grow" }, el("div", { class: "ttl" }, b.title),
            el("div", { class: "sub" }, b.inbox && b.inbox.length ? `${b.inbox.length} waiting in Inbox` : "Inbox clear"))),
        el("ul", { class: "sections" }, [...(b.inbox || []).slice(0, 2).map((x) => el("li", { class: "new" }, x)),
          ...(b.sections || []).slice(0, 4 - Math.min(2, (b.inbox || []).length)).map((x) => el("li", {}, x))]));
    })));
  },

  recent() {
    // the newest files take turns at the top; the two after it sit below
    const files = (data("recent").files || []).slice(0, 4);
    if (!files.length) return setFaces("recent", [() => empty("Files you open in any app show up here.")]);
    const glyph = (f) => { const kind = kindOf(f.name); return [/Python|JavaScript|TypeScript|C\+\+|^C$|Shell|JSON|YAML|HTML|CSS/.test(kind) ? "i-code" : "i-file", hue(kind), kind]; };
    const face = (f, i) => Object.assign(() => {
      const [ic, col, kind] = glyph(f);
      const rest = [1, 2].map((k) => files[(i + k) % files.length]).filter((x) => x !== f);
      return [
        el("button", { class: "headline", type: "button", style: "flex-direction:row;align-items:center;gap:12px", onclick: () => act({ id: "open_file", arg: f.path }) },
          el("span", { class: "bi", style: `--h:${col}` }, icon(ic)),
          el("div", { style: "min-width:0" }, el("div", { class: "ttl", style: "font-size:14px" }, f.name),
            el("div", { class: "sub" }, [kind, size(f.size), whenLong(f.when)].filter(Boolean).join(" · ")))),
        el("ul", { class: "rows", style: "margin-top:auto" }, rest.map((x) => el("li", { style: "cursor:pointer", onclick: () => act({ id: "open_file", arg: x.path }) },
          el("span", { class: "ttl grow", style: "font-weight:400;color:var(--soft)" }, x.name), el("span", { class: "time" }, when(x.when)))))];
    }, { key: f.path });
    setFaces("recent", files.map(face), { every: 7000, offset: 2500, keep: (LIVE.recent && LIVE.recent.faces[LIVE.recent.i] || {}).key });
  },

  note() {
    // the capture box and the three latest notes (no turning: typing here must not be interrupted)
    const old = $("#note-in");
    const keep = old ? { value: old.value, focused: document.activeElement === old } : null;
    const items = data("notes").items || [];
    const input = el("input", { id: "note-in", class: "note-in", placeholder: "Capture a thought…", "aria-label": "Capture a thought" });
    const form = el("form", { class: "note-box", style: "padding:6px 8px 6px 12px", onsubmit: async (e) => {
      e.preventDefault(); const text = input.value; input.value = ""; if (text.trim()) await post("/api/note", { text });
    } }, input, el("button", { class: "mini", type: "submit" }, "Save"));
    fill(body("note"), form, items.length ? el("ul", { class: "rows" }, items.slice(0, 12).map((n) => {
      const [at, ...text] = n.split(" · ");
      return el("li", {}, el("span", { class: "sub grow", style: "color:var(--soft)" }, text.join(" · ")), el("span", { class: "time" }, at));
    })) : el("div", { class: "sub" }, "Kept on this laptop"));
    if (keep) { input.value = keep.value; if (keep.focused) input.focus(); }
  },

  weather() {
    const w = data("weather");
    if (w.off || w.error || w.temp == null) {
      return setFaces("weather", [() => el("div", { class: "weather" }, icon("i-cloud", "wi"),
        el("div", { class: "grow" }, el("div", { class: "ttl" }, w.place || "Weather"), el("div", { class: "sub" }, w.off ? "Off in mario.json" : "No forecast right now")))]);
    }
    const skyIcon = (sky) => /rain|drizzle|shower|thunder/i.test(sky || "") ? "i-rain" : /clear/i.test(sky || "") ? "i-sun" : "i-cloud";
    const now = () => el("div", { class: "weather" }, icon(skyIcon(w.sky), "wi"),
      el("div", {}, el("b", {}, `${w.temp}°`), el("div", { class: "sub" }, w.place)),
      el("div", { style: "margin-left:auto;text-align:right" }, el("div", { style: "font-size:13px;font-weight:600" }, w.sky),
        el("div", { class: "sub" }, `Feels ${w.feels}° · rain ${w.rain ?? 0}%`)));
    const hours = () => el("div", { class: "between", style: "gap:4px" }, (w.hours || []).slice(0, 6).map((h) =>
      el("div", { style: "text-align:center;flex:1" }, el("div", { class: "sub" }, `${h.h}:00`),
        el("div", { style: "font-size:17px;font-weight:600;margin:3px 0" }, `${h.t}°`),
        el("div", { class: "sub", style: h.rain >= 50 ? "color:var(--cyan)" : "" }, `${h.rain ?? 0}%`))));
    const day = () => el("div", { class: "weather" }, icon(skyIcon(w.sky), "wi"),
      el("div", {}, el("div", { class: "sub" }, "Today"), el("b", { style: "font-size:24px" }, `${Math.round(w.high ?? w.temp)}° / ${Math.round(w.low ?? w.temp)}°`)),
      el("div", { style: "margin-left:auto;text-align:right" }, el("div", { style: "font-size:13px;font-weight:600" }, `Rain ${w.rain ?? 0}%`),
        el("div", { class: "sub" }, w.rain >= 50 ? "Carry an umbrella" : "Dry enough")));
    $("#c-weather").classList.add("flip");
    setFaces("weather", [now, ...(w.hours && w.hours.length ? [hours] : []), day], { every: 10000, offset: 4000 });
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
          el("div", { class: "bar" }, el("i", { style: `width:${p.used || 0}%;${p.used > 80 ? "background:var(--danger)" : ""}` })),
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

  apps() {
    const available = state.config.launch || {};
    document.querySelectorAll("[data-launch]").forEach((b) => b.classList.toggle("off", available[b.dataset.launch] === false));
  },

  week() {
    // commits per day across the repos Mario watches: the last seven days, then this week against last
    const days = data("builds").activity || [];
    if (!days.length) return setFaces("week", [() => empty("Counting commits…")]);
    const last7 = days.slice(-7), prev7 = days.slice(-14, -7);
    const top = Math.max(1, ...last7);
    const names = last7.map((_, i) => { const d = new Date(); d.setDate(d.getDate() - (6 - i)); return d.toLocaleDateString(undefined, { weekday: "narrow" }); });
    const total = last7.reduce((a, b) => a + b, 0), before = prev7.reduce((a, b) => a + b, 0);
    const bars = () => [
      el("div", { class: "big" }, total, el("small", {}, `commit${total === 1 ? "" : "s"} in 7 days`)),
      el("div", { class: "week" }, last7.map((n, i) => el("span", { class: i === 6 ? "today" : "", title: `${n} commits` },
        el("i", { style: `height:${Math.round((n / top) * 100)}%` }), names[i])))];
    const best = last7.indexOf(Math.max(...last7));
    const delta = total - before;
    const compare = () => [
      el("div", { class: "big" }, delta >= 0 ? `+${delta}` : delta, el("small", {}, "on last week")),
      el("div", { class: "kv" }, el("span", {}, "This week"), el("b", {}, total)),
      el("div", { class: "kv" }, el("span", {}, "Last week"), el("b", {}, before)),
      el("div", { class: "kv" }, el("span", {}, "Busiest day"), el("b", {}, total ? new Date(Date.now() - (6 - best) * 86400000).toLocaleDateString(undefined, { weekday: "long" }) : "–")),
      el("div", { class: "kv" }, el("span", {}, "Today"), el("b", {}, last7[6]))];
    setFaces("week", [bars, compare], { every: 11000, offset: 6000 });
  },

  news() {
    // one headline at a time; the tile rolls to the next every 30 seconds (paused under the pointer)
    const n = data("news");
    const items = n.items || [];
    const src = $("#news-src");
    if (!items.length) {
      src.textContent = "";
      $("#c-news .roll").classList.remove("go");
      return setFaces("news", [() => empty(n.off ? "News is off in mario.json." : n.errors && n.errors.length ? "Feeds are not reachable right now." : "Fetching headlines…")]);
    }
    // the hub opens the article itself (Google News links are only redirect pages)
    const open = (it) => act({ id: "open_news", arg: it.link });
    const face = (it, i) => Object.assign(() => [
      el("button", { class: "headline", type: "button", title: "Open the article", onclick: () => open(it) },
        newsPic(it, "hero"),
        el("span", { class: "src" }, `${it.source}${it.when ? ` · ${when(it.when)}` : ""}`), el("b", {}, it.title)),
      el("div", { class: "upnext" }, el("h4", {}, "Up next"),
        [1, 2].map((k) => items[(i + k) % items.length]).filter((x) => x !== it)
          .map((x) => el("button", { type: "button", title: "Open the article", onclick: () => open(x) }, newsPic(x, "thumb"), el("span", {}, x.title))))], { key: it.link });
    const t = LIVE.news;
    setFaces("news", items.map(face), { every: 30000, keep: t && t.faces[t.i] ? t.faces[t.i].key : undefined });
    TURNED.news(LIVE.news, !t);
  },
  brain() {
    // who answers: Claude, Gemini while Claude is at its limit, the laptop when both are out
    const b = state.brain || {};
    const pill = $("#brain");
    pill.className = `pill ${b.engine === "claude" ? "ok" : "warn"}`;
    pill.textContent = b.engine === "claude" ? (b.model || "Claude") : b.engine === "gemini"
      ? (/limit/.test((b.skipped || {}).claude || "") ? "Gemini · Claude at its limit" : "Gemini") : b.engine ? "On this laptop" : "Claude";
    pill.title = brainLine();
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
  mail: ["mail", "daysum", "tabs"], calendar: ["today", "daysum"], tasks: ["tasks", "daysum"],
  builds: ["projects", "week"], agent_sessions: ["projects"], agent_office: ["projects"], thinking_space: ["thinking"],
  recent: ["recent"], notes: ["note"], weather: ["weather"], phone: ["phone"], news: ["news"],
  news_media: ["news"], usage: ["ai"],
};
// ------------------------------------------------------------------- tabs
// Home is one window with tabs. Today is this page; every other tab is a site ("tabs" in
// mario.json) that the desktop host keeps open in its own view, laid exactly over #web. The page
// only says which tab is up and where that rectangle is. In a plain browser there is no host, so
// a site tab offers to open in the browser instead.
const HOST = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.home;
const tell = (msg) => { if (HOST) HOST.postMessage(JSON.stringify(msg)); };
let currentTab = "today";
const siteTabs = () => state.config.tabs || [];
function drawTabs() {
  const unread = data("mail").unread;
  fill($("#tabs"), [{ id: "today", name: "Today" }, ...siteTabs()].map((t, i) =>
    el("button", { class: `tab${t.id === currentTab ? " on" : ""}`, type: "button", role: "tab", "aria-selected": String(t.id === currentTab),
      title: `Ctrl+${i + 1}`, onclick: () => selectTab(t.id) }, t.name,
      t.id === "mail" && unread ? el("span", { class: "n" }, unread > 999 ? "999+" : String(unread)) : null)));
}
function webRect() {
  const r = $("#web").getBoundingClientRect();
  return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
}
function selectTab(id) {
  const site = siteTabs().find((t) => t.id === id);
  currentTab = site ? id : "today";
  drawTabs();
  $(".main").hidden = !!site;
  $("#web").hidden = !site;
  $(".dayhead .chips").hidden = !!site;
  $("#daysum").hidden = !!site;
  if (!site) return tell({ type: "tab", id: "today" });
  fill($("#web"), HOST ? el("span", { class: "web-wait muted" }, `Opening ${site.name}…`)
    : el("button", { class: "btn", type: "button", onclick: () => openUrl(site.url) }, `Open ${site.name} in the browser`));
  // after layout, so the rectangle is the one the host should cover
  requestAnimationFrame(() => tell({ type: "tab", id: site.id, url: site.url, rect: webRect() }));
}
// What the host calls: open() each time Home is shown, closed() once it is hidden, select() for
// Ctrl+1..9 pressed while a site has the keyboard.
window.homeSpace = {
  open(tab) {
    const picture = $("#backdrop");
    picture.onload = () => { picture.hidden = false; };
    picture.onerror = () => { picture.hidden = true; };
    picture.src = `/glass.png?${Date.now()}`;        // the wallpaper may have changed since last time
    document.querySelectorAll("#home .card").forEach((card, i) => card.style.setProperty("--i", i));
    document.body.classList.remove("opening"); void document.body.offsetWidth; document.body.classList.add("opening");
    greet();
    selectTab(tab || currentTab);
  },
  closed() { cancelVoice(); $("#answer").hidden = true; },
  select(n) { const all = ["today", ...siteTabs().map((t) => t.id)]; if (all[n - 1]) selectTab(all[n - 1]); },
};

function draw(name) { try { if (name === "tabs") return drawTabs(); render[name](); } catch (e) { console.error(name, e); } }
function renderAll() { Object.keys(render).forEach(draw); renderPresence(); greet(); if (!PANEL) drawTabs(); }

function renderPresence() {
  const p = state.presence || { state: "ready" };
  document.querySelectorAll(".mark").forEach((m) => m.setAttribute("data-state", p.state));
  const sub = $("#panel-sub");
  if (sub) sub.textContent = p.detail ? `${p.state.replace("_", " ")} · ${p.detail}` : brainLine();
}
const ENGINE = { claude: "Claude", gemini: "Gemini", local: "This laptop" };
function brainLine() {
  const b = state.brain || {};
  if (!b.engine) return "Claude answers";
  const why = Object.entries(b.skipped || {}).map(([n, w]) => `${ENGINE[n] || n} is ${w}`);
  const who = b.engine === "claude" && b.model ? `Claude ${b.model}` : ENGINE[b.engine] || b.engine;
  return `${who} answers${why.length ? ` · ${why.join("; ")}` : ""}`;
}

function greet() {
  const now = new Date(), h = now.getHours();
  $("#greeting").textContent = `Good ${h < 5 ? "night" : h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"}, Karthi`;
  $("#date").textContent = now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

// -------------------------------------------------------------------- ask
function answerNode(res) {
  if (res.error) return el("div", { class: "mario" }, res.error);
  if (res.handoff) return planNode(res.handoff);
  const meta = el("div", {});
  if (res.via) meta.append(el("span", { class: "pill" }, [res.via === "Mario" ? "instant" : res.via, res.model, res.ms ? `${(res.ms / 1000).toFixed(1)} s` : ""].filter(Boolean).join(" · ")));
  return el("div", { class: "mario" }, res.answer || "", res.note ? el("span", { class: "muted" }, res.note) : null, meta);
}

function planNode(plan) {
  const out = el("pre", { hidden: true });
  return el("div", { class: "plan", "data-handoff": plan.id },
    el("div", { class: "between" }, el("b", {}, `${plan.agent || "Claude Code"} in ${plan.repo}`),
      el("span", { class: "pill warn" }, plan.outward ? "you push or send yourself" : "edits files here")),
    plan.why ? el("span", { class: "muted" }, `${plan.why}, so Gemini takes this one.`) : null,
    el("ol", {}, plan.steps.map((s) => el("li", {}, s))),
    out,
    el("div", { style: "display:flex;gap:8px;flex-wrap:wrap" },
      el("button", { class: "btn primary", type: "button", onclick: async (e) => {
        e.target.parentElement.remove(); out.hidden = false; out.textContent = "Starting…\n";
        await post(`/api/handoff/${plan.id}`, { decision: "run" });
      } }, "Run"),
      el("button", { class: "btn", type: "button", onclick: () => act({ id: plan.engine === "gemini" ? "gemini_session" : "claude_session", arg: plan.cwd }) }, "Open in terminal instead"),
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
  showAnswer(res, where);
}
function showAnswer(res, where) {
  const box = $("#answer"); box.hidden = false;
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
    } else if (msg.type === "next") { state.next = msg.items; if (!PANEL) draw("next"); }
    else if (msg.type === "presence") { state.presence = msg; renderPresence(); }
    else if (msg.type === "brain") { state.brain = msg; if (!PANEL) draw("brain"); renderPresence(); }
    else if (msg.type === "handoff") handoffEvent(msg);
  };
  ws.onclose = () => { $("#offline").hidden = false; setTimeout(() => connect(Math.min(delay * 2, 10000)), delay); };
}

document.addEventListener("DOMContentLoaded", () => {
  if (PANEL) {
    document.body.classList.add("is-panel");
    // The host calls this each time Super+J shows the panel: it comes in again, ready to talk.
    window.marioShown = () => {
      document.body.classList.remove("shown"); void document.body.offsetWidth; document.body.classList.add("shown");
      const talk = $("#panel .voice-toggle"); if (talk) talk.focus();
    };
    window.marioShown();
    $("#home").hidden = true; $("#panel").hidden = false;
    $("#panel-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#panel-input"); ask(i.value, "panel"); i.value = ""; });
    $("#panel .voice-toggle").focus();
  } else {
    $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#ask"); ask(i.value, "home"); i.value = ""; });
    document.querySelectorAll("[data-ask]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.ask, "home")));
    document.querySelectorAll("[data-launch]").forEach((b) => b.addEventListener("click", () => act({ id: "launch", arg: b.dataset.launch })));
    document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openUrl(b.dataset.open)));
    $("[data-open-hub]").addEventListener("click", () => openUrl((data("thinking_space").hub || {}).url));
    $("#c-phone").addEventListener("click", () => act({ id: "launch", arg: "phone" }));
    // Escape closes what is open, innermost first: an answer, a voice session, then Home itself
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!$("#answer").hidden) $("#answer").hidden = true;
        else if (!voiceId && !voiceBusy && $("#voice-status").hidden) tell({ type: "close" });
      } else if (e.ctrlKey && !e.altKey && !e.metaKey && /^[1-9]$/.test(e.key)) { e.preventDefault(); window.homeSpace.select(Number(e.key)); }
    });
    window.addEventListener("resize", () => { if (currentTab !== "today") tell({ type: "rect", rect: webRect() }); });
    window.homeSpace.open();
    setInterval(() => { greet(); draw("today"); }, 60000);
  }
  document.querySelectorAll(".voice-toggle").forEach((b) => b.addEventListener("click", toggleVoice));
  $("#voice-cancel").addEventListener("click", cancelVoice);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") cancelVoice(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) cancelVoice(); });
  $("#type-toggle").addEventListener("click", () => {
    const input = $("#ask"); input.hidden = !input.hidden;
    $("#voice-hint").hidden = !input.hidden;
    $("#type-toggle").textContent = input.hidden ? "Type instead" : "Use voice";
    if (!input.hidden) input.focus();
  });
  connect();
});

// The desktop host uses WebKitGTK, which has no Web Speech recognizer. Capture and recognition
// belong to the local hub; the page only starts a bounded, explicit microphone session.
let voiceId = null, voiceGeneration = 0, voiceBusy = false;
// The picture of a voice session: three strands that move with the microphone while Mario listens
// ("listening", level 0..1 from the hub), run low while it recognises and answers ("working"), and
// go away once the answer is on the page ("idle").
function wavePath(waves, height) {
  // twice the picture's width, so it can drift by one width and repeat without a seam
  const step = 600 / waves / 2;
  let d = "M0 32";
  for (let i = 0; i < waves * 4; i++) d += ` Q${(i + 0.5) * step} ${32 + (i % 2 ? height : -height)} ${(i + 1) * step} 32`;
  return d;
}
function voicePhase(phase, level = 0) {
  const box = $("#voice-status");
  if (!box.querySelector(".w1").getAttribute("d")) {
    [["w1", 3, 58], ["w2", 4, 44], ["w3", 6, 30]].forEach(([c, n, a]) => box.querySelector(`.${c}`).setAttribute("d", wavePath(n, a)));
  }
  box.dataset.phase = phase;
  box.style.setProperty("--level", phase === "listening" ? String(Math.max(0.06, Math.min(1, level))) : phase === "working" ? "0.12" : "0");
}
function voiceStatus(text, active = false, phase = "idle", level = 0) {
  $("#voice-status").hidden = !text;
  voicePhase(text ? phase : "idle", level);
  $("#voice-status span").textContent = text;
  $("#voice-cancel").textContent = active ? "Cancel" : "Dismiss";
  document.querySelectorAll(".voice-toggle").forEach((b) => {
    b.textContent = active ? "Finish speaking" : "Talk to Mario";
    b.setAttribute("aria-pressed", String(active));
  });
}
async function cancelVoice() {
  const id = voiceId; voiceId = null; voiceGeneration++; voiceBusy = false;
  voiceStatus("");
  if (id) await post("/api/voice/cancel", { id }).catch(() => {});
}
async function toggleVoice() {
  if (voiceId) { await post("/api/voice/finish", { id: voiceId }); return; }
  if (voiceBusy) return;
  voiceBusy = true;
  const generation = ++voiceGeneration;
  voiceStatus("Opening microphone…", true, "working");
  try {
    const start = await post("/api/voice/start");
    if (generation !== voiceGeneration) {
      if (start.id) await post("/api/voice/cancel", { id: start.id });
      return;
    }
    if (start.error) throw new Error(start.error);
    voiceId = start.id;
    while (voiceId && generation === voiceGeneration) {
      const result = await post("/api/voice/status", { id: voiceId });
      if (generation !== voiceGeneration) return;
      if (result.error) throw new Error(result.error);
      if (result.state === "done") {
        voiceId = null;
        voiceStatus(`Heard: “${result.text}” · Working…`, false, "working");
        if (PANEL) $("#log").append(el("div", { class: "me" }, result.text));
        const res = await post("/api/ask", { text: result.text, spoken: true });
        if (generation !== voiceGeneration) return;
        showAnswer(res, PANEL ? "panel" : "home");
        voiceStatus(res.error || res.answer || "Review Mario’s plan below, then choose Run.");
        break;
      }
      const listening = result.state === "listening";
      voiceStatus(listening ? "Listening… speak now; a pause sends your command." : "Recognizing your words on this laptop…", true,
        listening ? "listening" : "working", result.level || 0);
      // while you speak the level is read often enough for the strands to follow your voice
      await new Promise((resolve) => setTimeout(resolve, listening ? 110 : 300));
    }
  } catch (e) {
    if (generation === voiceGeneration) {
      const id = voiceId; voiceId = null;
      if (id) await post("/api/voice/cancel", { id }).catch(() => {});
      voiceStatus(e.message || "Could not reach Mario. Try again.");
    }
  } finally { if (generation === voiceGeneration) voiceBusy = false; }
}
