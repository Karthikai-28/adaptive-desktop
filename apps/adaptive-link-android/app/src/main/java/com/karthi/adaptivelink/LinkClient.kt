package com.karthi.adaptivelink

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.selects.select
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
class LinkClient(context: Context, val computer: Computer) {
    private val appContext = context.applicationContext

    /** The address that answered last: Wi-Fi at home, Tailscale away. */
    @Volatile var host: String? = null
        private set

    /** Every address the computer is known by; it tells the phone when they change. */
    @Volatile private var hosts: List<String> = computer.hosts

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

    private fun base(host: String, port: Int = computer.port): String {
        val literal = if (host.contains(':')) "[$host]" else host
        return "https://$literal:$port"
    }

    /**
     * Find an address the computer answers on. All are tried at once and the
     * first to answer wins, so being away from home costs no waiting on the
     * home address.
     */
    suspend fun connect(): JSONObject? = coroutineScope {
        val quick = http.newBuilder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(4, TimeUnit.SECONDS).build()
        val attempts = hosts.map { candidate ->
            async(Dispatchers.IO) {
                runCatching {
                    quick.newCall(Request.Builder().url("${base(candidate)}/v1/status").build()).execute().use {
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
        host = found?.first
        found?.second?.let { learn(it) }
        found?.second
    }

    /**
     * The computer says where it can be reached now (its Tailscale name, its
     * current addresses). This came over the authenticated link, so it is the
     * paired computer saying it. The phone remembers them, newest first, which
     * is what lets it find the computer again after an address changes.
     */
    private fun learn(status: JSONObject) {
        val told = status.optJSONArray("hosts") ?: return
        val fresh = List(told.length()) { told.optString(it) }.filter { Computer.isAddress(it) }
        val merged = (fresh + hosts).distinct().take(8)
        if (merged == hosts || fresh.isEmpty()) return
        hosts = merged
        Store(appContext).computer = computer.copy(hosts = merged)
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

    suspend fun upload(name: String, body: RequestBody): JSONObject? {
        val target = okhttp3.HttpUrl.Builder().scheme("https").host(host ?: hosts.first())
            .port(computer.port).addPathSegments("v1/upload").addQueryParameter("name", name).build()
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
