#!/usr/bin/env python3
"""Checks for Air (Kinect hand-gesture control): the gesture engine against synthetic hands,
the sensor fusion (colour or infrared by the light, depth refining and finding hands) against a
synthetic living room, the Kinect probe and motor-state parsing, the frame protocol the shell
reads.

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
HERE_AIR = REPO / "services/adaptive-air"
sys.path.insert(0, str(HERE_AIR))

import fusion  # noqa: E402
import gestures  # noqa: E402
import kinect  # noqa: E402
import demo  # noqa: E402
import protocol  # noqa: E402
from synthetic import hand, room_depth  # noqa: E402

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
    config.setdefault("box_hands", 3.5)        # 0.42 of the image for these 0.12 hands
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
    for shape, want in (("open", "open"), ("fist", "fist"), ("point", "point"), ("L", "L"),
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
    e = gestures.Engine({"box_hands": 3.5})
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
    run(e, hold(0.0, 1.0, shape="open", size=0.01))
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
    types, s = run(e, move(1.0, 0.2, 0.5, 0.5, 0.6, 0.38))
    ev = [x for x in e.step(1.25, [hand(0.5, 0.38)])["events"]]
    check("a fast wave up scrolls down a chunk (the page follows the hand)",
          types == ["scroll"], types)
    e = engaged_engine()
    frames = move(1.0, 0.2, 0.5, 0.5, 0.4, 0.62)
    evs = [x for t, h in frames for x in e.step(t, h)["events"]]
    check("a fast wave down scrolls up 6 steps",
          [(x["type"], x["dy"]) for x in evs] == [("scroll", -6)], evs)
    frames = hold(1.2, 0.1, cy=0.62) + move(1.3, 0.2, 0.5, 0.5, 0.62, 0.4)
    evs = [x for t, h in frames for x in e.step(t, h)["events"]]
    check("the hand coming back up after a wave down does not scroll back", evs == [], evs)
    frames = hold(1.5, 0.6, cy=0.4) + move(2.1, 0.2, 0.5, 0.5, 0.4, 0.62)
    evs = [x for t, h in frames for x in e.step(t, h)["events"]]
    check("a second wave down scrolls again", [x["type"] for x in evs] == ["scroll"], evs)
    e = engaged_engine()
    before = e.cursor
    frames = move(1.0, 0.15, 0.5, 0.5, 0.5, 0.7) + move(1.15, 0.4, 0.5, 0.5, 0.7, 0.5) + \
        hold(1.55, 0.6, cy=0.5)
    _, st = run(e, frames)
    check("the hand coming back after a wave does not drag the pointer",
          abs(st["cursor"]["y"] - before[1]) < 0.06, (before, st["cursor"]))
    e = engaged_engine()
    frames = [(1.0 + i / 30, [hand(0.5, 0.5, shape="point", side="Right"),
                              hand(0.3, 0.4 + 0.035 * i, side="Left")]) for i in range(8)]
    evs = [x["type"] for t, h in frames for x in e.step(t, h)["events"]]
    check("the other hand can wave too", "scroll" in evs, evs)
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


def check_lzoom():
    print("One-hand zoom: the L")
    e = engaged_engine()
    before = e.cursor
    frames = hold(1.0, 0.2, shape="L", gap=0.4) + \
        [(1.2 + i / 30, [hand(shape="L", gap=0.4 + 0.05 * i)]) for i in range(13)]
    evs = [x for t, h in frames for x in e.step(t, h)["events"]]
    zoom = sum(x["steps"] for x in evs if x["type"] == "zoom")
    check("opening the L zooms in", zoom >= 2, evs)
    check("the pointer stays put while zooming", e.cursor == before)
    frames = [(1.65 + i / 30, [hand(shape="L", gap=1.0 - 0.06 * i)]) for i in range(14)] + \
        hold(2.12, 0.2, shape="pinch")
    evs = [x for t, h in frames for x in e.step(t, h)["events"]]
    zoom = sum(x["steps"] for x in evs if x["type"] == "zoom")
    check("closing it zooms out, and closing it all the way is not a click",
          zoom <= -3 and not any(x["type"] in ("press", "click") for x in evs), evs)
    types, st = run(e, hold(2.4, 0.4, shape="open"))
    check("an open hand leaves the zoom", st["mode"] is None, st["mode"])


def check_room():
    print("Across the room (Kinect on the TV)")
    e = gestures.Engine()
    small = 0.035                                     # a hand about 3 m away
    types, state = run(e, hold(0.0, 0.8, shape="open", size=small))
    check("a hand 3 m away engages", e.engaged, types)
    w, _ = e.box()
    check("the box shrinks with the hand (same arm movement)", abs(w - 0.15) < 1e-6, w)
    _, state = run(e, move(0.8, 0.5, 0.5, 0.5 + 0.075) + hold(1.3, 0.4, cx=0.575))
    check("half a box to the right moves the pointer half a screen",
          abs(state["cursor"]["x"] - 1.0) < 0.03, state["cursor"])


def check_edge():
    print("Carry a window to another desktop")
    e = engaged_engine()
    run(e, hold(1.0, 0.2, shape="fist"))
    types, _ = run(e, move(1.2, 0.3, 0.5, 0.75, shape="fist") + hold(1.5, 0.7, shape="fist", cx=0.75))
    check("a window held at the right edge goes to the next desktop",
          types.count("carry-right") == 1, types)
    types, _ = run(e, hold(2.2, 1.2, shape="fist", cx=0.75))
    check("held there longer, it goes on to the one after", types.count("carry-right") == 1, types)
    types, _ = run(e, hold(3.4, 0.3, shape="open", cx=0.75))
    check("opening the hand drops it there", "drop" in types, types)


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


def check_light():
    print("Colour or infrared, by the light (fusion.LightSwitch)")
    sw = fusion.LightSwitch()
    modes = [sw.step(t / 10, "rgb", 0.3) for t in range(50)]
    check("a lit room stays in colour", set(modes) == {"rgb"})
    sw = fusion.LightSwitch()
    got = [sw.step(t / 10, "rgb", 0.02 if t < 10 else 0.3) for t in range(40)]
    check("a moment of dark (a shadow) does not switch", set(got) == {"rgb"})
    sw = fusion.LightSwitch()
    t, mode = 0.0, "rgb"
    while mode == "rgb" and t < 10:
        mode = sw.step(t, "rgb", 0.02)
        t += 0.1
    check("dark for 2 s: infrared", mode == "ir" and 1.9 < t < 2.3, t)
    got = {sw.step(t + k, "ir", None) for k in range(1, 19)}
    check("in infrared it stays put between checks", got == {"ir"})
    check("every 20 s it looks at colour", sw.step(t + 20.5, "ir", None) == "rgb")
    check("... asking until the colour frames come", sw.step(t + 20.7, "ir", None) == "rgb")
    check("... looks for a moment", sw.step(t + 20.8, "rgb", 0.03) == "rgb")
    check("... still dark: back to infrared", sw.step(t + 21.3, "rgb", 0.03) == "ir")
    t2 = t + 42
    sw.step(t2, "ir", None)
    sw.step(t2 + 0.3, "rgb", 0.2)
    check("lights on: stays in colour", sw.step(t2 + 0.8, "rgb", 0.2) == "rgb"
          and sw.step(t2 + 3, "rgb", 0.2) == "rgb" and sw.reason == "lit")
    sw = fusion.LightSwitch()
    sw.step(0, "rgb", 0.01)
    sw.step(2.1, "rgb", 0.01)
    got = {sw.step(2.1 + k, "ir", None, busy=True) for k in range(1, 60)}
    check("never a colour check while someone is using Air", got == {"ir"})
    got = {sw.step(70 + k, "ir", None, hold=True) for k in range(1, 60)}
    check("... nor while the webcam is on", got == {"ir"})
    sw = fusion.LightSwitch()
    sw.step(0, "rgb", 0.01)
    sw.step(2.1, "rgb", 0.01)
    sw.step(23, "ir", None)
    sw.step(23.3, "rgb", 0.05)
    check("a dim room (between the two levels) goes back to infrared, no flapping",
          sw.step(23.8, "rgb", 0.05) == "ir")


def check_fusion():
    print("Depth fusion (fusion.py) in a synthetic living room")
    import time

    import numpy as np
    fx = 525.0
    check("the two cameras' lens numbers", kinect.intrinsics("rgb")[0] == 525.0
          and kinect.intrinsics("ir")[0] == 575.8 and kinect.intrinsics("x") == kinect.intrinsics("rgb"))
    check("the picture is 3.29 m wide at 2.7 m",
          abs(fusion.metres_per_width(2700, fx) - 3.291) < 0.01)
    check("a hand is ~17 px from wrist to knuckle at 2.7 m", abs(fusion.hand_px(2700, fx) - 17.5) < 0.3)

    depth, (hu, hv) = room_depth()
    r = 0.75 * fusion.hand_px(2450, fx)
    got = fusion.refine_palm(depth, hu + 4, hv - 3, r)
    check("refine_palm: the palm's centre from a seed 5 px off",
          got and math.hypot(got[0] - hu, got[1] - hv) < 1.5, (got, hu, hv))
    check("... and its distance", got and abs(got[2] - 2450) < 15, got)
    rng = np.random.default_rng(3)
    seeds, out = [], []
    for i in range(40):
        d, _ = room_depth(seed=i)
        su, sv = hu + rng.normal(0, 2), hv + rng.normal(0, 2)
        seeds.append((su, sv))
        out.append(fusion.refine_palm(d, su, sv, r)[:2])
    s_in = float(np.std(np.array(seeds), axis=0).mean())
    s_out = float(np.std(np.array(out), axis=0).mean())
    check("... a wobbling seed (landmarks 2 px of noise) gives a palm 2x steadier",
          s_out < 0.5 * s_in, (round(s_in, 2), round(s_out, 2)))
    check("refine_palm: nothing there, no palm", fusion.refine_palm(np.zeros_like(depth), hu, hv, r) is None)

    dh = fusion.DepthHands()
    found, spent = [], []
    for i in range(30):
        f = min(1, i / 15)
        d, at = room_depth((0.15, 0.35 - 0.35 * f, 2.75 - 0.30 * f), seed=i)
        t0 = time.perf_counter()
        found = dh.find(d, i / 30, fx)
        spent.append(time.perf_counter() - t0)
    check("a hand raised and held out toward the TV is found from depth alone",
          len(found) == 1 and math.hypot(found[0]["u"] - at[0], found[0]["v"] - at[1]) < 3
          and abs(found[0]["z"] - 2450) < 20, found)
    check("... quickly (a few ms a frame)", float(np.median(spent)) < 0.015, round(float(np.median(spent)) * 1000, 1))
    blobs = dh._blobs(room_depth(hand=None)[0], fx)
    check("the lamp's pole, the table, the head, the torso and the couch are not hands",
          all(not (abs(b["z"] - 1600) < 100 or abs(b["z"] - 2800) < 60 or abs(b["z"] - 3000) < 60)
              for b in blobs) and not any(abs(b["u"] - 128) < 6 and b["v"] > 200 for b in blobs), blobs)
    dh = fusion.DepthHands()
    for i in range(30):
        found = dh.find(room_depth(seed=i)[0], i / 30, fx)
    check("a hand-shaped thing that never moves (the lamp, a hand held still from the start)"
          " is never a hand", found == [], found)
    dh = fusion.DepthHands()
    d, at = room_depth()
    found = dh.find(d, 0.0, fx, seeds=[("Left", at[0] + 2, at[1], 2450)])
    check("a blob where MediaPipe found a hand is that hand (not a second one)", found == [], found)
    found = dh.find(room_depth(seed=1)[0], 0.033, fx)
    check("... and when MediaPipe loses it, depth carries it, with its side",
          len(found) == 1 and found[0]["side"] == "Left", found)
    found = dh.find(np.zeros_like(d), 1.0, fx)
    check("... until it is gone", found == [] and dh.tracks == [], dh.tracks)

    check("a hand the right size for its distance is plausible",
          fusion.plausible(17, 2700, fx, fusion.HAND_M))
    check("a 'hand' on a poster 3.6 m away, five times too big, is not",
          not fusion.plausible(65, 3600, fx, fusion.HAND_M))
    check("a 'person' 100 px wide at 0.55 m (a picture on a screen) is not",
          not fusion.plausible(100, 557, fx, fusion.SHOULDERS_M, 0.35, 2.5))
    check("no depth reading: nothing to go on, so plausible", fusion.plausible(40, None, fx, 0.09))
    check("depth_at: the median around a pixel", fusion.depth_at(depth, at[0], at[1]) and
          abs(fusion.depth_at(depth, at[0], at[1]) - 2450) < 15)


def far_hand(cx, cy, depth=2700.0, **kw):
    """A hand as the fusion gives it across the room: small, with its distance and scale."""
    h = hand(cx=cx, cy=cy, size=0.036, **kw)
    h.update(depth=depth, scale=fusion.metres_per_width(depth, 525.0), source="rgb")
    return h


def check_metres():
    print("Arm movement in metres (the Kinect knows how far you are)")
    moved = {}
    for z in (1000.0, 2700.0, 3600.0):
        scale = fusion.metres_per_width(z, 525.0)
        e = gestures.Engine()
        run(e, [(i / 30, [dict(far_hand(0.5, 0.5, z))]) for i in range(30)])
        assert e.engaged, z
        dx = 0.20 / scale                                      # 20 cm to the right, in 1 s
        state = None
        for i in range(45):
            state = e.step(1.0 + i / 30, [far_hand(0.5 + dx * min(1.0, i / 30), 0.5, z)])
        moved[z] = state["cursor"]["x"] - 0.5
    check("20 cm of arm movement moves the pointer the same at 1 m, 2.7 m and 3.6 m",
          max(moved.values()) - min(moved.values()) < 0.01 and 0.4 < moved[2700.0] < 0.5, moved)
    e = gestures.Engine()
    run(e, [(i / 30, [far_hand(0.5, 0.5)]) for i in range(30)])
    check("... the whole screen is box_metres (45 cm) of arm sweep",
          abs(e.box()[0] * fusion.metres_per_width(2700, 525.0) - 0.45) < 0.01, e.box())

    import random
    rnd = random.Random(4)
    spread = {}
    for fused in (False, True):
        e = gestures.Engine()
        xs = []
        for i in range(120):
            jx, jy = rnd.gauss(0, 1.5 / 640), rnd.gauss(0, 1.5 / 480)   # the whole hand wobbles
            h = far_hand(0.5 + jx, 0.5 + jy)
            for p in h["lm"]:
                p[0] += rnd.gauss(0, 0.8 / 640)
                p[1] += rnd.gauss(0, 0.8 / 480)
            if fused:
                h["palm"] = [0.5 + rnd.gauss(0, 0.35 / 640), 0.5 + rnd.gauss(0, 0.35 / 480)]
            state = e.step(i / 30, [h])
            if state["engaged"] and i > 40:
                xs.append(state["cursor"]["x"] * 1920)
        mean = sum(xs) / len(xs)
        spread[fused] = (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5
    check("a still hand 2.7 m away: the pointer is steadier on depth's palm than on landmarks",
          spread[True] < 0.4 * spread[False] and spread[True] < 4,
          {k: round(v, 1) for k, v in spread.items()})


def depth_only(cx, cy, z=2700.0, t=None):
    return {"side": "Right", "lm": None, "pose": "open", "palm": [cx, cy], "depth": z,
            "size": fusion.hand_px(z, 525.0) / 480, "scale": fusion.metres_per_width(z, 525.0),
            "source": "depth"}


def check_depth_only():
    print("A hand found by depth alone (too dark even for infrared)")
    e = gestures.Engine()
    events, state = run(e, [(i / 30, [depth_only(0.5, 0.5)]) for i in range(30)])
    check("held still: engages", e.engaged and "engage" in events, events)
    check("the shell gets its palm and no skeleton",
          state["hands"][0]["pts"] == [] and state["hands"][0]["palm"] == [0.5, 0.5]
          and state["hands"][0]["source"] == "depth", state["hands"])
    _, state = run(e, [(1 + i / 30, [depth_only(0.5 + 0.004 * i, 0.5)]) for i in range(20)])
    check("moving it moves the pointer", state["cursor"]["x"] > 0.6, state["cursor"])
    frames = [(2 + i / 30, [depth_only(0.576, 0.5, 2700 - (40 * i if i < 4 else 160))])
              for i in range(10)]
    events, _ = run(e, frames)
    check("pushing it toward the TV clicks", "push" in events and "click" in events, events)
    events, _ = run(e, [(4 + i / 30, [depth_only(0.576, 0.5, 2540)]) for i in range(30)])
    check("no fingers, so never a pinch or a grab", not {"press", "grab"} & set(events), events)
    events, _ = run(e, [(6 + i / 30, []) for i in range(30)])
    check("gone: disengages", "disengage" in events and not e.engaged, events)


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
               "throw-down", "carry-left", "carry-right", "swipe-left", "swipe-right", "spread", "collapse",
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
    want = ["engage", "press", "release", "click", "right-click", "scroll", "zoom", "scroll",
            "zoom", "grab",
            "resize-start", "resize-end", "drop", "throw-right", "swipe-left", "swipe-right",
            "zoom", "spread", "collapse", "disengage"]
    check("the demo plays every gesture, in order", names == want, names)
    zooms = [ev["steps"] for ev in events if ev["type"] == "zoom"]
    scrolls = [ev for ev in events if ev["type"] == "scroll"]
    check("its wave down scrolls up a chunk", scrolls[0].get("wave") == "down" and scrolls[0]["dy"] < 0,
          scrolls[:2])
    check("its zooms: the L and the V sign zoom in, two hands zoom in and back out",
          all(z > 0 for z in zooms[:5]) and any(z < 0 for z in zooms[5:]), zooms)


def check_hub():
    print("Kinect hub (frames, helpers, HTTP)")
    import asyncio
    import time
    import struct as st

    import numpy as np

    import frames
    import kinect_hub as hub_mod
    where = Path(tempfile.mkdtemp()) / "frames"
    w = frames.Writer(where)
    rgb = np.zeros((480, 640, 3), np.uint8)
    rgb[:, :, 0] = 200
    depth = np.full((480, 640), 1500, np.uint16)
    depth[:240] = 0
    w.write(rgb, depth, "ir", (10, 819, -5), 4.5, 29.7)
    r = frames.Reader(where)
    got_rgb, got_depth, head = r.read(timeout=0.5)
    check("a frame goes through shared memory whole",
          np.array_equal(got_rgb, rgb) and np.array_equal(got_depth, depth)
          and head["mode"] == "ir" and head["accel"] == [10, 819, -5] and head["frames"] == 1, head)
    try:
        r.read(timeout=0.05)
        check("a reader waits for a newer frame", False)
    except OSError:
        check("a reader waits for a newer frame", True)
    check("a reader marks itself seen (the hub stays up for it)", w.client_seen() > 0)
    check("the store is private to this user", (where.stat().st_mode & 0o777) == 0o600)
    r.close()
    w.close()
    check("the hub removes the store when it stops", not where.exists())

    check("level and upright: pitch 0, roll 0", hub_mod.angles([0, 819, 0]) == (0.0, 0.0))
    p, rl = hub_mod.angles([0, 579, 579])
    check("tipped forward 45 degrees reads as pitch 45", abs(p - 45) < 0.5 and abs(rl) < 0.5, (p, rl))
    stats = hub_mod.depth_stats(depth)
    check("depth stats: half the picture has no reading, the rest is 1.5 m",
          abs(stats["valid"] - 50) < 1 and stats["nearest"] == 1500 == stats["median"]
          and len(stats["hist"]) == 32 and max(stats["hist"]) == 1.0, stats)
    xyz, col = hub_mod.point_cloud(rgb, depth, step=4)
    check("point cloud: one point per valid sampled pixel, in metres",
          len(xyz) == 120 * 160 // 2 and abs(float(xyz[:, 2].mean()) - 1.5) < 1e-4
          and col.shape == (len(xyz), 3) and int(col[0, 0]) == 200, len(xyz))
    centre = hub_mod.point_cloud(rgb, np.where(np.arange(640)[None, :] == 320, 2000, 0)
                                 .astype(np.uint16).repeat(480, 0), step=1)[0]
    check("point cloud: the middle column is straight ahead (x ~ 0)",
          abs(float(centre[:, 0].mean())) < 0.01, float(centre[:, 0].mean()))
    blob = hub_mod.cloud_bytes(xyz, col, 7)
    n, seq = st.unpack("<II", blob[:8])
    check("the cloud's wire format: count, seq, xyz, rgb", n == len(xyz) and seq == 7
          and len(blob) == 8 + n * 15)
    ply = hub_mod.ply_bytes(xyz, col)
    check("a PLY export with a header and every point",
          ply.startswith(b"ply\nformat binary_little_endian 1.0") and
          f"element vertex {len(xyz)}".encode() in ply and len(ply.split(b"end_header\n", 1)[1]) == 15 * len(xyz))
    img = hub_mod.colour_depth(depth)
    check("depth colours: no reading is black", img.shape == (480, 640, 3) and not img[0].any()
          and img[300].any())

    d = Path(tempfile.mkdtemp())
    for name, label in (("video10", "Phone Camera"), ("video11", "Kinect Camera")):
        (d / name).mkdir()
        (d / name / "name").write_text(label + "\n")
    check("the webcam is the loopback device named Kinect Camera",
          hub_mod.find_webcam(sysfs=str(d)) == "/dev/video11")
    check("no Kinect Camera device: no webcam", hub_mod.find_webcam(sysfs=str(d / "none")) is None)
    for name, label in (("video10", 'Phone Camera"'), ("video11", '"Kinect Camera')):   # the old modprobe line's names
        (d / name / "name").write_text(label + "\n")
    check("the webcam is found by its name even with the stray quotes of the old install line",
          hub_mod.find_webcam(sysfs=str(d)) == "/dev/video11")

    # The HTTP side against a stand-in hub (no Kinect).
    from aiohttp.test_utils import TestClient, TestServer

    class Stub(hub_mod.Hub):
        def __init__(self):
            super().__init__({})
            self.rgb, self.depth, self.seq = rgb, depth, 2
            self.snap = frames.Snapshot(rgb, depth, "rgb", kinect.intrinsics("rgb"), 2, time.time(),
                                        time.monotonic())
            self.status = "streaming"
            self.sent = []

        def command(self, name, value):
            self.sent.append((name, value))

        def people_watch(self, seconds=3.0):         # no pose model in the check
            self.watched = seconds
            if self.people_seq == 0:
                self._publish({"count": 1, "standing": 1, "running": True, "people": [{"id": 1}]})

    stub = Stub()

    async def go():
        client = TestClient(TestServer(hub_mod.make_app(stub)))
        await client.start_server()
        try:
            out = {}
            res = await client.get("/api/status")
            out["status"] = (res.status, (await res.json())["status"])
            res = await client.get("/frame/video.jpg")
            out["video"] = (res.status, res.headers.get("Content-Type"), res.headers.get("X-Seq"),
                            (await res.read())[:2])
            res = await client.get("/frame/depth.jpg")
            out["depth"] = res.status
            res = await client.get("/frame/secret.jpg")
            out["unknown"] = res.status
            res = await client.get("/cloud.bin?step=4")
            out["cloud"] = len(await res.read())
            res = await client.get("/cloud.ply")
            out["ply"] = (res.status, "attachment" in res.headers.get("Content-Disposition", ""))
            res = await client.post("/api/tilt", json={"value": 12})
            out["tilt"] = res.status
            res = await client.post("/api/reboot", json={"value": 1})
            out["reboot"] = res.status
            res = await client.get("/")
            out["page"] = "Kinect Studio" in await res.text()
            res = await client.get("/api/people?after=0")
            body = await res.json()
            out["people"] = (res.status, body.get("count"), body.get("seq"))
            res = await client.get("/studio/studio.css")
            out["css"] = res.status
            res = await client.get("/depth-scale.png")
            out["scale"] = (await res.read())[:4]
            return out
        finally:
            await client.close()
    out = asyncio.run(go())
    check("status answers JSON", out["status"] == (200, "streaming"), out["status"])
    check("the colour view is a JPEG with its frame number",
          out["video"] == (200, "image/jpeg", "2", b"\xff\xd8"), out["video"])
    check("the depth view answers; unknown views do not",
          out["depth"] == 200 and out["unknown"] == 404, (out["depth"], out["unknown"]))
    check("the point cloud answers in its wire format", out["cloud"] == len(blob), out["cloud"])
    check("the PLY export downloads", out["ply"] == (200, True), out["ply"])
    check("controls reach the hub; unknown ones are refused",
          out["tilt"] == 200 and stub.sent == [("tilt", 12)] and out["reboot"] == 404,
          (out["tilt"], stub.sent, out["reboot"]))
    check("person boxes: overlap and inside", abs(hub_mod.iou((0, 0, 2, 2), (1, 0, 3, 2)) - 1 / 3) < 1e-9
          and hub_mod.iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0 and hub_mod.inside((1, 1), (0, 0, 2, 2)))
    check("/api/people answers everyone in view, with its number, and keeps the tracker running",
          out["people"] == (200, 1, 1) and getattr(stub, "watched", 0) > 0, out["people"])
    check("the Studio page, its stylesheet and the depth scale are served",
          out["page"] and out["css"] == 200 and out["scale"] == b"\x89PNG", out)
    page = (HERE_AIR / "studio/studio.js").read_text()
    for path in ("/frame/", "/cloud.bin", "/api/status", "/api/led", "/api/tilt", "/api/measure", "/api/people", "/presence"):
        check(f"the page uses {path}", path.split("/api/")[-1] in page or path in page)


def scene(person_height=1.78, distance=2.8, camera_height=1.92, pitch=12.0, radius=0.2,
          person=True, floor=True):
    """A depth frame (mm) of a person (a cylinder) standing on a floor, seen by a Kinect mounted
    camera_height up and pitched `pitch` degrees down; and its accelerometer reading and the
    pixel on the person's torso."""
    import numpy as np
    th = math.radians(pitch)
    xc = np.array([1.0, 0.0, 0.0])
    zc = np.array([0.0, -math.sin(th), math.cos(th)])
    yc = np.array([0.0, -math.cos(th), -math.sin(th)])
    v, u = np.mgrid[0:480, 0:640]
    dx, dy = (u - 319.5) / 525.0, (v - 239.5) / 525.0
    dw = dx[..., None] * xc + dy[..., None] * yc + zc              # world ray per pixel, z_cam = 1
    oy = camera_height
    t = np.full(u.shape, np.inf)
    if floor:
        with np.errstate(divide="ignore", invalid="ignore"):
            tf = np.where(dw[..., 1] < -1e-6, -oy / dw[..., 1], np.inf)
        t = np.minimum(t, tf)
    if person:
        a = dw[..., 0] ** 2 + dw[..., 2] ** 2
        b = -2 * distance * dw[..., 2]
        c = distance ** 2 - radius ** 2
        disc = b * b - 4 * a * c
        with np.errstate(invalid="ignore"):
            tc = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a)
        yh = oy + tc * dw[..., 1]
        tc = np.where((disc > 0) & (yh >= 0) & (yh <= person_height), tc, np.inf)
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = (person_height - oy) / dw[..., 1]
        px, pz = tt * dw[..., 0], tt * dw[..., 2] - distance
        tt = np.where((tt > 0) & (px ** 2 + pz ** 2 <= radius ** 2), tt, np.inf)
        t = np.minimum(t, np.minimum(tc, tt))
    rng = np.random.default_rng(1)
    depth = np.where(np.isfinite(t), t * 1000 + rng.normal(0, 4, t.shape), 0)
    depth = np.where((depth > 450) & (depth < 6000), depth, 0).astype(np.uint16)
    up = np.array([0.0, -math.cos(th), -math.sin(th)])            # up in camera coordinates
    accel = (-up[0] * 819, -up[1] * 819, up[2] * 819)
    torso = np.array([0.0, 1.1 - oy, distance - radius])          # world, relative to the camera
    cam = np.array([torso @ xc, torso @ yc, torso @ zc])
    seed = (319.5 + 525 * cam[0] / cam[2], 239.5 + 525 * cam[1] / cam[2])
    return depth, accel, seed


