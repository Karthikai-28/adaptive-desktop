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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * The machine itself and the desktop's own features: what is running, what
 * is plugged in, how it is connected, and the things Adaptive Desktop adds (projects, focus,
 * window placement, notes). The computer's side is services/adaptive-link/
 * system.py.
 */

private fun JSONArray?.objects(): List<JSONObject> =
    if (this == null) emptyList() else List(length()) { optJSONObject(it) }.filterNotNull()

private fun refused(reply: JSONObject?): String? = when {
    reply == null -> "The computer did not answer."
    reply.has("error") && reply.optString("error").isNotEmpty() && !reply.optBoolean("ok", false) -> reply.optString("error")
    else -> null
}

@Composable
private fun Heading(text: String) {
    Text(text, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 14.dp, bottom = 6.dp))
}

// -------------------------------------------------------------------- tasks

@Composable
fun TasksPage(client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var byMemory by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    var summary by remember { mutableStateOf<JSONObject?>(null) }
    var list by remember { mutableStateOf(listOf<JSONObject>()) }
    var note by remember { mutableStateOf("") }
    var chosen by remember { mutableStateOf<JSONObject?>(null) }

    suspend fun load() {
        val reply = client.get("/v1/tasks?sort=${if (byMemory) "memory" else "cpu"}&q=${java.net.URLEncoder.encode(query, "UTF-8")}")
        val problem = refused(reply)
        if (problem != null) {
            note = problem
        } else {
            note = ""
            summary = reply!!.optJSONObject("summary")
            list = reply.optJSONArray("processes").objects()
        }
    }

    // Kept fresh while the screen is open, as a task manager is.
    LaunchedEffect(byMemory, query) {
        while (true) {
            load()
            delay(4000)
        }
    }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Tasks", onBack)
        Column(Modifier.padding(horizontal = 14.dp).weight(1f)) {
            summary?.let { s ->
                Card(Modifier.fillMaxWidth()) {
                    Column {
                        val memory = s.optJSONObject("memory")
                        val total = memory?.optLong("total") ?: 0L
                        val used = total - (memory?.optLong("available") ?: 0L)
                        val load = s.optJSONArray("load")?.optDouble(0) ?: 0.0
                        val cpus = s.optInt("cpus", 1)
                        Muted("Load ${"%.2f".format(load)} on $cpus processors")
                        LinearProgressIndicator(
                            progress = { (load / cpus).toFloat().coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        )
                        Muted("Memory ${Protocol.formatSize(used)} of ${Protocol.formatSize(total)}")
                        LinearProgressIndicator(
                            progress = { if (total > 0) (used.toFloat() / total).coerceIn(0f, 1f) else 0f },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        )
                        s.optJSONArray("disks").objects().forEach { disk ->
                            Muted("${disk.optString("mount")}  ${Protocol.formatSize(disk.optLong("free"))} free of ${Protocol.formatSize(disk.optLong("total"))}")
                        }
                        Muted("Up ${Protocol.formatDuration(s.optInt("uptime"))}")
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = !byMemory, onClick = { byMemory = false }, label = { Text("Processor") })
                FilterChip(selected = byMemory, onClick = { byMemory = true }, label = { Text("Memory") })
                OutlinedTextField(
                    value = query, onValueChange = { query = it }, singleLine = true,
                    placeholder = { Text("Find a process") }, modifier = Modifier.weight(1f),
                )
            }
            if (note.isNotEmpty()) Text(note, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(vertical = 6.dp))
            LazyColumn(Modifier.weight(1f).padding(top = 6.dp)) {
                items(list, key = { it.optInt("pid") }) { process ->
                    Row(
                        Modifier.fillMaxWidth().clickable { chosen = process }.padding(vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(process.optString("name"), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Muted("${process.optInt("pid")} · ${process.optString("user")}")
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text("${process.optDouble("cpu")}%", fontFamily = FontFamily.Monospace, fontSize = 13.sp)
                            Muted(Protocol.formatSize(process.optLong("rss")))
                        }
                    }
                }
            }
        }
    }

    chosen?.let { process ->
        val pid = process.optInt("pid")
        fun act(action: String) {
            chosen = null
            scope.launch {
                val reply = client.post("/v1/tasks/signal", JSONObject().put("pid", pid).put("action", action))
                note = refused(reply) ?: ""
                load()
            }
        }
        AlertDialog(
            onDismissRequest = { chosen = null },
            title = { Text("${process.optString("name")} ($pid)") },
            text = {
                Column {
                    Text(process.optString("command"), fontFamily = FontFamily.Monospace, fontSize = 12.sp, maxLines = 8,
                        overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(8.dp))
                    Muted("Running for ${Protocol.formatDuration(process.optInt("elapsed"))} · " +
                        "${process.optDouble("memory")}% of memory")
                    if (!process.optBoolean("mine")) Muted("It belongs to ${process.optString("user")}: it cannot be stopped from here.")
                }
            },
            confirmButton = {
                Row {
                    TextButton(onClick = { act("pause") }) { Text("Pause") }
                    TextButton(onClick = { act("resume") }) { Text("Resume") }
                    TextButton(onClick = { act("stop") }) { Text("End") }
                    TextButton(onClick = { act("kill") }) { Text("Kill", color = MaterialTheme.colorScheme.error) }
                }
            },
            dismissButton = { TextButton(onClick = { chosen = null }) { Text("Close") } },
        )
    }
}

// ------------------------------------------------------------------ devices

@Composable
fun DevicesPage(client: LinkClient, onBack: () -> Unit, onBrowse: (String) -> Unit) {
    var usb by remember { mutableStateOf(listOf<JSONObject>()) }
    var drives by remember { mutableStateOf(listOf<JSONObject>()) }
    var note by remember { mutableStateOf("Looking…") }

    // Plugging something in shows up without leaving the screen.
    LaunchedEffect(Unit) {
        while (true) {
            val reply = client.get("/v1/devices")
            val problem = refused(reply)
            if (problem != null) note = problem else {
                note = ""
                usb = reply!!.optJSONArray("usb").objects()
                drives = reply.optJSONArray("drives").objects()
            }
            delay(3000)
        }
    }

    Column(Modifier.fillMaxSize()) {
        TopBar("Devices", onBack)
        Column(Modifier.padding(horizontal = 14.dp).verticalScroll(rememberScrollState())) {
            if (note.isNotEmpty()) Muted(note)
            Heading("USB")
            if (usb.isEmpty() && note.isEmpty()) Muted("Nothing is plugged in.")
            usb.forEach { device ->
                Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                    Column {
                        Text(device.optString("name"), fontWeight = FontWeight.SemiBold)
                        Muted(listOf(device.optString("kind"), device.optString("maker"), device.optString("speed"))
                            .filter { it.isNotBlank() }.joinToString(" · "))
                        Muted("${device.optString("id")} · port ${device.optString("port")}")
                    }
                }
            }
            Heading("Drives")
            drives.forEach { drive ->
                val mount = drive.optString("mount")
                Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                    Column {
                        Text(
                            drive.optString("name").ifBlank { drive.optString("device") } +
                                if (drive.optBoolean("removable")) "  (removable)" else "",
                            fontWeight = FontWeight.SemiBold,
                        )
                        Muted(listOf(drive.optString("device"), Protocol.formatSize(drive.optLong("size")),
                            drive.optString("format"), drive.optString("over")).filter { it.isNotBlank() }.joinToString(" · "))
                        if (mount.isNotEmpty()) {
                            Muted("At $mount" + if (drive.has("free")) ", ${Protocol.formatSize(drive.optLong("free"))} free" else "")
                            Spacer(Modifier.height(6.dp))
                            OutlinedButton(onClick = { onBrowse(mount) }) { Text("Browse") }
                        } else {
                            Muted("Not mounted")
                        }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

// ------------------------------------------------------------------ network

@Composable
fun NetworkPage(client: LinkClient, onBack: () -> Unit) {
    var interfaces by remember { mutableStateOf(listOf<JSONObject>()) }
    var dns by remember { mutableStateOf(listOf<String>()) }
    // Speed is the difference between this reading and the one before it.
    var before by remember { mutableStateOf<JSONObject?>(null) }
    var latest by remember { mutableStateOf<JSONObject?>(null) }
    var note by remember { mutableStateOf("Looking…") }

    LaunchedEffect(Unit) {
        while (true) {
            val reply = client.get("/v1/network")
            val problem = refused(reply)
            if (problem != null) note = problem else {
                note = ""
                before = latest
                latest = reply
                interfaces = reply!!.optJSONArray("interfaces").objects()
                dns = reply.optJSONArray("dns").let { list -> if (list == null) emptyList() else List(list.length()) { list.optString(it) } }
            }
            delay(2000)
        }
    }

    fun rate(name: String, key: String): String {
        val old = before?.optJSONArray("interfaces").objects().firstOrNull { it.optString("name") == name } ?: return "…"
        val now = interfaces.firstOrNull { it.optString("name") == name } ?: return "…"
        return Protocol.formatRate(old.optLong(key), now.optLong(key), latest!!.optDouble("time") - before!!.optDouble("time"))
    }

    Column(Modifier.fillMaxSize()) {
        TopBar("Network", onBack)
        Column(Modifier.padding(horizontal = 14.dp).verticalScroll(rememberScrollState())) {
            if (note.isNotEmpty()) Muted(note)
            if (interfaces.isEmpty() && note.isEmpty()) Muted("The computer has no network connection.")
            interfaces.forEach { link ->
                val name = link.optString("name")
                val up = link.optBoolean("up")
                val wifi = link.optJSONObject("wifi")
                Card(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                    Column {
                        Text(wifi?.optString("name")?.ifBlank { null } ?: link.optString("kind"), fontWeight = FontWeight.SemiBold)
                        Muted(listOf(link.optString("kind"), name, if (up) "Connected" else "Not connected",
                            if (link.optBoolean("default")) "Internet" else "").filter { it.isNotBlank() }.distinct().joinToString(" · "))
                        if (wifi != null) {
                            val signal = wifi.optInt("signal")
                            Spacer(Modifier.height(6.dp))
                            Muted("Signal $signal% · " + listOf(wifi.optString("frequency"), wifi.optString("rate"),
                                wifi.optString("security")).filter { it.isNotBlank() }.joinToString(" · "))
                            LinearProgressIndicator(
                                progress = { (signal / 100f).coerceIn(0f, 1f) },
                                modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                            )
                        }
                        if (up) {
                            Spacer(Modifier.height(6.dp))
                            Row {
                                Column(Modifier.weight(1f)) {
                                    Muted("Received")
                                    Text(rate(name, "received"), fontFamily = FontFamily.Monospace, fontSize = 15.sp)
                                    Muted("${Protocol.formatSize(link.optLong("received"))} in all")
                                }
                                Column(Modifier.weight(1f)) {
                                    Muted("Sent")
                                    Text(rate(name, "sent"), fontFamily = FontFamily.Monospace, fontSize = 15.sp)
                                    Muted("${Protocol.formatSize(link.optLong("sent"))} in all")
                                }
                            }
                            Spacer(Modifier.height(6.dp))
                        }
                        link.optJSONArray("addresses").let { list ->
                            if (list != null) repeat(list.length()) {
                                Text(list.optString(it), fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                            }
                        }
                        link.optString("gateway").takeIf { it.isNotBlank() }?.let { Muted("Router $it") }
                        link.optString("speed").takeIf { it.isNotBlank() }?.let { Muted("Link speed $it") }
                        link.optString("mac").takeIf { it.isNotBlank() }?.let { Muted("Hardware address $it") }
                    }
                }
            }
            if (dns.isNotEmpty()) {
                Heading("DNS")
                dns.forEach { Text(it, fontFamily = FontFamily.Monospace, fontSize = 12.sp) }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

// ------------------------------------------------------------------ desktop

@Composable
fun DesktopPage(client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var projects by remember { mutableStateOf(listOf<JSONObject>()) }
    var focus by remember { mutableStateOf(false) }
    var dark by remember { mutableStateOf(true) }
    var said by remember { mutableStateOf("") }
    var noteText by remember { mutableStateOf("") }
    var report by remember { mutableStateOf<Pair<String, String>?>(null) }
    var filter by remember { mutableStateOf("") }

    suspend fun load() {
        val reply = client.get("/v1/desktop")
        val problem = refused(reply)
        if (problem != null) said = problem else {
            projects = reply!!.optJSONArray("projects").objects()
            focus = reply.optBoolean("focus")
            dark = reply.optBoolean("dark", true)
        }
    }

    fun act(action: String, value: String = "") {
        scope.launch {
            val reply = client.post("/v1/desktop", JSONObject().put("action", action).put("value", value))
            said = refused(reply) ?: reply!!.optString("text").ifBlank { if (reply.optBoolean("ok")) "Done" else "It did not work" }
            load()
        }
    }

    fun show(name: String, title: String) {
        scope.launch {
            val reply = client.get("/v1/desktop/report?name=$name")
            report = title to (refused(reply) ?: reply!!.optString("text").ifBlank { "Nothing to show." })
        }
    }

    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Desktop", onBack)
        Column(Modifier.padding(horizontal = 14.dp).verticalScroll(rememberScrollState())) {
            if (said.isNotEmpty()) Muted(said, Modifier.padding(bottom = 4.dp))

            val active = projects.firstOrNull { it.optBoolean("active") }
            Heading("Project")
            Card(Modifier.fillMaxWidth()) {
                Column {
                    Text(active?.optString("name") ?: "No project is active", fontWeight = FontWeight.SemiBold)
                    active?.let { Muted(it.optString("path")) }
                    Spacer(Modifier.height(8.dp))
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        AssistChip(onClick = { show("git", "Git") }, label = { Text("Git") })
                        AssistChip(onClick = { show("time", "Time") }, label = { Text("Time") })
                        AssistChip(onClick = { show("tasks", "Open tasks") }, label = { Text("Open tasks") })
                        if (active != null) AssistChip(onClick = { act("project-clear") }, label = { Text("Leave project") })
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = filter, onValueChange = { filter = it }, singleLine = true,
                placeholder = { Text("Switch to a project") }, modifier = Modifier.fillMaxWidth(),
            )
            projects.filter { !it.optBoolean("active") && it.optString("name").contains(filter, ignoreCase = true) }
                .take(if (filter.isBlank()) 6 else 30).forEach { project ->
                    Row(
                        Modifier.fillMaxWidth().clickable { act("project", project.optString("id")) }.padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(project.optString("name"), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Muted(project.optString("path"))
                        }
                    }
                }

            Heading("Quick note")
            OutlinedTextField(
                value = noteText, onValueChange = { noteText = it },
                placeholder = { Text("A line for the project's inbox") }, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { if (noteText.isNotBlank()) { act("note", noteText); noteText = "" } }),
            )
            Spacer(Modifier.height(6.dp))
            Button(onClick = { act("note", noteText); noteText = "" }, enabled = noteText.isNotBlank()) { Text("Add note") }

            Heading("Focus")
            Row(verticalAlignment = Alignment.CenterVertically) {
                Muted("Hide notification banners on the computer", Modifier.weight(1f))
                Switch(checked = focus, onCheckedChange = { focus = it; act("focus", if (it) "on" else "off") })
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(25, 50, 90).forEach { minutes ->
                    AssistChip(onClick = { act("focus", minutes.toString()) }, label = { Text("$minutes min") })
                }
            }

            Heading("The window in front")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BigButton("Left", Modifier.weight(1f), height = 48) { act("tile", "left") }
                BigButton("Centre", Modifier.weight(1f), height = 48) { act("tile", "center") }
                BigButton("Right", Modifier.weight(1f), height = 48) { act("tile", "right") }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BigButton("Maximise", Modifier.weight(1f), height = 48) { act("tile", "maximize") }
                BigButton("Smart", Modifier.weight(1f), height = 48) { act("tile", "smart") }
                BigButton("Full screen", Modifier.weight(1f), height = 48) { act("fullscreen") }
            }

            Heading("Open on the computer")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BigButton("Palette", Modifier.weight(1f), height = 48) { act("open", "palette") }
                BigButton("Projects", Modifier.weight(1f), height = 48) { act("open", "projects") }
                BigButton("Settings", Modifier.weight(1f), height = 48) { act("open", "settings") }
            }

            Heading("Appearance and session")
            Row(verticalAlignment = Alignment.CenterVertically) {
                Muted("Dark appearance", Modifier.weight(1f))
                Switch(checked = dark, onCheckedChange = { dark = it; act("scheme", if (it) "dark" else "light") })
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { act("session-save") }) { Text("Save session") }
                Spacer(Modifier.width(2.dp))
                OutlinedButton(onClick = { show("session", "Session") }) { Text("Session status") }
            }
            Spacer(Modifier.height(20.dp))
        }
    }

    report?.let { (title, text) ->
        AlertDialog(
            onDismissRequest = { report = null },
            title = { Text(title) },
            text = {
                Text(text, fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                    modifier = Modifier.verticalScroll(rememberScrollState()))
            },
            confirmButton = { TextButton(onClick = { report = null }) { Text("Close") } },
        )
    }
}
