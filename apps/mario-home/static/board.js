// Home's Agents tile: the Agent Office's work as a Jira-style board, so you can see what every agent is doing
// without opening the office. Loaded after home.js (el, fill, data, act, render ...).
//
// The data is the office's own (GET /api/board, read by the hub's agent_office collector every 10 s):
//   agents      each agent's status word (Working, Blocked, Error, Paused, Idle: the same as the Agent Office's
//               Virtual Office, Command Center and the phone), its task and how long it has run
//   columns     To do (in the order it will run), In progress, Needs you (open Action Inbox items), Done today
// Every column scrolls inside itself; the tile and the page never scroll. A chip per agent (selecting one shows
// only its work), then the four columns. Selecting a card opens that task in the Agent Office window. It moves while there is work: running cards carry a moving bar and a ticking clock; new cards
// slide in. Like every tile, all of it stops while Home is hidden or when you asked for less motion.
"use strict";

const BOARD_COLS = [
  ["todo", "To do", "Waiting their turn, in the order they will run"],
  ["doing", "In progress", "Running now"],
  ["needs_you", "Needs you", "Failed or blocked work and decisions in the Action Inbox"],
  ["done", "Done today", "Done, failed or cancelled since midnight"],
];
const STATE_WORD = { working: "Working", blocked: "Blocked", error: "Error", paused: "Paused", idle: "Idle" };
let boardAgent = "";                 // the agent filter: "" is everyone
const boardSeen = new Set();         // cards already shown, so only new ones slide in

