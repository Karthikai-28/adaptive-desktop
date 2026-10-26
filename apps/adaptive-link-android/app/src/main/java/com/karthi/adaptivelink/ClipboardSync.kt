package com.karthi.adaptivelink

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.os.PersistableBundle
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Response
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

internal object ClipboardSync {
    const val TEXT_MAX = 20_000
    const val IMAGE_MAX = 8 * 1024 * 1024
    const val PIXEL_MAX = 64 * 1024 * 1024
    private const val CACHE_MAX = 40L * 1024 * 1024
    private const val CACHE_AGE = 24L * 60 * 60 * 1000
    private val IMAGE_TYPES = setOf("image/png", "image/jpeg")

    data class Item(val kind: String, val mime: String, val hash: String,
                    val text: String = "", val bytes: ByteArray? = null)

    internal fun sensitiveFlags(get: (String) -> Boolean): Boolean =
        get(ClipDescription.EXTRA_IS_SENSITIVE) || get("android.content.extra.IS_SENSITIVE")

    fun sensitive(description: ClipDescription?): Boolean {
        val extras = description?.extras ?: return false
        return sensitiveFlags { extras.getBoolean(it, false) }
    }

    internal fun hash(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }

    internal fun validText(text: String) = text.isNotEmpty() && text.length <= TEXT_MAX
    internal fun validImageMetadata(mime: String, size: Long, width: Int, height: Int) =
        mime in IMAGE_TYPES && size in 1..IMAGE_MAX.toLong() && width > 0 && height > 0 &&
            width.toLong() * height <= PIXEL_MAX

    private fun skipped(context: Context, description: ClipDescription, reason: String, message: String): Item? {
        val mime = (0 until description.mimeTypeCount).joinToString(",") { description.getMimeType(it) }
        val key = "$reason:${description.timestamp}:$mime"
        val store = Store(context)
        if (store.clipboardSkipSeen != key) {
            store.clipboardSkipSeen = key
            Handler(Looper.getMainLooper()).post {
                Toast.makeText(context.applicationContext, message, Toast.LENGTH_SHORT).show()
            }
        }
        return null
    }

