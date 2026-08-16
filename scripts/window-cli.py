#!/usr/bin/env python3
import argparse
import subprocess
import sys


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

    if args.preset == "left":
        move_resize(window, 172, top, max(320, (width - 172) // 2), usable_height)
    elif args.preset == "right":
        half = max(320, (width - 172) // 2)
        move_resize(window, 172 + half, top, half, usable_height)
    elif args.preset == "center":
        target_width = max(720, int((width - 172) * 0.66))
        target_height = max(520, int(usable_height * 0.78))
        x = 172 + max(0, ((width - 172) - target_width) // 2)
        y = top + max(0, (usable_height - target_height) // 2)
        move_resize(window, x, y, target_width, target_height)
    elif args.preset == "maximize":
        move_resize(window, 172, top, max(640, width - 172), usable_height)
    else:
        raise RuntimeError(f"Unknown preset: {args.preset}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Adaptive Desktop window presets")
    sub = parser.add_subparsers(dest="command", required=True)

    tile_parser = sub.add_parser("tile", help="Tile the active window")
    tile_parser.add_argument("preset", choices=["left", "right", "center", "maximize"])
    tile_parser.set_defaults(func=tile)

    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
