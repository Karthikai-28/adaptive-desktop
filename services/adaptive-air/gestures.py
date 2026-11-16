"""Air's gesture engine: hand tracks in, pointer state and gesture events out. Pure.

Input, once per camera frame (Engine.step):

    t      seconds (monotonic)
    hands  [{"side": "Left"|"Right", "lm": [[x, y, z] * 21], "depth": mm or None}]
           lm are MediaPipe hand landmarks, x/y normalised to the (mirrored) camera image; depth
           is the palm's distance from the Kinect in millimetres (None on a plain webcam).

Output: a dict the shell draws and acts on (shell/adaptive-shell@local/air.js):

    engaged, engage   whether Air drives the desktop; how far the open palm is toward engaging
    cursor            {"x", "y"} on the screen, 0..1, smoothed (One Euro filter)
    pressed           the primary button is held (pinch, or an air push)
    hands             per hand: screen-space landmarks, pose, pinch strength, depth
    grab              {"x", "y", "vx", "vy"} while a fist holds a window
    events            what happened this frame: engage, disengage, press, release, click, push,
                      right-click, scroll {dx, dy}, zoom {steps}, grab, drop,
                      throw-{left,right,up,down}, resize-start, resize-end,
                      swipe-{left,right,up}, spread, collapse
    mode              None | scroll | zoom | resize | palms (two open hands) | grab
    resize            how much the held window has grown (1.0 = as it was) while resizing

The vocabulary, in order of how often it is used:

    raise an open palm and hold it still   engage (the reticle fills, then locks on)
    move the hand                          the pointer follows the palm (not the fingertip,
                                           so pinching does not move it)
    pinch thumb and index                  press; let go to release: click, or drag while held
    pinch thumb and middle finger          right-click
    V sign (index and middle up), move it  scroll the window under the pointer (the pointer stays)
    ... push it toward / pull it back      zoom in / out (Ctrl + wheel)
    push the open palm toward the Kinect   click (Kinect only: needs depth)
    make a fist over a window              grab it and carry it; open the hand to drop it
    ... and fling it while letting go      throw: left/right = tile that half, up = maximise,
                                           down = minimise
    swipe the open hand fast left/right    previous / next workspace
    swipe it fast up                       overview
    both hands pinch, pull apart/together  zoom in / out, step by step (Ctrl + wheel)
    holding a window, make a second fist   resize it: pull the fists apart to grow it, together
                                           to shrink it; open the second hand to carry on
    both open palms pulled apart           spread: overview with every window laid out
    ... or pushed together                 collapse: back to the desktop
    drop the hand out of view              disengage
"""

import math

# Landmark indices (MediaPipe Hands)
WRIST, THUMB_IP, THUMB_TIP = 0, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20
PALM = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
FINGERS = ((INDEX_TIP, INDEX_PIP), (MIDDLE_TIP, MIDDLE_PIP), (RING_TIP, RING_PIP),
           (PINKY_TIP, PINKY_PIP))

DEFAULTS = {
    # Part of the camera image that maps onto the whole screen, as a fraction of the image's
    # width, centred where the hand engaged. Smaller = less arm movement per screen.
    "box_width": 0.42,
    "box_aspect": 1.6,           # screen width / height (1920x1200)
    "engage_hold": 0.55,         # s an open palm must be held still
    "engage_still": 0.35,        # max palm speed (image widths/s) while engaging
    "min_hand": 0.06,            # smallest hand (wrist to middle knuckle, image heights) to use
    "lost_after": 0.7,           # s without the primary hand before disengaging
    "pinch_on": 0.30,            # thumb-index distance / hand size
    "pinch_off": 0.42,
    "pinch_freeze": 0.12,        # s the pointer holds still as a pinch closes
    "click_max_move": 0.025,     # screen fraction a pinch may move and still be a click
    "pose_frames": 3,            # frames a new pose must last before it counts
    "swipe_speed": 2.2,          # screen widths/s at the peak of a swipe
    "swipe_distance": 0.30,      # screen widths travelled within swipe_window
    "swipe_window": 0.30,        # s
    "cooldown": 0.8,             # s after a swipe, throw, push, spread or collapse
    "push_mm": 70,               # palm moves this much closer to the Kinect...
    "push_window": 0.30,         # ...within this many seconds
    "throw_speed": 1.4,          # screen fractions/s when a fist opens
    "scroll_step": 0.035,        # screen fractions of V-sign movement per wheel step
    "natural_scroll": True,      # the page follows the hand (hand up = wheel down)
    "zoom_mm": 45,               # V sign moved this much closer to the Kinect = one zoom step
    "zoom_size": 0.12,           # ... or, with no depth (webcam), the hand this much bigger
    "zoom_ratio": 1.15,          # two pinching hands this much farther apart = one zoom step
    "spread_ratio": 1.6,         # two-hand distance grows / shrinks by this much
    "collapse_ratio": 0.6,
    "one_euro": {"min_cutoff": 1.4, "beta": 4.0, "d_cutoff": 1.0},
}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def palm_centre(lm):
    return (sum(lm[i][0] for i in PALM) / len(PALM), sum(lm[i][1] for i in PALM) / len(PALM))


