#!/usr/bin/env python3
"""Measure what the Kinect's body tracking really delivers, before and after changing it.

    scripts/kinect-baseline.py [--seconds 30] [--label "1 person, lights on"] [--save]

Reads the hub's /api/people long poll (starting the hub if it is not running) for a while and
reports, from the hub's own timestamps:

    updates/s        distinct skeleton states a second (target: 15 for one player, 12 for two)
    latency          capture -> skeleton ready (hub) and capture -> received here (end to end),
                     median and 95th percentile (target p95 < 200 ms)
    frames           skipped camera frames between states, repeated frames (must be none),
                     colour / infrared share and every switch between them
    people           how many in view per state, and their ids: ids born, ids lost, the longest
                     a single id lasted (identity churn)
    joints           per state and person: tracked / inferred / missing out of 33, and of the
                     joints each exercise family needs (legs, arms, whole body)
    coverage         where people stood on the floor (x, z in metres), 25 cm cells

Nothing but these numbers is kept: --save writes them as JSON to
~/.local/share/adaptive-desktop/kinect-baseline/<time>.json (no pictures, no skeletons).
--json prints the same JSON. The rest of the acceptance protocol: docs/KINECT_MOTION.md.
"""

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

HUB = os.environ.get("KINECT_HUB_URL", "http://127.0.0.1:8792")
OUT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "adaptive-desktop/kinect-baseline"
FAMILIES = {
    "legs": (23, 24, 25, 26, 27, 28),
    "arms": (11, 12, 13, 14, 15, 16),
    "body": (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28),
}


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def get(path, timeout=3.0):
    return json.loads(urllib.request.urlopen(HUB + path, timeout=timeout).read())


def ensure_hub():
    try:
        get("/api/status", 0.5)
        return
    except OSError:
        pass
    subprocess.run(["systemctl", "--user", "start", "adaptive-kinect.service"], capture_output=True)
    for _ in range(50):
        try:
            get("/api/status", 0.5)
            return
        except OSError:
            time.sleep(0.1)
    sys.exit("The Kinect hub does not answer (systemctl --user status adaptive-kinect)")


def measure(seconds):
    seq = 0
    states = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            st = get(f"/api/people?after={seq}")
        except OSError as err:
            states.append({"error": str(err), "received": time.time()})
            time.sleep(0.5)
            continue
        if st.get("seq") == seq:
            continue
        seq = st.get("seq", 0)
        st["received"] = time.time()
        if st.get("running"):
            states.append(st)
    return states


