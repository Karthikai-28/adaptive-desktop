#!/usr/bin/env python3
"""Generate the Adaptive desktop background from the design tokens.

The desktop background was the last stock-Ubuntu surface left in the session -
warty-final-ubuntu.png behind an otherwise Adaptive shell. This generates a
replacement from tokens/adaptive.tokens.json so the wallpaper cannot drift from
the palette the rest of the system is built on.

Three decisions worth keeping:

* Near-solid, not a picture. DESIGN_SYSTEM.md rules out random gradients and
  sci-fi decoration, and the dock, rail and palette all sit directly on this
  surface - a busy background would fight every one of them for contrast. The
  image spans bg.deep to bg.canvas, which is a one-value ramp.
* One soft off-centre bloom in accent.primary at 3% alpha, placed upper-left so
  the dock along the bottom stays on the darkest part of the image. Enough to
  keep the frame from reading as a flat fill, far below the threshold where it
  becomes a "glow".
* Composited in float, quantised exactly once. Everything here lives in the
  bottom 4% of the range, where 8-bit steps are wide enough to see: rounding
  the bloom mask to uint8 before compositing leaves it about 8 distinct values
  and renders as concentric contour rings, and an undithered vertical ramp
  bands horizontally. So the arithmetic stays float32 to the last line, and the
  only rounding is after the dither.

Rendered at 2x the panel (3840x2400) so an external monitor has headroom.

    ./scripts/build-adaptive-backgrounds.py
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "tokens" / "adaptive.tokens.json"
OUT = REPO / "design" / "backgrounds"

WIDTH = 3840
HEIGHT = 2400

# Bloom geometry as a fraction of the frame.
BLOOM_CX = 0.34
BLOOM_CY = 0.30
BLOOM_R = 0.62
BLOOM_ALPHA = 0.03

# Dither amplitude in LSB. 1.0 is the standard TPDF width for 8-bit output.
DITHER = 1.0

# Seeded so an unchanged token file rebuilds a byte-identical PNG rather than
# showing up as a diff on every run.
SEED = 0x0811_1B


def rgb(value):
    value = value.lstrip("#")
    return np.array(
        [int(value[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32
    )


def render(top, bottom, accent):
    # 1D bases broadcast into the frame; a full mgrid at this size costs 150 MB
    # and buys nothing.
    ys = np.linspace(0.0, 1.0, HEIGHT, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, WIDTH, dtype=np.float32)[None, :]

    ramp = top[None, None, :] + (bottom - top)[None, None, :] * ys[:, :, None]

    dx = (xs - BLOOM_CX) / BLOOM_R
    dy = (ys - BLOOM_CY) / (BLOOM_R * 1.15)
    alpha = (np.exp(-2.5 * (dx * dx + dy * dy)) * BLOOM_ALPHA)[:, :, None]

    frame = ramp * (1.0 - alpha) + accent[None, None, :] * alpha

    rand = np.random.default_rng(SEED)
    # Triangular (TPDF) dither: the difference of two uniforms, spanning one
    # LSB either side. Integer noise picked from {-1, 0, 1} does not decorrelate
    # the rounding error and leaves the contours it was meant to remove; TPDF
    # is the standard fix and is what makes a 4% -range ramp read as smooth.
    # One value per pixel applied to all three channels, so the grain reads as
    # luminance and does not tint the surface.
    noise = (rand.random((HEIGHT, WIDTH), dtype=np.float32)
             - rand.random((HEIGHT, WIDTH), dtype=np.float32)) * DITHER
    frame = frame + noise[:, :, None]

    # rint, not a bare astype: astype(uint8) truncates toward zero, which biases
    # every pixel down half a level and cancels out most of the dither.
    return Image.fromarray(np.clip(np.rint(frame), 0, 255).astype(np.uint8), "RGB")


def main():
    color = json.loads(TOKENS.read_text(encoding="utf-8"))["color"]

    image = render(
        rgb(color["bg.deep"]),
        rgb(color["bg.canvas"]),
        rgb(color["accent.primary"]),
    )

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "adaptive-desktop.png"
    image.save(target, "PNG", optimize=True)
    print(f"  {target}  {WIDTH}x{HEIGHT}")


if __name__ == "__main__":
    main()
