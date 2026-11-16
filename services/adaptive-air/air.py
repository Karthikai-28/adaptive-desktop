#!/usr/bin/env python3
"""Air: control the desktop with your hands, through the Kinect (or the webcam until it has power).

    air.py               run: own org.adaptive.Air on the session bus, send the shell a frame per
                         camera frame (the user service adaptive-air.service runs this)
    air.py --print       no D-Bus: print gesture events as they happen (try gestures in a terminal)
    air.py --preview     also show a window with the camera picture and the hand skeleton
    air.py --demo        no camera: play a scripted pair of hands (demo.py) through the engine,
                         to see the HUD and every gesture; --loop repeats it
    air.py --probe       say what of the Kinect is on USB and which source would be used; exit
    air.py --source kinect|webcam|auto   override the settings file

Settings: ~/.config/adaptive-desktop/air.json (all optional)
    {"source": "auto", "webcam": 0, "tilt": null, "tracking": "auto",
     "gestures": {...gestures.DEFAULTS...}}
    tracking: auto (whole picture, then you and your wrists when it finds nothing: across the
    room), near (the desk), room (always through your body first)

Privacy: camera pictures stay in this process's memory and are dropped after each frame. Nothing
is written to disk and nothing but hand landmarks (21 points per hand) leaves the process. The
shell shows the Air indicator whenever frames arrive. docs/AIR.md.
"""

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gestures  # noqa: E402
import kinect  # noqa: E402
import protocol  # noqa: E402

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "adaptive-desktop/air.json"
REPROBE_SECONDS = 3.0
IDLE_EVERY = 3            # with no hands in view, read only every third frame
IDLE_AFTER = 2.0          # seconds without hands before slowing down
HEARTBEAT = 1.0           # seconds between frames sent while nothing is happening


def log(msg):
    print(f"[air] {msg}", flush=True)