def check_height():
    print("How tall am I (measure.py)")
    import measure
    depth, accel, seed = scene()
    r = measure.measure(depth, accel, seed)
    check("a 1.78 m person 2.8 m away, Kinect on the TV: measured within 3 cm",
          r["ok"] and abs(r["height"] - 1.78) < 0.03 and r["floor"] == "seen", r)
    check("... and the Kinect's own height comes out of the floor",
          r["ok"] and abs(r["camera_height"] - 1.92) < 0.03, r)
    check("... and how far away they stand, across the floor", r["ok"] and abs(r["distance"] - 2.68) < 0.1, r)
    depth, accel, seed = scene(person_height=1.62, distance=3.4, pitch=8)
    r = measure.measure(depth, accel, seed)
    check("a 1.62 m person 3.4 m away, less tilt", r["ok"] and abs(r["height"] - 1.62) < 0.03, r)
    depth, accel, seed = scene(floor=False)
    r = measure.measure(depth, accel, seed, mount_height=1.92)
    check("no floor in view: the mount height stands in", r["ok"] and r["floor"] == "mount"
          and abs(r["height"] - 1.78) < 0.04, r)
    depth, accel, seed = scene(distance=1.2, camera_height=1.0, pitch=0)
    r = measure.measure(depth, accel, seed, mount_height=1.0)
    check("Kinect lower, standing close (head out of view): asks to step back", not r["ok"] and "Step back" in r["error"], r)
    depth, accel, seed = scene(person=False)
    r = measure.measure(depth, accel, seed)
    check("nobody there: says so", not r["ok"], r)
    runs = [measure.measure(*scene(person_height=1.78 + 0.004 * k)) for k in (-1, 0, 1, 0, 1)]
    summary = measure.summarise(runs)
    check("several frames: the median, in metres and feet and inches",
          summary["ok"] and abs(summary["height"] - 1.78) < 0.03 and
          (summary["feet"], summary["inches"]) == (5, 10), summary)
    check("Mario's sentence", measure.say(summary).startswith("You're 1.7") and "5 foot 10" in measure.say(summary),
          measure.say(summary))


