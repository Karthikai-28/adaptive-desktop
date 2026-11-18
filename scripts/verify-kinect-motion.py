#!/usr/bin/env python3
"""Check Kinect Motion (services/kinect-motion): exercises, gestures, players, training maths,
history, room events, the pad's outputs, the depth-fused joints, and the server.

No Kinect and no person needed: synthetic people built from joint angles (synthetic.py), so
every check knows the true answer. Runs in seconds; part of scripts/verify-all.sh --quick.
"""

import asyncio
import importlib.util
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
MOTION = REPO / "services/kinect-motion"
sys.path.insert(0, str(MOTION))
sys.path.insert(1, str(REPO / "services/adaptive-air"))     # people.py, measure.py, fusion.py

import bodygestures  # noqa: E402
import calibration  # noqa: E402
import engine  # noqa: E402
import games  # noqa: E402
import exercises as ex  # noqa: E402
import pad  # noqa: E402
import players  # noqa: E402
import room  # noqa: E402
import skeleton as sk  # noqa: E402
import store  # noqa: E402
import sim as sy  # noqa: E402
import training  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILED.append(name)


def run(move, key, seconds, drop=0.0, **kw):
    """A tracker fed a synthetic session; drop = share of frames lost at random."""
    tr = ex.Tracker(key)
    rng = np.random.default_rng(5)
    events = []
    for b in sy.session(move, seconds, **kw):
        if drop and rng.random() < drop:
            continue
        events += tr.step(b)
    return tr, events


def check_skeleton():
    print("Body geometry (skeleton.py)")
    b = sy.body(sy.figure(knee=90), 0, noise=0)
    check("a 90 deg knee measures 90 deg", abs(b.knee("left") - 90) < 0.5, b.knee("left"))
    b = sy.body(sy.figure(elbow=(60, 60)), 0, noise=0)
    check("a 60 deg elbow measures 60 deg, arm hanging", abs(b.elbow("right") - 60) < 0.5 and b.arm_drift("left") < 15)
    b = sy.body(sy.figure(lean=30), 0, noise=0)
    check("a 30 deg forward lean measures 30 deg", abs(b.trunk_lean() - 30) < 1, b.trunk_lean())
    b = sy.body(sy.figure(abduct=(90, 90)), 0, noise=0)
    check("arms straight out: abduction 90 deg", abs(b.abduction("left") - 90) < 3, b.abduction("left"))
    hidden = sy.body(sy.figure(), 0, hide=(sk.L_KNEE, sk.R_KNEE))
    check("hidden knees: a squat is not coached", ex.Tracker("squat").step(hidden)[0]["type"] == "unsure")
    f = sk.Filter()
    rng = np.random.default_rng(1)
    raw, smooth = [], []
    for i in range(60):
        b = sy.body(sy.figure(), i / 15, noise=0.02, rng=rng)
        raw.append(b.joints[sk.L_WR].copy())
        smooth.append(f(b).joints[sk.L_WR].copy())
    check("One Euro smoothing halves the jitter of a still wrist",
          np.std(np.array(smooth[20:]), axis=0).sum() < 0.5 * np.std(np.array(raw[20:]), axis=0).sum())
    f = sk.Filter()
    for i in range(20):
        f(sy.body(sy.figure(), i / 15, noise=0.003))
    bad = sy.body(sy.figure(), 2.0, noise=0.003)
    bad.joints[sk.L_KNEE] += np.array([0, 0, 0.6])          # a depth pixel on the sofa behind
    bad.states[sk.L_KNEE] = sk.TRACKED
    check("a knee 60 cm off its learnt bone length is demoted to inferred",
          f(bad).states[sk.L_KNEE] == sk.INFERRED)


def check_exercises():
    print("Exercises: counting, form, evidence (exercises.py)")
    cases = [("squat", "squat", 2.4, 5), ("jack", "jack", 1.0, 10), ("curl", "curl", 2.2, 4),
             ("press", "press", 2.0, 5), ("raise", "raise", 2.2, 4), ("chair", "chair", 3.0, 4)]
    for move, key, period, n in cases:
        tr, _ = run(move, key, period * n + 0.5)
        check(f"{key}: {n} repetitions counted exactly", tr.reps == n, tr.state())
    tr, _ = run("curl", "curl", 2.2 * 4 + 0.5)
    check("curl with both arms: 4 repetitions, each arm credited 4", tr.state()["sides"] == {"left": 4, "right": 4})
    tr, ev = run("shallow", "squat", 8.5)
    check("half squats are partials, not repetitions, with 'Go a little deeper'",
          tr.reps == 0 and tr.partials == 4 and any(e.get("say") == "Go a little deeper" for e in ev))
    tr, ev = run("squat-lean", "squat", 7.7)
    check("squatting bent over: counted, and told 'Keep your chest up'",
          tr.reps == 3 and all("chest" in r["cues"] for r in tr.history))
    tr, _ = run("curl-swing", "curl", 6.9)
    check("swinging curls: 'Don't swing your body' on every repetition",
          tr.reps == 3 and all("swing" in r["cues"] for r in tr.history))
    tr, _ = run("squat", "squat", 12.5)
    check("clean squats score 100", tr.good == 5 and tr.state()["form"] == 100, tr.state())
    tr, _ = run("squat", "squat", 12.5, noise=0.03)
    check("3 cm of sensor noise on every joint: still exactly 5", tr.reps == 5, tr.reps)
    tr, _ = run("squat", "squat", 12.5, drop=0.25)
    check("a quarter of the frames lost: still exactly 5", tr.reps == 5, tr.reps)
    tr, ev = run("squat", "squat", 12.5, hide=(sk.L_KNEE, sk.R_KNEE, sk.L_ANK))
    check("knees out of view: nothing counted or coached, and it says why",
          tr.reps == 0 and ev and ev[0]["type"] == "unsure" and len([e for e in ev if e["type"] == "unsure"]) == 1)
    # High knees: left and right alternately.
    tr = ex.Tracker("knees")
    for i in range(int(8 * 15)):
        t = i / 15
        k = sy.wave(t, 1.0)
        left = 80 * k if int(t) % 2 == 0 else 0
        right = 80 * k if int(t) % 2 == 1 else 0
        tr.step(sy.body(sy.figure(thigh=(left, right)), t))
    check("high knees: each knee counted on its own", tr.state()["sides"] == {"left": 4, "right": 4}, tr.state()["sides"])
    # Squat jumps: the jump height comes out in centimetres.
    tr = ex.Tracker("jump")
    for i in range(int(2 * 15)):                          # stand still first: the reference
        tr.step(sy.body(sy.figure(), i / 15, noise=0.002))
    for i in range(int(6 * 15)):
        t = 2 + i / 15
        lift = max(0.0, 0.25 * math.sin(math.pi * ((t - 2) % 1.5) / 0.6)) if (t - 2) % 1.5 < 0.6 else 0.0
        tr.step(sy.body(sy.figure(lift=lift), t, noise=0.002))
    s = tr.state()
    check("squat jumps: 4 jumps, best height ~25 cm", s["reps"] == 4 and abs(s.get("jump_best_cm", 0) - 25) < 3, s)
    # Holds.
    tr = ex.Tracker("balance")
    for i in range(int(6 * 15)):
        t = i / 15
        J = sy.figure()
        J[sk.R_ANK] += np.array([0, 0.15, 0])
        tr.step(sy.body(J, t, noise=0.004))
    s = tr.state()
    check("one-leg balance: the seconds held, and the sway in cm", 5.5 < s["held"] < 6.1 and s["sway_cm"] is not None and s["sway_cm"] < 2, s)
    tr = ex.Tracker("plank")
    for i in range(int(5 * 15)):
        J = sy.figure()
        J = (J - J[sk.L_ANK]) @ np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]).T + np.array([0, 0.15, 2.8])
        tr.step(sy.body(J, i / 15, noise=0.004))
    check("plank: a straight body held side-on counts its seconds", tr.state()["held"] > 4.5, tr.state())
    tr = ex.Tracker("plank")
    for i in range(30):
        tr.step(sy.body(sy.figure(), i / 15))
    check("standing is not a plank: no seconds, and a cue", tr.state()["held"] == 0)
    check("every exercise has a Compendium MET and a how-to",
          all(e["met"] > 0 and e["met_code"] and e["how"] for e in ex.describe()) and len(ex.describe()) == 14)


