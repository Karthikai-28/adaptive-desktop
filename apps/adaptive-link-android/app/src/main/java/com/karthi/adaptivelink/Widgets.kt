package com.karthi.adaptivelink

import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobService
import android.app.job.JobScheduler
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.view.View
import android.widget.RemoteViews
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * The home-screen widgets beyond the row of quick actions (QuickActions.kt):
 *
 *  - Status: whether the computer can be reached, its battery, volume and
 *    project. A tap looks again.
 *  - Media: what it is playing, with previous, play and next.
 *  - Controls: six of the owner's own buttons from the Controls screen.
 *  - AI usage: Codex, Claude and Gemini plan limits in a compact phone card.
 *
 * A widget cannot keep a connection, so each asks the computer when it is
 * tapped (and the status one every half hour, which is as often as Android
 * allows) and shows what it was told. They go over the same link as the app.
 */

/** What every widget here shares: being drawn again by its own kind of tap. */
abstract class LinkWidgetBase : AppWidgetProvider() {
    /** The widget as it should look now; `client` is null when the phone is paired with nothing. */
    abstract suspend fun draw(context: Context, client: LinkClient?): RemoteViews

    /** Something on the widget was tapped: do it, and say a word if there is one to say. */
    open suspend fun tapped(context: Context, client: LinkClient, what: String): String? = null

    private fun refresh(context: Context, what: String?) {
        WidgetRefreshJob.schedule(context, javaClass.simpleName, what)
    }

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) = refresh(context, null)

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == TAP) refresh(context, intent.getStringExtra(WHAT)) else super.onReceive(context, intent)
    }

    /** A tap on part of the widget, delivered back to this widget's own class. */
    protected fun tap(context: Context, what: String): PendingIntent = PendingIntent.getBroadcast(
        context, what.hashCode(), Intent(context, javaClass).setAction(TAP).putExtra(WHAT, what),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    protected fun open(context: Context): PendingIntent = PendingIntent.getActivity(
        context, 98, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)

    companion object {
        const val TAP = "com.karthi.adaptivelink.WIDGET_TAP"
        const val WHAT = "what"

        /** Draw every widget again: the computer changed, or the owner's buttons did. */
        fun refreshAll(context: Context) {
            for (kind in listOf(StatusWidget::class.java, MediaWidget::class.java, ControlsWidget::class.java,
                UsageWidget::class.java, AppsWidget::class.java)) {
                val ids = AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, kind))
                if (ids.isNotEmpty()) context.sendBroadcast(Intent(context, kind).setAction(TAP))
            }
        }
    }
}

class UsageWidget : LinkWidgetBase() {

    override fun onEnabled(context: Context) {
        super.onEnabled(context)
        UsageRefreshJob.schedule(context)
    }

    override fun onDisabled(context: Context) {
        UsageRefreshJob.cancel(context)
        super.onDisabled(context)
    }

    companion object {
        /** Refresh this widget while the phone app is already polling live usage. */
        fun refresh(context: Context) {
            val ids = AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, UsageWidget::class.java))
            if (ids.isNotEmpty()) context.sendBroadcast(Intent(context, UsageWidget::class.java)
                .setAction(LinkWidgetBase.TAP).putExtra(LinkWidgetBase.WHAT, "look"))
        }
    }

    private fun line(usage: JSONObject?, provider: String, weekly: Boolean): Pair<String, Int> {
        val used = UsageState.percent(usage, provider, weekly)?.toInt()
            ?: return "—" to 0xFF8E8E93.toInt()
        val colour = when {
            used >= 95 -> 0xFFFF453A.toInt()
            used >= 80 -> 0xFFFF9F0A.toInt()
            else -> 0xFF0A84FF.toInt()
        }
        return "$used%" to colour
    }

    override suspend fun draw(context: Context, client: LinkClient?): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_usage)
        val computer = Store(context).computer
        val cache = computer?.let { UsageCache(context, it.fingerprint) }
        val fresh = client?.get("/v1/ai-usage")?.takeIf { UsageState.valid(it) }
        if (fresh != null) cache?.save(fresh)
        val usage = fresh ?: cache?.read()
        listOf(
            Triple("codex", R.id.usage_codex_name, R.id.usage_codex_five),
            Triple("claude", R.id.usage_claude_name, R.id.usage_claude_five),
            Triple("gemini", R.id.usage_gemini_name, R.id.usage_gemini_five),
        ).forEach { (provider, name, five) ->
            val weekly = when (provider) { "codex" -> R.id.usage_codex_week; "claude" -> R.id.usage_claude_week; else -> R.id.usage_gemini_week }
            val (fiveText, fiveColour) = line(usage, provider, false)
            val (weekText, weekColour) = line(usage, provider, true)
            views.setTextViewText(five, fiveText)
            views.setTextColor(five, fiveColour)
            views.setTextViewText(weekly, weekText)
            views.setTextColor(weekly, weekColour)
            views.setOnClickPendingIntent(name, open(context))
        }
        views.setTextViewText(R.id.usage_state, when {
            fresh != null && !UsageState.stale(fresh) -> "Updated now"
            fresh != null -> "Some data is old"
            usage != null -> "Saved · tap to retry"
            Store(context).computer == null -> "Open Adaptive Link to pair"
            else -> "Tap to check the computer"
        })
        views.setOnClickPendingIntent(R.id.usage_root, tap(context, "look"))
        views.setOnClickPendingIntent(R.id.usage_title, open(context))
        views.setOnClickPendingIntent(R.id.usage_refresh, tap(context, "look"))
        views.setOnClickPendingIntent(R.id.usage_reconnect, tap(context, "reconnect"))
        return views
    }
}

