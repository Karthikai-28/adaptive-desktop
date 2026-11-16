#!/usr/bin/env python3
"""Checks for Air (Kinect hand-gesture control): the gesture engine against synthetic hands,
the Kinect probe and motor-state parsing, the frame protocol the shell reads.

    scripts/verify-air.py              pure checks (no camera, no Kinect, no D-Bus)
    scripts/verify-air.py --hardware   also report the Kinect on USB and the libfreenect build

Synthetic hands are built joint by joint (MediaPipe's 21 landmarks), so every pose the engine
knows is drawn here the way a camera would see it. docs/AIR.md.
"""

import json
import math
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/adaptive-air"))

import gestures  # noqa: E402
import kinect  # noqa: E402
import demo  # noqa: E402
import protocol  # noqa: E402
from synthetic import hand  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


# ------------------------------------------------------------------ helpers

def run(engine, frames):
    """frames: [(t, [hands])] -> list of every event, last state."""
    events, state = [], None
    for t, hands in frames:
        state = engine.step(t, hands)
        events += state["events"]
    return [e["type"] for e in events], state


def hold(t0, seconds, fps=30, **kw):
    n = int(seconds * fps)
    return [(t0 + i / fps, [hand(**kw)]) for i in range(n)]


def engaged_engine(**config):
    e = gestures.Engine(config)
    run(e, hold(0.0, 0.8, shape="open"))
    assert e.engaged
    return e


def move(t0, seconds, x0, x1, y0=0.5, y1=0.5, fps=30, **kw):
    n = max(2, int(seconds * fps))
    out = []
    for i in range(n):
        f = i / (n - 1)
        out.append((t0 + i / fps, [hand(cx=x0 + (x1 - x0) * f, cy=y0 + (y1 - y0) * f, **kw)]))
    return out


# ------------------------------------------------------------------ checks

def check_shapes():
    print("Hand shapes")
    for shape, want in (("open", "open"), ("fist", "fist"), ("point", "point"),
                        ("pinch", "pinch")):
        lm = hand(shape=shape)["lm"]
        pinching = gestures.pinch_ratio(lm) < gestures.DEFAULTS["pinch_on"] \
            and not gestures.curled(lm)
        got = gestures.classify(lm, pinching)
        check(f"{shape} hand reads as {want}", got == want, got)
    fist = hand(shape="fist")["lm"]
    check("a fist with the thumb near the index is not a pinch", gestures.curled(fist))


def check_filter():
    print("One Euro filter")
    f = gestures.OneEuro(min_cutoff=1.4, beta=4.0)
    jitter = [0.5 + (0.004 if i % 2 else -0.004) for i in range(60)]
    out = [f(x, i / 30) for i, x in enumerate(jitter)]
    spread = max(out[30:]) - min(out[30:])
    check("jitter on a still hand is damped", spread < 0.004, f"{spread:.4f}")
    f = gestures.OneEuro(min_cutoff=1.4, beta=4.0)
    out = [f(0.2 + 0.03 * i, i / 30) for i in range(20)]
    lag = (0.2 + 0.03 * 19) - out[-1]
    check("a fast move is followed closely", lag < 0.05, f"lag {lag:.3f}")


def check_engage():
    print("Engage and disengage")
    e = gestures.Engine()
    types, state = run(e, hold(0.0, 0.3, shape="open"))
    check("an open palm held briefly does not engage", not e.engaged and "engage" not in types)
    check("the reticle shows engage progress", 0.2 < state["engage"] < 1.0, state["engage"])
    types, state = run(e, hold(0.3, 0.5, shape="open"))
    check("an open palm held still engages", e.engaged and types.count("engage") == 1)
    check("the pointer starts at the centre", abs(state["cursor"]["x"] - 0.5) < 0.02)

    e = gestures.Engine()
    run(e, move(0.0, 1.0, 0.2, 0.8, shape="open"))
    check("a moving open hand does not engage", not e.engaged)

    e = gestures.Engine()
    run(e, hold(0.0, 1.0, shape="fist"))
    check("a fist does not engage", not e.engaged)

    e = gestures.Engine()
    run(e, hold(0.0, 1.0, shape="open", size=0.03))
    check("a small far-away hand (someone behind you) is ignored", not e.engaged)

    e = engaged_engine()
    types, _ = run(e, [(1.0 + i / 30, []) for i in range(30)])
    check("losing the hand disengages", not e.engaged and "disengage" in types)

    e = engaged_engine()
    types, _ = run(e, [(1.0 + i / 30, []) for i in range(8)] + hold(1.27, 0.3, shape="open"))
    check("a brief loss of the hand (a few frames) does not disengage",
          e.engaged and "disengage" not in types)


