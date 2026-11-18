#!/usr/bin/env python3
"""The Kinect hub: the one process that opens the Kinect, and everything that wants it.

libfreenect lets one process at a time open the Kinect, so this one does and shares it:

    frames.py   every frame (colour or infrared + depth registered to it) in shared memory,
                for Air's gestures
    webcam      the colour picture as a camera any app can pick ("Kinect Camera", a
                v4l2loopback device: scripts/install-virtual-cameras.sh makes it)
    studio      Kinect Studio at http://127.0.0.1:8792: the picture, depth, the point cloud,
                the accelerometer, tilt motor and LED, stream rates, a PLY export
    people      everyone in view (people.py): how many, their posture, their height in cm; for
                Studio's overlay (/api/people) and Mario (/api/measure). Runs only while asked.

    kinect_hub.py            run (the user service adaptive-kinect.service)
    kinect_hub.py --port N   another port

It stops itself (LED off) when nothing has used it for IDLE_EXIT seconds and the webcam is off,
so the camera is never left on by accident. Settings in ~/.config/adaptive-desktop/kinect.json:
{"webcam": false, "video": "auto", "tilt": null, "mount_height": 1.92,
 "dark_below": 0.04, "light_above": 0.07}
video: auto (colour while the room is lit, infrared in the dark: fusion.LightSwitch), rgb or ir.
mount_height: metres from the floor to the Kinect, for measuring people when the floor is out of
view (1.92 = on the TV). HTTP is bound to 127.0.0.1 only. docs/AIR.md.
"""

import argparse
import asyncio
import json
import math
import os
import queue
import struct
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import frames  # noqa: E402
import fusion  # noqa: E402
import kinect  # noqa: E402

PORT = 8792
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "adaptive-desktop/kinect.json"
STUDIO = HERE / "studio"
MODELS = HERE.parent.parent / ".local/air-models"
POSE_MODEL = MODELS / "pose_landmarker_full.task"
DETECTOR_MODEL = MODELS / "efficientdet_lite0.tflite"
MAX_PEOPLE = 6
PEOPLE_LINGER = 3.0    # s the people tracker keeps running after the last request
IDLE_EXIT = 20.0
REPROBE = 3.0
WEBCAM_NAME = "Kinect Camera"
VIDEO = ("auto", "rgb", "ir")
BUSY_STALE = 3.0       # s: Air saying it is engaged counts only while Air still reads frames
ACTIVITY_MAX = 10.0    # s an app may hold "an activity is live" (no colour checks) per request
LEASE_MAX = 600.0      # s a scan may hold one picture mode per request


def log(msg):
    print(f"[kinect-hub] {msg}", flush=True)


# ------------------------------------------------------------------ pure helpers

def load_settings(path=CONFIG):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data, path=CONFIG):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def angles(accel):
    """(pitch, roll) in degrees from the accelerometer; level and upright is (0, 0)."""
    ax, ay, az = (float(v) for v in accel)
    if not (ax or ay or az):
        return 0.0, 0.0
    pitch = math.degrees(math.atan2(az, math.hypot(ax, ay)))
    roll = math.degrees(math.atan2(ax, ay))
    return round(pitch, 1), round(roll, 1)


def depth_stats(depth, bins=32, near=400, far=4000):
    """Nearest / median / farthest valid distance (mm), share of valid pixels, a histogram."""
    import numpy as np
    small = depth[::4, ::4]
    valid = small[(small >= near) & (small <= far)]
    hist = np.histogram(valid, bins=bins, range=(near, far))[0] if valid.size else np.zeros(bins)
    peak = max(1, int(hist.max()))
    return {
        "valid": round(100.0 * valid.size / small.size, 1),
        "nearest": int(valid.min()) if valid.size else None,
        "median": int(np.median(valid)) if valid.size else None,
        "farthest": int(valid.max()) if valid.size else None,
        "hist": [round(int(v) / peak, 3) for v in hist],
        "range": [near, far],
    }


def colour_depth(depth, near=400, far=4000):
    """Depth as a picture (BGR, for JPEG): near is warm, far is cool, no reading is black."""
    import cv2
    import numpy as np
    d = depth.astype(np.float32)
    scaled = np.clip((far - d) / (far - near), 0, 1) * 255
    img = cv2.applyColorMap(scaled.astype(np.uint8), cv2.COLORMAP_TURBO)
    img[(depth == 0) | (depth > far)] = 0
    return img


def point_cloud(rgb, depth, step=4, far=4000, mode="rgb"):
    """(xyz float32 Nx3 in metres, camera frame: x right, y down, z forward; rgb uint8 Nx3).

    mode: which camera the depth is aligned to (the colour one, or in infrared the IR one)."""
    import numpy as np
    FX, FY, CX, CY = kinect.intrinsics(mode)
    d = depth[::step, ::step].astype(np.float32)
    v, u = np.mgrid[0:depth.shape[0]:step, 0:depth.shape[1]:step]
    keep = (d > 0) & (d <= far)
    z = d[keep] / 1000.0
    x = (u[keep] - CX) * z / FX
    y = (v[keep] - CY) * z / FY
    xyz = np.stack([x, y, z], axis=1).astype(np.float32)
    colours = rgb[::step, ::step][keep].astype(np.uint8)
    return xyz, colours


def cloud_bytes(xyz, colours, seq=0):
    """The point cloud for the page: u32 count, u32 seq, float32 xyz * n, uint8 rgb * n."""
    return struct.pack("<II", len(xyz), seq & 0xFFFFFFFF) + xyz.tobytes() + colours.tobytes()


