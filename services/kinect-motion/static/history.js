/* History: people, their week, movement summaries (form, range of motion, tempo, balance), how
   well the Kinect saw them, games, fitness checks and past workouts; equipment; and deleting
   history. Everything here is results kept on this computer: no pictures, no skeletons. */
"use strict";

(() => {
  let root = null, uid = null;

  async function mount(el) {
    root = el;
    el.innerHTML = `<div class="history"><div class="side" id="hi-people"><div class="skeleton" style="height:70px"></div></div><div class="main" id="hi-main"></div></div>`;
    el.addEventListener("click", click);
    await people();
  }

  async function people() {
    const users = await K.users(true);
    if (uid === null && users.length) uid = users[0].id;
    const side = root.querySelector("#hi-people");
    side.innerHTML = users.map((u) => `<button class="person ${u.id === uid ? "sel" : ""}" data-user="${u.id}"><span class="av">${K.esc(u.name.slice(0, 1).toUpperCase())}</span>
      <span><b>${K.esc(u.name)}</b><br><span class="muted">${u.totals.sessions} workouts this week · ${u.totals.streak} day streak</span></span></button>`).join("") +
      `<div class="card"><h2>Add a person</h2><div class="row"><input id="hi-name" type="text" placeholder="Name" maxlength="40" style="flex:1"><input id="hi-kg" type="number" min="20" max="250" placeholder="kg"></div>
        <div class="row"><button class="btn primary" id="hi-add">Add</button></div>
        <p class="note">Body weight is used only for the calorie estimate. Pick a person for a player before starting, and their results are kept; a Guest's are not.</p></div>
      <div class="card"><h2>All history</h2><p class="soft">Delete every workout, check, game and tracking record of everyone. People and their equipment stay.</p>
        <div class="row" style="margin-top:10px"><button class="btn danger" id="hi-wipe">Delete all history</button></div></div>`;
    main();
  }

  async function main() {
    const el = root.querySelector("#hi-main");
    if (!uid) { el.innerHTML = '<div class="empty"><b>No one yet</b>Add a person on the left, then choose them for a player in Fitness or Games.</div>'; return; }
    el.innerHTML = '<div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:240px"></div>';
    const [users, h, ins, cat] = await Promise.all([K.users(), K.api(`/api/history?user=${uid}`), K.api(`/api/insight?user=${uid}`), K.catalog()]);
    const u = users.find((x) => x.id === uid) || {};
    const t = h.totals;
    const name = (k) => (cat.exercises.find((e) => e.key === k) || {}).name || K.activityName(k);
    const due = h.checks.length ? Math.max(0, cat.retest_days - Math.floor((Date.now() / 1000 - h.checks[0].at) / 86400)) : null;
    const mv = Object.entries(ins.movement);
    el.innerHTML = `<div class="card"><div class="row"><h2 style="margin:0">${K.esc(u.name)}</h2><span class="spacer"></span><span class="muted">${u.kg ? `${u.kg} kg` : "no body weight"}</span></div>
        <h3>Last 7 days</h3><div class="stats">
        <div class="stat"><b>${t.sessions}</b><span>workouts</span></div><div class="stat"><b>${t.reps}</b><span>repetitions</span></div>
        <div class="stat"><b>${t.minutes}</b><span>minutes moving</span></div><div class="stat"><b>${u.kg ? `~${t.kcal}` : "–"}</b><span>kcal, estimated</span></div>
        <div class="stat"><b>${t.volume || "–"}</b><span>kg lifted</span></div><div class="stat"><b>${t.streak}</b><span>day streak</span></div></div>
        <p class="note">Calories are estimates (MET × body weight × time, 2024 Compendium), not measurements.</p></div>
      <div class="cols">
        <div class="card"><h2>Movement, last 4 weeks</h2>${mv.length ? `<table class="grid"><tr><th>Exercise</th><th>Reps</th><th>Form</th><th>Range</th><th>Tempo</th><th>L / R</th></tr>
          ${mv.map(([k, m]) => `<tr><td>${K.esc(name(k))}</td><td>${m.reps}</td><td>${m.form ?? "–"}${m.form !== null ? "%" : ""}</td><td>${m.rom !== null ? `${Math.round(m.rom * 100)}%` : "–"}</td>
            <td>${m.tempo_s ?? "–"}${m.tempo_s ? " s" : ""}</td><td>${m.sides ? `${m.sides.left} / ${m.sides.right}` : "–"}</td></tr>`).join("")}</table>
          <p class="note">Range: how far into the movement each repetition went, 100% = the full depth the count asks for.</p>` : '<p class="muted">No sets yet.</p>'}</div>
        <div class="card"><h2>How well the Kinect saw you</h2>${ins.quality.length ? `<table class="grid"><tr><th>Activity</th><th>Minutes</th><th>Seen</th><th>Lost</th><th>Updates</th><th>Dark</th></tr>
          ${ins.quality.map((q) => `<tr><td>${K.esc(name(q.activity))}</td><td>${q.minutes}</td><td>${q.seen_share !== null ? `${Math.round(q.seen_share * 100)}%` : "–"}</td><td>${q.losses ?? 0}×</td>
            <td>${q.updates_per_s ?? "–"}/s</td><td>${q.dark_share !== null ? `${Math.round(q.dark_share * 100)}%` : "–"}</td></tr>`).join("")}</table>
          <p class="note">Seen: the share of the time the camera saw you clearly. Dark: the share in infrared.</p>` : '<p class="muted">Nothing measured yet.</p>'}</div>
      </div>
      <div class="cols">
        <div class="card"><h2>Games</h2>${Object.keys(ins.best).length ? `<div class="stats">${Object.entries(ins.best).map(([g, b]) => `<div class="stat"><b>${b}</b><span>best ${K.esc(K.activityName(g))}</span></div>`).join("")}</div>
          <div class="list" style="margin-top:12px">${ins.games.slice(0, 6).map((g) => `<div class="item">${new Date(g.at * 1000).toLocaleString()} · <b>${K.esc(K.activityName(g.game))}</b> ${g.score}</div>`).join("")}</div>` : '<p class="muted">No games yet.</p>'}</div>
        <div class="card"><h2>Fitness checks</h2><div class="list">${h.checks.slice(0, 4).map((c) => `<div class="item"><b>${new Date(c.at * 1000).toLocaleDateString()}</b> ${Object.entries(c.results).map(([k, v]) => `${K.esc(name(k))}: ${Object.entries(v).filter(([, x]) => x !== null).map(([a, x]) => `${K.esc(a.replace(/_/g, " "))} ${x}`).join(", ")}`).join(" · ")}</div>`).join("") || '<p class="muted">None yet: take the check (Fitness → Check) for a baseline.</p>'}</div>
          ${due !== null ? `<p class="note">Next check ${due ? `in ${due} days` : "is due now"}.</p>` : ""}</div>
      </div>
      <div class="card"><h2>Recent workouts</h2><div class="list">${h.sessions.slice(0, 12).map((s) => `<div class="item row"><span><b>${new Date(s.started * 1000).toLocaleString()}</b> · ${K.esc(s.plan || "")}<br>
        <span class="soft">${s.sets.map((x) => `${K.esc(name(x.exercise))} ${x.reps}${x.form !== null ? ` (${Math.round(x.form)}%)` : ""}${x.load_kg ? ` @ ${x.load_kg} kg` : ""}`).join(", ")}</span></span>
        <span class="spacer"></span><button class="btn small" data-session="${s.id}">Delete</button></div>`).join("") || '<p class="muted">No workouts yet.</p>'}</div></div>
      <div class="card"><h2>${K.esc(u.name)}'s weights</h2><div class="list">${(u.equipment || []).map((e) => `<div class="item row">${K.esc(e.name)} · <b>${e.kg} kg</b><span class="spacer"></span><button class="btn small" data-equip="${e.id}">Remove</button></div>`).join("")}</div>
        <div class="row" style="margin-top:10px"><input id="hi-eq" type="text" placeholder="e.g. Blue dumbbells" maxlength="40"><input id="hi-eqkg" type="number" min="0.5" max="100" step="0.5" placeholder="kg"><button class="btn small" id="hi-eqadd">Add weight</button></div>
        <p class="note">The Kinect cannot see how heavy a weight is: a load is recorded only from what you register or type.</p></div>
      <div class="card"><h2>Delete</h2><div class="row"><button class="btn danger" data-clear="${uid}">Delete ${K.esc(u.name)}'s history</button><button class="btn danger" data-forget="${uid}">Forget ${K.esc(u.name)}</button></div>
        <p class="note">Deleting history keeps the person and their weights; forgetting removes them and everything recorded for them. Deleted results are gone from the file too.</p></div>`;
  }

  async function click(e) {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.user) { uid = +t.dataset.user; people(); }
    if (t.id === "hi-add") {
      const name = root.querySelector("#hi-name").value.trim();
      if (!name) return;
      const r = await K.api("/api/users", { name, kg: parseFloat(root.querySelector("#hi-kg").value) || null });
      uid = r.id; people();
    }
    if (t.id === "hi-eqadd") {
      const kg = parseFloat(root.querySelector("#hi-eqkg").value);
      if (kg > 0) { await K.api("/api/equipment", { user: uid, name: root.querySelector("#hi-eq").value, kg }); await K.users(true); main(); }
    }
    if (t.dataset.equip) { await K.api("/api/equipment", { delete: +t.dataset.equip }); await K.users(true); main(); }
    if (t.dataset.session && confirm("Delete this workout?")) { await K.api("/api/forget", { session: +t.dataset.session }); main(); }
    if (t.dataset.clear && confirm("Delete all of this person's workouts, checks, games and tracking records?")) { await K.api("/api/forget", { user: +t.dataset.clear }); K.toast("History deleted"); people(); }
    if (t.dataset.forget && confirm("Forget this person and everything recorded for them?")) { await K.api(`/api/users/${t.dataset.forget}`, undefined, "DELETE"); uid = null; people(); }
    if (t.id === "hi-wipe" && confirm("Delete everyone's history? People and equipment stay.")) { await K.api("/api/forget", { all: true }); K.toast("All history deleted"); people(); }
  }

  K.section("history", { title: "History", mount, unmount() {}, route() {} });
})();
