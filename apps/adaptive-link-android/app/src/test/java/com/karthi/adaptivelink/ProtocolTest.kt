package com.karthi.adaptivelink

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
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

    @Test
    fun savedCommandsSurviveBeingStored() {
        val commands = listOf(SavedCommand("Backup", "rsync -a ~/work /mnt/backup", false), SavedCommand("Player", "vlc", true))
        assertEquals(commands, SavedCommand.listFromJson(SavedCommand.listToJson(commands)))
        assertEquals(emptyList<SavedCommand>(), SavedCommand.listFromJson("not json"))
        // One without a name or without a command is not a button.
        assertEquals(1, SavedCommand.listFromJson("""[{"n":" ","c":"ls"},{"n":"ok","c":"ls"},{"n":"x","c":""}]""").size)
        assertEquals(SavedCommand.LIMIT, SavedCommand.listFromJson(SavedCommand.listToJson(List(40) { SavedCommand("n$it", "c", false) })).size)
    }

    @Test
    fun minutesAndProfilesReadAsWords() {
        assertEquals("45 min", Protocol.formatMinutes(45))
        assertEquals("2 h 5 min", Protocol.formatMinutes(125))
        assertEquals("Power saver", Protocol.profileName("power-saver"))
        assertEquals("Quiet mode", Protocol.profileName("quiet-mode"))
    }

    @Test
    fun aSharedPageIsItsAddress() {
        assertEquals("https://example.org/a?b=c", Protocol.sharedAddress("https://example.org/a?b=c"))
        assertEquals("https://example.org/x", Protocol.sharedAddress("A page worth reading\nhttps://example.org/x "))
        assertEquals(null, Protocol.sharedAddress("just some words"))
        assertEquals(null, Protocol.sharedAddress("https://example.org and then more words"))
        assertEquals(null, Protocol.sharedAddress("file:///sdcard/secret"))
        assertEquals(null, Protocol.sharedAddress(""))
    }

    @Test
    fun theWakePacketIsTheAddressSixteenTimes() {
        val packet = Protocol.magicPacket("00:1a:2b:3c:4d:ff")
        assertEquals(102, packet.size)
        assertTrue(packet.take(6).all { it == 0xFF.toByte() })
        val address = listOf(0x00, 0x1a, 0x2b, 0x3c, 0x4d, 0xff).map { it.toByte() }
        assertEquals(List(16) { address }.flatten(), packet.drop(6))
    }

    @Test
    fun whereToWakeTheComputerIsKeptWithIt() {
        val computer = Computer("pc", listOf("192.168.1.5"), 47823, 47824, "ab".repeat(32),
            listOf("00:1a:2b:3c:4d:ff|192.168.1.255"))
        assertEquals(computer, Computer.fromJson(computer.toJson()))
        // One paired before this was known still loads, with nowhere to send the packet.
        val old = """{"n":"pc","h":["192.168.1.5"],"p":47823,"pp":47824,"f":"${"ab".repeat(32)}"}"""
        assertEquals(emptyList<String>(), Computer.fromJson(old)!!.wake)
        assertTrue(Computer.isWake("00:1a:2b:3c:4d:ff|192.168.1.255"))
        assertFalse(Computer.isWake("00:1a:2b:3c:4d:ff|evil.example"))
        assertFalse(Computer.isWake("not-a-mac|192.168.1.255"))
    }

    @Test
    fun onlyATurnServerIsARelay() {
        val relay = Relay("turn:relay.example.org:3478?transport=tcp", "me", "secret")
        assertEquals(relay, Relay.fromJson(relay.toJson()))
        assertNull(Relay.fromJson(null))
        assertNull(Relay.fromJson(""))
        assertNull(Relay.fromJson("""{"url":"https://relay.example.org"}"""))
        assertNull(Relay.fromJson("""{"url":"turn:host and more"}"""))
        assertNull(Relay.fromJson("""{"username":"me"}"""))
    }

    @Test
    fun severalComputersAndTheOneTalkedTo() {
        val a = Computer("a", listOf("10.0.0.1"), 47823, 47824, "aa".repeat(32))
        val b = Computer("b", listOf("10.0.0.2"), 47823, 47824, "bb".repeat(32))
        // The first paired is the one talked to; a second becomes it.
        assertEquals(listOf(a) to a.fingerprint, Computers.after(emptyList(), null, a))
        assertEquals(listOf(a, b) to b.fingerprint, Computers.after(listOf(a), a.fingerprint, b))
        // What is learnt of one that is not being talked to does not change which is.
        val moved = a.copy(hosts = listOf("10.0.0.9"))
        assertEquals(listOf(moved, b) to b.fingerprint, Computers.after(listOf(a, b), b.fingerprint, moved))
        // Forgetting the one talked to moves to another; forgetting the last leaves none.
        assertEquals(listOf(a) to a.fingerprint, Computers.after(listOf(a, b), b.fingerprint, null))
        assertEquals(emptyList<Computer>() to null, Computers.after(listOf(a), a.fingerprint, null))
        assertEquals(listOf(a, b), Computers.fromJson(Computers.toJson(listOf(a, b))))
        assertEquals(b, Computers.current(listOf(a, b), b.fingerprint))
        assertEquals(a, Computers.current(listOf(a, b), "gone"))
        assertNull(Computers.fromJson(null))
    }

    @Test
    fun theOwnersButtons() {
        val controls = listOf(Control("Backup", "command", "rsync -a ~/work /mnt"), Control("Terminal", "keys", "ctrl+alt+t"))
        assertEquals(controls, Control.listFromJson(Control.listToJson(controls)))
        assertEquals(0, Control.listFromJson("""[{"l":"x","k":"format-disk","v":"y"},{"l":"","k":"keys","v":"a"}]""").size)
        assertEquals(Protocol.key("t", "ctrl", "alt"), Protocol.keys("Ctrl+Alt+t"))
        assertEquals(Protocol.key("Return"), Protocol.keys("enter"))
        assertEquals(Protocol.key("F5"), Protocol.keys(" F5 "))
        assertNull(Protocol.keys("ctrl+"))
        assertNull(Protocol.keys("hyper+a"))
        assertNull(Protocol.keys("a; reboot"))
        assertNull(Protocol.keys(""))
    }

    @Test
    fun aStickHoldsTheKeysItIsPushedTowards() {
        assertEquals(emptySet<String>(), Protocol.stickKeys(0.1f, -0.2f, "w", "s", "a", "d"))
        assertEquals(setOf("w"), Protocol.stickKeys(0f, -1f, "w", "s", "a", "d"))
        assertEquals(setOf("s", "d"), Protocol.stickKeys(0.8f, 0.7f, "w", "s", "a", "d"))
        assertEquals(setOf("a"), Protocol.stickKeys(-0.9f, 0.2f, "w", "s", "a", "d"))
    }

    @Test
    fun aSlantedPageComesOutStraight() {
        // Wider at the bottom than the top, as a page photographed from its foot is.
        val corners = listOf(100f to 100f, 900f to 120f, 1000f to 1500f, 0f to 1480f)
        val (width, height) = Protocol.pageSize(corners, 5000)
        assertEquals(1000, width)
        assertTrue(height in 1380..1385)
        val (w, h) = Protocol.pageSize(corners, 700)
        assertTrue(maxOf(w, h) in 699..700 && w < h)
        assertEquals(1 to 1, Protocol.pageSize(listOf(0f to 0f, 0f to 0f, 0f to 0f, 0f to 0f), 100))
    }

    @Test
    fun carryingOnWhereTheComputerLeftOff() {
        assertEquals("https://www.youtube.com/watch?v=abc&t=95s", Protocol.handoffAddress("https://www.youtube.com/watch?v=abc", 95))
        assertEquals("https://www.youtube.com/watch?v=abc&t=95s", Protocol.handoffAddress("https://www.youtube.com/watch?v=abc&t=12s", 95))
        assertEquals("https://example.org/film.mp4", Protocol.handoffAddress("https://example.org/film.mp4", 95))
        assertNull(Protocol.handoffAddress("file:///home/me/film.mkv", 95))
        assertNull(Protocol.handoffAddress("", 0))
    }

    @Test
    fun whatThePhoneSignsToApprove() {
        assertEquals("adaptive-link approve\nsudo\nabcd", String(Protocol.approvalMessage("sudo", "abcd")))
    }

    @Test
    fun whatWaitsForTheComputerIsKeptAsItWas() {
        val items = listOf(JSONObject().put("path", "/v1/open-url").put("body", JSONObject().put("url", "https://example.org")),
            JSONObject().put("file", "/data/outbox/1-photo.jpg").put("name", "photo.jpg"))
        val back = Protocol.outboxFromJson(Protocol.outboxToJson(items))
        assertEquals(2, back.size)
        assertEquals("https://example.org", back[0].getJSONObject("body").getString("url"))
        assertEquals("photo.jpg", back[1].getString("name"))
        // Only something for the link, or a file, is ever kept to be sent.
        assertEquals(0, Protocol.outboxFromJson("""[{"path":"https://elsewhere.example/steal"},{"x":1}]""").size)
        assertEquals(0, Protocol.outboxFromJson("not json").size)
    }
}
