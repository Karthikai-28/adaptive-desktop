package com.karthi.adaptivelink

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger
import java.security.MessageDigest

/**
 * What the phone and the computer agree on, with no Android in it, so the
 * unit tests check it on a plain JVM against the values the computer's own
 * code produces (services/adaptive-link/identity.py).
 */

/** The computer this phone is paired with. Nothing here is secret. */
data class Computer(
    val name: String,
    val hosts: List<String>,
    val port: Int,
    val pairingPort: Int,
    /** SHA-256 of the computer's certificate, lowercase hex: the pin. */
    val fingerprint: String,
    /** Where to send the packet that wakes it: "hardware address|broadcast address" each. */
    val wake: List<String> = emptyList(),
) {
    fun toJson(): String = JSONObject()
        .put("n", name).put("h", JSONArray(hosts)).put("p", port)
        .put("pp", pairingPort).put("f", fingerprint).put("w", JSONArray(wake)).toString()

    companion object {
        fun fromJson(text: String): Computer? = runCatching {
            val json = JSONObject(text)
            val hosts = json.getJSONArray("h").let { array -> List(array.length()) { array.getString(it) } }
            val fingerprint = json.getString("f").lowercase()
            val port = json.getInt("p")
            val pairingPort = json.optInt("pp", 0)
            require(hosts.isNotEmpty() && hosts.all { isAddress(it) })
            require(fingerprint.length == 64 && fingerprint.all { it in "0123456789abcdef" })
            require(port in 1024..65535 && (pairingPort == 0 || pairingPort in 1024..65535))
            val wake = json.optJSONArray("w").let { array ->
                if (array == null) emptyList() else List(array.length()) { array.optString(it) }
            }.filter { isWake(it) }.take(8)
            Computer(json.optString("n", "Computer").take(60), hosts, port, pairingPort, fingerprint, wake)
        }.getOrNull()

        /** "aa:bb:cc:dd:ee:ff|192.168.1.255": a hardware address and where its network listens. */
        fun isWake(entry: String): Boolean {
            val parts = entry.split('|')
            return parts.size == 2 && Regex("^([0-9a-f]{2}:){5}[0-9a-f]{2}$").matches(parts[0]) &&
                Regex("^(\\d{1,3}\\.){3}\\d{1,3}$").matches(parts[1])
        }

        /** An IPv4 or IPv6 literal or a plain host name: nothing with a path or a scheme in it. */
        fun isAddress(host: String): Boolean =
            host.length in 1..253 && host.all { it.isLetterOrDigit() || it in ".-:" }
    }
}

/** The computers a phone is paired with: kept as a list, with one of them the one being talked to. */
object Computers {
    const val LIMIT = 8

    fun toJson(computers: List<Computer>): String = JSONArray(computers.take(LIMIT).map { JSONObject(it.toJson()) }).toString()

    fun fromJson(text: String?): List<Computer>? = runCatching {
        val array = JSONArray(text ?: return null)
        List(array.length()) { array.getJSONObject(it).toString() }.mapNotNull { Computer.fromJson(it) }
            .distinctBy { it.fingerprint }.take(LIMIT)
    }.getOrNull()

    fun current(computers: List<Computer>, fingerprint: String?): Computer? =
        computers.firstOrNull { it.fingerprint == fingerprint } ?: computers.firstOrNull()

    /**
     * The list, and which is talked to, after `value` is stored while
     * `talkingTo` is the current one. A known computer is brought up to date
     * and nothing else changes; a new one is added and becomes current;
     * nothing (null) forgets the current one.
     */
    fun after(computers: List<Computer>, talkingTo: String?, value: Computer?): Pair<List<Computer>, String?> = when {
        value == null -> computers.filter { it.fingerprint != talkingTo }.let { it to it.firstOrNull()?.fingerprint }
        computers.any { it.fingerprint == value.fingerprint } ->
            computers.map { if (it.fingerprint == value.fingerprint) value else it } to talkingTo
        else -> (computers + value).takeLast(LIMIT) to value.fingerprint
    }
}

