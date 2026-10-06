package com.karthi.adaptivelink

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * One way in to everything the computer can do: ask for it in ordinary
 * words, typed or spoken. The computer says what that could mean (the
 * matching is its own, services/adaptive-link/actions.py) and each answer is
 * a sentence saying exactly what will happen. What changes nothing is done
 * at once; anything else is shown first.
 */
@Composable
fun AskBox(client: LinkClient, enabled: Boolean) {
    val scope = rememberCoroutineScope()
    var asked by remember { mutableStateOf("") }
    var matches by remember { mutableStateOf(listOf<JSONObject>()) }
    var said by remember { mutableStateOf("") }
    var canUndo by remember { mutableStateOf(false) }
    var confirming by remember { mutableStateOf<JSONObject?>(null) }
    var naming by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var done by remember { mutableStateOf(0) }

    // Asked as it is typed, a moment after the typing stops.
    LaunchedEffect(asked) {
        if (asked.isBlank()) { matches = emptyList(); return@LaunchedEffect }
        delay(350)
        val reply = client.post("/v1/ask", JSONObject().put("text", asked))
        matches = reply?.optJSONArray("matches").objects()
        canUndo = reply?.optBoolean("undo") == true
    }

    fun perform(match: JSONObject) {
        scope.launch {
            said = "…"
            // Anything but a safe one was put to the owner first (choose), and the computer
            // will not do what cannot be undone without hearing that it was.
            val reply = client.post("/v1/do", JSONObject().put("id", match.optString("id")).put("args", match.optJSONObject("args") ?: JSONObject())
                .put("confirm", match.optString("risk") != "safe"))
            // A change that could cut the phone off: say it can still be reached, or the computer puts it back.
            val kept = if (reply == null || reply.optInt("keep") > 0) keep(client, reply) else null
            said = kept ?: when {
                reply == null -> "The computer did not answer."
                reply.optBoolean("ok") -> reply.optString("text").ifBlank { match.optString("say") }
                else -> reply.optString("error").ifBlank { "It did not work" }
            }
            if (reply?.optBoolean("ok") == true) { done++; canUndo = true; asked = "" }
        }
    }

    fun choose(match: JSONObject) {
        if (match.optString("risk") == "safe") perform(match) else confirming = match
    }

    Column {
        OutlinedTextField(
            value = asked, onValueChange = { asked = it }, enabled = enabled, singleLine = true,
            placeholder = { Text("Ask the computer: “turn off bluetooth”") },
            // Said instead of typed: what is heard is asked.
            trailingIcon = { Dictate { asked = it } },
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
            keyboardActions = KeyboardActions(onGo = { matches.firstOrNull()?.takeIf { it.optBoolean("sure") }?.let { choose(it) } }),
        )
        if (matches.isNotEmpty()) Card(Modifier.fillMaxWidth().padding(top = 6.dp)) {
            Column {
                matches.take(4).forEach { match ->
                    Row(Modifier.fillMaxWidth().clickable { choose(match) }.padding(vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(match.optString("say"), Modifier.weight(1f),
                            fontWeight = if (match.optBoolean("sure")) FontWeight.SemiBold else FontWeight.Normal)
                        when (match.optString("risk")) {
                            "cuts" -> Muted("may disconnect")
                            "destroys" -> Text("cannot be undone", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        } else if (asked.isNotBlank()) Muted("Nothing the computer knows how to do matches that yet.", Modifier.padding(top = 6.dp))
        if (said.isNotEmpty() || canUndo) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Muted(said, Modifier.weight(1f))
            if (canUndo) TextButton(onClick = { perform(JSONObject().put("id", "undo").put("say", "Undone")) }) { Text("Undo") }
            // Two or more things done in a row can be kept as one, under a name to ask for.
            if (done >= 2) TextButton(onClick = { name = ""; naming = true }) { Text("Keep as one") }
        }
    }

    confirming?.let { match ->
        AlertDialog(
            onDismissRequest = { confirming = null },
            title = { Text(match.optString("say")) },
            text = {
                Text(when (match.optString("risk")) {
                    "cuts" -> "This may disconnect the phone from the computer. If the phone cannot reach it afterwards, the computer puts it back within a minute."
                    "destroys" -> "This cannot be undone."
                    else -> "This changes something on the computer. Undo puts it back."
                })
            },
            confirmButton = { TextButton(onClick = { confirming = null; perform(match) }) { Text("Do it") } },
            dismissButton = { TextButton(onClick = { confirming = null }) { Text("Cancel") } },
        )
    }

    if (naming) AlertDialog(
        onDismissRequest = { naming = false },
        title = { Text("Keep the last $done as one") },
        text = {
            Column {
                Muted("Ask for it by this name and each is done in turn.")
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = name, onValueChange = { name = it.take(60) }, singleLine = true,
                    placeholder = { Text("start the meeting") }, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            TextButton(enabled = name.isNotBlank(), onClick = {
                naming = false
                scope.launch {
                    val reply = client.post("/v1/chains", JSONObject().put("name", name.trim()).put("count", done.coerceAtMost(10)))
                    said = if (reply?.optBoolean("ok") == true) "Kept. Ask for “${name.trim()}”." else "It could not be kept."
                    done = 0
                }
            }) { Text("Keep") }
        },
        dismissButton = { TextButton(onClick = { naming = false }) { Text("Cancel") } },
    )
}

/** What is in front on the computer, to carry on with here. */
@Composable
fun FrontCard(client: LinkClient) {
    var front by remember { mutableStateOf<JSONObject?>(null) }
    val context = LocalContext.current
    LaunchedEffect(client) {
        while (true) {
            front = client.get("/v1/front")
            delay(6000)
        }
    }
    val playing = front?.optJSONObject("playing")
    val window = front?.optJSONObject("window")
    val address = playing?.let { Protocol.handoffAddress(it.optString("url"), it.optInt("position")) }
    if (window == null && playing == null) return
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Muted("On the computer now: " + (playing?.optString("title")?.ifBlank { null } ?: window?.optString("title")?.ifBlank { null }
            ?: window?.optString("app").orEmpty()).take(70), Modifier.weight(1f))
        if (address != null) TextButton(onClick = {
            (context as? MainActivity)?.awayOnPurpose = true
            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(address))) }
        }) { Text("Carry on here") }
    }
}

/** How the link is, as the computer sees it: only what is wrong is shown, each with what puts it right. */
@Composable
fun DoctorNotes(client: LinkClient) {
    var wrong by remember { mutableStateOf<List<JSONObject>?>(null) }
    LaunchedEffect(client) { wrong = client.get("/v1/doctor")?.optJSONArray("checks").objects().filter { !it.optBoolean("ok") } }
    val found = wrong ?: return
    if (found.isEmpty()) Muted("Everything the link depends on is in place.")
    found.forEach { item ->
        Text("${item.optString("name")}: ${item.optString("text")}")
        Muted("On the computer: ${item.optString("fix")}", Modifier.padding(bottom = 6.dp))
    }
}

// ------------------------------------------------------------------- offers

/**
 * Something the computer offers to do - a scene come round again, a backup
 * for the drive just plugged in - shown as a notification with one button.
 */
object Offers {
    const val ACTION = "com.karthi.adaptivelink.OFFER"

    fun show(context: Context, event: JSONObject) {
        val what = event.optJSONObject("do") ?: return
        EventsService.channels(context)
        if (!EventsService.mayNotify(context)) return
        val id = 7000 + (event.optLong("id") % 1000).toInt()
        val yes = PendingIntent.getBroadcast(context, id, Intent(context, OfferReceiver::class.java).setAction(ACTION)
            .putExtra("do", what.toString()).putExtra("notification", id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(id,
            NotificationCompat.Builder(context, EventsService.CHANNEL_ALERTS)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(event.optString("title"))
                .setContentText(event.optString("text"))
                .setSubText(Store(context).computer?.name)
                .addAction(0, "Do it", yes)
                .setAutoCancel(true).setTimeoutAfter(10 * 60_000L).build())
    }
}

class OfferReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val what = runCatching { JSONObject(intent.getStringExtra("do").orEmpty()) }.getOrNull() ?: return
        val app = context.applicationContext
        app.getSystemService(NotificationManager::class.java).cancel(intent.getIntExtra("notification", 0))
        val client = Link.client(app) ?: return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            val said = runCatching {
                if (client.host == null && client.connect() == null) "Cannot reach ${client.computer.name}"
                else client.post("/v1/do", what)?.let { it.optString("text").ifBlank { it.optString("error") }.ifBlank { "Done" } }
                    ?: "The computer did not answer"
            }.getOrDefault("It did not work")
            withContext(Dispatchers.Main) { Toast.makeText(app, said, Toast.LENGTH_SHORT).show() }
            pending.finish()
        }
    }
}

// ----------------------------------------------------------- pairing nearby

/**
 * Computers on this network that are waiting to be paired with. While its
 * pairing window is open a computer says so on its network, with what its
 * QR code holds; finding it here saves the scanning. It is still the six
 * digits, compared on both screens, that decide.
 */
@Composable
fun NearbyComputers(onChosen: (PairingOffer) -> Unit) {
    val context = LocalContext.current
    var found by remember { mutableStateOf(listOf<PairingOffer>()) }

    DisposableEffect(Unit) {
        val nsd = context.getSystemService(NsdManager::class.java)
        val listener = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(service: NsdServiceInfo) {
                @Suppress("DEPRECATION")
                runCatching {
                    nsd.resolveService(service, object : NsdManager.ResolveListener {
                        override fun onResolveFailed(info: NsdServiceInfo, error: Int) = Unit
                        override fun onServiceResolved(info: NsdServiceInfo) {
                            fun said(key: String) = info.attributes[key]?.let { String(it) }.orEmpty()
                            val host = info.host?.hostAddress ?: return
                            val offer = PairingOffer.parse(JSONObject().put("v", 1).put("n", said("n")).put("h", JSONArray(listOf(host)))
                                .put("p", said("p").toIntOrNull() ?: 0).put("pp", info.port).put("f", said("f")).put("t", said("t")).toString())
                                ?: return
                            found = (found.filter { it.computer.fingerprint != offer.computer.fingerprint } + offer)
                        }
                    })
                }
            }

            override fun onServiceLost(service: NsdServiceInfo) = Unit
            override fun onDiscoveryStarted(type: String) = Unit
            override fun onDiscoveryStopped(type: String) = Unit
            override fun onStartDiscoveryFailed(type: String, error: Int) = Unit
            override fun onStopDiscoveryFailed(type: String, error: Int) = Unit
        }
        runCatching { nsd.discoverServices("_adaptivelink._tcp", NsdManager.PROTOCOL_DNS_SD, listener) }
        onDispose { runCatching { nsd.stopServiceDiscovery(listener) } }
    }

    found.forEach { offer ->
        Card(Modifier.fillMaxWidth().padding(bottom = 8.dp).clickable { onChosen(offer) }) {
            Column {
                Text("${offer.computer.name} is nearby", fontWeight = FontWeight.SemiBold)
                Muted("It is waiting to be paired with. Tap, then compare the six digits on both screens.")
            }
        }
    }
}

