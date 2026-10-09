package com.karthi.adaptivelink

import android.app.Activity
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Switch
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.PointerType
import androidx.compose.ui.input.pointer.isSecondaryPressed
import android.content.res.Configuration
import android.graphics.Bitmap
import android.os.Build
import android.util.DisplayMetrics
import androidx.activity.compose.BackHandler
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.ui.platform.LocalConfiguration
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.TextButton
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.viewinterop.AndroidView
import android.graphics.BitmapFactory
import android.view.WindowManager
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.geometry.isSpecified
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FastForward
import androidx.compose.material.icons.filled.FastRewind
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material.icons.filled.VolumeDown
import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.AssistChip
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject

// ---------------------------------------------------------------- keyboard

private val SPECIAL_KEYS = listOf(
    "Esc" to { Protocol.key("Escape") }, "Tab" to { Protocol.key("Tab") },
    "Enter" to { Protocol.key("Return") }, "⌫" to { Protocol.key("BackSpace") },
    "←" to { Protocol.key("Left") }, "↓" to { Protocol.key("Down") },
    "↑" to { Protocol.key("Up") }, "→" to { Protocol.key("Right") },
    "Ctrl+C" to { Protocol.key("c", "ctrl") }, "Ctrl+V" to { Protocol.key("v", "ctrl") },
    "Ctrl+Z" to { Protocol.key("z", "ctrl") }, "Alt+Tab" to { Protocol.key("Tab", "alt") },
    "Super" to { Protocol.key("Super_L") }, "Alt+F4" to { Protocol.key("F4", "alt") },
    "Ctrl+Alt+T" to { Protocol.key("t", "ctrl", "alt") }, "Del" to { Protocol.key("Delete") },
)

/** A text field that types on the computer, and a row of the keys a phone keyboard lacks. */
@Composable
fun KeyboardBar(send: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(8.dp)) {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            SPECIAL_KEYS.forEach { (label, event) -> AssistChip(onClick = { send(event()) }, label = { Text(label) }) }
        }
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            placeholder = { Text("Type, then send") },
            singleLine = true,
            // Or say it: what is heard is typed on the computer.
            trailingIcon = { Dictate { send(Protocol.text(it)) } },
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = {
                if (text.isNotEmpty()) send(Protocol.text(text))
                text = ""
            }),
        )
    }
}

// ------------------------------------------------------------------ screen

/** Where a touch on the fitted picture falls on the computer's screen, 0..1. */
fun touchToScreen(touch: Offset, box: IntSize, picture: IntSize): Pair<Float, Float>? {
    if (box.width == 0 || box.height == 0 || picture.width == 0 || picture.height == 0) return null
    val scale = minOf(box.width / picture.width.toFloat(), box.height / picture.height.toFloat())
    val shownWidth = picture.width * scale
    val shownHeight = picture.height * scale
    val x = (touch.x - (box.width - shownWidth) / 2) / shownWidth
    val y = (touch.y - (box.height - shownHeight) / 2) / shownHeight
    return x.coerceIn(0f, 1f) to y.coerceIn(0f, 1f)
}

/**
 * The whole of this phone's screen, edge to edge: Android's bars hidden (a
 * swipe in from an edge brings them back for a moment), the picture drawn
 * past the camera's cutout, and the screen kept on - it is a display.
 */
private fun fullScreen(activity: Activity, on: Boolean) {
    val window = activity.window
    val bars = WindowCompat.getInsetsController(window, window.decorView)
    if (on) {
        bars.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        bars.hide(WindowInsetsCompat.Type.systemBars())
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    } else {
        bars.show(WindowInsetsCompat.Type.systemBars())
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
    window.attributes = window.attributes.apply {
        layoutInDisplayCutoutMode = if (on) WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        else WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_DEFAULT
    }
}

/** This phone's whole screen in pixels, bars and cutout included, long side first. */
private fun wholeScreen(activity: Activity): Pair<Int, Int> {
    val (w, h) = if (Build.VERSION.SDK_INT >= 30) activity.windowManager.maximumWindowMetrics.bounds.let { it.width() to it.height() }
    else DisplayMetrics().also { @Suppress("DEPRECATION") activity.windowManager.defaultDisplay.getRealMetrics(it) }
        .let { it.widthPixels to it.heightPixels }
    return maxOf(w, h) to minOf(w, h)
}

/** After a stylus was last seen, how long a touch is taken for the hand holding it rather than a finger. */
private const val PALM_MS = 500L

/** How large things are on this phone as a display: the longest side of the desktop it shows, in its pixels. */
internal val DISPLAY_SIZES = linkedMapOf("larger" to 1280, "standard" to 1600, "more" to 1920)

/**
 * The size of display to ask the computer for: this phone's whole screen in
 * shape, with as many pixels as the chosen size gives (fewer pixels, larger
 * text), never more than the phone has, upright or sideways.
 */
internal fun displaySize(wide: Int, high: Int, choice: String, upright: Boolean): String {
    val long = minOf(wide, DISPLAY_SIZES[choice] ?: 1600) / 8 * 8
    val short = (high * long / wide) / 8 * 8
    return if (upright) "${short}x$long" else "${long}x$short"
}

private fun displaySize(activity: Activity, choice: String, upright: Boolean): String =
    wholeScreen(activity).let { (wide, high) -> displaySize(wide, high, choice, upright) }

/** Where this phone's display goes and how it looks: chosen once, kept, and applied to the display there is. */
@Composable
private fun DisplaySettings(store: Store, onDone: (changed: Boolean) -> Unit) {
    var size by remember { mutableStateOf(store.displaySize) }
    var side by remember { mutableStateOf(store.displaySide) }
    var turns by remember { mutableStateOf(store.displayTurns) }
    AlertDialog(
        onDismissRequest = { onDone(false) },
        title = { Text("This phone as a display") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Size of things on it", fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("larger" to "Larger", "standard" to "Standard", "more" to "More space").forEach { (name, label) ->
                        FilterChip(selected = size == name, onClick = { size = name }, label = { Text(label) })
                    }
                }
                Text("Beside the computer's screen", fontWeight = FontWeight.SemiBold)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("left" to "Left", "right" to "Right", "above" to "Above", "below" to "Below").forEach { (name, label) ->
                        FilterChip(selected = side == name, onClick = { side = name }, label = { Text(label) })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Turn with the phone", fontWeight = FontWeight.SemiBold)
                        Muted("Upright, the display is tall; sideways, wide.")
                    }
                    Switch(checked = turns, onCheckedChange = { turns = it })
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val changed = size != store.displaySize || side != store.displaySide || turns != store.displayTurns
                store.displaySize = size
                store.displaySide = side
                store.displayTurns = turns
                onDone(changed)
            }) { Text("Done") }
        },
        dismissButton = { TextButton(onClick = { onDone(false) }) { Text("Cancel") } },
    )
}

