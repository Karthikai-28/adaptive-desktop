package com.karthi.adaptivelink

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException

class ConnectionRetryTest {
    @Test fun aSecondSessionResolvesTheRouteAgain() = runBlocking {
        val calls = mutableListOf<String>()
        var sessions = 0
        keepConnected(
            wanted = { sessions < 3 },
            connect = { calls.add("route"); true },
            session = { calls.add("session"); sessions++; true },
            pause = {},
        )
        assertEquals(List(3) { listOf("route", "session") }.flatten(), calls)
    }

    @Test fun outagesAndExceptionsRetryAndSuccessResetsTheDelay() = runBlocking {
        var attempts = 0
        var sessions = 0
        val waits = mutableListOf<Long>()
        keepConnected(
            wanted = { attempts < 7 },
            connect = {
                attempts++
                when (attempts) {
                    1 -> throw IOException("network unavailable")
                    2, 3, 4 -> false
                    else -> true
                }
            },
            session = {
                sessions++
                if (sessions == 1) throw IOException("socket setup failed")
                true
            },
            pause = { waits.add(it) },
        )
        assertEquals(3, sessions)
        assertEquals(listOf(3000L, 6000L, 12000L, 15000L, 15000L, 3000L, 3000L), waits)
    }

    @Test fun stoppingTheServiceDoesNotRetry() = runBlocking {
        for (cancelInSession in listOf(false, true)) {
            var waits = 0
            try {
                keepConnected(
                    wanted = { true },
                    connect = { if (!cancelInSession) throw CancellationException(); true },
                    session = { throw CancellationException() },
                    pause = { waits++ },
                )
                fail("Cancellation must propagate")
            } catch (_: CancellationException) {
                assertEquals(0, waits)
            }
        }
    }
}
