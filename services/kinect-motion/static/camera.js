/* Camera: what Kinect Studio did, in the app. The colour or infrared picture with everyone's
   skeleton, depth, the 3D point cloud (drag to turn, right-drag to move, scroll to zoom; PLY
   export), the picture mode, the "Kinect Camera" webcam, tilt, LED, measuring people, depth
   statistics and the frame pairing. Everything comes from the hub through /hub/ (this origin). */
"use strict";

(() => {
  let root = null, alive = false, status = null, poll = null, cloud = null, orbit = null;
  let colourBy = 0, step = 4, size = 2;

  function mount(el) {
    root = el; alive = true;
    el.innerHTML = `<div class="camera">
      <div class="stage main" id="c-pic"><canvas id="c-video" width="640" height="480"></canvas><canvas id="c-over"></canvas>
        <span class="label" id="c-pic-label">Picture</span>
        <div class="tools"><div class="seg" id="c-mode"><button data-video="auto">Auto</button><button data-video="rgb">Colour</button><button data-video="ir">Infrared</button></div></div></div>
      <div class="stage" id="c-depth"><canvas id="c-dv" width="640" height="480"></canvas><span class="label" id="c-depth-label">Depth</span>
        <div class="depthscale"><span>0.4 m</span><img src="/hub/depth-scale.png" alt=""><span>4 m</span></div></div>
      <div class="stage" id="c-cloud"><canvas id="c-cv"></canvas><span class="label" id="c-cloud-label">Point cloud</span>
        <div class="tools"><div class="seg"><button data-colour="0" class="on">Picture</button><button data-colour="1">Depth</button></div>
          <button class="btn small" id="c-spin">Orbit</button><button class="btn small" id="c-reset">Reset</button><a class="btn small" href="/hub/cloud.ply" download>Export PLY</a></div></div>
      <div class="side">
        <div class="card"><h2>Kinect</h2><div id="c-state"><div class="skeleton"></div></div></div>
        <div class="card"><h2>Tilt</h2><div class="row"><b class="num" id="c-tilt" style="font-size:32px">–</b><span class="spacer"></span><input type="range" id="c-tilt-set" min="-27" max="27" step="1" style="width:170px"></div>
          <div class="row"><button class="btn small" data-tilt="-15">Down</button><button class="btn small" data-tilt="0">Level</button><button class="btn small" data-tilt="15">Up</button></div></div>
        <div class="card"><h2>Webcam and LED</h2>
          <label class="switch"><input type="checkbox" id="c-webcam">"Kinect Camera" for video calls</label>
          <p class="note" id="c-webcam-note"></p>
          <div class="leds" style="margin-top:12px"><button class="g" data-led="green" title="Green"></button><button class="y" data-led="yellow" title="Yellow"></button>
            <button class="r" data-led="red" title="Red"></button><button class="g" data-led="blink-green" title="Blinking green"></button><button class="o" data-led="off" title="Off"></button></div></div>
        <div class="card"><h2>People</h2><div id="c-people" class="list"></div><div class="row" style="margin-top:10px"><button class="btn small" id="c-measure">Measure everyone</button></div></div>
        <div class="card"><h2>Depth</h2><div id="c-depthstats"></div><div class="bars" id="c-hist"></div>
          <div class="row" style="margin-top:10px"><label class="field">Cloud density <select id="c-step"><option value="2">Full</option><option value="3">High</option><option value="4" selected>Medium</option><option value="6">Low</option></select></label>
          <label class="field">Points <input type="range" id="c-size" min="1" max="6" step="0.5" value="2" style="width:90px"></label></div></div>
      </div></div>`;
    stream("video", el.querySelector("#c-video"), el.querySelector("#c-pic-label"));
    stream("depth", el.querySelector("#c-dv"), el.querySelector("#c-depth-label"));
    startCloud(el.querySelector("#c-cv"));
    overlay(el.querySelector("#c-over"));
    poll = setInterval(refresh, 500);
    refresh();
    el.addEventListener("click", async (e) => {
      const t = e.target.closest("button");
      if (!t) return;
      if (t.dataset.video) { await K.hub("video", t.dataset.video); refresh(); }
      if (t.dataset.tilt !== undefined) K.hub("tilt", +t.dataset.tilt);
      if (t.dataset.led) K.hub("led", t.dataset.led);
      if (t.dataset.colour !== undefined) { colourBy = +t.dataset.colour; for (const b of t.parentElement.children) b.classList.toggle("on", b === t); }
      if (t.id === "c-spin") { orbit.v.spin = !orbit.v.spin; t.classList.toggle("primary", orbit.v.spin); }
      if (t.id === "c-reset") orbit.reset();
      if (t.id === "c-measure") measure(t);
    });
    el.querySelector("#c-tilt-set").onchange = (e) => K.hub("tilt", +e.target.value);
    el.querySelector("#c-webcam").onchange = (e) => K.hub("webcam", e.target.checked);
    el.querySelector("#c-step").onchange = (e) => { step = +e.target.value; };
    el.querySelector("#c-size").oninput = (e) => { size = +e.target.value; };
  }

  // Each view asks for the frame after the one it last drew, so it runs as fast as the Kinect.
  function stream(kind, canvas, label) {
    const ctx = canvas.getContext("2d");
    let seq = 0, n = 0, since = performance.now();
    (async function loop() {
      while (alive && canvas.isConnected) {
        if (document.hidden) { await new Promise((r) => setTimeout(r, 300)); continue; }
        try {
          const res = await fetch(`/hub/frame/${kind}.jpg?after=${seq}`, { cache: "no-store" });
          if (res.status !== 200) { await new Promise((r) => setTimeout(r, 500)); continue; }
          seq = Number(res.headers.get("X-Seq")) || seq;
          const bmp = await createImageBitmap(await res.blob());
          ctx.save(); ctx.translate(canvas.width, 0); ctx.scale(-1, 1);       // a mirror, like everywhere else
          ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height); ctx.restore();
          bmp.close(); n++;
          const now = performance.now();
          if (now - since > 1000) {
            const name = kind === "video" ? (status && status.mode === "ir" ? "Infrared" : "Colour") : "Depth";
            label.textContent = `${name} · ${Math.round((n * 1000) / (now - since))} fps`; n = 0; since = now;
          }
        } catch (err) { await new Promise((r) => setTimeout(r, 1000)); }
      }
    })();
    canvas.style.objectFit = "contain";
  }

  function overlay(canvas) {
    const draw = () => {
      if (!alive || !canvas.isConnected) return;
      const d = Math.min(2, window.devicePixelRatio || 1), W = canvas.clientWidth, H = canvas.clientHeight;
      if (canvas.width !== Math.round(W * d)) { canvas.width = Math.round(W * d); canvas.height = Math.round(H * d); }
      const ctx = canvas.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
      const size = (K.live.state.hub && K.live.state.hub.size) || [640, 480];
      const k = Math.min(W / size[0], H / size[1]), ox = (W - size[0] * k) / 2, oy = (H - size[1] * k) / 2;
      for (const p of K.live.state.people || []) {
        if (!p.skeleton) continue;
        const pts = p.skeleton.map((q, i) => (q[2] < 0.5 ? null : [ox + (1 - q[0]) * size[0] * k, oy + q[1] * size[1] * k, p.joints && p.joints[i] ? p.joints[i][3] : 1]));
        ctx.strokeStyle = p.slot === null || p.slot === undefined ? K.playerColour(p.colour) : K.playerColour(p.slot);
        ctx.lineWidth = 4; ctx.lineCap = "round";
        for (const [a, b] of GL3.BONES) {
          if (!pts[a] || !pts[b]) continue;
          ctx.setLineDash(pts[a][2] === 2 && pts[b][2] === 2 ? [] : [7, 7]);
          ctx.beginPath(); ctx.moveTo(pts[a][0], pts[a][1]); ctx.lineTo(pts[b][0], pts[b][1]); ctx.stroke();
        }
        ctx.setLineDash([]);
        const head = pts[0] || pts[11];
        if (head) {
          ctx.font = "750 16px Inter, system-ui"; ctx.textAlign = "center"; ctx.fillStyle = K.colour("text");
          ctx.fillText(`${p.posture || ""}${p.height_cm ? ` · ${p.height_cm} cm` : ""}${p.distance ? ` · ${p.distance} m` : ""}`, head[0], head[1] - 26);
        }
      }
      requestAnimationFrame(draw);
    };
    requestAnimationFrame(draw);
  }

  function startCloud(canvas) {
    cloud = GL3.create(canvas);
    if (!cloud) { canvas.insertAdjacentHTML("afterend", '<div class="empty"><b>No 3D here</b>WebGL is not available.</div>'); return; }
    orbit = GL3.orbit(canvas, { target: [0, 0, 1.6], dist: 1.7, pitch: 0.12 });
    let seq = 0, n = 0, last = performance.now(), count = 0, since = performance.now();
    const flipY = GL3.M.scale(1, -1, 1);                // camera frame (y down) -> y up
    const draw = (now) => {
      if (!alive || !canvas.isConnected) return;
      const dt = (now - last) / 1000; last = now;
      cloud.resize(); cloud.clear(GL3.rgba("window"));
      const eye = orbit.eye(dt);
      cloud.camera(eye, orbit.v.target, 0.9);
      n = cloud.points(flipY, size, colourBy);
      requestAnimationFrame(draw);
    };
    requestAnimationFrame(draw);
    (async function fetchLoop() {
      while (alive && canvas.isConnected) {
        if (document.hidden) { await new Promise((r) => setTimeout(r, 300)); continue; }
        try {
          const res = await fetch(`/hub/cloud.bin?step=${step}&after=${seq}`, { cache: "no-store" });
          if (res.status !== 200) { await new Promise((r) => setTimeout(r, 500)); continue; }
          const buf = await res.arrayBuffer();
          const head = new Uint32Array(buf, 0, 2);
          seq = head[1];
          // Depth's own frame: y down; the points are drawn y up (flipY) and seen from the Kinect.
          cloud.setPoints(new Float32Array(buf, 8, head[0] * 3), new Uint8Array(buf, 8 + head[0] * 12, head[0] * 3));
          count++;
          const now = performance.now();
          if (now - since > 1000) { root.querySelector("#c-cloud-label").textContent = `Point cloud · ${n.toLocaleString()} points · ${Math.round((count * 1000) / (now - since))} fps`; count = 0; since = now; }
        } catch (err) { await new Promise((r) => setTimeout(r, 1000)); }
      }
    })();
  }

  async function refresh() {
    if (!alive) return;
    try { status = await K.api("/hub/api/status"); } catch (e) { status = null; }
    const el = root.querySelector("#c-state");
    if (!el) return;
    if (!status) { el.innerHTML = '<p class="soft">The Kinect hub is not answering. It starts by itself when the app needs it; check that the Kinect has its power supply.</p>'; return; }
    for (const b of root.querySelectorAll("[data-video]")) b.classList.toggle("on", b.dataset.video === status.video);
    const kv = (k, v) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`;
    const lease = status.lease ? `held for ${K.esc(status.lease.owner)} (${status.lease.mode}, ${Math.round(status.lease.left)} s)` : "no";
    el.innerHTML = kv("State", K.esc(status.status)) + (status.error ? `<p class="why">${K.esc(status.error)}</p>` : "") +
      kv("Picture", `${status.mode === "ir" ? "Infrared" : "Colour"}${status.video === "auto" ? ` · auto (${status.auto})` : ""}`) +
      kv("Frame rate", `${status.fps} fps`) + kv("Light", status.light ?? "–") +
      kv("Pitch / roll", `${status.pitch}° / ${status.roll}°`) +
      kv("Camera switches", status.epoch ?? 0) + kv("Pairs dropped", `${status.unpaired ?? 0}`) + kv("Picture held", lease) +
      kv("Air gestures", status.air ? "reading" : "off");
    root.querySelector("#c-tilt").textContent = status.tilt === null || status.tilt === undefined ? "–" : `${status.tilt}°`;
    const w = status.webcam || {};
    root.querySelector("#c-webcam").checked = !!w.on;
    root.querySelector("#c-webcam-note").textContent = w.error || (w.on ? (w.streaming ? `On: ${w.device}` : "Starting…") : w.device ? `Ready (${w.device})` : "No loopback device yet: scripts/install-virtual-cameras.sh");
    const dpt = status.depth;
    if (dpt) {
      root.querySelector("#c-depthstats").innerHTML = kv("Valid", `${dpt.valid}%`) + kv("Nearest", dpt.nearest ? `${(dpt.nearest / 1000).toFixed(2)} m` : "–") +
        kv("Median", dpt.median ? `${(dpt.median / 1000).toFixed(2)} m` : "–") + kv("Farthest", dpt.farthest ? `${(dpt.farthest / 1000).toFixed(2)} m` : "–");
      root.querySelector("#c-hist").innerHTML = dpt.hist.map((v) => `<i style="height:${Math.max(2, v * 100)}%"></i>`).join("");
    }
    const ppl = K.live.state.people || [];
    root.querySelector("#c-people").innerHTML = ppl.map((p) => `<div class="item row"><span class="chip"><i style="background:${K.playerColour(p.slot ?? p.colour)}"></i>${p.slot !== null && p.slot !== undefined ? `P${p.slot + 1}` : `#${p.id}`}</span>
      ${K.esc(p.posture || "")}${p.height_cm ? ` · <b>${p.height_cm} cm</b>` : ""}${p.distance ? ` · ${p.distance} m away` : ""}</div>`).join("") || '<p class="muted">Nobody in view.</p>';
  }

  async function measure(btn) {
    btn.disabled = true; btn.textContent = "Measuring… stand straight";
    try {
      const r = await K.api("/hub/api/measure?seconds=6");
      K.toast(r.sentence || r.error || "Done", r.ok ? "" : "warn", 5000);
    } catch (e) { K.toast(e.message, "warn"); }
    btn.disabled = false; btn.textContent = "Measure everyone";
  }

  K.section("camera", {
    title: "Camera", mount,
    unmount() { alive = false; clearInterval(poll); cloud = null; },
  });
})();