/** What a scanned pairing code holds: the computer, and the one-time token. */
data class PairingOffer(val computer: Computer, val token: String) {
    companion object {
        /** The same offer as text, for typing or pasting when it cannot be scanned. */
        const val TEXT_PREFIX = "ALINK1."

        /** Reads what the QR code holds, or the text form of it. */
        fun parse(scanned: String): PairingOffer? = runCatching {
            val trimmed = scanned.trim()
            val text = if (trimmed.startsWith(TEXT_PREFIX))
                String(java.util.Base64.getUrlDecoder().decode(trimmed.removePrefix(TEXT_PREFIX)))
            else trimmed
            val json = JSONObject(text)
            require(json.getInt("v") == 1)
            val token = json.getString("t")
            require(token.length in 20..200)
            PairingOffer(Computer.fromJson(text)!!, token)
        }.getOrNull()
    }
}

/** The owner's own relay, as the computer told this phone of it. */
data class Relay(val url: String, val username: String, val credential: String) {
    fun toJson(): String = JSONObject().put("url", url).put("username", username).put("credential", credential).toString()

    companion object {
        fun fromJson(text: String?): Relay? = runCatching {
            val json = JSONObject(text ?: return null)
            val url = json.getString("url")
            // A TURN server's address and nothing else: it is handed to the connection as it is.
            require(Regex("^turns?:[A-Za-z0-9.\\-:\\[\\]?=_]{1,190}$").matches(url))
            Relay(url, json.optString("username").take(200), json.optString("credential").take(200))
        }.getOrNull()
    }
}

/** A button the owner has put on their own page of controls. */
data class Control(val label: String, val kind: String, val value: String) {
    companion object {
        const val LIMIT = 40
        /** What a button can do: run a command, press keys, type text, or one of the one-tap actions. */
        val KINDS = listOf("command", "keys", "text", "action")

        fun listToJson(controls: List<Control>): String = JSONArray(controls.take(LIMIT).map {
            JSONObject().put("l", it.label).put("k", it.kind).put("v", it.value)
        }).toString()

        fun listFromJson(text: String): List<Control> = runCatching {
            val array = JSONArray(text)
            List(array.length()) { array.getJSONObject(it) }
                .map { Control(it.getString("l").trim().take(24), it.getString("k"), it.getString("v").take(8000)) }
                .filter { it.label.isNotBlank() && it.value.isNotBlank() && it.kind in KINDS }.take(LIMIT)
        }.getOrDefault(emptyList())
    }
}

/** A command the owner runs often, kept on the phone to be run with one tap. */
data class SavedCommand(val name: String, val command: String, val detach: Boolean) {
    companion object {
        const val LIMIT = 24

        fun listToJson(commands: List<SavedCommand>): String = JSONArray(commands.take(LIMIT).map {
            JSONObject().put("n", it.name).put("c", it.command).put("d", it.detach)
        }).toString()

        fun listFromJson(text: String): List<SavedCommand> = runCatching {
            val array = JSONArray(text)
            List(array.length()) { array.getJSONObject(it) }
                .map { SavedCommand(it.getString("n").trim().take(40), it.getString("c").take(8000), it.optBoolean("d")) }
                .filter { it.name.isNotBlank() && it.command.isNotBlank() }.take(LIMIT)
        }.getOrDefault(emptyList())
    }
}

object Protocol {
    fun fingerprint(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }

    /**
     * Six digits both screens show, from both certificates. If anything sat
     * between the phone and the computer while pairing, the two would hold
     * different certificates and so show different digits.
     */
    fun pairingCode(computerFingerprint: String, phoneFingerprint: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("$computerFingerprint|$phoneFingerprint".toByteArray())
        val number = BigInteger(1, digest.copyOfRange(0, 8)).mod(BigInteger.valueOf(1_000_000))
        return "%06d".format(number.toInt())
    }

    fun pem(der: ByteArray): String {
        val body = java.util.Base64.getMimeEncoder(64, "\n".toByteArray()).encodeToString(der)
        return "-----BEGIN CERTIFICATE-----\n$body\n-----END CERTIFICATE-----\n"
    }

    // Input events, as the computer's inputs.py reads them.
    fun move(x: Float, y: Float) = JSONObject().put("t", "move").put("x", x.toDouble()).put("y", y.toDouble()).toString()

