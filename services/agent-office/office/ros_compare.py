"""Small, deterministic comparisons for ROS 2 rosbag metadata."""
from pathlib import Path

import yaml


def _metadata(path):
    p = Path(path).expanduser().resolve()
    if p.is_dir():
        p = p / "metadata.yaml"
    if p.name != "metadata.yaml" or not p.is_file():
        raise ValueError(f"no rosbag metadata.yaml at {path}")
    if p.stat().st_size > 5_000_000:
        raise ValueError("rosbag metadata is too large")
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"cannot read rosbag metadata: {e}") from e
    info = raw.get("rosbag2_bagfile_information", raw)
    topics = {}
    for row in info.get("topics_with_message_count", []):
        meta = row.get("topic_metadata", {})
        name = str(meta.get("name", ""))
        if name:
            topics[name] = {"type": str(meta.get("type", "")), "messages": int(row.get("message_count", 0))}
    duration = info.get("duration", 0)
    if isinstance(duration, dict):
        duration = duration.get("nanoseconds", 0)
    return {"path": str(p.parent), "messages": int(info.get("message_count", 0)),
            "duration_ns": int(duration or 0), "topics": topics}


def compare_bags(baseline, candidate):
    before, after = _metadata(baseline), _metadata(candidate)
    names = sorted(set(before["topics"]) | set(after["topics"]))
    topics, flags = [], []
    for name in names:
        a, b = before["topics"].get(name), after["topics"].get(name)
        if not a:
            state = "added"
        elif not b:
            state = "missing"
            flags.append(f"topic missing: {name}")
        elif a["type"] != b["type"]:
            state = "type_changed"
            flags.append(f"topic type changed: {name}")
        else:
            state = "present"
        old, new = (a or {}).get("messages", 0), (b or {}).get("messages", 0)
        ratio = None if old == 0 else round(new / old, 4)
        if a and b and old and ratio < 0.5:
            flags.append(f"message count dropped over 50%: {name}")
        topics.append({"name": name, "state": state, "baseline": a, "candidate": b,
                       "message_ratio": ratio})
    return {"schema": 1, "baseline": before, "candidate": after,
            "message_delta": after["messages"] - before["messages"], "topics": topics,
            "flags": flags, "ok": not flags}
