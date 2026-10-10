"""Adaptive Link - the phone's camera as a webcam on the laptop.

The phone sends JPEG frames; they are decoded and written to a v4l2loopback
device, which every app that uses a webcam (browsers, Zoom, Meet, OBS) lists
like any other camera.

The loopback device is a kernel module, and loading one needs root, so it is
set up once by scripts/install-link-camera.sh. Until then find_device()
returns None and the phone is told the virtual camera is not installed.
"""

from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

Gst.init(None)

CARD_LABEL = "Phone Camera"
WIDTH, HEIGHT, RATE = 1280, 720, 30


def find_device(sys_root="/sys/devices/virtual/video4linux"):
    """/dev/videoN of the loopback device, or None if there is none."""
    try:
        entries = sorted(Path(sys_root).iterdir())
    except OSError:
        return None
    fallback = None
    for entry in entries:
        try:
            name = (entry / "name").read_text().strip()
        except OSError:
            continue
        device = f"/dev/{entry.name}"
        if name == CARD_LABEL:
            return device
        if "Dummy video device" in name:
            fallback = fallback or device
    return fallback


def pipeline_description(device):
    return (
        "appsrc name=src is-live=true do-timestamp=true format=time "
        "caps=image/jpeg "
        "! jpegdec ! videoconvert ! videoscale ! videorate "
        f"! video/x-raw,format=YUY2,width={WIDTH},height={HEIGHT},framerate={RATE}/1 "
        f"! v4l2sink device={device} sync=false"
    )


class Webcam:
    def __init__(self, device):
        self.device = device
        self._pipeline = None
        self._src = None

    def start(self):
        self._pipeline = Gst.parse_launch(pipeline_description(self.device))
        self._src = self._pipeline.get_by_name("src")
        self._pipeline.set_state(Gst.State.PLAYING)

    def push(self, jpeg):
        """One frame from the phone. False if the pipeline has gone."""
        if self._src is None or not jpeg.startswith(b"\xff\xd8"):
            return False
        return self._src.emit("push-buffer", Gst.Buffer.new_wrapped(jpeg)) == Gst.FlowReturn.OK

    def stop(self):
        if self._pipeline is not None:
            if self._src is not None:
                self._src.emit("end-of-stream")
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._src = None