    fun read(context: Context): Item? {
        val clipboard = context.getSystemService(ClipboardManager::class.java)
        val description = clipboard.primaryClipDescription ?: return null
        if (sensitive(description)) return skipped(context, description, "sensitive", "Sensitive clipboard item wasn’t shared")
        val clip = clipboard.primaryClip ?: return null
        val first = clip.getItemAt(0)
        val offered = (0 until description.mimeTypeCount).map { description.getMimeType(it) }
        val imageType = offered.firstOrNull { it in IMAGE_TYPES }
        if (imageType != null && first.uri != null) {
            val bytes = runCatching {
                context.contentResolver.openInputStream(first.uri!!)?.use { input ->
                    input.readNBytes(IMAGE_MAX + 1)
                }
            }.getOrNull() ?: return skipped(context, description, "image-read", "Clipboard image couldn’t be read")
            if (bytes.isEmpty()) return skipped(context, description, "image-empty", "Empty clipboard image wasn’t shared")
            if (bytes.size > IMAGE_MAX) return skipped(context, description, "image-size", "Clipboard image over 8 MiB wasn’t shared")
            val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
            android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0 ||
                bounds.outWidth.toLong() * bounds.outHeight > PIXEL_MAX)
                return skipped(context, description, "image-dimensions", "Invalid or oversized clipboard image wasn’t shared")
            return Item("image", imageType, hash(bytes), bytes = bytes)
        }
        if (offered.any { it.startsWith("image/") })
            return skipped(context, description, "image-type", "Only PNG and JPEG clipboard images can be shared")
        val text = first.text?.toString() ?: first.coerceToText(context)?.toString() ?: return null
        if (text.isEmpty()) return null
        if (text.length > TEXT_MAX) return skipped(context, description, "text-size", "Clipboard text over 20,000 characters wasn’t shared")
        val bytes = text.toByteArray()
        val link = android.util.Patterns.WEB_URL.matcher(text.trim()).matches() &&
            (text.trim().startsWith("http://") || text.trim().startsWith("https://"))
        return Item(if (link) "link" else "text", if (link) "text/uri-list" else "text/plain", hash(bytes), text = text)
    }

    suspend fun sendCurrent(context: Context, client: LinkClient): Boolean = withContext(Dispatchers.IO) {
        val store = Store(context)
        if (!store.syncClipboard) return@withContext false
        val item = read(context) ?: return@withContext false
        if (item.hash == store.clipboardSeen) return@withContext true
        val reply = if (item.kind in setOf("text", "link")) {
            client.post("/v1/clipboard", JSONObject().put("text", item.text).put("kind", item.kind)
                .put("mime", item.mime).put("hash", item.hash))
        } else {
            client.postBytes("/v1/clipboard/content", item.bytes!!, item.mime, item.hash)
        }
        if (reply?.optBoolean("ok") == true) {
            store.clipboardSeen = item.hash
            true
        } else false
    }

    suspend fun receive(context: Context, client: LinkClient, event: JSONObject): Boolean = withContext(Dispatchers.IO) {
        val item = event.optJSONObject("item")
        val kind = item?.optString("kind").orEmpty().ifEmpty { "text" }
        val digest = item?.optString("hash").orEmpty()
        val store = Store(context)
        if (digest.isNotEmpty() && digest == store.clipboardSeen) return@withContext true
        if (kind == "text" || kind == "link") {
            val text = item?.optString("text").orEmpty().ifEmpty { event.optString("text") }
            if (!validText(text)) return@withContext false
            store.clipboardSeen = digest.ifEmpty { hash(text.toByteArray()) }
            context.getSystemService(ClipboardManager::class.java)
                .setPrimaryClip(ClipData.newPlainText("From computer", text))
            return@withContext true
        }
        val mime = item?.optString("mime").orEmpty()
        if (kind != "image" || mime !in IMAGE_TYPES || item!!.optLong("size") !in 1..IMAGE_MAX.toLong())
            return@withContext false
        val response: Response = client.open("/v1/clipboard/content?id=${item.optString("hash")}")
            ?: return@withContext false
        val bytes = response.use { reply ->
            if (!reply.isSuccessful || reply.body == null) return@withContext false
            reply.body!!.byteStream().readNBytes(IMAGE_MAX + 1)
        }
        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bytes.isEmpty() || bytes.size > IMAGE_MAX || hash(bytes) != item.optString("hash") ||
            !validImageMetadata(mime, bytes.size.toLong(), bounds.outWidth, bounds.outHeight) ||
            (item.optInt("width") > 0 && item.optInt("width") != bounds.outWidth) ||
            (item.optInt("height") > 0 && item.optInt("height") != bounds.outHeight)) return@withContext false
        val file = keep(context, bytes, mime)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.clipboard", file)
        store.clipboardSeen = item.optString("hash")
        context.getSystemService(ClipboardManager::class.java)
            .setPrimaryClip(ClipData.newUri(context.contentResolver, "From computer", uri))
        true
    }

    private fun keep(context: Context, bytes: ByteArray, mime: String): File {
        val folder = File(context.cacheDir, "clipboard").apply { mkdirs() }
        clean(folder)
        val suffix = if (mime == "image/png") ".png" else ".jpg"
        val saved = File(folder, "${hash(bytes)}$suffix").apply { writeBytes(bytes); setLastModified(System.currentTimeMillis()) }
        clean(folder)
        return saved
    }

    internal fun clean(folder: File, now: Long = System.currentTimeMillis()) {
        val files = folder.listFiles()?.sortedByDescending { it.lastModified() }.orEmpty()
        var total = 0L
        files.forEachIndexed { index, file ->
            total += file.length()
            if (now - file.lastModified() > CACHE_AGE || index >= 5 || total > CACHE_MAX) file.delete()
        }
    }

    fun sensitiveClip(text: String): ClipData = ClipData.newPlainText("Sensitive", text).apply {
        description.extras = PersistableBundle().apply {
            putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
            putBoolean("android.content.extra.IS_SENSITIVE", true)
        }
    }
}
