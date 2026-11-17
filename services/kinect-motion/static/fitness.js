/* Kinect Fitness: the stage (everyone's skeleton, rep rings, cues) and the side panel
   (players, choosing a workout, the live scoreboard, history). State arrives from /ws. */
"use strict";

const $ = (id) => document.getElementById(id);
const { esc, api } = Motion;
let catalog = null, users = [], state = { people: [], players: [], workout: { mode: "idle" } };
let connected = false, chosen = "squat", cameraOn = false, lastPanel = 0;
const cues = {};          // slot -> {text, at}
const flashes = {};       // slot -> time of the last repetition
let sets = [], compare = {};

// -- the live feed -------------------------------------------------------------------------------
Motion.connect((msg) => {
  state = msg.state;
  for (const e of msg.events) onEvent(e);
  const now = performance.now();
  if (now - lastPanel > 180) { lastPanel = now; panels(); }
}, (ok) => { connected = ok; Motion.status($("status"), state, ok); });

function onEvent(e) {
  const now = performance.now();
  if (e.type === "rep" || e.type === "rep-both") {
    flashes[e.slot] = now;
    if (e.say) cues[e.slot] = { text: e.say, at: now };
  } else if (["cue", "partial", "unsure"].includes(e.type)) {
    cues[e.slot] = { text: e.say, at: now };
  } else if (e.type === "set") {
    sets.push(e);
  } else if (e.type === "check-compare") {
    compare[e.slot] = e.compare;
  } else if (e.type === "workout-done") {
    showResults();
  } else if (e.type === "safety" && e.warning) {
    cues[e.slot] = { text: e.warning, at: now };
  }
}

