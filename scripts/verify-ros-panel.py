#!/usr/bin/env python3
"""The ROS 2 panel's helper (shell/.../tools/ros_info.py) against real nodes.

A throwaway home with its own ~/.bashrc, workspace, RViz config and launch
file, and real nodes (a talker, a lifecycle talker, an action server, a
service, a static transform, and FIXTURE below) on a private domain with
localhost-only discovery, so nothing here sees or disturbs a real robot.
Checks the setup read from ~/.bashrc, settings, saved setups and launches, the
live graph, diagnostics, node details, type definitions, topic rate, previews
(an image too), the TF tree, QoS mismatches, every write (parameter, lifecycle,
service call, action goal, one message), rosbag, launching, stopping and how
runs ended, and that the watcher exits when its stdin closes. Skips without
ROS 2 under /opt/ros. About 40 s.
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

# One node with what the demos lack: /diagnostics from two separate messages,
# an image published best effort that its own reliable subscriber cannot get
# (a QoS mismatch), a moving TF frame, a typed parameter, and a topic whose
# messages land in a parameter, so a published message can be seen arriving.
FIXTURE = r"""
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from geometry_msgs.msg import TransformStamped
from sensor_msgs.msg import Image
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage

rclpy.init()
node = Node("fixture")
node.declare_parameter("gain", 1.5)
node.declare_parameter("last_command", "")
diagnostics = node.create_publisher(DiagnosticArray, "/diagnostics", 10)
image = node.create_publisher(Image, "/camera/image", QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT))
node.create_subscription(Image, "/camera/image", lambda m: None, QoSProfile(depth=5, reliability=ReliabilityPolicy.RELIABLE))
tf = node.create_publisher(TFMessage, "/tf", 10)
node.create_subscription(String, "/fixture/command",
                         lambda m: node.set_parameters([Parameter("last_command", value=m.data)]), 10)


def tick():
    for name, level in (("motor", 2), ("battery", 0)):
        diagnostics.publish(DiagnosticArray(status=[DiagnosticStatus(
            name=name, level=bytes([level]), message="overheated" if level else "fine")]))
    now = node.get_clock().now().to_msg()
    shot = Image(width=8, height=6, encoding="rgb8", step=24, data=bytes(range(144)))
    shot.header.stamp = now
    image.publish(shot)
    move = TransformStamped()
    move.header.frame_id, move.child_frame_id, move.header.stamp = "world", "base_link", now
    tf.publish(TFMessage(transforms=[move]))