def check_gestures():
    print("Whole-body gestures (bodygestures.py)")

    def feed(frames, busy=False):
        g, out = bodygestures.Gestures(), []
        for i, J in enumerate(frames):
            out += g.step(sy.body(J, i / 15, noise=0.003), busy)
        return [e["gesture"] for e in out], g

    up = sy.figure(abduct=(10, 175))                       # right arm straight up (person's right)
    names, _ = feed([up] * 15)
    check("right hand up for a moment: raise_right, once", names.count("raise_right") == 1 and "raise_left" not in names, names)
    names, _ = feed([up] * 6)
    check("a hand up for less than the hold: nothing", "raise_right" not in names, names)
    names, _ = feed([sy.figure(abduct=(175, 175))] * 20)
    check("both hands up held: hands_up (pause)", "hands_up" in names, names)
    names, _ = feed([sy.figure(abduct=(175, 175))] * 20, busy=True)
    check("mid-exercise, the same raise is too short to pause (a press is not a pause)", "hands_up" not in names, names)
    names, _ = feed([sy.figure(abduct=(90, 90))] * 25)
    check("T-pose held: t_pose", "t_pose" in names, names)
    frames = [sy.figure(abduct=(90, 90), elbow=(170, 170))] * 4 + [sy.figure(abduct=(30, 30), arm_forward=(70, 70), elbow=(175, 175))] * 4
    hands = []
    for J in frames:
        J = J.copy()
        hands.append(J)
    g, events = bodygestures.Gestures(), []
    for i, J in enumerate(hands):
        events += g.step(sy.body(J, i / 15, noise=0.0))
    # A clap by moving the wrists together directly.
    g, events = bodygestures.Gestures(), []
    for i in range(10):
        J = sy.figure(abduct=(30, 30), arm_forward=(70, 70))
        gap = 0.6 if i < 5 else 0.06
        J[sk.L_WR] = np.array([gap / 2, 1.3, 2.3])
        J[sk.R_WR] = np.array([-gap / 2, 1.3, 2.3])
        events += g.step(sy.body(J, i / 15, noise=0.0))
    check("hands brought together fast: clap", any(e["gesture"] == "clap" for e in events))
    # Swipe: the left wrist travels 50 cm across at chest height in a third of a second.
    g, events = bodygestures.Gestures(), []
    for i in range(8):
        J = sy.figure(abduct=(60, 10), arm_forward=(60, 0))
        J[sk.L_WR] = J[sk.L_SH] + np.array([-0.25 + 0.5 * min(1, i / 5), 0.0, -0.35])
        events += g.step(sy.body(J, i / 15, noise=0.0))
    check("a hand swept across fast: a swipe to the person's left", [e["gesture"] for e in events].count("swipe_left") == 1,
          [e["gesture"] for e in events])
    # Pointing: a straight arm down-forward points at the floor in front.
    J = sy.figure(abduct=(10, 10), arm_forward=(0, 55), elbow=(175, 178))
    b = sy.body(J, 0, noise=0)
    ray = bodygestures.pointing_ray(b, "right")
    check("a straight arm pointing down-forward hits the floor ahead of the person",
          ray and ray["at"] == "floor" and ray["point"][1] < 2.8, ray)
    check("an arm hanging down does not point", bodygestures.pointing_ray(sy.body(sy.figure(), 0, noise=0), "left") is None)
    # The steering wheel: hands level -> 0; right hand lower (turning right) -> positive.
    level = sy.figure(abduct=(30, 30), arm_forward=(70, 70), elbow=(150, 150))
    w0 = bodygestures.steering(sy.body(level, 0, noise=0))
    turned = level.copy()
    turned[sk.R_WR] += np.array([0, -0.15, 0])
    turned[sk.L_WR] += np.array([0, 0.15, 0])
    w1 = bodygestures.steering(sy.body(turned, 0, noise=0))
    check("steering: level hands 0, right hand dropped = turning right (positive)",
          abs(w0["wheel"]) < 0.05 and w1["wheel"] > 0.3, (w0, w1))
    check("steering: hands pushed out = throttle", w0["throttle"] > 0.3 and w0["brake"] == 0, w0)
    rest = bodygestures.steering(sy.body(sy.figure(), 0, noise=0))
    check("steering: hands down by your sides = brake, no throttle", rest["brake"] == 1 and rest["throttle"] == 0, rest)