@Composable
fun ScreenPage(activity: Activity, client: LinkClient, store: Store, workspaceId: String = "", contentStamp: String = "", whole: Boolean = false, mobileSession: String = "", appTitle: String = "Screen", onBack: () -> Unit) {
    var frame by remember { mutableStateOf<Bitmap?>(null) }
    var note by remember { mutableStateOf("Connecting…") }
    var quality by remember { mutableStateOf(store.screenQuality) }
    var scrolling by remember { mutableStateOf(false) }
    var keyboard by remember { mutableStateOf(false) }
    var box by remember { mutableStateOf(IntSize.Zero) }
    var socket by remember { mutableStateOf<WebSocket?>(null) }
    // Two fingers zoom and move the picture; one finger is still the pointer
    // on the computer, wherever the picture has been moved to.
    var zoom by remember { mutableStateOf(1f) }
    var shift by remember { mutableStateOf(Offset.Zero) }
    // As video (far less data, and the computer's sound with it), or a
    // picture at a time where video cannot be had.
    var video by remember { mutableStateOf(store.screenVideo) }
    var sound by remember { mutableStateOf(store.screenSound) }
    var hearing by remember { mutableStateOf(false) }
    var picture by remember { mutableStateOf(IntSize.Zero) }
    var options by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // The whole screen, or one display of it - which can be one made for
    // this phone, beside the computer's own.
    var display by remember { mutableStateOf("") }
    var displays by remember { mutableStateOf(listOf<String>()) }
    var primary by remember { mutableStateOf("") }
    var extended by remember { mutableStateOf("") }
    // Counts the times this phone's display was made: made again (another
    // size, turned), the picture and the touches start again on the new one.
    var generation by remember { mutableIntStateOf(0) }
    var settings by remember { mutableStateOf(false) }
    // Over a USB cable the link carries pictures at 30 a second; video's own
    // connection cannot go over the cable.
    var cable by remember { mutableStateOf(client.viaCable) }
    LaunchedEffect(Unit) { client.connect(); cable = client.viaCable }
    val showVideo = video && !cable
    val preset = if (cable) "cable" else quality
    val base = if (mobileSession.isEmpty()) "/v1" else "/v1/mobile"
    val showing = (if (mobileSession.isEmpty()) "" else "&session=$mobileSession") + (if (display.isEmpty()) "" else "&display=" + java.net.URLEncoder.encode(display, "UTF-8")) +
        (if (workspaceId.isEmpty()) "" else "&workspace=$workspaceId&whole=${if (whole) 1 else 0}")
    val input = remember(display, generation, workspaceId, contentStamp, whole) { InputSocket(client, "$base/input?x=1$showing") }
    LaunchedEffect(mobileSession, box, quality) {
        if (mobileSession.isNotEmpty() && box.width > 0 && box.height > 0) {
            delay(400)
            val scale = if (quality == "ultra" || quality == "high") 1.0f else (1.5f / activity.resources.displayMetrics.density).coerceAtLeast(0.85f)
            val size = org.json.JSONArray(listOf((box.width * scale).toInt().coerceIn(320, 3840), (box.height * scale).toInt().coerceIn(320, 3840)))
            val reply = client.post("/v1/mobile/sessions", JSONObject().put("operation", "resize").put("session", mobileSession).put("viewport", size))
            if (reply?.optBoolean("ok") == true) generation++
            else note = reply?.optString("error") ?: "Disconnected · phone applications remain open"
        }
    }
    val viewPrefs = remember { context.getSharedPreferences("mobile-view-${client.computer.fingerprint}", android.content.Context.MODE_PRIVATE) }
    LaunchedEffect(appTitle, mobileSession) {
        if (mobileSession.isNotEmpty()) {
            zoom = viewPrefs.getFloat("$appTitle.zoom", 1f)
            shift = Offset(viewPrefs.getFloat("$appTitle.x", 0f), viewPrefs.getFloat("$appTitle.y", 0f))
        }
    }
    DisposableEffect(appTitle, mobileSession) {
        onDispose { if (mobileSession.isNotEmpty()) viewPrefs.edit().putFloat("$appTitle.zoom", zoom).putFloat("$appTitle.x", shift.x).putFloat("$appTitle.y", shift.y).apply() }
    }
    LaunchedEffect(note) {
        if (mobileSession.isNotEmpty() && note == "Connection lost") { delay(2000); generation++ }
    }
    val surface = remember { VideoView(context) }
    DisposableEffect(Unit) { onDispose { surface.release() } }
    DisposableEffect(input) { onDispose { input.close() } }
    LaunchedEffect(options) {
        if (options && mobileSession.isEmpty()) client.get("/v1/machine/display")?.optJSONArray("outputs")?.let { outputs ->
            val on = List(outputs.length()) { outputs.optJSONObject(it) }.filterNotNull().filter { it.optBoolean("on") }
            displays = on.map { it.optString("name") }
            primary = on.firstOrNull { it.optBoolean("primary") }?.optString("name") ?: displays.firstOrNull() ?: ""
        }
    }
    val sideways = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE

    /** Make this phone a display - or have its display made again - as it is held and as its owner chose. */
    suspend fun makeDisplay(upright: Boolean = store.displayTurns && !sideways): Boolean {
        val reply = client.post("/v1/machine/display", JSONObject().put("action", "extend")
            .put("value", displaySize(activity, store.displaySize, upright)).put("target", store.displaySide))
        if (reply?.optBoolean("ok") != true) {
            note = reply?.optString("error")?.ifBlank { null } ?: "The computer could not make another display"
            return false
        }
        extended = reply.optString("text")
        display = extended
        generation += 1
        return true
    }

    // A display this phone let go of a moment ago (the app closed, the phone
    // locked) is still there: it is taken back, windows and all.
    LaunchedEffect(Unit) {
        val mine = if (mobileSession.isEmpty()) client.get("/v1/machine/display")?.optJSONArray("made").objects().any { it.optBoolean("mine") } else false
        if (mine && workspaceId.isEmpty() && mobileSession.isEmpty()) makeDisplay()
    }
    // Turned, the display turns with it: made again the other way up.
    LaunchedEffect(sideways) {
        if (extended.isNotEmpty() && store.displayTurns) {
            delay(700)   // a phone being turned passes through in-between angles
            makeDisplay()
        }
    }

    // Full screen: chosen from the bar, or by itself while this phone is a
    // display of the computer and held as it shows it.
    var full by remember { mutableStateOf(false) }
    var hint by remember { mutableStateOf(false) }
    LaunchedEffect(sideways, extended) { if (extended.isNotEmpty()) full = sideways || store.displayTurns }
    BackHandler(enabled = full) { full = false }
    DisposableEffect(full) {
        val on = full
        if (on) fullScreen(activity, true)
        onDispose { if (on) fullScreen(activity, false) }
    }
    LaunchedEffect(full) { hint = full; if (full) { delay(3000); hint = false } }

    // Leaving, this phone lets go of its display rather than taking it away:
    // the computer keeps it a while, in case the phone comes back.
    DisposableEffect(extended) {
        val made = extended
        onDispose {
            if (made.isNotEmpty()) kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.IO).launch {
                client.post("/v1/machine/display", JSONObject().put("action", "release"))
            }
        }
    }

    if (showVideo) {
        DisposableEffect(quality, sound, display, generation, workspaceId, contentStamp, whole) {
            note = "Connecting…"
            picture = IntSize.Zero
            val watching = ScreenVideo(context, client) { said -> if (picture != IntSize.Zero || said.isNotEmpty()) note = said }
            surface.fresh()
            surface.onSize = { w, h -> picture = IntSize(w, h); note = "" }
            watching.show(surface)
            val starting = scope.launch {
                val agreed = watching.start(quality, sound, display, workspaceId, whole, mobileSession)
                hearing = agreed && watching.sound
                // No picture after a while: the two could not reach each
                // other this way. The other way still works.
                if (agreed) for (waited in 1..40) { if (picture != IntSize.Zero) break; delay(250) }
                if (picture == IntSize.Zero) {
                    watching.stop()
                    video = false
                    note = "Video could not be started; showing a picture at a time"
                }
            }
            onDispose {
                starting.cancel()
                surface.onSize = null
                kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.IO).launch { watching.stop() }
            }
        }
    } else {
        DisposableEffect(preset, display, generation, workspaceId, contentStamp, whole) {
            val opened = client.socket("$base/screen?preset=$preset$showing", object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                    BitmapFactory.decodeByteArray(bytes.toByteArray(), 0, bytes.size)?.let {
                        frame = it
                        picture = IntSize(it.width, it.height)
                        note = ""
                    }
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    note = if (response?.code == 503) "The computer has no screen to show" else "Connection lost"
                }
            })
            socket = opened
            onDispose { opened.close(1000, null); socket = null }
        }
    }

    // With video the pictures come on their own connection; the pointer and
    // the keys go on the socket the trackpad uses.
    fun send(event: String) { if (showVideo) input.send(event) else socket?.send(event) }
    fun at(offset: Offset): Pair<Float, Float>? =
        picture.takeIf { it != IntSize.Zero }?.let { touchToScreen(unzoomed(offset, box, zoom, shift), box, it) }

    Column(Modifier.fillMaxSize().imePadding()) {
        if (!full) TopBar(appTitle, onBack) {
            Box {
                IconButton(onClick = { options = true }) { Icon(Icons.Filled.Tune, "Picture and sound") }
                DropdownMenu(expanded = options, onDismissRequest = { options = false }) {
                    listOf(
                        "ultra" to "Ultra HD · 60 FPS (Retina)",
                        "high" to "High quality · 30 FPS",
                        "medium" to "Medium quality",
                        "low" to "Low quality (Data saver)",
                    ).forEach { (name, label) ->
                        DropdownMenuItem(
                            text = { Text(label, color = if (quality == name) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface) },
                            onClick = { quality = name; store.screenQuality = name; options = false },
                        )
                    }
                    DropdownMenuItem(
                        text = {
                            Text(if (cable) "Over the USB cable: 30 pictures a second"
                                 else if (video) "Video: on (less data)" else "Video: off (a picture at a time)")
                        },
                        enabled = !cable,
                        onClick = { video = !video; store.screenVideo = video; options = false },
                    )
                    if (showVideo) DropdownMenuItem(
                        text = { Text(if (!sound) "Sound: off" else if (hearing || picture == IntSize.Zero) "Sound: on" else "Sound: on (the computer has none to send)") },
                        onClick = { sound = !sound; store.screenSound = sound; options = false },
                    )
                    if (workspaceId.isEmpty() && mobileSession.isEmpty()) {
                    if (displays.size > 1 || display.isNotEmpty()) (listOf("") + displays).distinct().forEach { name ->
                        DropdownMenuItem(
                            text = {
                                Text(if (name.isEmpty()) "Show every display" else "Show only $name",
                                    color = if (display == name) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                            },
                            onClick = { display = name; options = false },
                        )
                    }
                    if (extended.isEmpty()) {
                        DropdownMenuItem(
                            text = { Text("Use this phone as another display") },
                            onClick = { options = false; scope.launch { makeDisplay() } },
                        )
                        // The computer's own screen, as it is, filling this one.
                        if (primary.isNotEmpty()) DropdownMenuItem(
                            text = { Text("Mirror the computer's screen") },
                            onClick = { options = false; display = primary; full = true },
                        )
                    } else {
                        DropdownMenuItem(
                            text = { Text("Bring the window in front here") },
                            onClick = {
                                options = false
                                scope.launch {
                                    val reply = client.post("/v1/machine/display", JSONObject().put("action", "bring"))
                                    if (reply?.optBoolean("ok") != true) note = reply?.optString("error") ?: "It could not be moved"
                                }
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Stop using this phone as a display") },
                            onClick = {
                                options = false
                                val made = extended
                                display = ""
                                extended = ""
                                scope.launch {
                                    client.post("/v1/machine/display", JSONObject().put("action", "unextend").put("target", made))
                                }
                            },
                        )
                    }
                    DropdownMenuItem(text = { Text("Display settings…") }, onClick = { options = false; settings = true })
                    }
                }
            }
            IconButton(onClick = { full = true }) { Icon(Icons.Filled.Fullscreen, "Full screen") }
            IconButton(onClick = { scrolling = !scrolling }) {
                Icon(Icons.Filled.SwapVert, "Scroll mode",
                    tint = if (scrolling) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
            }
            IconButton(onClick = { keyboard = !keyboard }) {
                Icon(Icons.Filled.Keyboard, "Keyboard",
                    tint = if (keyboard) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
            }
        }
        Box(
            Modifier.weight(1f).fillMaxWidth().background(Color.Black).clipToBounds().onSizeChanged { box = it }
                // A stylus draws: pressure, the eraser end and its button go to
                // the computer as a tablet's (pen.py). While it is near, a hand
                // resting on the glass is not a touch. Seen before the gestures
                // below, which then leave what it took alone.
                .pointerInput(picture, box, zoom, shift) {
                    awaitPointerEventScope {
                        var penSeen = 0L
                        while (true) {
                            val event = awaitPointerEvent(PointerEventPass.Initial)
                            val stylus = event.changes.firstOrNull { it.type == PointerType.Stylus || it.type == PointerType.Eraser }
                            if (stylus == null) {
                                if ((event.changes.firstOrNull()?.uptimeMillis ?: 0L) - penSeen < PALM_MS) event.changes.forEach { it.consume() }
                                continue
                            }
                            penSeen = stylus.uptimeMillis
                            val stage = when (event.type) {
                                PointerEventType.Press -> "down"
                                PointerEventType.Release -> "up"
                                PointerEventType.Exit -> "away"
                                PointerEventType.Enter -> "near"
                                else -> if (stylus.pressed) "move" else "near"
                            }
                            at(stylus.position)?.let { (x, y) ->
                                send(Protocol.pen(x, y, stylus.pressure, stage, eraser = stylus.type == PointerType.Eraser,
                                    button = event.buttons.isSecondaryPressed))
                            }
                            event.changes.forEach { it.consume() }
                        }
                    }
                }
                .pointerInput(scrolling) {
                    detectTapGestures(
                        onTap = { at(it)?.let { (x, y) -> send(Protocol.move(x, y)); send(Protocol.click(1)) } },
                        onDoubleTap = { at(it)?.let { (x, y) -> send(Protocol.move(x, y)); send(Protocol.doubleClick()) } },
                        onLongPress = { at(it)?.let { (x, y) -> send(Protocol.move(x, y)); send(Protocol.click(3)) } },
                    )
                }
                .pointerInput(scrolling) {
                    var carried = 0f
                    detectDragGestures(
                        onDragStart = { start ->
                            carried = 0f
                            if (!scrolling) at(start)?.let { (x, y) ->
                                // A drag holds the button down: moving windows,
                                // selecting text, dragging a slider.
                                send(Protocol.move(x, y)); send(Protocol.button(true))
                            }
                        },
                        onDragEnd = { if (!scrolling) send(Protocol.button(false)) },
                        onDragCancel = { if (!scrolling) send(Protocol.button(false)) },
                    ) { change, drag ->
                        if (scrolling) {
                            carried += drag.y
                            val steps = (carried / 40f).toInt()
                            if (steps != 0) {
                                send(Protocol.scroll(0, -steps))
                                carried -= steps * 40f
                            }
                        } else {
                            at(change.position)?.let { (x, y) -> send(Protocol.move(x, y)) }
                        }
                    }
                }
                // Last, so it sees two fingers before the gestures above do
                // and takes them: a pinch is never a click or a drag.
                .pointerInput(Unit) {
                    awaitEachGesture {
                        awaitFirstDown(requireUnconsumed = false)
                        do {
                            val event = awaitPointerEvent()
                            if (event.changes.count { it.pressed } >= 2) {
                                val (newZoom, newShift) = zoomed(
                                    zoom, shift, box, event.calculateZoom(),
                                    event.calculateCentroid(useCurrent = false), event.calculatePan(),
                                )
                                zoom = newZoom
                                shift = newShift
                                event.changes.forEach { it.consume() }
                            }
                        } while (event.changes.any { it.pressed })
                    }
                },
            contentAlignment = Alignment.Center,
        ) {
            if (showVideo) {
                // The view is given the shape of the pictures, so that what
                // is drawn fills it exactly and a touch lands where it looks.
                val shape = if (picture == IntSize.Zero) 16f / 10f else picture.width / picture.height.toFloat()
                val tall = box != IntSize.Zero && box.width / box.height.toFloat() > shape
                AndroidView(
                    factory = { surface },
                    modifier = Modifier.aspectRatio(shape, matchHeightConstraintsFirst = tall).graphicsLayer {
                        scaleX = zoom; scaleY = zoom
                        translationX = shift.x; translationY = shift.y
                    }.semantics { contentDescription = "The computer's screen" },
                )
            } else frame?.let {
                Image(
                    it.asImageBitmap(), "The computer's screen",
                    Modifier.fillMaxSize().graphicsLayer {
                        scaleX = zoom; scaleY = zoom
                        translationX = shift.x; translationY = shift.y
                    },
                    contentScale = ContentScale.Fit,
                )
            }
            if (note.isNotEmpty()) Text(note, color = Color.White)
            if (picture != IntSize.Zero && !full) {
                Box(
                    Modifier.align(Alignment.TopEnd).padding(12.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .background(Color(0x991C1C1E))
                        .border(0.5.dp, Color(0x33FFFFFF), RoundedCornerShape(20.dp))
                        .clickable { options = true }
                        .padding(horizontal = 10.dp, vertical = 5.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(6.dp).clip(CircleShape).background(Color(0xFF30D158)))
                        Spacer(Modifier.width(6.dp))
                        Text(
                            if (cable) "USB · 30 FPS"
                            else if (quality == "ultra") "60 FPS · RETINA"
                            else "${quality.uppercase()} · ${if (hearing) "AUDIO" else "VIDEO"}",
                            color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }
            if (hint) Text(
                "Swipe in from an edge and go back to leave full screen", color = Color.White,
                modifier = Modifier.align(Alignment.BottomCenter).padding(16.dp)
                    .background(Color.Black.copy(alpha = 0.6f), RoundedCornerShape(8.dp)).padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }
        if (scrolling && !full) Muted("Scroll mode: drag up and down to scroll", Modifier.padding(8.dp))
        if (keyboard && !full) KeyboardBar(::send)
    }
    if (settings) DisplaySettings(store) { changed ->
        settings = false
        // Applied to the display there is, which is made again to suit.
        if (changed && extended.isNotEmpty()) scope.launch { makeDisplay() }
    }
}

/** Where a touch on the zoomed picture lies on the picture as first drawn. */
internal fun unzoomed(touch: Offset, box: IntSize, zoom: Float, shift: Offset): Offset {
    val centre = Offset(box.width / 2f, box.height / 2f)
    return centre + (touch - centre - shift) / zoom
}

/**
 * The picture's zoom and position after a pinch: it grows about the point
 * between the fingers and follows them, never smaller than the whole screen
 * and never moved off it.
 */
internal fun zoomed(zoom: Float, shift: Offset, box: IntSize, by: Float, between: Offset, moved: Offset): Pair<Float, Offset> {
    if (!between.isSpecified) return zoom to shift
    val next = (zoom * by).coerceIn(1f, 8f)
    if (next < 1.03f) return 1f to Offset.Zero
    val centre = Offset(box.width / 2f, box.height / 2f)
    val held = between - centre
    val wanted = held + moved - (held - shift) * (next / zoom)
    val reachX = box.width * (next - 1f) / 2f
    val reachY = box.height * (next - 1f) / 2f
    return next to Offset(wanted.x.coerceIn(-reachX, reachX), wanted.y.coerceIn(-reachY, reachY))
}

// ---------------------------------------------------------------- trackpad

@Composable
fun TrackpadPage(client: LinkClient, workspaceId: String = "", onBack: () -> Unit) {
    val input = remember(workspaceId) { InputSocket(client, if (workspaceId.isEmpty()) "/v1/input" else "/v1/input?workspace=$workspaceId") }
    DisposableEffect(Unit) { onDispose { input.close() } }
    var keyboard by remember { mutableStateOf(true) }
    // Aim the phone like a pointer, instead of dragging on it.
    var air by remember { mutableStateOf(false) }
    val context = LocalContext.current
    if (air) AirMouse { input.send(it) }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Trackpad", onBack) {
            if (hasGyroscope(context)) FilterChip(selected = air, onClick = { air = !air }, label = { Text("Air") },
                modifier = Modifier.padding(end = 4.dp))
            IconButton(onClick = { keyboard = !keyboard }) { Icon(Icons.Filled.Keyboard, "Keyboard") }
        }
        Row(Modifier.weight(1f).fillMaxWidth().padding(12.dp)) {
            Box(
                Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(18.dp))
                    .background(MaterialTheme.colorScheme.surface)
                    .pointerInput(Unit) {
                        detectTapGestures(
                            onTap = { input.send(Protocol.click(1)) },
                            onDoubleTap = { input.send(Protocol.doubleClick()) },
                            onLongPress = { input.send(Protocol.click(3)) },
                        )
                    }
                    .pointerInput(Unit) {
                        detectDragGestures { _, drag -> input.send(Protocol.relative(drag.x * 1.6f, drag.y * 1.6f)) }
                    },
                contentAlignment = Alignment.Center,
            ) { Muted("Drag to move · tap to click · hold for right-click") }
            Spacer(Modifier.width(10.dp))
            // A scroll strip, like the edge of a laptop trackpad.
            Box(
                Modifier.width(46.dp).fillMaxHeight().clip(RoundedCornerShape(18.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .pointerInput(Unit) {
                        var carried = 0f
                        detectDragGestures(onDragStart = { carried = 0f }) { _, drag ->
                            carried += drag.y
                            val steps = (carried / 36f).toInt()
                            if (steps != 0) {
                                input.send(Protocol.scroll(0, steps))
                                carried -= steps * 36f
                            }
                        }
                    },
                contentAlignment = Alignment.Center,
            ) { Icon(Icons.Filled.SwapVert, "Scroll", tint = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            BigButton("Left", Modifier.weight(1f)) { input.send(Protocol.click(1)) }
            BigButton("Right", Modifier.weight(1f)) { input.send(Protocol.click(3)) }
        }
        Spacer(Modifier.height(8.dp))
        if (keyboard) KeyboardBar(input::send)
    }
}

@Composable
fun BigButton(label: String, modifier: Modifier = Modifier, height: Int = 56, onClick: () -> Unit) {
    Box(
        modifier.height(height.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.surface)
            .pointerInput(onClick) { detectTapGestures(onTap = { onClick() }) },
        contentAlignment = Alignment.Center,
    ) { Text(label, fontWeight = FontWeight.SemiBold, fontSize = if (height > 100) 28.sp else 16.sp) }
}

// ------------------------------------------------------------------- media

@Composable
fun MediaPage(client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var player by remember { mutableStateOf<JSONObject?>(null) }
    var volume by remember { mutableStateOf<JSONObject?>(null) }

    suspend fun refresh() {
        val state = client.get("/v1/media") ?: return
        player = state.optJSONArray("players")?.optJSONObject(0)
        volume = state.optJSONObject("volume")
    }
    LaunchedEffect(Unit) { while (true) { refresh(); delay(2000) } }

    fun act(action: String, seconds: Int = 0) = scope.launch {
        client.post("/v1/media", JSONObject().put("action", action).put("seconds", seconds))
        refresh()
    }
    fun sound(action: String) = scope.launch {
        client.post("/v1/volume", JSONObject().put("action", action))?.optJSONObject("volume")?.let { volume = it }
    }

    TopBar("Media", onBack)
    Column(
        Modifier.fillMaxSize().padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        val current = player
        if (current == null) {
            Muted("Nothing is playing on the computer.")
            Spacer(Modifier.height(8.dp))
            Muted("Open a movie from Files, or start a player there.")
        } else {
            Muted(current.optString("name"))
            Spacer(Modifier.height(6.dp))
            Text(current.optString("title").ifBlank { "Playing" }, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            if (current.optString("artist").isNotBlank()) Muted(current.optString("artist"))
            Protocol.handoffAddress(current.optString("url"), current.optInt("position"))?.let { address ->
                // What is playing from the web can be carried on with here: paused there, opened here.
                val context = LocalContext.current
                TextButton(onClick = {
                    if (current.optString("status") == "Playing") act("pause")
                    (context as? MainActivity)?.awayOnPurpose = true
                    runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(address))) }
                }) { Text("Carry on with it on this phone") }
            }
            if (current.optInt("length") > 0) {
                Spacer(Modifier.height(6.dp))
                Muted("${Protocol.formatDuration(current.optInt("position"))} / ${Protocol.formatDuration(current.optInt("length"))}")
            }
            Spacer(Modifier.height(28.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                IconButton(enabled = current.optBoolean("can_previous"), onClick = { act("previous") }) { Icon(Icons.Filled.SkipPrevious, "Previous", Modifier.size(34.dp)) }
                IconButton(enabled = current.optBoolean("can_seek"), onClick = { act("seek", -10) }) { Icon(Icons.Filled.FastRewind, "Back 10 seconds", Modifier.size(30.dp)) }
                FilledIconButton(onClick = { act("play-pause") }, modifier = Modifier.size(76.dp)) {
                    val playing = current.optString("status") == "Playing"
                    Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, "Play or pause", Modifier.size(44.dp))
                }
                IconButton(enabled = current.optBoolean("can_seek"), onClick = { act("seek", 10) }) { Icon(Icons.Filled.FastForward, "Forward 10 seconds", Modifier.size(30.dp)) }
                IconButton(enabled = current.optBoolean("can_next"), onClick = { act("next") }) { Icon(Icons.Filled.SkipNext, "Next", Modifier.size(34.dp)) }
            }
        }
        Spacer(Modifier.height(36.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            IconButton(onClick = { sound("down") }) { Icon(Icons.Filled.VolumeDown, "Quieter", Modifier.size(32.dp)) }
            IconButton(onClick = { sound("mute") }) { Icon(Icons.Filled.VolumeOff, "Mute", Modifier.size(28.dp)) }
            IconButton(onClick = { sound("up") }) { Icon(Icons.Filled.VolumeUp, "Louder", Modifier.size(32.dp)) }
        }
        volume?.let {
            if (!it.isNull("percent")) Muted(if (it.optBoolean("muted")) "Muted" else "Volume ${it.optInt("percent")}%")
        }
    }
}

// --------------------------------------------------------------- presenter

@Composable
fun PresenterPage(activity: MainActivity, client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val input = remember { InputSocket(client) }
    var elapsed by remember { mutableIntStateOf(0) }
    var running by remember { mutableStateOf(false) }

    // Live presentation state
    var deckTitle by remember { mutableStateOf("Presentation") }
    var currentSlide by remember { mutableIntStateOf(1) }
    var totalSlides by remember { mutableIntStateOf(0) }
    var slideTitle by remember { mutableStateOf("") }
    var keypoints by remember { mutableStateOf(listOf<String>()) }
    var notesText by remember { mutableStateOf("") }
    var nextTitle by remember { mutableStateOf("") }
    var availableDecks by remember { mutableStateOf(listOf<JSONObject>()) }

    var showDeckDialog by remember { mutableStateOf(false) }
    var showJumpDialog by remember { mutableStateOf(false) }
    var showEditNotesDialog by remember { mutableStateOf(false) }
    var editedNotes by remember { mutableStateOf("") }
    val notesScrollState = rememberScrollState()

    fun applyState(json: JSONObject?) {
        if (json == null) return
        val titleStr = json.optString("title")
        if (titleStr.isNotBlank()) deckTitle = titleStr
        val cur = json.optInt("current_slide", 0)
        if (cur > 0) currentSlide = cur
        val total = json.optInt("total_slides", 0)
        if (total > 0) totalSlides = total

        val slide = json.optJSONObject("slide")
        if (slide != null) {
            slideTitle = slide.optString("title")
            notesText = slide.optString("notes")
            val kpArray = slide.optJSONArray("keypoints")
            val kps = mutableListOf<String>()
            if (kpArray != null) {
                for (i in 0 until kpArray.length()) {
                    val s = kpArray.optString(i)
                    if (s.isNotBlank()) kps.add(s)
                }
            }
            keypoints = kps
        } else {
            slideTitle = ""
            notesText = ""
            keypoints = emptyList()
        }

        val nextSlide = json.optJSONObject("next_slide")
        nextTitle = nextSlide?.optString("title") ?: ""

        val decksArray = json.optJSONArray("available_decks")
        if (decksArray != null) {
            val decks = mutableListOf<JSONObject>()
            for (i in 0 until decksArray.length()) {
                decksArray.optJSONObject(i)?.let { decks.add(it) }
            }
            availableDecks = decks
        }
    }

    fun act(action: String, slideNum: Int? = null) {
        scope.launch(Dispatchers.IO) {
            val body = JSONObject().put("action", action)
            if (slideNum != null) body.put("slide", slideNum)
            val res = client.post("/v1/presenter/action", body)
            withContext(Dispatchers.Main) {
                applyState(res)
            }
        }
    }

    fun onNext() {
        running = true
        if (totalSlides > 0 && currentSlide < totalSlides) {
            currentSlide += 1
        }
        input.send(Protocol.key("Right"))
        act("next")
    }

    fun onPrev() {
        if (currentSlide > 1) {
            currentSlide -= 1
        }
        input.send(Protocol.key("Left"))
        act("prev")
    }

    fun onStart() {
        running = true
        input.send(Protocol.key("F5"))
        act("start")
    }

    fun onBlank() {
        input.send(Protocol.key("b"))
        act("blank")
    }

    fun onExit() {
        running = false
        input.send(Protocol.key("Escape"))
        act("exit")
    }

    DisposableEffect(Unit) {
        // Keep screen awake while presenting, and volume keys advance/rewind slides
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        activity.volumeKeys = { up -> if (up) onPrev() else onNext() }
        val stop = client.watch.subscribe("presenter") { told ->
            scope.launch(Dispatchers.Main) {
                applyState(told)
            }
        }
        onDispose {
            activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            activity.volumeKeys = null
            stop()
            input.close()
        }
    }

    LaunchedEffect(Unit) {
        val res = client.get("/v1/presenter")
        applyState(res)
    }

    LaunchedEffect(running) {
        while (running) {
            delay(1000)
            elapsed += 1
        }
    }

    TopBar("Presenter", onBack) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { act("detect") }) {
                Icon(Icons.Filled.Refresh, "Detect active presentation", tint = Color(0xFFF5F5F7))
            }
            IconButton(onClick = { showDeckDialog = true }) {
                Icon(Icons.Filled.Layers, "Choose presentation deck", tint = Color(0xFF0A84FF))
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        // --- 1. Compact Header: Deck Info, Elapsed Timer, & Slide Pill ---
        Box(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Color(0xFF1C1C1E))
                .border(0.5.dp, Color(0x22FFFFFF), RoundedCornerShape(16.dp))
                .padding(horizontal = 14.dp, vertical = 10.dp)
        ) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        deckTitle,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        color = Color(0xFF8E8E93),
                        maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            Protocol.formatDuration(elapsed),
                            fontSize = 24.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color(0xFFF5F5F7)
                        )
                        Spacer(Modifier.width(8.dp))
                        Box(
                            Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .background(if (running) Color(0xFF30D158).copy(alpha = 0.18f) else Color(0x18FFFFFF))
                                .padding(horizontal = 6.dp, vertical = 2.dp)
                        ) {
                            Text(
                                if (running) "● Live" else "○ Paused",
                                fontSize = 11.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = if (running) Color(0xFF30D158) else Color(0xFF8E8E93)
                            )
                        }
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    // Slide Jump Pill
                    Box(
                        Modifier
                            .clip(RoundedCornerShape(10.dp))
                            .background(Color(0xFF0A84FF).copy(alpha = 0.20f))
                            .clickable { showJumpDialog = true }
                            .padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Text(
                            if (totalSlides > 0) "Slide $currentSlide of $totalSlides  ▾" else "Slide $currentSlide  ▾",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color(0xFF0A84FF)
                        )
                    }

                    // Timer Play/Pause
                    IconButton(
                        onClick = {
                            running = !running
                            act("timer")
                        },
                        modifier = Modifier.size(34.dp)
                    ) {
                        Icon(
                            if (running) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                            contentDescription = if (running) "Pause timer" else "Start timer",
                            tint = Color(0xFFF5F5F7),
                            modifier = Modifier.size(18.dp)
                        )
                    }
                }
            }
        }

        // --- 2. Middle Teleprompter Card (SCROLLABLE, fills available space) ---
        Box(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .clip(RoundedCornerShape(20.dp))
                .background(Color(0xFF1C1C1E))
                .border(0.5.dp, Color(0x22FFFFFF), RoundedCornerShape(20.dp))
                .padding(14.dp)
        ) {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(notesScrollState),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                // Header row: Badge + Edit Notes Button
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        "SLIDE $currentSlide NOTES & KEYPOINTS",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.sp,
                        color = Color(0xFF0A84FF)
                    )
                    IconButton(
                        onClick = {
                            editedNotes = notesText
                            showEditNotesDialog = true
                        },
                        modifier = Modifier.size(28.dp)
                    ) {
                        Icon(Icons.Filled.Edit, "Edit notes", tint = Color(0xFF8E8E93), modifier = Modifier.size(15.dp))
                    }
                }

                if (slideTitle.isNotBlank()) {
                    Text(
                        slideTitle,
                        fontSize = 19.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color(0xFFF5F5F7),
                        lineHeight = 24.sp
                    )
                }

                // Scannable Key Points
                if (keypoints.isNotEmpty()) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        keypoints.forEach { point ->
                            Row(verticalAlignment = Alignment.Top) {
                                Box(
                                    Modifier
                                        .padding(top = 7.dp, end = 8.dp)
                                        .size(6.dp)
                                        .clip(CircleShape)
                                        .background(Color(0xFF0A84FF))
                                )
                                Text(
                                    point,
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = Color(0xFFF5F5F7),
                                    lineHeight = 21.sp
                                )
                            }
                        }
                    }
                } else if (notesText.isNotBlank()) {
                    Text(
                        notesText,
                        fontSize = 15.sp,
                        color = Color(0xFFF5F5F7),
                        lineHeight = 21.sp
                    )
                } else {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 14.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            "No speaker notes for this slide.\nTap edit icon above to add key talking points.",
                            color = Color(0xFF8E8E93),
                            fontSize = 13.sp,
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center
                        )
                    }
                }

                // Verbatim full notes if lengthy and different
                if (notesText.isNotBlank() && keypoints.isNotEmpty() && notesText.length > 80) {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(Color(0x18FFFFFF))
                            .padding(10.dp)
                    ) {
                        Column {
                            Text(
                                "FULL SPEAKER NOTES",
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFF8E8E93)
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                notesText,
                                fontSize = 13.sp,
                                color = Color(0xFFD1D1D6),
                                lineHeight = 18.sp
                            )
                        }
                    }
                }

                // Up Next Preview
                if (nextTitle.isNotBlank()) {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(Color(0x12FFFFFF))
                            .border(0.5.dp, Color(0x22FFFFFF), RoundedCornerShape(12.dp))
                            .padding(horizontal = 12.dp, vertical = 8.dp)
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "NEXT  ▸",
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFF0A84FF),
                                modifier = Modifier.padding(end = 6.dp)
                            )
                            Text(
                                nextTitle,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                                color = Color(0xFFE5E5EA),
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                            )
                        }
                    }
                }
            }
        }

        // --- 3. Bottom Controls Dock (FIXED, NON-SCROLLING, ZERO GESTURE CONTENTION) ---
        Column(
            Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            // Hero Next Slide Button (Large Apple Blue Surface)
            Surface(
                onClick = { onNext() },
                modifier = Modifier.fillMaxWidth().height(68.dp),
                shape = RoundedCornerShape(18.dp),
                color = Color(0xFF0A84FF),
                shadowElevation = 4.dp
            ) {
                Row(
                    Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "Next Slide  ▸",
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        fontSize = 20.sp
                    )
                }
            }

            // Previous & Jump Row
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Surface(
                    onClick = { onPrev() },
                    modifier = Modifier.weight(1.3f).height(50.dp),
                    shape = RoundedCornerShape(14.dp),
                    color = Color(0xFF2C2C2E)
                ) {
                    Row(
                        Modifier.fillMaxSize(),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "◂  Previous",
                            color = Color(0xFFF5F5F7),
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 15.sp
                        )
                    }
                }

                Surface(
                    onClick = { showJumpDialog = true },
                    modifier = Modifier.weight(0.9f).height(50.dp),
                    shape = RoundedCornerShape(14.dp),
                    color = Color(0xFF2C2C2E)
                ) {
                    Row(
                        Modifier.fillMaxSize(),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "Jump  ⚏",
                            color = Color(0xFFF5F5F7),
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 15.sp
                        )
                    }
                }
            }

            // Start (F5), Blank (B), End (Esc) Quick Row
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Surface(
                    onClick = { onStart() },
                    modifier = Modifier.weight(1f).height(44.dp),
                    shape = RoundedCornerShape(12.dp),
                    color = Color(0xFF2C2C2E)
                ) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("Start (F5)", color = Color(0xFF30D158), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    }
                }

                Surface(
                    onClick = { onBlank() },
                    modifier = Modifier.weight(1f).height(44.dp),
                    shape = RoundedCornerShape(12.dp),
                    color = Color(0xFF2C2C2E)
                ) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("Blank (B)", color = Color(0xFFE5E5EA), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    }
                }

                Surface(
                    onClick = { onExit() },
                    modifier = Modifier.weight(1f).height(44.dp),
                    shape = RoundedCornerShape(12.dp),
                    color = Color(0xFF2C2C2E)
                ) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("End (Esc)", color = Color(0xFFFF453A), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                    }
                }
            }

            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text(
                    "Volume keys also advance & rewind slides",
                    color = Color(0xFF8E8E93),
                    fontSize = 11.sp
                )
            }
        }
    }

    // --- Modal: Deck Picker Dialog ---
    if (showDeckDialog) {
        AlertDialog(
            onDismissRequest = { showDeckDialog = false },
            title = { Text("Select Presentation Deck", fontWeight = FontWeight.Bold) },
            text = {
                Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "Decks detected on computer:",
                        fontSize = 13.sp,
                        color = Color(0xFF8E8E93)
                    )
                    if (availableDecks.isEmpty()) {
                        Text("No presentations found in ~/presentation or Documents.", color = Color(0xFF8E8E93))
                    } else {
                        availableDecks.forEach { deck ->
                            val path = deck.optString("path")
                            val name = deck.optString("name")
                            val type = deck.optString("type", "PPT")
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(Color(0x18FFFFFF))
                                    .clickable {
                                        scope.launch {
                                            client.post("/v1/presenter/deck", JSONObject().put("path", path))?.let {
                                                applyState(it)
                                            }
                                        }
                                        showDeckDialog = false
                                    }
                                    .padding(10.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Box(
                                    Modifier
                                        .clip(RoundedCornerShape(4.dp))
                                        .background(Color(0xFF0A84FF))
                                        .padding(horizontal = 6.dp, vertical = 2.dp)
                                ) {
                                    Text(type, fontSize = 10.sp, fontWeight = FontWeight.Bold, color = Color.White)
                                }
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    name,
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = Color(0xFFF5F5F7),
                                    maxLines = 1,
                                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis
                                )
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    act("detect")
                    showDeckDialog = false
                }) { Text("Re-scan Active Window") }
            },
            dismissButton = {
                TextButton(onClick = { showDeckDialog = false }) { Text("Close") }
            }
        )
    }

    // --- Modal: Jump to Slide Dialog ---
    if (showJumpDialog) {
        val total = if (totalSlides > 0) totalSlides else 30
        AlertDialog(
            onDismissRequest = { showJumpDialog = false },
            title = { Text("Jump to Slide", fontWeight = FontWeight.Bold) },
            text = {
                Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Select a slide to jump directly (1 to $total):", fontSize = 13.sp, color = Color(0xFF8E8E93))
                    val jumpScroll = rememberScrollState()
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .height(240.dp)
                            .verticalScroll(jumpScroll),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        val chunks = (1..total).chunked(5)
                        chunks.forEach { rowItems ->
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                rowItems.forEach { num ->
                                    val isCurrent = num == currentSlide
                                    Surface(
                                        onClick = {
                                            act("goto", num)
                                            showJumpDialog = false
                                        },
                                        modifier = Modifier.size(46.dp),
                                        shape = CircleShape,
                                        color = if (isCurrent) Color(0xFF0A84FF) else Color(0x22FFFFFF)
                                    ) {
                                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                            Text(
                                                "$num",
                                                fontWeight = FontWeight.Bold,
                                                color = Color(0xFFF5F5F7),
                                                fontSize = 14.sp
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showJumpDialog = false }) { Text("Close") }
            }
        )
    }

    // --- Modal: Edit Slide Notes Dialog ---
    if (showEditNotesDialog) {
        AlertDialog(
            onDismissRequest = { showEditNotesDialog = false },
            title = { Text("Edit Slide $currentSlide Notes", fontWeight = FontWeight.Bold) },
            text = {
                Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Keypoints & speaking notes for this slide:", fontSize = 13.sp, color = Color(0xFF8E8E93))
                    OutlinedTextField(
                        value = editedNotes,
                        onValueChange = { editedNotes = it },
                        modifier = Modifier.fillMaxWidth().height(160.dp),
                        placeholder = { Text("Enter talking points...") }
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        client.post(
                            "/v1/presenter/notes",
                            JSONObject().put("slide", currentSlide).put("notes", editedNotes)
                        )?.let { applyState(it) }
                    }
                    showEditNotesDialog = false
                }) { Text("Save Notes") }
            },
            dismissButton = {
                TextButton(onClick = { showEditNotesDialog = false }) { Text("Cancel") }
            }
        )
    }
}
