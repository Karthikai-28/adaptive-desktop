"""One person's body as numbers: joints in the room, angles, and how sure we are of them.

Pure numpy. The joints come from the Kinect hub (people.py `joints`): 33 MediaPipe joints in the
room frame, metres, x to the picture's right, y up from the floor, z away from the Kinect, and a
state per joint like the Kinect SDK's: 2 tracked (depth agrees), 1 inferred (model only), 0 missing.

Everything that coaches someone asks `evidence()` first: a joint the camera did not see must not
turn into a wrong correction ("insufficient evidence" instead).
"""

import math

import numpy as np

# MediaPipe's 33 landmarks, by name
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 2, 5, 7, 8
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 11, 12, 13, 14, 15, 16
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK = 23, 24, 25, 26, 27, 28
L_HEEL, R_HEEL, L_TOE, R_TOE = 29, 30, 31, 32
SIDES = {"left": (L_SH, L_EL, L_WR, L_HIP, L_KNEE, L_ANK),
         "right": (R_SH, R_EL, R_WR, R_HIP, R_KNEE, R_ANK)}
UP = np.array([0.0, 1.0, 0.0])
TRACKED, INFERRED, MISSING = 2, 1, 0

# The bones whose lengths a person keeps: checked against their own first seconds in view.
BONES = ((L_SH, L_EL), (L_EL, L_WR), (R_SH, R_EL), (R_EL, R_WR),
         (L_HIP, L_KNEE), (L_KNEE, L_ANK), (R_HIP, R_KNEE), (R_KNEE, R_ANK),
         (L_SH, R_SH), (L_HIP, R_HIP))


def angle(a, b, c):
    """Angle at b (degrees) between b->a and b->c, or None."""
    if a is None or b is None or c is None:
        return None
    u, w = a - b, c - b
    nu, nw = np.linalg.norm(u), np.linalg.norm(w)
    if nu < 1e-6 or nw < 1e-6:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, float(u @ w / (nu * nw))))))


def between(v, direction):
    """Angle (degrees) between a vector and a direction, or None."""
    if v is None:
        return None
    n, m = np.linalg.norm(v), np.linalg.norm(direction)
    if n < 1e-6 or m < 1e-6:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, float(v @ direction / (n * m))))))


