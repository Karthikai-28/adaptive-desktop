#!/usr/bin/env python3
"""Move every stylesheet from the old blue palette to the carbon/orange one.

The system was built on blue-tinted neutrals with a blue accent. The new theme
is carbon black with a single orange accent and pure-neutral greys. Around 150
colour values carry that across the shell, the Files inspector and the apps,
and editing them by hand is how contrast relationships get quietly broken.

So this changes hue and leaves lightness alone. A grey that was 62% light stays
62% light, it just stops being blue - which keeps every contrast ratio the
design was tuned for while changing what colour the system reads as.

Two rules:

* Accent colours - the saturated blues, cyans and violets - are mapped
  explicitly. There is no sensible arithmetic from "blue accent" to "orange
  accent" that lands on the brand colour, so the targets are named.
* Everything else that is blue-tinted is desaturated to a pure neutral of the
  same lightness. Pure white, pure black and the non-blue status colours
  (warning, danger, success) are left for the explicit map.

    ./scripts/retint-palette.py --check    # report, change nothing
    ./scripts/retint-palette.py            # rewrite in place
"""

import argparse
import colorsys
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TARGETS = [
    "shell/adaptive-shell@local/stylesheet.css",
    "extension/preview.css",
    "apps/adaptive-command/style.css",
    "apps/adaptive-projects/style.css",
    "apps/adaptive-projects/main.py",
    # Hand-maintained and forced on Files by adaptive-files-dispatch.sh via
    # GTK_THEME, so it overrides the generated session theme. Until its
    # Nautilus component rules are folded into build-adaptive-theme.py it has
    # to be retinted alongside everything else or Files keeps the old palette.
    "theme/AdaptiveFiles/gtk-3.0/gtk.css",
    "theme/AdaptiveFiles/gtk-3.0/gtk-dark.css",
    # The icon set is artwork, not styling, and it was painted in the old
    # palette - which is where the last of the blue was hiding after every
    # stylesheet had been converted.
    "icons/AdaptiveFilesIcons/**/*.svg",
]

# Named mappings. Blue -> orange has no arithmetic that lands on the brand
# colour, so these say exactly where each accent goes.
EXPLICIT = {
    # blue accent -> LexCorp orange
    "#78A9FF": "#F26522",
    "#8CB7FF": "#FF8340",
    "#5C93F0": "#D9551A",
    "#4A7FD8": "#C24A17",
    # cyan -> amber highlight
    "#66E0FF": "#FF9147",
    "#4FD2F5": "#F5822E",
    # violet -> steel, the grey half of the logo
    "#9A8BFF": "#A3A3A3",
    # status colours: keep their meaning, retune so they sit in a
    # carbon/orange system rather than a blue one
    "#F3C96B": "#FFC947",
    "#FF7A90": "#E0524C",
    "#65D9B5": "#52B788",
    # canvas and surfaces
    "#08111B": "#0D0D0D",
    "#07101A": "#080808",
    "#111A28": "#171717",
    "#162233": "#212121",
    "#30425C": "#3A3A3A",
    "#F2F6EF": "#F5F5F5",
    "#96A4B8": "#8E8E8E",
}

EXPLICIT = {k.upper(): v for k, v in EXPLICIT.items()}

HEX = re.compile(r"#([0-9A-Fa-f]{6})\b")
RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(,[^)]*)?\)")

# Blue-ish hue band, as a fraction of the colour wheel: roughly 170-280 degrees.
BLUE_LO, BLUE_HI = 170 / 360.0, 280 / 360.0


def neutralise(r, g, b):
    """Same lightness, no hue. Returns None if the colour is not blue-tinted."""
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

    if s < 0.02:
        return None                      # already neutral
    if not (BLUE_LO <= h <= BLUE_HI):
        return None                      # not ours to touch

    v = round(l * 255)
    return v, v, v


def convert_hex(match):
    value = "#" + match.group(1).upper()

    if value in EXPLICIT:
        return EXPLICIT[value]

    r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
    neutral = neutralise(r, g, b)

    if neutral is None:
        return match.group(0)

    return "#{:02X}{:02X}{:02X}".format(*neutral)


def convert_rgba(match):
    r, g, b = (int(match.group(i)) for i in (1, 2, 3))
    tail = match.group(4) or ""
    prefix = match.group(0)[:match.group(0).index("(")]

    key = "#{:02X}{:02X}{:02X}".format(r, g, b)

    if key in EXPLICIT:
        target = EXPLICIT[key]
        r, g, b = (int(target[i:i + 2], 16) for i in (1, 3, 5))
        return f"{prefix}({r}, {g}, {b}{tail})"

    neutral = neutralise(r, g, b)
    if neutral is None:
        return match.group(0)

    r, g, b = neutral
    return f"{prefix}({r}, {g}, {b}{tail})"


def convert(text):
    text = HEX.sub(convert_hex, text)
    text = RGBA.sub(convert_rgba, text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report what would change, write nothing")
    args = ap.parse_args()

    total = 0

    for name in TARGETS:
        if "*" in name:
            paths = sorted(REPO.glob(name))
            if not paths:
                print(f"  skip  {name} (no matches)")
                continue
        else:
            path = REPO / name
            if not path.exists():
                print(f"  skip  {name} (missing)")
                continue
            paths = [path]

        # A glob is reported as one line, or 110 icons bury everything else.
        if len(paths) > 1:
            edited = 0
            for path in paths:
                before = path.read_text(encoding="utf-8")
                after = convert(before)
                if before != after:
                    edited += 1
                    if not args.check:
                        path.write_text(after, encoding="utf-8")
            total += edited
            print(f"  {'would edit' if args.check else 'edited    '} "
                  f"{name}: {edited} of {len(paths)} file(s)")
            continue

        path = paths[0]

        before = path.read_text(encoding="utf-8")
        after = convert(before)

        changed = sum(1 for a, b in zip(before.split("\n"), after.split("\n"))
                      if a != b)

        if before == after:
            print(f"  ok    {name} (nothing to change)")
            continue

        total += changed
        print(f"  {'would edit' if args.check else 'edited    '} "
              f"{name}: {changed} line(s)")

        if not args.check:
            path.write_text(after, encoding="utf-8")

    print()
    print(f"{total} line(s) {'would change' if args.check else 'changed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