    /** A stylus on the picture: where, how hard (0..1), and what it is doing - near, down, move, up or away. */
    fun pen(x: Float, y: Float, pressure: Float, stage: String, eraser: Boolean = false, button: Boolean = false) =
        JSONObject().put("t", "pen").put("x", x.toDouble()).put("y", y.toDouble())
            .put("p", pressure.coerceIn(0f, 1f).toDouble()).put("s", stage).put("e", eraser).put("b", button).toString()
    fun relative(dx: Float, dy: Float) = JSONObject().put("t", "rel").put("dx", dx.toDouble()).put("dy", dy.toDouble()).toString()
    fun click(button: Int = 1) = JSONObject().put("t", "click").put("b", button).toString()
    fun button(down: Boolean, button: Int = 1) = JSONObject().put("t", if (down) "down" else "up").put("b", button).toString()
    fun doubleClick() = JSONObject().put("t", "double").toString()
    fun scroll(dx: Int, dy: Int) = JSONObject().put("t", "scroll").put("dx", dx).put("dy", dy).toString()
    fun key(name: String, vararg modifiers: String) =
        JSONObject().put("t", "key").put("k", name).put("m", JSONArray(modifiers.toList())).toString()
    fun text(value: String) = JSONObject().put("t", "text").put("s", value).toString()
    /** A key held down, or let go: a game pad's buttons. */
    fun hold(name: String, down: Boolean) = JSONObject().put("t", if (down) "keydown" else "keyup").put("k", name).toString()

    /**
     * A key with its modifiers as the owner writes it - "ctrl+alt+t", "F5",
     * "super" - as the event that presses it, or null if it is not one.
     */
    fun keys(written: String): String? {
        // "ctrl+" names no key: something was left unfinished.
        if (written.trim().endsWith("+")) return null
        val parts = written.trim().split('+').map { it.trim() }.filter { it.isNotEmpty() }
        val name = parts.lastOrNull() ?: return null
        val modifiers = parts.dropLast(1).map { it.lowercase() }
        if (!Regex("^[A-Za-z0-9_]{1,40}$").matches(name) || modifiers.any { it !in listOf("ctrl", "shift", "alt", "super") }) return null
        val key = when (name.lowercase()) {
            "enter" -> "Return"; "esc" -> "Escape"; "space" -> "space"; "tab" -> "Tab"; "super" -> "Super_L"
            "ctrl" -> "Control_L"; "shift" -> "Shift_L"; "alt" -> "Alt_L"
            "del" -> "Delete"; "backspace" -> "BackSpace"; "up" -> "Up"; "down" -> "Down"; "left" -> "Left"; "right" -> "Right"
            else -> name
        }
        return key(key, *modifiers.toTypedArray())
    }

    /**
     * Which of four keys a stick pushed to (x, y) holds down, each from -1
     * to 1: none near the middle, two on a diagonal.
     */
    fun stickKeys(x: Float, y: Float, up: String, down: String, left: String, right: String, dead: Float = 0.35f): Set<String> =
        buildSet {
            if (y < -dead) add(up)
            if (y > dead) add(down)
            if (x < -dead) add(left)
            if (x > dead) add(right)
        }

    fun formatSize(bytes: Long): String = when {
        bytes >= 1L shl 30 -> "%.1f GB".format(bytes / (1L shl 30).toDouble())
        bytes >= 1L shl 20 -> "%.1f MB".format(bytes / (1L shl 20).toDouble())
        bytes >= 1L shl 10 -> "%d KB".format(bytes shr 10)
        else -> "$bytes B"
    }

    /** A speed from two readings of a byte count taken `seconds` apart. */
    fun formatRate(before: Long, after: Long, seconds: Double): String =
        if (seconds <= 0 || after < before) "0 B/s" else formatSize(((after - before) / seconds).toLong()) + "/s"

