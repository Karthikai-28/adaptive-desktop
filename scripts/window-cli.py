#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


STATE_FILE = Path.home() / ".config" / "adaptive-desktop" / "window-placements.json"


def run(*args):
    return subprocess.run(["xdotool", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def active_window():
    result = run("getactivewindow")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "No active window")
    return result.stdout.strip()


def geometry():
    result = run("getdisplaygeometry")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Unable to read display geometry")
    width, height = result.stdout.strip().split()
    return int(width), int(height)


def window_geometry(window):
    result = run("getwindowgeometry", "--shell", window)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Unable to read active window geometry")

    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = int(value)

    return {
        "x": values.get("X", 0),
        "y": values.get("Y", 0),
        "width": values.get("WIDTH", 800),
        "height": values.get("HEIGHT", 600),
    }


def window_name(window):
    result = run("getwindowname", window)
    if result.returncode:
        return window
    return result.stdout.strip() or window


def move_resize(window, x, y, width, height):
    result = run("windowmove", window, str(x), str(y))
    if result.returncode:
        raise RuntimeError(result.stderr.strip())

    result = run("windowsize", window, str(width), str(height))
    if result.returncode:
        raise RuntimeError(result.stderr.strip())


def tile(args):
    window = active_window()
    width, height = geometry()
    top = 28
    usable_height = max(240, height - top)

    preset = args.preset
    if preset == "smart":
        current = window_geometry(window)
        midpoint = 172 + max(1, (width - 172) // 2)
        if current["x"] < midpoint and current["width"] < (width - 172) * 0.70:
            preset = "right"
        elif current["x"] >= midpoint:
            preset = "center"
        else:
            preset = "left"

    if preset == "left":
        move_resize(window, 172, top, max(320, (width - 172) // 2), usable_height)
    elif preset == "right":
        half = max(320, (width - 172) // 2)
        move_resize(window, 172 + half, top, half, usable_height)
    elif preset == "center":
        target_width = max(720, int((width - 172) * 0.66))
        target_height = max(520, int(usable_height * 0.78))
        x = 172 + max(0, ((width - 172) - target_width) // 2)
        y = top + max(0, (usable_height - target_height) // 2)
        move_resize(window, x, y, target_width, target_height)
    elif preset == "maximize":
        move_resize(window, 172, top, max(640, width - 172), usable_height)
    else:
        raise RuntimeError(f"Unknown preset: {preset}")

    return 0


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save(args):
    window = active_window()
    state = load_state()
    state[args.name] = {
        "title": window_name(window),
        **window_geometry(window),
    }
    save_state(state)
    print(f"Saved placement: {args.name}")
    return 0


def restore(args):
    window = active_window()
    state = load_state()
    placement = state.get(args.name)

    if not placement:
        raise RuntimeError(f"No saved placement: {args.name}")

    move_resize(
        window,
        placement["x"],
        placement["y"],
        placement["width"],
        placement["height"],
    )
    print(f"Restored placement: {args.name}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Adaptive Desktop window presets")
    sub = parser.add_subparsers(dest="command", required=True)

    tile_parser = sub.add_parser("tile", help="Tile the active window")
    tile_parser.add_argument("preset", choices=["left", "right", "center", "maximize", "smart"])
    tile_parser.set_defaults(func=tile)

    save_parser = sub.add_parser("save", help="Save active window placement")
    save_parser.add_argument("name", nargs="?", default="default")
    save_parser.set_defaults(func=save)

    restore_parser = sub.add_parser("restore", help="Restore active window placement")
    restore_parser.add_argument("name", nargs="?", default="default")
    restore_parser.set_defaults(func=restore)

    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
