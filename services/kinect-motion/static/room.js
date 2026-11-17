/* Kinect Room: the floor from above (people, zones, where they point, the coverage map),
   who is here and doing what, and the event feed. */
"use strict";

const $ = (id) => document.getElementById(id);
const C = Motion.colour, esc = Motion.esc;
let state = { people: [] }, connected = false, heat = false, coverage = null, zones = [];
const feed = [];
const HALF_FOV = 57 / 2 * Math.PI / 180;     // the Kinect v1's horizontal view

Motion.connect((msg) => {
  state = msg.state;
  for (const e of msg.events) if (e.type === "room" || e.type === "joined" || e.type === "left") log(e);
}, (ok) => { connected = ok; });

function log(e) {
  const t = new Date().toLocaleTimeString();
  const { type, t: _t, ...rest } = e;
  feed.push(`${t}  ${esc(rest.event || type)}  ${esc(JSON.stringify(Object.fromEntries(Object.entries(rest).filter(([k]) => k !== "event" && k !== "say"))))}`);
  while (feed.length > 60) feed.shift();
  $("feed").innerHTML = feed.map((l) => `<div>${l}</div>`).join("");
}

// -- the map: x across (mirrored, as you face the TV), z away from the TV, metres -> pixels
function map(W, H) {
  const s = Math.min(W / 5.4, (H - 60) / 5.0);
  return { s, x: (x) => W / 2 - x * s, z: (z) => 30 + z * s };
}

