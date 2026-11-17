"""Air's sensor fusion: what the Kinect's colour, infrared and depth each add. Pure (numpy).

The Kinect v1 has three ways of seeing, and they are not equal:

    colour     the RGB camera; MediaPipe finds hands in it, but only with light in the room
    infrared   the IR camera, lit by the Kinect's own projector: works in the dark. It shares
               one USB stream with colour, so the Kinect gives one or the other, never both
               (a switch takes ~0.3 s). LightSwitch picks which, from how bright colour is.
    depth      millimetres per pixel, from the same IR camera, alongside either picture. Works
               in any light, 0.5 to 4.5 m.

Depth does two jobs here:

    refine_palm   a hand MediaPipe found (in colour or infrared) gets its palm and its
                  distance from the depth pixels on it. Across the room a hand is ~20 pixels
                  wide and its 21 landmarks wobble by a pixel or two from frame to frame, a
                  centimetre at 2.7 m, which the pointer magnifies twenty times; the centre of
                  the few hundred depth pixels on the palm moves far less. And the distance
                  gives the hand's real size, so arm movement is measured in metres.
    DepthHands    a hand held out toward the Kinect, found from depth alone, for when neither
                  picture finds it (too dark even for infrared, too far, motion blur). It
                  carries a hand MediaPipe has just lost, and on its own it gives the pointer,
                  the air push, swipes and waves (no finger poses: depth cannot see fingers
                  at that range).

Coordinates are pixels of the (mirrored) 640x480 picture; distances are millimetres.
"""

import math

NEAR_MM, FAR_MM = 450, 4500
HAND_M = 0.09            # wrist to middle knuckle (what gestures.hand_size measures), metres
HAND_RADIUS_M = 0.085    # a hand's blob as depth sees it, palm centre to its edge, metres
SHOULDERS_M = 0.36       # shoulder to shoulder (MediaPipe Pose's landmarks), metres

# DepthHands, all in metres unless named otherwise
DEFAULTS = {
    "band": 0.10,          # a hand's pixels lie within this of its nearest part
    "ahead": 0.20,         # ... and the body behind it is at least this much farther
    "ring_near": 0.25,     # at most this share of the ring around the hand may be as near
    "area_min": 0.005,     # m^2 of hand as depth sees it (a fist to an open palm)
    "area_max": 0.035,
    "elongation": 2.6,     # longest / shortest axis at most: not a pole, a chair's edge, an arm
    "arm_move": 0.12,      # a depth-only hand counts once it has moved this much (raised)
    "match": 0.25,         # the same hand from one frame to the next is within this
    "lost": 0.4,           # s a track lives unseen
}


def metres_per_width(z_mm, fx, width=640):
    """How many metres across the whole picture is at this distance."""
    return z_mm / 1000.0 * width / fx


def hand_px(z_mm, fx):
    """A hand's wrist-to-knuckle length in pixels at this distance."""
    return HAND_M * fx / max(z_mm / 1000.0, 0.1)


def depth_at(depth, u, v, r=4):
    """The median valid distance (mm) in a small square around (u, v), or None."""
    import numpy as np
    h, w = depth.shape
    u, v = int(round(u)), int(round(v))
    patch = depth[max(0, v - r):min(h, v + r + 1), max(0, u - r):min(w, u + r + 1)]
    valid = patch[(patch >= NEAR_MM) & (patch <= FAR_MM)]
    return float(np.median(valid)) if valid.size else None


def plausible(size_px, z_mm, fx, real_m, low=0.3, high=2.2):
    """Is something size_px across the right size for real_m metres at z_mm? Depth's check on
    what a camera model found: a hand on a poster, or a "person" MediaPipe sees in a dark
    corner, is the wrong size for how far away it really is. Low is loose: a hand turned
    toward the Kinect looks shorter than it is."""
    if not z_mm:
        return True                                   # no reading: nothing to go on
    want = real_m * fx / (z_mm / 1000.0)
    return low * want <= size_px <= high * want


