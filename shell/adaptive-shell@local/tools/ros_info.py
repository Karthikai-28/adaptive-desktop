#!/usr/bin/env python3
"""ROS 2 for the shell's ROS panel, as JSON.

    ros_info.py status [refresh]       distro, setup, workspaces, tools (loads no ROS); the
                                       file search is cached for five minutes unless `refresh`
    ros_info.py set <key> <value>...   domain | localhost | rmw | workspace | follow_project;
                                       "" follows the shell (`set all ""` for all); several pairs
    ros_info.py launch <tool> [file] [name:=value...]
                                       rviz2 | gazebo | rqt | rqt_graph | demo | launch | node; file is
                                       a .rviz config, world, launch file or workspace executable
    ros_info.py launch-saved <name>    a saved launch (file and arguments)
    ros_info.py save-launch <name> <file> [name:=value...] | forget-launch <name>
    ros_info.py stop <tool>            ask what the panel started of it to quit
    ros_info.py runs                   what the panel started and how the last ones ended
    ros_info.py launch-args <file>     the arguments a launch file declares, for the form
    ros_info.py build [--up-to] [package...]   colcon build of the workspace (as it was built
                                       last), or of packages (--up-to: with their dependencies)
    ros_info.py log-tail <tool> [text] [all|warning|error]   a run's log, filtered
    ros_info.py run-control <tool> pause|resume   build | launch | node
    ros_info.py plot </topic/field>    rqt_plot on one numeric field
    ros_info.py plotjuggler <topic>...  PlotJuggler subscribed to exactly these topics
    ros_info.py bag-start --all | <topic>...   bag-play <bag> [rate] [loop] [clock] [start=SECONDS]
                                       <bag>: a bag folder, its metadata.yaml, a .db3 or an .mcap
    ros_info.py bag-info <bag> [remember]   length, topics, and which will not play (types not
                                       installed); remember lists it with the panel's bags
    ros_info.py bag-choose | bag-forget <bag>   a file chooser for a bag; drop an opened one
    ros_info.py bag-control pause|resume   the bag started here (playback; recording from Iron)
    ros_info.py save-setup <name> | use-setup <name> | forget-setup <name>
                                       saved robot setups: domain, discovery, middleware, workspace
    ros_info.py save-robot-profile <name> [package] | use-robot-profile <name> | forget-robot-profile <name>
                                       a setup plus package, favourites and saved launches
    ros_info.py parameter-profile save|diff|apply <node> <name>
                                       a node's parameters kept, compared, loaded back
    ros_info.py favorite <kind> <name> star or unstar a node, topic, service or action
    ros_info.py open-log <tool>        a terminal following that tool's log
    ros_info.py pkg-catalog            templates, dependencies (installed or not) and defaults
                                       for the New package dialog
    ros_info.py pkg-create <json>      a new package in ~/ros2_ws/src from a template: {"name",
                                       "template", "location", "dependencies", "node_name", ...,
                                       "build": true, "use_workspace": true}
    ros_info.py pkg-install-deps <path>   a terminal on rosdep install for that package
    ros_info.py say <command> [args]   any of these, answering with a sentence (the palette)
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

    {"id": 1, "cmd": "node", "name": "/ns/talker"}   parameter names, lifecycle state, QoS
    {"id": 2, "cmd": "topic", "name": "/chatter"}    every endpoint with its QoS
    {"id": 3, "cmd": "interface", "type": "std_msgs/msg/String"}
    {"id": 4, "cmd": "hz", "name": "/chatter"}       rate and bandwidth over two seconds
    {"cmd": "sample", "name": "/chatter"}            the next message (images as a thumbnail)
    {"cmd": "tf"}                                    the TF tree, rates and stale frames
    {"cmd": "tf_lookup", "source": ..., "target": ...}  one transform, its age and RPY
    {"cmd": "plot", "name": "/odom", "field": "pose/pose/position/x"}
                                                     progress lines of new values until cancelled
    {"cmd": "health"}                                QoS mismatches across every topic
    {"cmd": "template", "kind": "service", "type": "example_interfaces/srv/AddTwoInts"}
    {"cmd": "parameter", "node": ..., "name": ...}     fetch one typed value
    {"cmd": "cancel", "ids": [4]}                      cancel pending Hz/Preview/plot requests
    {"cmd": "set_parameter", "node": ..., "name": ..., "value": "1.5", "ptype": 3}
    {"cmd": "lifecycle", "node": ..., "transition": "configure"}
    {"cmd": "lifecycle_group", "nodes": [...], "transition": "activate"}   each node's outcome
    {"cmd": "call", "name": ..., "type": ..., "value": "{a: 1}"}       a service
    {"cmd": "goal", "name": ..., "type": ..., "value": "{order: 5}"}   an action; feedback
                                                     comes as progress lines
    {"cmd": "cancel_goal", "goal_id": n}             cancel the goal request n sent
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
ROBOT_PROFILES = CONFIG.parent / "ros-robot-profiles.json"
PARAMETER_PROFILES = CONFIG.parent / "ros-parameter-profiles"
BAGS = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "adaptive-desktop" / "rosbags"
OPENED_BAGS = CONFIG.parent / "ros-bags.json"
BAG_FILES = {".db3": "sqlite3", ".mcap": "mcap"}
# PlotJuggler's own settings (QSettings): its streamer and the topics it preselects
PLOTJUGGLER_SETTINGS = (Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "PlotJuggler" /
                        "io.plotjuggler.PlotJuggler.ini")
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
# colcon build options that end a --cmake-args list.
COLCON_OPTIONS = {"--base-paths", "--build-base", "--install-base", "--log-base", "--symlink-install",
                  "--merge-install", "--event-handlers", "--parallel-workers", "--executor",
                  "--continue-on-error", "--mixin", "--ament-cmake-args", "--catkin-cmake-args",
                  "--cmake-target", "--cmake-clean-cache", "--cmake-clean-first", "--cmake-force-configure"}
SKIP_DIRS = {"build", "install", "log", "node_modules", "snap", "venv", ".venv", "__pycache__"}
HZ_WINDOW_S = 2.0
REQUEST_TIMEOUT_S = 3.0
GRAPH_EVERY_S = 1.0
CONTROLLERS_EVERY_S = 3.0
IDLE_GRAPH_EVERY_S = 10.0
# Between full scans only the name lists are compared; a change in them, or
# this long, means asking every node again.
FULL_SCAN_EVERY_S = 5.0
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
PLOT_EVERY_S = 0.25
PLOT_MAX_S = 600.0
PLOT_KEEP = 200
TOOLS = ("rviz2", "gazebo", "rqt", "rqt_graph", "demo", "launch", "bag", "node", "build", "plot", "plotjuggler")
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


def has_packages(src, depth=4):
    """A package.xml somewhere in the first few levels under src."""
    if not src.is_dir():
        return False
    for directory, dirs, files in os.walk(src):
        if "package.xml" in files:
            return True
        if Path(directory).relative_to(src).parts.__len__() >= depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
    return False


def is_workspace(path):
    """Built (install/setup.bash) or not yet (packages under src/)."""
    path = Path(path)
    return (path / "install" / "setup.bash").is_file() or has_packages(path / "src")


def workspaces():
    """colcon workspaces in the home folder, built or not, two levels deep."""
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
            if is_workspace(path):
                found.append({"name": str(path.relative_to(HOME)), "path": str(path)})
                found += build_trees(path)
    return found


def build_trees(workspace):
    """Projects in a workspace that build into their own tree, like
    src/<project>/.build/<distro>, each a workspace of its own."""
    trees = []
    for setup in sorted(Path(workspace).glob("src/*/.build/*/install/setup.bash")):
        tree = setup.parent.parent
        trees.append({"name": workspace_name(str(tree)), "path": str(tree)})
    return trees


def workspace_layout(workspace):
    """Where a workspace's packages are and how colcon built it last. A build
    tree like proj/.build/humble keeps its sources elsewhere, which only its
    last colcon command line (log/latest_build/logger_all.log) says; without
    one the sources are src/ and colcon's defaults apply."""
    import ast
    root = Path(workspace)
    layout = {"sources": [root / "src"], "log_base": root / "log", "options": []}
    try:
        with open(root / "log" / "latest_build" / "logger_all.log", errors="replace") as log:
            line = next((l for l in (log.readline() for _ in range(8)) if "Command line arguments:" in l), "")
        argv = ast.literal_eval(line.split("Command line arguments:", 1)[1].strip())
    except (OSError, IndexError, SyntaxError, ValueError):
        return layout
    values, sources, i = {}, [], 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("--log-base", "--build-base", "--install-base") and i + 1 < len(argv):
            values[arg] = str((root / argv[i + 1]).resolve())
            i += 2
            continue
        if arg == "--base-paths":
            i += 1
            while i < len(argv) and not argv[i].startswith("-"):
                sources.append((root / argv[i]).resolve())
                i += 1
            continue
        if arg in ("--symlink-install", "--merge-install"):
            values[arg] = None
        elif arg == "--cmake-args":
            # Its values may start with "-" too; they run to the next colcon option.
            i += 1
            cmake = []
            while i < len(argv) and argv[i] not in COLCON_OPTIONS and not argv[i].startswith("--packages"):
                cmake.append(argv[i])
                i += 1
            values[arg] = cmake
            continue
        i += 1
    # Only a command line that built this very install tree describes it.
    if values.get("--install-base", str(root / "install")) != str(root / "install"):
        return layout
    if sources:
        layout["sources"] = sources
    layout["log_base"] = Path(values.get("--log-base", root / "log"))
    layout["options"] = [part for key, value in values.items() if key != "--log-base"
                         for part in ((key,) if value is None else (key, *value) if isinstance(value, list)
                                      else (key, value))]
    if sources:
        layout["options"] += ["--base-paths", *map(str, sources)]
    return layout