def check_players():
    print("Players: joining, identity, safety (players.py)")
    r = players.Roster()
    a = sy.body(sy.figure(x=-0.6, z=2.8), 0.0, pid=1, height_cm=180)
    ev = r.update([a], 0.0)
    check("alone: you are player 1 without doing anything", len(r.players) == 1 and ev[0]["type"] == "joined")
    b = sy.body(sy.figure(x=0.7, z=3.0), 1.0, pid=2, height_cm=160)
    r.update([a, b], 1.0)
    check("a second person does not join by just being there", len(r.players) == 1)
    r.join(b, 1.0)
    check("joining gives the next slot", sorted(p.slot for p in r.players) == [0, 1])
    r.update([b], 2.0)                                     # player 1 steps out
    back = sy.body(sy.figure(x=-0.5, z=2.9), 6.0, pid=7, height_cm=181)
    ev = r.update([back, b], 6.0)
    check("stepping out and back (new hub number, same place and height): same player",
          any(e["type"] == "rejoined" and e["slot"] == 0 for e in ev) and r.by_track(7).slot == 0, ev)
    other = sy.body(sy.figure(x=-0.5, z=2.9), 7.0, pid=8, height_cm=150)
    r.update([back, b], 7.0)
    r2 = players.Roster()
    r2.join(a, 0.0)
    r2.update([], 1.0)
    ev = r2.update([other], 3.0)
    check("someone 30 cm shorter in the same place is not taken for the player who left",
          not any(e["type"] == "rejoined" for e in ev))
    r3 = players.Roster()
    p1 = sy.body(sy.figure(x=0.0, z=2.8), 0, pid=1)
    p2 = sy.body(sy.figure(x=0.5, z=2.9), 0, pid=2)
    r3.join(p1, 0)
    r3.join(p2, 0)
    ev = r3.update([p1, p2], 0.1)
    check("two players half a metre apart: told to spread out",
          sum(1 for e in ev if e["type"] == "safety" and e["warning"] and "spread out" in e["warning"]) == 2, ev)
    check("1 m from the TV is too close; 2.8 m in the middle is fine; 2 m to the side is out of view",
          not players.in_zone((0, 1.0))[0] and players.in_zone((0, 2.8))[0] and not players.in_zone((2.0, 2.8))[0])


def check_training():
    print("Training maths and history (training.py, store.py)")
    check("calories: 8 MET, 73 kg, a minute = 10.2 kcal (ACSM's equation)", abs(training.kcal(8, 73, 60) - 10.22) < 0.01)
    check("no body weight: no calorie number at all", training.kcal(5, None, 60) is None)
    check("the weight comes from the most trusted source given",
          training.resolve_load([{"source": "label", "kg": 4}, {"source": "confirmed", "kg": 5},
                                 {"source": "catalog", "kg": 6}]) == (5.0, "confirmed"))
    check("a camera guess is never a weight", training.resolve_load([{"source": "vision", "kg": 7}]) == (None, "unknown"))
    check("volume: 12 reps x 5 kg x 2 hands = 120 kg", training.volume(12, 5, 2) == 120)
    check("progression: all sets done well -> more reps",
          training.progression([{"reps": 10, "form": 90}], 10)["action"] == "reps")
    check("progression: high reps with a weight -> heavier",
          training.progression([{"reps": 12, "form": 90}], 12, kg=5)["kg"] == 7.5)
    check("progression: poor form -> clean it up first",
          training.progression([{"reps": 12, "form": 55}], 12)["action"] == "form")
    check("fitness check comparison: more reps better, a lower reach better",
          training.compare({"chair": {"reps": 14}, "reach": {"reach_cm": 8}},
                           {"chair": {"reps": 11}, "reach": {"reach_cm": 15}}) == {"chair.reps": "better", "reach.reach_cm": "better"})
    for key in training.PLANS:
        p = training.plan(key)
        check(f"workout '{p['name']}' uses only known exercises", all(s["exercise"] in ex.CATALOG for s in p["steps"]))
    s = store.Store(":memory:")
    uid = s.add_user("Asha", kg=60)
    sid = s.start_session(uid, "free")
    s.add_set(sid, {"exercise": "squat", "reps": 10, "good": 9, "partials": 1, "form": 92}, 5, "catalog", 100, 3.2, 40)
    s.end_session(sid)
    t = s.totals(uid)
    check("history keeps sets and totals them", t["reps"] == 10 and t["volume"] == 100 and t["streak"] == 1, t)
    check("the last sets of an exercise come back for progression", len(s.last_sets(uid, "squat")) == 1)
    s.delete_user(uid)
    check("forgetting a person removes all their results",
          s.db.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 0)


def hub_frame(people, t):
    return {"captured": t - 0.05, "people": [
        {"id": pid, "colour": 0, "posture": posture, "height_cm": h,
         "joints": [[*map(float, j), 2] for j in J]} for pid, J, h, posture in people]}


