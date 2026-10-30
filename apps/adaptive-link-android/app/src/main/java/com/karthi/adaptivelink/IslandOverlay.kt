package com.karthi.adaptivelink

import android.app.KeyguardManager
import android.app.Notification
import android.app.PendingIntent
import android.content.*
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.session.MediaController
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.*
import android.provider.Settings
import android.service.notification.StatusBarNotification
import android.view.Gravity
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView

internal class IslandPreferences(context: Context) {
    val data = context.getSharedPreferences("dynamic-island", Context.MODE_PRIVATE)
    var enabled: Boolean
        get() = data.getBoolean("enabled", false)
        set(value) { data.edit().putBoolean("enabled", value).apply() }
    var previews: Boolean
        get() = data.getBoolean("previews", false)
        set(value) { data.edit().putBoolean("previews", value).apply() }
    var offset: Int
        get() = data.getInt("offset", 8).coerceIn(0, 100)
        set(value) { data.edit().putInt("offset", value.coerceIn(0, 100)).apply() }
}

/** Owned by Android's bound notification listener, so no polling service or wake lock is needed. */
internal class IslandOverlay(private val context: Context) {
    private val prefs = IslandPreferences(context)
    private val handler = Handler(Looper.getMainLooper())
    private val manager = context.getSystemService(WindowManager::class.java)
    private var view: LinearLayout? = null
    private var expanded = false
    private var hidden = false
    private val entries = linkedMapOf<String, StatusBarNotification>()
    private var current: StatusBarNotification? = null
    private var charging = false
    private var battery = 0
    private var transientKey: String? = null
    private val expire = Runnable { transientKey = null; expanded = false; render() }
    private val changes = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> handler.post { render() } }
    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_OFF -> { expanded = false; remove() }
                Intent.ACTION_USER_PRESENT -> { hidden = false; render() }
                Intent.ACTION_BATTERY_CHANGED -> {
                    val wasCharging = charging
                    charging = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0
                    val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100).coerceAtLeast(1)
                    battery = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, 0) * 100 / scale
                    if (charging && !wasCharging) hidden = false
                    render()
                }
            }
        }
    }
    init {
        prefs.data.registerOnSharedPreferenceChangeListener(changes)
        context.registerReceiver(receiver, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF); addAction(Intent.ACTION_USER_PRESENT); addAction(Intent.ACTION_BATTERY_CHANGED)
        })
    }
    fun posted(sbn: StatusBarNotification) { handler.post {
        if (sbn.packageName == context.packageName || sbn.notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return@post
        entries[sbn.key] = sbn
        while (entries.size > 32) entries.remove(entries.keys.first())
        hidden = false
        if (sbn.notification.category != Notification.CATEGORY_TRANSPORT) {
            transientKey = sbn.key
            handler.removeCallbacks(expire); handler.postDelayed(expire, 8000)
        }
        render()
    } }
    fun removed(key: String) { handler.post {
        entries.remove(key)
        if (transientKey == key) transientKey = null
        render()
    } }
    private fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    private fun label(text: String, size: Float = 14f, color: Int = Color.WHITE): TextView = TextView(context).apply {
        this.text = text; textSize = size; setTextColor(color); maxLines = 2
        ellipsize = android.text.TextUtils.TruncateAt.END
        setPadding(dp(12), dp(10), dp(12), dp(10))
        gravity = Gravity.CENTER_VERTICAL
    }
    private fun controller(sbn: StatusBarNotification?): MediaController? {
        val token = sbn?.notification?.extras?.getParcelable<MediaSession.Token>(Notification.EXTRA_MEDIA_SESSION) ?: return null
        return runCatching { MediaController(context, token) }.getOrNull()
    }
    private fun live(sbn: StatusBarNotification): Boolean = controller(sbn) != null ||
        (sbn.notification.flags and Notification.FLAG_ONGOING_EVENT != 0 && sbn.notification.category in
            listOf(Notification.CATEGORY_CALL, Notification.CATEGORY_ALARM, Notification.CATEGORY_PROGRESS))
    private fun render() {
        if (!prefs.enabled || !Settings.canDrawOverlays(context) || hidden ||
            context.getSystemService(KeyguardManager::class.java).isDeviceLocked ||
            !context.getSystemService(PowerManager::class.java).isInteractive) { remove(); return }
        current = transientKey?.let { entries[it] } ?: entries.values.lastOrNull { live(it) }
        val sbn = current
        if (sbn == null && !charging) { remove(); return }
        val media = controller(sbn)
        val app = sbn?.let { runCatching { context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(it.packageName, 0)).toString() }.getOrDefault("Notification") }
        val title = sbn?.notification?.extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val root = view ?: LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(3), dp(10), dp(3))
            background = GradientDrawable().apply { setColor(Color.BLACK); cornerRadius = dp(30).toFloat(); setStroke(dp(1), Color.rgb(44,44,46)) }
            elevation = dp(12).toFloat()
            setOnLongClickListener { hidden = true; remove(); true }
        }
        root.removeAllViews()
        val summary = when { sbn == null -> "⚡  Charging · $battery%"; media != null -> "♫  ${title.ifBlank { app.orEmpty() }}"; else -> "●  $app" }
        root.addView(label(summary).apply {
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            contentDescription = "$summary. Tap to ${if (expanded) "collapse" else "expand"}. Long press to hide."
            minHeight = dp(48)
            setOnClickListener {
                expanded = !expanded
                if (transientKey != null) { handler.removeCallbacks(expire); handler.postDelayed(expire, if (expanded) 20000 else 8000) }
                render()
            }
        })
        if (expanded) {
            if (sbn != null && (prefs.previews || media != null)) {
                val body = sbn.notification.extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
                root.addView(label(listOf(title, body).filter { it.isNotBlank() }.joinToString("\n"), 13f, Color.LTGRAY))
            }
            if (media != null) {
                val controls = LinearLayout(context)
                val state = media.playbackState
                fun action(text: String, supported: Long, run: () -> Unit) {
                    if ((state?.actions ?: 0L) and supported == 0L) return
                    controls.addView(label(text).apply { minHeight = dp(48); setOnClickListener { runCatching { run() }; handler.postDelayed({ render() }, 250) } }, LinearLayout.LayoutParams(0, -2, 1f))
                }
                action("Previous", PlaybackState.ACTION_SKIP_TO_PREVIOUS) { media.transportControls.skipToPrevious() }
                val playing = state?.state == PlaybackState.STATE_PLAYING
                action(if (playing) "Pause" else "Play", PlaybackState.ACTION_PLAY_PAUSE or if (playing) PlaybackState.ACTION_PAUSE else PlaybackState.ACTION_PLAY) {
                    if (playing) media.transportControls.pause() else media.transportControls.play()
                }
                action("Next", PlaybackState.ACTION_SKIP_TO_NEXT) { media.transportControls.skipToNext() }
                root.addView(controls)
            }
            if (media == null) sbn?.notification?.actions?.filter { it.remoteInputs.isNullOrEmpty() }?.take(3)?.forEach { action ->
                root.addView(label(action.title.toString(), color = Color.rgb(10,132,255)).apply {
                    minHeight = dp(48)
                    setOnClickListener { runCatching { action.actionIntent.send() }; expanded = false; render() }
                })
            }
            sbn?.notification?.contentIntent?.let { pending -> root.addView(label("Open $app", color = Color.rgb(10,132,255)).apply {
                minHeight = dp(48)
                setOnClickListener { runCatching { pending.send() }; expanded = false; remove() }
            }) }
            root.addView(label("Hide", color = Color.LTGRAY).apply { minHeight = dp(48); setOnClickListener { hidden = true; remove() } })
        }
        val width = minOf(dp(if (expanded) 340 else 224), context.resources.displayMetrics.widthPixels - dp(32))
        val params = WindowManager.LayoutParams(width, -2, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_SECURE,
            PixelFormat.TRANSLUCENT).apply { gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL; y = dp(prefs.offset) }
        try {
            if (view == null) { manager.addView(root, params); view = root; root.alpha = 0f; root.animate().alpha(1f).setDuration(180).start() }
            else manager.updateViewLayout(root, params)
        } catch (_: RuntimeException) { remove() }
    }
    private fun remove() { view?.let { runCatching { manager.removeView(it) } }; view = null }
    fun close() {
        handler.removeCallbacksAndMessages(null)
        prefs.data.unregisterOnSharedPreferenceChangeListener(changes)
        runCatching { context.unregisterReceiver(receiver) }
        remove(); entries.clear()
    }
}
