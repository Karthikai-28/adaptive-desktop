#!/usr/bin/env python3
"""ROS 2 for the shell's ROS panel, as JSON.

    ros_info.py status [refresh]       distro, setup, workspaces, tools (loads no ROS); the
                                       file search is cached for five minutes unless `refresh`
    ros_info.py set <key> <value>...   domain | localhost | rmw | workspace | follow_project;
                                       "" follows the shell (`set all ""` for all); several pairs
    ros_info.py launch <tool> [file] [name:=value...]
                                       rviz2 | gazebo | rqt | rqt_graph | demo | launch; file is
                                       a .rviz config, a world or a launch file
    ros_info.py launch-saved <name>    a saved launch (file and arguments)
    ros_info.py save-launch <name> <file> [name:=value...] | forget-launch <name>
    ros_info.py stop <tool>            ask what the panel started of it to quit
    ros_info.py runs                   what the panel started and how the last ones ended
    ros_info.py bag-start --all | <topic>...   bag-play <dir>
    ros_info.py save-setup <name> | use-setup <name> | forget-setup <name>
                                       saved robot setups: domain, discovery, middleware, workspace
    ros_info.py favorite <kind> <name> star or unstar a node, topic, service or action
    ros_info.py open-log <tool>        a terminal following that tool's log
    ros_info.py terminal               a terminal with the same ROS setup as the panel
    ros_info.py install-gazebo         a terminal on the apt command (the password is typed there)
    ros_info.py watch                  the live graph; see below

Whatever the panel starts runs under `ros_info.py run`, a small supervisor in
the same process group that writes how it ended (exit code, or stopped) to
run-history.json, so a launch that crashed can be told from one that was
stopped, and restarted. Every command exits non-zero when its reply has
"ok": false, so the command palette can report it.

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
    {"cmd": "sample", "name": "/chatter"}            the next message (images as a thumbnail)
    {"cmd": "tf"}                                    the TF tree, rates and stale frames
    {"cmd": "health"}                                QoS mismatches across every topic
    {"cmd": "template", "kind": "service", "type": "example_interfaces/srv/AddTwoInts"}
    {"cmd": "set_parameter", "node": ..., "name": ..., "value": "1.5", "ptype": 3}
    {"cmd": "lifecycle", "node": ..., "transition": "configure"}
    {"cmd": "call", "name": ..., "type": ..., "value": "{a: 1}"}       a service
    {"cmd": "goal", "name": ..., "type": ..., "value": "{order: 5}"}   an action
    {"cmd": "publish", "name": ..., "type": ..., "value": "{data: hi}"}  one message
    {"cmd": "controller", "manager": ..., "name": ..., "op": "activate"}
    {"cmd": "mode", "active": false}                 slower graph polling while closed

The graph carries /diagnostics too. Whatever writes to ROS (a parameter, a
transition, a call, a goal, a message, a controller) is only asked for by an
explicit, confirmed click in the panel.

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
HISTORY = CACHE / "run-history.json"
DISCOVERY = CACHE / "discovery.json"
THUMBS = CACHE / "thumbs"
FAVORITES = CONFIG.parent / "ros-favorites.json"
SAVED_LAUNCHES = CONFIG.parent / "ros-launches.json"
SETUPS = CONFIG.parent / "ros-setups.json"
BAGS = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "adaptive-desktop" / "rosbags"
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
# Between full scans only the name lists are compared; a change in them, or
# this long, means asking every node again.
FULL_SCAN_EVERY_S = 5.0
MAX_PARAMETERS = 200
MAX_ARRAY_ITEMS = 64
MAX_ACTIVE_SAMPLES = 3
MAX_ACTIVE_MEASURES = 4
CALL_TIMEOUT_S = 10.0
GOAL_TIMEOUT_S = 30.0
DISCOVERY_TTL_S = 300
DIAGNOSTIC_STALE_S = 15.0
DIAGNOSTIC_DROP_S = 120.0
TF_WINDOW_S = 1.5
TF_STALE_S = 1.0
THUMB_WIDTH = 240
HISTORY_KEEP = 20
TOOLS = ("rviz2", "gazebo", "rqt", "rqt_graph", "demo", "launch", "bag")
LAUNCH_SUFFIXES = (".launch.py", ".launch.xml", ".launch.yaml")
LAUNCH_ARG = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*:=.*$", re.S)
SAVED_NAME = re.compile(r"^[\w][\w .:+-]{0,40}$")


def emit(obj):
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        os._exit(0)


# ------------------------------------------------------------------ setup

def read_json(path, kind=dict):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, kind) else kind()
    except (OSError, ValueError):
        return kind()


def write_json(path, data):
    """Private, and atomic: a reader sees the old file or the new one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def read_config():
    return read_json(CONFIG)


def write_config(data):
    write_json(CONFIG, data)


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


