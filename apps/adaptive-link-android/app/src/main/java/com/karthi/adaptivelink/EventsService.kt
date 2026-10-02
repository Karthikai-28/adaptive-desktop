package com.karthi.adaptivelink

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.provider.MediaStore
import android.telephony.SmsManager
import android.telephony.TelephonyManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/**
 * The phone's standing connection to the computer, for everything the two
 * do without the app being open (the computer's side is alerts.py and
 * companion.py):
 *
 *  - the computer's alerts and notifications, shown here;
 *  - the clipboard, both ways;
 *  - the computer making this phone ring, to find it;
 *  - the phone's fingerprint approving something on the computer;
 *  - a text message written on the computer, sent from here;
 *  - saying that the phone is on the computer's network, so the computer
 *    can lock itself when it leaves;
 *  - the phone's battery and signal, and its new photos, sent over.
 *
 * It runs only while the owner has at least one of those switched on (More),
 * as a service Android shows in the notification shade, because it holds a
 * connection open while no screen of the app is. It listens on the same
 * mutually-authenticated link as everything else; when the computer cannot
 * be reached it waits and tries again, and on coming back asks for what was
 * said in the meantime.
 */
class EventsService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var listening: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_QUIET) {
            Ringer.stop(this)
            return START_STICKY
        }
        val store = Store(this)
        if (store.computer == null || !store.listens) {
            stopSelf()
            return START_NOT_STICKY
        }
        channels(this)
        val shown = NotificationCompat.Builder(this, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(store.computer?.name)
            .setContentText("Connected to this phone")
            .setOngoing(true)
            .setContentIntent(openApp(this))
        if (store.remoteNotification) {
            // The same buttons the widget has. A watch paired with this
            // phone shows them too, which makes it a remote for the computer.
            shown.addAction(0, "Lock", QuickActions.intent(this, "lock"))
            shown.addAction(0, "Play / pause", QuickActions.intent(this, "play-pause"))
            shown.addAction(0, "Next", QuickActions.intent(this, "next"))
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(ONGOING_ID, shown.build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(ONGOING_ID, shown.build())
        }
        // Started again when a switch changes: listen afresh, for what is wanted now.
        listening?.cancel()
        listening = scope.launch { listen() }
        return START_STICKY
    }

    override fun onDestroy() {
        Ringer.stop(this)
        scope.cancel()
        super.onDestroy()
    }

    private fun kinds(store: Store): List<String> = listOfNotNull(
        "alert".takeIf { store.computerAlerts },
        "notification".takeIf { store.computerNotifications },
        "clipboard".takeIf { store.syncClipboard },
        "ring".takeIf { store.findPhone },
        "approve".takeIf { store.approvals }, "approve-done".takeIf { store.approvals },
        "sms-send".takeIf { store.phoneMessages },
    )

    private suspend fun listen() {
        var wait = 3_000L
        while (true) {
            val store = Store(this)
            val client = Link.client(this) ?: return
            if (!store.listens) return
            if (client.host != null || client.connect() != null) {
                val ended = CompletableDeferred<Unit>()
                val path = "/v1/events?after=${store.lastEvent}&kinds=${kinds(store).joinToString(",")}" +
                    if (store.presence) "&present=1" else ""
                val socket = client.socket(path, object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        wait = 3_000L
                        scope.launch {
                            client.post("/v1/phone/state", PhoneState.read(this@EventsService))
                            if (store.copyPhotos && !client.tunnelled) Photos.copy(this@EventsService, client)
                        }
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        runCatching { JSONObject(text) }.getOrNull()?.let { runCatching { handle(client, it) } }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { ended.complete(Unit) }
                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { ended.complete(Unit) }
                })
                try {
                    ended.await()
                } finally {
                    socket.cancel()
                }
                // It may have moved to another network: look for it again.
                client.connect()
            }
            delay(wait)
            wait = (wait * 2).coerceAtMost(60_000L)
        }
    }

    private fun handle(client: LinkClient, event: JSONObject) {
        val store = Store(this)
        when (event.optString("kind")) {
            "clipboard" -> {
                val text = event.optString("text")
                if (text.isNotEmpty() && text != store.clipboardSeen) {
                    store.clipboardSeen = text
                    getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("From computer", text))
                }
            }
            "ring" -> Ringer.start(this)
            "approve" -> Approval.ask(this, event)
            "approve-done" -> Approval.done(this, event.optString("ask"))
            "sms-send" -> scope.launch {
                val sent = Texts.send(this@EventsService, event.optString("to"), event.optString("body"))
                client.post("/v1/phone/sent", JSONObject().put("id", event.optString("send")).put("ok", sent))
            }
            else -> show(event)
        }
    }

    private fun show(event: JSONObject) {
        val store = Store(this)
        val id = event.optLong("id")
        if (id <= store.lastEvent) return
        store.lastEvent = id
        if (!mayNotify(this)) return
        val alert = event.optString("kind") == "alert"
        val title = event.optString("title").ifBlank { event.optString("app") }.ifBlank { "Computer" }
        val text = event.optString("text")
        val shown = NotificationCompat.Builder(this, if (alert) CHANNEL_ALERTS else CHANNEL_NOTIFICATIONS)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setSubText(if (alert) store.computer?.name else event.optString("app").ifBlank { store.computer?.name })
            .setWhen(event.optLong("at") * 1000)
            .setAutoCancel(true)
            .setContentIntent(openApp(this))
            .build()
        // One notification per event, within a range that never meets the service's own.
        getSystemService(NotificationManager::class.java).notify(1000 + (id % 1_000_000).toInt(), shown)
    }

    companion object {
        const val ACTION_QUIET = "com.karthi.adaptivelink.QUIET"
        const val CHANNEL_SERVICE = "listening"
        const val CHANNEL_ALERTS = "alerts"
        const val CHANNEL_NOTIFICATIONS = "computer"
        const val CHANNEL_URGENT = "urgent"
        private const val ONGOING_ID = 1

        fun channels(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL_SERVICE, "Connected to the computer",
                NotificationManager.IMPORTANCE_LOW))
            manager.createNotificationChannel(NotificationChannel(CHANNEL_ALERTS, "Alerts about the computer",
                NotificationManager.IMPORTANCE_HIGH))
            manager.createNotificationChannel(NotificationChannel(CHANNEL_NOTIFICATIONS, "The computer's notifications",
                NotificationManager.IMPORTANCE_DEFAULT))
            manager.createNotificationChannel(NotificationChannel(CHANNEL_URGENT, "Approvals and finding this phone",
                NotificationManager.IMPORTANCE_HIGH))
        }

        fun mayNotify(context: Context): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

        fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)

        /** Start listening if the owner has asked for anything that needs it, or stop if they no longer do. */
        fun sync(context: Context) {
            val store = Store(context)
            val intent = Intent(context, EventsService::class.java)
            if (store.computer != null && store.listens) runCatching { ContextCompat.startForegroundService(context, intent) }
            else context.stopService(intent)
        }
    }
}

