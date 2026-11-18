/* Fitness: choose an exercise, a workout, a challenge or the check; then the session: a guided
   demonstration and a countdown, everyone on the stage as a figure with a ring that fills
   through each repetition, per-person coaching, rest periods with the next move shown, and a
   summary. Every count, cue and timer is the server's (engine.py); this draws and asks. */
"use strict";

(() => {
  let root = null, scene = null, demo = null, pip = null, timer = null, offEvent = null;
  let tab = "train", chosen = "squat", lastSec = null, cameraView = false, sets = [];
  const cues = {}, flashes = {};

  // -- choosing ------------------------------------------------------------------------------
  function badge(key) {
    const f = K.fit(key);
    if (!f) return "";
    return f.fits ? `<span class="badge ok">Fits</span>` : `<span class="badge no">Not here</span>`;
  }

  async function chooseView() {
    const cat = await K.catalog();
    const exTile = (e) => `<button class="tile ${e.key === chosen ? "sel" : ""} ${K.fit(e.key) && !K.fit(e.key).fits ? "dim" : ""}" data-ex="${e.key}">
      ${badge(e.key)}<b>${K.esc(e.name)}</b><span>${e.kind === "hold" ? `Hold ${e.target} s` : `${e.target} reps`} · ${K.esc(e.muscles.slice(0, 2).join(", "))}</span></button>`;
    const panes = {
      train: `<div class="tiles">${cat.exercises.map(exTile).join("")}</div>`,
      plans: `<div class="tiles" style="grid-template-columns:repeat(2,minmax(0,1fr))">${cat.plans.map((p) => {
        const miss = p.steps.filter((s) => K.fit(s.exercise) && !K.fit(s.exercise).fits);
        return `<button class="tile ${miss.length ? "dim" : ""}" data-plan="${p.key}">${miss.length ? `<span class="badge no">${miss.length} won't fit</span>` : ""}
          <b>${K.esc(p.name)}</b><span>${p.steps.map((s) => `${K.esc(cat.exercises.find((e) => e.key === s.exercise).name)} ${s.target}`).join(" · ")} · rest ${p.rest} s</span></button>`;
      }).join("")}</div>`,
      race: `<div class="card"><h2>Challenge</h2><p class="soft">Most clean, full repetitions in the time wins. Up to four players.</p>
        <div class="tiles" style="margin-top:14px">${cat.exercises.filter((e) => e.kind !== "hold").map(exTile).join("")}</div>
        <div class="row" style="margin-top:14px"><span class="soft">Time</span><div class="seg" id="race-secs">${[30, 60, 90].map((s) => `<button data-secs="${s}" class="${s === 60 ? "on" : ""}">${s} s</button>`).join("")}</div></div></div>`,
      check: `<div class="card"><h2>Fitness check</h2><p class="soft">Five timed tests. Take it every ${cat.retest_days / 7} weeks and compare with your own last one: no population norms are claimed.</p>
        <div class="list" style="margin-top:12px">${cat.check.steps.map((s) => `<div class="item row"><b>${K.esc(s.label)}</b><span class="spacer"></span>${badge(s.exercise)}</div>`).join("")}</div>
        <div class="row" style="margin-top:14px"><button class="btn primary big" data-start="check">Start the check</button></div></div>`,
    };
    root.innerHTML = `<div class="choose">
      <div class="left"><div class="subtabs">${[["train", "Train"], ["plans", "Workouts"], ["race", "Challenge"], ["check", "Check"]]
        .map(([k, n]) => `<button data-tab="${k}" class="${tab === k ? "on" : ""}">${n}</button>`).join("")}</div>
        <div class="scroll">${panes[tab]}</div></div>
      <div class="detail"><div class="stage" id="f-demo"><canvas></canvas><span class="label">Demonstration</span></div>
        <div class="card" id="f-detail"></div></div></div>`;
    if (demo) demo.stop();
    demo = K.demoPlayer(root.querySelector("#f-demo canvas"), chosen, { side: chosen === "plank" });
    detail();
  }

  async function detail() {
    const cat = await K.catalog();
    const e = cat.exercises.find((x) => x.key === chosen);
    const f = K.fit(chosen);
    const el = root.querySelector("#f-detail");
    if (!el) return;
    const users = await K.users();
    const st = K.live.state;
    const opts = (sel) => `<option value="">Guest (not saved)</option>` + users.map((u) => `<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${K.esc(u.name)}</option>`).join("");
    const players = (st.players || []).map((p) => {
      const u = users.find((x) => x.id === p.profile);
      return `<div class="row"><span class="chip"><i style="background:${K.playerColour(p.slot)}"></i>P${p.slot + 1}</span>
        <select data-profile="${p.slot}">${opts(p.profile)}</select>
        <select data-load="${p.slot}" title="The weight in your hands: only what you tell it"><option value="">No weights</option>
          ${(u ? u.equipment : []).map((q) => `<option value="catalog:${q.kg}">${K.esc(q.name)} · ${q.kg} kg</option>`).join("")}<option value="ask">Other weight…</option></select>
        <span class="muted">${K.esc(K.statusWords(p))}</span><button class="btn small" data-leave="${p.slot}">Leave</button></div>`;
    }).join("");
    const spare = (st.people || []).filter((p) => p.slot === null || p.slot === undefined);
    el.innerHTML = `<div class="row"><h2>${K.esc(e.name)}</h2><span class="spacer"></span>${f ? (f.fits ? `<span class="badge ok">Fits ${f.band[0]}–${f.band[1]} m from the Kinect</span>` : `<span class="badge no">Doesn't fit here</span>`) : ""}</div>
      <p class="how">${K.esc(e.how)}</p>
      ${f && !f.fits ? `<p class="why">${K.esc(f.why)} <a href="#" data-settings>What would fit?</a></p>` : ""}
      <p class="note">About ${e.met} MET${e.met_proxy ? " (nearest Compendium entry)" : ""} · ${K.esc(e.muscles.join(", "))}</p>
      <h3>Players</h3>
      <div class="list">${players || '<p class="muted">Nobody yet: stand in view (alone, you join by being there), or raise a hand.</p>'}</div>
      ${spare.length && (st.players || []).length < 4 ? `<div class="row" style="margin-top:8px">${spare.map((p) => `<button class="btn small" data-join="${p.id}">Add the person ${p.height_cm ? `(${p.height_cm} cm)` : "in view"}</button>`).join("")}</div>` : ""}
      <div class="row" style="margin-top:16px">${tab === "race" ? "" : `<label class="field">Target <input id="f-target" type="number" min="1" max="500" value="${e.target}"> ${e.kind === "hold" ? "s" : "reps"}</label>`}
        <span class="spacer"></span><button class="btn primary big" data-start="${tab === "race" ? "race" : "free"}">Start</button></div>`;
  }

  async function start(body) {
    sets = [];
    try { await K.api("/api/workout", { action: "start", ...body }); K.sound("select"); }
    catch (err) { K.toast(err.message, "warn"); }
  }

  // -- the session ---------------------------------------------------------------------------
  function sessionView() {
    root.innerHTML = `<div class="play">
      <div class="stage" id="f-stage"><img class="video" id="f-video" alt="" hidden>
        <div class="hud"><div class="title"><small id="f-plan"></small><b id="f-name"></b></div><div class="clock" id="f-clock"></div></div>
        <div class="big-count" id="f-count" hidden></div><div class="banner" id="f-banner" hidden></div>
        <div class="pip" id="f-pip" hidden><canvas></canvas><span id="f-pip-label">How it goes</span></div></div>
      <div class="players"><div class="card" style="padding:14px 16px"><div class="steps" id="f-steps"></div>
        <div class="row" style="margin-top:12px"><button class="btn" id="f-pause">Pause</button><button class="btn" id="f-next">Next</button>
          <span class="spacer"></span><button class="btn small" id="f-cam">${cameraView ? "Figures" : "Camera"}</button><button class="btn danger" id="f-finish">Finish</button></div></div>
        <div id="f-cards" class="list"></div></div></div>`;
    scene = K.scene(root.querySelector("#f-stage"), { decorate: overHeads });
    pip = null;
    root.querySelector("#f-pause").onclick = () => K.api("/api/workout", { action: (K.live.state.workout || {}).paused ? "resume" : "pause" });
    root.querySelector("#f-next").onclick = () => K.api("/api/workout", { action: "next" });
    root.querySelector("#f-finish").onclick = () => K.api("/api/workout", { action: "finish" });
    root.querySelector("#f-cam").onclick = () => { cameraView = !cameraView; sessionView(); };
    if (cameraView) videoLoop(root.querySelector("#f-video"));
  }

  function videoLoop(img) {
    img.hidden = false;
    let seq = 0;
    const next = () => {
      if (!img.isConnected) return;
      const probe = new Image();
      probe.onload = () => { img.src = probe.src; setTimeout(next, 30); };
      probe.onerror = () => setTimeout(next, 800);
      probe.src = `/hub/frame/video.jpg?after=${seq++}&r=${Date.now()}`;
    };
    next();
  }

  function overHeads(ctx, W, H, people, r, now) {
    const w = K.live.state.workout || {};
    if (cameraView) {
      // Over the picture: the hub's 2D landmarks, mirrored like the picture.
      const size = (K.live.state.hub && K.live.state.hub.size) || [640, 480];
      const k = Math.min(W / size[0], H / size[1]), ox = (W - size[0] * k) / 2, oy = (H - size[1] * k) / 2;
      for (const p of K.live.state.people || []) {
        if (!p.skeleton) continue;
        const pts = p.skeleton.map((q, i) => (q[2] < 0.5 ? null : [ox + (1 - q[0]) * size[0] * k, oy + q[1] * size[1] * k, p.joints && p.joints[i] ? p.joints[i][3] : 1]));
        ctx.strokeStyle = p.slot === null || p.slot === undefined ? K.colour("ghost") : K.playerColour(p.slot);
        ctx.lineWidth = 5; ctx.lineCap = "round";
        for (const [a, b] of GL3.BONES) {
          if (!pts[a] || !pts[b]) continue;
          ctx.setLineDash(pts[a][2] === 2 && pts[b][2] === 2 ? [] : [8, 8]);
          ctx.beginPath(); ctx.moveTo(pts[a][0], pts[a][1]); ctx.lineTo(pts[b][0], pts[b][1]); ctx.stroke();
        }
        ctx.setLineDash([]);
      }
    }
    for (const p of people) {
      if (p.slot === null || p.slot === undefined || !p.joints || !p.joints[0]) continue;
      const at = r.project([p.joints[0][0], p.joints[0][1] + 0.42, p.joints[0][2]]);
      if (!at) continue;
      const ps = (w.players || {})[p.slot];
      const col = K.playerColour(p.slot);
      if (ps) {
        const fresh = now - (flashes[p.slot] || 0) < 450;
        K.ring(ctx, at[0], at[1], fresh ? 40 : 34, ps.kind === "hold" ? Math.min(1, ps.held / ps.target) : ps.progress, col,
          ps.kind === "hold" ? Math.floor(ps.held) : ps.reps, fresh);
      }
      const c = cues[p.slot];
      if (c && now - c.at < 3200) {
        ctx.font = "750 24px Inter, system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
        ctx.fillStyle = K.colour(c.warn ? "warn" : "yellow");
        ctx.fillText(c.text, at[0], at[1] - 54);
      }
    }
  }

  async function sessionPanel() {
    const st = K.live.state, w = st.workout || {};
    if (!root.querySelector("#f-name")) return;
    const cat = await K.catalog();
    K.$("#f-plan").textContent = w.steps.length > 1 ? `${w.plan} · ${w.index + 1} of ${w.steps.length}` : w.mode === "challenge" ? "Challenge" : w.mode === "check" ? "Fitness check" : "Training";
    K.$("#f-name").textContent = w.name;
    const clock = w.left !== null && w.left !== undefined ? Math.ceil(w.left) : w.target ? (w.kind === "hold" ? `${w.target} s` : `× ${w.target}`) : "";
    K.$("#f-clock").textContent = clock;
    K.$("#f-steps").innerHTML = w.steps.length > 1 ? w.steps.map((s, i) => `<i class="${i < w.index ? "done" : i === w.index ? "cur" : ""}" title="${K.esc(s.name)}"></i>`).join("") : "";
    K.$("#f-pause").textContent = w.paused ? "Resume" : "Pause";
    // Countdown with ticks, and the demonstration in the corner while it counts and during rests.
    const count = K.$("#f-count");
    if (w.phase === "ready" && !w.paused) {
      const sec = Math.ceil(w.left || 0);
      count.hidden = false; count.textContent = sec || "Go";
      if (sec !== lastSec) { K.sound(sec ? "tick" : "go"); lastSec = sec; }
    } else { count.hidden = true; lastSec = null; }
    const showPip = w.phase === "ready" || w.phase === "rest";
    const pipEl = K.$("#f-pip");
    pipEl.hidden = !showPip;
    const pipKey = w.phase === "rest" && w.steps[w.index + 1] ? w.steps[w.index + 1].exercise : w.exercise;
    if (showPip) {
      if (!pip) pip = K.demoPlayer(pipEl.querySelector("canvas"), pipKey, { ground: GL3.rgba("shade") });
      else if (pip.key !== pipKey) pip.set(pipKey);
      pip.key = pipKey;
      K.$("#f-pip-label").textContent = w.phase === "rest" ? `Next: ${cat.exercises.find((e) => e.key === pipKey)?.name || ""}` : "How it goes";
    } else if (pip) { pip.stop(); pip = null; }
    // Banners: paused, rest, lost, unsafe.
    const banner = K.$("#f-banner");
    const players = st.players || [];
    const lost = players.filter((p) => p.lost);
    const warn = players.find((p) => p.warning && p.status === "active");
    let html = null, cls = "";
    if (w.paused) html = w.held_by === "tracking" ? `<b>Waiting for you</b><small>Step back into view: the clock is stopped</small>` : `Paused<small>Both hands up (hold) or Resume to carry on</small>`;
    else if (w.phase === "rest") html = `Rest · ${Math.ceil(w.left)} s<small>Next: ${K.esc(w.steps[w.index + 1] ? w.steps[w.index + 1].name : "")}</small>`;
    else if (w.phase === "go" && lost.length && lost.length === players.length) { html = `<b>I've lost you</b><small>Step back into view. Nothing counts until I can see you.</small>`; cls = "warn"; }
    else if (w.phase === "go" && warn) { html = `<b>Player ${warn.slot + 1}</b>: ${K.esc(warn.warning)}`; cls = "warn top"; }
    banner.hidden = !html; banner.className = `banner ${cls}`; if (html) banner.innerHTML = html;
    // Player cards.
    const now = performance.now();
    K.$("#f-cards").innerHTML = players.map((p) => {
      const s = (w.players || {})[p.slot];
      const c = cues[p.slot];
      const state = p.lost ? K.statusWords(p) : p.warning ? p.warning : s && s.unsure ? "Can't see the joints this needs: not counting" : "";
      if (!s) return `<div class="pcard ${p.lost ? "lost" : ""}" style="--pc:${K.playerColour(p.slot)}"><canvas data-ring="${p.slot}"></canvas>
        <div><div class="who">Player ${p.slot + 1}</div><div class="cue warn">${K.esc(state || "Waiting to see you")}</div></div></div>`;
      const big = s.kind === "hold" ? `${Math.floor(s.held)}<small> / ${s.target} s</small>` : `${s.reps}<small>${s.target ? ` / ${s.target}` : ""}</small>`;
      const meta = [];
      if (s.form !== undefined) meta.push(`form <b>${s.form}%</b>`);
      if (s.partials) meta.push(`<b>${s.partials}</b> not deep enough`);
      if (s.tempo_s) meta.push(`<b>${s.tempo_s}</b> s a rep`);
      if (s.sides) meta.push(`L <b>${s.sides.left}</b> · R <b>${s.sides.right}</b>`);
      if (s.jump_best_cm) meta.push(`best jump <b>${s.jump_best_cm} cm</b>`);
      if (s.sway_cm !== undefined && s.sway_cm !== null) meta.push(`sway <b>${s.sway_cm} cm</b>`);
      if (s.reach_cm !== undefined) meta.push(`hands <b>${s.reach_cm} cm</b> off the floor`);
      const cue = state ? `<div class="cue warn">${K.esc(state)}</div>` : c && now - c.at < 4000 ? `<div class="cue">${K.esc(c.text)}</div>` : `<div class="cue">${s.done ? "Done!" : ""}</div>`;
      return `<div class="pcard ${p.lost ? "lost" : ""}" style="--pc:${K.playerColour(p.slot)}"><canvas data-ring="${p.slot}" width="184" height="184"></canvas>
        <div><div class="who">Player ${p.slot + 1}</div><div class="n">${big}</div><div class="meta">${meta.join(" · ")}</div>${cue}</div></div>`;
    }).join("") || '<div class="card"><p class="soft">Step in front of the TV to play.</p></div>';
    for (const cv of root.querySelectorAll("[data-ring]")) {
      const s = (w.players || {})[cv.dataset.ring];
      const ctx = cv.getContext("2d"); cv.width = 184; cv.height = 184;
      K.ring(ctx, 92, 92, 70, s ? (s.kind === "hold" ? Math.min(1, s.held / s.target) : s.progress) : 0, K.playerColour(+cv.dataset.ring));
    }
  }

  function summary(e) {
    if (!sets.length) return;
    const q = e.quality || {};
    const body = sets.map((s) => `<div class="item"><b>Player ${s.slot + 1} · ${K.esc(s.name)}</b>: ${s.held !== null && s.held !== undefined && !s.reps ? `${s.held} s held` : `${s.reps} reps`}${s.form !== null && s.form !== undefined ? `, form ${s.form}%` : ""}${s.load_kg ? `, ${s.load_kg} kg (${s.load_source})` : ""}${s.kcal ? `, about ${s.kcal} kcal` : ""}
      ${s.next ? `<br><span class="soft">Next time: ${K.esc(s.next.say)}</span>` : ""}</div>`).join("");
    const seen = Object.entries(q).map(([slot, x]) => `<div class="item">Player ${+slot + 1}: seen <b>${Math.round(100 * x.seen_share)}%</b> of the time${x.losses ? `, lost ${x.losses}×` : ""}${x.updates_per_s ? ` · ${x.updates_per_s} updates/s` : ""}${x.dark_share ? ` · ${Math.round(100 * x.dark_share)}% in infrared` : ""}</div>`).join("");
    K.sound("done");
    K.modal(`<h1>Well done</h1><div class="list">${body}</div>${seen ? `<h3 style="margin-top:18px;color:var(--muted)">How well the Kinect saw you</h3><div class="list">${seen}</div>` : ""}
      <div class="row" style="margin-top:20px"><button class="btn primary big" data-close>Done</button><button class="btn" data-close onclick="K.go('history')">History</button></div>`);
    sets = [];
  }

  function onEvent(e) {
    const now = performance.now();
    if (e.type === "rep" || e.type === "rep-both") { flashes[e.slot] = now; K.sound("rep"); if (e.say) cues[e.slot] = { text: e.say, at: now }; }
    else if (["cue", "partial", "unsure"].includes(e.type)) cues[e.slot] = { text: e.say, at: now, warn: e.type === "unsure" };
    else if (e.type === "set") sets.push(e);
    else if (e.type === "workout-done") summary(e);
    else if (e.type === "safety" && e.warning) cues[e.slot] = { text: e.warning, at: now, warn: true };
    else if (e.type === "tracking" && e.lost && (K.live.state.workout || {}).phase === "go") { K.sound("lost"); cues[e.slot] = { text: "I've lost you", at: now, warn: true }; }
    else if (e.type === "rest") K.sound("pass");
  }

  // -- the section ---------------------------------------------------------------------------
  let shown = null;
  function render() {
    const w = K.live.state.workout || {};
    const want = w.mode && w.mode !== "idle" ? "session" : "choose";
    if (want !== shown) {
      if (scene) { scene.stop(); scene = null; }
      if (demo) { demo.stop(); demo = null; }
      if (pip) { pip.stop(); pip = null; }
      shown = want;
      if (want === "session") sessionView(); else chooseView();
    }
    if (want === "session") sessionPanel();
  }

  function mount(el, rest) {
    root = el;
    if (rest && rest[0]) { chosen = rest[0]; }
    shown = null;
    render();
    timer = setInterval(() => {
      render();
      if (shown === "choose" && !root.contains(document.activeElement) && Date.now() % 2000 < 260) detail();
    }, 250);
    offEvent = K.on("event", onEvent);
    el.addEventListener("click", async (ev) => {
      const t = ev.target.closest("button, a[data-settings]");
      if (!t) return;
      if (t.dataset.tab) { tab = t.dataset.tab; chooseView(); }
      if (t.dataset.ex) { chosen = t.dataset.ex; for (const x of root.querySelectorAll("[data-ex]")) x.classList.toggle("sel", x.dataset.ex === chosen); demo && demo.set(chosen); detail(); }
      if (t.dataset.secs) for (const b of t.parentElement.children) b.classList.toggle("on", b === t);
      if (t.dataset.plan) start({ mode: "plan", plan: t.dataset.plan });
      if (t.dataset.start === "free") start({ mode: "free", exercise: chosen, target: +(root.querySelector("#f-target") || {}).value || undefined });
      if (t.dataset.start === "race") start({ mode: "challenge", exercise: chosen, seconds: +(root.querySelector("#race-secs .on") || {}).dataset?.secs || 60 });
      if (t.dataset.start === "check") start({ mode: "check" });
      if (t.dataset.leave !== undefined) { await K.api("/api/player", { slot: +t.dataset.leave, leave: true }); detail(); }
      if (t.dataset.join !== undefined) { await K.api("/api/player", { slot: 0, join: +t.dataset.join }); detail(); }
      if (t.dataset.settings !== undefined) { ev.preventDefault(); K.settings(); }
    });
    el.addEventListener("change", async (ev) => {
      const t = ev.target;
      if (t.dataset.profile !== undefined) await K.api("/api/player", { slot: +t.dataset.profile, profile: t.value ? +t.value : null });
      else if (t.dataset.load !== undefined) {
        let load = [];
        if (t.value === "ask") { const kg = parseFloat(prompt("Weight in each hand, in kilograms?") || ""); if (kg > 0) load = [{ source: "confirmed", kg }]; }
        else if (t.value) load = [{ source: "catalog", kg: parseFloat(t.value.split(":")[1]) }];
        await K.api("/api/player", { slot: +t.dataset.load, load });
      }
    });
  }

  K.section("fitness", {
    title: "Fitness", mount,
    unmount() { clearInterval(timer); if (offEvent) offEvent(); for (const x of [scene, demo, pip]) if (x) x.stop(); scene = demo = pip = null; shown = null; },
    key(e) { if (e.key === " " && shown === "session") { e.preventDefault(); K.api("/api/workout", { action: (K.live.state.workout || {}).paused ? "resume" : "pause" }); } },
    back() { if (shown === "session") { K.api("/api/workout", { action: "finish" }); return true; } return false; },
  });
})();