def ply_bytes(xyz, colours):
    """A binary PLY of the point cloud (opens in MeshLab, CloudCompare, Blender, Open3D)."""
    import numpy as np
    head = ("ply\nformat binary_little_endian 1.0\ncomment Kinect v1, Adaptive Desktop\n"
            f"element vertex {len(xyz)}\nproperty float x\nproperty float y\nproperty float z\n"
            "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    rows = np.zeros(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                      ("r", "u1"), ("g", "u1"), ("b", "u1")])
    rows["x"], rows["y"], rows["z"] = xyz[:, 0], -xyz[:, 1], -xyz[:, 2]   # y up, looking down -z
    rows["r"], rows["g"], rows["b"] = colours[:, 0], colours[:, 1], colours[:, 2]
    return head.encode() + rows.tobytes()


def find_webcam(name=WEBCAM_NAME, sysfs="/sys/devices/virtual/video4linux"):
    """/dev/videoN of the v4l2loopback device with this name, or None."""
    try:
        entries = sorted(Path(sysfs).iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            if (entry / "name").read_text().strip() == name:
                return f"/dev/{entry.name}"
        except OSError:
            continue
    return None


# ------------------------------------------------------------------ the webcam

class Webcam:
    """Colour frames into the "Kinect Camera" loopback device through GStreamer."""

    def __init__(self, device):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        self.Gst = Gst
        self.device = device
        self.pipeline = Gst.parse_launch(
            "appsrc name=src is-live=true do-timestamp=true format=time "
            f"caps=video/x-raw,format=RGB,width={frames.W},height={frames.H},framerate=30/1 "
            "! videoconvert ! video/x-raw,format=YUY2 "
            f"! v4l2sink device={device} sync=false")
        self.src = self.pipeline.get_by_name("src")
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise OSError(f"the webcam {device} would not start")

    def push(self, rgb):
        self.src.emit("push-buffer", self.Gst.Buffer.new_wrapped(rgb.tobytes()))
        msg = self.pipeline.get_bus().pop_filtered(self.Gst.MessageType.ERROR)
        if msg:
            err, _ = msg.parse_error()
            raise OSError(f"webcam: {err.message}")

    def close(self):
        self.src.emit("end-of-stream")
        self.pipeline.set_state(self.Gst.State.NULL)


# ------------------------------------------------------------------ everyone's pose

class PoseSource:
    """Every person's landmarks, metric world landmarks and own mask in a picture.

    Top-down, as multi-person pose systems do it: a person detector (EfficientDet, COCO
    "person") finds everyone, then each person gets their own Pose Landmarker that follows them
    from frame to frame on a square crop around them (as air.py follows each hand). MediaPipe's
    one-shot multi-person mode misses most people in a group; this way each person is the only
    subject of their own model.

    The detector costs ~70 ms a frame and a new landmarker ~150 ms to build on this laptop
    (measured), more than a frame's budget, so neither happens on the frame path: the finder
    thread runs the detector on the newest frame it is given (continuously while nobody is
    followed, every FIND_EVERY s otherwise) and hands over newcomers with a landmarker it has
    already built; spare landmarkers are kept warm. The frame path only runs the followers.

    In infrared the picture is the projector's dot pattern: it is cleaned first (a median filter
    and CLAHE, as Air does for hands). Every crop also greys out what depth says is far behind or
    in front of its person (depth-supported foreground), which matters most in infrared, where a
    sofa and a person are the same grey. Models: .local/air-models (scripts/install-air.sh).
    Without the detector: the multi-person landmarker on the whole picture; without that either:
    the one-person Pose in MediaPipe."""

    FIND_EVERY = 0.4        # s between looks for newcomers while someone is followed
    MISSES = 3              # frames a follower may lose its person before it is let go
    REJECTS = 15            # frames depth may say "not a person" (a poster, a coat) before it is
    IGNORE_S = 20.0         # let go, and that place is ignored for this long
    SPARE = 2               # landmarkers built ahead
    BEHIND_MM, AHEAD_MM = 900, 1300    # depth kept around a person's torso in their crop

    def __init__(self, model=POSE_MODEL, detector=DETECTOR_MODEL, max_people=MAX_PEOPLE):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self.mp, self.vision, self.BaseOptions = mp, vision, BaseOptions
        self.model, self.max_people = str(model), max_people
        self.task = self.legacy = self.detector = None
        self.followers = []
        self.pool = None
        self.last_ts = 0
        self.ts_lock = threading.Lock()
        self._clahe = None
        self.finder = None
        self.timing = {}
        self.out = []           # the follower behind each pose detect() returned
        self.ignored = []       # [(box, until, depth mm)]: places depth said hold no person
        if Path(model).is_file() and Path(detector).is_file():
            self.detector = vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(detector)),
                running_mode=vision.RunningMode.IMAGE, score_threshold=0.4,
                category_allowlist=["person"], max_results=max_people))
            self.kind = "top-down"
            self.finder = Finder(self)
        elif Path(model).is_file():
            self.task = vision.PoseLandmarker.create_from_options(self._options(max_people))
            self.kind = "multi"
        else:
            self.legacy = mp.solutions.pose.Pose(model_complexity=1, enable_segmentation=True)
            self.kind = "single"

    def _options(self, num_poses=1):
        return self.vision.PoseLandmarkerOptions(
            base_options=self.BaseOptions(model_asset_path=self.model),
            running_mode=self.vision.RunningMode.VIDEO, num_poses=num_poses,
            min_pose_detection_confidence=0.3, min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5, output_segmentation_masks=True)

    def new_landmarker(self):
        """A landmarker, warmed: its first inference costs ~3x a later one (measured), so it is
        spent here, off the frame path, on a blank square."""
        import numpy as np
        lm = self.vision.PoseLandmarker.create_from_options(self._options())
        lm.detect_for_video(self._image(np.full((256, 256, 3), 128, np.uint8)), self._ts())
        return lm

    def _ts(self):
        with self.ts_lock:
            self.last_ts = max(self.last_ts + 1, int(time.monotonic() * 1000))   # must always increase
            return self.last_ts

    def _image(self, rgb):
        return self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)

    def prepare(self, rgb, mode):
        """What the models look at: the colour picture, or the infrared one cleaned up."""
        import numpy as np
        if mode != "ir":
            return np.ascontiguousarray(rgb)
        import cv2
        if self._clahe is None:
            self._clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        grey = self._clahe.apply(cv2.medianBlur(np.ascontiguousarray(rgb[:, :, 0]), 5))
        return cv2.cvtColor(grey, cv2.COLOR_GRAY2RGB)

    @staticmethod
    def _poses(result, place):
        """people.Pose list from a landmarker result; place maps crop (x, y, mask) to the frame."""
        import numpy as np

        import people
        out = []
        for i, lms in enumerate(result.pose_landmarks):
            world = result.pose_world_landmarks[i] if i < len(result.pose_world_landmarks or []) else None
            mask = None
            if result.segmentation_masks and i < len(result.segmentation_masks):
                mask = np.squeeze(result.segmentation_masks[i].numpy_view())
            image = np.array([(p.x, p.y, p.visibility or 0.0) for p in lms], np.float32)
            image, mask = place(image, mask)
            out.append(people.Pose(image, None if world is None else [(p.x, p.y, p.z) for p in world], mask))
        return out

    def detect(self, rgb, depth=None, mode="rgb"):
        """The poses in one frame. rgb: the picture as the camera gave it; depth: millimetres in
        the same geometry (or None); mode: "rgb" or "ir"."""
        import numpy as np
        t0 = time.perf_counter()
        rgb = self.prepare(rgb, mode)
        H, W = rgb.shape[:2]
        if self.detector is None:
            if self.task is not None:
                r = self.task.detect_for_video(self._image(rgb), self._ts())
                return self._poses(r, lambda image, mask: (image, mask))
            r = self.legacy.process(rgb)
            if not r.pose_landmarks:
                return []
            import people
            world = r.pose_world_landmarks.landmark if r.pose_world_landmarks else None
            return [people.Pose([(p.x, p.y, p.visibility) for p in r.pose_landmarks.landmark],
                                None if world is None else [(p.x, p.y, p.z) for p in world],
                                r.segmentation_mask)]

        # Newcomers the finder has found since the last frame (each with its own landmarker).
        self.finder.offer(rgb, bool(self.followers))
        now = time.monotonic()
        self.ignored = [x for x in self.ignored if x[1] > now]
        for box, lm in self.finder.take():
            if len(self.followers) < self.max_people and all(
                    iou(box, f["box"]) < 0.3 and not inside(centre(box), f["box"]) for f in self.followers) \
                    and not self._still_ignored(box, depth):
                self.followers.append({"lm": lm, "box": box, "miss": 0, "ts": 0, "z": None, "rejects": 0})
            else:
                self.finder.give_back(lm)

        # Each follower on its own square crop, all at once (MediaPipe lets go of the GIL).
        jobs = []
        for f in list(self.followers):
            job = self._crop(f, rgb, depth, W, H)
            if job is None:
                self._drop(f)
            else:
                jobs.append(job)
        if self.pool is None:
            from concurrent.futures import ThreadPoolExecutor
            self.pool = ThreadPoolExecutor(self.max_people, thread_name_prefix="pose")
        t1 = time.perf_counter()
        results = list(self.pool.map(
            lambda j: self._poses(j["f"]["lm"].detect_for_video(self._image(j["crop"]), j["ts"]), j["place"]),
            jobs))
        t2 = time.perf_counter()

        out, torsos = [], []
        self.out = []
        for job, poses in zip(jobs, results):
            f = job["f"]
            x0, y0, x1, y1 = f["box"]
            bw, bh = x1 - x0, y1 - y0
            pose = poses[0] if poses else None
            seen = pose.image[:, 2] > 0.5 if pose is not None else None
            body = [i for i in (11, 12, 23, 24) if seen[i]] if pose is not None else []
            torso = (float(pose.image[body, 0].mean() * W), float(pose.image[body, 1].mean() * H)) \
                if len(body) >= 2 else None
            grown = (x0 - 0.2 * bw, y0 - 0.1 * bh, x1 + 0.2 * bw, y1 + 0.1 * bh)
            if torso is None or not inside(torso, grown):    # lost, or wandered off to someone else
                f["miss"] += 1
                if f["miss"] > self.MISSES:
                    self._drop(f)
                continue
            if any(abs(torso[0] - t[0]) < 0.04 * W and abs(torso[1] - t[1]) < 0.04 * H for t in torsos):
                self._drop(f)                                # two followers on one person
                continue
            torsos.append(torso)
            f["miss"] = 0
            f["z"] = torso_depth(depth, torso) if depth is not None else None
            # Follow them: the next crop is around their mask (it includes the top of the head).
            if pose.mask is not None and (pose.mask > 0.5).sum() > 50:
                ys, xs = np.nonzero(pose.mask > 0.5)
                f["box"] = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
            else:
                xs, ys = pose.image[seen, 0] * W, pose.image[seen, 1] * H
                h = ys.max() - ys.min()
                f["box"] = (float(xs.min()), float(ys.min() - 0.15 * h), float(xs.max()), float(ys.max()))
            out.append(pose)
            self.out.append(f)
        self.timing = {"prepare_ms": round(1000 * (t1 - t0), 1), "models_ms": round(1000 * (t2 - t1), 1),
                       "followers": len(self.followers)}
        return out

    def _crop(self, f, rgb, depth, W, H):
        """The square crop a follower looks at (only its person in it), and how to map back."""
        import cv2
        import numpy as np
        x0, y0, x1, y1 = f["box"]
        side = max(x1 - x0, y1 - y0) * 1.25 + 16
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        sx, sy, S = int(cx - side / 2), int(cy - side / 2), int(side)
        ax0, ay0, ax1, ay1 = max(sx, 0), max(sy, 0), min(sx + S, W), min(sy + S, H)
        if ax1 <= ax0 or ay1 <= ay0:
            return None
        crop = np.zeros((S, S, 3), np.uint8)                  # square, padded at the edges
        crop[ay0 - sy:ay1 - sy, ax0 - sx:ax1 - sx] = rgb[ay0:ay1, ax0:ax1]
        # Grey out the crop beyond their box, so a neighbour standing close is not who the
        # model sees.
        bw, bh = x1 - x0, y1 - y0
        kx0, kx1 = int(x0 - 0.18 * bw - 6) - sx, int(x1 + 0.18 * bw + 6) - sx
        ky0, ky1 = int(y0 - 0.10 * bh - 6) - sy, int(y1 + 0.10 * bh + 6) - sy
        keep = np.zeros((S, S), bool)
        keep[max(ky0, 0):max(ky1, 0), max(kx0, 0):max(kx1, 0)] = True
        # And what depth says is not them: far behind (a wall, a sofa) or far in front. No
        # reading (0) is kept: hair and dark clothes often have none.
        if depth is not None and f.get("z"):
            d = np.zeros((S, S), np.uint16)
            d[ay0 - sy:ay1 - sy, ax0 - sx:ax1 - sx] = depth[ay0:ay1, ax0:ax1]
            keep &= ~(((d > f["z"] + self.BEHIND_MM) | ((d > 0) & (d < f["z"] - self.AHEAD_MM))))
        crop[~keep] = 128
        f["ts"] = max(f["ts"] + 1, self._ts())

        def place(image, mask):
            image = image.copy()
            image[:, 0] = (sx + image[:, 0] * S) / W
            image[:, 1] = (sy + image[:, 1] * S) / H
            full = None
            if mask is not None:
                full = np.zeros((H, W), np.float32)
                m = mask if mask.shape[:2] == (S, S) else cv2.resize(mask, (S, S))
                full[ay0:ay1, ax0:ax1] = m[ay0 - sy:ay1 - sy, ax0 - sx:ax1 - sx]
            return image, full

        return {"f": f, "crop": crop, "ts": f["ts"], "place": place}

    def _still_ignored(self, box, depth):
        """Is this box a place depth already said holds no person, and nothing has moved in
        since (the depth there within 30 cm of what it was)?"""
        for b, _, z in self.ignored:
            if iou(box, b) < 0.5:
                continue
            now = torso_depth(depth, centre(box)) if depth is not None else None
            if z is None or now is None or abs(now - z) < 300:
                return True
        return False

    def verdict(self, accepted, depth=None):
        """people.py's word on the poses detect() just returned (indices of the real people). A
        follower that depth keeps saying is not a person is let go, and its place ignored for a
        while, so a poster or a coat on a chair does not cost a model run every frame."""
        for i, f in enumerate(self.out):
            if f not in self.followers:
                continue
            if i in accepted:
                f["rejects"] = 0
                continue
            f["rejects"] = f.get("rejects", 0) + 1
            if f["rejects"] >= self.REJECTS:
                z = torso_depth(depth, centre(f["box"])) if depth is not None else None
                self.ignored.append((f["box"], time.monotonic() + self.IGNORE_S, z))
                self._drop(f)

    def _drop(self, f):
        self.followers.remove(f)
        # A landmarker in VIDEO mode remembers who it followed; a fresh one is cleaner than reuse.
        f["lm"].close()

    def close(self):
        if self.finder is not None:
            self.finder.close()
        if self.pool is not None:
            self.pool.shutdown(wait=True)
        for f in list(self.followers):
            self._drop(f)
        for x in (self.task, self.legacy, self.detector):
            if x is not None:
                x.close()