def hand_size(lm):
    return max(dist(lm[WRIST], lm[MIDDLE_MCP]), 1e-6)


def pinch_ratio(lm):
    return dist(lm[THUMB_TIP], lm[INDEX_TIP]) / hand_size(lm)


def extended(lm):
    """Which of index, middle, ring, little finger are straight (tip farther from the wrist)."""
    w = lm[WRIST]
    return [dist(w, lm[tip]) > dist(w, lm[pip]) * 1.12 for tip, pip in FINGERS]


def curled(lm):
    """Every finger folded back toward the palm (tip nearer the wrist than its middle joint).

    Checked before the pinch: in a fist the thumb often rests near the index tip, which would
    otherwise read as a pinch. In a real pinch the index is bent, not folded back.
    """
    w = lm[WRIST]
    return all(dist(w, lm[tip]) < dist(w, lm[pip]) * 0.98 for tip, pip in FINGERS)


def middle_ratio(lm):
    return dist(lm[THUMB_TIP], lm[MIDDLE_TIP]) / hand_size(lm)


def classify(lm, pinching, middle=False):
    """open | fist | point | vee | pinch | pinch-middle | relaxed for one hand's landmarks."""
    if curled(lm):
        return "fist"
    if pinching:
        return "pinch"
    if middle:
        return "pinch-middle"
    ext = extended(lm)
    n = sum(ext)
    if ext[0] and ext[1] and not ext[2] and not ext[3]:
        return "vee"
    if n >= 4 or (n == 3 and not ext[3]):
        return "open"
    if ext[0] and n == 1:
        return "point"
    return "relaxed"


class OneEuro:
    """One Euro filter (Casiez et al.): smooth when still, little lag when moving fast."""

    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self, x=None, t=None):
        self.x, self.dx, self.t = x, 0.0 if x is not None else None, t

    def __call__(self, x, t):
        if self.x is None or self.t is None or t <= self.t:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = t - self.t
        self.t = t
        dx = (x - self.x) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


class Track:
    """One hand followed from frame to frame: pose with debounce, pinch with hysteresis, history."""

    def __init__(self, side):
        self.side = side
        self.pose = "relaxed"
        self._candidate, self._candidate_n = None, 0
        self.pinching = False
        self.middle = False        # thumb on the middle fingertip (right-click)
        self.history = []          # (t, image x, image y, depth)
        self.lm = None
        self.depth = None
        self.seen = 0.0
        self.strength = 0.0

    def update(self, hand, t, cfg):
        lm = hand["lm"]
        self.lm, self.depth, self.seen = lm, hand.get("depth"), t
        ratio = pinch_ratio(lm)
        if curled(lm):
            self.pinching = False
        elif self.pinching:
            self.pinching = ratio < cfg["pinch_off"]
        else:
            self.pinching = ratio < cfg["pinch_on"]
        m = middle_ratio(lm)
        if curled(lm) or self.pinching:
            self.middle = False
        elif self.middle:
            self.middle = m < cfg["pinch_off"]
        else:
            # Only with the index clearly away from the thumb: fingers held together while
            # pinching the index would otherwise read as both.
            self.middle = m < cfg["pinch_on"] and ratio > cfg["pinch_off"]
        pose = classify(lm, self.pinching, self.middle)
        if pose in ("pinch", "pinch-middle") or pose == self.pose:
            # A pinch counts at once (it is a click); others must last a few frames.
            self.pose, self._candidate, self._candidate_n = pose, None, 0
        elif pose == self._candidate:
            self._candidate_n += 1
            if self._candidate_n >= cfg["pose_frames"]:
                self.pose, self._candidate, self._candidate_n = pose, None, 0
        else:
            self._candidate, self._candidate_n = pose, 1
        cx, cy = palm_centre(lm)
        self.size = hand_size(lm)
        self.history.append((t, cx, cy, self.depth))
        cutoff = t - 1.0
        while self.history and self.history[0][0] < cutoff:
            self.history.pop(0)
        self.strength = 0.0 if self.pose == "fist" else max(0.0, min(1.0, (0.55 - ratio) / (0.55 - cfg["pinch_on"])))

    def velocity(self, span=0.12):
        """Image-space palm velocity over the last `span` seconds (widths/s, heights/s)."""
        if len(self.history) < 2:
            return 0.0, 0.0
        t1, x1, y1, _ = self.history[-1]
        for t0, x0, y0, _ in reversed(self.history):
            if t1 - t0 >= span:
                break
        dt = t1 - t0
        if dt <= 0:
            return 0.0, 0.0
        return (x1 - x0) / dt, (y1 - y0) / dt


