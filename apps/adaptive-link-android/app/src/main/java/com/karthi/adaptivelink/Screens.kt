package com.karthi.adaptivelink

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.BatteryStd
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material.icons.filled.DesktopWindows
import androidx.compose.material.icons.filled.SettingsSuggest
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.Window
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Usb
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.Mouse
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.Slideshow
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

// ------------------------------------------------------------ building blocks

@Composable
fun TopBar(title: String, onBack: (() -> Unit)? = null, trailing: @Composable () -> Unit = {}) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) {
            IconButton(
                onClick = onBack,
                modifier = Modifier.size(36.dp).clip(CircleShape).background(Color(0x22FFFFFF)),
            ) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", modifier = Modifier.size(18.dp), tint = Color(0xFFF5F5F7)) }
            Spacer(Modifier.width(10.dp))
        } else {
            Spacer(Modifier.width(8.dp))
        }
        Text(title, fontSize = 21.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFF5F5F7), modifier = Modifier.weight(1f))
        trailing()
    }
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) {
    Text(text, color = Color(0xFF8E8E93), fontSize = 13.sp, modifier = modifier)
}

@Composable
fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(
        modifier
            .clip(RoundedCornerShape(22.dp))
            .background(Color(0xFF1C1C1E))
            .border(0.5.dp, Color(0x22FFFFFF), RoundedCornerShape(22.dp))
            .padding(18.dp)
    ) { content() }
}

// ------------------------------------------------------------------ pairing