class Finder:
    """PoseSource's person detector, off the frame path (a thread): the newest frame in, boxes of
    people with a landmarker ready for each out."""

    def __init__(self, source):
        self.source = source
        self.cv = threading.Condition()
        self.frame = None
        self.busy = False          # someone is followed: look only every FIND_EVERY s
        self.found = []
        self.spare = []
        self.stopped = False
        self.last = 0.0
        self.ms = None
        self.thread = threading.Thread(target=self._run, name="pose-finder", daemon=True)
        self.thread.start()

    def offer(self, rgb, busy):
        with self.cv:
            self.frame, self.busy = rgb, busy
            self.cv.notify()

    def take(self):
        with self.cv:
            out, self.found = self.found, []
            return out

    def give_back(self, lm):
        with self.cv:
            if len(self.spare) < PoseSource.SPARE and not self.stopped:
                self.spare.append(lm)
                return
        lm.close()

    def _landmarker(self):
        with self.cv:
            if self.spare:
                return self.spare.pop()
        return self.source.new_landmarker()

    def _run(self):
        src = self.source
        while True:
            with self.cv:
                while True:
                    if self.stopped:
                        return
                    due = self.frame is not None and not (
                        self.busy and time.monotonic() - self.last < PoseSource.FIND_EVERY)
                    if due:
                        rgb, self.frame, job = self.frame, None, "find"
                        break
                    if len(self.spare) < PoseSource.SPARE:
                        job = "spare"                 # build one while there is time
                        break
                    self.cv.wait(0.05)
            if job == "spare":
                self.give_back(src.new_landmarker())
                continue
            self.last = time.monotonic()
            t0 = time.perf_counter()
            found = src.detector.detect(src._image(rgb)).detections
            self.ms = round(1000 * (time.perf_counter() - t0), 1)
            new = []
            for d in sorted(found, key=lambda d: -d.categories[0].score):
                b = d.bounding_box
                box = (b.origin_x, b.origin_y, b.origin_x + b.width, b.origin_y + b.height)
                if any(iou(box, f["box"]) >= 0.3 or inside(centre(box), f["box"])
                       for f in list(src.followers)):
                    continue
                new.append((box, self._landmarker()))
            with self.cv:
                self.found.extend(new)

    def close(self):
        with self.cv:
            self.stopped = True
            self.cv.notify_all()
        self.thread.join(timeout=2)
        for _, lm in self.found:
            lm.close()
        for lm in self.spare:
            lm.close()
        self.found, self.spare = [], []