def room(bodies, camera_height=1.92, pitch=12.0, floor=True, seed=1):
    """A depth frame of several people (cylinders: (x, distance, height, radius)) on a floor, the
    accelerometer, each person's own mask, and the camera basis (for posing stick figures)."""
    import numpy as np
    th = math.radians(pitch)
    xc = np.array([1.0, 0.0, 0.0])
    zc = np.array([0.0, -math.sin(th), math.cos(th)])
    yc = np.array([0.0, -math.cos(th), -math.sin(th)])
    v, u = np.mgrid[0:480, 0:640]
    dx, dy = (u - 319.5) / 525.0, (v - 239.5) / 525.0
    dw = dx[..., None] * xc + dy[..., None] * yc + zc
    oy = camera_height
    t = np.full(u.shape, np.inf)
    who = np.full(u.shape, -1)
    if floor:
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(dw[..., 1] < -1e-6, -oy / dw[..., 1], np.inf)
    for k, (bx, dist, height, radius) in enumerate(bodies):
        ex, ez = dw[..., 0], dw[..., 2]
        a = ex ** 2 + ez ** 2
        b = -2 * (bx * ex + dist * ez)
        c = bx ** 2 + dist ** 2 - radius ** 2
        disc = b * b - 4 * a * c
        with np.errstate(invalid="ignore"):
            tc = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a)
        yh = oy + tc * dw[..., 1]
        tc = np.where((disc > 0) & (yh >= 0) & (yh <= height), tc, np.inf)
        with np.errstate(divide="ignore", invalid="ignore"):
            tt = (height - oy) / dw[..., 1]
        px, pz = tt * ex - bx, tt * ez - dist
        tt = np.where((tt > 0) & (px ** 2 + pz ** 2 <= radius ** 2), tt, np.inf)
        tk = np.minimum(tc, tt)
        closer = tk < t
        who = np.where(closer, k, who)
        t = np.where(closer, tk, t)
    rng = np.random.default_rng(seed)
    depth = np.where(np.isfinite(t), t * 1000 + rng.normal(0, 4, t.shape), 0)
    depth = np.where((depth > 450) & (depth < 6000), depth, 0).astype(np.uint16)
    up = np.array([0.0, -math.cos(th), -math.sin(th)])
    accel = (-up[0] * 819, -up[1] * 819, up[2] * 819)
    masks = [(who == k).astype(np.float32) for k in range(len(bodies))]
    return depth, accel, masks, (xc, yc, zc, oy)


