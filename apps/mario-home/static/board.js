// Home's Agents tile: the Agent Office's work as a Jira-style board, so you can see what every agent is doing
// without opening the office. Loaded after home.js (el, fill, data, act, render ...).
//
// The data is the office's own (GET /api/board, read by the hub's agent_office collector every 10 s):
//   agents      each agent's status (Working, Blocked, Error, Paused, Idle: the same as the Agent Office's
//               Virtual Office, Command Center and the phone), its task and how long it has run
//   columns     To do (in the order it will run), In progress, Needs you (open Action Inbox items), Done today
//
// A tile is too narrow for four columns side by side, so the columns are tabs with their counts and the chosen
// one is a single full-width list that scrolls inside the tile (the page never scrolls). Until you pick a tab
// it shows what matters most: Needs you, else In progress, else To do. Above the tabs, a face per agent ringed
// in its status colour, with its name; selecting one shows only its work. Selecting a row opens that task in the Agent Office.
// It moves while there is work: running rows carry light along their edge and a ticking clock, working faces
// pulse, new rows slide in. All of it stops while Home is hidden or under reduced motion.
"use strict";

const BOARD_COLS = [
  ["todo", "To do", "Waiting their turn, in the order they will run"],
  ["doing", "In progress", "Running now"],
  ["needs_you", "Needs you", "Failed or blocked work and decisions in the Action Inbox"],
  ["done", "Done today", "Done, failed or cancelled since midnight"],
];
const BOARD_EMPTY = { todo: "Nothing waiting.", doing: "Nobody is running a task.", needs_you: "Nothing needs you.", done: "Nothing finished yet today." };
const STATE_WORD = { working: "Working", blocked: "Blocked", error: "Error", paused: "Paused", idle: "Idle" };
const KIND_WORD = { blocked: "Blocked", failed: "Failed", approval: "Approval", question: "Question", decision: "Decision" };
let boardAgent = "";                 // the agent filter: "" is everyone
let boardCol = "";                   // the tab you picked: "" lets the tile choose
const boardSeen = new Set();         // rows already shown, so only new ones slide in

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
const initials = (name) => String(name || "?").trim().slice(0, 1).toUpperCase();
const avatar = (id, name, cls = "") => el("i", { class: `bd-av ${cls}`.trim(), style: `background:${hue(id || "?")}` }, initials(name || id));

