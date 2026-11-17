#!/usr/bin/env python3
"""The Kinect hub: the one process that opens the Kinect, and everything that wants it.

libfreenect lets one process at a time open the Kinect, so this one does and shares it:

    frames.py   every frame (colour or infrared + depth registered to it) in shared memory,
                for Air's gestures
    webcam      the colour picture as a camera any app can pick ("Kinect Camera", a
                v4l2loopback device: scripts/install-virtual-cameras.sh makes it)
    studio      Kinect Studio at http://127.0.0.1:8792: the picture, depth, the point cloud,
                the accelerometer, tilt motor and LED, stream rates, a PLY export

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
IDLE_EXIT = 20.0
REPROBE = 3.0
WEBCAM_NAME = "Kinect Camera"
VIDEO = ("auto", "rgb", "ir")
BUSY_STALE = 3.0       # s: Air saying it is engaged counts only while Air still reads frames


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


# ------------------------------------------------------------------ the hub

class Hub:
    def __init__(self, settings):
        self.settings = settings
        self.video = settings.get("video") if settings.get("video") in VIDEO else "auto"
        self.mode = "ir" if self.video == "ir" else "rgb"
        self.switch = fusion.LightSwitch(float(settings.get("dark_below", 0.04)),
                                         float(settings.get("light_above", 0.07)))
        self.busy = False      # Air is engaged: no colour checks from infrared while it is
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.rgb = self.depth = None
        self.seq = 0
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
                    if value != "auto":
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
        seen = self.writer.client_seen() if self.writer else 0.0
        return self.busy and now - seen < BUSY_STALE

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
                try:
                    rgb, depth = cam.read(self.mode)
                except OSError as err:
                    log(f"Kinect lost: {err}")
                    self.status, self.error = "error", str(err)
                    try:
                        cam.close()
                    except OSError:
                        pass
                    cam = None
                    continue
                if now - last_state >= 0.2:
                    try:
                        self.motor = cam.state()
                    except OSError:
                        pass
                    last_state = now
                frames_n += 1
                if now - fps_t >= 1.0:
                    self.fps, frames_n, fps_t = frames_n / (now - fps_t), 0, now
                self.writer.write(rgb, depth, self.mode, self.motor["accel"],
                                  self.motor["tilt"], self.fps)
                with self.lock:
                    self.rgb, self.depth, self.seq = rgb, depth, self.writer.seq
                if self.mode == "rgb":
                    self.light = round(fusion.light_level(rgb), 3)
                if now - last_stats >= 0.25:
                    self.stats = depth_stats(depth)
                    last_stats = now
                if self.video == "auto":
                    self.mode = self.switch.step(now, self.mode, self.light, busy=self._busy(now),
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

    # -- measuring someone (measure.py): "Mario, how tall am I?"

    def measure_height(self, seconds=1.2):
        import mediapipe as mp

        import measure
        for _ in range(50):                         # the hub may have only just started
            if self.latest()[0] is not None:
                break
            time.sleep(0.1)
        if self.latest()[0] is None:
            return {"ok": False, "error": self.error or "The Kinect isn't streaming."}
        self.last_use = time.monotonic()
        mount = float(self.settings.get("mount_height", 1.92))
        intr = kinect.intrinsics(self.mode)
        results, last = [], 0
        with mp.solutions.pose.Pose(model_complexity=0, static_image_mode=False) as pose:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                rgb, depth, seq = self.latest()
                if seq == last:
                    time.sleep(0.01)
                    continue
                last = seq
                found = pose.process(rgb).pose_landmarks
                torso = [found.landmark[i] for i in (11, 12, 23, 24)] if found else []
                torso = [p for p in torso if p.visibility > 0.4]
                if len(torso) < 2:
                    results.append({"ok": False, "error": "I can't see anyone in front of the Kinect."})
                    continue
                seed = (sum(p.x for p in torso) / len(torso) * frames.W,
                        sum(p.y for p in torso) / len(torso) * frames.H)
                results.append(measure.measure(depth, self.motor["accel"], seed, mount, intr=intr))
        summary = measure.summarise(results)
        summary["sentence"] = measure.say(summary)
        return summary

    # -- what the page reads

    def latest(self):
        with self.lock:
            return self.rgb, self.depth, self.seq

    def jpeg(self, kind):
        import cv2
        rgb, depth, seq = self.latest()
        if rgb is None:
            return None, 0
        cached = self._jpeg.get(kind)
        if cached and cached[0] == seq:
            return cached[1], seq
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) if kind == "video" else colour_depth(depth)
        ok, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        data = data.tobytes() if ok else None
        self._jpeg[kind] = (seq, data)
        return data, seq

    def cloud(self, step):
        rgb, depth, seq = self.latest()
        if rgb is None:
            return None
        cached = self._cloud.get(step)
        if cached and cached[0] == seq:
            return cached[1]
        data = cloud_bytes(*point_cloud(rgb, depth, step, mode=self.mode), seq)
        self._cloud = {step: (seq, data)}
        return data

    def info(self):
        pitch, roll = angles(self.motor["accel"])
        seen = self.writer.client_seen() if self.writer else 0.0
        g = math.sqrt(sum(float(v) ** 2 for v in self.motor["accel"])) / kinect.COUNTS_PER_G
        return {
            "status": self.status, "error": self.error, "kinect": kinect.probe(),
            "mode": self.mode, "video": self.video,
            "auto": self.switch.reason if self.video == "auto" else None,
            "fps": round(self.fps, 1), "seq": self.seq,
            "accel": self.motor["accel"], "g": round(g, 3), "pitch": pitch, "roll": roll,
            "tilt": self.motor["tilt"], "tilt_status": self.motor["status"], "led": self.led,
            "depth": self.stats, "light": self.light,
            "webcam": {"on": bool(self.settings.get("webcam")), "device": find_webcam(),
                       "streaming": self.webcam is not None, "error": self.webcam_error},
            "air": time.monotonic() - seen < 3.0 if seen else False,
            "studio": self.studio_clients,
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
        rgb, depth, _ = hub.latest()
        if rgb is None:
            raise web.HTTPServiceUnavailable(text="no Kinect frame yet")
        mode = hub.mode
        data = await in_thread(lambda: ply_bytes(*point_cloud(rgb, depth, 2, mode=mode)))
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

    async def measure_height(_request):
        return web.json_response(await in_thread(hub.measure_height))

    async def api(request):
        name = request.match_info["name"]
        if name not in ("led", "tilt", "video", "webcam", "busy"):
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
    app.router.add_get("/api/measure", measure_height)
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