def active_project():
    """(name, path) of Project Context's active project, or None.

    ADAPTIVE_ROS_PROJECT=<path> stands in for it (the checks use that)."""
    forced = os.environ.get("ADAPTIVE_ROS_PROJECT")
    if forced is not None:
        return (Path(forced).name, forced) if forced else None
    if not shutil.which("gdbus"):
        return None
    try:
        out = subprocess.run(
            ["gdbus", "call", "--session", "--timeout", "1", "--dest", "org.adaptive.ProjectContext",
             "--object-path", "/org/adaptive/ProjectContext",
             "--method", "org.adaptive.ProjectContext.GetActiveProject"],
            capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.findall(r"'((?:[^'\\]|\\.)*)'", out)
    if len(found) < 3 or not found[2]:
        return None
    return found[1], found[2]


def project_workspace(path):
    """The colcon workspace a project is, holds (proj/.build/<distro>), or sits in."""
    path = Path(path)
    candidates = [path]
    try:
        candidates += sorted(p for p in (path / ".build").iterdir() if p.is_dir())
    except OSError:
        pass
    candidates += [p for p in path.parents if p != HOME and HOME in p.parents]
    for candidate in candidates:
        if (candidate / "install" / "setup.bash").is_file():
            return str(candidate)
    return None


def settings():
    """The setup the panel uses, and where each part came from."""
    shell = from_shell_files()
    config = read_config()
    if config.get("follow_project") and "workspace" not in config:
        project = active_project()
        workspace = project and project_workspace(project[1])
        if workspace:
            shell["workspace"] = workspace
            shell["workspace_from_project"] = True
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
    if workspace_from == "shell" and shell.get("workspace_from_project"):
        workspace_from = "project"
    return {
        "follow_project": bool(config.get("follow_project")),
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
    if exe == "ros2" and rest[:1] == ["launch"]:
        return "launch"
    if exe == "ros2" and rest[:2] in (["bag", "record"], ["bag", "play"]):
        return "bag"
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


def is_world(path):
    return path.endswith(".world") or (path.endswith(".sdf") and "/worlds/" in path)


def discovered_files(spaces, refresh=False):
    """RViz configs, worlds and launch files: a walk of the home folder and every
    workspace's src, so it is kept for a few minutes (per set of workspaces)."""
    key = sorted(w["path"] for w in spaces)
    cached = read_json(DISCOVERY)
    if (not refresh and cached.get("key") == key
            and 0 <= time.time() - cached.get("at", 0) < DISCOVERY_TTL_S):
        return cached["files"]
    roots = [(HOME / ".rviz2", 0), (HOME, 2)] + [(Path(w["path"]) / "src", 7) for w in spaces]
    files = {
        "rviz_configs": recent_files(roots, lambda p: p.endswith(".rviz")),
        "worlds": recent_files(roots, is_world),
        "launch_files": recent_files([(Path(w["path"]) / "src", 8) for w in spaces],
                                     lambda p: p.endswith(LAUNCH_SUFFIXES), limit=12),
    }
    try:
        write_json(DISCOVERY, {"key": key, "at": time.time(), "files": files})
    except OSError:
        pass
    return files


def status(refresh=False):
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
    tools = {
        "rviz2": (base / "bin" / "rviz2").is_file(),
        "gazebo": flavour is not None,
        "rqt": (base / "bin" / "rqt").is_file(),
        "rqt_graph": (base / "bin" / "rqt_graph").is_file(),
        "demo": (base / "lib" / "demo_nodes_cpp" / "talker").is_file(),
        "launch": (base / "share" / "ros2launch").is_dir(),
        "bag": (base / "share" / "ros2bag").is_dir(),
    }
    spaces = workspaces()
    if setup["workspace"] and all(w["path"] != setup["workspace"] for w in spaces):
        spaces.append({"name": workspace_name(setup["workspace"]), "path": setup["workspace"]})
    project = active_project()
    project_ws = project and project_workspace(project[1])
    if project_ws and all(w["path"] != project_ws for w in spaces):
        spaces.append({"name": workspace_name(project_ws), "path": project_ws})
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
        **discovered_files(spaces, refresh),
        "saved_launches": read_json(SAVED_LAUNCHES, list),
        "setups": read_json(SETUPS, list),
        "project": {"name": project[0], "path": project[1], "workspace": project_ws} if project else None,
        "history": read_json(HISTORY, list)[-8:][::-1],
        "runs": {name: [{"pgid": e["pgid"], "meta": e.get("meta", {}), "started": e.get("started")}
                        for e in entries] for name, entries in owned.items()},
        "recording": recording(owned.get("bag", [])),
        "bags": recent_bags(),
        "bag_dir": str(BAGS),
        "bag_free": free_space(BAGS),
        "favorites": read_json(FAVORITES, list),
    }


def log_file(tool):
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{tool}.log"


def read_runs():
    return read_json(RUNS)


def write_runs(data):
    write_json(RUNS, data)


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


def remember_runs(tool, procs, argv, meta=None):
    with file_lock(RUNS.with_suffix(".lock")):
        data = read_runs()
        entries = [entry for entry in data.get(tool, [])
                   if process_group_exists(entry.get("pgid", 0))]
        entries.extend({"pid": proc.pid, "pgid": proc.pid, "argv": command, "meta": meta or {},
                        "started": time.time()} for proc, command in zip(procs, argv))
        data[tool] = entries
        write_runs(data)


def forget_runs(tool):
    with file_lock(RUNS.with_suffix(".lock")):
        data = read_runs()
        data.pop(tool, None)
        write_runs(data)


def spawn(argv, env, tool, meta=None, cwd=None):
    """Start argv under the supervisor (`run`), in a new process group whose id
    is the supervisor's pid, with its output appended to the tool's log."""
    path = log_file(tool)
    if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
        path.replace(path.with_suffix(".log.1"))
    with open(path, "ab") as log:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {shlex.join(argv)}\n".encode())
        log.flush()
        supervisor = [sys.executable, os.path.abspath(__file__), "run", tool,
                      json.dumps(meta or {}), "--", *argv]
        return subprocess.Popen(supervisor, env=env, cwd=cwd or str(HOME), start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log)


def start(tool, argv, env, meta=None, settle=0.8):
    """Start each command of argv; if one fails at once, stop them all."""
    procs = [spawn(a, env, tool, meta) for a in argv]
    # Something that cannot start says so at once; give it a moment to.
    deadline = time.monotonic() + settle
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
        lines = [line for line in log_file(tool).read_text(errors="replace").strip().splitlines()
                 if not line.startswith("--- ")][-3:]
        return {"ok": False, "error": lines[-1] if lines else "It exited at once", "log": str(log_file(tool))}
    remember_runs(tool, procs, argv, meta)
    return {"ok": True, "pids": [p.pid for p in procs], "log": str(log_file(tool))}


def launch_argv(file, args):
    path = Path(file)
    if not path.is_file() or not path.name.endswith(LAUNCH_SUFFIXES):
        return None, "That is not a ROS 2 launch file"
    bad = [a for a in args if not LAUNCH_ARG.match(a)]
    if bad:
        return None, f"Launch arguments are name:=value, not {bad[0]}"
    return ["ros2", "launch", str(path), *args], None


def launch(tool, file=None, args=(), saved=None):
    setup = settings()
    env = ros_env(setup)
    base = ROS_ROOT / setup["distro"]
    meta = {"file": str(file), "name": Path(file).name} if file else {}
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
    elif tool == "launch" and file:
        command, error = launch_argv(file, list(args))
        if error:
            return {"ok": False, "error": error}
        argv = [command]
        meta = {"file": str(file), "args": list(args), "name": saved or Path(file).name}
    else:
        return {"ok": False, "error": f"unknown tool {tool}"}
    return start(tool, argv, env, meta)


def launch_saved(name):
    for item in read_json(SAVED_LAUNCHES, list):
        if item.get("name") == name:
            return launch("launch", item.get("file"), item.get("args", []), saved=name)
    return {"ok": False, "error": f"No saved launch is called {name}"}


def save_launch(name, file, args):
    if not SAVED_NAME.match(name or ""):
        return {"ok": False, "error": "A name is letters, digits, spaces and .:+- (up to 40)"}
    _, error = launch_argv(file, list(args))
    if error:
        return {"ok": False, "error": error}
    with file_lock(SAVED_LAUNCHES.with_suffix(".lock")):
        items = [item for item in read_json(SAVED_LAUNCHES, list) if item.get("name") != name]
        items.append({"name": name, "file": str(file), "args": list(args)})
        items.sort(key=lambda item: item["name"].lower())
        write_json(SAVED_LAUNCHES, items)
    return {"ok": True, "saved_launches": items}


def forget_launch(name):
    with file_lock(SAVED_LAUNCHES.with_suffix(".lock")):
        items = [item for item in read_json(SAVED_LAUNCHES, list) if item.get("name") != name]
        write_json(SAVED_LAUNCHES, items)
    return {"ok": True, "saved_launches": items}


def supervise(tool, meta_text, argv):
    """`run`: start argv, wait for it, write down how it ended.

    It is the process group's leader, so the panel's Stop (a signal to the whole
    group) reaches it too: a signal it got means the run was stopped, an exit
    without one that it ended by itself. Handlers (not SIG_IGN) keep it alive
    through the signal, and are reset in the child when it execs."""
    stopped = {"by": None}

    def note(signum, _frame):
        stopped["by"] = signal.Signals(signum).name
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, note)
    started = time.time()
    try:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL)
    except OSError as e:
        print(f"{argv[0]}: {e}", flush=True)
        returncode = 127
    else:
        returncode = child.wait()
    try:
        meta = json.loads(meta_text) if meta_text else {}
    except ValueError:
        meta = {}
    entry = {"tool": tool, "argv": argv, "meta": meta, "pgid": os.getpid(),
             "started": started, "ended": time.time(), "returncode": returncode,
             "stopped": stopped["by"], "log": str(log_file(tool)),
             "crashed": returncode not in (0, None) and not stopped["by"]}
    with file_lock(HISTORY.with_suffix(".lock")):
        write_json(HISTORY, (read_json(HISTORY, list) + [entry])[-HISTORY_KEEP:])
    return returncode if returncode >= 0 else 128 - returncode


