package com.karthi.adaptivelink

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.view.WindowManager
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FastForward
import androidx.compose.material.icons.filled.FastRewind
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
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

@Composable
fun ScreenPage(client: LinkClient, store: Store, onBack: () -> Unit) {
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

    DisposableEffect(quality) {
        val opened = client.socket("/v1/screen?preset=$quality", object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                BitmapFactory.decodeByteArray(bytes.toByteArray(), 0, bytes.size)?.let {
                    frame = it
                    note = ""
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                note = if (response?.code == 503) "The computer has no screen to show" else "Connection lost"
            }
        })
        socket = opened
        onDispose { opened.close(1000, null) }
    }

    fun send(event: String) { socket?.send(event) }
    fun at(offset: Offset): Pair<Float, Float>? =
        frame?.let { touchToScreen(unzoomed(offset, box, zoom, shift), box, IntSize(it.width, it.height)) }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Screen", onBack) {
            listOf("low", "medium", "high").forEach { name ->
                FilterChip(
                    selected = quality == name, onClick = { quality = name; store.screenQuality = name },
                    label = { Text(name.take(1).uppercase()) }, modifier = Modifier.padding(end = 4.dp),
                )
            }
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
            frame?.let {
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
        }
        if (scrolling) Muted("Scroll mode: drag up and down to scroll", Modifier.padding(8.dp))
        if (keyboard) KeyboardBar(::send)
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
fun TrackpadPage(client: LinkClient, onBack: () -> Unit) {
    val input = remember { InputSocket(client) }
    DisposableEffect(Unit) { onDispose { input.close() } }
    var keyboard by remember { mutableStateOf(true) }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Trackpad", onBack) {
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
            if (current.optInt("length") > 0) {
                Spacer(Modifier.height(6.dp))
                Muted("${Protocol.formatDuration(current.optInt("position"))} / ${Protocol.formatDuration(current.optInt("length"))}")
            }
            Spacer(Modifier.height(28.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                IconButton(onClick = { act("previous") }) { Icon(Icons.Filled.SkipPrevious, "Previous", Modifier.size(34.dp)) }
                IconButton(onClick = { act("seek", -10) }) { Icon(Icons.Filled.FastRewind, "Back 10 seconds", Modifier.size(30.dp)) }
                FilledIconButton(onClick = { act("play-pause") }, modifier = Modifier.size(76.dp)) {
                    val playing = current.optString("status") == "Playing"
                    Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, "Play or pause", Modifier.size(44.dp))
                }
                IconButton(onClick = { act("seek", 10) }) { Icon(Icons.Filled.FastForward, "Forward 10 seconds", Modifier.size(30.dp)) }
                IconButton(onClick = { act("next") }) { Icon(Icons.Filled.SkipNext, "Next", Modifier.size(34.dp)) }
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
    val input = remember { InputSocket(client) }
    var elapsed by remember { mutableIntStateOf(0) }
    var running by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        // The screen stays on while presenting, and the volume buttons turn
        // the pages, so the phone can be held without looking at it.
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        activity.volumeKeys = { up -> input.send(Protocol.key(if (up) "Left" else "Right")) }
        onDispose {
            activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            activity.volumeKeys = null
            input.close()
        }
    }
    LaunchedEffect(running) { while (running) { delay(1000); elapsed += 1 } }

    TopBar("Presenter", onBack)
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(Protocol.formatDuration(elapsed), fontSize = 44.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            AssistChip(onClick = { running = !running }, label = { Text(if (running) "Pause" else "Start timer") })
            Spacer(Modifier.width(8.dp))
            AssistChip(onClick = { elapsed = 0; running = false }, label = { Text("Reset") })
        }
        BigButton("Next", Modifier.fillMaxWidth().weight(2f), height = 240) {
            running = true
            input.send(Protocol.key("Right"))
        }
        BigButton("Previous", Modifier.fillMaxWidth().weight(1f), height = 120) { input.send(Protocol.key("Left")) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BigButton("Start (F5)", Modifier.weight(1f)) { input.send(Protocol.key("F5")) }
            BigButton("Blank", Modifier.weight(1f)) { input.send(Protocol.key("b")) }
            BigButton("End (Esc)", Modifier.weight(1f)) { input.send(Protocol.key("Escape")) }
        }
        Muted("The volume buttons also go to the next and previous slide.")
    }
}
