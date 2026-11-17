"""Everyone in front of the Kinect: how many, how each one is holding themselves, how tall.

Pure numpy (+ cv2). The poses come from outside (kinect_hub.PoseSource: MediaPipe's multi-person
Pose Landmarker), so all of this is testable with synthetic depth and hand-made landmarks.

    floor     a plane fitted to the floor points (least squares, refined on its inliers), started
              from the accelerometer's "up" and, from the second frame on, from the last plane: the
              ground-plane step of the PCL / Munaro people detectors. The floor's tilt then comes
              from the floor itself, not only the accelerometer. No floor in view: the accelerometer
              and the mount height stand in (measure.py).
    region    each person's own depth pixels: the person's segmentation mask (slightly grown, so
              the top of the head is never cut) AND depth within reach of their torso AND above the
              floor. Two people standing side by side stay two people because each has their own
              mask; a wall behind them never joins because of the depth limit. Pixels on a depth
              edge (the Kinect's "flying pixels" between a head and the wall) are left out.
    height    the top of the region above the floor plane. Dark hair can leave holes in Kinect
              depth, so a top that is barely above the eyes is replaced by eyes + 11.5 cm.
    posture   standing / sitting / crouching / kneeling / bending / lying from joint angles (the
              landmarker's metric world landmarks: knee angle, thigh and torso against true up),
              with the hip height above the floor to tell a chair from a squat. Standing is then
              checked for "straight": torso upright, knees locked, arms down, head level, whole
              body in view. Rules after Google's ML Kit pose classification notes and the usual
              knee > 160 deg (straight) / < 140 deg (bent) thresholds.
    tracking  people keep their number and colour from frame to frame (nearest position on the
              floor), postures are a vote over the last frames (no flicker), and a height is only
              taken while someone stands straight and still, as the median of about a second of
              frames that agree within 3 cm. It stays with them when they sit down again.
"""

import math
from collections import deque

import numpy as np

import measure

STEP = 2                      # work on every 2nd pixel (320 x 240)
FEET_MARGIN = 0.05            # m above the floor plane that is still floor
DEPTH_REACH = 700             # mm from the torso's depth that can still be the same person
EYE_TO_TOP = 0.115            # m from the eyes to the top of the head (adult average)
LOCK_SECONDS = 1.0            # standing straight this long before a height counts
LOCK_SPREAD = 0.03            # m: the frames must agree this well
HISTORY = 45                  # straight-standing frames kept per person
VOTES = 9                     # posture frames voted over
LOST_AFTER = 1.2              # s unseen before a person is forgotten
MATCH_METRES = 0.7
COLOURS = 6                   # series.1 .. series.6 on the page
OUTLINE_POINTS = 64

# MediaPipe's 33 landmarks
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 2, 5, 7, 8
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 11, 12, 13, 14, 15, 16
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK = 23, 24, 25, 26, 27, 28

POSTURES = {
    "standing": "Standing",
    "sitting": "Sitting",
    "crouching": "Crouching",
    "kneeling": "Kneeling",
    "bending": "Bending over",
    "lying": "Lying down",
    "unknown": "Partly hidden",
}


class Pose:
    """One person as the landmarker saw them.

    image: (33, 3) x, y in 0..1 of the picture and visibility 0..1.
    world: (33, 3) metres around the hips (x right, y down, z away: the camera's axes), or None.
    mask:  (H, W) float 0..1, this person only, or None.
    """

    def __init__(self, image, world=None, mask=None):
        self.image = np.asarray(image, dtype=np.float32)
        self.world = None if world is None else np.asarray(world, dtype=np.float32)
        self.mask = mask


# ------------------------------------------------------------------ geometry

