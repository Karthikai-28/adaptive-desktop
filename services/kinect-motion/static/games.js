/* Games: Wall Dodge, Pose Match and Body Racer, and Kinect Pad. The server runs every game
   (games.py: players are roster slots, moves need joints the camera saw, nobody is penalised for
   being out of sight); this page draws them as 3D scenes, plays the sounds and runs the
   tutorial. Moving things come with the server times they were made and are due, so they glide
   at the screen's frame rate while every hit and point stays the server's. */
"use strict";

(() => {
  let root = null, r = null, hud = null, alive = false, timer = null, offEvent = null, tut = null, poses = null;
  let phase = "choose", pick = "walls", steer = "wheel", flash = {}, results = null;
  const M = GL3.M;
  const DESCRIPTIONS = {
    walls: "Walls rush at you: duck, jump, lean or throw your arms up or out to fit through the hole as it arrives. Three lives each.",
    pose: "Copy the white figure and hold it for a second. The closer and quicker, the more points.",
    race: "Hold an imaginary steering wheel: tilt it to steer, push your hands out to go, pull them back to brake. 60 seconds.",
  };

  // -- choosing ------------------------------------------------------------------------------
  async function chooseView() {
    const cat = await K.catalog();
    const badge = (k) => { const f = K.fit(k); return f ? (f.fits ? '<span class="badge ok">Fits</span>' : '<span class="badge no">Not here</span>') : ""; };
    const f = K.fit(pick);
    root.innerHTML = `<div class="choose">
      <div class="left"><div class="tiles" style="grid-template-columns:repeat(3,minmax(0,1fr))">${cat.games.map((g) => `<button class="tile ${g.key === pick ? "sel" : ""}" data-game="${g.key}" style="min-height:170px">${badge(g.key)}
        <b style="font-size:26px">${K.esc(g.name)}</b><span>${K.esc(DESCRIPTIONS[g.key])}</span></button>`).join("")}</div>
        <div class="card"><h2>Kinect Pad</h2><p class="soft">Your body as a game controller for any game on this computer: Steam, emulators, and PS5 games through chiaki-ng Remote Play.</p>
          <div class="row" style="margin-top:12px"><div class="seg" id="g-pad">${[["", "Off"], ["wheel", "Wheel"], ["lean", "Lean"], ["keys", "Arrow keys"]].map(([k, n]) => `<button data-pad="${k}" class="${(K.live.state.pad || "") === k ? "on" : ""}">${n}</button>`).join("")}</div></div>
          <p class="note" id="g-pad-note">${K.esc(K.live.state.pad_error || "Inputs are released the moment the player is out of sight or the Kinect stops sending.")}</p></div></div>
      <div class="detail"><div class="stage" id="g-demo"><canvas></canvas><span class="label">How to play</span></div>
        <div class="card"><div class="row"><h2>${K.esc(cat.games.find((g) => g.key === pick).name)}</h2><span class="spacer"></span>${f ? (f.fits ? `<span class="badge ok">Fits ${f.band[0]}–${f.band[1]} m away</span>` : '<span class="badge no">Doesn\'t fit here</span>') : ""}</div>
          <p class="how">${K.esc(DESCRIPTIONS[pick])}</p>${f && !f.fits ? `<p class="why">${K.esc(f.why)}</p>` : ""}
          ${pick === "race" ? `<div class="row" style="margin-top:12px"><span class="soft">Steer with</span><div class="seg" id="g-steer"><button data-steer="wheel" class="${steer === "wheel" ? "on" : ""}">Hands (wheel)</button><button data-steer="lean" class="${steer === "lean" ? "on" : ""}">Leaning</button></div></div>` : ""}
          <p class="note">Everyone who has joined plays, each in their own colour and lane; with nobody joined, everyone in view (up to four). Your slot stays yours wherever you stand.</p>
          <div class="row" style="margin-top:14px"><button class="btn" data-tutorial>Tutorial</button><span class="spacer"></span><button class="btn primary big" data-play>Play</button></div></div></div></div>`;
    const g = cat.games.find((x) => x.key === pick);
    demoLoop(root.querySelector("#g-demo canvas"), g.tutorial.map((s) => s.pose));
  }

  let demoP = null;
  function demoLoop(canvas, keys) {
    if (demoP) demoP.stop();
    const real = keys.filter((k) => k !== "T");
    demoP = K.demoPlayer(canvas, real[0] || "out");
    let i = 0;
    demoP.cycle = setInterval(() => { i = (i + 1) % Math.max(1, real.length); if (real.length > 1) demoP.set(real[i]); }, 2600);
    const stop = demoP.stop;
    demoP.stop = () => { clearInterval(demoP.cycle); stop(); };
  }

  // -- the tutorial, then 3-2-1 ---------------------------------------------------------------
  async function tutorial(then) {
    const cat = await K.catalog();
    const g = cat.games.find((x) => x.key === pick);
    let i = 0;
    const m = K.modal(`<h1>${K.esc(g.name)}</h1><div class="stage" style="height:380px"><canvas id="t-c"></canvas></div>
      <p class="how" id="t-say" style="font-size:24px;font-weight:700;margin-top:16px"></p><div class="steps" id="t-steps"></div>
      <div class="row" style="margin-top:18px"><button class="btn" id="t-skip">Skip</button><span class="spacer"></span><button class="btn primary big" id="t-next">Next</button></div>`, () => { clearInterval(tut); tut = null; dp.stop(); });
    const dp = K.demoPlayer(m.el.querySelector("#t-c"), g.tutorial[0].pose === "T" ? "out" : g.tutorial[0].pose);
    const show = () => {
      const s = g.tutorial[i];
      m.el.querySelector("#t-say").textContent = s.say;
      m.el.querySelector("#t-steps").innerHTML = g.tutorial.map((_, k) => `<i class="${k < i ? "done" : k === i ? "cur" : ""}"></i>`).join("");
      dp.set(s.pose === "T" ? "out" : s.pose);
      m.el.querySelector("#t-next").textContent = i === g.tutorial.length - 1 ? "Play" : "Next";
    };
    const next = () => { K.sound("select"); i += 1; if (i >= g.tutorial.length) { m.close(); then(); } else show(); };
    m.el.querySelector("#t-next").onclick = next;
    m.el.querySelector("#t-skip").onclick = () => { m.close(); then(); };
    clearInterval(tut);
    tut = setInterval(next, 4200);
    show();
  }

  function countdown(then) {
    phase = "count";
    let n = 3;
    playView();
    const el = root.querySelector("#g-count");
    el.hidden = false; el.textContent = n; K.sound("tick");
    const t = setInterval(() => {
      n -= 1;
      if (n > 0) { el.textContent = n; K.sound("tick"); return; }
      clearInterval(t); el.textContent = "Go"; K.sound("go");
      setTimeout(() => { el.hidden = true; }, 600);
      then();
    }, 900);
  }

  async function play() {
    results = null;
    try { await K.api("/api/game", { action: "start", game: pick, steer }); phase = "play"; }
    catch (err) { K.toast(err.message, "warn"); phase = "choose"; chooseView(); }
  }

  // -- playing -------------------------------------------------------------------------------
  function playView() {
    if (root.querySelector("#g-stage")) return;
    stopDemo();
    root.innerHTML = `<div class="play wide"><div class="stage" id="g-stage"><canvas id="g-gl"></canvas><canvas id="g-hud"></canvas>
      <div class="big-count" id="g-count" hidden></div><div class="banner" id="g-banner" hidden></div>
      <div class="hud" style="top:auto;bottom:18px;pointer-events:auto"><span></span><div class="controls"><button class="btn" id="g-stop">Stop</button></div></div></div></div>`;
    r = GL3.create(root.querySelector("#g-gl"));
    hud = root.querySelector("#g-hud");
    root.querySelector("#g-stop").onclick = stop;
    if (!alive) { alive = true; requestAnimationFrame(frame); }
  }

  async function stop() {
    await K.api("/api/game", { action: "stop" }).catch(() => {});
    phase = "choose"; alive = false; chooseView();
  }

  function frame(now) {
    if (!alive || !r || !root.querySelector("#g-gl")) { alive = false; return; }
    r.resize(); r.full(); r.clear(GL3.rgba("sky"));
    const d = Math.min(2, window.devicePixelRatio || 1), W = hud.clientWidth, H = hud.clientHeight;
    if (hud.width !== Math.round(W * d)) { hud.width = Math.round(W * d); hud.height = Math.round(H * d); }
    const ctx = hud.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    const g = K.live.state.game;
    const key = g ? g.key : pick;
    const lanes = g ? Object.values(g.lanes) : (K.live.state.players || []).map((p) => ({ slot: p.slot, status: "active" }));
    const ppl = K.people();
    if (key === "pose") drawPose(g, ppl, ctx, W, H, now);
    else {
      const n = Math.max(1, lanes.length);
      lanes.forEach((lane, i) => {
        const x0 = Math.round((r.w * i) / n), x1 = Math.round((r.w * (i + 1)) / n);
        r.viewport(x0, 0, x1 - x0, r.h);
        const body = ppl.find((p) => p.slot === lane.slot);
        if (key === "walls") drawWalls(g, lane, body, ctx, (x0 / r.w) * W, ((x1 - x0) / r.w) * W, H, now);
        else drawRace(g, lane, body, ctx, (x0 / r.w) * W, ((x1 - x0) / r.w) * W, H, now);
      });
      r.full();
      if (n > 1) { ctx.fillStyle = K.colour("line"); for (let i = 1; i < n; i++) ctx.fillRect((W * i) / n - 1, 0, 2, H); }
    }
    banner(g);
    requestAnimationFrame(frame);
  }

  // The player's figure in their lane's own frame: them at the origin, seen from behind (their
  // right on the screen's right), facing -z, the TV.
  function local(body) {
    if (!body || !body.joints) return null;
    const hips = [body.joints[23], body.joints[24]].filter(Boolean);
    if (!hips.length) return null;
    const cx = hips.reduce((a, h) => a + h[0], 0) / hips.length, cz = hips.reduce((a, h) => a + h[2], 0) / hips.length;
    return body.joints.map((j) => j && [-(j[0] - cx), j[1], j[2] - cz, j[3]]);
  }
  const box = (x0, x1, y0, y1, z, depth = 0.25) => M.mul(M.translate((x0 + x1) / 2, (y0 + y1) / 2, z), M.scale(x1 - x0, y1 - y0, depth));
  const HOLES = {   // solid parts of each wall (lane frame, metres): the hole is what is left
    duck: [[-1.6, 1.6, 1.05, 2.6]],
    jump: [[-1.6, 1.6, 0, 0.32], [-1.6, 1.6, 2.35, 2.6]],
    left: [[0.25, 1.6, 0, 2.6], [-1.6, -1.0, 0, 2.6], [-1.0, 0.25, 1.62, 2.6]],     // the gap is on your left
    right: [[-1.6, -0.25, 0, 2.6], [1.0, 1.6, 0, 2.6], [-0.25, 1.0, 1.62, 2.6]],
    up: [[-1.6, -0.32, 0, 2.6], [0.32, 1.6, 0, 2.6]],
    out: [[-1.6, -0.95, 0, 2.6], [0.95, 1.6, 0, 2.6], [-0.95, -0.28, 0, 1.18], [0.28, 0.95, 0, 1.18], [-0.95, 0.95, 1.62, 2.6], [-0.28, 0.28, 2.2, 2.6]],
  };

  function drawWalls(g, lane, body, ctx, x, w, H, now) {
    r.camera([0, 1.75, 2.6], [0, 1.15, -3], 0.95);
    r.fog = 7;
    r.grid(-1.6, 1.6, -16, 2, 0.8, GL3.rgba("grid-2"));
    for (const sx of [-1.6, 1.6]) r.lines([sx, 0, -16, sx, 0, 2, sx, 2.6, -16, sx, 2.6, 2], GL3.rgba("grid"));
    const me = local(body);
    const col = K.playerRGBA(lane.slot, lane.status === "active" ? 1 : 0.4);
    if (me) r.body(me, col);
    const t = K.serverNow();
    const wall = lane.wall;
    if (wall) {
      const at = wall.frozen !== null && wall.frozen !== undefined ? wall.frozen : t;
      const k = Math.max(0, Math.min(1.05, (at - wall.made) / Math.max(0.1, wall.due - wall.made)));
      const z = -14 * (1 - k);
      const c = lane.fits ? GL3.rgba("ok", 0.86) : GL3.rgba("wall", 0.86);
      for (const [a, b, c0, c1] of HOLES[wall.kind] || []) if (b - a > 0.001 && c1 - c0 > 0.001) r.draw("box", box(a, b, c0, c1, z), c);
      const p = r.project([0, 2.8, z]);
      if (p) { ctx.font = `850 ${Math.round(18 + 34 * k)}px Inter, system-ui`; ctx.textAlign = "center"; ctx.fillStyle = K.colour("white"); ctx.fillText(wall.say, p[0], p[1]); }
    }
    const f = flash[lane.slot];
    if (f && now - f.at < 520) { ctx.fillStyle = K.colour(f.kind === "hit" ? "danger" : f.kind === "pass" ? "ok" : "muted"); ctx.globalAlpha = 0.22 * (1 - (now - f.at) / 520); ctx.fillRect(x, 0, w, H); ctx.globalAlpha = 1; }
    laneHud(ctx, x, w, lane, `${lane.score ?? 0}`, lane.lives !== undefined ? "●".repeat(Math.max(0, lane.lives)) + "○".repeat(Math.max(0, 3 - lane.lives)) : "",
      lane.streak > 1 ? `${lane.streak} in a row` : "");
  }

  function drawRace(g, lane, body, ctx, x, w, H, now) {
    const car = lane.dist !== undefined ? lane : { x: 0, dist: 0, items: [], speed: 0 };
    const cx = (car.x || 0) * 1.4;
    r.camera([cx * 0.5, 2.6, 4.2], [cx * 0.5, 0.2, -8], 0.85);
    r.fog = 10;
    r.draw("box", M.mul(M.translate(0, -0.01, -20), M.scale(3.4, 0.02, 48)), GL3.rgba("floor"), 0.6);
    const off = ((car.dist || 0) * 0.2) % 2;
    const dash = [];
    for (let z = 4 - off; z > -40; z -= 2) dash.push(0, 0.005, z, 0, 0.005, z - 1);
    r.lines(dash, GL3.rgba("ghost"));
    for (const sx of [-1.7, 1.7]) r.lines([sx, 0.01, 4, sx, 0.01, -44], GL3.rgba("bone"));
    for (const it of car.items || []) {
      const z = -((it.d - (car.dist || 0)) * 0.2);
      if (z > 3 || z < -40) continue;
      const ix = it.x * 1.4;
      if (it.coin) r.draw("sphere", M.mul(M.translate(ix, 0.35, z), M.scale(0.2, 0.2, 0.06)), GL3.rgba("coin"));
      else r.draw("cone", M.mul(M.translate(ix, 0, z), M.scale(0.22, 0.55, 0.22)), GL3.rgba("cone"));
    }
    const bumped = car.bump && K.serverNow() - car.bump < 0.4;
    const col = bumped ? GL3.rgba("danger") : K.playerRGBA(lane.slot, lane.status === "active" ? 1 : 0.45);
    r.draw("box", M.mul(M.translate(cx, 0.26, -0.6), M.scale(0.8, 0.34, 1.5)), col);
    r.draw("box", M.mul(M.translate(cx, 0.56, -0.45), M.scale(0.62, 0.28, 0.7)), col);
    void body;
    laneHud(ctx, x, w, lane, `${Math.round(car.dist || 0)} m`, `${car.coins || 0} coins · ${car.hits || 0} bumps`, `${Math.round((car.speed || 0) * 50)} km/h`);
    if (g && g.left !== undefined) { ctx.font = "850 46px Inter, system-ui"; ctx.textAlign = "right"; ctx.fillStyle = K.colour("text"); ctx.fillText(g.left > 0 ? `${Math.ceil(g.left)} s` : "Finish!", x + w - 24, 58); }
    const inp = lane.input;
    if (inp) {   // steering gauge
      const gx = x + w / 2, gy = H - 50;
      ctx.fillStyle = K.colour("fill-2"); ctx.fillRect(gx - 120, gy, 240, 10);
      ctx.fillStyle = K.colour("accent"); ctx.fillRect(gx + Math.min(0, inp.steer * 120), gy, Math.abs(inp.steer * 120), 10);
    }
  }

  function drawPose(g, ppl, ctx, W, H, now) {
    r.full();
    r.camera([0, 1.4, -1.2], [0, 1.0, 2.6], 0.9);
    r.fog = 5;
    r.grid(-2.5, 2.5, 0.5, 4.5, 0.5, GL3.rgba("grid"));
    if (g && g.pose && poses) {
      const target = poses.find((p) => p.name === g.pose.name);
      if (target) r.body(target.frames[0].map((j) => [j[0], j[1], j[2] + 3.6, 2]), GL3.rgba("white", 0.55), { shadow: false, scale: 1.1 });
    }
    for (const p of ppl) if (p.joints && p.slot !== null && p.slot !== undefined) r.body(p.joints, K.playerRGBA(p.slot));
    if (!g) return;
    ctx.font = "850 50px Inter, system-ui"; ctx.textAlign = "center"; ctx.fillStyle = K.colour("text");
    ctx.fillText(g.pose ? g.pose.name : "", W / 2, 70);
    ctx.font = "650 20px Inter, system-ui"; ctx.fillStyle = K.colour("soft");
    ctx.fillText(g.paused ? "Waiting for you to step back in" : `${Math.ceil(g.left)} s · round ${g.round}`, W / 2, 102);
    for (const p of ppl) {
      if (!p.joints || !p.joints[0] || p.slot === null || p.slot === undefined) continue;
      const lane = g.lanes[String(p.slot)];
      if (!lane) continue;
      const at = r.project([p.joints[0][0], p.joints[0][1] + 0.42, p.joints[0][2]]);
      if (at) K.ring(ctx, at[0], at[1], 34, lane.done ? 1 : lane.held, K.playerColour(p.slot), lane.done ? "✓" : `${lane.sim}%`);
    }
    Object.values(g.lanes).forEach((lane, k) => {
      ctx.textAlign = "left"; ctx.font = "850 32px Inter, system-ui"; ctx.fillStyle = K.playerColour(lane.slot);
      ctx.fillText(`P${lane.slot + 1}  ${lane.score}`, 26, 56 + k * 42);
      if (lane.status !== "active") { ctx.font = "650 16px Inter, system-ui"; ctx.fillStyle = K.colour("warn"); ctx.fillText(statusLine(lane.status, lane.slot), 160, 50 + k * 42); }
    });
    void now;
  }

  function statusLine(s, slot) {
    const p = (K.live.state.players || []).find((q) => q.slot === slot);
    if (s === "warning" && p && p.warning) return p.warning;
    return { hidden: "Hidden: step out from behind", unsure: "Crossing: hold on", away: "Out of view", rejoin: "Raise a hand to rejoin", warning: "Move to where you fit", stale: "The Kinect is late" }[s] || s;
  }

  function laneHud(ctx, x, w, lane, big, line, extra) {
    ctx.textAlign = "left"; ctx.fillStyle = K.playerColour(lane.slot);
    ctx.font = "850 38px Inter, system-ui"; ctx.fillText(`P${lane.slot + 1}  ${big}`, x + 22, 52);
    ctx.font = "650 19px Inter, system-ui"; ctx.fillStyle = K.colour("soft"); ctx.fillText(line, x + 22, 80);
    if (extra) ctx.fillText(extra, x + 22, 104);
    if (lane.status && lane.status !== "active") {
      ctx.font = "750 22px Inter, system-ui"; ctx.fillStyle = K.colour("warn"); ctx.textAlign = "center";
      ctx.fillText(statusLine(lane.status, lane.slot), x + w / 2, 150);
      ctx.font = "600 16px Inter, system-ui"; ctx.fillStyle = K.colour("soft");
      ctx.fillText("Paused for you: nothing counts against you", x + w / 2, 176);
    }
  }

  function banner(g) {
    const b = root.querySelector("#g-banner");
    if (!b) return;
    if (g && g.over) {
      b.hidden = false; b.className = "banner";
      const lanes = Object.values(g.lanes).sort((a, z) => z.score - a.score);
      b.innerHTML = `${lanes.length > 1 ? `Player ${lanes[0].slot + 1} wins!` : "Game over"}<small>${lanes.map((l) => `P${l.slot + 1}: ${l.score}`).join(" · ")}</small>
        <div class="row" style="justify-content:center;margin-top:16px;pointer-events:auto"><button class="btn primary" data-again>Play again</button><button class="btn" data-choose>Choose a game</button></div>`;
      b.style.pointerEvents = "auto";
    } else if (!g && phase === "play") { b.hidden = false; b.innerHTML = "Starting…"; }
    else b.hidden = true;
  }

  function onEvent(e) {
    if (e.type === "game") {
      const now = performance.now();
      if (e.slot !== null && e.slot !== undefined) flash[e.slot] = { kind: e.event, at: now };
      K.sound({ pass: "pass", hit: "hit", unseen: null, match: "match", coin: "coin", bump: "bump", round: "tick", over: "done" }[e.event] || "");
    } else if (e.type === "game-over") { results = e; }
  }

  function stopDemo() { if (demoP) { demoP.stop(); demoP = null; } }

  function mount(el, rest) {
    root = el;
    if (rest && rest[0] && ["walls", "pose", "race"].includes(rest[0])) pick = rest[0];
    const g = K.live.state.game;
    phase = g && !g.over ? "play" : "choose";
    if (phase === "play") { pick = g.key; playView(); } else chooseView();
    K.api("/api/poses").then((p) => { poses = p; }).catch(() => {});
    offEvent = K.on("event", onEvent);
    timer = setInterval(() => {
      const gs = K.live.state.game;
      if (phase === "choose" && gs && !gs.over) { phase = "play"; pick = gs.key; playView(); }
      if (phase === "play" && !gs) { phase = "choose"; alive = false; chooseView(); }
    }, 300);
    el.addEventListener("click", async (ev) => {
      const t = ev.target.closest("button");
      if (!t) return;
      if (t.dataset.game) { pick = t.dataset.game; K.sound("select"); chooseView(); }
      if (t.dataset.steer) { steer = t.dataset.steer; for (const b of t.parentElement.children) b.classList.toggle("on", b === t); }
      if (t.dataset.play !== undefined) countdown(play);
      if (t.dataset.tutorial !== undefined) tutorial(() => countdown(play));
      if (t.dataset.again !== undefined) { await K.api("/api/game", { action: "stop" }).catch(() => {}); countdown(play); }
      if (t.dataset.choose !== undefined) stop();
      if (t.dataset.pad !== undefined) {
        const res = await K.api("/api/pad", { profile: t.dataset.pad || null });
        for (const b of t.parentElement.children) b.classList.toggle("on", res.ok ? b === t : !b.dataset.pad);
        root.querySelector("#g-pad-note").textContent = res.ok ? (t.dataset.pad ? "On: a virtual controller any game can see. Released whenever you leave the picture." : "Off.") : res.error;
      }
    });
  }

  K.section("games", {
    title: "Games", mount,
    unmount() { alive = false; clearInterval(timer); clearInterval(tut); if (offEvent) offEvent(); stopDemo(); r = null; },
    back() { if (phase === "play") { stop(); return true; } return false; },
  });
})();
