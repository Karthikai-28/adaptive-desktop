package com.karthi.adaptivelink

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

/**
 * The Agent Office's alerts on this phone: a failed or blocked task, an approval waiting, a quota stop,
 * finished work (grouped and quiet).
 *
 * The office numbers every notification and keeps them all (services/agent-office office/journal.py). The
 * link hands a new one to EventsService as kind "office" the moment it is made; that is only a nudge.
 * What is shown always comes from the office's own list, fetched after the last one this phone showed, in
 * order, so a phone that was away or out of reach misses nothing and never shows one twice. What was shown
 * is confirmed back to the office (its record of what is still undelivered) and the last hundred are kept
 * here, for the Office page's inbox while the computer can't be reached.
 *
 * Acknowledging from a notification only says "I'm on it": the office never treats it as approval.
 */
object OfficeAlerts {
    const val CHANNEL = "office"
    const val CHANNEL_DIGEST = "office-digest"
    const val CHANNEL_REPORTS = "office-reports"
    const val EXTRA_ROUTE = "com.karthi.adaptivelink.OFFICE_ROUTE"
    const val EXTRA_NOTIFICATION = "com.karthi.adaptivelink.OFFICE_NOTIFICATION"
    const val ACTION_ACK = "com.karthi.adaptivelink.OFFICE_ACK"
    const val ACTION_READ = "com.karthi.adaptivelink.OFFICE_READ"
    private const val GROUP_DONE = "office.done"
    private const val SUMMARY_ID = 2_999_999
    private const val KEEP = 100
    private const val PAGE = 100

    private val lock = Mutex()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** What a tapped notification asked the Office page to open: "task:12", "mission:3" or "inbox:5". */
    @Volatile var pendingRoute: String? = null

