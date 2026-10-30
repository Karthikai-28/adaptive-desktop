package com.karthi.adaptivelink

import android.app.job.*
import android.appwidget.AppWidgetManager
import android.content.*
import android.os.PersistableBundle
import android.widget.Toast
import kotlinx.coroutines.*

/** Network work belongs to a scheduled job, never a short-lived widget broadcast. */
class WidgetRefreshJob : JobService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val tasks = java.util.concurrent.ConcurrentHashMap<Int, Job>()
    override fun onStartJob(params: JobParameters): Boolean {
        val kind = params.extras.getString("kind")
        val widget = provider(kind)
        if (widget == null && kind != "QuickActions") return false
        tasks[params.jobId] = scope.launch {
            try {
                while (isActive) {
                    val work = params.dequeueWork() ?: break
                    if (kind == "QuickActions") {
                        val action = work.intent.getStringExtra(LinkWidgetBase.WHAT)
                        if (action in QuickActions.NAMES) {
                            val message = try { QuickActions.run(this@WidgetRefreshJob, action!!) }
                                catch (cancelled: CancellationException) { throw cancelled }
                                catch (_: Exception) { "Could not send action" }
                            withContext(Dispatchers.Main) { Toast.makeText(this@WidgetRefreshJob, message, Toast.LENGTH_SHORT).show() }
                        }
                        params.completeWork(work)
                        continue
                    }
                    widget!!
                    val manager = AppWidgetManager.getInstance(this@WidgetRefreshJob)
                    val ids = manager.getAppWidgetIds(ComponentName(this@WidgetRefreshJob, widget.javaClass))
                    if (ids.isNotEmpty()) {
                        // First draw cached/offline state. Network failure must not leave an empty widget.
                        manager.updateAppWidget(ids, widget.draw(this@WidgetRefreshJob, null))
                        try {
                            if (widget is AppsWidget) { params.completeWork(work); continue }
                            withTimeout(45_000) {
                                val client = Link.client(this@WidgetRefreshJob)
                                val what = work.intent.getStringExtra(LinkWidgetBase.WHAT)
                                if (what == "reconnect") client?.networkChanged()
                                val reached = client != null && client.connect() != null
                                val said = if (reached && client != null && what != null && what !in listOf("look", "reconnect")) widget.tapped(this@WidgetRefreshJob, client, what)
                                    else if (what != null && what !in listOf("look", "reconnect")) "Computer unavailable. Action was not sent." else null
                                manager.updateAppWidget(ids, widget.draw(this@WidgetRefreshJob, client?.takeIf { reached }))
                                if (said != null) withContext(Dispatchers.Main) { Toast.makeText(this@WidgetRefreshJob, said, Toast.LENGTH_SHORT).show() }
                            }
                        } catch (_: TimeoutCancellationException) {
                            // Keep the already-rendered saved state. Never repeat an uncertain action.
                        } catch (cancelled: CancellationException) { throw cancelled
                        } catch (_: Exception) { /* Keep the cached view, then accept the next manual refresh. */ }
                    }
                    params.completeWork(work)
                }
            } finally {
                tasks.remove(params.jobId)
                if (currentCoroutineContext().isActive) jobFinished(params, false)
            }
        }
        return true
    }
    override fun onStopJob(params: JobParameters): Boolean { tasks.remove(params.jobId)?.cancel(); return false }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
    companion object {
        private val kinds = listOf("StatusWidget", "MediaWidget", "ControlsWidget", "UsageWidget", "AppsWidget", "QuickActions")
        private fun provider(kind: String?): LinkWidgetBase? = when (kind) {
            "StatusWidget" -> StatusWidget(); "MediaWidget" -> MediaWidget()
            "ControlsWidget" -> ControlsWidget(); "UsageWidget" -> UsageWidget(); "AppsWidget" -> AppsWidget(); else -> null
        }
        fun schedule(context: Context, kind: String, what: String?) {
            val index = kinds.indexOf(kind)
            if (index < 0) return
            val info = JobInfo.Builder(478240 + index, ComponentName(context, WidgetRefreshJob::class.java))
                .setExtras(PersistableBundle().apply { putString("kind", kind) }).setOverrideDeadline(0).build()
            context.getSystemService(JobScheduler::class.java).enqueue(info,
                JobWorkItem(Intent().putExtra(LinkWidgetBase.WHAT, what)))
        }
    }
}
