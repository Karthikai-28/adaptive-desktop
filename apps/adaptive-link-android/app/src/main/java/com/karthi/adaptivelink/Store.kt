package com.karthi.adaptivelink

import android.content.Context

/** What the app remembers: which computer it is paired with, and a few switches. */
class Store(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("link", Context.MODE_PRIVATE)

    var computer: Computer?
        get() = prefs.getString("computer", null)?.let { Computer.fromJson(it) }
        // Written at once, not in the background: being paired or not must
        // never depend on whether the app lived long enough to save it.
        set(value) {
            prefs.edit().apply {
                if (value == null) remove("computer") else putString("computer", value.toJson())
            }.commit()
        }

    /** Ask for fingerprint or screen lock every time the app is opened. */
    var lockOnOpen: Boolean
        get() = prefs.getBoolean("lock_on_open", true)
        set(value) { prefs.edit().putBoolean("lock_on_open", value).commit() }

    /** Send this phone's notifications to the computer. */
    var relayNotifications: Boolean
        get() = prefs.getBoolean("relay_notifications", false)
        set(value) = prefs.edit().putBoolean("relay_notifications", value).apply()

    var screenQuality: String
        get() = prefs.getString("screen_quality", "medium") ?: "medium"
        set(value) = prefs.edit().putString("screen_quality", value).apply()

    var commandHistory: List<String>
        get() = prefs.getString("history", "")!!.split('\n').filter { it.isNotBlank() }
        set(value) = prefs.edit().putString("history", value.take(30).joinToString("\n")).apply()
}
