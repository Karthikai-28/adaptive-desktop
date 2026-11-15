// Mario over your work (/panel): what Super+J and "Hey Mario" bring up. Only the orb is there at
// first, at the centre of the screen, with nothing behind it; the words appear under it as you say
// them, then the answer. This script reports the outline of each thing it draws; the host
// (apps/mario-home/host.py) shows the page only inside those outlines and lets the pointer through
// everywhere else.
// Loaded after home.js and tiles.js, whose helpers (el, fill, $, post, tell, toggleVoice) it uses.
"use strict";

(() => {
  if (!PANEL) { window.marioLayer = null; return; }
  const panel = $("#panel"), heard = $("#heard"), words = $("#heard-text"), log = $("#log"), sheet = $("#train"),
    form = $("#panel-form"), input = $("#panel-input"), tools = $("#layer-tools");
  let mode = "quiet";          // how it was summoned: talk (the key), wake ("Hey Mario"), train, quiet
  let attended = false;        // the keyboard is on the layer: it stays until you send it away
  let leaveTimer = null, sheetKind = null, trainId = null, trainRun = 0, speaking = false, lastShape = "";
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const wake = () => state.wake || {};

  // ------------------------------------------------------------ what is drawn, and where
  function settle() {
    heard.hidden = !($("#orb-caption").textContent || words.textContent);
    panel.classList.toggle("has-more", !log.hidden || !sheet.hidden || !form.hidden);
    panel.classList.toggle("idle", !busy());
    shape();
  }
  // The outline of each thing drawn, as it is in this frame: x, y, width, height and corner radius.
  // Nothing else of the page is seen, so this follows every frame of a piece that is moving.
  function shape() {
    const shapes = [];
    const quiet = getComputedStyle(tools).opacity < 0.05;
    for (const node of [$("#orb-stage"), heard, log, sheet, form, ...tools.children]) {
      if (node.hidden || (quiet && node.parentElement === tools)) continue;
      const r = node.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const corner = getComputedStyle(node).borderTopLeftRadius;
      shapes.push([r.left, r.top, r.width, r.height, corner.endsWith("%") ? (parseFloat(corner) / 100) * r.width : parseFloat(corner) || 0]
        .map((v) => Math.round(v * 10) / 10));
    }
    const next = JSON.stringify(shapes);
    if (next !== lastShape) { lastShape = next; tell({ type: "shape", shapes }); }
  }
  (function everyFrame() { requestAnimationFrame(everyFrame); if (!document.hidden) shape(); })();
  setInterval(() => { if (!document.hidden) settle(); }, 150);    // what is busy, what is idle

  function clearExchange() {
    words.textContent = ""; words.classList.remove("note");
    fill(log); log.hidden = true;
  }
  function busy() {
    const now = (state.presence || {}).state;
    return !!(voiceId || voiceBusy || trainId || sheetKind || speaking || ["listening", "thinking", "speaking", "doing"].includes(now)
      || log.querySelector(".plan .btn.primary") || (!form.hidden && (input.value || document.activeElement === input)));
  }

  // ------------------------------------------------------------ leaving on its own
  // Summoned by voice, nobody is at the keyboard to send it away: once Mario has answered and you
  // have had time to read, it goes. With the keyboard on it (Super+J) it stays until Escape or the key.
  const leave = () => tell({ type: "close" });
  function planLeave() {
    clearTimeout(leaveTimer);
    if (attended || mode === "quiet" || mode === "train") return;
    if (busy() || panel.matches(":hover")) { leaveTimer = setTimeout(planLeave, 1000); return; }
    const reading = log.hidden ? (words.textContent ? 3500 : 1200) : Math.min(30000, 7000 + log.textContent.length * 35);
    leaveTimer = setTimeout(() => (attended || busy() || panel.matches(":hover") ? planLeave() : leave()), reading);
  }

  // ------------------------------------------------------------ the host's calls
  window.marioShown = (how) => {
    mode = how || "quiet";
    panel.dataset.mode = mode;
    attended = mode === "talk" || mode === "train";
    clearTimeout(leaveTimer);
    panel.classList.remove("shown"); void panel.offsetWidth; panel.classList.add("shown");
    if (mode === "talk" || mode === "wake") {
      closeSheet();
      if (!voiceId && !voiceBusy) { clearExchange(); form.hidden = true; toggleVoice(); }
    } else if (mode === "train") openSheet("wake");
    settle();
  };
  window.marioHidden = () => {
    clearTimeout(leaveTimer);
    cancelVoice(); closeSheet(); form.hidden = true; input.value = "";
  };
  window.marioAttended = (on) => { attended = !!on; planLeave(); };

  // ------------------------------------------------------------ what home.js tells the layer
  window.marioLayer = {
    settle,
    asked(text) { clearExchange(); words.textContent = text; settle(); },
    answer(res) {
      fill(log, answerNode(res)); log.hidden = false; log.scrollTop = 0;
      speaking = !!(res.answer || res.error);     // the reply is about to be read aloud; presence says when it ends
      setTimeout(() => { speaking = false; planLeave(); }, 1500);
      settle(); planLeave();
    },
    // a voice session: the words so far while you speak, the request once you stop, or what went wrong
    voice(text, active, phase, said) {
      if (said) { words.textContent = said; words.classList.remove("note"); }
      else if (active && phase === "listening") words.textContent = "";
      else if (!active && text) { words.textContent = text; words.classList.add("note"); }
      settle(); planLeave();
    },
    nothingSaid() { if (mode === "wake" && !attended) leave(); else settle(); },
    presence() { settle(); planLeave(); },
    wake() {
      const w = wake(), label = $("#tool-wake span"), tool = $("#tool-wake");
      tool.dataset.state = w.enabled && w.hearing ? "on" : w.enabled ? "waiting" : "off";
      label.textContent = !w.trained ? "Set up Hey Mario" : "Hey Mario";
      tool.title = !w.trained ? "Teach Mario your voice" : w.enabled ? (w.hearing ? "Listening for “Hey Mario”" : "Hey Mario is on; the microphone is not open yet") : "Hey Mario is off";
      if (sheetKind === "wake") drawWake();
    },
  };

  // ------------------------------------------------------------ "Hey Mario": the switch and the training
  function openSheet(kind) {
    cancelVoice(); clearExchange(); form.hidden = true;
    sheetKind = kind; sheet.hidden = false;
    if (kind === "wake") drawWake();
    settle();
  }
  function closeSheet() {
    if (trainId) { const id = trainId; trainId = null; trainRun++; post("/api/wake/train/cancel", { id }).catch(() => {}); }
    if (window.marioVoice) window.marioVoice("idle", 0);
    sheetKind = null; sheet.hidden = true; fill(sheet);
    settle(); planLeave();
  }
  const btn = (text, onclick, primary) => el("button", { class: `btn${primary ? " primary" : ""}`, type: "button", onclick }, text);
  async function wakeOp(op) {
    try { const res = await post("/api/wake", { op }); if (res.error) note(res.error); else { state.wake = res; window.marioLayer.wake(); } }
    catch (_) { note("Mario Hub is not answering. Try again."); }
  }
  function note(text) { const n = sheet.querySelector(".train-note"); if (n) n.textContent = text; }

  function drawWake() {
    const w = wake();
    if (!w.available) {
      return fill(sheet, el("h3", {}, "Hey Mario"),
        el("p", {}, "Hearing “Hey Mario” needs its two small models on this laptop. In a terminal, run:"),
        el("p", {}, code("scripts/install-mario-voice.sh")), el("div", { class: "train-acts" }, btn("Close", closeSheet)));
    }
    if (!w.trained) {
      return fill(sheet, el("h3", {}, "Teach Mario your voice"),
        el("p", {}, "Say “Hey Mario” and Mario comes up, without a key, and only for your voice. You will say the phrase four times."),
        el("p", { class: "muted" }, "Mario keeps a voiceprint (numbers, not recordings) on this laptop. While Hey Mario is on, the microphone stays open and is listened to only here; nothing is sent anywhere."),
        el("p", { class: "train-note" }),
        el("div", { class: "train-acts" }, btn("Start", train, true), btn("Not now", closeSheet)));
    }
    const on = !!w.enabled;
    fill(sheet, el("h3", {}, "Hey Mario"),
      el("label", { class: "switch-row" }, el("span", {}, el("b", {}, "Listen for “Hey Mario”"),
        el("span", { class: "muted" }, on ? (w.hearing ? "On. Listening on this laptop, for your voice." : w.error || "On. Waiting for the microphone.") : "Off. The microphone is closed.")),
        el("input", { type: "checkbox", role: "switch", checked: on, onchange: (e) => wakeOp(e.target.checked ? "enable" : "disable") })),
      el("p", { class: "muted" }, `Your voice was learned ${w.trained_at ? new Date(w.trained_at * 1000).toLocaleDateString(undefined, { day: "numeric", month: "long" }) : "earlier"}. You can add your request in the same breath: “Hey Mario, what is on today?”`),
      el("p", { class: "train-note" }),
      el("div", { class: "train-acts" }, btn("Train again", train), btn("Forget my voice", () => wakeOp("forget")), btn("Done", closeSheet, true)));
  }

  function drawTraining(t) {
    if (!sheet.querySelector(".train-dots")) {
      fill(sheet, el("h3", { id: "train-say" }),
        el("div", { class: "train-dots", role: "img" }, Array.from({ length: t.of || 4 }, () => el("i"))),
        el("p", { class: "train-note" }),
        el("div", { class: "train-acts" }, btn("Cancel", closeSheet)));
    }
    const done = t.state === "done", failed = t.state === "error";
    sheet.querySelector("h3").textContent = done ? "Mario knows your voice" : failed ? "That did not work" : t.state === "starting" ? "Getting ready…" : "Say “Hey Mario”";
    sheet.querySelectorAll(".train-dots i").forEach((dot, i) => {
      dot.className = i < t.step ? "got" : i === t.step && !done && !failed ? "now" : "";
    });
    sheet.querySelector(".train-dots").setAttribute("aria-label", `${t.step} of ${t.of}`);
    note(done ? "Hey Mario is on. Say “Hey Mario” any time, with your request in the same breath if you like."
      : t.message || (t.state === "checking" ? "Listening to that…" : t.state === "say" ? `${t.step + 1} of ${t.of}` : ""));
    if (done || failed) {
      fill(sheet.querySelector(".train-acts"), failed ? btn("Try again", train, true) : null, btn(done ? "Done" : "Close", closeSheet, done));
    }
  }

  async function train() {
    const run = ++trainRun;
    sheetKind = "train"; fill(sheet);
    drawTraining({ state: "starting", step: 0, of: 4 });
    settle();
    try {
      const start = await post("/api/wake/train/start");
      if (run !== trainRun) { if (start.id) post("/api/wake/train/cancel", { id: start.id }).catch(() => {}); return; }
      if (start.error) throw new Error(start.error);
      trainId = start.id;
      while (trainId && run === trainRun) {
        const t = await post("/api/wake/train/status", { id: trainId });
        if (run !== trainRun) return;
        if (t.error) throw new Error(t.error);
        drawTraining(t);
        // the orb listens with you: it moves with your voice while it waits for the phrase
        window.marioVoice(t.state === "say" ? "listening" : t.state === "checking" ? "working" : "idle", t.level || 0);
        if (t.state === "done" || t.state === "error") { trainId = null; break; }
        await sleep(t.state === "say" ? 110 : 250);
      }
    } catch (e) {
      if (run === trainRun) { trainId = null; drawTraining({ state: "error", step: 0, of: 4, message: e.message || "Could not reach Mario. Try again." }); }
    } finally { if (run === trainRun) { window.marioVoice("idle", 0); settle(); } }
  }

  // ------------------------------------------------------------ wiring
  function typeInstead() {
    cancelVoice(); closeSheet();
    form.hidden = false; settle();
    tell({ type: "keyboard" });          // summoned by voice, the layer does not have the keyboard yet
    input.focus();
  }
  document.addEventListener("DOMContentLoaded", () => {
    $("#orb-talk").addEventListener("click", () => { closeSheet(); toggleVoice(); });
    $("#tool-type").addEventListener("click", () => (form.hidden ? typeInstead() : (form.hidden = true, settle())));
    $("#tool-wake").addEventListener("click", () => (sheetKind ? closeSheet() : openSheet("wake")));
    $("#tool-close").addEventListener("click", leave);
    form.addEventListener("submit", (e) => { e.preventDefault(); const text = input.value; input.value = ""; form.hidden = true; ask(text, "panel"); });
    document.addEventListener("keydown", (e) => {
      const at = e.target instanceof Element ? e.target : document.body;
      if (at.closest("input, textarea")) return;
      // Space talks to Mario; any letter starts a typed message
      if (e.code === "Space" && !at.closest("button")) { e.preventDefault(); closeSheet(); toggleVoice(); }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== " " && !sheetKind) typeInstead();
    });
    // In a browser there is no host: the layer shows itself. In its host it says it has loaded and
    // is told how it was summoned.
    if (HOST) tell({ type: "ready" }); else window.marioShown("quiet");
    window.marioLayer.wake();
    settle();
  });
})();
