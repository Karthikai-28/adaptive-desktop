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
) {
    fun toJson(): String = JSONObject()
        .put("n", name).put("h", JSONArray(hosts)).put("p", port)
        .put("pp", pairingPort).put("f", fingerprint).toString()

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
            Computer(json.optString("n", "Computer").take(60), hosts, port, pairingPort, fingerprint)
        }.getOrNull()

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

    fun formatDuration(seconds: Int): String =
        if (seconds >= 3600) "%d:%02d:%02d".format(seconds / 3600, seconds % 3600 / 60, seconds % 60)
        else "%d:%02d".format(seconds / 60, seconds % 60)
}