node.create_timer(0.1, tick)
try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
"""


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
    (ws / "src" / "bringup" / "launch").mkdir(parents=True)
    robot_launch = ws / "src" / "bringup" / "launch" / "robot.launch.py"
    robot_launch.write_text(
        "from launch import LaunchDescription\n"
        "from launch.actions import ExecuteProcess\n\n\n"
        "def generate_launch_description():\n"
        "    return LaunchDescription([ExecuteProcess(cmd=['sleep', '60'])])\n")
    (home / ".bashrc").write_text(
        f"[ -f {setup} ] && source {setup}\n"
        f"export ROS_DOMAIN_ID={DOMAIN}   # comment\n"
        "export ROS_LOCALHOST_ONLY=1\n"
        f"source {ws}/install/setup.bash\n"
        "alias other='export ROS_DOMAIN_ID=5'\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ROS_", "AMENT_", "RMW_"))}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"),
               XDG_DATA_HOME=str(home / ".local" / "share"), SHELL="/bin/bash", ADAPTIVE_ROS_PROJECT="")

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
    check([f["name"] for f in status.get("launch_files", [])] == ["robot.launch.py"],
          "status: launch files in the workspace are found")
    (ws / "src" / "bringup" / "config" / "arm.rviz").write_text("Panels: []\n")
    check(len(helper(env, "status")["rviz_configs"]) == 1 and len(helper(env, "status", "refresh")["rviz_configs"]) == 2,
          "status: the file search is kept a while, and refresh walks again")
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

    # Project Context's active project (stood in for here) holds a workspace.
    project_env = env | {"ADAPTIVE_ROS_PROJECT": str(home / "lab")}
    suggested = helper(project_env, "status")
    check((suggested.get("project") or {}).get("workspace") == str(lab) and suggested.get("workspace") == str(ws),
          "status: the active project's workspace is offered, not used", suggested.get("project"))
    helper(project_env, "set", "follow_project", "1")
    followed = helper(project_env, "status")
    check(followed.get("workspace") == str(lab) and followed["from"]["workspace"] == "project",
          "status: following the project uses its workspace", followed.get("workspace"))
    helper(env, "set", "all", "")

    # Saved robot setups and saved launches.
    helper(env, "set", "domain", "12")
    check(helper(env, "save-setup", "../bad").get("ok") is False, "setups: a bad name is refused")
    check(helper(env, "save-setup", "Arm bench").get("ok") is True, "setups: the current setup is saved")
    helper(env, "set", "all", "")
    used = helper(env, "use-setup", "Arm bench")
    check(used.get("domain") == 12 and used.get("localhost") is True, "setups: using one applies it", used.get("domain"))
    check(helper(env, "forget-setup", "Arm bench").get("setups") == [], "setups: forgotten")
    said = subprocess.run([sys.executable, str(HELPER), "say", "use-setup", "Arm bench"], env=env,
                          capture_output=True, text=True)
    check(said.returncode == 1 and said.stdout.strip() == "No saved setup is called Arm bench",
          "say: the palette gets a sentence and a failing exit code", said.stdout)
    helper(env, "set", "all", "")
    check(helper(env, "save-launch", "Robot", str(robot_launch), "--launch-prefix=gdb").get("ok") is False,
          "launches: only name:=value arguments are taken")
    check(helper(env, "save-launch", "Robot", str(home / ".bashrc")).get("ok") is False,
          "launches: a file that is no launch file is refused")
    saved = helper(env, "save-launch", "Robot", str(robot_launch), "rate:=5")
    check([(s["name"], s["args"]) for s in saved.get("saved_launches", [])] == [("Robot", ["rate:=5"])],
          "launches: saved with its arguments", saved)

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
        ("/usr/bin/python3", "/opt/ros/humble/bin/ros2", "launch", "/ws/src/b/launch/robot.launch.py"): "launch",
        ("/usr/bin/python3", "/opt/ros/humble/bin/ros2", "bag", "record", "-a"): "bag",
        ("/usr/bin/python3", str(HELPER), "run", "demo", "{}", "--", "/opt/ros/humble/lib/demo_nodes_cpp/talker"): None,
        ("/usr/bin/python3", "/opt/ros/humble/bin/ros2", "topic", "echo", "/x"): None,
        ("vim", "rviz2.txt"): None,
    }
    wrong = {argv: ros_info.tool_of(list(argv)) for argv, tool in samples.items()
             if ros_info.tool_of(list(argv)) != tool}
    check(not wrong, "running tools are told apart by their command lines", wrong)

    # ---------------------------------------------------------- watch
    node_env = ros_info.ros_env({"distro": Path(setup).parent.name, "workspace": "", "domain": DOMAIN,
                                 "localhost": True, "rmw": "", "rmw_set": False}) | {"HOME": str(home)}
    fixture = home / "fixture.py"
    fixture.write_text(FIXTURE)
    nodes = [subprocess.Popen(argv, env=node_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for argv in ([str(lib / "demo_nodes_cpp" / "talker")],
                          [str(lib / "lifecycle" / "lifecycle_talker")],
                          [sys.executable, str(lib / "action_tutorials_py" / "fibonacci_action_server")],
                          [str(lib / "demo_nodes_cpp" / "add_two_ints_server")],
                          [str(lib / "tf2_ros" / "static_transform_publisher"), "--z", "0.1",
                           "--frame-id", "base_link", "--child-frame-id", "camera_link"],
                          [sys.executable, str(fixture)])]
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

        # ------------------------------------------------------ the rest of the panel
        watch.read(lambda: "/fixture" in nodes_named(watch) and
                   len(((watch.graph or {}).get("diagnostics") or {}).get("items", [])) >= 2, 10)
        graph = watch.graph or {}
        check(not [t["name"] for t in graph.get("topics", []) if not t["publishers"] and not t["subscribers"]],
              "watch: no topic only the panel itself uses (its /diagnostics) is listed")
        diagnostics = {d["name"]: d["level"] for d in (graph.get("diagnostics") or {}).get("items", [])}
        check(diagnostics == {"motor": 2, "battery": 0} and graph["diagnostics"]["counts"]["error"] == 1,
              "diagnostics: statuses from separate messages are merged, with their levels", diagnostics)

        preview = watch.ask("sample", name="/chatter")
        check("Hello World" in preview.get("text", ""), "sample: the next message is shown", preview)
        shot = watch.ask("sample", name="/camera/image")
        check(shot.get("image_width") == 8 and Path(shot.get("image", "/none")).read_bytes()[:4] == b"\x89PNG"
              and 0 <= shot.get("age_ms", -1) < 2000, "sample: an image becomes a thumbnail, with its age", shot)

        tf = watch.ask("tf")
        frames = {f["child"]: f for f in tf.get("frames", [])}
        check(frames.get("camera_link", {}).get("static") is True and frames["camera_link"]["parent"] == "base_link"
              and 5 < frames.get("base_link", {}).get("hz", 0) < 15 and tf.get("roots") == ["world"],
              "tf: static and moving frames, their parents, rate and the root", tf)

        mismatch = watch.ask("topic", name="/camera/image").get("qos_warnings", [])
        check(mismatch == ["/fixture is best effort but /fixture requires reliable"],
              "topic: a QoS mismatch is named", mismatch)
        check([q["topic"] for q in watch.ask("health").get("qos", [])] == ["/camera/image"],
              "health: QoS mismatches across the graph")

        fixture_params = {p["name"]: p for p in watch.ask("node", name="/fixture").get("parameters") or []}
        gain = fixture_params.get("gain", {})
        check(gain.get("ptype") == 3, "node: parameters carry their type", gain)
        refused = watch.ask("set_parameter", node="/fixture", name="gain", value="fast", ptype=3)
        check("Expected a number" in refused.get("error", ""), "set_parameter: a wrong value is refused here", refused)
        check(watch.ask("set_parameter", node="/fixture", name="gain", value="2", ptype=3).get("ok") is True,
              "set_parameter: '2' is taken for a double parameter")
        after = {p["name"]: p["value"] for p in watch.ask("node", name="/fixture").get("parameters") or []}
        check(after.get("gain") == 2.0 and isinstance(after.get("gain"), float), "set_parameter: the node has 2.0",
              after.get("gain"))

        configured = watch.ask("lifecycle", node="/lc_talker", transition="configure")
        check(configured.get("ok") is True and watch.ask("node", name="/lc_talker").get("lifecycle") == "inactive",
              "lifecycle: configure moves the node to inactive", configured)

        template = watch.ask("template", kind="service", type="example_interfaces/srv/AddTwoInts")
        check('"a": 0' in template.get("text", ""), "template: an empty request to start from", template)
        called = watch.ask("call", timeout=12, name="/add_two_ints", type="example_interfaces/srv/AddTwoInts",
                           value="{a: 2, b: 3}")
        check('"sum": 5' in called.get("text", ""), "call: a service answers", called)
        check("mapping" in watch.ask("call", name="/add_two_ints", type="example_interfaces/srv/AddTwoInts",
                                     value="[1, 2]").get("error", ""), "call: fields that are no mapping are refused")
        goal = watch.ask("goal", timeout=35, name="/fibonacci",
                         type="action_tutorials_interfaces/action/Fibonacci", value="{order: 3}")
        check(goal.get("status") == "succeeded" and "sequence" in goal.get("text", ""),
              "goal: an action goal runs to its result", goal)
        sent = watch.ask("publish", name="/fixture/command", type="std_msgs/msg/String", value="{data: go}")
        time.sleep(0.5)
        last = {p["name"]: p["value"] for p in watch.ask("node", name="/fixture").get("parameters") or []}
        check(sent.get("ok") is True and sent.get("subscribers") == 1 and last.get("last_command") == "go",
              "publish: one message arrives", (sent, last.get("last_command")))

        # rosbag, while the talker still talks.
        recorded = helper(env, "bag-start", "/chatter")
        check(recorded.get("ok") is True, "bag: recording starts", recorded)
        check(helper(env, "bag-start", "/chatter").get("ok") is False, "bag: one recording at a time")
        time.sleep(2.5)
        check((helper(env, "runs").get("recording") or {}).get("size", 0) > 0, "bag: the recording grows")
        helper(env, "stop", "bag")
        bags = helper(env, "status").get("bags", [])
        check(len(bags) == 1 and bags[0].get("messages", 0) >= 1 and bags[0].get("topics") == 1,
              "bag: the stopped recording is listed with its messages and topics", bags)

        for proc in nodes:
            proc.send_signal(signal.SIGINT)
        left = watch.read(lambda: not (want & set(nodes_named(watch))), 20)
        check(left, "watch: nodes that stop leave the graph", nodes_named(watch))
        watch.read(lambda: not (watch.graph or {}).get("topics"), 5)
        check(not watch.graph.get("topics"), "watch: with every node gone no topic is left, the panel's own neither",
              [t["name"] for t in watch.graph.get("topics", [])])

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
    demo = helper(env, "status")["tools"]["demo"]
    check(len(demo["pids"]) == 2 and sorted(demo["owned_pids"]) == sorted(demo["pids"]),
          "status: the demo is seen running, as started here", demo)
    stopped = helper(env, "stop", "demo")
    check(stopped.get("stopped") == 2 and not helper(env, "status")["tools"]["demo"]["pids"], "stop: the demo quits")
    ended = [h for h in helper(env, "runs")["history"] if h["tool"] == "demo"]
    check(len(ended) == 2 and all(h["stopped"] and not h["crashed"] for h in ended),
          "runs: a stopped run is not called a crash", ended)
    check(helper(env, "launch", "nonsense").get("ok") is False, "launch: an unknown tool is refused")

    # The supervisor on its own: an exit by itself, with a code, is a crash.
    subprocess.run([sys.executable, str(HELPER), "run", "launch", '{"name": "flaky"}', "--",
                    "bash", "-c", "exit 3"], env=env)
    last = helper(env, "runs")["history"][0]
    check(last["returncode"] == 3 and last["crashed"] and last["meta"]["name"] == "flaky",
          "runs: a run that exits by itself with an error is a crash", last)

    saved_run = helper(env, "launch-saved", "Robot")
    time.sleep(1)
    running_launch = helper(env, "runs")["running"].get("launch", [])
    check(saved_run.get("ok") is True and running_launch and running_launch[0]["meta"]["args"] == ["rate:=5"],
          "launch: a saved launch runs with its arguments", (saved_run, running_launch))
    helper(env, "stop", "launch")
    check(not helper(env, "status")["tools"]["launch"]["pids"], "stop: the launch and what it started quit")
    rc = ros_info.terminal_rc(ros_info.settings()).read_text()
    check(f"export ROS_DOMAIN_ID={DOMAIN}" in rc and "export ROS_LOCALHOST_ONLY=1" in rc and str(ws) in rc
          and rc.index(".zshrc") < rc.index("ROS_DOMAIN_ID"),
          "terminal: KTERM Zsh first, then the panel's setup")

    subprocess.run(["rm", "-rf", str(home)])
    print(f"\n{failures} check(s) failed" if failures else "\nAll ROS panel checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
