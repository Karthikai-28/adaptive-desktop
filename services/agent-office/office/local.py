"""Run one agent turn on a local model through Ollama, with the same interface as agy.AgyRun.

agy brings its own agent loop and tools; Ollama is only a model, so this module is the loop: it sends the
conversation with a small tool set, runs the tools the model asks for, and repeats until the model
answers. The tools give the same reach agy has and no more:

  run_command   a shell command inside the same bubblewrap sandbox agy runs in (empty home, read-only
                system, the company workspace writable, assigned repositories read-only); agents that must
                learn code only from local copies get no network at all (--unshare-net)
  read_file, list_dir, search_files      the workspace, the assigned repositories and the scoped graphs
  write_file, edit_file                  the workspace only
  fetch_url     a web page as text (not for code-local-only agents)

Conversations are JSON files under data/local/<provider>/, one per thread, so a project's work thread or an
agent's chat thread continues like an agy conversation does. Every model call is appended to
data/usage/<provider>.jsonl with the token counts Ollama reports; the token ledger reads those files, so
local usage is counted on its own and never mixed with Gemini's.
"""
import asyncio
import html
import json
import os
import re
import signal
import time
import urllib.parse
import uuid
from pathlib import Path

from . import agy
from .config import COMPANY, DATA, STATE

LOCAL_HOME = DATA / "local-home"         # the sandbox's HOME for local agents' shell commands
OUT_MAX = 8000                           # characters of tool output handed back to the model
CMD_TIMEOUT_S = 120
DEFAULTS = {"url": "http://127.0.0.1:11434", "num_ctx": 8192, "think": False, "max_steps": 30, "keep_alive": "15m"}

TOOLS = [
    ("run_command", "Run a shell command (sh -c) in the workspace. Output is cut to the last 8000 characters; "
                    "pipe long output through head, tail or wc.",
     {"command": ("string", "the command line")}, ["command"]),
    ("read_file", "Read a text file, optionally a line range (1-based, inclusive). At most 400 lines per call.",
     {"path": ("string", "file path, relative to the workspace or absolute"),
      "start_line": ("integer", "first line, default 1"), "end_line": ("integer", "last line")}, ["path"]),
    ("write_file", "Create or overwrite a file in the workspace with the given content.",
     {"path": ("string", "file path inside the workspace"), "content": ("string", "the full file content")},
     ["path", "content"]),
    ("edit_file", "Replace one exact, unique piece of text in a workspace file.",
     {"path": ("string", "file path inside the workspace"), "old_text": ("string", "text to find, exactly once"),
      "new_text": ("string", "replacement")}, ["path", "old_text", "new_text"]),
    ("list_dir", "List a folder (names, / marks folders).", {"path": ("string", "folder, default the workspace")}, []),
    ("search_files", "grep -rn for a regular expression under a folder; at most 60 matching lines.",
     {"pattern": ("string", "extended regular expression"), "path": ("string", "folder or file, default the workspace")},
     ["pattern"]),
    ("fetch_url", "Fetch a web page (http/https) and return its text.", {"url": ("string", "the URL")}, ["url"]),
]


def tool_schema(offline):
    out = []
    for name, desc, props, req in TOOLS:
        if offline and name == "fetch_url":
            continue
        out.append({"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "required": req,
                           "properties": {k: {"type": t, "description": d} for k, (t, d) in props.items()}}}})
    return out


def _cut(s, n=OUT_MAX):
    s = str(s)
    return s if len(s) <= n else f"[... {len(s) - n} characters cut ...]\n" + s[-n:]


def _approx_tokens(messages):
    return sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or "")) for m in messages) // 3


class OllamaError(Exception):
    pass


