"""One Miracast session: the RTSP control channel to the TV.

The TV opens a TCP connection to port 7236 once the Wi-Fi Direct group is
up. From then on this side drives the exchange:

  M1  OPTIONS          source -> sink
  M2  OPTIONS          sink -> source
  M3  GET_PARAMETER    source -> sink   what can you play, which UDP port
  M4  SET_PARAMETER    source -> sink   this format, this URL
  M5  SET_PARAMETER    source -> sink   trigger SETUP
  M6  SETUP            sink -> source
  M7  PLAY             sink -> source   start sending MPEG-TS over RTP
  M16 GET_PARAMETER    source -> sink   keep-alive while streaming

The media itself is stream.Stream. Everything runs on the GLib main loop.
"""

import secrets

from gi.repository import Gio, GLib

import stream as media
import wfd

PRESENTATION = "rtsp://{ip}/wfd1.0/streamid=0"
KEEPALIVE_S = 25
SESSION_TIMEOUT_S = 30
# Asked for in M3 beyond what the stream needs, so the window can say what
# the TV is and whether its remote could drive this laptop.
EXTRA_PARAMETERS = ("wfd_uibc_capability", "wfd_content_protection", "wfd_display_edid",
                    "wfd_connector_type")


def missing_elements():
    return media.missing_elements()


def have_aac():
    return media.aac_encoder() is not None