def workspace_packages(workspace):
    """Source packages plus installed executables; package names come from manifests."""
    import xml.etree.ElementTree as ET
    if not workspace:
        return []
    root = Path(workspace)
    found = []
    walks = (walk for source in workspace_layout(workspace)["sources"] for walk in os.walk(source))
    for directory, dirs, files in walks:
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        if "COLCON_IGNORE" in files or "AMENT_IGNORE" in files:
            dirs[:] = []
            continue
        if "package.xml" not in files:
            continue
        try:
            name = ET.parse(Path(directory) / "package.xml").getroot().findtext("name", "").strip()
        except (OSError, ET.ParseError):
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or any(f["name"] == name for f in found):
            continue
        executables = set()
        for lib in (root / "install" / name / "lib" / name, root / "install" / "lib" / name):
            if lib.is_dir():
                executables.update(str(f) for f in lib.iterdir() if f.is_file() and os.access(f, os.X_OK))
        built = (root / "install" / name).is_dir() or (root / "install" / "share" / name).is_dir()
        found.append({"name": name, "path": directory, "built": built,
                      "executables": [{"name": Path(f).name, "path": f} for f in sorted(executables)]})
        dirs[:] = []
    return sorted(found, key=lambda item: item["name"])


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
    if workspace and not is_workspace(workspace):
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
    if exe == "plotjuggler" or (exe == "ros2" and rest[:2] == ["run", "plotjuggler"]):
        return "plotjuggler"
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
    key = ["workspace-files-v4", *sorted(w["path"] for w in spaces)]
    cached = read_json(DISCOVERY)
    if (not refresh and cached.get("key") == key
            and 0 <= time.time() - cached.get("at", 0) < DISCOVERY_TTL_S):
        return cached["files"]
    roots = [(HOME / ".rviz2", 0), (HOME, 2)] + [(Path(w["path"]) / "src", 7) for w in spaces]
    files = {
        "rviz_configs": recent_files(roots, lambda p: p.endswith(".rviz")),
        "worlds": recent_files(roots, is_world),
        "launch_files": recent_files([(Path(w["path"]) / "src", 8) for w in spaces],
                                     lambda p: p.endswith(LAUNCH_SUFFIXES), limit=None),
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
        "build": shutil.which("colcon") is not None,
        "plot": (base / "lib" / "rqt_plot" / "rqt_plot").is_file() or shutil.which("rqt_plot") is not None,
        "plotjuggler": (base / "lib" / "plotjuggler" / "plotjuggler").is_file(),
    }
    spaces = workspaces()
    if setup["workspace"] and all(w["path"] != setup["workspace"] for w in spaces):
        spaces.append({"name": workspace_name(setup["workspace"]), "path": setup["workspace"]})
    packages = workspace_packages(setup["workspace"])
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
        "packages": packages,
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
        **discovered_files([w for w in spaces if w["path"] == setup["workspace"]], refresh),
        "saved_launches": read_json(SAVED_LAUNCHES, list),
        "setups": read_json(SETUPS, list),
        "project": {"name": project[0], "path": project[1], "workspace": project_ws} if project else None,
        "history": read_json(HISTORY, list)[-8:][::-1],
        "runs": {name: [{"pgid": e["pgid"], "meta": e.get("meta", {}), "started": e.get("started"),
                         "paused": bool(e.get("paused"))}
                        for e in entries] for name, entries in owned.items()},
        "recording": recording(owned.get("bag", [])),
        "bags": recent_bags(found_bags()),
        "bag_dir": str(BAGS),
        "bag_free": free_space(BAGS),
        "favorites": read_json(FAVORITES, list),
        "robot_profiles": read_json(ROBOT_PROFILES, list),
        "parameter_profiles": parameter_profiles(),
        "environment": environment_health(setup, packages),
        "build": build_progress() if owned.get("build") else {},
        "bag_recording_pauses": bag_pausable(distro, []),
    }


def environment_health(setup, packages):
    """What would make a build or a launch fail, said before it does. (Nodes on
    another domain are the "elsewhere" row's business.)"""
    issues = []
    if setup.get("rmw_set") and setup.get("rmw") not in middlewares(setup.get("distro")):
        issues.append({"level": "error", "text": f"{setup.get('rmw')} is not installed for {setup.get('distro')}"})
    if not setup.get("workspace"):
        return issues
    workspace = Path(setup["workspace"])
    layout = workspace_layout(workspace)
    if not any(source.is_dir() for source in layout["sources"]):
        issues.append({"level": "warning", "text": "The workspace has no src folder, so it cannot be built here"})
        return issues
    if shutil.which("colcon") is None:
        issues.append({"level": "warning", "text": "colcon is not installed: sudo apt install python3-colcon-common-extensions"})
    unbuilt = [p["name"] for p in packages if not (workspace / "install" / p["name"]).is_dir()]
    if unbuilt:
        issues.append({"level": "warning", "text": f"Not built yet: {', '.join(unbuilt[:4])}"
                                                   f"{f' and {len(unbuilt) - 4} more' if len(unbuilt) > 4 else ''}"})
    # colcon's events.log ends each package with "JobEnded: {..., 'rc': n}".
    latest = layout["log_base"] / "latest_build"
    try:
        events = (latest / "events.log").read_text(errors="replace")
        built_at = latest.resolve().stat().st_mtime
    except OSError:
        events, built_at = "", None
    failed = re.findall(r"JobEnded: \{'identifier': '([^']+)', 'rc': [1-9]", events)
    if failed:
        issues.append({"level": "error", "text": f"The last build failed for {', '.join(failed[:4])}"})
    if built_at is not None:
        newer = next((p["name"] for p in packages if newest_source(Path(p["path"])) > built_at), None)
        if newer:
            issues.append({"level": "info", "text": f"{newer} changed since the last build"})
    return issues


def newest_source(root, limit=400):
    """The newest modification time among a package's first `limit` files."""
    newest = 0.0
    seen = 0
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for name in files:
            try:
                newest = max(newest, os.stat(os.path.join(directory, name)).st_mtime)
            except OSError:
                pass
            seen += 1
            if seen >= limit:
                return newest
    return newest


def parameter_profiles():
    try:
        files = sorted(PARAMETER_PROFILES.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        files = []
    profiles = []
    for path in files[:40]:
        name, _, node = path.stem.partition("--")
        profiles.append({"name": name, "node": "/" + node.replace("__", "/") if node else "", "path": str(path)})
    return profiles


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


def start(tool, argv, env, meta=None, settle=0.8, cwd=None):
    """Start each command of argv; if one fails at once, stop them all."""
    procs = [spawn(a, env, tool, meta, cwd) for a in argv]
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
    elif tool == "node" and file:
        allowed = {e["path"] for p in workspace_packages(setup["workspace"]) for e in p["executables"]}
        if file not in allowed:
            return {"ok": False, "error": "Choose an installed executable from this workspace"}
        argv = [[file]]
        meta = {"file": file, "name": Path(file).name}
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


SHOW_ARG = re.compile(r"^    '(?P<name>[^']+)':$")
SHOW_DEFAULT = re.compile(r"^\s+\(default: (?P<value>.*)\)$")
SHOW_CHOICES = re.compile(r"\.? ?Valid choices are: (?P<list>\[.*\])$")


def parse_show_args(text):
    """`ros2 launch <file> --show-args`: each argument is "    'name':", then its
    description (which may run over several lines) and "(default: 'x')" when
    it has one. An argument without a default must be given."""
    import ast
    arguments = []
    current = None
    for raw in text.splitlines():
        match = SHOW_ARG.match(raw)
        if match:
            current = {"name": match["name"], "default": "", "description": "", "required": True, "choices": []}
            arguments.append(current)
            continue
        if current is None or not raw.strip():
            continue
        match = SHOW_DEFAULT.match(raw)
        if match:
            value = match["value"]
            try:
                value = str(ast.literal_eval(value))
            except (SyntaxError, ValueError):
                pass
            current.update(default=value, required=False)
            continue
        line = raw.strip()
        match = SHOW_CHOICES.search(line)
        if match:
            try:
                current["choices"] = [str(c) for c in ast.literal_eval(match["list"])]
                line = line[:match.start()]
            except (SyntaxError, ValueError):
                pass
        current["description"] = f"{current['description']} {line}".strip()
    return arguments


def launch_arguments(file):
    """The arguments a launch file declares, for the launch form."""
    command, error = launch_argv(file, [])
    if error:
        return {"ok": False, "error": error}
    try:
        proc = subprocess.run([*command, "--show-args"], env=ros_env(settings()), capture_output=True,
                              text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "The launch file took too long to load"}
    if proc.returncode:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        return {"ok": False, "error": lines[-1] if lines else f"ros2 launch exited with {proc.returncode}"}
    return {"ok": True, "arguments": parse_show_args(proc.stdout)}


def workspace_build(packages=(), up_to=False, workspace=None):
    """colcon build of the workspace (or the chosen packages, and with `up_to`
    what they depend on), the way it was built last, in the distro's
    environment without the overlay itself. `workspace` builds another one
    than the panel's (a package just made in ~/ros2_ws)."""
    setup = settings()
    if not (workspace or setup.get("workspace")):
        return {"ok": False, "error": "Choose a workspace first"}
    workspace = Path(workspace or setup["workspace"])
    layout = workspace_layout(workspace)
    if not any(source.is_dir() for source in layout["sources"]):
        return {"ok": False, "error": "The workspace has no src folder to build"}
    if shutil.which("colcon") is None:
        return {"ok": False, "error": "colcon is not installed"}
    if owned_runs("build"):
        return {"ok": False, "error": "A build started here is already running"}
    known = {p["name"] for p in workspace_packages(str(workspace))}
    chosen = sorted(set(packages))
    unknown = [name for name in chosen if name not in known]
    if unknown:
        return {"ok": False, "error": f"{unknown[0]} is not a package in this workspace"}
    argv = ["colcon", "--log-base", str(layout["log_base"]), "build", *layout["options"],
            "--event-handlers", "console_cohesion+"]
    if chosen:
        argv += ["--packages-up-to" if up_to else "--packages-select", *chosen]
    log_file("build").write_text("")
    meta = {"name": "Build " + (", ".join(chosen) if chosen else workspace_name(str(workspace))),
            "workspace": str(workspace), "packages": chosen, "up_to": bool(up_to and chosen)}
    return start("build", [argv], ros_env({**setup, "workspace": ""}), meta, cwd=str(workspace))


def build_progress():
    """How far the build started here is, from its console_cohesion output:
    which packages finished, which failed, and the last line."""
    try:
        lines = log_file("build").read_text(errors="replace").splitlines()
    except OSError:
        return {}
    finished = [m[1] for line in lines for m in [re.match(r"^Finished <<< (\S+)", line)] if m]
    failed = [m[1] for line in lines for m in [re.match(r"^Failed\s+<<< (\S+)", line)] if m]
    started = [m[1] for line in lines for m in [re.match(r"^Starting >>> (\S+)", line)] if m]
    last = next((line for line in reversed(lines) if line.strip() and not line.startswith("--- ")), "")
    return {"finished": finished, "failed": failed, "started": started, "last": last[:200]}


def log_tail(tool, query="", severity="all", limit=120):
    if tool not in TOOLS:
        return {"ok": False, "error": "Unknown ROS tool"}
    try:
        lines = log_file(tool).read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    query = query.lower().strip()
    levels = {"error": ("error", "fatal", "traceback", "exception"),
              "warning": ("warn", "error", "fatal", "traceback", "exception")}
    needles = levels.get(severity, ())
    lines = [line for line in lines if (not query or query in line.lower()) and
             (not needles or any(word in line.lower() for word in needles))]
    try:
        limit = max(1, min(int(limit), 500))
    except ValueError:
        limit = 120
    return {"ok": True, "text": "\n".join(lines[-limit:]), "lines": len(lines)}


def mark_paused(tool, paused):
    with file_lock(RUNS.with_suffix(".lock")):
        data = read_runs()
        for entry in data.get(tool, []):
            entry["paused"] = paused
        write_runs(data)


def control_run(tool, operation):
    """Pause or resume a tool's process groups (SIGSTOP / SIGCONT). Not for
    bag playback, whose clock would jump on resume: see bag_control."""
    if tool not in ("build", "launch", "node") or operation not in ("pause", "resume"):
        return {"ok": False, "error": "Only builds, launches and nodes pause"}
    entries = owned_runs(tool)
    if not entries:
        return {"ok": False, "error": "Nothing started here is running"}
    sig = signal.SIGSTOP if operation == "pause" else signal.SIGCONT
    for entry in entries:
        try:
            os.killpg(int(entry["pgid"]), sig)
        except OSError:
            pass
    mark_paused(tool, operation == "pause")
    return {"ok": True, "count": len(entries), "paused": operation == "pause"}


def plot_topic(expression):
    """rqt_plot on one numeric field: the larger, separate plot window."""
    if not re.fullmatch(r"(/[A-Za-z0-9_]+)+(\[[0-9]+\])?(/[A-Za-z0-9_]+(\[[0-9]+\])?)*", expression or ""):
        return {"ok": False, "error": "Choose a numeric topic field"}
    setup = settings()
    # rqt_plot lives in lib/, not on PATH.
    command = ROS_ROOT / setup["distro"] / "lib" / "rqt_plot" / "rqt_plot"
    if not command.is_file():
        return {"ok": False, "error": f"rqt_plot is not installed: sudo apt install ros-{setup['distro']}-rqt-plot"}
    return start("plot", [[str(command), expression]], ros_env(setup),
                 {"name": f"Plot {expression}", "expression": expression})


TOPIC_NAME = re.compile(r"(/[A-Za-z0-9_~{}]+)+")


def ini_set(text, section, key, value):
    """One key of a Qt INI file set; every other line is kept as it was."""
    lines = text.splitlines()
    head = next((i for i, line in enumerate(lines) if line.strip() == f"[{section}]"), None)
    if head is None:
        if lines and lines[-1].strip():
            lines.append("")
        return "\n".join(lines + [f"[{section}]", f"{key}={value}"]) + "\n"
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    for i in range(head + 1, end):
        if lines[i].split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        at = end
        while at > head + 1 and not lines[at - 1].strip():
            at -= 1
        lines.insert(at, f"{key}={value}")
    return "\n".join(lines) + "\n"


def plotjuggler(topics):
    """PlotJuggler streaming exactly these topics. Its ROS 2 subscriber always asks
    which topics to take; it is set as the streamer, with these topics preselected,
    the way PlotJuggler itself remembers the last choice, and the question is
    answered in the background (plotjuggler_confirm)."""
    topics = list(dict.fromkeys(topics))
    bad = [t for t in topics if not TOPIC_NAME.fullmatch(t)]
    if not topics or bad:
        return {"ok": False, "error": f"Not a topic name: {bad[0]}" if bad else "Choose a topic to plot"}
    setup = settings()
    command = ROS_ROOT / setup["distro"] / "lib" / "plotjuggler" / "plotjuggler"
    if not command.is_file():
        return {"ok": False, "error": f"PlotJuggler is not installed: sudo apt install ros-{setup['distro']}-plotjuggler-ros"}
    try:
        text = PLOTJUGGLER_SETTINGS.read_text()
    except FileNotFoundError:
        text = ""
    except OSError as e:
        return {"ok": False, "error": f"Cannot read PlotJuggler's settings: {e}"}
    text = ini_set(text, "General", "MainWindow.previousStreamingPlugin", "ROS2 Topic Subscriber")
    text = ini_set(text, "DataStreamROS2", "default_topics", ", ".join(topics))
    PLOTJUGGLER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = PLOTJUGGLER_SETTINGS.with_name(f"{PLOTJUGGLER_SETTINGS.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(PLOTJUGGLER_SETTINGS)
    started = start("plotjuggler", [[str(command), "-n", "--start_streamer"]], ros_env(setup),
                    {"name": f"PlotJuggler · {', '.join(topics)}", "topics": topics})
    if started.get("ok"):
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "plotjuggler-confirm", str(started["pids"][0])],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return {**started, "topics": topics}


def plotjuggler_confirm(pgid, wait_s=45.0):
    """Press OK on the topic dialog of the PlotJuggler started in process group pgid.
    Only when that very dialog has the keyboard: a Return sent anywhere else could
    land in a terminal. Otherwise it is left open, the topics already ticked."""
    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"):
        return {"ok": False, "error": "No X11 display or xdotool: press OK in PlotJuggler"}

    def xdo(*args):
        try:
            p = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=5)
            return p.stdout.split() if p.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            return []
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except OSError:
            return {"ok": False, "error": "PlotJuggler quit"}
        for wid in xdo("search", "--name", "^Select ROS messages$"):
            pid = xdo("getwindowpid", wid)
            try:
                if not pid or os.getpgid(int(pid[0])) != pgid:
                    continue
            except (OSError, ValueError):
                continue
            time.sleep(1.0)                       # it fills its topic list as they are discovered
            xdo("windowactivate", "--sync", wid)
            time.sleep(0.3)
            if wid not in xdo("getwindowfocus") + xdo("getactivewindow"):
                xdo("windowfocus", "--sync", wid)       # no window manager to ask (a bare X server)
                time.sleep(0.3)
            if wid not in xdo("getwindowfocus") + xdo("getactivewindow"):
                return {"ok": False, "error": "The topic dialog did not get the keyboard; left for the user"}
            xdo("key", "--clearmodifiers", "Return")
            return {"ok": True}
        time.sleep(0.3)
    return {"ok": False, "error": "No topic dialog appeared"}


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
            "running": {tool: [{"pgid": e["pgid"], "meta": e.get("meta", {}), "started": e.get("started"),
                                "paused": bool(e.get("paused"))}
                               for e in entries] for tool, entries in owned.items()},
            "recording": recording(owned.get("bag", [])),
            "build": build_progress() if owned.get("build") else {},
            "history": read_json(HISTORY, list)[-8:][::-1]}