// -- the stage, every animation frame ------------------------------------------------------------
function draw() {
  const [ctx, W, H] = Motion.fit($("view"));
  ctx.clearRect(0, 0, W, H);
  const w = state.workout || {};
  const now = performance.now();
  const label = (p, pts) => {
    if (p.slot === null || p.slot === undefined) return;
    const head = pts[0] || pts[11];
    if (!head) return;
    const col = Motion.playerColour(p.slot);
    const ps = (w.players || {})[p.slot];
    const x = head[0], y = head[1] - 70;
    if (ps) {
      // The ring fills through each repetition; the number is the count so far.
      const r = 34;
      Motion.ring(ctx, x, y, r, ps.kind === "hold" ? Math.min(1, ps.held / ps.target) : ps.progress, col);
      const fresh = now - (flashes[p.slot] || 0) < 450;
      ctx.fillStyle = fresh ? Motion.colour("yellow") : Motion.colour("text");
      ctx.font = `800 ${fresh ? 34 : 28}px Inter, system-ui`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(ps.kind === "hold" ? Math.floor(ps.held) : ps.reps, x, y + 1);
    } else {
      ctx.fillStyle = col; ctx.font = "700 18px Inter, system-ui"; ctx.textAlign = "center";
      ctx.fillText(`P${p.slot + 1}`, x, y + 20);
    }
    const c = cues[p.slot];
    if (c && now - c.at < 3500) {
      ctx.font = "700 22px Inter, system-ui"; ctx.textAlign = "center";
      ctx.fillStyle = Motion.colour("yellow");
      ctx.fillText(c.text, x, y - 52);
    }
  };
  const overVideo = cameraOn && (state.people || []).some((p) => p.skeleton);
  if (overVideo) Motion.drawOverVideo(ctx, W, H, state.people, state.hub && state.hub.size, label);
  else Motion.drawPeople(ctx, W, H, state.people || [], label);
  if (!(state.people || []).length) {
    ctx.fillStyle = Motion.colour("muted"); ctx.font = "600 24px Inter, system-ui"; ctx.textAlign = "center";
    ctx.fillText("Stand 2 to 3.5 metres from the TV, facing it", W / 2, H / 2);
  }
  // Countdown and banners.
  const count = $("count");
  if (w.phase === "ready" && !w.paused) { count.hidden = false; count.textContent = Math.ceil(w.left || 0) || "Go"; }
  else count.hidden = true;
  const banner = $("banner");
  const warn = (state.players || []).find((p) => p.warning && p.here);
  if (w.paused) { banner.hidden = false; banner.className = "banner"; banner.textContent = "Paused · both hands up to carry on"; }
  else if (w.phase === "rest") { banner.hidden = false; banner.className = "banner"; banner.textContent = `Rest · ${Math.ceil(w.left)} s · next: ${w.steps[w.index + 1] ? w.steps[w.index + 1].name : ""}`; }
  else if (warn) { banner.hidden = false; banner.className = "banner warn"; banner.textContent = `Player ${warn.slot + 1}: ${warn.warning}`; }
  else banner.hidden = true;
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// -- the side panel ------------------------------------------------------------------------------
function panels() {
  Motion.status($("status"), state, connected);
  $("voice").classList.toggle("on", !!state.voice);
  playersPanel();
  const w = state.workout || { mode: "idle" };
  $("setup").hidden = w.mode !== "idle";
  $("session").hidden = w.mode === "idle";
  if (w.mode !== "idle") sessionPanel(w);
}

function playersPanel() {
  const el = $("players");
  const focused = el.contains(document.activeElement);
  if (focused) return;                         // do not redraw a select while it is open
  const opts = (sel) => `<option value="">Guest (not saved)</option>` + users.map((u) =>
    `<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${esc(u.name)}</option>`).join("");
  el.innerHTML = (state.players || []).map((p) => {
    const u = users.find((x) => x.id === p.profile);
    const equip = u ? u.equipment : [];
    return `<div class="player">
      <span class="swatch" style="background:${Motion.playerColour(p.slot)}"></span>
      <div class="who">
        <div class="row"><b>Player ${p.slot + 1}</b>${p.here ? "" : ' <span class="muted">· stepped out</span>'}
          ${p.height_cm ? `<span class="muted num">${p.height_cm} cm</span>` : ""}</div>
        <div class="row">
          <select data-profile="${p.slot}">${opts(p.profile)}</select>
          <select data-load="${p.slot}" title="The weight in your hands: only what you tell it">
            <option value="">No weights</option>
            ${equip.map((e) => `<option value="catalog:${e.kg}">${esc(e.name)} · ${e.kg} kg</option>`).join("")}
            <option value="ask">Other weight…</option>
          </select>
        </div>
        ${p.warning ? `<div class="warnline">${esc(p.warning)}</div>` : ""}
      </div>
      <button class="btn" data-leave="${p.slot}">Leave</button></div>`;
  }).join("") || '<p class="muted">Nobody yet.</p>';
  const playing = new Set((state.players || []).map((p) => p.slot));
  const spare = (state.people || []).filter((p) => p.slot === null || p.slot === undefined);
  $("spare").innerHTML = spare.length && playing.size < 4 ? `<div class="row">${spare.map((p) =>
    `<button class="btn" data-join="${p.id}">Add person ${p.id}${p.height_cm ? ` · ${p.height_cm} cm` : ""}</button>`).join("")}</div>` : "";
}

document.addEventListener("change", async (ev) => {
  const t = ev.target;
  if (t.dataset.profile !== undefined) {
    await api("/api/player", { slot: +t.dataset.profile, profile: t.value ? +t.value : null });
  } else if (t.dataset.load !== undefined) {
    let load = [];
    if (t.value === "ask") {
      const kg = parseFloat(prompt("Weight in each hand, in kilograms?") || "");
      if (kg > 0) load = [{ source: "confirmed", kg }];
    } else if (t.value) load = [{ source: "catalog", kg: parseFloat(t.value.split(":")[1]) }];
    await api("/api/player", { slot: +t.dataset.load, load });
  }
});
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button");
  if (!t) return;
  if (t.dataset.leave !== undefined) await api("/api/player", { slot: +t.dataset.leave, leave: true });
  if (t.dataset.join !== undefined) await api("/api/player", { slot: 0, join: +t.dataset.join });
  if (t.dataset.tab) {
    for (const b of $("tabs").children) b.classList.toggle("on", b === t);
    for (const p of document.querySelectorAll("[data-pane]")) p.hidden = p.dataset.pane !== t.dataset.tab;
    if (t.dataset.tab === "history") history();
  }
  if (t.dataset.ex) { chosen = t.dataset.ex; exerciseTiles(); }
  if (t.dataset.plan) await start({ mode: "plan", plan: t.dataset.plan });
  if (t.dataset.delequip) { await api("/api/equipment", { delete: +t.dataset.delequip }); await loadUsers(); history(); }
  if (t.dataset.deluser && confirm("Forget this person and all their results?")) {
    await api(`/api/users/${t.dataset.deluser}`, undefined, "DELETE"); await loadUsers(); history();
  }
  if (t.id === "add-equip") {
    const kg = parseFloat($("eq-kg").value);
    if (kg > 0) { await api("/api/equipment", { user: +$("who").value, name: $("eq-name").value, kg }); await loadUsers(); history(); }
  }
});