class Floor:
    def __init__(self, up, camera_height, seen, inliers=0):
        self.up = np.asarray(up, dtype=np.float64)
        self.camera_height = float(camera_height)
        self.seen = bool(seen)
        self.inliers = int(inliers)

    def height(self, x, y, z):
        """Height above the floor of camera-frame points (arrays or scalars)."""
        return x * self.up[0] + y * self.up[1] + z * self.up[2] + self.camera_height

    def to_dict(self):
        return {"seen": self.seen, "camera_height": round(self.camera_height, 3),
                "tilt": round(math.degrees(math.asin(max(-1.0, min(1.0, -self.up[2])))), 1)}


def grid(depth, intr, step=STEP):
    """Camera-frame x, y, z (m) of every step-th pixel, and which of them have a reading."""
    fx, fy, cx, cy = intr
    d = depth[::step, ::step].astype(np.float32)
    v, u = np.mgrid[0:depth.shape[0]:step, 0:depth.shape[1]:step]
    valid = (d >= measure.NEAR) & (d <= measure.FAR)
    z = np.where(valid, d / 1000.0, 0.0)
    return (u - cx) * z / fx, (v - cy) * z / fy, z, valid, d


def _plane(pts):
    centre = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - centre, full_matrices=False)
    return centre, vt[2]


def ransac_floor(pts, accel_up, max_angle=15.0, tries=256, seed=0):
    """Floor points by RANSAC: of planes through 3 low points, tilted at most max_angle from the
    accelerometer's up, the one with the most points on it and hardly any below it."""
    rng = np.random.default_rng(seed)
    if len(pts) > 8000:
        pts = pts[rng.choice(len(pts), 8000, replace=False)]
    h = pts @ accel_up
    low = pts[h <= np.percentile(h, 40)]
    if len(low) < 100:
        return None
    tri = low[rng.integers(0, len(low), size=(tries, 3))]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    good = norm > 1e-6
    n, tri = n[good] / norm[good, None], tri[good]
    n *= np.sign(n @ accel_up)[:, None]
    ok = n @ accel_up >= math.cos(math.radians(max_angle))
    n, tri = n[ok], tri[ok]
    if not len(n):
        return None
    off = (pts @ n.T) - np.einsum("ij,ij->i", tri[:, 0], n)[None, :]     # height over each plane
    score = (np.abs(off) < 0.03).sum(axis=0) - 8 * (off < -0.08).sum(axis=0)
    best = int(np.argmax(score))
    on = np.abs(off[:, best]) < 0.04
    return pts[on] if on.sum() >= 100 else None


def fit_floor(x, y, z, valid, accel_up, mount_height, prev=None, max_angle=15.0):
    """The floor plane (a Floor), or the accelerometer + mount height when no floor is in view.

    A floor is a plane near level (by the accelerometer) holding a good share of the picture with
    next to nothing below it, the Kinect between 0.15 and 3 m above it. It need not agree with
    the mount height in the settings: the Kinect may have been moved."""
    accel_up = np.asarray(accel_up, dtype=np.float64)
    pts_all = np.stack([x[valid], y[valid], z[valid]], axis=1)
    fallback = Floor(accel_up, mount_height, False)
    if len(pts_all) < 400:
        return fallback
    cand = None
    if prev is not None and prev.seen:                  # last frame's floor, refined
        near = np.abs(pts_all @ prev.up + prev.camera_height) < 0.05
        if near.sum() >= max(400, 0.02 * len(pts_all)):
            cand = pts_all[near]
    if cand is None:
        cand = ransac_floor(pts_all, accel_up, max_angle)
        if cand is None:
            return fallback
    if len(cand) > 6000:
        cand = cand[np.linspace(0, len(cand) - 1, 6000).astype(int)]
    centre, n = _plane(cand)
    keep = np.ones(len(cand), bool)
    for _ in range(2):                                  # refit on the points that agree
        if n @ accel_up < 0:
            n = -n
        keep = np.abs((cand - centre) @ n) < 0.025
        if keep.sum() < 100:
            return fallback
        centre, n = _plane(cand[keep])
    if n @ accel_up < 0:
        n = -n
    angle = math.degrees(math.acos(max(-1.0, min(1.0, float(n @ accel_up)))))
    camera_height = -float(centre @ n)
    heights = pts_all @ n + camera_height
    on = int((np.abs(heights) < 0.03).sum())
    below = float((heights < -0.08).mean())
    if (angle > max_angle or not 0.15 <= camera_height <= 3.0 or below > 0.02
            or on < max(300, 0.015 * len(pts_all))):
        return fallback
    return Floor(n, camera_height, True, on)


