"""One Miracast session: the RTSP control channel and the media pipeline.

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

Everything runs on the GLib main loop; nothing blocks.
"""

import secrets

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst  # noqa: E402

import wfd  # noqa: E402

Gst.init(None)

PRESENTATION = "rtsp://{ip}/wfd1.0/streamid=0"
KEEPALIVE_S = 25
SESSION_TIMEOUT_S = 30
BITRATE_KBPS = {1080: 8000, 720: 5000}


def element(name):
    return Gst.ElementFactory.find(name) is not None


def pick_encoder():
    """Hardware H.264 first (Intel VA-API), then x264, then OpenH264."""
    for name in ("vaapih264enc", "x264enc", "openh264enc"):
        if element(name):
            return name
    return None


def missing_elements():
    """GStreamer elements this needs that are not installed, by package."""
    need = {
        "mpegtsmux": "gstreamer1.0-plugins-bad",
        "h264parse": "gstreamer1.0-plugins-bad",
        "rtpmp2tpay": "gstreamer1.0-plugins-good",
        "ximagesrc": "gstreamer1.0-plugins-good",
    }
    out = {pkg for name, pkg in need.items() if not element(name)}
    if not pick_encoder():
        out.add("gstreamer1.0-vaapi")
    return sorted(out)


def have_aac():
    return element("voaacenc") or element("avenc_aac") or element("fdkaacenc")


def encoder_chain(encoder, video):
    kbps = BITRATE_KBPS.get(video["height"], 3000)
    gop = video["fps"]
    if encoder == "vaapih264enc":
        # Constant QP: on this Gen9 iGPU the iHD driver refuses CBR/VBR
        # (bitrate control needs HuC firmware the kernel does not load), so
        # quality is fixed instead. Desktop content stays far below the
        # 50 Mbps a WFD sink takes.
        return f"vaapih264enc rate-control=cqp init-qp=26 keyframe-period={gop} max-bframes=0"
    if encoder == "x264enc":
        return (f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={kbps}"
                f" key-int-max={gop} bframes=0 sliced-threads=true")
    return f"openh264enc bitrate={kbps * 1000} gop-size={gop} complexity=low"


def aac_encoder():
    for name in ("voaacenc", "fdkaacenc", "avenc_aac"):
        if element(name):
            return name
    return None


def pipeline_description(video, audio, host, port, encoder, audio_device=None):
    """gst-launch text for the stream. Pure, so the check can read it.

    PIDs 0x1011 (video) and 0x1100 (audio) are the ones WFD sinks expect;
    mpegtsmux takes the PID from the requested pad name.
    """
    width, height, fps = video["width"], video["height"], video["fps"]
    # VA-API takes only NV12 here; the software encoders want I420.
    raw_format = "NV12" if encoder == "vaapih264enc" else "I420"
    parts = [
        f"mpegtsmux name=mux alignment=7 ! rtpmp2tpay pt=33 ! "
        f"udpsink host={host} port={port} sync=false async=false",
        f"ximagesrc use-damage=false show-pointer=true ! video/x-raw,framerate={fps}/1 ! "
        "queue leaky=downstream max-size-buffers=2 ! videoconvert ! videoscale ! "
        f"video/x-raw,format={raw_format},width={width},height={height},pixel-aspect-ratio=1/1 ! "
        f"{encoder_chain(encoder, video)} name=venc ! "
        "video/x-h264,profile=constrained-baseline ! "
        "h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! "
        "queue ! mux.sink_4113",
    ]
    if audio == "AAC":
        device = f" device={audio_device}" if audio_device else ""
        parts.append(
            f"pulsesrc{device} ! audioconvert ! audioresample ! "
            "audio/x-raw,rate=48000,channels=2 ! "
            f"{aac_encoder()} bitrate=128000 ! aacparse ! queue ! mux.sink_4352")
    return "  ".join(parts)


def monitor_source():
    """The monitor of the default output, so the TV plays what the laptop plays."""
    try:
        out = Gio.Subprocess.new(["pactl", "get-default-sink"], Gio.SubprocessFlags.STDOUT_PIPE)
        ok, stdout, _ = out.communicate_utf8(None, None)
        sink = (stdout or "").strip()
        return f"{sink}.monitor" if ok and sink else None
    except GLib.Error:
        return None


class Session:
    """Serves one TV on port 7236. Report state through on_state(state, text).

    States: listening, negotiating, streaming, ended, failed.
    """

    def __init__(self, on_state, log=print):
        self.on_state = on_state
        self.log = log
        self.service = None
        self.conn = None
        self.buffer = b""
        self.cseq = 0
        self.pending = {}
        self.pipeline = None
        self.keepalive = 0
        self.session_id = secrets.token_hex(4).upper()
        self.video = None
        self.audio = None
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

    def _close(self, reason, state="ended"):
        if self.keepalive:
            GLib.source_remove(self.keepalive)
            self.keepalive = 0
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
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
                self._send_request(
                    "GET_PARAMETER", "rtsp://localhost/wfd1.0",
                    body="wfd_video_formats\r\nwfd_audio_codecs\r\nwfd_client_rtp_ports\r\n",
                    then=self._on_capabilities)
        elif method == "SETUP":
            self._on_setup(message)
        elif method == "PLAY":
            self._reply(message, {"Session": self.session_id})
            self._start_stream()
        elif method == "PAUSE":
            self._reply(message, {"Session": self.session_id})
            if self.pipeline:
                self.pipeline.set_state(Gst.State.PAUSED)
        elif method == "TEARDOWN":
            self._reply(message, {"Session": self.session_id})
            self._close(self.stopping or "The TV ended the session")
        elif method == "SET_PARAMETER":
            self._reply(message)
            if "wfd_idr_request" in message.body:
                self._force_keyframe()
        else:
            self._reply(message)

    def _on_capabilities(self, message):
        params = wfd.parameters(message.body)
        self.log(f"cast: TV offers {params}")
        self.video = wfd.choose_video(params.get("wfd_video_formats"))
        if self.video is None:
            self._fail("The TV did not list any video format")
            return
        self.audio = wfd.choose_audio(params.get("wfd_audio_codecs"), have_aac())
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
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)
            return
        encoder = pick_encoder()
        description = pipeline_description(self.video, self.audio, self.sink_ip, self.rtp_port,
                                           encoder, monitor_source())
        self.log(f"cast: {description}")
        try:
            self.pipeline = Gst.parse_launch(description)
        except GLib.Error as error:
            self._fail(f"Could not build the stream: {error.message}")
            return
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.keepalive = GLib.timeout_add_seconds(KEEPALIVE_S, self._keep_alive)
        sound = "with sound" if self.audio else "no sound"
        self._set("streaming", f"Showing on the TV at {self.video['width']}x{self.video['height']}"
                               f" {self.video['fps']} fps, {sound}")

    def _keep_alive(self):
        self._send_request("GET_PARAMETER", "rtsp://localhost/wfd1.0")
        return GLib.SOURCE_CONTINUE

    def _force_keyframe(self):
        if not self.pipeline:
            return
        gi.require_version("GstVideo", "1.0")
        from gi.repository import GstVideo
        venc = self.pipeline.get_by_name("venc")
        if venc:
            event = GstVideo.video_event_new_upstream_force_key_unit(
                Gst.CLOCK_TIME_NONE, True, 0)
            venc.get_static_pad("src").send_event(event)

    def _on_error(self, _bus, message):
        error, _debug = message.parse_error()
        self._fail(f"Stream stopped: {error.message}")
