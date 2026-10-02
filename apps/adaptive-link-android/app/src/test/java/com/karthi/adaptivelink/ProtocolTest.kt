package com.karthi.adaptivelink

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The phone and the computer must compute the same things from the same
 * inputs. The expected values here were produced by the computer's code
 * (services/adaptive-link/identity.py).
 */
class ProtocolTest {
    private val a = "a".repeat(64)
    private val b = "b".repeat(64)

    @Test fun pairingCodeMatchesTheComputer() {
        assertEquals("131063", Protocol.pairingCode(a, b))
    }

    @Test fun fingerprintMatchesTheComputer() {
        assertEquals("4bc3f07393f7bc8e0d2b6a40b27695dcff105a082c93683ae5fc07e5af016be7", Protocol.fingerprint("adaptive".toByteArray()))
    }

    @Test fun aDifferentCertificateGivesDifferentDigits() {
        assert(Protocol.pairingCode(a, b) != Protocol.pairingCode(a, "c".repeat(64)))
    }

    private fun offer(change: JSONObject.() -> Unit = {}): String = JSONObject()
        .put("v", 1).put("n", "laptop").put("h", org.json.JSONArray(listOf("192.168.1.5", "100.101.102.103")))
        .put("p", 47823).put("pp", 47824).put("f", a).put("t", "t".repeat(43)).apply(change).toString()

    @Test fun aPairingCodeIsRead() {
        val parsed = PairingOffer.parse(offer())
        assertNotNull(parsed)
        assertEquals(listOf("192.168.1.5", "100.101.102.103"), parsed!!.computer.hosts)
        assertEquals(47823, parsed.computer.port)
        assertEquals(a, parsed.computer.fingerprint)
    }

    @Test fun theTextFormIsReadToo() {
        val text = PairingOffer.TEXT_PREFIX +
            java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(offer().toByteArray())
        assertEquals(PairingOffer.parse(offer()), PairingOffer.parse("  $text\n"))
        assertNull(PairingOffer.parse(PairingOffer.TEXT_PREFIX + "not base64 !!"))
    }

    @Test fun anythingElseIsRefused() {
        assertNull(PairingOffer.parse("https://example.com/"))
        assertNull(PairingOffer.parse(offer { put("v", 2) }))
        assertNull(PairingOffer.parse(offer { put("f", "not-a-fingerprint") }))
        assertNull(PairingOffer.parse(offer { put("p", 80) }))
        assertNull(PairingOffer.parse(offer { put("t", "short") }))
        assertNull(PairingOffer.parse(offer { put("h", org.json.JSONArray(listOf("evil.example/path?x="))) }))
        assertNull(PairingOffer.parse(offer { put("h", org.json.JSONArray()) }))
    }

    @Test fun theComputerIsRememberedAndReadBack() {
        val computer = PairingOffer.parse(offer())!!.computer
        assertEquals(computer, Computer.fromJson(computer.toJson()))
    }

    @Test fun inputEventsAreWhatTheComputerExpects() {
        assertEquals("move", JSONObject(Protocol.move(0.5f, 0.25f)).getString("t"))
        assertEquals(0.25, JSONObject(Protocol.move(0.5f, 0.25f)).getDouble("y"), 1e-6)
        val key = JSONObject(Protocol.key("Right", "ctrl", "shift"))
        assertEquals("Right", key.getString("k"))
        assertEquals(2, key.getJSONArray("m").length())
        assertEquals("hello", JSONObject(Protocol.text("hello")).getString("s"))
    }

    @Test fun aDeviceIsNamedByTheStartOfItsFingerprint() {
        val fingerprint = "ab".repeat(32)
        assertEquals(20, Cloud.deviceId(fingerprint).length)
        assert(fingerprint.startsWith(Cloud.deviceId(fingerprint)))
    }

    @Test fun sizesAndDurationsReadNaturally() {
        assertEquals("912 B", Protocol.formatSize(912))
        assertEquals("340 KB", Protocol.formatSize(348160))
        assertEquals("1.5 GB", Protocol.formatSize(1610612736))
        assertEquals("1:05", Protocol.formatDuration(65))
        assertEquals("1:01:01", Protocol.formatDuration(3661))
    }

    @Test fun aSpeedIsWorkedOutFromTwoReadings() {
        assertEquals("1.0 MB/s", Protocol.formatRate(1000, 1000 + (2L shl 20), 2.0))
        assertEquals("512 B/s", Protocol.formatRate(0, 1024, 2.0))
        // A counter that went back (the interface was reset) is not a speed.
        assertEquals("0 B/s", Protocol.formatRate(5000, 100, 2.0))
        assertEquals("0 B/s", Protocol.formatRate(0, 100, 0.0))
    }

    @Test fun aTouchOnTheZoomedPictureLandsWhereItLooks() {
        val box = androidx.compose.ui.unit.IntSize(1000, 2000)
        fun point(x: Float, y: Float) = androidx.compose.ui.geometry.Offset(x, y)
        // Pinched to twice the size about a point: that point stays under the fingers.
        val held = point(250f, 600f)
        val (zoom, shift) = zoomed(1f, point(0f, 0f), box, 2f, held, point(0f, 0f))
        assertEquals(2f, zoom, 1e-4f)
        val back = unzoomed(held, box, zoom, shift)
        assertEquals(250f, back.x, 0.5f)
        assertEquals(600f, back.y, 0.5f)
        // Pinched back out, the picture is whole and in place again.
        val (out, home) = zoomed(zoom, shift, box, 0.4f, held, point(0f, 0f))
        assertEquals(1f, out, 1e-4f)
        assertEquals(0f, home.x, 1e-4f)
        // And it cannot be dragged off the screen.
        val (_, far) = zoomed(2f, point(0f, 0f), box, 1f, point(500f, 1000f), point(9000f, -9000f))
        assertEquals(500f, far.x, 0.5f)
        assertEquals(-1000f, far.y, 0.5f)
    }
}
