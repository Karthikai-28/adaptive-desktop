"""Run one Gemini turn through the Antigravity CLI (agy) on the AI Pro subscription.

Every run is wrapped in bubblewrap. The system is read-only; the home folder is replaced by an
empty one that holds only what an agent needs: its developer tools (read-only), agy's own home,
the shared company workspace (the only place it can write), and the repositories it was
assigned to study (read-only). Everything else in the home folder - documents, personal files,
credentials, other projects - does not exist for agents. /tmp is the office's own. agy's
--sandbox additionally confines shell commands. The environment is rebuilt from scratch so no
API key can leak in (an inherited GEMINI_API_KEY would also switch agy to paid API billing).
"""
import asyncio
import json
import os
import signal
from pathlib import Path

from .config import AGY_HOME, AGY_HOME_LOCAL, COMPANY, DATA, HOME, ROOT, STATE
from .repos import AGENT_BIN, REMOTE_GIT, git_env

# developer tools agents may use, shown read-only inside their otherwise empty home
HOME_TOOLS = [".local/bin", ".local/lib", ".local/share/uv/python", ".local/share/uv/tools", "bin",
              ".cargo/bin", ".rustup", ".nvm", ".npm-global", ".bun", ".deno", "micromamba", ".pyenv"]
# credential files that can sit inside those tool folders
TOOL_SECRETS = [".cargo/credentials", ".cargo/credentials.toml"]
SECRET_DIRS = [".ssh", ".gnupg", ".aws", ".codex", ".claude", ".config/gh", ".gemini", ".kube",
               ".docker", ".password-store", ".local/share/keyrings", ".mozilla",
               ".config/google-chrome", ".config/chromium", ".kaggle", ".cache/huggingface",
               ".cache/ask-gemini", ".config/gcloud", ".azure", ".terraform.d"]
SECRET_FILES = [".netrc", ".git-credentials", ".zshenv", ".claude.json", ".npmrc", ".pypirc",
                ".bash_history", ".zsh_history", ".python_history"]
KEEP_ENV = ("PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "DBUS_SESSION_BUS_ADDRESS",
            "XDG_RUNTIME_DIR", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "SHELL")
AGENT_TMP = STATE / "tmp"
# where the company code lives remotely - agents learning the code may never touch these
CODE_HOSTS = ["bitbucket.org", "api.bitbucket.org", "bitbucket.io", "192.168.1.10"]

QUOTA_MARKERS = ("RESOURCE_EXHAUSTED", "quota", "rate limit", "429", "usage limit")


def write_agy_settings(repos=()):
    """Permissions for agents: write inside the company workspace and the repos (the sandbox mounts every
    repo read-only except a task's own, so that is where a write really lands), never read secrets, never
    run a git command that reaches a remote.
    (Belt and braces: the sandbox already hides the secrets.) Agents that must learn code only from
    the local copies get their own agy home: the web is open for research, but the code hosts
    (Bitbucket, the internal git server) and every git network command are denied."""
    # MCP is allowed: the only server configured in the agents' agy profiles is the scoped knowledge graph
    deny = [f"read_file({HOME / p})" for p in SECRET_DIRS + SECRET_FILES]
    # the office's own files (agy's home sits in DATA too and must stay readable: MCP tool schemas live there)
    deny += [f"read_file({DATA / p})" for p in ("office.db", "office.db-wal", "office.db-shm", "logs", "tts",
                                                 "operator.key", "mission-control")]
    for home, offline in ((AGY_HOME, False), (AGY_HOME_LOCAL, True)):
        cfg_dir = home / ".gemini" / "antigravity-cli"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        allow = ["command(*)", f"write_file({COMPANY})", "read_url(*)", "execute_url(*)", "mcp(*)"]
        allow += [f"write_file({r})" for r in repos]
        d = list(deny) + [f"command(git {c})" for c in REMOTE_GIT]
        if offline:
            for host in CODE_HOSTS:
                for form in (host, f"https://{host}", f"http://{host}", f"*{host}*"):
                    d += [f"read_url({form})", f"execute_url({form})"]
            d += [f"command({c})" for c in ("curl", "wget", "ssh", "scp", "sftp", "rsync")]
        settings = {"permissions": {"allow": allow, "deny": d}, "trustedWorkspaces": [str(COMPANY)]}
        (cfg_dir / "settings.json").write_text(json.dumps(settings, indent=1))


