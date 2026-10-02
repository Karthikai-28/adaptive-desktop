package com.karthi.adaptivelink

import android.content.Context
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * A direct connection to the computer when the phone is not on its network.
 *
 * The two devices tell each other, through the account's space, where each
 * can be reached, and connect straight to each other (WebRTC). Over that
 * runs a plain tunnel: this listens on a port on the phone itself, and every
 * connection made to that port is carried to the link's own port on the
 * computer (the computer's end is services/adaptive-link/rtc.py).
 *
 * So the rest of the app does not change. It talks to 127.0.0.1 instead of
 * the computer's address, with the same pinned certificate and the same key:
 * the tunnel only carries the bytes of that connection, and neither Google
 * nor anyone on the path can read them or stand in for the computer.
 *
 * There is no relay. Where the network does not allow a direct connection
 * at all (some mobile carriers), this fails and says so.
 */
class Tunnel(private val context: Context, private val cloud: Cloud, private val computerId: String) {
    private var peer: PeerConnection? = null
    private var server: ServerSocket? = null
    @Volatile var port = 0
        private set
    @Volatile var alive = false
        private set

    /** Bring the tunnel up. Returns the local port to connect to, or throws. */
    suspend fun open(): Int {
        if (alive && port != 0) return port
        close()
        val connection = factory(context).createPeerConnection(
            PeerConnection.RTCConfiguration(
                if (cloud.config.stun.isBlank()) emptyList()
                else listOf(PeerConnection.IceServer.builder(cloud.config.stun).createIceServer())
            ),
            object : Observer() {
                override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
                    if (state == PeerConnection.PeerConnectionState.FAILED ||
                        state == PeerConnection.PeerConnectionState.CLOSED ||
                        state == PeerConnection.PeerConnectionState.DISCONNECTED
                    ) alive = false
                }
            },
        ) ?: throw IllegalStateException("This phone could not start a direct connection")
        peer = connection

        // Made before the offer, so the offer describes a connection that
        // carries data channels at all.
        val control = connection.createDataChannel("control", DataChannel.Init())
        val opened = CountDownLatch(1)
        control.registerObserver(object : ChannelObserver() {
            override fun onStateChange() {
                if (control.state() == DataChannel.State.OPEN) opened.countDown()
            }
        })

        if (control.state() == DataChannel.State.OPEN) opened.countDown()

        val offer = connection.await { createOffer(it, MediaConstraints()) }
        connection.awaitDone { setLocalDescription(it, offer) }
        // All of this device's addresses go in the one offer, so the two
        // sides exchange one message each.
        withTimeout(12_000) {
            while (connection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) delay(100)
        }

        val session = UUID.randomUUID().toString().replace("-", "").take(20)
        val path = "signals/$computerId/$session"
        cloud.put(path, JSONObject().put("offer", connection.localDescription.description)
            .put("at", System.currentTimeMillis() / 1000.0))
        var answer: String? = null
        for (attempt in 1..60) {
            delay(500)
            answer = cloud.get("$path/answer") as? String
            if (!answer.isNullOrEmpty()) break
        }
        runCatching { cloud.delete(path) }
        if (answer.isNullOrEmpty()) throw IllegalStateException("The computer did not answer. Is it on, and signed in to this account?")
        connection.awaitDone { setRemoteDescription(it, SessionDescription(SessionDescription.Type.ANSWER, answer)) }

        val connected = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { opened.await(20, TimeUnit.SECONDS) }
        if (!connected) {
            close()
            throw IllegalStateException("A direct connection could not be made on this network.")
        }

        val listener = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        server = listener
        port = listener.localPort
        alive = true
        thread(name = "link-tunnel", isDaemon = true) {
            while (!listener.isClosed) {
                val socket = runCatching { listener.accept() }.getOrNull() ?: break
                thread(isDaemon = true) { carry(connection, socket) }
            }
        }
        return port
    }

    /** One connection made to the local port, carried over a channel of its own. */
    private fun carry(connection: PeerConnection, socket: Socket) {
        val channel = connection.createDataChannel("tcp", DataChannel.Init()) ?: return socket.close()
        val opened = CountDownLatch(1)
        val out = socket.getOutputStream()
        channel.registerObserver(object : ChannelObserver() {
            override fun onStateChange() {
                when (channel.state()) {
                    DataChannel.State.OPEN -> opened.countDown()
                    DataChannel.State.CLOSED, DataChannel.State.CLOSING -> runCatching { socket.close() }
                    else -> Unit
                }
            }

            override fun onMessage(buffer: DataChannel.Buffer) {
                val bytes = ByteArray(buffer.data.remaining())
                buffer.data.get(bytes)
                runCatching { out.write(bytes); out.flush() }.onFailure { runCatching { channel.close() } }
            }
        })
        // On a connection that is already up a channel opens at once, and
        // may have done so before anything was listening for it.
        if (channel.state() == DataChannel.State.OPEN) opened.countDown()
        try {
            if (!opened.await(15, TimeUnit.SECONDS)) return
            val input = socket.getInputStream()
            val chunk = ByteArray(CHUNK)
            while (true) {
                val read = input.read(chunk)
                if (read < 0) break
                // Wait while the channel is backed up, rather than queue without bound.
                while (channel.bufferedAmount() > HIGH_WATER && channel.state() == DataChannel.State.OPEN) Thread.sleep(5)
                if (channel.state() != DataChannel.State.OPEN) break
                channel.send(DataChannel.Buffer(ByteBuffer.wrap(chunk.copyOf(read)), true))
            }
        } catch (e: Exception) {
            // The connection ended; nothing to carry.
        } finally {
            runCatching { socket.close() }
            runCatching { channel.close() }
            runCatching { channel.dispose() }
        }
    }

    fun close() {
        alive = false
        port = 0
        runCatching { server?.close() }
        server = null
        runCatching { peer?.close() }
        peer = null
    }

    // WebRTC's callbacks, as suspending calls.
    private suspend fun PeerConnection.await(start: PeerConnection.(SdpObserver) -> Unit): SessionDescription =
        suspendCancellableCoroutine { continuation ->
            start(object : SdpObserver {
                override fun onCreateSuccess(description: SessionDescription) = continuation.resume(description)
                override fun onCreateFailure(reason: String?) = continuation.resumeWithException(IllegalStateException(reason))
                override fun onSetSuccess() = Unit
                override fun onSetFailure(reason: String?) = Unit
            })
        }

    private suspend fun PeerConnection.awaitDone(start: PeerConnection.(SdpObserver) -> Unit): Unit =
        suspendCancellableCoroutine { continuation ->
            start(object : SdpObserver {
                override fun onSetSuccess() = continuation.resume(Unit)
                override fun onSetFailure(reason: String?) = continuation.resumeWithException(IllegalStateException(reason))
                override fun onCreateSuccess(description: SessionDescription) = Unit
                override fun onCreateFailure(reason: String?) = Unit
            })
        }

    private open class ChannelObserver : DataChannel.Observer {
        override fun onBufferedAmountChange(previous: Long) = Unit
        override fun onStateChange() = Unit
        override fun onMessage(buffer: DataChannel.Buffer) = Unit
    }

    private open class Observer : PeerConnection.Observer {
        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = Unit
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) = Unit
        override fun onIceCandidate(candidate: IceCandidate) = Unit
        override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) = Unit
        override fun onAddStream(stream: MediaStream) = Unit
        override fun onRemoveStream(stream: MediaStream) = Unit
        override fun onDataChannel(channel: DataChannel) = Unit
        override fun onRenegotiationNeeded() = Unit
        override fun onAddTrack(receiver: RtpReceiver, streams: Array<MediaStream>) = Unit
    }

    companion object {
        private const val CHUNK = 16 * 1024
        private const val HIGH_WATER = 1024L * 1024

        @Volatile private var shared: PeerConnectionFactory? = null

        private fun factory(context: Context): PeerConnectionFactory = shared ?: synchronized(this) {
            shared ?: run {
                PeerConnectionFactory.initialize(
                    PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions()
                )
                PeerConnectionFactory.builder().createPeerConnectionFactory().also { shared = it }
            }
        }
    }
}
