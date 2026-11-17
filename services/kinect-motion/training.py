"""Training arithmetic: energy estimates, the weight in your hands, volume, what to do next time,
and the workouts. Pure Python.

Calories are an ESTIMATE, never a measurement: kcal/min = MET x 3.5 x body mass (kg) / 200
(ACSM's metabolic equation; 1 MET = 3.5 ml O2/kg/min, ~5 kcal per litre of O2), with MET values
from the 2024 Adult Compendium of Physical Activities. A heart-rate strap or a measured resting
rate would be needed for anything better, and the screen says "about".

The weight of a dumbbell cannot be seen: shape does not give density or what is inside. So a
load is only ever taken from a source that knows it (`resolve_load`), otherwise it is unknown.
Commercial systems do the same: Tempo recognises only its own weights and plates.
"""

LOAD_SOURCES = ("sensor", "confirmed", "catalog", "tag", "label")   # most to least trusted


def kcal(met, kg, seconds):
    """Energy estimate (kcal) for `seconds` of an activity of `met` by a person of `kg`."""
    if not met or not kg or seconds <= 0:
        return None
    return met * 3.5 * kg / 200.0 * seconds / 60.0


def resolve_load(candidates):
    """The weight to record, from candidates [{"source": ..., "kg": ...}], or (None, "unknown").

    sensor     a smart scale / connected dumbbell reported it
    confirmed  the person said or typed it for this set
    catalog    equipment the person registered ("my 5 kg dumbbells") and picked
    tag        an RFID / BLE tag on registered equipment
    label      a printed number the person confirmed
    A camera guess is never a source."""
    best = None
    for c in candidates or []:
        src, kg = c.get("source"), c.get("kg")
        if src not in LOAD_SOURCES or kg is None:
            continue
        try:
            kg = float(kg)
        except (TypeError, ValueError):
            continue
        if not 0 <= kg <= 300:
            continue
        rank = LOAD_SOURCES.index(src)
        if best is None or rank < best[2]:
            best = (kg, src, rank)
    return (best[0], best[1]) if best else (None, "unknown")


def volume(reps, kg, hands=1):
    """Training volume (kg): repetitions x load, for each hand holding one."""
    if kg is None:
        return None
    return round(reps * kg * hands, 1)


def progression(sets, target, kg=None, step_kg=2.5, top_reps=15):
    """What to do next time (double progression), from this exercise's last sets.

    Every set reached the target with good form (score >= 80): add repetitions, or once the reps
    are high, add load. Form under 70: keep the load and clean the movement up. Not enough
    sets: say nothing."""
    if not sets:
        return None
    reached = all(s.get("reps", 0) >= target for s in sets)
    forms = [s["form"] for s in sets if s.get("form") is not None]
    form = sum(forms) / len(forms) if forms else None
    if form is not None and form < 70:
        return {"action": "form", "say": "Same again, slower and cleaner: form first."}
    if not reached:
        return {"action": "repeat", "say": f"Aim for {target} again next time."}
    if kg is not None and target >= top_reps - 3:
        return {"action": "load", "kg": round(kg + step_kg, 1), "target": max(8, target - 4),
                "say": f"Ready for {round(kg + step_kg, 1)} kg next time."}
    return {"action": "reps", "target": target + 2, "say": f"Try {target + 2} next time."}


# Workouts: steps of (exercise, target reps or seconds), with rest in between.
PLANS = {
    "quick": {"name": "Quick start", "rest": 20,
              "steps": [("squat", 10), ("jack", 20), ("curl", 10), ("knees", 30), ("plank", 20)]},
    "strength": {"name": "Strength", "rest": 45,
                 "steps": [("squat", 12), ("lunge", 10), ("press", 10), ("curl", 12), ("raise", 12),
                           ("squat", 12), ("wallsit", 30)]},
    "cardio": {"name": "Cardio burst", "rest": 15,
               "steps": [("jack", 30), ("knees", 40), ("punch", 40), ("jump", 10), ("jack", 30),
                         ("punch", 40)]},
    "mobility": {"name": "Balance and mobility", "rest": 15,
                 "steps": [("balance", 20), ("balance", 20), ("reach", 15), ("chair", 8),
                           ("raise", 10), ("wallsit", 20)]},
}

# The fitness check (after Nike+ Kinect Training's assessment idea: a baseline, retaken every
# four weeks and compared with your own last one; no population norms are claimed).
ASSESSMENT = {"name": "Fitness check", "rest": 30, "timed": True,
              "steps": [("chair", 30, "Sit-to-stands in 30 seconds"),
                        ("jack", 30, "Jumping jacks in 30 seconds"),
                        ("balance", 30, "One-leg balance: seconds held, and how still"),
                        ("reach", 15, "Toe-touch reach: how close to the floor"),
                        ("jump", 20, "Squat jumps: best jump height")]}
RETEST_DAYS = 28


def plan(key):
    """A workout or the fitness check as a list of steps: {exercise, target, seconds?}."""
    if key == "check":
        return {"name": ASSESSMENT["name"], "rest": ASSESSMENT["rest"],
                "steps": [{"exercise": e, "target": None, "seconds": s, "label": label}
                          for e, s, label in ASSESSMENT["steps"]]}
    p = PLANS[key]
    return {"name": p["name"], "rest": p["rest"],
            "steps": [{"exercise": e, "target": n, "seconds": None, "label": None} for e, n in p["steps"]]}


def check_score(step, summary):
    """The number a fitness-check step records (higher is better unless noted)."""
    ex = step["exercise"]
    if ex == "balance":
        return {"held_s": summary.get("held"), "sway_cm": summary.get("sway_cm")}
    if ex == "reach":
        return {"reach_cm": summary.get("reach_cm")}           # lower is better: closer to the floor
    if ex == "jump":
        return {"jump_cm": summary.get("jump_best_cm"), "reps": summary.get("reps")}
    return {"reps": summary.get("reps")}


def compare(now, before):
    """Each fitness-check number against your previous check: better / same / worse."""
    out = {}
    for ex, vals in now.items():
        old = before.get(ex) or {}
        for k, v in (vals or {}).items():
            o = old.get(k)
            if v is None or o is None:
                continue
            lower_better = k in ("reach_cm", "sway_cm")
            diff = (o - v) if lower_better else (v - o)
            tol = 0.05 * max(abs(o), 1)
            out[f"{ex}.{k}"] = "better" if diff > tol else "worse" if diff < -tol else "same"
    return out
