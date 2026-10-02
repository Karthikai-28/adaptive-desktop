package com.karthi.adaptivelink

import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

enum class Page {
    Home, Screen, Trackpad, Media, Presenter, Run, Files, Camera, Tasks, Devices, Network, Desktop,
    Bluetooth, DisplaySound, Services, Windows, More,
}

/** Apple dark appearance with one accent, as on the desktop. */
private val Colors = darkColorScheme(
    primary = Color(0xFF0A84FF),
    onPrimary = Color.White,
    background = Color(0xFF1C1C1E),
    onBackground = Color(0xFFF5F5F7),
    surface = Color(0xFF2C2C2E),
    onSurface = Color(0xFFF5F5F7),
    surfaceVariant = Color(0xFF3A3A3C),
    onSurfaceVariant = Color(0xFF98989D),
    error = Color(0xFFFF453A),
)

class MainActivity : FragmentActivity() {
    /** The app's contents are shown only after the owner has unlocked it. */
    private var unlocked by mutableStateOf(false)
    private var lockMessage by mutableStateOf("")

    /**
     * Set while the app itself has sent the owner somewhere and is waiting
     * for them to come back: the QR scanner, the file picker, Android's
     * notification-access screen. Leaving for one of those is not leaving
     * the app, and must not lock it - locking discards the screen that is
     * waiting for the answer, and with it the code that was just scanned.
     */
    var awayOnPurpose = false
    private var stoppedAt = 0L

    /** While presenting, the volume buttons turn the pages. */
    var volumeKeys: ((up: Boolean) -> Unit)? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // What is on the computer's screen should not end up in the phone's
        // recent-apps thumbnails or in a screenshot taken by another app.
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)

        EventsService.sync(this)

        setContent {
            MaterialTheme(colorScheme = Colors) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    if (unlocked) App(this) else Locked(lockMessage) { unlock() }
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        // Coming back locks the app again if it was really left: not for a
        // screen it opened itself, and not for a glance away of a few seconds.
        val away = System.currentTimeMillis() - stoppedAt
        if (unlocked && stoppedAt != 0L && !awayOnPurpose && away > LOCK_AFTER_MS && Store(this).lockOnOpen)
            unlocked = false
        awayOnPurpose = false
        stoppedAt = 0L
        if (!unlocked) unlock()
    }

    override fun onStop() {
        super.onStop()
        if (!isChangingConfigurations) stoppedAt = System.currentTimeMillis()
    }

    private fun unlock() {
        val store = Store(this)
        if (!store.lockOnOpen) {
            unlocked = true
            return
        }
        // Before Android 11 a prompt cannot ask for the screen lock alone.
        val allowed = BIOMETRIC_WEAK or DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(allowed) != BiometricManager.BIOMETRIC_SUCCESS) {
            // No fingerprint and no screen lock on this phone: there is
            // nothing to ask for. Say so rather than pretend to be locked.
            lockMessage = "This phone has no screen lock. Set one in Settings to protect Adaptive Link."
            unlocked = true
            return
        }
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    lockMessage = ""
                    unlocked = true
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    lockMessage = errString.toString()
                }
            })
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder()
                .setTitle("Adaptive Link")
                .setSubtitle("Unlock to control your computer")
                .setAllowedAuthenticators(allowed)
                .build()
        )
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val handler = volumeKeys
        if (handler != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            handler(keyCode == KeyEvent.KEYCODE_VOLUME_UP)
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (volumeKeys != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN))
            return true
        return super.onKeyUp(keyCode, event)
    }

    companion object {
        /** Away for longer than this, the app asks to be unlocked again. */
        const val LOCK_AFTER_MS = 15_000L
    }

    fun phoneName(): String = "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}"
}

@Composable
private fun Locked(message: String, onUnlock: () -> Unit) {
    Column(
        Modifier.fillMaxSize().systemBarsPadding().padding(32.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Adaptive Link", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            message.ifBlank { "Locked" },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
        Button(onClick = onUnlock) { Text("Unlock") }
    }
}

@Composable
private fun App(activity: MainActivity) {
    val store = remember { Store(activity) }
    var computer by remember { mutableStateOf(store.computer) }
    var page by remember { mutableStateOf(Page.Home) }
    val state = remember { LinkState() }
    // Where the Files screen opens: home, or a drive chosen under Devices.
    var folder by remember { mutableStateOf("~") }

    LaunchedEffect(computer) { LinkWidget.refresh(activity) }

    val paired = computer
    if (paired == null) {
        PairScreen(activity) { computer = store.computer }
        return
    }
    val client = remember(paired) { Link.client(activity)!! }

    BackHandler(enabled = page != Page.Home) { page = Page.Home }

    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        when (page) {
            Page.Home -> HomeScreen(client, state, onOpen = { page = it })
            Page.Screen -> ScreenPage(client, store) { page = Page.Home }
            Page.Trackpad -> TrackpadPage(client) { page = Page.Home }
            Page.Media -> MediaPage(client) { page = Page.Home }
            Page.Presenter -> PresenterPage(activity, client) { page = Page.Home }
            Page.Run -> RunPage(client, store) { page = Page.Home }
            Page.Files -> FilesPage(activity, client, folder) { folder = "~"; page = Page.Home }
            Page.Tasks -> TasksPage(client) { page = Page.Home }
            Page.Devices -> DevicesPage(client, onBack = { page = Page.Home }, onBrowse = { folder = it; page = Page.Files })
            Page.Network -> NetworkPage(client) { page = Page.Home }
            Page.Desktop -> DesktopPage(client) { page = Page.Home }
            Page.Bluetooth -> BluetoothPage(client) { page = Page.Home }
            Page.DisplaySound -> DisplaySoundPage(client) { page = Page.Home }
            Page.Services -> ServicesPage(client) { page = Page.Home }
            Page.Windows -> WindowsPage(client) { page = Page.Home }
            Page.Camera -> CameraPage(activity, client) { page = Page.Home }
            Page.More -> MorePage(activity, client, store, state, onBack = { page = Page.Home }, onUnpaired = {
                computer = null
                page = Page.Home
            })
        }
    }
}
