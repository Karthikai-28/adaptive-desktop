"""Synthetic people exercising, for the checks and the demo (no Kinect, no person needed).

A stick figure built by forward kinematics from joint angles, in the hub's room frame (metres,
x to the picture's right, y up, z away from the Kinect), facing the Kinect. Segment lengths are
the usual anthropometric shares of standing height (Winter, Biomechanics and Motor Control of
Human Movement). Because each frame is made from angles, a check knows the true answer.
"""

import math

import numpy as np

import skeleton as sk

SEG = {"shank": 0.246, "thigh": 0.245, "torso": 0.288, "upper": 0.186, "fore": 0.146,
       "neck": 0.10, "hip_w": 0.055, "sh_w": 0.11}


def figure(height=1.75, x=0.0, z=2.8, knee=180.0, lean=0.0, abduct=(10.0, 10.0),
           elbow=(175.0, 175.0), fore="sagittal", thigh=(0.0, 0.0), feet=0.10, lift=0.0,
           arm_forward=(0.0, 0.0)):
    """33 joints (room frame) for a pose given by angles in degrees.

    knee: both knees (180 straight; the squat folds shanks forward and thighs back equally)
    lean: torso forward towards the Kinect; abduct: upper arms out to the side (0 = hanging)
    elbow: elbow angles; fore: forearm bends towards the Kinect (sagittal) or up/out (frontal)
    thigh: per-leg knee lift (high knees); feet: half the stance width; lift: whole body up (a jump)
    arm_forward: upper arm raised forwards (a punch or a guard)"""
    H = height
    J = np.zeros((33, 3))
    a = math.radians((180.0 - knee) / 2)
    side = {"left": 1.0, "right": -1.0}
    fwd = np.array([0.0, 0.0, -1.0])               # towards the Kinect
    for i, s in enumerate(("left", "right")):
        sh_, el_, wr_, hip_, kn_, an_ = sk.SIDES[s]
        q = math.radians(thigh[i])
        ank = np.array([x + side[s] * feet, 0.08 + lift, z])
        if thigh[i] > 0:                           # this knee lifted: the hip stays, the leg rises
            hip = np.array([x + side[s] * SEG["hip_w"] * H, 0.08 + lift + (SEG["shank"] + SEG["thigh"]) * H, z])
            kn = hip + SEG["thigh"] * H * np.array([0, -math.cos(q), -math.sin(q)])
            ank = kn + SEG["shank"] * H * np.array([0, -1.0, 0])
        else:
            kn = ank + SEG["shank"] * H * np.array([0, math.cos(a), -math.sin(a)])
            hip = kn + SEG["thigh"] * H * np.array([0, math.cos(a), math.sin(a)])
            hip[0] = x + side[s] * SEG["hip_w"] * H
        J[hip_], J[kn_], J[an_] = hip, kn, ank
        J[sk.L_HEEL if s == "left" else sk.R_HEEL] = ank + np.array([0, -0.05, 0.04])
        J[sk.L_TOE if s == "left" else sk.R_TOE] = ank + np.array([0, -0.06, -0.14])
    hip_mid = (J[sk.L_HIP] + J[sk.R_HIP]) / 2
    r = math.radians(lean)
    up_t = np.array([0.0, math.cos(r), -math.sin(r)])
    neck = hip_mid + SEG["torso"] * H * up_t
    for i, s in enumerate(("left", "right")):
        sh_, el_, wr_, _, _, _ = sk.SIDES[s]
        sh = neck + np.array([side[s] * SEG["sh_w"] * H, 0, 0])
        ab, af = math.radians(abduct[i]), math.radians(arm_forward[i])
        # The upper arm: down, swung out to the side by ab and forwards by af.
        d = np.array([side[s] * math.sin(ab) * math.cos(af), -math.cos(ab) * math.cos(af), -math.sin(af)])
        d /= np.linalg.norm(d)
        el = sh + SEG["upper"] * H * d
        f = math.radians(180.0 - elbow[i])
        if fore == "sagittal":                     # curls, punches: the forearm swings forward/up
            axis = np.cross(d, fwd)
            if np.linalg.norm(axis) < 1e-6:
                axis = np.array([1.0, 0, 0])
            axis /= np.linalg.norm(axis)
            fd = _rotate(d, -axis, f)
        else:                                      # presses: the forearm turns up in the frontal plane
            fd = _rotate(d, np.array([0, 0, side[s]]), f)
        wr = el + SEG["fore"] * H * fd
        J[sh_], J[el_], J[wr_] = sh, el, wr
        for k in ((17, 19, 21) if s == "left" else (18, 20, 22)):
            J[k] = wr + 0.04 * fd
    head = neck + SEG["neck"] * H * up_t
    J[sk.NOSE] = head + np.array([0, 0.02, -0.09])
    for k, dx in ((1, 0.02), (2, 0.03), (3, 0.045), (4, -0.02), (5, -0.03), (6, -0.045)):
        J[k] = head + np.array([dx, 0.05, -0.07])
    J[sk.L_EAR], J[sk.R_EAR] = head + np.array([0.075, 0.04, 0]), head + np.array([-0.075, 0.04, 0])
    J[9], J[10] = head + np.array([0.02, -0.02, -0.08]), head + np.array([-0.02, -0.02, -0.08])
    return J