def load_settings():
    try:
        data = json.loads(CONFIG.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ sources

HUB = "http://127.0.0.1:8792"


def hub_post(name, value):
    """Ask the Kinect hub for something (LED, tilt); quietly nothing when it is not there."""
    import urllib.request
    req = urllib.request.Request(f"{HUB}/api/{name}", data=json.dumps({"value": value}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=0.5).read()
    except OSError:
        pass


def ensure_hub():
    """Start the Kinect hub (adaptive-kinect.service, or the script itself) if it is not running."""
    import subprocess
    import urllib.request
    try:
        urllib.request.urlopen(f"{HUB}/api/status", timeout=0.5).read()
        return
    except OSError:
        pass
    if subprocess.run(["systemctl", "--user", "start", "adaptive-kinect.service"],
                      capture_output=True).returncode != 0:
        subprocess.Popen([sys.executable, str(HERE / "kinect_hub.py")], start_new_session=True)


class KinectSource:
    """The Kinect, through the hub (kinect_hub.py), which shares it with Studio and the webcam."""
    name = "kinect"
    has_depth = True

    def __init__(self, tilt=None):
        import frames
        ensure_hub()
        deadline = time.monotonic() + 10
        while True:
            try:
                self.reader = frames.Reader()
                self.reader.read(timeout=2.0)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise OSError("the Kinect hub gave no frames")
                time.sleep(0.3)
        if tilt is not None:
            hub_post("tilt", tilt)

    def read(self):
        rgb, depth, _ = self.reader.read(timeout=2.0)
        return rgb, depth

    def led(self, colour):
        hub_post("led", colour)

    def close(self):
        self.led("blink-green")
        self.reader.close()


class WebcamSource:
    name = "webcam"
    has_depth = False

    def __init__(self, device=0):
        import cv2
        self._cv2 = cv2
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, _ = self.cap.read()
        if not ok:
            self.cap.release()
            raise OSError(f"webcam {device} gave no picture")

    def read(self):
        ok, bgr = self.cap.read()
        if not ok:
            raise OSError("webcam stopped")
        return self._cv2.cvtColor(bgr, self._cv2.COLOR_BGR2RGB), None

    def led(self, colour):
        pass

    def close(self):
        self.cap.release()


def kinect_led(colour):
    """The Kinect's LED, through the motor, when no Kinect picture is open."""
    try:
        m = kinect.Motor()
        m.led(colour)
        m.close()
    except OSError:
        pass


def open_source(choice, settings):
    """(source or None, status, note)."""
    usb = kinect.probe()
    if choice in ("auto", "kinect") and usb["camera"] and kinect.available():
        try:
            return KinectSource(settings.get("tilt")), "tracking", None
        except OSError as err:
            note = f"Kinect camera did not start: {err}"
    elif choice in ("auto", "kinect") and usb["present"] and not usb["camera"]:
        note = "Kinect has no power: plug in its 12 V supply."
    elif choice in ("auto", "kinect") and usb["camera"]:
        note = "libfreenect is not built: run scripts/install-air.sh"
    else:
        note = None if choice == "webcam" else "No Kinect on USB."
    if choice == "kinect":
        return None, "kinect-unpowered" if usb["present"] else "no-camera", note
    try:
        source = WebcamSource(int(settings.get("webcam", 0)))
        return source, "tracking", (note + " Using the webcam." if note else None)
    except (OSError, ValueError) as err:
        return None, "no-camera", f"{note + ' ' if note else ''}{err}"


# ------------------------------------------------------------------ tracking

class Tracker:
    """Hands in the (mirrored) colour picture, plus each palm's depth when there is one.

    Near the Kinect (the desk) MediaPipe Hands finds hands in the whole picture. Across the room
    (the Kinect on the TV, you 2 to 4 m away) a hand is only ~25 pixels wide and Hands misses it,
    so MediaPipe Pose finds you first, and Hands looks again in a square cut around each wrist,
    sized from your shoulders and enlarged to CROP pixels. "tracking" in air.json: auto (whole
    picture first, the crops when it finds nothing), near, or room.
    """

    CROP = 256
    RECHECK = 15          # in room mode, try the whole picture again every this many frames

    def __init__(self, mode="auto"):
        import cv2
        import mediapipe as mp
        import numpy as np
        self.cv2, self.np, self.mp = cv2, np, mp
        self.mode = mode if mode in ("auto", "near", "room") else "auto"
        self.hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2,
                                              model_complexity=0, min_detection_confidence=0.6,
                                              min_tracking_confidence=0.5)
        self.crop_hands = None
        self.pose = None
        self.room = self.mode == "room"
        self.n = 0
        self.person = None        # the last pose: {"shoulders": px, "depth": mm} for the HUD

    def __call__(self, rgb, depth):
        cv2 = self.cv2
        rgb = cv2.flip(rgb, 1)                    # mirror: your right hand moves right
        if depth is not None:
            depth = cv2.flip(depth, 1)
        self.n += 1
        out = []
        if self.mode != "room" and (not self.room or self.n % self.RECHECK == 0):
            out = self._whole(rgb, depth)
            if out:
                self.room = False
        if not out and self.mode != "near":
            out = self._crops(rgb, depth)
            self.room = bool(out) or self.room
        return out, rgb

    def _palm_depth(self, lm, depth, w, h):
        if depth is None:
            return None
        cx, cy = gestures.palm_centre(lm)
        px, py = int(cx * w), int(cy * h)
        patch = depth[max(0, py - 6):py + 7, max(0, px - 6):px + 7]
        valid = patch[(patch > 300) & (patch < 4500)]
        return int(self.np.median(valid)) if valid.size else None

    def _whole(self, rgb, depth):
        result = self.hands.process(rgb)
        out = []
        if not result.multi_hand_landmarks:
            return out
        h, w = rgb.shape[:2]
        for marks, handed in zip(result.multi_hand_landmarks, result.multi_handedness or []):
            lm = [[p.x, p.y, p.z] for p in marks.landmark]
            out.append({"side": handed.classification[0].label, "lm": lm,
                        "depth": self._palm_depth(lm, depth, w, h)})
        return out

    def _crops(self, rgb, depth):
        mp, cv2 = self.mp, self.cv2
        if self.pose is None:
            self.pose = mp.solutions.pose.Pose(model_complexity=0, static_image_mode=False,
                                               min_detection_confidence=0.5)
            self.crop_hands = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=1,
                                                       model_complexity=0,
                                                       min_detection_confidence=0.5)
        result = self.pose.process(rgb)
        if not result.pose_landmarks:
            self.person = None
            return []
        h, w = rgb.shape[:2]
        P = result.pose_landmarks.landmark
        L = mp.solutions.pose.PoseLandmark
        shoulders = abs(P[L.LEFT_SHOULDER].x - P[L.RIGHT_SHOULDER].x) * w
        self.person = {"shoulders": round(shoulders)}
        side_px = int(max(64, 1.15 * shoulders))
        out = []
        for side, wrist, index in (("Left", L.LEFT_WRIST, L.LEFT_INDEX),
                                   ("Right", L.RIGHT_WRIST, L.RIGHT_INDEX)):
            if P[wrist].visibility < 0.5:
                continue
            # Centre the square a little past the wrist, toward the fingers.
            cx = (P[wrist].x + 0.6 * (P[index].x - P[wrist].x)) * w
            cy = (P[wrist].y + 0.6 * (P[index].y - P[wrist].y)) * h
            x0, y0 = int(cx - side_px / 2), int(cy - side_px / 2)
            box = rgb[max(0, y0):max(0, y0 + side_px), max(0, x0):max(0, x0 + side_px)]
            if box.shape[0] < 16 or box.shape[1] < 16:
                continue
            # Pad to a square when the cut runs off the picture, so the scale stays right.
            pad = self.np.zeros((side_px, side_px, 3), self.np.uint8)
            oy, ox = max(0, -y0), max(0, -x0)
            pad[oy:oy + box.shape[0], ox:ox + box.shape[1]] = box
            big = cv2.resize(pad, (self.CROP, self.CROP), interpolation=cv2.INTER_LINEAR)
            found = self.crop_hands.process(big)
            if not found.multi_hand_landmarks:
                continue
            lm = [[(x0 + p.x * side_px) / w, (y0 + p.y * side_px) / h, p.z]
                  for p in found.multi_hand_landmarks[0].landmark]
            out.append({"side": side, "lm": lm, "depth": self._palm_depth(lm, depth, w, h)})
        return out


