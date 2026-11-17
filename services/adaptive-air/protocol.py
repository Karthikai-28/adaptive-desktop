"""What Air sends the shell: one D-Bus signal per camera frame.

    bus name   org.adaptive.Air           (owned by services/adaptive-air/air.py)
    object     /org/adaptive/Air
    signal     org.adaptive.Air.Frame(s json)

The JSON is the gesture engine's state (gestures.Engine.step) plus where it came from:

    source   "kinect" | "webcam" | "none"
    video    "rgb" | "ir": which picture the Kinect gives (infrared in the dark); each hand also
             says where it was found: "rgb", "ir" or "depth" (depth alone)
    fps      frames per second actually processed
    status   "starting" | "tracking" | "no-camera" | "kinect-unpowered" | "stopping"
    note     a sentence for the HUD when something needs the user (plug in the 12 V supply ...)

Methods on the same object: Status() -> s json (the last frame's source/status/note/fps,
whether a Kinect is on USB), Stop(). The shell's side is shell/adaptive-shell@local/air.js.
"""

import json

NAME = "org.adaptive.Air"
PATH = "/org/adaptive/Air"
INTERFACE = "org.adaptive.Air"

XML = f"""
<node>
  <interface name="{INTERFACE}">
    <signal name="Frame"><arg type="s" name="json"/></signal>
    <method name="Status"><arg type="s" name="json" direction="out"/></method>
    <method name="Stop"/>
  </interface>
</node>
"""


def frame(state, source, fps, status, note=None, video=None):
    msg = dict(state)
    msg.pop("t", None)
    msg["source"] = source
    if video:
        msg["video"] = video
    msg["fps"] = round(fps, 1)
    msg["status"] = status
    if note:
        msg["note"] = note
    return json.dumps(msg, separators=(",", ":"))


def idle(source, status, note=None):
    """A frame with no hands, for when there is no camera picture to read."""
    return frame({"engaged": False, "engage": 0.0, "cursor": {"x": 0.5, "y": 0.5},
                  "pressed": False, "grab": None, "hands": [], "events": []},
                 source, 0.0, status, note)
