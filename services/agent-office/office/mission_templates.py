"""High-value mission templates that bind existing Adaptive tools to checked Office work."""
import json
import subprocess

from .config import ROOT

ROS_HELPER = ROOT.parents[1] / "shell" / "adaptive-shell@local" / "tools" / "ros_info.py"
ROS_CRITERIA = [
    "The failure is reproduced, or the report explains exactly why it could not be reproduced",
    "The timeline correlates relevant logs, diagnostics, parameters and recent code changes",
    "Every root-cause claim cites a file, command output, recording timestamp or measured signal",
    "A proposed fix or next experiment has a repeatable regression check",
    "The final report includes commands, inputs, observed results and remaining uncertainty",
]


def ros_snapshot():
    try:
        p = subprocess.run(["python3", str(ROS_HELPER), "status"], capture_output=True, text=True, timeout=10)
        data = json.loads(p.stdout) if p.stdout.strip() else {"ok": False, "error": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        data = {"ok": False, "error": str(e)}
    # The snapshot is context, not an unlimited log payload.
    return json.dumps(data, indent=2, sort_keys=True)[:20_000]


async def launch_ros_investigation(office, agent, title, problem, bag="", project="", repo=""):
    problem = (problem or "").strip()
    if not problem:
        raise ValueError("describe the ROS failure to investigate")
    snap = ros_snapshot()
    objective = (f"Investigate this ROS 2 failure and produce a reproducible, evidence-backed engineering report.\n\n"
                 f"Observed problem:\n{problem}\n\n"
                 + (f"Recording or dataset:\n{bag.strip()}\n\n" if bag.strip() else "")
                 + f"ROS setup snapshot captured when the mission was launched:\n```json\n{snap}\n```")
    mission = await office.add_mission(agent, title or "Investigate ROS 2 failure", objective,
                                       ROS_CRITERIA, project, repo)
    office.capsules.create(mission_id=mission["id"], command=f"python3 {ROS_HELPER} status",
                           datasets=[bag] if bag.strip() else [], notes="Initial ROS setup snapshot:\n" + snap)
    return office.store.mission(mission["id"], with_tasks=True)
