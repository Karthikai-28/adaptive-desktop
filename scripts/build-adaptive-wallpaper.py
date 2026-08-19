#!/usr/bin/env python3
"""Generate the Adaptive wallpaper from the design tokens.

The desktop was still on Ubuntu's purple gradient, which fights a carbon and
orange system every time a window is moved. This draws a near-black woven
texture in the palette instead: dark enough to sit under bright windows without
competing, textured enough not to read as a flat void on an OLED panel.

Colours come from tokens/adaptive.tokens.json, so it follows the theme rather
than pinning its own hexes. Regenerate after editing the tokens:

    ./scripts/build-adaptive-wallpaper.py

No logo. The reference this palette came from is a trademark; the colours are
the part worth taking.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "tokens" / "adaptive.tokens.json"
OUT = REPO / "assets" / "wallpapers" / "adaptive-carbon.png"

WIDTH, HEIGHT = 3840, 2400
CELL = 16          # weave pitch, in pixels, before downsampling


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def main():
    colors = json.loads(TOKENS.read_text(encoding="utf-8"))["color"]

    deep = hex_rgb(colors["bg.deep"])
    canvas = hex_rgb(colors["bg.canvas"])
    surface = hex_rgb(colors["surface.1"])
    accent = hex_rgb(colors["accent.primary"])

    image = Image.new("RGB", (WIDTH, HEIGHT), deep)
    draw = ImageDraw.Draw(image)

    # Woven twill: alternating blocks catch the light in opposite directions,
    # which is what stops a near-black field looking like a dead pixel region.
    # The first pass was so subtle the weave vanished and the desktop read as
    # flat black. The strands need real separation to show at all.
    light = mix(surface, hex_rgb(colors["surface.2"]), 0.85)
    dark = deep

    for row, y in enumerate(range(0, HEIGHT, CELL)):
        for col, x in enumerate(range(0, WIDTH, CELL)):
            up = (row + col) % 2 == 0
            base = light if up else dark

            for i in range(CELL):
                t = i / max(CELL - 1, 1)
                shade = mix(base, deep, 0.15 + 0.55 * (t if up else 1 - t))
                draw.line(
                    [(x, y + i), (x + CELL - 1, y + i)],
                    fill=shade,
                )

    image = image.filter(ImageFilter.GaussianBlur(0.4))

    # A single low corner glow, so the desktop has a direction to it.
    glow = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    radius = int(WIDTH * 0.55)
    gdraw.ellipse(
        [-radius // 3, HEIGHT - radius // 2, radius, HEIGHT + radius // 2],
        fill=mix((0, 0, 0), accent, 0.30),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(WIDTH // 12))

    image = Image.blend(image, Image.blend(image, glow, 0.5), 0.42)

    # Vignette, so bright windows sit forward of the background.
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).ellipse(
        [-WIDTH // 5, -HEIGHT // 5, WIDTH + WIDTH // 5, HEIGHT + HEIGHT // 5],
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(WIDTH // 10))
    image = Image.composite(image, Image.new("RGB", image.size, deep), mask)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, optimize=True)

    print(f"Wrote {OUT.relative_to(REPO)}  {WIDTH}x{HEIGHT}")
    print(f"  base    {colors['bg.deep']}")
    print(f"  weave   {colors['bg.canvas']} / {colors['surface.1']}")
    print(f"  glow    {colors['accent.primary']}")


if __name__ == "__main__":
    main()
