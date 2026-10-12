"""Run one agent turn on Claude (Haiku) through Claude Code (`claude -p`).

Claude is Gemini's backup (config.json: "fallback": "haiku", and the haiku provider's own
"fallback": "local"). It runs on the operator's own Claude Code login, the same one the manager uses;
the office never reads it.

The operator's Claude settings, hooks, plugins, MCP servers and memory are left out (--setting-sources
project, --strict-mcp-config, auto memory off): an agent gets only what is listed here.
- File tools: Read only inside the workspace, the studied repos and the knowledge graphs; Edit/Write only
  inside the workspace. Only Bash, Read, Edit, Write and the web tools exist (--tools); Glob and Grep would
  search anywhere, so agents search with grep/find in Bash.
- Bash runs in Claude Code's sandbox (bubblewrap), which must be available (failIfUnavailable) and can't
  be bypassed (allowUnsandboxedCommands false): the home folder is unreadable except the workspace, the
  studied repos, the graphs and the developer tools; only the workspace and /tmp are writable. Agents
  that must learn code only from local copies get no web tools.
- dontAsk: anything not allowed above is denied, never asked.

Usage is appended to data/usage/<provider>.jsonl in the same shape as local runs, so the token ledger
counts it on its own (the manager's own sessions are counted separately).
"""
import asyncio
import json
import os
import re
import signal
import time

from . import agy
from .config import COMPANY, DATA, HOME, STATE

LIMIT_RE = re.compile(r"usage limit|rate limit|limit reached|hit your limit|resets? (at|in)|overloaded|429", re.I)
DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def reset_from_error(err, now=None):
    """Claude's limit message carries the reset as "...|<unix time>"; else None."""
    m = re.search(r"\|(\d{10})\b", err or "")
    return int(m.group(1)) + 60 if m else None


class ClaudeRun:
    """One claude process. `await run.wait()` returns an agy.AgyResult; `run.cancel()` kills it."""

    def __init__(self, prompt, *, agent_name, agent_id, provider, cfg, conv_id=None, timeout_min=30,
                 on_event=None, tools=True, ro_dirs=(), offline=False, **_):
        self.prompt = prompt[-120_000:]
        self.agent_name, self.agent_id = agent_name, agent_id
        self.provider = provider
        self.cfg = cfg
        self.model = cfg["model"]
        self.conv_id = conv_id
        self.timeout = int(timeout_min * 60)
        self.on_event = on_event
        self.tools = tools
        self.offline = offline
        self.ro_dirs = [str(p) for p in (os.path.expanduser(d) for d in ro_dirs) if os.path.isdir(p)]
        self.proc = None
        self.result = agy.AgyResult()
        self.usage_file = DATA / "usage" / f"{provider}.jsonl"

    def _readable(self):
        dirs = [str(COMPANY), *self.ro_dirs]
        if (STATE / "graphs").is_dir():
            dirs.append(str(STATE / "graphs"))
        return dirs

    def _settings(self):
        tools_ro = [str(HOME / p) for p in agy.HOME_TOOLS if (HOME / p).exists()]
        return {
            "autoMemoryEnabled": False,
            "sandbox": {
                "enabled": True, "failIfUnavailable": True, "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
                "filesystem": {"denyRead": [str(HOME)], "allowRead": self._readable() + tools_ro,
                               "allowWrite": [str(COMPANY), "/tmp"]},
            },
        }

    def _allowed(self):
        if not self.tools:
            return []
        allowed = ["Bash", f"Edit(/{COMPANY}/**)", f"Write(/{COMPANY}/**)"]   # "//abs/path" rules
        allowed += [f"Read(/{d}/**)" for d in self._readable()]
        if not self.offline:
            allowed += ["WebSearch", "WebFetch"]
        return allowed

    def _cmd(self):
        cmd = ["claude", "-p", self.prompt, "--output-format", "stream-json", "--verbose", "--model", self.model,
               "--permission-mode", "dontAsk", "--setting-sources", "project", "--strict-mcp-config",
               "--settings", json.dumps(self._settings())]
        allowed = self._allowed()
        if allowed:                              # only these tools exist for the agent, each scoped by a rule
            offered = ["Bash", "Read", "Edit", "Write"] + ([] if self.offline else ["WebSearch", "WebFetch"])
            cmd += ["--tools", *offered, "--allowedTools", *allowed]
        else:                                    # talk only
            cmd += ["--tools", ""]
        if self.conv_id:
            cmd += ["--resume", self.conv_id]
        return cmd

    async def wait(self):
        r = self.result
        env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
        env["AGENT_NAME"] = self.agent_name
        turn = time.time()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self._cmd(), cwd=str(COMPANY), env=env, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
                limit=16 * 1024 * 1024)
        except FileNotFoundError as e:
            r.error = f"cannot start claude: {e}"
            return r
        err_task = asyncio.create_task(self.proc.stderr.read())
        await self._emit("start", "Started")
        try:
            await asyncio.wait_for(self._read(r, turn), timeout=self.timeout)
        except asyncio.TimeoutError:
            r.error = "ran out of time - partial work may be in the workspace"
            self.cancel()
        await self.proc.wait()
        stderr = (await err_task).decode(errors="replace").strip()
        if r.cancelled:
            r.status, r.error = "CANCELLED", "cancelled"
        elif r.text.strip() and not r.error:
            r.status = "SUCCESS"
        else:
            r.error = r.error or agy._short(stderr, 600) or f"claude exited {self.proc.returncode} without an answer"
        if not r.ok and LIMIT_RE.search(stderr + " " + r.error):
            r.quota = True
        return r

    async def _read(self, r, turn):
        step = 0
        async for raw in self.proc.stdout:
            try:
                d = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            r.conv_id = d.get("session_id") or r.conv_id
            if d.get("type") == "assistant":
                msg = d.get("message") or {}
                self._record(msg.get("usage") or {}, turn, step)
                step += 1
                for c in msg.get("content") or []:
                    if c.get("type") == "tool_use":
                        r.steps += 1
                        await self._emit(*_describe(c))
                    elif c.get("type") == "thinking":
                        await self._emit("think", "Thinking")
            elif d.get("type") == "result":
                u = d.get("usage") or {}
                r.tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                            "cache_creation_input_tokens", "output_tokens"))
                if d.get("is_error") or d.get("subtype") != "success":
                    r.error = agy._short(str(d.get("result") or d.get("subtype") or "error"), 600)
                else:
                    r.text = d.get("result") or ""

    def _record(self, u, turn, step):
        from .ledger import _kind
        kind, ref = _kind(self.prompt)
        row = {"ts": time.time(), "turn": turn, "agent": self.agent_id, "provider": self.provider,
               "model": self.model, "conv": self.result.conv_id, "kind": kind, "ref": ref,
               "fresh": int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
               "cached": int(u.get("cache_read_input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
               "think": 0, "step": step, "ms": round((time.time() - turn) * 1000)}
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


def _describe(c):
    name, inp = c.get("name", ""), c.get("input") or {}
    if name == "Bash":
        return "run", "$ " + agy._short(inp.get("command") or "", 120)
    if name in ("Edit", "Write"):
        return "write", "Writing " + os.path.basename(inp.get("file_path") or "")
    if name == "Read":
        return "read", "Reading " + os.path.basename(inp.get("file_path") or "")
    if name in ("WebSearch", "WebFetch"):
        return "web", agy._short(inp.get("query") or inp.get("url") or name, 100)
    return "run", name
