package com.karthi.adaptivelink

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Telephony
import android.telephony.TelephonyManager
import android.util.Base64
import androidx.activity.compose.setContent
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.security.Signature

/**
 * The phone's fingerprint saying yes to something on the computer:
 * unlocking it when the phone comes back, or sudo.
 *
 * The computer asks; the phone shows what is asked and by which computer;
 * the owner answers with their fingerprint or screen lock; and the yes is
 * signed with the key in this phone's secure hardware, over this request and
 * no other. Whoever asked checks that signature for themselves (for sudo
 * that is a program running as root, which trusts nothing else in between -
 * scripts/link-approve.py).
 */
object Approval {
    const val EXTRA_ASK = "ask"
    const val EXTRA_NONCE = "nonce"
    const val EXTRA_WHAT = "what"
    const val EXTRA_TEXT = "text"

    private fun id(ask: String) = 5000 + (ask.hashCode() and 0xFFF)

    /** The words for what is being asked. */
    fun title(what: String, computer: String): String = when (what) {
        "sudo" -> "Allow administrator rights on $computer?"
        "unlock" -> "Unlock $computer?"
        else -> "Approve on $computer?"
    }

    /** Put the question in front of the owner. */
    fun ask(context: Context, event: JSONObject) {
        val ask = event.optString("ask")
        val nonce = event.optString("nonce")
        val what = event.optString("title")
        if (ask.isEmpty() || !Regex("^[0-9a-f]{16,64}$").matches(nonce) || what !in listOf("sudo", "unlock")) return
        val open = Intent(context, ApproveActivity::class.java)
            .putExtra(EXTRA_ASK, ask).putExtra(EXTRA_NONCE, nonce).putExtra(EXTRA_WHAT, what)
            .putExtra(EXTRA_TEXT, event.optString("text"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        EventsService.channels(context)
        if (!EventsService.mayNotify(context)) return
        val pending = PendingIntent.getActivity(context, id(ask), open,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        context.getSystemService(NotificationManager::class.java).notify(id(ask),
            NotificationCompat.Builder(context, EventsService.CHANNEL_URGENT)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(title(what, Store(context).computer?.name ?: "the computer"))
                .setContentText("Tap to answer with your fingerprint")
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setContentIntent(pending)
                .setFullScreenIntent(pending, true)
                .setAutoCancel(true)
                .setTimeoutAfter(35_000)
                .build())
    }

    /** The question was answered, or given up on: take it away. */
    fun done(context: Context, ask: String) {
        if (ask.isNotEmpty()) context.getSystemService(NotificationManager::class.java).cancel(id(ask))
    }

    /** This phone's signature over one request, made by the key that never leaves its hardware. */
    fun sign(what: String, nonce: String): String {
        val signature = Signature.getInstance("SHA256withECDSA")
        signature.initSign(LinkIdentity.privateKey())
        signature.update(Protocol.approvalMessage(what, nonce))
        return Base64.encodeToString(signature.sign(), Base64.NO_WRAP)
    }
}

class ApproveActivity : FragmentActivity() {
    private var said by mutableStateOf("")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val ask = intent.getStringExtra(Approval.EXTRA_ASK).orEmpty()
        val nonce = intent.getStringExtra(Approval.EXTRA_NONCE).orEmpty()
        val what = intent.getStringExtra(Approval.EXTRA_WHAT).orEmpty()
        val text = intent.getStringExtra(Approval.EXTRA_TEXT).orEmpty()
        val computer = Store(this).computer?.name ?: "the computer"

        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Color(0xFF0A84FF), onPrimary = Color.White, background = Color(0xFF1C1C1E),
                onBackground = Color(0xFFF5F5F7), surface = Color(0xFF2C2C2E), onSurface = Color(0xFFF5F5F7),
                onSurfaceVariant = Color(0xFF98989D), error = Color(0xFFFF453A),
            )) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    Column(Modifier.fillMaxSize().systemBarsPadding().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text(Approval.title(what, computer), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                        if (text.isNotBlank()) Muted(text)
                        Muted("Say yes only if you asked for this yourself, just now.")
                        if (said.isNotEmpty()) Text(said, color = MaterialTheme.colorScheme.primary)
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Button(onClick = { confirm(ask, what, nonce) }, enabled = said.isEmpty()) { Text("Approve") }
                            OutlinedButton(onClick = { answer(ask, false, "") }, enabled = said.isEmpty()) { Text("Refuse") }
                        }
                    }
                }
            }
        }
    }

    /** The owner's fingerprint or screen lock, then the signed yes. */
    private fun confirm(ask: String, what: String, nonce: String) {
        val allowed = BIOMETRIC_WEAK or DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(allowed) != BiometricManager.BIOMETRIC_SUCCESS) {
            // A phone with no screen lock has nothing to prove who is holding it.
            said = "This phone has no screen lock, so it cannot approve anything. Set one in Settings."
            return
        }
        BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                answer(ask, true, runCatching { Approval.sign(what, nonce) }.getOrDefault(""))
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                said = errString.toString()
            }
        }).authenticate(BiometricPrompt.PromptInfo.Builder()
            .setTitle(Approval.title(what, Store(this).computer?.name ?: "the computer"))
            .setAllowedAuthenticators(allowed).build())
    }

    private fun answer(ask: String, ok: Boolean, signature: String) {
        said = if (ok) "Approving…" else "Refusing…"
        val client = Link.client(this)
        CoroutineScope(Dispatchers.IO).launch {
            val reply = client?.let {
                if (it.host == null) it.connect()
                it.post("/v1/approve", JSONObject().put("ask", ask).put("ok", ok && signature.isNotEmpty()).put("signature", signature))
            }
            runOnUiThread {
                Approval.done(this@ApproveActivity, ask)
                said = when {
                    reply?.optBoolean("ok") != true -> "The computer is no longer asking."
                    ok -> "Approved."
                    else -> "Refused."
                }
                window.decorView.postDelayed({ finish() }, 1200)
            }
        }
    }
}

