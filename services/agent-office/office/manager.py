"""Claude, the manager: one long-lived headless Claude Code session (`claude -p --resume`).

Claude talks to the owner, splits work into tasks and hands them to the Gemini agents with the
`office` CLI, reviews what comes back (autopilot) and chairs meetings. Turns run one at a time.
Claude may only run `office` and read files: everything else is denied (--permission-mode dontAsk).
"""
import asyncio
import json
import os
import signal
import time

from .config import COMPANY, ROOT

ALLOWED = ["Bash(office:*)", "Bash(office *)", "Read", "Glob", "Grep", "LS"]
DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
NOTHING = "NOTHING_TO_REPORT"


class Manager:
    def __init__(self, office):
        self.o = office
        self.cfg = office.mgr
        self.id = self.cfg["id"]
        self.q = asyncio.Queue()
        self.busy = False
        self.proc = None
        self.finished = []          # tasks waiting for an autopilot review
        self._flush_handle = None
        self._cancelled = False

    @property
    def pending(self):
        return self.q.qsize()

    def start(self):
        self.o._spawn(self._worker())

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
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    # ------------------------------------------------------------------ worker
    async def _worker(self):
        while True:
            prompt, kind, fut = await self.q.get()
            self.busy, self._cancelled = True, False
            await self.o.activity(self.id, "think", {"chat": "Thinking about your message",
                                                     "autopilot": "Reviewing finished work",
                                                     "meeting": "Listening in the meeting",
                                                     "minutes": "Writing meeting minutes"}.get(kind, "Thinking"))
            try:
                text, err = await self._run(prompt)
            except Exception as e:
                text, err = "", f"office error: {e}"
            self.busy = False
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

    def _brief(self):
        o = self.o
        team = "\n".join(f"- {a['id']}: {a['name']}, {a['role']} — {a['brief']}" for a in o.agents.values())
        return f"""You are Claude, the manager of {o.company}, an AI company owned by {o.operator}. {o.operator} talks to you through the office app (text and voice) and you are their single point of contact.

Your team are AI agents running on Gemini ({o.model}). Each has a desk in the office:
{team}
They share the workspace {COMPANY} (your working directory). Projects live in projects/<name>/, meeting notes in meetings/.

You manage with the `office` command (run `office help` for everything):
  office status                          who is doing what, queues
  office assign <agent> "<title>" --body "<details, deliverable, acceptance criteria>" --project <name> [--after <task id>]
  office tasks [--agent a] [--status s]  /  office show <id>  /  office cancel <id>  /  office retry <id>
  office ask <agent> "<question>"        quick question; waits for the reply
  office meeting start "<topic>" --with a,b,c   /  office meeting end
How to manage well:
- Turn the owner's goals into well-scoped tasks with a concrete deliverable and acceptance criteria. Pick the right person. Chain dependent work with --after (e.g. spec -> build -> test) so it runs in order.
- Agents cannot ask questions mid-task, so put everything they need in --body.
- Coordinate; don't do the team's work yourself. Review their output by reading the files. Send work back with specific fixes when it falls short. Have Omar test or review engineering work before you call it done.
- Every task spends the owner's Gemini quota: no busywork, no duplicate tasks. Check `office status` before assigning.
- Never touch credentials, never publish, push, buy or send anything outside this machine unless the owner explicitly asks.
Your replies appear in the office chat and may be read aloud: plain conversational text, short, most important thing first, no tables."""

    async def _run(self, prompt):
        sid = self.o.store.get("mgr:session")
        text, err, new_sid = await self._claude(prompt, sid)
        if not text and sid and ("session" in err.lower() or "conversation" in err.lower()) and not self._cancelled:
            self.o.store.delete("mgr:session")
            text, err, new_sid = await self._claude(prompt, None)
        if new_sid:
            self.o.store.set("mgr:session", new_sid)
        return text, err

    async def _claude(self, prompt, sid):
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "dontAsk", "--allowedTools", *ALLOWED,
               "--append-system-prompt", self._brief()]
        if self.cfg.get("model"):
            cmd += ["--model", self.cfg["model"]]
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
        err_task = asyncio.create_task(self.proc.stderr.read())
        out = {"text": "", "err": "", "sid": None}

        async def read():
            async for raw in self.proc.stdout:
                try:
                    d = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                out["sid"] = d.get("session_id") or out["sid"]
                if d.get("type") == "assistant":
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
        return text, err, new_sid


def _tool_line(c):
    inp = c.get("input") or {}
    if c.get("name") == "Bash":
        cmd = " ".join(str(inp.get("command", "")).split())
        return "$ " + (cmd[:110] + "…" if len(cmd) > 110 else cmd)
    target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
    return f"{c.get('name')} {target}".strip()
