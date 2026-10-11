#!/usr/bin/env python3
"""Asynchronous process metrics sampler for Adaptive TaskManager and Telemetry.

Samples /proc off the compositor thread to prevent UI frame drops and stutters.
"""
import json
import os
import sys

PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def get_user_processes(uid):
    procs = []
    try:
        entries = os.scandir("/proc")
    except OSError:
        return procs

    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            st = entry.stat()
            if st.st_uid != uid:
                continue
            with open(f"/proc/{entry.name}/stat", "r", encoding="utf-8", errors="replace") as f:
                stat = f.read()
            with open(f"/proc/{entry.name}/statm", "r", encoding="utf-8", errors="replace") as f:
                statm = f.read()
        except OSError:
            continue

        open_paren = stat.find("(")
        close_paren = stat.rfind(")")
        if open_paren < 0 or close_paren < 0 or close_paren < open_paren:
            continue
        comm = stat[open_paren + 1:close_paren]
        fields = stat[close_paren + 2:].split()
        if len(fields) < 13:
            continue
        try:
            statm_parts = statm.split()
            rss_pages = int(statm_parts[1]) if len(statm_parts) > 1 else 0
            procs.append({
                "pid": int(entry.name),
                "comm": comm,
                "state": fields[0],
                "ppid": int(fields[1]),
                "ticks": int(fields[11]) + int(fields[12]),
                "rss": rss_pages * PAGE_SIZE,
            })
        except (ValueError, IndexError):
            continue
    return procs


def get_telemetry():
    count = 0
    procs = []
    try:
        entries = os.scandir("/proc")
    except OSError:
        return {"count": 0, "procs": []}

    for entry in entries:
        if not entry.name.isdigit():
            continue
        count += 1
        try:
            with open(f"/proc/{entry.name}/stat", "r", encoding="utf-8", errors="replace") as f:
                stat = f.read()
            with open(f"/proc/{entry.name}/statm", "r", encoding="utf-8", errors="replace") as f:
                statm = f.read()
        except OSError:
            continue

        open_paren = stat.find("(")
        close_paren = stat.rfind(")")
        if open_paren < 0 or close_paren < 0 or close_paren < open_paren:
            continue
        comm = stat[open_paren + 1:close_paren]
        fields = stat[close_paren + 2:].split()
        if len(fields) < 22:
            continue
        try:
            utime = int(fields[11])
            stime = int(fields[12])
            statm_parts = statm.split()
            rss_pages = int(statm_parts[1]) if len(statm_parts) > 1 else 0
            rss_bytes = rss_pages * PAGE_SIZE
            procs.append([int(entry.name), comm, utime + stime, rss_bytes])
        except (ValueError, IndexError):
            continue

    return {
        "count": count,
        "procs": procs,
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "user"
    if mode == "user":
        uid = int(sys.argv[2]) if len(sys.argv) > 2 else os.getuid()
        print(json.dumps(get_user_processes(uid)))
    elif mode == "telemetry":
        print(json.dumps(get_telemetry()))
    else:
        print(json.dumps([]))


if __name__ == "__main__":
    main()