def stop(tool):
    entries = owned_runs(tool)
    groups = [int(entry["pgid"]) for entry in entries]
    for pgid in groups:
        try:
            # A paused group would hold SIGINT until it is resumed.
            os.killpg(pgid, signal.SIGCONT)
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
        overlay = shlex.quote(str(ws / "install" / "setup.zsh"))
        # A workspace may be chosen before its first build.
        lines += [f"[[ -f {overlay} ]] && source {overlay}", f"cd {shlex.quote(str(top))}"]
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


def bag_metadata(path):
    """A bag folder's metadata.yaml, or None (missing, or half written while a recording stops)."""
    try:
        import yaml
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)   # big bags list hundreds of topics
        return yaml.load((Path(path) / "metadata.yaml").read_text(), Loader=loader)["rosbag2_bagfile_information"]
    except Exception:
        return None


def bag_target(path):
    """What `ros2 bag play` gets for a path someone picked: a bag folder, its
    metadata.yaml or one of its files all mean the folder (a split bag has
    several); a .db3 or .mcap on its own plays alone with its storage named.
    {"path", "storage"}, or None when it is no bag."""
    try:
        p = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if p.is_file() and (p.name == "metadata.yaml" or p.suffix in BAG_FILES) and (p.parent / "metadata.yaml").is_file():
        p = p.parent
    if p.is_dir():
        if (p / "metadata.yaml").is_file():
            return {"path": p, "storage": None}
        files = [f for f in p.iterdir() if f.is_file() and f.suffix in BAG_FILES]
        return {"path": files[0], "storage": BAG_FILES[files[0].suffix]} if len(files) == 1 else None
    if p.is_file() and p.suffix in BAG_FILES:
        return {"path": p, "storage": BAG_FILES[p.suffix]}
    return None


def bag_summary(path, origin="recorded"):
    """Duration, message count and topics from a bag's metadata.yaml (a lone
    file shows its size until it is opened)."""
    path = Path(path)
    info = {"name": path.name, "path": str(path), "origin": origin,
            "size": dir_size(path) if path.is_dir() else path.stat().st_size}
    meta = bag_metadata(path) if path.is_dir() else None
    if meta:
        try:
            info["duration_s"] = meta["duration"]["nanoseconds"] / 1e9
            info["messages"] = meta["message_count"]
            info["topics"] = len(meta.get("topics_with_message_count") or [])
        except (KeyError, TypeError):
            pass
    return info


def is_bag_metadata(path):
    if not path.endswith("/metadata.yaml"):
        return False
    try:
        with open(path, errors="replace") as f:
            return f.read(64).lstrip().startswith("rosbag2_bagfile_information")
    except OSError:
        return False


def found_bags():
    """Bag folders someone downloaded or copied in (their metadata.yaml). Not
    cached with the other files: a bag just downloaded is listed the next time
    the panel opens, and the walk takes a millisecond."""
    return [str(Path(f["path"]).parent) for f in
            recent_files([(HOME / "Downloads", 4), (HOME, 2)], is_bag_metadata, limit=12)]


def recent_bags(found=(), limit=10):
    """Bags recorded here, bags opened from anywhere, and bags found in
    ~/Downloads and the home folder: newest first."""
    stamped = {}

    def add(path, origin, when=None):
        try:
            when = when if when is not None else Path(path).stat().st_mtime
        except OSError:
            return
        key = str(path)
        if key not in stamped or stamped[key][0] < when:
            stamped[key] = (when, origin)
    try:
        for path in BAGS.iterdir():
            if path.is_dir() and (path / "metadata.yaml").is_file():
                add(path, "recorded")
    except OSError:
        pass
    for path in found:
        add(path, "found")
    for entry in read_json(OPENED_BAGS, list):
        target = bag_target(entry.get("path", ""))
        if target:
            add(target["path"], "opened", entry.get("at"))
    newest = sorted(stamped.items(), key=lambda item: item[1][0], reverse=True)[:limit]
    bags = []
    for path, (_when, origin) in newest:
        try:
            bags.append(bag_summary(path, origin))
        except OSError:
            pass
    return bags


def remember_bag(path):
    with file_lock(OPENED_BAGS.with_suffix(".lock")):
        opened = [e for e in read_json(OPENED_BAGS, list) if e.get("path") != str(path)]
        write_json(OPENED_BAGS, [{"path": str(path), "at": time.time()}, *opened][:10])


def forget_bag(path):
    with file_lock(OPENED_BAGS.with_suffix(".lock")):
        opened = read_json(OPENED_BAGS, list)
        kept = [e for e in opened if e.get("path") != str(path)]
        write_json(OPENED_BAGS, kept)
    return {"ok": True, "forgotten": len(opened) - len(kept)}


def bag_topics_from_info(text):
    """Topics from `ros2 bag info` (a lone file has no metadata.yaml to read)."""
    topics = []
    for m in re.finditer(r"Topic:\s*(\S+)\s*\|\s*Type:\s*(\S+)\s*\|\s*Count:\s*(\d+)", text):
        topics.append({"name": m[1], "type": m[2], "count": int(m[3])})
    duration = re.search(r"Duration:\s*([\d.]+)s", text)
    messages = re.search(r"Messages:\s*(\d+)", text)
    return topics, float(duration[1]) if duration else None, int(messages[1]) if messages else None


def bag_details(path, remember=False):
    """A bag before it plays: length, messages, its topics and which of them
    will not play because their message package is not installed (ROS
    skips those with a warning)."""
    target = bag_target(path)
    if not target:
        return {"ok": False, "error": "That is not a ROS 2 bag (a folder with metadata.yaml, a .db3 or an .mcap)"}
    setup = settings()
    if not setup.get("distro"):
        return {"ok": False, "error": "ROS 2 is not installed"}
    bag = target["path"]
    if target["storage"]:
        done = subprocess.run(["ros2", "bag", "info", "-s", target["storage"], str(bag)], env=ros_env(setup),
                              capture_output=True, text=True, timeout=60)
        topics, duration, messages = bag_topics_from_info(done.stdout)
        if done.returncode != 0 and not topics:
            return {"ok": False, "error": (done.stderr or done.stdout).strip()[-300:] or "ros2 bag info failed"}
    else:
        meta = bag_metadata(bag)
        if not meta:
            return {"ok": False, "error": f"{bag / 'metadata.yaml'} cannot be read"}
        topics = [{"name": t["topic_metadata"]["name"], "type": t["topic_metadata"]["type"],
                   "count": t.get("message_count", 0)} for t in meta.get("topics_with_message_count") or []]
        duration = meta.get("duration", {}).get("nanoseconds", 0) / 1e9
        messages = meta.get("message_count")
    roots = [ROS_ROOT / setup["distro"]] + ([Path(setup["workspace"]) / "install"] if setup.get("workspace") else [])
    installed = installed_packages(roots)
    missing = {}
    for topic in topics:
        package = topic["type"].split("/")[0]
        if package not in installed:
            entry = missing.setdefault(package, {"package": package, "topics": 0, "messages": 0})
            entry["topics"] += 1
            entry["messages"] += topic["count"]
    if remember and not str(bag).startswith(str(BAGS)):
        remember_bag(bag)
    return {"ok": True, **bag_summary(bag, "opened"), "storage": target["storage"] or "",
            "duration_s": duration, "messages": messages, "topics": len(topics),
            "topic_list": sorted(topics, key=lambda t: t["name"])[:400],
            "skipped": sorted(missing.values(), key=lambda m: -m["topics"]),
            "playable": len(topics) - sum(m["topics"] for m in missing.values())}


