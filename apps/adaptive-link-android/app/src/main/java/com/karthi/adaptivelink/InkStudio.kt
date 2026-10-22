package com.karthi.adaptivelink

import android.app.Activity
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.Canvas as AndroidCanvas
import android.graphics.Paint
import android.os.Environment
import android.provider.MediaStore
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.isSpecified
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.input.pointer.*
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalViewConfiguration
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import kotlin.math.hypot

private enum class InkMode { INK, TABLET }
private data class InkPoint(val x: Float, val y: Float, val pressure: Float)
private data class InkStroke(val points: List<InkPoint>, val width: Float, val eraser: Boolean = false)

/** One recognizer owns the complete trackpad surface, so a chord cannot also become a click. */
@Composable
internal fun Modifier.adaptiveTrackpad(input: InputSocket): Modifier {
    val slop = LocalViewConfiguration.current.touchSlop
    return pointerInput(input, slop) {
      coroutineScope {
        var previousTapAt = 0L
        var previousTap = Offset.Unspecified
        var pendingClick: Job? = null
        awaitEachGesture {
            val first = awaitFirstDown(requireUnconsumed = false)
            val doubleCandidate = first.uptimeMillis - previousTapAt in 1..300 &&
                previousTap.isSpecified && (first.position - previousTap).getDistance() <= 24.dp.toPx()
            var maximumPointers = 1
            var moved = false
            var dragging = false
            var scrollX = 0f
            var scrollY = 0f
            var lastCentroid = first.position
            var lastSingle = first.position
            first.consume()
            do {
                val event = awaitPointerEvent()
                val pressed = event.changes.filter { it.pressed }
                maximumPointers = maxOf(maximumPointers, pressed.size)
                if (pressed.size == 1 && maximumPointers == 1) {
                    val change = pressed.first()
                    val delta = change.position - lastSingle
                    if (!moved && (change.position - first.position).getDistance() > slop) moved = true
                    if (moved) {
                        if (doubleCandidate && !dragging) {
                            pendingClick?.cancel(); pendingClick = null
                            input.send(Protocol.button(true)); dragging = true
                        }
                        input.send(Protocol.relative(delta.x * 1.6f, delta.y * 1.6f))
                    }
                    lastSingle = change.position
                } else if (pressed.size == 2) {
                    val centroid = Offset(pressed.sumOf { it.position.x.toDouble() }.toFloat() / 2f,
                        pressed.sumOf { it.position.y.toDouble() }.toFloat() / 2f)
                    val delta = centroid - lastCentroid
                    if (delta.getDistance() > 0f) moved = true
                    scrollX += delta.x; scrollY += delta.y
                    val sx = (scrollX / 36.dp.toPx()).toInt(); val sy = (scrollY / 36.dp.toPx()).toInt()
                    if (sx != 0 || sy != 0) {
                        input.send(Protocol.scroll(sx, sy))
                        scrollX -= sx * 36.dp.toPx(); scrollY -= sy * 36.dp.toPx()
                    }
                    lastCentroid = centroid
                }
                event.changes.forEach { it.consume() }
            } while (event.changes.any { it.pressed })

            if (dragging) input.send(Protocol.button(false))
            else if (!moved) when (maximumPointers) {
                1 -> if (doubleCandidate) {
                    pendingClick?.cancel(); pendingClick = null
                    input.send(Protocol.doubleClick()); previousTapAt = 0L; previousTap = Offset.Unspecified
                } else {
                    previousTapAt = first.uptimeMillis; previousTap = first.position
                    pendingClick?.cancel()
                    pendingClick = launch { delay(300); input.send(Protocol.click(1)); previousTapAt = 0L }
                }
                2 -> input.send(Protocol.click(3))
                3 -> input.send(Protocol.click(2))
            }
        }
      }
    }
}