def _rotate(v, axis, angle):
    """Rodrigues: v turned by angle (radians) about a unit axis."""
    axis = axis / np.linalg.norm(axis)
    return (v * math.cos(angle) + np.cross(axis, v) * math.sin(angle)
            + axis * (axis @ v) * (1 - math.cos(angle)))


def body(J, t, pid=1, noise=0.01, hide=(), rng=None, height_cm=175):
    """A sk.Body from joints, with sensor noise (m) and some joints hidden."""
    rng = rng or np.random.default_rng(0)
    states = np.full(33, sk.TRACKED, np.int8)
    joints = J + rng.normal(0, noise, J.shape)
    for i in hide:
        states[i] = sk.MISSING
        joints[i] = np.nan
    return sk.Body(pid, joints, states, t, height_cm=height_cm)


def wave(t, period):
    """0 -> 1 -> 0 once per period (a smooth repetition)."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * t / period)


# Each move: (rest pose, work pose) as figure() keyword arguments, and a repetition's length.
MOVES = {
    "squat": ({"knee": 178, "lean": 3}, {"knee": 88, "lean": 32, "feet": 0.16}, 2.4),
    "shallow": ({"knee": 178, "lean": 3}, {"knee": 125, "lean": 15}, 2.0),
    "squat-lean": ({"knee": 178, "lean": 3}, {"knee": 88, "lean": 62, "feet": 0.16}, 2.4),
    "jack": ({"abduct": (12, 12), "feet": 0.10}, {"abduct": (165, 165), "feet": 0.38}, 1.0),
    "curl": ({"elbow": (170, 170)}, {"elbow": (40, 40)}, 2.2),
    "curl-swing": ({"elbow": (170, 170), "lean": 0}, {"elbow": (40, 40), "lean": -20}, 2.2),
    "press": ({"abduct": (90, 90), "elbow": (88, 88), "fore": "frontal"},
              {"abduct": (172, 172), "elbow": (176, 176), "fore": "frontal"}, 2.0),
    "raise": ({"abduct": (8, 8)}, {"abduct": (85, 85)}, 2.2),
    "chair": ({"knee": 75, "lean": 25}, {"knee": 178, "lean": 2}, 3.0),
}


def move(name, t, **extra):
    """The figure doing `name` at time t (seconds)."""
    rest, work, period = MOVES[name]
    k = wave(t, period)
    kw = {}
    for key in set(rest) | set(work):
        r, w = rest.get(key), work.get(key)
        if isinstance(r, str) or isinstance(w, str):
            kw[key] = r or w
        elif isinstance(r, tuple) or isinstance(w, tuple):
            r = r or (10.0, 10.0) if key == "abduct" else r or (175.0, 175.0)
            w = w or r
            kw[key] = tuple(r[i] + (w[i] - r[i]) * k for i in range(2))
        else:
            r = r if r is not None else {"knee": 180, "lean": 0, "feet": 0.10}[key]
            w = w if w is not None else r
            kw[key] = r + (w - r) * k
    kw.update(extra)
    return figure(**kw)


def session(name, seconds, fps=15.0, **kw):
    """Bodies for `seconds` of `name` at `fps`."""
    rng = np.random.default_rng(7)
    hide = kw.pop("hide", ())
    noise = kw.pop("noise", 0.01)
    pid = kw.pop("pid", 1)
    out = []
    for i in range(int(seconds * fps)):
        t = i / fps
        out.append(body(move(name, t, **kw), t, pid=pid, noise=noise, hide=hide, rng=rng))
    return out
