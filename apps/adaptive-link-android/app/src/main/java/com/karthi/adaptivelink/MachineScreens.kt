package com.karthi.adaptivelink

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The rest of the machine: Bluetooth, the displays and the sound devices,
 * the owner's services, and the open windows. The computer's side is
 * services/adaptive-link/machine.py; each screen reads one part of it and
 * asks for one change at a time.
 */

/** One part of the machine, kept fresh while its screen is open, and a way to change it. */
private class Part(private val client: LinkClient, private val what: String, private val scope: CoroutineScope) {
    var now by mutableStateOf<JSONObject?>(null)
    var said by mutableStateOf("Looking…")
    var busy by mutableStateOf(false)

    suspend fun load() {
        val reply = client.get("/v1/machine/$what")
        val problem = refused(reply)
        if (problem != null) said = problem else {
            now = reply
            if (said == "Looking…") said = ""
        }
    }

    /**
     * Ask for a change. `guess` is how things will look if it works: shown
     * at once, so that a switch moves under the finger, and put right by
     * what the computer answers.
     */
    fun act(action: String, target: String = "", value: String = "", guess: ((JSONObject) -> Unit)? = null) {
        if (busy) return
        busy = true
        if (guess != null) now?.let { shown -> now = JSONObject(shown.toString()).also(guess) }
        scope.launch {
            val reply = client.post("/v1/machine/$what",
                JSONObject().put("action", action).put("target", target).put("value", value))
            said = refused(reply) ?: reply!!.optString("text")
            busy = false
            load()
        }
    }
}

@Composable
private fun rememberPart(client: LinkClient, what: String, every: Long): Part {
    val scope = rememberCoroutineScope()
    val part = remember(client, what) { Part(client, what, scope) }
    // Told by the computer whenever it changes...
    DisposableEffect(part) {
        val stop = client.watch.subscribe(what) { told ->
            if (!part.busy) {
                part.now = told
                if (part.said == "Looking…") part.said = ""
            }
        }
        onDispose { stop() }
    }
    // ...and asked for now and then all the same, should that telling stop.
    LaunchedEffect(part) {
        while (true) {
            if (!part.busy) part.load()
            delay(every * 4)
        }
    }
    return part
}

// --------------------------------------------------------------- bluetooth

@Composable
fun BluetoothPage(client: LinkClient, onBack: () -> Unit) {
    val part = rememberPart(client, "bluetooth", 4000)
    val now = part.now

    Column(Modifier.fillMaxSize()) {
        TopBar("Bluetooth", onBack)
        Column(Modifier.padding(horizontal = 14.dp).verticalScroll(rememberScrollState())) {
            if (part.said.isNotEmpty()) Muted(part.said, Modifier.padding(bottom = 6.dp))
            if (now != null && !now.optBoolean("available")) Muted("This computer has no Bluetooth.")
            if (now != null && now.optBoolean("available")) {
                val on = now.optBoolean("on")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Muted("Bluetooth on the computer", Modifier.weight(1f))
                    Switch(checked = on, enabled = !part.busy, onCheckedChange = { wanted ->
                        part.act("power", if (wanted) "on" else "off") { it.put("on", wanted) }
                    })
                }
                Heading("Devices")
                val devices = now.optJSONArray("devices").objects()
                if (devices.isEmpty()) Muted("The computer has not been paired with any device.")
                devices.forEach { device ->
                    val connected = device.optBoolean("connected")
                    Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(device.optString("name"), fontWeight = FontWeight.SemiBold)
                                Muted(listOf(device.optString("kind"), if (connected) "Connected" else "Not connected",
                                    if (device.isNull("battery")) "" else "Battery ${device.optInt("battery")}%")
                                    .filter { it.isNotBlank() }.joinToString(" · "))
                            }
                            OutlinedButton(enabled = on && !part.busy, onClick = {
                                part.said = if (connected) "" else "Connecting…"
                                part.act(if (connected) "disconnect" else "connect", device.optString("address"))
                            }) { Text(if (connected) "Disconnect" else "Connect") }
                        }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

// ------------------------------------------------------- display and sound

@Composable
private fun SoundDevice(part: Part, device: JSONObject, kind: String) {
    val name = device.optString("name")
    var level by remember(name, device.optInt("volume")) { mutableStateOf(device.optInt("volume").coerceIn(0, 100).toFloat()) }
    Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(device.optString("label"), fontWeight = FontWeight.SemiBold)
                    Muted(listOf(if (device.optBoolean("default")) "In use" else "", "${device.optInt("volume")}%",
                        if (device.optBoolean("muted")) "Muted" else "").filter { it.isNotBlank() }.joinToString(" · "))
                }
                if (!device.optBoolean("default")) {
                    OutlinedButton(enabled = !part.busy, onClick = { part.act("$kind-use", name) }) { Text("Use") }
                }
            }
            Slider(value = level, onValueChange = { level = it }, valueRange = 0f..100f,
                onValueChangeFinished = { part.act("$kind-volume", name, level.toInt().toString()) })
            Row(verticalAlignment = Alignment.CenterVertically) {
                Muted("Muted", Modifier.weight(1f))
                Switch(checked = device.optBoolean("muted"), enabled = !part.busy,
                    onCheckedChange = { part.act("$kind-mute", name, if (it) "on" else "off") })
            }
        }
    }
}

