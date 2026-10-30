package com.karthi.adaptivelink

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class UsageStateTest {
    private fun sample() = JSONObject("""{"ok":true,"codex":{"stale":false,"windows":[{"label":"5h","used":26.5},{"label":"Weekly","used":63}]},"claude":{"stale":true,"windows":[]},"gemini":{"stale":false,"windows":[{"label":"24h","used":18}]}}""")
    @Test fun errorsAndPartialPayloadsAreNotLiveMeasurements() {
        assertFalse(UsageState.valid(null))
        assertFalse(UsageState.valid(JSONObject("""{"error":"HTTP 404"}""")))
        assertFalse(UsageState.valid(JSONObject("""{"ok":true,"codex":{}}""")))
        assertFalse(UsageState.valid(sample().put("ok", false)))
        assertTrue(UsageState.valid(sample()))
    }
    @Test fun missingAndExpiredWindowsNeverAppearAsZeroUsage() {
        val sample = sample()
        assertNull(UsageState.percent(sample, "claude", false))
        assertNull(UsageState.percent(sample, "gemini", true))
        sample.getJSONObject("codex").getJSONArray("windows").getJSONObject(0).put("expired", true)
        assertNull(UsageState.percent(sample, "codex", false))
        assertEquals(63.0, UsageState.percent(sample, "codex", true)!!, .01)
    }
    @Test fun currentWindowDoesNotMislabelGeminisDailyLimitAsFiveHours() {
        assertEquals("24h", UsageState.window(sample(), "gemini", false)!!.getString("label"))
        assertEquals(18.0, UsageState.percent(sample(), "gemini", false)!!, .01)
        assertTrue(UsageState.stale(sample()))
    }
    @Test fun invalidNumbersAreIgnoredAndPercentagesAreBounded() {
        val sample = sample()
        val row = sample.getJSONObject("codex").getJSONArray("windows").getJSONObject(0)
        row.put("used", "NaN")
        assertNull(UsageState.percent(sample, "codex", false))
        row.put("used", 120)
        assertEquals(100.0, UsageState.percent(sample, "codex", false)!!, .01)
        row.put("used", JSONObject.NULL)
        assertNull(UsageState.percent(sample, "codex", false))
    }
}
