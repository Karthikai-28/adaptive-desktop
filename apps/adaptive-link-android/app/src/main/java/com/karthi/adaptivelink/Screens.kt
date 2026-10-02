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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Bluetooth
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
        Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
        } else {
            Spacer(Modifier.width(16.dp))
        }
        Text(title, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        trailing()
    }
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) {
    Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp, modifier = modifier)
}

@Composable
fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(
        modifier.clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surface).padding(16.dp)
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
    Tile(Page.Run, "Run", "Commands and apps", Icons.Filled.Terminal),
    Tile(Page.Files, "Files", "Browse, open, send", Icons.Filled.Folder),
    Tile(Page.Camera, "Webcam", "This phone's camera", Icons.Filled.Videocam),
    Tile(Page.Tasks, "Tasks", "Processes and load", Icons.Filled.Memory),
    Tile(Page.Devices, "Devices", "USB and drives", Icons.Filled.Usb),
    Tile(Page.Network, "Network", "Connections and traffic", Icons.Filled.Wifi),
    Tile(Page.Desktop, "Desktop", "Projects, focus, windows", Icons.Filled.Dashboard),
    Tile(Page.Windows, "Windows", "Switch, move, close", Icons.Filled.Window),
    Tile(Page.DisplaySound, "Display", "Screens and sound", Icons.Filled.Tune),
    Tile(Page.Bluetooth, "Bluetooth", "Devices nearby", Icons.Filled.Bluetooth),
    Tile(Page.Services, "Services", "Start, stop, restart", Icons.Filled.SettingsSuggest),
    Tile(Page.More, "More", "Clipboard, power, settings", Icons.Filled.MoreHoriz),
)

@Composable
fun HomeScreen(client: LinkClient, state: LinkState, onOpen: (Page) -> Unit) {
    val scope = rememberCoroutineScope()
    var woke by remember { mutableStateOf("") }

    suspend fun refresh() {
        state.connecting = state.status == null
        val status = client.connect()
        state.status = status
        state.connecting = false
        state.message = if (status == null) "Cannot reach ${client.computer.name}" else ""
    }

    // Keep the status fresh while this screen is showing.
    LaunchedEffect(client) {
        while (true) {
            refresh()
            delay(if (state.connected) 8000 else 4000)
        }
    }

    TopBar(client.computer.name)
    Column(Modifier.padding(horizontal = 16.dp)) {
        Card(Modifier.fillMaxWidth()) {
            val status = state.status
            Column {
                when {
                    status != null -> {
                        val via = if (client.tunnelled) "Direct, away" else "Local network"
                        Text("Connected · $via", fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.height(6.dp))
                        val parts = mutableListOf<String>()
                        status.optJSONObject("battery")?.let {
                            parts += "Battery ${it.optInt("percent")}%" + if (it.optBoolean("charging")) " charging" else ""
                        }
                        status.optJSONObject("volume")?.let { volume ->
                            if (!volume.isNull("percent"))
                                parts += if (volume.optBoolean("muted")) "Muted" else "Volume ${volume.optInt("percent")}%"
                        }
                        if (status.optBoolean("locked")) parts += "Locked"
                        status.optString("project").takeIf { it.isNotBlank() }?.let { parts += "Project $it" }
                        Muted(parts.joinToString("  ·  ").ifBlank { "Ready" })
                    }
                    state.connecting -> Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(10.dp))
                        Muted("Connecting…")
                    }
                    else -> {
                        Text("Not connected", fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.error)
                        Spacer(Modifier.height(6.dp))
                        Muted(client.awayProblem.ifBlank {
                            "The computer must be on with Adaptive Link started. Away from its network, this phone and the computer both need to be signed in to the same Google account."
                        })
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { scope.launch { refresh() } }) { Text("Try again") }
                            // Asleep, on this phone's own network: its network card can be asked to start it.
                            if (client.canWake) OutlinedButton(onClick = {
                                scope.launch {
                                    woke = if (client.wake() > 0) "Asked it to wake. That takes up to a minute, and only works on its own network, if it was set to (link-cli.py wake on)."
                                    else "This phone could not send the wake request on this network."
                                    refresh()
                                }
                            }) { Text("Wake it") }
                        }
                        if (woke.isNotEmpty()) { Spacer(Modifier.height(6.dp)); Muted(woke) }
                    }
                }
            }
        }
        Spacer(Modifier.height(14.dp))
        LazyVerticalGrid(
            columns = GridCells.Fixed(3),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(bottom = 16.dp),
        ) {
            items(TILES) { tile ->
                // More is always reachable: unpairing must work offline.
                val enabled = state.connected || tile.page == Page.More
                Column(
                    Modifier.aspectRatio(0.95f).clip(RoundedCornerShape(16.dp))
                        .background(MaterialTheme.colorScheme.surface)
                        .clickable(enabled = enabled) { onOpen(tile.page) }
                        .padding(14.dp),
                    verticalArrangement = Arrangement.SpaceBetween,
                ) {
                    Icon(
                        tile.icon, null, Modifier.size(30.dp),
                        tint = if (enabled) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Column {
                        Text(tile.label, fontWeight = FontWeight.SemiBold,
                            color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(tile.detail, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 11.sp, lineHeight = 13.sp, maxLines = 2)
                    }
                }
            }
        }
    }
}