def draw_preview(cv2, rgb, hands, state):
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    bones = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
             (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17),
             (17, 18), (18, 19), (19, 20)]
    for hand in hands:
        pts = [(int(p[0] * w), int(p[1] * h)) for p in hand["lm"]]
        for a, b in bones:
            cv2.line(img, pts[a], pts[b], (255, 200, 80), 2)
        label = f"{hand['side']} {hand.get('depth') or ''}"
        cv2.putText(img, label, pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    text = ("ENGAGED " if state["engaged"] else "") + " ".join(e["type"] for e in state["events"])
    cv2.putText(img, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 220, 120), 2)
    cv2.imshow("Air preview", img)
    cv2.waitKey(1)


# ------------------------------------------------------------------ the loop

class Air:
    def __init__(self, args, settings, emit):
        self.args, self.settings, self.emit = args, settings, emit
        self.stop = threading.Event()
        self.status = {"source": "none", "status": "starting", "note": None, "fps": 0.0}

    def send(self, payload):
        self.emit(payload)

    def work(self):
        """The thread's job: the camera loop, or the demo."""
        if self.args.demo:
            import demo
            self.status.update(source="demo", status="tracking", fps=float(demo.FPS))
            demo.run(lambda state: self.send(protocol.frame(state, "demo", demo.FPS, "tracking")),
                     self.stop, loop=self.args.loop)
            self.send(protocol.idle("none", "stopping"))
        else:
            self.run()

    def run(self):
        choice = self.args.source or self.settings.get("source", "auto")
        engine = gestures.Engine(self.settings.get("gestures"))
        tracker = None
        source, last_probe, led = None, 0.0, None
        frames, fps_t, fps = 0, time.monotonic(), 0.0
        last_hands, last_sent, n = time.monotonic(), 0.0, 0
        while not self.stop.is_set():
            now = time.monotonic()
            # (Re)open a source: at start, when it fails, and to move to the Kinect once powered
            want_upgrade = source is not None and source.name == "webcam" and choice == "auto"
            if (source is None or want_upgrade) and now - last_probe >= REPROBE_SECONDS:
                last_probe = now
                if source is None or kinect.probe()["camera"]:
                    if source is not None:
                        source.close()
                    source, status, note = open_source(choice, self.settings)
                    self.status.update(source=source.name if source else "none", status=status,
                                       note=note)
                    log(f"source: {self.status['source']} ({status}){' - ' + note if note else ''}")
                    if source is None:
                        kinect_led("blink-red-yellow")
                    led = None
            if source is None:
                self.send(protocol.idle("none", self.status["status"], self.status["note"]))
                self.stop.wait(REPROBE_SECONDS)
                continue
            if tracker is None:
                tracker = Tracker(self.settings.get("tracking", "auto"))

            try:
                rgb, depth = source.read()
            except OSError as err:
                log(f"camera lost: {err}")
                source.close()
                source = None
                continue
            n += 1
            idle = not engine.engaged and now - last_hands > IDLE_AFTER
            if idle and n % IDLE_EVERY:
                continue
            hands, mirrored = tracker(rgb, depth)
            if hands:
                last_hands = now
            state = engine.step(now, hands)
            frames += 1
            if now - fps_t >= 1.0:
                fps, frames, fps_t = frames / (now - fps_t), 0, now
            self.status["fps"] = round(fps, 1)

            want_led = "green" if engine.engaged else "blink-green"
            if want_led != led:
                source.led(want_led)
                if source.name != "kinect":
                    kinect_led(want_led)
                led = want_led

            if self.args.preview:
                draw_preview(tracker.cv2, mirrored, hands, state)
            busy = hands or state["engaged"] or state["events"]
            if busy or now - last_sent >= HEARTBEAT:
                self.send(protocol.frame(state, source.name, fps, self.status["status"],
                                         self.status["note"]))
                last_sent = now
        if source is not None:
            source.close()
        kinect_led("off")
        self.send(protocol.idle("none", "stopping"))