/** Full-screen blank tablet and durable local ink surface. Mirrored tablet mode reuses ScreenPage. */
@Composable
fun InkStudioPage(activity: Activity, client: LinkClient, onMirror: () -> Unit, onBack: () -> Unit) {
    val context = activity
    val prefs = remember(client.computer.fingerprint) {
        context.getSharedPreferences("ink-studio-${client.computer.fingerprint}", android.content.Context.MODE_PRIVATE)
    }
    val strokes = remember { mutableStateListOf<InkStroke>().apply { addAll(readInk(prefs.getString("draft", null))) } }
    val redo = remember { mutableStateListOf<InkStroke>() }
    val input = remember { InputSocket(client) }
    var mode by remember { mutableStateOf(InkMode.INK) }
    var width by remember { mutableFloatStateOf(5f) }
    var erasing by remember { mutableStateOf(false) }
    var palette by remember { mutableStateOf(true) }
    var size by remember { mutableStateOf(IntSize.Zero) }
    var status by remember { mutableStateOf(if (strokes.isEmpty()) "Ink is saved on this phone" else "Draft restored") }

    fun save() {
        prefs.edit().putString("draft", writeInk(strokes)).apply()
        status = "Draft saved"
    }
    fun leave() { save(); input.close(); onBack() }

    BackHandler { leave() }
    DisposableEffect(Unit) {
        fullScreen(activity, true)
        onDispose { save(); input.close(); fullScreen(activity, false) }
    }

    Box(Modifier.fillMaxSize().background(if (mode == InkMode.INK) Color(0xFFFAFAFC) else Color(0xFF111113))) {
        Canvas(
            Modifier.fillMaxSize().onSizeChanged { size = it }.pointerInput(mode, width, erasing, size) {
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    val tool = down.type
                    val stylus = tool == PointerType.Stylus || tool == PointerType.Eraser
                    val eraseStroke = erasing || tool == PointerType.Eraser
                    var active = InkStroke(emptyList(), width, eraseStroke)
                    var index = -1
                    var last = down.position
                    var remoteDown = false

                    fun pressure(change: PointerInputChange): Float =
                        if (stylus) change.pressure.coerceIn(0.01f, 1f) else 0.55f
                    fun append(change: PointerInputChange) {
                        if (size.width <= 0 || size.height <= 0) return
                        val point = InkPoint(
                            (change.position.x / size.width).coerceIn(0f, 1f),
                            (change.position.y / size.height).coerceIn(0f, 1f),
                            pressure(change),
                        )
                        if (mode == InkMode.TABLET) {
                            val phase = if (!remoteDown) "down" else "move"
                            input.send(Protocol.pen(point.x, point.y, point.pressure, phase, eraseStroke))
                            remoteDown = true
                        } else if (eraseStroke) {
                            removeNear(strokes, point, width / size.width.coerceAtLeast(1))?.let { redo.add(it) }
                        } else {
                            active = active.copy(points = active.points + point)
                            if (index < 0) { strokes.add(active); index = strokes.lastIndex; redo.clear() }
                            else strokes[index] = active
                        }
                        last = change.position
                    }
                    append(down)
                    down.consume()
                    var cancelled = false
                    do {
                        val event = awaitPointerEvent()
                        val pressed = event.changes.filter { it.pressed }
                        if (pressed.size > 1) {
                            cancelled = true
                            event.changes.forEach { it.consume() }
                            break
                        }
                        val change = event.changes.firstOrNull { it.id == down.id } ?: break
                        if (change.pressed && hypot(change.position.x - last.x, change.position.y - last.y) >= 0.5f) append(change)
                        change.consume()
                    } while (event.changes.any { it.pressed })
                    if (mode == InkMode.TABLET && remoteDown) {
                        input.send(Protocol.pen(
                            (last.x / size.width.coerceAtLeast(1)).coerceIn(0f, 1f),
                            (last.y / size.height.coerceAtLeast(1)).coerceIn(0f, 1f), 0f,
                            if (cancelled) "away" else "up", eraseStroke,
                        ))
                    }
                    if (mode == InkMode.INK && index >= 0) save()
                }
            },
        ) {
            strokes.forEach { stroke ->
                stroke.points.zipWithNext().forEach { (a, b) ->
                    drawLine(
                        color = if (stroke.eraser) Color.White else Color(0xFF111113),
                        start = Offset(a.x * size.width, a.y * size.height),
                        end = Offset(b.x * size.width, b.y * size.height),
                        strokeWidth = stroke.width * ((a.pressure + b.pressure) / 2f).coerceAtLeast(0.25f),
                        cap = StrokeCap.Round,
                    )
                }
                stroke.points.singleOrNull()?.let { p ->
                    drawCircle(Color(0xFF111113), stroke.width * p.pressure.coerceAtLeast(0.25f) / 2f, Offset(p.x * size.width, p.y * size.height))
                }
            }
        }

        if (mode == InkMode.TABLET) Text(
            "Blank tablet · absolute desktop mapping",
            color = Color.White.copy(alpha = 0.65f),
            modifier = Modifier.align(Alignment.Center),
        )

        if (palette) Surface(
            modifier = Modifier.align(Alignment.TopCenter).padding(8.dp),
            color = Color(0xE61C1C1E), shape = RoundedCornerShape(18.dp), tonalElevation = 6.dp,
        ) {
            Column(Modifier.padding(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = { leave() }) { Icon(Icons.Default.Close, "Exit", tint = Color.White) }
                    SingleChoiceSegmentedButtonRow {
                        SegmentedButton(mode == InkMode.INK, { mode = InkMode.INK; status = "Local editable ink" },
                            shape = SegmentedButtonDefaults.itemShape(0, 2)) { Text("Ink") }
                        SegmentedButton(mode == InkMode.TABLET, { save(); mode = InkMode.TABLET; status = "Drawing on the desktop" },
                            shape = SegmentedButtonDefaults.itemShape(1, 2)) { Text("Tablet") }
                    }
                    IconButton(onClick = { palette = false }) { Icon(Icons.Default.ExpandLess, "Hide controls", tint = Color.White) }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(enabled = mode == InkMode.INK && strokes.isNotEmpty(), onClick = {
                        redo.add(strokes.removeAt(strokes.lastIndex)); save()
                    }) { Icon(Icons.Default.Undo, "Undo", tint = Color.White) }
                    IconButton(enabled = mode == InkMode.INK && redo.isNotEmpty(), onClick = {
                        strokes.add(redo.removeAt(redo.lastIndex)); save()
                    }) { Icon(Icons.Default.Redo, "Redo", tint = Color.White) }
                    IconButton(onClick = { erasing = !erasing }) {
                        Icon(Icons.Default.AutoFixOff, "Stroke eraser", tint = if (erasing) MaterialTheme.colorScheme.primary else Color.White)
                    }
                    Slider(width, { width = it }, valueRange = 1f..24f, modifier = Modifier.width(110.dp))
                    IconButton(enabled = mode == InkMode.INK && strokes.isNotEmpty(), onClick = {
                        val exported = exportInk(context, strokes, size)
                        status = if (exported) "PNG and SVG saved to Downloads" else "Export failed"
                    }) { Icon(Icons.Default.Share, "Export PNG and SVG", tint = Color.White) }
                    TextButton(onClick = onMirror) { Text("Mirror") }
                }
                Text(status, color = Color(0xFFAEAEB2), style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(horizontal = 8.dp))
            }
        } else FloatingActionButton(
            onClick = { palette = true }, modifier = Modifier.align(Alignment.TopEnd).padding(12.dp), containerColor = Color(0xE61C1C1E),
        ) { Icon(Icons.Default.Draw, "Show controls", tint = Color.White) }
    }
}

