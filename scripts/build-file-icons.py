#!/usr/bin/env python3
"""Generate the Adaptive Files icon set (icons/AdaptiveFilesIcons) - liquid glass.

Three kinds of icon come out of one glyph library, so a folder, the file
inside it and the sidebar row that leads there all draw the same picture:

  places/   full-colour folders: blue glass, the place's glyph engraved on
            the front plate; plus Home, Desktop, Trash and friends.
  devices/  full-colour glass devices (disk, USB stick, disc, laptop, phone).
  mimetypes/ full-colour glass pages: a frosted sheet with a folded corner,
            the type's glyph in its colour and, where the glyph alone cannot
            tell two types apart, the extension on a pill (as Finder does).
  *-symbolic  the bare glyph, for the sidebar and path bar. Fill only: GTK
            recolours symbolic icons by overriding fill, so every glyph is
            built from filled outlines (round-capped strokes are expanded
            into capsules here) and never relies on an SVG stroke.

Colours are Apple's dark-appearance system colours. The chrome stays
single-accent (blue); type colours appear only on the glyph and label of a
file page, the way Finder's document icons carry their app's colour.

The label text is converted to outlines with cairo at build time, so the
icons do not depend on a font being installed where they are rendered.

The generator owns places/, devices/ and mimetypes/: it clears them and
writes them again. apps/, actions/ and emblems/ are drawn by hand and left
alone. Aliases (several MIME names, one drawing) are relative symlinks.

    ./scripts/build-file-icons.py            # regenerate in place
    ./scripts/build-file-icons.py --check    # exit 1 if the tree is stale
"""

import math
import shutil
import sys
import tempfile
from pathlib import Path

import cairo

REPO = Path(__file__).resolve().parent.parent
THEME = REPO / "icons" / "AdaptiveFilesIcons" / "scalable"
MANAGED = ("places", "devices", "mimetypes")

# Apple dark-appearance system colours.
C = {
    "blue": "#0A84FF", "indigo": "#5E5CE6", "purple": "#BF5AF2", "pink": "#FF375F",
    "red": "#FF453A", "orange": "#FF9F0A", "yellow": "#FFD60A", "green": "#30D158",
    "mint": "#66D4CF", "teal": "#40C8E0", "cyan": "#64D2FF", "brown": "#AC8E68",
    "silver": "#D1D1D6", "sand": "#D4B48A",
}


def fmt(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


# ---------------------------------------------------------------------------
# Geometry, in a 24 x 24 box. Every helper returns path data; outer shapes
# wind clockwise and holes anticlockwise, so one path filled with the
# nonzero rule unions the shapes and still cuts the holes.
# ---------------------------------------------------------------------------

def cap(x1, y1, x2, y2, w):
    """A round-capped segment as a filled capsule."""
    r = w / 2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return circle(x1, y1, r)
    nx, ny = -dy / length * r, dx / length * r
    a, b = (x1 + nx, y1 + ny), (x2 + nx, y2 + ny)
    c, d = (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)
    if _area([a, b, c, d]) < 0:
        a, b, c, d = d, c, b, a
    return (f"M{fmt(a[0])},{fmt(a[1])}L{fmt(b[0])},{fmt(b[1])}"
            f"A{fmt(r)},{fmt(r)} 0 0 1 {fmt(c[0])},{fmt(c[1])}"
            f"L{fmt(d[0])},{fmt(d[1])}A{fmt(r)},{fmt(r)} 0 0 1 {fmt(a[0])},{fmt(a[1])}Z")


def stroke(points, w, closed=False):
    pts = list(points) + ([points[0]] if closed else [])
    return "".join(cap(*pts[i], *pts[i + 1], w) for i in range(len(pts) - 1))


def ellipse(cx, cy, rx, ry, cw=True):
    s = 1 if cw else 0
    return (f"M{fmt(cx - rx)},{fmt(cy)}A{fmt(rx)},{fmt(ry)} 0 1 {s} {fmt(cx + rx)},{fmt(cy)}"
            f"A{fmt(rx)},{fmt(ry)} 0 1 {s} {fmt(cx - rx)},{fmt(cy)}Z")


def circle(cx, cy, r, cw=True):
    return ellipse(cx, cy, r, r, cw)


def ring(cx, cy, r, w):
    return circle(cx, cy, r + w / 2) + circle(cx, cy, r - w / 2, cw=False)


def ering(cx, cy, rx, ry, w):
    return ellipse(cx, cy, rx + w / 2, ry + w / 2) + ellipse(cx, cy, rx - w / 2, ry - w / 2, cw=False)


def rrect(x, y, w, h, r, cw=True):
    r = min(r, w / 2, h / 2)
    R = fmt(r)
    if cw:
        return (f"M{fmt(x + r)},{fmt(y)}H{fmt(x + w - r)}A{R},{R} 0 0 1 {fmt(x + w)},{fmt(y + r)}"
                f"V{fmt(y + h - r)}A{R},{R} 0 0 1 {fmt(x + w - r)},{fmt(y + h)}"
                f"H{fmt(x + r)}A{R},{R} 0 0 1 {fmt(x)},{fmt(y + h - r)}"
                f"V{fmt(y + r)}A{R},{R} 0 0 1 {fmt(x + r)},{fmt(y)}Z")
    return (f"M{fmt(x + r)},{fmt(y)}A{R},{R} 0 0 0 {fmt(x)},{fmt(y + r)}"
            f"V{fmt(y + h - r)}A{R},{R} 0 0 0 {fmt(x + r)},{fmt(y + h)}"
            f"H{fmt(x + w - r)}A{R},{R} 0 0 0 {fmt(x + w)},{fmt(y + h - r)}"
            f"V{fmt(y + r)}A{R},{R} 0 0 0 {fmt(x + w - r)},{fmt(y)}Z")


def rring(x, y, w, h, r, t):
    return rrect(x, y, w, h, r) + rrect(x + t, y + t, w - 2 * t, h - 2 * t, max(r - t, 0.4), cw=False)


def _area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))


def poly(points, cw=True):
    pts = list(points)
    if (_area(pts) > 0) != cw:
        pts.reverse()
    return "M" + "L".join(f"{fmt(x)},{fmt(y)}" for x, y in pts) + "Z"


