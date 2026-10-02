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

    /** Show on this phone the computer's alerts (a full disk, a finished command). */
    var computerAlerts: Boolean
        get() = prefs.getBoolean("computer_alerts", false)
        set(value) { prefs.edit().putBoolean("computer_alerts", value).commit() }

    /** ...and the computer's own notifications. */
    var computerNotifications: Boolean
        get() = prefs.getBoolean("computer_notifications", false)
        set(value) { prefs.edit().putBoolean("computer_notifications", value).commit() }

    /** The last thing the computer said that this phone has shown. */
    var lastEvent: Long
        get() = prefs.getLong("last_event", 0L)
        set(value) = prefs.edit().putLong("last_event", value).apply()

    /** The owner's relay, as JSON, or "" (Relay.fromJson). Its password is in it: it stays in the app's private storage. */
    var relay: String
        get() = prefs.getString("relay", "") ?: ""
        set(value) = prefs.edit().putString("relay", value).apply()

    /** The screen as video (less data) rather than a picture at a time. */
    var screenVideo: Boolean
        get() = prefs.getBoolean("screen_video", true)
        set(value) = prefs.edit().putBoolean("screen_video", value).apply()

    /** The computer's sound with the screen. */
    var screenSound: Boolean
        get() = prefs.getBoolean("screen_sound", true)
        set(value) = prefs.edit().putBoolean("screen_sound", value).apply()

    var screenQuality: String
        get() = prefs.getString("screen_quality", "medium") ?: "medium"
        set(value) = prefs.edit().putString("screen_quality", value).apply()

    /** Commands kept to be run with one tap (the Run screen). */
    var savedCommands: List<SavedCommand>
        get() = SavedCommand.listFromJson(prefs.getString("saved_commands", "[]") ?: "[]")
        set(value) = prefs.edit().putString("saved_commands", SavedCommand.listToJson(value)).apply()

    var commandHistory: List<String>
        get() = prefs.getString("history", "")!!.split('\n').filter { it.isNotBlank() }
        set(value) = prefs.edit().putString("history", value.take(30).joinToString("\n")).apply()
}
