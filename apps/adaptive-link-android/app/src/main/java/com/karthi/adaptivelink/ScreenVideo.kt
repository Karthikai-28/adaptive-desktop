package com.karthi.adaptivelink

import android.content.Context
import android.graphics.SurfaceTexture
import android.media.AudioAttributes
import android.view.TextureView
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.EglBase
import org.webrtc.EglRenderer
import org.webrtc.GlRectDrawer
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.MediaStreamTrack
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.VideoFrame
import org.webrtc.VideoSink
import org.webrtc.VideoTrack
import org.webrtc.audio.JavaAudioDeviceModule
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume

/**
 * What the direct tunnel and the screen-as-video share: one WebRTC factory
 * for the app, and where a connection may look for a way to the computer.
 */
object Rtc {
    /** The graphics context video is decoded and drawn with. */
    val egl: EglBase by lazy { EglBase.create() }

    @Volatile private var shared: PeerConnectionFactory? = null

    fun factory(context: Context): PeerConnectionFactory = shared ?: synchronized(this) {
        shared ?: run {
            val app = context.applicationContext
            PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(app).createInitializationOptions()
            )
            // The computer's sound is played as music is, at the media
            // volume, not as a phone call would be.
            val audio = JavaAudioDeviceModule.builder(app)
                .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .createAudioDeviceModule()
            PeerConnectionFactory.builder()
                .setAudioDeviceModule(audio)
                .setVideoDecoderFactory(DefaultVideoDecoderFactory(egl.eglBaseContext))
                .createPeerConnectionFactory().also { shared = it }
        }
    }

    /**
     * The server that tells each device its own address, and the owner's
     * relay if the computer has told this phone of one (Store.relay).
     */
    fun iceServers(context: Context, stun: String): List<PeerConnection.IceServer> {
        val servers = mutableListOf<PeerConnection.IceServer>()
        if (stun.isNotBlank()) servers += PeerConnection.IceServer.builder(stun).createIceServer()
        Relay.fromJson(Store(context).relay)?.let { relay ->
            servers += PeerConnection.IceServer.builder(relay.url).setUsername(relay.username)
                .setPassword(relay.credential).createIceServer()
        }
        return servers
    }
}

/**
 * The computer's screen as video, with its sound (the computer's side is
 * services/adaptive-link/media.py).
 *
 * The offer and the answer travel over the link, like any other request, so
 * only this paired phone can set the connection up; the pictures then come
 * on a connection of their own, encrypted between the two devices.
 */
