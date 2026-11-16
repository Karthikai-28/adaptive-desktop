"""How tall someone is, from one Kinect depth frame and its accelerometer. Pure numpy (+ cv2).

    up       the accelerometer gives which way is up in the camera's frame (camera: x right,
             y down, z forward; the Kinect's accelerometer axes are the camera's turned 180
             degrees about z, so up = (-ax, -ay, az), measured by tilting the motor)
    heights  every depth pixel as a 3D point, and its height along up (the camera is at 0)
    floor    the lowest dense layer of heights: where the floor is, which also gives how high
             the Kinect is mounted. Without a floor in view, the mount height in the settings
             (1.92 m: on top of the TV) stands in.
    person   the connected region of depth around a seed pixel on the torso (MediaPipe Pose
             gives it), with the floor cut away so the feet do not run into it
    height   the top of that region above the floor

measure() works on one frame; the hub takes the median of a second or so of frames.
"""

import math

import numpy as np

FX = FY = 525.0
CX, CY = 319.5, 239.5
NEAR, FAR = 450, 6000          # mm the Kinect measures reliably
FLOOR_BIN = 0.02               # m
FEET_MARGIN = 0.06             # m above the floor that is still floor, not feet


def up_vector(accel):
    ax, ay, az = (float(v) for v in accel)
    v = np.array([-ax, -ay, az])
    n = np.linalg.norm(v)
    if n < 1e-6:
        return np.array([0.0, -1.0, 0.0])
    return v / n


def points(depth, step=2):
    """(xyz Nx3 metres, (v, u) pixel rows/cols) of the valid pixels, every `step` pixels."""
    d = depth[::step, ::step].astype(np.float32)
    v, u = np.mgrid[0:depth.shape[0]:step, 0:depth.shape[1]:step]
    keep = (d >= NEAR) & (d <= FAR)
    z = d[keep] / 1000.0
    xyz = np.stack([(u[keep] - CX) * z / FX, (v[keep] - CY) * z / FY, z], axis=1)
    return xyz, (v[keep], u[keep])


def floor_level(heights, exclude=None):
    """The floor's height (m, negative: below the camera), or None when no floor is in view.

    The floor is a large flat layer, so it shows as a peak at the bottom of the heights.
    """
    h = heights if exclude is None else heights[~exclude]
    if h.size < 200:
        return None
    lo = float(np.percentile(h, 0.5))
    bins = np.arange(lo - FLOOR_BIN, lo + 1.2, FLOOR_BIN)
    counts, edges = np.histogram(h, bins=bins)
    need = max(150, int(0.04 * h.size))
    for i, c in enumerate(counts):
        if c >= need:
            near = h[(h >= edges[i] - FLOOR_BIN) & (h <= edges[i + 1] + FLOOR_BIN)]
            return float(np.median(near))
    return None


def person_mask(depth, seed, cut=None, tolerance=450, step=2):
    """Pixels (on the `step` grid) connected to the seed with no jump in depth over tolerance mm.

    cut: a mask (same grid) of pixels to leave out first, the floor.
    """
    import cv2
    d = depth[::step, ::step].astype(np.int32)
    sv, su = int(seed[1]) // step, int(seed[0]) // step
    sv = min(max(sv, 0), d.shape[0] - 1)
    su = min(max(su, 0), d.shape[1] - 1)
    patch = d[max(0, sv - 3):sv + 4, max(0, su - 3):su + 4]
    patch = patch[(patch >= NEAR) & (patch <= FAR)]
    if not patch.size:
        return None, None
    centre = int(np.median(patch))
    fg = ((d >= NEAR) & (d <= FAR) & (np.abs(d - centre) <= tolerance)).astype(np.uint8)
    if cut is not None:
        fg[cut] = 0
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels = cv2.connectedComponents(fg, connectivity=8)
    label = labels[sv, su]
    if label == 0:
        # the seed fell in a hole; take the component nearest to it
        ys, xs = np.nonzero(labels)
        if not ys.size:
            return None, centre
        k = np.argmin((ys - sv) ** 2 + (xs - su) ** 2)
        label = labels[ys[k], xs[k]]
    return labels == label, centre