def check_pointer():
    print("Pointer")
    e = engaged_engine()
    _, state = run(e, move(1.0, 0.6, 0.5, 0.6) + hold(1.6, 0.4, cx=0.6))
    w, _ = e.box()
    want = 0.5 + 0.1 / w
    check("the pointer follows the palm across the box", abs(state["cursor"]["x"] - want) < 0.02,
          f"{state['cursor']['x']:.3f} vs {want:.3f}")
    _, state = run(e, hold(2.0, 0.4, cx=0.99))
    check("the pointer stays on the screen", state["cursor"]["x"] <= 1.0)
    check("the primary hand is drawn in screen space", state["hands"][0]["primary"]
          and len(state["hands"][0]["pts"]) == 21)


def check_pinch():
    print("Pinch")
    e = engaged_engine()
    types, s1 = run(e, hold(1.0, 0.15, shape="pinch"))
    check("pinching presses", types == ["press"] and s1["pressed"], types)
    types, s2 = run(e, hold(1.15, 0.2, shape="open"))
    check("letting go releases and clicks", types == ["release", "click"], types)

    e = engaged_engine()
    types, _ = run(e, hold(1.0, 0.2, shape="pinch") + move(1.2, 0.6, 0.5, 0.65, shape="pinch")
                   + hold(1.8, 0.2, shape="open"))
    check("pinch, move, let go is a drag (no click)", types == ["press", "release"], types)

    e = engaged_engine()
    before = e.cursor
    run(e, hold(1.0, 0.1, shape="pinch"))
    check("the pointer holds still as the pinch closes", e.cursor == before)


def check_grab():
    print("Grab and throw")
    e = engaged_engine()
    types, s = run(e, hold(1.0, 0.2, shape="fist"))
    check("a fist grabs", types == ["grab"] and s["grab"] is not None, types)
    types, _ = run(e, move(1.2, 0.5, 0.5, 0.55, shape="fist") + hold(1.7, 0.3, shape="fist", cx=0.55)
                   + hold(2.0, 0.2, shape="open", cx=0.55))
    check("opening the hand after a slow carry drops (no throw)", types == ["drop"], types)

    e = engaged_engine()
    types, _ = run(e, hold(1.0, 0.2, shape="fist") + move(1.2, 0.15, 0.5, 0.62, shape="fist")
                   + hold(1.35, 0.2, shape="open", cx=0.62))
    check("flinging right while opening throws right", types[-2:] == ["drop", "throw-right"], types)

    e = engaged_engine()
    types, _ = run(e, hold(1.0, 0.2, shape="fist") + move(1.2, 0.15, 0.5, 0.5, 0.5, 0.36,
                                                         shape="fist")
                   + hold(1.35, 0.2, shape="open", cy=0.36))
    check("flinging up throws up (maximise)", "throw-up" in types, types)


