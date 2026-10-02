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
    fun relative(dx: Float, dy: Float) = JSONObject().put("t", "rel").put("dx", dx.toDouble()).put("dy", dy.toDouble()).toString()
    fun click(button: Int = 1) = JSONObject().put("t", "click").put("b", button).toString()
    fun button(down: Boolean, button: Int = 1) = JSONObject().put("t", if (down) "down" else "up").put("b", button).toString()
    fun doubleClick() = JSONObject().put("t", "double").toString()
    fun scroll(dx: Int, dy: Int) = JSONObject().put("t", "scroll").put("dx", dx).put("dy", dy).toString()
    fun key(name: String, vararg modifiers: String) =
        JSONObject().put("t", "key").put("k", name).put("m", JSONArray(modifiers.toList())).toString()
    fun text(value: String) = JSONObject().put("t", "text").put("s", value).toString()

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
