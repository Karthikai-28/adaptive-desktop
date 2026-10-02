package com.karthi.adaptivelink

import android.app.Activity
import android.content.Context
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * The owner's Google account, and the small space it gives their devices to
 * find each other in (the computer's side of this is services/adaptive-link/
 * cloud.py, which says what is and is not kept there).
 *
 * The phone signs in with Android's own Google account picker - no password
 * is typed into this app. That sign-in is exchanged for a session in the
 * owner's own Firebase project, whose database has one rule: the part under
 * users/<uid> can be read and written only by someone signed in as that uid.
 *
 * What comes from the space is where the computer is and what certificate it
 * has. That certificate is then pinned exactly as one from a pairing code
 * would be, and everything the phone sends goes to the computer directly,
 * under that pin. Nothing but those few public facts passes through Google.
 */
class Cloud(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("cloud", Context.MODE_PRIVATE)
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()

    /** Where Google is. The app's own test points this at a stand-in. */
    data class Config(
        val apiKey: String, val databaseUrl: String, val webClientId: String,
        val signInUrl: String = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp",
        val refreshUrl: String = "https://securetoken.googleapis.com/v1/token",
        /** Test only: a ready-made identity, in place of the account picker. */
        val testIdentity: String = "",
        val stun: String = "stun:stun.l.google.com:19302",
    ) {
        val usable get() = apiKey.isNotBlank() && databaseUrl.isNotBlank() && webClientId.isNotBlank()
    }

    val config: Config = run {
        val override = prefs.getString("override", null)?.let { runCatching { JSONObject(it) }.getOrNull() }
        if (override != null) Config(
            override.optString("api_key"), override.optString("database_url").trimEnd('/'),
            override.optString("web_client_id"), override.optString("sign_in"), override.optString("refresh"),
            override.optString("test_identity"), override.optString("stun"),
        ) else Config(
            BuildConfig.CLOUD_API_KEY, BuildConfig.CLOUD_DATABASE_URL.trimEnd('/'), BuildConfig.CLOUD_WEB_CLIENT_ID,
        )
    }

    /** Whether this build knows the owner's Google project at all. */
    val available get() = config.usable

    val email: String get() = prefs.getString("email", "") ?: ""
    val uid: String get() = prefs.getString("uid", "") ?: ""
    val signedIn: Boolean get() = uid.isNotEmpty() && !prefs.getString("refresh", "").isNullOrEmpty()

    @Volatile private var token = ""
    @Volatile private var tokenUntil = 0L

    // ------------------------------------------------------------ sign-in

    /** Show Android's Google account picker and sign in. Returns the email, or throws. */
    suspend fun signIn(activity: Activity): String {
        val googleToken = if (config.testIdentity.isNotEmpty()) config.testIdentity else {
            val option = GetGoogleIdOption.Builder()
                .setServerClientId(config.webClientId)
                .setFilterByAuthorizedAccounts(false)
                .setAutoSelectEnabled(false)
                .build()
            val result = CredentialManager.create(activity).getCredential(
                activity, GetCredentialRequest.Builder().addCredentialOption(option).build()
            )
            val credential = result.credential
            if (credential !is CustomCredential ||
                credential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
            ) throw IllegalStateException("That is not a Google account")
            GoogleIdTokenCredential.createFrom(credential.data).idToken
        }
        return signInWith(googleToken)
    }

    /** Exchange Google's proof of who this is for a session in the owner's project. */
    suspend fun signInWith(googleToken: String): String = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("postBody", "id_token=$googleToken&providerId=google.com")
            .put("requestUri", "http://localhost").put("returnSecureToken", true)
        val reply = http.newCall(
            Request.Builder().url("${config.signInUrl}?key=${config.apiKey}")
                .post(body.toString().toRequestBody(JSON)).build()
        ).execute().use { JSONObject(it.body?.string().orEmpty()) }
        val refresh = reply.optString("refreshToken")
        if (refresh.isEmpty())
            throw IllegalStateException(reply.optJSONObject("error")?.optString("message") ?: "Sign-in was refused")
        prefs.edit().putString("uid", reply.getString("localId")).putString("email", reply.optString("email"))
            .putString("refresh", refresh).commit()
        token = reply.getString("idToken")
        tokenUntil = System.currentTimeMillis() + (reply.optLong("expiresIn", 3600) - 120) * 1000
        email
    }

    fun signOut() {
        prefs.edit().remove("uid").remove("email").remove("refresh").commit()
        token = ""
        tokenUntil = 0
    }

    private fun currentToken(): String {
        if (token.isNotEmpty() && System.currentTimeMillis() < tokenUntil) return token
        val form = FormBody.Builder().add("grant_type", "refresh_token")
            .add("refresh_token", prefs.getString("refresh", "") ?: "").build()
        val reply = http.newCall(Request.Builder().url("${config.refreshUrl}?key=${config.apiKey}").post(form).build())
            .execute().use { JSONObject(it.body?.string().orEmpty()) }
        val fresh = reply.optString("id_token")
        if (fresh.isEmpty()) throw IllegalStateException("The sign-in is no longer valid; sign in again")
        token = fresh
        tokenUntil = System.currentTimeMillis() + (reply.optLong("expires_in", 3600) - 120) * 1000
        return fresh
    }

    // ---------------------------------------------------------- the space

    private fun url(path: String) =
        "${config.databaseUrl}/users/$uid/${path.trim('/')}.json?auth=${currentToken()}"

    /** The value at a path: a JSONObject, a JSONArray, a String, a number, a Boolean, or null. */
    suspend fun get(path: String): Any? = withContext(Dispatchers.IO) {
        http.newCall(Request.Builder().url(url(path)).build()).execute().use { reply ->
            val text = reply.body?.string().orEmpty().trim()
            if (!reply.isSuccessful) throw IllegalStateException("The account's space answered ${reply.code}")
            if (text.isEmpty()) null
            else org.json.JSONTokener(text).nextValue().takeUnless { it == JSONObject.NULL }
        }
    }

    suspend fun put(path: String, value: JSONObject) = withContext(Dispatchers.IO) {
        http.newCall(Request.Builder().url(url(path)).put(value.toString().toRequestBody(JSON)).build())
            .execute().use { if (!it.isSuccessful) throw IllegalStateException("The account's space answered ${it.code}") }
    }

    suspend fun delete(path: String) = withContext(Dispatchers.IO) {
        http.newCall(Request.Builder().url(url(path)).delete().build()).execute().close()
    }

    /** The computers signed in to this account: id -> what each says about itself. */
    suspend fun computers(): List<Pair<String, Computer>> {
        val found = get("computers") as? JSONObject ?: return emptyList()
        return found.keys().asSequence().mapNotNull { id ->
            val entry = found.optJSONObject(id) ?: return@mapNotNull null
            val hosts = entry.optJSONArray("hosts").let { array ->
                List(array?.length() ?: 0) { array!!.optString(it) }.filter { Computer.isAddress(it) }
            }
            val fingerprint = entry.optString("fingerprint").lowercase()
            // The id is the start of the fingerprint: an entry that does not
            // match its own name is not what it claims to be.
            if (fingerprint.length != 64 || !fingerprint.startsWith(id) || fingerprint.any { it !in "0123456789abcdef" })
                return@mapNotNull null
            id to Computer(entry.optString("name", "Computer").take(60), hosts, entry.optInt("port", 47823), 0, fingerprint)
        }.toList()
    }

    companion object {
        val JSON = "application/json".toMediaType()

        /** A device's name in the space: the start of its certificate fingerprint. */
        fun deviceId(fingerprint: String) = fingerprint.take(20)

        /** For the app's own test: point the app at a stand-in for Google. */
        fun override(context: Context, json: JSONObject?) {
            context.applicationContext.getSharedPreferences("cloud", Context.MODE_PRIVATE).edit().apply {
                if (json == null) remove("override") else putString("override", json.toString())
            }.commit()
        }
    }
}