function sessionPanel(w) {
  $("s-plan").textContent = w.steps.length > 1 ? `${w.plan} · ${w.index + 1} of ${w.steps.length}` :
    w.mode === "challenge" ? "Challenge" : "Training";
  $("s-name").textContent = w.name;
  $("s-how").textContent = w.how;
  $("s-timer").textContent = w.left !== null && w.left !== undefined ? `${Math.ceil(w.left)}` :
    w.target ? `${w.kind === "hold" ? `${w.target} s` : `× ${w.target}`}` : "";
  $("s-steps").innerHTML = w.steps.length > 1 ? w.steps.map((s, i) =>
    `<i class="${i < w.index ? "done" : i === w.index ? "cur" : ""}" title="${esc(s.name)}"></i>`).join("") : "";
  $("pause").textContent = w.paused ? "Resume" : "Pause";
  const now = performance.now();
  const rows = (state.players || []).map((p) => {
    const s = (w.players || {})[p.slot];
    if (!s) return `<div class="score"><span class="swatch" style="background:${Motion.playerColour(p.slot)}"></span><div class="muted">Player ${p.slot + 1}: waiting to see you</div><span></span></div>`;
    const big = s.kind === "hold" ? `${Math.floor(s.held)}<small> / ${s.target} s</small>` :
      `${s.reps}<small>${s.target ? ` / ${s.target}` : ""}</small>`;
    const meta = [];
    if (s.form !== undefined) meta.push(`form <b>${s.form}%</b>`);
    if (s.partials) meta.push(`<b>${s.partials}</b> not deep enough`);
    if (s.tempo_s) meta.push(`<b>${s.tempo_s}</b> s a rep`);
    if (s.sides) meta.push(`L <b>${s.sides.left}</b> · R <b>${s.sides.right}</b>`);
    if (s.jump_best_cm) meta.push(`best jump <b>${s.jump_best_cm} cm</b>`);
    if (s.sway_cm !== undefined && s.sway_cm !== null) meta.push(`sway <b>${s.sway_cm} cm</b>`);
    if (s.reach_cm !== undefined) meta.push(`hands <b>${s.reach_cm} cm</b> off the floor`);
    const c = cues[p.slot];
    const cue = s.unsure ? '<div class="unsure">Can\'t see you well enough: not counting</div>' :
      c && now - c.at < 4000 ? `<div class="cue">${esc(c.text)}</div>` : '<div class="cue"></div>';
    return `<div class="score"><span class="swatch" style="background:${Motion.playerColour(p.slot)}"></span>
      <div><div class="big">${big}</div><div class="meta">${meta.join(" · ")}</div>${cue}</div>
      <span class="muted">${s.done ? "Done" : ""}</span></div>`;
  });
  $("s-scores").innerHTML = rows.join("") || '<p class="muted">Step in front of the TV.</p>';
}

