package com.karthi.adaptivelink

import android.util.Base64
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * The link, end to end, on Android: this device's keystore, its TLS stack and
 * the app's own client, against the real daemon on the computer.
 *
 * scripts/verify-link-android.py starts the daemon, opens pairing, passes the
 * offer in as an argument and presses "Pair" on the computer's side when this
 * test asks. Run on its own, with no offer, the test is skipped.
 *
 * It also passes in a stand-in for Google (scripts/fake_cloud.py), which the
 * computer is signed in to, so that the account and the direct connection
 * are exercised with no real account and no internet.
 */
@RunWith(AndroidJUnit4::class)
class LinkInstrumentedTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    private fun offer(): PairingOffer? =
        InstrumentationRegistry.getArguments().getString("offer")
            ?.let { String(Base64.decode(it, Base64.URL_SAFE)) }
            ?.let { PairingOffer.parse(it) }

    private fun standIn(): JSONObject? =
        InstrumentationRegistry.getArguments().getString("cloud")
            ?.let { JSONObject(String(Base64.decode(it, Base64.URL_SAFE))) }

    /**
     * Not a check: points the installed app at the stand-in for Google, for
     * the part of the script that then uses the app's own screens.
     */
    @Test
    fun pointAtStandIn() {
        val standIn = standIn()
        assumeTrue("no stand-in was passed in", standIn != null)
        Cloud.override(context, standIn)
    }

    @Test
    fun pairThenUseTheLink() = runBlocking {
        val offer = offer()
        assumeTrue("no pairing offer was passed in", offer != null)
        offer!!

        // A fresh identity, made in this device's keystore.
        LinkIdentity.delete()
        val certificate = LinkIdentity.certificate(context)
        assertEquals("EC", certificate.publicKey.algorithm)
        assertTrue("the key must not be extractable", LinkIdentity.privateKey().encoded == null)

        // Before pairing, the link itself is closed to this device.
        val client = LinkClient(context, offer.computer)
        assertNull("an unpaired phone must not get in", client.connect())

        // Pairing: the computer answers with the digits this phone computes too.
        val answer = client.requestPairing(offer.token, "Test Phone")
        assertNotNull("the computer did not answer the pairing request", answer)
        assertEquals(
            Protocol.pairingCode(offer.computer.fingerprint, LinkIdentity.fingerprint(context)),
            answer!!.optString("code"),
        )
        assertEquals("paired", client.awaitPairing(offer.token))

        // The link: mutual TLS with the keystore key, the computer's certificate pinned.
        var status: JSONObject? = null
        for (attempt in 1..20) {
            status = client.connect()
            if (status != null) break
            Thread.sleep(500)   // the computer restarts its listener for the new phone
        }
        assertNotNull("the paired phone could not connect", status)
        assertEquals(1, status!!.getInt("version"))

        // The screen arrives as JPEG.
        val frame = CountDownLatch(1)
        var first: ByteArray? = null
        val screen = client.socket("/v1/screen?preset=low", object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                first = bytes.toByteArray()
                frame.countDown()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = frame.countDown()
        })
        assertTrue("no screen frame arrived", frame.await(15, TimeUnit.SECONDS))
        screen.close(1000, null)
        assertTrue("the frame is not a JPEG", first != null && first!![0] == 0xFF.toByte() && first!![1] == 0xD8.toByte())

        // A command runs and its output comes back.
        val finished = CountDownLatch(1)
        val output = StringBuilder()
        var exit = -1
        client.socket("/v1/exec", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(JSONObject().put("cmd", "echo from-the-phone").toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val json = JSONObject(text)
                output.append(json.optString("o"))
                if (json.has("exit")) { exit = json.getInt("exit"); finished.countDown() }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = finished.countDown()
        })
        assertTrue("the command did not finish", finished.await(15, TimeUnit.SECONDS))
        assertEquals("from-the-phone", output.toString().trim())
        assertEquals(0, exit)

        // Requests the app makes: the file listing, and a notification.
        assertNotNull(client.get("/v1/files?path=~")?.optJSONArray("entries"))
        assertNotNull(client.post("/v1/notify", JSONObject().put("key", "k").put("app", "Test").put("title", "Hi").put("text", "x")))

        standIn()?.let { awayThroughTheAccount(it, offer.computer) }

        if (InstrumentationRegistry.getArguments().getString("stay") != null) {
            // Leave the app paired, as scanning the code would have, so the
            // screens can be opened and looked at afterwards.
            Store(context).computer = offer.computer
            Store(context).lockOnOpen = false
            Link.forget()
            return@runBlocking
        }

        // Something claiming to be the computer, with a different certificate, is refused by the phone.
        val impostor = offer.computer.copy(fingerprint = "0".repeat(64))
        assertNull("a different certificate must not be trusted", LinkClient(context, impostor).connect())

        // And a phone with a different key is refused by the computer: the
        // pairing is to this key, not to this app or this address.
        LinkIdentity.delete()
        assertNull("a new key must not get in", LinkClient(context, offer.computer).connect())
    }

    /**
     * Away from the computer's network: none of its addresses answers, and
     * the phone reaches it through a direct connection set up by way of the
     * account both are signed in to.
     */
    private suspend fun awayThroughTheAccount(standIn: JSONObject, paired: Computer) {
        Cloud.override(context, standIn)
        val cloud = Cloud(context)
        cloud.signOut()
        assertEquals("me@example.com", cloud.signInWith("google:me@example.com"))

        val listed = cloud.computers().firstOrNull { it.second.fingerprint == paired.fingerprint }
        assertNotNull("the account does not list the computer", listed)
        assertEquals(Cloud.deviceId(paired.fingerprint), listed!!.first)

        // The computer has moved since the phone last saw it: the address
        // the phone remembers answers nothing, and the account says where
        // it is now.
        val elsewhere = listed.second.copy(hosts = listOf("192.0.2.1"))
        val moved = LinkClient(context, elsewhere)
        assertNotNull("the computer's new address was not found through the account", moved.connect())
        assertTrue(!moved.tunnelled)
        moved.close()

        // Away from its network altogether.
        val away = LinkClient(context, elsewhere, nearby = false)
        val status = away.connect()
        assertNotNull("no direct connection: ${away.awayProblem}", status)
        assertTrue(away.tunnelled)
        assertEquals("direct", status!!.optString("via"))
        assertNotNull(away.get("/v1/files?path=~")?.optJSONArray("entries"))

        // Something bigger than one message, both ways: a screen frame back.
        val frame = CountDownLatch(1)
        var size = 0
        val screen = away.socket("/v1/screen?preset=high", object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                size = bytes.size
                frame.countDown()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = frame.countDown()
        })
        assertTrue("no screen frame arrived through the direct connection", frame.await(20, TimeUnit.SECONDS))
        screen.close(1000, null)
        assertTrue("the frame through the direct connection is empty", size > 1000)
        away.close()

        // Another account's space does not have the computer in it, and
        // asking through it reaches nobody.
        cloud.signOut()
        assertEquals("someone-else@example.com", cloud.signInWith("google:someone-else@example.com"))
        assertTrue(cloud.computers().isEmpty())
        val stranger = LinkClient(context, elsewhere, nearby = false)
        assertNull("another account must not reach the computer", stranger.connect())
        stranger.close()

        cloud.signOut()
        Cloud.override(context, null)
    }
}