@Composable
fun DisplaySoundPage(client: LinkClient, onBack: () -> Unit) {
    val display = rememberPart(client, "display", 5000)
    val sound = rememberPart(client, "sound", 4000)
    // Turning a display off, or to a size it shows badly, is asked about first.
    var asking by remember { mutableStateOf<Triple<String, String, () -> Unit>?>(null) }

    Column(Modifier.fillMaxSize()) {
        TopBar("Display and sound", onBack)
        Column(Modifier.padding(horizontal = 14.dp).verticalScroll(rememberScrollState())) {
            listOf(display.said, sound.said).filter { it.isNotEmpty() }.distinct().forEach { Muted(it, Modifier.padding(bottom = 6.dp)) }

            Heading("Displays")
            display.now?.let { now ->
                if (!now.isNull("brightness")) {
                    var level by remember(now.optInt("brightness")) { mutableStateOf(now.optInt("brightness").toFloat()) }
                    Muted("Brightness ${level.toInt()}%")
                    Slider(value = level, onValueChange = { level = it }, valueRange = 1f..100f,
                        onValueChangeFinished = { display.act("brightness", "", level.toInt().toString()) })
                }
                val outputs = now.optJSONArray("outputs").objects()
                outputs.forEach { output ->
                    val name = output.optString("name")
                    val on = output.optBoolean("on")
                    Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                        Column {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(name, fontWeight = FontWeight.SemiBold)
                                    Muted(listOf(if (on) output.optString("mode") else "Off",
                                        if (output.optBoolean("primary")) "Main display" else "").filter { it.isNotBlank() }.joinToString(" · "))
                                }
                                Switch(checked = on, enabled = !display.busy, onCheckedChange = { wanted ->
                                    if (wanted) display.act("on", name)
                                    else asking = Triple("Turn $name off?", "Its windows move to another display.") { display.act("off", name) }
                                })
                            }
                            if (on) {
                                val modes = output.optJSONArray("modes")
                                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    if (modes != null) repeat(modes.length()) { index ->
                                        val mode = modes.optString(index)
                                        FilterChip(selected = mode == output.optString("mode"), enabled = !display.busy, onClick = {
                                            asking = Triple("Change $name to $mode?", "Whoever is at the computer sees the change at once.") {
                                                display.act("mode", name, mode)
                                            }
                                        }, label = { Text(mode) })
                                    }
                                }
                                if (!output.optBoolean("primary") && outputs.size > 1) {
                                    TextButton(enabled = !display.busy, onClick = { display.act("primary", name) }) { Text("Make it the main display") }
                                }
                            }
                        }
                    }
                }
            }

            sound.now?.let { now ->
                Heading("Sound comes out of")
                val outputs = now.optJSONArray("outputs").objects()
                if (outputs.isEmpty()) Muted("The computer has nothing to play sound through.")
                outputs.forEach { SoundDevice(sound, it, "output") }
                Heading("Microphone")
                val inputs = now.optJSONArray("inputs").objects()
                if (inputs.isEmpty()) Muted("The computer has no microphone.")
                inputs.forEach { SoundDevice(sound, it, "input") }
            }
            Spacer(Modifier.height(16.dp))
        }
    }

    asking?.let { (title, text, go) ->
        AlertDialog(
            onDismissRequest = { asking = null },
            title = { Text(title) },
            text = { Text(text) },
            confirmButton = { TextButton(onClick = { asking = null; go() }) { Text("Go ahead") } },
            dismissButton = { TextButton(onClick = { asking = null }) { Text("Cancel") } },
        )
    }
}

// ---------------------------------------------------------------- services

