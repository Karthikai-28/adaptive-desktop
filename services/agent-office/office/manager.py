"""Codex plans; Claude verifies, dispatches and reviews through one long-lived manager session.

For owner work requests, autopilot follow-ups and meeting action items, a fresh tool-free Codex turn
drafts the plan first. Claude receives the draft, corrects it where necessary, and only then may use
the `office` CLI to dispatch it. The manager checks that every available staff agent has useful work
before it reports completion. Claude also reviews finished work (autopilot) and chairs meetings.

Models (config.json "manager"): every turn runs on "model" (Sonnet). A turn goes to "complex_model"
(Opus, capped at Opus 5) only when it needs it: the owner asks for it ("opus:", "think hard"), or
Sonnet answers ESCALATE because the request is genuinely complex. Opus turns are capped per hour.
"""
import asyncio
import json
import os
import re
import signal
import time

from . import agy, codex, operator
from .config import COMPANY, HOME, ROOT

ALLOWED = ["Bash(office:*)", "Bash(office *)", "Read", "Glob", "Grep", "LS",
           f"Edit(/{HOME}/**)", f"Write(/{HOME}/**)"]
DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
NOTHING = "NOTHING_TO_REPORT"
LIMIT_RETRY_S = 10 * 60
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_COMPLEX_MODEL = "claude-opus-5"
ESCALATE = "ESCALATE_TO_OPUS"
WORK_PLAN = "WORK_PLAN"
NO_WORK_PLAN = "NO_WORK_PLAN"
PLAN_GATE = "[office plan gate]"
PLAN_KINDS = ("chat", "autopilot", "minutes")
ROTATE_CONTEXT = 120_000        # start a fresh session once one call re-reads more context than this
_OPUS_ASK_RE = re.compile(r"(^|\]:)\s*(opus\s*[:,]|/opus\b)|\b(think hard|think deeply|use opus|deep dive)\b", re.I)
_LIMIT_RE = re.compile(r"usage limit|rate limit|limit reached|resets? (at|in)|overloaded|429", re.I)


def _usage_limited(err):
    return bool(err and _LIMIT_RE.search(err))


def _plan_marker(text):
    """The planner must make the work/no-work decision explicit; an ambiguous draft cannot dispatch."""
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    return first if first in (WORK_PLAN, NO_WORK_PLAN) else ""