// -- choosing ------------------------------------------------------------------------------------
async function start(body) {
  sets = []; compare = {};
  try { await api("/api/workout", { action: "start", ...body }); } catch (err) { alert(err.message); }
}

function exerciseTiles() {
  $("exercises").innerHTML = catalog.exercises.map((e) => `<button class="tile ${e.key === chosen ? "sel" : ""}" data-ex="${e.key}">
    <b>${esc(e.name)}</b><span>${e.kind === "hold" ? `hold ${e.target} s` : `${e.target} reps`} · ${esc(e.muscles.slice(0, 2).join(", "))}</span></button>`).join("");
  const e = catalog.exercises.find((x) => x.key === chosen);
  $("target").value = e.target;
  $("ex-how").textContent = `${e.how} About ${e.met} MET${e.met_proxy ? " (nearest Compendium entry)" : ""}.`;
}

async function loadCatalog() {
  catalog = await api("/api/catalog");
  exerciseTiles();
  $("plans").innerHTML = catalog.plans.map((p) => `<button class="tile" data-plan="${p.key}">
    <b>${esc(p.name)}</b><span>${p.steps.map((s) => `${esc(catalog.exercises.find((e) => e.key === s.exercise).name)} ${s.target}`).join(" · ")} · rest ${p.rest} s</span></button>`).join("");
  $("race-ex").innerHTML = catalog.exercises.filter((e) => e.kind !== "hold").map((e) => `<option value="${e.key}">${esc(e.name)}</option>`).join("");
  $("check-steps").innerHTML = catalog.check.steps.map((s) => `<div class="item"><b>${esc(s.label)}</b></div>`).join("");
}

async function loadUsers() {
  users = await api("/api/users");
  const sel = $("who"), cur = sel.value;
  sel.innerHTML = users.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("") || "<option value=''>No one yet</option>";
  if (cur) sel.value = cur;
}

async function history() {
  const uid = +$("who").value;
  const el = $("hist");
  if (!uid) { el.innerHTML = '<p class="muted">Add a person below, then pick them as a player before you start.</p>'; $("equip").innerHTML = ""; return; }
  const h = await api(`/api/history?user=${uid}`);
  const t = h.totals, u = users.find((x) => x.id === uid) || {};
  const due = h.checks.length ? Math.max(0, catalog.retest_days - Math.floor((Date.now() / 1000 - h.checks[0].at) / 86400)) : null;
  el.innerHTML = `<h3>Last 7 days</h3><div class="stats">
      <div class="stat"><b>${t.sessions}</b><span>workouts</span></div>
      <div class="stat"><b>${t.reps}</b><span>repetitions</span></div>
      <div class="stat"><b>${t.minutes}</b><span>minutes moving</span></div>
      <div class="stat"><b>${u.kg ? `~${t.kcal}` : "–"}</b><span>kcal, estimated</span></div>
      <div class="stat"><b>${t.volume || "–"}</b><span>kg lifted</span></div>
      <div class="stat"><b>${t.streak}</b><span>day streak</span></div></div>
    <h3>Fitness checks</h3><div class="list">${h.checks.slice(0, 3).map((c) => `<div class="item"><b>${new Date(c.at * 1000).toLocaleDateString()}</b> ${Object.entries(c.results).map(([k, v]) => `${esc(k)}: ${Object.entries(v).filter(([, x]) => x !== null).map(([a, x]) => `${a.replace(/_/g, " ")} ${x}`).join(", ")}`).join(" · ")}</div>`).join("") || '<p class="muted">None yet: take the check to get a baseline.</p>'}</div>
    ${due !== null ? `<p class="note">Next check ${due ? `in ${due} days` : "is due now"}.</p>` : ""}
    <h3>Recent workouts</h3><div class="list">${h.sessions.slice(0, 8).map((s) => `<div class="item"><b>${new Date(s.started * 1000).toLocaleString()}</b> · ${esc(s.plan || "")}<br>${s.sets.map((x) => `${esc(x.exercise)} ${x.reps}${x.form !== null ? ` (${Math.round(x.form)}%)` : ""}${x.load_kg ? ` @ ${x.load_kg} kg` : ""}`).join(", ")}</div>`).join("") || '<p class="muted">No workouts yet.</p>'}</div>
    <p class="note">Calories are estimates (MET × body weight × time, 2024 Compendium), not measurements.</p>`;
  $("equip").innerHTML = `<h3>${esc(u.name || "")}'s weights</h3><div class="list">${(u.equipment || []).map((e) => `<div class="item row">${esc(e.name)} · <b>${e.kg} kg</b> <button class="btn" data-delequip="${e.id}">Remove</button></div>`).join("")}</div>
    <div class="row" style="margin-top:8px"><input id="eq-name" type="text" placeholder="e.g. Blue dumbbells" maxlength="40"><input id="eq-kg" type="number" min="0.5" max="100" step="0.5" placeholder="kg"><button class="btn" id="add-equip">Add weight</button></div>
    <p class="note">The Kinect cannot see how heavy a weight is, so a load is recorded only from what you register or type here.</p>
    <div class="row" style="margin-top:10px"><button class="btn danger" data-deluser="${uid}">Forget ${esc(u.name || "")}</button></div>`;
}