    fun channels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Agent Office: problems and approvals",
            NotificationManager.IMPORTANCE_HIGH))
        manager.createNotificationChannel(NotificationChannel(CHANNEL_DIGEST, "Agent Office: finished work",
            NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel(CHANNEL_REPORTS, "Agent Office: standup and evening summary",
            NotificationManager.IMPORTANCE_DEFAULT))
    }

    /** The link says there is something new: fetch it from the office, in order. */
    fun nudged(context: Context, client: LinkClient) {
        scope.launch { catchUp(context, client) }
    }

    /** Show everything the office has after the last one shown here, oldest first, and confirm it. */
    suspend fun catchUp(context: Context, client: LinkClient) = lock.withLock {
        val store = Store(context)
        if (!store.officeAlerts) return@withLock
        var after = store.lastOfficeNotification
        var shown = false
        for (page in 0 until 5) {
            val got = client.get("/v1/office/api/notifications?after=$after&limit=$PAGE&channel=link") ?: return@withLock
            if (got.has("error") || got.has("detail") || !got.has("head")) return@withLock
            val head = got.optLong("head")
            if (after == 0L || head < after) {
                // First time, or the office's records were started again: begin from now. Older alerts are in
                // the Office page's inbox; a flood of them on a new phone would help no one.
                store.lastOfficeNotification = head
                client.post("/v1/office/api/notifications/delivered", JSONObject().put("channel", "link").put("through", head))
                return@withLock
            }
            val items = got.optJSONArray("notifications") ?: JSONArray()
            for (i in 0 until items.length()) {
                val n = items.optJSONObject(i) ?: continue
                show(context, n)
                remember(context, n)
                after = n.optLong("id")
                store.lastOfficeNotification = after
                shown = true
            }
            if (items.length() < PAGE) break
        }
        if (shown) client.post("/v1/office/api/notifications/delivered", JSONObject().put("channel", "link").put("through", after))
    }

    private fun show(context: Context, n: JSONObject) {
        if (!EventsService.mayNotify(context)) return
        channels(context)
        val id = n.optLong("id")
        val priority = n.str("priority", "normal")
        val urgent = priority != "normal"
        val report = n.optLong("report_id") > 0
        val title = n.str("title").ifBlank { "Agent Office" }
        val text = n.str("text")
        val route = routeOf(n)
        val open = PendingIntent.getActivity(context, (id % Int.MAX_VALUE).toInt(),
            Intent(context, MainActivity::class.java)
                .putExtra(MainActivity.EXTRA_PAGE, Page.Office.name)
                .putExtra(EXTRA_ROUTE, route)
                .putExtra(EXTRA_NOTIFICATION, id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val builder = NotificationCompat.Builder(context, if (urgent) CHANNEL else if (report) CHANNEL_REPORTS else CHANNEL_DIGEST)
            .setSmallIcon(R.drawable.ic_launcher)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setSubText("Agent Office")
            .setWhen((n.optDouble("created_at", 0.0) * 1000).toLong())
            .setAutoCancel(true)
            .setContentIntent(open)
            .setDeleteIntent(receiver(context, ACTION_READ, id, 0))
            .setPriority(when (priority) {
                "critical" -> NotificationCompat.PRIORITY_MAX
                "high" -> NotificationCompat.PRIORITY_HIGH
                else -> NotificationCompat.PRIORITY_LOW
            })
        val inbox = n.optLong("inbox_id")
        if (urgent && inbox > 0) {
            // "I'm on it" - marks the inbox item in progress. Approving needs the operator key on the computer.
            builder.addAction(0, "Acknowledge", receiver(context, ACTION_ACK, id, inbox))
        }
        if (!urgent && !report) builder.setGroup(GROUP_DONE).setSilent(true)
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.notify(notificationId(id), builder.build())
        if (!urgent && !report) {
            manager.notify(SUMMARY_ID, NotificationCompat.Builder(context, CHANNEL_DIGEST)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle("Agent Office")
                .setContentText("Finished work")
                .setGroup(GROUP_DONE).setGroupSummary(true).setSilent(true).setAutoCancel(true)
                .build())
        }
    }

    private fun notificationId(id: Long) = 3_000_000 + (id % 1_000_000).toInt()

    private fun receiver(context: Context, action: String, notification: Long, inbox: Long): PendingIntent =
        PendingIntent.getBroadcast(context, ((notification * 2 + if (action == ACTION_ACK) 1 else 0) % Int.MAX_VALUE).toInt(),
            Intent(context, OfficeAlertReceiver::class.java).setAction(action)
                .putExtra(EXTRA_NOTIFICATION, notification).putExtra("inbox", inbox),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun routeOf(n: JSONObject): String = when {
        n.optLong("report_id") > 0 -> "report:${n.optLong("report_id")}"
        n.optLong("inbox_id") > 0 && n.str("priority") != "normal" -> "inbox:${n.optLong("inbox_id")}"
        n.optLong("task_id") > 0 -> "task:${n.optLong("task_id")}"
        n.optLong("mission_id") > 0 -> "mission:${n.optLong("mission_id")}"
        else -> "inbox"
    }

    /** A notification was tapped: remember where it leads and tell the office it was read. */
    fun opened(context: Context, intent: Intent?) {
        val route = intent?.getStringExtra(EXTRA_ROUTE) ?: return
        val id = intent.getLongExtra(EXTRA_NOTIFICATION, 0)
        intent.removeExtra(EXTRA_ROUTE)
        pendingRoute = route
        if (id > 0) markRead(context, id)
    }

    fun markRead(context: Context, id: Long) {
        scope.launch {
            Link.client(context)?.post("/v1/office/api/notifications/read", JSONObject().put("ids", JSONArray().put(id)))
        }
    }

    fun acknowledge(context: Context, notification: Long, inbox: Long, done: () -> Unit = {}) {
        scope.launch {
            val reply = Link.client(context)?.post("/v1/office/api/inbox/$inbox/ack", JSONObject().put("note", "from the phone"))
            Link.client(context)?.post("/v1/office/api/notifications/read", JSONObject().put("ids", JSONArray().put(notification)))
            val ok = reply != null && !reply.has("detail") && !reply.has("error")
            context.getSystemService(NotificationManager::class.java).cancel(notificationId(notification))
            if (!ok) {
                context.getSystemService(NotificationManager::class.java).notify(notificationId(notification),
                    NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.drawable.ic_launcher)
                        .setContentTitle("Couldn't acknowledge").setContentText("The computer didn't answer; try from the Office page.")
                        .setAutoCancel(true).build())
            }
            done()
        }
    }

    // ------------------------------------------------------------ kept on the phone

    private fun remember(context: Context, n: JSONObject) {
        val prefs = context.getSharedPreferences("office_alerts", 0)
        val list = runCatching { JSONArray(prefs.getString("recent", "[]")) }.getOrElse { JSONArray() }
        val out = JSONArray()
        for (i in maxOf(0, list.length() - KEEP + 1) until list.length()) out.put(list.get(i))
        out.put(n)
        prefs.edit().putString("recent", out.toString()).apply()
    }

    /** The last alerts shown here, newest first. */
    fun recent(context: Context): List<JSONObject> {
        val list = runCatching { JSONArray(context.getSharedPreferences("office_alerts", 0).getString("recent", "[]")) }
            .getOrElse { JSONArray() }
        return (0 until list.length()).mapNotNull { list.optJSONObject(it) }.reversed()
    }
}

/** The buttons on an office notification: Acknowledge, and a swipe-away that marks it read. */
class OfficeAlertReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val notification = intent.getLongExtra(OfficeAlerts.EXTRA_NOTIFICATION, 0)
        when (intent.action) {
            OfficeAlerts.ACTION_ACK -> {
                val pending = goAsync()
                OfficeAlerts.acknowledge(context, notification, intent.getLongExtra("inbox", 0)) { pending.finish() }
            }
            OfficeAlerts.ACTION_READ -> if (notification > 0) OfficeAlerts.markRead(context, notification)
        }
    }
}
