"""One cast from start to finish, whoever asked for it.

The window, the command line, the keyboard shortcut and the phone all drive
this one object. It ties together:

  tv.TvControl      wake the TV and open Screen Share first (home network)
  p2p.WifiDirect    the Wi-Fi Direct link
  session.Session   the RTSP session and, through it, the media stream
  audio.AudioRoute  where the laptop's sound goes
  desk.*            quiet notifications, no sleep while casting

and publishes its state to $XDG_RUNTIME_DIR/adaptive-cast.json, which the
shell reads for the Dynamic Island and the Control Center tile.

States: idle, preparing, connecting, negotiating, streaming, reconnecting,
ended, failed.
"""

import json
import os
import time
from pathlib import Path

from gi.repository import GLib

import audio
import desk
import p2p
import prefs as saved
import session as cast_session
import tv as tvcontrol

APP_ID = "com.karthi.AdaptiveCast"
ACTIVE = ("preparing", "connecting", "negotiating", "streaming", "reconnecting")
STATE_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "adaptive-cast.json"
OPEN_TIMEOUT_S = 30
# A TV that has just ended a session drops the next join for a few seconds.
RETRY_AFTER_S = 6
RECONNECT_TRIES = 3

# Options that change the picture without touching the stream.
LIVE_OVERLAY = ("cursor", "clock", "badge", "caption")
# Options that rebuild the stream but keep the TV session.
RESTREAM = ("fit", "record")


def recover():
    """Put back anything a crashed cast left changed."""
    audio.AudioRoute.recover()
    desk.QuietNotifications.recover()


