package com.karthi.adaptivelink

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.IntentCompat
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * "Share" from any other app, to the computer: a web address is opened in
 * its browser, text goes to its clipboard or its notes, files go to
 * ~/Downloads/Phone. It uses the same link as the rest of the app and does
 * nothing the app's own screens cannot; what was shared is shown first and
 * nothing is sent until one of the buttons is pressed.
 */
class ShareActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
        val files: List<Uri> = when (intent.action) {
            Intent.ACTION_SEND_MULTIPLE ->
                IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
            else -> listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
        }
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Color(0xFF0A84FF), onPrimary = Color.White, background = Color(0xFF1C1C1E),
                onBackground = Color(0xFFF5F5F7), surface = Color(0xFF2C2C2E), onSurface = Color(0xFFF5F5F7),
                onSurfaceVariant = Color(0xFF98989D), error = Color(0xFFFF453A),
            )) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    Share(text, files)
                }
            }
        }
    }

    @Composable
    private fun Share(text: String, files: List<Uri>) {
        val scope = rememberCoroutineScope()
        val client = remember { Link.client(this) }
        var said by remember { mutableStateOf("") }
        var busy by remember { mutableStateOf(false) }
        var done by remember { mutableStateOf(false) }
        val address = remember(text) { Protocol.sharedAddress(text) }

        /**
         * Reach the computer, do one thing, and say how it went. If it
         * cannot be reached, `later` keeps the thing to be sent when it can.
         */
        fun send(doing: String, finished: String, later: (() -> Boolean)? = null, work: suspend (LinkClient) -> String?) {
            val link = client ?: return
            busy = true
            said = doing
            scope.launch {
                val reached = link.connect() != null
                val problem = when {
                    reached -> work(link)
                    later != null && later() -> null.also {
                        said = "${link.computer.name} cannot be reached just now. Kept: it will go when it can (${Outbox.waiting(this@ShareActivity)} waiting)."
                        done = true
                        busy = false
                        return@launch
                    }
                    else -> "Cannot reach ${link.computer.name}."
                }
                said = problem ?: finished
                done = problem == null
                busy = false
            }
        }

        fun later(path: String, body: JSONObject): () -> Boolean = { Outbox.keep(this@ShareActivity, path, body) }

        fun answer(reply: JSONObject?): String? = when {
            reply == null -> "The computer did not answer."
            reply.optBoolean("ok") -> null
            else -> reply.optString("error").ifBlank { reply.optString("text") }.ifBlank { "It did not work." }
        }

        Column(Modifier.fillMaxSize().systemBarsPadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Send to ${client?.computer?.name ?: "computer"}", fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.titleLarge)
            if (client == null) {
                Muted("This phone is not paired with a computer yet. Open Adaptive Link to pair it.")
            } else {
                if (files.isNotEmpty()) {
                    Card(Modifier.fillMaxWidth()) {
                        Column {
                            files.take(6).forEach { Text(displayName(this@ShareActivity, it), maxLines = 1, overflow = TextOverflow.Ellipsis) }
                            if (files.size > 6) Muted("and ${files.size - 6} more")
                        }
                    }
                    Button(enabled = !busy && !done, modifier = Modifier.fillMaxWidth(), onClick = {
                        send("Sending…", if (files.size == 1) "It is in Downloads/Phone on the computer." else "They are in Downloads/Phone on the computer.",
                            later = { files.all { Outbox.keepFile(this@ShareActivity, displayName(this@ShareActivity, it), it) } }) { link ->
                            var problem: String? = null
                            for ((index, uri) in files.withIndex()) {
                                said = "Sending ${index + 1} of ${files.size}…"
                                val reply = link.upload(displayName(this@ShareActivity, uri), UriBody(this@ShareActivity, uri))
                                problem = answer(reply) ?: continue
                                break
                            }
                            problem
                        }
                    }) { Text(if (files.size == 1) "Send the file" else "Send ${files.size} files") }
                }
                if (text.isNotBlank()) {
                    Card(Modifier.fillMaxWidth()) { Text(text, maxLines = 8, overflow = TextOverflow.Ellipsis) }
                    if (address != null) {
                        Button(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                            send("Opening…", "Opened on the computer.", later("/v1/open-url", JSONObject().put("url", address))) {
                                answer(it.post("/v1/open-url", JSONObject().put("url", address)))
                            }
                        }) { Text("Open on the computer") }
                    }
                    OutlinedButton(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                        send("Copying…", "It is on the computer's clipboard.", later("/v1/clipboard", JSONObject().put("text", address ?: text))) {
                            answer(it.post("/v1/clipboard", JSONObject().put("text", address ?: text)))
                        }
                    }) { Text("Copy to its clipboard") }
                    OutlinedButton(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                        send("Noting…", "Added to the project's inbox.",
                            later("/v1/desktop", JSONObject().put("action", "note").put("value", text))) {
                            answer(it.post("/v1/desktop", JSONObject().put("action", "note").put("value", text)))
                        }
                    }) { Text("Add to the project's notes") }
                }
                if (files.isEmpty() && text.isBlank()) Muted("There is nothing here that can be sent.")
            }
            if (said.isNotEmpty()) Text(said, color = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.height(6.dp))
            OutlinedButton(onClick = { finish() }, modifier = Modifier.fillMaxWidth()) { Text(if (done) "Done" else "Cancel") }
        }
    }
}
