#!/usr/bin/env python3
"""ROS 2 for the shell's ROS panel, as JSON.

    ros_info.py status                 distro, setup, workspaces, tools (loads no ROS)
    ros_info.py set <key> <value>...   domain | localhost | rmw | workspace; "" follows the shell
                                       (`set all ""` for all four); several pairs at once
    ros_info.py launch <tool> [file]   rviz2 | gazebo | rqt | rqt_graph | demo; file is a
                                       .rviz config or a world
    ros_info.py stop <tool>            ask every running copy of it to quit
    ros_info.py terminal               a terminal with the same ROS setup as the panel
    ros_info.py install-gazebo         a terminal on the apt command (the password is typed there)
    ros_info.py watch                  the live graph; see below

The setup follows the login shell's startup files (~/.zshrc for Zsh, ~/.bashrc
for bash) unless the panel changed it: the distro and workspace they source,
`export ROS_DOMAIN_ID=`, `ROS_LOCALHOST_ONLY`, `RMW_IMPLEMENTATION`. A change
made in the panel is kept in ~/.config/adaptive-desktop/ros2.json. `status`
also reports ROS processes started outside the panel on another domain or
discovery range ("elsewhere"), so the panel can offer to follow them. Everything
that needs ROS runs in an environment made by sourcing the distro's setup.bash
(and the workspace's install/setup.bash) in bash, never ~/.bashrc itself.

`watch` keeps one rclpy node, hidden by its leading underscore, and prints JSON
lines: {"type": "graph", ...} whenever the graph changes, {"type": "reply",
"id": n, ...} for each request, {"type": "error", "error": ...} if ROS cannot
start. Requests come on stdin, one JSON object a line:

    {"id": 1, "cmd": "node", "name": "/ns/talker"}   parameters, lifecycle state, QoS
    {"id": 2, "cmd": "topic", "name": "/chatter"}    every endpoint with its QoS
    {"id": 3, "cmd": "interface", "type": "std_msgs/msg/String"}
    {"id": 4, "cmd": "hz", "name": "/chatter"}       rate and bandwidth over two seconds

It exits when stdin closes, so it cannot outlive the shell that started it.
"""

import json
import os
import pwd
import queue
import re
import fcntl
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "adaptive-desktop" / "ros2.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "adaptive-desktop" / "ros"
RUNS = CACHE / "owned-runs.json"
ROS_ROOT = Path(os.environ.get("ADAPTIVE_ROS_ROOT", "/opt/ros"))
SHELL_FILES = {"zsh": (".zshenv", ".zprofile", ".zshrc"),
               "bash": (".profile", ".bash_profile", ".bashrc")}
ENV_MARK = "ADAPTIVE_ROS_ENV"

# The middleware each distro uses when RMW_IMPLEMENTATION is not set.
DEFAULT_RMW = {"humble": "rmw_fastrtps_cpp", "iron": "rmw_fastrtps_cpp",
               "jazzy": "rmw_fastrtps_cpp", "kilted": "rmw_fastrtps_cpp", "rolling": "rmw_fastrtps_cpp"}
RMW_NAMES = {"rmw_fastrtps_cpp": "Fast DDS", "rmw_fastrtps_dynamic_cpp": "Fast DDS (dynamic)",
             "rmw_cyclonedds_cpp": "Cyclone DDS", "rmw_connextdds": "Connext DDS",
             "rmw_zenoh_cpp": "Zenoh"}
PARAMETER_SERVICES = {"describe_parameters", "get_parameter_types", "get_parameters",
                      "list_parameters", "set_parameters", "set_parameters_atomically"}
SKIP_DIRS = {"build", "install", "log", "node_modules", "snap", "venv", ".venv", "__pycache__"}
HZ_WINDOW_S = 2.0
REQUEST_TIMEOUT_S = 3.0
GRAPH_EVERY_S = 1.0
CONTROLLERS_EVERY_S = 3.0
IDLE_GRAPH_EVERY_S = 10.0
MAX_PARAMETERS = 200


def emit(obj):
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        os._exit(0)


# ------------------------------------------------------------------ setup

