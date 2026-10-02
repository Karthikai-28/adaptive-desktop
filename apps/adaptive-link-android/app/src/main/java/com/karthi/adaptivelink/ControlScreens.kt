package com.karthi.adaptivelink

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.Uri
import android.nfc.NdefMessage
import android.nfc.NdefRecord
import android.nfc.NfcAdapter
import android.nfc.tech.Ndef
import android.os.Bundle
import android.speech.RecognizerIntent
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import kotlin.math.roundToInt

/**
 * The owner's own controls: a page of buttons they make themselves, a game
 * pad, the phone waved as a pointer, and speaking instead of typing.
 */

// ---------------------------------------------------------- doing a button

/** Press one of the owner's buttons. Returns what to say. */
suspend fun press(context: Context, client: LinkClient, control: Control): String = when (control.kind) {
    "action" -> QuickActions.run(context, control.value)
    "keys", "text" -> {
        val event = if (control.kind == "keys") Protocol.keys(control.value) else Protocol.text(control.value)
        if (event == null) "Not a key" else withContext(Dispatchers.IO) {
            // One socket for one press: opened, used, closed.
            val sent = kotlinx.coroutines.CompletableDeferred<Boolean>()
            val socket = client.socket("/v1/input", object : okhttp3.WebSocketListener() {
                override fun onOpen(webSocket: okhttp3.WebSocket, response: okhttp3.Response) {
                    webSocket.send(event)
                    webSocket.close(1000, null)
                    sent.complete(true)
                }

                override fun onFailure(webSocket: okhttp3.WebSocket, t: Throwable, response: okhttp3.Response?) {
                    sent.complete(false)
                }
            })
            val went = kotlinx.coroutines.withTimeoutOrNull(8000) { sent.await() } ?: false
            if (!went) socket.cancel()
            if (went) control.label else "The computer did not take it"
        }
    }
    "command" -> withContext(Dispatchers.IO) {
        val started = kotlinx.coroutines.CompletableDeferred<String>()
        val socket = client.socket("/v1/exec", object : okhttp3.WebSocketListener() {
            override fun onOpen(webSocket: okhttp3.WebSocket, response: okhttp3.Response) {
                webSocket.send(JSONObject().put("cmd", control.value).put("cwd", "~").put("detach", true).toString())
            }

            override fun onMessage(webSocket: okhttp3.WebSocket, text: String) {
                started.complete(if (JSONObject(text).has("started")) "${control.label}: started" else "It did not start")
            }

            override fun onFailure(webSocket: okhttp3.WebSocket, t: Throwable, response: okhttp3.Response?) {
                started.complete(if (response?.code == 403) "Commands are turned off on the computer" else "Cannot reach the computer")
            }
        })
        kotlinx.coroutines.withTimeoutOrNull(10_000) { started.await() } ?: "The computer did not answer".also { socket.cancel() }
    }
    else -> "Unknown"
}