def light_level(rgb):
    """How bright the colour picture is, 0..1 (sampled; MediaPipe gives up below ~0.04)."""
    return float(rgb[::16, ::16].mean()) / 255.0


# ------------------------------------------------------------------ colour or infrared

class LightSwitch:
    """Which picture the Kinect gives in "auto": colour while the room is lit, infrared in the dark.

    In colour, a picture darker than dark_below for dark_for seconds switches to infrared. In
    infrared there is no way to see the room's light, so every check_every seconds, while nobody
    is using Air (busy) and nothing holds the picture (the webcam is on), it looks at colour for
    check_for seconds and stays there if it is brighter than light_above (above dark_below, so a
    dim room does not flip back and forth).
    """

    def __init__(self, dark_below=0.04, light_above=0.07, dark_for=2.0, check_every=20.0,
                 check_for=0.4):
        self.dark_below, self.light_above = dark_below, light_above
        self.dark_for, self.check_every, self.check_for = dark_for, check_every, check_for
        self.dark_since = None
        self.peek = None         # None | "asked" | time the colour look ends
        self.last_check = None
        self.reason = "lit"

    def step(self, now, mode, light, busy=False, hold=False):
        """The picture to use from now: "rgb" or "ir". mode: the one frames are in now; light:
        the colour picture's brightness (ignored in infrared)."""
        if self.peek is not None:
            if mode != "rgb":
                return "rgb"                          # the switch is on its way
            if self.peek == "asked":
                self.peek = now + self.check_for
            if now < self.peek:
                return "rgb"
            self.peek, self.last_check = None, now
            if light is not None and light >= self.light_above:
                self.dark_since, self.reason = None, "lit"
                return "rgb"
            self.reason = "dark"
            return "ir"
        if mode == "rgb":
            if light is not None and light < self.dark_below:
                if self.dark_since is None:
                    self.dark_since = now
                if now - self.dark_since >= self.dark_for:
                    self.dark_since, self.last_check, self.reason = None, now, "dark"
                    return "ir"
            else:
                self.dark_since = None
                self.reason = "lit"
            return "rgb"
        if self.last_check is None:
            self.last_check = now
        if not busy and not hold and now - self.last_check >= self.check_every:
            self.peek = "asked"
            return "rgb"
        return "ir"


# ------------------------------------------------------------------ a found hand, refined

def refine_palm(depth, u, v, radius, band_mm=80, iterations=3):
    """The palm as depth sees it: (u, v, z_mm, pixels) or None.

    (u, v) is a pixel on the palm (the landmarks' palm centre) and radius the palm's size in
    pixels. The hand is the nearest thing there, so its distance is taken from the near end of
    the pixels in the disc; the disc then moves to the centre of the pixels within band_mm of
    it (mean shift), which settles on the hand itself rather than on where the landmarks put it.
    """
    import numpy as np
    h, w = depth.shape
    r = max(3.0, float(radius))
    z = None
    n = 0
    for _ in range(iterations):
        x0, x1 = int(max(0, math.floor(u - r))), int(min(w, math.ceil(u + r) + 1))
        y0, y1 = int(max(0, math.floor(v - r))), int(min(h, math.ceil(v + r) + 1))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        patch = depth[y0:y1, x0:x1].astype(np.float32)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        valid = (((xx - u) ** 2 + (yy - v) ** 2) <= r * r) & (patch >= NEAR_MM) & (patch <= FAR_MM)
        if valid.sum() < 6:
            return None
        if z is None:
            z = float(np.percentile(patch[valid], 25))
        keep = valid & (np.abs(patch - z) <= band_mm)
        n = int(keep.sum())
        if n < 6:
            return None
        u, v = float(xx[keep].mean()), float(yy[keep].mean())
        z = float(np.median(patch[keep]))
    return u, v, z, n


