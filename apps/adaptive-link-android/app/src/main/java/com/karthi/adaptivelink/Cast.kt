package com.karthi.adaptivelink

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.Activity
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Path
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.provider.Settings
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.ScreenCapturerAndroid
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoSource
import org.webrtc.VideoTrack
import kotlin.coroutines.resume

/**
 * This phone's screen, shown in a window on the computer and used from
 * there (the computer's side is services/adaptive-link/phone_screen.py).
 *
 * Android asks its owner every time before an app may record the screen, and
 * shows that it is being recorded for as long as it is; this goes through
 * both. What is clicked and typed in the computer's window comes back over
 * the link, and is done here by an accessibility service - which the owner
 * turns on in Android's settings, or leaves off to be watched and not used.
 */
object Cast {
    @Volatile var showing = false
        internal set

    /** Ask Android's permission to record the screen, then start sending. */
    fun start(context: Context) {
        context.startActivity(Intent(context, CastActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun stop(context: Context) {
        context.stopService(Intent(context, CastService::class.java))
    }

    /** The computer asked for the screen: say so, for the owner to allow by tapping. */
    fun asked(context: Context) {
        EventsService.channels(context)
        if (!EventsService.mayNotify(context)) return
        val open = PendingIntent.getActivity(context, 61, Intent(context, CastActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ASKED,
            NotificationCompat.Builder(context, EventsService.CHANNEL_URGENT)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle("Show this phone on ${Store(context).computer?.name ?: "the computer"}?")
                .setContentText("Tap to allow. Android will ask once more.")
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setContentIntent(open).setAutoCancel(true).setTimeoutAfter(60_000).build())
    }

    internal const val NOTIFICATION_ASKED = 3
    internal const val NOTIFICATION_SHOWING = 4
}

/** Nothing to look at: it only carries Android's question about recording the screen. */
class CastActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        getSystemService(NotificationManager::class.java).cancel(Cast.NOTIFICATION_ASKED)
        val ask = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val data = result.data
            if (result.resultCode == Activity.RESULT_OK && data != null) {
                ContextCompat.startForegroundService(this, Intent(this, CastService::class.java)
                    .putExtra(CastService.EXTRA_CODE, result.resultCode).putExtra(CastService.EXTRA_DATA, data))
            }
            finish()
        }
        ask.launch(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent())
    }
}

class CastService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var peer: PeerConnection? = null
    private var capturer: ScreenCapturerAndroid? = null
    private var source: VideoSource? = null
    private var track: VideoTrack? = null
    private var helper: SurfaceTextureHelper? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        EventsService.channels(this)
        val stop = PendingIntent.getService(this, 62, Intent(this, CastService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val shown = NotificationCompat.Builder(this, EventsService.CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle("This phone's screen is on ${Store(this).computer?.name ?: "the computer"}")
            .setOngoing(true).addAction(0, "Stop", stop).build()
        // The kind of service Android requires for recording the screen, started before the recording is.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(Cast.NOTIFICATION_SHOWING, shown, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else startForeground(Cast.NOTIFICATION_SHOWING, shown)

        @Suppress("DEPRECATION") val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        val client = Link.client(this)
        if (data == null || client == null || peer != null) {
            if (peer == null) stopSelf()
            return START_NOT_STICKY
        }
        scope.launch {
            val agreed = runCatching { send(client, data) }.getOrDefault(false)
            if (!agreed) stopSelf()
        }
        return START_NOT_STICKY
    }

    private suspend fun send(client: LinkClient, permission: Intent): Boolean {
        if (client.host == null && client.connect() == null) return false
        // No larger than is useful in a window: the longer side at most 1280.
        val bounds = getSystemService(WindowManager::class.java).let {
            if (Build.VERSION.SDK_INT >= 30) it.currentWindowMetrics.bounds.let { b -> b.width() to b.height() }
            else resources.displayMetrics.let { m -> m.widthPixels to m.heightPixels }
        }
        val scale = minOf(1f, 1280f / maxOf(bounds.first, bounds.second))
        val width = (bounds.first * scale).toInt() / 2 * 2
        val height = (bounds.second * scale).toInt() / 2 * 2

        val factory = Rtc.factory(this)
        val recorder = ScreenCapturerAndroid(permission, object : MediaProjection.Callback() {
            override fun onStop() = stopSelf()   // stopped from Android's own "stop sharing"
        })
        val made = factory.createVideoSource(true)
        val textures = SurfaceTextureHelper.create("link-cast", Rtc.egl.eglBaseContext)
        recorder.initialize(textures, this, made.capturerObserver)
        recorder.startCapture(width, height, 15)
        val video = factory.createVideoTrack("phone-screen", made)
        capturer = recorder; source = made; helper = textures; track = video

        val connection = factory.createPeerConnection(
            PeerConnection.RTCConfiguration(Rtc.iceServers(this, Cloud(this).config.stun)).apply {
                sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            },
            object : Observer() {
                override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
                    if (state == PeerConnection.PeerConnectionState.FAILED || state == PeerConnection.PeerConnectionState.CLOSED) stopSelf()
                }
            },
        ) ?: return false
        peer = connection
        connection.addTransceiver(video, RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.SEND_ONLY))

        val offer = connection.create { createOffer(it, MediaConstraints()) } ?: return false
        if (!connection.set { setLocalDescription(it, offer) }) return false
        withTimeoutOrNull(4_000) {
            while (connection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) delay(50)
        }
        val reply = client.post("/v1/phone/screen", JSONObject().put("offer", connection.localDescription.description))
        if (reply?.optBoolean("ok") != true) return false
        Cast.showing = true
        return connection.set { setRemoteDescription(it, SessionDescription(SessionDescription.Type.ANSWER, reply.optString("answer"))) }
    }