class ScreenVideo(
    private val context: Context,
    private val client: LinkClient,
    /** "" while all is well, otherwise why there is no picture. */
    private val onState: (String) -> Unit,
) {
    private var peer: PeerConnection? = null
    private var session = 0
    @Volatile private var track: VideoTrack? = null
    @Volatile private var sink: VideoSink? = null

    /** Whether the computer is sending its sound as well. */
    @Volatile var sound = false
        private set

    /** Where the pictures are to be drawn. */
    fun show(on: VideoSink) {
        sink = on
        track?.addSink(on)
    }

    /** Ask the computer for its screen. Returns whether it agreed. */
    suspend fun start(preset: String, withSound: Boolean): Boolean {
        val stun = Cloud(context).config.stun
        val connection = Rtc.factory(context).createPeerConnection(
            PeerConnection.RTCConfiguration(Rtc.iceServers(context, stun)).apply {
                sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            },
            object : Observer() {
                override fun onTrack(transceiver: RtpTransceiver) {
                    (transceiver.receiver.track() as? VideoTrack)?.let { video ->
                        track = video
                        sink?.let { video.addSink(it) }
                    }
                }

                override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
                    when (state) {
                        PeerConnection.PeerConnectionState.CONNECTED -> onState("")
                        PeerConnection.PeerConnectionState.FAILED -> onState("The video connection could not be made")
                        PeerConnection.PeerConnectionState.DISCONNECTED -> onState("Connection lost")
                        else -> Unit
                    }
                }
            },
        ) ?: return false
        peer = connection

        val receive = RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY)
        val video = connection.addTransceiver(MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO, receive)
        // H.264 first where this phone has it: phones decode it in their
        // hardware, which is kinder to the battery. The order is only a
        // preference; if it cannot be set the phone's own order stands.
        runCatching {
            val codecs = Rtc.factory(context).getRtpReceiverCapabilities(MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO).codecs
            video.setCodecPreferences(codecs.sortedBy { if (it.name.equals("H264", ignoreCase = true)) 0 else 1 })
        }
        if (withSound) connection.addTransceiver(MediaStreamTrack.MediaType.MEDIA_TYPE_AUDIO, receive)

        val offer = connection.create { createOffer(it, MediaConstraints()) } ?: return false
        if (!connection.set { setLocalDescription(it, offer) }) return false
        // All of this phone's addresses go in the one offer. On the
        // computer's own network that takes no time; elsewhere, a moment.
        withTimeoutOrNull(4_000) {
            while (connection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) delay(50)
        }
        val reply = client.post("/v1/rtc", JSONObject().put("offer", connection.localDescription.description)
            .put("preset", preset).put("sound", withSound))
        if (reply == null || !reply.optBoolean("ok")) {
            onState(reply?.optString("error").orEmpty())
            return false
        }
        session = reply.optInt("id")
        sound = reply.optBoolean("sound")
        return connection.set { setRemoteDescription(it, SessionDescription(SessionDescription.Type.ANSWER, reply.optString("answer"))) }
    }

    /** Stop watching, and tell the computer so it stops capturing. */
    suspend fun stop() {
        val ended = session
        session = 0
        sink?.let { on -> runCatching { track?.removeSink(on) } }
        track = null
        runCatching { peer?.close() }
        runCatching { peer?.dispose() }
        peer = null
        if (ended != 0) client.post("/v1/rtc/close", JSONObject().put("id", ended))
    }

    private suspend fun PeerConnection.create(start: PeerConnection.(SdpObserver) -> Unit): SessionDescription? =
        suspendCancellableCoroutine { continuation ->
            start(object : SdpObserver {
                override fun onCreateSuccess(description: SessionDescription) = continuation.resume(description)
                override fun onCreateFailure(reason: String?) = continuation.resume(null)
                override fun onSetSuccess() = Unit
                override fun onSetFailure(reason: String?) = Unit
            })
        }

    private suspend fun PeerConnection.set(start: PeerConnection.(SdpObserver) -> Unit): Boolean =
        suspendCancellableCoroutine { continuation ->
            start(object : SdpObserver {
                override fun onSetSuccess() = continuation.resume(true)
                override fun onSetFailure(reason: String?) = continuation.resume(false)
                override fun onCreateSuccess(description: SessionDescription) = Unit
                override fun onCreateFailure(reason: String?) = Unit
            })
        }

    private open class Observer : PeerConnection.Observer {
        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = Unit
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) = Unit
        override fun onIceCandidate(candidate: IceCandidate) = Unit
        override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) = Unit
        override fun onAddStream(stream: MediaStream) = Unit
        override fun onRemoveStream(stream: MediaStream) = Unit
        override fun onDataChannel(channel: DataChannel) = Unit
        override fun onRenegotiationNeeded() = Unit
        override fun onAddTrack(receiver: RtpReceiver, streams: Array<MediaStream>) = Unit
    }
}

/**
 * Where the video is drawn. An ordinary view, so that it can be zoomed and
 * moved like the picture it replaces; it says how large the pictures are,
 * which is what a touch on it is measured against.
 */
class VideoView(context: Context) : TextureView(context), TextureView.SurfaceTextureListener, VideoSink {
    private val renderer = EglRenderer("screen")
    @Volatile private var frameWidth = 0
    @Volatile private var frameHeight = 0

    /** Called, on the main thread, when the size of the pictures is known or changes. */
    var onSize: ((Int, Int) -> Unit)? = null

    init {
        surfaceTextureListener = this
        renderer.init(Rtc.egl.eglBaseContext, EglBase.CONFIG_PLAIN, GlRectDrawer())
    }

    override fun onFrame(frame: VideoFrame) {
        if (frame.rotatedWidth != frameWidth || frame.rotatedHeight != frameHeight) {
            frameWidth = frame.rotatedWidth
            frameHeight = frame.rotatedHeight
            val (w, h) = frameWidth to frameHeight
            post { onSize?.invoke(w, h) }
        }
        renderer.onFrame(frame)
    }

    override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) {
        renderer.createEglSurface(surface)
    }

    override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) = Unit
    override fun onSurfaceTextureUpdated(surface: SurfaceTexture) = Unit

    override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
        // The surface must not go while a frame is being drawn on it.
        val released = CountDownLatch(1)
        renderer.releaseEglSurface { released.countDown() }
        released.await(1, TimeUnit.SECONDS)
        return true
    }

    /** A new stream is about to start: say how large its pictures are, even if they are as large as the last one's. */
    fun fresh() {
        frameWidth = 0
        frameHeight = 0
    }

    fun release() = renderer.release()
}