def _bwrap_prefix(ro_dirs=(), home=AGY_HOME, rw_dirs=(), hidden=()):
    AGENT_TMP.mkdir(parents=True, exist_ok=True)
    args = ["bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--bind", "/proc", "/proc",
            "--tmpfs", str(HOME)]                                  # an empty home ...
    for p in HOME_TOOLS:                                           # ... with the tools ...
        path = HOME / p
        if path.exists():
            args += ["--ro-bind", str(path), str(path)]
    for p in TOOL_SECRETS:
        if (HOME / p).is_file():
            args += ["--ro-bind", "/dev/null", str(HOME / p)]
    for d in ro_dirs:                                              # ... the repositories, read-only ...
        d = Path(d).expanduser()
        if d.is_dir():
            args += ["--ro-bind", str(d), str(d)]
    for d in rw_dirs:                                              # ... the one a task may change ...
        d = Path(d).expanduser()
        if d.is_dir():
            args += ["--bind", str(d), str(d)]
    for f in hidden:                                               # ... minus their secret files
        if os.path.isfile(f) and not os.path.islink(f):
            args += ["--ro-bind", "/dev/null", f]
    if AGENT_BIN.is_dir():                                         # the git that refuses remotes
        args += ["--ro-bind", str(AGENT_BIN), str(AGENT_BIN)]
    graphs = STATE / "graphs"
    if graphs.is_dir():                                            # ... the scoped knowledge graphs ...
        args += ["--ro-bind", str(graphs), str(graphs)]
    args += ["--bind", str(home), str(home),                       # ... agy's home and the workspace
             "--bind", str(COMPANY), str(COMPANY),
             "--bind", str(AGENT_TMP), "/tmp",
             "--die-with-parent", "--chdir", str(COMPANY)]
    return args


def _env(agent_name, home=AGY_HOME, graph=None):
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    extra = f"{HOME}/.local/bin:{HOME}/bin"   # where the agy installer puts agy
    env["PATH"] = f"{extra}:{env['PATH']}"
    env.update(HOME=str(home), TERM="dumb", AGENT_NAME=agent_name, NO_COLOR="1")
    if graph:
        env["OFFICE_AGENT_GRAPH"] = str(graph)       # which graph the "graph" MCP server serves
    return git_env(env)


def _short(s, n=90):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _fname(p):
    if not p:
        return ""
    try:
        rel = Path(p).resolve().relative_to(COMPANY)
        return str(rel)
    except (ValueError, OSError):
        return Path(p).name or str(p)


def describe_tool(name, params):
    """Turn an agy tool call into one human line for the activity feed."""
    p = params or {}
    first = next((v for v in p.values() if isinstance(v, str) and v), "")
    f = _fname(p.get("TargetFile") or p.get("AbsolutePath") or p.get("File") or p.get("Path") or "")
    if name == "write_to_file":
        return "write", f"Writing {f}"
    if name in ("replace_file_content", "multi_replace_file_content", "sed_file", "notebook_edit"):
        return "edit", f"Editing {f}"
    if name == "view_file":
        return "read", f"Reading {f}"
    if name == "list_dir":
        return "read", f"Looking in {_fname(p.get('DirectoryPath') or first) or '.'}"
    if name in ("grep_search", "find_by_name"):
        return "search", f"Searching files: {_short(p.get('Query') or p.get('Pattern') or first, 60)}"
    if name == "run_command":
        return "run", f"$ {_short(p.get('CommandLine') or first, 100)}"
    if name in ("command_status", "send_command_input"):
        return "run", "Checking a running command"
    if name == "search_web":
        return "web", f"Searching the web: {_short(p.get('query') or p.get('Query') or first, 70)}"
    if name in ("read_url_content", "open_browser_url", "read_browser_page"):
        return "web", f"Reading {_short(p.get('Url') or p.get('url') or first, 80)}"
    if name.startswith("browser") or "browser" in name:
        return "web", "Using the browser"
    if name == "generate_image":
        return "image", f"Generating an image: {_short(first, 60)}"
    if name in ("invoke_subagent", "browser_subagent", "define_subagent", "manage_subagents"):
        return "think", "Delegating to a helper"
    if name in ("manage_task", "finish", "wait", "wait_5_seconds", "schedule"):
        return "think", "Planning"
    return "tool", f"{name.replace('_', ' ')} {_short(first, 60)}".strip()


class AgyResult:
    def __init__(self):
        self.text = ""
        self.conv_id = None
        self.status = "ERROR"
        self.error = ""
        self.steps = 0
        self.tokens = 0
        self.quota = False
        self.cancelled = False

    @property
    def ok(self):
        return self.status == "SUCCESS" and bool(self.text.strip())


