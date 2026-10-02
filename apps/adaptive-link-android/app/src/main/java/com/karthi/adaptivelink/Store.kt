package com.karthi.adaptivelink

import android.content.Context

/** What the app remembers: the computers it is paired with, which of them it is talking to, and a few switches. */
class Store(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("link", Context.MODE_PRIVATE)

    /** Every computer this phone is paired with. One paired before there could be several is carried over. */
    val computers: List<Computer>
        get() = Computers.fromJson(prefs.getString("computers", null))
            ?: listOfNotNull(prefs.getString("computer", null)?.let { Computer.fromJson(it) })

    /**
     * The computer the app is talking to. Setting it keeps what is known of
     * that computer (a new one is added, and becomes the one talked to);
     * setting it to nothing forgets the one talked to and moves to another,
     * if there is one.
     */
    var computer: Computer?
        get() = Computers.current(computers, prefs.getString("current", null))
        // Written at once, not in the background: being paired or not must
        // never depend on whether the app lived long enough to save it.
        set(value) {
            val now = computer
            val (kept, current) = Computers.after(computers, now?.fingerprint, value)
            prefs.edit().putString("computers", Computers.toJson(kept)).remove("computer")
                .putString("current", current).commit()
        }

    /** Talk to another of the paired computers. */
    fun switchTo(fingerprint: String) {
        if (computers.any { it.fingerprint == fingerprint }) prefs.edit().putString("current", fingerprint).commit()
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

    /** What is copied on one can be pasted on the other. */
    var syncClipboard: Boolean
        get() = prefs.getBoolean("sync_clipboard", false)
        set(value) { prefs.edit().putBoolean("sync_clipboard", value).commit() }

    /** The last clipboard text that came from, or went to, the computer: not to be sent again. */
    var clipboardSeen: String
        get() = prefs.getString("clipboard_seen", "") ?: ""
        set(value) = prefs.edit().putString("clipboard_seen", value.take(20_000)).apply()

    /** The computer may make this phone ring, to find it. */
    var findPhone: Boolean
        get() = prefs.getBoolean("find_phone", false)
        set(value) { prefs.edit().putBoolean("find_phone", value).commit() }

    /** This phone's fingerprint approves things on the computer: unlocking it, sudo. */
    var approvals: Boolean
        get() = prefs.getBoolean("approvals", false)
        set(value) { prefs.edit().putBoolean("approvals", value).commit() }

    /** Tell the computer this phone is on its network, so it can lock when the phone leaves. */
    var presence: Boolean
        get() = prefs.getBoolean("presence", false)
        set(value) { prefs.edit().putBoolean("presence", value).commit() }

    /** This phone's calls and text messages are shown on the computer, and it sends texts written there. */
    var phoneMessages: Boolean
        get() = prefs.getBoolean("phone_messages", false)
        set(value) { prefs.edit().putBoolean("phone_messages", value).commit() }

    /** New photos are copied to the computer when it is reached on its own network. */
    var copyPhotos: Boolean
        get() = prefs.getBoolean("copy_photos", false)
        set(value) { prefs.edit().putBoolean("copy_photos", value).commit() }

    /** When the newest photo already copied was taken (seconds). */
    var photosCopiedTo: Long
        get() = prefs.getLong("photos_copied_to", 0L)
        set(value) = prefs.edit().putLong("photos_copied_to", value).apply()

    /** Lock, play and pause as buttons on a notification - which a watch shows too. */
    var remoteNotification: Boolean
        get() = prefs.getBoolean("remote_notification", false)
        set(value) { prefs.edit().putBoolean("remote_notification", value).commit() }

    /** Whether anything needs the phone to stay connected to the computer. */
    val listens: Boolean
        get() = computerAlerts || computerNotifications || syncClipboard || findPhone || approvals || presence ||
            phoneMessages || copyPhotos || remoteNotification

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

    /** The owner's own page of buttons (the Controls screen). */
    var controls: List<Control>
        get() = Control.listFromJson(prefs.getString("controls", "[]") ?: "[]")
        set(value) = prefs.edit().putString("controls", Control.listToJson(value)).apply()

    /**
     * What a tag written by this app carries besides the button's name, so
     * that nothing else on the phone can press the owner's buttons by
     * knowing their names. Made once, kept.
     */
    val tagSecret: String
        get() = prefs.getString("tag_secret", null) ?: java.util.UUID.randomUUID().toString().replace("-", "").also {
            prefs.edit().putString("tag_secret", it).commit()
        }

    var commandHistory: List<String>
        get() = prefs.getString("history", "")!!.split('\n').filter { it.isNotBlank() }
        set(value) = prefs.edit().putString("history", value.take(30).joinToString("\n")).apply()
}