class Manager:
    def __init__(self, office):
        self.o = office
        self.cfg = office.mgr
        self.id = self.cfg["id"]
        self.q = asyncio.Queue()
        self.busy = False
        self.proc = None
        self.pids = set()           # running manager processes: the server tells their `office` calls apart
        self.planner_run = None
        self.finished = []          # tasks waiting for an autopilot review
        self._flush_handle = None
        self._cancelled = False
        self._limit_tries = {}      # prompt -> attempts while Claude's usage limit is hit
        self._rotate = 0            # context size that made the session due for a fresh start
        self.held = []              # jobs waiting while the office is paused (store "mgr_held" keeps them)
        self._held_now = False      # the running turn was cut off by a pause

    @property
    def pending(self):
        return self.q.qsize() + len(self.held)

    def start(self):
        self.held = [(p, k, None) for p, k in self.o.store.get("mgr_held", [])]
        if not self.o.settings()["paused"]:
            self.release()
        self.o._spawn(self._worker())

    # ------------------------------------------------------------------ office pause
    def hold(self):
        """The office paused: stop the running turn; it waits, with every queued job, for release()."""
        if self.busy:
            self._held_now = True
            self.cancel()

    def _hold(self, job):
        self.held.append(job)
        # a turn someone awaits (meeting, minutes) can't outlive a restart; owner chats and reviews can
        self.o.store.set("mgr_held", [[p, k] for p, k, f in self.held if f is None])

    def release(self):
        held, self.held = self.held, []
        self.o.store.delete("mgr_held")
        for job in held:
            self.q.put_nowait(job)

    # ------------------------------------------------------------------ entry points
    def chat(self, text):
        """The owner wrote to Claude: answer in the manager thread."""
        self.q.put_nowait((f"[{self.o.operator} via the office app]: {text}", "chat", None))
        self.o._spawn(self.o.push_agent(self.id))

    async def ask(self, prompt, kind):
        fut = asyncio.get_running_loop().create_future()
        self.q.put_nowait((prompt, kind, fut))
        await self.o.push_agent(self.id)
        return await fut

    def task_finished(self, task):
        if not self.o.settings()["autopilot"]:
            return
        self.finished.append(task)
        if self._flush_handle:
            self._flush_handle.cancel()
        # wait a little so several finishing tasks are reviewed in one turn
        self._flush_handle = asyncio.get_running_loop().call_later(12, self._flush)

    def _flush(self):
        self._flush_handle = None
        tasks, self.finished = self.finished, []
        if not tasks:
            return
        hour_ago = time.time() - 3600
        log = [t for t in self.o.store.get("autopilot_log", []) if t > hour_ago]
        limit = self.cfg.get("autopilot_max_per_hour", 20)
        if len(log) >= limit:
            self.o._spawn(self.o.post("manager", self.id,
                                      f"Autopilot paused itself: {limit} automatic reviews in the last hour. "
                                      f"{len(tasks)} finished task(s) are waiting — ask me to review them.",
                                      {"kind": "notice"}))
            return
        self.o.store.set("autopilot_log", log + [time.time()])
        parts = []
        for t in tasks:
            who = self.o._name(t["agent"])
            body = (t["result"] or t["error"] or "")[:2500]
            parts.append(f"#{t['id']} {who} — \"{t['title']}\" — {t['status'].upper()}\n{body}")
        prompt = ("[office autopilot] Tasks you (or a meeting) assigned have finished:\n\n" + "\n\n".join(parts) +
                  "\n\nReview them (open the files they mention when quality matters), then assign follow-ups or "
                  "fixes with `office assign` if needed. If there is something the owner should hear now — a "
                  "finished deliverable, a blocker, or a decision only they can make — reply with a short report for "
                  f"them. Otherwise reply exactly: {NOTHING}")
        self.q.put_nowait((prompt, "autopilot", None))
        self.o._spawn(self.o.push_agent(self.id))

    def cancel(self):
        self._cancelled = True
        if self.planner_run:
            self.planner_run.cancel()
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    # ------------------------------------------------------------------ worker
    async def _worker(self):
        while True:
            job = await self.q.get()
            if self.o.settings()["paused"]:
                self._hold(job)
                continue
            prompt, kind, fut = job
            self.busy, self._cancelled, self._held_now = True, False, False
            work_plan = prompt.startswith(PLAN_GATE) and f"\n{WORK_PLAN}\n" in prompt
            try:
                if kind in PLAN_KINDS and not prompt.startswith(PLAN_GATE):
                    await self.o.activity(self.id, "think", "Codex is drafting the plan")
                    draft, plan_err = await self._codex_plan(prompt, kind)
                    marker = _plan_marker(draft)
                    if plan_err or not marker:
                        prompt = self._planning_failed_prompt(prompt, plan_err or
                                                              "the draft did not declare WORK_PLAN or NO_WORK_PLAN")
                        work_plan = False
                    else:
                        work_plan = marker == WORK_PLAN
                        prompt = self._verification_prompt(prompt, draft, kind)
                    if self._cancelled:
                        raise RuntimeError("cancelled")
                    await self.o.activity(self.id, "think", "Claude is verifying and correcting the plan")
                else:
                    await self.o.activity(self.id, "think", {"chat": "Thinking about your message",
                                                             "autopilot": "Reviewing finished work",
                                                             "meeting": "Listening in the meeting",
                                                             "minutes": "Writing meeting minutes"}.get(kind, "Thinking"))
                text, err = await self._turn(prompt, kind)
                if work_plan and text and not err and not self._cancelled:
                    missing = self._unoccupied_agents()
                    if missing:
                        names = ", ".join(f"{aid} ({self.o.agents[aid]['role']})" for aid in missing)
                        await self.o.activity(self.id, "think", "Claude is filling gaps in the verified plan")
                        fix, fix_err = await self._turn(
                            f"{PLAN_GATE}\nYour verified plan left these staff agents without running or queued "
                            f"work: {names}. Correct that now. Assign each one a useful, non-duplicative task that "
                            "advances the owner's original goal. Existing active study programs count as work and "
                            "will not appear in this list. Do not report completion until every listed agent has a "
                            "task. Then give the owner one short consolidated update; do not mention this internal "
                            "correction pass.", kind)
                        if fix:
                            text = fix
                        if fix_err:
                            err = (err + "; " if err else "") + fix_err
            except Exception as e:
                text, err = "", f"office error: {e}"
            self.busy = False
            if self._held_now:                  # paused mid-turn: the whole job runs again after the resume
                self._held_now = False
                self._hold(job)
                await self.o.activity(self.id, "info", "Paused - this picks up again when the office resumes")
                continue
            if not text and _usage_limited(err) and kind in ("chat", "autopilot", "minutes"):
                # Claude's own usage limit: keep the job and try again later, by itself
                tries = self._limit_tries.get(prompt, 0) + 1
                self._limit_tries[prompt] = tries
                if tries <= 36:   # up to six hours
                    if tries == 1 and kind == "chat":
                        await self.o.post("manager", self.id, "(I've hit my Claude usage limit. I'll answer this "
                                                              "automatically once it resets.)", {"kind": "failure"})
                    await self.o.activity(self.id, "error", "Claude usage limit - retrying in 10 minutes")
                    asyncio.get_running_loop().call_later(LIMIT_RETRY_S, self.q.put_nowait, (prompt, kind, fut))
                    continue
            self._limit_tries.pop(prompt, None)
            if fut and not fut.done():
                fut.set_result(text)
            if kind == "chat":
                if text:
                    await self.o.post("manager", self.id, text.strip())
                else:
                    await self.o.post("manager", self.id, f"(I couldn't respond: {err})", {"kind": "failure"})
            elif kind == "autopilot" and text and NOTHING not in text:
                await self.o.post("manager", self.id, text.strip(), {"kind": "report"})
                await self.o.toast("Claude has an update for you", "ok", self.id)
            elif err:
                await self.o.activity(self.id, "error", f"Claude turn failed: {err[:150]}")
            await self.o.activity(self.id, "done" if text else "error", "Ready" if text else "Turn failed")

    # ------------------------------------------------------------------ plan gate
    def _planning_context(self):
        lines = []
        for aid, a in self.o.agents.items():
            rt = self.o.rt[aid]
            queued = self.o.store.next_queued(aid)
            current = f"running #{rt['task']['id']} {rt['task']['title']}" if rt["task"] else "free"
            if queued:
                current += "; queued: " + "; ".join(f"#{t['id']} {t['title']}" for t in queued[:4])
            studies = [p["title"] for p in self.o.study.for_agent(aid) if self.o.study.state(p["id"])["active"]]
            if studies:
                current += "; active study: " + "; ".join(studies)
            lines.append(f"- {aid}: {a['name']}, {a['role']} — {current}. Strength: {a['brief']}")
        return "\n".join(lines)

    async def _codex_plan(self, request, kind):
        """Run a fresh, tool-free Codex turn. It can propose work but cannot assign or execute any of it."""
        pid = self.cfg.get("planner_provider", "codex")
        p = self.o.providers.get(pid)
        if not p or p.get("engine") != "codex":
            return "", f"planner provider {pid!r} is not a Codex provider"
        if self.o.provider_paused(pid, tools=False):
            return "", f"{self.o._label(pid)} is out of quota"
        prompt = f"""You are the planning stage for {self.o.company}. You cannot run tools or assign work. Claude
will independently verify and correct your draft before any task starts.

Classify the input first. If it is a question, status request, casual conversation, or needs no staff work, output
exactly {NO_WORK_PLAN} on the first line, then a short note explaining what Claude should answer or do itself.
If it calls for staff work, output exactly {WORK_PLAN} on the first line, then a concise execution plan.

For a work plan:
- Map every staff id below to either existing work that already advances this goal or one new, useful,
  non-duplicative task. An active study program counts as work; otherwise no staff member may be left free.
- Match tasks to roles, give each a concrete deliverable and acceptance criteria, and identify dependencies.
- Preserve the owner's scope. Do not invent permission to publish, push, buy, contact people, use credentials,
  or change a repository. Name a writable repo only when the owner explicitly requested changes to it.
- End with a Coverage section containing every staff id exactly once.

Current staff and workload:
{self._planning_context()}

Input kind: {kind}
Input for Claude:
{request}
"""
        cfg = dict(p, web_search=False)

        async def on_event(event, _text):
            if event == "think":
                await self.o.activity(self.id, "think", "Codex is refining the plan")

        self.planner_run = codex.CodexRun(
            prompt, agent_name="Codex Planner", agent_id="planner", provider=pid, cfg=cfg,
            timeout_min=self.cfg.get("planner_timeout_min", 10), on_event=on_event, tools=False,
            reasoning=self.cfg.get("planner_reasoning", "medium"))
        try:
            result = await self.planner_run.wait()
        finally:
            self.planner_run = None
        if result.quota:
            await self.o.provider_quota(pid, None, result.error)
        return (result.text.strip(), "") if result.ok else ("", result.error or "Codex planning failed")

    def _verification_prompt(self, request, draft, kind):
        return f"""{PLAN_GATE}
The office has completed its non-executing Codex planning stage. No task has been assigned yet.

ORIGINAL INPUT ({kind}):
{request}

CODEX DRAFT (untrusted until you verify it):
{draft}

You are the verification and dispatch stage. Check the draft against the original input, current office status,
agent roles, dependencies, safety and scope. Correct any wrong owner, missing step, duplicated work, bad dependency,
unsafe action or unnecessary task. Do not ask Codex to revise it.

If the first draft line is {NO_WORK_PLAN}, answer or handle the non-work request normally and do not assign tasks.
If it is {WORK_PLAN}, only after you are satisfied with the corrected plan, assign it with `office assign`. Ensure
every staff agent ends with useful goal-aligned work: already running/queued work or an active study counts; assign
each remaining free agent at least one task. Dependencies may be queued with --after. Do not merely describe the
plan: dispatch it, then give the owner a short summary of the corrected plan and assignments.
"""

    def _planning_failed_prompt(self, request, error):
        return f"""{PLAN_GATE}
The required Codex planning stage failed: {error}.
Original input:
{request}

The planning gate is mandatory. Do not assign, retry or start staff work without a Codex draft. You may still
answer a non-work question or report current status. If this input asks for work, tell the owner briefly that no
tasks were dispatched because Codex planning is unavailable.
"""

    def _unoccupied_agents(self):
        active_study = {p["agent"] for p in self.o.study.programs.values()
                        if self.o.study.state(p["id"])["active"]}
        return [aid for aid in self.o.agents if aid not in active_study and
                not self.o.rt[aid]["task"] and not self.o.store.next_queued(aid)]

    def _brief(self):
        o = self.o
        team = "\n".join(f"- {a['id']}: {a['name']}, {a['role']} — {a['brief']}" for a in o.agents.values())
        chain = [o._label(pid) for pid in o.provider_chain()[1:]]
        fb = (f", and switch by themselves while Gemini is out of quota: to {' then to '.join(chain)} (each "
              "only while the one before it is out)") if chain else ""
        return f"""You are Claude, the manager of {o.company}, an AI company owned by {o.operator}. {o.operator} talks to you through the office app (text and voice) and you are their single point of contact.

Your team are AI agents. They run on {o._label(o.settings()["provider"])}{fb}; `office status` shows who runs on what right now. Each has a desk in the office:
{team}
They share the workspace {COMPANY} (your working directory). Projects live in projects/<name>/, meeting notes in meetings/.
{self._studies()}

You manage with the `office` command (run `office help` for everything):
  office status                          who is doing what, queues
  office assign <agent> "<title>" --body "<details, deliverable, acceptance criteria>" --project <name> [--after <task id>] [--repo <path>]
  office repos                           repository index for agents' home-folder access
  office tasks [--agent a] [--status s]  /  office show <id>  /  office cancel <id>  /  office retry <id>
  office ask <agent> "<question>"        quick question; waits for the reply
  office meeting start "<topic>" --with a,b,c   /  office meeting end
Your shell runs only `office`, the same in meetings as in chat: one plain `office ...` command per call. You are
already in the workspace, so no `cd`, `mkdir`, shell variables, `;`/`&&` chains or heredocs - a compound command is
denied as a whole. To give several people a shared brief, repeat it inside each one's --body (one assign per call).
How to manage well:
- Codex is the planner. For owner work, autopilot follow-ups and meeting action items, never assign anything until
  the office gives you an `[office plan gate]` message containing Codex's draft. Verify it, correct it yourself,
  then dispatch the corrected plan. For WORK_PLAN, keep every staff agent occupied with useful work; active study
  and existing running or queued work count. Chain dependent work with --after (e.g. spec -> build -> test).
- Agents cannot ask questions mid-task, so put everything they need in --body.
- Every agent can read and write non-secret files throughout {HOME}; credentials and private Office records are
  inaccessible. Keep changes within the owner's requested scope and use `office repos` to list repositories.
  Nobody pushes, pulls or fetches - the owner does that.
- Coordinate; don't do the team's work yourself. Review their output by reading the files. Send work back with specific fixes when it falls short. Have Omar test or review engineering work before you call it done.
- Every task spends the owner's Gemini quota: no busywork, no duplicate tasks. Check `office status` before assigning.
- Codex (GPT) is about as capable as Gemini and has the same tools; tasks continue normally on it.
- A local model is much weaker and slower than Gemini (a few billion parameters on the laptop's CPU). While agents run on it, give small, concrete, well-specified tasks, expect simpler output, and review it more carefully.
- Never touch credentials, never publish, push, buy or send anything outside this machine unless the owner explicitly asks.
Your replies appear in the office chat and may be read aloud: plain conversational text, short, most important thing first, no tables.
You run on {self.model} to keep token use low. Handle routine work yourself: status, questions, assigning and chaining tasks, reviews, meetings. Only when a request from the owner or a review is genuinely complex (a multi-project plan, an architecture or design decision with real trade-offs, a hard technical judgement, a subtle bug or quality problem you cannot settle), reply with exactly {ESCALATE} and nothing else, before doing any work, and {self.complex_model} will take that turn. Never escalate meetings or simple requests."""

    def _studies(self):
        progs = self.o.study.programs.values()
        if not progs:
            return ""
        lines = [f"- {self.o._name(p['agent'])} runs the study program \"{p['title']}\" by himself, session after session "
                 f"(knowledge base study/{p['id']}/, `office study`). Don't assign him other work unless the owner asks; "
                 f"ask him questions about those codebases with `office ask {p['agent']}`." for p in progs]
        return "Study programs:\n" + "\n".join(lines)

    # ------------------------------------------------------------------ model routing
    @property
    def model(self):
        return self.cfg.get("model") or DEFAULT_MODEL

    @property
    def complex_model(self):
        return self.cfg.get("complex_model") or DEFAULT_COMPLEX_MODEL

    def _opus_allowed(self):
        hour_ago = time.time() - 3600
        log = [t for t in self.o.store.get("opus_log", []) if t > hour_ago]
        return len(log) < self.cfg.get("opus_max_per_hour", 6), log

    def _use_opus(self):
        ok, log = self._opus_allowed()
        if ok:
            self.o.store.set("opus_log", log + [time.time()])
        return ok

    async def _turn(self, prompt, kind):
        """Sonnet by default; Opus when the owner asks for it or Sonnet escalates (within the hourly cap)."""
        if self._rotate:
            await self._fresh_session()
        escalatable = kind in ("chat", "autopilot") and self.complex_model != self.model
        if escalatable and kind == "chat" and _OPUS_ASK_RE.search(prompt) and self._use_opus():
            await self.o.activity(self.id, "think", "Thinking it through (Opus)")
            return await self._run(prompt, self.complex_model)
        text, err = await self._run(prompt, self.model)
        if not (text and text.strip().startswith(ESCALATE)) or self._cancelled:
            return text, err
        if escalatable and self._use_opus():
            await self.o.activity(self.id, "think", "This one needs more thought (Opus)")
            return await self._run(f"[office] You escalated the previous message to {self.complex_model}. "
                                   "Handle it fully now.", self.complex_model)
        why = "the hourly Opus cap is reached" if escalatable else "this kind of turn stays on Sonnet"
        return await self._run(f"[office] Opus is not available ({why}). Handle the previous message yourself "
                               f"as well as you can; do not reply {ESCALATE}.", self.model)
        return text, err

    # ------------------------------------------------------------------ session size
    @property
    def rotate_at(self):
        return int(self.cfg.get("rotate_context_tokens") or ROTATE_CONTEXT)

    async def _fresh_session(self):
        """The session got big: every call re-reads all of it. Start over with a short hand-over instead.
        Done between turns, never inside one, so an escalation still sees the message it escalated."""
        size, self._rotate = self._rotate, 0
        self.o.store.delete("mgr:session")
        self.o.store.set("mgr:handoff", True)
        await self.o.activity(self.id, "think", f"Starting a fresh session (the old one re-read {size // 1000}k tokens a call)")

    def _handoff(self):
        lines = []
        for m in self.o.store.messages("manager", limit=12):
            who = self.o.operator if m["sender"] == "operator" else "You" if m["sender"] == self.id else m["sender"]
            text = " ".join(m["text"].split())
            lines.append(f"{who}: {text[:600] + '…' if len(text) > 600 else text}")
        recent = "\n".join(lines) or "(no messages yet)"
        return ("[office] Your previous session grew too long to keep re-reading, so this is a fresh one. "
                f"The latest messages between you and {self.o.operator}:\n{recent}\n"
                "Run `office status` and `office tasks` for the team's current state before acting on anything "
                "from before. Then handle this:\n\n")

    async def _run(self, prompt, model):
        sid = self.o.store.get("mgr:session")
        handoff = not sid and self.o.store.get("mgr:handoff", False)
        text, err, new_sid, ctx = await self._claude((self._handoff() if handoff else "") + prompt, sid, model)
        if not text and sid and ("session" in err.lower() or "conversation" in err.lower()) and not self._cancelled:
            self.o.store.delete("mgr:session")
            text, err, new_sid, ctx = await self._claude(self._handoff() + prompt, None, model)
        if new_sid:
            self.o.store.set("mgr:session", new_sid)
            seen = self.o.store.get("mgr:sessions", [])
            if new_sid not in seen:                    # every session ever used, for the token ledger
                self.o.store.set("mgr:sessions", seen + [new_sid])
            if handoff and text:
                self.o.store.delete("mgr:handoff")
        if ctx > self.rotate_at:
            self._rotate = ctx
        return text, err

    async def _claude(self, prompt, sid, model):
        protected = agy.protected_paths([operator.KEY_FILE, *self.o.repos.hidden])
        denied = [rule for p in protected for tool in ("Read", "Edit", "Write", "Glob", "Grep", "LS")
                  for rule in (f"{tool}(/{p})", f"{tool}(/{p}/**)")]
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "dontAsk", "--allowedTools", *ALLOWED,
               "--disallowedTools", *denied,
               "--model", model, "--append-system-prompt", self._brief()]
        if sid:
            cmd += ["--resume", sid]
        env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
        env["PATH"] = f"{ROOT / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}"
        env["OFFICE_ACTOR"] = "manager"
        env["OFFICE_URL"] = f"http://127.0.0.1:{self.o.cfg['port']}"
        self.proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(COMPANY), env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, limit=16 * 1024 * 1024)
        pid = self.proc.pid
        self.pids.add(pid)
        try:
            return await self._claude_turn()
        finally:
            self.pids.discard(pid)

    async def _claude_turn(self):
        err_task = asyncio.create_task(self.proc.stderr.read())
        out = {"text": "", "err": "", "sid": None, "ctx": 0}

        async def read():
            async for raw in self.proc.stdout:
                try:
                    d = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                out["sid"] = d.get("session_id") or out["sid"]
                if d.get("type") == "assistant":
                    u = d.get("message", {}).get("usage") or {}
                    ctx = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                            "cache_creation_input_tokens"))
                    out["ctx"] = max(out["ctx"], ctx)
                    for c in d.get("message", {}).get("content", []):
                        if c.get("type") == "tool_use":
                            await self.o.activity(self.id, "run", _tool_line(c))
                elif d.get("type") == "result":
                    if d.get("is_error") or d.get("subtype") != "success":
                        out["err"] = str(d.get("result") or d.get("subtype") or "error")[:500]
                    else:
                        out["text"] = d.get("result") or ""

        try:
            await asyncio.wait_for(read(), timeout=20 * 60)
        except asyncio.TimeoutError:
            out["err"] = "timed out"
            self.cancel()
        text, err, new_sid = out["text"], out["err"], out["sid"]
        await self.proc.wait()
        stderr = (await err_task).decode(errors="replace").strip()
        if not text and not err:
            err = stderr[-500:] or f"claude exited {self.proc.returncode}"
        if self._cancelled:
            err = err or "cancelled"
        return text, err, new_sid, out["ctx"]


def _tool_line(c):
    inp = c.get("input") or {}
    if c.get("name") == "Bash":
        cmd = " ".join(str(inp.get("command", "")).split())
        return "$ " + (cmd[:110] + "…" if len(cmd) > 110 else cmd)
    target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
    return f"{c.get('name')} {target}".strip()
