package com.karthi.adaptivelink

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.AtomicFile
import android.util.Base64
import android.util.LruCache
import android.view.View
import android.widget.RemoteViews
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Laptop apps as if they were the phone's own (docs/ADAPTIVE_LINK.md, *Apps in
 * the phone's form factor*):
 *
 *  - the screen the phone asks the laptop to draw its apps for (PhoneScreen);
 *  - their icons, kept on the phone once seen, for places with no
 *    connection to fetch them over: widgets and launcher shortcuts;
 *  - "Add to phone home screen" and the launcher's long-press shortcuts, each
 *    opening one laptop app straight into the phone session;
 *  - the Laptop apps widget: eight of them, pinned first, then recent.
 *
 * MainActivity is exported, so an intent asking it to open a laptop app
 * carries this install's own token: only what this app made can do it.
 */
internal object PhoneScreen {
    /** What phone_form.plan on the laptop is told: this space in dp, the density, the sharpness asked for. */
    fun describe(context: Context, widthPx: Int, heightPx: Int, sharpness: String): JSONObject {
        val density = context.resources.displayMetrics.density
        return JSONObject()
            .put("dp", JSONArray(listOf((widthPx / density).toInt(), (heightPx / density).toInt())))
            .put("density", density.toDouble())
            .put("sharpness", sharpness.toIntOrNull() ?: "auto")
    }

    /** The whole screen, before the app's own space has been measured. */
    fun whole(context: Context, sharpness: String): JSONObject {
        val metrics = context.resources.displayMetrics
        return describe(context, metrics.widthPixels, metrics.heightPixels, sharpness)
    }
}

internal object LaptopApps {
    const val EXTRA_APP = "com.karthi.adaptivelink.LAPTOP_APP"
    const val EXTRA_COMPUTER = "com.karthi.adaptivelink.COMPUTER"
    const val EXTRA_TOKEN = "com.karthi.adaptivelink.TOKEN"
    private const val SLOTS = 8

    private fun token(context: Context): String {
        val prefs = context.applicationContext.getSharedPreferences("link", Context.MODE_PRIVATE)
        prefs.getString("launch_token", null)?.let { return it }
        val made = ByteArray(24).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        prefs.edit().putString("launch_token", made).commit()
        return made
    }

    /** The laptop app an intent asks for, if this app made the intent. */
    fun requested(context: Context, intent: Intent?): Pair<String, String>? {
        val app = intent?.getStringExtra(EXTRA_APP) ?: return null
        if (intent.getStringExtra(EXTRA_TOKEN) != token(context)) return null
        return app to intent.getStringExtra(EXTRA_COMPUTER).orEmpty()
    }

    fun intent(context: Context, computer: String, appId: String): Intent =
        Intent(context, MainActivity::class.java).setAction(Intent.ACTION_VIEW)
            // Distinct data per app keeps one app's pending intent from replacing another's.
            .setData(Uri.parse("adaptive-link://app/" + Uri.encode(appId)))
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra(EXTRA_APP, appId).putExtra(EXTRA_COMPUTER, computer).putExtra(EXTRA_TOKEN, token(context))

    // --- Icons -----------------------------------------------------------

    private val seen = LruCache<String, Bitmap>(64)

    /** The icon if it is already in memory: a tile that has one draws it at once. */
    fun seenIcon(appId: String): Bitmap? = seen[appId]

    private fun iconFile(context: Context, appId: String): File {
        val name = MessageDigest.getInstance("SHA-256").digest(appId.toByteArray()).take(12).joinToString("") { "%02x".format(it) }
        return File(File(context.filesDir, "app-icons-2").apply { mkdirs() }, "$name.png")
    }

    fun cachedIcon(context: Context, appId: String): Bitmap? = seen[appId]
        ?: iconFile(context, appId).takeIf { it.isFile }?.let { BitmapFactory.decodeFile(it.path) }?.also { seen.put(appId, it) }

    /** Icons bring their own margins: without them they all fill a tile the same. */
    private fun trimmed(picture: Bitmap): Bitmap {
        val pixels = IntArray(picture.width * picture.height)
        picture.getPixels(pixels, 0, picture.width, 0, 0, picture.width, picture.height)
        val (left, top, right, bottom) = HomeMetrics.visibleBounds(pixels, picture.width, picture.height)?.toList() ?: return picture
        return Bitmap.createBitmap(picture, left, top, right - left, bottom - top)
    }

    /** The app's icon, from the phone if it has been seen, else from the laptop (and kept). */
    suspend fun icon(context: Context, client: LinkClient, appId: String): Bitmap? = withContext(Dispatchers.IO) {
        cachedIcon(context, appId)?.let { return@withContext it }
        val text = client.get("/v1/apps/icon?id=" + Uri.encode(appId))?.optString("png").orEmpty()
        val bytes = runCatching { Base64.decode(text, Base64.DEFAULT) }.getOrNull() ?: return@withContext null
        val fetched = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return@withContext null
        val picture = trimmed(fetched)
        // A daemon from before sharp icons sends 48 px: shown for now, not kept.
        if (maxOf(fetched.width, fetched.height) >= 96) {
            runCatching { iconFile(context, appId).outputStream().use { picture.compress(Bitmap.CompressFormat.PNG, 100, it) } }
            seen.put(appId, picture)
        }
        picture
    }

    // --- What the widget and the launcher show ---------------------------

    private fun listFile(context: Context) = AtomicFile(File(context.filesDir, "laptop-apps.json"))

    fun entries(context: Context): JSONObject = runCatching {
        JSONObject(listFile(context).openRead().bufferedReader().use { it.readText() })
    }.getOrElse { JSONObject().put("apps", JSONArray()) }