// ---------------------------------------------------------------- controls

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ControlsPage(activity: MainActivity, client: LinkClient, store: Store, onBack: () -> Unit, onGamepad: () -> Unit) {
    val scope = rememberCoroutineScope()
    var controls by remember { mutableStateOf(store.controls) }
    var said by remember { mutableStateOf("") }
    var adding by remember { mutableStateOf(false) }
    var chosen by remember { mutableStateOf<Control?>(null) }
    var writing by remember { mutableStateOf<Control?>(null) }

    Column(Modifier.fillMaxSize()) {
        TopBar("Controls", onBack) {
            TextButton(onClick = onGamepad) { Text("Game pad") }
            IconButton(onClick = { adding = true }) { Icon(Icons.Filled.Add, "Add a button") }
        }
        Column(Modifier.padding(horizontal = 14.dp)) {
            if (said.isNotEmpty()) Muted(said, Modifier.padding(bottom = 6.dp))
            if (controls.isEmpty()) Muted("A page of buttons of your own: a command to run, keys to press, text to type, or lock, play and focus. Add one with +. Hold a button to change or remove it.")
            LazyVerticalGrid(
                columns = GridCells.Adaptive(104.dp), horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(vertical = 8.dp),
            ) {
                items(controls) { control ->
                    Box(
                        Modifier.aspectRatio(1.25f).clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surface)
                            .combinedClickable(
                                onClick = { scope.launch { said = press(activity, client, control) } },
                                onLongClick = { chosen = control },
                            ).padding(10.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(control.label, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center, maxLines = 2)
                            Muted(control.kind)
                        }
                    }
                }
            }
        }
    }

    if (adding) AddControl(onDismiss = { adding = false }) { made ->
        controls = (controls + made).take(Control.LIMIT)
        store.controls = controls
        adding = false
    }

    chosen?.let { control ->
        AlertDialog(
            onDismissRequest = { chosen = null },
            title = { Text(control.label) },
            text = {
                Column {
                    Muted(control.kind)
                    Text(control.value, fontFamily = FontFamily.Monospace, fontSize = 12.sp, maxLines = 6)
                }
            },
            confirmButton = {
                Row {
                    if (NfcAdapter.getDefaultAdapter(activity) != null) {
                        TextButton(onClick = { writing = control; chosen = null }) { Text("Write to a tag") }
                    }
                    TextButton(onClick = { controls = controls - control; store.controls = controls; chosen = null }) {
                        Text("Remove", color = MaterialTheme.colorScheme.error)
                    }
                }
            },
            dismissButton = { TextButton(onClick = { chosen = null }) { Text("Close") } },
        )
    }

    writing?.let { control ->
        // Held to the phone, the tag is given this button: tapping it later presses the button.
        DisposableEffect(control) {
            val adapter = NfcAdapter.getDefaultAdapter(activity)
            adapter?.enableReaderMode(activity, { tag ->
                val wrote = runCatching {
                    val ndef = Ndef.get(tag) ?: error("not a tag that can be written")
                    ndef.connect()
                    ndef.writeNdefMessage(NdefMessage(NdefRecord.createUri(TagLink.forControl(store, control))))
                    ndef.close()
                }.isSuccess
                activity.runOnUiThread {
                    said = if (wrote) "The tag now presses “${control.label}”." else "That tag could not be written."
                    writing = null
                }
            }, NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_NFC_B or NfcAdapter.FLAG_READER_NFC_F or
                NfcAdapter.FLAG_READER_NFC_V, null)
            onDispose { adapter?.disableReaderMode(activity) }
        }
        AlertDialog(
            onDismissRequest = { writing = null },
            title = { Text("Hold a tag to the phone") },
            text = { Text("The tag will press “${control.label}” whenever this phone touches it. Anyone who can read the tag can copy what is on it, but only this phone can use it.") },
            confirmButton = { TextButton(onClick = { writing = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun AddControl(onDismiss: () -> Unit, onAdd: (Control) -> Unit) {
    var label by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("command") }
    var value by remember { mutableStateOf("") }
    val hint = mapOf("command" to "A command, started and left running", "keys" to "Keys, like ctrl+alt+t or F5",
        "text" to "Text to type", "action" to "lock, play-pause, next, mute or focus")
    val valid = label.isNotBlank() && value.isNotBlank() && when (kind) {
        "keys" -> Protocol.keys(value) != null
        "action" -> value.trim() in QuickActions.NAMES
        else -> true
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("A new button") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = label, onValueChange = { label = it.take(24) }, singleLine = true,
                    placeholder = { Text("What the button says") }, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Control.KINDS.forEach { name ->
                        FilterChip(selected = kind == name, onClick = { kind = name }, label = { Text(name.replaceFirstChar { it.uppercase() }) })
                    }
                }
                OutlinedTextField(value = value, onValueChange = { value = it }, singleLine = kind != "text",
                    placeholder = { Text(hint[kind].orEmpty()) }, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { TextButton(enabled = valid, onClick = { onAdd(Control(label.trim(), kind, value.trim())) }) { Text("Add") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

// ---------------------------------------------------------------- game pad

/** A round stick that holds down up to two of four keys, by where it is pushed. */
@Composable
private fun Stick(input: InputSocket, up: String, down: String, left: String, right: String, modifier: Modifier = Modifier) {
    var size by remember { mutableStateOf(IntSize.Zero) }
    var thumb by remember { mutableStateOf(Offset.Zero) }
    var held by remember { mutableStateOf(setOf<String>()) }

    fun hold(now: Set<String>) {
        (held - now).forEach { input.send(Protocol.hold(it, false)) }
        (now - held).forEach { input.send(Protocol.hold(it, true)) }
        held = now
    }
    DisposableEffect(Unit) { onDispose { hold(emptySet()) } }

    Box(
        modifier.aspectRatio(1f).clip(CircleShape).background(MaterialTheme.colorScheme.surface).onSizeChanged { size = it }
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown()
                    do {
                        val event = awaitPointerEvent()
                        val at = event.changes.firstOrNull { it.pressed }?.position
                        if (at != null && size.width > 0) {
                            val x = ((at.x / size.width) * 2 - 1).coerceIn(-1f, 1f)
                            val y = ((at.y / size.height) * 2 - 1).coerceIn(-1f, 1f)
                            thumb = Offset(x, y)
                            hold(Protocol.stickKeys(x, y, up, down, left, right))
                        }
                        event.changes.forEach { it.consume() }
                    } while (event.changes.any { it.pressed })
                    thumb = Offset.Zero
                    hold(emptySet())
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.offset { IntOffset((thumb.x * size.width * 0.3f).roundToInt(), (thumb.y * size.height * 0.3f).roundToInt()) }
                .size(56.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary)
        )
    }
}

/** A button that holds a key down for as long as it is pressed. */
@Composable
private fun HeldKey(input: InputSocket, label: String, key: String, modifier: Modifier = Modifier) {
    DisposableEffect(key) { onDispose { input.send(Protocol.hold(key, false)) } }
    Box(
        modifier.size(68.dp).clip(CircleShape).background(MaterialTheme.colorScheme.surface)
            .pointerInput(key) {
                detectTapGestures(onPress = {
                    input.send(Protocol.hold(key, true))
                    tryAwaitRelease()
                    input.send(Protocol.hold(key, false))
                })
            },
        contentAlignment = Alignment.Center,
    ) { Text(label, fontWeight = FontWeight.SemiBold) }
}

@Composable
fun GamepadPage(client: LinkClient, onBack: () -> Unit) {
    val input = remember { InputSocket(client) }
    DisposableEffect(Unit) { onDispose { input.close() } }
    var arrows by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        TopBar("Game pad", onBack) {
            FilterChip(selected = !arrows, onClick = { arrows = false }, label = { Text("WASD") }, modifier = Modifier.padding(end = 4.dp))
            FilterChip(selected = arrows, onClick = { arrows = true }, label = { Text("Arrows") }, modifier = Modifier.padding(end = 8.dp))
        }
        Muted("The stick holds the movement keys; each button holds its key for as long as it is pressed.",
            Modifier.padding(horizontal = 14.dp))
        Row(Modifier.fillMaxSize().padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            if (arrows) Stick(input, "Up", "Down", "Left", "Right", Modifier.weight(1f))
            else Stick(input, "w", "s", "a", "d", Modifier.weight(1f))
            Spacer(Modifier.size(18.dp))
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                HeldKey(input, "Y", "q")
                Row(horizontalArrangement = Arrangement.spacedBy(46.dp)) {
                    HeldKey(input, "X", "e")
                    HeldKey(input, "B", "shift")
                }
                HeldKey(input, "A", "space")
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    HeldKey(input, "Esc", "Escape")
                    HeldKey(input, "⏎", "Return")
                }
            }
        }
    }
}

// --------------------------------------------------------------- air mouse

/**
 * While this is on screen, turning the phone moves the computer's pointer,
 * the way a laser pointer is aimed.
 */
@Composable
fun AirMouse(send: (String) -> Unit) {
    val context = LocalContext.current
    DisposableEffect(Unit) {
        val sensors = context.getSystemService(SensorManager::class.java)
        val gyroscope = sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        var carriedX = 0f
        var carriedY = 0f
        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                // Turning about the phone's upright axis moves across; tilting it moves up and down.
                carriedX += -event.values[2] * AIR_SPEED
                carriedY += -event.values[0] * AIR_SPEED
                val dx = carriedX.toInt()
                val dy = carriedY.toInt()
                if (dx != 0 || dy != 0) {
                    send(Protocol.relative(dx.toFloat(), dy.toFloat()))
                    carriedX -= dx
                    carriedY -= dy
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }
        if (gyroscope != null) sensors.registerListener(listener, gyroscope, SensorManager.SENSOR_DELAY_GAME)
        onDispose { sensors.unregisterListener(listener) }
    }
}

private const val AIR_SPEED = 14f

fun hasGyroscope(context: Context): Boolean =
    context.getSystemService(SensorManager::class.java).getDefaultSensor(Sensor.TYPE_GYROSCOPE) != null

// ------------------------------------------------------------------- voice

/** A button that listens, and hands over what was said. */
@Composable
fun Dictate(onSaid: (String) -> Unit) {
    val context = LocalContext.current
    val listen = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val heard = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (result.resultCode == Activity.RESULT_OK && !heard.isNullOrBlank()) onSaid(heard)
    }
    IconButton(onClick = {
        (context as? MainActivity)?.awayOnPurpose = true
        runCatching {
            listen.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM))
        }.onFailure { Toast.makeText(context, "This phone has nothing that turns speech into text", Toast.LENGTH_SHORT).show() }
    }) { Icon(Icons.Filled.Mic, "Speak") }
}

// -------------------------------------------------------------------- tags

/**
 * What a tag, or a link, can ask of this app: one of the one-tap actions
 * (harmless, so anything may ask), or one of the owner's own buttons - which
 * only a tag this app wrote can press, because it carries a secret nothing
 * else on the phone knows.
 */
object TagLink {
    const val SCHEME = "adaptivelink"

    fun forControl(store: Store, control: Control): Uri = Uri.Builder().scheme(SCHEME).authority("do").appendPath("control")
        .appendPath(control.label).appendQueryParameter("k", store.tagSecret).build()

    /** What the link asks for, as a button to press, or null if it may not. */
    fun control(store: Store, uri: Uri?): Control? {
        if (uri == null || uri.scheme != SCHEME || uri.authority != "do") return null
        val parts = uri.pathSegments
        return when {
            parts.size == 1 && parts[0] in QuickActions.NAMES -> Control(parts[0], "action", parts[0])
            parts.size == 2 && parts[0] == "control" && uri.getQueryParameter("k") == store.tagSecret ->
                store.controls.firstOrNull { it.label == parts[1] }
            else -> null
        }
    }
}

/** A tag was touched, or a link of this app's was opened: press the button it names. */
class TagActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = Store(this)
        val control = TagLink.control(store, intent?.data)
        val client = Link.client(this)
        val app = applicationContext
        if (control == null || client == null) {
            Toast.makeText(app, if (client == null) "Not paired with a computer" else "This tag is not one of this phone's", Toast.LENGTH_SHORT).show()
        } else CoroutineScope(Dispatchers.IO).launch {
            val said = runCatching {
                if (client.host == null && client.connect() == null) "Cannot reach ${client.computer.name}" else press(app, client, control)
            }.getOrDefault("It did not work")
            withContext(Dispatchers.Main) { Toast.makeText(app, said, Toast.LENGTH_SHORT).show() }
        }
        finish()
    }
}