function showResults() {
  if (!sets.length) return;
  const body = sets.map((s) => `<div class="item"><b>Player ${s.slot + 1} · ${esc(s.name)}</b>: ${s.held !== null && s.held !== undefined && !s.reps ? `${s.held} s held` : `${s.reps} reps`}${s.form !== null ? `, form ${s.form}%` : ""}${s.load_kg ? `, ${s.load_kg} kg (${s.load_source})` : ""}${s.kcal ? `, about ${s.kcal} kcal` : ""}
    ${s.next ? `<br><span class="soft">Next time: ${esc(s.next.say)}</span>` : ""}
    ${s.check ? `<br><span class="soft">${Object.entries(s.check).filter(([, v]) => v !== null).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ")}</span>` : ""}</div>`).join("");
  const cmp = Object.entries(compare).map(([slot, c]) => `<h3>Player ${+slot + 1} against the last check</h3><div class="list">${Object.entries(c).map(([k, v]) => `<div class="item">${esc(k.replace(/[._]/g, " "))}: <b class="${v}">${v}</b></div>`).join("")}</div>`).join("");
  $("results-body").innerHTML = `<div class="list">${body}</div>${cmp}`;
  $("results").hidden = false;
}

// -- buttons -------------------------------------------------------------------------------------
$("start-free").onclick = () => start({ mode: "free", exercise: chosen, target: +$("target").value || undefined });
$("start-race").onclick = () => start({ mode: "challenge", exercise: $("race-ex").value, seconds: +$("race-secs").value });
$("start-check").onclick = () => start({ mode: "check" });
$("pause").onclick = () => api("/api/workout", { action: (state.workout || {}).paused ? "resume" : "pause" });
$("next").onclick = () => api("/api/workout", { action: "next" });
$("finish").onclick = () => api("/api/workout", { action: "finish" });
$("results-close").onclick = () => { $("results").hidden = true; };
$("refresh").onclick = history;
$("who").onchange = history;
$("add-user").onclick = async () => {
  const name = $("new-name").value.trim();
  if (!name) return;
  await api("/api/users", { name, kg: parseFloat($("new-kg").value) || null });
  $("new-name").value = ""; $("new-kg").value = "";
  await loadUsers(); history();
};
$("voice").onclick = () => api("/api/settings", { voice: !state.voice });
$("camera").onclick = () => { cameraOn = !cameraOn; $("camera").classList.toggle("on", cameraOn); $("video").hidden = !cameraOn; };
Motion.video($("video"), () => cameraOn);

loadCatalog().then(loadUsers);
