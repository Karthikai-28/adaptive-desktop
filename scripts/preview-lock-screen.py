#!/usr/bin/env python3
"""Render a dummy Adaptive lock screen.

The real lock screen cannot be inspected: gnome-screenshot returns an all-black
image while the session is locked, so there is no way to see a change without
locking yourself out of the feedback loop. This mirrors the same layout, sizes
and colours as shell/adaptive-shell@local/stylesheet.css so the composition can
be judged and iterated on directly.

It renders, it does not read the shell - if the stylesheet changes, change the
constants here too.

    ./scripts/preview-lock-screen.py [--out FILE] [--12h]
"""

import argparse
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1200

# Mirrors .unlock-dialog-clock-* and .adaptive-lock-activity.
TIME_PX, DATE_PX, ACTIVITY_PX, HINT_PX, PROMPT_PX = 76, 18, 12, 11, 13
WHITE = (255, 255, 255)
DIM = (255, 255, 255, 140)


def font(size, bold=False):
    for name in (
        "Ubuntu-{}.ttf".format("B" if bold else "R"),
        "DejaVuSans{}.ttf".format("-Bold" if bold else ""),
    ):
        for base in ("/usr/share/fonts/truetype/ubuntu", "/usr/share/fonts/truetype/dejavu"):
            path = Path(base) / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def running_apps():
    """Approximates Shell.AppSystem.get_running() for the dummy."""
    try:
        out = subprocess.run(
            ["wmctrl", "-lx"], capture_output=True, text=True, timeout=3
        ).stdout
        names = set()
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 3 and "." in parts[2]:
                names.add(parts[2].split(".")[-1])
        return sorted(names)
    except Exception:
        return ["Antigravity", "Firefox", "Files"]


def centre(draw, text, y, fnt, fill, spacing=0):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    draw.text(((W - (right - left)) / 2 - left, y), text, font=fnt, fill=fill)
    return bottom - top


def render(twelve_hour=False, ambient=False, prompt=False):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    now = time.localtime()
    clock = time.strftime("%I:%M:%S %p", now).lstrip("0") if twelve_hour \
        else time.strftime("%H:%M:%S", now)
    date = time.strftime("%A %B %-d", now)

    alpha = 145 if ambient else 255
    white = (255, 255, 255, alpha)

    y = int(H * 0.30)
    y += centre(d, clock, y, font(TIME_PX), white) + 18
    y += centre(d, date, y, font(DATE_PX), white) + 34

    apps = running_apps()
    if apps:
        shown = " · ".join(apps[:4])
        extra = len(apps) - min(len(apps), 4)
        label = "1 APP RUNNING" if len(apps) == 1 else f"{len(apps)} APPS RUNNING"
        fade = 0.57 if ambient else 1.0
        y += centre(d, label, y, font(ACTIVITY_PX, True),
                    (255, 255, 255, int(140 * fade))) + 8
        y += centre(d, shown + (f" +{extra}" if extra else ""), y,
                    font(ACTIVITY_PX), (255, 255, 255, int(110 * fade))) + 30

    if prompt:
        # .login-dialog-prompt-entry: 300x36, centred.
        ew, eh = 300, 36
        ex, ey = (W - ew) // 2, y + 20
        d.rounded_rectangle([ex, ey, ex + ew, ey + eh], 12,
                            fill=(255, 255, 255, 15),
                            outline=(255, 255, 255, 56))
        centre(d, "Password", ey - 26, font(PROMPT_PX), (255, 255, 255, 184))
    else:
        hint = "PRESS A KEY TO UNLOCK"
        tw = d.textbbox((0, 0), hint, font=font(HINT_PX, True))
        cw = tw[2] - tw[0]
        hx, hy = (W - cw) // 2, y + 10
        d.rounded_rectangle([hx - 12, hy - 5, hx + cw + 12, hy + 20], 9,
                            fill=(255, 255, 255, 10),
                            outline=(255, 255, 255, 40))
        d.text((hx, hy), hint, font=font(HINT_PX, True), fill=(255, 255, 255, 174))

    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/adaptive-lock-preview.png")
    ap.add_argument("--12h", dest="twelve", action="store_true")
    args = ap.parse_args()

    sheet = Image.new("RGB", (W, H * 3), (0, 0, 0))
    for i, (ambient, prompt) in enumerate(
        [(False, False), (True, False), (False, True)]
    ):
        sheet.paste(render(args.twelve, ambient, prompt), (0, H * i))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(f"wrote {args.out}")
    print("panels: just-locked / ambient (dimmed) / password prompt")


if __name__ == "__main__":
    main()