def check_engine():
    print("The engine: players, workouts, history, room (engine.py, room.py)")
    st = store.Store(":memory:")
    uid = st.add_user("Karthi", kg=72)
    e = engine.Engine(store=st)
    said = []
    for i in range(10):
        _, s = e.step(hub_frame([(1, sy.figure(x=-0.6), 175, "standing")], 100 + i / 15), now=100 + i / 15)
        said += s
    for i in range(20):
        t = 101 + i / 15
        _, s = e.step(hub_frame([(1, sy.figure(x=-0.6), 175, "standing"),
                                 (2, sy.figure(x=0.7, z=3.0, abduct=(10, 175)), 162, "standing")], t), now=t)
        said += s
    check("player 1 by being alone, player 2 by raising a hand", [p.slot for p in e.roster.players] == [0, 1])
    e.workout.users = {0: uid}
    e.workout.start("challenge", t, exercise="squat", seconds=20)
    T, events = t, []
    for i in range(int(25 * 15)):
        t = T + i / 15
        ev, s = e.step(hub_frame([(1, sy.move("squat", i / 15, x=-0.6), 175, "standing"),
                                  (2, sy.move("jack", i / 15, x=0.7, z=3.0), 162, "standing")], t), now=t)
        events += ev
        said += s
    sets = [x for x in events if x["type"] == "set"]
    # The squatter is half way down when "Go!" is said: that one is a false start (its first half
    # was before Go, and a repetition is only counted from rest), so 7 of the 8 under way count.
    check("a 20 s squat race: 7 squats for the squatter (not the one begun before Go), nothing for "
          "the one doing jacks", [(x["slot"], x["reps"]) for x in sets] == [(0, 7)], sets)
    check("the named player's set is saved with a calorie estimate; the guest's is not",
          st.totals(uid)["reps"] == 7 and sets[0]["kcal"] and len(st.history(uid)) == 1)
    check("it says who joined, go, and done", "Player 2, you're in." in said and "Go! Squat." in said
          and "Workout done. Well done!" in said, said)
    lat = e.latency_ms()
    check("latency from camera to engine is measured (50 ms here)", lat and lat["p50"] == 50, lat)
    # Pause by both hands up, resume the same way.
    e2 = engine.Engine()
    e2.step(hub_frame([(1, sy.figure(), 175, "standing")], 0), now=0)
    e2.workout.start("free", 0, exercise="squat")
    paused = False
    for i in range(40):
        ev, _ = e2.step(hub_frame([(1, sy.figure(abduct=(175, 175)), 175, "standing")], 1 + i / 15), now=1 + i / 15)
        paused |= any(x["type"] == "paused" for x in ev)
    check("both hands up held: the workout pauses", paused and e2.workout.paused_at is not None)
    # Room events.
    rm = room.Room({"zones": [{"name": "sofa", "on": "floor", "x": [-1, 1], "z": [3.2, 4.0]},
                              {"name": "tv", "on": "wall", "x": [-0.6, 0.6], "y": [0.5, 1.5]}],
                    "sit_minutes": 0.01})
    b = sy.body(sy.figure(z=3.5), 0, pid=4)
    b.posture = "sitting"
    ev = rm.step([b], {}, 0)
    names = [x["event"] for x in ev]
    check("someone arrives on the sofa: room_occupied, person_enter_zone sofa",
          "room_occupied" in names and {"event": "person_enter_zone", "zone": "sofa", "person": 4} in ev, ev)
    ev = rm.step([b], {4: [{"gesture": "point", "at": "wall", "point": [0.1, 1.0]}]}, 1.0)
    check("sitting a while: sit_reminder; pointing at the TV: point_at_zone tv",
          any(x["event"] == "sit_reminder" for x in ev) and any(x.get("zone") == "tv" for x in ev), ev)
    ev = rm.step([], {}, 2.0)
    check("everyone leaves: room_empty and person_leave_zone",
          {x["event"] for x in ev} == {"room_empty", "person_leave_zone"}, ev)
    cov = rm.coverage()
    check("the coverage map has the cell where they sat", cov["samples"] == 2 and any(v is not None for row in cov["grid"] for v in row))


def frame_of(people, captured, frame=None, hidden=(), retired=(), identity=None):
    """A hub state: people = [(id, joints, height_cm)], captured = when the frame was taken."""
    st = {"captured": captured, "frame": frame, "people": [
        {"id": pid, "colour": 0, "posture": "standing", "height_cm": h,
         "identity": (identity or {}).get(pid, "sure"),
         "joints": [[*map(float, j), 2] for j in J]} for pid, J, h in people],
        "hidden": [{"id": i, "seen_ago": 0.2, "remembered": True} for i in hidden],
        "retired": [{"id": i, "why": "unsure"} for i in retired]}
    return st