    override fun onDestroy() {
        val was = Cast.showing
        Cast.showing = false
        runCatching { capturer?.stopCapture() }
        runCatching { capturer?.dispose() }
        runCatching { peer?.close() }
        runCatching { peer?.dispose() }
        runCatching { track?.dispose() }
        runCatching { source?.dispose() }
        runCatching { helper?.dispose() }
        peer = null
        val client = Link.client(this)
        if (was && client != null) CoroutineScope(Dispatchers.IO).launch { client.post("/v1/phone/screen/close") }
        scope.cancel()
        super.onDestroy()
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

    companion object {
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
        const val ACTION_STOP = "com.karthi.adaptivelink.CAST_STOP"
    }
}

/**
 * Does on this phone what is done in its window on the computer: a touch, a
 * swipe, a long press, the back, home and recents keys, and typing. Android
 * lets an app do these to others only as an accessibility service, which its
 * owner has to turn on in Settings - and it acts only while the phone's
 * screen is being shown on the computer.
 */
class PhoneControl : AccessibilityService() {
    override fun onServiceConnected() { running = this }
    override fun onUnbind(intent: Intent?): Boolean { running = null; return super.onUnbind(intent) }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit

    private fun size(): Pair<Float, Float> = getSystemService(WindowManager::class.java).let {
        if (Build.VERSION.SDK_INT >= 30) it.currentWindowMetrics.bounds.let { b -> b.width().toFloat() to b.height().toFloat() }
        else resources.displayMetrics.let { m -> m.widthPixels.toFloat() to m.heightPixels.toFloat() }
    }

    private fun stroke(path: Path, ms: Long) {
        dispatchGesture(GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, ms)).build(), null, null)
    }

    fun perform(event: JSONObject) {
        val (width, height) = size()
        fun at(x: String, y: String) = (event.optDouble(x, 0.5).toFloat().coerceIn(0f, 1f) * (width - 1)) to
            (event.optDouble(y, 0.5).toFloat().coerceIn(0f, 1f) * (height - 1))
        when (event.optString("t")) {
            "tap", "hold" -> {
                val (x, y) = at("x", "y")
                stroke(Path().apply { moveTo(x, y); lineTo(x, y) }, if (event.optString("t") == "hold") 700 else 60)
            }
            "swipe" -> {
                val (x, y) = at("x", "y")
                val (x2, y2) = at("x2", "y2")
                stroke(Path().apply { moveTo(x, y); lineTo(x2, y2) }, event.optLong("ms", 300).coerceIn(50, 3000))
            }
            "key" -> when (event.optString("k")) {
                "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
                "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
                "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
                "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
                "lock" -> if (Build.VERSION.SDK_INT >= 28) performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN)
            }
            "text" -> type(event.optString("s"))
        }
    }

    /** Typing goes into whatever field has the cursor, as the phone's own keyboard's would. */
    private fun type(said: String) {
        val field = findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return
        if (said == "\n") {
            if (Build.VERSION.SDK_INT >= 30) field.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
            return
        }
        val now = if (field.isShowingHintText) "" else field.text?.toString().orEmpty()
        val next = if (said == "\b") now.dropLast(1) else now + said
        field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
            Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, next) })
    }

    companion object {
        @Volatile var running: PhoneControl? = null
            private set

        fun enabled(context: Context): Boolean =
            Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
                .contains(ComponentName(context, PhoneControl::class.java).flattenToString())
    }
}
