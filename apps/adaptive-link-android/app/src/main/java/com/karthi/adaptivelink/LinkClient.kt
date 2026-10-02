package com.karthi.adaptivelink

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.net.Socket
import java.security.Principal
import java.security.PrivateKey
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.X509ExtendedKeyManager
import javax.net.ssl.X509TrustManager

/**
 * The connection to the paired computer.
 *
 * Both directions are checked at the TLS handshake, before any request:
 *  - the computer must present exactly the certificate whose fingerprint was
 *    in the pairing code (PinnedTrust). No certificate authority is involved
 *    and no other certificate is accepted, so nobody can stand in for it;
 *  - this phone presents its own certificate, signed for by the key in its
 *    hardware keystore (PhoneKey). The computer accepts no other.
 */
class LinkClient(
    context: Context, val computer: Computer,
    /** False only in the app's own test, to be "away" while sitting next to the computer. */
    private val nearby: Boolean = true,
) {
    private val appContext = context.applicationContext

    /** The address that answered last: the computer's own on its network, this phone's when tunnelled. */
    @Volatile var host: String? = null
        private set

    /** The port that goes with it: the computer's, or the tunnel's on this phone. */
    @Volatile private var port: Int = computer.port

    /** The direct connection used away from the computer's network. */
    private val cloud = Cloud(appContext)
    private var tunnel: Tunnel? = null
    private val tunnelLock = Mutex()

    /** Whether the link is going through the direct connection just now. */
    val tunnelled get() = host == LOCAL

    @Volatile private var tunnelProblem = ""

    /** Why the computer could not be reached away from its network, for the screen. */
    @Volatile var awayProblem: String = ""
        private set

    /** Every address the computer is known by; it tells the phone when they change. */
    @Volatile private var hosts: List<String> = computer.hosts
    @Volatile private var wake: List<String> = computer.wake

    val http: OkHttpClient = build(withPhoneKey = true)

    private fun build(withPhoneKey: Boolean): OkHttpClient {
        val trust = PinnedTrust(computer.fingerprint)
        val keys = if (withPhoneKey) arrayOf(PhoneKey(appContext)) else null
        val ssl = SSLContext.getInstance("TLS").apply { init(keys, arrayOf(trust), null) }
        return OkHttpClient.Builder()
            .sslSocketFactory(ssl.socketFactory, trust)
            // The certificate itself is pinned; its name is not what is trusted.
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .pingInterval(15, TimeUnit.SECONDS)
            .build()
    }

    private fun base(host: String, port: Int = this.port): String {
        val literal = if (host.contains(':')) "[$host]" else host
        return "https://$literal:$port"
    }

    /**
     * Find a way to the computer. On its own network it is asked directly;
     * anywhere else, the two set up a direct connection through the account
     * (Tunnel) and the same requests go through that.
     */
    suspend fun connect(): JSONObject? {
        if (tunnelled) {
            // Already tunnelled: keep using it while it works, and look for
            // the computer's own network again only when it stops.
            askThroughTunnel()?.let { return it }
        }
        if (nearby) askOnNetwork()?.let { return it }
        // The computer may have moved to another network, or been given
        // another address: the account says where it is now. Whatever is
        // read there is only somewhere to look - the pinned certificate
        // still decides whether what answers is the computer.
        if (nearby && relocate()) askOnNetwork()?.let { return it }
        return openTunnel()
    }

    private suspend fun relocate(): Boolean {
        if (!cloud.available || !cloud.signedIn) return false
        val listed = runCatching { cloud.computers() }.getOrNull()
            ?.firstOrNull { it.second.fingerprint == computer.fingerprint }?.second ?: return false
        val merged = (listed.hosts + hosts).distinct().take(8)
        if (listed.hosts.isEmpty() || merged == hosts) return false
        hosts = merged
        val store = Store(appContext)
        if (store.computers.any { it.fingerprint == computer.fingerprint }) store.computer = computer.copy(hosts = merged)
        return true
    }

    private val quick by lazy {
        http.newBuilder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS).build()
    }

    private suspend fun askThroughTunnel(): JSONObject? = withContext(Dispatchers.IO) {
        val through = tunnel?.takeIf { it.alive } ?: return@withContext null
        runCatching {
            quick.newCall(Request.Builder().url("${base(LOCAL, through.port)}/v1/status").build()).execute().use {
                if (it.isSuccessful) JSONObject(it.body!!.string()) else null.also { _ -> tunnelProblem = "it answered ${it.code}" }
            }
        }.onFailure { tunnelProblem = describe(it as? Exception ?: RuntimeException(it)) }.getOrNull()?.also { learn(it) }
    }

    private suspend fun openTunnel(): JSONObject? = tunnelLock.withLock {
        if (!cloud.available || !cloud.signedIn) {
            awayProblem = ""
            return null
        }
        try {
            val through = tunnel?.takeIf { it.alive }
                ?: Tunnel(appContext, cloud, Cloud.deviceId(computer.fingerprint)).also {
                    tunnel?.close()
                    tunnel = it
                    it.open()
                }
            host = LOCAL
            port = through.port
            awayProblem = ""
            askThroughTunnel() ?: run {
                through.close()
                host = null
                port = computer.port
                awayProblem = "The direct connection was made, but the computer did not answer on it ($tunnelProblem)."
                null
            }
        } catch (e: Exception) {
            tunnel?.close()
            tunnel = null
            host = null
            port = computer.port
            awayProblem = e.message ?: e.javaClass.simpleName
            null
        }
    }

    /**
     * Every address the computer has on its network is tried at once and the
     * first to answer wins.
     */
    private suspend fun askOnNetwork(): JSONObject? = coroutineScope {
        val attempts = hosts.map { candidate ->
            async(Dispatchers.IO) {
                runCatching {
                    quick.newCall(Request.Builder().url("${base(candidate, computer.port)}/v1/status").build()).execute().use {
                        if (it.isSuccessful) candidate to JSONObject(it.body!!.string()) else null
                    }
                }.getOrNull()
            }
        }.toMutableList()
        var found: Pair<String, JSONObject>? = null
        while (found == null && attempts.isNotEmpty()) {
            val (finished, result) = select<Pair<Any, Pair<String, JSONObject>?>> {
                attempts.forEach { attempt -> attempt.onAwait { attempt to it } }
            }
            attempts.remove(finished)
            found = result
        }
        attempts.forEach { it.cancel() }
        if (found != null) {
            host = found.first
            port = computer.port
            // On the computer's own network again: the tunnel is not needed.
            tunnel?.close()
            tunnel = null
            learn(found.second)
        } else if (!tunnelled) host = null
        found?.second
    }

    /** Let go of the direct connection (unpairing, signing out). */
    fun close() {
        tunnel?.close()
        tunnel = null
        if (tunnelled) host = null
    }

    /**
     * The computer says which addresses it has on its network now. This came
     * over the authenticated link, so it is the paired computer saying it. The phone remembers them, newest first, which
     * is what lets it find the computer again after an address changes.
     */
    private fun learn(status: JSONObject) {
        // The owner's relay, or that there is none (any more).
        if (status.has("relay")) {
            val relay = Relay.fromJson(status.optJSONObject("relay")?.toString())?.toJson().orEmpty()
            val store = Store(appContext)
            if (store.relay != relay) store.relay = relay
        }
        val told = status.optJSONArray("hosts") ?: return
        val fresh = List(told.length()) { told.optString(it) }.filter { Computer.isAddress(it) }
        val merged = (fresh + hosts).distinct().take(8)
        // Where to send the packet that wakes it, for when it is asleep and cannot say.
        val waking = status.optJSONArray("wake").let { array ->
            if (array == null) wake else List(array.length()) { array.optJSONObject(it) }.filterNotNull()
                .map { "${it.optString("mac")}|${it.optString("broadcast")}" }.filter { Computer.isWake(it) }
        }
        if ((merged == hosts || fresh.isEmpty()) && waking == wake) return
        if (fresh.isNotEmpty()) hosts = merged
        wake = waking
        // Only while still paired: a computer just forgotten is not put back by its own last answer.
        val store = Store(appContext)
        if (store.computers.any { it.fingerprint == computer.fingerprint }) store.computer = computer.copy(hosts = hosts, wake = waking)
    }

    /** Whether this phone knows how to wake the computer at all. */
    val canWake get() = wake.isNotEmpty()

    /**
     * Ask the sleeping computer to wake. Only on its own network: the packet
     * is a broadcast, which no router passes on. Returns how many were sent.
     */
    suspend fun wake(): Int = withContext(Dispatchers.IO) {
        var sent = 0
        runCatching {
            java.net.DatagramSocket().use { socket ->
                socket.broadcast = true
                for (entry in wake) {
                    val (mac, broadcast) = entry.split('|')
                    val packet = Protocol.magicPacket(mac)
                    for (target in listOf(broadcast, "255.255.255.255")) for (port in listOf(9, 7)) {
                        runCatching {
                            socket.send(java.net.DatagramPacket(packet, packet.size, java.net.InetAddress.getByName(target), port))
                            sent++
                        }
                    }
                }
            }
        }
        sent
    }

    private fun url(path: String): String = base(host ?: hosts.first()) + path

    suspend fun get(path: String): JSONObject? = call(Request.Builder().url(url(path)).build())

    suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject? =
        call(Request.Builder().url(url(path)).post(body.toString().toRequestBody(JSON)).build())

    private suspend fun call(request: Request): JSONObject? = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                val json = runCatching { JSONObject(text) }.getOrElse { JSONObject() }
                if (!response.isSuccessful && !json.has("error")) json.put("error", "HTTP ${response.code}")
                json
            }
        }.getOrNull()
    }

    /** A raw response, for downloads. The caller closes it. */
    suspend fun open(path: String): Response? = withContext(Dispatchers.IO) {
        runCatching { http.newCall(Request.Builder().url(url(path)).build()).execute() }.getOrNull()
    }

    /** Send a file. `to` says what kind it is - "photos", "scans" - and so where it goes; "" is Downloads/Phone. */
    suspend fun upload(name: String, body: RequestBody, to: String = ""): JSONObject? {
        val target = okhttp3.HttpUrl.Builder().scheme("https").host(host ?: hosts.first())
            .port(port).addPathSegments("v1/upload").addQueryParameter("name", name).addQueryParameter("to", to).build()
        val long = http.newBuilder().writeTimeout(0, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS).build()
        return withContext(Dispatchers.IO) {
            runCatching {
                long.newCall(Request.Builder().url(target).post(body).build()).execute().use {
                    JSONObject(it.body?.string().orEmpty())
                }
            }.getOrNull()
        }
    }

    fun socket(path: String, listener: WebSocketListener): WebSocket =
        http.newWebSocket(Request.Builder().url(url(path)).build(), listener)

    /**
     * Pairing, before the computer knows this phone: the computer still has
     * to prove itself (same pin), the phone cannot yet.
     */
    suspend fun requestPairing(token: String, phoneName: String): JSONObject? = withContext(Dispatchers.IO) {
        lastProblem = ""
        val body = try {
            JSONObject().put("t", token).put("name", phoneName)
                .put("cert", Protocol.pem(LinkIdentity.certificate(appContext).encoded))
        } catch (e: Exception) {
            lastProblem = "This phone could not create its key: ${describe(e)}"
            return@withContext null
        }
        val open = build(withPhoneKey = false)
        val problems = mutableListOf<String>()
        for (candidate in computer.hosts) {
            try {
                val answer = open.newCall(
                    Request.Builder().url("${base(candidate, computer.pairingPort)}/pair")
                        .post(body.toString().toRequestBody(JSON)).build()
                ).execute().use { JSONObject(it.body!!.string()) }
                host = candidate
                return@withContext answer
            } catch (e: Exception) {
                problems += "$candidate: ${describe(e)}"
            }
        }
        lastProblem = problems.joinToString("\n")
        null
    }

    /** Why the last pairing request failed, in words fit to show. */
    @Volatile var lastProblem: String = ""
        private set

    private fun describe(e: Exception): String = when (e) {
        is java.net.SocketTimeoutException -> "no answer (timed out) - a firewall on the computer, or the two are on different networks"
        is java.net.ConnectException -> "connection refused - pairing is not open on the computer, or its window has closed"
        is java.net.NoRouteToHostException -> "no route - the phone is not on the computer's network"
        is javax.net.ssl.SSLException -> "secure connection failed: ${e.message}"
        else -> "${e.javaClass.simpleName}: ${e.message}"
    }

    /** Wait for the owner to press Pair or Reject on the computer. */
    suspend fun awaitPairing(token: String): String = withContext(Dispatchers.IO) {
        val open = build(withPhoneKey = false).newBuilder().readTimeout(35, TimeUnit.SECONDS).build()
        val target = okhttp3.HttpUrl.Builder().scheme("https").host(host ?: hosts.first())
            .port(computer.pairingPort).addPathSegments("pair/wait").addQueryParameter("t", token).build()
        repeat(8) {
            val state = runCatching {
                open.newCall(Request.Builder().url(target).build()).execute().use {
                    JSONObject(it.body!!.string()).optString("state")
                }
            }.getOrNull() ?: return@withContext "unreachable"
            if (state != "pending" && state != "waiting") return@withContext state
        }
        "expired"
    }

    companion object {
        val JSON = "application/json".toMediaType()

        /** Where the tunnel listens: on this phone, for this app. */
        const val LOCAL = "127.0.0.1"
    }
}