@Composable
fun PairScreen(activity: MainActivity, onPaired: () -> Unit) {
    val scope = rememberCoroutineScope()
    var stage by remember { mutableStateOf("start") }   // start, asking, confirm, failed
    var code by remember { mutableStateOf("") }
    var computerName by remember { mutableStateOf("") }
    var problem by remember { mutableStateOf("") }

    var typed by remember { mutableStateOf("") }

    val cloud = remember { Cloud(activity) }
    var account by remember { mutableStateOf("") }
    var signedIn by remember { mutableStateOf(cloud.signedIn) }
    var withCode by remember { mutableStateOf(!cloud.available) }
    var choices by remember { mutableStateOf(listOf<Pair<String, Computer>>()) }

    /** By code or by account, asking the computer is the same from here. */
    fun ask(offer: PairingOffer) {
        stage = "asking"
        scope.launch {
          try {
            val client = LinkClient(activity, offer.computer)
            val answer = client.requestPairing(offer.token, activity.phoneName())
            val expected = Protocol.pairingCode(offer.computer.fingerprint, LinkIdentity.fingerprint(activity))
            when {
                answer == null -> {
                    problem = "The computer did not answer.\n" + client.lastProblem
                    stage = "failed"
                }
                answer.optString("code") != expected -> {
                    // The computer computed the digits from a different pair
                    // of certificates than this phone sees: stop here.
                    problem = answer.optString("error").ifBlank { "The pairing could not be verified." }
                    stage = "failed"
                }
                else -> {
                    code = expected
                    computerName = answer.optString("host", offer.computer.name)
                    stage = "confirm"
                    // A computer set to accept its own account's devices
                    // answers "paired" straight away.
                    when (answer.optString("state").ifEmpty { client.awaitPairing(offer.token) }) {
                        "paired" -> {
                            Store(activity).computer = offer.computer
                            Link.forget()
                            onPaired()
                        }
                        "rejected" -> { problem = "The pairing was rejected on the computer."; stage = "failed" }
                        else -> { problem = "Pairing timed out. Start again from the computer."; stage = "failed" }
                    }
                }
            }
          } catch (e: Exception) {
            // Whatever went wrong, say it on the screen: a pairing that
            // fails silently, or by closing the app, cannot be diagnosed.
            problem = "Pairing failed: ${e.javaClass.simpleName}: ${e.message}"
            stage = "failed"
          }
        }
    }

    /** Scanned or typed, a pairing code is handled the same way. */
    fun begin(scanned: String) {
        val offer = PairingOffer.parse(scanned)
        if (offer == null) {
            problem = "That is not an Adaptive Link pairing code."
            stage = "failed"
            return
        }
        account = ""
        ask(offer)
    }

    /**
     * No code: ask the computer through the account both are signed in to.
     * The request, and the answer, go through the account's space; what the
     * owner checks is the same six digits, on the same two screens.
     */
    fun askByAccount(id: String, computer: Computer) {
        stage = "asking"
        scope.launch {
            try {
                val mine = Cloud.deviceId(LinkIdentity.fingerprint(activity))
                // An answer left from an earlier request is not this one's.
                cloud.delete("computers/$id/accepted/$mine")
                cloud.put("phones/$mine", org.json.JSONObject()
                    .put("name", activity.phoneName()).put("want", id)
                    .put("cert", Protocol.pem(LinkIdentity.certificate(activity).encoded))
                    .put("at", System.currentTimeMillis() / 1000.0))
                code = Protocol.pairingCode(computer.fingerprint, LinkIdentity.fingerprint(activity))
                computerName = computer.name
                stage = "confirm"
                var answer: Any? = null
                val until = System.currentTimeMillis() + 10 * 60_000
                while (answer !is Boolean && System.currentTimeMillis() < until) {
                    delay(1500)
                    answer = runCatching { cloud.get("computers/$id/accepted/$mine") }.getOrNull()
                }
                when (answer) {
                    true -> {
                        Store(activity).computer = computer
                        Link.forget()
                        onPaired()
                    }
                    false -> { problem = "The pairing was rejected on the computer."; stage = "failed" }
                    else -> { problem = "Nobody answered on $computerName. Is it on?"; stage = "failed" }
                }
            } catch (e: Exception) {
                problem = "Pairing failed: ${e.message ?: e.javaClass.simpleName}"
                stage = "failed"
            }
        }
    }

    fun signIn() {
        stage = "asking"
        activity.awayOnPurpose = true
        scope.launch {
            try {
                account = if (cloud.signedIn) cloud.email else cloud.signIn(activity)
                signedIn = true
                val found = cloud.computers()
                when (found.size) {
                    0 -> {
                        problem = "No computer is signed in as $account.\nOn the computer, run: link-cli.py signin"
                        stage = "failed"
                    }
                    1 -> askByAccount(found[0].first, found[0].second)
                    else -> { choices = found; stage = "choose" }
                }
            } catch (e: androidx.credentials.exceptions.GetCredentialCancellationException) {
                stage = "start"
            } catch (e: androidx.credentials.exceptions.NoCredentialException) {
                problem = "This phone has no Google account to sign in with. Add one in Settings, or use a pairing code."
                stage = "failed"
            } catch (e: Exception) {
                problem = "Sign-in failed: ${e.message ?: e.javaClass.simpleName}"
                stage = "failed"
            }
        }
    }

    val scanner = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { begin(it) }
    }

    Column(
        Modifier.fillMaxSize().systemBarsPadding().padding(28.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Adaptive Link", fontSize = 28.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(12.dp))
        // A computer on this network that is waiting to be paired with: no code to scan.
        if (stage == "start") NearbyComputers { ask(it) }
        when (stage) {
            "asking" -> {
                CircularProgressIndicator()
                Spacer(Modifier.height(16.dp))
                Muted("Contacting the computer…")
            }
            "choose" -> {
                Muted("Signed in as $account. Which computer?", Modifier.padding(bottom = 12.dp))
                choices.forEach { (id, computer) ->
                    OutlinedButton(onClick = { askByAccount(id, computer) }, modifier = Modifier.fillMaxWidth()) {
                        Text(computer.name)
                    }
                    Spacer(Modifier.height(8.dp))
                }
            }
            "confirm" -> {
                if (account.isNotEmpty()) Muted("Signed in as $account", Modifier.padding(bottom = 4.dp))
                Muted("Check that $computerName shows the same digits, then press Pair there.", Modifier.padding(8.dp))
                Spacer(Modifier.height(16.dp))
                Text("${code.take(3)} ${code.drop(3)}", fontSize = 44.sp, fontWeight = FontWeight.Bold, letterSpacing = 4.sp)
                Spacer(Modifier.height(20.dp))
                CircularProgressIndicator()
            }
            else -> {
                Text(
                    if (stage == "failed") problem
                    else if (cloud.available) "Sign in with the Google account your computer is signed in to. The computer then asks you to confirm this phone."
                    else "Pair this phone with your computer using the code it shows.",
                    textAlign = TextAlign.Center,
                    color = if (stage == "failed") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(24.dp))
                if (cloud.available) {
                    Button(onClick = { signIn() }) {
                        Text(if (signedIn) "Find my computer" else "Sign in with Google")
                    }
                    if (signedIn) {
                        TextButton(onClick = { cloud.signOut(); signedIn = false; account = ""; stage = "start" }) {
                            Text("Sign out of ${cloud.email}")
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                }
                if (!withCode) {
                    TextButton(onClick = { withCode = true }) { Text("Use a pairing code instead") }
                } else {
                    OutlinedButton(onClick = {
                        activity.awayOnPurpose = true
                        scanner.launch(
                            ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                .setPrompt("Scan the code on your computer").setBeepEnabled(false).setOrientationLocked(true)
                        )
                    }) { Text("Scan pairing code") }
                    Spacer(Modifier.height(8.dp))
                    // The same code the QR holds, for when it cannot be
                    // scanned: the computer shows it under the QR code.
                    OutlinedTextField(
                        value = typed, onValueChange = { typed = it },
                        placeholder = { Text("ALINK1\u2026") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(onClick = { begin(typed) }, enabled = typed.isNotBlank()) { Text("Pair with this code") }
                }
                Spacer(Modifier.height(20.dp))
                Muted(
                    "This phone's key is made in its secure hardware and never leaves it. " +
                        "Only this phone will be able to connect.",
                    Modifier.padding(horizontal = 8.dp),
                )
            }
        }
    }
}

// --------------------------------------------------------------------- home

private data class Tile(val page: Page, val label: String, val detail: String, val icon: ImageVector)

private val TILES = listOf(
    Tile(Page.Screen, "Screen", "See and control", Icons.Filled.DesktopWindows),
    Tile(Page.Trackpad, "Trackpad", "Pointer and keyboard", Icons.Filled.Mouse),
    Tile(Page.Media, "Media", "Play, pause, volume", Icons.Filled.PlayCircle),
    Tile(Page.Presenter, "Presenter", "Slides, with a timer", Icons.Filled.Slideshow),
    Tile(Page.Apps, "Apps", "Your apps and saved layouts", Icons.Filled.Apps),
    Tile(Page.Run, "Run", "Commands and apps", Icons.Filled.Terminal),
    Tile(Page.Files, "Files", "Browse, open, send", Icons.Filled.Folder),
    Tile(Page.Camera, "Webcam", "This phone's camera", Icons.Filled.Videocam),
    Tile(Page.Tasks, "Tasks", "Processes and load", Icons.Filled.Memory),
    Tile(Page.Devices, "Devices", "USB and drives", Icons.Filled.Usb),
    Tile(Page.Network, "Network", "Connections and traffic", Icons.Filled.Wifi),
    Tile(Page.Desktop, "Desktop", "Projects, focus, windows", Icons.Filled.Dashboard),
    Tile(Page.Controls, "Controls", "Your own buttons", Icons.Filled.Apps),
    Tile(Page.Scan, "Scan", "Paper to a PDF", Icons.Filled.DocumentScanner),
    Tile(Page.Windows, "Windows", "Switch, move, close", Icons.Filled.Window),
    Tile(Page.DisplaySound, "Display", "Screens and sound", Icons.Filled.Tune),
    Tile(Page.Bluetooth, "Bluetooth", "Devices nearby", Icons.Filled.Bluetooth),
    Tile(Page.Services, "Services", "Start, stop, restart", Icons.Filled.SettingsSuggest),
    Tile(Page.More, "More", "Clipboard, power, settings", Icons.Filled.MoreHoriz),
)

private fun tileGradient(page: Page): Pair<Color, Color> = when (page) {
    Page.Screen -> Color(0xFF007AFF) to Color(0xFF0051C6)
    Page.Trackpad -> Color(0xFF48484A) to Color(0xFF2C2C2E)
    Page.Media -> Color(0xFFFF2D55) to Color(0xFFD6183C)
    Page.Presenter -> Color(0xFF5856D6) to Color(0xFF3634A3)
    Page.Apps -> Color(0xFF0A84FF) to Color(0xFF0058D0)
    Page.Run -> Color(0xFF3A3A3C) to Color(0xFF1C1C1E)
    Page.Files -> Color(0xFF32ADE6) to Color(0xFF007AFF)
    Page.Camera -> Color(0xFF34C759) to Color(0xFF248A3D)
    Page.Tasks -> Color(0xFF5E5CE6) to Color(0xFF3B39B8)
    Page.Devices -> Color(0xFFFF9500) to Color(0xFFC97100)
    Page.Network -> Color(0xFF30B0C7) to Color(0xFF1E8294)
    Page.Desktop -> Color(0xFFAF52DE) to Color(0xFF7E35A3)
    Page.Controls -> Color(0xFF00C7BE) to Color(0xFF008E88)
    Page.Scan -> Color(0xFFFFCC00) to Color(0xFFD6A700)
    Page.Windows -> Color(0xFF636366) to Color(0xFF3A3A3C)
    Page.DisplaySound -> Color(0xFF64D2FF) to Color(0xFF0A84FF)
    Page.Bluetooth -> Color(0xFF007AFF) to Color(0xFF0040DD)
    Page.Services -> Color(0xFF8E8E93) to Color(0xFF48484A)
    Page.More -> Color(0xFFA28BFE) to Color(0xFF6C47FF)
    else -> Color(0xFF0A84FF) to Color(0xFF0051C6)
}

@Composable
fun HomeScreen(
    client: LinkClient, state: LinkState, onOpen: (Page) -> Unit,
    computers: List<Computer> = emptyList(), onAdd: () -> Unit = {}, onSwitch: (Computer) -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current.applicationContext
    var choosing by remember { mutableStateOf(false) }
    var woke by remember { mutableStateOf("") }

    suspend fun refresh() {
        state.connecting = state.status == null
        val status = client.connect()
        state.status = status
        state.connecting = false
        state.message = if (status == null) "Cannot reach ${client.computer.name}" else ""
        // Reached: what was kept for it while it could not be goes now.
        if (status != null && Outbox.waiting(context) > 0) Outbox.deliver(context, client)
    }

    // Keep the status fresh while this screen is showing.
    LaunchedEffect(client) {
        while (true) {
            refresh()
            delay(if (state.connected) 8000 else 4000)
        }
    }

    TopBar(client.computer.name) {
        // Which computer: the others this phone is paired with, and pairing another.
        Box {
            IconButton(
                onClick = { choosing = true },
                modifier = Modifier.size(36.dp).clip(CircleShape).background(Color(0x22FFFFFF)),
            ) { Icon(Icons.Filled.Computer, "Computers", modifier = Modifier.size(18.dp), tint = Color(0xFFF5F5F7)) }
            DropdownMenu(expanded = choosing, onDismissRequest = { choosing = false }) {
                computers.forEach { other ->
                    DropdownMenuItem(
                        text = {
                            Text(other.name, color = if (other.fingerprint == client.computer.fingerprint)
                                MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                        },
                        onClick = { choosing = false; if (other.fingerprint != client.computer.fingerprint) onSwitch(other) },
                    )
                }
                DropdownMenuItem(text = { Text("Pair another computer") }, onClick = { choosing = false; onAdd() })
            }
        }
    }
    Column(Modifier.padding(horizontal = 16.dp)) {
        Card(Modifier.fillMaxWidth()) {
            val status = state.status
            Column {
                if (status != null) {
                    val via = if (client.tunnelled) "Direct P2P" else "Local Wi-Fi"
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Row(
                            Modifier.clip(RoundedCornerShape(12.dp))
                                .background(Color(0x2230D158))
                                .border(0.5.dp, Color(0x4430D158), RoundedCornerShape(12.dp))
                                .padding(horizontal = 8.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFF30D158)))
                            Spacer(Modifier.width(6.dp))
                            Text("ONLINE · 60 FPS ULTRA", color = Color(0xFF30D158), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.weight(1f))
                        Text(via, color = Color(0xFF8E8E93), fontSize = 12.sp, fontWeight = FontWeight.Medium)
                    }
                    Spacer(Modifier.height(14.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        status.optJSONObject("battery")?.let { b ->
                            val pct = b.optInt("percent")
                            val charging = b.optBoolean("charging")
                            Row(
                                Modifier.clip(RoundedCornerShape(10.dp)).background(Color(0xFF2C2C2E)).padding(horizontal = 8.dp, vertical = 5.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(if (charging) Icons.Filled.BatteryChargingFull else Icons.Filled.BatteryStd, null, Modifier.size(15.dp),
                                    tint = if (charging) Color(0xFF30D158) else if (pct <= 20) Color(0xFFFF453A) else Color(0xFFF5F5F7))
                                Spacer(Modifier.width(4.dp))
                                Text("$pct%", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFF5F5F7))
                            }
                        }
                        status.optJSONObject("volume")?.let { v ->
                            if (!v.isNull("percent")) {
                                val muted = v.optBoolean("muted")
                                val vol = v.optInt("percent")
                                Row(
                                    Modifier.clip(RoundedCornerShape(10.dp)).background(Color(0xFF2C2C2E)).padding(horizontal = 8.dp, vertical = 5.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(if (muted) Icons.Filled.VolumeOff else Icons.Filled.VolumeUp, null, Modifier.size(15.dp), tint = Color(0xFFF5F5F7))
                                    Spacer(Modifier.width(4.dp))
                                    Text(if (muted) "Muted" else "$vol%", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFF5F5F7))
                                }
                            }
                        }
                        status.optString("project").takeIf { it.isNotBlank() }?.let { proj ->
                            Row(
                                Modifier.clip(RoundedCornerShape(10.dp)).background(Color(0xFF2C2C2E)).padding(horizontal = 8.dp, vertical = 5.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(Icons.Filled.Folder, null, Modifier.size(14.dp), tint = Color(0xFF0A84FF))
                                Spacer(Modifier.width(4.dp))
                                Text(proj, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFF5F5F7), maxLines = 1)
                            }
                        }
                    }
                } else if (state.connecting) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(18.dp), color = Color(0xFF0A84FF), strokeWidth = 2.dp)
                        Spacer(Modifier.width(10.dp))
                        Text("Connecting to ${client.computer.name}…", color = Color(0xFF8E8E93), fontSize = 13.sp)
                    }
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(Color(0xFFFF453A)))
                        Spacer(Modifier.width(8.dp))
                        Text("Not Connected", fontWeight = FontWeight.SemiBold, color = Color(0xFFFF453A))
                    }
                    Spacer(Modifier.height(6.dp))
                    Muted(client.awayProblem.ifBlank {
                        "Computer must be awake with Adaptive Link active. Away from local Wi-Fi, both devices must be signed in to the same Google account."
                    })
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { scope.launch { refresh() } }) { Text("Retry") }
                        if (client.canWake) OutlinedButton(onClick = {
                            scope.launch {
                                woke = if (client.wake() > 0) "Wake-on-LAN broadcast sent." else "Could not broadcast wake request."
                                refresh()
                            }
                        }) { Text("Wake Computer") }
                    }
                    if (woke.isNotEmpty()) { Spacer(Modifier.height(6.dp)); Muted(woke) }
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        // One way in to everything below, and more: ask for it.
        AskBox(client, enabled = state.connected)
        if (state.connected) FrontCard(client)
        Spacer(Modifier.height(10.dp))
        LazyVerticalGrid(
            columns = GridCells.Fixed(3),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(bottom = 20.dp),
        ) {
            items(TILES) { tile ->
                val enabled = state.connected || tile.page == Page.More
                val (g1, g2) = tileGradient(tile.page)
                Column(
                    Modifier.aspectRatio(0.92f)
                        .clip(RoundedCornerShape(20.dp))
                        .background(Color(0xFF1C1C1E))
                        .border(0.5.dp, Color(0x1FFFFFFF), RoundedCornerShape(20.dp))
                        .clickable(enabled = enabled) { onOpen(tile.page) }
                        .padding(12.dp),
                    verticalArrangement = Arrangement.SpaceBetween,
                ) {
                    Box(
                        Modifier.size(38.dp).clip(RoundedCornerShape(10.dp))
                            .background(Brush.linearGradient(listOf(g1, g2))),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(tile.icon, null, Modifier.size(22.dp), tint = Color.White)
                    }
                    Column {
                        Text(tile.label, fontWeight = FontWeight.SemiBold, fontSize = 13.sp,
                            color = if (enabled) Color(0xFFF5F5F7) else Color(0xFF8E8E93))
                        Text(tile.detail, color = Color(0xFF8E8E93), fontSize = 10.5.sp, lineHeight = 12.sp, maxLines = 2)
                    }
                }
            }
        }
    }
}
