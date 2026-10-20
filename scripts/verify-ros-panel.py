#!/usr/bin/env python3
"""The ROS 2 panel's helper (shell/.../tools/ros_info.py) against real nodes.

A throwaway home with its own ~/.bashrc, workspace and RViz config, and demo
nodes (a talker, a lifecycle talker, an action server) on a private domain
with localhost-only discovery, so nothing here sees or disturbs a real robot.
Checks the setup read from ~/.bashrc, settings, the live graph, node details,
type definitions, topic rate, launching and stopping, and that the watcher
exits when its stdin closes. Skips without ROS 2 under /opt/ros. About 20 s.
"""

import glob
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "shell" / "adaptive-shell@local" / "tools" / "ros_info.py"
DOMAIN = 88

failures = 0


def check(ok, what, detail=""):
    global failures
    print(f"{'OK  ' if ok else 'FAIL'} {what}{'' if ok or not detail else f' ({detail})'}")
    if not ok:
        failures += 1


def helper(env, *args):
    out = subprocess.run([sys.executable, str(HELPER), *args], env=env,
                         capture_output=True, text=True, timeout=30).stdout
    return json.loads(out)


class Watch:
    def __init__(self, env):
        self.proc = subprocess.Popen([sys.executable, str(HELPER), "watch"], env=env, text=True,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.graph = None
        self.replies = {}
        self.next_id = 1

    def read(self, until, timeout):
        """Reads lines until `until()` holds or `timeout` passes."""
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(self.proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        while not until() and time.monotonic() < deadline:
            if not selector.select(timeout=max(0, deadline - time.monotonic())):
                break
            line = self.proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message["type"] == "graph":
                self.graph = message
            elif message["type"] == "reply":
                self.replies[message["id"]] = message
            elif message["type"] == "error":
                print("watch error:", message["error"])
        return until()

    def ask(self, cmd, timeout=6, **fields):
        rid = self.next_id
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"id": rid, "cmd": cmd, **fields}) + "\n")
        self.proc.stdin.flush()
        self.read(lambda: rid in self.replies, timeout)
        return self.replies.get(rid, {"error": "no reply"})


def nodes_named(watch):
    return [n["name"] for n in (watch.graph or {}).get("nodes", [])]


