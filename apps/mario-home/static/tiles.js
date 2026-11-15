// Home's own tiles (Watch next, Sticky note, Storage, Spotify, Photos), the weather's moving sky,
// the accounts sheet and Mario's orb in the panel. Loaded after home.js, whose helpers (el, fill,
// data, post, act, render, FEEDS ...) it uses; like there, everything shown comes from the hub.
"use strict";

const bytes = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(b >= 1e10 ? 0 : 1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`);
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function svgEl(tag, attrs, ...kids) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  node.append(...kids);
  return node;
}
// redraw a tile without losing where its list was scrolled to
function keepScroll(card, build) {
  const old = body(card).querySelector(".scroll");
  const top = old ? old.scrollTop : 0;
  build();
  const now = body(card).querySelector(".scroll");
  if (now) now.scrollTop = top;
}

// A tile whose data just changed shows it: one pass of light across it. (Not for the ones that
// change every few seconds while they play or while you type.)
window.cardChanged = (name) => {
  if (name === "spotify" || name === "sticky" || name === "news_media") return;
  for (const r of FEEDS[name] || []) {
    const tile = $(`#c-${r}`);
    if (!tile) continue;
    tile.classList.remove("fresh"); void tile.offsetWidth; tile.classList.add("fresh");
    setTimeout(() => tile.classList.remove("fresh"), 1100);
  }
};