def check_freshness():
    print("Freshness: stale and repeated frames, tracking loss, the watchdog (engine.py)")
    # A set of squats where every frame arrives a second late: nothing may count.
    e = engine.Engine()
    e.step(frame_of([(1, sy.figure(), 175)], 0.0, 1), now=0.0)
    e.workout.start("free", 0.0, exercise="squat")
    for i in range(int(16 * 15)):
        t = 0.0 + i / 15
        e.step(frame_of([(1, sy.move("squat", i / 15), 175)], t - 1.0, 2 + i), now=t)
    tr = e.workout.trackers.get(0)
    check("frames that arrive a second late: zero repetitions",
          (tr is None or tr.reps == 0) and e.dropped["late"] > 200, (tr and tr.reps, e.dropped))
    # The same frame number again and again (a hub that repeats itself): counted once at most.
    e = engine.Engine()
    e.step(frame_of([(1, sy.figure(), 175)], 0.0, 1), now=0.0)
    e.workout.start("free", 0.0, exercise="squat")
    k = 0
    for i in range(int(4 * 15)):                      # 4 s of real squatting first
        t = i / 15
        k += 1
        e.step(frame_of([(1, sy.move("squat", t), 175)], t, k), now=t)
    before = e.workout.trackers[0].reps
    bottom, top = sy.move("squat", 1.2), sy.figure(knee=178)
    for j in range(60):                              # then two frames repeated, alternating
        t = 4 + j / 15
        J, n = (bottom, k + 1) if j % 2 else (top, k + 2)
        e.step(frame_of([(1, J, 175)], t, n), now=t)
    check("repeated frames are dropped: no repetitions from replays",
          e.workout.trackers[0].reps - before <= 1 and e.dropped["repeated"] >= 25,
          (before, e.workout.trackers[0].reps, e.dropped))

    # The camera stops mid-repetition and comes back at the bottom: that repetition is dropped.
    e = engine.Engine()
    e.step(frame_of([(1, sy.figure(), 175)], 0.0, 1), now=0.0)
    e.workout.start("free", 0.0, exercise="squat")
    n, t = 1, 0.0
    for i in range(int(2 * 2.4 * 15)):                # two clean squats
        t = 3.1 + i / 15
        n += 1
        e.step(frame_of([(1, sy.move("squat", i / 15), 175)], t, n), now=t)
    reps2 = e.workout.trackers[0].reps
    for i in range(int(0.5 * 15)):                    # half way down the third
        t += 1 / 15
        n += 1
        e.step(frame_of([(1, sy.move("squat", i / 15), 175)], t, n), now=t)
    lost_events = []
    for j in range(30):                               # one second with no frames at all
        t += 1 / 30
        lost_events += e.tick(t)
    check("no frames for a second: the player is lost (the watchdog, not a frame, says so)",
          any(x["type"] == "tracking" and x["lost"] for x in lost_events) and e.lost.get(0), lost_events)
    for i in range(int(0.7 * 15)):                    # back, already at the bottom, standing up
        t += 1 / 15
        n += 1
        e.step(frame_of([(1, sy.move("squat", 1.2 + i / 15), 175)], t, n), now=t)
    check("... the interrupted repetition is not counted when they stand up",
          e.workout.trackers[0].reps == reps2, (reps2, e.workout.trackers[0].reps))
    for i in range(int(2.4 * 2 * 15)):
        t += 1 / 15
        n += 1
        e.step(frame_of([(1, sy.move("squat", i / 15), 175)], t, n), now=t)
    check("... and the next ones are", e.workout.trackers[0].reps == reps2 + 2, e.workout.trackers[0].reps)

    # A timed challenge waits while nobody is seen.
    e = engine.Engine()
    e.step(frame_of([(1, sy.figure(), 175)], 0.0, 1), now=0.0)
    e.workout.start("challenge", 0.0, exercise="squat", seconds=20)
    t, n = 0.0, 1
    for i in range(int(5 * 15)):
        t = i / 15
        n += 1
        e.step(frame_of([(1, sy.figure(), 175)], t, n), now=t)
    left0 = e.workout.state(e.roster, {}, t)["left"]
    for j in range(150):                              # 5 s of nothing
        t += 1 / 30
        e.tick(t)
    w = e.workout.state(e.roster, {}, t)
    check("a timed challenge pauses while nobody is seen", w["paused"] and w["held_by"] == "tracking"
          and abs(w["left"] - left0) < 0.2, (left0, w))
    for i in range(5):
        t += 1 / 15
        n += 1
        e.step(frame_of([(1, sy.figure(), 175)], t, n), now=t)
    check("... and goes on by itself when they are back", not e.workout.state(e.roster, {}, t)["paused"])

    # The pad lets go when frames stop, without waiting for a frame to say so.
    e = engine.Engine()
    e.pad_profile = "wheel"
    wheel = sy.figure(abduct=(30, 30), arm_forward=(70, 70), elbow=(150, 150))
    e.step(frame_of([(1, wheel, 175)], 0.0, 1), now=0.0)
    held = e.pad_outputs()["axes"]["throttle"]
    e.tick(0.6)
    out = e.pad_outputs()
    check("Kinect Pad: throttle held while seen, released when frames stop",
          held > 0.3 and out["axes"]["throttle"] == 0 and out["keys"] == {}, (held, out))


def check_roster_identity():
    print("Players: hidden, unsure, retired, look-alikes (players.py with the hub's identity)")
    e = engine.Engine()
    e.step(frame_of([(1, sy.figure(x=-0.6), 180)], 0.0, 1), now=0.0)
    e.workout.start("free", 0.0, exercise="squat")
    t, n = 0.0, 1
    for i in range(int(3.2 * 15)):
        t = i / 15
        n += 1
        e.step(frame_of([(1, sy.figure(x=-0.6), 180)], t, n), now=t)
    # Hidden behind someone for two seconds while "squatting" (not seen: nothing counts).
    for i in range(30):
        t += 1 / 15
        n += 1
        e.step(frame_of([(2, sy.move("squat", i / 15, x=0.6), 165)], t, n, hidden=(1,)), now=t)
    p = e.roster.by_slot(0)
    check("hidden behind someone: status hidden, nothing counted", p.status == "hidden" and
          e.workout.trackers.get(0) is None or e.workout.trackers[0].reps == 0, p.status)
    e.step(frame_of([(1, sy.figure(x=-0.6), 180)], t + 0.1, n + 1), now=t + 0.1)
    check("... back under the same number: active again", e.roster.by_slot(0).status == "active")
    # The hub is unsure who is who (a crossing): the player is unsure; nothing counts.
    e.step(frame_of([(1, sy.figure(x=-0.6), 180)], t + 0.2, n + 2, identity={1: "unsure"}), now=t + 0.2)
    check("mid-crossing (hub unsure): the player is unsure, not counted",
          e.roster.by_slot(0).status == "unsure" and 1 not in e.active_bodies())
    # The hub retired the number: the player waits to rejoin, nobody is matched automatically.
    e.step(frame_of([(9, sy.figure(x=-0.6), 180)], t + 0.3, n + 3, retired=(1,)), now=t + 0.3)
    p = e.roster.by_slot(0)
    check("number retired by the hub: 'raise a hand' (rejoin), not matched to whoever is there",
          p.status == "rejoin" and p.track == 1, (p.status, p.track))
    tt = t + 0.3
    for i in range(20):
        tt += 1 / 15
        e.step(frame_of([(9, sy.figure(x=-0.6, abduct=(10, 175)), 180)], tt, n + 4 + i), now=tt)
    p = e.roster.by_slot(0)
    check("... a raised hand makes them player 1 again", p.status == "active" and p.track == 9, (p.status, p.track))

    # Two players leave; one person comes back between where both stood, as tall as both.
    r = players.Roster(auto_solo=False)
    a = sy.body(sy.figure(x=-0.3, z=2.8), 0.0, pid=1, height_cm=175)
    b = sy.body(sy.figure(x=0.3, z=2.8), 0.0, pid=2, height_cm=176)
    r.join(a, 0.0)
    r.join(b, 0.0)
    for i in range(10):
        r.update([sy.body(sy.figure(x=-0.3, z=2.8), i / 15, pid=1, height_cm=175),
                  sy.body(sy.figure(x=0.3, z=2.8), i / 15, pid=2, height_cm=176)], i / 15)
    r.update([], 1.0)
    ev = r.update([sy.body(sy.figure(x=0.0, z=2.8), 2.0, pid=5, height_cm=175)], 2.0)
    check("two look-alike players could be the one who came back: nobody is assumed",
          not any(x["type"] == "rejoined" for x in ev) and any(p.status == "rejoin" for p in r.players), ev)
    # Clearly one of them: back automatically.
    r = players.Roster(auto_solo=False)
    r.join(a, 0.0)
    for i in range(10):
        r.update([sy.body(sy.figure(x=-0.3, z=2.8), i / 15, pid=1, height_cm=175)], i / 15)
    r.update([], 1.0)
    ev = r.update([sy.body(sy.figure(x=-0.25, z=2.85), 3.0, pid=6, height_cm=175)], 3.0)
    check("... one clear candidate is matched back", any(x["type"] == "rejoined" for x in ev), ev)
    # Players keep their slots when they swap places (no left-to-right numbering).
    e = engine.Engine()
    e.step(frame_of([(1, sy.figure(x=-0.8), 180), (2, sy.figure(x=0.8), 160)], 0.0, 1), now=0.0)
    e.join_everyone(0.0)
    slots = {p.track: p.slot for p in e.roster.players}
    for i in range(60):
        f = i / 59
        t = 0.1 + i / 15
        e.step(frame_of([(1, sy.figure(x=-0.8 + 1.6 * f), 180), (2, sy.figure(x=0.8 - 1.6 * f), 160)], t, 2 + i), now=t)
    check("two players swap sides: each keeps their slot", {p.track: p.slot for p in e.roster.players} == slots)


