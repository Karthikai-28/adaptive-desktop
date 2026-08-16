#!/usr/bin/env python3
import argparse
import json
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


def tile(args):
    window = active_window()
    width, height = geometry()
    top = TOP_BAR_HEIGHT
    usable_height = max(240, height - top)

    preset = args.preset
    if preset == "smart":
        current = window_geometry(window)
        midpoint = DOCK_WIDTH + max(1, (width - DOCK_WIDTH) // 2)
        if current["x"] < midpoint and current["width"] < (width - DOCK_WIDTH) * 0.70:
            preset = "right"
        elif current["x"] >= midpoint:
            preset = "center"
        else:
            preset = "left"

    if preset == "left":
        move_resize(window, DOCK_WIDTH, top, max(320, (width - DOCK_WIDTH) // 2), usable_height)
    elif preset == "right":
        half = max(320, (width - DOCK_WIDTH) // 2)
        move_resize(window, DOCK_WIDTH + half, top, half, usable_height)
    elif preset == "center":
        target_width = max(720, int((width - DOCK_WIDTH) * 0.66))
        target_height = max(520, int(usable_height * 0.78))
        x = DOCK_WIDTH + max(0, ((width - DOCK_WIDTH) - target_width) // 2)
        y = top + max(0, (usable_height - target_height) // 2)
        move_resize(window, x, y, target_width, target_height)
    elif preset == "maximize":
        move_resize(window, DOCK_WIDTH, top, max(640, width - DOCK_WIDTH), usable_height)
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


def placement_key(name, project=False):
    if not project:
        return name

    project_id = current_project_id()
    if not project_id:
        raise RuntimeError("No active project for project placement")
    return f"project:{project_id}:{name}"


def clamp_placement(placement):
    display_width, display_height = geometry()
    min_x = DOCK_WIDTH
    min_y = TOP_BAR_HEIGHT
    max_width = max(320, display_width - DOCK_WIDTH)
    max_height = max(240, display_height - TOP_BAR_HEIGHT)

    width = min(max(320, int(placement["width"])), max_width)
    height = min(max(240, int(placement["height"])), max_height)
    x = min(max(min_x, int(placement["x"])), max(min_x, display_width - width))
    y = min(max(min_y, int(placement["y"])), max(min_y, display_height - height))

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

    safe = clamp_placement(placement)
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

    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
