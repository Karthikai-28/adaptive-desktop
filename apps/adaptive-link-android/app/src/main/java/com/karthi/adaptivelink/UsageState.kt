package com.karthi.adaptivelink

import android.content.Context
import org.json.JSONObject

/** Shared parsing keeps the app and RemoteViews honest about stale/missing measurements. */
internal object UsageState {
    val providers = listOf("codex", "claude", "gemini")
    fun valid(value: JSONObject?): Boolean = value != null && !value.has("error") &&
        value.optBoolean("ok", true) && providers.all { value.optJSONObject(it) != null }
    fun window(value: JSONObject?, provider: String, weekly: Boolean): JSONObject? =
        value?.optJSONObject(provider)?.optJSONArray("windows").rows().firstOrNull {
            !it.optBoolean("expired") && it.optString("label").startsWith("Weekly", true) == weekly &&
                it.has("used") && !it.isNull("used") && it.optDouble("used").isFinite()
        }
    fun percent(value: JSONObject?, provider: String, weekly: Boolean): Double? =
        window(value, provider, weekly)?.optDouble("used")?.coerceIn(0.0, 100.0)
    fun stale(value: JSONObject?): Boolean = providers.any { value?.optJSONObject(it)?.optBoolean("stale", true) != false }
}

internal class UsageCache(context: Context, fingerprint: String) {
    // Each computer owns its measurements. Unpairing must never display another computer's cache.
    private val prefs = context.getSharedPreferences("usage-${fingerprint}", Context.MODE_PRIVATE)
    fun read(): JSONObject? = prefs.getString("snapshot", null)?.let { runCatching { JSONObject(it) }.getOrNull() }?.takeIf { UsageState.valid(it) }
    fun save(value: JSONObject) { if (UsageState.valid(value)) prefs.edit().putString("snapshot", value.toString()).apply() }
}
