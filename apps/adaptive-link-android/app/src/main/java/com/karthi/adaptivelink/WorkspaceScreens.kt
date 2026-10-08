package com.karthi.adaptivelink

import android.content.res.Configuration
import android.graphics.BitmapFactory
import android.util.Base64
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder

@Composable
internal fun AppsPage(activity: MainActivity, client: LinkClient, store: Store, onBack: () -> Unit) {
    val cache = remember(client.computer.fingerprint) { WorkspaceStore(activity, client.computer, store) }
    val scope = rememberCoroutineScope()
    var apps by remember { mutableStateOf(cache.catalog()) }
    var session by remember { mutableStateOf<JSONObject?>(null) }
    var query by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("Connecting…") }
    var supported by remember { mutableStateOf(false) }
    var online by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var favorites by remember { mutableStateOf(cache.favorites()) }
    var choices by remember { mutableStateOf<List<JSONObject>?>(null) }
    var pickingApp by remember { mutableStateOf<JSONObject?>(null) }
    var rememberMatch by remember { mutableStateOf(false) }
    var global by remember { mutableStateOf(false) }
    var layoutApp by remember { mutableStateOf<JSONObject?>(null) }
    suspend fun refresh() {
        val status = client.connect()
        online = status != null
        supported = status?.optJSONObject("capabilities")?.optInt("app_workspaces") == 1
        if (status == null) { note = "Offline · saved layouts are available"; return }
        if (!supported) { note = "Update the computer service to use app workspaces. Screen and Run remain available."; return }
        val list = client.get("/v1/apps")?.optJSONArray("apps")
        if (list != null) { apps = list.rows(); cache.catalog(list) }
        note = cache.sync(client)
    }
    LaunchedEffect(client) { while (true) { refresh(); delay(15000) } }
    fun open(app: JSONObject, window: Int = 0, newWindow: Boolean = false) {
        if (busy) return
        busy = true
        scope.launch {
            try {
                val config = activity.resources.configuration
                val size = if (config.orientation == Configuration.ORIENTATION_LANDSCAPE) "1280x800" else "800x1280"
                val answer = client.post("/v1/app-sessions", JSONObject().put("app_id", app.getString("id"))
                    .put("window_id", window).put("new_window", newWindow).put("remember", rememberMatch).put("size", size))
                if (answer?.optBoolean("ok") == true) {
                    session = answer.getJSONObject("session")
                    cache.recent(app.getString("id")); choices = null
                    if (cache.profiles().none { it.optString("app_id") == app.getString("id") }) {
                        starterLayouts(app.getString("id"), app.optString("adapter")).forEach { cache.save(it) }
                        cache.sync(client)
                    }
                } else {
                    note = answer?.optString("error")?.ifBlank { "Choose a window" } ?: "Cannot reach the computer"
                    choices = answer?.optJSONArray("choose_window")?.rows()
                    pickingApp = app
                }
            } finally { busy = false }
        }
    }
    val current = session
    if (current != null) {
        AppWorkspace(activity, client, store, cache, current, onExpired = {
            // The computer let the workspace go while this phone was away: open the same window again.
            session = null
            apps.firstOrNull { it.optString("id") == current.optString("app_id") }?.let { open(it, current.optInt("window_id")) }
        }) { session = null }
        return
    }
    if (global) {
        LayoutManager(activity, client, cache, layoutApp?.optString("id").orEmpty(), layoutApp?.optString("name") ?: "Global layouts", null, onBack = { global = false })
        return
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("Apps", onBack) { TextButton(onClick = { layoutApp = null; global = true }) { Text("Layouts") } }
        OutlinedTextField(query, { query = it }, label = { Text("Search apps") }, singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp))
        Row(Modifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(note, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { scope.launch { refresh() } }) { Text("Refresh") }
        }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        val recent = cache.recents()
        val listed = apps.filter { it.optString("name").contains(query, true) }.sortedWith(
            compareByDescending<JSONObject> { it.optString("id") in favorites }
                .thenBy { recent.indexOf(it.optString("id")).let { n -> if (n < 0) 999 else n } }.thenBy { it.optString("name") })
        LazyColumn(Modifier.weight(1f)) {
            items(listed, key = { it.optString("id") }) { app ->
                val id = app.optString("id")
                Row(Modifier.fillMaxWidth().clickable(enabled = online && supported && !busy) { open(app) }
                    .padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    AppIcon(client, app)
                    Column(Modifier.weight(1f).padding(start = 12.dp)) {
                        Text(app.optString("name"), style = MaterialTheme.typography.titleMedium)
                        val running = app.optJSONArray("windows")?.length() ?: 0
                        Text(if (running > 0) "$running running" else if (id in recent) "Recent" else app.optString("adapter"), style = MaterialTheme.typography.bodySmall)
                    }
                    TextButton(onClick = { cache.favorite(id); favorites = cache.favorites() }, modifier = Modifier.semantics { contentDescription = "Favorite ${app.optString("name")}" }) { Text(if (id in favorites) "★" else "☆") }
                    TextButton(onClick = { layoutApp = app; global = true }) { Text("Layouts") }
                    if (app.optBoolean("new_window")) TextButton(enabled = online && !busy, onClick = { open(app, newWindow = true) }) { Text("New") }
                }
            }
        }
    }
    choices?.let { windows ->
        AlertDialog(onDismissRequest = { choices = null }, title = { Text("Choose the app window") }, text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(rememberMatch, { rememberMatch = it }); Text("Remember this app association") }
                if (windows.isEmpty()) Text("No window yet. Close this picker and retry the app.")
                LazyColumn(Modifier.heightIn(max = 350.dp)) {
                    items(windows) { w -> TextButton(onClick = { pickingApp?.let { open(it, w.getInt("id")) } }) { Text(w.optString("title")) } }
                }
            }
        }, confirmButton = { TextButton(onClick = { choices = null }) { Text("Close") } })
    }
}