// ------------------------------------------------------------------ outbox

/**
 * What was meant for the computer while it could not be reached: kept on
 * the phone, and sent when it can be. A link to open, text for its
 * clipboard or its notes, files for its Downloads. Nothing is lost for the
 * computer having been asleep or out of range, and nothing is sent twice.
 */
object Outbox {
    const val LIMIT = 20
    private val lock = Any()

    private fun folder(context: Context) = java.io.File(context.filesDir, "outbox").apply { mkdirs() }

    /** How many things are waiting to go. */
    fun waiting(context: Context): Int = Protocol.outboxFromJson(Store(context).outbox).size

    /** Keep a request for later: where it goes on the link, and what it says. */
    fun keep(context: Context, path: String, body: JSONObject): Boolean = synchronized(lock) {
        val store = Store(context)
        val kept = Protocol.outboxFromJson(store.outbox)
        if (kept.size >= LIMIT) return false
        store.outbox = Protocol.outboxToJson(kept + JSONObject().put("path", path).put("body", body))
        true
    }

    /** Keep a file for later: copied into the app's own storage, since what another app lent is taken back. */
    fun keepFile(context: Context, name: String, uri: android.net.Uri): Boolean {
        val copy = java.io.File(folder(context), "${System.currentTimeMillis()}-${name.replace('/', '_').take(80)}")
        val copied = runCatching {
            context.contentResolver.openInputStream(uri)!!.use { from -> copy.outputStream().use { to -> from.copyTo(to) } }
        }.isSuccess
        if (!copied) { copy.delete(); return false }
        synchronized(lock) {
            val store = Store(context)
            val kept = Protocol.outboxFromJson(store.outbox)
            if (kept.size >= LIMIT) { copy.delete(); return false }
            store.outbox = Protocol.outboxToJson(kept + JSONObject().put("file", copy.absolutePath).put("name", name))
        }
        return true
    }

    /** Send what is waiting, oldest first, stopping at the first that does not go. Returns how many went. */
    suspend fun deliver(context: Context, client: LinkClient): Int {
        var sent = 0
        while (true) {
            val next = synchronized(lock) { Protocol.outboxFromJson(Store(context).outbox).firstOrNull() } ?: break
            val went = if (next.has("file")) {
                val file = java.io.File(next.optString("file"))
                !file.exists() || client.upload(next.optString("name"), okhttp3.RequestBody.create(null, file))?.optBoolean("ok") == true
            } else {
                // Any answer means it arrived; a refusal is the computer's answer, not a reason to send it again.
                client.post(next.optString("path"), next.optJSONObject("body") ?: JSONObject()) != null
            }
            if (!went) break
            if (next.has("file")) java.io.File(next.optString("file")).delete()
            synchronized(lock) {
                val store = Store(context)
                store.outbox = Protocol.outboxToJson(Protocol.outboxFromJson(store.outbox).drop(1))
            }
            sent++
        }
        return sent
    }
}