def lean(J, metres):
    """The upper body shifted sideways: + = towards the person's right (the picture's left)."""
    J = J.copy()
    for i in list(range(0, 23)):
        J[i] = J[i] + np.array([-metres, 0, 0])
    return J


def check_games():
    print("Games: the same evidence rules, no penalty for tracking loss (games.py)")
    check("leaning to your right is +, to your left is - (the person's own sides)",
          bodygestures.lean_of(sy.body(lean(sy.figure(), 0.25), 0, noise=0)) > 0.5 and
          bodygestures.lean_of(sy.body(lean(sy.figure(), -0.25), 0, noise=0)) < -0.5)

    def play(kind, pose_at, seconds=8.0, status_at=None, hide=()):
        g = games.WallDodge([0], 0.0, seed=1)
        g.KINDS = {kind: kind.upper()}
        events, t = [], 0.0
        for i in range(int(seconds * 30)):
            t = i / 30
            st = status_at(t) if status_at else "active"
            if st == "active" and i % 2 == 0:
                g.frame(0, sy.body(pose_at(t), t, noise=0.003, hide=hide), t)
            events += g.tick(t, {0: st})
        return g, [x["event"] for x in events]

    stand = lambda t: sy.figure()                                           # noqa: E731
    g, ev = play("up", lambda t: sy.figure(abduct=(175, 175)))
    check("Wall Dodge: arms up through an ARMS UP wall passes", ev and set(ev) == {"pass"} and g.lanes[0].lives == 3, ev)
    g, ev = play("up", stand)
    check("... standing still through it is a hit", "hit" in ev and g.lanes[0].lives < 3, ev)
    g, ev = play("up", stand, hide=(sk.L_WR, sk.R_WR))
    check("... hands out of the picture: waved through, no life lost", ev and set(ev) == {"unseen"} and
          g.lanes[0].lives == 3, ev)
    g, ev = play("up", stand, status_at=lambda t: "hidden" if 2.0 < t < 7.9 else "active")
    w = g.lanes[0].wall
    check("... lost as the wall arrives: the wall waits, nothing is lost", g.lanes[0].lives == 3 and
          "hit" not in ev and (w is None or w["frozen"] is not None or w["due"] > 3.6), (ev, w))
    g, ev = play("left", lambda t: lean(sy.figure(), -0.25))
    check("... LEAN LEFT passed by leaning to your own left", set(ev) == {"pass"}, ev)

    pm = games.PoseMatch([0, 1], 0.0, seed=2)
    target = pm.lanes and games.POSES[pm.k]["name"]
    for i in range(int(3 * 30)):
        pm.tick(i / 30, {0: "hidden", 1: "away"})
    check("Pose Match: the round clock waits while every player is out of sight",
          pm.state(3.0)["left"] > pm.ROUND - 0.2 and pm.state(3.0)["paused"], pm.state(3.0)["left"])
    star = sy.figure(abduct=(150, 150), feet=0.35)
    pm = games.PoseMatch([0], 0.0, seed=0)
    pm.k = 0                                                              # Star
    for i in range(int(2 * 30)):
        t = i / 30
        if i % 2 == 0:
            pm.frame(0, sy.body(star, t, noise=0.003), t)
        pm.tick(t, {0: "active"})
    check("Pose Match: holding the Star for a second scores", pm.lanes[0].score > 100 or pm.round > 1,
          (pm.lanes[0].score, pm.lanes[0].sim))
    pm = games.PoseMatch([0], 0.0, seed=0)
    pm.k = 0
    for i in range(int(2 * 30)):
        t = i / 30
        if i % 2 == 0:
            pm.frame(0, sy.body(star, t, noise=0.003, hide=(sk.L_ANK, sk.R_ANK, sk.L_KNEE, sk.R_KNEE,
                                                            sk.L_WR, sk.R_WR)), t)
        pm.tick(t, {0: "active"})
    check("... with half the joints unseen it does not score from a guess", pm.lanes[0].score == 0,
          pm.lanes[0].sim)

    race = games.BodyRacer([0], 0.0, seed=3)
    wheel = sy.figure(abduct=(30, 30), arm_forward=(70, 70), elbow=(150, 150))
    for i in range(int(10 * 30)):
        t = i / 30
        if i % 2 == 0:
            race.frame(0, sy.body(wheel, t, noise=0.002), t)
        race.tick(t, {0: "active"})
    car = race.lanes[0]
    d0, h0, c0 = car.dist, car.hits, car.coins
    check("Body Racer: hands out drives the car forward", d0 > 200 and car.speed > 1.0, (d0, car.speed))
    for i in range(int(10 * 30)):
        t = 10 + i / 30
        race.tick(t, {0: "hidden"})
    check("... lost: the car coasts to a stop and hits nothing", car.speed < 0.2 and car.hits == h0 and
          car.coins == c0, (car.speed, car.hits, h0))
    check("... and the race clock does not run while nobody is seen", race.played < 10.2, race.played)