    /**
     * How large a page marked by four corners (top-left, top-right,
     * bottom-right, bottom-left, in pixels) comes out when pulled straight:
     * as wide as its wider edge and as tall as its taller one, and no
     * larger than `longest` on its longer side.
     */
    fun pageSize(corners: List<Pair<Float, Float>>, longest: Int): Pair<Int, Int> {
        fun between(a: Pair<Float, Float>, b: Pair<Float, Float>) =
            Math.hypot((a.first - b.first).toDouble(), (a.second - b.second).toDouble())
        val width = maxOf(between(corners[0], corners[1]), between(corners[3], corners[2]))
        val height = maxOf(between(corners[0], corners[3]), between(corners[1], corners[2]))
        val scale = minOf(1.0, longest / maxOf(width, height, 1.0))
        return maxOf(1, (width * scale).toInt()) to maxOf(1, (height * scale).toInt())
    }

    /**
     * Where to carry on with what the computer is playing: its address, at
     * the second it has reached where the site takes one (YouTube does).
     */
    fun handoffAddress(url: String, position: Int): String? {
        if (!Regex("^https?://[^\\s/]+\\S*$", RegexOption.IGNORE_CASE).matches(url)) return null
        val host = url.substringAfter("://").substringBefore('/').lowercase()
        if (position <= 0 || !(host.endsWith("youtube.com") || host.endsWith("youtu.be"))) return url
        val bare = url.replace(Regex("([?&])t=[^&#]*&?"), "$1").trimEnd('?', '&')
        return bare + (if ('?' in bare) "&" else "?") + "t=${position}s"
    }

    /** What is waiting to be sent to the computer, as it is stored. */
    fun outboxToJson(items: List<JSONObject>): String = JSONArray(items).toString()

    fun outboxFromJson(text: String): List<JSONObject> = runCatching {
        val array = JSONArray(text)
        List(array.length()) { array.optJSONObject(it) }.filterNotNull()
            .filter { (it.has("path") && it.optString("path").startsWith("/v1/")) || it.has("file") }
    }.getOrDefault(emptyList())

    /** What the phone signs to approve something on the computer: this request and no other. */
    fun approvalMessage(what: String, nonce: String): ByteArray = "adaptive-link approve\n$what\n$nonce".toByteArray()

    /**
     * The packet that wakes a sleeping computer: six bytes of 0xFF, then its
     * hardware address sixteen times. A network card left listening starts
     * the machine when it sees its own address in this form.
     */
    fun magicPacket(mac: String): ByteArray {
        val address = mac.split(':').map { it.toInt(16).toByte() }
        require(address.size == 6)
        return ByteArray(6) { 0xFF.toByte() } + ByteArray(96) { address[it % 6] }
    }

    /**
     * The web address in something shared, if that is what it is. Apps share
     * a page as its address alone or as "Title https://…": the address is
     * the last word.
     */
    fun sharedAddress(text: String): String? {
        val last = text.trim().split(Regex("\\s+")).lastOrNull() ?: return null
        return last.takeIf { Regex("^https?://[^\\s/]+\\S*$", RegexOption.IGNORE_CASE).matches(it) && it.length <= 2000 }
    }

    /** The computer's status in a line: battery, volume, project - what a glance wants. */
    fun statusLine(status: JSONObject): String {
        val parts = mutableListOf<String>()
        status.optJSONObject("battery")?.let {
            parts += "Battery ${it.optInt("percent")}%" + if (it.optBoolean("charging")) " charging" else ""
        }
        status.optJSONObject("volume")?.let { volume ->
            if (!volume.isNull("percent")) parts += if (volume.optBoolean("muted")) "Muted" else "Volume ${volume.optInt("percent")}%"
        }
        status.optString("project").takeIf { it.isNotBlank() }?.let { parts += "Project $it" }
        return parts.joinToString("  ·  ").ifBlank { "Ready" }
    }

    fun formatMinutes(minutes: Int): String =
        if (minutes >= 60) "${minutes / 60} h ${minutes % 60} min" else "$minutes min"

    /** A power profile's name as the computer's own settings show it. */
    fun profileName(id: String): String = when (id) {
        "power-saver" -> "Power saver"
        "performance" -> "Performance"
        "balanced" -> "Balanced"
        else -> id.replace('-', ' ').replaceFirstChar { it.uppercase() }
    }

    fun formatDuration(seconds: Int): String =
        if (seconds >= 3600) "%d:%02d:%02d".format(seconds / 3600, seconds % 3600 / 60, seconds % 60)
        else "%d:%02d".format(seconds / 60, seconds % 60)
}