/**
 * This phone's calls and text messages, shown on the computer. Android hands
 * these to the app only if the owner has given it the permissions, which the
 * switch in More asks for.
 */
private fun tellComputer(context: Context, intent: Intent, pending: BroadcastReceiver.PendingResult?) {
    val body = when (intent.action) {
        Telephony.Sms.Intents.SMS_RECEIVED_ACTION -> {
            val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent)
            if (parts.isNullOrEmpty()) null
            else "/v1/phone/sms" to JSONObject().put("from", parts[0].displayOriginatingAddress.orEmpty())
                .put("text", parts.joinToString("") { it.displayMessageBody.orEmpty() })
        }
        TelephonyManager.ACTION_PHONE_STATE_CHANGED -> {
            val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE)
            @Suppress("DEPRECATION") val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER)
            // Sent twice by Android, once without the number: wait for the one that has it, if one will come.
            if (state == TelephonyManager.EXTRA_STATE_RINGING && number == null &&
                ContextCompat.checkSelfPermission(context, android.Manifest.permission.READ_CALL_LOG) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED) null
            else "/v1/phone/call" to JSONObject().put("from", number.orEmpty())
                .put("state", if (state == TelephonyManager.EXTRA_STATE_RINGING) "ringing" else "ended")
        }
        else -> null
    }
    val client = if (Store(context).phoneMessages && body != null) Link.client(context) else null
    if (client == null || body == null) {
        pending?.finish()
        return
    }
    CoroutineScope(Dispatchers.IO).launch {
        runCatching {
            if (client.host != null || client.connect() != null) client.post(body.first, body.second)
        }
        pending?.finish()
    }
}

/** A text message has arrived. */
class PhoneReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = tellComputer(context.applicationContext, intent, goAsync())
}

/** The phone is ringing, or has stopped. Sent by Android without the permission texts carry, so it has a receiver of its own. */
class CallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) = tellComputer(context.applicationContext, intent, goAsync())
}
