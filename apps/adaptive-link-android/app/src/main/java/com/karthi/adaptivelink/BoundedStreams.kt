package com.karthi.adaptivelink

import java.io.InputStream
import java.io.ByteArrayOutputStream

/** Android 10-compatible bounded reads; callers request limit + 1 to detect oversized input. */
internal fun InputStream.readBounded(limit: Int): ByteArray {
    require(limit >= 0)
    val output = ByteArrayOutputStream(minOf(limit, 8192))
    val buffer = ByteArray(minOf(limit, 8192))
    while (output.size() < limit) {
        val count = read(buffer, 0, minOf(buffer.size, limit - output.size()))
        if (count < 0) break
        if (count == 0) { val one = read(); if (one < 0) break; output.write(one) }
        else output.write(buffer, 0, count)
    }
    return output.toByteArray()
}