@Composable
fun ServicesPage(client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val part = rememberPart(client, "services", 5000)
    var query by remember { mutableStateOf("") }
    var chosen by remember { mutableStateOf<JSONObject?>(null) }
    var log by remember { mutableStateOf<Pair<String, String>?>(null) }
    val units = part.now?.optJSONArray("services").objects()
        .filter { it.optString("name").contains(query, ignoreCase = true) || it.optString("label").contains(query, ignoreCase = true) }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Services", onBack)
        Column(Modifier.padding(horizontal = 14.dp).weight(1f)) {
            OutlinedTextField(value = query, onValueChange = { query = it }, singleLine = true,
                placeholder = { Text("Find a service") }, modifier = Modifier.fillMaxWidth())
            if (part.said.isNotEmpty()) Muted(part.said, Modifier.padding(top = 6.dp))
            LazyColumn(Modifier.weight(1f).padding(top = 6.dp)) {
                items(units, key = { it.optString("name") }) { unit ->
                    Row(Modifier.fillMaxWidth().clickable { chosen = unit }.padding(vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(unit.optString("name").removeSuffix(".service"), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Muted(unit.optString("label"))
                        }
                        Text(
                            if (unit.optBoolean("failed")) "failed" else if (unit.optBoolean("running")) "running" else "stopped",
                            fontSize = 13.sp,
                            color = when {
                                unit.optBoolean("failed") -> MaterialTheme.colorScheme.error
                                unit.optBoolean("running") -> MaterialTheme.colorScheme.primary
                                else -> MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                    }
                }
            }
        }
    }

    chosen?.let { unit ->
        val name = unit.optString("name")
        fun act(action: String) { chosen = null; part.act(action, name) }
        AlertDialog(
            onDismissRequest = { chosen = null },
            title = { Text(name.removeSuffix(".service")) },
            text = {
                Column {
                    Text(unit.optString("label"))
                    Spacer(Modifier.height(6.dp))
                    Muted(unit.optString("state"))
                    if (unit.optBoolean("own")) Muted("This is Adaptive Link itself: it can be restarted from here, not stopped.")
                    TextButton(onClick = {
                        chosen = null
                        scope.launch {
                            val reply = client.get("/v1/machine/services/log?name=${java.net.URLEncoder.encode(name, "UTF-8")}")
                            log = name to (refused(reply) ?: reply!!.optString("text").ifBlank { "It has written nothing." })
                        }
                    }) { Text("What it last wrote") }
                }
            },
            confirmButton = {
                Row {
                    if (unit.optBoolean("running")) {
                        TextButton(onClick = { act("restart") }) { Text("Restart") }
                        if (!unit.optBoolean("own")) TextButton(onClick = { act("stop") }) { Text("Stop", color = MaterialTheme.colorScheme.error) }
                    } else TextButton(onClick = { act("start") }) { Text("Start") }
                }
            },
            dismissButton = { TextButton(onClick = { chosen = null }) { Text("Close") } },
        )
    }

    log?.let { (name, text) ->
        AlertDialog(
            onDismissRequest = { log = null },
            title = { Text(name.removeSuffix(".service")) },
            text = { Text(text, fontFamily = FontFamily.Monospace, fontSize = 11.sp, modifier = Modifier.verticalScroll(rememberScrollState())) },
            confirmButton = { TextButton(onClick = { log = null }) { Text("Close") } },
        )
    }
}

// ----------------------------------------------------------------- windows

@Composable
fun WindowsPage(client: LinkClient, onBack: () -> Unit) {
    val part = rememberPart(client, "windows", 3000)
    val windows = part.now?.optJSONArray("windows").objects()
    // While this phone is a display of the computer, a window can be sent to it.
    var mine by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        mine = client.get("/v1/machine/display")?.optJSONArray("made").objects().any { it.optBoolean("mine") }
    }

    Column(Modifier.fillMaxSize()) {
        TopBar("Windows", onBack)
        Column(Modifier.padding(horizontal = 14.dp).verticalScroll(rememberScrollState())) {
            if (part.said.isNotEmpty()) Muted(part.said, Modifier.padding(bottom = 6.dp))
            if (part.now != null && windows.isEmpty()) Muted("No windows are open on the computer.")
            windows.forEach { window ->
                val id = window.optLong("id").toString()
                Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                    Column {
                        Text(window.optString("title").ifBlank { window.optString("app") }, maxLines = 2,
                            overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.SemiBold)
                        Muted(listOf(window.optString("app"), if (window.optBoolean("active")) "In front" else "",
                            if (window.optBoolean("minimized")) "Minimised" else "").filter { it.isNotBlank() }.joinToString(" · "))
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(enabled = !part.busy, onClick = { part.act("show", id) }) { Text("Show") }
                            if (mine) OutlinedButton(enabled = !part.busy, onClick = {
                                scope.launch {
                                    val reply = client.post("/v1/machine/display", JSONObject().put("action", "bring").put("target", id))
                                    part.said = refused(reply) ?: "On this phone's display"
                                    part.load()
                                }
                            }) { Text("To this phone") }
                            OutlinedButton(enabled = !part.busy, onClick = { part.act("minimize", id) }) { Text("Minimise") }
                            OutlinedButton(enabled = !part.busy, onClick = { part.act("move", id, "left") }) { Text("◀ display") }
                            OutlinedButton(enabled = !part.busy, onClick = { part.act("move", id, "right") }) { Text("display ▶") }
                            OutlinedButton(enabled = !part.busy, onClick = { part.act("close", id) }) {
                                Text("Close", color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}
