package com.karthi.adaptivelink

import org.json.JSONObject

/**
 * The Agent Office's status words and figures on the phone: the same as the desktop's Virtual Office and
 * Command Center (services/agent-office/static/views.js) and the office's own rule (office/activity.py
 * desk_state). Pure, so OfficeDeskTest checks it.
 *
 * Progress is only what the office really knows: a mission's tasks done out of its tasks so far, how long a run
 * has gone and the actions it recorded. A single task has no known share done, so there is no percentage.
 */
internal object OfficeDesk {
    val STATES = listOf("working", "blocked", "error", "paused", "idle")

    fun word(state: String) = when (state) {
        "working" -> "Working"
        "blocked" -> "Blocked"
        "error" -> "Error"
        "paused" -> "Paused"
        else -> "Idle"
    }

    /** The status word for an agent the overview does not cover (the manager), from its live status. */
    fun fromStatus(status: String, inMeeting: Boolean = false): Pair<String, String> = when {
        status == "paused" -> "paused" to "Paused"
        status == "quota" -> "blocked" to "Waiting for quota"
        status == "working" -> "working" to "Working"
        status == "thinking" -> "working" to "Replying"
        inMeeting -> "working" to "In a meeting"
        else -> "idle" to "Idle"
    }

    fun duration(seconds: Double): String {
        val s = if (seconds.isNaN() || seconds < 0) 0L else Math.round(seconds)
        if (s < 60) return "${s}s"
        val m = s / 60
        if (m < 60) return "${m}m ${(s % 60).toString().padStart(2, '0')}s"
        return "${m / 60}h ${(m % 60).toString().padStart(2, '0')}m"
    }

    private fun JSONObject.num(key: String): Double = if (!has(key) || isNull(key)) 0.0 else optDouble(key, 0.0)

    /** How long this run has gone, `elapsed` seconds after the overview was read; 0 when nothing runs. */
    fun runningFor(desk: JSONObject, elapsed: Double): Double =
        if (desk.num("running_since") > 0) desk.num("running_s") + elapsed.coerceAtLeast(0.0) else 0.0

    /** "running 12m 03s · 14 actions · 2 queued": time and counts. */
    fun runLine(desk: JSONObject, elapsed: Double): String {
        val queued = desk.optInt("queued_count")
        val task = desk.optJSONObject("task")
            ?: return if (queued > 0) "$queued queued" else "${duration(desk.num("active_24h_s"))} active in 24 h"
        val parts = mutableListOf<String>()
        val run = runningFor(desk, elapsed)
        parts += if (run > 0) "running ${duration(run)}" else if (task.str("status") == "queued") "waiting its turn" else task.str("status")
        val actions = desk.optInt("actions")
        if (actions > 0) parts += "$actions action${if (actions == 1) "" else "s"}"
        if (queued > 0) parts += "$queued queued"
        return parts.joinToString(" · ")
    }

    /** "2 of 5 tasks done · 1 failed", or "No tasks yet". */
    fun missionLine(m: JSONObject): String {
        val total = m.optInt("total_tasks")
        if (total <= 0) return "No tasks yet"
        val failed = m.optInt("failed_tasks")
        return "${m.optInt("done_tasks")} of $total task${if (total == 1) "" else "s"} done" + if (failed > 0) " · $failed failed" else ""
    }

    /** The share of a mission's tasks done, for its bar; null when it has none yet. */
    fun missionFraction(m: JSONObject): Float? {
        val total = m.optInt("total_tasks")
        return if (total <= 0) null else (m.optInt("done_tasks").toFloat() / total).coerceIn(0f, 1f)
    }

    /** Today's figures for the Team tab: (value, label) - the same as the Command Center's. */
    fun today(o: JSONObject): List<Pair<String, String>> {
        val c = o.optJSONObject("counts") ?: JSONObject()
        val inbox = o.optJSONObject("inbox") ?: JSONObject()
        return listOf(
            "${c.optInt("active")}/${c.optInt("agents")}" to "working",
            "${c.optInt("done_today")}" to "done today",
            "${c.optInt("failed_today")}" to "failed today",
            "${inbox.optInt("NEEDS_ATTENTION")}" to "need you",
        )
    }
}