def check_calibration():
    print("Calibration: what fits where, from the camera (calibration.py)")
    cam = calibration.Camera((525.0, 525.0, 319.5, 239.5), 1.0, tilt_deg=0.0)
    sp = calibration.Space(cam)
    v = sp.view_at(2.0)
    top, bottom = 1.0 + 2.0 * 239.5 / 525, 1.0 - 2.0 * 240.5 / 525
    check("a level camera 1 m up sees from 0.08 to 1.91 m high at 2 m (pinhole maths)",
          abs(v["top"] - top) < 0.02 and abs(v["bottom"] - bottom) < 0.02, v)
    check("... and 2.44 m across", abs(v["width"] - 2 * 2.0 * 320 / 525) < 0.03, v)
    ok, why = sp.fits("squat", (0.0, 2.0), 1.75)
    check("a squat at 2 m: feet out of view, said as such", not ok and "feet" in why, why)
    check("... at 3 m it fits", sp.fits("squat", (0.0, 3.0), 1.75)[0])
    band, why = calibration.Space(cam, limit=2.0).band("squat", 1.75)
    check("a squat with only 2 m of room fits nowhere, and the reason names the feet and the 2 m",
          band is None and "feet" in why and "2.0 m" in why, why)
    band, _ = calibration.Space(cam, limit=2.0).band("curl", 1.75)
    check("a curl (hips to shoulders) fits within 2 m", band is not None and band[0] <= 2.0, band)
    infra = calibration.Camera((575.8, 575.8, 314.5, 235.5), 1.0, tilt_deg=0.0)
    check("the infrared lens (fx 575.8) sees less than the colour one at the same distance",
          calibration.Space(infra).view_at(2.0)["width"] < v["width"])
    down = calibration.Camera((525.0, 525.0, 319.5, 239.5), 1.9, tilt_deg=12.0)
    check("from the TV (1.9 m, 12 deg down) jumping jacks fit from about 2.9 m",
          (calibration.Space(down).band("jack", 1.75)[0] or (9, 9))[0] < 3.2,
          calibration.Space(down).band("jack", 1.75))
    hint = calibration.suggest_tilt(calibration.Space(calibration.Camera((525, 525, 319.5, 239.5), 0.8,
                                                                         tilt_deg=3.3), limit=2.0))
    check("a low Kinect with 2 m of room: tilting it up is suggested, with what would then fit",
          hint["by"] > 0 and len(hint["fits"]) >= len(hint["now"]), hint)
    e = engine.Engine(cfg={"space_m": 2.0})
    hub = frame_of([(1, sy.figure(z=1.6), 175)], 0.0, 1)
    hub.update(floor={"camera_height": 1.0, "tilt": 0.0, "up": [0, -1, 0], "seen": True},
               intrinsics=[525.0, 525.0, 319.5, 239.5], room={"far": 3.5})
    e.step(hub, now=0.0)
    e.workout.start("free", 0.0, exercise="squat")
    hub2 = dict(hub, frame=2, captured=0.05)
    ev, _ = e.step(hub2, now=0.05)
    p = e.roster.by_slot(0)
    check("the engine uses it: a squat at 1.6 m from this camera is paused with the reason",
          p.warning and "feet" in p.warning, p.warning)


def check_pad():
    print("Kinect Pad outputs (pad.py; no device is created)")
    w = {"wheel": 0.5, "throttle": 0.8, "brake": 0.0}
    out = pad.outputs("wheel", w, 0.0, [{"gesture": "jump"}], True)
    check("wheel: steering shaped, throttle passed, A on a jump",
          0 < out["axes"]["steer"] < 0.5 and out["axes"]["throttle"] == 0.8 and out["keys"]["jump"])
    check("a small wobble in the dead zone steers nothing", pad.shape(0.05) == 0.0)
    out = pad.outputs("keys", {"wheel": -0.9, "throttle": 0.6, "brake": 0}, 0, [], True)
    check("keys: hard left = Left arrow, hands out = Up arrow", out["keys"]["left"] and out["keys"]["up"] and not out["keys"]["right"])
    out = pad.outputs("lean", None, 0.7, [], True)
    check("lean: steering from the body, no hands needed", out["axes"]["steer"] > 0.4)
    out = pad.outputs("wheel", w, 0.0, [{"gesture": "jump"}], False)
    check("tracking lost: every input released", out["keys"] == {} and out["axes"]["steer"] == 0 and out["axes"]["throttle"] == 0)


def check_fusion():
    print("Depth-fused 3D joints (people.py joints3d)")
    try:
        import cv2  # noqa: F401
    except ImportError:
        print("  skip  OpenCV not in this Python (it is in .local/air-venv)")
        return
    spec = importlib.util.spec_from_file_location("va", REPO / "scripts/verify-air.py")
    va = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(va)
    import measure
    import people
    intr = (525.0, 525.0, 319.5, 239.5)
    depth, accel, masks, basis = va.room([(-0.7, 2.8, 1.78, 0.2), (0.6, 3.2, 1.62, 0.2)])
    poses = [va.figure(basis, -0.7, 2.8, 1.78, "standing", masks[0]), va.figure(basis, 0.6, 3.2, 1.62, "standing", masks[1])]
    seen, _ = people.observe(poses, depth, measure.up_vector(accel), 1.92, intr)
    a = seen[0]
    j, s = a["joints"], a["jstate"]
    check("the head's height above the floor within 4 cm", abs(j[0][1] - 0.92 * 1.78) < 0.04, j[0][1])
    check("the hips' height within 6 cm, their side-to-side place within 6 cm",
          abs(j[23][1] - 0.53 * 1.78) < 0.06 and abs(j[23][0] - (-0.6)) < 0.06, j[23])
    check("the ankles on the floor (within 6 cm)", abs(j[27][1] - 0.08) < 0.06, j[27])
    # A wrist the picture puts over the empty room (no depth of this person there): estimated
    # from the model, never trusted, and still placed near where the model says it is.
    moved = people.Pose(poses[0].image.copy(), poses[0].world, poses[0].mask)
    moved.image[15, 0] -= 0.12
    seen2, _ = people.observe([moved, poses[1]], depth, measure.up_vector(accel), 1.92, intr)
    s2 = seen2[0]["jstate"]
    check("a joint with no depth under it is estimated (inferred), the torso stays tracked",
          s2[15] == people.INFERRED and all(s2[i] == people.TRACKED for i in (11, 23, 24)), s2[:25])
    check("most joints of a person in full view are depth-tracked", int((s == people.TRACKED).sum()) >= 20, int((s == 2).sum()))
    check("everyone gets 33 joints in the room frame", all(len(o["joints"]) == 33 for o in seen))