def choose_bag():
    """A file chooser (zenity) for a bag; the panel shows nothing while it is open."""
    if shutil.which("zenity") is None:
        return {"ok": False, "error": "No file chooser (zenity) is installed; type the path instead"}
    start = HOME / "Downloads" if (HOME / "Downloads").is_dir() else HOME
    done = subprocess.run(["zenity", "--file-selection", "--title=Open a ROS 2 bag", f"--filename={start}/",
                           "--file-filter=ROS 2 bags | *.db3 *.mcap metadata.yaml", "--file-filter=All files | *"],
                          capture_output=True, text=True)
    path = done.stdout.strip()
    if done.returncode != 0 or not path:
        return {"ok": False, "cancelled": True, "error": ""}
    return bag_details(path, remember=True)


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


def bag_play(path, rate=1.0, loop=False, clock=False, start_offset=0.0):
    target = bag_target(path)
    if not target:
        return {"ok": False, "error": "That is not a ROS 2 bag (a folder with metadata.yaml, a .db3 or an .mcap)"}
    bag = target["path"]
    if owned_runs("bag"):
        return {"ok": False, "error": "A bag started here is already running; stop it first"}
    env = ros_env(settings())
    try:
        rate = float(rate)
    except ValueError:
        rate = 0
    if not 0.1 <= rate <= 10:
        return {"ok": False, "error": "Playback speed is 0.1 to 10"}
    try:
        start_offset = float(start_offset or 0)
    except ValueError:
        start_offset = -1
    if not 0 <= start_offset <= 1e7:
        return {"ok": False, "error": "Start at is a number of seconds into the bag"}
    argv = ["ros2", "bag", "play", str(bag), "--rate", str(rate)]
    if target["storage"]:
        argv += ["-s", target["storage"]]
    if start_offset:
        argv += ["--start-offset", str(start_offset)]
    if loop:
        argv.append("--loop")
    if clock:
        argv.append("--clock")
    if not str(bag).startswith(str(BAGS)):
        remember_bag(bag)
    result = start("bag", [argv], env, {"play": str(bag), "name": bag.name, "rate": rate, "loop": loop,
                                        "clock": clock, "start": start_offset})
    return {**result, "path": str(bag)}


def bag_pausable(distro, entries):
    """Playback always pauses (through the player's service). Recording only
    from Iron on: Humble's recorder has no pause service."""
    playing = any((entry.get("meta") or {}).get("play") for entry in entries)
    return playing or distro not in ("foxy", "galactic", "humble")