/** Listening starts again by itself when the phone is switched on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) EventsService.sync(context)
    }
}

/** Makes the phone ring, at full volume and whatever it is set to, until it is found. */
object Ringer {
    private const val NOTIFICATION = 2
    private var player: MediaPlayer? = null
    private var volumeBefore = -1

    @Synchronized
    fun start(context: Context) {
        if (player != null) return
        val app = context.applicationContext
        val audio = app.getSystemService(AudioManager::class.java)
        volumeBefore = audio.getStreamVolume(AudioManager.STREAM_ALARM)
        runCatching { audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0) }
        val sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        player = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build())
                setDataSource(app, sound)
                isLooping = true
                prepare()
                start()
            }
        }.getOrNull()
        EventsService.channels(app)
        if (EventsService.mayNotify(app)) {
            val quiet = PendingIntent.getService(app, 7, Intent(app, EventsService::class.java).setAction(EventsService.ACTION_QUIET),
                PendingIntent.FLAG_IMMUTABLE)
            app.getSystemService(NotificationManager::class.java).notify(NOTIFICATION,
                NotificationCompat.Builder(app, EventsService.CHANNEL_URGENT)
                    .setSmallIcon(R.drawable.ic_launcher)
                    .setContentTitle("Here I am")
                    .setContentText("${Store(app).computer?.name ?: "The computer"} is looking for this phone")
                    .setPriority(NotificationCompat.PRIORITY_MAX)
                    .setCategory(Notification.CATEGORY_ALARM)
                    .setContentIntent(quiet)
                    .addAction(0, "Stop", quiet)
                    .setAutoCancel(true)
                    .build())
        }
        // Not for ever: found or not, it stops after a minute.
        CoroutineScope(Dispatchers.Default).launch {
            delay(60_000)
            stop(app)
        }
    }

    @Synchronized
    fun stop(context: Context) {
        val playing = player ?: return
        player = null
        runCatching { playing.stop() }
        runCatching { playing.release() }
        val app = context.applicationContext
        if (volumeBefore >= 0) runCatching {
            app.getSystemService(AudioManager::class.java).setStreamVolume(AudioManager.STREAM_ALARM, volumeBefore, 0)
        }
        app.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION)
    }

    val ringing get() = player != null
}