@Composable
private fun AppIcon(client: LinkClient, app: JSONObject) {
    var picture by remember(app.optString("id")) { mutableStateOf<android.graphics.Bitmap?>(null) }
    LaunchedEffect(app.optString("id")) {
        val text = client.get("/v1/apps/icon?id=" + URLEncoder.encode(app.optString("id"), "UTF-8"))?.optString("png").orEmpty()
        picture = runCatching { Base64.decode(text, Base64.DEFAULT).let { BitmapFactory.decodeByteArray(it, 0, it.size) } }.getOrNull()
    }
    picture?.let { Image(it.asImageBitmap(), null, Modifier.size(40.dp)) }
        ?: Icon(Icons.Default.Apps, null, Modifier.size(40.dp))
}

@Composable
private fun AppWorkspace(activity: MainActivity, client: LinkClient, store: Store, cache: WorkspaceStore,
                         initial: JSONObject, onExpired: () -> Unit, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val id = initial.getString("id")
    val app = initial.getString("app_id")
    var session by remember(id) { mutableStateOf(initial) }
    var online by remember { mutableStateOf(true) }
    var profiles by remember { mutableStateOf(cache.profiles()) }
    var chosen by remember { mutableStateOf(cache.selected(app)) }
    var layouts by remember { mutableStateOf(false) }
    var mode by remember { mutableStateOf("Live") }
    var full by remember { mutableStateOf(false) }
    var drawer by remember { mutableStateOf(true) }
    var whole by remember { mutableStateOf(false) }
    var url by remember { mutableStateOf("") }
    var run by remember { mutableStateOf<JSONObject?>(null) }
    var note by remember { mutableStateOf(if (initial.optString("display").isNotBlank()) "Moved to phone" else "Viewing the app on the computer") }
    var prompt by remember { mutableStateOf<JSONObject?>(null) }
    var promptValue by remember { mutableStateOf("") }
    var confirmation by remember { mutableStateOf<JSONObject?>(null) }
    var pendingPress by remember { mutableStateOf(false) }
    var holdReleased by remember { mutableStateOf(false) }
    var volume by remember { mutableStateOf<JSONObject?>(null) }
    var players by remember { mutableStateOf(emptyList<JSONObject>()) }
    var timer by remember { mutableIntStateOf(0) }
    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    val available = profiles.filter { it.optString("app_id") in listOf(app, "") }
    val selected = available.firstOrNull { it.optString("id") == chosen }
        ?: available.firstOrNull { it.optString("app_id") == app && it.optBoolean("default") }
        ?: available.firstOrNull()
    val working = run?.optString("state") == "running" || pendingPress
    fun submit(c: JSONObject, confirm: Boolean = false) {
        if (!online || working) return
        val asked = c.optJSONArray("steps").rows().any { it.optBoolean("prompt") }
        if (asked) { prompt = c; promptValue = ""; return }
        pendingPress = true
        holdReleased = false
        scope.launch {
            try {
                val answer = client.post("/v1/control-runs", JSONObject().put("request_id", freshId()).put("session", id)
                    .put("steps", c.getJSONArray("steps")).put("hold", c.optString("mode") == "hold").put("confirm", confirm))
                if (answer?.optBoolean("confirm") == true) confirmation = c
                else if (answer?.optBoolean("ok") == true) {
                    run = answer.getJSONObject("run")
                    if (c.optString("mode") == "hold" && holdReleased) client.post("/v1/control-runs", JSONObject().put("operation", "cancel").put("id", run!!.getString("id")))
                } else note = answer?.optString("error") ?: "Connection lost · action was not retried"
            } finally { pendingPress = false }
        }
    }
    fun stop() {
        holdReleased = true
        run?.optString("id")?.let { rid -> scope.launch { client.post("/v1/control-runs", JSONObject().put("operation", "cancel").put("id", rid)) } }
    }
    val foreground = WorkspaceForeground(activity) { stop() }
    LaunchedEffect(id, foreground) {
        while (foreground) {
            val response = client.get("/v1/app-sessions?id=$id")
            online = response?.optBoolean("ok") == true
            if (response != null && !online) { onExpired(); break }
            response?.optJSONObject("session")?.let { session = it }
            if (!online) note = response?.optString("error") ?: "Disconnected · actions paused"
            profiles = cache.profiles()
            if (run != null) {
                val state = client.get("/v1/control-runs?id=${run!!.optString("id")}")?.optJSONArray("runs")?.optJSONObject(0)
                if (state != null) {
                    run = state
                    if (state.optString("state") != "running") {
                        note = "${state.optString("state")} · step ${state.optInt("step")}/${state.optInt("total")}" + state.optString("error").let { if (it.isBlank()) "" else ": $it" }
                        if (state.optString("layout").isNotBlank()) {
                            val target = profiles.firstOrNull { it.optString("id") == state.optString("layout") || it.optString("name") == state.optString("layout") }
                            target?.let { chosen = it.getString("id"); cache.select(app, chosen) }
                        }
                    }
                }
            }
            val media = client.get("/v1/media")
            volume = media?.optJSONObject("volume")
            players = media?.optJSONArray("players").rows()
            delay(1000)
        }
    }
    LaunchedEffect(id, landscape) {
        client.post("/v1/app-sessions", JSONObject().put("operation", "resize").put("id", id).put("size", if (landscape) "1280x800" else "800x1280"))
    }
    LaunchedEffect(id) { while (true) { delay(1000); timer++ } }
    DisposableEffect(id) {
        onDispose { CoroutineScope(Dispatchers.IO).launch { client.post("/v1/app-sessions", JSONObject().put("operation", "close").put("id", id)) } }
    }
    BackHandler { when { layouts -> layouts = false; full -> full = false; mode != "Live" -> mode = "Live"; else -> onBack() } }
    val enabled = online && session.optBoolean("control") && !session.optBoolean("closed") && !working
    @Composable fun controlsPanel(modifier: Modifier) {
        Column(modifier) {
            Row(Modifier.horizontalScroll(rememberScrollState())) {
                available.forEach { p -> FilterChip(chosen == p.optString("id") || selected === p, onClick = { chosen = p.getString("id"); cache.select(app, chosen) }, label = { Text(p.optString("name")) }) }
            }
            selected?.let { ControlGrid(it, enabled, volume, players, app, onPress = { submit(it) }, onRelease = { stop() }) }
                ?: TextButton(onClick = { layouts = true }) { Text("Create a layout") }
        }
    }
    @Composable fun content(modifier: Modifier) {
        Box(modifier) {
            if (!foreground) Text("Workspace paused") else when (mode) {
                "Trackpad" -> TrackpadPage(client, id) { mode = "Live" }
                "Tasks" -> when (initial.optString("adapter")) {
                    "files" -> FilesPage(activity, client) { mode = "Live" }
                    "terminal" -> RunPage(client, store) { mode = "Live" }
                    else -> ScreenPage(activity, client, store, id, session.optJSONArray("region")?.toString().orEmpty(), whole) { mode = "Live" }
                }
                else -> ScreenPage(activity, client, store, id, session.optJSONArray("region")?.toString().orEmpty(), whole) { onBack() }
            }
        }
    }
    if (layouts) {
        Column(Modifier.fillMaxSize()) {
            if (working) Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Running ${run?.optInt("step") ?: 0}/${run?.optInt("total") ?: 0}", Modifier.weight(1f))
                Button(onClick = { stop() }) { Text("Stop") }
            }
            Text(note, Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.bodySmall)
            Box(Modifier.weight(1f)) {
                LayoutManager(activity, client, cache, app, initial.optString("name"), selected,
                    onBack = { layouts = false; profiles = cache.profiles() }, test = { submit(it) })
            }
        }
    } else Column(Modifier.fillMaxSize()) {
        if (!full) {
            TopBar(initial.optString("name"), onBack) { TextButton(onClick = { layouts = true }) { Text("Layouts") } }
            Text(session.optString("title"), style = MaterialTheme.typography.bodySmall, maxLines = 1, modifier = Modifier.padding(horizontal = 12.dp))
            Text(if (!online) note else if (session.optBoolean("closed")) "Window closed · return to Apps to reopen" else if (!session.optBoolean("focused")) "App is in background · controls will focus it" else note,
                modifier = Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.bodySmall)
            if (!session.optBoolean("control")) TextButton(onClick = { scope.launch {
                client.post("/v1/app-sessions", JSONObject().put("operation", "take-control").put("id", id))?.optJSONObject("session")?.let { session = it }
            } }) { Text("Take control from other phone") }
            if (session.optString("display").isNotBlank()) TextButton(onClick = { scope.launch {
                client.post("/v1/app-sessions", JSONObject().put("operation", "return").put("id", id))?.optJSONObject("session")?.let { session = it; note = "Returned to computer" }
            } }) { Text("Return window to computer") }
            if (initial.optString("adapter") == "browser") Row(Modifier.padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(url, { url = it }, label = { Text("URL") }, singleLine = true, modifier = Modifier.weight(1f))
                TextButton(enabled = enabled && url.isNotBlank(), onClick = { submit(control("Open URL", step("launch", if (url.contains("://")) url else "https://$url", args = JSONObject().put("type", "url")))) }) { Text("Open") }
            }
            if (initial.optString("adapter") == "presenter") Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Presentation · ${Protocol.formatDuration(timer)}", Modifier.padding(horizontal = 12.dp))
                TextButton(onClick = { timer = 0 }) { Text("Reset timer") }
            }
            if (initial.optString("adapter") == "media") players.firstOrNull { initial.optString("app_id").contains(it.optString("id").substringBefore('.'), true) }?.let {
                Text("${it.optString("title")} · ${it.optString("artist")}", Modifier.padding(12.dp))
            }
        }
        if (working) Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Running ${run?.optInt("step") ?: 0}/${run?.optInt("total") ?: 0}", Modifier.weight(1f).padding(8.dp))
            Button(onClick = { stop() }) { Text("Stop") }
        }
        if (landscape && drawer && !full) Row(Modifier.weight(1f)) {
            content(Modifier.weight(1f).fillMaxHeight()); controlsPanel(Modifier.width(260.dp).fillMaxHeight())
        } else Column(Modifier.weight(1f)) {
            content(Modifier.weight(1f).fillMaxWidth())
            if (drawer && !full) controlsPanel(Modifier.fillMaxWidth().height(220.dp))
        }
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically) {
            if (full) TextButton(onClick = { full = false }) { Text("Show controls") }
            else {
                TextButton(onClick = onBack) { Text("Apps") }
                TextButton(onClick = { mode = if (mode == "Trackpad") "Live" else "Trackpad" }) { Text(if (mode == "Trackpad") "Live" else "Trackpad") }
                if (initial.optString("adapter") in listOf("files", "terminal")) TextButton(onClick = { mode = if (mode == "Tasks") "Live" else "Tasks" }) { Text(if (mode == "Tasks") "Live" else "Tasks") }
                TextButton(onClick = { drawer = !drawer }) { Text("Controls") }
                TextButton(onClick = { whole = !whole }) { Text(if (whole) "App view" else "Desktop") }
                TextButton(onClick = { full = true }) { Text("Full screen") }
            }
        }
    }
    prompt?.let { c -> AlertDialog(onDismissRequest = { prompt = null }, title = { Text(c.optString("label")) }, text = {
        OutlinedTextField(promptValue, { promptValue = it }, label = { Text("Text to insert") })
    }, confirmButton = { TextButton(onClick = {
        val copy = c.copyJson(); copy.optJSONArray("steps").rows().forEach { if (it.optBoolean("prompt")) it.put("value", promptValue).put("prompt", false) }
        prompt = null; submit(copy)
    }) { Text("Run") } }, dismissButton = { TextButton(onClick = { prompt = null }) { Text("Cancel") } }) }
    confirmation?.let { c -> AlertDialog(onDismissRequest = { confirmation = null }, title = { Text("Confirm ${c.optString("label")}") },
        text = { Text("This action includes a change that cannot be undone.") }, confirmButton = { TextButton(onClick = { confirmation = null; submit(c, true) }) { Text("Run") } },
        dismissButton = { TextButton(onClick = { confirmation = null }) { Text("Cancel") } }) }
}

