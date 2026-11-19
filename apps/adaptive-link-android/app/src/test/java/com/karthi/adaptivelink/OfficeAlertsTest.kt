package com.karthi.adaptivelink

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Where a tapped Agent Office notification leads: a problem to its inbox item, finished work to the task. */
class OfficeAlertsTest {
    private fun note(priority: String, inbox: Long = 0, task: Long = 0, mission: Long = 0) = JSONObject()
        .put("priority", priority).put("inbox_id", inbox).put("task_id", task).put("mission_id", mission)

    @Test fun problemsOpenTheirInboxItem() {
        assertEquals("inbox:5", OfficeAlerts.routeOf(note("high", inbox = 5, task = 12)))
        assertEquals("inbox:7", OfficeAlerts.routeOf(note("critical", inbox = 7)))
    }

    @Test fun finishedWorkOpensTheWork() {
        assertEquals("task:12", OfficeAlerts.routeOf(note("normal", task = 12, mission = 3)))
        assertEquals("mission:3", OfficeAlerts.routeOf(note("normal", mission = 3)))
    }

    @Test fun anythingElseOpensTheInbox() {
        assertEquals("inbox", OfficeAlerts.routeOf(note("normal")))
        assertEquals("inbox", OfficeAlerts.routeOf(JSONObject().put("priority", "high").put("task_id", JSONObject.NULL)))
    }

    @Test fun reportsOpenTheReport() {
        assertEquals("report:4", OfficeAlerts.routeOf(note("normal").put("report_id", 4)))
    }

    @Test fun reportMarkdownBecomesBlocks() {
        val blocks = reportBlocks("# Morning standup — 10:00\n\n*window*\n\n## Blockers\n\n- **Maya**: none\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
        assertEquals(listOf("h1", "note", "h2", "line", "table"), blocks.map { it.first })
        assertEquals("• Maya: none", blocks[3].second)
        assertEquals("A  B\n1  2", blocks[4].second)
    }
}
