package com.karthi.adaptivelink

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.pdf.PdfDocument
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

/**
 * Paper, photographed and straightened, sent to the computer as a PDF - into
 * the Scans folder of the project that is active there. And the phone's
 * microphone, as a microphone on the computer.
 */

// ------------------------------------------------------------------- pages

/** A photograph's corner-marked page, pulled straight: what was a slanted quadrilateral becomes a rectangle. */
fun straighten(shot: Bitmap, corners: List<Offset>, grey: Boolean): Bitmap {
    // The corners are fractions of the picture: top-left, top-right, bottom-right, bottom-left.
    val points = corners.map { Offset(it.x * shot.width, it.y * shot.height) }
    val (width, height) = Protocol.pageSize(points.map { it.x to it.y }, 1654)
    val from = floatArrayOf(points[0].x, points[0].y, points[1].x, points[1].y, points[2].x, points[2].y, points[3].x, points[3].y)
    val to = floatArrayOf(0f, 0f, width.toFloat(), 0f, width.toFloat(), height.toFloat(), 0f, height.toFloat())
    val matrix = Matrix().apply { setPolyToPoly(from, 0, to, 0, 4) }
    val page = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
    if (grey) {
        // No colour, and more contrast: ink darker, paper lighter.
        val contrast = 1.35f
        val shift = (-0.5f * contrast + 0.5f) * 255f
        val colours = ColorMatrix().apply { setSaturation(0f) }
        colours.postConcat(ColorMatrix(floatArrayOf(
            contrast, 0f, 0f, 0f, shift, 0f, contrast, 0f, 0f, shift, 0f, 0f, contrast, 0f, shift, 0f, 0f, 0f, 1f, 0f)))
        paint.colorFilter = ColorMatrixColorFilter(colours)
    }
    Canvas(page).apply { drawColor(android.graphics.Color.WHITE); drawBitmap(shot, matrix, paint) }
    return page
}

/** The pages as one PDF, in the app's own scratch space. */
fun pdfOf(context: Context, pages: List<Bitmap>): File {
    val document = PdfDocument()
    pages.forEachIndexed { index, page ->
        // A4 across at 72 points to the inch; as tall as the page's own shape makes it.
        val width = 595
        val height = (width.toFloat() * page.height / page.width).toInt().coerceAtLeast(1)
        val sheet = document.startPage(PdfDocument.PageInfo.Builder(width, height, index + 1).create())
        sheet.canvas.drawBitmap(page, null, android.graphics.Rect(0, 0, width, height), Paint(Paint.FILTER_BITMAP_FLAG))
        document.finishPage(sheet)
    }
    val file = File(context.cacheDir, "scan.pdf")
    file.outputStream().use { document.writeTo(it) }
    document.close()
    return file
}

@Composable
fun ScanPage(activity: MainActivity, client: LinkClient, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) {
        if (!granted) {
            activity.awayOnPurpose = true
            permission.launch(Manifest.permission.CAMERA)
        }
    }
    var shot by remember { mutableStateOf<Bitmap?>(null) }
    var corners by remember { mutableStateOf(START_CORNERS) }
    var pages by remember { mutableStateOf(listOf<Bitmap>()) }
    var grey by remember { mutableStateOf(true) }
    var said by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val capture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY).build() }

    Column(Modifier.fillMaxSize()) {
        TopBar(if (pages.isEmpty()) "Scan" else "Scan · ${pages.size} page${if (pages.size == 1) "" else "s"}", onBack)
        Column(Modifier.fillMaxSize().padding(14.dp)) {
            if (!granted) {
                Muted("Adaptive Link needs the camera permission to photograph a page.")
                return@Column
            }
            if (said.isNotEmpty()) Muted(said, Modifier.padding(bottom = 6.dp))
            val taken = shot
            if (taken == null) {
                val preview = remember { PreviewView(activity) }
                AndroidView(factory = { preview }, modifier = Modifier.fillMaxWidth().weight(1f))
                DisposableEffect(Unit) {
                    val future = ProcessCameraProvider.getInstance(activity)
                    var cameras: ProcessCameraProvider? = null
                    future.addListener({
                        cameras = future.get()
                        val view = Preview.Builder().build().also { it.setSurfaceProvider(preview.surfaceProvider) }
                        runCatching {
                            cameras?.unbindAll()
                            cameras?.bindToLifecycle(activity, CameraSelector.DEFAULT_BACK_CAMERA, view, capture)
                        }.onFailure { said = "This phone's camera could not be opened" }
                    }, ContextCompat.getMainExecutor(activity))
                    onDispose { cameras?.unbindAll() }
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Button(enabled = !busy, onClick = {
                        busy = true
                        capture.takePicture(ContextCompat.getMainExecutor(activity), object : ImageCapture.OnImageCapturedCallback() {
                            override fun onCaptureSuccess(image: ImageProxy) {
                                val turned = Matrix().apply { postRotate(image.imageInfo.rotationDegrees.toFloat()) }
                                val picture = image.toBitmap()
                                shot = Bitmap.createBitmap(picture, 0, 0, picture.width, picture.height, turned, true)
                                image.close()
                                corners = START_CORNERS
                                busy = false
                                said = ""
                            }

                            override fun onError(exception: ImageCaptureException) {
                                said = "The picture could not be taken"
                                busy = false
                            }
                        })
                    }) { Text(if (pages.isEmpty()) "Photograph the page" else "Photograph another page") }
                    if (pages.isNotEmpty()) OutlinedButton(enabled = !busy, onClick = {
                        busy = true
                        said = "Sending…"
                        scope.launch {
                            val name = "Scan ${SimpleDateFormat("yyyy-MM-dd HH.mm", Locale.US).format(Date())}.pdf"
                            val reply = withContext(Dispatchers.IO) {
                                val file = pdfOf(activity, pages)
                                client.upload(name, file.asRequestBody("application/pdf".toMediaType()), "scans").also { file.delete() }
                            }
                            said = if (reply?.optBoolean("ok") == true) "On the computer: ${reply.optString("path")}"
                            else reply?.optString("error")?.ifBlank { null } ?: "The computer did not take it"
                            if (reply?.optBoolean("ok") == true) pages = emptyList()
                            busy = false
                        }
                    }) { Text("Send as PDF") }
                }
            } else {
                Muted("Drag the corners onto the corners of the page.")
                Spacer(Modifier.height(6.dp))
                CornerPicker(taken, corners, Modifier.fillMaxWidth().weight(1f)) { corners = it }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = {
                        pages = pages + straighten(taken, corners, grey)
                        shot = null
                    }) { Text("Use this page") }
                    OutlinedButton(onClick = { shot = null }) { Text("Take it again") }
                    FilterChip(selected = grey, onClick = { grey = !grey }, label = { Text("Black and white") })
                }
            }
        }
    }
}

