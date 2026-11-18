/* Scan: guided 3D scanning. Choose the subject -> frame it -> capture -> reconstruct -> inspect
   -> export or save. The server runs the job (scan.py, scan_worker.py): it holds the Kinect in
   infrared depth while framing and capturing, and deletes the depth captures as soon as there is
   a result. Nothing is kept unless you press Save (into ~/Kinect Scans) or Export (a download). */
"use strict";

(() => {
  let root = null, job = null, timer = null, offEvent = null, previewOn = false, viewer = null, roiDrag = null;
  const KINDS = {
    object: { name: "Object", line: "A still object: one view of the side facing the Kinect. Quickest; its back is not seen.", glyph: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>' },
    rotating: { name: "Turning object", line: "Turn it in place in twelve steps, letting go each time: the whole way round.", glyph: '<path d="M12 4a8 8 0 1 1-7.4 5"/><path d="M4 4v5h5"/>' },
    person: { name: "Person", line: "Stand still and turn on the spot in eight steps when asked: a 3D you.", glyph: '<circle cx="12" cy="5" r="2.5"/><path d="M12 8v7M8 11h8M12 15l-3 6M12 15l3 6"/>' },
  };
  const STEPS = ["Subject", "Frame", "Capture", "Build", "Inspect", "Export"];

  function stepOf(j) {
    if (!j) return 0;
    if (j.state === "failed") return 4;                 // the failure is shown where the result would be
    if (j.state === "framing" || j.state === "background") return 1;
    if (j.state === "capturing") return 2;
    if (j.state === "captured" || j.state === "reconstructing") return 3;
    if (j.state === "done") return 4;
    return 1;
  }

  async function mount(el) {
    root = el;
    el.innerHTML = `<div class="scan"><div class="stage" id="s-stage"></div><div class="side" id="s-side"></div></div>`;
    offEvent = K.on("event", (e) => { if (e.type === "scan") { job = e; render(); } });
    job = await K.api("/api/scan").catch(() => null);
    render();
    timer = setInterval(async () => { if (job && ["capturing", "reconstructing", "background", "captured"].includes(job.state)) { job = await K.api("/api/scan").catch(() => job); render(); } }, 1000);
  }

  // -- the right-hand panel and the stage, per step -----------------------------------------
  let shown = null;
  function render() {
    const step = stepOf(job), key = `${step}|${job ? job.state : ""}|${job ? job.id : ""}`;
    const side = root.querySelector("#s-side");
    const wiz = `<div class="wizard">${STEPS.map((s, i) => `<span class="${i < step ? "done" : i === step ? "on" : ""}">${s}</span>`).join("")}</div>`;
    if (key !== shown) {
      shown = key;
      stopPreview(); stopViewer();
      if (step === 0) chooseView(side, wiz);
      else if (step === 1) frameView(side, wiz);
      else if (step === 2 || step === 3) workView(side, wiz, step);
      else inspectView(side, wiz);
    }
    if (step === 2 || step === 3) workUpdate(step);
    if (step === 1) frameUpdate();
  }

  async function chooseView(side, wiz) {
    const stage = root.querySelector("#s-stage");
    stage.innerHTML = `<div class="tiles" style="position:absolute;inset:24px;grid-template-columns:repeat(3,minmax(0,1fr));align-content:center">
      ${Object.entries(KINDS).map(([k, d]) => `<button class="tile" data-kind="${k}" style="min-height:240px"><svg class="glyph" viewBox="0 0 24 24">${d.glyph}</svg><b style="font-size:26px">${d.name}</b><span>${d.line}</span></button>`).join("")}</div>`;
    const saved = await K.api("/api/scans").catch(() => []);
    side.innerHTML = `${wiz}<div class="card"><h2>3D scanning</h2><p class="soft">Pick what to scan. The Kinect's depth is good to a few millimetres at arm's length and a couple of centimetres across the room; it sees only surfaces facing it, and nothing it did not see is made up.</p>
      <p class="note">While you scan, the Kinect stays in infrared depth. A workout or game has to be paused first.</p></div>
      <div class="card"><h2>Saved scans</h2><div class="list">${saved.map((s) => `<div class="item"><b>${K.esc(s.name)}</b> · ${K.esc(KINDS[s.kind] ? KINDS[s.kind].name : s.kind)}
        <br><span class="muted">${new Date(s.at * 1000).toLocaleString()} · ${s.report && s.report.aabb_extent_mm ? s.report.aabb_extent_mm.map((v) => Math.round(v)).join(" × ") + " mm" : ""}${s.report && s.report.complete ? "" : " · incomplete"}</span>
        <br><span class="muted">${K.esc(s.path)}</span><div class="row" style="margin-top:6px"><button class="btn small" data-forget-scan="${s.id}">Remove from list</button><button class="btn small danger" data-delete-scan="${s.id}">Delete files</button></div></div>`).join("") || '<p class="muted">None yet. Saved scans go to the Kinect Scans folder in your home.</p>'}</div></div>`;
  }

  // -- framing: the live depth view ----------------------------------------------------------
  function frameView(side, wiz) {
    const stage = root.querySelector("#s-stage");
    stage.innerHTML = `<img id="s-prev" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain">
      <canvas id="s-roi" style="position:absolute;inset:0;width:100%;height:100%;cursor:crosshair"></canvas>
      <div class="guide" id="s-guide">Waiting for the Kinect…</div><span class="label">Depth · the subject is lit</span>`;
    const seg = job.segment || {};
    const k = job.kind;
    side.innerHTML = `${wiz}<div class="card"><h2>Frame the ${k === "person" ? "person" : "object"}</h2>
        <p class="soft">${k === "person" ? "Stand 1.6 to 2.6 m from the Kinect with all of you in the picture, arms a little away from your body." :
          "Put it 0.6 to 1 m from the Kinect, on something plain, with space around it."}</p>
        <div class="kv"><span>Distance</span><b id="s-dist">–</b></div><div class="kv"><span>Size</span><b id="s-size">–</b></div>
        <h3>Depth range</h3><div class="row"><label class="field">From <input type="number" id="s-zmin" min="0.4" max="4" step="0.05" value="${seg.z_min}"> m</label>
          <label class="field">to <input type="number" id="s-zmax" min="0.5" max="5" step="0.05" value="${seg.z_max}"> m</label></div>
        <p class="note">Only what lies in this range is the subject. Drag on the picture to keep only an area${seg.roi ? ' (<a href="#" id="s-clear-roi">clear it</a>)' : ""}.</p>
        <h3>Background</h3><div class="row"><button class="btn small" id="s-bg">${job.background ? "Capture it again" : "Capture the empty background"}</button>${job.background ? '<span class="badge ok">Captured</span><button class="btn small" id="s-bg-clear">Clear</button>' : ""}</div>
        <p class="note">Take the subject out of view first. Then only what is in front of the background counts.</p>
        ${job.error ? `<p class="why">${K.esc(job.error)}</p>` : ""}
        <div class="row" style="margin-top:16px"><button class="btn" id="s-back">Back</button><span class="spacer"></span><button class="btn primary big" id="s-capture">Capture</button></div></div>`;
    side.querySelector("#s-zmin").onchange = side.querySelector("#s-zmax").onchange = () =>
      K.api("/api/scan", { segment: { z_min: +side.querySelector("#s-zmin").value, z_max: +side.querySelector("#s-zmax").value } }, "PATCH").then((j) => { job = j; });
    const clr = side.querySelector("#s-clear-roi");
    if (clr) clr.onclick = (e) => { e.preventDefault(); K.api("/api/scan", { segment: { roi: null } }, "PATCH").then((j) => { job = j; shown = null; render(); }); };
    side.querySelector("#s-bg").onclick = () => K.api("/api/scan/run", { what: "background" }).then((j) => { job = j; K.toast("Keep the scene empty…"); }).catch((e) => K.toast(e.message, "warn"));
    const bgc = side.querySelector("#s-bg-clear");
    if (bgc) bgc.onclick = () => K.api("/api/scan", { segment: { background: false } }, "PATCH").then((j) => { job = j; shown = null; render(); });
    side.querySelector("#s-back").onclick = discard;
    side.querySelector("#s-capture").onclick = capture;
    roiInput(root.querySelector("#s-roi"));
    startPreview();
  }

  let stats = null;
  function startPreview() {
    previewOn = true;
    (async function loop() {
      while (previewOn && root.querySelector("#s-prev")) {
        try {
          const r = await K.api("/api/scan/preview");
          const img = root.querySelector("#s-prev"), g = root.querySelector("#s-guide");
          if (!img) break;
          if (r.waiting) { g.textContent = r.waiting; g.className = "guide"; }
          else {
            if (r.jpg) img.src = `data:image/jpeg;base64,${r.jpg}`;
            stats = r.stats;
            g.textContent = stats.say; g.className = `guide ${stats.ok ? "ok" : "warn"}`;
          }
        } catch (e) { await new Promise((res) => setTimeout(res, 700)); }
        await new Promise((res) => setTimeout(res, 120));
      }
    })();
  }
  function stopPreview() { previewOn = false; }
  function frameUpdate() {
    if (!stats || !root.querySelector("#s-dist")) return;
    root.querySelector("#s-dist").textContent = stats.distance ? `${stats.distance} m` : "–";
    root.querySelector("#s-size").textContent = stats.size_mm ? `${stats.size_mm.map((v) => Math.round(v / 10)).join(" × ")} cm` : "–";
  }
  setInterval(() => { if (root && root.isConnected) frameUpdate(); }, 400);

  // Drag a rectangle on the (mirrored) preview: the area the subject must be in.
  function roiInput(cv) {
    const toImage = (e) => {
      const r = cv.getBoundingClientRect(), k = Math.min(r.width / 640, r.height / 480);
      const ox = (r.width - 640 * k) / 2, oy = (r.height - 480 * k) / 2;
      const x = (e.clientX - r.left - ox) / k, y = (e.clientY - r.top - oy) / k;
      return [Math.max(0, Math.min(640, 640 - x)), Math.max(0, Math.min(480, y))];      // un-mirror
    };
    cv.onpointerdown = (e) => { roiDrag = { a: toImage(e), b: toImage(e) }; cv.setPointerCapture(e.pointerId); };
    cv.onpointermove = (e) => {
      if (!roiDrag) return;
      roiDrag.b = toImage(e);
      const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
      cv.width = r.width * d; cv.height = r.height * d;
      const ctx = cv.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0);
      const k = Math.min(r.width / 640, r.height / 480), ox = (r.width - 640 * k) / 2, oy = (r.height - 480 * k) / 2;
      const X = (x) => ox + (640 - x) * k, Y = (y) => oy + y * k;
      ctx.strokeStyle = K.colour("white"); ctx.lineWidth = 2; ctx.setLineDash([8, 6]);
      ctx.strokeRect(X(roiDrag.a[0]), Y(roiDrag.a[1]), X(roiDrag.b[0]) - X(roiDrag.a[0]), Y(roiDrag.b[1]) - Y(roiDrag.a[1]));
    };
    cv.onpointerup = () => {
      if (!roiDrag) return;
      const [a, b] = [roiDrag.a, roiDrag.b];
      roiDrag = null;
      cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);
      const roi = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])].map(Math.round);
      if (roi[2] - roi[0] < 20 || roi[3] - roi[1] < 20) return;
      K.api("/api/scan", { segment: { roi } }, "PATCH").then((j) => { job = j; shown = null; render(); });
    };
  }

  // -- capturing and building ------------------------------------------------------------------
  function workView(side, wiz, step) {
    const stage = root.querySelector("#s-stage");
    const turns = job.kind === "person" ? 8 : job.kind === "rotating" ? 12 : 0;
    stage.innerHTML = step === 2 ? `<img id="s-prev" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain"><div class="guide" id="s-guide"></div>` :
      '<div class="empty"><div class="spinner"></div><b id="s-build">Building the 3D model…</b><span id="s-build-2"></span></div>';
    side.innerHTML = `${wiz}<div class="card"><h2>${step === 2 ? "Capturing" : "Building"}</h2>
      <p class="soft" id="s-say">${step === 2 ? (turns ? "Follow the instructions on the screen." : "Hold it still…") : "Lining up the views, then fusing them into one surface."}</p>
      <div class="progress" style="margin-top:14px"><i id="s-prog" style="width:0%"></i></div>
      ${turns && step === 2 ? `<div class="turns" id="s-turns" style="grid-template-columns:repeat(${turns},1fr)">${Array.from({ length: turns }, () => "<i></i>").join("")}</div>
        <h3>Holding still</h3><div class="progress"><i id="s-still" style="width:0%;background:var(--ok)"></i></div>` : ""}
      <div class="row" style="margin-top:16px"><span class="spacer"></span><button class="btn danger" id="s-cancel">Cancel</button></div>
      <p class="note">Cancel stops at once and deletes everything captured so far.</p></div>`;
    side.querySelector("#s-cancel").onclick = async () => { await K.api("/api/scan/cancel", {}); K.toast("Scan cancelled: nothing kept"); job = null; shown = null; render(); };
    if (step === 2) startPreview();
  }
  let lastTurn = null;
  function workUpdate(step) {
    const p = root.querySelector("#s-prog");
    if (p) p.style.width = `${Math.round(100 * (job.progress || 0))}%`;
    if (step === 3) {
      const b = root.querySelector("#s-build");
      if (b) b.textContent = { register: "Lining up the views…", fuse: "Fusing them into one surface…", mesh: "Building the mesh…" }[job.stage] || "Building the 3D model…";
      return;
    }
    const t = job.turn || {};
    if (job.message && root.querySelector("#s-say")) root.querySelector("#s-say").textContent = job.message;
    const g = root.querySelector("#s-guide");
    if (g && t.say) { g.textContent = t.say; g.className = "guide"; }
    const grid = root.querySelector("#s-turns");
    if (grid && t.turn !== undefined) [...grid.children].forEach((c, i) => { c.className = i < t.turn || (i === t.turn && t.taken) ? "done" : i === t.turn ? "cur" : ""; });
    const still = root.querySelector("#s-still");
    if (still) still.style.width = `${Math.round(100 * (t.still || 0))}%`;
    if (t.taken && lastTurn !== t.turn) { lastTurn = t.turn; K.sound("pass"); }
  }

  // -- inspecting and exporting ----------------------------------------------------------------
  async function inspectView(side, wiz) {
    const stage = root.querySelector("#s-stage");
    if (job.state === "failed") {
      stage.innerHTML = `<div class="empty"><b>The scan did not work</b><span>${K.esc(job.error || "")}</span></div>`;
      side.innerHTML = `${wiz}<div class="card"><h2>What happened</h2><p class="why">${K.esc(job.error || "")}</p><p class="note">The captures were deleted. Nothing was kept.</p>
        <div class="row" style="margin-top:14px"><button class="btn primary" id="s-again">Capture again</button><button class="btn" id="s-discard">Start over</button></div></div>`;
      side.querySelector("#s-again").onclick = capture;
      side.querySelector("#s-discard").onclick = discard;
      return;
    }
    const r = job.result;
    stage.innerHTML = `<canvas id="s-gl"></canvas><span class="label">Drag to turn · right-drag to move · scroll to zoom</span>
      <div class="hud" style="top:auto;bottom:16px;justify-content:flex-start;pointer-events:auto"><div class="seg" id="s-show"><button data-show="mesh" class="on">Surface</button><button data-show="points">Points</button></div></div>`;
    startViewer(stage.querySelector("#s-gl"));
    stage.querySelector("#s-show").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; for (const x of b.parentElement.children) x.classList.toggle("on", x === b); viewer.show = b.dataset.show; };
    const ext = r.aabb_extent_mm || [0, 0, 0], obb = r.pca_obb_extent_mm || [0, 0, 0];
    const cov = r.coverage || {};
    const missing = [];
    if (cov.missing) missing.push(cov.missing);
    if (cov.missing_angles && cov.missing_angles.length) missing.push(`turns at ${cov.missing_angles.map((a) => `${Math.round(a)}°`).join(", ")} did not line up and were left out`);
    side.innerHTML = `${wiz}<div class="card"><div class="row"><h2 style="margin:0">${K.esc(KINDS[job.kind].name)}</h2><span class="spacer"></span>
        <span class="badge ${r.complete ? "ok" : "no"}">${r.complete ? "Complete" : "Incomplete"}</span></div>
        <h3>Size</h3><div class="kv"><span>Across × up × deep</span><b>${ext.map((v) => Math.round(v)).join(" × ")} mm</b></div>
        <div class="kv"><span>Along its own axes</span><b>${obb.map((v) => Math.round(v)).join(" × ")} mm</b></div>
        <h3>What was seen</h3><div class="kv"><span>Views fused</span><b>${cov.views}${cov.of ? ` of ${cov.of}` : ""}</b></div>
        <div class="kv"><span>Open edges</span><b>${r.open_edges}${r.closed ? " (closed)" : ""}</b></div>
        ${missing.length ? `<p class="why">Not seen: ${K.esc(missing.join("; "))}. Nothing there was filled in.</p>` : ""}
        ${r.alignment_failure ? `<p class="why">${K.esc(r.alignment_failure.kept)}: ${K.esc(r.alignment_failure.why || "")}</p>` : ""}
        <p class="note">Extents of the surface the Kinect saw, not certified dimensions. ${job.kind === "object" ? "One view: depth here is how far the visible surface goes, not the object's real depth." : ""}</p></div>
      <div class="card"><h2>Export</h2><div class="row"><a class="btn" href="/api/scan/${job.id}/export?format=stl&units=mm" download>STL · mm</a>
        <a class="btn" href="/api/scan/${job.id}/export?format=obj&units=m" download>OBJ · m</a><a class="btn" href="/api/scan/${job.id}/export?format=obj&units=mm" download>OBJ · mm</a>
        <a class="btn" href="/api/scan/${job.id}/export?format=ply&units=m" download>PLY · m</a></div>
        <p class="note">Each file gets a .units.json beside it: STL cannot say its own units.</p>
        <h3>Save</h3><div class="row"><input type="text" id="s-name" placeholder="Name" maxlength="60" style="flex:1"><button class="btn primary" id="s-save">Save</button></div>
        <p class="note">Saves every format and the measurement report in ~/Kinect Scans.</p>
        <div class="row" style="margin-top:14px"><button class="btn" id="s-new">Scan again</button><button class="btn danger" id="s-discard">Discard</button></div></div>`;
    side.querySelector("#s-save").onclick = async () => {
      const res = await K.api(`/api/scan/${job.id}/save`, { name: side.querySelector("#s-name").value }).catch((e) => ({ error: e.message }));
      K.toast(res.error ? res.error : `Saved to ${res.path}`, res.error ? "warn" : "", 5000);
    };
    side.querySelector("#s-new").onclick = discard;
    side.querySelector("#s-discard").onclick = discard;
  }

  function startViewer(canvas) {
    const r = GL3.create(canvas);
    if (!r) return;
    viewer = { r, show: "mesh", alive: true, orbit: GL3.orbit(canvas, { target: [0, 0, 1], dist: 1.2, pitch: 0.25 }) };
    fetch(`/api/scan/${job.id}/geometry.bin`).then((x) => x.arrayBuffer()).then((buf) => {
      const [np, nv, nt] = new Uint32Array(buf, 0, 3);
      let off = 12;
      const pts = new Float32Array(buf, off, np * 3); off += np * 12;
      const verts = new Float32Array(buf, off, nv * 3); off += nv * 12;
      const tris = new Uint32Array(buf, off, nt * 3);
      r.setPoints(pts, null);
      if (nt) r.setMesh(verts, tris); else viewer.show = "points";
      let c = [0, 0, 0];
      for (let i = 0; i < np; i++) { c[0] += pts[i * 3]; c[1] += pts[i * 3 + 1]; c[2] += pts[i * 3 + 2]; }
      c = c.map((v) => v / Math.max(1, np));
      viewer.orbit.v.target = [c[0], -c[1], c[2]];
      let ext = 0;
      for (let i = 0; i < np; i += 50) ext = Math.max(ext, Math.hypot(pts[i * 3] - c[0], pts[i * 3 + 1] - c[1], pts[i * 3 + 2] - c[2]));
      viewer.orbit.v.dist = Math.max(0.4, ext * 3);
    });
    const flipY = GL3.M.scale(1, -1, 1);
    let last = performance.now();
    const frame = (now) => {
      if (!viewer || !viewer.alive || !canvas.isConnected) return;
      const dt = (now - last) / 1000; last = now;
      r.resize(); r.clear(GL3.rgba("window"));
      r.camera(viewer.orbit.eye(dt), viewer.orbit.v.target, 0.8);
      r.light = viewer.orbit.eye(0).map((v, i) => v - viewer.orbit.v.target[i]);
      if (viewer.show === "mesh" && r.hasMesh()) r.draw("mesh", flipY, GL3.rgba("accent"));
      else r.points(flipY, 2, 2, GL3.rgba("cyan"));
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }
  function stopViewer() { if (viewer) viewer.alive = false; viewer = null; }

  // -- actions -----------------------------------------------------------------------------------
  async function choose(kind) {
    try { job = await K.api("/api/scan", { kind }); }
    catch (e) {
      let info = null;
      try { info = JSON.parse(e.message); } catch (x) { info = null; }
      if (info && info.needs_pause) {
        const m = K.modal(`<h1>Pause and scan?</h1><p class="soft" style="font-size:19px">${K.esc(info.say)} Scanning needs the Kinect in infrared depth for a while.</p>
          <div class="row" style="margin-top:20px"><button class="btn primary big" id="m-yes">Pause it and scan</button><button class="btn" data-close>Not now</button></div>`);
        m.el.querySelector("#m-yes").onclick = async () => { m.close(); job = await K.api("/api/scan", { kind, pause_activity: true }); shown = null; render(); };
        return;
      }
      K.toast(e.message, "warn"); return;
    }
    shown = null; render();
  }
  async function capture() {
    if (stats && !stats.ok && !confirm(`${stats.say}\n\nCapture anyway?`)) return;
    try { job = await K.api("/api/scan/run", { what: "capture" }); shown = null; render(); }
    catch (e) { K.toast(e.message, "warn"); }
  }
  async function discard() { await K.api("/api/scan", undefined, "DELETE").catch(() => {}); job = null; shown = null; render(); }

  K.section("scan", {
    title: "Scan",
    mount(el) {
      mount(el);
      el.addEventListener("click", async (e) => {
        const t = e.target.closest("button");
        if (!t) return;
        if (t.dataset.kind) { K.sound("select"); choose(t.dataset.kind); }
        if (t.dataset.forgetScan) { await K.api(`/api/scans/${t.dataset.forgetScan}`, undefined, "DELETE"); shown = null; render(); }
        if (t.dataset.deleteScan && confirm("Delete this scan's files from the Kinect Scans folder?")) { await K.api(`/api/scans/${t.dataset.deleteScan}?files=1`, undefined, "DELETE"); shown = null; render(); }
      });
    },
    unmount() { clearInterval(timer); stopPreview(); stopViewer(); if (offEvent) offEvent(); shown = null; },
    back() { if (job && stepOf(job) === 1) { discard(); return true; } return false; },
  });
})();