// one row: who, what (one line, the task), and under it the agent, the mission and how it stands; the figure
// that matters for its column on the right
function boardRow(kind, c, agents) {
  const t = kind === "needs_you" ? c.task || {} : c;
  const who = t.agent || c.agent;
  const a = agents.find((x) => x.id === who);
  const key = `${kind}:${kind === "needs_you" ? c.inbox_id : c.id}`;
  const fresh = !boardSeen.has(key);
  boardSeen.add(key);

  const title = kind === "needs_you" && !t.id ? (c.reason || c.kind) : t.title;
  const sub = [a ? a.name : who || "Office", t.mission || c.mission];
  let side;
  if (kind === "todo") {
    sub.push(c.depends_on ? `after #${c.depends_on}` : "", (c.attempts || 0) > 1 ? `try ${c.attempts}` : "");
    side = el("span", { class: "bd-pill" }, "Queued");
  } else if (kind === "doing") {
    sub.push(c.last || (c.actions ? `${c.actions} action${c.actions === 1 ? "" : "s"}` : ""));
    side = el("span", { class: "bd-time", "data-since": c.running_since || "" }, c.running_since ? boardDur(Date.now() / 1000 - c.running_since) : "");
  } else if (kind === "needs_you") {
    sub.push(c.state === "IN_PROGRESS" ? "on it" : c.since ? boardAgo(c.since) : "");
    side = el("span", { class: `bd-pill ${c.priority || ""}` }, KIND_WORD[c.kind] || (c.kind ? c.kind[0].toUpperCase() + c.kind.slice(1) : "Open"));
  } else {
    sub.push(c.run_s ? `ran ${boardDur(c.run_s)}${c.estimated ? "*" : ""}` : "");
    side = el("span", { class: `bd-pill ${c.status}` }, c.status === "done" ? "Done" : c.status === "failed" ? "Failed" : "Cancelled");
  }
  const id = t.id || null;
  return el("button", { class: `bd-row ${kind}${fresh ? " fresh" : ""}${c.priority ? ` pri-${c.priority}` : ""}`, type: "button", role: "listitem",
    "data-key": key, title: `${id ? `#${id} ` : ""}${title || ""}\n${id ? "Open this task in the Agent Office" : "Open the Action Inbox"}`,
    onclick: () => act({ id: "office", arg: id ? `task:${id}` : "inbox" }) },
    avatar(who, a ? a.name : who),
    el("span", { class: "bd-text" },
      el("span", { class: "bd-title" }, id ? el("b", null, `#${id}`) : null, title || ""),
      el("span", { class: "bd-sub" }, sub.filter(Boolean).join("  ·  "))),
    side,
    kind === "doing" ? el("i", { class: "bd-run", "aria-hidden": "true" }) : null);
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
  const columns = b.columns || {};
  const mine = (c) => !boardAgent || ((c.task || {}).agent || c.agent) === boardAgent;
  const shown = Object.fromEntries(BOARD_COLS.map(([key]) => [key, (columns[key] || []).filter(mine)]));
  const col = boardCol || ["needs_you", "doing", "todo", "done"].find((k) => shown[k].length) || "doing";
  const old = box.querySelector(".bd-list");
  const scroll = old && old.dataset.col === col ? old.scrollTop : 0;

  const c = b.counts || {};
  const need = (b.inbox || {}).NEEDS_ATTENTION || 0;
  if (sum) sum.textContent = `${c.active || 0} of ${c.agents || 0} working${need ? ` · ${need} need${need === 1 ? "s" : ""} you` : ""}`;

  // the team: a face per agent, ringed in its status colour, and its name
  const strip = el("div", { class: "bd-agents", role: "list", "aria-label": "Agents" }, agents.map((a) => {
    const on = boardAgent === a.id;
    const state = a.state_label || STATE_WORD[a.state] || a.state;
    return el("button", { class: `bd-agent st-${a.state}${on ? " on" : ""}`, type: "button", role: "listitem",
      "aria-label": `${a.name}, ${state}`, "aria-pressed": String(on),
      title: `${a.name} · ${a.role} · ${state}${a.task ? `\n#${a.task.id} ${a.task.title}` : ""}\n` +
        (on ? "Select to show everyone's work" : `Select to show only ${a.name}'s work`),
      onclick: () => { boardAgent = on ? "" : a.id; render.board(); } },
      avatar(a.id, a.name),
      el("span", { class: "bd-aname" }, a.name),
      a.needs_you ? el("span", { class: "bd-need" }, String(a.needs_you)) : null);
  }));

  const tabs = el("div", { class: "bd-tabs", role: "tablist" }, BOARD_COLS.map(([key, name, hint]) => {
    const n = key === "todo" && !boardAgent ? b.todo_total || shown.todo.length : shown[key].length;
    return el("button", { class: `bd-tab ${key}${key === col ? " on" : ""}`, type: "button", role: "tab", "aria-selected": String(key === col),
      title: hint, onclick: () => { boardCol = key; render.board(); } }, name, el("span", { class: "bd-n" }, String(n)));
  }));

  const rows = shown[col];
  const list = el("div", { class: "bd-list", "data-col": col, role: "list" },
    rows.length ? rows.map((x) => boardRow(col, x, agents)) : el("div", { class: "bd-none" }, BOARD_EMPTY[col]));
  fill(box, strip, tabs, list);
  const more = () => strip.classList.toggle("more", strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 2);
  strip.addEventListener("scroll", more, { passive: true });
  more();
  if (scroll) list.scrollTop = scroll;
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
