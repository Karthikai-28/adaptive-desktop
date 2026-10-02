package com.karthi.adaptivelink

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.filled.Cameraswitch
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType
import okhttp3.RequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.BufferedSink
import okio.source
import org.json.JSONObject
import java.net.URLEncoder

// --------------------------------------------------------------------- run

@Composable
fun RunPage(client: LinkClient, store: Store, onBack: () -> Unit) {
    var command by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("") }
    var running by remember { mutableStateOf<WebSocket?>(null) }
    var keep by remember { mutableStateOf(false) }
    var history by remember { mutableStateOf(store.commandHistory) }
    val scroll = rememberScrollState()

    DisposableEffect(Unit) { onDispose { running?.close(1000, null) } }
    LaunchedEffect(output) { scroll.scrollTo(scroll.maxValue) }

    fun run(text: String) {
        if (text.isBlank() || running != null) return
        history = (listOf(text) + history.filter { it != text }).take(30)
        store.commandHistory = history
        output = "$ $text\n"
        running = client.socket("/v1/exec", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(JSONObject().put("cmd", text).put("cwd", "~").put("detach", keep).toString())
            }

            override fun onMessage(webSocket: WebSocket, message: String) {
                val json = JSONObject(message)
                when {
                    json.has("o") -> output = (output + json.getString("o")).takeLast(60_000)
                    json.has("exit") -> { output += "\n[finished: ${json.getInt("exit")}]\n"; running = null }
                    json.has("started") -> { output += "[started and left running, pid ${json.getInt("started")}]\n"; running = null }
                    json.has("error") -> { output += "[${json.getString("error")}]\n"; running = null }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                output += if (response?.code == 403) "[Running commands is turned off on the computer]\n" else "[connection lost]\n"
                running = null
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { running = null }
        })
    }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Run", onBack)
        Column(Modifier.padding(horizontal = 14.dp).weight(1f)) {
            OutlinedTextField(
                value = command, onValueChange = { command = it },
                placeholder = { Text("A command to run on the computer") },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
                textStyle = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { run(command) }),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = keep, onCheckedChange = { keep = it })
                Spacer(Modifier.width(8.dp))
                Muted("Start and leave running (a player, an app)", Modifier.weight(1f))
                if (running != null) {
                    OutlinedButton(onClick = { running?.send("{\"kill\":true}") }) { Text("Stop") }
                } else {
                    Button(onClick = { run(command) }) { Text("Run") }
                }
            }
            if (history.isNotEmpty()) {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    history.take(12).forEach { past ->
                        AssistChip(onClick = { command = past }, label = { Text(past.take(28)) })
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Card(Modifier.fillMaxWidth().weight(1f)) {
                Text(
                    output.ifEmpty { "Output appears here." },
                    fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                    modifier = Modifier.fillMaxSize().verticalScroll(scroll),
                )
            }
            Spacer(Modifier.height(10.dp))
        }
    }
}

// ------------------------------------------------------------------- files

private data class Entry(val name: String, val dir: Boolean, val size: Long)

/** A file on the phone, streamed to the computer without loading it into memory. */
private class UriBody(private val context: Context, private val uri: Uri) : RequestBody() {
    override fun contentType(): MediaType? = null
    override fun writeTo(sink: BufferedSink) {
        context.contentResolver.openInputStream(uri)!!.use { sink.writeAll(it.source()) }
    }
}

private fun displayName(context: Context, uri: Uri): String {
    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        if (cursor.moveToFirst()) return cursor.getString(0) ?: "file"
    }
    return uri.lastPathSegment ?: "file"
}

