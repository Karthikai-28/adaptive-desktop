"""Where the laptop's sound goes while casting.

  tv      every app plays into a virtual "TV (Cast)" output; the TV gets its
          monitor and the laptop speakers stay silent
  both    the same, plus a loopback from that output to the speakers (the
          laptop plays a little ahead of the TV: the stream adds delay)
  laptop  nothing changes and the TV gets no sound

The previous default output is written to the restore file before anything
moves, so a crash mid-cast is put right the next time Cast starts.
"""

import subprocess

import desk

SINK = "adaptive_cast"


def _pactl(*args):
    try:
        done = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)
        return done.returncode == 0, done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False, ""


def default_sink():
    ok, out = _pactl("get-default-sink")
    return out if ok else None


def _sink_inputs():
    ok, out = _pactl("list", "short", "sink-inputs")
    return [line.split()[0] for line in out.splitlines() if line.strip()] if ok else []


def _move_all(sink):
    for ident in _sink_inputs():
        _pactl("move-sink-input", ident, sink)


class AudioRoute:
    def __init__(self, mode):
        self.mode = mode
        self.modules = []
        self.previous = None

    @property
    def capture_device(self):
        """The PulseAudio source the stream should record, or None for no sound."""
        if self.mode == "laptop":
            return None
        return f"{SINK}.monitor" if self.modules else None

    def start(self):
        if self.mode == "laptop" or self.modules:
            return
        self.previous = default_sink()
        desk._remember("default-sink", self.previous)
        ok, module = _pactl("load-module", "module-null-sink", f"sink_name={SINK}",
                            "rate=48000", "channels=2",
                            # No spaces: PulseAudio's module arguments refuse them here.
                            "sink_properties=device.description=Cast_to_TV")
        if not ok:
            desk._remember("default-sink", None)
            return
        self.modules.append(module)
        if self.mode == "both" and self.previous:
            ok, loop = _pactl("load-module", "module-loopback", f"source={SINK}.monitor",
                              f"sink={self.previous}", "latency_msec=60")
            if ok:
                self.modules.append(loop)
        _pactl("set-default-sink", SINK)
        _move_all(SINK)

    def stop(self):
        if not self.modules:
            return
        if self.previous:
            _pactl("set-default-sink", self.previous)
            _move_all(self.previous)
        for module in reversed(self.modules):
            _pactl("unload-module", module)
        self.modules = []
        desk._remember("default-sink", None)

    @staticmethod
    def recover():
        """Undo a route left behind by a crash."""
        previous = desk.pending_restore().get("default-sink")
        ok, out = _pactl("list", "short", "modules")
        stale = [line.split()[0] for line in out.splitlines()
                 if f"sink_name={SINK}" in line or f"source={SINK}.monitor" in line] if ok else []
        if previous:
            _pactl("set-default-sink", previous)
            _move_all(previous)
        for module in stale:
            _pactl("unload-module", module)
        desk._remember("default-sink", None)