def bag_control(operation):
    """Pause or resume the bag started here through rosbag2's own services. A
    stopped process would not do: the player's clock would jump on resume and
    send everything that fell due at once."""
    if operation not in ("pause", "resume"):
        return {"ok": False, "error": "Bag control is pause or resume"}
    entries = owned_runs("bag")
    if not entries:
        return {"ok": False, "error": "No bag started here is running"}
    setup = settings()
    if not bag_pausable(setup["distro"], entries):
        return {"ok": False, "error": f"Recording cannot pause on {setup['distro'].title()}; "
                                      "stop it and record a new bag"}
    playing = any((entry.get("meta") or {}).get("play") for entry in entries)
    service = f"/rosbag2_{'player' if playing else 'recorder'}/{operation}"
    kind = f"rosbag2_interfaces/srv/{operation.title()}"
    env = ros_env(setup)
    try:
        # `service call` waits for ever for a service that is not there.
        listed = subprocess.run(["ros2", "service", "list"], env=env, capture_output=True,
                                text=True, timeout=8).stdout.split()
        if service not in listed:
            return {"ok": False, "error": f"The bag does not offer {service} yet"}
        proc = subprocess.run(["ros2", "service", "call", service, kind, "{}"], env=env,
                              capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{service} did not answer"}
    if proc.returncode:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        return {"ok": False, "error": lines[-1] if lines else f"{service} failed"}
    mark_paused("bag", operation == "pause")
    return {"ok": True, "paused": operation == "pause"}


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


def save_robot_profile(name, package=""):
    if not SAVED_NAME.match(name or ""):
        return {"ok": False, "error": "A profile name is letters, digits, spaces and .:+-"}
    setup = settings()
    item = {"name": name, "domain": setup["domain"], "localhost": setup["localhost"],
            "rmw": setup["rmw"] if setup["rmw_set"] else "", "workspace": setup["workspace"],
            "package": package, "favorites": read_json(FAVORITES, list),
            "launches": read_json(SAVED_LAUNCHES, list)}
    with file_lock(ROBOT_PROFILES.with_suffix(".lock")):
        items = [profile for profile in read_json(ROBOT_PROFILES, list) if profile.get("name") != name]
        items.append(item)
        items.sort(key=lambda profile: profile["name"].lower())
        write_json(ROBOT_PROFILES, items)
    return {"ok": True, "robot_profiles": items}


def forget_robot_profile(name):
    with file_lock(ROBOT_PROFILES.with_suffix(".lock")):
        items = [profile for profile in read_json(ROBOT_PROFILES, list) if profile.get("name") != name]
        write_json(ROBOT_PROFILES, items)
    return {"ok": True, "robot_profiles": items}


def use_robot_profile(name):
    """The profile's setup, its favourites, and its saved launches (added to
    the ones kept now; a launch of the same name is replaced)."""
    profile = next((p for p in read_json(ROBOT_PROFILES, list) if p.get("name") == name), None)
    if not profile:
        return {"ok": False, "error": f"No robot profile is called {name}"}
    result = set_values([("domain", str(profile.get("domain", 0))),
                         ("localhost", "1" if profile.get("localhost") else "0"),
                         ("rmw", profile.get("rmw") or ""),
                         ("workspace", profile.get("workspace") or "none")])
    if result.get("ok") is False:
        return result
    with file_lock(FAVORITES.with_suffix(".lock")):
        write_json(FAVORITES, profile.get("favorites") or [])
    launches = [item for item in profile.get("launches") or [] if isinstance(item, dict) and item.get("name")]
    if launches:
        with file_lock(SAVED_LAUNCHES.with_suffix(".lock")):
            names = {item["name"] for item in launches}
            items = [item for item in read_json(SAVED_LAUNCHES, list) if item.get("name") not in names]
            write_json(SAVED_LAUNCHES, sorted(items + launches, key=lambda item: item["name"].lower()))
    result.update(favorites=read_json(FAVORITES, list), saved_launches=read_json(SAVED_LAUNCHES, list),
                  profile=profile)
    return result


def flat_parameters(document):
    """A `ros2 param dump` document as {"a.b": value}: the one node's
    ros__parameters, nested names joined with dots."""
    nodes = [v for v in (document or {}).values() if isinstance(v, dict)]
    values = (nodes[0] if nodes else {}).get("ros__parameters") or {}
    flat = {}

    def walk(prefix, item):
        for key, value in item.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                walk(name, value)
            else:
                flat[name] = value
    walk("", values)
    return flat


def dump_parameters(node, env):
    """The node's parameters as YAML text (Humble on prints them to stdout)."""
    try:
        proc = subprocess.run(["ros2", "param", "dump", node], env=env, capture_output=True,
                              text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return None, f"{node} did not answer"
    if proc.returncode or not proc.stdout.strip():
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        return None, lines[-1] if lines else f"{node} did not answer"
    return proc.stdout, None


def parameter_profile(operation, node, name):
    """save: the node's parameters now. diff: what applying would change.
    apply: load them back (`ros2 param load`)."""
    import yaml
    if operation not in ("save", "diff", "apply") or not SAVED_NAME.match(name or ""):
        return {"ok": False, "error": "A profile name is letters, digits, spaces and .:+-"}
    if not re.fullmatch(r"(/[A-Za-z_][A-Za-z0-9_]*)+", node or ""):
        return {"ok": False, "error": "That is not a node name"}
    # "--" separates the profile from the node in the file name.
    safe_name = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9_.+-]+", "_", name))
    path = PARAMETER_PROFILES / f"{safe_name}--{node.strip('/').replace('/', '__')}.yaml"
    env = ros_env(settings())
    if operation == "save":
        text, error = dump_parameters(node, env)
        if error:
            return {"ok": False, "error": error}
        # qos_overrides are read-only once a node runs: loading them back
        # could only fail, so they are not kept.
        document = yaml.safe_load(text) or {}
        for values in document.values():
            if isinstance(values, dict) and isinstance(values.get("ros__parameters"), dict):
                values["ros__parameters"].pop("qos_overrides", None)
        PARAMETER_PROFILES.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(document, sort_keys=False))
        return {"ok": True, "path": str(path), "parameter_profiles": parameter_profiles()}
    if not path.is_file():
        return {"ok": False, "error": f"No parameter profile is called {name}"}
    if operation == "diff":
        text, error = dump_parameters(node, env)
        if error:
            return {"ok": False, "error": error}
        try:
            now, saved = flat_parameters(yaml.safe_load(text)), flat_parameters(yaml.safe_load(path.read_text()))
        except (OSError, yaml.YAMLError) as error:
            return {"ok": False, "error": f"Cannot read the profile: {error}"}
        saved = {key: value for key, value in saved.items() if not key.startswith("qos_overrides.")}
        changes = [{"name": key, "current": now.get(key), "saved": saved[key], "missing": key not in now}
                   for key in sorted(saved) if now.get(key) != saved[key] or key not in now]
        return {"ok": True, "changes": changes, "unchanged": len(saved) - len(changes)}
    try:
        proc = subprocess.run(["ros2", "param", "load", node, str(path)], env=env,
                              capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{node} did not answer"}
    # `param load` prints a line per parameter and exits 0 when some fail; a
    # read-only one (set when the node started) is skipped, not an error.
    outcome = [line for line in proc.stdout.splitlines() if line.startswith("Set parameter")]
    read_only = [line for line in outcome if "read-only" in line]
    failed = [line for line in outcome if "successful" not in line and line not in read_only]
    if proc.returncode or failed:
        lines = failed or (proc.stderr or proc.stdout).strip().splitlines()
        return {"ok": False, "error": lines[-1] if lines else "The parameters did not load"}
    return {"ok": True, "path": str(path), "applied": len(outcome) - len(read_only),
            "read_only": len(read_only), "parameter_profiles": parameter_profiles()}


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
                value = str(Path(value).expanduser().resolve()) if value != "none" else value
                if value != "none" and not is_workspace(value):
                    return {"ok": False, "error": f"{value} is not a colcon workspace (no install/setup.bash, no packages in src)"}
                config[key] = "" if value == "none" else value
            else:
                return {"ok": False, "error": f"unknown setting {key}"}
        write_config(config)
    return {"ok": True, **status()}


def set_value(key, value):
    return set_values([(key, value)])


# ------------------------------------------------------------------ new packages

# `pkg-catalog` feeds the New package dialog; `pkg-create` makes the package with
# `ros2 pkg create` and then finishes the template (a real node, a component,
# interfaces, a launch package). Packages are only ever made under ~/ros2_ws/src.
ROS_WS = HOME / "ros2_ws"
NEW_PACKAGE_PREFS = CONFIG.parent / "ros-new-package.json"
PACKAGE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
CODE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
LICENSES = ["Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "MIT", "MIT-0", "BSL-1.0", "GPL-3.0-only",
            "LGPL-3.0-only", "Proprietary"]
PACKAGE_TEMPLATES = [
    {"id": "cpp_node", "title": "C++ node", "language": "C++", "build_type": "ament_cmake",
     "subtitle": "An rclcpp node with a timer, ready to run", "icon": "text-x-script-symbolic",
     "required": ["rclcpp"], "suggested": ["std_msgs"], "fields": ["node_name"]},
    {"id": "python_node", "title": "Python node", "language": "Python", "build_type": "ament_python",
     "subtitle": "An rclpy node with a timer, ready to run", "icon": "text-x-python-symbolic",
     "required": ["rclpy"], "suggested": ["std_msgs"], "fields": ["node_name"]},
    {"id": "cpp_component", "title": "C++ component", "language": "C++", "build_type": "ament_cmake",
     "subtitle": "A composable node: runs alone or in a container", "icon": "application-x-addon-symbolic",
     "required": ["rclcpp", "rclcpp_components"], "suggested": ["std_msgs"], "fields": ["node_name"]},
    {"id": "cpp_library", "title": "C++ library", "language": "C++", "build_type": "ament_cmake",
     "subtitle": "A shared library other packages link against", "icon": "folder-documents-symbolic",
     "required": [], "suggested": ["rclcpp"], "fields": ["library_name"]},
    {"id": "interfaces", "title": "Interfaces", "language": "IDL", "build_type": "ament_cmake",
     "subtitle": "Your own messages, services and actions", "icon": "mail-attachment-symbolic",
     "required": ["rosidl_default_generators", "rosidl_default_runtime"], "suggested": [],
     "fields": ["interfaces"]},
    {"id": "bringup", "title": "Launch & config", "language": "Launch", "build_type": "ament_cmake",
     "subtitle": "Launch files and parameters that start a robot", "icon": "media-playback-start-symbolic",
     "required": ["launch", "launch_ros", "ament_index_python"], "suggested": [], "fields": []},
    {"id": "empty_cmake", "title": "Empty CMake package", "language": "C++", "build_type": "ament_cmake",
     "subtitle": "Only package.xml and CMakeLists.txt", "icon": "document-new-symbolic",
     "required": [], "suggested": [], "fields": []},
    {"id": "empty_python", "title": "Empty Python package", "language": "Python", "build_type": "ament_python",
     "subtitle": "Only package.xml, setup.py and the module", "icon": "document-new-symbolic",
     "required": [], "suggested": [], "fields": []},
]
INTERFACE_STARTERS = {
    "msg": ("msg/Status.msg", "# A status report\nstring name\nbool ok\nstring message\n"),
    "srv": ("srv/Command.srv", "# Request\nstring command\n---\n# Response\nbool success\nstring message\n"),
    "action": ("action/Task.action", "# Goal\nint32 target\n---\n# Result\nbool success\n---\n"
                                     "# Feedback\nfloat32 progress\n"),
}
# The packages most ROS 2 work depends on, by area, so they are offered (and
# described) even before they are installed. Everything else installed is listed
# under "Other installed".
DEPENDENCY_CATALOG = {
    "Core": {
        "rclcpp": "C++ client library: nodes, topics, services, parameters",
        "rclpy": "Python client library: nodes, topics, services, parameters",
        "rclcpp_components": "Composable C++ nodes loaded into containers",
        "rclcpp_lifecycle": "Managed (lifecycle) C++ nodes",
        "rclcpp_action": "Action clients and servers in C++",
        "rcl_interfaces": "Parameter and logging interfaces",
        "builtin_interfaces": "Time and Duration",
        "ament_index_cpp": "Find a package's share folder from C++",
        "ament_index_python": "Find a package's share folder from Python",
        "launch": "The launch system",
        "launch_ros": "ROS actions for launch files: Node, ComposableNode",
        "pluginlib": "Load plugins (classes) at run time",
    },
    "Messages": {
        "std_msgs": "Basic types: String, Bool, Int32, Float64, Header",
        "std_srvs": "Trigger, SetBool and Empty services",
        "geometry_msgs": "Poses, twists, transforms, points",
        "sensor_msgs": "Images, laser scans, IMU, point clouds, joint states",
        "nav_msgs": "Odometry, paths, occupancy grids",
        "trajectory_msgs": "Joint and multi-DOF trajectories",
        "visualization_msgs": "Markers for RViz",
        "diagnostic_msgs": "Diagnostic status reports",
        "action_msgs": "Goal status for actions",
        "example_interfaces": "AddTwoInts, Fibonacci and other examples",
        "control_msgs": "Controller commands and states",
        "ackermann_msgs": "Ackermann steering commands",
        "vision_msgs": "Detections and classifications",
    },
    "TF & robot model": {
        "tf2": "Coordinate frame transforms",
        "tf2_ros": "TF listeners, broadcasters and buffers",
        "tf2_geometry_msgs": "Transform geometry_msgs types",
        "tf2_eigen": "Transform Eigen types",
        "tf2_msgs": "TF messages",
        "urdf": "Parse URDF robot descriptions",
        "xacro": "Macros for URDF files",
        "robot_state_publisher": "Publish TF from a URDF and joint states",
        "joint_state_publisher": "Publish joint states for a URDF",
        "kdl_parser": "Build a KDL tree from a URDF",
        "angles": "Angle normalisation helpers",
        "eigen3_cmake_module": "Find Eigen from CMake",
    },
    "Perception": {
        "cv_bridge": "Convert between ROS images and OpenCV",
        "image_transport": "Compressed and raw image topics",
        "image_geometry": "Camera models",
        "camera_info_manager": "Load and serve camera calibration",
        "pcl_conversions": "Convert between ROS and PCL point clouds",
        "pcl_ros": "PCL filters as ROS nodes",
        "laser_geometry": "Laser scans to point clouds",
        "message_filters": "Synchronise messages by time stamp",
    },
    "Navigation": {
        "nav2_msgs": "Navigation 2 messages and actions",
        "nav2_util": "Navigation 2 helpers",
        "nav2_core": "Plugin interfaces for planners and controllers",
        "nav2_costmap_2d": "2D costmaps",
        "nav2_common": "Launch helpers for Navigation 2",
        "slam_toolbox": "2D SLAM",
        "robot_localization": "Sensor fusion (EKF/UKF)",
    },
    "Control": {
        "controller_interface": "Write a ros2_control controller",
        "hardware_interface": "Write a ros2_control hardware interface",
        "controller_manager": "Load and switch controllers",
        "realtime_tools": "Realtime-safe publishers and buffers",
        "joy": "Joystick input",
        "teleop_twist_keyboard": "Drive a robot from the keyboard",
    },
    "Manipulation": {
        "moveit_core": "MoveIt core: kinematics, planning scene",
        "moveit_ros_planning_interface": "MoveGroup interface from C++ and Python",
        "moveit_msgs": "MoveIt messages and actions",
    },
    "Simulation": {
        "gazebo_ros": "Gazebo Classic with ROS",
        "gazebo_msgs": "Gazebo Classic messages",
        "ros_gz_sim": "Gazebo (new) with ROS",
        "ros_gz_bridge": "Bridge Gazebo and ROS topics",
    },
    "Visualization": {
        "rviz2": "3D visualiser",
        "rviz_common": "Write RViz plugins",
        "rviz_default_plugins": "RViz's standard displays",
        "interactive_markers": "Clickable markers in RViz",
    },
    "Logging & tools": {
        "rosbag2_cpp": "Read and write bags from C++",
        "rosbag2_py": "Read and write bags from Python",
        "diagnostic_updater": "Publish diagnostics from a node",
        "rcutils": "Logging macros and C utilities",
    },
    "Testing": {
        "ament_cmake_gtest": "C++ unit tests with GoogleTest",
        "ament_cmake_pytest": "Python tests from CMake",
        "launch_testing": "Tests that start nodes",
        "launch_testing_ament_cmake": "Register launch tests from CMake",
        "ament_lint_auto": "Run the linters as tests",
        "ament_lint_common": "The usual linters",
    },
}


def installed_packages(roots):
    """Package name -> its share folder, from the ament index of each prefix."""
    found = {}
    for root in roots:
        for index in [root / "share" / "ament_index" / "resource_index" / "packages",
                      *root.glob("*/share/ament_index/resource_index/packages")]:
            try:
                names = [p.name for p in index.iterdir()]
            except OSError:
                continue
            for name in names:
                found.setdefault(name, index.parents[2] / name)
    return found


def manifest_description(share):
    import xml.etree.ElementTree as ET
    try:
        text = ET.parse(share / "package.xml").getroot().findtext("description", "")
    except (OSError, ET.ParseError):
        return ""
    text = " ".join(text.split())
    return text if len(text) <= 140 else text[:139] + "…"


def has_cmake_config(share, name):
    return any((share / "cmake" / f).is_file() for f in (f"{name}Config.cmake", f"{name}-config.cmake"))


def package_locations():
    """Where a new package may go: ~/ros2_ws/src, and folders under it that
    already hold packages (src/<project>/packages)."""
    src = ROS_WS / "src"
    found = [{"name": "src", "path": str(src)}]
    if not src.is_dir():
        return found
    for directory, dirs, files in os.walk(src):
        rel = Path(directory).relative_to(src)
        if "package.xml" in files or "COLCON_IGNORE" in files or len(rel.parts) >= 3:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        if rel.parts and any((Path(directory) / d / "package.xml").is_file() for d in dirs):
            found.append({"name": str(Path("src") / rel), "path": directory})
    return found


def new_package_defaults():
    """The last choices, else a maintainer from the account. The git identity is
    left alone: its global config can be a work account."""
    prefs = read_json(NEW_PACKAGE_PREFS)
    try:
        account = pwd.getpwuid(os.getuid())
        full = account.pw_gecos.split(",")[0].strip() or account.pw_name
    except KeyError:
        full = os.environ.get("USER", "")
    return {"maintainer_name": prefs.get("maintainer_name") or full,
            "maintainer_email": prefs.get("maintainer_email", ""),
            "license": prefs.get("license") if prefs.get("license") in LICENSES else "Apache-2.0",
            "location": prefs.get("location", "src"), "template": prefs.get("template", "cpp_node")}


def package_catalog():
    setup = settings()
    distro = setup.get("distro")
    if not distro:
        return {"ok": False, "error": "ROS 2 is not installed"}
    roots = [ROS_ROOT / distro, ROS_WS / "install"]
    if setup.get("workspace"):
        roots.append(Path(setup["workspace"]) / "install")
    installed = installed_packages(roots)
    in_workspace = {p["name"] for p in workspace_packages(str(ROS_WS))} if (ROS_WS / "src").is_dir() else set()
    rows, seen = [], set()
    for category, entries in DEPENDENCY_CATALOG.items():
        for name, description in entries.items():
            share = installed.get(name)
            rows.append({"name": name, "category": category, "description": description,
                         "installed": share is not None, "cmake": bool(share and has_cmake_config(share, name))})
            seen.add(name)
    for name in sorted(in_workspace - seen):
        rows.append({"name": name, "category": "This workspace", "description": "In ~/ros2_ws/src",
                     "installed": True, "workspace": True, "cmake": True})
        seen.add(name)
    for name, share in sorted(installed.items()):
        if name not in seen:
            rows.append({"name": name, "category": "Other installed", "description": manifest_description(share),
                         "installed": True, "cmake": has_cmake_config(share, name)})
    return {"ok": True, "distro": distro, "workspace": str(ROS_WS), "workspace_exists": ROS_WS.is_dir(),
            "panel_workspace": setup.get("workspace") or "", "locations": package_locations(),
            "taken": sorted(in_workspace), "shadowed": sorted(n for n in installed if n not in in_workspace),
            "templates": PACKAGE_TEMPLATES, "categories": [*DEPENDENCY_CATALOG, "This workspace", "Other installed"],
            "packages": rows, "licenses": LICENSES, "defaults": new_package_defaults(),
            "colcon": shutil.which("colcon") is not None, "rosdep": shutil.which("rosdep") is not None}


def pascal(name):
    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part) or "Node"


