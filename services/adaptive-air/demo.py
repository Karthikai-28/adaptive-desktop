"""Air's demo: a scripted pair of hands played through the real gesture engine, no camera.

`air.py --demo` sends these frames to the shell exactly as the camera would, so the whole HUD and
every action can be seen (and checked: scripts/verify-air-nested.sh) before the Kinect has power.

    0.0  open palm held still at the centre        engage
    1.2  a small circle                             the pointer follows
    2.6  pinch and let go                           click
    3.6  thumb on the middle finger                 right-click
    4.6  a wave down                                scroll up
    6.0  an L, opened                               zoom in
    6.8  V sign moved up, then pushed forward       scroll, then zoom in
    8.8  fist; a second fist pulled away            grab, resize (the window grows)
   10.4  second hand gone, carry, fling right       throw right: the window takes the right half
   12.2  sweep left, then back right                next desktop, previous desktop
   14.4  both hands pinch, apart then together      zoom in, zoom out
   16.4  both open palms apart, then together       every window (overview), back to work
   19.8  hands drop out of view                     disengage
"""

import math

from synthetic import hand

DURATION = 21.4
INSERT = (4.2, 2.4)       # the wave and the L, played before the rest moves on
FPS = 30


def _ease(f):
    return f * f * (3 - 2 * f)


def _lerp(a, b, f):
    return a + (b - a) * f


def _seg(t, t0, t1):
    return _ease(min(1.0, max(0.0, (t - t0) / (t1 - t0))))


def hands_at(t):
    """The demo's hands at time t (seconds)."""
    x, y, d = 0.5, 0.5, 900
    one = lambda cx, cy=y, shape="open", depth=d: [hand(cx, cy, shape=shape, depth=depth)]  # noqa: E731

    def pair(gap, shape, right=None, cy=y):
        return [hand((right if right is not None else x + gap / 2), cy, shape=shape, depth=d,
                     side="Right"),
                hand((right if right is not None else x + gap / 2) - gap, cy, shape=shape,
                     depth=d, side="Left")]

    if t < 1.2:
        return one(x)
    if t < 2.4:
        a = (t - 1.2) / 1.2 * 2 * math.pi
        r = 0.035 * math.sin(math.pi * (t - 1.2) / 1.2)
        return one(x + r * math.sin(a), y - r * (1 - math.cos(a)) * 0.6)
    if t < 3.4:
        return one(x, shape="pinch" if 2.6 <= t < 2.9 else "open")
    if t < 4.2:
        return one(x, shape="pinch-middle" if 3.6 <= t < 3.9 else "open")
    if t < INSERT[0] + INSERT[1]:
        if t < 4.6:
            return one(x)
        if t < 4.75:
            return one(x, _lerp(y, y + 0.2, (t - 4.6) / 0.15))
        if t < 4.85:
            return one(x, y + 0.2)
        if t < 5.25:
            return one(x, _lerp(y + 0.2, y, _seg(t, 4.85, 5.25)))    # the hand comes back up
        if t < 5.8:
            return one(x, y)
        if t < 6.0:
            return [hand(x, y, shape="L", gap=0.6, depth=d)]
        if t < 6.5:
            return [hand(x, y, shape="L", gap=_lerp(0.6, 1.4, _seg(t, 6.0, 6.5)), depth=d)]
        return [hand(x, y, shape="L", gap=1.4, depth=d)]
    t -= INSERT[1]
    if t < 4.4:
        return one(x, shape="vee")
    if t < 5.0:
        return one(x, _lerp(y, y - 0.06, _seg(t, 4.4, 5.0)), shape="vee")
    if t < 5.6:
        return one(x, y - 0.06, shape="vee", depth=int(_lerp(d, d - 140, _seg(t, 5.0, 5.5))))
    y, d = y - 0.06, d - 140          # the hand stays where the zoom left it
    one = lambda cx, cy=y, shape="open", depth=d: [hand(cx, cy, shape=shape, depth=depth)]  # noqa: E731
    if t < 6.4:
        return one(x, y)
    if t < 6.9:
        return one(x, y, shape="fist")
    if t < 7.9:
        gap = 0.15 + 0.07 * _seg(t, 7.1, 7.8)
        return [hand(x, y, shape="fist", depth=d, side="Right"),
                hand(x - gap, y, shape="fist", depth=d, side="Left")]
    if t < 8.2:
        return one(x, y, shape="fist")
    if t < 8.6:
        return one(_lerp(x, x - 0.04, _seg(t, 8.2, 8.6)), y, shape="fist")
    if t < 8.75:
        return one(_lerp(x - 0.04, x + 0.07, (t - 8.6) / 0.15), y, shape="fist")
    x = x + 0.07
    if t < 9.8:
        return one(x, y)
    if t < 9.95:
        return one(_lerp(x, x - 0.20, (t - 9.8) / 0.15), y)
    if t < 11.0:
        return one(x - 0.20, y)
    if t < 11.15:
        return one(_lerp(x - 0.20, x, (t - 11.0) / 0.15), y)
    if t < 12.0:
        return one(_lerp(x, 0.55, _seg(t, 11.15, 11.7)), y)
    x = 0.55
    if t < 12.2:
        return pair(0.15, "open", right=x)
    if t < 13.0:
        return pair(_lerp(0.15, 0.30, _seg(t, 12.2, 12.9)), "pinch", right=x + 0.075 * _seg(t, 12.2, 12.9))
    if t < 13.6:
        return pair(_lerp(0.30, 0.20, _seg(t, 13.0, 13.5)), "pinch", right=x + 0.075 - 0.05 * _seg(t, 13.0, 13.5))
    x = x + 0.025
    if t < 14.0:
        return pair(0.20, "open", right=x)
    if t < 14.7:
        return pair(_lerp(0.20, 0.38, _seg(t, 14.0, 14.6)), "open", right=x + 0.09 * _seg(t, 14.0, 14.6))
    if t < 15.8:
        return pair(0.38, "open", right=x + 0.09)
    if t < 16.4:
        return pair(_lerp(0.38, 0.12, _seg(t, 15.8, 16.3)), "open", right=x + 0.09 - 0.13 * _seg(t, 15.8, 16.3))
    if t < 17.4:
        return one(0.5, y)
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