def check_swipe():
    print("Swipes")
    e = engaged_engine()
    types, s = run(e, move(1.0, 0.2, 0.5, 0.25))
    check("a fast open-hand swipe left", types == ["swipe-left"], types)
    check("the swipe puts the pointer back", abs(s["cursor"]["x"] - 0.5) < 0.08, s["cursor"])
    e = engaged_engine()
    types, _ = run(e, move(1.0, 0.2, 0.5, 0.75))
    check("a fast open-hand swipe right", types == ["swipe-right"], types)
    e = engaged_engine()
    types, _ = run(e, move(1.0, 0.2, 0.5, 0.5, 0.6, 0.38))
    check("a fast swipe up", types == ["swipe-up"], types)
    e = engaged_engine()
    types, _ = run(e, move(1.0, 1.2, 0.5, 0.25))
    check("an ordinary move is not a swipe", types == [], types)
    e = engaged_engine()
    types, _ = run(e, move(1.0, 0.2, 0.5, 0.25) + move(1.25, 0.2, 0.25, 0.5))
    check("the hand coming back after a swipe is not a second swipe", types == ["swipe-left"],
          types)
    e = engaged_engine()
    run(e, move(1.0, 0.2, 0.5, 0.25) + hold(1.2, 1.0, cx=0.25))
    held = e.cursor[0]
    _, s = run(e, move(2.2, 0.3, 0.25, 0.30) + hold(2.5, 0.4, cx=0.30))
    w, _ = e.box()
    check("after a swipe the pointer carries on from where it was (clutch)",
          abs(held - 0.5) < 0.08 and abs(s["cursor"]["x"] - (held + 0.05 / w)) < 0.04,
          f"held {held:.2f}, then {s['cursor']['x']:.2f}")


def check_push():
    print("Air push (depth)")
    e = gestures.Engine()
    run(e, hold(0.0, 0.8, shape="open", depth=900))
    frames = [(0.8 + i / 30, [hand(shape="open", depth=900 - 15 * i)]) for i in range(8)]
    types, _ = run(e, frames)
    check("the palm moving 7 cm toward the Kinect clicks", types[:2] == ["push", "click"], types)
    e = engaged_engine()
    types, _ = run(e, hold(1.0, 0.4, shape="open"))
    check("without depth there is no push", "push" not in types)
    e = gestures.Engine()
    run(e, hold(0.0, 0.8, shape="open", depth=900))
    frames = [(0.8 + i / 30, [hand(shape="open", depth=900 - 2 * i)]) for i in range(40)]
    types, _ = run(e, frames)
    check("drifting slowly closer is not a push", "push" not in types, types)


def check_right_click():
    print("Right-click (thumb on the middle finger)")
    e = engaged_engine()
    types, _ = run(e, hold(1.0, 0.3, shape="pinch-middle") + hold(1.3, 0.2, shape="open"))
    check("thumb on the middle fingertip right-clicks once", types == ["right-click"], types)
    types, _ = run(e, hold(1.5, 0.3, shape="pinch-middle"))
    check("a second touch right-clicks again", types == ["right-click"], types)
    e = engaged_engine()
    types, _ = run(e, hold(1.0, 0.3, shape="pinch"))
    check("an index pinch is not a right-click", "right-click" not in types, types)


def check_scroll():
    print("Scroll and zoom with the V sign")
    e = engaged_engine()
    before = e.cursor
    frames = hold(1.0, 0.2, shape="vee") + move(1.2, 0.5, 0.5, 0.5, 0.5, 0.42, shape="vee")
    types, state = run(e, frames)
    evs = [ev for f in [] for ev in f]
    e2 = engaged_engine()
    total = 0
    for t, hands in frames:
        for ev in e2.step(t, hands)["events"]:
            if ev["type"] == "scroll":
                total += ev["dy"]
    check("moving the V sign up scrolls down (the page follows the hand)", total >= 4, total)
    check("the pointer stays put while scrolling", e2.cursor == before, (e2.cursor, before))
    check("the V sign is reported as scroll mode", state["mode"] == "scroll", state["mode"])
    e3 = engaged_engine(natural_scroll=False)
    total = sum(ev["dy"] for t, hands in frames for ev in e3.step(t, hands)["events"]
                if ev["type"] == "scroll")
    check("natural_scroll off: hand up scrolls up", total <= -4, total)
    types, s2 = run(e2, hold(1.8, 0.3, shape="open") + move(2.1, 0.3, 0.5, 0.55))
    w, _ = e2.box()
    check("after scrolling the pointer carries on from where it was",
          s2["mode"] is None and abs(s2["cursor"]["x"] - (0.5 + 0.05 / w)) < 0.05, s2["cursor"])

    e = gestures.Engine()
    run(e, hold(0.0, 0.8, shape="open", depth=900))
    frames = hold(0.8, 0.2, shape="vee", depth=900) + \
        [(1.0 + i / 30, [hand(shape="vee", depth=900 - 8 * i)]) for i in range(20)]
    zoom = sum(ev["steps"] for t, hands in frames for ev in e.step(t, hands)["events"]
               if ev["type"] == "zoom")
    check("the V sign pushed 15 cm toward the Kinect zooms in 3 steps", zoom == 3, zoom)
    check("pushing a V sign is not an air click", "push" not in types)
    e = engaged_engine()
    frames = hold(1.0, 0.2, shape="vee") + \
        [(1.2 + i / 30, [hand(shape="vee", size=0.12 * (1 - 0.012 * i))]) for i in range(25)]
    zoom = sum(ev["steps"] for t, hands in frames for ev in e.step(t, hands)["events"]
               if ev["type"] == "zoom")
    check("without depth, the V sign drawn back (hand smaller) zooms out", zoom <= -1, zoom)