def xml_add(text, lines, after=None, before=("  <test_depend>", "  <export>")):
    """Add manifest lines after the last `after` line, else before the first of
    `before` there is: package.xml's schema fixes the order of its elements."""
    block = "".join(f"  {line}\n" for line in lines)
    if after and after in text:
        at = text.index("\n", text.rindex(after)) + 1
        return text[:at] + block + text[at:]
    for marker in before:
        if marker in text:
            at = text.index(marker)
            return text[:at] + block + "\n" + text[at:]
    return text.replace("</package>", block + "</package>")


def cmake_add(text, block):
    """Add a CMake block before the tests (or ament_package())."""
    marker = "if(BUILD_TESTING)" if "if(BUILD_TESTING)" in text else "ament_package()"
    at = text.index(marker)
    return text[:at] + block.rstrip() + "\n\n" + text[at:]


def cpp_node_source(node, publish):
    cls = pascal(node)
    return f"""#include <chrono>
#include <memory>
{'#include <string>' + chr(10) if publish else ''}
#include "rclcpp/rclcpp.hpp"
{'#include "std_msgs/msg/string.hpp"' + chr(10) if publish else ''}
using namespace std::chrono_literals;

class {cls} : public rclcpp::Node
{{
public:
  {cls}()
  : Node("{node}")
  {{
{'    publisher_ = create_publisher<std_msgs::msg::String>("~/status", 10);' + chr(10) if publish else ''}    timer_ = create_wall_timer(1s, [this]() {{tick();}});
  }}

private:
  void tick()
  {{
{'''    std_msgs::msg::String message;
    message.data = "running";
    publisher_->publish(message);
''' if publish else ''}    RCLCPP_INFO(get_logger(), "{node} is running");
  }}

{'  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr publisher_;' + chr(10) if publish else ''}  rclcpp::TimerBase::SharedPtr timer_;
}};

int main(int argc, char ** argv)
{{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<{cls}>());
  rclcpp::shutdown();
  return 0;
}}
"""


def cpp_component_source(package, node, publish):
    cls = pascal(node)
    return f"""#include <chrono>
#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp_components/register_node_macro.hpp"
{'#include "std_msgs/msg/string.hpp"' + chr(10) if publish else ''}
using namespace std::chrono_literals;

namespace {package}
{{

class {cls} : public rclcpp::Node
{{
public:
  explicit {cls}(const rclcpp::NodeOptions & options)
  : Node("{node}", options)
  {{
{'    publisher_ = create_publisher<std_msgs::msg::String>("~/status", 10);' + chr(10) if publish else ''}    timer_ = create_wall_timer(1s, [this]() {{tick();}});
  }}

private:
  void tick()
  {{
{'''    std_msgs::msg::String message;
    message.data = "running";
    publisher_->publish(message);
''' if publish else ''}    RCLCPP_INFO(get_logger(), "{node} is running");
  }}

{'  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr publisher_;' + chr(10) if publish else ''}  rclcpp::TimerBase::SharedPtr timer_;
}};

}}  // namespace {package}

RCLCPP_COMPONENTS_REGISTER_NODE({package}::{cls})
"""


def python_node_source(node, publish):
    cls = pascal(node)
    return f'''"""The {node} node."""

import rclpy
from rclpy.node import Node
{'from std_msgs.msg import String' + chr(10) if publish else ''}

class {cls}(Node):
    """Says it is running, once a second."""

    def __init__(self):
        super().__init__('{node}')
{"        self.publisher = self.create_publisher(String, '~/status', 10)" + chr(10) if publish else ''}        self.timer = self.create_timer(1.0, self.tick)

    def tick(self):
        """Run once a second."""
{"        self.publisher.publish(String(data='running'))" + chr(10) if publish else ''}        self.get_logger().info('{node} is running')


def main(args=None):
    """Spin the node until Ctrl+C."""
    rclpy.init(args=args)
    node = {cls}()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
'''


def finish_template(template, path, name, spec, cmake_deps):
    """Turn what `ros2 pkg create` wrote into the chosen template."""
    tid, node = template["id"], spec.get("node_name") or f"{name}_node"
    publish = "std_msgs" in spec["dependencies"]
    manifest, cmake = path / "package.xml", path / "CMakeLists.txt"
    if tid == "cpp_node":
        (path / "src" / f"{node}.cpp").write_text(cpp_node_source(node, publish))
    elif tid == "python_node":
        (path / name / f"{node}.py").write_text(python_node_source(node, publish))
    elif tid == "cpp_component":
        (path / "src").mkdir(exist_ok=True)
        (path / "src" / f"{node}.cpp").write_text(cpp_component_source(name, node, publish))
        cmake.write_text(cmake_add(cmake.read_text(), f"""
add_library({node}_component SHARED src/{node}.cpp)
target_compile_features({node}_component PUBLIC cxx_std_17)
ament_target_dependencies({node}_component {' '.join(f'"{d}"' for d in cmake_deps)})
rclcpp_components_register_node({node}_component
  PLUGIN "{name}::{pascal(node)}"
  EXECUTABLE {node})
install(TARGETS {node}_component
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin)
"""))
    elif tid == "interfaces":
        kinds = [k for k in INTERFACE_STARTERS if k in (spec.get("interfaces") or ["msg"])] or ["msg"]
        files = []
        for kind in kinds:
            rel, body = INTERFACE_STARTERS[kind]
            (path / rel).parent.mkdir(exist_ok=True)
            (path / rel).write_text(body)
            files.append(rel)
        deps = [d for d in spec["dependencies"] if d not in template["required"]]
        if "action" in kinds and "action_msgs" not in deps:
            deps.append("action_msgs")
        finds = "".join(f"find_package({d} REQUIRED)\n" for d in deps)
        cmake.write_text(cmake_add(cmake.read_text(), f"""
find_package(rosidl_default_generators REQUIRED)
{finds}rosidl_generate_interfaces(${{PROJECT_NAME}}
{''.join(f'  "{f}"{chr(10)}' for f in files)}{f'  DEPENDENCIES {" ".join(deps)}{chr(10)}' if deps else ''})
ament_export_dependencies(rosidl_default_runtime)
"""))
        text = xml_add(manifest.read_text(), ["<buildtool_depend>rosidl_default_generators</buildtool_depend>"],
                       after="<buildtool_depend>")
        text = xml_add(text, [*(f"<depend>{d}</depend>" for d in deps),
                              "<exec_depend>rosidl_default_runtime</exec_depend>"])
        text = xml_add(text, ["<member_of_group>rosidl_interface_packages</member_of_group>"],
                       before=("  <export>",))
        manifest.write_text(text)
    elif tid == "bringup":
        (path / "launch").mkdir(exist_ok=True)
        (path / "config").mkdir(exist_ok=True)
        (path / "launch" / f"{name}.launch.py").write_text(f'''"""Start what {name} brings up."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node  # noqa: F401


def generate_launch_description():
    share = get_package_share_directory('{name}')
    config = os.path.join(share, 'config', 'params.yaml')  # noqa: F841
    return LaunchDescription([
        # The nodes this package starts, for example:
        # Node(package='my_robot', executable='driver', parameters=[config]),
    ])
''')
        (path / "config" / "params.yaml").write_text(
            f"# Parameters for the nodes {name} starts, by node name.\n/**:\n  ros__parameters: {{}}\n")
        cmake.write_text(cmake_add(cmake.read_text(), """
install(DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME})
"""))


