"""Run one agent turn through the Codex CLI (`codex exec`) on the operator's ChatGPT subscription.

Codex is a talk-only provider: config.json "meeting_provider" sends meeting turns here, nothing else.
Every tool that can touch the machine (shell, exec, browser, computer use, apps, plugins) is switched
off, so a turn can only think, search the web and answer. Codex signs in with its own stored login in
~/.codex; the office never reads or copies it. The user's Codex config, rules and AGENTS.md are ignored
(--ignore-user-config, --ignore-rules) so agents don't inherit the operator's personal setup.

Usage is appended to data/usage/<provider>.jsonl in the same shape as local runs, so the token ledger
counts Codex on its own.
"""
import asyncio
import json
import os
import signal
import time

from . import agy
from .config import COMPANY, DATA

# tools a meeting turn must never have; web search stays on
DISABLE = ("shell_tool", "unified_exec", "apps", "plugins", "browser_use", "browser_use_external",
           "in_app_browser", "computer_use", "image_generation", "hooks", "code_mode_host", "goals",
           "skill_mcp_dependency_install")
QUOTA_MARKERS = ("usage limit", "rate limit", "429", "quota", "too many requests")


class CodexRun:
    """One codex process. `await run.wait()` returns an agy.AgyResult; `run.cancel()` kills it."""

    def __init__(self, prompt, *, agent_name, agent_id, provider, cfg, conv_id=None, timeout_min=30,
                 on_event=None, **_):
        self.prompt = prompt[-120_000:]
        self.agent_name, self.agent_id = agent_name, agent_id
        self.provider = provider
        self.cfg = cfg
        self.model = cfg["model"]
        self.conv_id = conv_id
        self.timeout = int(timeout_min * 60)
        self.on_event = on_event
        self.proc = None
        self.result = agy.AgyResult()
        self.usage_file = DATA / "usage" / f"{provider}.jsonl"

    def _cmd(self):
        opts = ["--json", "-m", self.model, "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
                "-c", f'model_reasoning_effort="{self.cfg.get("reasoning", "medium")}"',
                "-c", f'web_search="{"live" if self.cfg.get("web_search", True) else "disabled"}"']
        for f in DISABLE:
            opts += ["--disable", f]
        if self.conv_id:
            return ["codex", "exec", "resume", self.conv_id, *opts, "-"]
        return ["codex", "exec", "-s", "read-only", *opts, "-"]

    async def wait(self):
        r = self.result
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
        turn = time.time()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self._cmd(), cwd=str(COMPANY), env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
                limit=16 * 1024 * 1024)
        except FileNotFoundError as e:
            r.error = f"cannot start codex: {e}"
            return r
        self.proc.stdin.write(self.prompt.encode())
        await self.proc.stdin.drain()
        self.proc.stdin.close()
        err_task = asyncio.create_task(self.proc.stderr.read())
        await self._emit("start", "Started")
        try:
            await asyncio.wait_for(self._read(r, turn), timeout=self.timeout)
        except asyncio.TimeoutError:
            r.error = "timed out"
            self.cancel()
        await self.proc.wait()
        stderr = (await err_task).decode(errors="replace")
        if r.cancelled:
            r.status, r.error = "CANCELLED", "cancelled"
        elif r.text.strip() and not r.error:
            r.status = "SUCCESS"
        else:
            tail = "\n".join(l for l in stderr.splitlines() if l.strip() and "Reading additional input" not in l)
            r.error = r.error or agy._short(tail, 600) or f"codex exited {self.proc.returncode} without an answer"
        if not r.ok and any(m in (stderr + " " + r.error).lower() for m in QUOTA_MARKERS):
            r.quota = True
        return r

    async def _read(self, r, turn):
        step = 0
        async for raw in self.proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "thread.started":
                r.conv_id = d.get("thread_id") or r.conv_id
            elif t == "item.started" and (d.get("item") or {}).get("type") == "web_search":
                r.steps += 1
                await self._emit("web", "Searching the web")
            elif t == "item.completed":
                item = d.get("item") or {}
                if item.get("type") == "agent_message":
                    r.text = item.get("text") or ""
                elif item.get("type") == "reasoning":
                    await self._emit("think", "Thinking")
            elif t == "turn.completed":
                u = d.get("usage") or {}
                r.tokens += int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
                self._record(u, turn, step)
                step += 1
            elif t in ("turn.failed", "error"):
                e = d.get("error") or d.get("message") or line
                r.error = agy._short(e.get("message", str(e)) if isinstance(e, dict) else str(e), 600)

    def _record(self, u, turn, step):
        from .ledger import _kind
        kind, ref = _kind(self.prompt)
        inp, cached = int(u.get("input_tokens") or 0), int(u.get("cached_input_tokens") or 0)
        row = {"ts": time.time(), "turn": turn, "agent": self.agent_id, "provider": self.provider,
               "model": self.model, "conv": self.result.conv_id, "kind": kind, "ref": ref,
               "fresh": max(0, inp - cached), "cached": cached, "out": int(u.get("output_tokens") or 0),
               "think": int(u.get("reasoning_output_tokens") or 0), "step": step,
               "ms": round((time.time() - turn) * 1000)}
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.usage_file, "a") as fh:
            fh.write(json.dumps(row) + "\n")

    async def _emit(self, kind, text):
        if self.on_event:
            try:
                await self.on_event(kind, text)
            except Exception:
                pass

    def cancel(self):
        self.result.cancelled = True
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            asyncio.get_running_loop().call_later(5, self._kill)

    def _kill(self):
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