class Engine:
    def __init__(self, config=None):
        self.cfg = dict(DEFAULTS)
        if config:
            self.cfg.update({k: v for k, v in config.items() if k in DEFAULTS})
        self.tracks = {}
        self.engaged = False
        self.primary = None
        self.engage_since = None
        self.engage_side = None
        self.anchor = (0.5, 0.5)
        oe = self.cfg["one_euro"]
        self.fx, self.fy = OneEuro(**oe), OneEuro(**oe)
        self.cursor = (0.5, 0.5)
        self.pressed = False
        self.press_by = None       # "pinch" | None
        self.press_at = None       # (t, cursor) when the press began
        self.freeze_until = 0.0
        self.grab = None           # {"t", "x", "y"} cursor-space position history while a fist holds
        self.cooldown_until = 0.0
        self.clutch_until = None
        self.two_hand = None       # (mode, starting distance) while two hands act together
        self.mode = None           # scroll | zoom | resize | palms
        self.scroll_from = None    # (x, y, depth, size) the V sign is measured from
        self.right_latched = False
        self.resize = None
        self.last_seen = None

    # ------------------------------------------------------------ geometry

    def box(self):
        w = self.cfg["box_width"]
        h = w / self.cfg["box_aspect"] * (640 / 480)   # image is 4:3, screen 16:10
        return w, h

    def to_screen(self, x, y):
        w, h = self.box()
        return (x - self.anchor[0]) / w + 0.5, (y - self.anchor[1]) / h + 0.5

    # ------------------------------------------------------------ frame

    def step(self, t, hands):
        cfg = self.cfg
        events = []
        seen = set()
        for hand in hands or []:
            if hand_size(hand["lm"]) < cfg["min_hand"]:
                continue        # someone far behind the user
            side = hand.get("side") or "Right"
            if side in seen:
                side = "Left" if side == "Right" else "Right"
            seen.add(side)
            track = self.tracks.get(side)
            if not track:
                track = self.tracks[side] = Track(side)
            track.update(hand, t, cfg)
        for side in list(self.tracks):
            if side not in seen and t - self.tracks[side].seen > cfg["lost_after"]:
                del self.tracks[side]
        live = {s: tr for s, tr in self.tracks.items() if s in seen}

        if not self.engaged:
            self._try_engage(t, live, events)
        else:
            primary = live.get(self.primary)
            if primary is None:
                if self.primary not in self.tracks:
                    self._disengage(t, events)
            else:
                self._drive(t, primary, live, events)

        return self._state(t, live, events)

    def _try_engage(self, t, live, events):
        cfg = self.cfg
        best = None
        for track in live.values():
            vx, vy = track.velocity()
            if track.pose == "open" and math.hypot(vx, vy) < cfg["engage_still"]:
                best = track
                break
        if best is None:
            self.engage_since = None
            return
        if self.engage_since is None or self.engage_side != best.side:
            self.engage_since, self.engage_side = t, best.side
        if t - self.engage_since >= cfg["engage_hold"]:
            self.engaged = True
            self.primary = best.side
            _, cx, cy, _ = best.history[-1]
            w, h = self.box()
            # Centre the box on the palm, kept inside the image.
            self.anchor = (min(max(cx, w / 2), 1 - w / 2), min(max(cy, h / 2), 1 - h / 2))
            sx, sy = self.to_screen(cx, cy)
            self.fx.reset(sx, t)
            self.fy.reset(sy, t)
            self.cursor = (sx, sy)
            self.engage_since = None
            self.cooldown_until = t + 0.4
            events.append({"type": "engage", "side": best.side})

    def _disengage(self, t, events):
        if self.pressed:
            events.append({"type": "release"})
        if self.grab:
            events.append({"type": "drop", "vx": 0.0, "vy": 0.0})
        self.engaged = False
        self.primary = None
        self.clutch_until = None
        self.pressed = False
        self.press_by = None
        if self.resize is not None:
            events.append({"type": "resize-end"})
        self.grab = None
        self.two_hand = None
        self.mode = None
        self.resize = None
        self.scroll_from = None
        self.right_latched = False
        events.append({"type": "disengage"})

    def _drive(self, t, primary, live, events):
        cfg = self.cfg
        _, cx, cy, depth = primary.history[-1]
        if self.clutch_until is not None and t >= self.clutch_until:
            # Like lifting a mouse: wherever the hand is now continues from where the pointer is.
            w, h = self.box()
            self.anchor = (cx - (self.cursor[0] - 0.5) * w, cy - (self.cursor[1] - 0.5) * h)
            self.fx.reset(self.cursor[0], t)
            self.fy.reset(self.cursor[1], t)
            self.clutch_until = None
        sx, sy = self.to_screen(cx, cy)
        fx, fy = self.fx(sx, t), self.fy(sy, t)
        if t >= self.freeze_until and self.clutch_until is None:
            self.cursor = (min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0))

        others = [tr for s, tr in live.items() if s != primary.side]
        if others and self._two_hands(t, primary, others[0], events):
            return
        self._end_two_hands(t, events)

        # Thumb on the middle fingertip: right-click, once per touch
        if primary.middle and not self.right_latched and not self.pressed and not self.grab:
            self.right_latched = True
            self.freeze_until = t + cfg["pinch_freeze"]
            events.append({"type": "right-click", "x": self.cursor[0], "y": self.cursor[1]})
            return
        if not primary.middle:
            self.right_latched = False

        # V sign: scroll by moving it, zoom by pushing/pulling it; the pointer stays put
        if primary.pose == "vee" and not self.pressed and not self.grab:
            self._scroll(t, primary, cx, cy, depth, events)
            return
        if self.mode == "scroll":
            self.mode, self.scroll_from = None, None
            self.clutch_until = t + 0.1

        # Pinch: press / release / click
        if primary.pinching and not self.pressed and not self.grab:
            self.pressed, self.press_by = True, "pinch"
            self.press_at = (t, self.cursor)
            self.freeze_until = t + cfg["pinch_freeze"]
            events.append({"type": "press", "x": self.cursor[0], "y": self.cursor[1]})
        elif self.pressed and self.press_by == "pinch" and not primary.pinching:
            self.pressed, self.press_by = False, None
            events.append({"type": "release", "x": self.cursor[0], "y": self.cursor[1]})
            t0, c0 = self.press_at
            if dist(c0, self.cursor) <= cfg["click_max_move"]:
                events.append({"type": "click", "x": self.cursor[0], "y": self.cursor[1]})

        # Fist: grab / carry / drop / throw
        if primary.pose == "fist" and not self.grab and not self.pressed:
            self.grab = [(t, self.cursor[0], self.cursor[1])]
            events.append({"type": "grab", "x": self.cursor[0], "y": self.cursor[1]})
        elif self.grab:
            self.grab.append((t, self.cursor[0], self.cursor[1]))
            self.grab = [g for g in self.grab if t - g[0] <= 0.25] or self.grab[-1:]
            if primary.pose in ("open", "relaxed", "point"):
                vx, vy = self._grab_velocity()
                self.grab = None
                events.append({"type": "drop", "vx": vx, "vy": vy})
                speed = math.hypot(vx, vy)
                if speed >= cfg["throw_speed"] and t >= self.cooldown_until:
                    if abs(vx) >= abs(vy):
                        direction = "right" if vx > 0 else "left"
                    else:
                        direction = "down" if vy > 0 else "up"
                    events.append({"type": "throw-" + direction, "speed": speed})
                    self.cooldown_until = t + cfg["cooldown"]

        if self.pressed or self.grab or t < self.cooldown_until:
            return

        # Air push (needs depth): the open or pointing palm moves toward the Kinect quickly
        if depth and primary.pose in ("open", "point"):
            for t0, _, _, d0 in primary.history:
                if t - t0 <= cfg["push_window"] and d0 and d0 - depth >= cfg["push_mm"]:
                    events.append({"type": "push", "x": self.cursor[0], "y": self.cursor[1]})
                    events.append({"type": "click", "x": self.cursor[0], "y": self.cursor[1]})
                    self.cooldown_until = t + cfg["cooldown"]
                    return

        # Swipe: an open hand moving fast and far, mostly along one axis
        if primary.pose == "open":
            swipe = self._swipe(t, primary)
            if swipe:
                events.append({"type": "swipe-" + swipe})
                self.cooldown_until = t + cfg["cooldown"]
                # The swipe dragged the pointer along; put it back where it was and hold it
                # there while the hand comes back (the clutch), then carry on from there.
                back = self._cursor_before(t - cfg["swipe_window"], primary)
                if back:
                    self.cursor = back
                self.clutch_until = t + cfg["cooldown"]

    def _grab_velocity(self, span=0.1):
        """The fastest the held window moved over any `span` seconds of the last quarter second.

        A throw is a fling and an opening hand at once, and the open hand takes a few frames to
        be recognised: an average over the whole window would be diluted by those still frames.
        """
        g = self.grab
        best = (0.0, 0.0)
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                dt = g[j][0] - g[i][0]
                if dt >= span:
                    v = ((g[j][1] - g[i][1]) / dt, (g[j][2] - g[i][2]) / dt)
                    if math.hypot(*v) > math.hypot(*best):
                        best = v
                    break
        return best

    def _swipe(self, t, track):
        cfg = self.cfg
        w, h = self.box()
        recent = [p for p in track.history if t - p[0] <= cfg["swipe_window"]]
        if len(recent) < 3:
            return None
        dx = (recent[-1][1] - recent[0][1]) / w
        dy = (recent[-1][2] - recent[0][2]) / h
        vx, vy = track.velocity(0.08)
        peak = max(abs(vx / w), abs(vy / h))
        if peak < cfg["swipe_speed"]:
            return None
        if abs(dx) >= cfg["swipe_distance"] and abs(dx) > 2 * abs(dy):
            return "right" if dx > 0 else "left"
        if dy <= -cfg["swipe_distance"] and abs(dy) > 2 * abs(dx):
            return "up"
        return None

    def _cursor_before(self, t0, track):
        for t, x, y, _ in track.history:
            if t >= t0:
                sx, sy = self.to_screen(x, y)
                return (min(max(sx, 0.0), 1.0), min(max(sy, 0.0), 1.0))
        return None

    def _scroll(self, t, track, cx, cy, depth, events):
        cfg = self.cfg
        w, h = self.box()
        if self.mode != "scroll":
            self.mode = "scroll"
            self.scroll_from = (cx, cy, depth, track.size)
            self.clutch_until = math.inf          # hold the pointer while scrolling
            return
        x0, y0, d0, s0 = self.scroll_from
        step = cfg["scroll_step"]
        sx = int((cx - x0) / w / step)
        sy = int((cy - y0) / h / step)
        if sx or sy:
            sign = -1 if cfg["natural_scroll"] else 1
            events.append({"type": "scroll", "dx": max(-5, min(5, sign * sx)),
                           "dy": max(-5, min(5, sign * sy))})
            x0 += sx * step * w
            y0 += sy * step * h
        zoom = 0
        if depth and d0:
            zoom = int((d0 - depth) / cfg["zoom_mm"])
            if zoom:
                d0 -= zoom * cfg["zoom_mm"]
        elif not depth:
            zoom = int(math.log(track.size / s0) / math.log(1 + cfg["zoom_size"]))
            if zoom:
                s0 *= (1 + cfg["zoom_size"]) ** zoom
        if zoom:
            events.append({"type": "zoom", "steps": max(-5, min(5, zoom))})
        self.scroll_from = (x0, y0, d0 if depth else None, s0)

    def _two_hands(self, t, a, b, events):
        """Two hands acting together. a is the primary hand. True when they took the frame.

            both pinching             zoom: a step for every zoom_ratio of change in distance
            a holds a window, b fist  resize: the window scales with the distance
            both open palms           spread / collapse past a ratio (overview)
        """
        cfg = self.cfg
        d = dist(palm_centre(a.lm), palm_centre(b.lm))
        if a.pinching and b.pinching:
            mode = "zoom"
        elif self.grab and a.pose == "fist" and b.pose == "fist":
            mode = "resize"
        elif a.pose == "open" and b.pose == "open" and not self.grab and not self.pressed:
            mode = "palms"
        else:
            return False
        if self.two_hand is None or self.two_hand[0] != mode:
            self._end_two_hands(t, events)
            if self.mode == "scroll":
                self.scroll_from = None
                self.clutch_until = t + 0.1       # the pointer was held for the scroll
            if self.pressed and self.press_by == "pinch":
                # The primary pinch began first: that press is cancelled, not clicked.
                self.pressed, self.press_by = False, None
                events.append({"type": "release", "x": self.cursor[0], "y": self.cursor[1],
                               "cancel": True})
            self.two_hand = (mode, d)
            self.mode = mode
            if mode == "resize":
                self.resize = 1.0
                events.append({"type": "resize-start"})
            return True
        d0 = self.two_hand[1]
        ratio = d / max(d0, 1e-6)
        if mode == "zoom":
            steps = int(math.log(ratio) / math.log(cfg["zoom_ratio"]))
            if steps:
                events.append({"type": "zoom", "steps": max(-5, min(5, steps))})
                self.two_hand = (mode, d0 * cfg["zoom_ratio"] ** steps)
        elif mode == "resize":
            self.resize = round(max(0.3, min(4.0, ratio)), 3)
        elif t >= self.cooldown_until:
            if ratio >= cfg["spread_ratio"]:
                events.append({"type": "spread"})
                self.cooldown_until = t + cfg["cooldown"]
                self.two_hand = (mode, d)
            elif ratio <= cfg["collapse_ratio"]:
                events.append({"type": "collapse"})
                self.cooldown_until = t + cfg["cooldown"]
                self.two_hand = (mode, d)
        return True

    def _end_two_hands(self, t, events):
        if self.two_hand is None:
            return
        if self.two_hand[0] == "resize":
            events.append({"type": "resize-end", "scale": self.resize})
            self.resize = None
            if self.grab:
                # A fresh start, so the resize is not read as a fling when the fist opens.
                self.grab = [(t, self.cursor[0], self.cursor[1])]
        self.two_hand = None
        self.mode = None

    # ------------------------------------------------------------ output

    def _state(self, t, live, events):
        cfg = self.cfg
        engage = 0.0
        if not self.engaged and self.engage_since is not None:
            engage = min(1.0, (t - self.engage_since) / cfg["engage_hold"])
        hands = []
        for side, tr in live.items():
            pts = [self.to_screen(p[0], p[1]) for p in tr.lm] if self.engaged else \
                [(0.5 + (p[0] - 0.5) * 0.9, 0.5 + (p[1] - 0.5) * 0.9) for p in tr.lm]
            hands.append({
                "side": side, "primary": side == self.primary, "pose": tr.pose,
                "pinch": round(tr.strength, 3), "depth": tr.depth,
                "pts": [[round(x, 4), round(y, 4)] for x, y in pts],
            })
        grab = None
        if self.grab:
            vx, vy = self._grab_velocity()
            grab = {"x": self.cursor[0], "y": self.cursor[1], "vx": vx, "vy": vy}
        return {
            "t": t, "engaged": self.engaged, "engage": round(engage, 3),
            "cursor": {"x": round(self.cursor[0], 4), "y": round(self.cursor[1], 4)},
            "pressed": self.pressed, "grab": grab, "hands": hands, "events": events,
            "mode": self.mode or ("grab" if self.grab else None), "resize": self.resize,
        }