async def ollama(url, path, body, timeout):
    """POST JSON to Ollama and return the JSON answer. Plain asyncio streams, so cancelling the run closes
    the connection and Ollama stops generating."""
    u = urllib.parse.urlsplit(url)
    host, port = u.hostname or "127.0.0.1", u.port or 80
    data = json.dumps(body).encode()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 10)
    except (OSError, asyncio.TimeoutError):
        raise OllamaError(f"the local model server (Ollama) is not reachable at {url}")
    try:
        writer.write(f"POST {path} HTTP/1.0\r\nHost: {host}:{port}\r\nContent-Type: application/json\r\n"
                     f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), timeout)
    except asyncio.TimeoutError:
        raise OllamaError("the local model did not answer in time")
    finally:
        writer.close()
    head, _, payload = raw.partition(b"\r\n\r\n")
    status = head.split(b" ", 2)[1:2]
    try:
        d = json.loads(payload or b"{}")
    except json.JSONDecodeError:
        raise OllamaError(f"Ollama sent something that is not JSON: {payload[:200]!r}")
    if status != [b"200"] or "error" in d:
        err = d.get("error") or f"HTTP {status[0].decode() if status else '?'}"
        if "not found" in err and "model" in err:
            err += f" - pull it first: ollama pull {body.get('model')}"
        raise OllamaError(err)
    return d


async def status(cfg):
    """What the office shows about a local provider: is Ollama up, is the model there, is it loaded."""
    url, model = cfg.get("url", DEFAULTS["url"]), cfg.get("model", "")
    out = {"engine": "ollama", "model": model, "up": False, "pulled": False, "loaded": False, "version": ""}
    try:
        u = urllib.parse.urlsplit(url)
        for path, key in (("/api/version", "version"), ("/api/tags", "models"), ("/api/ps", "loaded_models")):
            reader, writer = await asyncio.wait_for(asyncio.open_connection(u.hostname, u.port or 80), 3)
            writer.write(f"GET {path} HTTP/1.0\r\nHost: {u.hostname}\r\n\r\n".encode())
            raw = await asyncio.wait_for(reader.read(), 5)
            writer.close()
            d = json.loads(raw.partition(b"\r\n\r\n")[2] or b"{}")
            if key == "version":
                out["version"] = d.get("version", "")
            else:
                names = {m.get("name") for m in d.get("models", [])}
                hit = model in names or f"{model}:latest" in names
                out["pulled" if key == "models" else "loaded"] = hit
        out["up"] = True
    except (OSError, asyncio.TimeoutError, json.JSONDecodeError, ValueError):
        pass
    return out