private val START_CORNERS = listOf(Offset(0.08f, 0.08f), Offset(0.92f, 0.08f), Offset(0.92f, 0.92f), Offset(0.08f, 0.92f))

/** The photograph, with four corners to drag onto the page's own. */
@Composable
private fun CornerPicker(picture: Bitmap, corners: List<Offset>, modifier: Modifier, onChange: (List<Offset>) -> Unit) {
    var box by remember { mutableStateOf(IntSize.Zero) }
    // Where the picture lies in the box it is fitted into.
    fun frame(): Pair<Offset, Offset> {
        val scale = minOf(box.width / picture.width.toFloat(), box.height / picture.height.toFloat())
        val size = Offset(picture.width * scale, picture.height * scale)
        return Offset((box.width - size.x) / 2, (box.height - size.y) / 2) to size
    }
    Box(modifier.background(Color.Black).onSizeChanged { box = it }.pointerInput(picture) {
        var moving = -1
        detectDragGestures(
            onDragStart = { at ->
                val (origin, size) = frame()
                // The corner nearest the finger is the one that moves.
                moving = corners.indices.minByOrNull { index ->
                    (Offset(origin.x + corners[index].x * size.x, origin.y + corners[index].y * size.y) - at).getDistance()
                } ?: -1
            },
        ) { change, _ ->
            val (origin, size) = frame()
            if (moving >= 0 && size.x > 0 && size.y > 0) {
                val to = Offset(((change.position.x - origin.x) / size.x).coerceIn(0f, 1f),
                    ((change.position.y - origin.y) / size.y).coerceIn(0f, 1f))
                onChange(corners.mapIndexed { index, corner -> if (index == moving) to else corner })
            }
        }
    }) {
        Image(picture.asImageBitmap(), "The photograph", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        val line = MaterialTheme.colorScheme.primary
        Canvas(Modifier.fillMaxSize()) {
            if (box == IntSize.Zero) return@Canvas
            val (origin, size) = frame()
            val points = corners.map { Offset(origin.x + it.x * size.x, origin.y + it.y * size.y) }
            drawPath(Path().apply {
                moveTo(points[0].x, points[0].y)
                points.drop(1).forEach { lineTo(it.x, it.y) }
                close()
            }, line, style = Stroke(width = 4f))
            points.forEach { drawCircle(line, radius = 22f, center = it) }
        }
    }
}

// -------------------------------------------------------------- microphone

/**
 * This phone's microphone, sent to the computer as it is heard: 16 kHz, one
 * channel. The computer makes a microphone of it that its apps can choose
 * (services/adaptive-link/companion.py).
 */
class MicStreamer(private val client: LinkClient, private val onState: (String) -> Unit) {
    @Volatile private var running = false
    private var socket: WebSocket? = null

    @Suppress("MissingPermission")   // asked for by the screen that starts this
    fun start() {
        if (running) return
        running = true
        val opened = client.socket("/v1/mic", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = onState("Live on the computer as “Phone Microphone”")
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                running = false
                onState(when (response?.code) {
                    503 -> "The computer has no sound server to give the microphone to"
                    403 -> "The computer is view-only"
                    else -> "Connection lost"
                })
            }
        })
        socket = opened
        thread(name = "link-mic", isDaemon = true) {
            val size = maxOf(AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT), 4096)
            val recorder = runCatching {
                AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, size)
            }.getOrNull()
            if (recorder == null || recorder.state != AudioRecord.STATE_INITIALIZED) {
                onState("This phone's microphone could not be opened")
                running = false
                opened.close(1000, null)
                return@thread
            }
            val chunk = ByteArray(RATE / 25 * 2)   // 40 ms
            recorder.startRecording()
            try {
                while (running) {
                    val read = recorder.read(chunk, 0, chunk.size)
                    // Behind by more than a second: the link is the bottleneck, so this piece is dropped.
                    if (read > 0 && opened.queueSize() < RATE * 2) opened.send(chunk.toByteString(0, read - read % 2))
                }
            } finally {
                runCatching { recorder.stop() }
                recorder.release()
            }
        }
    }

    fun stop() {
        running = false
        socket?.close(1000, null)
        socket = null
    }

    private companion object {
        const val RATE = 16000
    }
}
