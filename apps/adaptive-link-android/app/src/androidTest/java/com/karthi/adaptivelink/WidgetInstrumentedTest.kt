package com.karthi.adaptivelink

import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import android.widget.FrameLayout
import android.widget.RemoteViews
import android.widget.TextView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class WidgetInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    @Test fun everyWidgetInflatesWithRemoteViewsAndRendersAtItsMinimumSize() {
        val widgets = listOf(
            Triple(R.layout.widget, 250, 90), Triple(R.layout.widget_status, 180, 90),
            Triple(R.layout.widget_media, 250, 120), Triple(R.layout.widget_controls, 250, 160),
            Triple(R.layout.widget_usage, 250, 220), Triple(R.layout.widget_apps, 250, 150),
        )
        val output = File(context.getExternalFilesDir(null), "widget-previews").apply { mkdirs() }
        instrumentation.runOnMainSync {
            for ((layout, width, height) in widgets) {
                val view = RemoteViews(context.packageName, layout).apply(context, FrameLayout(context))
                val density = context.resources.displayMetrics.density
                val w = (width * density).toInt(); val h = (height * density).toInt()
                view.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(h, View.MeasureSpec.EXACTLY))
                view.layout(0, 0, w, h)
                val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
                view.draw(Canvas(bitmap))
                File(output, context.resources.getResourceEntryName(layout) + ".png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                bitmap.recycle()
            }
        }
    }
    @Test fun offlineUsageWidgetShowsAStateAndWorkingRefreshTargets() = runBlocking {
        val views = UsageWidget().draw(context, null)
        instrumentation.runOnMainSync {
            val view = views.apply(context, FrameLayout(context))
            assertTrue(view.findViewById<TextView>(R.id.usage_state).text.isNotBlank())
            assertTrue(view.findViewById<TextView>(R.id.usage_refresh).hasOnClickListeners())
            assertTrue(view.findViewById<TextView>(R.id.usage_reconnect).hasOnClickListeners())
            assertFalse(view.findViewById<TextView>(R.id.usage_state).text.contains("LIVE"))
        }
    }
    @Test fun savedUsageActuallyPopulatesTheWidgetWithoutNetwork() = runBlocking {
        val isolated = object : android.content.ContextWrapper(context) {
            override fun getApplicationContext(): android.content.Context = this
            override fun getSharedPreferences(name: String, mode: Int) = context.getSharedPreferences("widget-render-$name", mode)
        }
        val computer = Computer("Test laptop", listOf("127.0.0.1"), 47933, 47934, "a".repeat(64))
        Store(isolated).computer = computer
        UsageCache(isolated, computer.fingerprint).save(org.json.JSONObject("""{"ok":true,"codex":{"stale":false,"windows":[{"label":"5h","used":26},{"label":"Weekly","used":63}]},"claude":{"stale":true,"windows":[]},"gemini":{"stale":false,"windows":[{"label":"24h","used":18}]}}"""))
        val views = UsageWidget().draw(isolated, null)
        instrumentation.runOnMainSync {
            val view = views.apply(context, FrameLayout(context))
            assertEquals("26%", view.findViewById<TextView>(R.id.usage_codex_five).text.toString())
            assertEquals("63%", view.findViewById<TextView>(R.id.usage_codex_week).text.toString())
            assertEquals("18%", view.findViewById<TextView>(R.id.usage_gemini_five).text.toString())
            assertEquals("—", view.findViewById<TextView>(R.id.usage_claude_five).text.toString())
            assertTrue(view.findViewById<TextView>(R.id.usage_state).text.startsWith("Saved"))
            val density = context.resources.displayMetrics.density
            val w = (250 * density).toInt(); val h = (220 * density).toInt()
            view.measure(View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(h, View.MeasureSpec.EXACTLY))
            view.layout(0, 0, w, h)
            val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            val output = File(context.getExternalFilesDir(null), "widget-previews").apply { mkdirs() }
            File(output, "widget_usage_populated.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
        }
    }
    @Test fun cacheNeverCrossesComputerBoundariesOrAcceptsErrors() {
        val a = UsageCache(context, "test-widget-a")
        val b = UsageCache(context, "test-widget-b")
        context.getSharedPreferences("usage-test-widget-a", 0).edit().clear().commit()
        context.getSharedPreferences("usage-test-widget-b", 0).edit().clear().commit()
        try {
            a.save(org.json.JSONObject("""{"ok":true,"codex":{},"claude":{},"gemini":{}}"""))
            assertNotNull(a.read()); assertNull(b.read())
            a.save(org.json.JSONObject("""{"error":"offline"}"""))
            assertNotNull(a.read())
        } finally {
            context.getSharedPreferences("usage-test-widget-a", 0).edit().clear().commit()
            context.getSharedPreferences("usage-test-widget-b", 0).edit().clear().commit()
        }
    }
}
