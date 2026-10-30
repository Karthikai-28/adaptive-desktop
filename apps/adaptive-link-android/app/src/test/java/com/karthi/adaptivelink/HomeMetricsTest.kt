package com.karthi.adaptivelink

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeMetricsTest {
    @Test fun columnsFollowTheScreen() {
        assertEquals(4, HomeMetrics.columns(320))
        assertEquals(4, HomeMetrics.columns(360))
        assertEquals(5, HomeMetrics.columns(393))
        assertEquals(5, HomeMetrics.columns(412))
        assertEquals(6, HomeMetrics.columns(480))
        assertEquals(8, HomeMetrics.columns(600))
        assertEquals(8, HomeMetrics.columns(1280))
    }

    @Test fun largeTextGetsWiderCells() {
        assertEquals(4, HomeMetrics.columns(393, 1.3f))
        assertEquals(4, HomeMetrics.columns(360, 2f))
        assertEquals(3, HomeMetrics.columns(320, 1.3f))
        assertEquals(5, HomeMetrics.columns(393, .85f))
    }

    @Test fun everyCellHasRoomForItsTile() {
        for (width in 320..1280) {
            val cell = (width - 2 * HomeMetrics.GUTTER) / HomeMetrics.columns(width)
            assertTrue("$width dp", cell >= HomeMetrics.TILE)
        }
    }

    @Test fun theDockNeverOverflowsAndStaysTappable() {
        for (width in 320..1280) for (count in 1..6) {
            val tile = HomeMetrics.dockTile(width, count)
            val used = count * tile + (count - 1) * HomeMetrics.DOCK_GAP + 2 * HomeMetrics.DOCK_PADDING + 2 * HomeMetrics.DOCK_MARGIN
            assertTrue("$count apps at $width dp take $used dp", used <= width)
            assertTrue("$count apps at $width dp are $tile dp", tile + HomeMetrics.DOCK_GAP >= 48)
            assertTrue(tile <= HomeMetrics.DOCK_TILE)
        }
    }

    @Test fun visibleBoundsIgnoreClearAndFaintEdges() {
        val clear = 0x00FFFFFF
        val faint = 0x10FFFFFF
        val solid = 0xFF102030.toInt()
        val pixels = intArrayOf(
            clear, clear, clear, clear,
            clear, solid, solid, faint,
            clear, clear, solid, clear,
        )
        assertArrayEquals(intArrayOf(1, 1, 3, 3), HomeMetrics.visibleBounds(pixels, 4, 3))
        assertNull(HomeMetrics.visibleBounds(IntArray(4) { clear }, 2, 2))
    }
}