class OneEuro3:
    """The One Euro filter (Casiez et al. 2012) on 3D points: steady when still, quick when moving."""

    def __init__(self, min_cutoff=1.2, beta=0.4, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.x is None or t <= self.t:
            self.x, self.dx, self.t = x.copy(), np.zeros(3), t
            return x
        dt = t - self.t
        self.t = t
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * (x - self.x) / dt + (1 - a_d) * self.dx
        a = self._alpha(self.min_cutoff + self.beta * float(np.linalg.norm(self.dx)), dt)
        self.x = a * x + (1 - a) * self.x
        return self.x.copy()


class Body:
    """One frame of one person: joints (33, 3) with NaN for missing, states (33,), time t."""

    def __init__(self, pid, joints, states, t, height_cm=None, posture=None, colour=0, identity="sure"):
        self.id, self.t, self.colour = pid, t, colour
        self.joints = np.asarray(joints, dtype=np.float64)
        self.states = np.asarray(states, dtype=np.int8)
        self.height_cm, self.posture = height_cm, posture
        self.identity = identity          # the hub's: "sure", or "unsure" mid-crossing

    @classmethod
    def from_hub(cls, person, t):
        """A Body from one entry of the hub's /api/people."""
        joints = np.full((33, 3), np.nan)
        states = np.zeros(33, np.int8)
        for i, j in enumerate(person.get("joints") or []):
            if j is not None:
                joints[i], states[i] = j[:3], j[3]
        return cls(person["id"], joints, states, t, person.get("height_cm"), person.get("posture"),
                   person.get("colour", 0), person.get("identity", "sure"))

    # -- joints

    def p(self, i):
        return None if self.states[i] == MISSING else self.joints[i]

    def mid(self, a, b):
        pa, pb = self.p(a), self.p(b)
        if pa is None or pb is None:
            return pa if pb is None else pb
        return (pa + pb) / 2

    def evidence(self, ids):
        """0..1: how well the camera actually saw these joints (tracked 1, inferred 0.5)."""
        s = self.states[list(ids)]
        return float(np.mean(np.where(s == TRACKED, 1.0, np.where(s == INFERRED, 0.5, 0.0))))

    # -- angles the exercises use

    def knee(self, side):
        _, _, _, hip, knee, ank = SIDES[side]
        return angle(self.p(hip), self.p(knee), self.p(ank))

    def hip(self, side):
        sh, _, _, hip, knee, _ = SIDES[side]
        return angle(self.p(sh), self.p(hip), self.p(knee))

    def elbow(self, side):
        sh, el, wr, _, _, _ = SIDES[side]
        return angle(self.p(sh), self.p(el), self.p(wr))

    def abduction(self, side):
        """Upper arm away from the body (0 = hanging down, 90 = out to the side), against the
        torso's own down direction (shoulders' middle to hips' middle), so a lean does not count."""
        sh = SIDES[side][0]
        s, e = self.p(sh), self.p(SIDES[side][1])
        top, bottom = self.mid(L_SH, R_SH), self.mid(L_HIP, R_HIP)
        if s is None or e is None or top is None or bottom is None:
            return None
        return between(e - s, bottom - top)

    def arm_drift(self, side):
        """Upper arm against straight down (degrees): elbows "by your sides" is under ~25."""
        sh, el, _, _, _, _ = SIDES[side]
        s, e = self.p(sh), self.p(el)
        return None if s is None or e is None else between(e - s, -UP)

    def trunk_lean(self):
        """Torso against true vertical (degrees): 0 upright, 90 lying."""
        sh, hp = self.mid(L_SH, R_SH), self.mid(L_HIP, R_HIP)
        return None if sh is None or hp is None else between(sh - hp, UP)

    def thigh(self, side):
        """Thigh against straight down (0 standing, 90 knee lifted to hip height)."""
        _, _, _, hip, knee, _ = SIDES[side]
        h, k = self.p(hip), self.p(knee)
        return None if h is None or k is None else between(k - h, -UP)

    def hip_height(self):
        hp = self.mid(L_HIP, R_HIP)
        return None if hp is None else float(hp[1])

    def width(self, a, b):
        """Horizontal distance between two joints (m), on the floor plane."""
        pa, pb = self.p(a), self.p(b)
        if pa is None or pb is None:
            return None
        d = pa - pb
        return float(math.hypot(d[0], d[2]))

    def centre(self):
        """Where the body stands on the floor (x, z): the middle of the hips, else the shoulders."""
        c = self.mid(L_HIP, R_HIP)
        if c is None:
            c = self.mid(L_SH, R_SH)
        return None if c is None else np.array([c[0], c[2]])

    def body_line(self):
        """Shoulder-hip-ankle angle (degrees): 180 is a straight plank."""
        return angle(self.mid(L_SH, R_SH), self.mid(L_HIP, R_HIP), self.mid(L_ANK, R_ANK))

    def wrist_above_head(self, side):
        wr = self.p(SIDES[side][2])
        nose = self.p(NOSE)
        if wr is None or nose is None:
            return None
        return float(wr[1] - nose[1])

    def bone_lengths(self):
        out = {}
        for a, b in BONES:
            if self.states[a] == TRACKED and self.states[b] == TRACKED:
                out[(a, b)] = float(np.linalg.norm(self.joints[a] - self.joints[b]))
        return out


class Filter:
    """Per-person joint smoothing and evidence checks, over time.

    Each joint gets a One Euro filter. Each person's bone lengths are learnt from their first
    tracked frames (medians); later, a joint whose bone is more than 30% off its learnt length is
    demoted to inferred: a depth pixel on the sofa, not the knee. A joint that moved faster than
    any limb can (MAX_SPEED, from where it was last frame) is demoted the same way: a landmark
    that jumped to the other arm, or depth from the wall behind a hand."""

    LEARN = 15            # frames of bone lengths before they are trusted
    OFF = 0.30
    MAX_SPEED = 12.0      # m/s: a punching fist peaks near 8

    def __init__(self):
        self.filters = {}
        self.lengths = {}
        self.samples = {}
        self.last = {}        # pid -> (t, raw joints)

    def __call__(self, body):
        prev = self.last.get(body.id)
        raw = body.joints.copy()
        if prev is not None and body.t > prev[0]:
            dt = body.t - prev[0]
            moved = np.linalg.norm(raw - prev[1], axis=1) / dt
            fast = np.nan_to_num(moved, nan=0.0) > self.MAX_SPEED
            body.states[fast & (body.states == TRACKED)] = INFERRED
        self.last[body.id] = (body.t, raw)
        # Bone check first, on the raw joints.
        learnt = self.lengths.get(body.id, {})
        for (a, b), length in body.bone_lengths().items():
            ref = learnt.get((a, b))
            if ref is not None and abs(length - ref) > self.OFF * ref:
                for j in (a, b):                     # the end further from the torso is the suspect
                    if j not in (L_SH, R_SH, L_HIP, R_HIP):
                        body.states[j] = INFERRED
            else:
                s = self.samples.setdefault(body.id, {}).setdefault((a, b), [])
                if len(s) < 60:
                    s.append(length)
                if len(s) >= self.LEARN:
                    learnt[(a, b)] = float(np.median(s))
        self.lengths[body.id] = learnt
        # Then smoothing.
        f = self.filters.setdefault(body.id, [OneEuro3() for _ in range(33)])
        for i in range(33):
            if body.states[i] != MISSING:
                body.joints[i] = f[i](body.joints[i], body.t)
        return body

    def forget(self, pid):
        for d in (self.filters, self.lengths, self.samples, self.last):
            d.pop(pid, None)
