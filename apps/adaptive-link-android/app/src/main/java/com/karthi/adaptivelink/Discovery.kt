package com.karthi.adaptivelink

import android.os.Build
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Dns
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** A computer found by signing in, and the account it is signed in with. */
data class Found(val computer: Computer, val account: String)

/**
 * Finding the computer by account instead of by a pairing code.
 *
 * Both devices are signed in to the same Tailscale network with the same
 * account (a Google account, for instance). On that network every device has
 * a name, and the connection to it is encrypted to keys that device signed in
 * with: reaching "adaptive-link" there is reaching a device of this account
 * and nothing else. So the phone looks the computer up by its well-known
 * name, asks who it is, and pins the certificate it answers with.
 *
 * That first question is the one moment the app talks to a computer whose
 * certificate it does not know yet. It is only ever asked of an address
 * inside Tailscale's range: a name that resolves anywhere else is refused, so
 * an ordinary network can never stand in for the computer.
 */
object Discovery {
    /** The names the computer side gives its Tailscale node (install-link-tailnet.sh). */
    val NAMES = listOf("adaptive-link", "adaptive-link-1", "adaptive-link-2")
    const val PAIRING_PORT = 47824

    fun isEmulator(): Boolean =
        Build.FINGERPRINT.startsWith("generic") || Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish"

    /** Tailscale's address ranges: 100.64.0.0/10 and fd7a:115c:a1e0::/48. */
    fun onTailnet(address: InetAddress): Boolean = when (address) {
        is Inet4Address -> address.address.let { (it[0].toInt() and 0xFF) == 100 && (it[1].toInt() and 0xC0) == 64 }
        is Inet6Address -> address.address.let {
            it[0] == 0xfd.toByte() && it[1] == 0x7a.toByte() && it[2] == 0x11.toByte() &&
                it[3] == 0x5c.toByte() && it[4] == 0xa1.toByte() && it[5] == 0xe0.toByte()
        }
        else -> false
    }

    private fun allowed(address: InetAddress): Boolean =
        onTailnet(address) ||
            // The emulator's alias for the machine it runs on: how the app's
            // own test reaches a computer. Never accepted on a real phone.
            (isEmulator() && address.hostAddress == "10.0.2.2")

    /** Remembers the certificate the other end presented. */
    private class Capture : X509TrustManager {
        @Volatile var fingerprint: String = ""
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            fingerprint = Protocol.fingerprint(chain[0].encoded)
        }
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = Unit
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    /**
     * Look for the computer. [typed] is a name or address the owner entered
     * ("name" or "name:port"), tried before the well-known names.
     * Returns what was found, or why nothing was.
     */
    suspend fun find(typed: String = ""): Pair<Found?, String> = withContext(Dispatchers.IO) {
        val problems = mutableListOf<String>()
        val candidates = (listOf(typed.trim()).filter { it.isNotEmpty() } + NAMES).distinct()
        for (candidate in candidates) {
            val host = candidate.substringBeforeLast(":", candidate).takeIf { candidate.count { c -> c == ':' } == 1 } ?: candidate
            val port = candidate.substringAfterLast(":", "").toIntOrNull()?.takeIf { candidate.count { c -> c == ':' } == 1 }
                ?: PAIRING_PORT
            if (!Computer.isAddress(host)) {
                problems += "$candidate: not a name or address"
                continue
            }
            val addresses = runCatching { InetAddress.getAllByName(host).filter { allowed(it) } }.getOrDefault(emptyList())
            if (addresses.isEmpty()) {
                if (candidate == typed.trim()) problems += "$host: not found on your Tailscale network"
                continue
            }
            val capture = Capture()
            val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(capture), null) }
            val client = OkHttpClient.Builder()
                .sslSocketFactory(ssl.socketFactory, capture)
                .hostnameVerifier { _, _ -> true }
                // Only the addresses that passed the check above are dialled.
                .dns(object : Dns { override fun lookup(hostname: String) = addresses })
                .connectTimeout(4, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS)
                .build()
            val literal = if (host.contains(':')) "[$host]" else host
            try {
                client.newCall(Request.Builder().url("https://$literal:$port/hello").build()).execute().use { reply ->
                    val json = JSONObject(reply.body?.string().orEmpty())
                    if (!reply.isSuccessful) {
                        problems += "$host: " + json.optString("error", "refused (${reply.code})")
                        return@use
                    }
                    val fingerprint = json.optString("fingerprint")
                    if (fingerprint.isEmpty() || fingerprint != capture.fingerprint) {
                        problems += "$host: answered with a certificate that is not its own"
                        return@use
                    }
                    val told = json.optJSONArray("hosts")
                    val hosts = (listOf(host) + List(told?.length() ?: 0) { told!!.optString(it) })
                        .filter { Computer.isAddress(it) }.distinct()
                    val computer = Computer(
                        json.optString("name", host).take(60), hosts,
                        json.optInt("port", 47823), json.optInt("pairing_port", port), fingerprint,
                    )
                    return@withContext Found(computer, json.optString("account")) to ""
                }
            } catch (e: Exception) {
                problems += "$host: ${e.javaClass.simpleName}: ${e.message}"
            }
        }
        null to problems.joinToString("\n").ifBlank {
            "No computer answered as \u201cadaptive-link\u201d. Tailscale has to be on, on this phone and on the " +
                "computer, signed in with the same account."
        }
    }
}