def blend_floor(prev, new, k=0.3):
    """Smooth the floor over frames, so the heights do not wobble with it."""
    if prev is None or prev.seen != new.seen:
        return new
    up = (1 - k) * prev.up + k * new.up
    up /= np.linalg.norm(up)
    return Floor(up, (1 - k) * prev.camera_height + k * new.camera_height, new.seen, new.inliers)


def project(p, intr):
    """Camera-frame point (m) -> pixel (u, v)."""
    fx, fy, cx, cy = intr
    return (cx + fx * p[0] / p[2], cy + fy * p[1] / p[2])


def angle_at(a, b, c):
    """The angle at b (degrees) between b->a and b->c."""
    u, w = np.asarray(a) - np.asarray(b), np.asarray(c) - np.asarray(b)
    nu, nw = np.linalg.norm(u), np.linalg.norm(w)
    if nu < 1e-6 or nw < 1e-6:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, float(u @ w / (nu * nw))))))


def tilt_from(v, direction):
    """Angle (degrees) between vector v and a unit direction."""
    n = np.linalg.norm(v)
    if n < 1e-6:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.asarray(v) @ direction / n)))))


# ------------------------------------------------------------------ one person's depth

def region(pose, d, valid, heights, shape, step=STEP):
    """This person's pixels on the step grid (bool), and the depth at their torso (mm)."""
    import cv2
    gh, gw = d.shape
    H, W = shape
    lm = pose.image
    seen = lm[:, 2] > 0.5
    torso = [i for i in (L_SH, R_SH, L_HIP, R_HIP) if seen[i]]
    if len(torso) < 2:
        return None, None
    su = int(np.clip(lm[torso, 0].mean() * W / step, 0, gw - 1))
    sv = int(np.clip(lm[torso, 1].mean() * H / step, 0, gh - 1))
    patch_ok = valid[max(0, sv - 4):sv + 5, max(0, su - 4):su + 5]
    patch = d[max(0, sv - 4):sv + 5, max(0, su - 4):su + 5][patch_ok]
    if not patch.size:                              # a hole at the torso: try the joints
        pv = np.clip((lm[torso, 1] * H / step).astype(int), 0, gh - 1)
        pu = np.clip((lm[torso, 0] * W / step).astype(int), 0, gw - 1)
        patch = d[pv, pu][valid[pv, pu]]
        if not patch.size:
            return None, None
    centre = float(np.median(patch))
    cand = valid & (np.abs(d - centre) <= DEPTH_REACH) & (heights > FEET_MARGIN)
    if pose.mask is not None:
        m = (np.asarray(pose.mask)[::step, ::step] > 0.4).astype(np.uint8)
        m = cv2.dilate(m, np.ones((5, 5), np.uint8)) > 0
        cand &= m[:gh, :gw]
    else:                                           # no mask: the landmarks' box, grown
        xs, ys = lm[seen, 0] * W / step, lm[seen, 1] * H / step
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        gx, gy = 0.35 * (x1 - x0) + 6, 0.25 * (y1 - y0) + 6
        box = np.zeros_like(cand)
        box[max(0, int(y0 - gy)):int(y1 + 4), max(0, int(x0 - gx)):int(x1 + gx)] = True
        cand &= box
    # Flying pixels: on a depth edge the Kinect reports depths between the person and the wall.
    med = cv2.medianBlur(np.where(valid, d, 0).astype(np.uint16), 3).astype(np.float32)
    cand &= np.abs(d - med) < 60
    cand = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    if n <= 1:
        return None, centre
    if pose.mask is not None:                       # everything left is this person
        big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 12]
        mask = np.isin(labels, big)
    else:                                           # the part around the torso
        label = labels[sv, su]
        if label == 0:
            ys, xs = np.nonzero(labels)
            k = np.argmin((ys - sv) ** 2 + (xs - su) ** 2)
            label = labels[ys[k], xs[k]]
        mask = labels == label
    return (mask if mask.sum() >= 60 else None), centre