def figure(basis, bx, dist, height, posture="standing", mask=None):
    """A people.Pose of a stick figure standing (or sitting, crouching...) at (bx, dist)."""
    import numpy as np
    import people
    xc, yc, zc, oy = basis
    H = height
    front = dist - 0.2                               # the front of the body, towards the camera
    J = {}
    def put(i, x, y, z=0.0):
        J[i] = np.array([bx + x, y, front + z])     # world: x right, y up, z away from camera
    legs = {"standing": (0.53, 0.28, 0, 0), "bending": (0.53, 0.28, 0, 0),
            "arms-up": (0.53, 0.28, 0, 0), "leaning": (0.53, 0.28, 0, 0)}
    if posture in legs or posture == "lying":
        hip, knee = 0.53 * H, 0.28 * H
        for s, x in ((1, 0.1), (-1, -0.1)):
            put(23 if s > 0 else 24, x, hip); put(25 if s > 0 else 26, x, knee); put(27 if s > 0 else 28, x, 0.08)
        tilt = {"bending": 55, "leaning": 20, "lying": 85}.get(posture, 0)
    elif posture == "sitting":
        hip = 0.48
        for s, x in ((1, 0.1), (-1, -0.1)):
            put(23 if s > 0 else 24, x, hip); put(25 if s > 0 else 26, x, 0.52, -0.42); put(27 if s > 0 else 28, x, 0.08, -0.45)
        tilt = 5
    elif posture == "crouching":
        hip = 0.42
        for s, x in ((1, 0.12), (-1, -0.12)):
            put(23 if s > 0 else 24, x, hip); put(25 if s > 0 else 26, x, 0.5, -0.35); put(27 if s > 0 else 28, x, 0.08, -0.15)
        tilt = 25
    if posture == "lying":                           # lying along the floor
        for i in (23, 24, 25, 26, 27, 28):
            J[i][1] = 0.15
    r = math.radians(tilt)
    def torso(i, x, along):
        J[i] = np.array([bx + x, hip + along * math.cos(r), front - along * math.sin(r)])
    torso(11, 0.19, 0.29 * H); torso(12, -0.19, 0.29 * H)
    torso(0, 0, 0.39 * H); torso(2, 0.03, 0.405 * H); torso(5, -0.03, 0.405 * H)
    torso(7, 0.07, 0.40 * H); torso(8, -0.07, 0.40 * H)
    torso(1, 0.02, 0.405 * H); torso(3, 0.04, 0.405 * H); torso(4, -0.02, 0.405 * H); torso(6, -0.04, 0.405 * H)
    torso(9, 0.02, 0.37 * H); torso(10, -0.02, 0.37 * H)
    if posture == "arms-up":
        torso(13, 0.22, 0.45 * H); torso(14, -0.22, 0.45 * H); torso(15, 0.2, 0.55 * H); torso(16, -0.2, 0.55 * H)
    else:
        torso(13, 0.24, 0.12 * H); torso(14, -0.24, 0.12 * H); torso(15, 0.25, -0.05 * H); torso(16, -0.25, -0.05 * H)
    for i in range(17, 23):
        J[i] = J[15 if i % 2 else 16].copy()
    for i in (29, 31):
        J[i] = J[27] + np.array([0, -0.05, -0.08])
    for i in (30, 32):
        J[i] = J[28] + np.array([0, -0.05, -0.08])
    image, world = [], []
    for i in range(33):
        w = J[i]
        rel = np.array([w[0], w[1] - oy, w[2]])
        cam = np.array([rel @ xc, rel @ yc, rel @ zc])
        image.append((319.5 + 525 * cam[0] / cam[2]) / 640), image.append((239.5 + 525 * cam[1] / cam[2]) / 480)
        world.append(cam)
    image = np.array(image).reshape(33, 2)
    world = np.array(world)
    world -= (world[23] + world[24]) / 2
    image = np.hstack([image, np.full((33, 1), 0.95)])
    return people.Pose(image, world, mask)


