"""Where each activity fits in this room, from the camera's real geometry. Pure Python + numpy.

The old play area was a fixed band (1.3 to 4.2 m from the TV, away from the picture's edges).
What the Kinect can actually see depends on how high it is, how far it points down, which lens
the picture comes from (colour or infrared), how deep the room is, and how big the player is
and what they are about to do: jumping jacks need hands overhead and a wide stance in view, a
curl needs only the upper body, a plank lies along the floor. So:

    camera    the lens numbers of the picture the joints came from (the hub's snapshot), the
              floor plane's up vector and the Kinect's height above it (people.py's floor fit)
    room      how far the floor goes before a wall or a sofa (people.room_extent), and the
              owner's own limit (`"space_m"` in motion.json: under two metres here)
    body      the player's height (measured by the hub while standing straight; 1.75 m until
              then) and shares of it for reach, stance and limb lengths (Winter's tables)
    activity  an envelope per exercise and game: the lowest and highest points that must be in
              the picture, how wide it gets, how far forward it reaches, and the joints its
              counting needs (exercises.CATALOG[...].joints)

Every room point is projected into the picture with the camera's numbers; a pose fits at a
place on the floor when every point of its envelope lands inside the picture (with a margin),
the place is within the depth camera's reliable range, and in front of whatever the room ends
at. `report()` gives, per activity, the floor band it fits in and, when it does not fit at all,
exactly why ("your hands would leave the top of the picture closer than 2.6 m, and the room
ends at 1.9 m").
"""

import math

import numpy as np

W, H = 640, 480
MARGIN = 0.03              # share of the picture kept clear at each edge (joints near the edge wobble)
DEPTH_NEAR, DEPTH_FAR = 0.8, 4.0    # m: Kinect v1 depth is reliable for a body in this range
WALL_GAP = 0.35            # m kept between a player's centre and the end of the room
DEFAULT_HEIGHT = 1.75

# Envelopes, as shares of standing height H unless the name says metres:
#   low / high    heights (y) of the lowest / highest point that must be seen
#   half          half the width (x) across the picture
#   ahead         how far the body reaches towards the Kinect (a lunge, a punch), metres
#   jump          metres of jump on top of `high` (and `low`)
#   needs         which joint groups the counting reads (for the "why")
ENVELOPES = {
    # The joints each one counts and coaches from (exercises.CATALOG[...].joints and its cues),
    # at their heights: ankles ~0.04 H, knees 0.28, hips 0.53, shoulders 0.82, wrists overhead
    # ~1.25. The head is not needed unless a rule reads it.
    "squat":   {"low": 0.0, "high": 0.86, "half": 0.22, "ahead": 0.35, "needs": "feet to shoulders"},
    "lunge":   {"low": 0.0, "high": 0.86, "half": 0.22, "ahead": 0.60, "needs": "feet to shoulders and a step forward"},
    "jack":    {"low": 0.0, "high": 1.25, "half": 0.55, "ahead": 0.1, "jump": 0.10,
                "needs": "feet to raised hands, arms out wide"},
    "knees":   {"low": 0.24, "high": 0.58, "half": 0.20, "ahead": 0.45, "needs": "knees and hips, knees lifted"},
    "curl":    {"low": 0.48, "high": 0.86, "half": 0.26, "ahead": 0.35, "needs": "hips to shoulders"},
    "press":   {"low": 0.48, "high": 1.27, "half": 0.30, "ahead": 0.1, "needs": "hips to hands overhead"},
    "raise":   {"low": 0.48, "high": 0.88, "half": 0.52, "ahead": 0.1, "needs": "hips to shoulders, arms out to the side"},
    "chair":   {"low": 0.22, "high": 0.58, "half": 0.25, "ahead": 0.55, "needs": "knees and hips, sitting and standing"},
    "jump":    {"low": 0.0, "high": 0.58, "half": 0.22, "ahead": 0.2, "jump": 0.35, "needs": "feet and hips, in the air"},
    "punch":   {"low": 0.75, "high": 0.86, "half": 0.30, "ahead": 0.75, "needs": "shoulders and arms reaching forward"},
    "plank":   {"low": 0.0, "high": 0.45, "half": 0.62, "ahead": 0.1, "needs": "your whole body lying side-on"},
    "wallsit": {"low": 0.0, "high": 0.45, "half": 0.25, "ahead": 0.6, "needs": "feet to hips, seated against a wall"},
    "balance": {"low": 0.0, "high": 0.58, "half": 0.30, "ahead": 0.3, "needs": "feet and hips"},
    "reach":   {"low": 0.0, "high": 0.58, "half": 0.25, "ahead": 0.55, "needs": "feet to hips, hands to the floor"},
    # Games
    "walls":   {"low": 0.25, "high": 1.25, "half": 0.55, "ahead": 0.3, "jump": 0.25,
                "needs": "hips to raised hands, leaning and ducking"},
    "pose":    {"low": 0.0, "high": 1.22, "half": 0.55, "ahead": 0.2, "needs": "feet to raised hands, arms out wide"},
    "race":    {"low": 0.48, "high": 0.86, "half": 0.30, "ahead": 0.55, "needs": "hips to shoulders, hands on a wheel"},
}
NAMES = {"walls": "Wall Dodge", "pose": "Pose Match", "race": "Body Racer"}