def check_server():
    print("The server (server.py, demo people)")
    try:
        from aiohttp.test_utils import TestClient, TestServer
    except ImportError:
        print("  skip  aiohttp missing")
        return
    import server

    async def go():
        svc = server.Service({"voice": False}, store.Store(":memory:"), demo=True)
        import demoroom
        src = demoroom.Demo()
        hub = src.next()
        svc.engine.step(hub)
        svc.snapshot = svc.engine.state(hub)
        client = TestClient(TestServer(server.make_app(svc)))
        await client.start_server()
        try:
            out = {}
            r = await client.get("/api/catalog")
            out["catalog"] = len((await r.json())["exercises"])
            r = await client.post("/api/users", json={"name": "Test", "kg": 70})
            uid = (await r.json())["id"]
            r = await client.post("/api/workout", json={"action": "start", "mode": "free", "exercise": "squat"})
            out["start"] = r.status
            out["players"] = len(svc.engine.roster.players)
            r = await client.post("/api/workout", json={"action": "start", "mode": "free", "exercise": "nope"})
            out["bad"] = r.status
            r = await client.post("/api/workout", json={"action": "fly"})
            out["bad_action"] = r.status
            r = await client.get(f"/api/history?user={uid}")
            out["history"] = r.status
            ws = await client.ws_connect("/ws")
            msg = await ws.receive_json(timeout=2)
            out["ws"] = "state" in msg and "people" in msg["state"]
            await ws.close()
            for page in ("fitness", "arcade", "room", "studio"):
                r = await client.get(f"/{page}", allow_redirects=False)
                out[page] = (r.status, r.headers.get("Location"))
            r = await client.get("/arcade?game=walls", allow_redirects=False)
            out["arcade-game"] = r.headers.get("Location")
            r = await client.get("/app")
            out["app"] = (r.status, "Kinect" in await r.text())
            r = await client.get("/static/app.css")
            out["css"] = r.status
            r = await client.get("/api/demo/squat")
            out["demo"] = (r.status, len((await r.json())["frames"]))
            r = await client.get("/api/demo/nope")
            out["demo-bad"] = r.status
            r = await client.get("/api/poses")
            out["poses"] = len(await r.json())
            r = await client.get(f"/api/insight?user={uid}")
            out["insight"] = sorted((await r.json()).keys())
            r = await client.get("/hub/etc/passwd")
            out["proxy-guard"] = r.status
            r = await client.post("/api/game", json={"action": "start", "game": "walls"})
            out["game"] = (r.status, svc.engine.game is not None and svc.engine.game.key)
            r = await client.post("/api/game", json={"action": "start", "game": "tetris"})
            out["game-bad"] = r.status
            r = await client.post("/api/game", json={"action": "stop"})
            out["game-stop"] = (r.status, svc.engine.game)
            r = await client.post("/api/forget", json={"user": uid})
            out["forget"] = r.status
            r = await client.get("/api/catalog")
            out["games"] = [g["key"] for g in (await r.json())["games"]]
            return out
        finally:
            await client.close()

    out = asyncio.run(go())
    check("catalog lists the 14 exercises", out["catalog"] == 14, out)
    check("Start with nobody joined: everyone in view plays", out["start"] == 200 and out["players"] == 2, out)
    check("an unknown exercise or action is refused", out["bad"] == 400 and out["bad_action"] == 400, out)
    check("the live state arrives on /ws", out["ws"], out)
    check("one app at /app, with its stylesheet", out["app"] == (200, True) and out["css"] == 200, out)
    check("the old pages open the app's sections (arcade = games, studio = camera)",
          out["fitness"] == (302, "/app#/fitness") and out["arcade"] == (302, "/app#/games") and
          out["room"] == (302, "/app#/room") and out["studio"] == (302, "/app#/camera") and
          out["arcade-game"] == "/app#/games/walls", out)
    check("demonstrations for exercises (and none for unknown moves), and the Pose Match figures",
          out["demo"][0] == 200 and out["demo"][1] > 20 and out["demo-bad"] == 404 and out["poses"] == 7, out)
    check("history: movement, tracking quality, games and best scores", out["insight"] == ["best", "games", "movement", "quality"]
          and out["history"] == 200 and out["forget"] == 200, out)
    check("the hub proxy passes only the hub's own pictures and controls", out["proxy-guard"] == 404, out)
    check("games start on the server (and only known ones), stop, and are listed with tutorials",
          out["game"] == (200, "walls") and out["game-bad"] == 400 and out["game-stop"] == (200, None)
          and out["games"] == ["walls", "pose", "race"], out)
    if shutil.which("node"):
        bad = []
        for js in sorted((MOTION / "static").glob("*.js")):
            if subprocess.run(["node", "--check", str(js)], capture_output=True).returncode:
                bad.append(js.name)
        check("the pages' scripts parse", not bad, bad)


def main():
    check_skeleton()
    check_exercises()
    check_gestures()
    check_players()
    check_training()
    check_engine()
    check_freshness()
    check_roster_identity()
    check_games()
    check_calibration()
    check_pad()
    check_fusion()
    check_server()
    print()
    if FAILED:
        print(f"Kinect Motion: {len(FAILED)} check(s) FAILED")
        return 1
    print("Kinect Motion: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