def check_people():
    print("Everyone in view (people.py)")
    import measure
    import numpy as np
    import people
    intr = (525.0, 525.0, 319.5, 239.5)

    def frame(spec, **kw):
        bodies = [(x, d, h if p in ("standing", "arms-up", "leaning") else
                   {"sitting": 1.3, "crouching": 1.05, "bending": 1.25, "lying": 0.35}.get(p, h), 0.2)
                  for x, d, h, p in spec]
        depth, accel, masks, basis = room(bodies, **kw)
        poses = [figure(basis, x, d, h, p, masks[k]) for k, (x, d, h, p) in enumerate(spec)]
        import measure
        return poses, depth, measure.up_vector(accel)

    poses, depth, up = frame([(-0.7, 2.8, 1.78, "standing"), (0.6, 3.2, 1.62, "standing")])
    seen, floor = people.observe(poses, depth, up, 1.92, intr)
    check("the floor plane is fitted: the Kinect's height and tilt come out of it",
          floor.seen and abs(floor.camera_height - 1.92) < 0.02 and abs(floor.to_dict()["tilt"] - 12) < 1,
          floor.to_dict())
    check("two people side by side: two people, each with their own height",
          len(seen) == 2 and abs(seen[0]["top"] - 1.78) < 0.03 and abs(seen[1]["top"] - 1.62) < 0.03,
          [round(o["top"], 3) for o in seen])
    check("... both standing straight",
          all(o["posture"] == "standing" and o["straight"] for o in seen),
          [(o["posture"], o["hint"]) for o in seen])
    check("... with an outline, a head and a floor point for the ruler",
          all(len(o["outline"]) == people.OUTLINE_POINTS and o["head"] and o["foot"] and o["ring"]
              for o in seen) and all(o["foot"][1] > o["head"][1] for o in seen))

    # A person on the TV: flat, and far too small for how far away the screen is.
    depth, accel, masks, basis = room([(0.0, 3.0, 1.78, 0.2)])
    tv = figure(basis, 0.0, 3.0, 1.78, "standing", masks[0])
    flat = depth.copy()
    flat[masks[0] > 0] = 3500                       # the same picture, painted on a wall
    seen, _ = people.observe([tv], flat, measure.up_vector(accel), 1.92, intr)
    check("a person on a flat screen is not counted", not seen, len(seen))
    small = people.Pose(tv.image.copy(), tv.world, tv.mask)
    small.image[11, 0] = small.image[12, 0] + 0.02   # shoulders 13 px apart at 2.8 m
    seen, _ = people.observe([small], depth, measure.up_vector(accel), 1.92, intr)
    check("a person far too small for their distance is not counted", not seen, len(seen))

    # The accelerometer 5 degrees out, and the Kinect moved to a desk (settings still say the TV).
    bodies = [(0.0, 3.0, 1.74, 0.2)]
    depth, accel, masks, basis = room(bodies, camera_height=0.8, pitch=4)
    off = math.radians(5)
    skew = np.array([[1, 0, 0], [0, math.cos(off), -math.sin(off)], [0, math.sin(off), math.cos(off)]])
    pose = figure(basis, 0.0, 3.0, 1.74, "standing", masks[0])
    seen, floor = people.observe([pose], depth, skew @ measure.up_vector(accel), 1.92, intr)
    check("Kinect moved and its accelerometer 5 degrees out: the floor plane still gives 1.74 m",
          floor.seen and abs(floor.camera_height - 0.8) < 0.03 and seen and abs(seen[0]["top"] - 1.74) < 0.03,
          (floor.to_dict(), seen and round(seen[0]["top"], 3)))
    depth, accel, masks, basis = room(bodies, floor=False)
    seen, floor = people.observe([figure(basis, 0.0, 3.0, 1.74, "standing", masks[0])], depth,
                                 measure.up_vector(accel), 1.92, intr)
    check("no floor in view: the mount height stands in", not floor.seen and seen
          and abs(seen[0]["top"] - 1.74) < 0.04, (floor.to_dict(), seen and seen[0]["top"]))

    spec = [(-1.1, 3.0, 1.75, "standing"), (-0.2, 2.6, 1.70, "sitting"), (0.6, 3.0, 1.70, "crouching"),
            (1.4, 3.4, 1.70, "bending")]
    poses, depth, up = frame(spec)
    seen, _ = people.observe(poses, depth, up, 1.92, intr)
    got = sorted([(round(o["centre_x"], 2), o["posture"]) for o in seen])
    check("four people: standing, sitting, crouching, bending over",
          [p for _, p in got] == ["standing", "sitting", "crouching", "bending"], got)
    for posture, hint in (("arms-up", "Lower your arms"), ("leaning", "Stand up straight")):
        poses, depth, up = frame([(0, 2.8, 1.78, posture)])
        seen, _ = people.observe(poses, depth, up, 1.92, intr)
        check(f"standing but {posture}: not straight, and told '{hint}'",
              seen and seen[0]["posture"] == "standing" and not seen[0]["straight"]
              and seen[0]["hint"] == hint, seen and (seen[0]["posture"], seen[0]["hint"]))
    check("lying down", people.classify({"torso": 85, "legs": True, "thigh": 88, "knee": 175}) == "lying")
    check("legs hidden behind a table, hips high: standing; hips low: sitting",
          people.classify({"torso": 4, "legs": False, "hip_h": 0.95}) == "standing"
          and people.classify({"torso": 4, "legs": False, "hip_h": 0.5}) == "sitting")
    check("kneeling", people.classify({"torso": 5, "legs": True, "thigh": 10, "knee": 95,
                                       "knee_h": 0.1, "hip_h": 0.6}) == "kneeling")

    # Over time: numbers stay with people, a height only after a second of standing straight.
    tracker = people.People()
    spec = [(-0.7, 2.8, 1.78, "standing"), (0.6, 3.0, 1.70, "sitting")]
    t = 0.0
    state = None
    for k in range(20):
        poses, depth, up = frame(spec, seed=k)
        state = tracker.step(poses, depth, up, 1.92, intr, t)
        if k == 2:
            early = state
        t += 1 / 15
    by_x = state["people"]
    check("the count, and how many stand", state["count"] == 2 and state["standing"] == 1,
          (state["count"], state["standing"]))
    check("no height before a second of standing straight",
          early["people"][0]["height_cm"] is None and 0 < early["people"][0]["measuring"] < 1,
          early["people"][0]["measuring"])
    check("after it: 178 cm for the one standing; the one sitting is asked to stand",
          abs(by_x[0]["height_cm"] - 178) <= 2 and by_x[1]["height_cm"] is None
          and by_x[1]["posture"] == "sitting" and "Stand up" in by_x[1]["hint"],
          [(p["height_cm"], p["posture"], p["hint"]) for p in by_x])
    check("each keeps their number and colour", [p["id"] for p in by_x] == [1, 2]
          and len({p["colour"] for p in by_x}) == 2)
    sentence = people.say(state)
    check("Mario says how many, who stands, the height, and asks the other to stand",
          "2 people" in sentence and "1 standing" in sentence and "1 sitting" in sentence
          and str(by_x[0]["height_cm"]) in sentence and "stand up straight" in sentence, sentence)
    check("one person sitting: asked to stand up straight",
          "stand up straight" in people.say({"people": [{"height_cm": None, "posture": "sitting",
                                                         "hint": "x"}]}))
    check("nobody: says so", "can't see anyone" in people.say({"people": []}))
    check("feet and inches", people.feet_inches(178) == (5, 10) and people.feet_inches(152) == (5, 0))


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