def run_print(args, settings):
    def emit(payload):
        data = json.loads(payload)
        for ev in data["events"]:
            extra = {k: v for k, v in ev.items() if k != "type"}
            print(f"{time.strftime('%H:%M:%S')}  {ev['type']:<12} {json.dumps(extra) if extra else ''}",
                  flush=True)
    air = Air(args, settings, emit)
    signal.signal(signal.SIGINT, lambda *_: air.stop.set())
    signal.signal(signal.SIGTERM, lambda *_: air.stop.set())
    air.work()


def run_dbus(args, settings):
    from gi.repository import Gio, GLib
    loop = GLib.MainLoop()
    node = Gio.DBusNodeInfo.new_for_xml(protocol.XML)
    conn_box = {}
    air = None

    def emit(payload):
        conn = conn_box.get("conn")
        if conn is None:
            return
        GLib.idle_add(lambda: (conn.emit_signal(None, protocol.PATH, protocol.INTERFACE, "Frame",
                                                GLib.Variant("(s)", (payload,))), False)[1])

    def on_call(conn, sender, path, iface, method, params, invocation):
        if method == "Status":
            info = dict(air.status)
            info["kinect"] = kinect.probe()
            invocation.return_value(GLib.Variant("(s)", (json.dumps(info),)))
        elif method == "Stop":
            invocation.return_value(None)
            air.stop.set()

    def on_bus(conn, name):
        conn_box["conn"] = conn
        conn.register_object(protocol.PATH, node.interfaces[0], on_call, None, None)

    def on_lost(conn, name):
        log("another Air already owns org.adaptive.Air; leaving")
        air.stop.set()

    air = Air(args, settings, emit)
    owner = Gio.bus_own_name(Gio.BusType.SESSION, protocol.NAME, Gio.BusNameOwnerFlags.NONE,
                             on_bus, None, on_lost)
    worker = threading.Thread(target=air.work, name="air", daemon=True)

    def stop(*_):
        air.stop.set()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)

    def watch():
        if worker.is_alive():
            return GLib.SOURCE_CONTINUE
        # let the last frame ("stopping") go out, then leave
        GLib.timeout_add(200, loop.quit)
        return GLib.SOURCE_REMOVE

    worker.start()
    GLib.timeout_add(250, watch)
    loop.run()
    Gio.bus_unown_name(owner)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print", action="store_true", help="print gesture events, no D-Bus")
    parser.add_argument("--preview", action="store_true", help="show the camera and hands")
    parser.add_argument("--probe", action="store_true", help="what of the Kinect is on USB")
    parser.add_argument("--demo", action="store_true", help="scripted hands, no camera")
    parser.add_argument("--loop", action="store_true", help="with --demo: repeat it")
    parser.add_argument("--source", choices=("auto", "kinect", "webcam"))
    args = parser.parse_args()
    settings = load_settings()
    if args.probe:
        info = kinect.probe()
        info["libfreenect"] = kinect.available()
        print(json.dumps(info, indent=2))
        return 0
    if args.print:
        run_print(args, settings)
    else:
        run_dbus(args, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
