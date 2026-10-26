package com.karthi.adaptivelink

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

/** User-invoked focused activity: Android then permits reading the current clipboard. */
class ClipboardSendActivity : ComponentActivity() {
    private var sending = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setDimAmount(0f)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus || sending || isFinishing) return
        sending = true
        val client = Link.client(this) ?: return finish()
        lifecycleScope.launch {
            val reached = client.host != null || client.connect() != null
            val sent = reached && ClipboardSync.sendCurrent(this@ClipboardSendActivity, client)
            Toast.makeText(this@ClipboardSendActivity,
                if (sent) "Clipboard sent to ${client.computer.name}" else "Nothing shareable on the clipboard",
                Toast.LENGTH_SHORT).show()
            finish()
        }
    }
}