private fun removeNear(strokes: SnapshotStateList<InkStroke>, p: InkPoint, radius: Float): InkStroke? {
    val index = strokes.indexOfLast { stroke -> stroke.points.any { hypot(it.x - p.x, it.y - p.y) <= radius.coerceAtLeast(0.015f) } }
    return if (index >= 0) strokes.removeAt(index) else null
}

private fun writeInk(strokes: List<InkStroke>): String = JSONObject().put("v", 1).put("strokes", JSONArray(strokes.map { stroke ->
    JSONObject().put("w", stroke.width).put("e", stroke.eraser).put("p", JSONArray(stroke.points.map {
        JSONArray(listOf(it.x.toDouble(), it.y.toDouble(), it.pressure.toDouble()))
    }))
})).toString()

private fun readInk(text: String?): List<InkStroke> = runCatching {
    val root = JSONObject(text ?: return emptyList())
    if (root.optInt("v") != 1) return emptyList()
    val array = root.getJSONArray("strokes")
    List(array.length()) { n ->
        val stroke = array.getJSONObject(n); val points = stroke.getJSONArray("p")
        InkStroke(List(points.length()) { i -> points.getJSONArray(i).let { InkPoint(it.getDouble(0).toFloat(), it.getDouble(1).toFloat(), it.getDouble(2).toFloat()) } },
            stroke.optDouble("w", 5.0).toFloat().coerceIn(1f, 24f), stroke.optBoolean("e"))
    }.takeLast(10_000)
}.getOrDefault(emptyList())

private fun exportInk(activity: Activity, strokes: List<InkStroke>, shown: IntSize): Boolean = runCatching {
    val width = shown.width.coerceAtLeast(1080); val height = shown.height.coerceAtLeast(1920)
    val stamp = System.currentTimeMillis()
    val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    val canvas = AndroidCanvas(bitmap); canvas.drawColor(android.graphics.Color.WHITE)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = android.graphics.Color.rgb(17, 17, 19); style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
    strokes.forEach { stroke -> stroke.points.zipWithNext().forEach { (a, b) ->
        paint.strokeWidth = stroke.width * ((a.pressure + b.pressure) / 2f).coerceAtLeast(0.25f)
        canvas.drawLine(a.x * width, a.y * height, b.x * width, b.y * height, paint)
    } }
    val resolver = activity.contentResolver
    fun values(ext: String, mime: String) = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, "adaptive-ink-$stamp.$ext")
        put(MediaStore.MediaColumns.MIME_TYPE, mime)
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Adaptive Link")
    }
    val png = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values("png", "image/png")) ?: error("PNG destination")
    resolver.openOutputStream(png)!!.use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }
    bitmap.recycle()
    val svg = buildString {
        append("<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 $width $height\" width=\"$width\" height=\"$height\"><rect width=\"100%\" height=\"100%\" fill=\"white\"/>")
        strokes.forEach { stroke -> stroke.points.zipWithNext().forEach { (a, b) ->
            val sw = stroke.width * ((a.pressure + b.pressure) / 2f).coerceAtLeast(0.25f)
            append(String.format(Locale.US, "<path d=\"M %.2f %.2f L %.2f %.2f\" fill=\"none\" stroke=\"#111113\" stroke-width=\"%.2f\" stroke-linecap=\"round\"/>", a.x * width, a.y * height, b.x * width, b.y * height, sw))
        } }
        append("</svg>")
    }
    val svgUri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values("svg", "image/svg+xml")) ?: error("SVG destination")
    resolver.openOutputStream(svgUri)!!.bufferedWriter().use { it.write(svg) }
    Toast.makeText(activity, "Saved PNG and SVG to Downloads/Adaptive Link", Toast.LENGTH_SHORT).show()
    true
}.getOrElse { Toast.makeText(activity, "Could not export ink", Toast.LENGTH_SHORT).show(); false }