def arc(cx, cy, rx, ry, a0, a1, n=14):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def bezier(p0, p1, p2, p3, n=12):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(tuple(u ** 3 * p0[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t ** 3 * p3[k]
                         for k in (0, 1)))
    return out


def text_path(text, size, weight=cairo.FONT_WEIGHT_BOLD):
    """Text as path data with its ink box: (d, x0, y0, width, height)."""
    surface = cairo.ImageSurface(cairo.FORMAT_A8, 8, 8)
    ctx = cairo.Context(surface)
    ctx.select_font_face("Inter", cairo.FONT_SLANT_NORMAL, weight)
    ctx.set_font_size(size)
    ext = ctx.text_extents(text)
    ctx.move_to(-ext.x_bearing, -ext.y_bearing)
    ctx.text_path(text)
    d = []
    for kind, pts in ctx.copy_path():
        if kind == cairo.PATH_MOVE_TO:
            d.append(f"M{fmt(pts[0])},{fmt(pts[1])}")
        elif kind == cairo.PATH_LINE_TO:
            d.append(f"L{fmt(pts[0])},{fmt(pts[1])}")
        elif kind == cairo.PATH_CURVE_TO:
            d.append("C" + ",".join(fmt(v) for v in pts))
        else:
            d.append("Z")
    return "".join(d), ext.width, ext.height


# ---------------------------------------------------------------------------
# Glyphs (24 x 24)
# ---------------------------------------------------------------------------

def g_folder():
    return ("M3,7Q3,5 5,5H9.4Q10.2,5 10.8,5.6L12.2,7H19Q21,7 21,9V17.5Q21,19.5 19,19.5H5Q3,19.5 3,17.5Z"
            + rrect(4.8, 9.4, 14.4, 8.3, 0.6, cw=False))


def g_doc():
    return ("M7,2.5H13.6L19,7.9V19.5Q19,21.5 17,21.5H7Q5,21.5 5,19.5V4.5Q5,2.5 7,2.5Z"
            "M7.2,4.2Q6.7,4.2 6.7,4.7V19.3Q6.7,19.8 7.2,19.8H16.8Q17.3,19.8 17.3,19.3V9.4H13.6"
            "Q12.4,9.4 12.4,8.2V4.2Z"
            + cap(9, 13.4, 15, 13.4, 1.6) + cap(9, 16.6, 13, 16.6, 1.6))


def g_lines():
    return (cap(4, 5.5, 20, 5.5, 2) + cap(4, 10, 16, 10, 2) + cap(4, 14.5, 20, 14.5, 2)
            + cap(4, 19, 11, 19, 2))


def g_paragraph():
    return (cap(4, 4.5, 14, 4.5, 2.6) + cap(4, 9.5, 20, 9.5, 1.8) + cap(4, 13.5, 20, 13.5, 1.8)
            + cap(4, 17.5, 20, 17.5, 1.8) + cap(4, 21.2, 13, 21.2, 1.8))


def g_list():
    out = ""
    for y in (5.5, 12, 18.5):
        out += circle(4.5, y, 1.5) + cap(9, y, 20.5, y, 2)
    return out


def g_markdown():
    return (rring(1.5, 5, 21, 14, 3, 1.6)
            + stroke([(5.6, 15.4), (5.6, 8.8), (8.8, 12.2), (12, 8.8), (12, 15.4)], 1.8)
            + cap(17, 8.6, 17, 14.6, 1.8) + stroke([(14.4, 12.4), (17, 15.2), (19.6, 12.4)], 1.8))


def g_code():
    return (stroke([(8, 6.5), (3, 12), (8, 17.5)], 2.1) + stroke([(16, 6.5), (21, 12), (16, 17.5)], 2.1)
            + cap(14, 4.5, 10, 19.5, 2.1))


def g_terminal():
    return stroke([(4, 6), (10, 12), (4, 18)], 2.3) + cap(12.5, 18, 20.5, 18, 2.3)


def g_braces():
    left = [(10, 3.5), (8.4, 3.8), (7.6, 5), (7.6, 9.6), (6.9, 11.3), (4.8, 12), (6.9, 12.7),
            (7.6, 14.4), (7.6, 19), (8.4, 20.2), (10, 20.5)]
    right = [(24 - x, y) for x, y in left]
    return stroke(left, 2) + stroke(right, 2)


def g_sliders():
    out = ""
    for y, knob in ((5.5, 15.5), (12, 8), (18.5, 13)):
        out += cap(3, y, 21, y, 1.7) + circle(knob, y, 2.8)
    return out


def g_gear():
    pts = []
    for i in range(8):
        a = i * 45
        for da, r in ((-15, 7.2), (-9, 9.6), (9, 9.6), (15, 7.2)):
            t = math.radians(a + da)
            pts.append((12 + r * math.cos(t), 12 + r * math.sin(t)))
    return poly(pts) + circle(12, 12, 3, cw=False)


def g_table():
    return (rring(2.5, 3.5, 19, 17, 2.8, 1.7) + rrect(2.5, 3.5, 19, 5.6, 2.8)
            + cap(3.4, 14.4, 20.6, 14.4, 1.4) + cap(9.8, 8.5, 9.8, 19.6, 1.4))


def g_database():
    return (ering(12, 5.8, 7.6, 2.8, 1.7) + cap(4.4, 5.8, 4.4, 18.2, 1.7) + cap(19.6, 5.8, 19.6, 18.2, 1.7)
            + stroke(arc(12, 12, 7.6, 2.8, 0, 180), 1.7) + stroke(arc(12, 18.2, 7.6, 2.8, 0, 180), 1.7))


def g_photo():
    return (rring(2, 4, 20, 16, 3.2, 1.7)
            + poly([(5.2, 17.2), (10, 11.2), (13.6, 15), (15.6, 12.8), (18.8, 17.2)])
            + circle(16, 8.8, 1.8))


def g_play():
    return rrect(2, 4.5, 20, 15, 3.8) + poly([(9.8, 8.4), (9.8, 15.6), (15.8, 12)], cw=False)


def g_wave():
    out = ""
    for x, h in ((3.2, 3), (6.7, 9), (10.2, 15), (13.7, 11), (17.2, 6.5), (20.7, 3)):
        out += cap(x, 12 - h / 2, x, 12 + h / 2, 2.4)
    return out


def g_note():
    return (ellipse(7.6, 17.8, 3.2, 2.6) + ellipse(16.6, 15.8, 3.2, 2.6)
            + rrect(9.3, 6, 1.8, 11.8, 0.5) + rrect(18.3, 4, 1.8, 11.8, 0.5)
            + poly([(9.3, 6), (20.1, 3.2), (20.1, 6.6), (9.3, 9.4)]))


def g_zip():
    out = ""
    for i in range(4):
        y = 1 + i * 2.85
        out += rrect(7.4 if i % 2 else 12, y, 4.6, 2.2, 0.8)
    return out + rring(7.2, 12.6, 9.6, 10.6, 2.6, 2.2) + rrect(10.9, 15.4, 2.2, 4.8, 0.8)


def _hexagon():
    return [(12, 2.5), (20.5, 7.2), (20.5, 16.8), (12, 21.5), (3.5, 16.8), (3.5, 7.2)]


def g_package():
    return (stroke(_hexagon(), 1.8, closed=True) + stroke([(3.5, 7.2), (12, 12), (20.5, 7.2)], 1.8)
            + cap(12, 12, 12, 21.5, 1.8) + cap(7.6, 4.9, 16.2, 9.6, 1.8))


def g_cube():
    return (stroke(_hexagon(), 1.8, closed=True) + poly([(12, 2.5), (20.5, 7.2), (12, 12), (3.5, 7.2)])
            + cap(12, 12, 12, 21.5, 1.8))


def g_chip():
    out = rring(5.5, 5.5, 13, 13, 2.4, 1.7) + rrect(9.2, 9.2, 5.6, 5.6, 1.2)
    for p in (9, 12, 15):
        out += (cap(p, 2.2, p, 5, 1.5) + cap(p, 19, p, 21.8, 1.5)
                + cap(2.2, p, 5, p, 1.5) + cap(19, p, 21.8, p, 1.5))
    return out


def g_font():
    d, w, h = text_path("Aa", 16)
    s = min(20 / w, 15 / h)
    return f'<path transform="translate({fmt(12 - w * s / 2)},{fmt(12 - h * s / 2)}) scale({fmt(s)})" d="{d}"/>'


def g_disc():
    return (circle(12, 12, 9.8) + circle(12, 12, 4.4, cw=False) + circle(12, 12, 3.4)
            + circle(12, 12, 1.7, cw=False))


def g_key():
    return (ring(7.2, 12, 3.9, 2.1) + cap(11.2, 12, 21, 12, 2.3) + cap(17.6, 12, 17.6, 16, 2.3)
            + cap(21, 12, 21, 15, 2.3))


def g_lock():
    return (rrect(4.5, 10.2, 15, 11.3, 2.6) + circle(12, 15.2, 1.9, cw=False)
            + stroke(arc(12, 10.2, 4.6, 5.2, 180, 360), 2.1))


def g_shield():
    return ("M12,2.4L19.6,5.2V11Q19.6,17.6 12,21.6Q4.4,17.6 4.4,11V5.2Z"
            "M12,4.3L6.2,6.4V11Q6.2,16.4 12,19.6Q17.8,16.4 17.8,11V6.4Z"
            + stroke([(8.6, 11.8), (11, 14.2), (15.4, 9.4)], 1.9))


def g_calendar():
    out = rring(2.5, 4, 19, 17, 3, 1.7) + rrect(2.5, 4, 19, 5.8, 3)
    out += cap(7.6, 2.4, 7.6, 6, 2) + cap(16.4, 2.4, 16.4, 6, 2)
    for x, y in ((7.6, 13), (12, 13), (16.4, 13), (7.6, 17), (12, 17)):
        out += circle(x, y, 1.2)
    return out


def g_person():
    return circle(12, 7.8, 4) + "M4.2,20.8Q4.2,13.6 12,13.6Q19.8,13.6 19.8,20.8Z"


def g_share():
    return (stroke([(8.2, 9), (5.2, 9), (5.2, 20.6), (18.8, 20.6), (18.8, 9), (15.8, 9)], 1.9)
            + cap(12, 3, 12, 14.5, 1.9) + stroke([(8.4, 6.4), (12, 2.9), (15.6, 6.4)], 1.9))


def g_globe():
    return (ring(12, 12, 9.2, 1.8) + ering(12, 12, 4, 9.2, 1.5) + cap(3.2, 12, 20.8, 12, 1.5))


def g_star():
    pts = []
    for i in range(10):
        r = 10.2 if i % 2 == 0 else 4.4
        t = math.radians(-90 + i * 36)
        pts.append((12 + r * math.cos(t), 12.8 + r * math.sin(t)))
    return poly(pts)


def g_clock():
    return ring(12, 12, 9.1, 1.9) + stroke([(12, 6.6), (12, 12), (15.8, 14.3)], 2)


def g_search():
    return ring(10.4, 10.4, 6.4, 2.1) + cap(15.2, 15.2, 20.4, 20.4, 2.9)


def g_home():
    return (stroke([(2.6, 11.6), (12, 3.4), (21.4, 11.6)], 2.2)
            + stroke([(5.6, 10), (5.6, 20.6), (18.4, 20.6), (18.4, 10)], 2)
            + rrect(10, 14, 4, 6.6, 1))


def g_desktop():
    return (rring(2, 3.4, 20, 13.6, 2.4, 1.8) + rrect(10.5, 16.4, 3, 3.4, 0.4)
            + cap(7.4, 20.4, 16.6, 20.4, 2))


def g_download():
    return (cap(12, 2.8, 12, 13.6, 2.1) + stroke([(7.4, 9.4), (12, 14), (16.6, 9.4)], 2.1)
            + stroke([(3.8, 14.4), (3.8, 19.6), (20.2, 19.6), (20.2, 14.4)], 2.1))


def g_templates():
    return (stroke([(7.2, 6.6), (7.2, 3.4), (20.6, 3.4), (20.6, 16.8), (17.4, 16.8)], 1.7)
            + rring(3, 7, 14, 14, 2.6, 1.7))


def g_trash(full=False):
    lid = cap(3.4, 6, 20.6, 6, 2) + stroke([(9, 5.6), (9, 3), (15, 3), (15, 5.6)], 1.7)
    if full:
        return lid + poly([(5.2, 8.6), (18.8, 8.6), (17.5, 20.8), (6.5, 20.8)])
    return (lid + stroke([(5.6, 8.6), (6.8, 20.4), (17.2, 20.4), (18.4, 8.6)], 1.9)
            + cap(10, 10.8, 10.3, 17.6, 1.5) + cap(14, 10.8, 13.7, 17.6, 1.5))


def g_drive():
    return rring(2, 6, 20, 12, 3, 1.8) + cap(5.6, 12, 12.4, 12, 1.6) + circle(17.2, 12, 1.5)


def g_usb():
    return (rring(1.8, 7, 14, 10, 2.4, 1.8) + rrect(15, 8.6, 7, 6.8, 1.2)
            + rrect(17, 10.4, 1.6, 1.4, 0.3, cw=False) + rrect(17, 12.6, 1.6, 1.4, 0.3, cw=False))


def g_server():
    return (rring(2.5, 3, 19, 8, 2.2, 1.7) + rring(2.5, 13, 19, 8, 2.2, 1.7)
            + circle(17, 7, 1.2) + circle(17, 17, 1.2) + cap(6.4, 7, 10.4, 7, 1.5) + cap(6.4, 17, 10.4, 17, 1.5))


def g_laptop():
    return (rring(4, 4, 16, 11.6, 2, 1.7)
            + "M2.6,17.4H21.4Q21.4,20 19,20H5Q2.6,20 2.6,17.4Z")


def g_phone():
    return rring(6.5, 2, 11, 20, 2.8, 1.7) + cap(10.6, 18.2, 13.4, 18.2, 1.4)


def g_rocket():
    return ("M12,2.4C15.6,5 16.7,9.4 16.1,14.8H7.9C7.3,9.4 8.4,5 12,2.4Z"
            + circle(12, 8.8, 1.9, cw=False)
            + poly([(8.2, 10.6), (4.8, 14.6), (4.8, 17.6), (8.6, 15.2)])
            + poly([(15.8, 10.6), (19.2, 14.6), (19.2, 17.6), (15.4, 15.2)])
            + poly([(9.8, 16.2), (14.2, 16.2), (12, 21.6)]))


def g_robot():
    return (rrect(3, 18.4, 10.4, 3.2, 1.2) + stroke([(8.2, 18.4), (8.2, 12.8), (14.6, 7.4)], 2.5)
            + circle(8.2, 12.8, 2.4) + circle(14.6, 7.4, 2.4) + cap(14.6, 7.4, 18.8, 11.2, 2.2)
            + cap(18.8, 11.2, 18.2, 15, 1.7) + cap(18.8, 11.2, 22, 13.2, 1.7))


def g_bubble():
    return (rring(2, 3, 20, 14, 3.2, 1.7) + poly([(6.6, 16.2), (6.6, 21.4), (12, 16.2)])
            + cap(6.6, 8.2, 17.4, 8.2, 1.7) + cap(6.6, 11.8, 13.6, 11.8, 1.7))


def g_record():
    return ring(12, 12, 9.2, 1.8) + circle(12, 12, 4.8)


def g_neural():
    a = [(4.4, 7), (4.4, 17)]
    b = [(12, 4.2), (12, 12), (12, 19.8)]
    c = [(19.6, 12)]
    out = ""
    for p in a:
        for q in b:
            out += cap(*p, *q, 1.1)
    for p in b:
        for q in c:
            out += cap(*p, *q, 1.1)
    for x, y in a + b + c:
        out += circle(x, y, 2.3)
    return out


def g_grid():
    out = ""
    for x in (3, 9.5, 16):
        for y in (3, 9.5, 16):
            out += rrect(x, y, 5, 5, 1.3)
    return out


def g_notebook():
    out = rring(5.2, 2.2, 15.6, 19.6, 2.6, 1.7)
    for y in (6.6, 12, 17.4):
        out += cap(2.8, y, 6.8, y, 1.7)
    return out + rrect(9.2, 6.6, 7.8, 3.6, 1) + rrect(9.2, 12.4, 7.8, 5, 1)


def g_container():
    out = ""
    for x, y in ((2.6, 12.6), (9.3, 12.6), (16, 12.6), (6, 5.9), (12.7, 5.9)):
        out += rrect(x, y, 5.4, 5.4, 1.1)
    return out + cap(2.6, 20.6, 21.4, 20.6, 1.7)


def g_wrench():
    return cap(4.6, 19.4, 13.2, 10.8, 3.2) + stroke(arc(16.2, 7.8, 3.8, 3.8, 352, 638, 18), 2.7)


def g_branch():
    return (ring(6.4, 4.8, 2.2, 1.7) + ring(6.4, 19.2, 2.2, 1.7) + ring(17.6, 7.4, 2.2, 1.7)
            + cap(6.4, 7, 6.4, 17, 1.8)
            + stroke(bezier((17.6, 9.6), (17.6, 14.2), (8.4, 12.6), (6.6, 16.6)), 1.8))


def g_diff():
    return (cap(12, 3, 12, 12, 2.2) + cap(7.5, 7.5, 16.5, 7.5, 2.2) + cap(7.5, 18, 16.5, 18, 2.2))


def g_drop():
    return "M12,2.6C12,2.6 5,10.4 5,14.6A7,7 0 0 0 19,14.6C19,10.4 12,2.6 12,2.6Z"


def g_vector():
    curve = bezier((4.4, 17.6), (4.4, 7.6), (19.6, 16.4), (19.6, 6.4))
    return (stroke(curve, 1.9) + rrect(2.2, 15.4, 4.4, 4.4, 0.9) + rrect(17.4, 4.2, 4.4, 4.4, 0.9)
            + cap(4.4, 15, 4.4, 9.4, 1.1) + circle(4.4, 8.6, 1.5)
            + cap(19.6, 9, 19.6, 14.6, 1.1) + circle(19.6, 15.4, 1.5))


def g_presentation():
    return (rring(2, 3, 20, 13.6, 2.2, 1.7) + rrect(6.6, 9.6, 2.6, 4.2, 0.6)
            + rrect(10.7, 6.8, 2.6, 7, 0.6) + rrect(14.8, 8.4, 2.6, 5.4, 0.6)
            + cap(12, 16.6, 12, 20.4, 1.8) + cap(8.4, 20.6, 15.6, 20.6, 1.8))


def g_book():
    left = [(12, 6.4), (9.2, 4.8), (3.2, 4.8), (3.2, 18.4), (9.2, 18.4), (12, 20)]
    return stroke(left, 1.8) + stroke([(24 - x, y) for x, y in left], 1.8) + cap(12, 6.4, 12, 20, 1.8)


def g_apps():
    return "".join(rrect(x, y, 7.6, 7.6, 2.2) for x in (3.2, 13.2) for y in (3.2, 13.2))


def g_exec():
    return rring(2, 3.5, 20, 17, 3, 1.7) + stroke([(6, 9), (9.6, 12), (6, 15)], 1.9) + cap(11.6, 15.4, 17.4, 15.4, 1.9)


GLYPHS = {name[2:]: fn for name, fn in globals().items() if name.startswith("g_")}


def glyph(name):
    d = GLYPHS[name]() if name != "trash_full" else g_trash(full=True)
    return d


def glyph_element(d, **attrs):
    """A glyph as one SVG element (text glyphs are already an element)."""
    extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    if d.startswith("<path"):
        return f"<g{extra}>{d}</g>"
    return f'<path{extra} d="{d}"/>'


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def rgb(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    ra, rb = rgb(a), rgb(b)
    return "#" + "".join(f"{round(ra[i] + (rb[i] - ra[i]) * t):02X}" for i in range(3))


def luminance(hex_):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------------------
# Full-colour drawings (64 x 64)
# ---------------------------------------------------------------------------

SHADOW = ('<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">'
          '<feGaussianBlur stdDeviation="1.8"/></filter>')


def svg(body, defs=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'
            f"<defs>{SHADOW}{defs}</defs>\n{body}\n</svg>\n")


def placed(d, cx, cy, size):
    s = size / 24
    return f'transform="translate({fmt(cx - 12 * s)},{fmt(cy - 12 * s)}) scale({fmt(s)})"', d


def folder(name=None, open_=False):
    """Blue glass folder; the place's glyph is engraved on the front plate."""
    front_y = 25 if open_ else 22
    defs = (
        '<linearGradient id="back" x1="0" y1="10" x2="0" y2="54" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#2F86F0"/><stop offset="1" stop-color="#0B4FB4"/></linearGradient>'
        '<linearGradient id="front" x1="0" y1="20" x2="0" y2="56" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#8CC8FF" stop-opacity=".94"/>'
        '<stop offset=".5" stop-color="#4AA2FF" stop-opacity=".9"/>'
        '<stop offset="1" stop-color="#1679EC" stop-opacity=".92"/></linearGradient>'
        '<linearGradient id="sheen" x1="0" y1="20" x2="0" y2="40" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".34"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>'
        '<linearGradient id="rim" x1="0" y1="20" x2="0" y2="56" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".75"/>'
        '<stop offset=".35" stop-color="#FFFFFF" stop-opacity=".18"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".28"/></linearGradient>'
    )
    if open_:
        front = "M4,26.5Q4.6,25 6.2,25H57.8Q59.4,25 60,26.5L57.2,51Q56.8,54 53.8,54H10.2Q7.2,54 6.8,51Z"
    else:
        front = rrect(6, front_y, 52, 54 - front_y, 5.5)
    body = [
        f'<path d="{rrect(9, 15, 46, 41, 6)}" fill="#000" opacity=".42" filter="url(#shadow)" transform="translate(0,1.6)"/>',
        '<path d="M6,15.5Q6,11 10.5,11H23.4Q25.2,11 26.4,12.3L29,15H53.5Q58,15 58,19.5V48H6Z" fill="url(#back)"/>',
        '<path d="M8,15.6H24.6" stroke="#FFFFFF" stroke-opacity=".35" stroke-width=".8" fill="none" stroke-linecap="round"/>',
        f'<path d="{rrect(10, 18, 44, 20, 2.5)}" fill="#FFFFFF" opacity=".5"/>',
        f'<path d="{front}" fill="url(#front)"/>',
        f'<path d="{front}" fill="url(#sheen)"/>',
        f'<path d="{front}" fill="none" stroke="url(#rim)" stroke-width="1"/>',
        f'<path d="M11,{front_y + 0.9}H53" stroke="#FFFFFF" stroke-opacity=".8" stroke-width=".9" stroke-linecap="round"/>',
    ]
    if name:
        t, d = placed(glyph(name), 32, (front_y + 54) / 2 + 0.5, 20)
        body.append(f'<g {t}>{glyph_element(d, fill="#FFFFFF", fill_opacity=".5", transform="translate(0,.8)")}'
                    f'{glyph_element(d, fill="#0A3F86", fill_opacity=".78")}</g>')
    return svg("\n".join(body), defs)


PAGE = "M19,6H39.5L51,17.5V53Q51,58 46,58H19Q14,58 14,53V11Q14,6 19,6Z"
FOLD = "M39.5,6V14.5Q39.5,17.5 42.5,17.5H51Z"


def page(glyph_name, colour, label=None):
    """A frosted glass sheet tinted by its type, the glyph in that colour."""
    tint = mix("#FFFFFF", colour, 0.55)
    top = mix("#FFFFFF", colour, 0.0)
    defs = (
        '<linearGradient id="sheet" x1="0" y1="6" x2="0" y2="58" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{top}" stop-opacity=".46"/>'
        f'<stop offset=".55" stop-color="{tint}" stop-opacity=".2"/>'
        f'<stop offset="1" stop-color="{colour}" stop-opacity=".18"/></linearGradient>'
        '<linearGradient id="rim" x1="14" y1="6" x2="51" y2="58" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".85"/>'
        '<stop offset=".45" stop-color="#FFFFFF" stop-opacity=".22"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".4"/></linearGradient>'
        '<linearGradient id="sheen" x1="0" y1="6" x2="0" y2="30" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".22"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>'
        '<linearGradient id="fold" x1="39" y1="6" x2="51" y2="18" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".9"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".45"/></linearGradient>'
        '<linearGradient id="ink" x1="0" y1="0" x2="0" y2="24" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{mix(colour, "#FFFFFF", 0.28)}"/>'
        f'<stop offset="1" stop-color="{colour}"/></linearGradient>'
    )
    body = [
        f'<path d="{PAGE}" fill="#000" opacity=".4" filter="url(#shadow)" transform="translate(0,1.6)"/>',
        f'<path d="{PAGE}" fill="#2C2C2E" fill-opacity=".42"/>',
        f'<path d="{PAGE}" fill="url(#sheet)"/>',
        f'<path d="{PAGE}" fill="url(#sheen)"/>',
        f'<path d="{PAGE}" fill="none" stroke="url(#rim)" stroke-width="1"/>',
        '<path d="M37.6,17.5Q39.5,20.5 44,20H51V17.5Z" fill="#000" opacity=".12"/>',
        f'<path d="{FOLD}" fill="url(#fold)"/>',
    ]
    if glyph_name:
        cy, size = (28.5, 21) if label else (33, 23)
        t, d = placed(glyph(glyph_name), 32.5, cy, size)
        body.append(f'<g {t}>{glyph_element(d, fill="#000000", fill_opacity=".28", transform="translate(0,.7)")}'
                    f'{glyph_element(d, fill="url(#ink)")}</g>')
    if label:
        size = 8.2
        d, w, h = text_path(label, size)
        if w > 26:
            size *= 26 / w
            d, w, h = text_path(label, size)
        pw, ph = w + 8.4, 11
        px, py = 32.5 - pw / 2, 43.4
        ink = "#1C1C1E" if luminance(colour) > 0.45 else "#FFFFFF"
        body.append(f'<path d="{rrect(px, py, pw, ph, ph / 2)}" fill="{colour}" fill-opacity=".92"/>')
        body.append(f'<path transform="translate({fmt(32.5 - w / 2)},{fmt(py + (ph - h) / 2)})" d="{d}" fill="{ink}"/>')
    return svg("\n".join(body), defs)


def glass(shape, tint="#8E8E93"):
    """Defs and layers shared by the glass devices."""
    defs = (
        '<linearGradient id="body" x1="0" y1="0" x2="0" y2="64" gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{mix(tint, "#FFFFFF", 0.35)}" stop-opacity=".78"/>'
        f'<stop offset="1" stop-color="{mix(tint, "#000000", 0.45)}" stop-opacity=".88"/></linearGradient>'
        '<linearGradient id="rim" x1="0" y1="0" x2="0" y2="64" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".8"/>'
        '<stop offset=".5" stop-color="#FFFFFF" stop-opacity=".2"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".35"/></linearGradient>'
    )
    layers = [
        f'<path d="{shape}" fill="#000" opacity=".4" filter="url(#shadow)" transform="translate(0,1.6)"/>',
        f'<path d="{shape}" fill="url(#body)"/>',
        f'<path d="{shape}" fill="none" stroke="url(#rim)" stroke-width="1"/>',
    ]
    return defs, layers


def led(cx, cy):
    return f'<circle cx="{cx}" cy="{cy}" r="1.8" fill="#0A84FF"/>'


def device(kind):
    if kind == "drive":
        shape = rrect(6, 19, 52, 26, 7)
        defs, layers = glass(shape)
        layers += ['<path d="M12,20.2H52" stroke="#FFFFFF" stroke-opacity=".7" stroke-width=".9" stroke-linecap="round"/>',
                   f'<path d="{rrect(12, 35.5, 24, 2.2, 1.1)}" fill="#FFFFFF" fill-opacity=".28"/>',
                   led(49, 36.6)]
    elif kind == "usb":
        shape = rrect(4, 20, 40, 24, 6)
        defs, layers = glass(shape, "#0A84FF")
        plug = rrect(44, 25, 16, 14, 2)
        layers = ([f'<path d="{plug}" fill="#D1D1D6" fill-opacity=".9"/>',
                   f'<path d="{plug}" fill="none" stroke="#FFFFFF" stroke-opacity=".6" stroke-width=".8"/>',
                   f'<path d="{rrect(50, 28.5, 4, 2.8, .6)}{rrect(50, 32.7, 4, 2.8, .6)}" fill="#636366"/>']
                  + layers
                  + ['<path d="M9,21.2H39" stroke="#FFFFFF" stroke-opacity=".7" stroke-width=".9" stroke-linecap="round"/>',
                     led(37, 37)])
    elif kind == "disc":
        defs = ('<radialGradient id="body" cx="32" cy="32" r="26" gradientUnits="userSpaceOnUse">'
                '<stop offset=".2" stop-color="#FFFFFF" stop-opacity=".55"/>'
                '<stop offset=".7" stop-color="#C7C7CC" stop-opacity=".45"/>'
                '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".7"/></radialGradient>'
                '<linearGradient id="rim" x1="0" y1="6" x2="0" y2="58" gradientUnits="userSpaceOnUse">'
                '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".9"/>'
                '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".3"/></linearGradient>')
        shape = circle(32, 32, 26) + circle(32, 32, 5, cw=False)
        layers = [f'<path d="{shape}" fill="#000" opacity=".4" filter="url(#shadow)" transform="translate(0,1.6)"/>',
                  f'<path d="{shape}" fill="url(#body)"/>',
                  f'<path d="{ring(32, 32, 11, 1)}" fill="#FFFFFF" fill-opacity=".45"/>',
                  f'<path d="{shape}" fill="none" stroke="url(#rim)" stroke-width="1"/>']
    elif kind == "laptop":
        screen = rrect(11, 12, 42, 30, 4)
        defs, layers = glass(screen, "#3A3A3C")
        defs += ('<linearGradient id="wall" x1="14" y1="15" x2="50" y2="39" gradientUnits="userSpaceOnUse">'
                 '<stop offset="0" stop-color="#409CFF"/><stop offset="1" stop-color="#0B4FB4"/></linearGradient>')
        base = "M5,44H59Q59,50 53,50H11Q5,50 5,44Z"
        layers += [f'<path d="{rrect(14, 15, 36, 24, 2)}" fill="url(#wall)" fill-opacity=".9"/>',
                   f'<path d="{base}" fill="#D1D1D6" fill-opacity=".85"/>',
                   f'<path d="{base}" fill="none" stroke="#FFFFFF" stroke-opacity=".6" stroke-width=".8"/>',
                   '<path d="M27,44.4H37" stroke="#636366" stroke-width="1.6" stroke-linecap="round"/>']
    elif kind == "phone":
        shape = rrect(19, 5, 26, 54, 7)
        defs, layers = glass(shape, "#3A3A3C")
        defs += ('<linearGradient id="wall" x1="22" y1="9" x2="42" y2="55" gradientUnits="userSpaceOnUse">'
                 '<stop offset="0" stop-color="#409CFF"/><stop offset="1" stop-color="#0B4FB4"/></linearGradient>')
        layers += [f'<path d="{rrect(22, 8, 20, 48, 4.5)}" fill="url(#wall)" fill-opacity=".9"/>',
                   f'<path d="{rrect(28.5, 10, 7, 2.4, 1.2)}" fill="#000" fill-opacity=".7"/>']
    elif kind == "server":
        top, bottom = rrect(7, 10, 50, 19, 5), rrect(7, 34, 50, 19, 5)
        defs, layers = glass(top + bottom)
        for y in (19.5, 43.5):
            layers += [f'<path d="{rrect(13, y - 1.1, 18, 2.2, 1.1)}" fill="#FFFFFF" fill-opacity=".3"/>', led(50, y)]
    else:
        raise ValueError(kind)
    return svg("\n".join(layers), defs)


def trash(full=False):
    defs = (
        '<linearGradient id="body" x1="0" y1="18" x2="0" y2="58" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".42"/>'
        '<stop offset="1" stop-color="#C7C7CC" stop-opacity=".22"/></linearGradient>'
        '<linearGradient id="rim" x1="0" y1="10" x2="0" y2="58" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".9"/>'
        '<stop offset=".5" stop-color="#FFFFFF" stop-opacity=".25"/>'
        '<stop offset="1" stop-color="#FFFFFF" stop-opacity=".45"/></linearGradient>'
    )
    can = "M15,20H49L46.2,54Q45.8,58 41.8,58H22.2Q18.2,58 17.8,54Z"
    lid = rrect(12, 13, 40, 6.5, 3.2)
    body = [f'<path d="{can}" fill="#000" opacity=".4" filter="url(#shadow)" transform="translate(0,1.6)"/>',
            f'<path d="{can}" fill="#2C2C2E" fill-opacity=".5"/>']
    if full:
        # Sheets of paper inside the glass, the top ones standing above the
        # rim; a full bin has no lid, as in Finder.
        for angle, x, y, w, h in ((-14, 18, 15, 16, 22), (9, 30, 11, 16, 24), (-4, 24, 28, 18, 20)):
            sheet = rrect(x, y, w, h, 1.6)
            body += [f'<path d="{sheet}" transform="rotate({angle} {x + w / 2} {y + h / 2})" fill="#F5F5F7" fill-opacity=".92"/>',
                     f'<path d="M{x + 3},{y + 6}H{x + w - 4}M{x + 3},{y + 10}H{x + w - 6}" '
                     f'transform="rotate({angle} {x + w / 2} {y + h / 2})" stroke="#AEAEB2" stroke-width="1.2" stroke-linecap="round"/>']
    body += [f'<path d="{can}" fill="url(#body)"/>']
    for x in (25, 32, 39):
        body.append(f'<path d="M{x},25V52" stroke="#FFFFFF" stroke-opacity=".35" stroke-width="1.6" stroke-linecap="round"/>')
    body.append(f'<path d="{can}" fill="none" stroke="url(#rim)" stroke-width="1"/>')
    if full:
        body.append('<path d="M15.6,20.4H48.4" stroke="#FFFFFF" stroke-opacity=".85" stroke-width="1.4" stroke-linecap="round"/>')
    else:
        body += [f'<path d="{rring(26, 8.5, 12, 6, 2, 1.6)}" fill="#E5E5EA" fill-opacity=".8"/>',
                 f'<path d="{lid}" fill="#E5E5EA" fill-opacity=".72"/>',
                 f'<path d="{lid}" fill="none" stroke="#FFFFFF" stroke-opacity=".8" stroke-width=".8"/>']
    return svg("\n".join(body), defs)


def star():
    d = g_star()
    defs = ('<linearGradient id="ink" x1="0" y1="0" x2="0" y2="24" gradientUnits="userSpaceOnUse">'
            '<stop offset="0" stop-color="#FFE45C"/><stop offset="1" stop-color="#FF9F0A"/></linearGradient>')
    t, d = placed(d, 32, 32, 52)
    return svg(f'<g {t}>{glyph_element(d, fill="#000", opacity=".35", transform="translate(0,.8)")}'
               f'{glyph_element(d, fill="url(#ink)", fill_opacity=".92")}'
               f'{glyph_element(d, fill="none", stroke="#FFFFFF", stroke_opacity=".7", stroke_width=".5")}</g>', defs)


def symbolic(name):
    d = glyph(name)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24">\n'
            f'{glyph_element(d, fill="#2E3436")}\n</svg>\n')


# ---------------------------------------------------------------------------
# What gets drawn
# ---------------------------------------------------------------------------

# Folder places: icon name -> engraved glyph. The symbolic twin is the bare
# glyph, as in Finder's sidebar.
FOLDERS = {
    "folder": None, "folder-documents": "doc", "folder-download": "download",
    "folder-music": "note", "folder-pictures": "photo", "folder-videos": "play",
    "folder-templates": "templates", "folder-publicshare": "share", "folder-remote": "globe",
    "folder-recent": "clock", "folder-saved-search": "search", "folder-starred": "star",
    "user-home": "home", "user-desktop": "desktop", "network-workgroup": "globe",
    "folder-development": "code", "folder-projects": "code",
}
SYMBOLIC_ONLY = {
    "folder": "folder", "starred": "star", "user-trash": "trash", "user-trash-full": "trash_full",
    "network-server": "server", "drive-harddisk": "drive", "drive-removable-media": "usb",
    "media-removable": "usb", "drive-optical": "disc", "media-optical": "disc", "computer": "laptop",
    "phone": "phone",
}
DEVICES = {
    "drive-harddisk": "drive", "drive-harddisk-system": "drive", "drive-harddisk-solidstate": "drive",
    "drive-removable-media": "usb", "drive-removable-media-usb": "usb", "media-removable": "usb",
    "media-flash": "usb", "drive-optical": "disc", "media-optical": "disc", "computer": "laptop",
    "phone": "phone", "network-server": "server",
}

# (glyph, colour, label, icon names). A row is one drawing; the first name
# is the file and the rest are symlinks to it.
TYPES = [
    # Text and documents
    ("lines", "silver", None, ["text-x-generic", "text-x-readme"]),
    ("lines", "silver", "TXT", ["text-plain"]),
    ("list", "silver", "LOG", ["text-x-log"]),
    ("markdown", "cyan", "MD", ["text-markdown", "text-x-markdown"]),
    ("lines", "teal", "RST", ["text-x-rst"]),
    ("lines", "green", "TEX", ["text-x-tex"]),
    ("book", "brown", "BIB", ["text-x-bibtex"]),
    ("doc", "red", "PDF", ["application-pdf"]),
    ("paragraph", "blue", None, ["x-office-document", "application-rtf", "text-rtf"]),
    ("paragraph", "blue", "DOCX", ["application-vnd.openxmlformats-officedocument.wordprocessingml.document"]),
    ("paragraph", "blue", "DOC", ["application-msword"]),
    ("paragraph", "blue", "ODT", ["application-vnd.oasis.opendocument.text"]),
    ("table", "green", None, ["x-office-spreadsheet"]),
    ("table", "green", "XLSX", ["application-vnd.openxmlformats-officedocument.spreadsheetml.sheet"]),
    ("table", "green", "XLS", ["application-vnd.ms-excel"]),
    ("table", "green", "ODS", ["application-vnd.oasis.opendocument.spreadsheet"]),
    ("table", "green", "CSV", ["text-csv"]),
    ("table", "green", "TSV", ["text-tab-separated-values"]),
    ("presentation", "orange", None, ["x-office-presentation"]),
    ("presentation", "orange", "PPTX", ["application-vnd.openxmlformats-officedocument.presentationml.presentation"]),
    ("presentation", "orange", "PPT", ["application-vnd.ms-powerpoint"]),
    ("presentation", "orange", "ODP", ["application-vnd.oasis.opendocument.presentation"]),
    ("presentation", "orange", "KEY", ["application-vnd.apple.keynote"]),
    ("book", "orange", "EPUB", ["application-epub+zip"]),
    ("calendar", "red", "ICS", ["text-calendar", "x-office-calendar"]),
    ("person", "blue", "VCF", ["text-vcard", "text-x-vcard", "x-office-address-book"]),

    # Code
    ("terminal", "green", None, ["text-x-script"]),
    ("code", "blue", "PY", ["text-x-python", "text-x-python3", "application-x-python", "application-x-python3",
                            "text-x-python-script"]),
    ("chip", "blue", "PYC", ["application-x-python-bytecode"]),
    ("notebook", "orange", "IPYNB", ["application-x-ipynb+json"]),
    ("code", "indigo", "C", ["text-x-csrc", "text-x-c"]),
    ("code", "indigo", "H", ["text-x-chdr", "text-x-c-header"]),
    ("code", "purple", "C++", ["text-x-c++src", "text-x-cpp"]),
    ("code", "purple", "HPP", ["text-x-c++hdr"]),
    ("code", "green", "CU", ["text-x-cuda"]),
    ("chip", "teal", "INO", ["text-x-arduino"]),
    ("code", "yellow", "JS", ["application-javascript", "application-x-javascript", "text-javascript",
                              "text-x-javascript"]),
    ("code", "yellow", "JSX", ["text-x-jsx"]),
    ("code", "cyan", "TS", ["text-x-typescript", "application-typescript", "text-typescript"]),
    ("code", "cyan", "TSX", ["text-x-tsx"]),
    ("code", "orange", "JAVA", ["text-x-java", "text-x-java-source"]),
    ("code", "purple", "KT", ["text-x-kotlin"]),
    ("code", "brown", "RS", ["text-rust", "text-x-rust"]),
    ("code", "teal", "GO", ["text-x-go"]),
    ("code", "orange", "SWIFT", ["text-x-swift"]),
    ("code", "red", "RB", ["application-x-ruby", "text-x-ruby"]),
    ("code", "indigo", "PHP", ["application-x-php", "text-x-php"]),
    ("code", "blue", "LUA", ["text-x-lua"]),
    ("terminal", "green", "SH", ["application-x-shellscript", "application-x-sh", "text-x-shellscript"]),
    ("database", "blue", "SQL", ["application-sql", "text-x-sql"]),
    ("globe", "orange", "HTML", ["text-html", "application-xhtml+xml"]),
    ("code", "mint", "XML", ["application-xml", "text-xml"]),
    ("drop", "blue", "CSS", ["text-css", "text-x-css"]),
    ("drop", "pink", "SCSS", ["text-x-scss", "text-x-sass"]),
    ("braces", "yellow", "JSON", ["application-json", "application-x-json"]),
    ("braces", "indigo", "PROTO", ["text-x-protobuf"]),
    ("sliders", "mint", "YAML", ["application-x-yaml", "application-yaml", "text-yaml", "text-x-yaml"]),
    ("sliders", "mint", "TOML", ["application-toml", "text-x-toml"]),
    ("sliders", "mint", "CONF", ["text-x-config", "text-x-ini"]),
    ("wrench", "orange", "MAKE", ["text-x-makefile"]),
    ("wrench", "green", "CMAKE", ["text-x-cmake"]),
    ("container", "blue", None, ["text-x-dockerfile"]),
    ("branch", "orange", "GIT", ["text-x-git-config"]),
    ("diff", "green", "DIFF", ["text-x-patch", "text-x-diff"]),
    ("apps", "blue", None, ["application-x-desktop"]),
    ("gear", "silver", None, ["text-x-dbus-service", "text-x-systemd-unit"]),
    ("key", "yellow", "ENV", ["text-x-dotenv"]),
    ("lock", "silver", "LOCK", ["text-x-lockfile"]),
    ("shield", "green", "CERT", ["application-x-x509-ca-cert", "application-pkix-cert", "application-x-pem-file",
                                 "application-pem-certificate-chain"]),
    ("lock", "indigo", "GPG", ["application-pgp-encrypted", "application-pgp-keys", "application-pgp-signature"]),

    # Robotics (ROS 2)
    ("rocket", "blue", None, ["application-x-ros-launch"]),
    ("robot", "teal", "URDF", ["application-x-urdf"]),
    ("robot", "teal", "XACRO", ["application-x-xacro"]),
    ("bubble", "indigo", "MSG", ["text-x-ros-msg"]),
    ("bubble", "indigo", "SRV", ["text-x-ros-srv"]),
    ("bubble", "indigo", "ACT", ["text-x-ros-action"]),
    ("record", "red", "BAG", ["application-x-rosbag"]),
    ("record", "red", "MCAP", ["application-x-mcap"]),
    ("record", "red", "DB3", ["application-x-rosbag2"]),
    ("sliders", "purple", "RVIZ", ["application-x-rviz"]),

    # Data and machine learning
    ("grid", "purple", "NPY", ["application-x-npy"]),
    ("grid", "purple", "NPZ", ["application-x-npz"]),
    ("grid", "purple", "PKL", ["application-x-pickle"]),
    ("neural", "purple", "PT", ["application-x-pytorch"]),
    ("neural", "purple", "ONNX", ["application-x-onnx"]),
    ("neural", "purple", None, ["application-x-safetensors"]),
    ("neural", "purple", "H5", ["application-x-hdf", "application-x-hdf5"]),
    ("table", "purple", "PQ", ["application-vnd.apache.parquet"]),
    ("database", "blue", "DB", ["application-vnd.sqlite3", "application-x-sqlite3"]),

    # 3D
    ("cube", "indigo", None, ["model-x-generic"]),
    ("cube", "indigo", "STL", ["model-stl"]),
    ("cube", "indigo", "OBJ", ["model-obj"]),
    ("cube", "indigo", "DAE", ["model-vnd.collada+xml"]),
    ("cube", "indigo", "GLB", ["model-gltf-binary", "model-gltf+json"]),
    ("cube", "indigo", "PLY", ["model-x-ply"]),
    ("cube", "orange", "BLEND", ["application-x-blender"]),

    # Media
    ("photo", "cyan", None, ["image-x-generic"]),
    ("photo", "cyan", "PNG", ["image-png"]),
    ("photo", "cyan", "JPG", ["image-jpeg"]),
    ("photo", "cyan", "GIF", ["image-gif"]),
    ("photo", "cyan", "WEBP", ["image-webp"]),
    ("photo", "cyan", "HEIC", ["image-heif", "image-heic"]),
    ("photo", "cyan", "TIFF", ["image-tiff"]),
    ("photo", "cyan", "RAW", ["image-x-dcraw", "image-x-adobe-dng", "image-x-canon-cr2", "image-x-nikon-nef",
                              "image-x-sony-arw"]),
    ("vector", "orange", "SVG", ["image-svg+xml", "image-svg+xml-compressed"]),
    ("play", "purple", None, ["video-x-generic"]),
    ("play", "purple", "MP4", ["video-mp4"]),
    ("play", "purple", "MKV", ["video-x-matroska"]),
    ("play", "purple", "MOV", ["video-quicktime"]),
    ("play", "purple", "WEBM", ["video-webm"]),
    ("play", "purple", "AVI", ["video-x-msvideo"]),
    ("wave", "pink", None, ["audio-x-generic"]),
    ("wave", "pink", "MP3", ["audio-mpeg"]),
    ("wave", "pink", "FLAC", ["audio-flac"]),
    ("wave", "pink", "WAV", ["audio-x-wav", "audio-wav"]),
    ("wave", "pink", "OGG", ["audio-ogg", "audio-x-vorbis+ogg"]),
    ("wave", "pink", "OPUS", ["audio-x-opus+ogg"]),
    ("wave", "pink", "M4A", ["audio-mp4", "audio-aac"]),
    ("font", "purple", None, ["font-x-generic"]),
    ("font", "purple", "TTF", ["font-ttf", "application-x-font-ttf"]),
    ("font", "purple", "OTF", ["font-otf", "application-x-font-otf"]),
    ("font", "purple", "WOFF", ["font-woff", "font-woff2"]),

    # Archives, packages and binaries
    ("zip", "sand", None, ["package-x-generic"]),
    ("zip", "sand", "ZIP", ["application-zip"]),
    ("zip", "sand", "TAR", ["application-x-tar"]),
    ("zip", "sand", "TGZ", ["application-x-compressed-tar", "application-gzip", "application-x-gzip"]),
    ("zip", "sand", "TXZ", ["application-x-xz-compressed-tar", "application-x-xz"]),
    ("zip", "sand", "ZST", ["application-zstd", "application-x-zstd-compressed-tar"]),
    ("zip", "sand", "BZ2", ["application-x-bzip", "application-x-bzip-compressed-tar"]),
    ("zip", "sand", "7Z", ["application-x-7z-compressed"]),
    ("zip", "sand", "RAR", ["application-vnd.rar", "application-x-rar"]),
    ("package", "orange", "DEB", ["application-vnd.debian.binary-package", "application-x-deb"]),
    ("package", "orange", "RPM", ["application-x-rpm"]),
    ("package", "orange", "JAR", ["application-x-java-archive"]),
    ("package", "orange", "WHL", ["application-x-wheel+zip"]),
    ("package", "green", "APK", ["application-vnd.android.package-archive"]),
    ("package", "orange", "SNAP", ["application-vnd.snap"]),
    ("disc", "silver", "ISO", ["application-x-cd-image", "application-x-iso9660-image", "application-x-raw-disk-image"]),
    ("exec", "silver", None, ["application-x-executable", "application-vnd.appimage", "application-x-iso9660-appimage"]),
    ("exec", "blue", "EXE", ["application-x-ms-dos-executable", "application-x-msdownload"]),
    ("chip", "silver", "SO", ["application-x-sharedlib"]),
    ("chip", "silver", "O", ["application-x-object"]),
    ("chip", "silver", "A", ["application-x-archive"]),
    ("chip", "silver", "BIN", ["application-octet-stream"]),
    (None, "silver", None, ["application-x-generic", "unknown"]),
]


def build(root):
    """Write the managed directories under root (a copy of scalable/)."""
    for sub in MANAGED:
        shutil.rmtree(root / sub, ignore_errors=True)
        (root / sub).mkdir(parents=True)

    def write(sub, name, text):
        (root / sub / f"{name}.svg").write_text(text)

    def alias(sub, name, target):
        (root / sub / f"{name}.svg").symlink_to(f"{target}.svg")

    drawn = {}
    for name, g in FOLDERS.items():
        write("places", name, folder(g))
        if g:
            write("places", f"{name}-symbolic", symbolic(g))
    write("places", "folder-open", folder(None, open_=True))
    alias("places", "folder-drag-accept", "folder-open")
    write("places", "user-trash", trash())
    write("places", "user-trash-full", trash(full=True))
    write("places", "starred", star())
    for name, g in SYMBOLIC_ONLY.items():
        sub = "devices" if name in DEVICES else "places"
        write(sub, f"{name}-symbolic", symbolic(g))

    for name, kind in DEVICES.items():
        if kind in drawn:
            alias("devices", name, drawn[kind])
        else:
            write("devices", name, device(kind))
            drawn[kind] = name
    alias("places", "network-server", "../devices/network-server")

    seen = set()
    for g, colour, label, names in TYPES:
        for n in names:
            if n in seen:
                raise SystemExit(f"{n} is listed twice")
            seen.add(n)
        write("mimetypes", names[0], page(g, C[colour], label))
        for n in names[1:]:
            alias("mimetypes", n, names[0])


def snapshot(root):
    out = {}
    for sub in MANAGED:
        for f in sorted((root / sub).iterdir()):
            out[f"{sub}/{f.name}"] = ("-> " + str(f.readlink())) if f.is_symlink() else f.read_text()
    return out


def main():
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp))
            fresh, current = snapshot(Path(tmp)), snapshot(THEME)
        stale = sorted(set(fresh.items()) ^ set(current.items()))
        if stale:
            print(f"icons are stale ({len({k for k, _ in stale})} files): run scripts/build-file-icons.py")
            return 1
        print(f"icons up to date ({len(fresh)} files)")
        return 0
    build(THEME)
    print(f"wrote {sum(1 for s in MANAGED for _ in (THEME / s).iterdir())} icons to {THEME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
