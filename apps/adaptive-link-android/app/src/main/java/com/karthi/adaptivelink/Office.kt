package com.karthi.adaptivelink

import android.content.Context
import android.content.Intent
import android.media.MediaPlayer
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelChildren
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder

/**
 * The Agent Office on the computer (services/agent-office), through the link.
 *
 * The office itself listens on the computer's 127.0.0.1 only; the daemon carries it to a paired
 * phone as /v1/office/api/... and /v1/office/ws, inside the same mutual TLS as the rest of the
 * link, so this works at home and away. The state here is the office's own snapshot, kept current
 * by its live updates, exactly as the desktop page keeps it.
 */
class Office(private val client: LinkClient) {
    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var connected by mutableStateOf(false)
        private set
    var problem by mutableStateOf("")
        private set
    var company by mutableStateOf("Office")
        private set
    var roster by mutableStateOf<List<JSONObject>>(emptyList())
        private set
    val agents = mutableStateMapOf<String, JSONObject>()
    val tasks = mutableStateMapOf<Int, JSONObject>()
    val missions = mutableStateMapOf<Int, JSONObject>()
    var meeting by mutableStateOf<JSONObject?>(null)
        private set
    var settings by mutableStateOf(JSONObject())
        private set
    var quotaUntil by mutableDoubleStateOf(0.0)
        private set
    var usage by mutableStateOf<List<JSONObject>>(emptyList())
        private set
    var studies by mutableStateOf<List<JSONObject>>(emptyList())
        private set
    /** Conversations that a screen has opened, kept current as messages arrive. */
    val threads = mutableStateMapOf<String, List<JSONObject>>()
    /** Recent activity per agent, for the agents whose page is open. */
    val events = mutableStateMapOf<String, List<JSONObject>>()

    /** Short notices from the office ("Meeting ended", "Quota is back"). */
    val notices = MutableSharedFlow<String>(extraBufferCapacity = 16)
    /** Every message as it arrives, for whoever reads replies aloud. */
    val incoming = MutableSharedFlow<JSONObject>(extraBufferCapacity = 64)

    @Volatile private var socket: WebSocket? = null
    @Volatile private var running = false
    private var keepAlive: Job? = null

    val managerId get() = roster.firstOrNull { it.str("kind") == "claude" }?.str("id") ?: "claude"
    fun person(id: String) = roster.firstOrNull { it.str("id") == id }
    fun name(id: String) = when (id) {
        "operator" -> "You"
        "system" -> "Office"
        else -> person(id)?.str("name")?.ifBlank { null } ?: id
    }
    fun threadOf(id: String) = if (id == managerId) "manager" else "dm:$id"
    val team get() = roster.filter { it.str("kind") != "claude" }

    // ---------------------------------------------------------------- live updates
    fun start() {
        if (running) return
        running = true
        scope.launch { open() }
        keepAlive = scope.launch {
            while (isActive) {
                delay(25_000)
                socket?.send("ping")
            }
        }
    }

    fun stop() {
        running = false
        keepAlive?.cancel()
        socket?.close(1000, null)
        socket = null
        scope.coroutineContext.cancelChildren()
    }

    private suspend fun open() {
        if (!running || socket != null) return
        if (client.host == null && withContext(Dispatchers.IO) { client.connect() } == null) {
            problem = "Can't reach your computer right now."
            retry()
            return
        }
        socket = client.socket("/v1/office/ws", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = main.post {
                connected = true
                problem = ""
            }.let { }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val m = runCatching { JSONObject(text) }.getOrNull() ?: return
                main.post { handle(m) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                val why = when (response?.code) {
                    403 -> "This phone isn't allowed to run commands on the computer, which the office needs."
                    503 -> "The office isn't running on the computer."
                    else -> "Reconnecting to the office…"
                }
                lost(webSocket, why)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = lost(webSocket, "Reconnecting to the office…")
        })
    }

    private fun lost(which: WebSocket, why: String) = main.post {
        if (socket !== which) return@post
        socket = null
        connected = false
        problem = why
        retry()
    }.let { }

    private fun retry() {
        if (!running) return
        scope.launch {
            delay(3000)
            open()
        }
    }