function boardDur(s) {
  s = Math.max(0, Math.round(Number(s) || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
const boardAgo = (ts) => {
  const s = Date.now() / 1000 - ts;
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : new Date(ts * 1000).toLocaleDateString();
};
const openTaskInOffice = (id) => act({ id: "office", arg: `task:${id}` });
const initials = (name) => String(name || "?").trim().slice(0, 1).toUpperCase();

function boardWho(agents, id) {
  const a = agents.find((x) => x.id === id);
  return el("span", { class: "bd-who", title: a ? `${a.name} · ${a.role}` : id },
    el("i", { class: "bd-av", style: `background:${hue(id || "?")}` }, initials(a ? a.name : id)), a ? a.name : id || "Office");
}

function boardCard(kind, c, agents) {
  const t = kind === "needs_you" ? c.task : c;
  const key = `${kind}:${kind === "needs_you" ? c.inbox_id : c.id}`;
  const fresh = !boardSeen.has(key);
  boardSeen.add(key);
  const cls = ["bd-card", kind, fresh ? "fresh" : "", t ? `st-${t.status}` : "", c.priority ? `pri-${c.priority}` : ""].filter(Boolean).join(" ");
  const parts = [];
  if (kind === "needs_you") {
    parts.push(el("div", { class: "bd-reason" }, el("i", { class: `bd-pri ${c.priority}` }), c.reason || c.kind));
    if (t) parts.push(el("div", { class: "bd-title" }, `#${t.id} ${t.title}`));
  } else {
    parts.push(el("div", { class: "bd-title" }, el("b", null, `#${c.id}`), " ", c.title));
  }
  const mission = (t && t.mission) || c.mission;
  if (mission) parts.push(el("div", { class: "bd-mission", title: mission }, mission));
  const foot = [boardWho(agents, (t && t.agent) || c.agent)];
  if (kind === "todo") {
    if (c.depends_on) foot.push(el("span", { class: "bd-tag" }, `after #${c.depends_on}`));
    if ((c.attempts || 0) > 1) foot.push(el("span", { class: "bd-tag" }, `try ${c.attempts}`));
  } else if (kind === "doing") {
    foot.push(el("span", { class: "bd-time", "data-since": c.running_since || "" }, c.running_since ? boardDur(Date.now() / 1000 - c.running_since) : ""));
    if (c.actions) foot.push(el("span", { class: "bd-tag" }, `${c.actions} action${c.actions === 1 ? "" : "s"}`));
  } else if (kind === "needs_you") {
    foot.push(el("span", { class: "bd-tag" }, c.state === "IN_PROGRESS" ? "on it" : boardAgo(c.since)));
  } else {
    foot.push(el("span", { class: `bd-tag ${c.status}` }, c.status === "done" ? "done" : c.status));
    if (c.run_s) foot.push(el("span", { class: "bd-tag" }, `ran ${boardDur(c.run_s)}${c.estimated ? "*" : ""}`));
  }
  const kids = [...parts];
  if (kind === "doing") {
    if (c.last) kids.push(el("div", { class: "bd-last", title: c.last }, c.last));
    kids.push(el("i", { class: "bd-run", "aria-hidden": "true" }));
  }
  kids.push(el("div", { class: "bd-foot" }, foot));
  const id = t ? t.id : null;
  return el("button", { class: cls, type: "button", "data-key": key, title: id ? `Open task #${id} in the Agent Office` : "Open the Action Inbox",
    onclick: () => (id ? openTaskInOffice(id) : act({ id: "office", arg: "inbox" })) }, kids);
}

render.board = () => {
  const box = body("board");
  if (!box) return;
  const office = data("agent_office");
  const sum = $("#board-sum");
  if (sum) sum.textContent = "";
  if (!office.running) {
    return fill(box, el("div", { class: "bd-empty" }, icon("i-bot", "big-ic"),
      el("div", { class: "ttl" }, "The Agent Office is not running"),
      el("button", { class: "btn primary", type: "button", onclick: () => act({ id: "office", arg: "" }) }, "Open the Agent Office")));
  }
  const b = office.board;
  if (!b) {
    return fill(box, el("div", { class: "bd-empty" }, el("div", { class: "ttl" }, "Reading the office's board…"),
      el("div", { class: "sub" }, "An office that has not been restarted since the update has no board yet.")));
  }
  const agents = b.agents || [];
  const mine = (c) => !boardAgent || ((c.task || c).agent || c.agent) === boardAgent;
  const scrolls = {};
  box.querySelectorAll(".bd-list").forEach((l) => { scrolls[l.dataset.col] = l.scrollTop; });

  // the team: one chip per agent, its status dot and what it is doing in the tooltip; selecting one
  // filters the board to its work, selecting it again shows everyone's
  const strip = el("div", { class: "bd-agents", role: "list" }, agents.map((a) => el("button", {
    class: `bd-agent st-${a.state}${boardAgent === a.id ? " on" : ""}`, type: "button", role: "listitem",
    title: `${a.name} · ${a.role} · ${a.state_label || STATE_WORD[a.state] || a.state}` +
      (a.task ? ` · #${a.task.id} ${a.task.title}` : a.queued_count ? ` · ${a.queued_count} waiting` : "") +
      (boardAgent === a.id ? "\nSelect to show everyone's work" : `\nSelect to show only ${a.name}'s work`),
    onclick: () => { boardAgent = boardAgent === a.id ? "" : a.id; render.board(); } },
    el("i", { class: "bd-av", style: `background:${hue(a.id)}` }, initials(a.name)),
    el("span", { class: "bd-aname" }, a.name),
    a.needs_you ? el("span", { class: "bd-need", title: `${a.needs_you} need${a.needs_you === 1 ? "s" : ""} you` }, String(a.needs_you)) : null,
    el("i", { class: `bd-dot st-${a.state}`, "aria-label": a.state_label || a.state }))));

  const c = b.counts || {};
  // in the tile's header: who is working and how much waits on you (the Needs you column)
  if (sum) sum.textContent = `${c.active || 0} of ${c.agents || 0} working · ${(b.inbox || {}).NEEDS_ATTENTION || 0} need you`;

  const cols = el("div", { class: "bd-cols" }, BOARD_COLS.map(([key, name, hint]) => {
    const all = (b.columns || {})[key] || [];
    const shown = all.filter(mine);
    const total = key === "todo" && !boardAgent ? b.todo_total || all.length : shown.length;
    const list = el("div", { class: "bd-list", "data-col": key },
      shown.length ? shown.map((x) => boardCard(key, x, agents))
        : el("div", { class: "bd-none" }, key === "needs_you" ? "Nothing needs you." : key === "doing" ? "Nobody is running a task." : key === "todo" ? "Nothing waiting." : "Nothing finished yet today."));
    return el("section", { class: `bd-col ${key}` }, el("header", { title: hint }, el("h3", null, name), el("span", { class: "bd-n" }, String(total))), list);
  }));
  fill(box, strip, cols);
  box.querySelectorAll(".bd-list").forEach((l) => { if (scrolls[l.dataset.col]) l.scrollTop = scrolls[l.dataset.col]; });
};

// the running clocks count on between the hub's updates
setInterval(() => {
  const box = body("board");
  if (!box || document.body.classList.contains("away")) return;
  const now = Date.now() / 1000;
  box.querySelectorAll(".bd-time[data-since]").forEach((t) => { const s = Number(t.dataset.since); if (s) t.textContent = boardDur(now - s); });
}, 1000);

// the tile's header button: the Agent Office in its own window
$("#board-open").addEventListener("click", () => act({ id: "office", arg: "" }));