// Every refresh button: read that card again now, turn while it does, then say when.
const refreshedAt = {};
async function refreshCard(button) {
  const card = button.dataset.refresh;
  if (button.classList.contains("busy")) return;
  button.classList.add("busy");
  try {
    const res = await post("/api/refresh", { card });
    if (res.ok) {
      refreshedAt[card] = Date.now();
      button.title = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}`;
      (FEEDS[card] || []).forEach(draw);
      window.cardChanged(card);
    } else showAnswer({ error: res.error || "Could not refresh." }, "home");
  } catch (_) { showAnswer({ error: "Mario Hub is not answering. Try again." }, "home"); }
  button.classList.remove("busy");
}

// ------------------------------------------------------------------ movies
render.movies = () => {
  const m = data("movies");
  const items = m.items || [];
  count("movies", m.left || "");
  $("#movies-sheet").hidden = !m.sheet;
  if (!items.length) return fill(body("movies"), empty(m.error || "Reading your list…"));
  const by = Object.fromEntries(items.map((i) => [i.title, i]));
  const seen = (it) => el("button", { class: `seen${it.watched ? " on" : ""}`, type: "button", "aria-pressed": String(!!it.watched),
    title: it.watched ? "Watched. Click to take the mark off" : "Mark as watched",
    "aria-label": `${it.watched ? "Watched" : "Not watched"}: ${it.title}`,
    onclick: (e) => { e.currentTarget.classList.toggle("on"); post("/api/movie", { title: it.title, watched: !it.watched }); } }, icon("i-check"));
  const about = (it) => [it.where, it.year, it.type !== "Movie" ? it.type : ""].filter(Boolean).join(" · ");
  const pick = (label, title) => {
    const it = by[title];
    return it ? el("div", { class: `pick${it.watched ? " done" : ""}` }, el("span", { class: "strip", "aria-hidden": "true" }),
      el("div", { class: "grow" }, el("span", { class: "when" }, label), el("div", { class: "ttl" }, it.title), el("div", { class: "sub" }, about(it))),
      seen(it)) : null;
  };
  const rest = items.filter((i) => i.title !== m.today && i.title !== m.tomorrow);
  keepScroll("movies", () => fill(body("movies"),
    el("div", { class: "picks" }, pick("Today", m.today), pick("Tomorrow", m.tomorrow)),
    el("ul", { class: "rows scroll movie-list" }, rest.map((it) => el("li", { class: it.watched ? "done" : "" },
      el("div", { class: "grow" }, el("div", { class: "ttl" }, it.title), el("div", { class: "sub" }, about(it))), seen(it)))),
    el("div", { class: "sub tally" }, `${m.watched} watched · ${m.left} to go`)));
};

// ------------------------------------------------------------- sticky note
// One note you scribble on. It saves itself as you type; "Tidy with Mario" has Mario rewrite it as
// clean notes, file them on today's page of Mario Notes and hand the sticky back empty.
let stickyTimer = 0, stickyDirty = false, stickyBusy = false;
async function saveSticky() {
  const area = $("#sticky-text");
  if (!area || !stickyDirty) return;
  stickyDirty = false;
  try { await post("/api/sticky", { text: area.value }); $("#sticky-state").textContent = "Saved"; }
  catch (_) { stickyDirty = true; $("#sticky-state").textContent = "Not saved yet"; }
}
async function tidySticky() {
  const area = $("#sticky-text");
  if (stickyBusy || !area.value.trim()) return;
  stickyBusy = true;
  clearTimeout(stickyTimer); stickyDirty = true; await saveSticky();
  const paper = $("#c-sticky .paper");
  paper.classList.add("tidying"); $("#sticky-state").textContent = "Mario is tidying…";
  let res;
  try { res = await post("/api/sticky/tidy"); } catch (_) { res = { error: "Mario Hub is not answering. Your note is still here." }; }
  paper.classList.remove("tidying");
  stickyBusy = false;
  if (res.ok) {
    area.value = "";
    paper.classList.add("filed"); setTimeout(() => paper.classList.remove("filed"), 700);
    $("#sticky-state").textContent = "Filed";
    showAnswer({ answer: `Filed in Mario Notes:\n\n${res.text}`, via: res.via || "Mario", note: res.note }, "home");
  } else { $("#sticky-state").textContent = ""; showAnswer({ error: res.error || "Could not tidy the note." }, "home"); }
  render.sticky();
}
render.sticky = () => {
  const s = data("sticky");
  let area = $("#sticky-text");
  if (!area) {
    area = el("textarea", { id: "sticky-text", spellcheck: "false", "aria-label": "Sticky note", placeholder: "Scribble anything here…" });
    area.addEventListener("input", () => {
      stickyDirty = true; $("#sticky-state").textContent = "";
      clearTimeout(stickyTimer); stickyTimer = setTimeout(saveSticky, 700);
      $("#sticky-tidy").disabled = !area.value.trim();
    });
    area.addEventListener("blur", () => { clearTimeout(stickyTimer); saveSticky(); });
    fill(body("sticky"), el("div", { class: "paper" }, el("i", { class: "tape", "aria-hidden": "true" }), area),
      el("div", { class: "foot" },
        el("button", { class: "btn primary", type: "button", id: "sticky-tidy", onclick: tidySticky }, icon("i-spark"), "Tidy with Mario"),
        el("button", { class: "link", type: "button", id: "sticky-filed", hidden: true })));
    area.value = s.text || "";
  } else if (document.activeElement !== area && !stickyDirty && !stickyBusy) area.value = s.text || "";
  $("#sticky-tidy").disabled = !area.value.trim();
  const filed = $("#sticky-filed");
  filed.hidden = !s.filed;
  filed.textContent = `${s.filed} filed today`;
  filed.onclick = () => act({ id: "open_place", arg: s.page });
};

// ----------------------------------------------------------------- storage
let storageAsk = null, storageBusy = null, storageFreed = null;
async function clearPlace(p) {
  if (storageAsk !== p.id) { storageAsk = p.id; storageFreed = null; return render.storage(); }   // first press asks
  storageAsk = null; storageBusy = p.id; render.storage();
  let res;
  try { res = await post("/api/storage/clear", { id: p.id }); } catch (_) { res = { error: "Mario Hub is not answering." }; }
  storageBusy = null;
  if (res.ok) storageFreed = `${p.label}: ${bytes(res.freed)} freed`; else showAnswer({ error: res.error || "Could not clear it." }, "home");
  render.storage();
}
render.storage = () => {
  const s = data("storage");
  if (s.total == null) return fill(body("storage"), empty(s.error || "Measuring the disk…"));
  const R = 30, C = 2 * Math.PI * R, pct = Math.min(100, s.pct || 0);
  const ring = svgEl("svg", { viewBox: "0 0 76 76", class: `ring${pct > 85 ? " hot" : ""}`, "aria-hidden": "true" },
    svgEl("circle", { cx: 38, cy: 38, r: R, class: "track" }),
    svgEl("circle", { cx: 38, cy: 38, r: R, class: "used", "stroke-dasharray": C.toFixed(1), style: `--full:${C.toFixed(1)};--left:${(C * (1 - pct / 100)).toFixed(1)}` }));
  const top = Math.max(1, ...(s.places || []).map((p) => p.bytes), ...(s.folders || []).map((f) => f.bytes));
  const place = (p) => el("li", { class: "place" },
    el("div", { class: "grow" },
      el("div", { class: "between" }, el("span", { class: "ttl" }, p.label), el("b", {}, bytes(p.bytes))),
      el("div", { class: "bar thin" }, el("i", { style: `--w:${Math.max(3, Math.round(p.bytes * 100 / top))}%` })),
      el("div", { class: "sub" }, p.admin ? [p.hint, ": ", code(p.admin)] : p.hint)),
    p.clear ? el("button", { class: `mini${storageAsk === p.id ? " danger" : ""}`, type: "button", disabled: storageBusy === p.id,
      onclick: () => clearPlace(p) }, storageBusy === p.id ? "Clearing…" : storageAsk === p.id ? `Clear ${bytes(p.bytes)}?` : "Clear")
      : p.admin ? null : el("button", { class: "mini", type: "button", onclick: () => act({ id: "open_place", arg: p.path }) }, "Open"));
  const folder = (f) => el("li", { class: "place" },
    el("button", { class: "grow mrow", type: "button", title: "Open in Files", onclick: () => act({ id: "open_place", arg: f.path }) },
      el("div", { class: "grow" }, el("div", { class: "between" }, el("span", { class: "ttl" }, f.name), el("b", {}, bytes(f.bytes))),
        el("div", { class: "bar thin soft" }, el("i", { style: `--w:${Math.max(3, Math.round(f.bytes * 100 / top))}%` })))));
  keepScroll("storage", () => fill(body("storage"),
    el("div", { class: "disk" }, el("div", { class: "gauge" }, ring, el("b", {}, `${Math.round(pct)}%`)),
      el("div", { class: "grow" }, el("div", { class: "big" }, bytes(s.free), el("small", {}, "free")),
        el("div", { class: "sub" }, `${bytes(s.used)} used of ${bytes(s.total)}`),
        el("div", { class: "sub gain" }, storageFreed || (s.reclaim ? `${bytes(s.reclaim)} can be cleared here` : "Nothing worth clearing")))),
    el("div", { class: "scroll" },
      (s.places || []).length ? el("h4", {}, "Take space back") : null,
      el("ul", { class: "rows" }, (s.places || []).map(place)),
      (s.folders || []).length ? el("h4", {}, "Biggest folders in Home") : null,
      el("ul", { class: "rows" }, (s.folders || []).map(folder)))));
};

// ----------------------------------------------------------------- spotify
// Built once and then patched, so the bars and the turning cover never restart when the hub sends
// the next position.
let spot = { pos: 0, len: 0, at: 0, playing: false };
async function spotCmd(cmd) { const r = await post("/api/spotify", { cmd }).catch(() => ({ error: "Mario Hub is not answering." })); if (r.error) showAnswer(r, "home"); }
render.spotify = () => {
  const s = data("spotify");
  const tile = $("#c-spotify");
  const playing = s.running && s.status === "Playing";
  tile.classList.toggle("playing", !!playing);
  $("#spotify-meta").textContent = !s.running ? "" : s.is_spotify === false ? `from ${s.player}` : playing ? "Playing" : "Paused";
  if (!s.running || !s.title) {
    spot = { pos: 0, len: 0, at: 0, playing: false };
    return fill(body("spotify"), el("div", { class: "sp-idle" },
      el("div", { class: "eq big", "aria-hidden": "true" }, [0, 1, 2, 3, 4].map(() => el("i"))),
      el("div", { class: "sub" }, s.running ? "Nothing is playing" : "Spotify is closed"),
      el("button", { class: "btn primary", type: "button", onclick: () => (s.installed === false ? openUrl("https://open.spotify.com/") : act({ id: "launch", arg: "spotify" })) },
        icon("i-play"), "Open Spotify")));
  }
  if (!$("#sp-root")) {
    fill(body("spotify"), el("div", { id: "sp-root", class: "sp" },
      el("div", { class: "sp-top" },
        el("div", { class: "sp-art" }, el("img", { id: "sp-img", alt: "", draggable: "false" }), icon("i-music")),
        el("div", { class: "grow" }, el("div", { class: "ttl", id: "sp-title" }), el("div", { class: "sub", id: "sp-artist" }),
          el("div", { class: "eq", "aria-hidden": "true" }, [0, 1, 2, 3].map(() => el("i"))))),
      el("div", { class: "sp-time" }, el("span", { id: "sp-pos" }), el("div", { class: "bar thin" }, el("i", { id: "sp-bar" })), el("span", { id: "sp-len" })),
      el("div", { class: "sp-ctl" },
        el("button", { type: "button", "aria-label": "Previous track", onclick: () => spotCmd("previous") }, icon("i-prev")),
        el("button", { type: "button", class: "go", id: "sp-play", onclick: () => spotCmd("playpause") }, icon("i-play")),
        el("button", { type: "button", "aria-label": "Next track", onclick: () => spotCmd("next") }, icon("i-skip")))));
  }
  $("#sp-title").textContent = s.title; $("#sp-title").title = s.album ? `${s.title} · ${s.album}` : s.title;
  $("#sp-artist").textContent = s.artist || s.album || "";
  const img = $("#sp-img"), src = s.art ? `/news-img/${s.art}` : "";
  if (img.getAttribute("src") !== src) { if (src) img.setAttribute("src", src); else img.removeAttribute("src"); }
  img.hidden = !src;
  const play = $("#sp-play");
  play.setAttribute("aria-label", playing ? "Pause" : "Play");
  play.querySelector("use").setAttribute("href", playing ? "#i-pause" : "#i-play");
  spot = { pos: s.position || 0, len: s.length || 0, at: Date.now(), playing };
  spotTick();
};
function spotTick() {
  const bar = $("#sp-bar");
  if (!bar || !spot.len) return;
  const pos = Math.min(spot.len, spot.pos + (spot.playing ? (Date.now() - spot.at) / 1000 : 0));
  bar.style.width = `${(pos * 100 / spot.len).toFixed(2)}%`;
  $("#sp-pos").textContent = clock(pos); $("#sp-len").textContent = clock(spot.len);
}
setInterval(() => { if (!document.hidden && spot.playing) spotTick(); }, 500);

// ------------------------------------------------------------------ photos
// Your shared album, turning by itself: each picture drifts a little while it is up, then gives way
// to the next. Back, pause and forward are on the tile; a click opens the picture across the screen.
const PHOTO_EVERY = 7000;
let photoI = 0, photoAt = 0, photoPaused = false, photoList = [], photoSetup = false;
const photoSrc = (i) => `/photo/${photoList[(i + photoList.length) % photoList.length].name}`;
function showPhoto(i, dir = 1) {
  if (!photoList.length) return;
  photoI = (i + photoList.length) % photoList.length;
  photoAt = Date.now();
  const stage = $("#ph-stage");
  if (stage) {
    const next = el("img", { class: `ph ${dir < 0 ? "back" : ""}`, alt: "", draggable: "false", src: photoSrc(photoI) });
    next.style.setProperty("--pan", `${(photoI % 3) - 1}`);
    stage.querySelectorAll("img.ph").forEach((old) => { old.classList.add("gone"); setTimeout(() => old.remove(), 1300); });
    stage.prepend(next);
    $("#photos-meta").textContent = `${photoI + 1} / ${photoList.length}`;
  }
  if (!$("#lightbox").hidden) { $("#lb-img").src = photoSrc(photoI); $("#lb-count").textContent = `${photoI + 1} / ${photoList.length}`; drawStrip(); }
  new Image().src = photoSrc(photoI + 1);            // the next one is ready before its turn
}
// The viewer's strip: every picture of the album, small, to pick one from
let stripKey = "";
function drawStrip() {
  const strip = $("#lb-strip"), key = photoList.map((p) => p.name).join();
  if (key !== stripKey) {
    stripKey = key;
    fill(strip, ...photoList.map((p, i) => el("button", { type: "button", role: "option", "aria-label": `Photo ${i + 1}`,
      onclick: () => showPhoto(i, i < photoI ? -1 : 1) }, el("img", { alt: "", loading: "lazy", draggable: "false", src: `/photo/${p.name}?thumb=1` }))));
  }
  [...strip.children].forEach((b, i) => { b.classList.toggle("on", i === photoI); b.setAttribute("aria-selected", String(i === photoI)); });
  const now = strip.children[photoI];
  if (now) strip.scrollTo({ left: now.offsetLeft - (strip.clientWidth - now.offsetWidth) / 2, behavior: "smooth" });
}
function photoPause(on) {
  photoPaused = on;
  for (const [sel, label] of [["#ph-play", "the slideshow"], ["#lb-play", "the slideshow"]]) {
    const b = $(sel); if (!b) continue;
    b.querySelector("use").setAttribute("href", on ? "#i-play" : "#i-pause");
    b.setAttribute("aria-label", `${on ? "Play" : "Pause"} ${label}`);
  }
}
function lightbox(open) {
  const box = $("#lightbox");
  if (open && !photoList.length) return;
  box.hidden = !open;
  if (open) { tell({ type: "tab", id: "today" }); $("#lb-img").src = photoSrc(photoI); $("#lb-count").textContent = `${photoI + 1} / ${photoList.length}`; drawStrip(); $("#lb-close").focus(); }
}
async function saveAlbum(input, note) {
  note.textContent = "Looking at the album…";
  let res;
  try { res = await post("/api/photos", { album: input.value.trim() }); } catch (_) { res = { error: "Mario Hub is not answering." }; }
  if (res.ok) { photoSetup = false; note.textContent = "Fetching your photos…"; } else note.textContent = res.error || "That did not work.";
}
render.photos = () => {
  const p = data("photos");
  photoList = p.items || [];
  const tile = $("#c-photos");
  if (p.setup || photoSetup || !photoList.length) {
    tile.classList.remove("has-photos");
    $("#photos-meta").textContent = "";
    if ($("#ph-album") && document.activeElement === $("#ph-album")) return;      // you are typing the link
    const input = el("input", { id: "ph-album", placeholder: "https://photos.app.goo.gl/…", "aria-label": "Shared album link", value: p.album || "" });
    const note = el("div", { class: "sub", style: "white-space:normal" }, p.error || (photoList.length || !p.album ? "" : "Fetching your photos…"));
    return fill(body("photos"), el("div", { class: "ph-setup" }, icon("i-image", "big-ic"),
      el("div", { class: "ttl" }, "Your Google Photos, here"),
      el("div", { class: "sub", style: "white-space:normal" }, "In Google Photos open an album, choose Share, then Create link, and paste that link."),
      el("form", { class: "note-box", onsubmit: (e) => { e.preventDefault(); saveAlbum(input, note); } }, input, el("button", { class: "mini", type: "submit" }, "Show")),
      note, photoList.length ? el("button", { class: "link", type: "button", onclick: () => { photoSetup = false; render.photos(); } }, "Keep the current album") : null));
  }
  tile.classList.add("has-photos");
  if (!$("#ph-stage")) {
    fill(body("photos"), el("div", { class: "ph-wrap" },
      el("button", { id: "ph-stage", class: "ph-stage", type: "button", "aria-label": "Open this photo across the screen", onclick: () => lightbox(true) }),
      el("div", { class: "ph-ctl" },
        el("button", { type: "button", "aria-label": "Previous photo", onclick: () => showPhoto(photoI - 1, -1) }, icon("i-back")),
        el("button", { type: "button", id: "ph-play", "aria-label": "Pause the slideshow", onclick: () => photoPause(!photoPaused) }, icon("i-pause")),
        el("button", { type: "button", "aria-label": "Next photo", onclick: () => showPhoto(photoI + 1) }, icon("i-chev")),
        el("span", { class: "grow" }),
        el("button", { type: "button", "aria-label": "Choose another album", title: "Choose another album", onclick: () => { photoSetup = true; render.photos(); } }, icon("i-gear")),
        el("button", { type: "button", "aria-label": "Open the album in Google Photos", title: "Open in Google Photos", onclick: () => openUrl(data("photos").album) }, icon("i-out")),
        el("button", { type: "button", "aria-label": "Full screen", title: "Full screen", onclick: () => lightbox(true) }, icon("i-expand")))));
    showPhoto(Math.min(photoI, photoList.length - 1));
  } else {
    if (photoI >= photoList.length) showPhoto(photoList.length - 1);
    $("#photos-meta").textContent = `${photoI + 1} / ${photoList.length}`;
    if (!$("#lightbox").hidden) drawStrip();
  }
  $("#ph-stage").title = p.title || "";
};
setInterval(() => {
  if (document.hidden || photoPaused || photoList.length < 2 || document.body.classList.contains("away")) return;
  const open = !$("#lightbox").hidden;
  if (!open && (!$("#ph-stage") || $("#c-photos").matches(":hover, :focus-within"))) return;
  if (Date.now() - photoAt >= PHOTO_EVERY) showPhoto(photoI + 1);
}, 500);

// ----------------------------------------------------------------- weather
// The weather tile's sky does what the sky is doing: rain falls, clouds drift, the sun turns, stars
// come out after dark. The pieces are made once per scene and moved by the stylesheet.
let skyScene = null;
const rnd = (a, b) => a + Math.random() * (b - a);
function paintSky(scene) {
  if (scene === skyScene) return;
  skyScene = scene;
  const sky = $("#c-weather .sky");
  const [kind, night] = [scene.replace("-night", ""), scene.endsWith("-night")];
  $("#c-weather").dataset.scene = kind; $("#c-weather").dataset.night = String(night);
  const many = (n, cls, style) => Array.from({ length: n }, (_, i) => el("i", { class: cls, style: style(i) }));
  const parts = [];
  if (kind === "clear") parts.push(night ? el("i", { class: "moon" }) : el("i", { class: "sun" }, el("b")));
  if (night && (kind === "clear" || kind === "clouds")) parts.push(...many(22, "star", () => `left:${rnd(2, 98).toFixed(1)}%;top:${rnd(4, 70).toFixed(1)}%;animation-delay:${rnd(0, 4).toFixed(2)}s;--s:${rnd(1, 2.4).toFixed(1)}px`));
  if (kind !== "clear") parts.push(...many(kind === "clouds" || kind === "fog" ? 4 : 3, "cloud", (i) => `top:${(-18 + i * 17 + rnd(-4, 4)).toFixed(0)}%;--w:${rnd(110, 190).toFixed(0)}px;animation-duration:${rnd(28, 52).toFixed(0)}s;animation-delay:-${rnd(0, 40).toFixed(0)}s`));
  if (kind === "rain" || kind === "storm" || kind === "drizzle") parts.push(...many(kind === "drizzle" ? 16 : 34, "drop", () => `left:${rnd(-4, 100).toFixed(1)}%;animation-duration:${rnd(0.55, 1.05).toFixed(2)}s;animation-delay:-${rnd(0, 1.2).toFixed(2)}s;--l:${rnd(9, 20).toFixed(0)}px`));
  if (kind === "snow") parts.push(...many(26, "flake", () => `left:${rnd(0, 100).toFixed(1)}%;animation-duration:${rnd(3.5, 7).toFixed(1)}s;animation-delay:-${rnd(0, 7).toFixed(1)}s;--s:${rnd(2, 5).toFixed(1)}px`));
  if (kind === "storm") parts.push(el("i", { class: "flash" }));
  if (kind === "fog") parts.push(...many(3, "mist", (i) => `top:${20 + i * 26}%;animation-delay:-${i * 4}s`));
  fill(sky, parts);
}
const weatherBase = render.weather;
render.weather = () => {
  weatherBase();
  const w = data("weather");
  paintSky(w.off || w.error || w.temp == null ? "clouds" : w.scene || "clouds");
};

// -------------------------------------------------------------- AI assistants
const aiBase = render.ai;
render.ai = () => {
  aiBase();
  const at = (state.cards.usage || {}).at;
  const seen = Math.max(refreshedAt.usage || 0, at ? at * 1000 : 0);
  $("#ai-at").textContent = seen ? new Date(seen).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
  // the bars grow to their value each time they are drawn
  document.querySelectorAll("#c-ai .bar i").forEach((i) => { i.style.setProperty("--w", i.style.width); i.style.width = ""; });
};

// ---------------------------------------------------------------- accounts
// A Google tab (Mail, Calendar) shows one chip per account: the chip takes that tab to that account,
// through Google's own account chooser, which asks you to sign in when you have not yet.
const tabAccount = {};
const accountsNow = () => data("accounts").accounts || [];
function accountUrl(site, user) {
  const u = new URL(site.url);
  let dest;
  if (u.hostname === "mail.google.com") dest = `https://mail.google.com/mail/u/${user}/`;
  else { u.pathname = u.pathname.replace(/\/u\/\d+\//, "/"); u.searchParams.set("authuser", user); dest = u.toString(); }
  return `https://accounts.google.com/AccountChooser?Email=${encodeURIComponent(user)}&continue=${encodeURIComponent(dest)}`;
}
window.drawAccts = () => {
  const site = siteTabs().find((t) => t.id === currentTab);
  const box = $("#accts");
  const accounts = accountsNow();
  const google = site && /(^|\.)google\.com$/.test(new URL(site.url).hostname);
  box.hidden = !google || !accounts.length;
  if (box.hidden) return;
  const chosen = tabAccount[site.id] || (accounts.find((a) => a.main) || accounts[0]).user;
  const unread = Object.fromEntries(((data("mail").accounts) || []).map((a) => [a.user, a.unread]));
  fill(box, accounts.map((a) => el("button", { class: `acct${a.user === chosen ? " on" : ""}`, type: "button", role: "tab", "aria-selected": String(a.user === chosen),
    title: a.user, onclick: () => { tabAccount[site.id] = a.user; tell({ type: "go", id: site.id, url: accountUrl(site, a.user) }); window.drawAccts(); } },
    el("span", { class: "nm" }, a.user.split("@")[0]), a.main ? el("small", {}, "main") : null,
    site.id === "mail" && unread[a.user] ? el("span", { class: "n" }, unread[a.user] > 999 ? "999+" : String(unread[a.user])) : null)));
};

let sheetNote = "", sheetRemove = null;
async function accountEdit(change) {
  let res;
  try { res = await post("/api/accounts", change); } catch (_) { res = { error: "Mario Hub is not answering." }; }
  sheetNote = res.ok ? "" : res.error || "That did not work.";
  if (res.ok) document.querySelectorAll("#sheet-body input").forEach((i) => { if (i.dataset.key && i.dataset.key.startsWith(change.user || "")) i.value = ""; });
  render.sheet();
  return res.ok;
}
function openSheet(open) {
  $("#sheet").hidden = !open;
  sheetNote = ""; sheetRemove = null;
  if (open) { tell({ type: "tab", id: "today" }); render.sheet(); $("#sheet-close").focus(); } else selectTab(currentTab);
}
const toggle = (on, label, change) => el("button", { class: `switch${on ? " on" : ""}`, type: "button", role: "switch", "aria-checked": String(!!on), "aria-label": label, onclick: change }, el("i"));
render.sheet = () => {
  if ($("#sheet").hidden) return;
  const d = data("accounts");
  const typed = Object.fromEntries([...document.querySelectorAll("#sheet-body input")].map((i) => [i.dataset.key, i.value]));
  const focus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
  const field = (key, attrs) => el("input", { "data-key": key, autocomplete: "off", ...attrs });
  const secret = (a, what, has, placeholder, label) => {
    const input = field(`${a.user}:${what}`, { type: what === "mail" ? "password" : "url", placeholder, "aria-label": label });
    return el("form", { class: "note-box", onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) accountEdit({ op: "secret", user: a.user, what, secret: input.value }); } },
      input, el("button", { class: "mini", type: "submit" }, has ? "Replace" : "Save"));
  };
  const row = (a) => el("li", { class: "acct-row" },
    el("div", { class: "acct-head" }, el("span", { class: "avatar", style: `--h:${hue(a.user)}` }, a.user[0].toUpperCase()),
      el("div", { class: "grow" }, el("div", { class: "ttl" }, a.user), el("div", { class: "sub" }, a.main ? "Main account: shown first" : "")),
      a.main ? null : el("button", { class: "mini", type: "button", onclick: () => accountEdit({ op: "main", user: a.user }) }, "Make main"),
      el("button", { class: `mini${sheetRemove === a.user ? " danger" : ""}`, type: "button", onclick: () => {
        if (sheetRemove !== a.user) { sheetRemove = a.user; return render.sheet(); }
        sheetRemove = null; accountEdit({ op: "remove", user: a.user });
      } }, sheetRemove === a.user ? "Remove it?" : "Remove")),
    el("div", { class: "sync" },
      el("div", { class: "sync-line" }, icon("i-mail"), el("div", { class: "grow" }, el("div", { class: "ttl" }, "Mail"),
        el("div", { class: "sub" }, !a.mail ? "Not synced: no unread count for this account" : a.has_password ? "Synced: unread count and badge" : "Needs an app password to count unread mail")),
        toggle(a.mail, `Sync mail for ${a.user}`, () => accountEdit({ op: "sync", user: a.user, what: "mail", on: !a.mail }))),
      a.mail ? secret(a, "mail", a.has_password, a.has_password ? "New app password" : "Google app password (16 letters)", `App password for ${a.user}`) : null,
      a.mail && !a.has_password ? el("button", { class: "link", type: "button", onclick: () => openUrl("https://myaccount.google.com/apppasswords") }, "Create an app password", icon("i-out")) : null,
      el("div", { class: "sync-line" }, icon("i-cal"), el("div", { class: "grow" }, el("div", { class: "ttl" }, "Calendar"),
        el("div", { class: "sub" }, !a.calendar ? "Not synced: its events stay off Today" : a.has_calendar ? "Synced: its events show on Today" : "Needs the calendar's secret iCal address")),
        toggle(a.calendar, `Sync the calendar of ${a.user}`, () => accountEdit({ op: "sync", user: a.user, what: "calendar", on: !a.calendar }))),
      a.calendar ? secret(a, "calendar", a.has_calendar, a.has_calendar ? "New secret iCal address" : "Secret address in iCal format (…/basic.ics)", `Calendar address for ${a.user}`) : null));
  const add = field("new", { type: "email", placeholder: "name@gmail.com", "aria-label": "Add an account" });
  fill($("#sheet-body"),
    el("p", { class: "sub", style: "white-space:normal" }, "Switch between accounts with the chips beside the Mail and Calendar tabs; the first time, Google asks you to sign in to that account inside Home. The switches decide what Home reads for each account."),
    d.waiting ? el("p", { class: "empty" }, d.error) : null,
    el("ul", { class: "acct-list scroll" }, (d.accounts || []).map(row)),
    el("form", { class: "note-box", onsubmit: async (e) => { e.preventDefault(); if (add.value.trim() && await accountEdit({ op: "add", user: add.value.trim() })) add.value = ""; } },
      icon("i-plus"), add, el("button", { class: "mini", type: "submit" }, "Add account")),
    sheetNote ? el("p", { class: "empty warn" }, sheetNote) : null);
  document.querySelectorAll("#sheet-body input").forEach((i) => {
    if (typed[i.dataset.key]) i.value = typed[i.dataset.key];
    if (focus && i.dataset.key === focus) i.focus();
  });
};

// -------------------------------------------------------------- Mario's orb
// The panel's picture of Mario: rings that turn slowly while it waits, a ring that takes the shape
// of your voice while it listens (the microphone's level, from the hub), arcs that race while it
// thinks, and waves that leave the ring and travel outward while it talks back.
function startOrb() {
  const cv = $("#orb");
  const ctx = cv.getContext("2d");
  const css = getComputedStyle(document.documentElement);
  const rgb = (name) => {                       // a token's colour as numbers, so it can be drawn at any strength
    const probe = el("i", { style: `color:${css.getPropertyValue(name).trim()}` });
    document.body.append(probe);
    const out = getComputedStyle(probe).color.match(/[\d.]+/g).slice(0, 3).join(",");
    probe.remove();
    return out;
  };
  const ink = { a: rgb("--mario"), b: rgb("--mario-2"), c: rgb("--blue"), t: rgb("--text"), w: rgb("--warn") };
  const col = (k, alpha) => `rgba(${ink[k]},${alpha})`;
  const orb = { level: 0, heard: 0, phase: "idle", spin: 0, last: 0, ripples: [], lastRipple: 0 };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.marioVoice = (phase, level) => { orb.phase = phase; orb.heard = phase === "listening" ? level : 0; };
  const CAPTION = { ready: "Tap or press Space to talk", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…", doing: "Working…", needs_you: "Needs you" };
  const WAVES = [[3, 1.7, 0.42], [5, -2.6, 0.28], [8, 3.9, 0.18], [13, -5.3, 0.12]];     // lobes, turn rate, share

  function fit() {
    const box = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    cv.width = Math.round(box.width * d); cv.height = Math.round(box.height * d);
  }
  function frame(ts) {
    requestAnimationFrame(frame);
    if (document.hidden) return;
    const dt = Math.min(0.05, (ts - orb.last) / 1000 || 0);
    orb.last = ts;
    const t = ts / 1000;
    const st = orb.phase === "listening" ? "listening" : orb.phase === "working" ? "thinking" : (state.presence || {}).state || "ready";
    if (cv.dataset.state !== st) { cv.dataset.state = st; $("#orb-caption").textContent = CAPTION[st] || ""; $("#orb-talk").setAttribute("aria-label", st === "listening" ? "Finish speaking" : "Talk to Mario"); }
    // how far the ring swells: your voice, Mario's own speech (syllables and breaths), or a slow breath
    let want = 0.05 + 0.03 * Math.sin(t * 1.1);
    if (st === "listening") want = Math.max(0.1, orb.heard);
    else if (st === "speaking") want = 0.22 + 0.62 * Math.abs(Math.sin(t * 7.3)) * (0.55 + 0.45 * Math.sin(t * 2.1 + 1)) * (Math.sin(t * 0.9) > -0.75 ? 1 : 0.15);
    else if (st === "thinking" || st === "doing") want = 0.13 + 0.04 * Math.sin(t * 5);
    orb.level += (want - orb.level) * Math.min(1, dt * (want > orb.level ? 16 : 7));
    orb.spin += dt * ({ ready: 0.22, listening: 0.55, thinking: 2.4, doing: 1.5, speaking: 0.8, needs_you: 0.15 }[st] || 0.3) * (still ? 0 : 1);
    if ((st === "speaking" || st === "listening") && orb.level > 0.42 && ts - orb.lastRipple > (st === "speaking" ? 300 : 420) && !still) {
      orb.ripples.push({ age: 0, k: st === "speaking" ? "b" : "c" });
      orb.lastRipple = ts;
    }

    const W = cv.width, H = cv.height, cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.21;
    const main = st === "needs_you" ? "w" : "a";
    ctx.clearRect(0, 0, W, H);
    ctx.lineCap = "round";

    // waves that left the ring
    orb.ripples = orb.ripples.filter((r) => (r.age += dt) < 1.5);
    for (const r of orb.ripples) {
      const p = r.age / 1.5;
      ctx.beginPath(); ctx.arc(cx, cy, R * (1.05 + p * 1.25), 0, Math.PI * 2);
      ctx.strokeStyle = col(r.k, 0.5 * (1 - p) ** 1.6); ctx.lineWidth = R * 0.03 * (1 - p * 0.6); ctx.stroke();
    }
    // the glow at the centre
    const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * (1.25 + orb.level * 0.7));
    glow.addColorStop(0, col(main, 0.5 + orb.level * 0.4)); glow.addColorStop(0.45, col("b", 0.14 + orb.level * 0.2)); glow.addColorStop(1, col("b", 0));
    ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cy, R * 2, 0, Math.PI * 2); ctx.fill();

    // the turning rings: long arcs, shorter arcs the other way, then a ring of ticks
    const arcs = (radius, n, sweep, turn, key, alpha, width) => {
      ctx.strokeStyle = col(key, alpha); ctx.lineWidth = width;
      for (let i = 0; i < n; i++) {
        const a0 = turn + (i * Math.PI * 2) / n;
        ctx.beginPath(); ctx.arc(cx, cy, radius, a0, a0 + sweep); ctx.stroke();
      }
    };
    arcs(R * 1.5, 3, 1.5, orb.spin, "b", 0.55, R * 0.035);
    arcs(R * 1.72, 2, 2.3, -orb.spin * 0.7 + 1, main, 0.4, R * 0.022);
    arcs(R * 1.93, 48, 0.035, orb.spin * 0.35, "t", 0.22, R * 0.03);
    if (st === "thinking" || st === "doing") {                 // a light that runs the inner ring
      const a = orb.spin * 1.6;
      ctx.beginPath(); ctx.arc(cx + Math.cos(a) * R * 1.5, cy + Math.sin(a) * R * 1.5, R * 0.07, 0, Math.PI * 2);
      ctx.fillStyle = col("t", 0.95); ctx.fill();
    }

    // the voice ring: a circle bent by a few waves, as deep as the level
    const ring = (scale, key, alpha, width, sign) => {
      ctx.beginPath();
      for (let i = 0; i <= 180; i++) {
        const th = (i / 180) * Math.PI * 2;
        let n = 0;
        for (const [lobes, rate, share] of WAVES) n += share * Math.sin(lobes * th + t * rate * (still ? 0 : 1));
        const r = R * scale * (1 + sign * orb.level * 0.55 * n);
        const x = cx + Math.cos(th) * r, y = cy + Math.sin(th) * r;
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      }
      ctx.closePath(); ctx.strokeStyle = col(key, alpha); ctx.lineWidth = width; ctx.stroke();
    };
    ring(1.0, "c", 0.35, R * 0.02, -1);
    ring(1.0, "b", 0.9, R * 0.04, 1);
    ring(0.86, main, 0.75, R * 0.028, 1);
    // the core
    ctx.beginPath(); ctx.arc(cx, cy, R * (0.2 + orb.level * 0.22), 0, Math.PI * 2);
    ctx.fillStyle = col("t", 0.92); ctx.fill();
  }
  fit();
  window.addEventListener("resize", fit);
  requestAnimationFrame(frame);
}

