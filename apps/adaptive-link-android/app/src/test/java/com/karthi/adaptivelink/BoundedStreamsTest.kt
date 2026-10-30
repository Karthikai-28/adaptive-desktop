package com.karthi.adaptivelink
import org.junit.Assert.*
import org.junit.Test
class BoundedStreamsTest {
    @Test fun detectsOversizeWithoutReadingWholeInput() {
        val stream = ByteArray(20000) { (it % 251).toByte() }.inputStream()
        assertEquals(8193, stream.readBounded(8193).size)
        assertEquals(20000 - 8193, stream.available())
    }
    @Test fun handlesEmptyShortAndZeroLimits() {
        assertArrayEquals(byteArrayOf(), byteArrayOf().inputStream().readBounded(10))
        assertArrayEquals(byteArrayOf(1, 2), byteArrayOf(1, 2).inputStream().readBounded(8))
        val stream = byteArrayOf(1).inputStream()
        assertEquals(0, stream.readBounded(0).size)
        assertEquals(1, stream.available())
    }
}
