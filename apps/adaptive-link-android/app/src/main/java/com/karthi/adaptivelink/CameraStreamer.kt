package com.karthi.adaptivelink

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

/**
 * This phone's camera, sent to the computer as a webcam.
 *
 * Each frame is turned upright, compressed to JPEG and sent on a socket; the
 * computer feeds them to its virtual camera (services/adaptive-link/camera.py).
 * If the connection is busy the frame is dropped rather than queued, so the
 * picture stays live instead of falling behind.
 */
class CameraStreamer(
    private val context: Context,
    private val client: LinkClient,
    private val onState: (String) -> Unit,
) {
    private val executor = Executors.newSingleThreadExecutor()
    private var socket: WebSocket? = null
    private var provider: ProcessCameraProvider? = null

    fun start(owner: LifecycleOwner, preview: PreviewView, front: Boolean) {
        val opened = client.socket("/v1/camera", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = onState("Live on the computer as “Phone Camera”")
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                onState(
                    if (response?.code == 503) "The virtual camera is not installed on the computer"
                    else "Connection lost"
                )
            }
        })
        socket = opened

        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val cameras = future.get()
            provider = cameras
            val view = Preview.Builder().build().also { it.setSurfaceProvider(preview.surfaceProvider) }
            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            analysis.setAnalyzer(executor) { image ->
                try {
                    // Up to about one megabyte waiting to go: more than that
                    // and the link is the bottleneck, so skip this frame.
                    if (opened.queueSize() < 1_000_000) {
                        val upright = rotate(image.toBitmap(), image.imageInfo.rotationDegrees, front)
                        val scaled = fit(upright, 1280)
                        val out = ByteArrayOutputStream()
                        scaled.compress(Bitmap.CompressFormat.JPEG, 70, out)
                        opened.send(out.toByteArray().toByteString())
                    }
                } finally {
                    image.close()
                }
            }
            val selector = if (front) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA
            cameras.unbindAll()
            runCatching { cameras.bindToLifecycle(owner, selector, view, analysis) }
                .onFailure { onState("This phone's camera could not be opened") }
        }, ContextCompat.getMainExecutor(context))
    }

    fun stop() {
        provider?.unbindAll()
        provider = null
        socket?.close(1000, null)
        socket = null
    }

    private fun rotate(bitmap: Bitmap, degrees: Int, mirror: Boolean): Bitmap {
        if (degrees == 0 && !mirror) return bitmap
        val matrix = Matrix().apply {
            postRotate(degrees.toFloat())
            // A front camera is seen mirrored on the phone; the computer
            // should get the unmirrored picture others would see.
        }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }

    private fun fit(bitmap: Bitmap, longest: Int): Bitmap {
        val scale = longest.toFloat() / maxOf(bitmap.width, bitmap.height)
        if (scale >= 1f) return bitmap
        return Bitmap.createScaledBitmap(
            bitmap, (bitmap.width * scale).toInt(), (bitmap.height * scale).toInt(), true
        )
    }
}
