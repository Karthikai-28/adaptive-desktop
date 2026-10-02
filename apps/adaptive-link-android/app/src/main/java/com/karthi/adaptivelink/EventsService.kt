package com.karthi.adaptivelink

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
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
 * Shows on this phone what the computer has to say without being asked: its
 * own notifications, and alerts about the machine (a disk nearly full, a low
 * battery, a command that has finished). The computer's side is
 * services/adaptive-link/alerts.py.
 *
 * It runs only while the owner has one of the two switches on (More), as a
 * service Android shows in the notification shade, because it holds a
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
        val store = Store(this)
        if (store.computer == null || !(store.computerAlerts || store.computerNotifications)) {
            stopSelf()
            return START_NOT_STICKY
        }
        channels(this)
        val shown = NotificationCompat.Builder(this, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle("Listening to ${store.computer?.name}")
            .setContentText("For its alerts and notifications")
            .setOngoing(true)
            .setContentIntent(openApp(this))
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(ONGOING_ID, shown, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(ONGOING_ID, shown)
        }
        // Started again when a switch changes: listen afresh, for what is wanted now.
        listening?.cancel()
        listening = scope.launch { listen() }
        return START_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun listen() {
        var wait = 3_000L
        while (true) {
            val store = Store(this)
            val client = Link.client(this) ?: return
            val kinds = listOfNotNull("alert".takeIf { store.computerAlerts },
                "notification".takeIf { store.computerNotifications }).joinToString(",")
            if (kinds.isEmpty()) return
            if (client.host != null || client.connect() != null) {
                val ended = CompletableDeferred<Unit>()
                val socket = client.socket("/v1/events?after=${store.lastEvent}&kinds=$kinds", object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) { wait = 3_000L }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        runCatching { JSONObject(text) }.getOrNull()?.let { show(it) }
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

    private fun show(event: JSONObject) {
        val store = Store(this)
        val id = event.optLong("id")
        if (id <= store.lastEvent) return
        store.lastEvent = id
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
        ) return
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
        private const val CHANNEL_SERVICE = "listening"
        private const val CHANNEL_ALERTS = "alerts"
        private const val CHANNEL_NOTIFICATIONS = "computer"
        private const val ONGOING_ID = 1

        private fun channels(context: Context) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL_SERVICE, "Listening to the computer",
                NotificationManager.IMPORTANCE_MIN))
            manager.createNotificationChannel(NotificationChannel(CHANNEL_ALERTS, "Alerts about the computer",
                NotificationManager.IMPORTANCE_HIGH))
            manager.createNotificationChannel(NotificationChannel(CHANNEL_NOTIFICATIONS, "The computer's notifications",
                NotificationManager.IMPORTANCE_DEFAULT))
        }

        private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)

        /** Start listening if the owner has asked for it, or stop if they no longer do. */
        fun sync(context: Context) {
            val store = Store(context)
            val wanted = store.computer != null && (store.computerAlerts || store.computerNotifications)
            val intent = Intent(context, EventsService::class.java)
            if (wanted) runCatching { ContextCompat.startForegroundService(context, intent) }
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