class Camera:
    """The projection from the room frame (x right, y up, z forward, origin on the floor under
    the Kinect) to the picture, from the hub's floor fit and lens numbers."""

    def __init__(self, intrinsics=(525.0, 525.0, 319.5, 239.5), camera_height=1.0, up=None,
                 tilt_deg=None, size=(W, H)):
        self.fx, self.fy, self.cx, self.cy = (float(v) for v in intrinsics)
        self.h = float(camera_height)
        self.size = size
        if up is None:
            t = math.radians(tilt_deg or 0.0)
            up = (0.0, -math.cos(t), -math.sin(t))
        up = np.asarray(up, dtype=np.float64)
        up /= max(np.linalg.norm(up), 1e-9)
        fwd = np.array([0.0, 0.0, 1.0]) - up[2] * up
        fwd /= max(np.linalg.norm(fwd), 1e-9)
        self.up, self.fwd, self.right = up, fwd, np.cross(fwd, up)

    @classmethod
    def from_hub(cls, hub):
        floor = hub.get("floor") or {}
        if not floor.get("camera_height"):
            return None
        intr = hub.get("intrinsics") or ((575.8, 575.8, 314.5, 235.5) if hub.get("mode") == "ir"
                                         else (525.0, 525.0, 319.5, 239.5))
        size = tuple(hub.get("size") or (W, H))
        return cls(intr, floor["camera_height"], floor.get("up"), floor.get("tilt"), size)

    def key(self):
        return (round(self.fx), round(self.cx), round(self.h, 2), tuple(np.round(self.up, 2)), self.size)

    def project(self, pts):
        """Room points (N, 3) -> pixels (N, 2) and whether each is in front of the camera."""
        p = np.atleast_2d(np.asarray(pts, dtype=np.float64))
        q = (np.outer(p[:, 0], self.right) + np.outer(p[:, 1] - self.h, self.up)
             + np.outer(p[:, 2], self.fwd))
        front = q[:, 2] > 0.2
        z = np.where(front, q[:, 2], 1.0)
        return np.stack([self.cx + self.fx * q[:, 0] / z, self.cy + self.fy * q[:, 1] / z], axis=1), front

    def where(self, pts, margin=MARGIN):
        """For each room point: "in", or which edge it leaves by ("top", "bottom", "left", "right")."""
        px, front = self.project(pts)
        w, h = self.size
        mx, my = margin * w, margin * h
        out = []
        for (u, v), f in zip(px, front):
            if not f:
                out.append("behind")
            elif v < my:
                out.append("top")
            elif v > h - my:
                out.append("bottom")
            elif u < mx:
                out.append("left")
            elif u > w - mx:
                out.append("right")
            else:
                out.append("in")
        return out