def create_package(spec):
    """`ros2 pkg create` under ~/ros2_ws/src, the template finished, then
    optionally built and made the panel's workspace."""
    if not isinstance(spec, dict):
        return {"ok": False, "error": "The package description is not valid"}
    setup = settings()
    if not setup.get("distro"):
        return {"ok": False, "error": "ROS 2 is not installed"}
    template = next((t for t in PACKAGE_TEMPLATES if t["id"] == spec.get("template")), None)
    if not template:
        return {"ok": False, "error": "Choose a template"}
    name = str(spec.get("name", "")).strip()
    if not PACKAGE_NAME.match(name) or "__" in name or name.endswith("_") or len(name) > 64:
        return {"ok": False, "error": "A package name is lowercase letters, digits and single underscores, "
                                      "starting with a letter"}
    if template["build_type"] == "ament_python":
        import keyword
        if keyword.iskeyword(name):
            return {"ok": False, "error": f"{name} is a Python keyword"}
    src = (ROS_WS / "src").resolve() if (ROS_WS / "src").exists() else ROS_WS / "src"
    location = Path(os.path.expanduser(str(spec.get("location") or src)))
    location = (ROS_WS / location if not location.is_absolute() else location).resolve()
    if location != src and src not in location.parents:
        return {"ok": False, "error": "New packages go in ~/ros2_ws/src"}
    if location == src:
        src.mkdir(parents=True, exist_ok=True)
    elif not location.is_dir():
        return {"ok": False, "error": f"{location} does not exist"}
    target = location / name
    if target.exists() or os.path.lexists(target):
        return {"ok": False, "error": f"{str(target).replace(str(HOME), '~')} already exists"}
    if name in {p["name"] for p in workspace_packages(str(ROS_WS))}:
        return {"ok": False, "error": f"~/ros2_ws already has a package named {name}"}
    for field in ("node_name", "library_name"):
        value = str(spec.get(field) or "")
        if value and not CODE_NAME.match(value):
            return {"ok": False, "error": f"{field.replace('_', ' ').capitalize()} must be a C/Python identifier"}
    email = str(spec.get("maintainer_email") or "").strip()
    if email and not EMAIL.match(email):
        return {"ok": False, "error": "The maintainer email does not look like an address"}
    license_name = spec.get("license") if spec.get("license") in LICENSES else "Apache-2.0"
    deps = []
    for dep in [*template["required"], *(spec.get("dependencies") or [])]:
        dep = str(dep).strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", dep):
            return {"ok": False, "error": f"{dep or 'An empty name'} is not a package name"}
        if dep not in deps and dep != name:
            deps.append(dep)
    spec = {**spec, "dependencies": deps}

    installed = installed_packages([ROS_ROOT / setup["distro"], ROS_WS / "install"])
    in_workspace = {p["name"] for p in workspace_packages(str(ROS_WS))}
    missing = [d for d in deps if d not in installed and d not in in_workspace]
    cmake_template = template["build_type"] == "ament_cmake"
    # CMake finds only packages with a CMake config; the rest are run-time dependencies.
    cmake_deps = [d for d in deps if d in in_workspace or d in missing
                  or has_cmake_config(installed[d], d)] if cmake_template else deps
    run_deps = [d for d in deps if d not in cmake_deps]
    if template["id"] == "interfaces":
        cmake_deps, run_deps = [], []
    argv = ["ros2", "pkg", "create", name, "--build-type", template["build_type"],
            "--destination-directory", str(location), "--license", license_name,
            "--description", str(spec.get("description") or "").strip() or f"The {name} package",
            "--maintainer-name", str(spec.get("maintainer_name") or "").strip() or os.environ.get("USER", "maintainer")]
    if email:
        argv += ["--maintainer-email", email]
    if template["id"] in ("cpp_node", "python_node"):
        argv += ["--node-name", str(spec.get("node_name") or f"{name}_node")]
    if template["id"] == "cpp_library":
        argv += ["--library-name", str(spec.get("library_name") or name)]
    if cmake_deps:
        argv += ["--dependencies", *cmake_deps]
    env = ros_env({**setup, "workspace": ""})
    done = subprocess.run(argv, cwd=str(location), env=env, capture_output=True, text=True, timeout=60)
    if done.returncode != 0 or not (target / "package.xml").is_file():
        if target.is_dir():
            shutil.rmtree(target)
        return {"ok": False, "error": (done.stderr or done.stdout).strip()[-400:] or "ros2 pkg create failed"}
    try:
        finish_template(template, target, name, spec, cmake_deps)
        if run_deps:
            manifest = target / "package.xml"
            manifest.write_text(xml_add(manifest.read_text(), [f"<exec_depend>{d}</exec_depend>" for d in run_deps]))
    except (OSError, ValueError) as e:
        shutil.rmtree(target)
        return {"ok": False, "error": f"Finishing the {template['title']} template failed: {e}"}

    with file_lock(NEW_PACKAGE_PREFS.with_suffix(".lock")):
        write_json(NEW_PACKAGE_PREFS, {
            "maintainer_name": str(spec.get("maintainer_name") or "").strip(), "maintainer_email": email,
            "license": license_name, "template": template["id"],
            "location": str(location.relative_to(src.parent)) if location != src else "src"})
    files = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())
    reply = {"ok": True, "name": name, "path": str(target), "files": files, "missing": missing,
             "command": " ".join(shlex.quote(a) for a in argv)}
    if spec.get("use_workspace") and setup.get("workspace") != str(ROS_WS.resolve()):
        used = set_value("workspace", str(ROS_WS))
        reply["workspace_set"] = used.get("ok") is not False
    if spec.get("build"):
        reply["build"] = workspace_build([name], workspace=str(ROS_WS))
    return reply


def install_package_dependencies(path):
    """A terminal on rosdep for a package in ~/ros2_ws (the password is typed there)."""
    target = Path(path).expanduser().resolve()
    src = (ROS_WS / "src").resolve()
    if src not in target.parents or not (target / "package.xml").is_file():
        return {"ok": False, "error": "That is not a package in ~/ros2_ws/src"}
    distro = settings()["distro"]
    if not distro:
        return {"ok": False, "error": "ROS 2 is not installed"}
    if shutil.which("rosdep") is None:
        return {"ok": False, "error": "rosdep is not installed (sudo apt install python3-rosdep)"}
    command = (f"rosdep install --from-paths {shlex.quote(str(target))} --ignore-src -y -r "
               f"--rosdistro {shlex.quote(distro)}")
    script = (f"echo {shlex.quote('$ ' + command)}; {command} || echo 'If rosdep is not set up yet: "
              f"sudo rosdep init; rosdep update'; echo; read -rp 'Press Enter to close. '")
    return open_terminal(f"Dependencies of {target.name}", ["bash", "-c", script])


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


def plot_path(field):
    """"pose/position/x" or "ranges[3]" as attribute names and indexes."""
    path = []
    for part in (field or "").strip("/").split("/"):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)((?:\[[0-9]+\])*)", part)
        if not match:
            return None
        path.append(match[1])
        path += [int(i) for i in re.findall(r"\[([0-9]+)\]", match[2])]
    return path or None


def field_value(message, path):
    value = message
    for step in path:
        value = value[step] if isinstance(step, int) else getattr(value, step)
    return value


def quaternion_rpy(x, y, z, w):
    """Roll, pitch and yaw in degrees."""
    import math
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [round(math.degrees(a), 3) for a in (roll, pitch, yaw)]


REQUEST_EMPTY = {}


def request_is_empty(type_name):
    """True when a service's request has no fields (std_srvs/Trigger, Empty): the panel
    calls those with one tap. None when the type is not in this setup."""
    if type_name not in REQUEST_EMPTY:
        from rosidl_runtime_py.utilities import get_service
        try:
            REQUEST_EMPTY[type_name] = not get_service(type_name).Request.get_fields_and_field_types()
        except (AttributeError, ModuleNotFoundError, ValueError):
            REQUEST_EMPTY[type_name] = None
    return REQUEST_EMPTY[type_name]


