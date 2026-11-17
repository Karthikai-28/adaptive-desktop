"""Exercises: counting repetitions, timing holds and coaching form from a Body.

Pure Python + numpy. Every repeated exercise is the same shape: a body signal (a knee angle, an
elbow angle, how far the arms are raised) leaves its rest value, reaches its work value and comes
back. One state machine with hysteresis does that for all of them (`Machine`); each exercise adds
what to watch on the way (`cues`), what a full repetition means, and its energy cost (MET).

Rules of thumb behind the numbers (knee > 155 deg standing, < 100 deg squatting, elbows within
~25-30 deg of vertical in a curl, etc.) are the usual coaching thresholds, the same kind as the
straight-knee rule in people.py. They are trend signals, not clinical measurements: Kinect-class
joint angles agree with marker systems well when a joint is seen and poorly when it is hidden
(Jo et al., Sensors 2022), so nothing here coaches a joint the camera did not see.

MET values: 2024 Adult Compendium of Physical Activities (Herrmann et al.), codes cited per
exercise. `proxy` marks an exercise the Compendium has no entry for; the nearest code is used.
"""

from collections import deque

import numpy as np

import skeleton as sk
from skeleton import (L_ANK, L_HIP, L_KNEE, L_SH, L_WR, R_ANK, R_HIP, R_KNEE, R_SH, R_WR,
                      L_EL, R_EL)

EVIDENCE = 0.55        # below this the joints are too unsure to count or coach
CUE_FRAMES = 3         # a fault must show on this many frames of a rep before it is said
CUE_PENALTY = 15       # points off a rep's form score per fault


# ------------------------------------------------------------------ the repetition machine

class Machine:
    """rest -> work -> rest on one signal, with hysteresis.

    `rest` and `work` are the two thresholds; the signal may run either way between them (a squat's
    knee angle falls, a press's arm height rises). Leaving rest starts a repetition; reaching work
    makes it full; coming back to rest finishes it. Turning back before work, after at least
    `partial` of the way, is a partial repetition (counted apart, with a cue)."""

    def __init__(self, rest, work, partial=0.45, min_time=0.35, max_time=12.0):
        self.rest, self.work = float(rest), float(work)
        self.sign = 1.0 if work > rest else -1.0
        self.partial, self.min_time, self.max_time = partial, min_time, max_time
        self.phase = "rest"
        self.t0 = self.tw = None
        self.peak = None

    def depth(self, v):
        """0 at rest, 1 at work (can go past either end)."""
        return (v - self.rest) * self.sign / ((self.work - self.rest) * self.sign)

    def reset(self):
        self.phase, self.t0, self.tw, self.peak = "rest", None, None, None

    def step(self, v, t):
        """Feed one value; returns None, or ("rep", info) / ("partial", info)."""
        if v is None:
            return None
        d = self.depth(v)
        if self.phase == "rest":
            if d > 0.12:                                    # left the rest position
                self.phase, self.t0, self.tw, self.peak = "going", t, None, d
            return None
        self.peak = max(self.peak, d)
        if self.t0 is not None and t - self.t0 > self.max_time:   # stalled half way: start over
            self.reset()
            return None
        if self.phase == "going" and d >= 1.0:
            self.phase, self.tw = "work", t
            return None
        if d <= 0.05:                                      # back at rest
            info = {"t0": self.t0, "t1": t, "peak": self.peak,
                    "down": (self.tw - self.t0) if self.tw else None,
                    "up": (t - self.tw) if self.tw else None}
            full = self.phase == "work"
            self.reset()
            if t - info["t0"] < self.min_time:
                return None                                 # a twitch, not a repetition
            if full:
                return ("rep", info)
            if info["peak"] >= self.partial:
                return ("partial", info)
        return None

    def progress(self, v):
        """0..1 through the repetition, for the ring on the screen."""
        if v is None or self.phase == "rest":
            return 0.0
        return max(0.0, min(1.0, self.depth(v)))


# ------------------------------------------------------------------ exercise definitions

