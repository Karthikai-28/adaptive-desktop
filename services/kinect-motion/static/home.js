/* Home: the room as the Kinect sees it now, everyone in it as a figure, and the way in to
   everything else. Big tiles (hover with your hand, arrows and Enter, or a click). */
"use strict";

(() => {
  const ICONS = {
    fitness: '<path d="M6 8v8M18 8v8M3 10v4M21 10v4M6 12h12"/>',
    games: '<rect x="3" y="7" width="18" height="11" rx="5"/><path d="M8 11v3M6.5 12.5h3M15.5 12h.01M17.5 14h.01"/>',
    camera: '<path d="M4 8h3l2-2h6l2 2h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    room: '<path d="M3 11l9-7 9 7v9H3z"/><path d="M9 20v-6h6v6"/>',
    scan: '<path d="M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4"/><path d="M12 7l4 2.5v5L12 17l-4-2.5v-5z"/>',
    history: '<path d="M4 19V5M4 19h16M8 15v-4M12 15V8M16 15v-6"/>',
  };
  const TILES = [
    ["fitness", "Fitness", "Workouts that count your reps and coach your form"],
    ["games", "Games", "Wall Dodge, Pose Match and Body Racer"],
    ["camera", "Camera", "Colour, infrared, depth and the 3D point cloud"],
    ["room", "Room", "Who is where, zones, and where the Kinect sees you well"],
    ["scan", "Scan", "Guided 3D scans of objects and people"],
    ["history", "History", "Your workouts, scores and progress"],
  ];
  let scene = null, timer = null;

  function mount(el) {
    el.innerHTML = `<div class="home">
      <div class="stage" id="h-stage"><div class="welcome"><div><h1 id="h-title">Step in front of the TV</h1>
        <p id="h-sub">The Kinect is looking for you.</p></div>
        <div class="counts"><div class="count"><b id="h-seen">0</b><span>in view</span></div>
          <div class="count"><b id="h-hidden">0</b><span>hidden</span></div>
          <div class="count"><b id="h-play">0</b><span>playing</span></div></div></div></div>
      <div class="tiles">${TILES.map(([k, n, d]) => `<button class="tile" data-go="${k}"><svg class="glyph" viewBox="0 0 24 24">${ICONS[k]}</svg><b>${n}</b><span>${d}</span></button>`).join("")}</div>
      <div class="card fitcard" id="h-fit"><div class="skeleton"></div></div>
    </div>`;
    scene = K.scene(el.querySelector("#h-stage"), { decorate: label });
    el.addEventListener("click", (e) => {
      const t = e.target.closest("[data-go]");
      if (t) { K.sound("select"); K.go(t.dataset.go); }
      if (e.target.closest("[data-settings]")) K.settings();
      const tb = e.target.closest("[data-tilt-by]");
      if (tb) { tb.disabled = true; K.api("/api/calibration", { tilt_by: +tb.dataset.tiltBy }).then((r) => K.toast(`Tilting the Kinect to ${r.tilt}°`)).catch((err) => K.toast(err.message, "warn")); }
    });
    timer = setInterval(update, 400);
    update();
  }

  function label(ctx, W, H, people, r) {
    for (const p of people) {
      if (!p.joints || !p.joints[0]) continue;
      const at = r.project([p.joints[0][0], p.joints[0][1] + 0.32, p.joints[0][2]]);
      if (!at) continue;
      const playing = p.slot !== null && p.slot !== undefined;
      ctx.font = "800 20px Inter, system-ui"; ctx.textAlign = "center";
      ctx.fillStyle = playing ? K.playerColour(p.slot) : K.colour("muted");
      ctx.fillText(playing ? `P${p.slot + 1}` : p.height_cm ? `${p.height_cm} cm` : "", at[0], at[1]);
    }
  }

  async function update() {
    const st = K.live.state, t = st.tracking || {};
    const seen = t.visible ?? (st.people || []).length;
    K.$("#h-seen").textContent = seen;
    K.$("#h-hidden").textContent = t.hidden || 0;
    K.$("#h-play").textContent = t.active || 0;
    const players = st.players || [];
    K.$("#h-title").textContent = !K.live.connected ? "Connecting…" : st.hub_error ? "The Kinect isn't ready" :
      seen ? (players.length ? `Hello${players.length > 1 ? ", everyone" : ""}` : seen > 1 ? `${seen} people in view` : "I can see you") : "Step in front of the TV";
    K.$("#h-sub").textContent = st.hub_error ? st.hub_error :
      seen && !players.length ? "Raise a hand to join, then pick something to do." :
        players.length ? "Hold a hand out towards the screen to point, and hover to choose." : "Stand where the floor lines are, facing the TV.";
    const fit = K.$("#h-fit");
    const sp = st.space;
    if (!sp) {
      fit.innerHTML = `<h2>Your space</h2><p class="soft">${st.fresh === false ? "Waiting for the Kinect's first pictures…" : "The Kinect has not found the floor yet: clear the floor in front of it, or tilt it down a little."}</p>`;
      return;
    }
    const n = sp.activities.filter((a) => a.fits).length, all = sp.activities.length;
    const hint = sp.tilt_hint;
    const better = hint && hint.by && hint.fits.length > hint.now.length;
    if (fit.dataset.sig === `${n}|${all}|${better}|${hint && hint.by}`) return;
    fit.dataset.sig = `${n}|${all}|${better}|${hint && hint.by}`;
    await K.catalog().catch(() => {});
    fit.innerHTML = `<div class="row"><h2 style="margin:0">Your space</h2><span class="spacer"></span><button class="btn small" data-settings>Details</button></div>
      <div class="bar-fit"><i style="width:${(100 * n) / all}%"></i></div>
      <p class="soft"><b>${n} of ${all}</b> activities fit where the Kinect is now${sp.limit ? `, in your ${sp.limit} m` : ""}.
      ${n < all ? `Not: ${sp.activities.filter((a) => !a.fits).slice(0, 4).map((a) => K.activityName(a.activity)).join(", ")}${all - n > 4 ? " and more" : ""}.` : ""}</p>
      ${better ? `<div class="row" style="margin-top:10px"><button class="btn small primary" data-tilt-by="${hint.by}">Tilt ${hint.by > 0 ? "up" : "down"} ${Math.abs(hint.by)}°: ${hint.fits.length} fit</button></div>` : ""}`;
  }

  K.section("home", {
    title: "Home", mount,
    unmount() { if (scene) scene.stop(); clearInterval(timer); scene = null; },
  });
})();