def torso_depth(depth, torso, r=6):
    """Median depth (mm) around a torso point in the picture, or None."""
    import numpy as np
    u, v = int(torso[0]), int(torso[1])
    H, W = depth.shape
    patch = depth[max(0, v - r):min(H, v + r + 1), max(0, u - r):min(W, u + r + 1)]
    ok = patch[(patch > 300) & (patch < 9000)]
    return float(np.median(ok)) if ok.size >= 5 else None


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def centre(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def inside(p, box):
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


# ------------------------------------------------------------------ the hub

class Hub:
    def __init__(self, settings):
        self.settings = settings
        self.video = settings.get("video") if settings.get("video") in VIDEO else "auto"
        self.mode = "ir" if self.video == "ir" else "rgb"
        self.switch = fusion.LightSwitch(float(settings.get("dark_below", 0.04)),
                                         float(settings.get("light_above", 0.07)))
        self.busy = False      # Air is engaged: no colour checks from infrared while it is
        self.activity_until = 0.0   # a workout or game is live (Kinect Motion): the same
        self.lease = None      # {"owner", "mode", "until"}: a scan holds one picture mode
        self.snap = None       # frames.Snapshot: the newest frame, all of it under one lock
        self.epoch = 0         # colour/infrared switches so far
        self.unpaired = 0      # picture + depth pairs dropped: not taken together
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.rgb = self.depth = None
        self.seq = 0
        self.captured = 0.0      # wall-clock time of the newest frame, for end-to-end latency
        self.fps = 0.0
        self.motor = {"accel": [0, 0, 0], "tilt": None, "status": None}
        self.led = None
        self.stats = None
        self.light = None        # how bright the picture is, 0..1 (too dark for colour: < 0.04)
        self.status = "starting"
        self.error = None
        self.webcam = None
        self.webcam_error = None
        self.last_use = time.monotonic()
        self.studio_clients = 0
        self.writer = None
        self._jpeg = {}
        self._cloud = {}
        self.people_state = {"count": 0, "standing": 0, "people": [], "running": False}
        self.people_seq = 0
        self.people_until = 0.0
        self.people_thread = None

    # -- commands from the page / Air, carried out on the capture thread

    def command(self, name, value):
        self.last_use = time.monotonic()
        if name == "webcam":
            self.settings["webcam"] = bool(value)
            save_settings(self.settings)
        elif name == "video" and value in VIDEO:
            self.settings["video"] = value
            save_settings(self.settings)
        elif name == "busy":
            self.busy = bool(value)
            return
        elif name == "activity":
            # {"value": seconds}: a workout or game is live for that long (re-sent while it is).
            try:
                hold = min(ACTIVITY_MAX, max(0.0, float(value or 0)))
            except (TypeError, ValueError):
                hold = 0.0
            self.activity_until = time.monotonic() + hold if hold else 0.0
            return
        elif name == "lease":
            # {"value": {"owner": "scan", "mode": "ir", "seconds": 120}} holds the picture mode;
            # {"value": null} lets it go. While held, the light switch does not change it.
            if isinstance(value, dict) and value.get("mode") in ("rgb", "ir"):
                seconds = min(LEASE_MAX, max(1.0, float(value.get("seconds") or 60)))
                self.lease = {"owner": str(value.get("owner") or "app")[:40], "mode": value["mode"],
                              "until": time.monotonic() + seconds}
                self.commands.put(("force", value["mode"]))
            else:
                self.lease = None
            return
        self.commands.put((name, value))

    def _apply(self, cam):
        while True:
            try:
                name, value = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                if name == "led" and value in kinect.LED:
                    cam.led(value)
                    self.led = value
                elif name == "tilt":
                    cam.tilt(float(value))
                elif name == "video" and value in VIDEO:
                    self.video = value
                    self.switch = fusion.LightSwitch(self.switch.dark_below,
                                                     self.switch.light_above)
                    if value != "auto" and not self._leased():
                        self.mode = value
                elif name == "force" and value in ("rgb", "ir"):
                    self.mode = value
            except (OSError, ValueError) as err:
                log(f"{name}: {err}")

    def _sync_webcam(self, rgb):
        want = bool(self.settings.get("webcam"))
        if want and self.webcam is None:
            device = find_webcam()
            if not device:
                self.webcam_error = ("No 'Kinect Camera' device: run "
                                     "scripts/install-virtual-cameras.sh once (asks for sudo).")
                return
            try:
                self.webcam = Webcam(device)
                self.webcam_error = None
                log(f"webcam on: {device}")
            except (OSError, ValueError) as err:
                self.webcam_error = str(err)
                return
        if not want and self.webcam is not None:
            self.webcam.close()
            self.webcam = None
            log("webcam off")
        if self.webcam is not None:
            try:
                self.webcam.push(rgb)
            except OSError as err:
                self.webcam_error = str(err)
                self.webcam.close()
                self.webcam = None

    def _busy(self, now):
        """No colour checks from infrared now: Air is engaged (and still reading), or a workout
        or game is live. A look at colour interrupts infrared tracking for most of a second."""
        seen = self.writer.client_seen() if self.writer else 0.0
        return (self.busy and now - seen < BUSY_STALE) or now < self.activity_until

    def _leased(self, now=None):
        now = time.monotonic() if now is None else now
        if self.lease is not None and now >= self.lease["until"]:
            self.lease = None
        return self.lease is not None

    def idle(self, now):
        if self.settings.get("webcam") or self.studio_clients > 0:
            return False
        seen = self.writer.client_seen() if self.writer else 0.0
        return now - max(self.last_use, seen) > IDLE_EXIT

    def run(self):
        """The capture loop (a thread)."""
        cam = None
        last_probe = 0.0
        frames_n, fps_t, last_state, last_stats = 0, time.monotonic(), 0.0, 0.0
        last_vts, last_mode = None, None
        self.writer = frames.Writer()
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                if self.idle(now):
                    log("nothing is using the Kinect; stopping")
                    break
                if cam is None:
                    if now - last_probe < REPROBE:
                        self.stop.wait(0.2)
                        continue
                    last_probe = now
                    usb = kinect.probe()
                    if not usb["camera"]:
                        self.status = "no-kinect" if not usb["present"] else "unpowered"
                        self.error = usb["advice"]
                        continue
                    try:
                        cam = kinect.Camera()
                        cam.read(self.mode)
                        if self.settings.get("tilt") is not None:
                            cam.tilt(float(self.settings["tilt"]))
                        cam.led("blink-green")
                        self.led = "blink-green"
                        self.status, self.error = "streaming", None
                        log("Kinect streaming")
                    except OSError as err:
                        self.status, self.error = "error", str(err)
                        cam = None
                        continue
                self._apply(cam)
                mode = self.mode
                try:
                    rgb, depth, (vts, dts) = cam.read(mode, stamps=True)
                except OSError as err:
                    log(f"Kinect lost: {err}")
                    self.status, self.error = "error", str(err)
                    try:
                        cam.close()
                    except OSError:
                        pass
                    cam = None
                    continue
                # A picture and a depth frame not taken together (the first pair after a
                # colour/infrared switch is half a second apart), or a repeat: never published.
                if not kinect.paired(vts, dts) or vts == last_vts:
                    self.unpaired += 1
                    last_vts = vts
                    continue
                last_vts = vts
                if mode != last_mode:
                    if last_mode is not None:
                        self.epoch += 1
                    last_mode = mode
                if now - last_state >= 0.2:
                    try:
                        self.motor = cam.state()
                    except OSError:
                        pass
                    last_state = now
                frames_n += 1
                if now - fps_t >= 1.0:
                    self.fps, frames_n, fps_t = frames_n / (now - fps_t), 0, now
                captured = time.time()
                self.writer.write(rgb, depth, mode, self.motor["accel"],
                                  self.motor["tilt"], self.fps, self.epoch)
                snap = frames.Snapshot(rgb, depth, mode, kinect.intrinsics(mode), self.writer.seq,
                                       captured, now, self.motor["accel"], self.epoch, (vts, dts))
                with self.lock:
                    self.snap = snap
                    self.rgb, self.depth, self.seq = rgb, depth, self.writer.seq
                    self.captured = captured
                if mode == "rgb":
                    self.light = round(fusion.light_level(rgb), 3)
                if now - last_stats >= 0.25:
                    self.stats = depth_stats(depth)
                    last_stats = now
                if self._leased(now):
                    self.mode = self.lease["mode"]
                elif self.video == "auto":
                    self.mode = self.switch.step(now, mode, self.light, busy=self._busy(now),
                                                 hold=bool(self.settings.get("webcam")))
                self._sync_webcam(rgb)            # in infrared mode: a night-vision webcam
        finally:
            if self.webcam is not None:
                self.webcam.close()
            if cam is not None:
                try:
                    cam.led("off")
                    cam.close()
                except OSError:
                    pass
            self.writer.close()
            self.stop.set()

    # -- everyone in front of the Kinect (people.py): the page's overlay, "Mario, how tall am I?"

    def people_watch(self, seconds=PEOPLE_LINGER):
        """Keep the people tracker running for `seconds` more; it starts on the first call."""
        now = time.monotonic()
        self.last_use = now
        self.people_until = max(self.people_until, now + seconds)
        with self.lock:
            if self.people_thread is None or not self.people_thread.is_alive():
                self.people_thread = threading.Thread(target=self._people_loop, name="people",
                                                      daemon=True)
                self.people_thread.start()

    def _publish(self, state):
        self.people_state = state
        self.people_seq += 1

    def _people_loop(self):
        import measure
        import people
        try:
            source = PoseSource()
        except Exception as err:                    # noqa: BLE001 (MediaPipe missing or broken)
            self._publish({"count": 0, "standing": 0, "people": [], "running": False,
                           "error": f"Pose model would not load: {err}"})
            return
        log(f"people tracker on ({source.kind} pose)")
        tracker = people.People()
        last, epoch = 0, None
        try:
            while not self.stop.is_set() and time.monotonic() < self.people_until:
                snap = self.snapshot()
                if snap is None or snap.seq == last:
                    time.sleep(0.004)
                    continue
                last = snap.seq                      # always the newest frame: no backlog
                if snap.epoch != epoch:
                    if epoch is not None:
                        tracker.new_geometry()        # another camera: the floor is refitted
                    epoch = snap.epoch
                t0 = time.perf_counter()
                poses = source.detect(snap.rgb, snap.depth, snap.mode)
                t1 = time.perf_counter()
                state = tracker.step(poses, snap.depth, measure.up_vector(snap.accel),
                                     float(self.settings.get("mount_height", 1.92)),
                                     snap.intrinsics, snap.mono)
                source.verdict(tracker.accepted, snap.depth)
                # Everything about the frame these skeletons came from (one snapshot), and when
                # they were ready: the latency budget.
                state.update(running=True, source=source.kind, **snap.meta(),
                             ready=round(time.time(), 4),
                             timing={**source.timing, "pose_ms": round(1000 * (t1 - t0), 1),
                                     "people_ms": round(1000 * (time.perf_counter() - t1), 1),
                                     "find_ms": source.finder.ms if source.finder else None})
                self._publish(state)
        except Exception as err:                    # noqa: BLE001
            log(f"people tracker stopped: {err}")
            self._publish({**self.people_state, "running": False, "error": str(err)})
        finally:
            source.close()
            if self.people_state.get("running"):
                self._publish({**self.people_state, "running": False})
            log("people tracker off")

    def measure_people(self, seconds=6.0):
        """Watch for up to `seconds`: done early once everyone in view has been measured
        (standing straight and still for a second). The answer for Mario and the Studio."""
        import people
        for _ in range(50):                         # the hub may have only just started
            if self.latest()[0] is not None:
                break
            time.sleep(0.1)
        if self.latest()[0] is None:
            return {"ok": False, "count": 0, "people": [],
                    "error": self.error or "The Kinect isn't streaming."}
        start = time.monotonic()
        seq0 = self.people_seq
        while True:
            self.people_watch(PEOPLE_LINGER)
            time.sleep(0.1)
            now = time.monotonic()
            state = self.people_state
            if self.people_seq == seq0 and now - start < 8:
                continue                            # the pose model is still loading
            crowd = state.get("people") or []
            if state.get("error") and not state.get("running"):
                break
            if crowd and all(p["height_cm"] is not None for p in crowd) and now - start > 1.2:
                break
            if not crowd and now - start > 3.0:     # nobody there
                break
            if now - start > seconds:
                break
        crowd = state.get("people") or []
        out = {"ok": any(p["height_cm"] is not None for p in crowd), "count": len(crowd),
               "standing": state.get("standing", 0), "floor": state.get("floor"),
               "people": [{k: p[k] for k in ("id", "posture", "label", "straight", "hint",
                                             "height_cm", "distance")} for p in crowd],
               "sentence": people.say(state), "count_sentence": people.count(state)}
        if state.get("error"):
            out["error"] = state["error"]
        elif not crowd:
            out["error"] = out["sentence"]
        if crowd:                                   # the one nearest the middle, for "how far am I"
            main = min(crowd, key=lambda p: abs(p["x"] - 0.5))
            out["distance"] = main["distance"]
            if main["height_cm"] is not None:
                out["height"] = main["height_cm"] / 100
                out["feet"], out["inches"] = people.feet_inches(main["height_cm"])
        return out

    # -- what the page reads

    def latest(self):
        with self.lock:
            return self.rgb, self.depth, self.seq

    def snapshot(self):
        """The newest frame as one frames.Snapshot (picture, depth, mode, lens, times), or None."""
        with self.lock:
            return self.snap

    def jpeg(self, kind):
        import cv2
        snap = self.snapshot()
        if snap is None:
            return None, 0
        cached = self._jpeg.get(kind)
        if cached and cached[0] == snap.seq:
            return cached[1], snap.seq
        img = cv2.cvtColor(snap.rgb, cv2.COLOR_RGB2BGR) if kind == "video" else colour_depth(snap.depth)
        ok, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        data = data.tobytes() if ok else None
        self._jpeg[kind] = (snap.seq, data)
        return data, snap.seq

    def cloud(self, step):
        snap = self.snapshot()
        if snap is None:
            return None
        cached = self._cloud.get(step)
        if cached and cached[0] == snap.seq:
            return cached[1]
        data = cloud_bytes(*point_cloud(snap.rgb, snap.depth, step, mode=snap.mode), snap.seq)
        self._cloud = {step: (snap.seq, data)}
        return data

    def info(self):
        pitch, roll = angles(self.motor["accel"])
        seen = self.writer.client_seen() if self.writer else 0.0
        g = math.sqrt(sum(float(v) ** 2 for v in self.motor["accel"])) / kinect.COUNTS_PER_G
        return {
            "status": self.status, "error": self.error, "kinect": kinect.probe(),
            # The picture frames are in now (the snapshot's), and the one asked for next.
            "mode": self.snap.mode if self.snap is not None else self.mode, "next_mode": self.mode,
            "video": self.video,
            "auto": self.switch.reason if self.video == "auto" else None,
            "fps": round(self.fps, 1), "seq": self.seq,
            "accel": self.motor["accel"], "g": round(g, 3), "pitch": pitch, "roll": roll,
            "tilt": self.motor["tilt"], "tilt_status": self.motor["status"], "led": self.led,
            "depth": self.stats, "light": self.light,
            "webcam": {"on": bool(self.settings.get("webcam")), "device": find_webcam(),
                       "streaming": self.webcam is not None, "error": self.webcam_error},
            "air": time.monotonic() - seen < 3.0 if seen else False,
            "studio": self.studio_clients,
            "epoch": self.epoch, "unpaired": self.unpaired,
            "activity": time.monotonic() < self.activity_until,
            "lease": None if not self._leased() else
            {"owner": self.lease["owner"], "mode": self.lease["mode"],
             "left": round(self.lease["until"] - time.monotonic(), 1)},
            "intrinsics": list(self.snap.intrinsics if self.snap is not None else kinect.intrinsics(self.mode)),
        }


# ------------------------------------------------------------------ HTTP

def make_app(hub):
    from aiohttp import web

    loop_box = {}

    async def in_thread(fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    @web.middleware
    async def note_use(request, handler):
        hub.last_use = time.monotonic()
        response = await handler(request)
        if request.path.startswith(("/frame", "/cloud", "/api")):
            response.headers["Cache-Control"] = "no-store"
        elif request.path == "/" or request.path.startswith("/studio/"):
            response.headers["Cache-Control"] = "no-cache"      # a new Studio shows at once
        return response

    async def index(_request):
        return web.FileResponse(STUDIO / "index.html")

    async def frame(request):
        kind = request.match_info["kind"]
        if kind not in ("video", "depth"):
            raise web.HTTPNotFound()
        after = int(request.query.get("after", "0") or 0)
        for _ in range(100):                       # wait up to ~1 s for a newer frame
            _, _, seq = hub.latest()
            if seq and seq != after:
                break
            await asyncio.sleep(0.01)
        data, seq = await in_thread(hub.jpeg, kind)
        if data is None:
            return web.Response(status=204)
        return web.Response(body=data, content_type="image/jpeg", headers={"X-Seq": str(seq)})

    async def cloud(request):
        step = min(16, max(2, int(request.query.get("step", "4") or 4)))
        after = int(request.query.get("after", "0") or 0)
        for _ in range(100):
            _, _, seq = hub.latest()
            if seq and seq != after:
                break
            await asyncio.sleep(0.01)
        data = await in_thread(hub.cloud, step)
        if data is None:
            return web.Response(status=204)
        return web.Response(body=data, content_type="application/octet-stream")

    async def ply(_request):
        snap = hub.snapshot()
        if snap is None:
            raise web.HTTPServiceUnavailable(text="no Kinect frame yet")
        data = await in_thread(lambda: ply_bytes(*point_cloud(snap.rgb, snap.depth, 2, mode=snap.mode)))
        name = time.strftime("kinect-%Y%m%d-%H%M%S.ply")
        return web.Response(body=data, content_type="application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def scale(_request):
        # The depth colours, near (left) to far (right): the same map the depth view uses.
        import cv2
        import numpy as np
        ramp = np.tile(np.linspace(400, 4000, 256).astype(np.uint16), (2, 1))
        ok, data = cv2.imencode(".png", colour_depth(ramp))
        return web.Response(body=data.tobytes(), content_type="image/png")

    async def status(_request):
        return web.json_response(hub.info())

    async def measure(request):
        # ?seconds=N: how long to wait for everyone to stand straight (2 for a quick count).
        try:
            seconds = min(10.0, max(1.0, float(request.query.get("seconds", "6"))))
        except ValueError:
            seconds = 6.0
        return web.json_response(await in_thread(hub.measure_people, seconds))

    async def people(request):
        # Long poll: the state after the one the page has (?after=N), within about a second.
        after = int(request.query.get("after", "0") or 0)
        hub.people_watch()
        for _ in range(100):
            if hub.people_seq != after:
                break
            await asyncio.sleep(0.01)
        return web.json_response({**hub.people_state, "seq": hub.people_seq})

    async def api(request):
        name = request.match_info["name"]
        if name not in ("led", "tilt", "video", "webcam", "busy", "activity", "lease"):
            raise web.HTTPNotFound()
        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text="JSON body expected")
        hub.command(name, body.get("value"))
        return web.json_response({"ok": True})

    async def presence(request):
        # The page holds this open while it is showing; the hub stays up for as long.
        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)
        hub.studio_clients += 1
        try:
            async for _msg in ws:
                hub.last_use = time.monotonic()
        finally:
            hub.studio_clients -= 1
        return ws

    app = web.Application(middlewares=[note_use])
    app.router.add_get("/", index)
    app.router.add_static("/studio/", STUDIO)
    app.router.add_get("/frame/{kind}.jpg", frame)
    app.router.add_get("/cloud.bin", cloud)
    app.router.add_get("/cloud.ply", ply)
    app.router.add_get("/depth-scale.png", scale)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/measure", measure)
    app.router.add_get("/api/people", people)
    app.router.add_post("/api/{name}", api)
    app.router.add_get("/presence", presence)
    loop_box["app"] = app
    return app


async def serve(hub, port):
    from aiohttp import web
    runner = web.AppRunner(make_app(hub), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    log(f"Kinect Studio on http://127.0.0.1:{port}")
    while not hub.stop.is_set():
        await asyncio.sleep(0.25)
    await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    hub = Hub(load_settings())
    worker = threading.Thread(target=hub.run, name="capture", daemon=True)
    worker.start()
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: hub.stop.set())
    try:
        asyncio.run(serve(hub, args.port))
    finally:
        hub.stop.set()
        worker.join(timeout=3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