def real(pose, mask, centre_mm, x, y, z, intr, shape):
    """A real person, not one on the TV or a poster: shoulders the right size for how far away
    the depth says they are (fusion.plausible, ~0.4 m), and a body that is not flat."""
    import fusion
    H, W = shape
    lm = pose.image
    if lm[L_SH, 2] > 0.5 and lm[R_SH, 2] > 0.5 and centre_mm:
        across = math.hypot((lm[L_SH, 0] - lm[R_SH, 0]) * W, (lm[L_SH, 1] - lm[R_SH, 1]) * H)
        if not fusion.plausible(across, centre_mm, intr[0], 0.40, low=0.3, high=2.2):
            return False
    pts = np.stack([x[mask], y[mask], z[mask]], axis=1)
    if len(pts) >= 200:
        if len(pts) > 3000:
            pts = pts[np.linspace(0, len(pts) - 1, 3000).astype(int)]
        s = np.linalg.svd(pts - pts.mean(axis=0), full_matrices=False, compute_uv=False)
        if s[2] / math.sqrt(len(pts)) < 0.012:      # flat as a screen to within ~1 cm
            return False
    return True


def point_at(lm_xy, mask, x, y, z, shape, step=STEP, r=3):
    """Camera-frame point of a landmark: the median of this person's depth around it."""
    H, W = shape
    gh, gw = mask.shape
    u, v = int(lm_xy[0] * W / step), int(lm_xy[1] * H / step)
    if not (0 <= u < gw and 0 <= v < gh):
        return None
    sl = (slice(max(0, v - r), v + r + 1), slice(max(0, u - r), u + r + 1))
    ok = mask[sl]
    if ok.sum() < 3:
        return None
    return np.array([np.median(x[sl][ok]), np.median(y[sl][ok]), np.median(z[sl][ok])])


# ------------------------------------------------------------------ posture