@Composable
fun FilesPage(activity: MainActivity, client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var path by remember { mutableStateOf("~") }
    var parent by remember { mutableStateOf("") }
    val entries = remember { mutableStateListOf<Entry>() }
    var note by remember { mutableStateOf("") }
    var chosen by remember { mutableStateOf<Entry?>(null) }

    fun encoded(value: String) = URLEncoder.encode(value, "UTF-8")

    fun load(target: String) = scope.launch {
        val listing = client.get("/v1/files?path=${encoded(target)}")
        if (listing == null || listing.has("error")) {
            note = listing?.optString("error") ?: "Cannot reach the computer"
            return@launch
        }
        path = listing.getString("path")
        parent = listing.optString("parent")
        val array = listing.getJSONArray("entries")
        entries.clear()
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            entries += Entry(item.getString("name"), item.getBoolean("dir"), item.optLong("size"))
        }
        note = ""
    }
    LaunchedEffect(Unit) { load("~") }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) scope.launch {
            val name = displayName(activity, uri)
            note = "Sending $name…"
            val result = client.upload(name, UriBody(activity, uri))
            note = if (result?.optBoolean("ok") == true) "Sent to ${result.optString("path")}" else "Sending failed"
        }
    }

    fun download(entry: Entry) = scope.launch {
        note = "Downloading ${entry.name}…"
        val saved = withContext(Dispatchers.IO) {
            val response = client.open("/v1/file?path=${encoded("$path/${entry.name}")}") ?: return@withContext false
            response.use {
                if (!it.isSuccessful) return@withContext false
                val values = ContentValues().apply { put(MediaStore.Downloads.DISPLAY_NAME, entry.name) }
                val target = activity.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: return@withContext false
                activity.contentResolver.openOutputStream(target)!!.use { out -> it.body!!.byteStream().copyTo(out) }
                true
            }
        }
        note = if (saved) "${entry.name} is in this phone's Downloads" else "Download failed"
    }

    TopBar("Files", onBack) {
        IconButton(onClick = { activity.awayOnPurpose = true; picker.launch("*/*") }) { Icon(Icons.Filled.Upload, "Send a file to the computer") }
    }
    Column(Modifier.fillMaxSize().padding(horizontal = 14.dp)) {
        Muted(path)
        if (note.isNotEmpty()) Text(note, color = MaterialTheme.colorScheme.primary, fontSize = 13.sp)
        Spacer(Modifier.height(6.dp))
        LazyColumn(Modifier.weight(1f)) {
            if (parent.isNotEmpty()) item {
                FileRow("..", true, "") { load(parent) }
            }
            items(entries) { entry ->
                FileRow(entry.name, entry.dir, if (entry.dir) "" else Protocol.formatSize(entry.size)) {
                    if (entry.dir) load("$path/${entry.name}") else chosen = entry
                }
            }
        }
    }

    chosen?.let { entry ->
        AlertDialog(
            onDismissRequest = { chosen = null },
            title = { Text(entry.name) },
            text = { Text(Protocol.formatSize(entry.size)) },
            confirmButton = {
                TextButton(onClick = {
                    chosen = null
                    scope.launch {
                        val opened = client.post("/v1/open", JSONObject().put("path", "$path/${entry.name}"))
                        note = if (opened?.optBoolean("ok") == true) "Opened on the computer" else "Could not open it"
                    }
                }) { Text("Open on computer") }
            },
            dismissButton = { TextButton(onClick = { chosen = null; download(entry) }) { Text("Download to phone") } },
        )
    }
}

@Composable
private fun FileRow(name: String, dir: Boolean, detail: String, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            if (dir) Icons.Filled.Folder else Icons.AutoMirrored.Filled.InsertDriveFile, null, Modifier.size(22.dp),
            tint = if (dir) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(12.dp))
        Text(name, Modifier.weight(1f), maxLines = 1)
        if (detail.isNotEmpty()) Muted(detail)
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.surface)
}

// ------------------------------------------------------------------ camera

@Composable
fun CameraPage(activity: MainActivity, client: LinkClient, onBack: () -> Unit) {
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var front by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf("Starting…") }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) {
        if (!granted) {
            activity.awayOnPurpose = true
            permission.launch(Manifest.permission.CAMERA)
        }
    }

    TopBar("Webcam", onBack) {
        IconButton(onClick = { front = !front }) { Icon(Icons.Filled.Cameraswitch, "Switch camera") }
    }
    Column(Modifier.fillMaxSize().padding(14.dp)) {
        if (!granted) {
            Muted("Adaptive Link needs the camera permission to use this phone as a webcam.")
            return@Column
        }
        Muted(note)
        Spacer(Modifier.height(8.dp))
        val preview = remember { PreviewView(activity) }
        AndroidView(factory = { preview }, modifier = Modifier.fillMaxWidth().weight(1f))
        DisposableEffect(front) {
            val streamer = CameraStreamer(activity, client) { note = it }
            streamer.start(activity, preview, front)
            onDispose { streamer.stop() }
        }
        Spacer(Modifier.height(8.dp))
        Muted("On the computer, choose “Phone Camera” as the camera in your meeting app or browser. It stops when you leave this screen.")
    }
}

// -------------------------------------------------------------------- more

