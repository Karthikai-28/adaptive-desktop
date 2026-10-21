"""Small, deterministic comparisons for ROS 2 rosbag metadata.

A recording is a rosbag2 folder (it holds metadata.yaml), its metadata.yaml, or any file inside that
folder (a .db3 or .mcap split). A lone file without a metadata.yaml next to it cannot be compared.
"""
from pathlib import Path


def _int(v, what):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        raise ValueError(f"rosbag metadata has an invalid {what}: {v!r}") from None


def _metadata(path):
    p = Path(str(path)).expanduser().resolve()
    if p.is_file() and p.name != "metadata.yaml":
        p = p.parent
    if p.is_dir():
        p = p / "metadata.yaml"
    if p.name != "metadata.yaml" or not p.is_file():
        raise ValueError(f"no rosbag2 metadata.yaml at {path} (comparison needs a rosbag2 recording folder)")
    if p.stat().st_size > 5_000_000:
        raise ValueError("rosbag metadata is too large")
    try:
        import yaml
    except ImportError:
        raise ValueError("comparing recordings needs PyYAML (apt install python3-yaml)") from None
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"cannot read rosbag metadata: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{p} is not rosbag2 metadata")
    info = raw.get("rosbag2_bagfile_information", raw)
    rows = info.get("topics_with_message_count") if isinstance(info, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{p} is not rosbag2 metadata (no topics_with_message_count)")
    topics = {}
    for row in rows:
        meta = row.get("topic_metadata") if isinstance(row, dict) else None
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or "")
        if name:
            topics[name] = {"type": str(meta.get("type") or ""),
                            "messages": _int(row.get("message_count"), "message count")}
    duration = info.get("duration", 0)
    if isinstance(duration, dict):
        duration = duration.get("nanoseconds", 0)
    return {"path": str(p.parent), "messages": _int(info.get("message_count"), "message count"),
            "duration_ns": _int(duration, "duration"), "topics": topics}


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