class Cast:
    def __init__(self, on_state, on_displays, log=print, preview=False):
        self.on_state = on_state
        self.log = log
        self.preview = preview
        recover()
        self.prefs = saved.load()
        self.link = p2p.WifiDirect(on_displays, self._on_link, log)
        self.tv = tvcontrol.TvControl(self.prefs, log)
        self.session = None
        self.audio = None
        self.quiet = desk.QuietNotifications()
        self.awake = desk.StayAwake(APP_ID)
        self.source = {"kind": "screen"}
        self.display = None
        self.wanted = False
        self.was_streaming = False
        self.retried = False
        self.reconnects = 0
        self.wait_timer = 0
        self.frozen = False
        self.curtain = None
        self.state = "idle"
        self.text = ""
        self.since = None
        self._publish()

    # --- what callers use ------------------------------------------------

    def start(self, display, source=None, restart=False):
        # A restart (new quality) keeps the TV on Screen Share: no setup
        # before, no putting it back after.
        self.stop(report=False, finish_tv=False)
        self.wanted = True
        self.display = display
        self.retried = False
        self.reconnects = 0
        if source:
            self.source = source
        self.prefs = saved.update(last_display={"name": display.name, "address": display.address})
        self.tv.prefs = self.prefs
        if not restart and self.prefs.get("tv_setup") and self.tv.known_for(display.name):
            self._report("preparing", f"Getting {display.name} ready")
            self.tv.prepare(display.name, lambda: self._join(display))
        else:
            self._join(display)

    def stop(self, report=True, finish_tv=True):
        was = self.was_streaming
        self.was_streaming = False
        self.wanted = False
        self._clear_wait()
        if self.session:
            session, self.session = self.session, None
            session.on_state = lambda *_: None
            session.stop()
        self.display = None
        self.link.disconnect()
        self._comfort(False)
        self.frozen = False
        self.curtain = None
        if was and finish_tv:
            self.tv.finish()
        if report:
            self._report("ended", "Stopped")

    def find_display(self, wanted=None):
        """A display by name/address, or the last one used, among those found."""
        last = self.prefs.get("last_display") or {}
        for display in self.link.displays():
            if wanted and (wanted.lower() in display.name.lower() or wanted == display.address):
                return display
            if not wanted and display.address == last.get("address"):
                return display
        return None

    def set_source(self, source):
        self.source = source
        if self.session:
            self.session.restream(source=source)
        self._publish()

    def set_option(self, key, value):
        self.prefs[key] = value
        saved.save(self.prefs)
        overlay = self._overlay()
        if key in LIVE_OVERLAY and overlay:
            setattr(overlay, key, value)
        elif key in RESTREAM and self.session:
            self.session.restream(prefs=self.prefs)
        elif key == "sound" and self.session:
            self._route_audio()
            self.session.restream(audio_device=self.audio.capture_device or "")
        elif key == "quality" and self.session and self.display:
            # A new mode has to be agreed with the TV, so the session restarts.
            self.start(self.display, self.source, restart=True)
        elif key == "quiet" and self.state == "streaming":
            (self.quiet.start if value else self.quiet.stop)()
        self._publish()

    def freeze(self, on):
        self.frozen = bool(on)
        overlay = self._overlay()
        if overlay:
            overlay.freeze = self.frozen
        self._publish()

    def set_curtain(self, text):
        """None lifts it; any text (even empty) shows it."""
        self.curtain = text
        overlay = self._overlay()
        if overlay:
            overlay.curtain = text
        self._publish()

    def stats(self):
        stream = self.session.stream if self.session else None
        return stream.stats() if stream else None

    def preview_frame(self):
        stream = self.session.stream if self.session else None
        return stream.preview() if stream else None

    @property
    def casting(self):
        return self.wanted

    # --- internals -------------------------------------------------------

    def _overlay(self):
        stream = self.session.stream if self.session else None
        return stream.overlay if stream else None

    def _join(self, display):
        if not self.wanted or self.display is not display:
            return
        self._route_audio()
        self.session = cast_session.Session(
            self._on_session, self.prefs, self.source, self.audio.capture_device, self.log,
            self.preview)
        try:
            self.session.listen()
        except GLib.Error as error:
            self.session = None
            self.wanted = False
            self._report("failed", f"Port 7236 is busy: {error.message}")
            return
        self.link.connect_to(display)

    def _route_audio(self):
        if self.audio:
            self.audio.stop()
        self.audio = audio.AudioRoute(self.prefs.get("sound", "tv"))
        self.audio.start()

    def _comfort(self, on):
        if on:
            if self.prefs.get("quiet"):
                self.quiet.start()
            self.awake.start()
        else:
            self.quiet.stop()
            self.awake.stop()
            if self.audio:
                self.audio.stop()
                self.audio = None

    def _clear_wait(self):
        if self.wait_timer:
            GLib.source_remove(self.wait_timer)
            self.wait_timer = 0

    def _drop_session(self, reason=None):
        if self.session:
            session, self.session = self.session, None
            session.on_state = lambda *_: None
            session.stop(reason or "Stopped")

    def _on_link(self, state, text):
        self.log(f"cast: link {state}: {text}")
        if state == "connecting":
            self._report("connecting", text)
        elif state == "connected":
            self._report("connecting", "Linked. Waiting for the TV to open the session")
            self.wait_timer = GLib.timeout_add_seconds(OPEN_TIMEOUT_S, self._open_timeout)
        elif state in ("disconnected", "failed"):
            if not self.wanted or self.display is None:
                return
            display = self.display
            self._clear_wait()
            never_opened = self.session and self.session.state == "listening"
            self._drop_session(text)
            if state == "disconnected" and never_opened and not self.retried:
                self.retried = True
                self._report("connecting", "The TV is still busy. Trying again")
                GLib.timeout_add_seconds(RETRY_AFTER_S, self._again, display)
                return
            if (self.was_streaming and self.prefs.get("reconnect")
                    and self.reconnects < RECONNECT_TRIES):
                self.reconnects += 1
                self._report("reconnecting", f"Lost the TV. Reconnecting "
                                             f"({self.reconnects} of {RECONNECT_TRIES})")
                GLib.timeout_add_seconds(RETRY_AFTER_S, self._again, display)
                return
            self.stop(report=False)
            self._report("failed" if state == "failed" else "ended", text)

    def _again(self, display):
        if self.wanted and self.display is display and self.session is None:
            self._join(display)
        return GLib.SOURCE_REMOVE

    def _open_timeout(self):
        self.wait_timer = 0
        if self.session and self.session.state == "listening":
            self.stop(report=False)
            self._report("failed", "The TV linked but never opened the session. "
                                   "Open Screen Share on the TV and try again.")
        return GLib.SOURCE_REMOVE

    def _on_session(self, state, text):
        if state == "listening":
            return
        if state in ("negotiating", "streaming"):
            self._clear_wait()
        if state == "streaming":
            self.reconnects = 0
            self._comfort(True)
            overlay = self._overlay()
            if overlay:
                overlay.freeze = self.frozen
                overlay.curtain = self.curtain
        if state in ("ended", "failed"):
            self.session = None
            self.stop(report=False)
        self._report(state, text)

    def _report(self, state, text):
        if state == "streaming" and self.state != "streaming":
            self.since = time.time()
            self.was_streaming = True
        elif state in ("ended", "failed", "idle"):
            self.since = None
            self.was_streaming = False
        self.state, self.text = state, text
        self.log(f"cast: [{state}] {text}")
        self._publish()
        self.on_state(state, text)

    def _publish(self):
        data = {
            "state": self.state,
            "text": self.text,
            "tv": self.display.name if self.display else None,
            "since": self.since,
            "quality": self.prefs.get("quality"),
            "sound": self.prefs.get("sound"),
            "source": self.source.get("title") or self.source.get("kind"),
            "frozen": self.frozen,
            "curtain": self.curtain is not None,
            "recording": bool(self.prefs.get("record")) and self.state == "streaming",
            "pid": os.getpid(),
        }
        try:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(STATE_FILE)
        except OSError:
            pass
