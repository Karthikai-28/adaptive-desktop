"""Guided demonstrations: a figure doing each exercise and game move, for the page to play.

Built by forward kinematics from joint angles (sim.figure, the same synthetic person the checks
count), so the demonstration is the movement the counter measures: the depth a squat must
reach, how high a lateral raise goes, what "arms out" means to Wall Dodge. Each demo is one
repetition as frames of 33 room-frame joints (x right, y up, z away from the Kinect), standing
at x = 0, z = 0, played in a loop.
"""

import math

import numpy as np

import sim
import skeleton as sk

FPS = 15


def _wave(t, period):
    return 0.5 - 0.5 * math.cos(2 * math.pi * t / period)


def _lerp(a, b, k):
    if isinstance(a, tuple):
        return tuple(x + (y - x) * k for x, y in zip(a, b))
    return a + (b - a) * k


def _between(rest, work, period, extra=None):
    """A repetition from rest to work and back: figure() keyword sets."""
    def pose(t):
        k = _wave(t, period)
        kw = {}
        for key in set(rest) | set(work):
            r, w = rest.get(key, work.get(key)), work.get(key, rest.get(key))
            kw[key] = r if isinstance(r, str) else _lerp(r, w, k)
        if extra:
            kw.update(extra)
        return sim.figure(z=0.0, **kw)
    return pose, period


def _lunge(t, period=2.6):
    k = _wave(t, period)
    J = sim.figure(z=0.0, knee=180 - 75 * k, lean=4)
    # The left foot steps forward (towards the Kinect), the right stays back.
    J[sk.L_ANK] += np.array([0, 0, -0.45 * k])
    J[sk.L_KNEE] += np.array([0, 0, -0.30 * k])
    J[sk.L_HEEL] += np.array([0, 0, -0.45 * k])
    J[sk.L_TOE] += np.array([0, 0, -0.45 * k])
    J[sk.R_KNEE] += np.array([0, -0.10 * k, 0.12 * k])
    return J


def _knees(t, period=1.0):
    k = _wave(t % period, period)
    left = 80 * k if int(t / period) % 2 == 0 else 0
    right = 80 * k if int(t / period) % 2 == 1 else 0
    return sim.figure(z=0.0, thigh=(left, right), abduct=(20, 20), elbow=(90, 90))


def _jump(t, period=1.6):
    p = t % period
    lift = max(0.0, 0.25 * math.sin(math.pi * p / 0.6)) if p < 0.6 else 0.0
    knee = 180 - 50 * _wave(p, period) if lift == 0 else 175
    return sim.figure(z=0.0, lift=lift, knee=knee, abduct=(30, 30))


def _punch(t, period=1.2):
    k = _wave(t % period, period)
    left = int(t / period) % 2 == 0
    return sim.figure(z=0.0, arm_forward=(70 + 20 * k if left else 70, 70 if left else 70 + 20 * k),
                      elbow=(80 + 95 * k if left else 80, 80 if left else 80 + 95 * k), abduct=(15, 15))


def _plank(t, period=4.0):
    J = sim.figure(z=0.0)
    rot = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]).T
    J = (J - J[sk.L_ANK]) @ rot
    # Side-on to the Kinect: the body along x, a little above the floor.
    J = J @ np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]]).T + np.array([-0.8, 0.15, 0.0])
    return J


def _balance(t, period=4.0):
    J = sim.figure(z=0.0, abduct=(25, 25))
    lift = 0.15 * min(1.0, 2 * _wave(t, period))
    J[sk.R_ANK] += np.array([0, lift, 0.05])
    J[sk.R_HEEL] += np.array([0, lift, 0.05])
    J[sk.R_TOE] += np.array([0, lift, 0.05])
    J[sk.R_KNEE] += np.array([0, lift * 0.5, -0.05])
    return J


def _reach(t, period=4.0):
    k = _wave(t, period)
    return sim.figure(z=0.0, lean=85 * k, abduct=(5, 5), arm_forward=(10 + 70 * k, 10 + 70 * k))


def _lean(direction):
    def pose(t, period=2.0):
        k = min(1.0, 2 * _wave(t, period))
        J = sim.figure(z=0.0)
        for i in range(0, 23):
            J[i] = J[i] + np.array([-direction * 0.25 * k, -0.02 * k, 0])
        return J
    return pose


def _hold(**kw):
    return lambda t, period=2.0: sim.figure(z=0.0, **kw)


EXERCISES = {
    "squat": _between({"knee": 178, "lean": 3}, {"knee": 92, "lean": 30, "feet": 0.16}, 2.4),
    "lunge": (_lunge, 2.6),
    "jack": _between({"abduct": (12, 12), "feet": 0.10}, {"abduct": (165, 165), "feet": 0.38}, 1.2),
    "knees": (_knees, 2.0),
    "curl": _between({"elbow": (170, 170)}, {"elbow": (45, 45)}, 2.2),
    "press": _between({"abduct": (90, 90), "elbow": (88, 88), "fore": "frontal"},
                      {"abduct": (172, 172), "elbow": (176, 176), "fore": "frontal"}, 2.0),
    "raise": _between({"abduct": (8, 8)}, {"abduct": (88, 88)}, 2.2),
    "chair": _between({"knee": 80, "lean": 25}, {"knee": 178, "lean": 2}, 3.0),
    "jump": (_jump, 1.6),
    "punch": (_punch, 2.4),
    "plank": (_plank, 4.0),
    "wallsit": (_hold(knee=95, lean=0, abduct=(10, 10)), 3.0),
    "balance": (_balance, 4.0),
    "reach": (_reach, 4.0),
}

MOVES = {
    # Wall Dodge
    "duck": _between({"knee": 178}, {"knee": 85, "lean": 35}, 1.6),
    "jump": (_jump, 1.6),
    "left": (_lean(-1), 2.0),
    "right": (_lean(1), 2.0),
    "up": _between({"abduct": (12, 12)}, {"abduct": (172, 172)}, 1.6),
    "out": _between({"abduct": (12, 12)}, {"abduct": (90, 90)}, 1.6),
    # Body Racer
    "wheel": (_hold(abduct=(30, 30), arm_forward=(70, 70), elbow=(150, 150)), 2.0),
}


def pose_figure(a):
    """A Pose Match target (its angles, games.POSES[...]["a"]) as a standing figure."""
    knee = (a["lkn"] + a["rkn"]) / 2
    return sim.figure(z=0.0, abduct=(a["lab"], a["rab"]), elbow=(a["lel"], a["rel"]), knee=knee,
                      feet=a["feet"] / 2, fore="frontal")


def frames(key, height=1.75):
    """{"key", "period", "fps", "frames": [[[x, y, z], ...33], ...]} or None."""
    item = EXERCISES.get(key) or MOVES.get(key)
    if item is None:
        return None
    fn, period = item
    n = max(2, int(round(period * FPS)))
    out = []
    for i in range(n):
        J = fn(i / FPS)
        J = J * (height / 1.75)
        out.append([[round(float(v), 3) for v in j] for j in J])
    return {"key": key, "period": period, "fps": FPS, "frames": out}