def features(pose, floor, mask, x, y, z, heights, shape, step=STEP):
    """What the posture rules look at, from the landmarks and this person's depth."""
    H, W = shape
    lm, seen = pose.image, pose.image[:, 2] > 0.5
    inside = (lm[:, 0] > 0.01) & (lm[:, 0] < 0.99) & (lm[:, 1] > 0.01) & (lm[:, 1] < 0.99)
    ok = seen & inside
    up = floor.up
    world = pose.world
    if world is None:                               # no metric landmarks: lift them with depth
        world = np.full((33, 3), np.nan, np.float32)
        for i in np.nonzero(ok)[0]:
            p = point_at(lm[i, :2], mask, x, y, z, shape, step)
            if p is not None:
                world[i] = p
    have = lambda *ids: all(ok[i] and not np.isnan(world[i]).any() for i in ids)   # noqa: E731
    mid = lambda a, b: (world[a] + world[b]) / 2                                    # noqa: E731

    f = {"legs": bool(ok[L_KNEE] and ok[R_KNEE] and (ok[L_ANK] or ok[R_ANK])),
         "torso": None, "knee": None, "thigh": None, "arms_up": False, "head_down": False}
    if have(L_SH, R_SH, L_HIP, R_HIP):
        f["torso"] = tilt_from(mid(L_SH, R_SH) - mid(L_HIP, R_HIP), up)
    elif have(L_SH, L_HIP):
        f["torso"] = tilt_from(world[L_SH] - world[L_HIP], up)
    elif have(R_SH, R_HIP):
        f["torso"] = tilt_from(world[R_SH] - world[R_HIP], up)
    knees, thighs = [], []
    for hip, knee, ank in ((L_HIP, L_KNEE, L_ANK), (R_HIP, R_KNEE, R_ANK)):
        if have(hip, knee):
            t = tilt_from(world[knee] - world[hip], -up)
            if t is not None:
                thighs.append(t)
            if have(ank):
                a = angle_at(world[hip], world[knee], world[ank])
                if a is not None:
                    knees.append(a)
    f["knee"] = min(knees) if knees else None
    f["thigh"] = max(thighs) if thighs else None
    # Arms up: a wrist above the nose (along true up).
    if ok[NOSE] and not np.isnan(world[NOSE]).any():
        for w in (L_WR, R_WR):
            if seen[w] and not np.isnan(world[w]).any() and (world[w] - world[NOSE]) @ up > 0.02:
                f["arms_up"] = True
        ears = [e for e in (L_EAR, R_EAR) if seen[e] and not np.isnan(world[e]).any()]
        if ears:
            f["head_down"] = bool((np.mean([world[e] for e in ears], axis=0) - world[NOSE]) @ up > 0.09)

    # Heights above the floor, from depth.
    def h_of(i):
        if not ok[i]:
            return None
        p = point_at(lm[i, :2], mask, x, y, z, shape, step)
        return None if p is None else float(floor.height(*p))
    hips = [h for h in (h_of(L_HIP), h_of(R_HIP)) if h is not None]
    f["hip_h"] = float(np.mean(hips)) if hips else None
    knees_h = [h for h in (h_of(L_KNEE), h_of(R_KNEE)) if h is not None]
    f["knee_h"] = min(knees_h) if knees_h else None
    eyes = [h for h in (h_of(L_EYE), h_of(R_EYE)) if h is not None]
    f["eye_h"] = float(np.mean(eyes)) if eyes else None
    f["head_seen"] = bool(seen[NOSE] and lm[NOSE, 1] > 0.02)
    return f


def classify(f):
    """The posture name from features()."""
    torso, knee, thigh = f.get("torso"), f.get("knee"), f.get("thigh")
    hip_h, knee_h, top = f.get("hip_h"), f.get("knee_h"), f.get("top")
    if torso is None:
        if top is not None and top < 0.6:
            return "lying"
        return "unknown"
    if torso > 60:
        return "lying"
    if f.get("legs") and thigh is not None:
        if knee_h is not None and knee_h < 0.18 and hip_h is not None and hip_h > 0.45 and thigh < 40:
            return "kneeling"
        if knee is not None and knee < 80:
            return "crouching"
        if hip_h is not None and hip_h < 0.30:
            return "crouching"
        if thigh > 50 and (knee is None or knee < 145):
            return "sitting"
        if knee is not None and knee < 140:
            return "crouching"                      # knees bent, thighs not level: ducking
        if torso > 30:
            return "bending"
        return "standing"
    # Legs hidden (a table, the sofa, the bottom of the picture): go by the hips and the head.
    if torso > 30:
        return "bending"
    if hip_h is not None:
        return "standing" if hip_h > 0.7 else "sitting" if hip_h < 0.65 else "unknown"
    if top is not None:
        return "standing" if top > 1.35 else "sitting"
    return "unknown"


def straightness(f):
    """(straight?, what to say) for someone standing: the first thing to fix."""
    if not f.get("head_seen") or f.get("head_cut"):
        return False, "Step back: your head is out of view"
    if f.get("side_cut"):
        return False, "Move towards the middle"
    if not f.get("legs"):
        return False, "Step back so I can see your feet"
    if f.get("distance") is not None and f["distance"] < 1.3:
        return False, "Step back a little"
    if f.get("distance") is not None and f["distance"] > 4.6:
        return False, "Come a little closer"
    if f.get("arms_up"):
        return False, "Lower your arms"
    if f.get("torso") is not None and f["torso"] > 12:
        return False, "Stand up straight"
    if f.get("knee") is not None and f["knee"] < 160:
        return False, "Straighten your knees"
    if f.get("head_down"):
        return False, "Look straight ahead"
    return True, "Hold still"


