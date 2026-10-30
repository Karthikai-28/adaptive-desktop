package com.karthi.adaptivelink

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

@Composable
internal fun LinkActivityIsland(online: Boolean, busy: Boolean, count: Int, computer: String, note: String,
                                onOpen: () -> Unit, onSettings: () -> Unit, onRefresh: () -> Unit, onReconnect: () -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Surface(shape = RoundedCornerShape(28.dp), color = Color(0xFF080809),
        border = androidx.compose.foundation.BorderStroke(.5.dp, Color(0xFF333336)),
        modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp).fillMaxWidth().animateContentSize()) {
        Column {
            Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable { expanded = !expanded }.padding(horizontal = 18.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(if (online) Icons.Default.Link else Icons.Default.LinkOff, null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(12.dp))
                Text(if (busy) "Working…" else if (!online) "Reconnecting" else if (count > 0) "$count apps running" else computer,
                    Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                if (busy) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                else Icon(if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore, if (expanded) "Collapse activity" else "Expand activity", Modifier.size(20.dp))
            }
            AnimatedVisibility(expanded) {
                Column(Modifier.padding(start = 18.dp, end = 18.dp, bottom = 12.dp)) {
                    Text(note.ifBlank { if (online) "Your computer is ready." else "Waiting for your computer." }, style = MaterialTheme.typography.bodySmall)
                    Row {
                        TextButton(onClick = onRefresh) { Text("Refresh") }
                        TextButton(onClick = onReconnect) { Text("Reconnect") }
                    }
                    Row {
                        TextButton(onClick = onOpen) { Text("Running apps") }
                        TextButton(onClick = onSettings) { Text("Island settings") }
                    }
                }
            }
        }
    }
}

@Composable
internal fun IslandSettings(activity: MainActivity, onBack: () -> Unit) {
    val prefs = remember { IslandPreferences(activity) }
    var enabled by remember { mutableStateOf(prefs.enabled) }
    var offset by remember { mutableFloatStateOf(prefs.offset.toFloat()) }
    var previews by remember { mutableStateOf(prefs.previews) }
    var overlay by remember { mutableStateOf(Settings.canDrawOverlays(activity)) }
    var access by remember { mutableStateOf(androidx.core.app.NotificationManagerCompat.getEnabledListenerPackages(activity).contains(activity.packageName)) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) {
            overlay = Settings.canDrawOverlays(activity)
            access = androidx.core.app.NotificationManagerCompat.getEnabledListenerPackages(activity).contains(activity.packageName)
        } }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        TopBar("Dynamic Island", onBack)
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            Box(Modifier.fillMaxWidth().height(112.dp).background(Color(0xFF1C1C1E), RoundedCornerShape(28.dp)), contentAlignment = Alignment.Center) {
                Surface(shape = RoundedCornerShape(50), color = Color.Black) {
                    Row(Modifier.padding(horizontal = 28.dp, vertical = 18.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.GraphicEq, null, tint = Color(0xFF0A84FF))
                        Spacer(Modifier.width(24.dp)); Text("Made to stay with you", fontSize = 13.sp)
                    }
                }
            }
            Text("A little space. A lot happening.", style = MaterialTheme.typography.headlineSmall)
            Muted("Music, new notifications and charging, above your other apps. Tap to expand. Long press to hide until the next activity. Hidden while your phone is locked.")
            Card(Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Dynamic Island", Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                    Switch(enabled, { enabled = it; prefs.enabled = it })
                }
            }
            Card(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Set up on this phone", style = MaterialTheme.typography.titleMedium)
                    TextButton(onClick = {
                        activity.awayOnPurpose = true
                        activity.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${activity.packageName}")))
                    }) { Text(if (overlay) "✓ Display over other apps allowed" else "Allow display over other apps") }
                    TextButton(onClick = {
                        activity.awayOnPurpose = true
                        activity.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                    }) { Text(if (access) "✓ Notification access allowed" else "Allow notification access") }
                    Muted(if (enabled && overlay && access) "Ready. Play music or receive a notification to see your island." else "Both Android permissions and the switch above are needed.")
                }
            }
            Card(Modifier.fillMaxWidth()) {
                Column {
                    Text("Position", style = MaterialTheme.typography.titleMedium)
                    Muted("Adjust below the camera and status bar. ${offset.toInt()} dp offset.")
                    Slider(offset, { offset = it }, valueRange = 0f..100f, onValueChangeFinished = { prefs.offset = offset.toInt() })
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) { Text("Notification previews"); Muted("Show message text when expanded") }
                        Switch(previews, { previews = it; prefs.previews = it })
                    }
                }
            }
        }
    }
}