def summarise(states, seconds, label=None):
    live = [s for s in states if "error" not in s and s.get("captured")]
    out = {"label": label, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": seconds,
           "states": len(live), "errors": sum("error" in s for s in states)}
    if not live:
        out["verdict"] = "No skeleton states: is the hub streaming and the pose model installed?"
        return out
    span = live[-1]["received"] - live[0]["received"]
    out["updates_per_s"] = round((len(live) - 1) / span, 1) if span > 0 else None
    hub_ms = [1000 * (s["ready"] - s["captured"]) for s in live if s.get("ready")]
    e2e_ms = [1000 * (s["received"] - s["captured"]) for s in live]
    out["latency_ms"] = {
        "hub_p50": round(pct(hub_ms, 0.5) or 0), "hub_p95": round(pct(hub_ms, 0.95) or 0),
        "end_to_end_p50": round(pct(e2e_ms, 0.5)), "end_to_end_p95": round(pct(e2e_ms, 0.95)),
        "end_to_end_max": round(max(e2e_ms))}
    frames = [s.get("frame") for s in live if s.get("frame") is not None]
    gaps = [b - a for a, b in zip(frames, frames[1:])]
    # The frame store counts by two per frame (a sequence lock): a gap of 2 = the next frame.
    out["frames"] = {"repeated": sum(g == 0 for g in gaps),
                     "skipped_per_state": round(statistics.mean(max(0, g / 2 - 1) for g in gaps), 2) if gaps else None,
                     "modes": dict(Counter(s.get("mode") for s in live)),
                     "mode_switches": sum(a.get("mode") != b.get("mode") for a, b in zip(live, live[1:]))}
    counts = [len(s.get("people") or []) for s in live]
    out["people"] = {"per_state": dict(sorted(Counter(counts).items())),
                     "max": max(counts), "mean": round(statistics.mean(counts), 2)}
    life = {}
    for s in live:
        for p in s.get("people") or []:
            first, _ = life.get(p["id"], (s["received"], None))
            life[p["id"]] = (first, s["received"])
    births = len(life)
    out["identity"] = {"ids": births,
                       "longest_s": round(max(b - a for a, b in life.values()), 1) if life else 0,
                       "ids_per_minute": round(60 * births / span, 1) if span > 0 else None}
    fam = {k: [] for k in FAMILIES}
    all_states = Counter()
    cells = Counter()
    for s in live:
        for p in s.get("people") or []:
            joints = p.get("joints") or []
            st = [j[3] if j else 0 for j in joints] + [0] * (33 - len(joints))
            all_states.update(st)
            for k, ids in FAMILIES.items():
                fam[k].append(sum(st[i] == 2 for i in ids) / len(ids))
            hips = [joints[i] for i in (23, 24) if i < len(joints) and joints[i]]
            if hips:
                x = sum(h[0] for h in hips) / len(hips)
                z = sum(h[2] for h in hips) / len(hips)
                cells[(math.floor(x / 0.25), math.floor(z / 0.25))] += 1
    n = sum(all_states.values()) or 1
    out["joints"] = {"tracked": round(all_states[2] / n, 3), "inferred": round(all_states[1] / n, 3),
                     "missing": round(all_states[0] / n, 3),
                     "families_tracked": {k: round(statistics.mean(v), 3) if v else None for k, v in fam.items()}}
    out["coverage_cells"] = [{"x": round(cx * 0.25, 2), "z": round(cz * 0.25, 2), "states": c}
                             for (cx, cz), c in sorted(cells.items())]
    floor = live[-1].get("floor")
    if floor:
        out["floor"] = {k: floor.get(k) for k in ("camera_height", "tilt", "seen") if k in floor}
    return out


def verdict(r, players=1):
    rate_target = 15 if players <= 1 else 12
    lines = []
    if r.get("updates_per_s") is not None:
        ok = r["updates_per_s"] >= rate_target
        lines.append(f"{'PASS' if ok else 'FAIL'} updates {r['updates_per_s']}/s (target {rate_target})")
    if r.get("latency_ms"):
        p95 = r["latency_ms"]["end_to_end_p95"]
        lines.append(f"{'PASS' if p95 < 200 else 'FAIL'} capture to here p95 {p95} ms (target < 200)")
    if r.get("frames"):
        rep = r["frames"]["repeated"]
        lines.append(f"{'PASS' if rep == 0 else 'FAIL'} repeated frames {rep} (must be 0)")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--label", help='what was in front of the Kinect, e.g. "2 people, dark"')
    ap.add_argument("--players", type=int, default=1, help="people meant to be in view (sets the rate target)")
    ap.add_argument("--save", action="store_true", help="keep the numbers in ~/.local/share/adaptive-desktop/kinect-baseline")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    ensure_hub()
    get("/api/people?after=0")                 # start the people tracker; let the model load
    time.sleep(3.0)
    r = summarise(measure(args.seconds), args.seconds, args.label)
    r["checks"] = verdict(r, args.players)
    if args.save:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / time.strftime("%Y%m%d-%H%M%S.json")
        path.write_text(json.dumps(r, indent=2) + "\n")
        r["saved"] = str(path)
    if args.json:
        print(json.dumps(r, indent=2))
        return 0
    print(f"{r.get('label') or 'Kinect baseline'}: {r['states']} states in {args.seconds:.0f} s")
    for k in ("updates_per_s", "latency_ms", "frames", "people", "identity", "joints", "floor"):
        if k in r:
            print(f"  {k:14} {json.dumps(r[k])}")
    if r.get("coverage_cells"):
        print(f"  {'coverage':14} {len(r['coverage_cells'])} cells of 25 cm")
    for line in r["checks"]:
        print("  " + line)
    if r.get("saved"):
        print(f"  saved {r['saved']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
