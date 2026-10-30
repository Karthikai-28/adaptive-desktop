package com.karthi.adaptivelink

import android.app.Notification
import android.os.UserHandle
import android.provider.Settings
import android.service.notification.StatusBarNotification
import android.view.View
import android.view.ViewGroup
import android.view.inspector.WindowInspector
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class IslandInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private fun main(block: () -> Unit) = instrumentation.runOnMainSync(block)
    private fun texts(view: View): List<String> = (if (view is TextView) listOf(view.text.toString()) else emptyList()) +
        if (view is ViewGroup) (0 until view.childCount).flatMap { texts(view.getChildAt(it)) } else emptyList()

    @Test fun overlayRespectsSwitchPrivacyRemovalAndCleanup() {
        assumeTrue("Enable overlay permission on the test emulator", Settings.canDrawOverlays(context))
        val keyguard = context.getSystemService(android.app.KeyguardManager::class.java)
        val deadline = System.currentTimeMillis() + 10000
        while (keyguard.isDeviceLocked && System.currentTimeMillis() < deadline) Thread.sleep(100)
        assertFalse("Test emulator must finish unlocking before overlays can be visible", keyguard.isDeviceLocked)
        assertTrue(context.getSystemService(android.os.PowerManager::class.java).isInteractive)
        val prefs = IslandPreferences(context)
        val enabled = prefs.enabled
        val previews = prefs.previews
        var island: IslandOverlay? = null
        val notification = Notification.Builder(context, "island-test").setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Private test title").setContentText("Private test body").build()
        val sbn = StatusBarNotification("android", "android", 42, "island-test", 1000, 0, 0, notification,
            android.os.Process.myUserHandle(), System.currentTimeMillis())
        try {
            main { prefs.enabled = false; prefs.previews = false; island = IslandOverlay(context); island!!.posted(sbn) }
            instrumentation.waitForIdleSync()
            main { assertFalse(WindowInspector.getGlobalWindowViews().flatMap(::texts).any { it.contains("●") }) }
            main { prefs.enabled = true; island!!.posted(sbn) }
            instrumentation.waitForIdleSync()
            main {
                val root = WindowInspector.getGlobalWindowViews().first { texts(it).any { text -> text.contains("●") } }
                assertFalse(texts(root).contains("Private test title"))
                fun expand(v: View): Boolean {
                    if (v is TextView && v.text.contains("●")) return v.performClick()
                    if (v is ViewGroup) for (i in 0 until v.childCount) if (expand(v.getChildAt(i))) return true
                    return false
                }
                assertTrue(expand(root))
                assertFalse(texts(root).any { it.contains("Private test body") })
            }
            main { prefs.previews = true }
            instrumentation.waitForIdleSync()
            main { assertTrue(WindowInspector.getGlobalWindowViews().flatMap(::texts).any { it.contains("Private test body") }) }
            main { island!!.removed(sbn.key) }
            instrumentation.waitForIdleSync()
            main { assertFalse(WindowInspector.getGlobalWindowViews().flatMap(::texts).any { it.contains("Private test body") }) }
            main { island!!.posted(sbn) }
            instrumentation.waitForIdleSync()
            main { prefs.enabled = false }
            instrumentation.waitForIdleSync()
            main { assertFalse(WindowInspector.getGlobalWindowViews().flatMap(::texts).any { it.contains("●") }) }
        } finally {
            main { island?.close(); prefs.enabled = enabled; prefs.previews = previews }
        }
    }
}