def _mean(*vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _arm_height(b, side):
    """Wrist above the shoulder, in arm lengths (0 at shoulder height, ~1 straight overhead)."""
    sh, el, wr = sk.SIDES[side][:3]
    s, e, w = b.p(sh), b.p(el), b.p(wr)
    if s is None or e is None or w is None:
        return None
    arm = np.linalg.norm(e - s) + np.linalg.norm(w - e)
    return float((w[1] - s[1]) / max(arm, 0.2))


class Exercise:
    """One exercise. Subclasses set the fields and override signal / cues where needed."""

    key = name = ""
    kind = "reps"            # reps | sides (each arm or leg counted on its own) | hold
    joints = ()
    rest = work = 0.0
    partial = 0.45
    min_time = 0.35                  # s: anything quicker is a twitch, not a repetition
    together = False                 # both sides at once count as one repetition (curls)
    met = (3.0, "02056", False)      # (MET, Compendium code, proxy?)
    target = 10                      # reps, or seconds for a hold
    how = ""
    partial_cue = "Go the full range"
    bilateral = None                 # (left signal, right signal) for an asymmetry figure
    muscles = ()

    def signal(self, b, side=None):
        raise NotImplementedError

    def cues(self, b, ctx):
        """Faults this frame (only frames inside a repetition): [(key, words)]."""
        return []

    def rep_cues(self, info, ctx):
        """Faults of a whole repetition (tempo, depth)."""
        return []

    def sides(self):
        return ("left", "right") if self.kind == "sides" else (None,)


class Squat(Exercise):
    key, name = "squat", "Squat"
    joints = (L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK)
    rest, work, partial = 155.0, 100.0, 0.4
    met = (5.0, "02052", False)
    how = "Feet shoulder-width apart, sit back until your thighs are level, stand up tall."
    partial_cue = "Go a little deeper"
    muscles = ("quads", "glutes", "hamstrings", "core")

    def signal(self, b, side=None):
        return _mean(b.knee("left"), b.knee("right"))

    def cues(self, b, ctx):
        out = []
        lean = b.trunk_lean()
        if lean is not None and lean > 48:
            out.append(("chest", "Keep your chest up"))
        kw, aw = b.width(L_KNEE, R_KNEE), b.width(L_ANK, R_ANK)
        # Knees caving in (valgus), seen from the front: knees closer together than the ankles.
        if kw is not None and aw and aw > 0.15 and kw / aw < 0.78 and ctx["depth"] > 0.6:
            out.append(("knees", "Push your knees out over your toes"))
        l, r = b.knee("left"), b.knee("right")
        if l is not None and r is not None and abs(l - r) > 18 and ctx["depth"] > 0.6:
            out.append(("even", "Sit evenly on both legs"))
        return out

    def rep_cues(self, info, ctx):
        if info["down"] is not None and info["down"] < 0.4:
            return [("slow", "Lower yourself more slowly")]
        return []


class Lunge(Exercise):
    key, name = "lunge", "Lunge"
    joints = (L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK)
    rest, work, partial = 155.0, 108.0, 0.4
    met = (3.8, "02022", False)
    how = "Step forward, lower until both knees bend to about a right angle, push back. Alternate legs."
    partial_cue = "Drop your back knee lower"
    muscles = ("quads", "glutes", "hamstrings")

    def signal(self, b, side=None):
        k = [v for v in (b.knee("left"), b.knee("right")) if v is not None]
        return min(k) if k else None

    def lead(self, b):
        """Which leg is in front: the ankle nearer the Kinect."""
        la, ra = b.p(L_ANK), b.p(R_ANK)
        if la is None or ra is None:
            return None
        return "left" if la[2] < ra[2] else "right"

    def cues(self, b, ctx):
        lean = b.trunk_lean()
        return [("upright", "Keep your torso upright")] if lean is not None and lean > 28 else []


class JumpingJack(Exercise):
    key, name = "jack", "Jumping jacks"
    joints = (L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_ANK, R_ANK)
    rest, work, partial = 40.0, 135.0, 0.5
    met = (7.5, "02020", False)
    target = 20
    how = "Jump your feet wide while your arms sweep overhead, then back together."
    partial_cue = "Arms all the way up"
    muscles = ("full body", "calves", "shoulders")

    def signal(self, b, side=None):
        return _mean(b.abduction("left"), b.abduction("right"))

    def cues(self, b, ctx):
        aw, hw = b.width(L_ANK, R_ANK), b.width(L_HIP, R_HIP)
        if ctx["depth"] > 0.9 and aw is not None and hw and aw < 1.5 * hw:
            return [("feet", "Jump your feet wider")]
        return []


class HighKnees(Exercise):
    key, name, kind = "knees", "High knees", "sides"
    joints = (L_HIP, R_HIP, L_KNEE, R_KNEE)
    rest, work, partial = 25.0, 68.0, 0.5
    met = (7.5, "02020", True)            # no running-in-place entry: vigorous calisthenics
    target = 30
    how = "Run on the spot, lifting each knee to hip height."
    partial_cue = "Knees higher"
    muscles = ("hip flexors", "quads", "calves")

    def signal(self, b, side=None):
        return b.thigh(side)


class Curl(Exercise):
    key, name, kind = "curl", "Biceps curl", "sides"
    together = True
    joints = (L_SH, R_SH, L_EL, R_EL, L_WR, R_WR)
    rest, work, partial = 145.0, 62.0, 0.5
    met = (3.5, "02054", False)
    target = 12
    how = "Elbows by your sides, curl the weights up to your shoulders, lower slowly."
    partial_cue = "Curl all the way up"
    muscles = ("biceps", "forearms")

    def signal(self, b, side=None):
        return b.elbow(side)

    def cues(self, b, ctx):
        out = []
        drift = b.arm_drift(ctx["side"])
        if drift is not None and drift > 32:
            out.append(("elbows", "Keep your elbows by your sides"))
        lean = b.trunk_lean()
        if lean is not None and ctx.get("lean0") is not None and abs(lean - ctx["lean0"]) > 12:
            out.append(("swing", "Don't swing your body"))
        return out

    def rep_cues(self, info, ctx):
        if info["up"] is not None and info["up"] < 0.45:
            return [("lower", "Lower the weight slowly")]
        return []


class Press(Exercise):
    key, name = "press", "Shoulder press"
    joints = (L_SH, R_SH, L_EL, R_EL, L_WR, R_WR)
    rest, work, partial = 0.55, 0.88, 0.5     # rack: wrists a forearm above the shoulders
    met = (3.5, "02054", False)
    target = 10
    how = "Hands at shoulder height, press straight up overhead, lower back to your shoulders."
    partial_cue = "Press all the way up"
    muscles = ("shoulders", "triceps", "upper chest")

    def signal(self, b, side=None):
        return _mean(_arm_height(b, "left"), _arm_height(b, "right"))

    def cues(self, b, ctx):
        out = []
        lean = b.trunk_lean()
        if lean is not None and lean > 15:
            out.append(("arch", "Brace your core, don't lean back"))
        l, r = _arm_height(b, "left"), _arm_height(b, "right")
        if l is not None and r is not None and abs(l - r) > 0.18 and ctx["depth"] > 0.5:
            out.append(("even", "Press both arms evenly"))
        return out


class LateralRaise(Exercise):
    key, name = "raise", "Lateral raise"
    joints = (L_SH, R_SH, L_EL, R_EL, L_HIP, R_HIP)
    rest, work, partial = 25.0, 78.0, 0.5
    met = (3.5, "02054", False)
    target = 12
    how = "Arms by your sides, raise them out to shoulder height, lower slowly."
    partial_cue = "Raise to shoulder height"
    muscles = ("shoulders",)

    def signal(self, b, side=None):
        return _mean(b.abduction("left"), b.abduction("right"))

    def cues(self, b, ctx):
        out = []
        a = self.signal(b)
        if a is not None and a > 110:
            out.append(("high", "Stop at shoulder height"))
        l, r = b.abduction("left"), b.abduction("right")
        if l is not None and r is not None and abs(l - r) > 18 and ctx["depth"] > 0.5:
            out.append(("even", "Raise both arms evenly"))
        return out


class SitToStand(Exercise):
    key, name = "chair", "Sit to stand"
    joints = (L_HIP, R_HIP, L_KNEE, R_KNEE)
    rest, work, partial = 0.70, 0.93, 0.6
    met = (3.0, "02056", False)
    target = 10
    how = "Sit on a chair, arms crossed, stand all the way up and sit back down."
    partial_cue = "Stand all the way up"
    muscles = ("quads", "glutes")

    def signal(self, b, side=None):
        """Hip height as a share of this person's standing hip height (learnt, see Tracker)."""
        h = b.hip_height()
        stand = getattr(b, "stand_hip", None)
        return None if h is None or not stand else h / stand


class SquatJump(Exercise):
    key, name = "jump", "Squat jump"
    joints = (L_HIP, R_HIP, L_ANK, R_ANK)
    rest, work, partial = 0.02, 0.08, 0.9
    met = (6.5, "02057", False)
    target = 10
    how = "Squat down, jump as high as you can, land softly with bent knees."
    muscles = ("quads", "glutes", "calves")

    def signal(self, b, side=None):
        """Metres the hips are above their standing height: positive only in the air."""
        h, stand = b.hip_height(), getattr(b, "stand_hip", None)
        return None if h is None or not stand else h - stand


class Punch(Exercise):
    key, name, kind = "punch", "Punches", "sides"
    joints = (L_SH, R_SH, L_EL, R_EL, L_WR, R_WR)
    rest, work, partial = 100.0, 150.0, 0.8
    min_time = 0.15                       # a jab is quick
    met = (7.5, "02020", True)            # no shadow-boxing entry: vigorous calisthenics
    target = 40
    how = "Hands up in a guard, punch straight out towards the TV and snap back."
    muscles = ("shoulders", "core", "chest")

    def signal(self, b, side=None):
        return b.elbow(side)


# -- holds: seconds count only while the form is right

class Hold(Exercise):
    kind = "hold"
    target = 30

    def check(self, b, ctx):
        """(in position?, cue or None)."""
        raise NotImplementedError


class Plank(Hold):
    key, name = "plank", "Plank"
    joints = (L_SH, R_SH, L_HIP, R_HIP, L_ANK, R_ANK)
    met = (2.8, "02024", False)
    how = "Forearms on the floor, body in one straight line from head to heels. Side-on to the TV."
    muscles = ("core", "shoulders")

    def check(self, b, ctx):
        lean, line = b.trunk_lean(), b.body_line()
        if lean is None or line is None or lean < 55:
            return False, "Get into a plank, side-on to the TV"
        sh, hp, an = b.mid(L_SH, R_SH), b.mid(L_HIP, R_HIP), b.mid(L_ANK, R_ANK)
        # Where the hips should be on the shoulder-ankle line, and how far off they are.
        along = np.clip((hp - sh) @ (an - sh) / max(float((an - sh) @ (an - sh)), 1e-6), 0, 1)
        off = float(hp[1] - (sh + along * (an - sh))[1])
        if off < -0.07:
            return False, "Lift your hips a little"
        if off > 0.10:
            return False, "Lower your hips into a straight line"
        return True, None


class WallSit(Hold):
    key, name = "wallsit", "Wall sit"
    joints = (L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK)
    met = (3.8, "02022", True)            # no wall-sit entry: moderate calisthenics
    how = "Back against a wall, slide down until your knees are at a right angle, hold."
    muscles = ("quads", "glutes")

    def check(self, b, ctx):
        k = _mean(b.knee("left"), b.knee("right"))
        if k is None:
            return False, "Face the TV so I can see your knees"
        if k > 120:
            return False, "Slide down to about a right angle"
        if k < 70:
            return False, "Not quite that low"
        return True, None


class Balance(Hold):
    key, name = "balance", "One-leg balance"
    joints = (L_HIP, R_HIP, L_ANK, R_ANK)
    met = (2.3, "02101", True)            # no general balance entry: mild stretching
    how = "Stand on one leg, the other foot off the floor, arms wherever helps. Then swap."
    muscles = ("ankles", "core")

    def check(self, b, ctx):
        la, ra = b.p(L_ANK), b.p(R_ANK)
        if la is None or ra is None:
            return False, "Step back so I can see your feet"
        if abs(float(la[1] - ra[1])) < 0.07:
            return False, "Lift one foot off the floor"
        return True, None


class Reach(Hold):
    key, name = "reach", "Toe-touch reach"
    joints = (L_HIP, R_HIP, L_KNEE, R_KNEE, L_WR, R_WR)
    met = (2.3, "02101", False)
    target = 15
    how = "Legs straight, fold forward and reach your hands down as far as you comfortably can."
    muscles = ("hamstrings", "lower back")

    def check(self, b, ctx):
        lean = b.trunk_lean()
        k = _mean(b.knee("left"), b.knee("right"))
        if lean is None or lean < 45:
            return False, "Fold forward from your hips"
        if k is not None and k < 155:
            return False, "Keep your knees straight"
        return True, None


CATALOG = {e.key: e for e in (Squat(), Lunge(), JumpingJack(), HighKnees(), Curl(), Press(),
                              LateralRaise(), SitToStand(), SquatJump(), Punch(),
                              Plank(), WallSit(), Balance(), Reach())}


# ------------------------------------------------------------------ one person doing one exercise

class Tracker:
    """Counts, times and coaches one exercise for one person. step(body) -> events.

    Events: {"type": "rep" | "partial" | "cue" | "unsure" | "hold", ...}. Joints the camera did not
    see well enough (evidence < EVIDENCE) freeze the count and the coaching, and say so."""

    def __init__(self, exercise, target=None):
        self.ex = exercise if isinstance(exercise, Exercise) else CATALOG[exercise]
        self.target = target or self.ex.target
        self.machines = {s: Machine(self.ex.rest, self.ex.work, self.ex.partial, self.ex.min_time)
                         for s in self.ex.sides()}
        self.reps, self.partials, self.good = 0, 0, 0
        self.per_side = {"left": 0, "right": 0}
        self.history = []                      # one dict per repetition (the set's record)
        self.faults = {s: {} for s in self.ex.sides()}
        self.ctx = {s: {"side": s, "depth": 0.0, "lean0": None} for s in self.ex.sides()}
        self.hold_time, self.hold_best, self.hold_since = 0.0, 0.0, None
        self.sway = deque(maxlen=60)
        self.reach_best = None
        self.last_t = None
        self.unsure = False
        self.stand_hips = deque(maxlen=90)     # standing hip heights: the reference for sit/jump
        self.last_cue = None
        self.peak_value = None
        self.asym = []

    # -- standing reference (sit-to-stand, jumps)

    def _learn_standing(self, b):
        h, k = b.hip_height(), _mean(b.knee("left"), b.knee("right"))
        if h is not None and k is not None and k > 160 and (b.trunk_lean() or 0) < 15:
            self.stand_hips.append(h)
        if self.stand_hips:
            b.stand_hip = float(np.percentile(self.stand_hips, 60))

    def step(self, b):
        t = b.t
        dt = 0.0 if self.last_t is None else min(0.5, t - self.last_t)
        self.last_t = t
        self._learn_standing(b)
        ev = b.evidence(self.ex.joints)
        # Too unsure: a required joint not seen at all, or too many only estimated.
        if ev < EVIDENCE or any(b.states[j] == sk.MISSING for j in self.ex.joints):
            was, self.unsure = self.unsure, True
            if self.ex.kind == "hold":
                self.hold_since = None
            return [] if was else [{"type": "unsure", "evidence": round(ev, 2),
                                    "say": "I can't see you well enough. Step back into view."}]
        self.unsure = False
        if self.ex.kind == "hold":
            return self._hold(b, dt)
        events = []
        for side, m in self.machines.items():
            v = self.ex.signal(b, side)
            ctx = self.ctx[side]
            if v is None:
                continue
            ctx["depth"] = m.depth(v)
            if m.phase == "rest":
                ctx["lean0"] = b.trunk_lean()
                self.faults[side] = {}
            else:
                # Inside a repetition: note each fault, it is said once it shows on a few frames.
                for key, words in self.ex.cues(b, ctx):
                    n = self.faults[side].get(key, (0, words))[0] + 1
                    self.faults[side][key] = (n, words)
                    if n == CUE_FRAMES:
                        events.append({"type": "cue", "key": key, "say": words, "side": side})
            out = m.step(v, t)
            if out is None:
                continue
            kind, info = out
            if kind == "partial":
                self.partials += 1
                events.append({"type": "partial", "side": side, "say": self.ex.partial_cue,
                               "reach": round(info["peak"], 2)})
                continue
            events.append(self._rep(b, side, info))
        return events

    def _rep(self, b, side, info):
        ctx = self.ctx[side]
        faults = [(k, w) for k, (n, w) in self.faults[side].items() if n >= CUE_FRAMES]
        faults += self.ex.rep_cues(info, ctx)
        if side in self.per_side:
            self.per_side[side] += 1
        # Both arms curling together: the second arm joins the first arm's repetition.
        prev = self.history[-1] if self.history else None
        if (self.ex.together and prev and prev["side"] not in (side, "both")
                and info["t1"] - prev["t1"] < 0.6):
            prev["side"] = "both"
            prev["cues"] = sorted(set(prev["cues"]) | {k for k, _ in faults})
            return {**prev, "type": "rep-both"}
        self.reps += 1
        if isinstance(self.ex, Lunge):
            lead = self.ex.lead(b)
            if lead:
                self.per_side[lead] += 1
        score = max(0, 100 - CUE_PENALTY * len(faults))
        if not faults:
            self.good += 1
        rec = {"type": "rep", "n": self.reps, "side": side, "score": score,
               "cues": [k for k, _ in faults], "say": faults[0][1] if faults else None,
               "rom": round(info["peak"], 2),
               "down_s": None if info["down"] is None else round(info["down"], 2),
               "up_s": None if info["up"] is None else round(info["up"], 2),
               "time_s": round(info["t1"] - info["t0"], 2), "t1": info["t1"]}
        if isinstance(self.ex, SquatJump) and getattr(b, "stand_hip", None):
            # Jump height: how far above standing the hips went (peak of the signal, in metres).
            rec["jump_cm"] = round(100 * (self.ex.rest + info["peak"] * (self.ex.work - self.ex.rest)), 1)
        self.history.append(rec)
        return rec

    def _hold(self, b, dt):
        ok, cue = self.ex.check(b, self.ctx[None])
        events = []
        c = b.centre()
        if ok:
            if self.hold_since is None:
                self.hold_since = b.t
                events.append({"type": "hold", "state": "start"})
            self.hold_time += dt
            self.hold_best = max(self.hold_best, b.t - self.hold_since)
            if c is not None:
                self.sway.append(c)
            if isinstance(self.ex, Reach):
                w = [p[1] for p in (b.p(L_WR), b.p(R_WR)) if p is not None]
                if w:
                    self.reach_best = min(w) if self.reach_best is None else min(self.reach_best, min(w))
        else:
            if self.hold_since is not None:
                events.append({"type": "hold", "state": "stop", "held_s": round(b.t - self.hold_since, 1)})
            self.hold_since = None
            if cue and cue != self.last_cue:
                events.append({"type": "cue", "key": "hold", "say": cue})
        self.last_cue = cue
        return events

    # -- what the screen shows

    def sway_cm(self):
        """How much the body moved over the floor while holding (cm, standard deviation)."""
        if len(self.sway) < 10:
            return None
        s = np.array(self.sway)
        return round(100 * float(np.sqrt(s.var(axis=0).sum())), 1)

    def state(self, b=None):
        prog = 0.0
        if b is not None and self.ex.kind != "hold":
            vals = [m.progress(self.ex.signal(b, s)) for s, m in self.machines.items()]
            prog = max(vals) if vals else 0.0
        done = (self.hold_time if self.ex.kind == "hold" else self.reps) >= self.target
        out = {"exercise": self.ex.key, "name": self.ex.name, "kind": self.ex.kind,
               "target": self.target, "reps": self.reps, "good": self.good,
               "partials": self.partials, "progress": round(prog, 2), "unsure": self.unsure,
               "done": done, "sides": dict(self.per_side) if self.ex.kind == "sides" or
               isinstance(self.ex, Lunge) else None}
        if self.ex.kind == "hold":
            out.update(held=round(self.hold_time, 1), best=round(self.hold_best, 1),
                       holding=self.hold_since is not None, sway_cm=self.sway_cm())
            if self.reach_best is not None:
                out["reach_cm"] = round(100 * self.reach_best, 1)
        if self.history:
            out["form"] = round(sum(r["score"] for r in self.history) / len(self.history))
            jumps = [r["jump_cm"] for r in self.history if r.get("jump_cm") is not None]
            if jumps:
                out["jump_best_cm"] = max(jumps)
            tempo = [r["time_s"] for r in self.history]
            out["tempo_s"] = round(sum(tempo) / len(tempo), 2)
        if self.ex.kind == "sides" or isinstance(self.ex, Lunge):
            l, r = self.per_side["left"], self.per_side["right"]
            out["balance"] = None if l + r == 0 else round(abs(l - r) / max(l, r), 2)
        return out

    def summary(self):
        """The set, for the history: what was done, never how it looked."""
        s = self.state()
        s["record"] = self.history
        return s


def describe():
    """The catalog for the page."""
    return [{"key": e.key, "name": e.name, "kind": e.kind, "target": e.target, "how": e.how,
             "met": e.met[0], "met_code": e.met[1], "met_proxy": e.met[2], "muscles": list(e.muscles)}
            for e in CATALOG.values()]
