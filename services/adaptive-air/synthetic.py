"""Hands drawn joint by joint, the way MediaPipe reports them: for the checks and the demo.

hand(cx, cy, size, shape) gives 21 landmarks of an upright hand whose palm centre is at (cx, cy)
in image fractions; shape is open | fist | point | L | pinch | pinch-middle | vee; gap is the L's thumb-index opening.
"""

import gestures

MCP = {"index": (-0.30, -0.95), "middle": (0.0, -1.0), "ring": (0.25, -0.93),
       "pinky": (0.45, -0.80)}
ORDER = ("index", "middle", "ring", "pinky")


def hand(cx=0.5, cy=0.5, size=0.12, shape="open", depth=None, side="Right", gap=1.0):
    pts = [(0.0, 0.0)] + [None] * 20
    for i, name in enumerate(ORDER):
        mx, my = MCP[name]
        base = 5 + 4 * i
        folded = shape == "fist" or (shape in ("point", "L") and name != "index") or \
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
    elif shape == "L":
        # Thumb out to the side; its tip `gap` hand-sizes from the index tip.
        tip, out = pts[8], (-1.0, -0.6)
        span = ((out[0] - tip[0]) ** 2 + (out[1] - tip[1]) ** 2) ** 0.5
        f = min(1.0, gap / span)
        thumb = [(-0.35, -0.25), (-0.65, -0.40), (-0.85, -0.52),
                 (tip[0] + (out[0] - tip[0]) * f, tip[1] + (out[1] - tip[1]) * f)]
    elif shape in ("fist", "vee", "point"):
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


def room_depth(hand=(0.15, 0.0, 2.45), lamp=True, table=True, noise=6.0, seed=0, fx=525.0):
    """A Kinect depth frame (mm, 640x480, mirrored like the tracker's) of a living room seen
    from on top of the TV: a wall at 3.6 m, a couch at 3 m, someone sitting on it at 2.8 m
    (head, torso, the other arm down) and, if hand is (x, y, z) metres, that hand held out with
    its forearm running back to the shoulder; a free-standing lamp and a coffee table nearer.
    Returns (depth, (u, v) of the hand's centre)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    v, u = np.mgrid[0:480, 0:640]
    d = np.full((480, 640), 3600.0)

    def px(x, y, z):
        return 319.5 + fx * x / z, 239.5 + fx * y / z

    def box(x0, x1, y0, y1, z):
        a0, b0 = px(x0, y0, z)
        a1, b1 = px(x1, y1, z)
        m = (u >= a0) & (u <= a1) & (v >= b0) & (v <= b1)
        d[m] = np.minimum(d[m], z * 1000)

    def disc(x, y, z, r):
        a, b = px(x, y, z)
        rp = fx * r / z
        m = (u - a) ** 2 + (v - b) ** 2 <= rp * rp
        d[m] = np.minimum(d[m], z * 1000)

    box(-0.9, 0.9, 0.1, 1.2, 3.0)                          # couch
    box(-0.2, 0.2, -0.2, 0.45, 2.8)                        # torso
    disc(0.0, -0.33, 2.8, 0.1)                             # head
    box(-0.3, -0.18, -0.15, 0.3, 2.8)                      # the other arm, down
    at = None
    if hand:
        hx, hy, hz = hand
        disc(hx, hy, hz, 0.07)                             # palm and fingers
        for f in np.linspace(0.15, 1, 12):                 # forearm back to the shoulder
            disc(hx + (0.2 - hx) * f, hy + (-0.15 - hy) * f, hz + (2.75 - hz) * f, 0.035)
        at = px(hx, hy, hz)
    if lamp:
        disc(-0.8, -0.2, 2.2, 0.08)                        # lamp shade
        box(-0.81, -0.79, -0.12, 1.0, 2.2)                 # its pole
    if table:
        box(-0.5, 0.5, 0.6, 0.75, 1.6)                     # coffee table
    d = d + rng.normal(0, noise, d.shape)
    return d.astype(np.uint16), at
