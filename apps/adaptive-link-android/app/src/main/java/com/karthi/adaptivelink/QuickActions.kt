package com.karthi.adaptivelink

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.RemoteViews
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Things done to the computer with one tap, without opening the app: the
 * home-screen widget and the quick-settings tiles.
 *
 * Only what is harmless to do by accident is here - locking the computer,
 * what is playing, the volume, focus. Nothing that unlocks it, runs a
 * command, reads a file or turns it off: those stay behind the app's own
 * lock. Each goes over the same link as the app, and says in a word how it
 * went.
 */
object QuickActions {
    const val ACTION = "com.karthi.adaptivelink.QUICK"
    const val EXTRA = "what"
    val NAMES = listOf("lock", "play-pause", "next", "mute", "focus")

    /** Do one of them. Returns what to say. */
    suspend fun run(context: Context, what: String): String {
        val client = Link.client(context) ?: return "Not paired with a computer"
        return withTimeoutOrNull(15_000) {
            if (client.host == null && client.connect() == null) return@withTimeoutOrNull "Cannot reach ${client.computer.name}"
            val reply = when (what) {
                "lock" -> client.post("/v1/power", JSONObject().put("action", "lock"))
                "play-pause", "next" -> client.post("/v1/media", JSONObject().put("action", what))
                "mute" -> client.post("/v1/volume", JSONObject().put("action", "mute"))
                "focus" -> {
                    val on = client.get("/v1/desktop")?.optBoolean("focus") ?: false
                    client.post("/v1/desktop", JSONObject().put("action", "focus").put("value", if (on) "off" else "on"))
                        ?.also { it.put("said", if (on) "Focus off" else "Focus on") }
                }
                else -> return@withTimeoutOrNull "Unknown"
            }
            when {
                reply == null -> "Cannot reach ${client.computer.name}"
                reply.optString("error").isNotEmpty() -> reply.optString("error")
                !reply.optBoolean("ok", true) -> if (what == "play-pause" || what == "next") "Nothing is playing" else "It did not work"
                else -> reply.optString("said").ifBlank { DONE[what] ?: "Done" }
            }
        } ?: "The computer did not answer"
    }

    private val DONE = mapOf("lock" to "Locked", "play-pause" to "Play / pause", "next" to "Next", "mute" to "Mute")

    fun intent(context: Context, what: String): PendingIntent = PendingIntent.getBroadcast(
        context, NAMES.indexOf(what), Intent(context, QuickReceiver::class.java).setAction(ACTION).putExtra(EXTRA, what),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
}

/** A tap on the widget arrives here. */
class QuickReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val what = intent.getStringExtra(QuickActions.EXTRA)
        if (intent.action != QuickActions.ACTION || what !in QuickActions.NAMES) return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            val said = runCatching { QuickActions.run(context.applicationContext, what!!) }.getOrDefault("It did not work")
            withContext(Dispatchers.Main) { Toast.makeText(context.applicationContext, said, Toast.LENGTH_SHORT).show() }
            pending.finish()
        }
    }
}

class LinkWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        val views = RemoteViews(context.packageName, R.layout.widget)
        views.setTextViewText(R.id.widget_title, Store(context).computer?.name ?: "Adaptive Link - not paired")
        mapOf(R.id.widget_lock to "lock", R.id.widget_play_pause to "play-pause", R.id.widget_next to "next",
            R.id.widget_mute to "mute", R.id.widget_focus to "focus",
        ).forEach { (view, what) -> views.setOnClickPendingIntent(view, QuickActions.intent(context, what)) }
        views.setOnClickPendingIntent(R.id.widget_title, PendingIntent.getActivity(
            context, 99, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
        ids.forEach { manager.updateAppWidget(it, views) }
    }

    companion object {
        /** Show the computer's name on the widget as it is now (paired, unpaired). */
        fun refresh(context: Context) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, LinkWidget::class.java))
            if (ids.isNotEmpty()) LinkWidget().onUpdate(context, manager, ids)
        }
    }
}

/** A quick-settings tile that does one of the quick actions. */
abstract class QuickTile(private val what: String) : TileService() {
    override fun onStartListening() {
        qsTile?.apply {
            state = if (Store(this@QuickTile).computer == null) Tile.STATE_UNAVAILABLE else Tile.STATE_INACTIVE
            updateTile()
        }
    }

    override fun onClick() {
        val context = applicationContext
        CoroutineScope(Dispatchers.IO).launch {
            val said = runCatching { QuickActions.run(context, what) }.getOrDefault("It did not work")
            withContext(Dispatchers.Main) { Toast.makeText(context, said, Toast.LENGTH_SHORT).show() }
        }
    }
}

class LockTile : QuickTile("lock")
class PlayPauseTile : QuickTile("play-pause")
class FocusTile : QuickTile("focus")
