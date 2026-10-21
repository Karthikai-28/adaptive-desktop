"""High-value mission templates that bind existing Adaptive tools to checked Office work."""
import asyncio
import json
import subprocess

from .config import ROOT
from .ros_compare import compare_bags

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


async def launch_ros_investigation(office, agent, title, problem, bag="", project="", repo="",
                                   baseline_bag="", simulation_command="", criteria=None, **mission):
    """Start a ROS investigation; mission carries created_by/risk/workflow/approval through to add_mission.
    The ROS snapshot and recording comparison are taken fresh on every launch, off the event loop."""
    problem, bag, baseline_bag = (problem or "").strip(), (bag or "").strip(), (baseline_bag or "").strip()
    simulation_command = (simulation_command or "").strip()
    if not problem:
        raise ValueError("describe the ROS failure to investigate")
    if baseline_bag and not bag:
        raise ValueError("a baseline recording needs a recording to compare it with")
    comparison = await asyncio.to_thread(compare_bags, baseline_bag, bag) if baseline_bag else None
    snap = await asyncio.to_thread(ros_snapshot)
    objective = (f"Investigate this ROS 2 failure and produce a reproducible, evidence-backed engineering report.\n\n"
                 f"Observed problem:\n{problem}\n\n"
                 + (f"Recording or dataset:\n{bag}\n\n" if bag else "")
                 + (f"Baseline recording:\n{baseline_bag}\n\n" if baseline_bag else "")
                 + (f"Simulation or replay command:\n{simulation_command}\n\n" if simulation_command else "")
                 + (f"Recording comparison:\n```json\n{json.dumps(comparison, indent=2)}\n```\n\n" if comparison else "")
                 + f"ROS setup snapshot captured when the mission was launched:\n```json\n{snap}\n```")
    template = {"kind": "ros-investigation", "problem": problem, "bag": bag, "baseline_bag": baseline_bag,
                "simulation_command": simulation_command}
    m = await office.add_mission(agent, title or "Investigate ROS 2 failure", objective, criteria or ROS_CRITERIA,
                                 project, repo, template=template, **mission)
    notes = "Initial ROS setup snapshot:\n" + snap
    if comparison:
        notes += "\n\nRecording comparison:\n" + json.dumps(comparison, indent=2)
    out = office.store.mission(m["id"], with_tasks=True)
    try:   # the mission is already queued: a capsule that cannot be written is reported, not raised
        await office.capsules.create(mission_id=m["id"], command=simulation_command or f"python3 {ROS_HELPER} status",
                                     datasets=[x for x in (baseline_bag, bag) if x], notes=notes)
    except (OSError, ValueError) as e:
        out["capsule_error"] = str(e)
        await office.activity(agent, "info", f"Mission #{m['id']}: the work capsule could not be saved ({e})",
                              m["tasks"][0]["id"] if m.get("tasks") else None)
    return out