/** What the phone says of itself: battery, signal, how it is connected. */
object PhoneState {
    fun read(context: Context): JSONObject {
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        val plugged = (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
        val state = JSONObject().put("charging", plugged)
        if (level >= 0 && scale > 0) state.put("battery", level * 100 / scale)
        runCatching {
            context.getSystemService(TelephonyManager::class.java).signalStrength?.level?.let { state.put("signal", it) }
        }
        runCatching {
            val network = context.getSystemService(ConnectivityManager::class.java)
            val using = network.getNetworkCapabilities(network.activeNetwork)
            state.put("network", when {
                using == null -> ""
                using.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                using.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile data"
                using.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                else -> ""
            })
        }
        return state
    }
}

/** Text messages: one written on the computer is sent from here. */
object Texts {
    fun maySend(context: Context) =
        ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED

    fun send(context: Context, to: String, body: String): Boolean {
        if (!maySend(context) || !Regex("^\\+?\\d{3,15}$").matches(to) || body.isBlank()) return false
        return runCatching {
            val manager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) context.getSystemService(SmsManager::class.java)
            else @Suppress("DEPRECATION") SmsManager.getDefault()
            manager.sendMultipartTextMessage(to, null, manager.divideMessage(body.take(1000)), null, null)
        }.isSuccess
    }
}

/** New photos, copied to the computer's Pictures/Phone. */
object Photos {
    fun mayRead(context: Context): Boolean {
        val permission = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES
        else Manifest.permission.READ_EXTERNAL_STORAGE
        return ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
    }

    /** Copy what was taken since the last copy, oldest first, a batch at a time. Returns how many went. */
    suspend fun copy(context: Context, client: LinkClient, batch: Int = 40): Int {
        val store = Store(context)
        if (!mayRead(context)) return 0
        // Turned on today, it starts from today: not the whole camera roll.
        if (store.photosCopiedTo == 0L) store.photosCopiedTo = System.currentTimeMillis() / 1000
        var copied = 0
        val columns = arrayOf(MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.DATE_ADDED)
        runCatching {
            context.contentResolver.query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, columns,
                "${MediaStore.Images.Media.DATE_ADDED} > ?", arrayOf(store.photosCopiedTo.toString()),
                "${MediaStore.Images.Media.DATE_ADDED} ASC")?.use { found ->
                while (found.moveToNext() && copied < batch) {
                    val uri = ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, found.getLong(0))
                    val reply = client.upload(found.getString(1) ?: "photo.jpg", UriBody(context, uri), "photos")
                    if (reply?.optBoolean("ok") != true) break
                    store.photosCopiedTo = found.getLong(2)
                    copied++
                }
            }
        }
        return copied
    }
}
