/* A live 3D room: the floor, the Kinect's view on it, and everyone in view as an articulated
   figure in their player colour (people not playing are drawn faint). Draws on a WebGL canvas
   with a 2D canvas on top for labels and rings; sections pass `decorate` to add their own. */
"use strict";

K.scene = function scene(host, opts = {}) {
  host.insertAdjacentHTML("afterbegin", `<canvas class="gl"></canvas><canvas class="hud2"></canvas>`);
  const glc = host.querySelector(":scope > .gl"), hud = host.querySelector(":scope > .hud2");
  const r = GL3.create(glc);
  let alive = true, last = performance.now();
  const view = { eye: [0, 1.55, -0.9], target: [0, 0.95, 2.6], ...opts.view };
  if (!r) {
    host.insertAdjacentHTML("beforeend", '<div class="empty"><b>No 3D here</b>WebGL is not available in this window.</div>');
    return { stop() {}, r: null };
  }
  function frame(now) {
    if (!alive) return;
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    r.resize();
    r.clear(GL3.rgba("window"));
    r.fog = 3.5;
    r.camera(view.eye, view.target, opts.fov || 0.9);
    const sp = K.live.state.space;
    const far = sp ? sp.usable[1] : 4;
    r.grid(-2.5, 2.5, 0.5, Math.max(far + 0.6, 3), 0.5, GL3.rgba("grid"));
    if (sp) {
      // The usable band, as lines on the floor.
      const z0 = sp.usable[0], z1 = sp.usable[1], c = GL3.rgba("accent", 0.45);
      r.lines([-1.6, 0.003, z0, 1.6, 0.003, z0, -1.6, 0.003, z1, 1.6, 0.003, z1], c);
    }
    const people = K.people();
    for (const p of people) {
      if (!p.joints) continue;
      const playing = p.slot !== null && p.slot !== undefined;
      const lost = playing && (K.live.state.players || []).some((q) => q.slot === p.slot && q.lost);
      const col = playing ? K.playerRGBA(p.slot, lost ? 0.45 : 1) : GL3.rgba("ghost");
      r.body(p.joints, col);
    }
    if (opts.extra3d) opts.extra3d(r, dt, now);
    // The 2D layer.
    const d = Math.min(2, window.devicePixelRatio || 1);
    const W = hud.clientWidth, H = hud.clientHeight;
    if (hud.width !== Math.round(W * d) || hud.height !== Math.round(H * d)) { hud.width = Math.round(W * d); hud.height = Math.round(H * d); }
    const ctx = hud.getContext("2d");
    ctx.setTransform(d, 0, 0, d, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (opts.decorate) opts.decorate(ctx, W, H, people, r, now);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  return { r, view, stop() { alive = false; } };
};

// A ring (0..1) with a number in it, for counts over heads.
K.ring = function ring(ctx, x, y, rad, value, col, text, big) {
  ctx.lineWidth = rad / 4; ctx.lineCap = "round";
  ctx.strokeStyle = K.colour("fill-3");
  ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = col;
  ctx.beginPath(); ctx.arc(x, y, rad, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0, Math.min(1, value))); ctx.stroke();
  if (text !== undefined) {
    ctx.fillStyle = big ? K.colour("yellow") : K.colour("text");
    ctx.font = `800 ${Math.round(rad * (big ? 1.05 : 0.9))}px Inter, system-ui`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(String(text), x, y + 1);
  }
};

// A small looping demonstration: a figure doing a move, in its own canvas.
K.demoPlayer = function demoPlayer(canvas, key, opts = {}) {
  const r = GL3.create(canvas);
  let data = null, alive = true, t0 = performance.now();
  K.demo(key).then((d) => { data = d; });
  const col = opts.colour || GL3.rgba("white", 0.92);
  function frame(now) {
    if (!alive) return;
    r.resize(); r.clear(opts.ground || GL3.rgba("window"));
    const yaw = opts.side ? 1.2 : 0.35;
    r.camera([Math.sin(yaw) * -3.2, 1.25, -Math.cos(yaw) * 3.2], [0, 0.85, 0], 0.62);
    r.grid(-1.2, 1.2, -1.2, 1.2, 0.4, GL3.rgba("grid"));
    if (data && data.frames.length) {
      const f = ((now - t0) / 1000) * data.fps;
      const i = Math.floor(f) % data.frames.length, k = f - Math.floor(f), j = (i + 1) % data.frames.length;
      const A = data.frames[i], B = data.frames[j];
      r.body(A.map((a, n) => [a[0] + (B[n][0] - a[0]) * k, a[1] + (B[n][1] - a[1]) * k, a[2] + (B[n][2] - a[2]) * k, 2]), col);
    }
    requestAnimationFrame(frame);
  }
  if (r) requestAnimationFrame(frame);
  return { stop() { alive = false; }, set(k) { key = k; data = null; K.demo(k).then((d) => { if (key === k) data = d; }); t0 = performance.now(); } };
};