def pair(t, gap, shape="pinch", depth=None, shape_left=None):
    return (t, [hand(cx=0.5 + gap / 2, shape=shape, side="Right", depth=depth),
                hand(cx=0.5 - gap / 2, shape=shape_left or shape, side="Left", depth=depth)])


def check_two_hands():
    print("Two hands")
    e = engaged_engine()
    frames = [pair(1.0 + i / 30, 0.15 + 0.008 * i) for i in range(25)]
    evs = [ev for t, hands in frames for ev in e.step(t, hands)["events"]]
    zoom = sum(ev["steps"] for ev in evs if ev["type"] == "zoom")
    check("both hands pinching and pulling apart zoom in step by step", zoom == 5,
          [ev["type"] for ev in evs])
    check("a two-hand pinch is not a click", not any(ev["type"] == "click" for ev in evs))
    frames = [pair(1.9 + i / 30, 0.342 - 0.008 * i) for i in range(20)]
    zoom = sum(ev["steps"] for t, hands in frames for ev in e.step(t, hands)["events"]
               if ev["type"] == "zoom")
    check("... and pushing together zoom out", zoom <= -3, zoom)

    e = engaged_engine()
    frames = [pair(1.0 + i / 30, 0.15 + 0.01 * i, shape="open") for i in range(20)]
    types, _ = run(e, frames)
    check("both open palms pulled apart: spread (overview)", "spread" in types, types)
    e = engaged_engine()
    frames = [pair(1.0 + i / 30, 0.40 - 0.012 * i, shape="open") for i in range(20)]
    types, _ = run(e, frames)
    check("both open palms pushed together: collapse", "collapse" in types, types)
    check("two open hands never swipe", not any(t.startswith("swipe") for t in types), types)

    e = engaged_engine()
    run(e, hold(1.0, 0.2, shape="fist"))
    frames = [(1.2 + i / 30, [hand(cx=0.55, shape="fist", side="Right"),
                              hand(cx=0.40, shape="fist", side="Left")]) for i in range(5)]
    frames += [(1.4 + i / 30, [hand(cx=0.55 + 0.004 * i, shape="fist", side="Right"),
                               hand(cx=0.40 - 0.004 * i, shape="fist", side="Left")])
               for i in range(15)]
    types, state = run(e, frames)
    check("holding a window, a second fist starts a resize", "resize-start" in types, types)
    check("pulling the fists apart grows the window", state["resize"] and state["resize"] > 1.5,
          state["resize"])
    types, state = run(e, [(2.0 + i / 30, [hand(cx=0.6, shape="fist")]) for i in range(10)]
                       + hold(2.4, 0.3, shape="open", cx=0.6))
    check("letting the second hand go ends the resize, opening drops without a throw",
          types == ["resize-end", "drop"], types)


