"""Hands drawn joint by joint, the way MediaPipe reports them: for the checks and the demo.

hand(cx, cy, size, shape) gives 21 landmarks of an upright hand whose palm centre is at (cx, cy)
in image fractions; shape is open | fist | point | pinch | pinch-middle | vee.
"""

import gestures

MCP = {"index": (-0.30, -0.95), "middle": (0.0, -1.0), "ring": (0.25, -0.93),
       "pinky": (0.45, -0.80)}
ORDER = ("index", "middle", "ring", "pinky")


def hand(cx=0.5, cy=0.5, size=0.12, shape="open", depth=None, side="Right"):
    pts = [(0.0, 0.0)] + [None] * 20
    for i, name in enumerate(ORDER):
        mx, my = MCP[name]
        base = 5 + 4 * i
        folded = shape == "fist" or (shape == "point" and name != "index") or \
            (shape == "vee" and name in ("ring", "pinky"))
        if folded:
            joints = [(mx, my), (mx, my - 0.35), (mx, my - 0.15), (mx, my + 0.08)]
        elif shape == "pinch-middle" and name == "middle":
            joints = [(mx, my), (mx - 0.05, my - 0.35), (mx - 0.15, my - 0.50),
                      (mx - 0.20, my - 0.45)]
        elif shape == "pinch" and name == "index":
            joints = [(mx, my), (mx - 0.10, my - 0.40), (mx - 0.25, my - 0.55),
                      (mx - 0.38, my - 0.60)]
        else:
            joints = [(mx, my), (mx, my - 0.45), (mx, my - 0.75), (mx, my - 0.95)]
        for j, p in enumerate(joints):
            pts[base + j] = p
    if shape == "pinch":
        tip = pts[8]
        thumb = [(-0.35, -0.25), (-0.55, -0.55), (-0.62, -0.95), (tip[0] + 0.03, tip[1] + 0.03)]
    elif shape == "pinch-middle":
        tip = pts[12]
        thumb = [(-0.35, -0.25), (-0.50, -0.55), (-0.45, -0.95), (tip[0] + 0.03, tip[1] + 0.03)]
    elif shape in ("fist", "vee"):
        thumb = [(-0.35, -0.25), (-0.45, -0.50), (-0.30, -0.70), (-0.08, -0.75)]
    else:
        thumb = [(-0.35, -0.25), (-0.60, -0.45), (-0.78, -0.65), (-0.90, -0.85)]
    pts[1:5] = thumb
    if side == "Left":
        pts = [(-x, y) for x, y in pts]
    palm = [pts[i] for i in gestures.PALM]
    px = sum(p[0] for p in palm) / 5
    py = sum(p[1] for p in palm) / 5
    lm = [[cx + (x - px) * size * 0.75, cy + (y - py) * size, 0.0] for x, y in pts]
    return {"side": side, "lm": lm, "depth": depth}