# ------------------------------------------------------------------ hands from depth alone

class DepthHands:
    """Hands held out toward the Kinect, found in depth: a hand-sized blob well ahead of
    whatever is around it (the body behind the arm), followed from frame to frame.

    A blob counts as a hand only once it has moved arm_move metres (raised toward the screen),
    or when it is where a hand MediaPipe found is (then it carries that hand's side, and keeps
    the hand going for a moment when MediaPipe loses it). A lamp, a cup or a head never moves
    like that, and a head has shoulders around it at its own distance.
    """

    STEP = 2       # work on every second pixel: 320x240
    CELL = 12      # candidate search: the nearest pixel of each 12x12 cell
    CANDIDATES = 14

    def __init__(self, config=None):
        self.cfg = dict(DEFAULTS)
        if config:
            self.cfg.update({k: v for k, v in config.items() if k in DEFAULTS})
        self.tracks = []
        self._next = 1
        self._grid = None

    def find(self, depth, t, fx, cx=319.5, cy=239.5, seeds=()):
        """Armed hands that no seed accounts for, as [{"id", "side" (or None), "u", "v", "z",
        "area", "linked"}] in full-size pixels. seeds: [(side, u, v, z or None)] of the hands
        MediaPipe found this frame (a blob at one of them is that hand)."""
        blobs = self._blobs(depth, fx)
        cfg = self.cfg

        def world(u, v, z):
            return ((u - cx) * z / fx / 1000.0, (v - cy) * z / fx / 1000.0, z / 1000.0)

        found = []
        used = set()
        for b in blobs:
            p = world(b["u"], b["v"], b["z"])
            best, best_d = None, cfg["match"]
            for i, tr in enumerate(self.tracks):
                if i in used:
                    continue
                d = math.dist(p, tr["p"])
                if d < best_d:
                    best, best_d = i, d
            if best is None:
                tr = {"id": self._next, "side": None, "start": p, "moved": 0.0, "armed": False}
                self._next += 1
                self.tracks.append(tr)
                best = len(self.tracks) - 1
            used.add(best)
            tr = self.tracks[best]
            tr.update(p=p, u=b["u"], v=b["v"], z=b["z"], area=b["area"], seen=t, linked=False)
            tr["moved"] = max(tr["moved"], math.dist(p, tr["start"]))
            if tr["moved"] >= cfg["arm_move"]:
                tr["armed"] = True
            found.append(tr)
        for side, su, sv, sz in seeds:
            for tr in found:
                if sz:
                    close = math.dist(world(su, sv, sz), tr["p"]) < 0.15
                else:
                    close = math.hypot(su - tr["u"], sv - tr["v"]) < 1.5 * hand_px(tr["z"], fx)
                if close:
                    tr.update(side=side, armed=True, linked=True)
        self.tracks = [tr for tr in self.tracks if t - tr["seen"] <= cfg["lost"]]
        return [{"id": tr["id"], "side": tr["side"], "u": tr["u"], "v": tr["v"], "z": tr["z"],
                 "area": tr["area"], "linked": tr["linked"]}
                for tr in found if tr["armed"] and not tr["linked"]]

    def name(self, track_id, side):
        """Give a depth-only hand a side, kept for as long as it is followed."""
        for tr in self.tracks:
            if tr["id"] == track_id:
                tr["side"] = side

    def _blobs(self, depth, fx):
        """Every hand-shaped blob ahead of its surroundings in this frame."""
        import numpy as np
        k, c = self.STEP, self.CELL
        d = depth[::k, ::k].astype(np.float32)
        d[(d < NEAR_MM) | (d > FAR_MM)] = np.inf
        H, W = d.shape
        if self._grid is None or self._grid[0].shape != d.shape:
            self._grid = np.mgrid[0:H, 0:W].astype(np.float32)
        fxh = fx / k
        hh, ww = H // c * c, W // c * c
        cells = d[:hh, :ww].reshape(hh // c, c, ww // c, c).transpose(0, 2, 1, 3)
        cells = cells.reshape(hh // c, ww // c, c * c)
        mins = cells.min(axis=2)
        where = cells.argmin(axis=2)
        pad = np.pad(mins, 1, constant_values=np.inf)
        around = np.full(mins.shape, np.inf, np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    around = np.minimum(around, pad[1 + dy:1 + dy + mins.shape[0],
                                                    1 + dx:1 + dx + mins.shape[1]])
        local = np.isfinite(mins) & (mins <= around)
        cand = sorted(zip(mins[local].tolist(), *np.nonzero(local)))[:self.CANDIDATES]
        out = []
        for z0, gy, gx in cand:
            i = int(where[gy, gx])
            v0, u0 = gy * c + i // c, gx * c + i % c
            if any(abs(z0 - o["z"]) < 150 and math.hypot(u0 - o["u"] / k, v0 - o["v"] / k)
                   < 2.5 * HAND_RADIUS_M * fxh / (o["z"] / 1000) for o in out):
                continue                              # part of a hand already found
            blob = self._blob(d, u0, v0, z0, fxh)
            if blob is None:
                continue
            u, v, z, area = blob
            if any(math.hypot(u - o["u"] / k, v - o["v"] / k) < 1.5 * HAND_RADIUS_M * fxh / (z / 1000)
                   for o in out):
                continue
            out.append({"u": u * k, "v": v * k, "z": z, "area": area})
        return out

    def _blob(self, d, u, v, z0, fxh):
        import numpy as np
        cfg = self.cfg
        H, W = d.shape
        gy, gx = self._grid
        band = cfg["band"] * 1000
        z = z0
        for _ in range(3):
            r = HAND_RADIUS_M * fxh / (z / 1000.0)
            R = 1.3 * r
            x0, x1 = int(max(0, u - R)), int(min(W, u + R + 1))
            y0, y1 = int(max(0, v - R)), int(min(H, v + R + 1))
            patch = d[y0:y1, x0:x1]
            yy, xx = gy[y0:y1, x0:x1], gx[y0:y1, x0:x1]
            keep = (((xx - u) ** 2 + (yy - v) ** 2) <= R * R) & (patch <= z0 + band)
            n = int(keep.sum())
            if n < 8:
                return None
            u, v = float(xx[keep].mean()), float(yy[keep].mean())
            z = float(np.median(patch[keep]))
            if x0 == 0 or y0 == 0 or x1 == W or y1 == H:
                return None                           # cut by the picture's edge
        area = n * (z / 1000.0 / fxh) ** 2
        if not cfg["area_min"] <= area <= cfg["area_max"]:
            return None
        ex, ey = xx[keep] - u, yy[keep] - v
        cov = np.cov(np.stack([ex, ey]))
        lo, hi = np.linalg.eigvalsh(cov)
        if lo <= 0 or math.sqrt(hi / lo) > cfg["elongation"]:
            return None
        # The ring around the hand: mostly farther (the body, the room) or no reading at all.
        r = HAND_RADIUS_M * fxh / (z / 1000.0)
        R1, R2 = 1.7 * r, 2.5 * r
        x0, x1 = int(max(0, u - R2)), int(min(W, u + R2 + 1))
        y0, y1 = int(max(0, v - R2)), int(min(H, v + R2 + 1))
        patch = d[y0:y1, x0:x1]
        yy, xx = gy[y0:y1, x0:x1], gx[y0:y1, x0:x1]
        rr = (xx - u) ** 2 + (yy - v) ** 2
        ring = (rr >= R1 * R1) & (rr <= R2 * R2)
        total = int(ring.sum())
        if total < 8:
            return None
        near = int((ring & (patch < z + cfg["ahead"] * 1000)).sum())
        if near / total > cfg["ring_near"]:
            return None
        return u, v, z, area
