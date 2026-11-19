package com.karthi.adaptivelink

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/** The phone says what the desktop says (static/views.js, office/activity.py): the same words, times and counts. */
class OfficeDeskTest {
    private fun desk(vararg pairs: Pair<String, Any?>) = JSONObject().apply { pairs.forEach { (k, v) -> put(k, v ?: JSONObject.NULL) } }

    @Test fun theFiveStatusWords() {
        assertEquals(listOf("Working", "Blocked", "Error", "Paused", "Idle"), OfficeDesk.STATES.map(OfficeDesk::word))
        assertEquals("working" to "Replying", OfficeDesk.fromStatus("thinking"))
        assertEquals("blocked" to "Waiting for quota", OfficeDesk.fromStatus("quota"))
        assertEquals("working" to "In a meeting", OfficeDesk.fromStatus("idle", inMeeting = true))
        assertEquals("idle" to "Idle", OfficeDesk.fromStatus("idle"))
    }

    @Test fun durationsMatchTheDesktop() {
        assertEquals("5s", OfficeDesk.duration(5.0))
        assertEquals("2m 05s", OfficeDesk.duration(125.0))
        assertEquals("1h 02m", OfficeDesk.duration(3725.0))
        assertEquals("0s", OfficeDesk.duration(Double.NaN))
    }

    @Test fun aRunIsTimeAndCountsNeverAShareDone() {
        val d = desk("task" to JSONObject().put("id", 3).put("status", "running"), "running_since" to 1000.0, "running_s" to 60.0,
            "actions" to 3, "queued_count" to 2)
        assertEquals(70.0, OfficeDesk.runningFor(d, 10.0), 0.001)            // counts on from when the overview was read
        val line = OfficeDesk.runLine(d, 10.0)
        assertEquals("running 1m 10s · 3 actions · 2 queued", line)
        assertFalse(line.contains("%"))
        val idle = desk("task" to null, "running_since" to null, "queued_count" to 0, "active_24h_s" to 125.0)
        assertEquals(0.0, OfficeDesk.runningFor(idle, 30.0), 0.0)
        assertEquals("2m 05s active in 24 h", OfficeDesk.runLine(idle, 0.0))
    }

    @Test fun missionProgressIsTasksDone() {
        val m = JSONObject().put("total_tasks", 4).put("done_tasks", 1).put("failed_tasks", 1)
        assertEquals("1 of 4 tasks done · 1 failed", OfficeDesk.missionLine(m))
        assertEquals(0.25f, OfficeDesk.missionFraction(m)!!, 0.0001f)
        assertEquals("No tasks yet", OfficeDesk.missionLine(JSONObject().put("total_tasks", 0)))
        assertNull(OfficeDesk.missionFraction(JSONObject()))
    }

    @Test fun todaysFiguresAreTheCommandCenters() {
        val o = JSONObject().put("counts", JSONObject().put("active", 2).put("agents", 8).put("done_today", 7).put("failed_today", 1))
            .put("inbox", JSONObject().put("NEEDS_ATTENTION", 3))
        assertEquals(listOf("2/8" to "working", "7" to "done today", "1" to "failed today", "3" to "need you"), OfficeDesk.today(o))
    }
}