// --------------------------------------------------------------------- wiring
document.addEventListener("DOMContentLoaded", () => {
  if (PANEL) {
    startOrb();
    // Space talks to Mario unless you are typing
    document.addEventListener("keydown", (e) => {
      if (e.code === "Space" && !e.target.closest("input, textarea, button")) { e.preventDefault(); toggleVoice(); }
    });
    return;
  }
  document.querySelectorAll("[data-refresh]").forEach((b) => b.addEventListener("click", () => refreshCard(b)));
  $("#movies-sheet").addEventListener("click", () => openUrl(data("movies").sheet));
  $("#accounts-btn").addEventListener("click", () => openSheet(true));
  $("#sheet-close").addEventListener("click", () => openSheet(false));
  $("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") openSheet(false); });
  $("#lb-prev").addEventListener("click", () => showPhoto(photoI - 1, -1));
  $("#lb-next").addEventListener("click", () => showPhoto(photoI + 1));
  $("#lb-play").addEventListener("click", () => photoPause(!photoPaused));
  $("#lb-close").addEventListener("click", () => lightbox(false));
  $("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox" || e.target.id === "lb-img") lightbox(false); });
  // Escape and the arrows belong to what is open on top, before Home's own Escape
  document.addEventListener("keydown", (e) => {
    const box = !$("#lightbox").hidden, sheet = !$("#sheet").hidden;
    if (!box && !sheet) return;
    if (e.key === "Escape") { e.stopPropagation(); if (box) lightbox(false); else openSheet(false); }
    else if (box && e.key === "ArrowLeft") showPhoto(photoI - 1, -1);
    else if (box && e.key === "ArrowRight") showPhoto(photoI + 1);
    else if (box && e.key === " ") { e.preventDefault(); photoPause(!photoPaused); }
  }, true);
});
