"""Whole-body gestures from across the room: the controls that need no remote.

Pure Python + numpy. The research behind this (and fifteen years of Kinect use) agrees that
gestures work for coarse, deliberate actions - raise a hand, both hands up, point at something,
step into a place - and not as a mouse. So every gesture here is big, held or fast on purpose, and
the exercises that look like one (a press raises both hands) switch the controls off while a set
is running unless the gesture is held longer.

Events (per person): raise_left / raise_right (a hand above the head, held), hands_up (both,
held: pause), t_pose (calibrate), clap, swipe_left / swipe_right, point (a ray at the floor or the
TV wall, held), jump, duck, lean (continuous, -1..1).
"""

import math

import numpy as np

import skeleton as sk

HOLD_RAISE = 0.6      # s a hand stays up before it counts
HOLD_BOTH = 1.0
HOLD_T = 1.2
HOLD_POINT = 1.0
SWIPE_SPEED = 1.4     # m/s across
SWIPE_TRAVEL = 0.35   # m
CLAP_NEAR = 0.12      # m between wrists
COOLDOWN = 1.2        # s before the same gesture fires again


class Gestures:
    """One person's gesture state. step(body, busy) -> list of events."""

    def __init__(self):
        self.since = {}
        self.fired = {}
        self.wrists = {"left": [], "right": []}
        self.apart = 0.0
        self.stand_hip = None
        self.lean = 0.0
        self.pointing = None

    def _held(self, key, on, t, hold):
        """True once, when `on` has lasted `hold` seconds (then not again until released)."""
        if not on:
            self.since.pop(key, None)
            self.fired.pop(key, None)
            return False
        start = self.since.setdefault(key, t)
        if t - start >= hold and not self.fired.get(key):
            self.fired[key] = t
            return True
        return False

    def _fresh(self, key, t):
        last = self.fired.get("~" + key)
        if last is not None and t - last < COOLDOWN:
            return False
        self.fired["~" + key] = t
        return True

    def step(self, b, busy=False):
        t, out = b.t, []
        slow = 1.8 if busy else 1.0          # mid-exercise: hold longer
        up = {s: b.wrist_above_head(s) for s in ("left", "right")}
        lu, ru = (up["left"] or -1) > 0.10, (up["right"] or -1) > 0.10
        if self._held("both", lu and ru, t, HOLD_BOTH * slow):
            out.append({"gesture": "hands_up"})
        if self._held("raise_left", lu and not ru, t, HOLD_RAISE * slow):
            out.append({"gesture": "raise_left"})
        if self._held("raise_right", ru and not lu, t, HOLD_RAISE * slow):
            out.append({"gesture": "raise_right"})
        # T-pose: both arms straight out to the side.
        ab = [b.abduction(s) for s in ("left", "right")]
        el = [b.elbow(s) for s in ("left", "right")]
        tpose = all(a is not None and 75 <= a <= 105 for a in ab) and all(e is not None and e > 150 for e in el)
        if self._held("t_pose", tpose, t, HOLD_T * slow):
            out.append({"gesture": "t_pose"})
        # Clap: the wrists come together quickly from apart.
        lw, rw = b.p(sk.L_WR), b.p(sk.R_WR)
        if lw is not None and rw is not None:
            gap = float(np.linalg.norm(lw - rw))
            if gap > 0.40:
                self.apart = t
            elif gap < CLAP_NEAR and t - self.apart < 0.5 and self._fresh("clap", t):
                out.append({"gesture": "clap"})
        # Swipes: a wrist travels fast across the body at chest height (not while busy).
        for s, w in (("left", lw), ("right", rw)):
            hist = self.wrists[s]
            if w is None:
                hist.clear()
                continue
            hist.append((t, float(w[0]), float(w[1])))
            while hist and t - hist[0][0] > 0.4:
                hist.pop(0)
            sh = b.p(sk.L_SH if s == "left" else sk.R_SH)
            if busy or len(hist) < 3 or sh is None or abs(w[1] - sh[1]) > 0.3:
                continue
            dx, dt = hist[-1][1] - hist[0][1], hist[-1][0] - hist[0][0]
            if dt > 0 and abs(dx) >= SWIPE_TRAVEL and abs(dx) / dt >= SWIPE_SPEED:
                # x grows to the picture's right = the person's left when facing the TV.
                name = "swipe_left" if dx > 0 else "swipe_right"
                if self._fresh("swipe", t):
                    out.append({"gesture": name, "speed": round(abs(dx) / dt, 2)})
                hist.clear()
        # Jump / duck, against the standing hip height learnt while still and straight.
        h = b.hip_height()
        k = [v for v in (b.knee("left"), b.knee("right")) if v is not None]
        if h is not None and k and min(k) > 160:
            self.stand_hip = h if self.stand_hip is None else 0.95 * self.stand_hip + 0.05 * h
        if h is not None and self.stand_hip:
            if h - self.stand_hip > 0.08 and self._fresh("jump", t):
                out.append({"gesture": "jump", "cm": round(100 * (h - self.stand_hip))})
            if self.stand_hip - h > 0.25 and self._fresh("duck", t):
                out.append({"gesture": "duck"})
        # Lean: the shoulders' sideways offset over the hips, in the person's own terms: -1
        # leaning to their left .. 1 to their right. Facing the Kinect, their right is the
        # picture's left (smaller x), so it is hips minus shoulders.
        self.lean = lean_of(b, self.lean)
        # Pointing: a straight arm held still away from the body -> where it points.
        self.pointing = None
        for s in ("left", "right"):
            ray = pointing_ray(b, s)
            if ray is not None:
                self.pointing = {"side": s, **ray}
        if self._held("point", self.pointing is not None and not busy, t, HOLD_POINT):
            out.append({"gesture": "point", **self.pointing})
        return out