def check_pairing():
    """Frames: a picture is published only with the depth taken with it, as one snapshot."""
    print("Frames: pairing, snapshots, the activity hold and the scan lease")
    import time

    import numpy as np

    import frames
    import kinect_hub as hub_mod
    gap = kinect.tick_gap
    check("device clock difference, both ways", gap(3_000_000, 1_000_000) == 2_000_000 and gap(1, 2_000_001) == -2_000_000)
    check("... across the 32-bit wrap", gap(500, 0xFFFFFFFF - 499) == 1000)
    check("a normal colour + depth pair (measured: 3.1 M ticks apart) is paired",
          kinect.paired(1_043_050_578, 1_046_188_534))
    check("the first pair after a switch (measured: 31 M ticks apart) is not",
          not kinect.paired(1_013_046_265, 1_044_186_379))
    snap = frames.Snapshot(np.zeros((480, 640, 3), np.uint8), np.zeros((480, 640), np.uint16), "ir",
                           kinect.intrinsics("ir"), 42, 1000.5, 7.0, epoch=3)
    m = snap.meta()
    check("a snapshot carries its own mode, lens numbers, frame and epoch",
          m["mode"] == "ir" and m["intrinsics"][0] == 575.8 and m["frame"] == 42 and m["epoch"] == 3)
    d = Path(tempfile.mkdtemp())
    w = frames.Writer(d / "f")
    w.write(snap.rgb, snap.depth, "ir", epoch=5)
    r = frames.Reader(d / "f")
    _, _, head = r.read(timeout=0.5)
    check("the shared frame store carries the epoch", head["epoch"] == 5 and head["mode"] == "ir", head)
    r.close()
    w.close()

    # Depth-supported foreground in a pose crop: what is far behind the person is greyed out.
    src = object.__new__(hub_mod.PoseSource)
    src.last_ts, src.ts_lock = 0, __import__("threading").Lock()
    pic = np.full((480, 640, 3), 200, np.uint8)
    dep = np.full((480, 640), 4000, np.uint16)                  # a wall 4 m away
    dep[100:400, 280:360] = 2500                                 # the person at 2.5 m
    dep[150:200, 300:340] = 0                                    # dark hair: no reading
    f = {"box": (260, 90, 380, 410), "ts": 0, "z": 2500.0}
    job = src._crop(f, pic, dep, 640, 480)
    crop, sx = job["crop"], int(320 - job["crop"].shape[1] / 2)
    S = job["crop"].shape[0]
    sy0 = int(250 - S / 2)
    check("pose crop: the person kept, the wall behind greyed out, no-reading kept",
          (crop[250 - sy0, 320 - sx] == 200).all() and (crop[250 - sy0, 270 - sx] == 128).all()
          and (crop[175 - sy0, 320 - sx] == 200).all())
    check("the torso's depth is read as a robust median", abs(hub_mod.torso_depth(dep, (320, 300)) - 2500) < 1)

    hub = hub_mod.Hub({})
    now = time.monotonic()
    check("no activity: colour checks allowed", not hub._busy(now))
    hub.command("activity", 4)
    check("a live workout holds off colour checks", hub._busy(time.monotonic()))
    hub.command("activity", 999)
    check("... for at most ten seconds a request", hub.activity_until - time.monotonic() <= 10.01)
    hub.command("activity", 0)
    check("... and lets go", not hub._busy(time.monotonic()))
    hub.command("lease", {"owner": "scan", "mode": "ir", "seconds": 30})
    check("a scan leases the infrared picture", hub._leased() and hub.lease["mode"] == "ir"
          and ("force", "ir") in list(hub.commands.queue))
    hub.command("video", "rgb")
    hub._apply(type("Cam", (), {})())
    check("... a mode change asked for during the lease waits", hub.mode == "ir", hub.mode)
    hub.command("lease", None)
    check("... released", not hub._leased())
    hub.lease = {"owner": "scan", "mode": "ir", "until": time.monotonic() - 1}
    check("an expired lease is let go by itself", not hub._leased())