/** Android widgets are otherwise refreshed at most every 30 minutes. */
class UsageRefreshJob : JobService() {
    private var task: kotlinx.coroutines.Job? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onStartJob(params: JobParameters): Boolean {
        task = scope.launch {
            try {
                val manager = AppWidgetManager.getInstance(this@UsageRefreshJob)
                val ids = manager.getAppWidgetIds(ComponentName(this@UsageRefreshJob, UsageWidget::class.java))
                if (ids.isNotEmpty()) {
                    val client = Link.client(this@UsageRefreshJob)
                    val reached = client != null && (withTimeoutOrNull(12_000) { client.host != null || client.connect() != null } ?: false)
                    val views = UsageWidget().draw(this@UsageRefreshJob, client?.takeIf { reached || it.host != null })
                    manager.updateAppWidget(ids, views)
                }
            } catch (cancelled: kotlinx.coroutines.CancellationException) { throw cancelled
            } catch (_: Exception) {
                // The next scheduled run will retry. Never crash the process for advisory data.
            } finally { if (kotlinx.coroutines.currentCoroutineContext().isActive) jobFinished(params, false) }
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean { task?.cancel(); return true }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val JOB_ID = 478231
        fun schedule(context: Context) {
            if (AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, UsageWidget::class.java)).isEmpty()) return
            val scheduler = context.getSystemService(JobScheduler::class.java)
            val info = JobInfo.Builder(JOB_ID, ComponentName(context, UsageRefreshJob::class.java))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .build()
            scheduler.schedule(info)
        }
        fun cancel(context: Context) {
            context.getSystemService(JobScheduler::class.java).cancel(JOB_ID)
        }
    }
}

class StatusWidget : LinkWidgetBase() {
    override suspend fun draw(context: Context, client: LinkClient?): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_status)
        val computer = Store(context).computer
        views.setTextViewText(R.id.status_name, computer?.name ?: "Adaptive Link")
        val status = client?.get("/v1/status")?.takeIf { !it.has("error") && it.has("capabilities") }
        when {
            computer == null -> {
                views.setTextViewText(R.id.status_line, "Not paired")
                views.setTextViewText(R.id.status_detail, "Open the app to pair with a computer")
            }
            status == null -> {
                views.setTextViewText(R.id.status_line, "Cannot be reached")
                views.setTextViewText(R.id.status_detail, "Tap to look again")
            }
            else -> {
                views.setTextViewText(R.id.status_line, "Connected" + if (status.optBoolean("locked")) " · locked" else "")
                views.setTextViewText(R.id.status_detail, Protocol.statusLine(status))
            }
        }
        views.setOnClickPendingIntent(R.id.status_root, tap(context, "look"))
        views.setOnClickPendingIntent(R.id.status_name, open(context))
        return views
    }
}

class MediaWidget : LinkWidgetBase() {
    override suspend fun draw(context: Context, client: LinkClient?): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_media)
        val player = client?.get("/v1/media")?.optJSONArray("players")?.optJSONObject(0)
        views.setTextViewText(R.id.media_title, when {
            client == null -> "The computer cannot be reached"
            player == null -> "Nothing is playing"
            else -> player.optString("title").ifBlank { player.optString("name") }
        })
        views.setTextViewText(R.id.media_artist, player?.optString("artist").orEmpty())
        views.setTextViewText(R.id.media_play, if (player?.optString("status") == "Playing") "Pause" else "Play")
        views.setOnClickPendingIntent(R.id.media_previous, tap(context, "previous"))
        views.setOnClickPendingIntent(R.id.media_play, tap(context, "play-pause"))
        views.setOnClickPendingIntent(R.id.media_next, tap(context, "next"))
        views.setOnClickPendingIntent(R.id.media_title, tap(context, "look"))
        return views
    }

    override suspend fun tapped(context: Context, client: LinkClient, what: String): String? {
        if (what == "look") return null
        val reply = client.post("/v1/media", JSONObject().put("action", what))
        return if (reply?.optBoolean("ok") == true) null else "Nothing is playing"
    }
}

class ControlsWidget : LinkWidgetBase() {
    private val slots = listOf(R.id.control_0, R.id.control_1, R.id.control_2, R.id.control_3, R.id.control_4, R.id.control_5)

    override suspend fun draw(context: Context, client: LinkClient?): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_controls)
        val store = Store(context)
        val controls = store.controls.take(slots.size)
        views.setTextViewText(R.id.controls_title, when {
            store.computer == null -> "Not paired"
            controls.isEmpty() -> "Add buttons in the app's Controls screen"
            else -> store.computer?.name.orEmpty()
        })
        slots.forEachIndexed { index, slot ->
            val control = controls.getOrNull(index)
            views.setViewVisibility(slot, if (control == null) View.INVISIBLE else View.VISIBLE)
            views.setTextViewText(slot, control?.label.orEmpty())
            // Named by what it says, not where it sits: buttons can be moved while the widget is on the screen.
            if (control != null) views.setOnClickPendingIntent(slot, tap(context, "press:${control.label}"))
        }
        views.setOnClickPendingIntent(R.id.controls_title, open(context))
        return views
    }

    override suspend fun tapped(context: Context, client: LinkClient, what: String): String? {
        val control = Store(context).controls.firstOrNull { "press:${it.label}" == what } ?: return null
        return press(context, client, control)
    }
}