class Session:
    """Serves one TV on port 7236. Report state through on_state(state, text).

    States: listening, negotiating, streaming, ended, failed.
    """

    def __init__(self, on_state, prefs, source=None, audio_device=None, log=print,
                 preview=False):
        self.on_state = on_state
        self.prefs = prefs
        self.source = source or {"kind": "screen"}
        self.audio_device = audio_device
        self.log = log
        self.preview = preview
        self.service = None
        self.conn = None
        self.buffer = b""
        self.cseq = 0
        self.pending = {}
        self.stream = None
        self.keepalive = 0
        self.session_id = secrets.token_hex(4).upper()
        self.video = None
        self.audio = None
        self.sink_params = {}
        self.rtp_port = None
        self.sink_ip = None
        self.local_ip = None
        self.state = None
        self.stopping = None
        self.cancel = Gio.Cancellable()

    # --- lifecycle -------------------------------------------------------

    def listen(self):
        self.service = Gio.SocketService.new()
        self.service.add_inet_port(wfd.CONTROL_PORT, None)
        self.service.connect("incoming", self._incoming)
        self.service.start()
        self._set("listening", "Waiting for the TV to open the session")

    def stop(self, reason="Stopped"):
        """Ask the TV to tear down, then close everything."""
        self.stopping = reason
        if self.conn and self.state == "streaming":
            self._send_request("SET_PARAMETER", "rtsp://localhost/wfd1.0",
                               body="wfd_trigger_method: TEARDOWN\r\n")
            GLib.timeout_add(500, self._close, reason)
        else:
            self._close(reason)

    def restream(self, source=None, prefs=None, audio_device=None):
        """Rebuild the media with a new source or options, keeping the TV session.

        The video mode stays as negotiated; the TV sees a fresh keyframe.
        """
        if source is not None:
            self.source = source
        if prefs is not None:
            self.prefs = prefs
        if audio_device is not None:
            self.audio_device = audio_device or None
        if self.state != "streaming":
            return
        self._stop_stream()
        self._start_stream()

    def _close(self, reason, state="ended"):
        if self.keepalive:
            GLib.source_remove(self.keepalive)
            self.keepalive = 0
        self._stop_stream()
        self.cancel.cancel()
        if self.conn:
            self.conn.close(None)
            self.conn = None
        if self.service:
            self.service.stop()
            self.service.close()
            self.service = None
        if self.state not in ("ended", "failed"):
            self._set(state, reason)
        return GLib.SOURCE_REMOVE

    def _fail(self, reason):
        self.log(f"cast: {reason}")
        self._close(reason, "failed")

    def _set(self, state, text):
        self.state = state
        self.on_state(state, text)

    # --- control channel -------------------------------------------------

    def _incoming(self, _service, conn, _source):
        if self.conn:
            return True
        self.conn = conn
        self.sink_ip = conn.get_remote_address().get_address().to_string()
        self.local_ip = conn.get_local_address().get_address().to_string()
        self.log(f"cast: TV connected from {self.sink_ip} to {self.local_ip}")
        self._set("negotiating", "Agreeing on a picture format with the TV")
        self._read()
        self._send_request("OPTIONS", "*", {"Require": "org.wfa.wfd1.0"})
        return True

    def _read(self):
        if not self.conn:
            return
        self.conn.get_input_stream().read_bytes_async(
            65536, GLib.PRIORITY_DEFAULT, self.cancel, self._on_read)

    def _on_read(self, stream, result):
        try:
            data = stream.read_bytes_finish(result).get_data()
        except GLib.Error as error:
            if not self.cancel.is_cancelled():
                self._fail(f"Lost the TV: {error.message}")
            return
        if not data:
            if self.state != "ended":
                self._close(self.stopping or "The TV ended the session")
            return
        self.buffer += data
        while True:
            message, self.buffer = wfd.take_message(self.buffer)
            if message is None:
                break
            self._handle(message)
        self._read()

    def _write(self, payload):
        if not self.conn:
            return
        try:
            self.conn.get_output_stream().write_all(payload, None)
        except GLib.Error as error:
            self._fail(f"Could not reach the TV: {error.message}")

    def _send_request(self, method, uri, headers=None, body="", then=None):
        self.cseq += 1
        self.pending[self.cseq] = (method, then)
        self.log(f"cast: -> {method} (CSeq {self.cseq})")
        self._write(wfd.request(method, uri, self.cseq, headers, body))

    def _reply(self, message, headers=None, body=""):
        self._write(wfd.response(message.cseq, headers, body))

    def _handle(self, message):
        self.log(f"cast: <- {message.first_line} (CSeq {message.cseq}) {message.body.strip()!r}")
        if message.is_response:
            method, then = self.pending.pop(message.cseq, (None, None))
            if message.status != 200 and method != "GET_PARAMETER":
                self._fail(f"The TV refused {method} ({message.first_line})")
                return
            if then:
                then(message)
            return

        method = message.method
        if method == "OPTIONS":
            self._reply(message, {"Public": "org.wfa.wfd1.0, SETUP, TEARDOWN, PLAY, PAUSE, "
                                            "GET_PARAMETER, SET_PARAMETER"})
            if self.video is None:
                wanted = ("wfd_video_formats", "wfd_audio_codecs", "wfd_client_rtp_ports",
                          *EXTRA_PARAMETERS)
                self._send_request("GET_PARAMETER", "rtsp://localhost/wfd1.0",
                                   body="\r\n".join(wanted) + "\r\n", then=self._on_capabilities)
        elif method == "SETUP":
            self._on_setup(message)
        elif method == "PLAY":
            self._reply(message, {"Session": self.session_id})
            if self.stream:
                self.stream.pause(False)
            else:
                self._start_stream()
        elif method == "PAUSE":
            self._reply(message, {"Session": self.session_id})
            if self.stream:
                self.stream.pause(True)
        elif method == "TEARDOWN":
            self._reply(message, {"Session": self.session_id})
            self._close(self.stopping or "The TV ended the session")
        elif method == "SET_PARAMETER":
            self._reply(message)
            if "wfd_idr_request" in message.body and self.stream:
                self.stream.force_keyframe()
        else:
            self._reply(message)

    def _on_capabilities(self, message):
        params = wfd.parameters(message.body)
        self.sink_params = params
        quality = self.prefs.get("quality", "sharp")
        order = wfd.QUALITY.get(quality, wfd.QUALITY["sharp"])["order"]
        self.video = wfd.choose_video(params.get("wfd_video_formats"), order=order)
        if self.video is None:
            self._fail("The TV did not list any video format")
            return
        sound = self.audio_device is not None
        self.audio = wfd.choose_audio(params.get("wfd_audio_codecs"), have_aac() and sound)
        self.rtp_port = wfd.client_rtp_port(params.get("wfd_client_rtp_ports")) or 19000
        lines = [
            f"wfd_video_formats: {wfd.video_formats_value(self.video)}",
            f"wfd_presentation_URL: {PRESENTATION.format(ip=self.local_ip)} none",
            f"wfd_client_rtp_ports: RTP/AVP/UDP;unicast {self.rtp_port} 0 mode=play",
        ]
        if self.audio:
            lines.append(f"wfd_audio_codecs: {wfd.audio_codecs_value(self.audio)}")
        self._send_request("SET_PARAMETER", "rtsp://localhost/wfd1.0",
                           body="\r\n".join(lines) + "\r\n", then=self._trigger_setup)

    def _trigger_setup(self, _message):
        self._send_request("SET_PARAMETER", "rtsp://localhost/wfd1.0",
                           body="wfd_trigger_method: SETUP\r\n")

    def _on_setup(self, message):
        transport = message.header("Transport", "")
        for part in transport.split(";"):
            if part.startswith("client_port="):
                self.rtp_port = int(part.split("=", 1)[1].split("-")[0])
        self._reply(message, {
            "Session": f"{self.session_id};timeout={SESSION_TIMEOUT_S}",
            "Transport": f"RTP/AVP/UDP;unicast;client_port={self.rtp_port};server_port=6000-6001",
        })

    # --- media -----------------------------------------------------------

    def _start_stream(self):
        self.stream = media.Stream(
            self.video, self.audio, self.sink_ip, self.rtp_port, self.prefs, self.source,
            self.audio_device, self._on_stream_error, self.log, self.preview)
        try:
            self.stream.start()
        except GLib.Error as error:
            self.stream = None
            self._fail(f"Could not build the stream: {error.message}")
            return
        if not self.keepalive:
            self.keepalive = GLib.timeout_add_seconds(KEEPALIVE_S, self._keep_alive)
        sound = "with sound" if self.audio else "no sound"
        self._set("streaming", f"Showing on the TV at {self.video['width']}x{self.video['height']}"
                               f" {self.video['fps']} fps, {sound}")

    def _stop_stream(self):
        if self.stream:
            stream, self.stream = self.stream, None
            stream.stop()

    def _on_stream_error(self, text):
        self._fail(text)

    def _keep_alive(self):
        self._send_request("GET_PARAMETER", "rtsp://localhost/wfd1.0")
        return GLib.SOURCE_CONTINUE
