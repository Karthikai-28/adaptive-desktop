"""Run one agent turn through the Codex CLI (`codex exec`) on the operator's ChatGPT subscription.

Codex answers meetings ("meeting_provider"). It can also do work turns, as a provider in the fallback
chain, once the office's own Codex home is signed in (`office codex-login`); until then it counts as
unavailable for work and the chain skips it.

Two kinds of turn:
- Talk only (meetings, tools=False): every tool that can touch the machine is switched off, so the turn
  can only think, search the web and answer. It uses the operator's own Codex login in ~/.codex, which
  the office never reads; the operator's Codex config, rules and AGENTS.md are ignored.
- Work (tasks, direct messages): Codex runs inside the same bubblewrap sandbox as agy (read-only system,
  an empty home, the workspace writable, the studied repos read-only) with its own home,
  data/codex-home, signed in once by the operator (`office codex-login`) with the token in the OS
  keyring, never in a file. The operator's ~/.codex does not exist inside the sandbox. Codex's own
  workspace-write sandbox confines shell commands on top; agents that must learn code only from local
  copies get no network in their shell and no web search.

Usage is appended to data/usage/<provider>.jsonl in the same shape as local runs, so the token ledger
counts Codex on its own.
"""
import asyncio
import json
import os
import re
import signal
import time

from . import agy
from .config import COMPANY, DATA

CODEX_HOME = DATA / "codex-home"            # the office's own Codex login and threads (work turns)
KEYRING = ["-c", 'cli_auth_credentials_store="keyring"']
# never available to an agent; talk-only turns lose the shell and exec tools as well
NEVER = ("apps", "plugins", "browser_use", "browser_use_external", "in_app_browser", "computer_use",
         "image_generation", "hooks", "goals", "skill_mcp_dependency_install", "memories")
TALK_ONLY = ("shell_tool", "unified_exec", "code_mode_host")
QUOTA_MARKERS = ("usage limit", "rate limit", "429", "quota", "too many requests")
CODEX_HOME.mkdir(parents=True, exist_ok=True)


async def logged_in():
    """Is the office's own Codex home signed in? (work turns need it; talk-only turns don't)"""
    try:
        p = await asyncio.create_subprocess_exec(
            "codex", "login", "status", *KEYRING, env={**_base_env(), "CODEX_HOME": str(CODEX_HOME)},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        return await asyncio.wait_for(p.wait(), 30) == 0
    except (OSError, asyncio.TimeoutError):
        return False


def _base_env():
    return {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}


def reset_from_error(err, now=None):
    """When Codex says the limit resets ("try again in 2 hours 5 minutes" / "in 37 minutes"), else None."""
    now = now or time.time()
    m = re.search(r"in\s+(?:(\d+)\s*days?)?[\s,]*(?:(\d+)\s*h(?:ours?)?)?[\s,]*(?:(\d+)\s*m(?:in(?:utes?)?)?)?", err or "", re.I)
    if not m or not any(m.groups()):
        return None
    d, h, mi = (int(x or 0) for x in m.groups())
    return now + d * 86400 + h * 3600 + mi * 60 + 60


class CodexRun:
    """One codex process. `await run.wait()` returns an agy.AgyResult; `run.cancel()` kills it."""

    def __init__(self, prompt, *, agent_name, agent_id, provider, cfg, conv_id=None, timeout_min=30,
                 on_event=None, tools=True, reasoning=None, ro_dirs=(), offline=False, **_):
        self.prompt = prompt[-120_000:]
        self.agent_name, self.agent_id = agent_name, agent_id
        self.provider = provider
        self.cfg = cfg
        self.model = cfg["model"]
        self.reasoning = reasoning or cfg.get("reasoning", "low")
        self.conv_id = conv_id
        self.timeout = int(timeout_min * 60)
        self.on_event = on_event
        self.tools = tools
        self.offline = offline
        self.ro_dirs = [str(p) for p in (os.path.expanduser(d) for d in ro_dirs) if os.path.isdir(p)]
        self.proc = None
        self.result = agy.AgyResult()
        self.usage_file = DATA / "usage" / f"{provider}.jsonl"

    def _cmd(self):
        web = self.cfg.get("web_search", True) and not self.offline
        opts = ["--json", "-m", self.model, "--skip-git-repo-check", "--ignore-rules",
                "-c", f'model_reasoning_effort="{self.reasoning}"',
                "-c", f'web_search="{"live" if web else "disabled"}"']
        for f in NEVER + (() if self.tools else TALK_ONLY):
            opts += ["--disable", f]
        if self.tools:
            opts += [*KEYRING, "-c", 'approval_policy="never"', "-c", 'sandbox_mode="workspace-write"',
                     "-c", f"sandbox_workspace_write.network_access={'false' if self.offline else 'true'}"]
        else:
            opts += ["--ignore-user-config", "-s", "read-only"]
        if self.conv_id:
            cmd = ["codex", "exec", "resume", self.conv_id, *opts, "-"]
        else:
            cmd = ["codex", "exec", *opts, "-"]
        if self.tools:
            return agy._bwrap_prefix(self.ro_dirs, CODEX_HOME) + cmd
        return cmd

    def _env(self):
        if not self.tools:
            return _base_env()
        env = agy._env(self.agent_name, CODEX_HOME)
        env["CODEX_HOME"] = str(CODEX_HOME)
        return env

    async def wait(self):
        r = self.result
        turn = time.time()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self._cmd(), cwd=str(COMPANY), env=self._env(), stdin=asyncio.subprocess.PIPE,
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
            r.error = "ran out of time - partial work may be in the workspace"
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
            t, item = d.get("type"), d.get("item") or {}
            kind = item.get("type")
            if t == "thread.started":
                r.conv_id = d.get("thread_id") or r.conv_id
            elif t == "item.started" and kind == "command_execution":
                r.steps += 1
                await self._emit("run", "$ " + agy._short(item.get("command") or "", 120))
            elif t == "item.started" and kind == "web_search":
                r.steps += 1
                await self._emit("web", "Searching: " + agy._short(item.get("query") or "the web", 100))
            elif t == "item.completed" and kind == "file_change":
                r.steps += 1
                names = ", ".join(os.path.basename(c.get("path", "")) for c in item.get("changes") or [])
                await self._emit("write", "Writing " + agy._short(names, 100))
            elif t == "item.completed" and kind == "agent_message":
                r.text = item.get("text") or ""
            elif t == "item.completed" and kind == "reasoning":
                await self._emit("think", "Thinking")
            elif t == "turn.completed":
                self._record(d.get("usage") or {}, turn, step)
                u = d.get("usage") or {}
                r.tokens += int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
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