def check_probe():
    print("Kinect on USB (sysfs)")

    def fake(products):
        d = Path(tempfile.mkdtemp())
        for i, (vendor, product) in enumerate(products):
            dev = d / f"1-{i}"
            dev.mkdir()
            (dev / "idVendor").write_text(vendor + "\n")
            (dev / "idProduct").write_text(product + "\n")
        return d
    p = kinect.probe(fake([("046d", "c534")]))
    check("no Kinect", not p["present"])
    p = kinect.probe(fake([("0409", "005a"), ("045e", "02b0")]))
    check("motor only: model 1414, camera missing, asks for the 12 V supply",
          p["model"] == "1414" and p["motor"] and not p["camera"] and "12 V" in p["advice"])
    p = kinect.probe(fake([("045e", "02b0"), ("045e", "02ad"), ("045e", "02ae")]))
    check("powered model 1414: camera ready", p["camera"] and p["audio"])
    p = kinect.probe(fake([("045e", "02c2"), ("045e", "02bf")]))
    check("model 1473 is recognised", p["model"] == "1473" and p["camera"])
    s = kinect.parse_state(bytes([0, 0, 0, 8, 3, 88, 0, 11, 2, 0]))
    check("motor state: accelerometer and tilt",
          s["accel"] == [8, 856, 11] and s["tilt"] == 1.0 and s["status"] == "stopped", s)


def check_protocol():
    print("Frame protocol")
    e = engaged_engine()
    state = e.step(1.0, [hand(shape="pinch", depth=850)])
    msg = protocol.frame(state, source="kinect", fps=29.6, status="tracking")
    data = json.loads(msg)
    check("a frame is compact JSON with the fields the shell reads",
          {"engaged", "engage", "cursor", "pressed", "hands", "events", "source", "fps"}
          <= set(data) and len(msg) < 4000, len(msg))
    check("depth reaches the shell in millimetres", data["hands"][0]["depth"] == 850)
    shell = (REPO / "shell/adaptive-shell@local/air.js").read_text()
    for field in ("engaged", "engage", "cursor", "pressed", "hands", "events", "grab", "status",
                  "mode", "resize"):
        check(f"air.js reads '{field}'", f".{field}" in shell)
    for ev in ("right-click", "scroll", "zoom", "resize-start", "resize-end",
               "press", "release", "grab", "drop", "throw-left", "throw-right", "throw-up",
               "throw-down", "swipe-left", "swipe-right", "swipe-up", "spread", "collapse",
               "engage", "disengage", "click"):
        check(f"air.js handles '{ev}'", f"'{ev}'" in shell)


def check_demo():
    print("Demo (air.py --demo)")
    e = gestures.Engine()
    events = []
    for i in range(int(demo.DURATION * demo.FPS)):
        t = i / demo.FPS
        events += e.step(t, demo.hands_at(t))["events"]
    names = []
    for ev in events:
        if not names or names[-1] != ev["type"] or ev["type"] not in ("scroll", "zoom"):
            names.append(ev["type"])
    want = ["engage", "press", "release", "click", "right-click", "scroll", "zoom", "grab",
            "resize-start", "resize-end", "drop", "throw-right", "swipe-left", "swipe-right",
            "zoom", "spread", "collapse", "disengage"]
    check("the demo plays every gesture, in order", names == want, names)
    zooms = [ev["steps"] for ev in events if ev["type"] == "zoom"]
    check("its zooms: three in with the V sign, then in and back out with two hands",
          sum(zooms[:3]) == 3 and sum(z for z in zooms[3:] if z > 0) >= 3
          and any(z < 0 for z in zooms[3:]), zooms)


def hardware():
    print("Hardware")
    p = kinect.probe()
    print("  " + json.dumps(p))
    print("  libfreenect built: " + ("yes" if kinect.available() else "no (kinect/build-libfreenect.sh)"))
    if p["motor"]:
        try:
            m = kinect.Motor()
            print("  motor: " + json.dumps(m.state()))
            m.close()
        except OSError as err:
            print(f"  motor: {err}")


def main():
    check_shapes()
    check_filter()
    check_engage()
    check_pointer()
    check_pinch()
    check_grab()
    check_swipe()
    check_push()
    check_right_click()
    check_scroll()
    check_two_hands()
    check_probe()
    check_protocol()
    check_demo()
    if "--hardware" in sys.argv:
        hardware()
    print()
    if FAILED:
        print(f"{len(FAILED)} failed: " + ", ".join(FAILED))
        return 1
    print("Air: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
