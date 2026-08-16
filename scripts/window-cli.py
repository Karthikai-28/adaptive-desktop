#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


CONFIG_DIR = Path.home() / ".config" / "adaptive-desktop"
STATE_FILE = CONFIG_DIR / "window-placements.json"
PROJECTS_FILE = CONFIG_DIR / "projects.json"
DOCK_WIDTH = 172
TOP_BAR_HEIGHT = 28


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


def monitors():
    def fallback():
        try:
            width, height = geometry()
            return [{"name": "display", "x": 0, "y": 0, "width": width, "height": height, "primary": True}]
        except Exception:
            return []

    result = subprocess.run(
        ["xrandr", "--query"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode:
        return fallback()

    pattern = re.compile(
        r"^(?P<name>\S+) connected(?P<primary> primary)? "
        r"(?P<width>\d+)x(?P<height>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
    )
    values = []

    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue

        values.append(
            {
                "name": match.group("name"),
                "x": int(match.group("x")),
                "y": int(match.group("y")),
                "width": int(match.group("width")),
                "height": int(match.group("height")),
                "primary": bool(match.group("primary")),
            }
        )

    if values:
        return values

    return fallback()


def active_monitor(window):
    current = window_geometry(window)
    center_x = current["x"] + current["width"] // 2
    center_y = current["y"] + current["height"] // 2
    available = monitors()
    if not available:
        raise RuntimeError("No monitor geometry available")

    for monitor in available:
        if (
            monitor["x"] <= center_x < monitor["x"] + monitor["width"]
            and monitor["y"] <= center_y < monitor["y"] + monitor["height"]
        ):
            return monitor

    return next((monitor for monitor in available if monitor["primary"]), available[0])


def usable_area(monitor):
    dock = DOCK_WIDTH if monitor.get("primary") else 0
    top = TOP_BAR_HEIGHT

    return {
        "x": monitor["x"] + dock,
        "y": monitor["y"] + top,
        "width": max(320, monitor["width"] - dock),
        "height": max(240, monitor["height"] - top),
    }


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


def current_project_id():
    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    project_id = data.get("active_id")
    if project_id and project_id in data.get("projects", {}):
        return project_id
    return None


def move_resize(window, x, y, width, height):
    result = run("windowmove", window, str(x), str(y))
    if result.returncode:
        raise RuntimeError(result.stderr.strip())

    result = run("windowsize", window, str(width), str(height))
    if result.returncode:
        raise RuntimeError(result.stderr.strip())


def wmctrl(*args):
    return subprocess.run(["wmctrl", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def tile(args):
    window = active_window()
    area = usable_area(active_monitor(window))
    width = area["width"]
    top = area["y"]
    left = area["x"]
    usable_height = area["height"]

    preset = args.preset
    if preset == "smart":
        current = window_geometry(window)
        midpoint = left + max(1, width // 2)
        if current["x"] < midpoint and current["width"] < width * 0.70:
            preset = "right"
        elif current["x"] >= midpoint:
            preset = "center"
        else:
            preset = "left"

    if preset == "left":
        move_resize(window, left, top, max(320, width // 2), usable_height)
    elif preset == "right":
        half = max(320, width // 2)
        move_resize(window, left + half, top, half, usable_height)
    elif preset == "center":
        target_width = max(720, int(width * 0.66))
        target_height = max(520, int(usable_height * 0.78))
        x = left + max(0, (width - target_width) // 2)
        y = top + max(0, (usable_height - target_height) // 2)
        move_resize(window, x, y, target_width, target_height)
    elif preset == "maximize":
        move_resize(window, left, top, max(640, width), usable_height)
    else:
        raise RuntimeError(f"Unknown preset: {preset}")

    return 0


def snap(args):
    args.preset = args.edge
    return tile(args)


def fullscreen(_args):
    result = wmctrl("-r", ":ACTIVE:", "-b", "toggle,fullscreen")
    if result.returncode:
        result = run("key", "F11")
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Unable to toggle fullscreen")
    print("Toggled fullscreen for active window")
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


def placement_key(name, project=False):
    if not project:
        return name

    project_id = current_project_id()
    if not project_id:
        raise RuntimeError("No active project for project placement")
    return f"project:{project_id}:{name}"


def clamp_placement(placement, window):
    area = usable_area(active_monitor(window))
    min_x = area["x"]
    min_y = area["y"]
    max_width = area["width"]
    max_height = area["height"]

    width = min(max(320, int(placement["width"])), max_width)
    height = min(max(240, int(placement["height"])), max_height)
    x = min(max(min_x, int(placement["x"])), max(min_x, min_x + max_width - width))
    y = min(max(min_y, int(placement["y"])), max(min_y, min_y + max_height - height))

    return {"x": x, "y": y, "width": width, "height": height}


def save(args):
    window = active_window()
    state = load_state()
    key = placement_key(args.name, args.project)
    state[key] = {
        "title": window_name(window),
        "project_id": current_project_id() if args.project else "",
        **window_geometry(window),
    }
    save_state(state)
    label = f"{args.name} for active project" if args.project else args.name
    print(f"Saved placement: {label}")
    return 0


def restore(args):
    window = active_window()
    state = load_state()
    key = placement_key(args.name, args.project)
    placement = state.get(key)

    if not placement:
        label = f"{args.name} for active project" if args.project else args.name
        raise RuntimeError(f"No saved placement: {label}")

    safe = clamp_placement(placement, window)
    move_resize(
        window,
        safe["x"],
        safe["y"],
        safe["width"],
        safe["height"],
    )
    label = f"{args.name} for active project" if args.project else args.name
    print(f"Restored placement: {label}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Adaptive Desktop window presets")
    sub = parser.add_subparsers(dest="command", required=True)

    tile_parser = sub.add_parser("tile", help="Tile the active window")
    tile_parser.add_argument("preset", choices=["left", "right", "center", "maximize", "smart"])
    tile_parser.set_defaults(func=tile)

    snap_parser = sub.add_parser("snap", help="Snap the active window to an edge")
    snap_parser.add_argument("edge", choices=["left", "right", "center", "maximize"])
    snap_parser.set_defaults(func=snap)

    sub.add_parser("fullscreen", help="Toggle fullscreen for the active window").set_defaults(func=fullscreen)

    save_parser = sub.add_parser("save", help="Save active window placement")
    save_parser.add_argument("name", nargs="?", default="default")
    save_parser.add_argument("--project", action="store_true", help="Scope placement to the active project")
    save_parser.set_defaults(func=save)

    restore_parser = sub.add_parser("restore", help="Restore active window placement")
    restore_parser.add_argument("name", nargs="?", default="default")
    restore_parser.add_argument("--project", action="store_true", help="Scope placement to the active project")
    restore_parser.set_defaults(func=restore)

    save_project_parser = sub.add_parser("save-project", help="Save active window placement for the active project")
    save_project_parser.add_argument("name", nargs="?", default="default")
    save_project_parser.set_defaults(func=lambda args: save(argparse.Namespace(name=args.name, project=True)))

    restore_project_parser = sub.add_parser("restore-project", help="Restore active project window placement")
    restore_project_parser.add_argument("name", nargs="?", default="default")
    restore_project_parser.set_defaults(func=lambda args: restore(argparse.Namespace(name=args.name, project=True)))

    sub.add_parser("monitors", help="List detected monitors").set_defaults(
        func=lambda _args: print(json.dumps(monitors(), indent=2)) or 0
    )

    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
