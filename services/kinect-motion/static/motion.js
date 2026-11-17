/* Shared by Kinect Fitness, Arcade and Room: the live connection, colours, skeleton drawing.
   Colours come from motion.css's custom properties (tokens), never written here. */
"use strict";

const Motion = (() => {
  const HUB = `${location.protocol}//${location.hostname}:8792`;
  // MediaPipe's 33-joint skeleton: which joints a bone joins.
  const BONES = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24],
    [23, 25], [25, 27], [24, 26], [26, 28], [27, 31], [28, 32], [27, 29], [28, 30], [15, 19], [16, 20]];
  const css = getComputedStyle(document.documentElement);
  const colour = (name) => css.getPropertyValue(`--${name}`).trim();
  const playerColour = (slot) => colour(`p${(slot ?? 5) % 6 + 1}`);

  // -- the live state: one message per Kinect frame, reconnecting by itself
  function connect(onMessage, onStatus) {
    let ws, retry = 500;
    const open = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      ws.onopen = () => { retry = 500; onStatus && onStatus(true); };
      ws.onmessage = (m) => onMessage(JSON.parse(m.data));
      ws.onclose = () => { onStatus && onStatus(false); setTimeout(open, retry); retry = Math.min(retry * 2, 5000); };
    };
    open();
  }

  async function api(path, body, method) {
    const opts = body === undefined && !method ? {} : {
      method: method || "POST", headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body) };
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  // -- the camera picture from the hub, one frame after another (only while shown)
  function video(img, isOn) {
    let seq = 0;
    const next = () => {
      if (!isOn()) { setTimeout(next, 500); return; }
      const probe = new Image();
      probe.onload = () => { img.src = probe.src; setTimeout(next, 30); };
      probe.onerror = () => setTimeout(next, 1000);
      probe.src = `${HUB}/frame/video.jpg?after=${seq++}&r=${Date.now()}`;
    };
    next();
  }

  // -- where things go on a canvas: a mirror (your left hand on the left), room metres -> pixels
  function frontView(W, H) {
    const s = Math.min(W / 4.6, (H - 80) / 2.25);              // 4.6 m wide, 2.25 m tall
    return { s, x: (x) => W / 2 - x * s, y: (y) => H - 60 - y * s };   // floor above the hints
  }

  function drawSkeleton(ctx, pts, col, width) {
    // Bones: solid between joints the camera saw, dashed if either was only inferred.
    for (const [a, b] of BONES) {
      const p = pts[a], q = pts[b];
      if (!p || !q) continue;
      ctx.setLineDash(p[2] === 2 && q[2] === 2 ? [] : [6, 6]);
      ctx.strokeStyle = col; ctx.lineWidth = width; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    }
    ctx.setLineDash([]);
    // The neck: nose to between the shoulders.
    if (pts[0] && pts[11] && pts[12]) {
      ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
      ctx.lineTo((pts[11][0] + pts[12][0]) / 2, (pts[11][1] + pts[12][1]) / 2); ctx.stroke();
    }
    for (const i of [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]) {
      const p = pts[i];
      if (!p) continue;
      ctx.beginPath(); ctx.arc(p[0], p[1], i === 0 ? width * 2.6 : width * 1.1, 0, Math.PI * 2);
      if (p[2] === 2) { ctx.fillStyle = col; ctx.fill(); }
      else { ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke(); }   // inferred: hollow
    }
  }

  // Everyone as a mirror image from their 3D joints (no camera picture needed).
  function drawPeople(ctx, W, H, people, extra) {
    const v = frontView(W, H);
    ctx.strokeStyle = colour("grid"); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, v.y(0)); ctx.lineTo(W, v.y(0)); ctx.stroke();
    for (const p of people) {
      if (!p.joints) continue;
      const col = p.slot === null || p.slot === undefined ? colour("ghost") : playerColour(p.slot);
      const pts = p.joints.map((j) => j && [v.x(j[0]), v.y(j[1]), j[3]]);
      // A shadow on the floor under them: where they stand.
      const feet = [p.joints[27], p.joints[28]].filter(Boolean);
      if (feet.length) {
        const fx = v.x(feet.reduce((a, f) => a + f[0], 0) / feet.length);
        ctx.fillStyle = colour("fill-2");
        ctx.beginPath(); ctx.ellipse(fx, v.y(0), 0.32 * v.s, 0.05 * v.s, 0, 0, Math.PI * 2); ctx.fill();
      }
      drawSkeleton(ctx, pts, col, Math.max(3, v.s / 70));
      if (extra) extra(p, pts, v);
    }
    return v;
  }

  // The same over the camera picture (contain-fitted, mirrored), from the hub's 2D landmarks.
  function drawOverVideo(ctx, W, H, people, size, extra) {
    const [iw, ih] = size || [640, 480];
    const k = Math.min(W / iw, H / ih), ox = (W - iw * k) / 2, oy = (H - ih * k) / 2;
    for (const p of people) {
      if (!p.skeleton) continue;
      const col = p.slot === null || p.slot === undefined ? colour("ghost") : playerColour(p.slot);
      const pts = p.skeleton.map((q, i) => {
        if (q[2] < 0.5) return null;
        const state = p.joints && p.joints[i] ? p.joints[i][3] : 1;
        return [ox + (1 - q[0]) * iw * k, oy + q[1] * ih * k, state];
      });
      drawSkeleton(ctx, pts, col, Math.max(3, W / 320));
      if (extra) extra(p, pts, null);
    }
  }

  function ring(ctx, x, y, r, value, col) {
    ctx.lineWidth = r / 4;
    ctx.strokeStyle = colour("fill-2");
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = col;
    ctx.beginPath(); ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0, Math.min(1, value))); ctx.stroke();
  }

  function fit(canvas) {
    const r = canvas.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(r.width * d) || canvas.height !== Math.round(r.height * d)) {
      canvas.width = Math.round(r.width * d); canvas.height = Math.round(r.height * d);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(d, 0, 0, d, 0, 0);
    return [ctx, r.width, r.height];
  }

  // The status pills every page shows: Kinect, people, latency.
  function status(el, st, connected) {
    if (!el) return;
    const hub = st.hub || {};
    const live = connected && !st.hub_error && hub.running !== false;
    const lat = st.latency ? ` · ${st.latency.p50} ms` : "";
    const src = hub.source === "demo" ? "Demo people" : hub.mode === "ir" ? "Kinect · infrared" : "Kinect";
    el.className = `pill ${live ? "live" : connected ? "warn" : "bad"}`;
    el.innerHTML = `<span class="dot"></span>${!connected ? "Reconnecting…" :
      st.hub_error ? st.hub_error : `${src} · ${(st.people || []).length} in view${lat}`}`;
    el.title = st.latency ? `Camera to screen: median ${st.latency.p50} ms, 95% under ${st.latency.p95} ms` : "";
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  return { HUB, BONES, colour, playerColour, connect, api, video, frontView, drawSkeleton,
    drawPeople, drawOverVideo, ring, fit, status, esc };
})();