def compact_json(value, depth=0):
    """JSON with each field on its own line but a list of plain values on one,
    so an Odometry's two 36-number covariances take two lines, not 72."""
    pad, inner = "  " * depth, "  " * (depth + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f"{inner}{json.dumps(str(k))}: {compact_json(v, depth + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, (list, tuple)):
        if all(not isinstance(v, (dict, list, tuple)) for v in value):
            return "[" + ", ".join(json.dumps(v, default=str) for v in value) + "]"
        return "[\n" + ",\n".join(f"{inner}{compact_json(v, depth + 1)}" for v in value) + f"\n{pad}]"
    return json.dumps(value, default=str)


def message_text(message, limit=4000):
    from rosidl_runtime_py.convert import message_to_ordereddict
    text = compact_json(message_to_ordereddict(message, truncate_length=MAX_ARRAY_ITEMS))
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
        self.active_goals = {}
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
                             "clients": ends["clients"].get(name, []),
                             "no_request": request_is_empty(types[0]) if types else None})
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
                self.controllers = {"list": sorted(found, key=lambda c: c["name"]),
                                    "managers": [m.rsplit("/", 1)[0] for m in managers]}
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
            elif cmd == "parameter":
                self.parameter(rid, request["node"], request["name"])
            elif cmd == "cancel":
                for job in list(self.jobs):
                    if job.rid in request.get("ids", []) and job.kind in ("measure", "sample", "plot"):
                        if job.cleanup:
                            job.cleanup()
                        self.jobs.remove(job)
                emit({"type": "reply", "id": rid, "ok": True})
            elif cmd == "hz":
                self.measure(rid, request["name"])
            elif cmd == "sample":
                self.sample(rid, request["name"])
            elif cmd == "tf":
                self.tf_tree(rid)
            elif cmd == "tf_lookup":
                self.tf_lookup(rid, request["source"], request["target"])
            elif cmd == "plot":
                self.plot(rid, request["name"], request["field"])
            elif cmd == "health":
                emit({"type": "reply", "id": rid, **self.health()})
            elif cmd == "template":
                emit({"type": "reply", "id": rid, **self.template(request["kind"], request["type"])})
            elif cmd == "set_parameter":
                self.set_parameter(rid, request["node"], request["name"], request.get("value", ""),
                                   request.get("ptype", 0))
            elif cmd == "lifecycle":
                self.lifecycle_transition(rid, request["node"], request["transition"])
            elif cmd == "lifecycle_group":
                self.lifecycle_group(rid, request.get("nodes", []), request["transition"])
            elif cmd == "call":
                self.call_service(rid, request["name"], request["type"], request.get("value", ""))
            elif cmd == "goal":
                self.send_goal(rid, request["name"], request["type"], request.get("value", ""))
            elif cmd == "cancel_goal":
                goal_id = int(request.get("goal_id", 0))
                handle = self.active_goals.get(goal_id)
                if handle:
                    handle.cancel_goal_async()
                    emit({"type": "reply", "id": rid, "ok": True})
                else:
                    emit({"type": "reply", "id": rid, "error": "That goal is no longer running"})
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
        from rosidl_runtime_py.convert import message_to_ordereddict
        values = message_to_ordereddict(message)
        fields = []
        def walk(msg, value, path):
            types = msg.get_fields_and_field_types()
            for key, val in value.items():
                child = getattr(msg, key)
                if hasattr(child, "get_fields_and_field_types"):
                    walk(child, val, path + [key])
                else:
                    fields.append({"path": path + [key], "type": types[key], "value": val})
        walk(message, values, [])
        return {"text": text, "fields": fields, "values": values}

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
            from rcl_interfaces.srv import ListParameters
            lister = self.node.create_client(ListParameters, f"{full}/list_parameters")
            state = {"values": None, "total": 0}
            waiting.append(lister)
            def on_list(future):
                if future.result() is not None:
                    names = sorted(future.result().result.names)
                    state.update(total=len(names), values=[{"name": name} for name in names])
            lister.call_async(ListParameters.Request()).add_done_callback(on_list)
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

    def parameter(self, rid, node, name):
        from rcl_interfaces.srv import GetParameters
        from rclpy.parameter import parameter_value_to_python
        def result(reply):
            if not reply.values:
                return {"error": "Parameter no longer exists"}
            value = reply.values[0]
            python = parameter_value_to_python(value)
            item = {"name": name, "ptype": value.type, "value": python}
            if isinstance(python, (list, tuple, bytes)):
                item["value"] = list(python[:MAX_ARRAY_ITEMS])
                if len(python) > MAX_ARRAY_ITEMS:
                    item["truncated"] = len(python)
            return item
        self.call(rid, self.node.create_client(GetParameters, f"{node}/get_parameters"),
                  GetParameters.Request(names=[name]), result, "parameter")

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
            span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0
            emit({"type": "reply", "id": rid, "count": len(stamps), "window": HZ_WINDOW_S,
                  "hz": (len(stamps) - 1) / span if span > 0 else 0.0,
                  "bytes_per_s": sum(sizes) / HZ_WINDOW_S,
                  "size": sum(sizes) / len(sizes) if sizes else 0})
            return True
        job = Job(rid, finish, "measure")
        job.cleanup = lambda: self.node.destroy_subscription(sub)
        self.jobs.append(job)

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
        job = Job(rid, finish, "sample")
        job.cleanup = lambda: self.node.destroy_subscription(sub)
        self.jobs.append(job)

    def plot(self, rid, topic, field):
        """One numeric field of a topic over time: progress lines carry the new
        values (at most every PLOT_EVERY_S) until it is cancelled, the panel
        goes away, or PLOT_MAX_S passes."""
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
        if self.busy("plot", 1):
            emit({"type": "reply", "id": rid, "error": "One plot at a time"})
            return
        type_name, message_type = self.message_class(topic)
        if not type_name:
            emit({"type": "reply", "id": rid, "error": message_type})
            return
        path = plot_path(field)
        if path is None:
            emit({"type": "reply", "id": rid, "error": "Choose a numeric field"})
            return
        fresh, state = [], {"count": 0, "error": None}
        start = time.monotonic()

        def on_message(message):
            try:
                value = field_value(message, path)
            except (AttributeError, IndexError, TypeError) as error:
                state["error"] = f"{field}: {error}"
                return
            if isinstance(value, bool):
                value = int(value)
            if isinstance(value, (int, float)):
                fresh.append([round(time.monotonic() - start, 3), value])
                state["count"] += 1
                del fresh[:-PLOT_KEEP]
        # Best effort and volatile match every publisher, as for Hz.
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=10)
        sub = self.node.create_subscription(message_type, topic, on_message, qos)
        state["next"] = start + PLOT_EVERY_S

        def finish():
            now = time.monotonic()
            if fresh and now >= state["next"]:
                emit({"type": "progress", "id": rid, "values": list(fresh), "count": state["count"]})
                fresh.clear()
                state["next"] = now + PLOT_EVERY_S
            if state["error"] or now - start >= PLOT_MAX_S:
                emit({"type": "reply", "id": rid, "count": state["count"],
                      **({"error": state["error"]} if state["error"] else {"ok": True})})
                return True
            return False
        job = Job(rid, finish, "plot")
        job.cleanup = lambda: self.node.destroy_subscription(sub)
        self.jobs.append(job)

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

    def tf_lookup(self, rid, source, target):
        """Resolve a transform between two selected frames without shelling out."""
        if not source or not target or source == target:
            emit({"type": "reply", "id": rid, "error": "Choose two different frames"})
            return
        from tf2_ros import Buffer, TransformListener
        buffer = Buffer()
        listener = TransformListener(buffer, self.node, spin_thread=False)
        deadline = time.monotonic() + REQUEST_TIMEOUT_S

        def finish():
            try:
                transform = buffer.lookup_transform(target, source, self.rclpy.time.Time())
            except Exception as error:
                if time.monotonic() < deadline:
                    return False
                emit({"type": "reply", "id": rid, "error": str(error)})
                return True
            t, q = transform.transform.translation, transform.transform.rotation
            stamp = transform.header.stamp
            # Time 0 means static (or the latest of a static chain).
            age = None
            if stamp.sec or stamp.nanosec:
                age = time.time() - (stamp.sec + stamp.nanosec / 1e9)
            emit({"type": "reply", "id": rid, "ok": True, "source": source, "target": target,
                  "translation": [t.x, t.y, t.z], "rotation": [q.x, q.y, q.z, q.w],
                  "rpy": quaternion_rpy(q.x, q.y, q.z, q.w),
                  "age_ms": round(age * 1000) if age is not None and -1 < age < 3600 else None})
            return True
        job = Job(rid, finish, "tf")
        job.cleanup = lambda: listener.unregister()
        self.jobs.append(job)

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

    def lifecycle_group(self, rid, nodes, transition):
        """Apply one transition to selected nodes and report every outcome."""
        from lifecycle_msgs.msg import Transition
        from lifecycle_msgs.srv import ChangeState
        ids = {"configure": Transition.TRANSITION_CONFIGURE,
               "cleanup": Transition.TRANSITION_CLEANUP,
               "activate": Transition.TRANSITION_ACTIVATE,
               "deactivate": Transition.TRANSITION_DEACTIVATE}
        nodes = sorted({str(node) for node in nodes if str(node).startswith("/")})[:40]
        if transition not in ids or not nodes:
            emit({"type": "reply", "id": rid, "error": "Choose lifecycle nodes and a transition"})
            return
        clients, futures, results = [], {}, {}
        request = ChangeState.Request()
        request.transition.id = ids[transition]
        deadline = time.monotonic() + REQUEST_TIMEOUT_S
        for name in nodes:
            client = self.node.create_client(ChangeState, f"{name}/change_state")
            clients.append(client)
            if client.service_is_ready():
                futures[name] = client.call_async(request)

        def finish():
            for name in nodes:
                if name not in futures:
                    client = clients[nodes.index(name)]
                    if client.service_is_ready():
                        futures[name] = client.call_async(request)
            for name, future in list(futures.items()):
                if future.done() and name not in results:
                    reply = future.result()
                    results[name] = bool(reply and reply.success)
            if len(results) < len(nodes) and time.monotonic() < deadline:
                return False
            for name in nodes:
                results.setdefault(name, False)
            emit({"type": "reply", "id": rid, "ok": all(results.values()), "results": results,
                  **({} if all(results.values()) else {"error": "Some nodes turned the transition down"})})
            return True
        job = Job(rid, finish, "lifecycle")
        job.cleanup = lambda: [self.node.destroy_client(client) for client in clients]
        self.jobs.append(job)

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
            out = {"ok": True, "text": text, "truncated": truncated}
            # std_srvs-style replies say whether the server did it, and why not
            if isinstance(getattr(response, "success", None), bool):
                out["success"] = response.success
            if isinstance(getattr(response, "message", None), str):
                out["message"] = response.message
            return out
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
        state = {"sent": None, "result": None, "feedback": 0, "handle": None}
        deadline = time.monotonic() + GOAL_TIMEOUT_S
        statuses = {1: "accepted", 2: "executing", 3: "canceling", 4: "succeeded", 5: "canceled", 6: "aborted"}

        def on_feedback(message):
            state["feedback"] += 1
            text, truncated = message_text(message.feedback, 1200)
            emit({"type": "progress", "id": rid, "feedback": state["feedback"],
                  "text": text, "truncated": truncated})

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
            if state["handle"] is None:
                state["handle"] = handle
                self.active_goals[rid] = handle
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
        def cleanup():
            self.active_goals.pop(rid, None)
            client.destroy()
        job.cleanup = cleanup
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
        if op in ("configure", "load", "unload"):
            try:
                from controller_manager_msgs import srv
                Configure = getattr(srv, {"configure": "ConfigureController", "load": "LoadController",
                                          "unload": "UnloadController"}[op])
            except ImportError:
                emit({"type": "reply", "id": rid, "error": "controller_manager_msgs is not in this setup"})
                return
            request = Configure.Request(name=name)
            self.call(rid, self.node.create_client(Configure, f"{manager}/{op}_controller"), request,
                      lambda r: {"ok": True} if r.ok else {"error": f"{name} did not {op}"}, "controller")
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


def run_command(command, args, program="ros_info.py"):
    """One one-shot command's reply."""
    try:
        if command == "status":
            return status(refresh=args[:1] == ["refresh"])
        if command == "set" and args and len(args) % 2 == 0:
            return set_values(list(zip(args[::2], args[1::2])))
        if command == "launch" and args:
            return launch(args[0], args[1] if len(args) > 1 else None, args[2:])
        if command == "launch-saved" and len(args) == 1:
            return launch_saved(args[0])
        if command == "save-launch" and len(args) >= 2:
            return save_launch(args[0], args[1], args[2:])
        if command == "forget-launch" and len(args) == 1:
            return forget_launch(args[0])
        if command == "launch-args" and len(args) == 1:
            return launch_arguments(args[0])
        if command == "build":
            return workspace_build([a for a in args if a != "--up-to"], "--up-to" in args)
        if command == "log-tail" and args:
            return log_tail(args[0], args[1] if len(args) > 1 else "",
                            args[2] if len(args) > 2 else "all", args[3] if len(args) > 3 else 120)
        if command == "run-control" and len(args) == 2:
            return control_run(args[0], args[1])
        if command == "plot" and len(args) == 1:
            return plot_topic(args[0])
        if command == "plotjuggler":
            return plotjuggler(args)
        if command == "plotjuggler-confirm" and len(args) == 1:
            return plotjuggler_confirm(int(args[0]))
        if command == "stop" and args:
            return stop(args[0])
        if command == "runs":
            return runs()
        if command == "terminal":
            return terminal()
        if command == "install-gazebo":
            return install_gazebo()
        if command == "favorite" and len(args) == 2:
            return toggle_favorite(args[0], args[1])
        if command == "bag-start" and args:
            return bag_start(args)
        if command == "bag-play" and args:
            offset = next((a.split("=", 1)[1] for a in args[2:] if a.startswith("start=")), 0)
            return bag_play(args[0], args[1] if len(args) > 1 else 1.0,
                            "loop" in args[2:], "clock" in args[2:], offset)
        if command == "bag-info" and args:
            return bag_details(args[0], remember="remember" in args[1:])
        if command == "bag-forget" and len(args) == 1:
            return forget_bag(args[0])
        if command == "bag-choose":
            return choose_bag()
        if command == "bag-control" and len(args) == 1:
            return bag_control(args[0])
        if command == "save-setup" and len(args) == 1:
            return save_setup(args[0])
        if command == "use-setup" and len(args) == 1:
            return use_setup(args[0])
        if command == "forget-setup" and len(args) == 1:
            return forget_setup(args[0])
        if command == "save-robot-profile" and args:
            return save_robot_profile(args[0], args[1] if len(args) > 1 else "")
        if command == "use-robot-profile" and len(args) == 1:
            return use_robot_profile(args[0])
        if command == "forget-robot-profile" and len(args) == 1:
            return forget_robot_profile(args[0])
        if command == "parameter-profile" and len(args) == 3:
            return parameter_profile(args[0], args[1], args[2])
        if command == "open-log" and len(args) == 1:
            return open_log(args[0])
        if command == "pkg-catalog":
            return package_catalog()
        if command == "pkg-create" and len(args) == 1:
            return create_package(json.loads(args[0]))
        if command == "pkg-install-deps" and len(args) == 1:
            return install_package_dependencies(args[0])
        return {"ok": False, "error": f"usage: see the top of {program}"}
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # The shell reads stdout as JSON, whatever happened.
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}


def sentence(command, result):
    """A reply as one line for a notification (`say`, for the command palette)."""
    if result.get("ok") is False:
        return result.get("error") or "It did not work"
    if command in ("launch", "launch-saved"):
        return "Started"
    if command == "stop":
        count = result.get("stopped", 0)
        return f"Stopped {count} run{'s' if count != 1 else ''}" if count else "Nothing started here was running"
    if command == "bag-start":
        return f"Recording to {result.get('path', '').replace(str(HOME), '~')}"
    if command == "bag-play":
        return f"Playing {Path(result.get('path', '')).name}"
    if command == "build":
        return "Building"
    if command == "pkg-create":
        return f"Created {result.get('name')} in {result.get('path', '').replace(str(HOME), '~')}"
    if command in ("run-control", "bag-control"):
        return "Paused" if result.get("paused") else "Resumed"
    if command == "use-robot-profile" and result.get("profile"):
        return f"Using robot profile {result['profile']['name']}"
    if command in ("set", "use-setup") and result.get("installed"):
        named = next((w["name"] for w in result.get("workspaces", []) if w["path"] == result.get("workspace")), "none")
        return (f"Domain {result['domain']}, {'this computer only' if result['localhost'] else 'whole network'}, "
                f"{result.get('rmw_name', '')}, workspace {named}")
    return "Done"


def main(argv):
    command = argv[1] if len(argv) > 1 else "status"
    args = argv[2:]
    if command == "watch":
        return watch()
    if command == "run" and len(args) >= 4 and args[2] == "--":
        return supervise(args[0], args[1], args[3:])
    if command == "say" and args:
        result = run_command(args[0], args[1:], argv[0])
        print(sentence(args[0], result), flush=True)
    else:
        result = run_command(command, args, argv[0])
        emit(result)
    return 1 if result.get("ok") is False else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
