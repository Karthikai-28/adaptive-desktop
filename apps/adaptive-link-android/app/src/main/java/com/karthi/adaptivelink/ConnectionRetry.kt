package com.karthi.adaptivelink

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive

internal fun nextListenWait(current: Long) = (current * 2).coerceAtMost(15_000L)

/** Revalidate the route after every ended session, including graceful closes. */
internal suspend fun keepConnected(
    wanted: () -> Boolean,
    connect: suspend () -> Boolean,
    session: suspend () -> Boolean,
    pause: suspend (Long) -> Unit = { delay(it) },
) {
    var wait = 3_000L
    while (wanted()) {
        currentCoroutineContext().ensureActive()
        try {
            if (connect() && session()) wait = 3_000L
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // A failed attempt must not kill the standing listener.
        }
        pause(wait)
        wait = nextListenWait(wait)
    }
}
