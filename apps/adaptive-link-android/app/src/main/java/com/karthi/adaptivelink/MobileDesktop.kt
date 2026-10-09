package com.karthi.adaptivelink

import android.util.AtomicFile
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

internal fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else (0 until length()).map { optString(it) }

/** Phone shell preferences survive process death and are scoped to the paired computer. */
internal class ShellStore(activity: MainActivity, fingerprint: String) {
    private val disk = AtomicFile(File(activity.filesDir, "mobile-shell-$fingerprint.json"))
    var data = try { JSONObject(disk.openRead().bufferedReader().use { it.readText() }) }
        catch (_: java.io.FileNotFoundException) { defaults() }
        catch (_: org.json.JSONException) {
            disk.baseFile.copyTo(File(disk.baseFile.path + ".recovery"), true)
            defaults()
        }
        private set
    fun defaults() = JSONObject().put("schema", 1).put("revision", 0)
        .put("pins", JSONArray(listOf("native:files", "native:control", "native:connections")))
        .put("dock", JSONArray(listOf("native:drawer", "native:files", "native:control")))
        .put("folders", JSONObject()).put("recent", JSONArray())
    @Synchronized fun save(value: JSONObject) {
        val out = disk.startWrite()
        try { out.write(value.toString().toByteArray()); disk.finishWrite(out); data = value.copyJson() }
        catch (error: Exception) { disk.failWrite(out); throw error }
    }
}