class AgyRun:
    """One agy process. `await run.wait()` returns an AgyResult; `run.cancel()` kills it."""

    def __init__(self, prompt, *, agent_name, model, conv_id=None, timeout_min=30, on_event=None, ro_dirs=(), offline=False, graph=None,
                 rw_dirs=(), hidden=()):
        self.prompt = prompt[-120_000:]   # stay under the kernel's single-argument limit
        self.agent_name = agent_name
        self.model = model
        self.conv_id = conv_id
        self.timeout = int(timeout_min * 60)
        self.on_event = on_event
        self.home = AGY_HOME_LOCAL if offline else AGY_HOME
        self.graph = graph
        self.ro_dirs = [str(Path(d).expanduser()) for d in ro_dirs if Path(d).expanduser().is_dir()]
        self.rw_dirs = [str(Path(d).expanduser()) for d in rw_dirs if Path(d).expanduser().is_dir()]
        self.hidden = hidden
        self.proc = None
        self.result = AgyResult()

    async def wait(self):
        r = self.result
        cmd = _bwrap_prefix(self.ro_dirs, self.home, self.rw_dirs, self.hidden) + ["agy", "-p", self.prompt, "--model", self.model, "--sandbox",
                                 "--output-format", "stream-json", "--print-timeout", f"{self.timeout}s"]
        if self.conv_id:
            cmd += ["--conversation", self.conv_id]
        for d in dict.fromkeys(self.ro_dirs + self.rw_dirs):   # let agy's file tools reach the repositories
            cmd += ["--add-dir", d]
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(COMPANY), env=_env(self.agent_name, self.home, self.graph),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=16 * 1024 * 1024)
        except FileNotFoundError as e:
            r.error = f"cannot start agy: {e}"
            return r
        err_task = asyncio.create_task(self.proc.stderr.read())
        try:
            await asyncio.wait_for(self._read(r), timeout=self.timeout + 120)
        except asyncio.TimeoutError:
            r.error = "timed out"
            self.cancel()
        await self.proc.wait()
        stderr = (await err_task).decode(errors="replace")
        stderr = "\n".join(l for l in stderr.splitlines() if not l.startswith("Shell cwd was reset"))
        if r.cancelled:
            r.status, r.error = "CANCELLED", "cancelled"
        elif r.status != "SUCCESS" or not r.text.strip():
            r.error = r.error or _short(stderr, 600) or f"agy exited {self.proc.returncode} without an answer"
            if "print timeout" in stderr:
                r.error = "ran out of time (print timeout) — partial work may be in the workspace"
        blob = (stderr + " " + r.error).lower()
        if not r.ok and any(m.lower() in blob for m in QUOTA_MARKERS):
            r.quota = True
        return r

    async def _read(self, r):
        async for raw in self.proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = d.get("event")
            if ev == "init":
                r.conv_id = d.get("conversation_id") or r.conv_id
                await self._emit("start", "Started")
            elif ev == "step_update":
                s = d.get("step_update", {})
                r.conv_id = s.get("conversation_id") or r.conv_id
                kind, state = s.get("step_type"), s.get("state")
                if kind == "tool" and state == "ACTIVE":
                    r.steps += 1
                    info = s.get("tool_info") or {}
                    k, text = describe_tool(s.get("tool_name") or info.get("name", ""), info.get("parameters"))
                    await self._emit(k, text)
                elif kind == "tool" and state == "ERROR":
                    msg = ((s.get("tool_info") or {}).get("error") or {}).get("message", "")
                    await self._emit("error", "Tool failed: " + _short(msg, 140))
                elif kind == "agent_response" and state == "DONE":
                    u = s.get("usage") or {}
                    r.tokens += int(u.get("total_tokens") or 0)
                    await self._emit("think", "Thinking")
            elif ev == "result":
                res = d.get("result", {})
                r.conv_id = res.get("conversation_id") or r.conv_id
                r.status = res.get("status", "ERROR")
                r.text = res.get("response", "") or ""
                if not r.tokens:
                    r.tokens = int((res.get("usage") or {}).get("total_tokens") or 0)
                if r.status != "SUCCESS":
                    r.error = _short(res.get("error") or res.get("message") or r.status, 600)
            elif ev == "error":
                r.error = _short(d.get("error") or d.get("message") or line, 600)

    async def _emit(self, kind, text):
        if self.on_event:
            try:
                await self.on_event(kind, text)
            except Exception:  # an activity-feed hiccup must never kill the run
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