def envelope_points(env, height, x, z):
    """The corners of an activity's envelope for someone of `height` standing at (x, z)."""
    H_ = float(height)
    jump = env.get("jump", 0.0)
    low, high = env["low"] * H_, env["high"] * H_ + jump
    half = env["half"] * H_
    pts = []
    for dz in (0.0, -env.get("ahead", 0.0)):          # forward = towards the Kinect
        for y in (low, high):
            for dx in (-half, half):
                pts.append((x + dx, y, z + dz))
    return np.array(pts)


EDGE_WORDS = {"top": "would leave the top of the picture", "bottom": "would leave the bottom of the picture",
              "left": "would leave the side of the picture", "right": "would leave the side of the picture",
              "behind": "would be behind the camera"}


class Space:
    """What fits where. Built from a Camera, the room's end and the owner's limit."""

    STEP = 0.05

    def __init__(self, camera, room_end=None, limit=None):
        self.camera = camera
        self.room_end = room_end              # m along the floor where the room stops (or None)
        self.limit = limit                    # m the owner says they have (or None)
        self._cache = {}

    def usable_far(self):
        far = DEPTH_FAR
        if self.room_end:
            far = min(far, self.room_end - WALL_GAP)
        if self.limit:
            far = min(far, self.limit)
        return far

    def fits(self, activity, pos, height=None):
        """(ok, why) for a player of `height` at floor point pos = (x, z)."""
        env = ENVELOPES.get(activity)
        if env is None:
            return True, None
        x, z = float(pos[0]), float(pos[1])
        if z < DEPTH_NEAR:
            return False, "Step back from the TV"
        if self.room_end and z > self.room_end - 0.1:
            return False, "Come a little closer"
        if z > DEPTH_FAR:
            return False, "Come a little closer"
        edges = set(self.camera.where(envelope_points(env, height or DEFAULT_HEIGHT, x, z))) - {"in"}
        if not edges:
            return True, None
        if edges & {"left", "right"} and not edges & {"top", "bottom"}:
            return False, "Move towards the middle"
        if "bottom" in edges:
            return False, "Step back: your feet are out of view" if env["low"] == 0.0 else "Step back a little"
        return False, "Step back: your hands would leave the picture" if env["high"] > 1.0 else "Step back a little"

    def band(self, activity, height=None):
        """The floor distances (z0, z1) where the activity fits in the middle of the picture, or
        None, with the reason when there is none. Cached per camera and height."""
        height = round(float(height or DEFAULT_HEIGHT), 2)
        key = (activity, height, self.camera.key(), self.room_end, self.limit)
        if key in self._cache:
            return self._cache[key]
        env = ENVELOPES[activity]
        far = self.usable_far()
        zs = np.arange(DEPTH_NEAR, DEPTH_FAR + 1e-6, self.STEP)
        ok = []
        first_in = {}                                  # edge -> nearest z where it is in view
        for z in zs:
            where = self.camera.where(envelope_points(env, height, 0.0, z))
            out = set(where) - {"in"}
            for edge in ("top", "bottom", "left", "right"):
                if edge not in out and edge not in first_in:
                    first_in[edge] = z
            if not out and z <= far + 1e-9:
                ok.append(z)
        if ok:
            result = ((round(float(ok[0]), 2), round(float(ok[-1]), 2)), None)
        else:
            result = (None, self._why(env, height, zs, first_in, far))
        self._cache[key] = result
        return result

    def _why(self, env, height, zs, first_in, far):
        """The binding reason an activity fits nowhere."""
        needs = env["needs"]
        limits = []
        if self.limit and (not self.room_end or self.limit < self.room_end - WALL_GAP):
            limits.append(f"you have {self.limit:.1f} m")
        elif self.room_end:
            limits.append(f"the room ends at {self.room_end:.1f} m")
        room = (" and " + limits[0]) if limits else ""
        # The nearest distance where each part comes into view.
        worst = None
        for edge in ("top", "bottom", "left", "right"):
            z = first_in.get(edge)
            if z is None:
                worst = (edge, None)
                break
            if worst is None or (worst[1] is not None and z > worst[1]):
                worst = (edge, z)
        if worst is None:
            return f"It needs {needs} in view, which this camera cannot see from {DEPTH_NEAR:.1f} to {DEPTH_FAR:.1f} m."
        edge, z = worst
        top_part = "your raised hands" if env["high"] > 1.0 else (
            "your shoulders" if env["high"] > 0.7 else "your hips")
        bottom_part = "your feet" if env["low"] < 0.1 else ("your knees" if env["low"] < 0.4 else "your hips")
        part = {"top": top_part, "bottom": bottom_part, "left": "your arms", "right": "your arms"}[edge]
        if z is None:
            return f"It needs {needs} in view: {part} {EDGE_WORDS[edge]} anywhere up to {DEPTH_FAR:.0f} m."
        if z > far:
            return (f"It needs {needs} in view: {part} {EDGE_WORDS[edge]} closer than {z:.1f} m{room}.")
        return f"It needs {needs} in view, and no single place keeps all of it in the picture."

    def report(self, height=None, activities=None):
        """Every activity: fits or not, its band, and why not."""
        out = []
        for key in activities or ENVELOPES:
            band, why = self.band(key, height)
            out.append({"activity": key, "fits": band is not None, "band": band, "why": why})
        return out

    def view_at(self, z):
        """How much of the room the picture covers at floor distance z (in the middle): the
        heights of the picture's bottom and top edge and its width, metres."""
        cam = self.camera
        ys = np.linspace(-1.0, 3.5, 451)
        pts = np.stack([np.zeros_like(ys), ys, np.full_like(ys, z)], axis=1)
        inside = [y for y, w in zip(ys, cam.where(pts, margin=0.0)) if w == "in"]
        xs = np.linspace(-3.0, 3.0, 601)
        pts = np.stack([xs, np.full_like(xs, cam.h), np.full_like(xs, z)], axis=1)
        wide = [x for x, w in zip(xs, cam.where(pts, margin=0.0)) if w == "in"]
        return {"z": z, "bottom": round(min(inside), 2) if inside else None,
                "top": round(max(inside), 2) if inside else None,
                "width": round(max(wide) - min(wide), 2) if wide else None}

    def to_dict(self, height=None):
        far = self.usable_far()
        return {"camera_height": round(self.camera.h, 2),
                "tilt": round(math.degrees(math.asin(max(-1.0, min(1.0, -self.camera.up[2])))), 1),
                "lens": [round(self.camera.fx, 1), round(self.camera.fy, 1)],
                "room_end": self.room_end, "limit": self.limit, "usable": [DEPTH_NEAR, round(far, 2)],
                "height": round(float(height or DEFAULT_HEIGHT), 2),
                "view": [self.view_at(z) for z in (1.5, 2.0, 2.5, 3.0) if z <= DEPTH_FAR],
                "activities": self.report(height)}