def pointing_ray(b, side):
    """Where a straight, raised arm points: the TV wall (z = 0) or the floor (y = 0).

    The ray runs from the eyes through the wrist (people aim along their sight line, the
    eye-hand model of pointing research), only when the elbow is straight (> 150 deg) and the
    arm is clearly out from the body (> 35 deg)."""
    sh_, el_, wr_ = sk.SIDES[side][:3]
    e = b.elbow(side)
    out_angle = b.arm_drift(side)
    if e is None or e < 150 or out_angle is None or out_angle < 35:
        return None
    eye = b.mid(sk.L_EYE, sk.R_EYE)
    w = b.p(wr_)
    if eye is None or w is None:
        return None
    d = w - eye
    n = np.linalg.norm(d)
    if n < 0.2:
        return None
    d = d / n
    hits = []
    if d[2] < -0.2:                                   # towards the TV wall
        k = -eye[2] / d[2]
        p = eye + k * d
        hits.append(("wall", k, [round(float(p[0]), 2), round(float(p[1]), 2)]))
    if d[1] < -0.2:                                   # down at the floor
        k = -eye[1] / d[1]
        p = eye + k * d
        hits.append(("floor", k, [round(float(p[0]), 2), round(float(p[2]), 2)]))
    if not hits:
        return None
    where, _, at = min(hits, key=lambda h: h[1])
    return {"at": where, "point": at}


def lean_of(b, default=0.0):
    """-1 (leaning to their left) .. 1 (to their right): 25 deg of torso tilt is full."""
    sh, hp = b.mid(sk.L_SH, sk.R_SH), b.mid(sk.L_HIP, sk.R_HIP)
    if sh is None or hp is None:
        return default
    ang = math.degrees(math.atan2(hp[0] - sh[0], max(sh[1] - hp[1], 1e-3)))
    return max(-1.0, min(1.0, ang / 25.0))


def steering(b):
    """An imaginary steering wheel held in both hands: -1 (full left) .. 1 (full right), or None.

    The angle of the line between the wrists against level, as Kinect Joy Ride did it; +-60 deg is
    full lock. Throttle: how far both hands are pushed out ahead of the shoulders, 0..1."""
    lw, rw = b.p(sk.L_WR), b.p(sk.R_WR)
    ls, rs = b.p(sk.L_SH), b.p(sk.R_SH)
    if lw is None or rw is None or ls is None or rs is None:
        return None
    # The person's right hand is at smaller x (facing the Kinect); turning right drops it.
    dx, dy = lw[0] - rw[0], lw[1] - rw[1]
    angle = math.degrees(math.atan2(dy, max(abs(dx), 1e-3)))
    wheel = max(-1.0, min(1.0, angle / 60.0))
    reach = ((ls[2] + rs[2]) / 2) - ((lw[2] + rw[2]) / 2)      # hands nearer the TV than shoulders
    throttle = max(0.0, min(1.0, (reach - 0.25) / 0.25))
    brake = 1.0 if reach < 0.12 else 0.0
    return {"wheel": round(wheel, 3), "throttle": round(throttle, 3), "brake": brake}