def read_config():
    try:
        data = json.loads(CONFIG.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_config(data):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_name(f"{CONFIG.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG)


class file_lock:
    """An advisory lock for the panel's small cross-process state files."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_args):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def login_shell():
    """zsh or bash: whose startup files hold the user's ROS setup."""
    shell = os.environ.get("SHELL")
    if not shell:
        try:
            shell = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            shell = ""
    return "zsh" if os.path.basename(shell) == "zsh" else "bash"


def shell_rc():
    return "~/" + SHELL_FILES[login_shell()][-1]


def from_shell_files():
    """What the login shell's startup files set at top level: the last value of each wins."""
    found = {}
    export = re.compile(r"^\s*export\s+(ROS_DOMAIN_ID|ROS_LOCALHOST_ONLY|RMW_IMPLEMENTATION)="
                        r"(['\"]?)([^'\"\s#;]*)\2")
    assign = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(['\"]?)([^'\"\s;]*)\2\s*(?:#.*)?$")
    source = re.compile(r"^\s*(?:\[\[?[^]]*\]\]?\s*&&\s*)?(?:source|\.)\s+(['\"]?)([^'\"\s;]+)\1")
    variables = {}

    def expand(text):
        text = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?",
                      lambda m: variables.get(m.group(1), os.environ.get(m.group(1), m.group(0))), text)
        return os.path.expanduser(text)

    for name in SHELL_FILES[login_shell()]:
        try:
            lines = (HOME / name).read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = export.match(line)
            if m:
                found[m.group(1)] = m.group(3)
                continue
            m = assign.match(line)
            if m:
                variables[m.group(1)] = expand(m.group(3))
                continue
            m = source.match(line)
            if not m:
                continue
            path = expand(m.group(2))
            distro = re.match(rf"^{re.escape(str(ROS_ROOT))}/([^/]+)/setup\.(?:bash|sh|zsh)$", path)
            if distro:
                found["distro"] = distro.group(1)
            elif re.search(r"/install/(?:local_)?setup\.(?:bash|sh|zsh)$", path):
                found["workspace"] = str(Path(path).parent.parent)
    return found


def distros():
    try:
        return sorted(p.name for p in ROS_ROOT.iterdir() if (p / "setup.bash").is_file())
    except OSError:
        return []


def workspaces():
    """colcon workspaces in the home folder: <dir>/install/setup.bash, two levels deep."""
    found = []
    try:
        tops = [p for p in HOME.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        tops = []
    for top in sorted(tops):
        candidates = [top]
        try:
            candidates += sorted(p for p in top.iterdir()
                                 if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIRS)
        except OSError:
            pass
        for path in candidates:
            if (path / "install" / "setup.bash").is_file():
                found.append({"name": str(path.relative_to(HOME)), "path": str(path)})
    return found


def workspace_name(path):
    """A short name: a build tree like proj/.build/humble is called proj."""
    path = Path(path)
    try:
        parts = path.relative_to(HOME).parts
    except ValueError:
        parts = path.parts[1:]
    for i, part in enumerate(parts):
        if part.startswith(".") and i:
            return parts[i - 1]
    return "/".join(parts) or str(path)


def settings():
    """The setup the panel uses, and where each part came from."""
    shell = from_shell_files()
    config = read_config()
    available = distros()
    distro = config.get("distro") or shell.get("distro")
    if distro not in available:
        distro = available[-1] if available else None

    def pick(key, shell_key, parse, default):
        if key in config:
            return parse(config[key]), "panel"
        if shell_key in shell:
            try:
                return parse(shell[shell_key]), "shell"
            except ValueError:
                pass
        return default, "default"

    domain, domain_from = pick("domain", "ROS_DOMAIN_ID", int, 0)
    localhost, localhost_from = pick("localhost", "ROS_LOCALHOST_ONLY",
                                     lambda v: str(v).lower() in ("1", "true"), False)
    rmw, rmw_from = pick("rmw", "RMW_IMPLEMENTATION", str, "")
    workspace, workspace_from = pick("workspace", "workspace", str, "")
    if workspace and not (Path(workspace) / "install" / "setup.bash").is_file():
        workspace = ""
    return {
        "distro": distro,
        "domain": domain,
        "localhost": localhost,
        "rmw": rmw or DEFAULT_RMW.get(distro or "", "rmw_fastrtps_cpp"),
        "rmw_set": bool(rmw),
        "workspace": workspace,
        "from": {"domain": domain_from, "localhost": localhost_from,
                 "rmw": rmw_from, "workspace": workspace_from},
    }


def middlewares(distro):
    lib = ROS_ROOT / (distro or "") / "lib"
    return [name for name in RMW_NAMES if (lib / f"lib{name}.so").is_file()]


def ros_env(setup=None):
    """os.environ with the distro (and workspace) sourced and the setup applied."""
    setup = setup or settings()
    if not setup["distro"]:
        raise RuntimeError("ROS 2 is not installed")
    script = f"source {shlex.quote(str(ROS_ROOT / setup['distro'] / 'setup.bash'))} >/dev/null 2>&1; "
    if setup["workspace"]:
        script += f"source {shlex.quote(str(Path(setup['workspace']) / 'install' / 'setup.bash'))} >/dev/null 2>&1; "
    script += "env -0"
    base = {k: v for k, v in os.environ.items()
            if not k.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_")) and k != "CMAKE_PREFIX_PATH"}
    out = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", script], env=base,
                         capture_output=True, timeout=20).stdout
    env = dict(item.split("=", 1) for item in out.decode(errors="replace").split("\0") if "=" in item)
    if "AMENT_PREFIX_PATH" not in env:
        raise RuntimeError(f"Sourcing ROS 2 {setup['distro']} failed")
    env["ROS_DOMAIN_ID"] = str(setup["domain"])
    if setup["localhost"]:
        env["ROS_LOCALHOST_ONLY"] = "1"
    else:
        env.pop("ROS_LOCALHOST_ONLY", None)
    if setup["rmw_set"]:
        env["RMW_IMPLEMENTATION"] = setup["rmw"]
    env[ENV_MARK] = "1"
    return env


def prefixes(env=None):
    env = env if env is not None else os.environ
    return [Path(p) for p in env.get("AMENT_PREFIX_PATH", "").split(":") if p]


# ------------------------------------------------------------------ tools

def processes():
    """(pid, argv) of every process of this user."""
    me, uid = os.getpid(), os.getuid()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            with open(f"/proc/{entry.name}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if argv:
            yield int(entry.name), argv


INTERPRETERS = re.compile(r"^(python[\d.]*|ruby[\d.]*|bash|sh)$")


def tool_of(argv):
    """Which panel tool a command line is, or None."""
    words = argv[:]
    while words and INTERPRETERS.match(os.path.basename(words[0])):
        words = [w for w in words[1:] if not w.startswith("-")] if len(words) > 1 else []
    if not words:
        return None
    exe = os.path.basename(words[0])
    rest = words[1:]
    if exe == "rviz2":
        return "rviz2"
    if exe in ("rqt", "rqt_graph"):
        return exe
    if exe in ("gzserver", "gzclient", "gazebo"):
        return "gazebo"
    if exe in ("gz", "ign") and rest[:1] in (["sim"], ["gazebo"]):
        return "gazebo"
    if exe == "ros2" and rest[:1] == ["launch"] and any(
            a.endswith(("gazebo.launch.py", "gz_sim.launch.py")) for a in rest):
        return "gazebo"
    if words[0].endswith(("/demo_nodes_cpp/talker", "/demo_nodes_cpp/listener")):
        return "demo"
    return None


def running():
    found = {}
    for pid, argv in processes():
        tool = tool_of(argv)
        if tool:
            found.setdefault(tool, []).append(pid)
    return found


def elsewhere(setup):
    """ROS processes started outside the panel on a domain or range the panel does not see."""
    groups = {}
    for pid, argv in processes():
        if any(a.endswith("_ros2_daemon") for a in argv[:3]):
            continue
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = dict(item.split(b"=", 1) for item in f.read().split(b"\0") if b"=" in item)
        except OSError:
            continue
        if b"ROS_DISTRO" not in env or ENV_MARK.encode() in env:
            continue
        roots = [r.decode(errors="replace") + "/" for r in env.get(b"AMENT_PREFIX_PATH", b"").split(b":") if r]
        if not ("--ros-args" in argv or tool_of(argv)
                or any(w.startswith(r) for w in argv[:2] for r in roots)):
            continue
        try:
            domain = int(env.get(b"ROS_DOMAIN_ID", b"0") or 0)
        except ValueError:
            continue
        localhost = env.get(b"ROS_LOCALHOST_ONLY", b"").lower() in (b"1", b"true")
        distro = env.get(b"ROS_DISTRO", b"").decode(errors="replace")
        rmw = env.get(b"RMW_IMPLEMENTATION", b"").decode(errors="replace") or DEFAULT_RMW.get(distro, "")
        if (domain, localhost, rmw) != (setup["domain"], setup["localhost"], setup["rmw"]):
            groups[(domain, localhost, rmw)] = groups.get((domain, localhost, rmw), 0) + 1
    return [{"domain": d, "localhost": l, "rmw": r,
             "rmw_name": RMW_NAMES.get(r, r), "count": n}
            for (d, l, r), n in sorted(groups.items(), key=lambda kv: -kv[1])]


def gazebo_flavour(distro, env_path=None):
    """How Gazebo is started here: (flavour, argv for a world or None), or (None, None)."""
    share = ROS_ROOT / (distro or "") / "share"
    path = env_path or os.environ.get("PATH", "")
    if (share / "ros_gz_sim").is_dir():
        return "gz", lambda world: ["ros2", "launch", "ros_gz_sim", "gz_sim.launch.py",
                                    f"gz_args:={world or 'empty.sdf'}"]
    if (share / "gazebo_ros").is_dir():
        return "classic", lambda world: ["ros2", "launch", "gazebo_ros", "gazebo.launch.py",
                                         *([f"world:={world}"] if world else [])]
    if shutil.which("gz", path=path):
        return "gz", lambda world: ["gz", "sim", world or "empty.sdf"]
    if shutil.which("ign", path=path):
        return "gz", lambda world: ["ign", "gazebo", world or "empty.sdf"]
    if shutil.which("gazebo", path=path):
        return "classic", lambda world: ["gazebo", *([world] if world else [])]
    return None, None


def recent_files(roots, match, limit=6):
    """Files matching `match(path)` under `roots` [(dir, depth)], newest first."""
    seen = {}

    def walk(path, depth):
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for e in entries:
            if e.name.startswith(".") and e.name != ".rviz2":
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth > 0 and e.name not in SKIP_DIRS:
                        walk(e.path, depth - 1)
                elif e.is_file() and match(e.path):
                    seen[e.path] = e.stat().st_mtime
            except OSError:
                continue
    for root, depth in roots:
        walk(str(root), depth)
    newest = sorted(seen, key=seen.get, reverse=True)[:limit]
    return [{"name": os.path.basename(p), "path": p} for p in newest]


def search_roots(setup):
    roots = [(HOME / ".rviz2", 0), (HOME, 2)]
    for ws in workspaces():
        roots.append((Path(ws["path"]) / "src", 7))
    return roots


def is_world(path):
    return path.endswith(".world") or (path.endswith(".sdf") and "/worlds/" in path)


def status():
    setup = settings()
    distro = setup["distro"]
    if not distro:
        return {"installed": False, "distros": []}
    base = ROS_ROOT / distro
    flavour, _ = gazebo_flavour(distro)
    procs = running()
    owned = owned_runs()
    owned_groups = {name: {int(entry["pgid"]) for entry in entries}
                    for name, entries in owned.items()}
    roots = search_roots(setup)
    tools = {
        "rviz2": (base / "bin" / "rviz2").is_file(),
        "gazebo": flavour is not None,
        "rqt": (base / "bin" / "rqt").is_file(),
        "rqt_graph": (base / "bin" / "rqt_graph").is_file(),
        "demo": (base / "lib" / "demo_nodes_cpp" / "talker").is_file(),
    }
    spaces = workspaces()
    if setup["workspace"] and all(w["path"] != setup["workspace"] for w in spaces):
        spaces.append({"name": workspace_name(setup["workspace"]), "path": setup["workspace"]})
    return {
        "installed": True,
        "distros": distros(),
        **setup,
        "shell_rc": shell_rc(),
        "elsewhere": elsewhere(setup),
        "rmw_name": RMW_NAMES.get(setup["rmw"], setup["rmw"]),
        "middlewares": [{"id": m, "name": RMW_NAMES[m]} for m in middlewares(distro)],
        "workspaces": spaces,
        "tools": {name: {
            "installed": ok,
            "pids": procs.get(name, []),
            "owned_pids": [pid for pid in procs.get(name, [])
                           if pid_group(pid) in owned_groups.get(name, set())],
            "external_pids": [pid for pid in procs.get(name, [])
                              if pid_group(pid) not in owned_groups.get(name, set())],
        } for name, ok in tools.items()},
        "gazebo_flavour": flavour,
        "gazebo_install": f"sudo apt install ros-{distro}-ros-gz",
        "rviz_configs": recent_files(roots, lambda p: p.endswith(".rviz")),
        "worlds": recent_files(roots, is_world),
    }


def log_file(tool):
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{tool}.log"


def read_runs():
    try:
        data = json.loads(RUNS.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_runs(data):
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNS.with_name(f"{RUNS.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(RUNS)


def process_group_exists(pgid):
    try:
        os.killpg(int(pgid), 0)
        return True
    except (OSError, ValueError):
        return False


def pid_group(pid):
    try:
        # /proc/<pid>/stat: process group is field five. Split after the final
        # ')' because a process name itself may contain spaces.
        rest = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(rest[2])
    except (OSError, ValueError, IndexError):
        return 0


def owned_runs(tool=None):
    """Live process groups started by this panel, pruning dead entries."""
    with file_lock(RUNS.with_suffix(".lock")):
        data = read_runs()
        cleaned = {}
        for name, entries in data.items():
            live = [entry for entry in entries if process_group_exists(entry.get("pgid", 0))]
            if live:
                cleaned[name] = live
        if cleaned != data:
            write_runs(cleaned)
    return cleaned.get(tool, []) if tool else cleaned


def remember_runs(tool, procs, argv):
    with file_lock(RUNS.with_suffix(".lock")):
        data = read_runs()
        entries = [entry for entry in data.get(tool, [])
                   if process_group_exists(entry.get("pgid", 0))]
        entries.extend({"pid": proc.pid, "pgid": proc.pid, "argv": command,
                        "started": time.time()} for proc, command in zip(procs, argv))
        data[tool] = entries
        write_runs(data)


def forget_runs(tool):
    with file_lock(RUNS.with_suffix(".lock")):
        data = read_runs()
        data.pop(tool, None)
        write_runs(data)


def spawn(argv, env, tool, cwd=None):
    path = log_file(tool)
    if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
        path.replace(path.with_suffix(".log.1"))
    log = open(path, "ab")
    log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(argv)}\n".encode())
    log.flush()
    return subprocess.Popen(argv, env=env, cwd=cwd or str(HOME), start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=log, stderr=log)


def launch(tool, file=None):
    setup = settings()
    env = ros_env(setup)
    base = ROS_ROOT / setup["distro"]
    if tool == "rviz2":
        argv = [["rviz2", *(["-d", file] if file else [])]]
    elif tool in ("rqt", "rqt_graph"):
        argv = [[tool]]
    elif tool == "gazebo":
        _, command = gazebo_flavour(setup["distro"], env.get("PATH"))
        if not command:
            return {"ok": False, "error": "Gazebo is not installed"}
        argv = [command(file)]
    elif tool == "demo":
        lib = base / "lib" / "demo_nodes_cpp"
        argv = [[str(lib / "talker")], [str(lib / "listener")]]
    else:
        return {"ok": False, "error": f"unknown tool {tool}"}
    procs = [spawn(a, env, tool) for a in argv]
    # Something that cannot start says so at once; give it a moment to.
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline and all(p.poll() is None for p in procs):
        time.sleep(0.05)
    failed = [p for p in procs if p.poll() not in (None, 0)]
    if failed:
        for proc in procs:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    pass
        tail = log_file(tool).read_text(errors="replace").strip().splitlines()[-3:]
        return {"ok": False, "error": tail[-1] if tail else "It exited at once", "log": str(log_file(tool))}
    remember_runs(tool, procs, argv)
    return {"ok": True, "pids": [p.pid for p in procs], "log": str(log_file(tool))}


def stop(tool):
    entries = owned_runs(tool)
    groups = [int(entry["pgid"]) for entry in entries]
    for pgid in groups:
        try:
            os.killpg(pgid, signal.SIGINT)
        except OSError:
            pass
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(process_group_exists(pgid) for pgid in groups):
        time.sleep(0.1)
    for pgid in groups:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except OSError:
            pass
    forget_runs(tool)
    return {"ok": True, "stopped": len(groups)}


def terminal_rc(setup):
    """Load the normal KTERM Zsh startup, then apply the panel's ROS setup."""
    user_dotdir = os.environ.get("ZDOTDIR")
    user_rc = Path(user_dotdir or HOME) / ".zshrc"
    lines = [f"export ZDOTDIR={shlex.quote(user_dotdir)}" if user_dotdir else "unset ZDOTDIR",
             f"[[ -f {shlex.quote(str(user_rc))} ]] && source {shlex.quote(str(user_rc))}",
             f"source {shlex.quote(str(ROS_ROOT / setup['distro'] / 'setup.zsh'))}"]
    if setup["workspace"]:
        ws = Path(setup["workspace"])
        # A build tree like proj/.build/humble opens in proj.
        top = next((p.parent for p in (ws, *ws.parents) if p.name.startswith(".")), ws)
        lines += [f"source {shlex.quote(str(ws / 'install' / 'setup.zsh'))}", f"cd {shlex.quote(str(top))}"]
    lines.append(f"export ROS_DOMAIN_ID={int(setup['domain'])}")
    lines.append("export ROS_LOCALHOST_ONLY=1" if setup["localhost"] else "unset ROS_LOCALHOST_ONLY")
    if setup["rmw_set"]:
        lines.append(f"export RMW_IMPLEMENTATION={shlex.quote(setup['rmw'])}")
    dotdir = CACHE / "terminal-zsh"
    dotdir.mkdir(parents=True, exist_ok=True)
    rc = dotdir / ".zshrc"
    rc.write_text("\n".join(lines) + "\n")
    return rc


def open_terminal(title, command=None):
    cmd = command or []
    if shutil.which("kterm-terminal"):
        argv = ["kterm-terminal", "-T", title, "-x", *cmd] if cmd else ["kterm-terminal", "-T", title]
    elif shutil.which("terminator"):
        argv = ["terminator", "-T", title, "-x", *cmd] if cmd else ["terminator", "-T", title]
    elif shutil.which("gnome-terminal"):
        argv = ["gnome-terminal", "--title", title, "--", *cmd] if cmd else ["gnome-terminal", "--title", title]
    else:
        argv = ["x-terminal-emulator", "-e", *cmd] if cmd else ["x-terminal-emulator"]
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


def terminal():
    setup = settings()
    if not setup.get("distro"):
        return open_terminal("Terminal", [])
    rc = terminal_rc(setup)
    return open_terminal(f"ROS 2 {setup['distro']} · domain {setup['domain']}",
                         ["env", "-u", "KARTHI_MODERN_LOADED", "-u", "KARTHI_HUD_SHOWN",
                          "KARTHI_SHELL_MODE=modern", f"ZDOTDIR={rc.parent}", "zsh", "-i"])


def install_gazebo():
    distro = settings()["distro"]
    if not distro:
        return {"ok": False, "error": "ROS 2 is not installed"}
    command = f"sudo apt install ros-{distro}-ros-gz"
    script = f"echo {shlex.quote('$ ' + command)}; {command}; echo; read -rp 'Press Enter to close. '"
    return open_terminal("Install Gazebo", ["bash", "-c", script])


def set_values(pairs):
    """Validate and commit a setting batch atomically across helper processes."""
    with file_lock(CONFIG.with_suffix(".lock")):
        config = read_config()
        for key, value in pairs:
            if key == "all" and value == "":
                config = {}
            elif value == "":
                config.pop(key, None)
            elif key == "domain":
                domain = int(value)
                if not 0 <= domain <= 232:
                    return {"ok": False, "error": "A domain ID is 0 to 232"}
                config[key] = domain
            elif key == "localhost":
                config[key] = value.lower() in ("1", "true", "yes", "on")
            elif key == "rmw":
                if value not in middlewares(settings()["distro"]):
                    return {"ok": False, "error": f"{value} is not installed"}
                config[key] = value
            elif key == "workspace":
                if value != "none" and not (Path(value) / "install" / "setup.bash").is_file():
                    return {"ok": False, "error": f"{value} has no install/setup.bash"}
                config[key] = "" if value == "none" else value
            else:
                return {"ok": False, "error": f"unknown setting {key}"}
        write_config(config)
    return {"ok": True, **status()}


def set_value(key, value):
    return set_values([(key, value)])


# ------------------------------------------------------------------ interfaces

PRIMITIVES = {"bool", "byte", "char", "float32", "float64", "int8", "uint8", "int16", "uint16",
              "int32", "uint32", "int64", "uint64", "string", "wstring", "duration", "time"}


def interface_file(type_name, env=None):
    parts = type_name.split("/")
    if len(parts) == 2:
        parts = [parts[0], "msg", parts[1]]
    if len(parts) != 3:
        return None
    package, kind, name = parts
    for prefix in prefixes(env):
        path = prefix / "share" / package / kind / f"{name}.{kind}"
        if path.is_file():
            return path
    return None


def interface_text(type_name, depth=0, env=None, budget=None):
    """The definition, with nested types indented under their field like `ros2 interface show`."""
    budget = budget if budget is not None else [120]
    path = interface_file(type_name, env)
    if not path:
        return None
    package = type_name.split("/")[0]
    out = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if budget[0] <= 0:
            out.append("\t" * depth + "…")
            break
        budget[0] -= 1
        out.append("\t" * depth + line.strip())
        words = line.split()
        if line.strip() == "---" or len(words) < 2 or "=" in line:
            continue
        field_type = re.sub(r"(\[.*\]|<=\d+)$", "", words[0])
        field_type = re.sub(r"<=\d+$", "", field_type)
        if field_type in PRIMITIVES or depth >= 2:
            continue
        nested = field_type if "/" in field_type else f"{package}/{field_type}"
        if nested == "Header" or field_type == "Header":
            nested = "std_msgs/Header"
        inner = interface_text(nested, depth + 1, env, budget)
        if inner:
            out.append(inner)
    return "\n".join(out)


# ------------------------------------------------------------------ watch

def join_name(ns, name):
    return f"{ns.rstrip('/')}/{name}" if ns != "/" else f"/{name}"


def split_name(full):
    ns, _, name = full.rpartition("/")
    return ns or "/", name


def hidden(name):
    return any(part.startswith("_") for part in name.split("/") if part)


# Discovery carries reliability and durability; depth and history stay local to
# each endpoint (they read 0 and "unknown"), so they are not shown.
def qos_summary(profile):
    def label(value):
        return value.name.lower().replace("_", " ") if hasattr(value, "name") else str(value)
    return {"reliability": label(profile.reliability), "durability": label(profile.durability)}


class Watcher:
    def __init__(self):
        import rclpy
        import rclpy.action
        from rclpy.executors import SingleThreadedExecutor

        self.rclpy = rclpy
        self.action = rclpy.action
        rclpy.init(args=[])
        self.node = rclpy.create_node(f"_adaptive_panel_{os.getpid()}",
                                      start_parameter_services=False, enable_rosout=False)
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.requests = queue.Queue()
        self.jobs = []
        self.last_graph = None
        self.graph = {}
        self.controllers = None
        self.controller_jobs = {}
        self.next_controllers = 0.0
        self.graph_every = GRAPH_EVERY_S
        self.next_graph = 0.0

    # --- the graph

    def by_node(self, name, ns):
        n, a = self.node, self.action

        def named(pairs):
            return [{"name": t, "types": types} for t, types in pairs if not hidden(t)]
        services = self.node.get_service_names_and_types_by_node(name, ns)
        full = join_name(ns, name)
        params = [s for s, _ in services if s.startswith(full + "/") and s[len(full) + 1:] in PARAMETER_SERVICES]
        return {
            "publishers": named(n.get_publisher_names_and_types_by_node(name, ns)),
            "subscribers": named(n.get_subscriber_names_and_types_by_node(name, ns)),
            "services": [s for s in named(services) if s["name"] not in params],
            "clients": [c for c in named(n.get_client_names_and_types_by_node(name, ns))
                        if not (c["name"].rsplit("/", 1)[-1] in PARAMETER_SERVICES)],
            "action_servers": named(a.get_action_server_names_and_types_by_node(n, name, ns)),
            "action_clients": named(a.get_action_client_names_and_types_by_node(n, name, ns)),
            "parameter_services": len(params) > 0,
            "lifecycle": any(s == f"{full}/get_state" for s, _ in services),
        }

    def snapshot(self):
        nodes, hidden_nodes, counts = [], 0, {}
        ends = {kind: {} for kind in ("publishers", "subscribers", "services", "clients",
                                      "action_servers", "action_clients")}
        for name, ns, enclave in self.node.get_node_names_and_namespaces_with_enclaves():
            full = join_name(ns, name)
            counts[full] = counts.get(full, 0) + 1
            if counts[full] > 1:
                continue
            if hidden(full):
                hidden_nodes += 1
                continue
            try:
                parts = self.by_node(name, ns)
            except Exception:  # The node left between the two calls.
                continue
            for kind in ends:
                for item in parts[kind]:
                    ends[kind].setdefault(item["name"], []).append(full)
            nodes.append({"name": full, "short": name, "namespace": ns, "enclave": enclave, **parts})
        for node in nodes:
            node["copies"] = counts[node["name"]]
        nodes.sort(key=lambda n: n["name"])

        topics, hidden_topics = [], 0
        for name, types in self.node.get_topic_names_and_types():
            if hidden(name):
                hidden_topics += 1
                continue
            publishers = ends["publishers"].get(name, [])
            subscribers = ends["subscribers"].get(name, [])
            system = name in ("/rosout", "/parameter_events")
            # Every node has these two, the panel's own included; with only
            # hidden nodes on them they say nothing.
            if system and not publishers and not subscribers:
                hidden_topics += 1
                continue
            topics.append({"name": name, "types": types, "publishers": publishers,
                           "subscribers": subscribers, "system": system})
        services, parameter_services = [], 0
        for name, types in self.node.get_service_names_and_types():
            if hidden(name):
                continue
            if name.rsplit("/", 1)[-1] in PARAMETER_SERVICES and types[:1] and types[0].startswith("rcl_interfaces/"):
                parameter_services += 1
                continue
            services.append({"name": name, "types": types,
                             "servers": ends["services"].get(name, []),
                             "clients": ends["clients"].get(name, [])})
        actions = [{"name": name, "types": types,
                    "servers": ends["action_servers"].get(name, []),
                    "clients": ends["action_clients"].get(name, [])}
                   for name, types in self.action.get_action_names_and_types(self.node)
                   if not hidden(name)]
        return {"nodes": nodes, "topics": topics, "services": services, "actions": actions,
                "hidden": {"nodes": hidden_nodes, "topics": hidden_topics,
                           "parameter_services": parameter_services}}

    def publish_graph(self):
        graph = self.snapshot()
        self.graph = graph
        self.poll_controllers(graph)
        graph = {**graph, "controllers": self.controllers}
        text = json.dumps(graph, sort_keys=True)
        if text != self.last_graph:
            self.last_graph = text
            emit({"type": "graph", **graph})

    # ros2_control: every controller_manager's ListControllers, every few seconds.
    def poll_controllers(self, graph):
        managers = [s["name"] for s in graph["services"]
                    if "controller_manager_msgs/srv/ListControllers" in s["types"]]
        if not managers:
            self.controllers = None
            return
        if time.monotonic() < self.next_controllers or self.controller_jobs:
            return
        self.next_controllers = time.monotonic() + CONTROLLERS_EVERY_S
        try:
            from controller_manager_msgs.srv import ListControllers
        except ImportError:
            self.controllers = {"error": "controller_manager_msgs is not in this setup"}
            return
        found = []
        errors = []
        for service in managers:
            client = self.node.create_client(ListControllers, service)
            future = client.call_async(ListControllers.Request())
            self.controller_jobs[service] = (client, future, time.monotonic() + REQUEST_TIMEOUT_S)

        def collect():
            for service, (client, future, deadline) in list(self.controller_jobs.items()):
                if not future.done() and time.monotonic() < deadline:
                    continue
                try:
                    response = future.result() if future.done() else None
                    if response is not None:
                        for c in response.controller:
                            found.append({"name": c.name, "type": getattr(c, "type", ""),
                                          "state": getattr(c, "state", ""),
                                          "manager": service.rsplit("/", 1)[0] or "/"})
                    elif future.done():
                        errors.append(f"{service} did not answer")
                    else:
                        errors.append(f"{service} timed out")
                except Exception as e:
                    errors.append(f"{service}: {str(e) or e.__class__.__name__}")
                finally:
                    self.node.destroy_client(client)
                    del self.controller_jobs[service]
            if not self.controller_jobs:
                self.controllers = {"list": sorted(found, key=lambda c: c["name"])}
                if errors:
                    self.controllers["error"] = "; ".join(errors)
                return True
            return False
        self.jobs.append(Job(None, collect))

    # --- requests

    def handle(self, request):
        rid = request.get("id")
        cmd = request.get("cmd")
        try:
            if cmd == "interface":
                text = interface_text(request["type"])
                emit({"type": "reply", "id": rid, "text": text} if text is not None
                     else {"type": "reply", "id": rid, "error": "Not found in this setup"})
            elif cmd == "topic":
                emit({"type": "reply", "id": rid, **self.topic_detail(request["name"])})
            elif cmd == "node":
                self.node_detail(rid, request["name"])
            elif cmd == "hz":
                self.measure(rid, request["name"])
            elif cmd == "mode":
                active = bool(request.get("active"))
                self.graph_every = GRAPH_EVERY_S if active else IDLE_GRAPH_EVERY_S
                if active:
                    self.next_graph = 0.0
                emit({"type": "reply", "id": rid, "ok": True})
            else:
                emit({"type": "reply", "id": rid, "error": f"unknown request {cmd}"})
        except Exception as e:
            emit({"type": "reply", "id": rid, "error": str(e) or e.__class__.__name__})

    def endpoints(self, topic):
        def rows(infos):
            return [{"node": join_name(i.node_namespace, i.node_name), "type": i.topic_type,
                     **qos_summary(i.qos_profile)} for i in infos
                    if not hidden(join_name(i.node_namespace, i.node_name))]
        return (rows(self.node.get_publishers_info_by_topic(topic)),
                rows(self.node.get_subscriptions_info_by_topic(topic)))

    def topic_detail(self, topic):
        pubs, subs = self.endpoints(topic)
        return {"publishers": pubs, "subscribers": subs}

    def node_detail(self, rid, full):
        ns, name = split_name(full)
        if (name, ns) not in self.node.get_node_names_and_namespaces():
            emit({"type": "reply", "id": rid, "error": "This node is no longer running"})
            return
        info = self.by_node(name, ns)
        qos = {}
        for kind, index in (("publishers", 0), ("subscribers", 1)):
            for topic in info[kind]:
                for end in self.endpoints(topic["name"])[index]:
                    if end["node"] == full:
                        qos[f"{kind}:{topic['name']}"] = {k: end[k] for k in ("reliability", "durability")}
        result = {"qos": qos, "parameters": None, "lifecycle": None}
        waiting = []

        if info["parameter_services"]:
            from rcl_interfaces.srv import GetParameters, ListParameters
            from rclpy.parameter import parameter_value_to_python
            lister = self.node.create_client(ListParameters, f"{full}/list_parameters")
            getter = self.node.create_client(GetParameters, f"{full}/get_parameters")
            state = {"names": None, "values": None, "total": 0}
            listed = lister.call_async(ListParameters.Request())
            waiting.append(lister)
            waiting.append(getter)

            def on_list(future):
                if future.result() is None:
                    return
                all_names = sorted(future.result().result.names)
                state["total"] = len(all_names)
                names = all_names[:MAX_PARAMETERS]
                state["names"] = names
                request = GetParameters.Request()
                request.names = names
                getter.call_async(request).add_done_callback(on_values)

            def on_values(future):
                if future.result() is None:
                    return
                values = []
                for key, value in zip(state["names"], future.result().values):
                    try:
                        values.append({"name": key, "value": parameter_value_to_python(value)})
                    except Exception:
                        values.append({"name": key, "value": None})
                state["values"] = values
            listed.add_done_callback(on_list)
        else:
            state = {"values": []}

        if info["lifecycle"]:
            from lifecycle_msgs.srv import GetState
            getstate = self.node.create_client(GetState, f"{full}/get_state")
            waiting.append(getstate)
            lifecycle = {"label": None}

            def on_state(future):
                if future.result() is not None:
                    lifecycle["label"] = future.result().current_state.label
            getstate.call_async(GetState.Request()).add_done_callback(on_state)
        else:
            lifecycle = {"label": False}

        deadline = time.monotonic() + REQUEST_TIMEOUT_S

        def finish():
            done = state["values"] is not None and lifecycle["label"] is not None
            if not done and time.monotonic() < deadline:
                return False
            result["parameters"] = state["values"]
            result["parameter_total"] = state.get("total", len(state["values"] or []))
            result["parameters_truncated"] = result["parameter_total"] > len(state["values"] or [])
            result["lifecycle"] = lifecycle["label"] or None
            if not done:
                result["timed_out"] = True
            for client in waiting:
                self.node.destroy_client(client)
            emit({"type": "reply", "id": rid, **result})
            return True
        self.jobs.append(Job(rid, finish))

    def measure(self, rid, topic):
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        from rosidl_runtime_py.utilities import get_message
        types = dict(self.node.get_topic_names_and_types()).get(topic)
        if not types:
            emit({"type": "reply", "id": rid, "error": "Nobody publishes it now"})
            return
        try:
            message = get_message(types[0])
        except (AttributeError, ModuleNotFoundError, ValueError):
            emit({"type": "reply", "id": rid,
                  "error": f"{types[0]} is not in this setup; choose the workspace that builds it"})
            return
        # Best effort and volatile match every publisher, reliable and latched ones too.
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=50)
        stamps, sizes = [], []

        def on_message(data):
            stamps.append(time.monotonic())
            sizes.append(len(data))
        sub = self.node.create_subscription(message, topic, on_message, qos, raw=True)
        end = time.monotonic() + HZ_WINDOW_S

        def finish():
            if time.monotonic() < end:
                return False
            self.node.destroy_subscription(sub)
            span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0
            emit({"type": "reply", "id": rid, "count": len(stamps), "window": HZ_WINDOW_S,
                  "hz": (len(stamps) - 1) / span if span > 0 else 0.0,
                  "bytes_per_s": sum(sizes) / HZ_WINDOW_S,
                  "size": sum(sizes) / len(sizes) if sizes else 0})
            return True
        self.jobs.append(Job(rid, finish))

    # --- the loop

    def run(self):
        def read_stdin():
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.requests.put(json.loads(line))
                except ValueError:
                    pass
            self.requests.put(None)
        threading.Thread(target=read_stdin, daemon=True).start()

        emit({"type": "ready", "node": self.node.get_fully_qualified_name()})
        # Discovery takes a moment; the first graph waits for it a little.
        settle = time.monotonic() + 0.6
        while time.monotonic() < settle:
            self.executor.spin_once(timeout_sec=0.05)
        while True:
            self.executor.spin_once(timeout_sec=0.05)
            while True:
                try:
                    request = self.requests.get_nowait()
                except queue.Empty:
                    break
                if request is None:
                    return
                self.handle(request)
            self.jobs = [job for job in self.jobs if not job.step()]
            if time.monotonic() >= self.next_graph:
                self.next_graph = time.monotonic() + self.graph_every
                self.publish_graph()

    def close(self):
        try:
            self.node.destroy_node()
            self.rclpy.try_shutdown()
        except Exception:
            pass


class Job:
    """Work spread over loop turns: `step()` is true once it has replied."""

    def __init__(self, rid, check):
        self.rid = rid
        self.check = check

    def step(self):
        try:
            return self.check()
        except Exception as e:
            if self.rid is not None:
                emit({"type": "reply", "id": self.rid, "error": str(e) or e.__class__.__name__})
            return True


def watch():
    if not os.environ.get(ENV_MARK):
        try:
            env = ros_env()
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            emit({"type": "error", "error": str(e)})
            return 1
        os.execve(sys.executable, [sys.executable, os.path.abspath(__file__), "watch"], env)
    try:
        watcher = Watcher()
    except Exception as e:
        emit({"type": "error", "error": f"ROS 2 did not start: {e}"})
        return 1
    try:
        watcher.run()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.close()
    return 0


def main(argv):
    command = argv[1] if len(argv) > 1 else "status"
    args = argv[2:]
    if command == "watch":
        return watch()
    try:
        if command == "status":
            result = status()
        elif command == "set" and args and len(args) % 2 == 0:
            result = set_values(list(zip(args[::2], args[1::2])))
        elif command == "launch" and args:
            result = launch(args[0], args[1] if len(args) > 1 else None)
        elif command == "stop" and args:
            result = stop(args[0])
        elif command == "terminal":
            result = terminal()
        elif command == "install-gazebo":
            result = install_gazebo()
        else:
            result = {"ok": False, "error": f"usage: {argv[0]} status|set|launch|stop|terminal|watch"}
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        result = {"ok": False, "error": str(e)}
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
