/* Kinect Arcade: three body games drawn on one canvas, and the Kinect Pad switch.
   Original games built on the motion layer's primitives (lean, hip height, arms, the wheel):
   the research's point that once the gesture layer exists, games are just game logic. */
"use strict";

const $ = (id) => document.getElementById(id);
const C = Motion.colour;
let state = { people: [], players: [] }, connected = false, game = null;

Motion.connect((msg) => { state = msg.state; padGauges(); }, (ok) => { connected = ok; });
setInterval(() => Motion.status($("status"), state, connected), 300);

// -- reading a body ------------------------------------------------------------------------------
function vec(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function angle(a, b, c) {
  if (!a || !b || !c) return null;
  const u = vec(a, b), w = vec(c, b);
  const nu = Math.hypot(...u), nw = Math.hypot(...w);
  if (nu < 1e-6 || nw < 1e-6) return null;
  return Math.acos(Math.max(-1, Math.min(1, (u[0] * w[0] + u[1] * w[1] + u[2] * w[2]) / (nu * nw)))) * 180 / Math.PI;
}
// Players in slot order, each with their body (people with joints).
function players() {
  const out = [];
  const people = state.people || [];
  const joined = (state.players || []).filter((p) => p.here);
  if (joined.length) {
    for (const p of joined) {
      const body = people.find((x) => x.slot === p.slot);
      if (body && body.joints) out.push({ slot: p.slot, body });
    }
  } else {
    // Nobody joined: everyone in view plays, numbered left to right as you see them (up to four).
    const seen = people.filter((p) => p.joints && (p.joints[23] || p.joints[24]))
      .sort((a, b) => ((b.joints[23] || b.joints[24])[0]) - ((a.joints[23] || a.joints[24])[0])).slice(0, 4);
    seen.forEach((body, k) => out.push({ slot: k, body }));
  }
  return out;
}
const J = (b, i) => b.joints[i];
function features(b) {
  const hip = J(b, 23) && J(b, 24) ? (J(b, 23)[1] + J(b, 24)[1]) / 2 : null;
  const nose = J(b, 0);
  const up = (i) => J(b, i) && nose ? J(b, i)[1] - nose[1] : -1;
  return {
    hip, lean: b.lean || 0,
    armsUp: up(15) > 0.08 && up(16) > 0.08,
    armsOut: [[23, 11, 13], [24, 12, 14]].every(([h, s, e]) => { const a = angle(J(b, h), J(b, s), J(b, e)); return a !== null && a > 70 && a < 115; }),
    angles: {
      lab: angle(J(b, 23), J(b, 11), J(b, 13)), rab: angle(J(b, 24), J(b, 12), J(b, 14)),
      lel: angle(J(b, 11), J(b, 13), J(b, 15)), rel: angle(J(b, 12), J(b, 14), J(b, 16)),
      lkn: angle(J(b, 23), J(b, 25), J(b, 27)), rkn: angle(J(b, 24), J(b, 26), J(b, 28)),
      feet: J(b, 27) && J(b, 28) ? Math.abs(J(b, 27)[0] - J(b, 28)[0]) : null,
    },
  };
}
const standHip = {};   // slot -> standing hip height, learnt while upright
function learn(slot, f) {
  if (f.hip === null) return;
  if (standHip[slot] === undefined) standHip[slot] = f.hip;
  if (f.hip > standHip[slot] - 0.03 && f.hip < standHip[slot] + 0.03) standHip[slot] = 0.97 * standHip[slot] + 0.03 * f.hip;
}

// -- Wall Dodge ----------------------------------------------------------------------------------
const WALLS = [
  { need: "duck", say: "DUCK", ok: (f, s) => f.hip !== null && f.hip < standHip[s] - 0.22 },
  { need: "jump", say: "JUMP", ok: (f, s) => f.hip !== null && f.hip > standHip[s] + 0.05 },
  { need: "left", say: "LEAN LEFT", ok: (f) => f.lean < -0.45 },
  { need: "right", say: "LEAN RIGHT", ok: (f) => f.lean > 0.45 },
  { need: "up", say: "ARMS UP", ok: (f) => f.armsUp },
  { need: "out", say: "ARMS OUT", ok: (f) => f.armsOut },
];
function wallsGame() {
  const g = { name: "Wall Dodge", lanes: {}, t0: performance.now(), speed: 0.28, over: false };
  g.step = (now, dt, ps) => {
    for (const { slot, body } of ps) {
      const lane = g.lanes[slot] || (g.lanes[slot] = { score: 0, lives: 3, wall: null, flash: -1e9, ok: false, hold: -1e9 });
      const f = features(body);
      learn(slot, f);
      if (lane.lives <= 0) continue;
      if (!lane.wall) lane.wall = { ...WALLS[Math.floor(Math.random() * WALLS.length)], z: 1 };
      lane.wall.z -= dt * g.speed;
      lane.ok = lane.wall.ok(f, slot);
      // Jumps are brief: being in the air any time in the last stretch counts.
      if (lane.ok && lane.wall.z < 0.25) lane.hold = now;
      if (lane.wall.z <= 0) {
        const passed = now - lane.hold < 400;
        if (passed) lane.score += 1; else lane.lives -= 1;
        lane.flash = now; lane.passed = passed; lane.wall = null;
      }
    }
    g.speed = 0.28 + (now - g.t0) / 1000 * 0.004;
  };
  g.draw = (ctx, W, H, ps, now) => {
    const n = Math.max(1, ps.length), lw = W / n;
    ps.forEach(({ slot, body }, k) => {
      const lane = g.lanes[slot]; if (!lane) return;
      const x0 = k * lw, col = Motion.playerColour(slot);
      ctx.save(); ctx.beginPath(); ctx.rect(x0, 0, lw, H); ctx.clip();
      // The tunnel: lines to a vanishing point.
      ctx.strokeStyle = C("grid"); ctx.lineWidth = 2;
      const vx = x0 + lw / 2, vy = H * 0.32;
      for (const [ax, ay] of [[x0, H], [x0 + lw, H], [x0, 0], [x0 + lw, 0]]) { ctx.beginPath(); ctx.moveTo(vx, vy); ctx.lineTo(ax, ay); ctx.stroke(); }
      if (lane.wall) {
        const s = 1 - lane.wall.z, w = lw * (0.1 + 0.9 * s), h = H * (0.1 + 0.9 * s);
        ctx.globalAlpha = 0.35 + 0.65 * s;
        ctx.fillStyle = lane.ok ? C("ok") : C("danger");
        ctx.fillRect(vx - w / 2, vy - h * 0.32, w, h);
        ctx.globalAlpha = 1;
        ctx.fillStyle = C("white"); ctx.font = `800 ${Math.round(18 + 50 * s)}px Inter, system-ui`; ctx.textAlign = "center";
        ctx.fillText(lane.wall.say, vx, vy + h * 0.15);
      }
      // You, small, at the bottom of your lane.
      const hip = body.joints[23] || body.joints[24];
      if (hip) {
        const pts = body.joints.map((j) => j && [vx - (j[0] - hip[0]) * 120, H - 30 - j[1] * 120, j[3]]);
        Motion.drawSkeleton(ctx, pts, col, 4);
      }
      ctx.fillStyle = col; ctx.font = "800 34px Inter, system-ui"; ctx.textAlign = "left";
      ctx.fillText(`P${slot + 1}  ${lane.score}`, x0 + 16, 44);
      ctx.fillStyle = C("soft"); ctx.font = "600 18px Inter, system-ui";
      ctx.fillText(lane.lives > 0 ? "♥".repeat(lane.lives) : "Out", x0 + 16, 72);
      if (now - lane.flash < 500) { ctx.fillStyle = lane.passed ? C("ok") : C("danger"); ctx.globalAlpha = 0.25; ctx.fillRect(x0, 0, lw, H); ctx.globalAlpha = 1; }
      ctx.restore();
    });
  };
  g.hint = "Fit through each wall: <b>duck</b>, <b>jump</b>, <b>lean</b>, <b>arms up</b> or <b>arms out</b> as it arrives. Three lives.";
  return g;
}

// -- Pose Match ----------------------------------------------------------------------------------
// Targets as joint angles (degrees): arm abduction, elbow, knee, and how wide the feet are (m).
const POSES = [
  { name: "Star", a: { lab: 150, rab: 150, lel: 175, rel: 175, lkn: 175, rkn: 175, feet: 0.7 } },
  { name: "Robot", a: { lab: 90, rab: 90, lel: 90, rel: 90, lkn: 175, rkn: 175, feet: 0.25 } },
  { name: "Goalpost", a: { lab: 90, rab: 90, lel: 95, rel: 95, lkn: 120, rkn: 120, feet: 0.55 } },
  { name: "T", a: { lab: 90, rab: 90, lel: 175, rel: 175, lkn: 175, rkn: 175, feet: 0.25 } },
  { name: "Skier", a: { lab: 20, rab: 20, lel: 160, rel: 160, lkn: 110, rkn: 110, feet: 0.3 } },
  { name: "Reach up", a: { lab: 170, rab: 170, lel: 175, rel: 175, lkn: 175, rkn: 175, feet: 0.2 } },
  { name: "Half star", a: { lab: 135, rab: 20, lel: 175, rel: 175, lkn: 175, rkn: 175, feet: 0.6 } },
];
function similarity(a, target) {
  let sum = 0, n = 0;
  for (const k of Object.keys(target)) {
    if (a[k] === null || a[k] === undefined) continue;
    const d = k === "feet" ? Math.abs(a[k] - target[k]) * 100 : Math.abs(a[k] - target[k]);   // 1 cm ~ 1 deg
    sum += Math.min(d, 90); n += 1;
  }
  return n < 5 ? 0 : Math.max(0, 100 - 1.6 * sum / n);
}
function poseGame() {
  const g = { name: "Pose Match", scores: {}, k: 0, since: performance.now(), held: {}, round: 0, done: {} };
  g.next = (now) => { g.k = (g.k + 1 + Math.floor(Math.random() * (POSES.length - 1))) % POSES.length; g.since = now; g.held = {}; g.done = {}; g.round += 1; };
  g.step = (now, dt, ps) => {
    const target = POSES[g.k].a;
    for (const { slot, body } of ps) {
      g.scores[slot] = g.scores[slot] || 0;
      const sim = similarity(features(body).angles, target);
      body._sim = sim;
      if (g.done[slot]) continue;
      if (sim >= 78) {
        g.held[slot] = (g.held[slot] || 0) + dt;
        if (g.held[slot] >= 1.0) { g.done[slot] = true; g.scores[slot] += Math.round(sim + Math.max(0, 60 - (now - g.since) / 100)); }
      } else g.held[slot] = 0;
    }
    if ((ps.length && ps.every(({ slot }) => g.done[slot])) || now - g.since > 9000) g.next(now);
  };
  g.draw = (ctx, W, H, ps, now) => {
    const t = POSES[g.k];
    // The target as a ghost figure in the middle (front view, built from its angles).
    const cx = W / 2, base = H - 70, s = Math.min(W, H) / 4.2;
    const ghost = figure2d(t.a, cx, base, s);
    ctx.globalAlpha = 0.5; Motion.drawSkeleton(ctx, ghost, C("white"), 10); ctx.globalAlpha = 1;
    ctx.fillStyle = C("text"); ctx.font = "800 46px Inter, system-ui"; ctx.textAlign = "center";
    ctx.fillText(t.name, cx, 70);
    ctx.fillStyle = C("soft"); ctx.font = "600 18px Inter, system-ui";
    ctx.fillText(`${Math.max(0, Math.ceil(9 - (now - g.since) / 1000))} s`, cx, 100);
    Motion.drawPeople(ctx, W, H, (state.people || []).map((p) => ({ ...p })), (p, pts) => {
      const head = pts[0]; if (!head || p.slot === null || p.slot === undefined) return;
      const pl = ps.find((x) => x.slot === p.slot);
      const sim = pl && pl.body._sim !== undefined ? Math.round(pl.body._sim) : 0;
      Motion.ring(ctx, head[0], head[1] - 60, 28, g.done[p.slot] ? 1 : (g.held[p.slot] || 0), Motion.playerColour(p.slot));
      ctx.fillStyle = C("text"); ctx.font = "800 18px Inter, system-ui"; ctx.textAlign = "center";
      ctx.fillText(g.done[p.slot] ? "✓" : `${sim}%`, head[0], head[1] - 54);
    });
    ctx.textAlign = "left"; ctx.font = "800 30px Inter, system-ui";
    ps.forEach(({ slot }, k) => { ctx.fillStyle = Motion.playerColour(slot); ctx.fillText(`P${slot + 1}  ${g.scores[slot] || 0}`, 24, 50 + k * 38); });
  };
  g.hint = "Match the white shape and <b>hold it for a second</b>. Quicker matches score more.";
  return g;
}
// A front-view stick figure from pose angles, for the target (pixels, all joints "tracked").
function figure2d(a, cx, base, s) {
  const pts = new Array(33).fill(null);
  const rad = (d) => d * Math.PI / 180;
  const thigh = 0.43, shank = 0.43, torso = 0.5, upper = 0.32, fore = 0.27, half = 0.18, hipw = 0.1;
  const bend = (k) => (180 - k) / 2;
  const legs = (side, kn) => {
    const fx = side * Math.max(hipw, a.feet / 2), b = rad(bend(kn));
    const ank = [fx, 0.08], knee = [fx + side * 0.02, ank[1] + shank * Math.cos(b)];
    const hip = [side * hipw, knee[1] + thigh * Math.cos(b)];
    return [hip, knee, ank];
  };
  const L = legs(1, a.lkn), R = legs(-1, a.rkn);
  const hipY = (L[0][1] + R[0][1]) / 2, sh = hipY + torso;
  const arm = (side, ab, el) => {
    const s0 = [side * half, sh], d = [side * Math.sin(rad(ab)), -Math.cos(rad(ab))];
    const e = [s0[0] + upper * d[0], s0[1] + upper * d[1]];
    const turn = rad(180 - el) * side;      // forearm turns up/in
    const fd = [d[0] * Math.cos(turn) - d[1] * Math.sin(turn), d[0] * Math.sin(turn) + d[1] * Math.cos(turn)];
    return [s0, e, [e[0] + fore * fd[0], e[1] + fore * fd[1]]];
  };
  const LA = arm(1, a.lab, a.lel), RA = arm(-1, a.rab, a.rel);
  const put = (i, p) => { pts[i] = [cx - p[0] * s, base - p[1] * s, 2]; };   // mirror, like the people
  [[23, L[0]], [25, L[1]], [27, L[2]], [24, R[0]], [26, R[1]], [28, R[2]],
    [11, LA[0]], [13, LA[1]], [15, LA[2]], [12, RA[0]], [14, RA[1]], [16, RA[2]], [0, [0, sh + 0.22]]].forEach(([i, p]) => put(i, p));
  return pts;
}

// -- Body Racer ----------------------------------------------------------------------------------
function raceGame() {
  const g = { name: "Body Racer", cars: {}, t0: performance.now(), length: 60000, items: [], spawn: 0 };
  g.step = (now, dt, ps) => {
    const mode = $("steer").value;
    for (const { slot, body } of ps) {
      const car = g.cars[slot] || (g.cars[slot] = { x: 0, speed: 0, dist: 0, coins: 0, hits: 0, bump: -1e9 });
      const w = body.wheel;
      const steer = mode === "lean" ? (body.lean || 0) : (w ? w.wheel : 0);
      const gas = mode === "lean" ? 0.8 : (w ? w.throttle : 0);
      const brake = mode === "lean" ? 0 : (w ? w.brake : 0);
      const done = now - g.t0 > g.length;
      car.speed += ((done ? 0 : gas) * 1.6 - brake * 2.2 - car.speed * 0.35) * dt;
      car.speed = Math.max(0, Math.min(2.2, car.speed));
      car.x = Math.max(-1, Math.min(1, car.x + steer * 1.4 * dt * (0.4 + car.speed / 2.2)));
      car.dist += car.speed * dt * 60;
    }
    if (now > g.spawn) { g.items.push({ x: Math.random() * 1.8 - 0.9, y: 0, coin: Math.random() < 0.55 }); g.spawn = now + 700; }
    const lead = Math.max(0.6, ...Object.values(g.cars).map((c) => c.speed));
    for (const it of g.items) it.y += dt * 0.35 * lead;
    for (const [slot, car] of Object.entries(g.cars)) {
      for (const it of g.items) {
        if (it.taken && it.taken[slot]) continue;
        if (it.y > 0.82 && it.y < 0.92 && Math.abs(it.x - car.x) < 0.16) {
          (it.taken = it.taken || {})[slot] = true;
          if (it.coin) car.coins += 1; else { car.hits += 1; car.speed *= 0.3; car.bump = now; }
        }
      }
    }
    g.items = g.items.filter((it) => it.y < 1.1);
  };
  g.draw = (ctx, W, H, ps, now) => {
    const n = Math.max(1, ps.length), lw = W / n;
    const left = Math.max(0, Math.ceil((g.length - (now - g.t0)) / 1000));
    ps.forEach(({ slot }, k) => {
      const car = g.cars[slot]; if (!car) return;
      const x0 = k * lw, road = lw * 0.7, rx = x0 + (lw - road) / 2;
      ctx.fillStyle = C("raised"); ctx.fillRect(rx, 0, road, H);
      ctx.strokeStyle = C("ghost"); ctx.setLineDash([30, 30]); ctx.lineDashOffset = -(car.dist * 4) % 60; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(rx + road / 2, 0); ctx.lineTo(rx + road / 2, H); ctx.stroke(); ctx.setLineDash([]);
      for (const it of g.items) {
        if (it.taken && it.taken[slot]) continue;
        ctx.fillStyle = it.coin ? C("yellow") : C("orange");
        const ix = rx + road / 2 + it.x * road / 2, iy = it.y * H;
        ctx.beginPath();
        if (it.coin) ctx.arc(ix, iy, 14, 0, Math.PI * 2); else { ctx.moveTo(ix, iy - 20); ctx.lineTo(ix - 16, iy + 14); ctx.lineTo(ix + 16, iy + 14); }
        ctx.fill();
      }
      const cxp = rx + road / 2 + car.x * road / 2, cy = H * 0.87;
      ctx.fillStyle = now - car.bump < 300 ? C("danger") : Motion.playerColour(slot);
      ctx.fillRect(cxp - 22, cy - 36, 44, 72);
      ctx.fillStyle = Motion.playerColour(slot); ctx.font = "800 30px Inter, system-ui"; ctx.textAlign = "left";
      ctx.fillText(`P${slot + 1}  ${Math.round(car.dist)} m`, x0 + 14, 42);
      ctx.fillStyle = C("soft"); ctx.font = "600 18px Inter, system-ui";
      ctx.fillText(`coins ${car.coins} · bumps ${car.hits} · ${Math.round(car.speed * 50)} km/h`, x0 + 14, 68);
    });
    // The clock, bottom middle, clear of every lane's score.
    ctx.fillStyle = C("text"); ctx.font = "800 44px Inter, system-ui"; ctx.textAlign = "center";
    ctx.fillText(left ? `${left} s` : "Finish!", W / 2, H - 60);
  };
  g.hint = "Hands on an imaginary wheel: <b>tilt</b> to steer, <b>push out</b> to go, <b>pull back</b> to brake. Grab coins, miss cones.";
  return g;
}

// -- the loop ------------------------------------------------------------------------------------
let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  const [ctx, W, H] = Motion.fit($("view"));
  ctx.clearRect(0, 0, W, H);
  const ps = players();
  if (game) { game.step(now, dt, ps); game.draw(ctx, W, H, ps, now); }
  else {
    Motion.drawPeople(ctx, W, H, state.people || []);
    ctx.fillStyle = C("muted"); ctx.font = "600 26px Inter, system-ui"; ctx.textAlign = "center";
    ctx.fillText("Pick a game", W / 2, 60);
  }
  $("banner").hidden = !!ps.length || !game;
  $("banner").textContent = "Stand in front of the TV to play";
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button");
  if (!t) return;
  if (t.dataset.game) {
    game = { walls: wallsGame, pose: poseGame, race: raceGame }[t.dataset.game]();
    $("hint").innerHTML = `<span>${game.hint}</span>`;
  }
  if (t.id === "stop") { game = null; $("hint").innerHTML = ""; }
  if (t.dataset.pad !== undefined) {
    const r = await Motion.api("/api/pad", { profile: t.dataset.pad || null });
    for (const b of $("pad").children) b.classList.toggle("on", b === t && r.ok);
    if (!r.ok) { for (const b of $("pad").children) b.classList.toggle("on", !b.dataset.pad); }
    $("pad-note").textContent = r.ok ? $("pad-note").textContent : r.error;
  }
});

function padGauges() {
  const p = (state.people || []).find((x) => x.slot === 0) || (state.people || [])[0];
  const w = p && p.wheel;
  const steer = w ? w.wheel : 0;
  const g = $("g-steer");
  g.style.left = steer >= 0 ? "50%" : `${50 + steer * 50}%`;
  g.style.width = `${Math.abs(steer) * 50}%`;
  $("g-gas").style.width = `${(w ? w.throttle : 0) * 100}%`;
  $("g-brake").style.width = `${(w ? w.brake : 0) * 100}%`;
  if (state.pad_error) $("pad-note").textContent = state.pad_error;
}

// /arcade?game=walls (or pose, race) opens straight into a game.
const asked = new URLSearchParams(location.search).get("game");
if (asked) { const b = document.querySelector(`[data-game="${asked}"]`); if (b) b.click(); }
