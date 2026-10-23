#!/usr/bin/env python3
"""The ROS 2 panel's New package dialog, end to end through its helper.

In a throwaway home: `pkg-catalog` (templates, installed and missing
dependencies, where a package may go), `pkg-create` refusing what it must
(bad names, existing packages, anything outside ~/ros2_ws/src, a symlink out of
it), then one package from every template, all built with colcon and run: the
C++ and Python nodes and the component log, the interfaces exist, the launch
file loads, and every package passes its own tests (the ROS linters). A last package is built through the panel's own build (`build`:
true) and made the panel's workspace. Nodes run on a private domain with
localhost-only discovery. Skips without ROS 2 or colcon. About four minutes.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "shell" / "adaptive-shell@local" / "tools" / "ros_info.py"
DOMAIN = 86
failures = 0


def check(ok, what, detail=""):
    global failures
    print(f"{'OK  ' if ok else 'FAIL'} new package: {what}" + ("" if ok else f"  {str(detail)[:600]}"))
    failures += 0 if ok else 1


def helper(env, *args):
    done = subprocess.run([sys.executable, str(HELPER), *args], env=env, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"ok": False, "error": done.stderr[-600:]}


def create(env, **spec):
    return helper(env, "pkg-create", json.dumps(spec))


def main():
    distros = sorted(p.name for p in Path("/opt/ros").glob("*") if (p / "setup.bash").is_file())
    if not distros or not shutil.which("colcon"):
        print("SKIP new package: ROS 2 or colcon is not installed")
        return 0
    distro = distros[-1]
    home = Path(tempfile.mkdtemp(prefix="ros-newpkg-", dir=os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "XDG_"))
           and k not in ("CMAKE_PREFIX_PATH", "PYTHONPATH", "LD_LIBRARY_PATH")}
    env.update(HOME=str(home), SHELL="/bin/bash", ROS_DOMAIN_ID=str(DOMAIN), ROS_LOCALHOST_ONLY="1")
    (home / ".bashrc").write_text(f"export ROS_DOMAIN_ID={DOMAIN}\nexport ROS_LOCALHOST_ONLY=1\n")
    ws = home / "ros2_ws"
    try:
        catalog = helper(env, "pkg-catalog")
        check(catalog.get("ok") and len(catalog["templates"]) == 8 and catalog["workspace"] == str(ws),
              "the catalog has every template and ~/ros2_ws", catalog.get("error"))
        rows = {r["name"]: r for r in catalog.get("packages", [])}
        check(rows.get("rclcpp", {}).get("installed") and rows["rclcpp"]["cmake"] and rows["rclcpp"]["category"] == "Core",
              "rclcpp is installed, CMake-capable, under Core", rows.get("rclcpp"))
        check(rows.get("launch_ros", {}).get("installed") and not rows["launch_ros"]["cmake"],
              "launch_ros is Python only (a run-time dependency for CMake packages)", rows.get("launch_ros"))
        check(any(r["category"] == "Other installed" for r in rows.values()), "everything else installed is offered")
        check([l["name"] for l in catalog.get("locations", [])] == ["src"], "a new workspace offers src only",
              catalog.get("locations"))

        refused = {
            "upper case": {"name": "MyPkg", "template": "empty_cmake"},
            "a leading digit": {"name": "1pkg", "template": "empty_cmake"},
            "a double underscore": {"name": "my__pkg", "template": "empty_cmake"},
            "a Python keyword": {"name": "class", "template": "empty_python"},
            "a path outside the workspace": {"name": "outside", "template": "empty_cmake", "location": "/tmp"},
            "a path climbing out": {"name": "outside", "template": "empty_cmake", "location": "src/../.."},
            "an unknown template": {"name": "nope", "template": "android"},
            "a bad dependency name": {"name": "nope", "template": "empty_cmake", "dependencies": ["rm -rf"]},
            "a bad node name": {"name": "nope", "template": "cpp_node", "node_name": "my-node"},
            "a bad email": {"name": "nope", "template": "empty_cmake", "maintainer_email": "nobody"},
        }
        for what, spec in refused.items():
            reply = create(env, **spec)
            check(reply.get("ok") is False, f"refuses {what}", reply)
        (ws / "src").mkdir(parents=True, exist_ok=True)
        (ws / "src" / "escape").symlink_to(home)
        check(create(env, name="through_link", template="empty_cmake", location="src/escape").get("ok") is False,
              "refuses a symlink out of src")
        (ws / "src" / "escape").unlink()

        made = {
            "demo_cpp": dict(template="cpp_node", node_name="talker", dependencies=["std_msgs"],
                             maintainer_name="Test Person", maintainer_email="test@example.com", license="MIT"),
            "demo_py": dict(template="python_node", node_name="listener", dependencies=["std_msgs"]),
            "demo_component": dict(template="cpp_component", node_name="worker"),
            "demo_lib": dict(template="cpp_library", library_name="demo_lib", dependencies=["rclcpp"]),
            "demo_interfaces": dict(template="interfaces", interfaces=["msg", "srv", "action"],
                                    dependencies=["std_msgs"]),
            "demo_bringup": dict(template="bringup"),
            "demo_empty": dict(template="empty_cmake", dependencies=["launch_ros", "not_a_real_package_xyz"]),
            "demo_empty_py": dict(template="empty_python"),
        }
        for name, spec in made.items():
            reply = create(env, name=name, **spec)
            check(reply.get("ok") and Path(reply["path"]) == ws / "src" / name, f"creates {name} ({spec['template']})",
                  reply)
        check(create(env, name="demo_cpp", template="empty_cmake").get("ok") is False, "refuses an existing package")
        manifest = (ws / "src" / "demo_empty" / "package.xml").read_text()
        check("<exec_depend>launch_ros</exec_depend>" in manifest and "<depend>not_a_real_package_xyz</depend>" in manifest,
              "a Python-only dependency is a run-time dependency; a missing one stays a full one", manifest)
        missing = create(env, name="demo_missing", template="empty_python", dependencies=["not_a_real_package_xyz"])
        check(missing.get("missing") == ["not_a_real_package_xyz"], "a dependency that is not installed is reported",
              missing)
        shutil.rmtree(ws / "src" / "demo_missing")
        cpp = (ws / "src" / "demo_cpp")
        check("Test Person" in (cpp / "package.xml").read_text() and (cpp / "LICENSE").is_file()
              and "create_publisher<std_msgs::msg::String>" in (cpp / "src" / "talker.cpp").read_text(),
              "the C++ node has the maintainer, the licence and a publisher for std_msgs")
        defaults = helper(env, "pkg-catalog").get("defaults", {})
        check(defaults.get("template") == "empty_python", "the last choices are remembered", defaults)

        source = f"source /opt/ros/{distro}/setup.bash"
        build = subprocess.run(["bash", "-c", f"{source} && colcon build --event-handlers console_direct- "
                                              "--packages-skip demo_empty"],
                               cwd=ws, env=env, capture_output=True, text=True, timeout=900)
        check(build.returncode == 0, "every template builds with colcon", build.stderr[-1500:] + build.stdout[-1500:])
        if build.returncode == 0:
            run = f"{source} && source install/setup.bash && "

            def output(cmd, seconds=4):
                """What a command printed in `seconds`; a node still running then is stopped with
                its whole process group (ros2 run's child would outlive bash)."""
                proc = subprocess.Popen(["bash", "-c", run + cmd], cwd=ws, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, start_new_session=True)
                try:
                    return proc.communicate(timeout=seconds)[0]
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGINT)
                    try:
                        return proc.communicate(timeout=5)[0]
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        return proc.communicate()[0]

            check("talker is running" in output("ros2 run demo_cpp talker"), "the C++ node runs")
            check("listener is running" in output("ros2 run demo_py listener"), "the Python node runs")
            check("worker is running" in output("ros2 run demo_component worker"), "the component runs alone")
            shown = output("ros2 interface show demo_interfaces/msg/Status && ros2 interface show demo_interfaces/srv/Command"
                           " && ros2 interface show demo_interfaces/action/Task", 20)
            check("bool ok" in shown and "bool success" in shown and "float32 progress" in shown,
                  "the message, service and action are generated", shown)
            check("demo_lib" in output("ls install/demo_lib/lib", 10), "the library is installed")
            launched = output("ros2 launch demo_bringup demo_bringup.launch.py", 20)
            check("Error" not in launched and "Traceback" not in launched, "the launch file loads", launched)
            tested = subprocess.run(["bash", "-c", f"{source} && colcon test --event-handlers console_direct- "
                                                   "--packages-skip demo_empty >/dev/null; colcon test-result"],
                                    cwd=ws, env=env, capture_output=True, text=True, timeout=900)
            check(tested.returncode == 0, "every template passes its own tests (the ROS linters)",
                  tested.stdout[-1500:])

        built = create(env, name="demo_built", template="empty_python", build=True, use_workspace=True)
        check(built.get("ok") and built.get("build", {}).get("ok") and built.get("workspace_set"),
              "creating can start the panel's build and switch the panel to ~/ros2_ws", built)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and helper(env, "runs").get("running", {}).get("build"):
            time.sleep(1)
        status = helper(env, "status")
        package = next((p for p in status.get("packages", []) if p["name"] == "demo_built"), {})
        check(status.get("workspace") == str(ws) and package.get("built"), "the panel lists it, built",
              [status.get("workspace"), package])
    finally:
        subprocess.run([sys.executable, str(HELPER), "stop", "build"], env=env, capture_output=True, timeout=30)
        subprocess.run(["pkill", "-f", str(home)], capture_output=True)   # nothing from the test may stay running
        shutil.rmtree(home, ignore_errors=True)
    print("new package checks passed" if not failures else f"{failures} new package check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
