#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def pgrep(pattern):
    result = subprocess.run(
        ["pgrep", "-u", str(Path.home().owner()), "-f", pattern],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    return [int(pid) for pid in result.stdout.split() if pid.isdigit()]


def rss_kb(pid):
    status = Path(f"/proc/{pid}/status")
    for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError(f"VmRSS not found for pid {pid}")


def sample_process(pid):
    return {
        "pid": pid,
        "rss_kb": rss_kb(pid),
        "time": int(time.time()),
    }


def main():
    parser = argparse.ArgumentParser(description="Sample GNOME Shell memory over time")
    parser.add_argument("--seconds", type=int, default=30, help="Sample duration")
    parser.add_argument("--interval", type=int, default=5, help="Seconds between samples")
    parser.add_argument("--max-growth-mb", type=int, default=120, help="Allowed RSS growth")
    parser.add_argument("--allow-missing", action="store_true", help="Skip when GNOME Shell is not observable")
    parser.add_argument("--json", action="store_true", help="Print JSON sample data")
    args = parser.parse_args()

    pids = pgrep("gnome-shell")
    if not pids:
        if args.allow_missing:
            print("GNOME Shell process not observable from this context; memory sampling skipped.")
            return 0
        print("GNOME Shell process not found", file=sys.stderr)
        return 1

    pid = pids[0]
    duration = max(1, args.seconds)
    interval = max(1, args.interval)
    deadline = time.time() + duration
    samples = []

    while True:
        samples.append(sample_process(pid))
        if time.time() >= deadline:
            break
        time.sleep(min(interval, max(0, deadline - time.time())))

    first = samples[0]["rss_kb"]
    last = samples[-1]["rss_kb"]
    growth_mb = (last - first) / 1024
    allowed = args.max_growth_mb

    if args.json:
        print(json.dumps({"samples": samples, "growth_mb": growth_mb}, indent=2))

    print(
        f"GNOME Shell RSS: {first // 1024} MB -> {last // 1024} MB "
        f"({growth_mb:+.1f} MB over {duration}s)"
    )

    if growth_mb > allowed:
        print(f"Memory growth exceeded {allowed} MB", file=sys.stderr)
        return 1

    print("Shell memory sampling passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
