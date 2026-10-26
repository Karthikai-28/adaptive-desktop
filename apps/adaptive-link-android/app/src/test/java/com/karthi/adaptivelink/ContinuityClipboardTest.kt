package com.karthi.adaptivelink

import java.io.File
import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

class ContinuityClipboardTest {
    @Test fun navigationHistorySerializesAndPopsPredictably() {
        var stack = ShellRoutes.push("home", "drawer")
        stack = ShellRoutes.push(stack, "native")
        assertEquals("home|drawer|native", stack)
        assertEquals("home|drawer" to "drawer", ShellRoutes.pop(stack))
        assertEquals("home" to "home", ShellRoutes.pop("home"))
        assertEquals("home|continue", ShellRoutes.normalize("bad|home|continue|unknown"))
    }

    @Test fun reconnectDescriptorUsesStableWindowIdentityOnly() {
        val saved = ContinuityDescriptor("ab".repeat(32), "firefox.desktop", 91, "phone-display")
        val restored = ContinuityDescriptor.parse(saved.json())
        assertEquals(saved, restored)
        assertTrue(restored!!.matches("ab".repeat(32), "firefox.desktop", 91))
        assertFalse(restored.matches("ab".repeat(32), "firefox.desktop", 92))
        assertNull(ContinuityDescriptor.parse("{}"))
    }

    @Test fun clipboardLimitsHashesAndSensitiveFlagsAreDeterministic() {
        assertTrue(ClipboardSync.validText("copied"))
        assertFalse(ClipboardSync.validText("x".repeat(ClipboardSync.TEXT_MAX + 1)))
        assertTrue(ClipboardSync.validImageMetadata("image/png", 1024, 4000, 3000))
        assertFalse(ClipboardSync.validImageMetadata("image/gif", 1024, 1, 1))
        assertFalse(ClipboardSync.validImageMetadata("image/jpeg", ClipboardSync.IMAGE_MAX + 1L, 1, 1))
        assertFalse(ClipboardSync.validImageMetadata("image/png", 1024, 10000, 10000))
        assertEquals("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            ClipboardSync.hash("hello".toByteArray()))
        assertTrue(ClipboardSync.sensitiveFlags { it.endsWith("IS_SENSITIVE") })
        assertFalse(ClipboardSync.sensitiveFlags { false })
    }

    @Test fun clipboardCacheKeepsFiveRecentItemsAndFortyMegabytes() {
        val folder = Files.createTempDirectory("clipboard-test").toFile()
        try {
            repeat(7) { index ->
                File(folder, "$index.png").writeBytes(ByteArray(10))
                File(folder, "$index.png").setLastModified(1_000L + index)
            }
            ClipboardSync.clean(folder, 2_000L)
            assertEquals(listOf("2.png", "3.png", "4.png", "5.png", "6.png"), folder.listFiles()!!.map { it.name }.sorted())
        } finally {
            folder.deleteRecursively()
        }
    }

    @Test fun clipboardV2MigrationEnablesOnceAndThenHonorsOptOut() {
        assertEquals(true to 2, clipboardPolicy(0, false))
        assertEquals(false to 2, clipboardPolicy(2, false))
        assertEquals(true to 2, clipboardPolicy(2, true))
    }
}
