#!/usr/bin/env python3
"""Open Adaptive Home once when the paired LG TV comes online.

Retail webOS does not let a Developer Mode app replace LG Home or register a
persistent boot callback. This small desktop-side companion uses the Cast
pairing that already exists, notices an off -> on edge, and launches the TV
app once. It never fights the user after the launch: another attempt is armed
only after the TV has been unreachable for several consecutive checks.
"""

import sys
from pathlib import Path


APP_ID = "com.karthi.adaptivetv"
CHECK_SECONDS = 3
OFF_SAMPLES = 3
RETRY_SECONDS = 15


class WakeState:
    """Debounce reachability and report only a newly-online edge."""

    def __init__(self, off_samples=OFF_SAMPLES):
        self.off_samples_needed = off_samples
        self.off_samples = off_samples
        self.armed = True

    def update(self, online):
        if online:
            self.off_samples = 0
            if self.armed:
                self.armed = False
                return True
            return False
        self.off_samples += 1
        if self.off_samples >= self.off_samples_needed:
            self.armed = True
        return False


def run():
    cast_dir = Path(__file__).resolve().parents[1] / "adaptive-cast"
    sys.path.insert(0, str(cast_dir))

    from gi.repository import GLib
    import prefs as saved
    import tv as tvcontrol

    prefs = saved.load()
    control = tvcontrol.TvControl(prefs, lambda text: print(text, flush=True))
    state = WakeState()
    status = {"connecting": False, "retry": 0, "timeout": 0,
              "polling": False, "poll_timeout": 0}

    def retry():
        status["retry"] = 0
        status["connecting"] = False
        # Re-arm only this failed attempt. WakeState will still prevent a
        # successful launch from repeating during the same power-on cycle.
        state.armed = True
        return GLib.SOURCE_REMOVE

    def launch():
        if status["connecting"]:
            return
        status["connecting"] = True

        def ready(link):
            link.call("ssap://system.launcher/launch", {"id": APP_ID}, finished)

        def finished(reply):
            if not status["connecting"]:
                return
            status["connecting"] = False
            if status["timeout"]:
                GLib.source_remove(status["timeout"])
                status["timeout"] = 0
            if reply is None and not status["retry"]:
                status["retry"] = GLib.timeout_add_seconds(RETRY_SECONDS, retry)

        def failed(text):
            print("adaptive-tv-home: " + text, flush=True)
            finished(None)

        def timed_out():
            status["timeout"] = 0
            finished(None)
            return GLib.SOURCE_REMOVE

        status["timeout"] = GLib.timeout_add_seconds(10, timed_out)
        control.connect(ready, failed)

    def finish_poll(payload):
        if not status["polling"]:
            return
        status["polling"] = False
        if status["poll_timeout"]:
            GLib.source_remove(status["poll_timeout"])
            status["poll_timeout"] = 0
        # Quick Start can leave the socket reachable during standby. Read the
        # actual power state so that only a lit, usable TV counts as online.
        active = bool(payload) and payload.get("state") == "Active"
        if state.update(active):
            launch()

    def check():
        if status["polling"]:
            return GLib.SOURCE_CONTINUE
        status["polling"] = True

        def ready(link):
            def timed_out():
                status["poll_timeout"] = 0
                finish_poll(None)
                return GLib.SOURCE_REMOVE

            status["poll_timeout"] = GLib.timeout_add_seconds(8, timed_out)
            link.call("ssap://com.webos.service.tvpower/power/getPowerState", None,
                      finish_poll)

        control.connect(ready, lambda _text: finish_poll(None))
        return GLib.SOURCE_CONTINUE

    check()
    GLib.timeout_add_seconds(CHECK_SECONDS, check)
    GLib.MainLoop().run()


if __name__ == "__main__":
    run()