private fun notificationAccessGranted(context: Context): Boolean {
    val enabled = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners").orEmpty()
    return enabled.contains(ComponentName(context, NotificationRelay::class.java).flattenToString())
}

@Composable
fun MorePage(
    activity: MainActivity, client: LinkClient, store: Store, state: LinkState,
    onBack: () -> Unit, onUnpaired: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var note by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf<Pair<String, String>?>(null) }
    var relay by remember { mutableStateOf(store.relayNotifications && notificationAccessGranted(activity)) }
    var lock by remember { mutableStateOf(store.lockOnOpen) }
    var unpair by remember { mutableStateOf(false) }
    val clipboard = remember { activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager }

    fun power(action: String) = scope.launch {
        val result = client.post("/v1/power", JSONObject().put("action", action))
        note = when {
            result == null -> "Cannot reach the computer"
            result.has("error") -> result.getString("error")
            else -> "Done"
        }
    }

    TopBar("More", onBack)
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (note.isNotEmpty()) Text(note, color = MaterialTheme.colorScheme.primary)

        Section("Clipboard") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    scope.launch {
                        val text = client.get("/v1/clipboard")?.optString("text").orEmpty()
                        if (text.isEmpty()) note = "The computer's clipboard is empty"
                        else {
                            clipboard.setPrimaryClip(ClipData.newPlainText("From computer", text))
                            note = "Copied the computer's clipboard to this phone"
                        }
                    }
                }) { Text("Get from computer") }
                OutlinedButton(onClick = {
                    val text = clipboard.primaryClip?.getItemAt(0)?.coerceToText(activity)?.toString().orEmpty()
                    if (text.isEmpty()) note = "This phone's clipboard is empty"
                    else scope.launch {
                        client.post("/v1/clipboard", JSONObject().put("text", text))
                        note = "Sent this phone's clipboard to the computer"
                    }
                }) { Text("Send to computer") }
            }
        }

        Section("Computer") {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { power("lock") }) { Text("Lock") }
                OutlinedButton(onClick = { power("unlock") }) { Text("Unlock") }
                OutlinedButton(onClick = { power("screen-off") }) { Text("Screen off") }
                OutlinedButton(onClick = { confirm = "suspend" to "Suspend the computer? You will not be able to wake it from the phone." }) { Text("Suspend") }
                OutlinedButton(onClick = { confirm = "reboot" to "Restart the computer? Unsaved work will be lost." }) { Text("Restart") }
                OutlinedButton(onClick = { confirm = "poweroff" to "Shut the computer down? Unsaved work will be lost, and it cannot be started from the phone." }) { Text("Shut down") }
            }
            if (!state.can("power")) Muted("Power actions are turned off on the computer.")
        }

        Section("This phone's notifications") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Muted("Show them on the computer", Modifier.weight(1f))
                Switch(checked = relay, onCheckedChange = { wanted ->
                    store.relayNotifications = wanted
                    relay = wanted && notificationAccessGranted(activity)
                    if (wanted && !notificationAccessGranted(activity)) {
                        note = "Allow Adaptive Link in the list that opens, then come back."
                        activity.awayOnPurpose = true
                        activity.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                    }
                })
            }
        }

        Section("Security") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Muted("Ask for fingerprint or screen lock when opened", Modifier.weight(1f))
                Switch(checked = lock, onCheckedChange = { lock = it; store.lockOnOpen = it })
            }
            Spacer(Modifier.height(4.dp))
            Muted("Paired with ${client.computer.name}. This phone's key is held in its secure hardware and cannot be copied to another device.")
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = { unpair = true }) { Text("Unpair this phone", color = MaterialTheme.colorScheme.error) }
        }
        Spacer(Modifier.height(20.dp))
    }

    confirm?.let { (action, question) ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            text = { Text(question) },
            confirmButton = { TextButton(onClick = { confirm = null; power(action) }) { Text("Yes") } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
        )
    }
    if (unpair) {
        AlertDialog(
            onDismissRequest = { unpair = false },
            title = { Text("Unpair this phone?") },
            text = { Text("This phone's key is destroyed. To stop the computer accepting it as well, also run link-cli.py unpair there.") },
            confirmButton = {
                TextButton(onClick = {
                    unpair = false
                    LinkIdentity.delete()
                    store.computer = null
                    store.relayNotifications = false
                    Link.forget()
                    onUnpaired()
                }) { Text("Unpair") }
            },
            dismissButton = { TextButton(onClick = { unpair = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column {
            Text(title, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            content()
        }
    }
}