class LocalRun:
    """One local agent turn. `await run.wait()` returns an agy.AgyResult; `run.cancel()` stops it."""

    def __init__(self, prompt, *, agent_name, provider, cfg, agent_id, conv_id=None, timeout_min=30,
                 on_event=None, ro_dirs=(), offline=False, graph=None, tools=True, max_steps=None):
        self.prompt = prompt
        self.agent_name, self.agent_id = agent_name, agent_id
        self.provider = provider
        self.cfg = {**DEFAULTS, **cfg}
        self.model = self.cfg["model"]
        self.conv_id = conv_id
        self.timeout = int(timeout_min * 60)
        self.on_event = on_event
        self.offline = offline
        self.graph = graph
        self.tools = tools
        self.max_steps = max_steps or self.cfg["max_steps"]
        self.ro_dirs = [str(Path(d).expanduser()) for d in ro_dirs if Path(d).expanduser().is_dir()]
        self.read_roots = [COMPANY.resolve(), *(Path(d).resolve() for d in self.ro_dirs)]
        if (STATE / "graphs").is_dir():
            self.read_roots.append((STATE / "graphs").resolve())
        self.result = agy.AgyResult()
        self._task = None
        self._procs = set()
        self.conv_dir = DATA / "local" / provider
        self.usage_file = DATA / "usage" / f"{provider}.jsonl"

    # ------------------------------------------------------------------ the loop
    async def wait(self):
        r = self.result
        self._task = asyncio.ensure_future(self._run(r))    # its own task, so cancel() never hits the caller
        try:
            await asyncio.wait_for(self._task, self.timeout)
        except asyncio.TimeoutError:
            r.error = "ran out of time - partial work may be in the workspace"
        except asyncio.CancelledError:
            if not r.cancelled:
                raise
        except OllamaError as e:
            r.error = str(e)
        except Exception as e:  # a broken tool or a bad answer must end this run, not the office
            r.error = f"local run failed: {e}"
        if r.cancelled:
            r.status, r.error = "CANCELLED", "cancelled"
        return r

    async def _run(self, r):
        conv = self._load()
        r.conv_id = conv["id"]
        msgs = conv["messages"]
        if not msgs:
            msgs.append({"role": "system", "content": self._system()})
        msgs.append({"role": "user", "content": self.prompt})
        turn = time.time()
        await self._emit("start", "Started")
        schema = tool_schema(self.offline) if self.tools else None
        try:
            for step in range(self.max_steps + 1):
                last = step == self.max_steps
                if last and schema:
                    msgs.append({"role": "user", "content": "You have used all your steps. Stop using tools and "
                                                            "write your final answer or report now."})
                self._fit(msgs)
                body = {"model": self.model, "messages": msgs, "stream": False, "think": bool(self.cfg["think"]),
                        "keep_alive": self.cfg["keep_alive"], "options": {"num_ctx": int(self.cfg["num_ctx"])}}
                if schema and not last:
                    body["tools"] = schema
                await self._emit("think", "Thinking")
                d = await ollama(self.cfg["url"], "/api/chat", body, self.timeout)
                m = d.get("message") or {}
                calls = m.get("tool_calls") or []
                self._record(d, turn, calls[0]["function"]["name"] if calls else "answer")
                r.tokens += int(d.get("prompt_eval_count") or 0) + int(d.get("eval_count") or 0)
                reply = {"role": "assistant", "content": m.get("content") or ""}
                if calls:
                    reply["tool_calls"] = calls
                msgs.append(reply)
                if not calls:
                    r.text, r.status = reply["content"], "SUCCESS"
                    if not r.text.strip():
                        r.status, r.error = "ERROR", "the local model gave an empty answer"
                    return
                for c in calls:
                    fn = c.get("function") or {}
                    name, args = fn.get("name", ""), fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    r.steps += 1
                    out = await self._tool(name, args)
                    msgs.append({"role": "tool", "tool_name": name, "content": _cut(out)})
        finally:
            self._save(conv)

    def _system(self):
        roots = ", ".join(str(p) for p in self.read_roots[1:]) or "none"
        net = ("You have no network access." if self.offline else "fetch_url reads web pages.")
        return (f"You are running on a local model ({self.model}) on the owner's computer. "
                f"Your working directory is {COMPANY}; it is the only place you can write. "
                f"Read-only folders you may also read: {roots}. {net} There is no image generation tool. "
                "Use the tools to do real work: look before you change things, verify what you build by running it, "
                "and keep tool output small. Only create or change files when your task or the message asks for it; "
                "a question just needs an answer. When you are done, answer without calling a tool.")

    def _fit(self, msgs):
        """Keep the conversation inside the model's context window: old tool output goes first, then the
        oldest exchanges (the system message and the first prompt, which carries the persona, always stay)."""
        budget = int(self.cfg["num_ctx"]) * 0.75
        if _approx_tokens(msgs) <= budget:
            return
        for m in msgs[2:-6]:
            if m["role"] == "tool" and len(m["content"]) > 200:
                m["content"] = m["content"][:200] + "\n[... older output removed to save space ...]"
        while _approx_tokens(msgs) > budget and len(msgs) > 8:
            del msgs[2]
            while len(msgs) > 3 and msgs[2]["role"] == "tool":    # never leave a tool answer without its call
                del msgs[2]

    # ------------------------------------------------------------------ tools
    async def _tool(self, name, a):
        try:
            if name == "run_command":
                cmd = str(a.get("command", ""))
                await self._emit("run", f"$ {agy._short(cmd, 100)}")
                return await self._sh(cmd)
            if name == "read_file":
                p = self._path(a.get("path", ""), write=False)
                await self._emit("read", f"Reading {agy._fname(p)}")
                lines = p.read_text(errors="replace").splitlines()
                start = max(1, int(a.get("start_line") or 1))
                end = min(len(lines), int(a.get("end_line") or start + 399), start + 399)
                body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
                more = f"\n[file has {len(lines)} lines; showing {start}-{end}]" if end < len(lines) or start > 1 else ""
                return (body or "(empty file)") + more
            if name == "write_file":
                p = self._path(a.get("path", ""), write=True)
                await self._emit("write", f"Writing {agy._fname(p)}")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(str(a.get("content", "")))
                return f"wrote {p} ({p.stat().st_size} bytes)"
            if name == "edit_file":
                p = self._path(a.get("path", ""), write=True)
                await self._emit("edit", f"Editing {agy._fname(p)}")
                text, old = p.read_text(), str(a.get("old_text", ""))
                n = text.count(old) if old else 0
                if n != 1:
                    return f"error: old_text found {n} times in {p}; it must match exactly once"
                p.write_text(text.replace(old, str(a.get("new_text", "")), 1))
                return f"edited {p}"
            if name == "list_dir":
                p = self._path(a.get("path") or ".", write=False)
                await self._emit("read", f"Looking in {agy._fname(p) or '.'}")
                items = sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
                return "\n".join(c.name + ("/" if c.is_dir() else "") for c in items[:300]) or "(empty folder)"
            if name == "search_files":
                p = self._path(a.get("path") or ".", write=False)
                pat = str(a.get("pattern", ""))
                await self._emit("search", f"Searching files: {agy._short(pat, 60)}")
                return await self._sh(f"grep -rnIE -m 20 --exclude-dir=.git --exclude-dir=node_modules -- "
                                      f"{_q(pat)} {_q(str(p))} | head -60")
            if name == "fetch_url" and not self.offline:
                url = str(a.get("url", ""))
                await self._emit("web", f"Reading {agy._short(url, 80)}")
                return await asyncio.to_thread(_fetch, url)
            return f"error: unknown tool {name}"
        except (OSError, ValueError, UnicodeError) as e:
            return f"error: {e}"

    def _path(self, raw, write):
        p = Path(str(raw)).expanduser()
        p = (p if p.is_absolute() else COMPANY / p).resolve()
        roots = [COMPANY.resolve()] if write else self.read_roots
        if not any(p == r or r in p.parents for r in roots):
            raise ValueError(f"{p} is outside the folders you may {'write' if write else 'read'}")
        return p

    async def _sh(self, cmd):
        LOCAL_HOME.mkdir(parents=True, exist_ok=True)
        pre = agy._bwrap_prefix(self.ro_dirs, LOCAL_HOME)
        if self.offline:
            pre.insert(1, "--unshare-net")
        proc = await asyncio.create_subprocess_exec(
            *pre, "sh", "-c", cmd, cwd=str(COMPANY), env=agy._env(self.agent_name, LOCAL_HOME, self.graph),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True)
        self._procs.add(proc)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), CMD_TIMEOUT_S)
        except asyncio.TimeoutError:
            _killpg(proc)
            await proc.wait()
            return f"error: the command ran longer than {CMD_TIMEOUT_S} s and was stopped"
        finally:
            self._procs.discard(proc)
        text = out.decode(errors="replace")
        return f"{text}\n[exit {proc.returncode}]" if proc.returncode else (text or "(no output)")

    # ------------------------------------------------------------------ conversations and usage
    def _load(self):
        if self.conv_id:
            f = self.conv_dir / f"{self.conv_id}.json"
            try:
                conv = json.loads(f.read_text())
                if conv.get("model") == self.model:
                    return conv
            except (OSError, json.JSONDecodeError):
                pass
        return {"id": uuid.uuid4().hex, "agent": self.agent_id, "model": self.model, "messages": []}

    def _save(self, conv):
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.conv_dir / f".{conv['id']}.tmp"
        tmp.write_text(json.dumps(conv))
        tmp.replace(self.conv_dir / f"{conv['id']}.json")

    def _record(self, d, turn, step):
        from .ledger import _kind     # the same classification the ledger uses for Gemini prompts
        kind, ref = _kind(self.prompt)
        row = {"ts": time.time(), "turn": turn, "agent": self.agent_id, "provider": self.provider,
               "model": d.get("model") or self.model, "conv": self.result.conv_id, "kind": kind, "ref": ref,
               "fresh": int(d.get("prompt_eval_count") or 0), "cached": 0, "out": int(d.get("eval_count") or 0),
               "think": 0, "step": step, "ms": round((d.get("total_duration") or 0) / 1e6)}
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.usage_file, "a") as fh:
            fh.write(json.dumps(row) + "\n")

    async def _emit(self, kind, text):
        if self.on_event:
            try:
                await self.on_event(kind, text)
            except Exception:  # an activity-feed hiccup must never kill the run
                pass

    def cancel(self):
        self.result.cancelled = True
        for p in list(self._procs):
            _killpg(p)
        if self._task and not self._task.done():
            self._task.cancel()


def _killpg(proc):
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _fetch(url):
    import urllib.request
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        return "error: only http and https URLs"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (agent-office)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(2_000_000).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    if "html" in (resp.headers.get_content_type() or ""):
        raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
        raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return _cut(re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", raw)).strip(), 12000)