def tilted(camera, degrees):
    """The same camera turned about its own x axis by `degrees` (positive = up), as the Kinect's
    tilt motor turns it (the pivot is a few cm below the lens; that offset is ignored)."""
    r = math.radians(degrees)
    # In camera coordinates (y down, z forward) tilting the camera up turns the world's up
    # vector the other way about x.
    c, s = math.cos(r), math.sin(r)
    rot = np.array([[1, 0, 0], [0, c, s], [0, -s, c]])
    out = Camera((camera.fx, camera.fy, camera.cx, camera.cy), camera.h, rot @ camera.up, size=camera.size)
    return out


def suggest_tilt(space, height=None, activities=None, current=None, span=(-20, 20)):
    """Which tilt fits the most activities here: {"by": degrees up (+) or down (-), "fits":
    [...], "now": [...]}. `current`: the motor's angle now, so the answer stays within its +-27."""
    keys = list(activities or ENVELOPES)

    def fitting(cam):
        sp = Space(cam, space.room_end, space.limit)
        return [k for k in keys if sp.band(k, height)[0] is not None]

    now = fitting(space.camera)
    best = (len(now), 0, now)
    lo, hi = span
    if current is not None:
        lo, hi = max(lo, -27 - current), min(hi, 27 - current)
    for d in range(int(lo), int(hi) + 1):
        if d == 0:
            continue
        f = fitting(tilted(space.camera, d))
        if len(f) > best[0] or (len(f) == best[0] and abs(d) < abs(best[1]) and best[1] != 0):
            best = (len(f), d, f)
    return {"by": best[1], "fits": best[2], "now": now}
