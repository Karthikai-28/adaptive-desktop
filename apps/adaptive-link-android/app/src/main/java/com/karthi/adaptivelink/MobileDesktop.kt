package com.karthi.adaptivelink

import android.util.AtomicFile
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
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
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
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
        .put("pins", JSONArray(listOf("native:office", "native:files", "native:control", "native:connections")))
        .put("dock", JSONArray(listOf("native:drawer", "native:files", "native:control")))
        .put("folders", JSONObject()).put("recent", JSONArray()).put("office_pinned", true)
    init {
        // Home screens saved before the Office existed get it pinned once; unpinning it later sticks.
        if (!data.optBoolean("office_pinned")) {
            val pins = data.optJSONArray("pins").strings()
            runCatching { save(data.copyJson().put("pins", JSONArray(listOf("native:office") + pins.filterNot { it == "native:office" })).put("office_pinned", true)) }
        }
    }
    @Synchronized fun save(value: JSONObject) {
        val out = disk.startWrite()
        try { out.write(value.toString().toByteArray()); disk.finishWrite(out); data = value.copyJson() }
        catch (error: Exception) { disk.failWrite(out); throw error }
    }
}

private data class ShellApp(val id: String, val name: String, val page: Page? = null, val icon: ImageVector = Icons.Default.Apps)
private val NativeApps = listOf(
    ShellApp("native:island", "Dynamic Island", Page.Island, Icons.Default.HorizontalRule),
    ShellApp("native:office", "Office", Page.Office, Icons.Default.Groups),
    ShellApp("native:control", "Control Center", icon = Icons.Default.Tune), ShellApp("native:files", "Files", Page.Files, Icons.Default.Folder),
    ShellApp("native:tasks", "Tasks", Page.Tasks, Icons.Default.Memory), ShellApp("native:remote", "Desktop Remote", Page.Screen, Icons.Default.DesktopWindows),
    ShellApp("native:workspaces", "Desktop workspaces", Page.Apps, Icons.Default.Dashboard), ShellApp("native:camera", "Camera & microphone", Page.Camera, Icons.Default.Videocam),
    ShellApp("native:scanner", "Scanner", Page.Scan, Icons.Default.DocumentScanner), ShellApp("native:presenter", "Presentation remote", Page.Presenter, Icons.Default.Slideshow),
    ShellApp("native:trackpad", "Laptop trackpad", Page.Trackpad, Icons.Default.TouchApp), ShellApp("native:controls", "Global controls", Page.Controls, Icons.Default.SmartButton),
    ShellApp("native:drawing", "Ink Studio", Page.Ink, Icons.Default.Draw), ShellApp("native:media", "Media", Page.Media, Icons.Default.PlayCircle),
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
private val ControlSections = listOf("Dynamic Island" to Page.Island, "Network & Wi-Fi" to Page.Network, "Bluetooth" to Page.Bluetooth,
    "Sound & displays" to Page.DisplaySound, "Power & accessories" to Page.More, "Storage & devices" to Page.Devices,
    "Desktop & projects" to Page.Desktop, "Tasks & resources" to Page.Tasks, "User services" to Page.Services)

private fun usageColour(used: Double) = when {
    used >= 95 -> Color(0xFFFF453A)
    used >= 80 -> Color(0xFFFF9F0A)
    else -> Color(0xFF0A84FF)
}

@Composable
private fun AiUsageCard(usage: JSONObject?, loading: Boolean, message: String, retry: () -> Unit) {
    var weekly by remember { mutableStateOf(false) }
    val providers = listOf("codex" to "Codex", "claude" to "Claude", "gemini" to "Gemini")
    fun window(provider: JSONObject?, week: Boolean): JSONObject? = provider?.optJSONArray("windows").rows()
        .firstOrNull { !it.optBoolean("expired") && it.optString("label").startsWith("Weekly", true) == week }
    Surface(
        shape = RoundedCornerShape(14.dp), color = Color(0xFF1C1C1E),
        border = BorderStroke(0.5.dp, Color(0x22FFFFFF)),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)
            .pointerInput(Unit) {
                var distance = 0f
                detectHorizontalDragGestures(onHorizontalDrag = { _, amount -> distance += amount }, onDragEnd = {
                    if (kotlin.math.abs(distance) > 48f) weekly = distance < 0
                    distance = 0f
                })
            }) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.AutoAwesome, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(6.dp))
                Text("AI usage", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                if (loading) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 1.5.dp)
                else IconButton(onClick = retry, modifier = Modifier.size(48.dp)) { Icon(Icons.Default.Refresh, "Refresh AI usage", Modifier.size(20.dp)) }
            }
            if (message.isNotBlank()) Text(message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(8.dp))
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                listOf(false to "Current", true to "Weekly").forEachIndexed { index, (week, title) ->
                    SegmentedButton(selected = weekly == week, onClick = { weekly = week },
                        shape = SegmentedButtonDefaults.itemShape(index, 2), label = { Text(title) })
                }
            }
            Spacer(Modifier.height(5.dp))
            AnimatedContent(weekly, transitionSpec = { fadeIn(spring()) togetherWith fadeOut(spring()) }, label = "usage-window") { selectedWeek ->
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    providers.forEach { (key, label) ->
                        val provider = usage?.optJSONObject(key)
                        val reading = UsageState.window(usage, key, selectedWeek)
                        val used = reading?.optDouble("used")?.takeIf { it.isFinite() }?.toFloat()?.coerceIn(0f, 100f)
                        val progress by animateFloatAsState(used ?: 0f, animationSpec = spring(), label = "$key-progress")
                        val tint by animateColorAsState(used?.let { usageColour(it.toDouble()) } ?: Color(0xFF48484A), label = "$key-color")
                        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Color(0xFF2C2C2E)).padding(horizontal = 10.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(label, Modifier.width(62.dp), fontSize = 12.sp, fontWeight = FontWeight.Medium)
                            Column(Modifier.weight(1f)) {
                                LinearProgressIndicator(progress = { progress / 100f }, Modifier.fillMaxWidth().height(5.dp).clip(CircleShape), color = tint, trackColor = Color(0xFF48484A))
                                Text(reading?.optString("label").orEmpty().ifBlank { if (provider?.optString("error").isNullOrBlank()) "Not reported" else "Unavailable" }, fontSize = 10.sp, color = Color(0xFFAEAEB2), maxLines = 1)
                            }
                            Text(used?.let { "${it.toInt()}%" } ?: "—", Modifier.width(42.dp), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = tint, textAlign = androidx.compose.ui.text.style.TextAlign.End)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun MobileDesktop(activity: MainActivity, client: LinkClient, store: Store, state: LinkState,
                           externalPage: Page = Page.Home, consumed: () -> Unit = {},
                           externalApp: String? = null, appConsumed: () -> Unit = {},
                           connections: @Composable () -> Unit, native: @Composable (Page, () -> Unit) -> Unit) {
    val tablet = LocalConfiguration.current.smallestScreenWidthDp >= 600
    val scope = rememberCoroutineScope()
    val configuration = LocalConfiguration.current
    val disk = remember(client.computer.fingerprint) { ShellStore(activity, client.computer.fingerprint) }
    val cache = remember(client.computer.fingerprint) { WorkspaceStore(activity, client.computer, store) }
    val restoredShell = remember(client.computer.fingerprint) {
        runCatching { JSONObject(store.shellState(client.computer.fingerprint)) }.getOrElse { JSONObject() }
    }
    val restoredRoutes = remember(client.computer.fingerprint) {
        ShellRoutes.normalize(restoredShell.optString("stack", restoredShell.optString("route", "home"))).split('|')
    }
    val initialRoute = restoredRoutes.last()
    val navController = rememberNavController()
    val navEntry by navController.currentBackStackEntryAsState()
    var layout by remember(client.computer.fingerprint) { mutableStateOf(disk.data.copyJson()) }
    var location by rememberSaveable(client.computer.fingerprint) { mutableStateOf(initialRoute) }
    var routeStack by rememberSaveable(client.computer.fingerprint) { mutableStateOf(restoredRoutes.joinToString("|")) }
    var restoringNavigation by remember(client.computer.fingerprint) { mutableStateOf(restoredRoutes.size > 1) }
    var nativePage by rememberSaveable(client.computer.fingerprint) {
        mutableStateOf(restoredShell.optString("native").takeIf { it.isNotBlank() }?.let { runCatching { Page.valueOf(it) }.getOrNull() })
    }
    var session by remember { mutableStateOf<JSONObject?>(null) }
    var apps by remember { mutableStateOf(cache.catalog()) }
    var laptopApps by remember { mutableStateOf(emptyList<JSONObject>()) }
    var hostLoaded by remember { mutableStateOf(false) }
    var liveSession by remember { mutableStateOf<JSONObject?>(null) }
    var liveClosed by remember { mutableStateOf(false) }
    var restoringLive by remember { mutableStateOf(false) }
    var folderPath by rememberSaveable { mutableStateOf(restoredShell.optString("folder", "~")) }
    var query by rememberSaveable { mutableStateOf(restoredShell.optString("query")) }
    var drawerFocused by remember { mutableStateOf(false) }
    val compactDrawer = location == "drawer" && (drawerFocused || WindowInsets.ime.getBottom(androidx.compose.ui.platform.LocalDensity.current) > 0)
    var category by rememberSaveable { mutableStateOf(restoredShell.optString("category", "All")) }
    var note by remember { mutableStateOf("Connecting to your laptop…") }
    val usageCache = remember(client.computer.fingerprint) { UsageCache(activity, client.computer.fingerprint) }
    var aiUsage by remember(client.computer.fingerprint) { mutableStateOf(usageCache.read()) }
    var usageLoading by remember { mutableStateOf(false) }
    var usageMessage by remember { mutableStateOf("Waiting for computer connection") }
    var usageRetry by remember { mutableIntStateOf(0) }
    var refreshEpoch by remember { mutableIntStateOf(0) }
    var reconnectEpoch by remember { mutableIntStateOf(0) }
    var handledReconnect by remember { mutableIntStateOf(0) }
    var online by remember { mutableStateOf(false) }
    var supported by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var choices by remember { mutableStateOf<List<JSONObject>?>(null) }
    var selectedApp by rememberSaveable { mutableStateOf(restoredShell.optString("selected_app")) }
    var organizing by remember { mutableStateOf<JSONObject?>(null) }
    var folderName by remember { mutableStateOf("") }
    var editLayouts by remember { mutableStateOf(false) }
    var controls by remember { mutableStateOf(false) }
    var confirmEnd by remember { mutableStateOf(false) }
    // The laptop app starting in the phone session, for the launch animation.
    var launching by remember { mutableStateOf<JSONObject?>(null) }
    var homeMenu by remember { mutableStateOf(false) }
    var layoutMenu by remember { mutableStateOf(false) }
    // A laptop app whose profile another copy has open: on the laptop or another phone.
    var held by remember { mutableStateOf<JSONObject?>(null) }
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
    fun visit(destination: String, replace: Boolean = false) {
        if (destination == location) return
        routeStack = ShellRoutes.push(if (replace) "home" else routeStack, destination)
        location = destination
        navController.navigate(destination) { launchSingleTop = true }
    }
    fun goHome() {
        editLayouts = false; controls = false; nativePage = null
        routeStack = "home"; location = "home"
        navController.navigate("home") {
            popUpTo(navController.graph.id) { inclusive = true }
            launchSingleTop = true
        }
    }
    fun back() {
        when {
            editLayouts -> { editLayouts = false; profileVersion++; return }
            controls -> { controls = false; return }
        }
        val previous = ShellRoutes.pop(routeStack)
        routeStack = previous.first
        location = previous.second
        navController.popBackStack()
        if (location != "native") nativePage = null
    }
    BackHandler(editLayouts || controls) { back() }
    LaunchedEffect(navController, client.computer.fingerprint) {
        // Navigation Compose restores its own stack after rotation/ordinary
        // process recreation. The persisted route list covers cold process
        // recreation too, without creating duplicate entries in the former.
        val current = navController.currentDestination?.route
        if (restoringNavigation && current == "home") {
            restoredRoutes.drop(1).forEach { route ->
                navController.navigate(route) { launchSingleTop = true }
            }
        }
        restoringNavigation = false
    }
    LaunchedEffect(navEntry?.destination?.route) {
        if (restoringNavigation) return@LaunchedEffect
        val route = navEntry?.destination?.route ?: return@LaunchedEffect
        location = route
        val known = ShellRoutes.normalize(routeStack).split('|')
        val index = known.indexOfLast { it == route }
        if (index >= 0) routeStack = known.take(index + 1).joinToString("|")
    }
    LaunchedEffect(externalPage) { if (externalPage != Page.Home) { nativePage = externalPage; visit("native"); consumed() } }
    LaunchedEffect(client.computer.fingerprint, online, usageRetry) {
        if (!online) { usageLoading = false; usageMessage = if (aiUsage == null) "Computer offline · reconnect to load usage" else "Saved usage · computer offline"; return@LaunchedEffect }
        var usagePolls = 0
        while (isActive) {
            usageLoading = true
            try {
                val reply = withTimeoutOrNull(12_000) { client.get("/v1/ai-usage") }
                if (UsageState.valid(reply)) {
                    aiUsage = reply
                    usageCache.save(reply!!)
                    if (usagePolls++ % 4 == 0) UsageWidget.refresh(activity)
                    usageMessage = if (UsageState.stale(reply)) "Some providers have older or missing reports" else "Updated just now"
                } else {
                    usageMessage = if (aiUsage != null) "Showing saved usage · refresh failed" else "Usage unavailable · check the laptop service and retry"
                }
            } catch (cancelled: CancellationException) { throw cancelled
            } catch (_: Exception) { usageMessage = "Could not load usage · tap refresh to retry"
            } finally { usageLoading = false }
            delay(30_000)
        }
    }
    LaunchedEffect(location, routeStack, nativePage, query, category, selectedApp, folderPath) {
        store.shellState(client.computer.fingerprint, JSONObject().put("route", location).put("stack", routeStack)
            .put("native", nativePage?.name ?: "").put("query", query).put("category", category)
            .put("selected_app", selectedApp).put("folder", folderPath).toString())
    }
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
    fun continueWindow(app: JSONObject, window: JSONObject, presentation: String = "mirror", restoring: Boolean = false) {
        if (busy || liveSession != null) return
        busy = true
        if (!restoring) visit("continue")
        scope.launch {
            try {
                val size = if (configuration.orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE) "1280x800" else "800x1280"
                val answer = client.post("/v1/app-sessions", JSONObject().put("app_id", app.getString("id"))
                    .put("window_id", window.getInt("id")).put("presentation", presentation).put("size", size))
                if (answer?.optBoolean("ok") == true) {
                    val opened = answer.getJSONObject("session")
                    liveSession = opened
                    liveClosed = false
                    store.continuity(client.computer.fingerprint, ContinuityDescriptor(client.computer.fingerprint,
                        opened.optString("app_id"), opened.optInt("window_id"), opened.optString("presentation", "mirror")).json())
                    if (location != "continue") visit("continue")
                } else {
                    liveClosed = true
                    note = answer?.optString("error") ?: "Cannot reach the laptop"
                }
            } finally {
                busy = false
                restoringLive = false
            }
        }
    }
    fun stop() {
        released = true
        scope.launch { client.post("/v1/mobile/runs", JSONObject().put("operation", "cancel")) }
    }
    val foreground = WorkspaceForeground(activity) { stop() }
    LaunchedEffect(client, foreground, refreshEpoch, reconnectEpoch) {
        if (!foreground) return@LaunchedEffect
        if (handledReconnect != reconnectEpoch) {
            client.networkChanged()
            handledReconnect = reconnectEpoch
        }
        var count = 0
        while (true) {
            state.connecting = true
            val status = try {
                withTimeoutOrNull(45_000) { client.connect() }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                note = "Connection failed · ${error.message?.takeIf { it.isNotBlank() } ?: "tap Retry to try again"}"
                null
            }
            state.connecting = false
            state.status = status
            online = status != null
            val capability = status?.optJSONObject("capabilities")?.optJSONObject("mobile_desktop")
            val continuity = status?.optJSONObject("capabilities")?.optInt("continuity") == 1
            supported = capability?.optBoolean("available") == true
            if (!online && !note.startsWith("Connection failed")) note = client.awayProblem.ifBlank {
                "Disconnected · your phone apps stay open on the laptop"
            }
            else if (!supported) note = "Connected · ${client.computer.name} · " + (if (capability == null) "update the laptop service for phone apps; Desktop Remote is available"
                else "phone apps need ${capability.optJSONArray("missing").strings().joinToString()} on the laptop")
            else {
                val reply = client.get("/v1/mobile/sessions")
                session = reply?.optJSONArray("sessions")?.optJSONObject(0)
                if (session?.optString("state") == "failed") note = session?.optString("error").orEmpty()
                else if (!busy && run?.optString("state") != "failed") note = "Connected · ${client.computer.name}"
                if (count % 8 == 0) {
                    client.get("/v1/mobile/apps")?.optJSONArray("apps")?.let { apps = it.rows(); cache.catalog(it) }
                    if (continuity) client.get("/v1/apps")?.optJSONArray("apps")?.let { laptopApps = it.rows(); hostLoaded = true }
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
    LaunchedEffect(location, hostLoaded, laptopApps, liveSession) {
        if (location != "continue" || !hostLoaded || liveSession != null || restoringLive || busy) return@LaunchedEffect
        val descriptor = ContinuityDescriptor.parse(store.continuity(client.computer.fingerprint))
        val appId = descriptor?.appId.orEmpty()
        val windowId = descriptor?.windowId ?: 0
        val app = laptopApps.firstOrNull { it.optString("id") == appId }
        val window = app?.optJSONArray("windows").rows().firstOrNull { it.optInt("id") == windowId }
        if (app != null && window != null) {
            restoringLive = true
            continueWindow(app, window, descriptor?.presentation ?: "mirror", restoring = true)
        } else if (appId.isNotEmpty()) {
            liveClosed = true
        }
    }
    suspend fun ensureSession(): String? {
        if (session?.optString("state") == "ready") return session?.getString("id")
        val reply = client.post("/v1/mobile/sessions", JSONObject().put("operation", "open").put("phone", PhoneScreen.whole(activity, store.phoneSharpness)))
        if (reply?.optBoolean("ok") != true) { note = reply?.optString("error") ?: "Cannot reach the laptop"; return null }
        session = reply.getJSONObject("session")
        return session?.getString("id")
    }
    fun open(appId: String, new: Boolean = false, take: Boolean = false) {
        layout.optJSONObject("pinned_folders")?.optString(appId)?.takeIf { it.isNotBlank() }?.let {
            folderPath = it; nativePage = Page.Files; visit("native"); return
        }
        val entry = NativeApps.firstOrNull { it.id == appId }
        if (entry != null) {
            when (appId) {
                "native:drawer" -> visit("drawer")
                "native:recents" -> visit("recents")
                "native:control" -> visit("control")
                "native:connections" -> visit("connections")
                else -> { folderPath = "~"; nativePage = entry.page; visit("native") }
            }
            return
        }
        if (appId.contains("control-center")) { visit("control"); return }
        if (!online || !supported || busy) return
        busy = true
        if (session?.optJSONArray("apps").rows().none { it.optString("app_id") == appId && it.optString("state") == "running" }) launching = JSONObject().put("id", appId)
            .put("name", (apps + laptopApps).firstOrNull { it.optString("id") == appId }?.optString("name") ?: "Laptop app")
            .put("layout", session?.optJSONObject("layouts")?.optString(appId)?.ifBlank { null } ?: "phone")
        scope.launch {
            try {
                val sid = ensureSession() ?: return@launch
                val reply = client.post("/v1/mobile/apps", JSONObject().put("session", sid).put("app_id", appId).put("new_window", new).put("take", take))
                reply?.optJSONObject("held")?.let { held = it; return@launch }
                if (reply?.optBoolean("ok") == true) {
                    if (reply.optString("native") == "control-center") { visit("control"); return@launch }
                    if (reply.optString("native") == "files") { folderPath = "~"; nativePage = Page.Files; visit("native"); return@launch }
                    if (reply.optString("learned") == "compact") note = "Opened in compact layout: this app is wider than a phone. Change it under Layout."
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
                    visit("app")
                } else note = reply?.optString("error") ?: "Connection lost · launch was not retried"
            } finally { busy = false; launching = null }
        }
    }
    /** Phone, compact or desktop layout for an app; a running app is reopened in it. */
    fun relayout(appId: String, mode: String) {
        if (id.isEmpty() || busy) return
        busy = true
        launching = JSONObject().put("id", appId).put("layout", mode)
            .put("name", (apps + laptopApps).firstOrNull { it.optString("id") == appId }?.optString("name") ?: "Laptop app")
        scope.launch {
            try {
                val reply = client.post("/v1/mobile/apps", JSONObject().put("session", id).put("operation", "layout")
                    .put("app_id", appId).put("layout", mode).put("reopen", true))
                reply?.optJSONObject("session")?.let { session = it }
                reply?.optJSONObject("held")?.let { held = it }
                note = when {
                    reply == null -> "Connection lost"
                    reply.has("held") -> note
                    reply.optBoolean("pending") -> reply.optString("error")
                    reply.optBoolean("ok") -> "${launching?.optString("name")} · ${mode.replaceFirstChar { it.uppercase() }} layout"
                    else -> reply.optString("error")
                }
            } finally { busy = false; launching = null }
        }
    }
    /** The laptop's profile (signed in as there) or one of this phone's own; a running app is reopened with it. */
    fun useProfile(appId: String, profile: String, openAfter: Boolean = false) {
        if (id.isEmpty() || busy) return
        busy = true
        scope.launch {
            var start = false
            try {
                val reply = client.post("/v1/mobile/apps", JSONObject().put("session", id).put("operation", "profile")
                    .put("app_id", appId).put("profile", profile).put("reopen", true))
                reply?.optJSONObject("session")?.let { session = it }
                reply?.optJSONObject("held")?.let { held = it }
                note = when {
                    reply == null -> "Connection lost"
                    reply.has("held") -> note
                    reply.optBoolean("pending") || !reply.optBoolean("ok") -> reply.optString("error")
                    profile == "phone" -> "Opens with this phone's own profile from now on"
                    else -> "Opens with the laptop's profile from now on"
                }
                start = openAfter && reply?.optBoolean("ok") == true && !reply.optBoolean("running")
            } finally { busy = false }
            if (start) open(appId)
        }
    }
    /** Closes the app here and opens it on the laptop: one computer, the app goes where you are. */
    fun toLaptop(appId: String) {
        if (id.isEmpty() || busy) return
        busy = true
        val name = (apps + laptopApps).firstOrNull { it.optString("id") == appId }?.optString("name") ?: "The app"
        scope.launch {
            try {
                val reply = client.post("/v1/mobile/apps", JSONObject().put("session", id).put("operation", "to-laptop").put("app_id", appId))
                reply?.optJSONObject("session")?.let { session = it }
                if (reply?.optString("moved") == "laptop") { note = "$name is open on the laptop"; back() }
                else note = reply?.optString("error") ?: "Connection lost"
            } finally { busy = false }
        }
    }
    fun window(w: JSONObject, operation: String = "activate", confirmed: Boolean = false) {
        scope.launch {
            val reply = client.post("/v1/mobile/apps", JSONObject().put("session", id).put("operation", operation).put("window", w.optInt("id")).put("confirm", confirmed))
            if (reply?.optBoolean("ok") == true) {
                session = reply.optJSONObject("session") ?: session
                if (operation == "activate" || operation == "close" || operation == "split") { selectedApp = w.optString("app_id"); visit("app") }
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
    val all = (nativeJson + folderApps + laptopApps + apps.filterNot { it.optString("id").contains("control-center") }).distinctBy { it.optString("id") }
    val liveWindows = laptopApps.flatMap { app -> app.optJSONArray("windows").rows().map { app to it } }
        .sortedWith(compareByDescending<Pair<JSONObject, JSONObject>> { it.second.optBoolean("active") }
            .thenBy { it.second.optString("title").lowercase() })
    val running = session?.optJSONArray("apps").rows().filter { it.optString("state") == "running" }.map { it.optString("app_id") }.toSet()
    val folders = layout.optJSONObject("folders") ?: JSONObject()
    val pinned = layout.optJSONArray("pins").strings()
    val launcherApps = (pinned + layout.optJSONArray("recent").strings()).filterNot { it.startsWith("native:") }
        .mapNotNull { pin -> all.firstOrNull { it.optString("id") == pin }?.let { pin to it.optString("name") } }
    LaunchedEffect(launcherApps) { if (online && launcherApps.isNotEmpty()) runCatching { LaptopApps.publish(activity, client, launcherApps) } }
    LaunchedEffect(externalApp, online, supported) {
        val wanted = externalApp ?: return@LaunchedEffect
        if (online && supported) { appConsumed(); open(wanted) }
    }
    fun activate(appId: String) {
        val live = liveWindows.firstOrNull { it.first.optString("id") == appId }
        if (live != null) continueWindow(live.first, live.second) else open(appId)
    }
    @Composable fun grid(entries: List<JSONObject>, modifier: Modifier = Modifier) {
        LazyVerticalGrid(GridCells.Adaptive(96.dp), modifier, contentPadding = PaddingValues(12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(entries, key = { it.optString("id") }) { app ->
                val aid = app.optString("id")
                Surface(
                    shape = RoundedCornerShape(22.dp),
                    color = MaterialTheme.colorScheme.surface,
                    border = BorderStroke(0.5.dp, Color(0x22FFFFFF)),
                    modifier = Modifier.animateItem().heightIn(min = 108.dp).clip(RoundedCornerShape(22.dp))
                        .pressable(onLongClick = { organizing = app; folderName = folders.optString(aid) }) { activate(aid) },
                ) {
                    Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(
                            Modifier.size(46.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
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
                                PulseDot(Color(0xFF30D158), 5)
                                Spacer(Modifier.width(2.dp))
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
    Box(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        if (location != "continue" && location != "app" && !compactDrawer && !(location == "native" && nativePage == Page.Office)) LinkActivityIsland(online, busy, running.size, client.computer.name, note,
            onOpen = { visit("recents") }, onSettings = { nativePage = Page.Island; visit("native") },
            onRefresh = { refreshEpoch++; usageRetry++ }, onReconnect = { online = false; state.status = null; note = "Reconnecting…"; reconnectEpoch++; usageRetry++ })
        if (editLayouts) {
            Box(Modifier.weight(1f)) { LayoutManager(activity, client, cache, selectedApp,
                apps.firstOrNull { it.optString("id") == selectedApp }?.optString("name") ?: "Custom controls", profile,
                onBack = { editLayouts = false; profileVersion++ }, test = { submit(it) }) }
        } else NavHost(navController, startDestination = "home", modifier = Modifier.weight(1f),
            enterTransition = Motion.enter, exitTransition = Motion.exit, popEnterTransition = Motion.popEnter, popExitTransition = Motion.popExit) {
            ShellRoutes.destinations.forEach { destination -> composable(destination) { when (destination) {
            "continue" -> Box(Modifier.fillMaxSize()) {
                liveSession?.let { current ->
                    AppWorkspace(activity, client, store, cache, current, onExpired = {
                        liveSession = null
                        liveClosed = true
                    }) {
                        liveSession = null
                        back()
                    }
                } ?: Column(Modifier.fillMaxSize()) {
                    TopBar("Continue", ::back)
                    if (busy || restoringLive) LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(if (liveClosed) "Window closed" else "Reconnecting to the exact laptop window…",
                        Modifier.padding(horizontal = 16.dp, vertical = 8.dp), style = MaterialTheme.typography.titleMedium)
                    if (liveClosed) Text("Nothing was relaunched. Choose a matching live window, or go back.",
                        Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.bodySmall)
                    val descriptor = ContinuityDescriptor.parse(store.continuity(client.computer.fingerprint))
                    val matches = liveWindows.filter { descriptor == null || it.first.optString("id") == descriptor.appId }
                    LazyColumn(Modifier.weight(1f)) {
                        items(matches, key = { it.second.optInt("id") }) { (app, window) ->
                            ListItem(
                                headlineContent = { Text(window.optString("title").ifBlank { app.optString("name") }, maxLines = 2) },
                                supportingContent = { Text(app.optString("name")) },
                                leadingContent = { AppIcon(client, app) },
                                modifier = Modifier.combinedClickable(onClick = { liveClosed = false; continueWindow(app, window) }),
                            )
                        }
                    }
                }
            }
            "native" -> Box(Modifier.fillMaxSize()) {
                if (nativePage == Page.Files) FilesPage(activity, client, folderPath, onOpen = { path ->
                    scope.launch {
                        val sid = ensureSession() ?: return@launch
                        val reply = client.post("/v1/mobile/apps", JSONObject().put("session", sid).put("operation", "open-file").put("path", path))
                        if (reply?.optBoolean("ok") == true) { session = reply.getJSONObject("session"); selectedApp = session?.optString("selected_app").orEmpty(); visit("app") }
                        else note = reply?.optString("error") ?: "Connection lost · file open was not retried"
                    }
                }, onPin = { path ->
                    val key = "native:folder:" + path.hashCode().toString()
                    persist(layout.copyJson().put("pinned_folders", folderPins.copyJson().put(key, path)).put("pins", JSONArray((pinned + key).distinct())))
                    note = "Folder pinned to Home"
                }, onBack = ::back)
                else nativePage?.let { native(it, ::back) }
            }
            "connections" -> Box(Modifier.fillMaxSize()) { connections() }
            "control" -> Column(Modifier.fillMaxSize()) {
                TopBar("Control Center", ::back)
                Text("Everything within reach", Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(ControlSections) { (title, page) ->
                        val symbol = when (page) {
                            Page.Island -> Icons.Default.HorizontalRule
                            Page.Network -> Icons.Default.Wifi
                            Page.Bluetooth -> Icons.Default.Bluetooth
                            Page.DisplaySound -> Icons.Default.VolumeUp
                            Page.More -> Icons.Default.PowerSettingsNew
                            Page.Devices -> Icons.Default.Storage
                            Page.Desktop -> Icons.Default.DesktopWindows
                            Page.Tasks -> Icons.Default.Memory
                            else -> Icons.Default.Settings
                        }
                        ListItem(headlineContent = { Text(title, fontWeight = FontWeight.Medium) },
                            leadingContent = { Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.primaryContainer) {
                                Icon(symbol, null, Modifier.padding(10.dp).size(22.dp), tint = MaterialTheme.colorScheme.primary)
                            } }, trailingContent = { Icon(Icons.Default.ChevronRight, null, tint = MaterialTheme.colorScheme.onSurfaceVariant) },
                            modifier = Modifier.clip(RoundedCornerShape(20.dp)).combinedClickable(onClick = { nativePage = page; visit("native") }))
                    }
                }
            }
            "recents" -> Column(Modifier.fillMaxSize()) {
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
            "app" -> Column(Modifier.fillMaxSize()) {
                val appName = apps.firstOrNull { it.optString("id") == selectedApp }?.optString("name") ?: "Phone application"
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { choices = session?.optJSONArray("windows").rows().filter { it.optString("app_id") == selectedApp } }) { Text("Windows") }
                    TextButton(onClick = { open(selectedApp, true) }) { Text("New") }
                    Spacer(Modifier.weight(1f))
                    val current = session?.optJSONObject("layouts")?.optString(selectedApp)?.ifBlank { null } ?: "phone"
                    Box {
                        TextButton(onClick = { layoutMenu = true }) {
                            Icon(when (current) { "desktop" -> Icons.Default.DesktopWindows; "compact" -> Icons.Default.TabletAndroid; else -> Icons.Default.PhoneAndroid },
                                null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Layout")
                        }
                        DropdownMenu(layoutMenu, { layoutMenu = false }) {
                            listOf(Triple("phone", "Phone", "The app's own phone layout, full size"),
                                Triple("compact", "Compact", "For apps wider than a phone: readable text, smaller controls"),
                                Triple("desktop", "Desktop", "As on the laptop, a little larger; desktop websites")).forEach { (mode, label, detail) ->
                                DropdownMenuItem(text = { Column { Text(label, fontWeight = if (mode == current) FontWeight.SemiBold else FontWeight.Normal)
                                    Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } },
                                    leadingIcon = { RadioButton(mode == current, null) },
                                    onClick = { layoutMenu = false; if (mode != current) relayout(selectedApp, mode) })
                            }
                            HorizontalDivider()
                            val profileNow = session?.optJSONObject("profiles")?.optString(selectedApp)?.ifBlank { null } ?: "laptop"
                            Text("Profile", Modifier.padding(start = 16.dp, top = 8.dp, bottom = 4.dp), style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            listOf(Triple("laptop", "The laptop's", "Signed in and set up as on the laptop"),
                                Triple("phone", "This phone's own", "A separate profile: sign in again here")).forEach { (choice, label, detail) ->
                                DropdownMenuItem(text = { Column { Text(label, fontWeight = if (choice == profileNow) FontWeight.SemiBold else FontWeight.Normal)
                                    Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } },
                                    leadingIcon = { RadioButton(choice == profileNow, null) },
                                    onClick = { layoutMenu = false; if (choice != profileNow) useProfile(selectedApp, choice) })
                            }
                            HorizontalDivider()
                            DropdownMenuItem(text = { Text("Move to laptop") }, leadingIcon = { Icon(Icons.Default.Laptop, null) },
                                onClick = { layoutMenu = false; toLaptop(selectedApp) })
                        }
                    }
                    TextButton(onClick = { controls = !controls }) { Text("Controls") }
                }
                if (session?.optInt("selected_window") != 0 && session?.optString("state") == "ready") {
                    Box(Modifier.weight(1f)) { key(id) { ScreenPage(activity, client, store, mobileSession = id, appTitle = appName,
                        contentStamp = session?.optJSONArray("canvas").toString(), onBack = ::back) } }
                } else Column(Modifier.weight(1f).padding(20.dp), verticalArrangement = Arrangement.Center) {
                    Text(session?.optJSONArray("apps").rows().firstOrNull { it.optString("app_id") == selectedApp }?.optString("message") ?: "Choose a phone window to continue")
                    TextButton(onClick = { open(selectedApp, true) }) { Text("Retry launch") }
                    TextButton(onClick = { visit("recents") }) { Text("Choose a window") }
                }
                androidx.compose.animation.AnimatedVisibility(controls, enter = androidx.compose.animation.expandVertically(androidx.compose.animation.core.tween(300, easing = Motion.Emphasized)) + androidx.compose.animation.fadeIn(),
                    exit = androidx.compose.animation.shrinkVertically(androidx.compose.animation.core.tween(200, easing = Motion.EmphasizedAccelerate)) + androidx.compose.animation.fadeOut()) { Column(Modifier.heightIn(max = 280.dp)) {
                    Row(Modifier.horizontalScroll(rememberScrollState())) {
                        profiles.forEach { p -> FilterChip(p.optString("id") == profile?.optString("id"), {
                            chosenLayout = p.getString("id"); cache.select(selectedApp, chosenLayout)
                        }, label = { Text(p.optString("name")) }) }
                        TextButton(onClick = { editLayouts = true }) { Text("Edit layouts") }
                    }
                    profile?.let { ControlGrid(it, online && !pending && run?.optString("state") != "running", onPress = { c -> submit(c) }, onRelease = ::stop) }
                } }
            }
            else -> Column(Modifier.fillMaxSize().then(if (destination == "home") Modifier.verticalScroll(rememberScrollState()) else Modifier)) {
                if (!compactDrawer) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) { Text(if (location == "drawer") "All apps" else "Home", style = MaterialTheme.typography.headlineMedium)
                        Text(client.computer.name, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    IconButton(onClick = { visit("control") }, modifier = Modifier.size(48.dp).clip(CircleShape).background(Color(0x22FFFFFF))) {
                        Icon(Icons.Default.Tune, "Control Center", modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurface)
                    }
                    Spacer(Modifier.width(8.dp))
                    Box {
                        IconButton(onClick = { homeMenu = true }, modifier = Modifier.size(48.dp).clip(CircleShape).background(Color(0x22FFFFFF))) {
                            Icon(Icons.Default.MoreVert, "Phone apps settings", modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurface)
                        }
                        DropdownMenu(homeMenu, { homeMenu = false }) {
                            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S) DropdownMenuItem(
                                text = { Text("Wallpaper colours") }, leadingIcon = { Icon(Icons.Default.Palette, null) },
                                trailingIcon = { Switch(activity.wallpaperColours, null) },
                                onClick = { activity.wallpaperColours = !activity.wallpaperColours; store.wallpaperColours = activity.wallpaperColours })
                            HorizontalDivider()
                            Text("Sharpness of laptop apps", Modifier.padding(horizontal = 16.dp, vertical = 8.dp), style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            var sharp by remember { mutableStateOf(store.phoneSharpness) }
                            listOf("auto" to "Automatic (2×)", "1" to "Light (1×) · least data", "2" to "Sharp (2×)", "3" to "Sharpest (3×) · most data").forEach { (value, label) ->
                                DropdownMenuItem(text = { Text(label) }, leadingIcon = { RadioButton(sharp == value, null) }, onClick = {
                                    sharp = value; store.phoneSharpness = value
                                    note = "Apps opened from now on are drawn at this sharpness"
                                })
                            }
                        }
                    }
                }
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { refreshEpoch++; usageRetry++ }, enabled = !busy) { Icon(Icons.Default.Refresh, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Refresh") }
                    TextButton(onClick = { online = false; state.status = null; note = "Reconnecting…"; reconnectEpoch++; usageRetry++ }, enabled = !busy) { Icon(Icons.Default.Link, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Reconnect") }
                }
                }
                if (location == "drawer") {
                    OutlinedTextField(
                        value = query, onValueChange = { query = it },
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp).onFocusChanged { drawerFocused = it.isFocused },
                        placeholder = { Text("Search your apps", color = Color(0xFF8E8E93)) },
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
                    AiUsageCard(aiUsage, usageLoading, usageMessage) { usageRetry++ }
                    if (liveWindows.isNotEmpty()) {
                        Text("Continue", Modifier.padding(start = 16.dp, top = 4.dp), style = MaterialTheme.typography.titleSmall, color = Color(0xFF8E8E93))
                        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 6.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            liveWindows.forEach { (app, window) ->
                                Surface(shape = RoundedCornerShape(14.dp), color = Color(0xFF1C1C1E),
                                    border = BorderStroke(0.5.dp, if (window.optBoolean("active")) Color(0x660A84FF) else Color(0x22FFFFFF))) {
                                    Column(Modifier.width(220.dp).padding(10.dp)) {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            AppIcon(client, app)
                                            Column(Modifier.padding(start = 8.dp)) {
                                                Text(window.optString("title").ifBlank { app.optString("name") }, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                                Text(app.optString("name"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                            }
                                        }
                                        Row {
                                            TextButton(onClick = { continueWindow(app, window) }) { Text("Continue") }
                                            TextButton(onClick = { open(app.optString("id")) }) { Text("Open phone copy") }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if (running.isNotEmpty()) {
                        Surface(
                            shape = RoundedCornerShape(14.dp),
                            color = Color(0x2230D158),
                            border = BorderStroke(0.5.dp, Color(0x5530D158)),
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp).combinedClickable(onClick = { visit("recents") }),
                        ) {
                            Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFF30D158)))
                                Spacer(Modifier.width(8.dp))
                                Text("Phone workspace · ${running.size} running app${if (running.size > 1) "s" else ""}", color = Color(0xFF30D158), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                            }
                        }
                    }
                    val recent = layout.optJSONArray("recent").strings().take(6)
                    Text("Pinned", Modifier.padding(start = 16.dp, top = 4.dp), style = MaterialTheme.typography.titleSmall, color = Color(0xFF8E8E93))
                    val pinnedEntries = pinned.mapNotNull { pin -> all.firstOrNull { it.optString("id") == pin } }
                    val columns = ((configuration.screenWidthDp - 14) / 106).coerceAtLeast(1)
                    grid(pinnedEntries, Modifier.height((((pinnedEntries.size + columns - 1) / columns) * 128 + 24).dp))
                    if (recent.isNotEmpty()) {
                        Text("Recent", Modifier.padding(start = 16.dp), style = MaterialTheme.typography.titleSmall, color = Color(0xFF8E8E93))
                        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            recent.forEach { aid ->
                                val app = all.firstOrNull { it.optString("id") == aid }
                                Surface(
                                    shape = RoundedCornerShape(12.dp),
                                    color = Color(0xFF1C1C1E),
                                    border = BorderStroke(0.5.dp, Color(0x22FFFFFF)),
                                    modifier = Modifier.combinedClickable(onClick = { activate(aid) }),
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
                                        modifier = Modifier.combinedClickable(onClick = { activate(aid) }, onLongClick = { organizing = app }),
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
        } } } }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (run?.optString("state") == "running") Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Step ${run?.optInt("step")}/${run?.optInt("total")}", Modifier.weight(1f).padding(12.dp))
            Button(onClick = ::stop) { Text("Stop") }
        }
        // The Office has its own tabs and connection line: it fills the screen without the shell's.
        val ownChrome = (location == "native" && nativePage == Page.Office) || location == "continue"
        if (!ownChrome && (location != "app" || !online || note.startsWith("Step"))) Text(note, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), style = MaterialTheme.typography.bodySmall)
        if (!ownChrome) NavigationBar(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp).clip(RoundedCornerShape(30.dp)),
            containerColor = Color(0xFF1C1C1E),
            windowInsets = WindowInsets(0, 0, 0, 0),
            tonalElevation = 0.dp,
        ) {
            NavigationBarItem(
                selected = location == "home", onClick = { goHome() },
                icon = { Icon(Icons.Default.Home, "Home") },
                label = { Text("Home", fontWeight = FontWeight.Medium) },
            )
            NavigationBarItem(
                selected = location == "drawer", onClick = { editLayouts = false; visit("drawer") },
                icon = { Icon(Icons.Default.Apps, "Apps") },
                label = { Text("All Apps", fontWeight = FontWeight.Medium) },
            )
            NavigationBarItem(
                selected = location == "recents", onClick = { editLayouts = false; visit("recents") },
                icon = { Icon(Icons.Default.ViewCarousel, "Recents") },
                label = { Text("Running", fontWeight = FontWeight.Medium) },
            )
        }
    }
    LaunchOverlay(launching != null, launching?.optString("name").orEmpty(), launching?.optString("layout").orEmpty()) {
        launching?.let { app -> AppIcon(client, app) }
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
                if (!aid.startsWith("native:")) TextButton(onClick = {
                    val name = app.optString("name"); organizing = null
                    scope.launch { if (!LaptopApps.pin(activity, client, aid, name)) note = "This launcher cannot add shortcuts" }
                }) { Text("Add to phone home screen") }
                if (aid in running) TextButton(onClick = { session?.optJSONArray("windows").rows().filter { it.optString("app_id") == aid }.forEach { window(it, "close") }; organizing = null }) { Text("Close application") }
            }
        }, confirmButton = { TextButton(onClick = { persist(layout.copyJson().put("folders", folders.copyJson().put(aid, folderName.trim()))); organizing = null }) { Text("Done") } })
    }
    held?.let { h ->
        val appId = h.optString("app_id")
        val name = h.optString("name").ifBlank { "This app" }
        val onLaptop = h.optString("where") == "laptop"
        val live = liveWindows.firstOrNull { it.first.optString("id") == appId }
        AlertDialog(onDismissRequest = { held = null },
            icon = { Icon(if (onLaptop) Icons.Default.Laptop else Icons.Default.PhoneAndroid, null) },
            title = { Text(if (onLaptop) "$name is open on the laptop" else "$name is open on your other phone") },
            text = { Text(if (onLaptop) "The phone and the laptop share its profile and sign-ins, and only one copy can have them open. " +
                "Move it here: it closes on the laptop as if you closed it there, then opens on the phone. If it asks to save, answer it on the laptop."
                else "Only one copy can have its profile open. Close it on the other phone, or give it a profile of this phone's own.") },
            confirmButton = {
                if (onLaptop) TextButton(onClick = { held = null; open(appId, take = true) }) { Text("Move here") }
                else TextButton(onClick = { held = null; useProfile(appId, "phone", openAfter = true) }) { Text("Use this phone's profile") }
            },
            dismissButton = { Row {
                if (onLaptop && live != null) TextButton(onClick = { held = null; continueWindow(live.first, live.second) }) { Text("Its laptop window") }
                TextButton(onClick = { held = null }) { Text("Cancel") }
            } })
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
            if (reply?.optBoolean("pending") == true) { session = reply.optJSONObject("session"); selectedApp = session?.optString("selected_app").orEmpty(); visit("app") }
            else { session = null; goHome() }
        } }) { Text("Close normally") } }, dismissButton = { TextButton(onClick = { confirmEnd = false; scope.launch {
            client.post("/v1/mobile/sessions", JSONObject().put("session", id).put("operation", "force-end").put("confirm", true)); session = null; goHome()
        } }) { Text("Force end") } })
}