def check_identity():
    """People keep their numbers through crossings and short occlusions (people.People.track),
    from synthetic observations: two people who walk past each other, stop and turn back, look
    alike, or hide behind each other. The right answer is known for every frame."""
    print("Identity: crossings, occlusion, look-alikes (people.py)")
    import numpy as np

    import people as P

    def body(x, z, height=1.75, shoulders=0.40, limb=1.0):
        j = np.full((33, 3), np.nan)
        st = np.zeros(33, np.int8)
        hip_y, sh_y = 0.52 * height, 0.82 * height
        pts = {P.L_SH: (-shoulders / 2, sh_y), P.R_SH: (shoulders / 2, sh_y),
               P.L_EL: (-shoulders / 2 - 0.02, sh_y - 0.29 * limb), P.R_EL: (shoulders / 2 + 0.02, sh_y - 0.29 * limb),
               P.L_WR: (-shoulders / 2 - 0.03, sh_y - 0.54 * limb), P.R_WR: (shoulders / 2 + 0.03, sh_y - 0.54 * limb),
               P.L_HIP: (-0.10, hip_y), P.R_HIP: (0.10, hip_y),
               P.L_KNEE: (-0.11, hip_y - 0.24 * height * limb), P.R_KNEE: (0.11, hip_y - 0.24 * height * limb),
               P.L_ANK: (-0.11, 0.06), P.R_ANK: (0.11, 0.06)}
        for i, (dx, y) in pts.items():
            j[i], st[i] = (x + dx, y, z), P.TRACKED
        return {"pos": np.array([x, 0.0, z]), "joints": j, "jstate": st, "top": height,
                "posture": "standing", "straight": True, "hint": "", "distance": z,
                "features": {}, "outline": [], "box": [0, 0, 1, 1], "head": None, "foot": None,
                "ring": [], "skeleton": [[0.5, 0.5, 1.0]] * 33, "centre_x": 0.5 + x / 4}

    def ids_at(state, xs):
        """The id of whoever is nearest each x (in the state's own people)."""
        out = []
        for x in xs:
            p = min(state["people"], key=lambda q: abs(q["x"] - (0.5 + x / 4)))
            out.append(p["id"])
        return out

    # The optimal assignment, not nearest-first: greedy would give track 0 its nearest (0.1)
    # and leave track 1 with nothing within reach.
    check("global assignment beats nearest-first", P.assign([[0.1, 0.3], [0.2, None]]) == {0: 1, 1: 0})
    check("nothing within reach stays unmatched", P.assign([[None], [None]]) == {})

    def walk(a, b, frames=60, fps=15.0, turn_back=False, hide=None):
        """Person A from x=-1 to +1, person B the other way, at z = 2.5 m; -> (tracker, states)."""
        tr, states = P.People(), []
        for k in range(frames):
            t = k / fps
            f = k / (frames - 1)
            xa, xb = -1.0 + 2.0 * f, 1.0 - 2.0 * f
            if turn_back and f > 0.5:             # both stop in the middle and go back
                xa, xb = -1.0 + 2.0 * (1 - f), 1.0 - 2.0 * (1 - f)
            seen = [body(xa, 2.5 + 0.05, **a), body(xb, 2.5 - 0.05, **b)]
            if hide and hide[0] <= k < hide[1]:
                seen = seen[:1]                    # B hidden behind A
            states.append(tr.track(seen, t))
        return tr, states

    tall, short = {"height": 1.86, "shoulders": 0.44}, {"height": 1.62, "shoulders": 0.35}
    tr, st = walk(tall, short)
    first, last = st[2], st[-1]
    a0, b0 = ids_at(first, [-0.95, 0.95])
    a1, b1 = ids_at(last, [1.0, -1.0])
    check("two people cross: each keeps their number", (a1, b1) == (a0, b0), (a0, b0, a1, b1))
    check("... and nobody else appears", tr.next_id == 3, tr.next_id)
    check("... sure of both once apart", all(p["identity"] == "sure" for p in last["people"]),
          [p["identity"] for p in last["people"]])

    tr, st = walk(tall, short, turn_back=True)
    a0, b0 = ids_at(st[2], [-0.95, 0.95])
    a1, b1 = ids_at(st[-1], [-1.0, 1.0])
    retired = {r["id"] for s in st for r in s["retired"]}
    check("meet half way and turn back (velocity says they swapped): a tall and a short person keep "
          "their numbers, by their bodies", (a1, b1) == (a0, b0) and not retired, (a0, b0, a1, b1, retired))

    same = {"height": 1.75, "shoulders": 0.40}
    tr, st = walk(same, same, turn_back=True, frames=200)
    a0, b0 = ids_at(st[2], [-0.95, 0.95])
    unsure = [k for k, s in enumerate(st) if any(p["identity"] == "unsure" for p in s["people"])]
    retired = {r["id"] for s in st for r in s["retired"]}
    a1, b1 = ids_at(st[-1], [-1.0, 1.0])
    check("look-alikes who meet and turn back: marked unsure from the moment they meet",
          bool(unsure) and 90 <= unsure[0] <= 101, unsure[:1])
    check("... and once apart, both numbers retired rather than guessed",
          {a0, b0} <= retired and {a1, b1}.isdisjoint({a0, b0}), (retired, a0, b0, a1, b1))
    check("... the new numbers are sure", all(p["identity"] == "sure" for p in st[-1]["people"]))

    tr, st = walk(tall, short, hide=(20, 30))
    hidden_frames = st[20:30]
    check("hidden behind someone: not reported as present",
          all(len(s["people"]) == 1 for s in hidden_frames))
    check("... but listed as hidden, with how long ago they were seen, and no joints",
          all(len(s["hidden"]) == 1 and s["hidden"][0]["remembered"] and "joints" not in s["hidden"][0]
              for s in hidden_frames) and hidden_frames[-1]["hidden"][0]["seen_ago"] > 0.5)
    b_id = ids_at(st[5], [1.0 - 2.0 * 5 / 59])[0]
    check("... and back under their own number", b_id in [p["id"] for p in st[40]["people"]],
          (b_id, [p["id"] for p in st[40]["people"]]))
    check("counts: visible and hidden apart", st[25]["count"] == 1 and st[25]["hidden_count"] == 1)


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
    check_lzoom()
    check_room()
    check_edge()
    check_scroll()
    check_two_hands()
    check_light()
    check_fusion()
    check_metres()
    check_depth_only()
    check_probe()
    check_protocol()
    check_demo()
    check_hub()
    check_height()
    check_people()
    check_pairing()
    check_identity()
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