/** Trusts one certificate: the one whose fingerprint was in the pairing code. */
private class PinnedTrust(private val fingerprint: String) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
        if (chain.isEmpty() || Protocol.fingerprint(chain[0].encoded) != fingerprint)
            throw CertificateException("This is not the paired computer")
    }

    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) =
        throw CertificateException("not a server")

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
}

/** Presents this phone's certificate; the signing happens inside the keystore. */
private class PhoneKey(private val context: Context) : X509ExtendedKeyManager() {
    private val alias = "phone"
    override fun chooseClientAlias(keyTypes: Array<String>?, issuers: Array<Principal>?, socket: Socket?) = alias
    override fun chooseEngineClientAlias(keyTypes: Array<String>?, issuers: Array<Principal>?, engine: SSLEngine?) = alias
    override fun getCertificateChain(alias: String?): Array<X509Certificate> = arrayOf(LinkIdentity.certificate(context))
    override fun getPrivateKey(alias: String?): PrivateKey = LinkIdentity.privateKey()
    override fun getClientAliases(keyType: String?, issuers: Array<Principal>?) = arrayOf(alias)
    override fun getServerAliases(keyType: String?, issuers: Array<Principal>?): Array<String>? = null
    override fun chooseServerAlias(keyType: String?, issuers: Array<Principal>?, socket: Socket?): String? = null
}