function draw() {
  const [ctx, W, H] = Motion.fit($("view"));
  ctx.clearRect(0, 0, W, H);
  const m = map(W, H);
  // Metre grid.
  ctx.strokeStyle = C("grid"); ctx.lineWidth = 1;
  for (let z = 0; z <= 5; z += 0.5) { ctx.beginPath(); ctx.moveTo(m.x(2.7), m.z(z)); ctx.lineTo(m.x(-2.7), m.z(z)); ctx.stroke(); }
  for (let x = -2.5; x <= 2.5; x += 0.5) { ctx.beginPath(); ctx.moveTo(m.x(x), m.z(0)); ctx.lineTo(m.x(x), m.z(5)); ctx.stroke(); }
  ctx.fillStyle = C("muted"); ctx.font = "12px Inter, system-ui"; ctx.textAlign = "left";
  for (let z = 1; z <= 5; z += 1) ctx.fillText(`${z} m`, m.x(2.6), m.z(z) - 4);
  // Coverage heat map.
  if (heat && coverage) {
    const { cell, x: [x0], z: [z0], grid } = coverage;
    grid.forEach((row, i) => row.forEach((v, j) => {
      if (v === null) return;
      ctx.fillStyle = v > 0.8 ? C("ok") : v > 0.6 ? C("yellow") : C("danger");
      ctx.globalAlpha = 0.45;
      const xa = x0 + j * cell, za = z0 + i * cell;
      ctx.fillRect(m.x(xa + cell), m.z(za), cell * m.s, cell * m.s);
      ctx.globalAlpha = 1;
    }));
  }
  // What the Kinect sees, and the area where a whole body is tracked well (1.3 to 4.2 m).
  ctx.fillStyle = C("fill"); ctx.strokeStyle = C("line-2"); ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(m.x(0), m.z(0));
  ctx.lineTo(m.x(5 * Math.tan(HALF_FOV)), m.z(5)); ctx.lineTo(m.x(-5 * Math.tan(HALF_FOV)), m.z(5)); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.setLineDash([8, 8]); ctx.strokeStyle = C("ok");
  const t = Math.tan(HALF_FOV), mg = 0.35;
  ctx.beginPath();
  ctx.moveTo(m.x(1.3 * t - mg), m.z(1.3)); ctx.lineTo(m.x(4.2 * t - mg), m.z(4.2));
  ctx.lineTo(m.x(-(4.2 * t - mg)), m.z(4.2)); ctx.lineTo(m.x(-(1.3 * t - mg)), m.z(1.3)); ctx.closePath(); ctx.stroke();
  ctx.setLineDash([]);
  // The TV and the Kinect.
  ctx.fillStyle = C("text"); ctx.fillRect(m.x(0.6), m.z(0) - 10, 1.2 * m.s, 8);
  ctx.fillStyle = C("accent"); ctx.beginPath(); ctx.arc(m.x(0), m.z(0), 7, 0, Math.PI * 2); ctx.fill();
  // Zones.
  for (const zn of zones) {
    if ((zn.on || "floor") !== "floor") continue;
    ctx.strokeStyle = C("purple"); ctx.lineWidth = 2; ctx.fillStyle = C("purple"); ctx.globalAlpha = 0.15;
    ctx.fillRect(m.x(zn.x[1]), m.z(zn.z[0]), (zn.x[1] - zn.x[0]) * m.s, (zn.z[1] - zn.z[0]) * m.s);
    ctx.globalAlpha = 1; ctx.strokeRect(m.x(zn.x[1]), m.z(zn.z[0]), (zn.x[1] - zn.x[0]) * m.s, (zn.z[1] - zn.z[0]) * m.s);
    ctx.fillStyle = C("purple"); ctx.font = "600 14px Inter, system-ui"; ctx.fillText(zn.name, m.x(zn.x[1]) + 6, m.z(zn.z[0]) + 18);
  }
  // People: a dot where they stand, their facing shoulders, where they point.
  for (const p of state.people || []) {
    if (!p.joints) continue;
    const hip = p.joints[23] && p.joints[24] ? [(p.joints[23][0] + p.joints[24][0]) / 2, (p.joints[23][2] + p.joints[24][2]) / 2] : null;
    if (!hip) continue;
    const col = p.slot === null || p.slot === undefined ? Motion.playerColour(p.colour) : Motion.playerColour(p.slot);
    if (p.joints[11] && p.joints[12]) {
      ctx.strokeStyle = col; ctx.lineWidth = 5; ctx.beginPath();
      ctx.moveTo(m.x(p.joints[11][0]), m.z(p.joints[11][2])); ctx.lineTo(m.x(p.joints[12][0]), m.z(p.joints[12][2])); ctx.stroke();
    }
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(m.x(hip[0]), m.z(hip[1]), 13, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = C("text"); ctx.font = "700 14px Inter, system-ui"; ctx.textAlign = "center";
    ctx.fillText(`${p.id}`, m.x(hip[0]), m.z(hip[1]) + 5);
    ctx.textAlign = "left"; ctx.fillStyle = C("soft"); ctx.font = "13px Inter, system-ui";
    ctx.fillText(`${p.posture || ""}${p.height_cm ? ` · ${p.height_cm} cm` : ""}`, m.x(hip[0]) + 18, m.z(hip[1]) + 4);
    if (p.pointing && p.pointing.at === "floor") {
      const [px, pz] = p.pointing.point;
      ctx.strokeStyle = C("yellow"); ctx.setLineDash([4, 6]); ctx.beginPath();
      ctx.moveTo(m.x(hip[0]), m.z(hip[1])); ctx.lineTo(m.x(px), m.z(pz)); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = C("yellow"); ctx.beginPath(); ctx.arc(m.x(px), m.z(pz), 8, 0, Math.PI * 2); ctx.fill();
    } else if (p.pointing && p.pointing.at === "wall") {
      ctx.fillStyle = C("yellow"); ctx.beginPath(); ctx.arc(m.x(p.pointing.point[0]), m.z(0) + 6, 8, 0, Math.PI * 2); ctx.fill();
    }
  }
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

function panel() {
  Motion.status($("status"), state, connected);
  const people = state.people || [];
  $("people").innerHTML = people.map((p) => {
    const hip = p.joints && p.joints[23] ? p.joints[23] : null;
    return `<div class="item"><b>Person ${p.id}</b> · ${esc(p.posture || "")}${p.height_cm ? ` · ${p.height_cm} cm` : ""}
      ${hip ? `<br><span class="muted num">x ${hip[0].toFixed(2)} m · z ${hip[2].toFixed(2)} m from the TV</span>` : ""}
      ${p.pointing ? `<br><span class="soft">pointing at the ${p.pointing.at} (${p.pointing.point.join(", ")})</span>` : ""}</div>`;
  }).join("") || '<p class="muted">Nobody in view.</p>';
}
setInterval(panel, 300);

async function loadCoverage() {
  coverage = await Motion.api("/api/coverage");
  $("cov-n").textContent = `${coverage.samples} samples`;
}
setInterval(() => { if (heat) loadCoverage(); }, 2000);

async function loadSettings() {
  const s = await Motion.api("/api/settings");
  zones = s.zones || [];
  $("always").checked = !!s.room_always;
  $("zones").innerHTML = zones.map((z, i) => `<div class="item row"><b>${esc(z.name)}</b> <span class="muted">${z.on || "floor"} · x ${z.x.join("…")} · ${z.on === "wall" ? `y ${z.y.join("…")}` : `z ${z.z.join("…")}`}</span>
    <button class="btn" data-del="${i}">Remove</button></div>`).join("") || '<p class="muted">No zones yet.</p>';
}

$("heat").onclick = () => { heat = !heat; $("heat").classList.toggle("on", heat); if (heat) loadCoverage(); };
$("cov-reset").onclick = async () => { coverage = await Motion.api("/api/coverage", {}); $("cov-n").textContent = "0 samples"; };
$("z-on").onchange = () => { $("z-b").textContent = $("z-on").value === "wall" ? "y" : "z"; };
$("z-add").onclick = async () => {
  const name = $("z-name").value.trim();
  if (!name) return;
  const on = $("z-on").value, a = [+$("z-a0").value, +$("z-a1").value].sort((p, q) => p - q), b = [+$("z-b0").value, +$("z-b1").value].sort((p, q) => p - q);
  zones.push(on === "wall" ? { name, on, x: a, y: b } : { name, on, x: a, z: b });
  await Motion.api("/api/settings", { zones }); $("z-name").value = ""; loadSettings();
};
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button[data-del]");
  if (!t) return;
  zones.splice(+t.dataset.del, 1);
  await Motion.api("/api/settings", { zones }); loadSettings();
});
$("always").onchange = () => Motion.api("/api/settings", { room_always: $("always").checked });
loadSettings();
