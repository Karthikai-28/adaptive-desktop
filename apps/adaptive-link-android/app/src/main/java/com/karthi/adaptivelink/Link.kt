package com.karthi.adaptivelink

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/**
 * The app's one connection, shared by the screens and by the notification
 * relay (which runs when no screen is open).
 */
object Link {
    @Volatile private var cached: LinkClient? = null

    fun client(context: Context): LinkClient? {
        val computer = Store(context).computer ?: return null.also { cached = null }
        cached?.let { if (it.computer == computer) return it }
        return LinkClient(context, computer).also { cached = it }
    }

    fun forget() {
        cached = null
    }
}

/** What the screens show about the connection. */
class LinkState {
    var status by mutableStateOf<JSONObject?>(null)
    var connecting by mutableStateOf(false)
    var message by mutableStateOf("")

    val connected get() = status != null
    fun can(what: String): Boolean = status?.optJSONObject("can")?.optBoolean(what, false) ?: false
}

/**
 * Pointer and key events to the computer, with no picture: the trackpad, the
 * remote and the presenter all send through one of these. It opens on first
 * use and quietly reopens if the connection drops.
 */
class InputSocket(private val client: LinkClient) {
    @Volatile private var socket: WebSocket? = null

    @Synchronized
    private fun open(): WebSocket {
        socket?.let { return it }
        val created = client.socket("/v1/input", object : WebSocketListener() {
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (socket === webSocket) socket = null
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (socket === webSocket) socket = null
            }
        })
        socket = created
        return created
    }

    fun send(event: String) {
        open().send(event)
    }

    fun close() {
        socket?.close(1000, null)
        socket = null
    }
}