def main():
    setups = sorted(glob.glob("/opt/ros/*/setup.bash"))
    if not setups:
        print("SKIP ROS 2 is not installed")
        return 0
    setup = setups[-1]
    lib = Path(setup).parent / "lib"

    home = Path(tempfile.mkdtemp(prefix="adaptive-ros-"))
    ws = home / "robot_ws"
    (ws / "install").mkdir(parents=True)
    (ws / "install" / "setup.bash").write_text("# an empty overlay\n")
    (ws / "src" / "bringup" / "config").mkdir(parents=True)
    (ws / "src" / "bringup" / "config" / "robot.rviz").write_text("Panels: []\n")
    (ws / "src" / "bringup" / "worlds").mkdir(parents=True)
    (ws / "src" / "bringup" / "worlds" / "yard.sdf").write_text("<sdf/>\n")
    (home / ".bashrc").write_text(
        f"[ -f {setup} ] && source {setup}\n"
        f"export ROS_DOMAIN_ID={DOMAIN}   # comment\n"
        "export ROS_LOCALHOST_ONLY=1\n"
        f"source {ws}/install/setup.bash\n"
        "alias other='export ROS_DOMAIN_ID=5'\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ROS_", "AMENT_", "RMW_"))}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"),
               SHELL="/bin/bash")

    # ---------------------------------------------------------- setup
    status = helper(env, "status")
    check(status.get("installed") is True, "status: ROS 2 is found")
    check(status.get("domain") == DOMAIN and status["from"]["domain"] == "shell"
          and status.get("shell_rc") == "~/.bashrc",
          "status: the domain comes from ~/.bashrc, not from an alias", status.get("domain"))
    check(status.get("localhost") is True, "status: localhost-only comes from ~/.bashrc")
    check(status.get("workspace") == str(ws), "status: the workspace ~/.bashrc sources is used",
          status.get("workspace"))
    check([w["name"] for w in status.get("workspaces", [])] == ["robot_ws"], "status: workspaces are found")
    check([c["name"] for c in status.get("rviz_configs", [])] == ["robot.rviz"], "status: RViz configs are found")
    check([w["name"] for w in status.get("worlds", [])] == ["yard.sdf"], "status: worlds are found")
    check(status["tools"]["rviz2"]["installed"] is True, "status: RViz2 is installed")
    check(not status["tools"]["demo"]["pids"], "status: nothing of ours is running yet")

    check(helper(env, "set", "domain", "500").get("ok") is False, "set: a domain over 232 is refused")
    check(helper(env, "set", "rmw", "rmw_nonexistent").get("ok") is False, "set: a missing middleware is refused")
    check(helper(env, "set", "workspace", str(home)).get("ok") is False, "set: a folder that is no workspace is refused")
    changed = helper(env, "set", "domain", str(DOMAIN + 1))
    check(changed.get("domain") == DOMAIN + 1 and changed["from"]["domain"] == "panel", "set: the panel's domain wins")
    reset = helper(env, "set", "all", "")
    check(reset.get("domain") == DOMAIN and reset["from"]["domain"] == "shell", "set: all '' follows ~/.bashrc again")
    both = helper(env, "set", "domain", "7", "localhost", "0")
    check(both.get("domain") == 7 and both.get("localhost") is False, "set: several pairs at once", both)
    rejected = helper(env, "set", "domain", "8", "rmw", "rmw_nonexistent")
    after_rejected = helper(env, "status")
    check(rejected.get("ok") is False and after_rejected.get("domain") == 7,
          "set: a rejected batch changes nothing", rejected)
    helper(env, "set", "all", "")

    # A Zsh login reads ~/.zshrc, and a workspace sourced through a variable from a
    # build tree inside a dot-folder is still found and named.
    lab = home / "lab" / ".build" / "humble"
    (lab / "install").mkdir(parents=True)
    (lab / "install" / "setup.bash").write_text("# an empty overlay\n")
    (home / ".zshrc").write_text(
        f"source {setup[:-len('bash')]}zsh\n"
        '_lab="$HOME/lab/.build/humble/install/local_setup.zsh"\n'
        '[[ -r "$_lab" ]] && source "$_lab"\n')
    zsh = helper(env | {"SHELL": "/usr/bin/zsh"}, "status")
    check(zsh.get("domain") == 0 and zsh.get("localhost") is False and zsh.get("shell_rc") == "~/.zshrc",
          "status: a Zsh login follows ~/.zshrc, not ~/.bashrc", zsh.get("domain"))
    check(zsh.get("workspace") == str(lab) and zsh["from"]["workspace"] == "shell"
          and {"name": "lab", "path": str(lab)} in zsh.get("workspaces", []),
          "status: a workspace ~/.zshrc sources through a variable is used and named", zsh.get("workspace"))
    (home / ".zshrc").unlink()

    # Imported here, after HOME points at the throwaway home: it reads HOME once.
    os.environ.update(SHELL="/bin/bash", HOME=env["HOME"], XDG_CONFIG_HOME=env["XDG_CONFIG_HOME"], XDG_CACHE_HOME=env["XDG_CACHE_HOME"])
    sys.path.insert(0, str(HELPER.parent))
    import ros_info
    samples = {
        ("/opt/ros/humble/lib/rviz2/rviz2", "-d", "x.rviz"): "rviz2",
        ("/usr/bin/python3", "/opt/ros/humble/bin/rqt_graph"): "rqt_graph",
        ("ruby", "/usr/bin/ign", "gazebo", "-g"): "gazebo",
        ("gzserver", "w.world"): "gazebo",
        ("/usr/bin/python3", "/opt/ros/humble/bin/ros2", "launch", "ros_gz_sim", "gz_sim.launch.py"): "gazebo",
        ("/opt/ros/humble/lib/demo_nodes_cpp/talker",): "demo",
        ("/usr/bin/python3", "/opt/ros/humble/bin/ros2", "topic", "echo", "/x"): None,
        ("vim", "rviz2.txt"): None,
    }
    wrong = {argv: ros_info.tool_of(list(argv)) for argv, tool in samples.items()
             if ros_info.tool_of(list(argv)) != tool}
    check(not wrong, "running tools are told apart by their command lines", wrong)

    # ---------------------------------------------------------- watch
    node_env = ros_info.ros_env({"distro": Path(setup).parent.name, "workspace": "", "domain": DOMAIN,
                                 "localhost": True, "rmw": "", "rmw_set": False}) | {"HOME": str(home)}
    nodes = [subprocess.Popen(argv, env=node_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for argv in ([str(lib / "demo_nodes_cpp" / "talker")],
                          [str(lib / "lifecycle" / "lifecycle_talker")],
                          [sys.executable, str(lib / "action_tutorials_py" / "fibonacci_action_server")])]
    # Started like from a terminal (no panel mark) on another domain: the panel offers to follow it.
    stray_env = {k: v for k, v in node_env.items() if k != ros_info.ENV_MARK} | {"ROS_DOMAIN_ID": str(DOMAIN + 3)}
    nodes.append(subprocess.Popen([str(lib / "demo_nodes_cpp" / "listener")], env=stray_env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.5)
    elsewhere = helper(env, "status").get("elsewhere", [])
    check(any(item.get("domain") == DOMAIN + 3 and item.get("localhost") is True and
              item.get("rmw") == "rmw_fastrtps_cpp" and item.get("count") == 1 for item in elsewhere),
          "status: a ROS process on another domain is reported with its middleware", elsewhere)
    watch = Watch(env)
    try:
        want = {"/talker", "/lc_talker", "/fibonacci_action_server"}
        seen = watch.read(lambda: want <= set(nodes_named(watch)), 15)
        check(seen, "watch: the graph lists the running nodes", nodes_named(watch))
        graph = watch.graph or {"nodes": [], "topics": [], "actions": [], "hidden": {}}
        check(not any(n.startswith("/_") for n in nodes_named(watch)) and graph["hidden"].get("nodes", 0) >= 1,
              "watch: its own node is hidden")
        talker = next((n for n in graph["nodes"] if n["name"] == "/talker"), {})
        check(any(t["name"] == "/chatter" and t["types"] == ["std_msgs/msg/String"]
                  for t in talker.get("publishers", [])), "watch: a node lists what it publishes, with types")
        check(any(a["name"] == "/fibonacci" and a["servers"] == ["/fibonacci_action_server"]
                  for a in graph["actions"]), "watch: actions list their server")
        check(not any(t["name"].startswith("/fibonacci/_action") for t in graph["topics"]),
              "watch: an action's hidden topics are left out")
        check(next((n["lifecycle"] for n in graph["nodes"] if n["name"] == "/lc_talker"), False),
              "watch: a lifecycle node is marked")

        detail = watch.ask("node", name="/talker")
        names = [p["name"] for p in detail.get("parameters") or []]
        check("use_sim_time" in names, "node: parameters are read", detail.get("error") or names)
        check(detail.get("qos", {}).get("publishers:/chatter") == {"reliability": "reliable", "durability": "volatile"},
              "node: QoS of what it publishes", detail.get("qos"))
        lifecycle = watch.ask("node", name="/lc_talker")
        check(lifecycle.get("lifecycle") == "unconfigured", "node: a lifecycle node's state",
              lifecycle.get("lifecycle"))
        gone = watch.ask("node", name="/not_running")
        check(gone.get("error") == "This node is no longer running", "node: a node that is gone says so")

        definition = watch.ask("interface", type="geometry_msgs/msg/PoseStamped").get("text") or ""
        check("std_msgs/Header header" in definition and "\t\tfloat64 x" in definition,
              "interface: nested types are shown indented", definition[:80])
        check(watch.ask("interface", type="no_such_msgs/msg/Nothing").get("error") == "Not found in this setup",
              "interface: an unknown type says so")

        topic = watch.ask("topic", name="/chatter")
        check([p["node"] for p in topic.get("publishers", [])] == ["/talker"], "topic: who publishes it, with QoS")
        rate = watch.ask("hz", name="/chatter", timeout=8)
        check(0.5 < rate.get("hz", 0) < 1.6 and rate.get("bytes_per_s", 0) > 0,
              "hz: the talker's rate is about 1 Hz", rate)
        check(watch.ask("hz", name="/nobody").get("error") == "Nobody publishes it now", "hz: an empty topic says so")
        check(not any(s["node"].startswith("/_") for s in watch.ask("topic", name="/chatter").get("subscribers", [])),
              "topic: the panel's own measuring is not listed")

        for proc in nodes:
            proc.send_signal(signal.SIGINT)
        left = watch.read(lambda: not (want & set(nodes_named(watch))), 20)
        check(left, "watch: nodes that stop leave the graph", nodes_named(watch))

        watch.proc.stdin.close()
        try:
            watch.proc.wait(5)
            check(True, "watch: exits when its stdin closes")
        except subprocess.TimeoutExpired:
            check(False, "watch: exits when its stdin closes")
    finally:
        for proc in [*nodes, watch.proc]:
            if proc.poll() is None:
                proc.kill()

    # ---------------------------------------------------------- launch
    external = subprocess.Popen([str(lib / "demo_nodes_cpp" / "talker")], env=node_env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    refused_stop = helper(env, "stop", "demo")
    check(refused_stop.get("stopped") == 0 and external.poll() is None,
          "stop: a demo started outside the panel is left alone", refused_stop)
    external.send_signal(signal.SIGINT)
    external.wait(5)

    launched = helper(env, "launch", "demo")
    check(launched.get("ok") is True and len(launched.get("pids", [])) == 2, "launch: the demo starts", launched)
    time.sleep(1)
    check(sorted(helper(env, "status")["tools"]["demo"]["pids"]) == sorted(launched.get("pids", [])),
          "status: the demo is seen running")
    stopped = helper(env, "stop", "demo")
    check(stopped.get("stopped") == 2 and not helper(env, "status")["tools"]["demo"]["pids"], "stop: the demo quits")
    check(helper(env, "launch", "nonsense").get("ok") is False, "launch: an unknown tool is refused")
    rc = ros_info.terminal_rc(ros_info.settings()).read_text()
    check(f"export ROS_DOMAIN_ID={DOMAIN}" in rc and "export ROS_LOCALHOST_ONLY=1" in rc and str(ws) in rc
          and rc.index(".zshrc") < rc.index("ROS_DOMAIN_ID"),
          "terminal: KTERM Zsh first, then the panel's setup")

    subprocess.run(["rm", "-rf", str(home)])
    print(f"\n{failures} check(s) failed" if failures else "\nAll ROS panel checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