def runs():
    """What the panel started that still runs, and how the last ones ended."""
    owned = owned_runs()
    return {"ok": True,
            "running": {tool: [{"pgid": e["pgid"], "meta": e.get("meta", {}), "started": e.get("started")}
                               for e in entries] for tool, entries in owned.items()},
            "recording": recording(owned.get("bag", [])),
            "history": read_json(HISTORY, list)[-8:][::-1]}


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


def toggle_favorite(kind, name):
    if kind not in ("node", "topic", "service", "action") or not name.startswith("/"):
        return {"ok": False, "error": "Not a ROS graph item"}
    with file_lock(FAVORITES.with_suffix(".lock")):
        items = read_json(FAVORITES, list)
        target = {"kind": kind, "name": name}
        if target in items:
            items.remove(target)
            active = False
        else:
            items.append(target)
            items.sort(key=lambda item: (item["kind"], item["name"]))
            active = True
        write_json(FAVORITES, items)
    return {"ok": True, "active": active, "favorites": items}


# ------------------------------------------------------------------ bags

def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def free_space(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def bag_summary(path):
    """Duration, message count and topics from a bag's metadata.yaml."""
    info = {"name": path.name, "path": str(path), "size": dir_size(path)}
    try:
        import yaml
        meta = yaml.safe_load((path / "metadata.yaml").read_text())["rosbag2_bagfile_information"]
        info["duration_s"] = meta["duration"]["nanoseconds"] / 1e9
        info["messages"] = meta["message_count"]
        info["topics"] = len(meta.get("topics_with_message_count") or [])
    except Exception:  # Missing, or half written while the recording stops.
        pass
    return info


def recent_bags(limit=6):
    try:
        bags = [path for path in BAGS.iterdir() if path.is_dir() and (path / "metadata.yaml").is_file()]
    except OSError:
        bags = []
    stamped = []
    for path in bags:
        try:
            stamped.append((path.stat().st_mtime, path))
        except OSError:
            pass
    return [bag_summary(path) for _, path in sorted(stamped, reverse=True)[:limit]]


def recording(entries):
    """The bag the panel is recording now, and how big it has grown."""
    for entry in entries:
        output = (entry.get("meta") or {}).get("output")
        if output:
            return {"path": output, "topics": entry["meta"].get("topics"),
                    "size": dir_size(output), "started": entry.get("started")}
    return None


def bag_start(topics):
    every = topics == ["--all"]
    topics = sorted({topic for topic in topics if topic.startswith("/") and not hidden(topic)})
    if not every and not topics:
        return {"ok": False, "error": "Choose at least one visible topic"}
    if len(topics) > 100:
        return {"ok": False, "error": "Recording is limited to 100 topics from the panel"}
    if owned_runs("bag"):
        return {"ok": False, "error": "A bag started here is already running; stop it first"}
    env = ros_env(settings())
    BAGS.mkdir(parents=True, exist_ok=True)
    output = BAGS / time.strftime("%Y%m%d-%H%M%S")
    argv = ["ros2", "bag", "record", "-o", str(output), *(["-a"] if every else topics)]
    result = start("bag", [argv], env, {"output": str(output), "topics": "all" if every else len(topics),
                                         "name": "Recording"})
    return {**result, "path": str(output), "topics": "all" if every else topics}


def bag_play(path):
    bag = Path(path)
    if not bag.is_dir() or not (bag / "metadata.yaml").is_file():
        return {"ok": False, "error": "That is not a ROS 2 bag"}
    if owned_runs("bag"):
        return {"ok": False, "error": "A bag started here is already running; stop it first"}
    env = ros_env(settings())
    result = start("bag", [["ros2", "bag", "play", str(bag)]], env, {"play": str(bag), "name": bag.name})
    return {**result, "path": str(bag)}


# ------------------------------------------------------------------ saved setups

def save_setup(name):
    if not SAVED_NAME.match(name or ""):
        return {"ok": False, "error": "A name is letters, digits, spaces and .:+- (up to 40)"}
    setup = settings()
    item = {"name": name, "domain": setup["domain"], "localhost": setup["localhost"],
            "rmw": setup["rmw"] if setup["rmw_set"] else "", "workspace": setup["workspace"]}
    with file_lock(SETUPS.with_suffix(".lock")):
        items = [i for i in read_json(SETUPS, list) if i.get("name") != name] + [item]
        items.sort(key=lambda i: i["name"].lower())
        write_json(SETUPS, items)
    return {"ok": True, "setups": items}


def forget_setup(name):
    with file_lock(SETUPS.with_suffix(".lock")):
        items = [i for i in read_json(SETUPS, list) if i.get("name") != name]
        write_json(SETUPS, items)
    return {"ok": True, "setups": items}


def use_setup(name):
    item = next((i for i in read_json(SETUPS, list) if i.get("name") == name), None)
    if not item:
        return {"ok": False, "error": f"No saved setup is called {name}"}
    return set_values([("domain", str(item.get("domain", 0))),
                       ("localhost", "1" if item.get("localhost") else "0"),
                       ("rmw", item.get("rmw") or ""),
                       ("workspace", item.get("workspace") or "none")])


def open_log(tool):
    if tool not in TOOLS:
        return {"ok": False, "error": "Unknown ROS tool"}
    path = log_file(tool)
    path.touch(exist_ok=True)
    return open_terminal(f"ROS 2 · {tool} log", ["tail", "-n", "200", "-f", str(path)])


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
            elif key in ("localhost", "follow_project"):
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


# ------------------------------------------------------------------ thumbnails

def png(width, height, rows, channels):
    """A PNG from raw rows (bytes, `channels` 1 or 3 per pixel), no libraries needed."""
    import struct
    import zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    colour = 2 if channels == 3 else 0
    raw = b"".join(b"\0" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def image_thumbnail(message, type_name):
    """Write a small picture of a sensor_msgs Image or CompressedImage to the
    cache; (path, width, height) or (None, reason)."""
    THUMBS.mkdir(parents=True, exist_ok=True)
    for old in sorted(THUMBS.iterdir(), key=lambda p: p.stat().st_mtime)[:-8]:
        old.unlink(missing_ok=True)
    stem = THUMBS / f"{time.time_ns()}"
    if type_name.endswith("CompressedImage"):
        fmt = message.format.lower()
        suffix = ".png" if "png" in fmt else ".jpg" if ("jpeg" in fmt or "jpg" in fmt) else None
        if not suffix:
            return None, f"{message.format or 'This'} compression has no preview"
        path = stem.with_suffix(suffix)
        path.write_bytes(bytes(message.data))
        return str(path), 0, 0
    width, height, step = message.width, message.height, message.step
    layouts = {"rgb8": (3, (0, 1, 2)), "bgr8": (3, (2, 1, 0)), "rgba8": (4, (0, 1, 2)),
               "bgra8": (4, (2, 1, 0)), "mono8": (1, (0,)), "8uc1": (1, (0,)),
               "mono16": (2, (0 if message.is_bigendian else 1,)), "16uc1": (2, (0 if message.is_bigendian else 1,))}
    layout = layouts.get(message.encoding.lower())
    if not layout or not width or not height:
        return None, f"{message.encoding or 'This'} images have no preview"
    size, picks = layout
    every = max(1, -(-width // THUMB_WIDTH))
    data = bytes(message.data)
    out_w = len(range(0, width, every))
    rows = []
    for y in range(0, height, every):
        line = data[y * step:y * step + width * size]
        if len(line) < width * size:  # a short message: keep what is whole
            break
        if len(picks) == 1:
            rows.append(line[picks[0]::size * every][:out_w])
            continue
        row = bytearray(out_w * 3)
        for channel, pick in enumerate(picks):
            row[channel::3] = line[pick::size * every][:out_w]
        rows.append(bytes(row))
    if not rows:
        return None, "The image is empty"
    path = stem.with_suffix(".png")
    path.write_bytes(png(out_w, len(rows), rows, 3 if len(picks) == 3 else 1))
    return str(path), out_w, len(rows)


# ------------------------------------------------------------------ parameters

def coerce_parameter(text, ptype):
    """A ParameterValue of the parameter's own type from what was typed."""
    from rcl_interfaces.msg import ParameterType as T, ParameterValue

    def parse_bool(value):
        word = str(value).strip().lower()
        if word in ("true", "1", "yes", "on"):
            return True
        if word in ("false", "0", "no", "off"):
            return False
        raise ValueError("Expected true or false")

    def parse_list(value):
        items = json.loads(value)
        if not isinstance(items, list):
            raise ValueError("Expected a list like [1, 2, 3]")
        return items

    def number(kind, value):
        try:
            return kind(value)
        except (TypeError, ValueError):
            raise ValueError(f"Expected {'an integer' if kind is int else 'a number'}, not {value}") from None

    text = text.strip()
    value = ParameterValue(type=ptype)
    try:
        if ptype == T.PARAMETER_BOOL:
            value.bool_value = parse_bool(text)
        elif ptype == T.PARAMETER_INTEGER:
            value.integer_value = number(int, text)
        elif ptype == T.PARAMETER_DOUBLE:
            value.double_value = number(float, text)
        elif ptype == T.PARAMETER_STRING:
            quoted = len(text) > 1 and text[0] == text[-1] == '"'
            value.string_value = json.loads(text) if quoted else text
        elif ptype == T.PARAMETER_BYTE_ARRAY:
            value.byte_array_value = [bytes([number(int, i)]) for i in parse_list(text)]
        elif ptype == T.PARAMETER_BOOL_ARRAY:
            value.bool_array_value = [parse_bool(i) for i in parse_list(text)]
        elif ptype == T.PARAMETER_INTEGER_ARRAY:
            value.integer_array_value = [number(int, i) for i in parse_list(text)]
        elif ptype == T.PARAMETER_DOUBLE_ARRAY:
            value.double_array_value = [number(float, i) for i in parse_list(text)]
        elif ptype == T.PARAMETER_STRING_ARRAY:
            value.string_array_value = [str(i) for i in parse_list(text)]
        else:
            from rclpy.parameter import Parameter
            try:
                guess = json.loads(text)
            except ValueError:
                guess = text
            value = Parameter("x", value=guess).to_parameter_msg().value
    except json.JSONDecodeError:
        raise ValueError("Expected a list like [1, 2, 3]") from None
    return value


def parse_fields(text):
    """A message's fields from what was typed: YAML (so JSON too), a mapping."""
    import yaml
    try:
        data = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as e:
        raise ValueError(f"Not YAML: {getattr(e, 'problem', None) or e}") from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Write the fields as a mapping, like {a: 1, b: 2}")
    return data


def message_text(message, limit=4000):
    from rosidl_runtime_py.convert import message_to_ordereddict
    text = json.dumps(message_to_ordereddict(message, truncate_length=MAX_ARRAY_ITEMS), indent=2, default=str)
    return text[:limit], len(text) > limit


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
        # The last full scan: its name lists, and what each node had.
        self.names = None
        self.parts = {}
        self.next_full = 0.0
        self.diagnostics = {}
        self.diagnostics_available = False
        try:
            from diagnostic_msgs.msg import DiagnosticArray
            self.diagnostic_subscription = self.node.create_subscription(
                DiagnosticArray, "/diagnostics", self.on_diagnostics, 10)
        except ImportError:
            self.diagnostic_subscription = None

    # --- /diagnostics

    # Several nodes publish /diagnostics, each with only its own statuses, so
    # they are merged by name. One that stops updating turns stale, and is
    # dropped after a while.
    def on_diagnostics(self, message):
        self.diagnostics_available = True
        now = time.monotonic()
        for status in message.status[:200]:
            key = status.name or status.hardware_id or "Unnamed diagnostic"
            self.diagnostics[key] = {"name": key, "hardware_id": status.hardware_id,
                                     "level": int.from_bytes(status.level, "little")
                                     if isinstance(status.level, bytes) else int(status.level),
                                     "message": status.message[:200], "seen": now}
        if len(self.diagnostics) > 400:
            for key in sorted(self.diagnostics, key=lambda k: self.diagnostics[k]["seen"])[:-400]:
                del self.diagnostics[key]

    def diagnostic_snapshot(self):
        now = time.monotonic()
        items = []
        for key, item in list(self.diagnostics.items()):
            age = now - item["seen"]
            if age > DIAGNOSTIC_DROP_S:
                del self.diagnostics[key]
                continue
            shown = {k: v for k, v in item.items() if k != "seen"}
            if age > DIAGNOSTIC_STALE_S:
                shown.update(level=3, message=f"No update for over {int(DIAGNOSTIC_STALE_S)} s")
            items.append(shown)
        items.sort(key=lambda item: (-item["level"], item["name"]))
        counts = {"ok": 0, "warn": 0, "error": 0, "stale": 0}
        labels = ("ok", "warn", "error", "stale")
        for item in items:
            counts[labels[item["level"]] if 0 <= item["level"] < len(labels) else "error"] += 1
        return {"available": self.diagnostics_available, "counts": counts, "items": items}

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
        node_list = self.node.get_node_names_and_namespaces_with_enclaves()
        topic_list = self.node.get_topic_names_and_types()
        service_list = self.node.get_service_names_and_types()
        # Asking every node for its endpoints is most of the cost. When no name
        # came or went, what each node had is reused for a few seconds.
        names = (sorted(node_list), sorted((t, tuple(ty)) for t, ty in topic_list),
                 sorted((s, tuple(ty)) for s, ty in service_list))
        full_scan = names != self.names or time.monotonic() >= self.next_full
        if full_scan:
            self.names = names
            self.next_full = time.monotonic() + FULL_SCAN_EVERY_S
            self.parts = {}

        nodes, hidden_nodes, counts = [], 0, {}
        ends = {kind: {} for kind in ("publishers", "subscribers", "services", "clients",
                                      "action_servers", "action_clients")}
        for name, ns, enclave in node_list:
            full = join_name(ns, name)
            counts[full] = counts.get(full, 0) + 1
            if counts[full] > 1:
                continue
            if hidden(full):
                hidden_nodes += 1
                continue
            parts = self.parts.get(full)
            if parts is None:
                try:
                    parts = self.by_node(name, ns)
                except Exception:  # The node left between the two calls.
                    continue
                self.parts[full] = parts
            for kind in ends:
                for item in parts[kind]:
                    ends[kind].setdefault(item["name"], []).append(full)
            nodes.append({"name": full, "short": name, "namespace": ns, "enclave": enclave, **parts})
        for node in nodes:
            node["copies"] = counts[node["name"]]
        nodes.sort(key=lambda n: n["name"])

        topics, hidden_topics = [], 0
        for name, types in topic_list:
            publishers = ends["publishers"].get(name, [])
            subscribers = ends["subscribers"].get(name, [])
            # A hidden name, or a topic only hidden nodes use: the panel's own
            # /diagnostics, Hz and preview subscriptions, every node's /rosout.
            if hidden(name) or not (publishers or subscribers):
                hidden_topics += 1
                continue
            topics.append({"name": name, "types": types, "publishers": publishers,
                           "subscribers": subscribers, "system": name in ("/rosout", "/parameter_events")})
        services, parameter_services = [], 0
        for name, types in service_list:
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
                "diagnostics": self.diagnostic_snapshot(),
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
            elif cmd == "sample":
                self.sample(rid, request["name"])
            elif cmd == "tf":
                self.tf_tree(rid)
            elif cmd == "health":
                emit({"type": "reply", "id": rid, **self.health()})
            elif cmd == "template":
                emit({"type": "reply", "id": rid, **self.template(request["kind"], request["type"])})
            elif cmd == "set_parameter":
                self.set_parameter(rid, request["node"], request["name"], request.get("value", ""),
                                   request.get("ptype", 0))
            elif cmd == "lifecycle":
                self.lifecycle_transition(rid, request["node"], request["transition"])
            elif cmd == "call":
                self.call_service(rid, request["name"], request["type"], request.get("value", ""))
            elif cmd == "goal":
                self.send_goal(rid, request["name"], request["type"], request.get("value", ""))
            elif cmd == "publish":
                self.publish_once(rid, request["name"], request["type"], request.get("value", ""))
            elif cmd == "controller":
                self.controller(rid, request["manager"], request["name"], request["op"])
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

    @staticmethod
    def qos_warnings(pubs, subs):
        """Pairs that cannot talk: what a subscriber asks for, no publisher offers."""
        warnings = []
        for pub in pubs:
            for sub in subs:
                if pub["reliability"] == "best effort" and sub["reliability"] == "reliable":
                    warnings.append(f"{pub['node']} is best effort but {sub['node']} requires reliable")
                if pub["durability"] == "volatile" and sub["durability"] == "transient local":
                    warnings.append(f"{pub['node']} is volatile but {sub['node']} requires transient local")
        return sorted(set(warnings))

    def topic_detail(self, topic):
        pubs, subs = self.endpoints(topic)
        return {"publishers": pubs, "subscribers": subs, "qos_warnings": self.qos_warnings(pubs, subs)}

    def health(self):
        """QoS mismatches across every visible topic with both ends."""
        found = []
        for topic in (self.graph.get("topics") or [])[:300]:
            if topic["publishers"] and topic["subscribers"]:
                pubs, subs = self.endpoints(topic["name"])
                found += [{"topic": topic["name"], "warning": w} for w in self.qos_warnings(pubs, subs)]
        return {"qos": found}

    def template(self, kind, type_name):
        """An empty message of the type, as YAML-ready JSON, to start from."""
        from rosidl_runtime_py.utilities import get_action, get_message, get_service
        try:
            if kind == "service":
                message = get_service(type_name).Request()
            elif kind == "action":
                message = get_action(type_name).Goal()
            elif kind == "topic":
                message = get_message(type_name)()
            else:
                return {"error": f"unknown kind {kind}"}
        except (AttributeError, ModuleNotFoundError, ValueError):
            return {"error": f"{type_name} is not in this setup"}
        text, _ = message_text(message)
        return {"text": text}

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

            # Long arrays are cut short (and not editable here): the rest would
            # only cross the pipe to be ellipsized.
            def on_values(future):
                if future.result() is None:
                    return
                values = []
                for key, value in zip(state["names"], future.result().values):
                    try:
                        python = parameter_value_to_python(value)
                    except Exception:
                        python = None
                    item = {"name": key, "value": python, "ptype": value.type}
                    if isinstance(python, (list, tuple, bytes)) and len(python) > MAX_ARRAY_ITEMS:
                        item.update(value=list(python[:MAX_ARRAY_ITEMS]), truncated=len(python))
                    elif isinstance(python, bytes):
                        item["value"] = list(python)
                    values.append(item)
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

    def busy(self, kind, limit):
        return sum(job.kind == kind for job in self.jobs) >= limit

    def message_class(self, topic):
        """(type name, class) of a topic, or (None, the reason)."""
        from rosidl_runtime_py.utilities import get_message
        types = dict(self.node.get_topic_names_and_types()).get(topic)
        if not types:
            return None, "Nobody publishes it now"
        try:
            return types[0], get_message(types[0])
        except (AttributeError, ModuleNotFoundError, ValueError):
            return None, f"{types[0]} is not in this setup; choose the workspace that builds it"

    def measure(self, rid, topic):
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        if self.busy("measure", MAX_ACTIVE_MEASURES):
            emit({"type": "reply", "id": rid, "error": f"{MAX_ACTIVE_MEASURES} topics are being measured already"})
            return
        type_name, message = self.message_class(topic)
        if not type_name:
            emit({"type": "reply", "id": rid, "error": message})
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
        self.jobs.append(Job(rid, finish, "measure"))

    def sample(self, rid, topic):
        """The next message on a topic, its age, and for images a thumbnail."""
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        if self.busy("sample", MAX_ACTIVE_SAMPLES):
            emit({"type": "reply", "id": rid, "error": f"{MAX_ACTIVE_SAMPLES} topic previews are running already"})
            return
        type_name, message_type = self.message_class(topic)
        if not type_name:
            emit({"type": "reply", "id": rid, "error": message_type})
            return
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=1)
        got = {"message": None, "at": 0.0}

        def on_message(message):
            if got["message"] is None:
                got.update(message=message, at=time.time())
        sub = self.node.create_subscription(message_type, topic, on_message, qos)
        deadline = time.monotonic() + HZ_WINDOW_S

        def finish():
            if got["message"] is None and time.monotonic() < deadline:
                return False
            self.node.destroy_subscription(sub)
            message = got["message"]
            if message is None:
                emit({"type": "reply", "id": rid, "error": f"No message arrived in {HZ_WINDOW_S:g} s"})
                return True
            reply = {"type": "reply", "id": rid, "type_name": type_name}
            stamp = getattr(getattr(message, "header", None), "stamp", None)
            if stamp is not None:
                age = got["at"] - (stamp.sec + stamp.nanosec / 1e9)
                # Simulated time (or none set) makes an age meaningless.
                if -1 < age < 3600:
                    reply["age_ms"] = round(age * 1000)
            if type_name in ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage"):
                try:
                    shot = image_thumbnail(message, type_name)
                except (OSError, ValueError, AttributeError) as e:
                    shot = (None, str(e))
                if shot[0]:
                    reply.update(image=shot[0], image_width=shot[1], image_height=shot[2])
                else:
                    reply["image_error"] = shot[1]
                header = getattr(message, "header", None)
                summary = {"frame_id": getattr(header, "frame_id", ""),
                           **{k: getattr(message, k) for k in ("width", "height", "encoding", "format")
                              if hasattr(message, k)}}
                reply["text"], reply["truncated"] = json.dumps(summary, indent=2), False
            else:
                reply["text"], reply["truncated"] = message_text(message, 20000)
            emit(reply)
            return True
        self.jobs.append(Job(rid, finish, "sample"))

    def tf_tree(self, rid):
        """Listen to /tf and /tf_static a moment: every frame's parent, rate and
        age, and what is wrong with the tree (separate trees, stale frames)."""
        try:
            from tf2_msgs.msg import TFMessage
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        except ImportError:
            emit({"type": "reply", "id": rid, "error": "tf2_msgs is not in this setup"})
            return
        if self.busy("tf", 1):
            emit({"type": "reply", "id": rid, "error": "The TF tree is being read already"})
            return
        topic_names = dict(self.node.get_topic_names_and_types())
        wanted = [name for name in ("/tf", "/tf_static") if name in topic_names]
        if not wanted:
            emit({"type": "reply", "id": rid, "error": "No TF topics are being published"})
            return
        frames = {}

        def listener(static):
            def on_message(message):
                now = time.time()
                for transform in message.transforms:
                    child = transform.child_frame_id.lstrip("/")
                    if not child or (child not in frames and len(frames) >= 500):
                        continue
                    frame = frames.setdefault(child, {"parents": set(), "arrivals": [], "static": static})
                    frame["parents"].add(transform.header.frame_id.lstrip("/"))
                    frame["arrivals"].append(now)
                    stamp = transform.header.stamp
                    frame["age"] = now - (stamp.sec + stamp.nanosec / 1e9)
            return on_message
        subscriptions = []
        for name in wanted:
            static = name == "/tf_static"
            qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE if static else ReliabilityPolicy.BEST_EFFORT,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL if static else DurabilityPolicy.VOLATILE,
                             history=HistoryPolicy.KEEP_LAST, depth=100)
            subscriptions.append(self.node.create_subscription(TFMessage, name, listener(static), qos))
        deadline = time.monotonic() + TF_WINDOW_S

        def finish():
            if time.monotonic() < deadline:
                return False
            for sub in subscriptions:
                self.node.destroy_subscription(sub)
            rows, warnings = [], []
            for child, frame in sorted(frames.items()):
                parents = sorted(frame["parents"])
                arrivals = frame["arrivals"]
                span = arrivals[-1] - arrivals[0] if len(arrivals) > 1 else 0
                row = {"child": child, "parent": parents[-1], "static": frame["static"]}
                if not frame["static"]:
                    row["hz"] = round((len(arrivals) - 1) / span, 1) if span > 0 else 0.0
                    age = frame.get("age")
                    if age is not None and -1 < age < 3600:
                        row["age_ms"] = round(age * 1000)
                        if age > TF_STALE_S:
                            warnings.append(f"{child} is {age:.1f} s old")
                if len(parents) > 1:
                    warnings.append(f"{child} has more than one parent: {', '.join(parents)}")
                rows.append(row)
            roots = sorted({row["parent"] for row in rows} - {row["child"] for row in rows})
            if len(roots) > 1:
                warnings.append(f"The frames form {len(roots)} separate trees: {', '.join(roots)}")
            emit({"type": "reply", "id": rid, "frames": rows, "roots": roots, "warnings": warnings,
                  "truncated": len(frames) >= 500})
            return True
        self.jobs.append(Job(rid, finish, "tf"))

    # --- writes: each one is a confirmed click in the panel

    def call(self, rid, client, request, answer, kind, timeout=REQUEST_TIMEOUT_S):
        """Send `request` once the service is there; reply with answer(response)."""
        state = {"future": None}
        deadline = time.monotonic() + timeout
        service = client.srv_name

        def finish():
            try:
                if state["future"] is None:
                    if client.service_is_ready():
                        state["future"] = client.call_async(request)
                        return False
                    if time.monotonic() < deadline:
                        return False
                    emit({"type": "reply", "id": rid, "error": f"{service} is not available"})
                    return True
                future = state["future"]
                if not future.done() and time.monotonic() < deadline:
                    return False
                if not future.done():
                    emit({"type": "reply", "id": rid, "error": f"{service} did not answer in time"})
                else:
                    emit({"type": "reply", "id": rid, **answer(future.result())})
                return True
            except Exception as e:
                emit({"type": "reply", "id": rid, "error": str(e) or e.__class__.__name__})
                return True
        job = Job(rid, finish, kind)
        job.cleanup = lambda: self.node.destroy_client(client)
        self.jobs.append(job)

    def set_parameter(self, rid, node_name, name, value_text, ptype=0):
        from rcl_interfaces.msg import Parameter as ParameterMsg
        from rcl_interfaces.srv import SetParameters
        request = SetParameters.Request()
        request.parameters = [ParameterMsg(name=name, value=coerce_parameter(str(value_text), int(ptype)))]

        def answer(response):
            result = response.results[0] if response.results else None
            if result and result.successful:
                return {"ok": True}
            return {"error": (result.reason if result else "") or "The node turned the value down"}
        self.call(rid, self.node.create_client(SetParameters, f"{node_name}/set_parameters"),
                  request, answer, "parameter")

    def lifecycle_transition(self, rid, node_name, transition):
        from lifecycle_msgs.msg import Transition
        from lifecycle_msgs.srv import ChangeState
        ids = {
            "configure": Transition.TRANSITION_CONFIGURE,
            "cleanup": Transition.TRANSITION_CLEANUP,
            "activate": Transition.TRANSITION_ACTIVATE,
            "deactivate": Transition.TRANSITION_DEACTIVATE,
            "shutdown": Transition.TRANSITION_UNCONFIGURED_SHUTDOWN,
        }
        if transition not in ids:
            emit({"type": "reply", "id": rid, "error": "Unknown lifecycle transition"})
            return
        request = ChangeState.Request()
        request.transition.id = ids[transition]
        self.call(rid, self.node.create_client(ChangeState, f"{node_name}/change_state"), request,
                  lambda response: {"ok": True} if response.success
                  else {"error": f"{node_name} turned down {transition}"}, "lifecycle")

    def call_service(self, rid, name, type_name, text):
        from rosidl_runtime_py.set_message import set_message_fields
        from rosidl_runtime_py.utilities import get_service
        try:
            service = get_service(type_name)
        except (AttributeError, ModuleNotFoundError, ValueError):
            emit({"type": "reply", "id": rid, "error": f"{type_name} is not in this setup"})
            return
        request = service.Request()
        set_message_fields(request, parse_fields(text))

        def answer(response):
            text, truncated = message_text(response)
            return {"ok": True, "text": text, "truncated": truncated}
        self.call(rid, self.node.create_client(service, name), request, answer, "call", CALL_TIMEOUT_S)

    def send_goal(self, rid, name, type_name, text):
        """Send a goal and wait for its result; a goal still running when the
        time is up is cancelled, so nothing is left behind."""
        from rclpy.action import ActionClient
        from rosidl_runtime_py.set_message import set_message_fields
        from rosidl_runtime_py.utilities import get_action
        try:
            action = get_action(type_name)
        except (AttributeError, ModuleNotFoundError, ValueError):
            emit({"type": "reply", "id": rid, "error": f"{type_name} is not in this setup"})
            return
        goal = action.Goal()
        set_message_fields(goal, parse_fields(text))
        client = ActionClient(self.node, action, name)
        state = {"sent": None, "result": None, "feedback": 0}
        deadline = time.monotonic() + GOAL_TIMEOUT_S
        statuses = {1: "accepted", 2: "executing", 3: "canceling", 4: "succeeded", 5: "canceled", 6: "aborted"}

        def on_feedback(_message):
            state["feedback"] += 1

        def finish():
            now = time.monotonic()
            if state["sent"] is None:
                if client.server_is_ready():
                    state["sent"] = client.send_goal_async(goal, feedback_callback=on_feedback)
                    return False
                if now < deadline:
                    return False
                emit({"type": "reply", "id": rid, "error": f"No server for {name}"})
                return True
            sent = state["sent"]
            if not sent.done():
                if now < deadline:
                    return False
                emit({"type": "reply", "id": rid, "error": f"{name} did not take the goal in time"})
                return True
            handle = sent.result()
            if not handle.accepted:
                emit({"type": "reply", "id": rid, "error": f"{name} turned the goal down"})
                return True
            if state["result"] is None:
                state["result"] = handle.get_result_async()
            if not state["result"].done():
                if now < deadline:
                    return False
                handle.cancel_goal_async()
                emit({"type": "reply", "id": rid,
                      "error": f"No result in {GOAL_TIMEOUT_S:g} s; the goal was cancelled"})
                return True
            outcome = state["result"].result()
            text, truncated = message_text(outcome.result)
            emit({"type": "reply", "id": rid, "ok": True, "status": statuses.get(outcome.status, "unknown"),
                  "feedback": state["feedback"], "text": text, "truncated": truncated})
            return True
        job = Job(rid, finish, "goal")
        job.cleanup = client.destroy
        self.jobs.append(job)

    def publish_once(self, rid, topic, type_name, text):
        """One message, once a subscriber is there to get it (up to a second)."""
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        from rosidl_runtime_py.set_message import set_message_fields
        from rosidl_runtime_py.utilities import get_message
        try:
            message_type = get_message(type_name)
        except (AttributeError, ModuleNotFoundError, ValueError):
            emit({"type": "reply", "id": rid, "error": f"{type_name} is not in this setup"})
            return
        message = message_type()
        set_message_fields(message, parse_fields(text))
        # Reliable and volatile reach reliable and best-effort subscribers alike.
        qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=1)
        publisher = self.node.create_publisher(message_type, topic, qos)
        state = {"sent": None}
        deadline = time.monotonic() + 1.0

        def finish():
            now = time.monotonic()
            if state["sent"] is None:
                if publisher.get_subscription_count() == 0 and now < deadline:
                    return False
                publisher.publish(message)
                state["sent"] = now
                return False
            # A moment for a reliable delivery before the publisher goes.
            if now < state["sent"] + 0.3:
                return False
            emit({"type": "reply", "id": rid, "ok": True, "subscribers": publisher.get_subscription_count()})
            return True
        job = Job(rid, finish, "publish")
        job.cleanup = lambda: self.node.destroy_publisher(publisher)
        self.jobs.append(job)

    def controller(self, rid, manager, name, op):
        """ros2_control: configure, activate or deactivate one controller."""
        if op == "configure":
            try:
                from controller_manager_msgs.srv import ConfigureController as Configure
            except ImportError:
                emit({"type": "reply", "id": rid, "error": "controller_manager_msgs is not in this setup"})
                return
            request = Configure.Request(name=name)
            self.call(rid, self.node.create_client(Configure, f"{manager}/configure_controller"), request,
                      lambda r: {"ok": True} if r.ok else {"error": f"{name} did not configure"}, "controller")
            return
        if op not in ("activate", "deactivate"):
            emit({"type": "reply", "id": rid, "error": f"unknown controller operation {op}"})
            return
        try:
            from controller_manager_msgs.srv import SwitchController
        except ImportError:
            emit({"type": "reply", "id": rid, "error": "controller_manager_msgs is not in this setup"})
            return
        request = SwitchController.Request()
        # Humble names them activate/deactivate; older releases start/stop.
        on, off = (("activate_controllers", "deactivate_controllers")
                   if hasattr(request, "activate_controllers") else ("start_controllers", "stop_controllers"))
        setattr(request, on if op == "activate" else off, [name])
        request.strictness = SwitchController.Request.STRICT
        if hasattr(request, "timeout"):
            request.timeout.sec = int(REQUEST_TIMEOUT_S)
        self.call(rid, self.node.create_client(SwitchController, f"{manager}/switch_controller"), request,
                  lambda r: {"ok": True} if r.ok else {"error": f"{name} did not {op}"}, "controller")

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

    def __init__(self, rid, check, kind="other"):
        self.rid = rid
        self.check = check
        self.kind = kind
        # Run once the job is over, however it ended (a client to destroy).
        self.cleanup = None

    def step(self):
        try:
            done = self.check()
        except Exception as e:
            if self.rid is not None:
                emit({"type": "reply", "id": self.rid, "error": str(e) or e.__class__.__name__})
            done = True
        if done and self.cleanup:
            try:
                self.cleanup()
            except Exception:
                pass
        return done


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
    if command == "run" and len(args) >= 4 and args[2] == "--":
        return supervise(args[0], args[1], args[3:])
    try:
        if command == "status":
            result = status(refresh=args[:1] == ["refresh"])
        elif command == "set" and args and len(args) % 2 == 0:
            result = set_values(list(zip(args[::2], args[1::2])))
        elif command == "launch" and args:
            result = launch(args[0], args[1] if len(args) > 1 else None, args[2:])
        elif command == "launch-saved" and len(args) == 1:
            result = launch_saved(args[0])
        elif command == "save-launch" and len(args) >= 2:
            result = save_launch(args[0], args[1], args[2:])
        elif command == "forget-launch" and len(args) == 1:
            result = forget_launch(args[0])
        elif command == "stop" and args:
            result = stop(args[0])
        elif command == "runs":
            result = runs()
        elif command == "terminal":
            result = terminal()
        elif command == "install-gazebo":
            result = install_gazebo()
        elif command == "favorite" and len(args) == 2:
            result = toggle_favorite(args[0], args[1])
        elif command == "bag-start" and args:
            result = bag_start(args)
        elif command == "bag-play" and len(args) == 1:
            result = bag_play(args[0])
        elif command == "save-setup" and len(args) == 1:
            result = save_setup(args[0])
        elif command == "use-setup" and len(args) == 1:
            result = use_setup(args[0])
        elif command == "forget-setup" and len(args) == 1:
            result = forget_setup(args[0])
        elif command == "open-log" and len(args) == 1:
            result = open_log(args[0])
        else:
            result = {"ok": False, "error": f"usage: see the top of {argv[0]}"}
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        result = {"ok": False, "error": str(e)}
    except Exception as e:  # The shell reads stdout as JSON, whatever happened.
        result = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    emit(result)
    return 1 if result.get("ok") is False else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