    private fun handle(m: JSONObject) {
        when (m.str("type")) {
            "state" -> {
                company = m.str("company", "Office")
                roster = m.optJSONArray("roster").objects()
                agents.clear()
                m.optJSONArray("agents").objects().forEach { agents[it.str("id")] = it }
                tasks.clear()
                m.optJSONArray("tasks").objects().forEach { tasks[it.optInt("id")] = it }
                missions.clear()
                m.optJSONArray("missions").objects().forEach { missions[it.optInt("id")] = it }
                meeting = m.optJSONObject("meeting")
                settings = m.optJSONObject("settings") ?: JSONObject()
                quotaUntil = m.optDouble("quota_until", 0.0).let { if (it.isNaN()) 0.0 else it }
                studies = m.optJSONArray("studies").objects()
                // Whatever is open is read again: messages may have arrived while away.
                threads.keys.toList().forEach { scope.launch { loadThread(it) } }
            }
            "agent" -> m.optJSONObject("agent")?.let { agents[it.str("id")] = it }
            "event" -> m.optJSONObject("event")?.let { e ->
                val who = e.str("agent")
                events[who]?.let { events[who] = (it + e).takeLast(60) }
            }
            "message" -> m.optJSONObject("message")?.let { msg ->
                val thread = msg.str("thread")
                threads[thread]?.let { list ->
                    if (list.none { it.optInt("id") == msg.optInt("id") }) threads[thread] = list + msg
                }
                incoming.tryEmit(msg)
            }
            "task" -> m.optJSONObject("task")?.let { tasks[it.optInt("id")] = it }
            "mission" -> m.optJSONObject("mission")?.let { missions[it.optInt("id")] = it }
            "meeting" -> {
                meeting = m.optJSONObject("meeting")
                m.optJSONObject("ended")?.str("minutes_path")?.takeIf { it.isNotBlank() }?.let {
                    notices.tryEmit("Meeting ended. Notes saved to $it")
                }
            }
            "toast" -> m.str("text").takeIf { it.isNotBlank() }?.let { notices.tryEmit(it) }
            "settings" -> {
                settings = m.optJSONObject("settings") ?: settings
                quotaUntil = m.optDouble("quota_until", 0.0).let { if (it.isNaN()) 0.0 else it }
            }
            "usage" -> usage = m.optJSONArray("rows").objects()
            "study" -> studies = m.optJSONArray("studies").objects()
        }
    }

    // ---------------------------------------------------------------- requests
    private fun api(path: String) = "/v1/office/api/$path"

    suspend fun text(path: String): String? = withContext(Dispatchers.IO) {
        client.open(api(path))?.use { if (it.isSuccessful) it.body?.string() else null }
    }

    suspend fun bytes(path: String): ByteArray? = withContext(Dispatchers.IO) {
        client.open(api(path))?.use { if (it.isSuccessful) it.body?.bytes() else null }
    }

    suspend fun obj(path: String): JSONObject? = text(path)?.let { runCatching { JSONObject(it) }.getOrNull() }
    suspend fun array(path: String): List<JSONObject> = text(path)?.let { runCatching { JSONArray(it) }.getOrNull() }.objects()

    /** A change: null when it worked, else what went wrong (also said as a notice). */
    suspend fun act(path: String, body: JSONObject = JSONObject()): String? {
        val reply = client.post(api(path), body)
        val error = when {
            reply == null -> "The computer didn't answer."
            // The office's own refusals carry "detail"; the link's carry ok=false, or "HTTP <code>".
            // A task's record has an "error" field of its own, which is not a failed request.
            reply.has("detail") -> reply.opt("detail").let { d -> if (d is JSONArray) "Check what you entered." else d.toString() }
            reply.has("ok") && !reply.optBoolean("ok") -> reply.str("error").ifBlank { "That didn't work." }
            reply.str("error").startsWith("HTTP ") && !reply.has("id") -> reply.str("error")
            else -> null
        }
        if (error != null) notices.tryEmit(error)
        return error
    }

