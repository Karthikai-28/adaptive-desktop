package com.karthi.adaptivelink

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Shows this phone's notifications on the paired computer.
 *
 * Android only runs this after the owner turns it on in Settings
 * (Notification access), and the app's own switch has to be on as well. It
 * sends the app name, title and text of each notification over the same
 * mutually-authenticated link as everything else, and tells the computer when
 * one is dismissed. If the computer cannot be reached the notification is
 * simply not sent; nothing is queued or stored.
 */
class NotificationRelay : NotificationListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun wanted(sbn: StatusBarNotification): Boolean {
        if (!Store(this).relayNotifications || sbn.packageName == packageName) return false
        val flags = sbn.notification.flags
        // Not the permanent ones (music controls, "app is running"), and not
        // the header Android adds above a group of notifications.
        return flags and Notification.FLAG_ONGOING_EVENT == 0 &&
            flags and Notification.FLAG_GROUP_SUMMARY == 0
    }

    private fun appName(packageName: String): String = runCatching {
        packageManager.getApplicationLabel(packageManager.getApplicationInfo(packageName, 0)).toString()
    }.getOrDefault(packageName)

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (!wanted(sbn)) return
        val extras = sbn.notification.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
            ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString().orEmpty()
        if (title.isBlank() && text.isBlank()) return
        val body = JSONObject().put("key", sbn.key).put("app", appName(sbn.packageName))
            .put("title", title).put("text", text)
        send("/v1/notify", body)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        if (!Store(this).relayNotifications || sbn.packageName == packageName) return
        send("/v1/notify/dismiss", JSONObject().put("key", sbn.key))
    }

    private fun send(path: String, body: JSONObject) {
        val client = Link.client(this) ?: return
        scope.launch {
            if (client.host == null && client.connect() == null) return@launch
            if (client.post(path, body) == null) {
                // The address may have changed (left home, joined Tailscale).
                if (client.connect() != null) client.post(path, body)
            }
        }
    }
}