@Composable
internal fun ControlGrid(profile: JSONObject, enabled: Boolean, volume: JSONObject? = null, players: List<JSONObject> = emptyList(), app: String = "",
                         onPress: (JSONObject) -> Unit, onRelease: () -> Unit = {}, editing: Boolean = false,
                         onMove: (String, Int) -> Unit = { _, _ -> }) {
    var page by remember(profile.optString("id")) { mutableStateOf("Main") }
    val pages = profile.optJSONArray("pages") ?: JSONArray(listOf("Main"))
    val names = (0 until pages.length()).map { pages.getString(it) }
    if (page !in names) page = names.firstOrNull() ?: "Main"
    Column {
        if (names.size > 1) Row(Modifier.horizontalScroll(rememberScrollState())) {
            names.forEach { p -> FilterChip(page == p, { page = p }, label = { Text(p) }) }
        }
        LazyVerticalGrid(columns = GridCells.Adaptive(100.dp), contentPadding = PaddingValues(6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(profile.optJSONArray("controls").rows().filter { it.optString("page", "Main") == page }, key = { it.optString("id") },
                span = { GridItemSpan(if (it.optBoolean("wide")) maxLineSpan else 1) }) { c ->
                val binding = c.optJSONArray("steps")?.optJSONObject(0)
                val player = players.firstOrNull { app.contains(it.optString("id").substringBefore('.'), true) }
                val capability = when (binding?.optString("value")) { "next" -> "can_next"; "previous" -> "can_previous"; "seek" -> "can_seek"; else -> "can_control" }
                val allowed = enabled && (binding?.optString("kind") != "media" || player?.optBoolean(capability) == true || app.isBlank())
                val color = if (c.optBoolean("emphasis")) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant
                val latestEnabled by rememberUpdatedState(allowed)
                val latestPress by rememberUpdatedState(onPress)
                val latestRelease by rememberUpdatedState(onRelease)
                var drag by remember { mutableFloatStateOf(0f) }
                var modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(RoundedCornerShape(12.dp)).background(color)
                    .semantics { contentDescription = c.optString("label") }
                if (editing) modifier = modifier.clickable { onPress(c) }.pointerInput(c.optString("id")) {
                    detectDragGesturesAfterLongPress(onDragStart = { drag = 0f }, onDrag = { change, amount -> change.consume(); drag += amount.y + amount.x },
                        onDragEnd = { if (kotlin.math.abs(drag) > 24) onMove(c.getString("id"), if (drag > 0) 1 else -1) })
                }
                else if (c.optString("mode") == "hold") modifier = modifier.pointerInput(c.optString("id")) {
                    detectTapGestures(onPress = { if (latestEnabled) { latestPress(c); try { tryAwaitRelease() } finally { latestRelease() } } })
                }
                else if (c.optString("mode") == "button") modifier = modifier.clickable(enabled = allowed) { onPress(c) }
                Column(modifier.padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text((c.optString("icon").let { if (it.isBlank()) "" else "$it " }) + c.optString("label"), maxLines = 2,
                        color = if (allowed || editing) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)
                    if (!editing && c.optString("mode") == "slider") {
                        var value by remember(volume?.toString()) { mutableFloatStateOf(volume?.optInt("percent")?.toFloat() ?: 0f) }
                        Slider(value, { value = it }, valueRange = 0f..100f, enabled = enabled && volume != null && !volume.isNull("percent"), onValueChangeFinished = {
                            val copy = c.copyJson(); copy.getJSONArray("steps").getJSONObject(0).put("value", value.toInt().toString()); onPress(copy)
                        })
                    }
                    if (!editing && c.optString("mode") == "toggle") Switch(volume?.optBoolean("muted") ?: false,
                        onCheckedChange = { onPress(c) }, enabled = enabled && volume != null && !volume.isNull("percent"))
                }
            }
        }
    }
}

/** Stop actions and detach input surfaces as soon as Android backgrounds the app. */
@Composable
internal fun WorkspaceForeground(activity: MainActivity, onStop: () -> Unit): Boolean {
    var active by remember { mutableStateOf(activity.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.STARTED)) }
    val stop by rememberUpdatedState(onStop)
    DisposableEffect(activity) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_STOP) { active = false; stop() }
            if (event == androidx.lifecycle.Lifecycle.Event.ON_START) active = true
        }
        activity.lifecycle.addObserver(observer)
        onDispose { activity.lifecycle.removeObserver(observer) }
    }
    return active
}
