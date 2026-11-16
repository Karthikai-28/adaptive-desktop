"""Air's demo: a scripted pair of hands played through the real gesture engine, no camera.

`air.py --demo` sends these frames to the shell exactly as the camera would, so the whole HUD and
every action can be seen (and checked: scripts/verify-air-nested.sh) before the Kinect has power.

    0.0  open palm held still at the centre        engage
    1.2  a small circle                             the pointer follows
    2.6  pinch and let go                           click
    3.4  fist, carry a little left, fling right     grab, throw right: the window takes the right half
    5.2  sweep left, then back right                next desktop, previous desktop
    8.0  both hands pinch and pull apart            every window (overview)
    9.8  ... and push together                      back to work
   11.6  hands drop out of view                     disengage
"""

import math

from synthetic import hand

DURATION = 13.0
FPS = 30


def _ease(f):
    return f * f * (3 - 2 * f)


def _lerp(a, b, f):
    return a + (b - a) * f


def hands_at(t):
    """The demo's hands at time t (seconds)."""
    x, y, depth = 0.5, 0.5, 900
    if t < 1.2:
        return [hand(x, y, shape="open", depth=depth)]
    if t < 2.4:
        a = (t - 1.2) / 1.2 * 2 * math.pi
        r = 0.035 * math.sin(math.pi * (t - 1.2) / 1.2)
        return [hand(x + r * math.sin(a), y - r * (1 - math.cos(a)) * 0.6, shape="open",
                     depth=depth)]
    if t < 3.4:
        shape = "pinch" if 2.6 <= t < 2.9 else "open"
        return [hand(x, y, shape=shape, depth=depth)]
    if t < 3.9:
        return [hand(x, y, shape="fist", depth=depth)]
    if t < 4.4:
        return [hand(_lerp(x, x - 0.04, _ease((t - 3.9) / 0.5)), y, shape="fist", depth=depth)]
    if t < 4.55:
        return [hand(_lerp(x - 0.04, x + 0.07, (t - 4.4) / 0.15), y, shape="fist", depth=depth)]
    x = x + 0.07
    if t < 5.6:
        return [hand(x, y, shape="open", depth=depth)]
    if t < 5.75:
        return [hand(_lerp(x, x - 0.20, (t - 5.6) / 0.15), y, shape="open", depth=depth)]
    if t < 6.8:
        return [hand(x - 0.20, y, shape="open", depth=depth)]
    if t < 6.95:
        return [hand(_lerp(x - 0.20, x, (t - 6.8) / 0.15), y, shape="open", depth=depth)]
    x = 0.5
    if t < 8.0:
        return [hand(_lerp(0.57, x, min(1.0, (t - 6.95) / 0.6)), y, shape="open", depth=depth)]

    def pair(gap, shape):
        return [hand(x + gap / 2, y, shape=shape, depth=depth, side="Right"),
                hand(x - gap / 2, y, shape=shape, depth=depth, side="Left")]
    if t < 8.3:
        return pair(0.15, "open")
    if t < 8.9:
        return pair(_lerp(0.15, 0.36, _ease((t - 8.3) / 0.6)), "pinch")
    if t < 9.8:
        return pair(0.36, "open")
    if t < 10.1:
        return pair(0.36, "pinch")
    if t < 10.7:
        return pair(_lerp(0.36, 0.11, _ease((t - 10.1) / 0.6)), "pinch")
    if t < 11.6:
        return [hand(0.5, y, shape="open", depth=depth)]
    return []


def run(emit_state, stop, loop=False, clock=None):
    """Play the demo: emit_state(state) for every frame, in real time. Returns when done/stopped."""
    import time

    import gestures
    clock = clock or time.monotonic
    while True:
        engine = gestures.Engine()
        start = clock()
        while not stop.is_set():
            t = clock() - start
            if t > DURATION:
                break
            emit_state(engine.step(t, hands_at(t)))
            stop.wait(max(0.0, 1.0 / FPS - (clock() - start - t)))
        if not loop or stop.is_set():
            return