private data class ShellApp(val id: String, val name: String, val page: Page? = null, val icon: ImageVector = Icons.Default.Apps)
private val NativeApps = listOf(
    ShellApp("native:control", "Control Center", icon = Icons.Default.Tune), ShellApp("native:files", "Files", Page.Files, Icons.Default.Folder),
    ShellApp("native:tasks", "Tasks", Page.Tasks, Icons.Default.Memory), ShellApp("native:remote", "Desktop Remote", Page.Screen, Icons.Default.DesktopWindows),
    ShellApp("native:workspaces", "Desktop workspaces", Page.Apps, Icons.Default.Dashboard), ShellApp("native:camera", "Camera & microphone", Page.Camera, Icons.Default.Videocam),
    ShellApp("native:scanner", "Scanner", Page.Scan, Icons.Default.DocumentScanner), ShellApp("native:presenter", "Presentation remote", Page.Presenter, Icons.Default.Slideshow),
    ShellApp("native:trackpad", "Laptop trackpad", Page.Trackpad, Icons.Default.TouchApp), ShellApp("native:controls", "Global controls", Page.Controls, Icons.Default.SmartButton),
    ShellApp("native:drawing", "Drawing input", Page.Screen, Icons.Default.Draw), ShellApp("native:media", "Media", Page.Media, Icons.Default.PlayCircle),
    ShellApp("native:run", "Run a command", Page.Run, Icons.Default.Terminal), ShellApp("native:windows", "Laptop windows", Page.Windows, Icons.Default.WebAsset),
    ShellApp("native:gamepad", "Game pad", Page.Gamepad, Icons.Default.SportsEsports),
    // The full set of laptop tools, with the computers paired and pairing another.
    ShellApp("native:connections", "Laptop tools", icon = Icons.Default.Laptop),
    ShellApp("native:drawer", "All apps"), ShellApp("native:recents", "Running apps", icon = Icons.Default.ViewCarousel),
)
/** What a launch in a phone session showed about an app (scripts/link-mobile-compat.py). */
private fun compatibilityNote(app: JSONObject) = when (app.optString("compatibility")) {
    "no-window" -> "May not open on phone"
    "failed" -> "Did not start on phone"
    else -> ""
}
private val ControlSections = listOf("Network & Wi-Fi" to Page.Network, "Bluetooth" to Page.Bluetooth,
    "Sound & displays" to Page.DisplaySound, "Power & accessories" to Page.More, "Storage & devices" to Page.Devices,
    "Desktop & projects" to Page.Desktop, "Tasks & resources" to Page.Tasks, "User services" to Page.Services)

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun MobileDesktop(activity: MainActivity, client: LinkClient, store: Store, state: LinkState,
                           externalPage: Page = Page.Home, consumed: () -> Unit = {},
                           connections: @Composable () -> Unit, native: @Composable (Page, () -> Unit) -> Unit) {
    val tablet = LocalConfiguration.current.smallestScreenWidthDp >= 600
    val scope = rememberCoroutineScope()
    val disk = remember(client.computer.fingerprint) { ShellStore(activity, client.computer.fingerprint) }
    val cache = remember(client.computer.fingerprint) { WorkspaceStore(activity, client.computer, store) }
    var layout by remember(client.computer.fingerprint) { mutableStateOf(disk.data.copyJson()) }
    var location by rememberSaveable(client.computer.fingerprint) { mutableStateOf("home") }
    var nativePage by remember { mutableStateOf<Page?>(null) }
    var session by remember { mutableStateOf<JSONObject?>(null) }
    var apps by remember { mutableStateOf(cache.catalog()) }
    var folderPath by rememberSaveable { mutableStateOf("~") }
    var query by rememberSaveable { mutableStateOf("") }
    var category by rememberSaveable { mutableStateOf("All") }
    var note by remember { mutableStateOf("Connecting to your laptop…") }
    var online by remember { mutableStateOf(false) }
    var supported by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var choices by remember { mutableStateOf<List<JSONObject>?>(null) }
    var selectedApp by rememberSaveable { mutableStateOf("") }
    var organizing by remember { mutableStateOf<JSONObject?>(null) }
    var folderName by remember { mutableStateOf("") }
    var editLayouts by remember { mutableStateOf(false) }
    var controls by remember { mutableStateOf(false) }
    var confirmEnd by remember { mutableStateOf(false) }
    var forceWindow by remember { mutableStateOf<JSONObject?>(null) }
    var run by remember { mutableStateOf<JSONObject?>(null) }
    var pending by remember { mutableStateOf(false) }
    var released by remember { mutableStateOf(false) }
    var confirmation by remember { mutableStateOf<JSONObject?>(null) }
    var prompt by remember { mutableStateOf<JSONObject?>(null) }
    var text by remember { mutableStateOf("") }
    var chosenLayout by remember(selectedApp) { mutableStateOf(cache.selected(selectedApp)) }
    var profileVersion by remember { mutableIntStateOf(0) }
    val profiles = remember(profileVersion, chosenLayout, selectedApp) { cache.profiles().filter { it.optString("app_id") in listOf(selectedApp, "") } }
    val profile = profiles.firstOrNull { it.optString("id") == chosenLayout } ?: profiles.firstOrNull { it.optString("app_id") == selectedApp }
    val id = session?.optString("id").orEmpty()
    fun back() { editLayouts = false; controls = false; nativePage = null; location = "home" }
    BackHandler(location != "home" || editLayouts || controls) { back() }
    LaunchedEffect(externalPage) { if (externalPage != Page.Home) { nativePage = externalPage; location = "native"; consumed() } }
    fun persist(next: JSONObject) {
        next.put("dirty", true)
        disk.save(next); layout = next.copyJson()
    }
    fun toggle(key: String, item: String, limit: Int = 100) {
        val entries = layout.optJSONArray(key).strings().toMutableList()
        if (!entries.remove(item)) entries.add(item)
        persist(layout.copyJson().put(key, JSONArray(entries.takeLast(limit))))
    }
    suspend fun syncShell() {
        if (layout.optBoolean("dirty")) {
            val sent = layout.copyJson()
            val reply = client.post("/v1/mobile/layout", JSONObject().put("revision", sent.optInt("revision")).put("layout", sent))
            if (reply?.optBoolean("ok") == true && layout.toString() == sent.toString()) {
                layout = reply.getJSONObject("layout"); disk.save(layout)
            } else if (reply?.optBoolean("conflict") == true) {
                // Keep local organization as an explicit recovery copy.
                val preserved = layout.copyJson()
                layout = reply.getJSONObject("layout").put("offline_copy", preserved)
                disk.save(layout); note = "Shell changed on the laptop. Your offline organization is preserved."
            }
        } else {
            client.get("/v1/mobile/layout")?.optJSONObject("layout")?.let { remote ->
                if (remote.optInt("revision") > 0) { layout = remote; disk.save(layout) }
            }
        }
    }
    fun stop() {
        released = true
        scope.launch { client.post("/v1/mobile/runs", JSONObject().put("operation", "cancel")) }
    }
    val foreground = WorkspaceForeground(activity) { stop() }
    LaunchedEffect(client, foreground) {
        if (!foreground) return@LaunchedEffect
        var count = 0
        while (true) {
            val status = client.connect()
            state.status = status
            online = status != null
            val capability = status?.optJSONObject("capabilities")?.optJSONObject("mobile_desktop")
            supported = capability?.optBoolean("available") == true
            if (!online) note = "Disconnected · your phone apps stay open on the laptop"
            else if (!supported) note = "Connected · ${client.computer.name} · " + (if (capability == null) "update the laptop service for phone apps; Desktop Remote is available"
                else "phone apps need ${capability.optJSONArray("missing").strings().joinToString()} on the laptop")
            else {
                val reply = client.get("/v1/mobile/sessions")
                session = reply?.optJSONArray("sessions")?.optJSONObject(0)
                if (session?.optString("state") == "failed") note = session?.optString("error").orEmpty()
                else if (!busy && run?.optString("state") != "failed") note = "Connected · ${client.computer.name}"
                if (count % 8 == 0) {
                    client.get("/v1/mobile/apps")?.optJSONArray("apps")?.let { apps = it.rows(); cache.catalog(it) }
                    syncShell(); cache.sync(client); profileVersion++
                }
                if (run?.optString("state") == "running") {
                    val latest = client.get("/v1/mobile/runs")?.optJSONArray("runs").rows().firstOrNull { it.optString("id") == run?.optString("id") }
                    if (latest != null) {
                        run = latest
                        if (latest.optString("state") == "failed") note = "Step ${latest.optInt("step")}: ${latest.optString("error") }"
                        val next = latest.optString("layout")
                        profiles.firstOrNull { it.optString("id") == next || it.optString("name") == next }?.let {
                            chosenLayout = it.getString("id"); cache.select(selectedApp, chosenLayout)
                        }
                    }
                }
            }
            count++; delay(if (run?.optString("state") == "running") 700 else 2000)
        }
    }
    suspend fun ensureSession(): String? {
        if (session?.optString("state") == "ready") return session?.getString("id")
        val reply = client.post("/v1/mobile/sessions", JSONObject().put("operation", "open"))
        if (reply?.optBoolean("ok") != true) { note = reply?.optString("error") ?: "Cannot reach the laptop"; return null }
        session = reply.getJSONObject("session")
        return session?.getString("id")
    }
    fun open(appId: String, new: Boolean = false) {
        layout.optJSONObject("pinned_folders")?.optString(appId)?.takeIf { it.isNotBlank() }?.let {
            folderPath = it; nativePage = Page.Files; location = "native"; return
        }
        val entry = NativeApps.firstOrNull { it.id == appId }
        if (entry != null) {
            when (appId) {
                "native:drawer" -> location = "drawer"
                "native:recents" -> location = "recents"
                "native:control" -> location = "control"
                "native:connections" -> location = "connections"
                else -> { folderPath = "~"; nativePage = entry.page; location = "native" }
            }
            return
        }
        if (appId.contains("control-center")) { location = "control"; return }
        if (!online || !supported || busy) return
        busy = true
        scope.launch {
            try {
                val sid = ensureSession() ?: return@launch
                val reply = client.post("/v1/mobile/apps", JSONObject().put("session", sid).put("app_id", appId).put("new_window", new))
                if (reply?.optBoolean("ok") == true) {
                    if (reply.optString("native") == "control-center") { location = "control"; return@launch }
                    reply.optJSONObject("session")?.let { session = it }
                    choices = reply.optJSONArray("choose_window")?.rows()
                    selectedApp = appId
                    if (cache.profiles().none { it.optString("app_id") == appId }) {
                        starterLayouts(appId, when {
                            appId.contains("firefox") || appId.contains("chrome") -> "browser"
                            appId.contains("code") || appId.contains("gedit") -> "editor"
                            appId.contains("terminal") -> "terminal"
                            appId.contains("impress") -> "presenter"
                            else -> "universal"
                        }).forEach { cache.save(it) }
                        profileVersion++
                    }
                    chosenLayout = cache.selected(appId)
                    persist(layout.copyJson().put("recent", JSONArray((listOf(appId) + layout.optJSONArray("recent").strings().filterNot { it == appId }).take(20))))
                    location = "app"
                } else note = reply?.optString("error") ?: "Connection lost · launch was not retried"
            } finally { busy = false }
        }
    }
    fun window(w: JSONObject, operation: String = "activate", confirmed: Boolean = false) {
        scope.launch {
            val reply = client.post("/v1/mobile/apps", JSONObject().put("session", id).put("operation", operation).put("window", w.optInt("id")).put("confirm", confirmed))
            if (reply?.optBoolean("ok") == true) {
                session = reply.optJSONObject("session") ?: session
                if (operation == "activate" || operation == "close" || operation == "split") { selectedApp = w.optString("app_id"); location = "app" }
                choices = null
            } else note = reply?.optString("error") ?: "Connection lost"
        }
    }
    fun submit(c: JSONObject, confirmed: Boolean = false) {
        if (!online || pending || run?.optString("state") == "running") return
        if (c.optJSONArray("steps").rows().any { it.optBoolean("prompt") }) { prompt = c; text = ""; return }
        pending = true; released = false
        scope.launch {
            try {
                val reply = client.post("/v1/mobile/runs", JSONObject().put("session", id).put("request_id", freshId())
                    .put("app_id", selectedApp).put("steps", c.getJSONArray("steps")).put("hold", c.optString("mode") == "hold").put("confirm", confirmed))
                if (reply?.optBoolean("confirm") == true) confirmation = c
                else if (reply?.optBoolean("ok") == true) {
                    run = reply.getJSONObject("run")
                    if (released && c.optString("mode") == "hold") stop()
                } else note = reply?.optString("error") ?: "Connection lost · action was not retried"
            } finally { pending = false }
        }
    }
    val nativeJson = NativeApps.map { JSONObject().put("id", it.id).put("name", it.name) }
    val folderPins = layout.optJSONObject("pinned_folders") ?: JSONObject()
    val folderApps = folderPins.keys().asSequence().map { key -> JSONObject().put("id", key).put("name", File(folderPins.getString(key)).name.ifBlank { "Home folder" }) }.toList()
    val all = (nativeJson + folderApps + apps.filterNot { it.optString("id").contains("control-center") }).distinctBy { it.optString("id") }
    val running = session?.optJSONArray("apps").rows().filter { it.optString("state") == "running" }.map { it.optString("app_id") }.toSet()
    val folders = layout.optJSONObject("folders") ?: JSONObject()
    val pinned = layout.optJSONArray("pins").strings()
    @Composable fun grid(entries: List<JSONObject>, modifier: Modifier = Modifier) {
        LazyVerticalGrid(GridCells.Adaptive(96.dp), modifier, contentPadding = PaddingValues(12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(entries, key = { it.optString("id") }) { app ->
                val aid = app.optString("id")
                Surface(
                    shape = RoundedCornerShape(18.dp),
                    color = Color(0xFF1C1C1E),
                    border = BorderStroke(0.5.dp, Color(0x22FFFFFF)),
                    modifier = Modifier.heightIn(min = 108.dp).combinedClickable(onClick = { open(aid) }, onLongClick = { organizing = app; folderName = folders.optString(aid) }),
                ) {
                    Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(
                            Modifier.size(46.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xFF2C2C2E)),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (aid.startsWith("native:")) Icon(NativeApps.firstOrNull { it.id == aid }?.icon ?: Icons.Default.Folder,
                                null, Modifier.size(28.dp), tint = MaterialTheme.colorScheme.primary)
                            else AppIcon(client, app)
                        }
                        Spacer(Modifier.height(6.dp))
                        Text(app.optString("name"), maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelMedium, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                        if (aid in running) {
                            Spacer(Modifier.height(2.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(5.dp).clip(CircleShape).background(Color(0xFF30D158)))
                                Spacer(Modifier.width(4.dp))
                                Text("Running", color = Color(0xFF30D158), fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
                            }
                        } else compatibilityNote(app).takeIf { it.isNotEmpty() }?.let {
                            Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 10.sp)
                        }
                    }
                }
            }
        }
    }
    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        if (editLayouts) {
            Box(Modifier.weight(1f)) { LayoutManager(activity, client, cache, selectedApp,
                apps.firstOrNull { it.optString("id") == selectedApp }?.optString("name") ?: "Custom controls", profile,
                onBack = { editLayouts = false; profileVersion++ }, test = { submit(it) }) }
        } else when (location) {
            "native" -> Box(Modifier.weight(1f)) {
                if (nativePage == Page.Files) FilesPage(activity, client, folderPath, onOpen = { path ->
                    scope.launch {
                        val sid = ensureSession() ?: return@launch
                        val reply = client.post("/v1/mobile/apps", JSONObject().put("session", sid).put("operation", "open-file").put("path", path))
                        if (reply?.optBoolean("ok") == true) { session = reply.getJSONObject("session"); selectedApp = session?.optString("selected_app").orEmpty(); location = "app" }
                        else note = reply?.optString("error") ?: "Connection lost · file open was not retried"
                    }
                }, onPin = { path ->
                    val key = "native:folder:" + path.hashCode().toString()
                    persist(layout.copyJson().put("pinned_folders", folderPins.copyJson().put(key, path)).put("pins", JSONArray((pinned + key).distinct())))
                    note = "Folder pinned to Home"
                }, onBack = ::back)
                else nativePage?.let { native(it, ::back) }
            }
            "connections" -> Box(Modifier.weight(1f)) { connections() }
            "control" -> Column(Modifier.weight(1f)) {
                TopBar("Control Center", ::back)
                Text("Laptop settings · changes apply directly", Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium)
                LazyColumn { items(ControlSections) { (title, page) ->
                    ListItem(headlineContent = { Text(title) }, leadingContent = { Icon(Icons.Default.Tune, null) },
                        modifier = Modifier.combinedClickable(onClick = { nativePage = page; location = "native" }))
                } }
            }
            "recents" -> Column(Modifier.weight(1f)) {
                TopBar("Running apps", ::back) { TextButton(onClick = { confirmEnd = true }, enabled = id.isNotEmpty()) { Text("End session") } }
                val windows = session?.optJSONArray("windows").rows()
                if (windows.isEmpty()) Text("No phone applications are open", Modifier.padding(24.dp))
                LazyColumn { items(windows, key = { it.optInt("id") }) { w ->
                    ListItem(headlineContent = { Text(w.optString("title"), maxLines = 2) }, supportingContent = { Text(w.optString("app_id").ifEmpty { "Unassigned phone window" }) },
                        modifier = Modifier.combinedClickable(onClick = { window(w) }), trailingContent = {
                            Row {
                                if (tablet && w.optInt("id") != session?.optInt("selected_window")) IconButton(onClick = { window(w, "split") }) { Icon(Icons.Default.ViewWeek, "Show beside current app") }
                                IconButton(onClick = { window(w, "close") }) { Icon(Icons.Default.Close, "Close normally") }
                                IconButton(onClick = { forceWindow = w }) { Icon(Icons.Default.MoreVert, "Force quit options") } }
                        })
                } }
            }
            "app" -> Column(Modifier.weight(1f)) {
                val appName = apps.firstOrNull { it.optString("id") == selectedApp }?.optString("name") ?: "Phone application"
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { choices = session?.optJSONArray("windows").rows().filter { it.optString("app_id") == selectedApp } }) { Text("Windows") }
                    TextButton(onClick = { open(selectedApp, true) }) { Text("New") }
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { controls = !controls }) { Text("Controls") }
                }
                if (session?.optInt("selected_window") != 0 && session?.optString("state") == "ready") {
                    Box(Modifier.weight(1f)) { key(id) { ScreenPage(activity, client, store, mobileSession = id, appTitle = appName,
                        contentStamp = session?.optJSONArray("canvas").toString(), onBack = ::back) } }
                } else Column(Modifier.weight(1f).padding(20.dp), verticalArrangement = Arrangement.Center) {
                    Text(session?.optJSONArray("apps").rows().firstOrNull { it.optString("app_id") == selectedApp }?.optString("message") ?: "Choose a phone window to continue")
                    TextButton(onClick = { open(selectedApp, true) }) { Text("Retry launch") }
                    TextButton(onClick = { location = "recents" }) { Text("Choose a window") }
                }
                if (controls) Column(Modifier.heightIn(max = 280.dp)) {
                    Row(Modifier.horizontalScroll(rememberScrollState())) {
                        profiles.forEach { p -> FilterChip(p.optString("id") == profile?.optString("id"), {
                            chosenLayout = p.getString("id"); cache.select(selectedApp, chosenLayout)
                        }, label = { Text(p.optString("name")) }) }
                        TextButton(onClick = { editLayouts = true }) { Text("Edit layouts") }
                    }
                    profile?.let { ControlGrid(it, online && !pending && run?.optString("state") != "running", onPress = { c -> submit(c) }, onRelease = ::stop) }
                }
            }
            else -> Column(Modifier.weight(1f)) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { Text(if (location == "drawer") "All apps" else "Home", style = MaterialTheme.typography.headlineMedium)
                        Text(client.computer.name, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    IconButton(onClick = { location = "control" }, modifier = Modifier.size(36.dp).clip(CircleShape).background(Color(0x22FFFFFF))) {
                        Icon(Icons.Default.Tune, "Control Center", modifier = Modifier.size(18.dp), tint = Color(0xFFF5F5F7))
                    }
                }
                if (location == "drawer") {
                    OutlinedTextField(
                        value = query, onValueChange = { query = it },
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                        placeholder = { Text("Spotlight Search…", color = Color(0xFF8E8E93)) },
                        leadingIcon = { Icon(Icons.Default.Search, null, tint = Color(0xFF8E8E93)) },
                        trailingIcon = { if (query.isNotEmpty()) IconButton(onClick = { query = "" }) { Icon(Icons.Default.Close, null, tint = Color(0xFF8E8E93)) } },
                        shape = RoundedCornerShape(16.dp),
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedContainerColor = Color(0xFF1C1C1E),
                            unfocusedContainerColor = Color(0xFF1C1C1E),
                            focusedBorderColor = Color(0xFF0A84FF),
                            unfocusedBorderColor = Color(0x22FFFFFF),
                        ),
                    )
                    val categories = listOf("All", "Favorites") + apps.flatMap { it.optJSONArray("categories").strings() }.filter { it.isNotBlank() }.distinct().sorted() +
                        folders.keys().asSequence().map { folders.optString(it) }.filter { it.isNotBlank() }.distinct().map { "Folder: $it" }.toList()
                    Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        categories.forEach { c -> FilterChip(category == c, { category = c }, label = { Text(c) }) }
                    }
                    grid(all.filter { app -> app.optString("name").contains(query, true) && when {
                        category == "All" -> true
                        category == "Favorites" -> app.optString("id") in pinned
                        category.startsWith("Folder: ") -> folders.optString(app.optString("id")) == category.removePrefix("Folder: ")
                        else -> category in app.optJSONArray("categories").strings()
                    } }.sortedBy { it.optString("name").lowercase() }, Modifier.weight(1f))
                } else {
                    layout.optJSONObject("offline_copy")?.let { copy -> TextButton(onClick = {
                        persist(copy.copyJson().put("revision", layout.optInt("revision")))
                    }) { Text("Restore offline Home organization") } }
                    if (running.isNotEmpty()) {
                        Surface(
                            shape = RoundedCornerShape(14.dp),
                            color = Color(0x2230D158),
                            border = BorderStroke(0.5.dp, Color(0x5530D158)),
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp).combinedClickable(onClick = { location = "recents" }),
                        ) {
                            Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFF30D158)))
                                Spacer(Modifier.width(8.dp))
                                Text("Active Stage · ${running.size} running app${if (running.size > 1) "s" else ""}", color = Color(0xFF30D158), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                            }
                        }
                    }
                    val recent = layout.optJSONArray("recent").strings().take(6)
                    Text("Pinned", Modifier.padding(start = 16.dp, top = 4.dp), style = MaterialTheme.typography.titleSmall, color = Color(0xFF8E8E93))
                    grid(pinned.mapNotNull { pin -> all.firstOrNull { it.optString("id") == pin } }, Modifier.weight(1f))
                    if (recent.isNotEmpty()) {
                        Text("Recent", Modifier.padding(start = 16.dp), style = MaterialTheme.typography.titleSmall, color = Color(0xFF8E8E93))
                        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            recent.forEach { aid ->
                                val app = all.firstOrNull { it.optString("id") == aid }
                                Surface(
                                    shape = RoundedCornerShape(12.dp),
                                    color = Color(0xFF1C1C1E),
                                    border = BorderStroke(0.5.dp, Color(0x22FFFFFF)),
                                    modifier = Modifier.combinedClickable(onClick = { open(aid) }),
                                ) {
                                    Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                        Box(Modifier.size(20.dp), contentAlignment = Alignment.Center) {
                                            if (aid.startsWith("native:")) Icon(NativeApps.firstOrNull { it.id == aid }?.icon ?: Icons.Default.Apps, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                                            else AppIcon(client, app ?: JSONObject().put("id", aid))
                                        }
                                        Spacer(Modifier.width(6.dp))
                                        Text(app?.optString("name") ?: aid, fontSize = 12.sp, color = Color(0xFFF5F5F7), fontWeight = FontWeight.Medium)
                                    }
                                }
                            }
                        }
                    }
                    // Apple iOS Floating Frosted Glass Dock
                    Box(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Surface(
                            shape = RoundedCornerShape(28.dp),
                            color = Color(0x77202024),
                            border = BorderStroke(0.5.dp, Color(0x33FFFFFF)),
                            tonalElevation = 8.dp,
                        ) {
                            Row(
                                Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                                horizontalArrangement = Arrangement.spacedBy(14.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                layout.optJSONArray("dock").strings().forEach { aid ->
                                    val app = all.firstOrNull { it.optString("id") == aid }
                                    val isRunning = aid in running
                                    Column(
                                        horizontalAlignment = Alignment.CenterHorizontally,
                                        modifier = Modifier.combinedClickable(onClick = { open(aid) }, onLongClick = { organizing = app }),
                                    ) {
                                        Box(
                                            Modifier.size(48.dp).clip(RoundedCornerShape(13.dp))
                                                .background(Color(0xFF2C2C2E)),
                                            contentAlignment = Alignment.Center,
                                        ) {
                                            if (aid.startsWith("native:")) {
                                                Icon(NativeApps.firstOrNull { it.id == aid }?.icon ?: Icons.Default.Apps,
                                                    null, Modifier.size(26.dp), tint = MaterialTheme.colorScheme.primary)
                                            } else {
                                                AppIcon(client, app ?: JSONObject().put("id", aid))
                                            }
                                        }
                                        Spacer(Modifier.height(3.dp))
                                        if (isRunning) {
                                            Box(Modifier.size(4.dp).clip(CircleShape).background(Color(0xFF30D158)))
                                        } else {
                                            Spacer(Modifier.height(4.dp))
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (run?.optString("state") == "running") Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Step ${run?.optInt("step")}/${run?.optInt("total")}", Modifier.weight(1f).padding(12.dp))
            Button(onClick = ::stop) { Text("Stop") }
        }
        if (location != "app" || !online || note.startsWith("Step")) Text(note, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), style = MaterialTheme.typography.bodySmall)
        NavigationBar(
            containerColor = Color(0xFF141416),
            tonalElevation = 8.dp,
        ) {
            NavigationBarItem(
                selected = location == "home", onClick = { back() },
                icon = { Icon(Icons.Default.Home, "Home") },
                label = { Text("Home", fontWeight = FontWeight.Medium) },
            )
            NavigationBarItem(
                selected = location == "drawer", onClick = { location = "drawer"; editLayouts = false },
                icon = { Icon(Icons.Default.Apps, "Apps") },
                label = { Text("All Apps", fontWeight = FontWeight.Medium) },
            )
            NavigationBarItem(
                selected = location == "recents", onClick = { location = "recents"; editLayouts = false },
                icon = { Icon(Icons.Default.ViewCarousel, "Recents") },
                label = { Text("Stage", fontWeight = FontWeight.Medium) },
            )
        }
    }
    organizing?.let { app ->
        val aid = app.optString("id")
        AlertDialog(onDismissRequest = { organizing = null }, title = { Text(app.optString("name")) }, text = {
            Column {
                Text(aid, style = MaterialTheme.typography.bodySmall)
                app.optJSONArray("categories").strings().filter { it.isNotBlank() }.takeIf { it.isNotEmpty() }?.let {
                    Text(it.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                compatibilityNote(app).takeIf { it.isNotEmpty() }?.let {
                    Text("$it. Opening it again retries; nothing opens on the laptop.", style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = { toggle("pins", aid) }) { Text(if (aid in pinned) "Unpin from Home" else "Pin to Home / Favorite") }
                TextButton(onClick = { toggle("dock", aid, 6) }) { Text(if (aid in layout.optJSONArray("dock").strings()) "Remove from dock" else "Add to dock") }
                TextButton(onClick = { val entries = layout.optJSONArray("pins").strings(); persist(layout.copyJson().put("pins", JSONArray(listOf(aid) + entries.filterNot { it == aid }))) }) { Text("Move to first position") }
                OutlinedTextField(folderName, { folderName = it }, label = { Text("Drawer folder (blank removes)") })
                if (!aid.startsWith("native:")) TextButton(onClick = { selectedApp = aid; editLayouts = true; organizing = null }) { Text("Custom controls") }
                if (aid in running) TextButton(onClick = { session?.optJSONArray("windows").rows().filter { it.optString("app_id") == aid }.forEach { window(it, "close") }; organizing = null }) { Text("Close application") }
            }
        }, confirmButton = { TextButton(onClick = { persist(layout.copyJson().put("folders", folders.copyJson().put(aid, folderName.trim()))); organizing = null }) { Text("Done") } })
    }
    choices?.let { windows -> AlertDialog(onDismissRequest = { choices = null }, title = { Text("Choose a phone window") }, text = {
        LazyColumn { items(windows) { w -> TextButton(onClick = { window(w) }) { Text(w.optString("title")) } } }
    }, confirmButton = { TextButton(onClick = { choices = null }) { Text("Cancel") } }) }
    confirmation?.let { c -> AlertDialog(onDismissRequest = { confirmation = null }, title = { Text("Run laptop action?") },
        text = { Text(c.optString("label")) }, confirmButton = { TextButton(onClick = { confirmation = null; submit(c, true) }) { Text("Run") } },
        dismissButton = { TextButton(onClick = { confirmation = null }) { Text("Cancel") } }) }
    prompt?.let { c -> AlertDialog(onDismissRequest = { prompt = null }, title = { Text(c.optString("label")) }, text = {
        OutlinedTextField(text, { text = it }, label = { Text("Text to insert") })
    }, confirmButton = { TextButton(onClick = {
        val copy = c.copyJson(); copy.optJSONArray("steps").rows().filter { it.optBoolean("prompt") }.forEach { it.put("prompt", false).put("value", text) }
        prompt = null; submit(copy)
    }) { Text("Send") } }) }
    forceWindow?.let { w -> AlertDialog(onDismissRequest = { forceWindow = null }, title = { Text("Force quit?") },
        text = { Text("Unsaved work in ${w.optString("title")} may be lost.") }, confirmButton = { TextButton(onClick = { forceWindow = null; window(w, "force-quit", true) }) { Text("Force quit") } },
        dismissButton = { TextButton(onClick = { forceWindow = null }) { Text("Cancel") } }) }
    if (confirmEnd) AlertDialog(onDismissRequest = { confirmEnd = false }, title = { Text("End phone session") },
        text = { Text("Close normally to save your work. Force end discards unsaved changes in phone applications.") },
        confirmButton = { TextButton(onClick = { confirmEnd = false; scope.launch {
            val reply = client.post("/v1/mobile/sessions", JSONObject().put("session", id).put("operation", "end"))
            note = reply?.optString("error")?.ifEmpty { "Session ended" } ?: "Connection lost"
            if (reply?.optBoolean("pending") == true) { session = reply.optJSONObject("session"); selectedApp = session?.optString("selected_app").orEmpty(); location = "app" }
            else { session = null; location = "home" }
        } }) { Text("Close normally") } }, dismissButton = { TextButton(onClick = { confirmEnd = false; scope.launch {
            client.post("/v1/mobile/sessions", JSONObject().put("session", id).put("operation", "force-end").put("confirm", true)); session = null; location = "home"
        } }) { Text("Force end") } })
}