    suspend fun loadThread(thread: String) {
        val list = text("messages?thread=${enc(thread)}&limit=200")?.let { runCatching { JSONArray(it) }.getOrNull() } ?: return
        threads[thread] = list.objects()
    }

    suspend fun loadEvents(agent: String) {
        events[agent] = array("events?agent=${enc(agent)}&limit=60").sortedBy { it.optInt("id") }
    }

    suspend fun send(to: String, text: String) = act("chat", JSONObject().put("to", to).put("text", text))
    suspend fun say(text: String) = act("meeting/say", JSONObject().put("text", text))

    /** The speech for one line, in that person's own voice: an mp3 in the app's cache. */
    suspend fun speech(context: Context, who: String, text: String): File? {
        val data = bytes("tts?who=${enc(who)}&text=${enc(text)}") ?: return null
        return withContext(Dispatchers.IO) {
            File(context.cacheDir, "office-voice-${(who + text).hashCode()}.mp3").apply { writeBytes(data) }
        }
    }

    companion object {
        fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")
    }
}

/** A field's text, with JSON null (and a missing field) as "" rather than org.json's "null". */
internal fun JSONObject.str(key: String, default: String = ""): String = if (!has(key) || isNull(key)) default else optString(key)

/** Replies read aloud one after another, each in its speaker's voice, as on the desktop. */
class OfficeVoice(private val context: Context, private val office: Office) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val queue = ArrayDeque<Pair<String, String>>()
    private var player: MediaPlayer? = null
    var speaking by mutableStateOf(false)
        private set

    fun speak(who: String, text: String) {
        val line = spoken(text)
        if (line.isBlank()) return
        queue.addLast(who to line)
        if (!speaking) next()
    }

    private fun next() {
        val (who, line) = queue.removeFirstOrNull() ?: run { speaking = false; return }
        speaking = true
        scope.launch {
            val file = office.speech(context, who, line)
            if (file == null) { next(); return@launch }
            runCatching {
                player = MediaPlayer().apply {
                    setDataSource(file.path)
                    setOnCompletionListener { it.release(); if (player === it) player = null; next() }
                    setOnErrorListener { mp, _, _ -> mp.release(); if (player === mp) player = null; next(); true }
                    prepare()
                    start()
                }
            }.onFailure { next() }
        }
    }

    fun stop() {
        queue.clear()
        player?.runCatching { stop(); release() }
        player = null
        speaking = false
    }

    fun close() {
        stop()
        scope.coroutineContext.cancelChildren()
    }

    companion object {
        /** What is worth saying: no markdown, no code, not a whole report. */
        fun spoken(text: String): String {
            val plain = text.replace(Regex("```[\\s\\S]*?```"), " ")
                .replace(Regex("`([^`]*)`"), "$1")
                .replace(Regex("[*_#>|]+"), "")
                .replace(Regex("\\[([^]]*)]\\([^)]*\\)"), "$1")
                .replace(Regex("\\s+"), " ").trim()
            if (plain.length <= 600) return plain
            val cut = plain.take(600)
            return cut.substring(0, cut.lastIndexOf('.').takeIf { it > 200 }?.plus(1) ?: cut.length)
        }
    }
}

/** Speech to text on the phone, without a dialog: Android's own recognizer. */
class OfficeEars(private val context: Context) {
    private var recognizer: SpeechRecognizer? = null
    var listening by mutableStateOf(false)
        private set
    var partial by mutableStateOf("")
        private set

    val available get() = SpeechRecognizer.isRecognitionAvailable(context)

    /** Listen for one utterance; `done` gets the words, or "" when nothing was understood. */
    fun listen(done: (String) -> Unit) {
        recognizer?.destroy()
        partial = ""
        val r = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
            override fun onPartialResults(partialResults: Bundle?) {
                partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { partial = it }
            }
            override fun onResults(results: Bundle?) {
                listening = false
                val words = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                partial = ""
                done(words)
            }
            override fun onError(error: Int) {
                listening = false
                partial = ""
                done("")
            }
        })
        listening = true
        r.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true))
    }

    fun stop() {
        recognizer?.stopListening()
    }

    fun close() {
        recognizer?.destroy()
        recognizer = null
        listening = false
    }
}