    /**
     * Pinned laptop apps first, then recent ones: what the Laptop apps
     * widget shows and the launcher offers on a long press. Drawn again only
     * when it changed.
     */
    suspend fun publish(context: Context, client: LinkClient, apps: List<Pair<String, String>>) {
        val chosen = apps.distinctBy { it.first }.take(SLOTS)
        val next = JSONObject().put("computer", client.computer.fingerprint).put("name", client.computer.name)
            .put("apps", JSONArray(chosen.map { (id, name) -> JSONObject().put("id", id).put("name", name) }))
        if (next.toString() == entries(context).toString()) return
        chosen.forEach { (id, _) -> icon(context, client, id) }
        val disk = listFile(context)
        val out = disk.startWrite()
        try { out.write(next.toString().toByteArray()); disk.finishWrite(out) } catch (error: Exception) { disk.failWrite(out); throw error }
        // Four on the launcher's long press, the most a launcher shows.
        val shortcuts = chosen.take(4).mapIndexed { rank, (id, name) -> shortcut(context, client.computer.fingerprint, id, name).setRank(rank).build() }
        runCatching { ShortcutManagerCompat.setDynamicShortcuts(context, shortcuts) }
        AppsWidget.refresh(context)
    }

    private fun shortcut(context: Context, computer: String, appId: String, name: String): ShortcutInfoCompat.Builder {
        val picture = cachedIcon(context, appId)
        return ShortcutInfoCompat.Builder(context, "laptop:" + appId.take(60))
            .setShortLabel(name.take(24).ifBlank { appId }).setLongLabel(name.ifBlank { appId })
            .setIcon(if (picture != null) IconCompat.createWithAdaptiveBitmap(padded(picture)) else IconCompat.createWithResource(context, R.drawable.ic_launcher))
            .setIntent(intent(context, computer, appId))
    }

    /** An adaptive icon's art sits in the middle two thirds: the app's icon is put there. */
    private fun padded(picture: Bitmap): Bitmap {
        val size = 216
        val out = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(out)
        canvas.drawColor(0xFF1C1C1E.toInt())
        val inset = 54
        val art = size - 2 * inset
        val wide = picture.width >= picture.height
        val width = if (wide) art else art * picture.width / picture.height
        val height = if (wide) art * picture.height / picture.width else art
        val left = (size - width) / 2; val top = (size - height) / 2
        canvas.drawBitmap(picture, null, android.graphics.Rect(left, top, left + width, top + height), android.graphics.Paint(android.graphics.Paint.FILTER_BITMAP_FLAG))
        return out
    }

    /** Eight full-size icons would strain the one binder call that updates a widget. */
    fun forWidget(picture: Bitmap): Bitmap {
        val longest = maxOf(picture.width, picture.height)
        if (longest <= 96) return picture
        return Bitmap.createScaledBitmap(picture, maxOf(1, picture.width * 96 / longest), maxOf(1, picture.height * 96 / longest), true)
    }

    /** Asks the launcher to put this laptop app on the phone's home screen. */
    suspend fun pin(context: Context, client: LinkClient, appId: String, name: String): Boolean {
        if (!ShortcutManagerCompat.isRequestPinShortcutSupported(context)) return false
        icon(context, client, appId)
        return ShortcutManagerCompat.requestPinShortcut(context, shortcut(context, client.computer.fingerprint, appId, name).build(), null)
    }
}

/** Eight laptop apps on the phone's home screen; a tap opens one in the phone's form factor. */
class AppsWidget : LinkWidgetBase() {
    private val slots = listOf(R.id.app_0, R.id.app_1, R.id.app_2, R.id.app_3, R.id.app_4, R.id.app_5, R.id.app_6, R.id.app_7)
    private val icons = listOf(R.id.icon_0, R.id.icon_1, R.id.icon_2, R.id.icon_3, R.id.icon_4, R.id.icon_5, R.id.icon_6, R.id.icon_7)
    private val labels = listOf(R.id.label_0, R.id.label_1, R.id.label_2, R.id.label_3, R.id.label_4, R.id.label_5, R.id.label_6, R.id.label_7)

    // Drawn from what the phone kept: opening an app needs no connection first.
    override suspend fun draw(context: Context, client: LinkClient?): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.widget_apps)
        val entries = LaptopApps.entries(context)
        val apps = entries.optJSONArray("apps")
        val computer = entries.optString("computer")
        views.setTextViewText(R.id.apps_title, entries.optString("name").ifBlank { "Laptop apps" })
        views.setTextViewText(R.id.apps_hint, if ((apps?.length() ?: 0) == 0) "Open apps in Adaptive Link to see them here" else "In your phone's form factor")
        slots.forEachIndexed { index, slot ->
            val app = apps?.optJSONObject(index)
            views.setViewVisibility(slot, if (app == null) View.INVISIBLE else View.VISIBLE)
            if (app == null) return@forEachIndexed
            val id = app.optString("id")
            views.setTextViewText(labels[index], app.optString("name"))
            val picture = LaptopApps.cachedIcon(context, id)
            if (picture != null) views.setImageViewBitmap(icons[index], LaptopApps.forWidget(picture)) else views.setImageViewResource(icons[index], R.drawable.ic_launcher)
            views.setOnClickPendingIntent(slot, PendingIntent.getActivity(context, 300 + index,
                LaptopApps.intent(context, computer, id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        }
        views.setOnClickPendingIntent(R.id.apps_title, open(context))
        return views
    }

    companion object {
        fun refresh(context: Context) {
            val ids = AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, AppsWidget::class.java))
            if (ids.isNotEmpty()) context.sendBroadcast(Intent(context, AppsWidget::class.java).setAction(LinkWidgetBase.TAP))
        }
    }
}