ASK = {
    "sitting": "Stand up to be measured",
    "crouching": "Stand up straight to be measured",
    "kneeling": "Stand up to be measured",
    "bending": "Stand up straight",
    "lying": "Stand up to be measured",
    "unknown": "Stand straight, facing the Kinect",
}


# ------------------------------------------------------------------ the picture

def outline(mask, step=STEP, n=OUTLINE_POINTS):
    """The person's silhouette as n points (full-resolution pixels), evenly spaced along it and
    starting at its top, so the page can glide one outline into the next."""
    import cv2
    m = mask.astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return []
    c = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float32) * step + step / 2
    if len(c) < 4:
        return []
    c = np.vstack([np.roll(c, -int(np.argmin(c[:, 1])), axis=0)])
    closed = np.vstack([c, c[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n, endpoint=False)
    return np.stack([np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])], axis=1)


def floor_ring(foot, floor, intr, radius=0.32, n=24):
    """A circle on the floor around someone's feet, as pixels (it is drawn under them)."""
    up = floor.up
    e1 = np.array([1.0, 0.0, 0.0]) - up[0] * up
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    out = []
    for a in np.linspace(0, 2 * math.pi, n, endpoint=False):
        p = foot + radius * (math.cos(a) * e1 + math.sin(a) * e2)
        if p[2] < 0.3:
            return []
        out.append(project(p, intr))
    return out


# ------------------------------------------------------------------ one frame

def observe(poses, depth, accel_up, mount_height, intr, floor_prev=None, step=STEP):
    """Every person in this frame: [{...}], and the floor used."""
    H, W = depth.shape
    x, y, z, valid, d = grid(depth, intr, step)
    floor = blend_floor(floor_prev, fit_floor(x, y, z, valid, accel_up, mount_height, floor_prev))
    heights = floor.height(x, y, z)
    seen = []
    taken = np.zeros_like(valid)
    order = sorted(range(len(poses)), key=lambda i: -float(poses[i].image[:, 2].sum()))
    for i in order:
        pose = poses[i]
        mask, centre = region(pose, d, valid, heights, (H, W), step)
        if mask is None:
            continue
        mask &= ~taken                              # a pixel belongs to one person only
        if mask.sum() < 60 or not real(pose, mask, centre, x, y, z, intr, (H, W)):
            continue
        taken |= mask
        ph = heights[mask]
        top = float(np.percentile(ph, 99.5))
        f = features(pose, floor, mask, x, y, z, heights, (H, W), step)
        if f["eye_h"] is not None and top < f["eye_h"] + 0.05:
            top = f["eye_h"] + EYE_TO_TOP           # dark hair left a hole on top of the head
        f["top"] = top
        rows, cols = np.nonzero(mask)
        f["head_cut"] = bool(rows.min() <= 1)
        f["side_cut"] = bool(cols.min() <= 1 or cols.max() >= mask.shape[1] - 2)
        pts = np.stack([x[mask], y[mask], z[mask]], axis=1)
        flat = pts - np.outer(pts @ floor.up, floor.up)
        centre3 = np.median(flat, axis=0)
        f["distance"] = float(np.linalg.norm(centre3))
        posture = classify(f)
        straight, hint = straightness(f) if posture == "standing" else (False, ASK[posture])
        # The head point (the top of the region) and the floor point under it, for the ruler.
        near_top = mask & (heights >= top - 0.03)
        if near_top.any():
            hp = np.array([np.median(x[near_top]), np.median(y[near_top]), np.median(z[near_top])])
        else:
            hp = pts[np.argmax(ph)]
        hp = hp + (top - float(floor.height(*hp))) * floor.up
        foot = hp - top * floor.up
        lm = pose.image
        seen.append({
            "pos": centre3, "top": top, "posture": posture, "straight": straight, "hint": hint,
            "features": f, "distance": f["distance"],
            "outline": outline(mask, step), "box": [int(cols.min()) * step, int(rows.min()) * step,
                                                    int(cols.max()) * step + step, int(rows.max()) * step + step],
            "head": project(hp, intr) if hp[2] > 0.3 else None,
            "foot": project(foot, intr) if foot[2] > 0.3 else None,
            "ring": floor_ring(foot, floor, intr),
            "skeleton": [[float(lm[k, 0]), float(lm[k, 1]), float(lm[k, 2])] for k in range(33)],
            "centre_x": float(cols.mean()) * step / W,
        })
    return seen, floor