def measure(depth, accel, seed, mount_height=1.92, step=2):
    """One frame's measurement: {"ok", "height", "distance", "floor", "camera_height", ...}.

    seed: (u, v) pixel on the person's torso in the (unmirrored) depth picture.
    """
    up = up_vector(accel)
    d = depth[::step, ::step].astype(np.float32)
    v, u = np.mgrid[0:depth.shape[0]:step, 0:depth.shape[1]:step]
    valid = (d >= NEAR) & (d <= FAR)
    z = np.where(valid, d / 1000.0, 0.0)
    x = (u - CX) * z / FX
    y = (v - CY) * z / FY
    h = x * up[0] + y * up[1] + z * up[2]          # height above the camera, per pixel

    # The floor first, from every point: it is far bigger than the feet standing on it. A
    # "floor" far from where the Kinect is said to be mounted is a sofa or a table, not the floor.
    floor = floor_level(h[valid])
    floor_seen = floor is not None and abs(-floor - float(mount_height)) <= 0.4
    if not floor_seen:
        floor = -float(mount_height)
    # Again without the floor, so the feet do not run into it.
    cut = valid & (h <= floor + FEET_MARGIN)
    person, centre = person_mask(depth, seed, cut, step=step)
    if person is None or person.sum() < 80:
        return {"ok": False, "error": "I can't find you in the depth picture. Stand in front of the Kinect."}
    rows = np.nonzero(person.any(axis=1))[0]
    if rows[0] <= 1:
        return {"ok": False, "error": "Your head is out of view. Step back a little so I can see all of you."}
    ph = h[person & valid]
    top = float(np.percentile(ph, 99.5))
    bottom = float(np.percentile(ph, 0.5))
    height = top - floor
    # How far away, across the floor: the person's points with their height taken out.
    pts = np.stack([x[person & valid], y[person & valid], z[person & valid]], axis=1)
    level = pts - np.outer(pts @ up, up)
    distance = float(np.median(np.linalg.norm(level, axis=1)))
    feet = floor_seen and bottom - floor < 0.15
    if not 0.5 < height < 2.6:
        return {"ok": False, "error": "That didn't look like a person standing. Stand up straight, facing the Kinect."}
    return {"ok": True, "height": round(height, 3), "distance": round(distance, 2),
            "floor": "seen" if floor_seen else "mount", "feet": bool(feet),
            "camera_height": round(-floor, 3), "tilt": round(math.degrees(math.asin(-up[2])), 1)}


def summarise(results):
    """The median of several frames' measurements, or the most common reason none worked."""
    good = [r for r in results if r.get("ok")]
    if len(good) < max(3, len(results) // 3):
        errors = [r["error"] for r in results if not r.get("ok")]
        return {"ok": False, "error": max(set(errors), key=errors.count) if errors
                else "I couldn't see you."}
    heights = np.array([r["height"] for r in good])
    height = float(np.median(heights))
    feet_total = height / 0.3048
    feet, inches = int(feet_total), round((feet_total - int(feet_total)) * 12)
    if inches == 12:
        feet, inches = feet + 1, 0
    floor_seen = sum(r["floor"] == "seen" for r in good) > len(good) / 2
    return {"ok": True, "height": round(height, 3), "feet": feet, "inches": inches,
            "spread_cm": round(float(np.percentile(heights, 90) - np.percentile(heights, 10)) * 100, 1),
            "distance": float(np.median([r["distance"] for r in good])),
            "floor": "seen" if floor_seen else "mount",
            "camera_height": float(np.median([r["camera_height"] for r in good])),
            "frames": len(good)}


def say(summary):
    """The sentence Mario says."""
    if not summary.get("ok"):
        return summary.get("error") or "I couldn't measure you."
    s = (f"You're {summary['height']:.2f} metres tall, about {summary['feet']} foot "
         f"{summary['inches']}.")
    if summary["floor"] == "mount":
        s += " I couldn't see the floor, so that assumes the Kinect is where you set it."
    return s
