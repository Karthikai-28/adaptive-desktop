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

    @Test fun sizesAndDurationsReadNaturally() {
        assertEquals("912 B", Protocol.formatSize(912))
        assertEquals("340 KB", Protocol.formatSize(348160))
        assertEquals("1.5 GB", Protocol.formatSize(1610612736))
        assertEquals("1:05", Protocol.formatDuration(65))
        assertEquals("1:01:01", Protocol.formatDuration(3661))
    }
}