# ------------------------------------------------------------------ over time

class Track:
    def __init__(self, tid, colour, obs, now):
        self.id, self.colour = tid, colour
        self.first = self.last = now
        self.votes = deque(maxlen=VOTES)
        self.posture = obs["posture"]
        self.samples = deque(maxlen=HISTORY)
        self.straight_since = None
        self.measured = None           # m, once locked
        self.measured_at = None
        self.live = obs["top"]
        self.obs = obs
        self.update(obs, now)

    def update(self, obs, now):
        self.obs, self.last = obs, now
        self.pos = obs["pos"]
        self.live = 0.6 * self.live + 0.4 * obs["top"]
        self.votes.append(obs["posture"])
        counts = {p: self.votes.count(p) for p in set(self.votes)}
        best = max(counts, key=counts.get)
        if best != self.posture and (counts[best] >= (VOTES + 1) // 2 or len(self.votes) < 3):
            self.posture = best
        if self.posture == "standing" and obs["posture"] == "standing" and obs["straight"]:
            if self.straight_since is None:
                self.straight_since = now
                self.samples.clear()
            self.samples.append(obs["top"])
            if now - self.straight_since >= LOCK_SECONDS and len(self.samples) >= 6:
                s = np.array(self.samples)
                if np.percentile(s, 90) - np.percentile(s, 10) <= LOCK_SPREAD:
                    self.measured = float(np.median(s))
                    if self.measured_at is None:
                        self.measured_at = now
        else:
            self.straight_since = None

    def progress(self, now):
        if self.measured is not None:
            return 1.0
        if self.straight_since is None:
            return 0.0
        return min(0.99, (now - self.straight_since) / LOCK_SECONDS)

    def state(self, now):
        """What the page and Mario get about this person."""
        o, f = self.obs, self.obs["features"]
        if self.posture == "standing":
            straight = o["posture"] == "standing" and o["straight"]
            hint = ("Measured" if self.measured is not None and straight else
                    "Hold still" if straight else o["hint"])
        else:
            straight, hint = False, ASK.get(self.posture, o["hint"])
        r = lambda v, k=3: None if v is None else round(float(v), k)   # noqa: E731
        return {
            "id": self.id, "colour": self.colour,
            "posture": self.posture, "label": POSTURES[self.posture],
            "straight": straight, "hint": hint,
            "height_cm": None if self.measured is None else int(round(self.measured * 100)),
            "live_cm": int(round(self.live * 100)),
            "measuring": r(self.progress(now), 2),
            "distance": r(o["distance"], 2),
            "box": o["box"], "head": _pt(o["head"]), "foot": _pt(o["foot"]),
            "ring": [_pt(p) for p in o["ring"]],
            "outline": [[round(float(px), 1), round(float(py), 1)] for px, py in o["outline"]],
            "skeleton": [[round(a, 4), round(b, 4), round(c, 2)] for a, b, c in o["skeleton"]],
            "angles": {"torso": r(f.get("torso"), 1), "knee": r(f.get("knee"), 1),
                       "thigh": r(f.get("thigh"), 1), "hip_cm": None if f.get("hip_h") is None
                       else int(round(f["hip_h"] * 100))},
            "x": round(o["centre_x"], 3),
        }


def _pt(p):
    return None if p is None else [round(float(p[0]), 1), round(float(p[1]), 1)]


class People:
    """Everyone over time. step() once per frame; state() for the page and Mario."""

    def __init__(self):
        self.tracks = []
        self.floor = None
        self.next_id = 1

    def step(self, poses, depth, accel_up, mount_height, intr, now):
        seen, self.floor = observe(poses, depth, accel_up, mount_height, intr, self.floor)
        pairs = sorted(((float(np.linalg.norm(t.pos - o["pos"])), ti, oi)
                        for ti, t in enumerate(self.tracks) for oi, o in enumerate(seen)),
                       key=lambda p: p[0])
        used_t, used_o = set(), set()
        for dist, ti, oi in pairs:
            if dist > MATCH_METRES or ti in used_t or oi in used_o:
                continue
            self.tracks[ti].update(seen[oi], now)
            used_t.add(ti)
            used_o.add(oi)
        for oi, o in enumerate(seen):
            if oi not in used_o:
                taken = {t.colour for t in self.tracks}
                colour = next((c for c in range(COLOURS) if c not in taken), self.next_id % COLOURS)
                self.tracks.append(Track(self.next_id, colour, o, now))
                self.next_id += 1
        self.tracks = [t for t in self.tracks if now - t.last <= LOST_AFTER]
        return self.state(now)

    def state(self, now):
        people = [t.state(now) for t in self.tracks if now - t.last < 0.4]
        people.sort(key=lambda p: p["x"])
        return {
            "count": len(people),
            "standing": sum(p["posture"] == "standing" for p in people),
            "postures": {k: sum(p["posture"] == k for p in people) for k in POSTURES
                         if any(p["posture"] == k for p in people)},
            "floor": self.floor.to_dict() if self.floor else None,
            "people": people,
        }


# ------------------------------------------------------------------ in words

def feet_inches(cm):
    total = cm / 2.54
    feet, inches = int(total // 12), int(round(total - 12 * (total // 12)))
    if inches == 12:
        feet, inches = feet + 1, 0
    return feet, inches


def say(state):
    """Mario's sentence about everyone in view."""
    people = state.get("people") or []
    if not people:
        return "I can't see anyone in front of the Kinect. Stand two to four metres away, facing it."
    note = ""
    if state.get("floor") and not state["floor"]["seen"]:
        note = " I couldn't see the floor, so that assumes the Kinect is where you set it."
    if len(people) == 1:
        p = people[0]
        if p["height_cm"] is not None:
            ft, inch = feet_inches(p["height_cm"])
            return f"You're {p['height_cm']} centimetres tall, about {ft} foot {inch}.{note}"
        if p["posture"] == "standing":
            return f"{p['hint']}, facing the Kinect, and ask me again."
        return (f"You look like you're {DOING[p['posture']]}. Please stand up straight, facing the "
                "Kinect, and ask me again.")
    counts = state.get("postures") or {}
    s = f"I can see {len(people)} people: " + _join([f"{n} {DOING[k]}" for k, n in counts.items()]) + "."
    measured = [p for p in people if p["height_cm"] is not None]
    if len(measured) == 1:
        s += f" One of you is {measured[0]['height_cm']} centimetres tall."
    elif measured:
        s += " From the left: " + _join([str(p["height_cm"]) for p in measured]) + " centimetres."
    if len(measured) < len(people):
        s += (" Everyone else, please stand up straight facing the Kinect." if measured else
              " Please stand up straight, facing the Kinect, so I can measure you.")
    return s + (note if measured else "")


def count(state):
    """Mario's answer to "how many people are there?"."""
    people = state.get("people") or []
    if not people:
        return "I can't see anyone in front of the Kinect."
    if len(people) == 1:
        p = people[0]
        return "Just one person." if p["posture"] == "unknown" else f"Just one person, {DOING[p['posture']]}."
    counts = state.get("postures") or {}
    return f"I can see {len(people)} people: " + _join([f"{n} {DOING[k]}" for k, n in counts.items()]) + "."


DOING = {"standing": "standing", "sitting": "sitting", "crouching": "crouching",
         "kneeling": "kneeling", "bending": "bending over", "lying": "lying down",
         "unknown": "partly hidden"}


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
