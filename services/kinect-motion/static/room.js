/* Room: the floor from above (everyone where they stand, which way they face, where they point,
   zones, the coverage map, and where activities fit from the camera's real geometry), who is in
   the room, zones, and the event feed. */
"use strict";

(() => {
  let root = null, alive = false, timer = null, offEvent = null, heat = false, coverage = null, zones = [], activity = "squat";
  const feed = [];

  function mount(el) {
    root = el; alive = true;
    el.innerHTML = `<div class="room">
      <div class="stage"><canvas id="r-map"></canvas><span class="label">From above: the Kinect at the top</span>
        <div class="hud" style="top:auto;bottom:16px;justify-content:flex-start;gap:10px;pointer-events:auto">
          <button class="btn small" id="r-heat">Coverage map</button>
          <label class="field" style="background:var(--shade);padding:6px 12px;border-radius:12px">Show where <select id="r-act"></select> fits</label></div></div>
      <div class="side">
        <div class="card"><h2>In the room</h2><div id="r-people" class="list"></div></div>
        <div class="card"><h2>Tracking coverage</h2><p class="soft">Walk slowly around the area you use, alone, for a minute. Green: the Kinect saw your whole body there; red: parts were hidden or out of view.</p>
          <div class="row" style="margin-top:10px"><button class="btn small" id="r-reset">Start over</button><span class="muted num" id="r-n"></span></div></div>
        <div class="card"><h2>Zones</h2><div id="r-zones" class="list"></div>
          <div class="row" style="margin-top:10px"><input id="z-name" type="text" placeholder="Name (sofa, lamp…)" maxlength="30" style="width:170px">
            <select id="z-on"><option value="floor">on the floor</option><option value="wall">on the TV wall</option></select></div>
          <div class="row"><label class="field">x <input id="z-a0" type="number" step="0.1" value="-0.5"> to <input id="z-a1" type="number" step="0.1" value="0.5"></label></div>
          <div class="row"><label class="field"><span id="z-b">z</span> <input id="z-b0" type="number" step="0.1" value="2.5"> to <input id="z-b1" type="number" step="0.1" value="3.5"></label>
            <button class="btn small" id="z-add">Add zone</button><button class="btn small" id="z-here">Where I stand</button></div>
          <p class="note">Metres from the Kinect. x: across (the map is a mirror, as you face the TV); z: away from the TV; y: height on the wall.</p></div>
        <div class="card"><h2>Events</h2><div class="feed" id="r-feed"></div>
          <p class="note">Live at <code>ws://127.0.0.1:8793/events</code> as small JSON messages. For Home Assistant, put its webhook in <code>motion.json</code> as <code>"webhook"</code>; nothing leaves this computer otherwise.</p></div>
      </div></div>`;
    K.catalog().then((cat) => {
      const opts = [...cat.exercises.map((e) => [e.key, e.name]), ["walls", "Wall Dodge"], ["pose", "Pose Match"], ["race", "Body Racer"]];
      el.querySelector("#r-act").innerHTML = opts.map(([k, n]) => `<option value="${k}" ${k === activity ? "selected" : ""}>${K.esc(n)}</option>`).join("");
    });
    el.querySelector("#r-act").onchange = (e) => { activity = e.target.value; };
    el.querySelector("#r-heat").onclick = (e) => { heat = !heat; e.target.classList.toggle("primary", heat); if (heat) loadCoverage(); };
    el.querySelector("#r-reset").onclick = async () => { coverage = await K.api("/api/coverage", {}); el.querySelector("#r-n").textContent = "0 samples"; };
    el.querySelector("#z-on").onchange = (e) => { el.querySelector("#z-b").textContent = e.target.value === "wall" ? "y" : "z"; };
    el.querySelector("#z-add").onclick = addZone;
    el.querySelector("#z-here").onclick = () => {
      const p = (K.live.state.people || []).find((q) => q.joints && q.joints[23] && q.joints[24]);
      if (!p) { K.toast("Stand in view first", "warn"); return; }
      const x = (p.joints[23][0] + p.joints[24][0]) / 2, z = (p.joints[23][2] + p.joints[24][2]) / 2;
      el.querySelector("#z-a0").value = (x - 0.4).toFixed(1); el.querySelector("#z-a1").value = (x + 0.4).toFixed(1);
      el.querySelector("#z-b0").value = (z - 0.4).toFixed(1); el.querySelector("#z-b1").value = (z + 0.4).toFixed(1);
    };
    el.addEventListener("click", async (ev) => {
      const t = ev.target.closest("button[data-del]");
      if (!t) return;
      zones.splice(+t.dataset.del, 1);
      await K.api("/api/settings", { zones }); loadZones();
    });
    offEvent = K.on("event", (e) => { if (["room", "joined", "left", "rejoined", "status"].includes(e.type)) log(e); });
    timer = setInterval(() => { panel(); if (heat) loadCoverage(); }, 1000);
    loadZones(); panel();
    requestAnimationFrame(draw);
  }

  function log(e) {
    const { type, t: _t, ...rest } = e;
    void _t;
    feed.push(`${new Date().toLocaleTimeString()}  ${rest.event || type}  ${JSON.stringify(Object.fromEntries(Object.entries(rest).filter(([k]) => k !== "event" && k !== "say")))}`);
    while (feed.length > 80) feed.shift();
    const f = root.querySelector("#r-feed");
    if (f) f.innerHTML = feed.map((l) => `<div>${K.esc(l)}</div>`).join("");
  }

  function draw() {
    if (!alive) return;
    const cv = root.querySelector("#r-map");
    if (!cv) return;
    const d = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight;
    if (cv.width !== Math.round(W * d)) { cv.width = Math.round(W * d); cv.height = Math.round(H * d); }
    const ctx = cv.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    const C = K.colour, st = K.live.state, sp = st.space;
    const depth = Math.max(4.5, sp && sp.room_end ? sp.room_end + 0.5 : 4.5);
    const s = Math.min(W / 5.6, (H - 90) / depth), X = (x) => W / 2 - x * s, Z = (z) => 46 + z * s;
    ctx.strokeStyle = C("grid"); ctx.lineWidth = 1;
    for (let z = 0; z <= depth; z += 0.5) { ctx.beginPath(); ctx.moveTo(X(2.8), Z(z)); ctx.lineTo(X(-2.8), Z(z)); ctx.stroke(); }
    for (let x = -2.5; x <= 2.5; x += 0.5) { ctx.beginPath(); ctx.moveTo(X(x), Z(0)); ctx.lineTo(X(x), Z(depth)); ctx.stroke(); }
    ctx.fillStyle = C("muted"); ctx.font = "13px Inter, system-ui"; ctx.textAlign = "left";
    for (let z = 1; z <= depth; z += 1) ctx.fillText(`${z} m`, X(2.7), Z(z) - 4);
    if (heat && coverage) {
      const { cell, x: [x0], z: [z0], grid } = coverage;
      grid.forEach((row, i) => row.forEach((v, j) => {
        if (v === null) return;
        ctx.fillStyle = v > 0.8 ? C("ok") : v > 0.6 ? C("yellow") : C("danger"); ctx.globalAlpha = 0.42;
        ctx.fillRect(X(x0 + (j + 1) * cell), Z(z0 + i * cell), cell * s, cell * s); ctx.globalAlpha = 1;
      }));
    }
    // What the Kinect sees (its real lens), and where the chosen activity fits.
    const fx = sp ? sp.lens[0] : 525, half = Math.atan(320 / fx);
    ctx.fillStyle = C("fill"); ctx.strokeStyle = C("line-2"); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(X(0), Z(0)); ctx.lineTo(X(depth * Math.tan(half)), Z(depth)); ctx.lineTo(X(-depth * Math.tan(half)), Z(depth)); ctx.closePath(); ctx.fill(); ctx.stroke();
    if (sp && sp.room_end) { ctx.strokeStyle = C("muted"); ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(X(2.8), Z(sp.room_end)); ctx.lineTo(X(-2.8), Z(sp.room_end)); ctx.stroke(); ctx.fillStyle = C("muted"); ctx.fillText("the room ends here", X(-2.75) - 120, Z(sp.room_end) - 8); }
    if (sp && sp.limit) { ctx.setLineDash([3, 6]); ctx.strokeStyle = C("warn"); ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(X(2.8), Z(sp.limit)); ctx.lineTo(X(-2.8), Z(sp.limit)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = C("warn"); ctx.fillText(`your ${sp.limit} m`, X(-2.75) - 70, Z(sp.limit) - 8); }
    const f = sp && sp.activities.find((a) => a.activity === activity);
    if (f && f.band) {
      const [z0, z1] = f.band, t = Math.tan(half), m = 0.4;
      ctx.setLineDash([8, 8]); ctx.strokeStyle = C("ok"); ctx.fillStyle = C("ok-tint"); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(X(Math.max(0.05, z0 * t - m)), Z(z0)); ctx.lineTo(X(Math.max(0.05, z1 * t - m)), Z(z1));
      ctx.lineTo(X(-Math.max(0.05, z1 * t - m)), Z(z1)); ctx.lineTo(X(-Math.max(0.05, z0 * t - m)), Z(z0)); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.setLineDash([]);
    } else if (f) {
      ctx.fillStyle = C("warn"); ctx.font = "650 17px Inter, system-ui"; ctx.textAlign = "center";
      ctx.fillText(`${K.activityName(activity)} doesn't fit anywhere from here: Settings shows why`, W / 2, 96);
    }
    ctx.fillStyle = C("text"); ctx.fillRect(X(0.6), Z(0) - 12, 1.2 * s, 8);
    ctx.fillStyle = C("accent"); ctx.beginPath(); ctx.arc(X(0), Z(0), 8, 0, Math.PI * 2); ctx.fill();
    for (const zn of zones) {
      if ((zn.on || "floor") !== "floor") continue;
      ctx.strokeStyle = C("purple"); ctx.lineWidth = 2; ctx.fillStyle = C("purple"); ctx.globalAlpha = 0.16;
      ctx.fillRect(X(zn.x[1]), Z(zn.z[0]), (zn.x[1] - zn.x[0]) * s, (zn.z[1] - zn.z[0]) * s);
      ctx.globalAlpha = 1; ctx.strokeRect(X(zn.x[1]), Z(zn.z[0]), (zn.x[1] - zn.x[0]) * s, (zn.z[1] - zn.z[0]) * s);
      ctx.fillStyle = C("purple"); ctx.font = "650 15px Inter, system-ui"; ctx.textAlign = "left"; ctx.fillText(zn.name, X(zn.x[1]) + 6, Z(zn.z[0]) + 19);
    }
    for (const p of K.people()) {
      if (!p.joints || !p.joints[23] || !p.joints[24]) continue;
      const hx = (p.joints[23][0] + p.joints[24][0]) / 2, hz = (p.joints[23][2] + p.joints[24][2]) / 2;
      const col = p.slot === null || p.slot === undefined ? K.playerColour(p.colour) : K.playerColour(p.slot);
      if (p.joints[11] && p.joints[12]) { ctx.strokeStyle = col; ctx.lineWidth = 6; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(X(p.joints[11][0]), Z(p.joints[11][2])); ctx.lineTo(X(p.joints[12][0]), Z(p.joints[12][2])); ctx.stroke(); }
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(X(hx), Z(hz), 15, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = C("black"); ctx.font = "800 14px Inter, system-ui"; ctx.textAlign = "center";
      ctx.fillText(p.slot !== null && p.slot !== undefined ? `P${p.slot + 1}` : `${p.id}`, X(hx), Z(hz) + 5);
      ctx.textAlign = "left"; ctx.fillStyle = C("soft"); ctx.font = "14px Inter, system-ui";
      ctx.fillText(`${p.posture || ""}${p.height_cm ? ` · ${p.height_cm} cm` : ""}`, X(hx) + 20, Z(hz) + 5);
      if (p.pointing && p.pointing.at === "floor") {
        const [px, pz] = p.pointing.point;
        ctx.strokeStyle = C("yellow"); ctx.setLineDash([4, 6]); ctx.beginPath(); ctx.moveTo(X(hx), Z(hz)); ctx.lineTo(X(px), Z(pz)); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = C("yellow"); ctx.beginPath(); ctx.arc(X(px), Z(pz), 9, 0, Math.PI * 2); ctx.fill();
      }
    }
    requestAnimationFrame(draw);
  }

  function panel() {
    const el = root && root.querySelector("#r-people");
    if (!el) return;
    const st = K.live.state;
    el.innerHTML = (st.people || []).map((p) => {
      const h = p.joints && p.joints[23];
      return `<div class="item"><b>${p.slot !== null && p.slot !== undefined ? `Player ${p.slot + 1}` : `Person ${p.id}`}</b> · ${K.esc(p.posture || "")}${p.height_cm ? ` · ${p.height_cm} cm` : ""}
        ${h ? `<br><span class="muted num">x ${h[0].toFixed(2)} m · z ${h[2].toFixed(2)} m from the Kinect</span>` : ""}
        ${p.pointing ? `<br><span class="soft">pointing at the ${p.pointing.at}</span>` : ""}</div>`;
    }).join("") + (st.tracking && st.tracking.hidden ? `<p class="muted">${st.tracking.hidden} hidden behind someone (not shown: only what the camera sees now is drawn)</p>` : "") ||
      '<p class="muted">Nobody in view.</p>';
  }

  async function loadCoverage() {
    coverage = await K.api("/api/coverage").catch(() => null);
    const n = root && root.querySelector("#r-n");
    if (n && coverage) n.textContent = `${coverage.samples} samples`;
  }
  async function loadZones() {
    const s = await K.api("/api/settings").catch(() => ({}));
    zones = s.zones || [];
    const el = root.querySelector("#r-zones");
    if (el) el.innerHTML = zones.map((z, i) => `<div class="item row"><b>${K.esc(z.name)}</b><span class="muted">${z.on || "floor"} · x ${z.x.join("…")} · ${z.on === "wall" ? `y ${z.y.join("…")}` : `z ${z.z.join("…")}`}</span>
      <span class="spacer"></span><button class="btn small" data-del="${i}">Remove</button></div>`).join("") || '<p class="muted">No zones yet.</p>';
  }
  async function addZone() {
    const v = (id) => root.querySelector(id).value;
    const name = v("#z-name").trim();
    if (!name) return;
    const on = v("#z-on"), a = [+v("#z-a0"), +v("#z-a1")].sort((p, q) => p - q), b = [+v("#z-b0"), +v("#z-b1")].sort((p, q) => p - q);
    zones.push(on === "wall" ? { name, on, x: a, y: b } : { name, on, x: a, z: b });
    await K.api("/api/settings", { zones }); root.querySelector("#z-name").value = ""; loadZones();
  }

  K.section("room", { title: "Room", mount, unmount() { alive = false; clearInterval(timer); if (offEvent) offEvent(); } });
})();
