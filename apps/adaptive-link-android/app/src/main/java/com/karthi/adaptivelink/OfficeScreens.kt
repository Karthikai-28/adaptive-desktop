@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package com.karthi.adaptivelink

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Headset
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

// ------------------------------------------------------------------ look

private val Ink = Color(0xFFF5F5F7)
private val Dim = Color(0xFF8E8E93)
private val Panel = Color(0xFF1C1C1E)
private val Raised = Color(0xFF2C2C2E)
private val Hair = Color(0x22FFFFFF)
private val Accent = Color(0xFF0A84FF)
private val Green = Color(0xFF30D158)
private val Amber = Color(0xFFFF9F0A)
private val Violet = Color(0xFFBF5AF2)
private val Sky = Color(0xFF64D2FF)
private val Red = Color(0xFFFF453A)

private enum class OfficeTab(val label: String, val icon: ImageVector) {
    Team("Team", Icons.Filled.Groups), Claude("Claude", Icons.Filled.AutoAwesome), Tasks("Tasks", Icons.Filled.Checklist),
    Missions("Missions", Icons.Filled.Description), Meeting("Meeting", Icons.Filled.Forum), More("More", Icons.Filled.Tune),
}

private sealed class Route {
    data class Person(val id: String, val tab: String = "chat", val draft: String = "") : Route()
    data class Task(val id: Int) : Route()
    data class NewTask(val agent: String = "") : Route()
    data class Mission(val id: Int) : Route()
    object NewMission : Route()
    data class Files(val path: String) : Route()
    object Inbox : Route()
    data class InboxItem(val id: Int) : Route()
    object Reports : Route()
    data class Report(val id: Int) : Route()
}

/** Where a tapped office notification leads (OfficeAlerts.routeOf). */
private fun routeFrom(link: String): Route? {
    val (kind, id) = link.split(":", limit = 2).let { it[0] to it.getOrNull(1)?.toIntOrNull() }
    return when {
        kind == "inbox" && id != null -> Route.InboxItem(id)
        kind == "inbox" -> Route.Inbox
        kind == "task" && id != null -> Route.Task(id)
        kind == "mission" && id != null -> Route.Mission(id)
        kind == "report" && id != null -> Route.Report(id)
        kind == "reports" -> Route.Reports
        else -> null
    }
}

/** The status word and its colour, the same as the desktop's: the office overview's for an agent, the live status
 *  mapped onto the same words for the manager (OfficeDesk). Working green, blocked amber, error red, idle grey. */
private fun deskStatus(office: Office, id: String): Pair<String, Color> {
    office.desks[id]?.let { d -> return d.str("state_label").ifBlank { OfficeDesk.word(d.str("state")) } to stateTint(d.str("state")) }
    val a = office.agents[id] ?: return "Away" to Dim
    val (state, label) = OfficeDesk.fromStatus(a.str("status"), a.optBoolean("in_meeting"))
    return label to stateTint(state)
}

private fun stateTint(state: String) = when (state) {
    "working" -> Green
    "blocked" -> Amber
    "error" -> Red
    else -> Dim
}

/** Seconds since the epoch, moving every second while it is shown (run times count on). */
@Composable
private fun nowTick(): Double {
    val now by produceState(System.currentTimeMillis() / 1000.0) {
        while (true) { delay(1000); value = System.currentTimeMillis() / 1000.0 }
    }
    return now
}

/** A mission's tasks done out of its tasks so far: the only progress the office really knows. */
@Composable
private fun Progress(fraction: Float, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(5.dp).clip(RoundedCornerShape(3.dp)).background(Raised)) {
        Box(Modifier.fillMaxWidth(fraction).fillMaxHeight().clip(RoundedCornerShape(3.dp)).background(Accent))
    }
}

private fun taskColor(status: String) = when (status) {
    "running" -> Amber
    "queued" -> Accent
    "done" -> Green
    "failed" -> Red
    else -> Dim
}

private fun missionColor(status: String) = when (status) {
    "running", "unverified" -> Amber
    "queued" -> Accent
    "succeeded" -> Green
    "failed" -> Red
    else -> Dim
}

private fun ago(ts: Double): String {
    if (ts <= 0) return ""
    val s = (System.currentTimeMillis() / 1000.0 - ts).toLong()
    return when {
        s < 60 -> "now"
        s < 3600 -> "${s / 60} min ago"
        s < 86_400 -> "${s / 3600} h ago"
        else -> "${s / 86_400} d ago"
    }
}

private fun clock(ts: Double): String =
    java.text.SimpleDateFormat(if (ts - System.currentTimeMillis() / 1000.0 > 20 * 3600) "EEE HH:mm" else "HH:mm",
        java.util.Locale.getDefault()).format(java.util.Date((ts * 1000).toLong()))

private fun shirt(p: JSONObject?): Color = runCatching {
    Color(android.graphics.Color.parseColor(p?.optJSONObject("look")?.str("shirt") ?: "#0A84FF"))
}.getOrDefault(Accent)

// ------------------------------------------------------------------ the page

@Composable
fun OfficePage(activity: MainActivity, client: LinkClient, onBack: () -> Unit) {
    val office = remember(client) { Office(client) }
    val voice = remember(office) { OfficeVoice(activity, office) }
    val ears = remember { OfficeEars(activity) }
    val prefs = remember { activity.getSharedPreferences("office", 0) }
    var speakReplies by remember { mutableStateOf(prefs.getBoolean("speak", true)) }
    val snack = remember { SnackbarHostState() }
    var tab by rememberSaveable { mutableStateOf(OfficeTab.Team) }
    val stack = remember { mutableStateListOf<Route>() }

    DisposableEffect(office) {
        office.start()
        onDispose { office.stop(); voice.close(); ears.close() }
    }
    LaunchedEffect(office) { office.notices.collect { snack.showSnackbar(it) } }
    // opened from an office notification: go straight to what it is about
    LaunchedEffect(Unit) {
        OfficeAlerts.pendingRoute?.let { link -> OfficeAlerts.pendingRoute = null; routeFrom(link)?.let { stack.add(it) } }
    }
    BackHandler(enabled = stack.isNotEmpty()) { stack.removeAt(stack.lastIndex) }

    // The microphone is asked for the first time it is needed.
    var afterPermission by remember { mutableStateOf<(() -> Unit)?>(null) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) afterPermission?.invoke() else office.notices.tryEmit("Voice needs the microphone permission.")
        afterPermission = null
    }
    val withMic: (() -> Unit) -> Unit = { go ->
        if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) go()
        else { afterPermission = go; activity.awayOnPurpose = true; permission.launch(Manifest.permission.RECORD_AUDIO) }
    }
    val ctx = Ctx(office, voice, ears, withMic, speakReplies, { speakReplies = it; prefs.edit().putBoolean("speak", it).apply(); if (!it) voice.stop() },
        push = { stack.add(it) }, pop = { if (stack.isNotEmpty()) stack.removeAt(stack.lastIndex) })

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            when (val top = stack.lastOrNull()) {
                null -> {
                    TopBar(if (tab == OfficeTab.Claude) office.name(office.managerId) else office.company, onBack) {
                        InboxPill(office) { stack.add(Route.Inbox) }
                        Spacer(Modifier.width(6.dp))
                        QuotaPill(office)
                        Spacer(Modifier.width(8.dp))
                    }
                    ConnectionLine(office)
                    Box(Modifier.weight(1f)) {
                        when (tab) {
                            OfficeTab.Team -> TeamTab(ctx)
                            OfficeTab.Claude -> Conversation(ctx, office.managerId, Modifier.fillMaxSize())
                            OfficeTab.Tasks -> TasksTab(ctx)
                            OfficeTab.Missions -> MissionsTab(ctx)
                            OfficeTab.Meeting -> MeetingTab(ctx)
                            OfficeTab.More -> MoreTab(ctx)
                        }
                    }
                    TabBar(tab, meetingOn = office.meeting != null) { tab = it }
                }
                is Route.Person -> PersonScreen(ctx, top)
                is Route.Task -> TaskScreen(ctx, top.id)
                is Route.NewTask -> NewTaskScreen(ctx, top.agent)
                is Route.Mission -> MissionScreen(ctx, top.id)
                Route.NewMission -> NewMissionScreen(ctx)
                is Route.Files -> FilesScreen(ctx, top.path)
                Route.Inbox -> InboxScreen(ctx)
                Route.Reports -> ReportsScreen(ctx)
                is Route.Report -> ReportScreen(ctx, top.id)
                is Route.InboxItem -> InboxItemScreen(ctx, top.id)
            }
        }
        SnackbarHost(snack, Modifier.align(Alignment.BottomCenter).padding(bottom = 72.dp)) {
            Snackbar(it, containerColor = Raised, contentColor = Ink, shape = RoundedCornerShape(14.dp))
        }
    }
}

/** What every part of the Office page needs. */
private class Ctx(
    val office: Office, val voice: OfficeVoice, val ears: OfficeEars, val withMic: (() -> Unit) -> Unit,
    val speak: Boolean, val setSpeak: (Boolean) -> Unit, val push: (Route) -> Unit, val pop: () -> Unit,
)

@Composable
private fun ConnectionLine(office: Office) {
    AnimatedVisibility(!office.connected) {
        Text(office.problem.ifBlank { "Connecting to the office…" }, color = Dim, fontSize = 12.sp,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 2.dp))
    }
}

@Composable
private fun QuotaPill(office: Office) {
    val now = System.currentTimeMillis() / 1000.0
    val (text, color) = when {
        office.quotaUntil > now -> "Quota out · ${clock(office.quotaUntil)}" to Red
        office.usage.isNotEmpty() -> {
            val low = office.usage.minByOrNull { it.str("remaining").trimEnd('%').toIntOrNull() ?: 100 }!!
            "${low.str("remaining")} ${low.str("window")}" to
                ((low.str("remaining").trimEnd('%').toIntOrNull() ?: 100).let { if (it < 15) Amber else Dim })
        }
        else -> return
    }
    Text(text, color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium,
        modifier = Modifier.heightIn(min = 40.dp).wrapContentHeight().clip(RoundedCornerShape(12.dp)).background(Panel)
            .padding(horizontal = 12.dp, vertical = 10.dp), maxLines = 1)
}

@Composable
private fun TabBar(selected: OfficeTab, meetingOn: Boolean, onSelect: (OfficeTab) -> Unit) {
    Row(Modifier.fillMaxWidth().background(Color(0xFF0B0B0C)).border(0.5.dp, Hair).padding(vertical = 6.dp)) {
        OfficeTab.entries.forEach { t ->
            val on = t == selected
            Column(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable { onSelect(t) }.padding(vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Box {
                    Icon(t.icon, t.label, Modifier.size(22.dp), tint = if (on) Accent else Dim)
                    if (t == OfficeTab.Meeting && meetingOn)
                        Box(Modifier.size(8.dp).clip(CircleShape).background(Sky).align(Alignment.TopEnd))
                }
                Text(t.label, fontSize = 10.sp, color = if (on) Accent else Dim, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
            }
        }
    }
}

// ------------------------------------------------------------------ small parts

@Composable
private fun Avatar(person: JSONObject?, size: Int = 40) {
    val name = person?.str("name").orEmpty()
    Box(Modifier.size(size.dp).clip(CircleShape).background(shirt(person)), contentAlignment = Alignment.Center) {
        Text(name.take(1).uppercase(), color = Color.White, fontSize = (size * 0.42).sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun Dot(color: Color, size: Int = 8) = Box(Modifier.size(size.dp).clip(CircleShape).background(color))

@Composable
private fun Chip(text: String, on: Boolean = false, color: Color = Accent, onClick: (() -> Unit)? = null) {
    Text(text, fontSize = 13.sp, color = if (on) Color.White else Ink, fontWeight = FontWeight.Medium,
        modifier = Modifier.clip(RoundedCornerShape(16.dp)).background(if (on) color else Raised)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 7.dp))
}

@Composable
private fun Section(text: String) {
    Text(text.uppercase(), color = Dim, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
        modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 6.dp))
}

@Composable
private fun Group(content: @Composable () -> Unit) {
    Column(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Panel)) { content() }
}

@Composable
private fun Line(title: String, detail: String = "", leading: @Composable (() -> Unit)? = null,
                 trailing: @Composable (() -> Unit)? = null, onClick: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
        .padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        if (leading != null) { leading(); Spacer(Modifier.width(12.dp)) }
        Column(Modifier.weight(1f)) {
            Text(title, color = Ink, fontSize = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (detail.isNotBlank()) Text(detail, color = Dim, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        if (trailing != null) { Spacer(Modifier.width(8.dp)); trailing() }
    }
}

@Composable
private fun Button(text: String, color: Color = Accent, filled: Boolean = true, enabled: Boolean = true, onClick: () -> Unit) {
    Text(text, color = if (!enabled) Dim else if (filled) Color.White else color, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.clip(RoundedCornerShape(12.dp)).background(if (filled && enabled) color else Raised)
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 18.dp, vertical = 10.dp))
}

@Composable
private fun Field(value: String, onChange: (String) -> Unit, hint: String, modifier: Modifier = Modifier, lines: Int = 1) {
    Box(modifier.clip(RoundedCornerShape(12.dp)).background(Panel).padding(horizontal = 14.dp, vertical = 12.dp)) {
        if (value.isEmpty()) Text(hint, color = Dim, fontSize = 15.sp)
        BasicTextField(value, onChange, textStyle = TextStyle(color = Ink, fontSize = 15.sp), cursorBrush = SolidColor(Accent),
            singleLine = lines == 1, minLines = lines, modifier = Modifier.fillMaxWidth())
    }
}

// ------------------------------------------------------------------ team

@Composable
private fun TeamTab(ctx: Ctx) {
    val office = ctx.office
    val o = office.overview
    val c = o?.optJSONObject("counts")
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
        // the same figures as the desktop's Command Center
        if (o != null) item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Panel).padding(vertical = 12.dp)) {
                OfficeDesk.today(o).forEachIndexed { i, (value, label) ->
                    val alert = value != "0" && (i == 2 || i == 3)
                    Column(Modifier.weight(1f).then(if (i == 3) Modifier.clickable { ctx.push(Route.Inbox) } else Modifier),
                        horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(value, color = if (alert) (if (i == 2) Red else Amber) else Ink, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                        Text(label, color = Dim, fontSize = 12.sp)
                    }
                }
            }
        }
        item {
            Row(Modifier.padding(horizontal = 20.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                val words = if (c != null) listOf("active" to "working", "blocked" to "blocked", "error" to "with a failure", "paused" to "paused", "idle" to "idle")
                    .filter { c.optInt(it.first) > 0 }.map { (k, w) -> Triple("${c.optInt(k)} $w", k, w) }
                    else emptyList()
                words.forEachIndexed { i, (text, k, _) ->
                    Text((if (i > 0) "  ·  " else "") + text, color = stateTint(if (k == "active") "working" else k), fontSize = 13.sp)
                }
                office.meeting?.let { Text("  ·  meeting on", color = Sky, fontSize = 13.sp) }
            }
        }
        item { Section("Manager") }
        item { Group { PersonLine(ctx, office.person(office.managerId)) } }
        item { Section("Team") }
        item {
            Group {
                office.team.forEachIndexed { i, p ->
                    if (i > 0) Box(Modifier.padding(start = 68.dp).fillMaxWidth().height(0.5.dp).background(Hair))
                    PersonLine(ctx, p)
                }
            }
        }
    }
}

@Composable
private fun PersonLine(ctx: Ctx, p: JSONObject?) {
    p ?: return
    val id = p.str("id")
    val a = ctx.office.agents[id]
    val d = ctx.office.desks[id]
    val (label, color) = deskStatus(ctx.office, id)
    val activity = a?.str("activity").orEmpty()
    val queued = a?.optInt("queued") ?: 0
    val task = d?.optJSONObject("task")
    val detail = when {
        task != null -> "#${task.optInt("id")} ${task.str("title")}"
        activity.isNotBlank() && a?.str("status") != "idle" -> activity
        d != null && d.optJSONArray("blockers").objects().isNotEmpty() -> d.optJSONArray("blockers").objects().first().str("title")
        else -> p.str("role")
    }
    val running = if (d != null) OfficeDesk.runningFor(d, nowTick() - ctx.office.overviewAt) else 0.0
    Line(p.str("name"), detail = detail,
        leading = { Box { Avatar(p); Box(Modifier.align(Alignment.BottomEnd).size(12.dp).clip(CircleShape).background(Color.Black).padding(2.dp)) { Dot(color, 8) } } },
        trailing = {
            Column(horizontalAlignment = Alignment.End) {
                Text(label, color = color, fontSize = 12.sp)
                if (running > 0) Text(OfficeDesk.duration(running), color = Dim, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                else if (queued > 0) Text("+$queued queued", color = Dim, fontSize = 11.sp)
            }
        },
        onClick = { ctx.push(Route.Person(id)) })
}

@Composable
private fun PersonScreen(ctx: Ctx, route: Route.Person) {
    val office = ctx.office
    val p = office.person(route.id)
    val a = office.agents[route.id]
    val study = office.studies.firstOrNull { it.str("agent") == route.id }
    val isManager = route.id == office.managerId
    var tab by remember(route) { mutableStateOf(route.tab) }
    var menu by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    TopBar(p?.str("name") ?: route.id, ctx.pop) {
        if (!isManager) Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "More", tint = Ink) }
            DropdownMenu(menu, { menu = false }, containerColor = Raised) {
                DropdownMenuItem({ Text("Assign a task") }, { menu = false; ctx.push(Route.NewTask(route.id)) })
                DropdownMenuItem({ Text("Call (1:1 meeting)") }, {
                    menu = false
                    scope.launch {
                        if (office.meeting == null) office.act("meeting/start", JSONObject().put("topic", "Call with ${p?.str("name")}")
                            .put("attendees", JSONArray(listOf(route.id))))
                        else office.act("meeting/invite", JSONObject().put("attendees", JSONArray(listOf(route.id))))
                        office.notices.tryEmit("Open the Meeting tab to talk")
                    }
                })
                DropdownMenuItem({ Text("Stop what they're doing") }, { menu = false; scope.launch { office.act("agents/${route.id}/stop") } })
                DropdownMenuItem({ Text("Reset memory") }, { menu = false; scope.launch { if (office.act("agents/${route.id}/reset") == null) office.notices.tryEmit("Memory reset") } })
            }
        }
    }
    Row(Modifier.padding(horizontal = 20.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Avatar(p, 48)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(p?.str("role").orEmpty(), color = Ink, fontSize = 15.sp)
            val (label, color) = deskStatus(office, route.id)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Dot(color); Spacer(Modifier.width(6.dp))
                Text(listOf(label, a?.str("activity").orEmpty().takeIf { a?.str("status") != "idle" }.orEmpty()).filter { it.isNotBlank() }.joinToString(" · "),
                    color = Dim, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
    val tabs = buildList { add("chat" to "Chat"); add("work" to "Work"); if (study != null) add("learning" to "Learning") }
    if (tabs.size > 1) Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Panel).padding(3.dp)) {
        tabs.forEach { (key, label) ->
            Text(label, color = if (tab == key) Ink else Dim, fontSize = 14.sp, fontWeight = FontWeight.Medium,
                modifier = Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).background(if (tab == key) Raised else Color.Transparent)
                    .clickable { tab = key }.padding(vertical = 7.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }
    Box(Modifier.fillMaxSize()) {
        when (tab) {
            "work" -> WorkView(ctx, route.id)
            "learning" -> study?.let { LearningView(ctx, it) { draft -> tab = "chat"; ctx.pop(); ctx.push(Route.Person(route.id, "chat", draft)) } }
            else -> Conversation(ctx, route.id, Modifier.fillMaxSize(), route.draft)
        }
    }
}

// ------------------------------------------------------------------ conversations

/** A direct conversation with one person (an agent or Claude), as text and voice. */
@Composable
private fun Conversation(ctx: Ctx, who: String, modifier: Modifier, draft: String = "") {
    val office = ctx.office
    val thread = office.threadOf(who)
    LaunchedEffect(thread, office.connected) { if (office.connected) office.loadThread(thread) }
    DisposableEffect(thread) { onDispose { office.threads.remove(thread) } }
    LaunchedEffect(thread, ctx.speak) {
        if (ctx.speak) office.incoming.collect { m ->
            if (m.str("thread") == thread && m.str("sender") !in listOf("operator", "system")) ctx.voice.speak(m.str("sender"), m.str("text"))
        }
    }
    val a = office.agents[who]
    val typing = if (who == office.managerId) a?.str("status") == "working" else a?.optBoolean("chatting") == true
    Messages(ctx, office.threads[thread], typing = if (typing) "${office.name(who)} is replying…" else "", modifier = modifier,
        empty = "Say hello to ${office.name(who)}. ${if (who == office.managerId) "Tell Claude what you want done; it plans the work and assigns the team." else "They answer right away, even mid-task."}",
        draft = draft) { text -> office.send(who, text) }
}

@Composable
private fun Messages(ctx: Ctx, messages: List<JSONObject>?, typing: String, modifier: Modifier, empty: String, draft: String = "",
                   handsFree: Boolean? = null, setHandsFree: ((Boolean) -> Unit)? = null, send: suspend (String) -> String?) {
    val list = rememberLazyListState()
    val count = messages?.size ?: 0
    LaunchedEffect(count, typing) { if (count > 0) list.animateScrollToItem(if (typing.isNotBlank()) count else count - 1) }
    Column(modifier) {
        Box(Modifier.weight(1f)) {
            when {
                messages == null -> Muted("Loading…", Modifier.padding(20.dp))
                messages.isEmpty() -> Muted(empty, Modifier.padding(24.dp))
                else -> LazyColumn(state = list, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp)) {
                    items(messages, key = { it.optInt("id") }) { Bubble(ctx, it) }
                    if (typing.isNotBlank()) item { Text(typing, color = Dim, fontSize = 13.sp, modifier = Modifier.padding(8.dp)) }
                }
            }
        }
        Composer(ctx, draft, handsFree, setHandsFree, send)
    }
}

@Composable
private fun Bubble(ctx: Ctx, m: JSONObject) {
    val office = ctx.office
    val sender = m.str("sender")
    val mine = sender == "operator"
    val text = m.str("text")
    val kind = m.optJSONObject("meta")?.str("kind").orEmpty()
    if (sender == "system") {
        Text(text, color = Dim, fontSize = 12.sp, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
            textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        return
    }
    var open by remember(m.optInt("id")) { mutableStateOf(text.length < 1400) }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
        if (!mine) Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, bottom = 3.dp)) {
            Text(office.name(sender), color = Dim, fontSize = 12.sp, fontWeight = FontWeight.Medium)
            val tag = when (kind) { "report" -> "report"; "learning" -> "learning report"; "failure" -> "problem"; "notice" -> "notice"; else -> "" }
            if (tag.isNotBlank()) Text("  ·  $tag", color = if (kind == "failure") Red else Sky, fontSize = 12.sp)
        }
        Box(Modifier.widthIn(max = 320.dp).clip(RoundedCornerShape(18.dp))
            .background(if (mine) Accent else if (kind == "failure") Color(0x33FF453A) else Panel)
            .clickable(enabled = text.length >= 1400) { open = !open }.padding(horizontal = 14.dp, vertical = 10.dp)) {
            SelectionContainer {
                Text(if (open) text else text.take(1200) + "…", color = if (mine) Color.White else Ink, fontSize = 15.sp, lineHeight = 21.sp)
            }
        }
        Row(Modifier.padding(horizontal = 6.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(clock(m.optDouble("ts")), color = Dim, fontSize = 11.sp)
            if (text.length >= 1400) Text(if (open) "  ·  show less" else "  ·  show all", color = Accent, fontSize = 11.sp, modifier = Modifier.clickable { open = !open })
            if (!mine) Icon(Icons.AutoMirrored.Filled.VolumeUp, "Read aloud", tint = Dim,
                modifier = Modifier.padding(start = 8.dp).size(16.dp).clickable { ctx.voice.speak(sender, text) })
        }
    }
}

/** Where you write or speak. In a meeting it can also listen hands-free. */
@Composable
private fun Composer(ctx: Ctx, draft: String, handsFree: Boolean?, setHandsFree: ((Boolean) -> Unit)?, send: suspend (String) -> String?) {
    var text by remember(draft) { mutableStateOf(draft) }
    var sending by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ears = ctx.ears
    fun submit(words: String) {
        val t = words.trim()
        if (t.isEmpty() || sending) return
        sending = true
        scope.launch {
            if (send(t) == null) text = ""
            sending = false
        }
    }
    Column(Modifier.fillMaxWidth().background(Color(0xFF0B0B0C)).border(0.5.dp, Hair).padding(horizontal = 10.dp, vertical = 8.dp).imePadding()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { ctx.setSpeak(!ctx.speak) }, modifier = Modifier.size(40.dp)) {
                Icon(if (ctx.speak) Icons.AutoMirrored.Filled.VolumeUp else Icons.AutoMirrored.Filled.VolumeOff,
                    if (ctx.speak) "Replies are read aloud" else "Replies are not read aloud", tint = if (ctx.speak) Accent else Dim)
            }
            Box(Modifier.weight(1f).clip(RoundedCornerShape(20.dp)).background(Panel).padding(horizontal = 14.dp, vertical = 10.dp)) {
                val shown = if (ears.listening) ears.partial else text
                if (shown.isEmpty()) Text(if (ears.listening) "Listening…" else "Message", color = Dim, fontSize = 15.sp)
                BasicTextField(shown, { text = it }, textStyle = TextStyle(color = Ink, fontSize = 15.sp), cursorBrush = SolidColor(Accent),
                    maxLines = 6, modifier = Modifier.fillMaxWidth().heightIn(min = 20.dp))
            }
            Spacer(Modifier.width(6.dp))
            if (text.isBlank() && !ears.listening) {
                IconButton(onClick = {
                    ctx.voice.stop()
                    ctx.withMic { ears.listen { words -> if (words.isNotBlank()) submit(words) } }
                }, modifier = Modifier.size(40.dp).clip(CircleShape).background(Raised)) { Icon(Icons.Filled.Mic, "Speak", tint = Ink) }
            } else if (ears.listening) {
                IconButton(onClick = { ears.stop() }, modifier = Modifier.size(40.dp).clip(CircleShape).background(Red)) { Icon(Icons.Filled.Stop, "Stop listening", tint = Color.White) }
            } else {
                IconButton(onClick = { submit(text) }, enabled = !sending, modifier = Modifier.size(40.dp).clip(CircleShape).background(Accent)) {
                    Icon(Icons.AutoMirrored.Filled.Send, "Send", tint = Color.White, modifier = Modifier.size(18.dp))
                }
            }
        }
        if (handsFree != null && setHandsFree != null) Row(Modifier.padding(start = 48.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.Headset, null, tint = if (handsFree) Sky else Dim, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(if (handsFree) "Hands-free: listening between replies" else "Hands-free", color = if (handsFree) Sky else Dim, fontSize = 13.sp, modifier = Modifier.weight(1f))
            Switch(handsFree, { on -> if (on) ctx.withMic { setHandsFree(true) } else setHandsFree(false) },
                colors = SwitchDefaults.colors(checkedTrackColor = Sky))
        }
    }
}

// ------------------------------------------------------------------ work

@Composable
private fun WorkView(ctx: Ctx, id: String) {
    val office = ctx.office
    LaunchedEffect(id, office.connected) { if (office.connected) office.loadEvents(id) }
    DisposableEffect(id) { onDispose { office.events.remove(id) } }
    val mine = office.tasks.values.filter { it.str("agent") == id }.sortedByDescending { it.optInt("id") }
    val active = mine.filter { it.str("status") in listOf("running", "queued") }
    val past = mine.filter { it.str("status") !in listOf("running", "queued") }.take(25)
    val d = office.desks[id]
    val now = nowTick()
    // the last week's runs with their times (GET /api/activity/history), read again when the agent's work changes
    var history by remember(id) { mutableStateOf<List<JSONObject>?>(null) }
    val changed = active.joinToString { "${it.optInt("id")}:${it.str("status")}" }
    LaunchedEffect(id, office.connected, changed) {
        if (!office.connected) return@LaunchedEffect
        val until = System.currentTimeMillis() / 1000.0
        history = office.array("activity/history?agent=${Office.enc(id)}&since=${until - 7 * 86_400}&until=$until&limit=40")
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) { Button("Assign a task") { ctx.push(Route.NewTask(id)) } }
        }
        if (d != null) {
            item { Section("At the desk") }
            item {
                Group {
                    val (label, color) = deskStatus(office, id)
                    Line(label, OfficeDesk.runLine(d, now - office.overviewAt), leading = { Dot(color, 10) })
                    d.optJSONObject("task")?.let { t ->
                        Line("#${t.optInt("id")}  ${t.str("title")}", "current task", onClick = { ctx.push(Route.Task(t.optInt("id"))) })
                    }
                    d.optJSONObject("mission")?.let { m ->
                        Column(Modifier.fillMaxWidth().clickable { ctx.push(Route.Mission(m.optInt("id"))) }.padding(horizontal = 16.dp, vertical = 12.dp)) {
                            Text(m.str("title"), color = Ink, fontSize = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            OfficeDesk.missionFraction(m)?.let { Progress(it, Modifier.padding(vertical = 6.dp)) }
                            Text("Mission · ${OfficeDesk.missionLine(m)}", color = Dim, fontSize = 13.sp)
                        }
                    }
                    d.optJSONArray("blockers").objects().forEach { b ->
                        Line(b.str("title"), if (b.str("state") == "IN_PROGRESS") "in progress" else "needs you",
                            leading = { Dot(priorityColor(b.str("priority")), 10) }, onClick = { ctx.push(Route.InboxItem(b.optInt("id"))) })
                    }
                    Line("Last 24 hours", "${OfficeDesk.duration(d.optDouble("active_24h_s", 0.0))} active · ${d.optInt("runs_24h")} runs" +
                        if (d.optBoolean("estimated")) " · partly estimated" else "")
                }
            }
        }
        if (active.isNotEmpty()) { item { Section("Now") }; item { Group { active.forEach { TaskLine(ctx, it, showAgent = false) } } } }
        val events = office.events[id].orEmpty().takeLast(25).reversed()
        if (events.isNotEmpty()) {
            item { Section("Activity") }
            item {
                Group {
                    events.forEach { e ->
                        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                            Text(clock(e.optDouble("ts")), color = Dim, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.width(48.dp))
                            Text(e.str("text"), color = Ink, fontSize = 13.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
        history?.takeIf { it.isNotEmpty() }?.let { rows ->
            item { Section("Last 7 days") }
            item {
                Group {
                    rows.forEach { r ->
                        val t = r.optJSONObject("task") ?: JSONObject()
                        val outcome = r.str("outcome")
                        val bits = listOfNotNull("ran ${OfficeDesk.duration(r.optDouble("run_s", 0.0))}" + if (r.optBoolean("estimated")) " (estimated)" else "",
                            r.optDouble("queue_s", 0.0).takeIf { it >= 1 }?.let { "waited ${OfficeDesk.duration(it)}" }, outcome)
                        Line("#${t.optInt("id")}  ${t.str("title")}", bits.joinToString(" · "), leading = { Dot(taskColor(if (outcome == "running") "running" else outcome), 10) },
                            onClick = { ctx.push(Route.Task(t.optInt("id"))) })
                    }
                }
            }
        }
        if (past.isNotEmpty()) { item { Section("Earlier") }; item { Group { past.forEach { TaskLine(ctx, it, showAgent = false) } } } }
        if (mine.isEmpty() && events.isEmpty()) item { Muted("No work yet.", Modifier.padding(24.dp)) }
    }
}

@Composable
private fun TaskLine(ctx: Ctx, t: JSONObject, showAgent: Boolean = true) {
    val status = t.str("status")
    val bits = listOfNotNull(if (showAgent) ctx.office.name(t.str("agent")) else null, status,
        t.str("project").takeIf { it.isNotBlank() }, ago(t.optDouble("finished_at").takeIf { !it.isNaN() && it > 0 } ?: t.optDouble("created_at")))
    Line("#${t.optInt("id")}  ${t.str("title")}", bits.joinToString(" · "), leading = { Dot(taskColor(status), 10) },
        onClick = { ctx.push(Route.Task(t.optInt("id"))) })
}

@Composable
private fun MissionsTab(ctx: Ctx) {
    val rows = ctx.office.missions.values.sortedByDescending { it.optInt("id") }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Button("+ New mission") { ctx.push(Route.NewMission) }
        }
        if (rows.isEmpty()) Muted("No missions yet. Launch an outcome with measurable acceptance criteria.", Modifier.padding(24.dp))
        else LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
            item { Group { rows.forEachIndexed { i, m ->
                if (i > 0) Box(Modifier.padding(start = 38.dp).fillMaxWidth().height(0.5.dp).background(Hair))
                val status = m.str("status")
                Line("#${m.optInt("id")}  ${m.str("title")}",
                    listOf(status, m.str("project").ifBlank { "no project" }, ago(m.optDouble("finished_at").takeIf { !it.isNaN() && it > 0 } ?: m.optDouble("created_at"))).joinToString(" · "),
                    leading = { Dot(missionColor(status), 10) }, onClick = { ctx.push(Route.Mission(m.optInt("id"))) })
            } } }
        }
    }
}

@Composable
private fun MissionScreen(ctx: Ctx, id: Int) {
    val office = ctx.office
    val live = office.missions[id]
    var detail by remember { mutableStateOf<JSONObject?>(null) }
    var search by rememberSaveable { mutableStateOf("") }
    var hits by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var searching by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(id, live?.str("status")) { office.obj("missions/$id")?.let { detail = it } }
    val m = detail ?: live
    TopBar("Mission #$id", ctx.pop)
    if (m == null) { Muted("Loading…", Modifier.padding(20.dp)); return }
    val status = m.str("status")
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp).imePadding()) {
        Text(m.str("title"), color = Ink, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 20.dp))
        FlowRow(Modifier.padding(horizontal = 20.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip(status, true, missionColor(status)); m.str("project").takeIf { it.isNotBlank() }?.let { Chip(it) }
        }
        if (status in listOf("running", "queued")) Row(Modifier.padding(horizontal = 20.dp)) {
            Button("Cancel mission", Red) { scope.launch { office.act("missions/$id/cancel") } }
        }
        Section("Objective"); TextBlock(m.str("objective"))
        Section("Acceptance criteria")
        val verdicts = m.optJSONArray("verdicts").objects().associateBy { it.str("id") }
        Group {
            m.optJSONArray("criteria").strings().forEachIndexed { i, c ->
                val v = verdicts["C${i + 1}"]
                val mark = when (v?.str("verdict")) { "PASS" -> "✓"; "FAIL" -> "✗"; "MISSING" -> "?"; else -> "◻" }
                Line("$mark  C${i + 1} · $c", v?.str("evidence") ?: "")
            }
        }
        Section("Evidence search")
        Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Field(search, { search = it }, "Search reports, capsules and files", Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            Button(if (searching) "…" else "Search", enabled = !searching && search.isNotBlank()) {
                searching = true; scope.launch {
                    val q = java.net.URLEncoder.encode(search, "UTF-8")
                    hits = office.obj("evidence/search?q=$q&mission_id=$id&limit=30")?.optJSONArray("results").objects()
                    searching = false
                }
            }
        }
        if (hits.isNotEmpty()) Group { hits.forEach { h -> Line("[${h.str("kind")}] ${h.str("title")}", "${h.str("snippet")}\n${h.str("ref")}") } }
        val tasks = m.optJSONArray("tasks").objects()
        if (tasks.isNotEmpty()) { Section("Work"); Group { tasks.forEach { TaskLine(ctx, it) } } }
        m.str("summary").takeIf { it.isNotBlank() }?.let { Section("Evidence report"); TextBlock(it) }
        m.str("error").takeIf { it.isNotBlank() }?.let { Section("Problem"); TextBlock(it) }
    }
}

@Composable
private fun NewMissionScreen(ctx: Ctx) {
    val office = ctx.office
    var who by remember { mutableStateOf(office.team.firstOrNull()?.str("id").orEmpty()) }
    var title by rememberSaveable { mutableStateOf("") }
    var objective by rememberSaveable { mutableStateOf("") }
    var criteria by rememberSaveable { mutableStateOf("") }
    var project by rememberSaveable { mutableStateOf("") }
    var repo by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    TopBar("New mission", ctx.pop)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp).imePadding()) {
        Section("Owner")
        FlowRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            office.team.forEach { p -> Chip(p.str("name"), who == p.str("id")) { who = p.str("id") } }
        }
        Section("Outcome")
        Field(title, { title = it }, "Mission title", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Spacer(Modifier.height(10.dp)); Field(objective, { objective = it }, "Objective and boundaries", Modifier.padding(horizontal = 16.dp).fillMaxWidth(), lines = 5)
        Spacer(Modifier.height(10.dp)); Field(criteria, { criteria = it }, "Acceptance criteria, one per line", Modifier.padding(horizontal = 16.dp).fillMaxWidth(), lines = 5)
        Section("Scope")
        Field(project, { project = it.filter { c -> c.isLetterOrDigit() || c in "-_" } }, "Project", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Spacer(Modifier.height(10.dp)); Field(repo, { repo = it }, "Writable repository path or name", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Muted("Every criterion must be reported as PASS or FAIL with evidence. Only the named repository can be changed.", Modifier.padding(20.dp))
        Row(Modifier.padding(horizontal = 16.dp)) {
            val checks = criteria.lines().map { it.trim() }.filter { it.isNotBlank() }
            Button(if (busy) "Launching…" else "Launch mission", enabled = !busy && who.isNotBlank() && title.isNotBlank() && objective.isNotBlank() && checks.isNotEmpty()) {
                busy = true; scope.launch {
                    val payload = JSONObject().put("agent", who).put("title", title.trim()).put("objective", objective.trim())
                        .put("criteria", JSONArray(checks)).put("project", project.trim()).put("repo", repo.trim())
                    if (office.act("missions", payload) == null) { office.notices.tryEmit("Mission launched"); ctx.pop() }
                    busy = false
                }
            }
        }
    }
}

@Composable
private fun TasksTab(ctx: Ctx) {
    var filter by rememberSaveable { mutableStateOf("active") }
    val all = ctx.office.tasks.values.sortedByDescending { it.optInt("id") }
    val shown = when (filter) {
        "active" -> all.filter { it.str("status") in listOf("running", "queued") }
        "done" -> all.filter { it.str("status") == "done" }
        "failed" -> all.filter { it.str("status") in listOf("failed", "cancelled") }
        else -> all
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            listOf("active" to "Active", "done" to "Done", "failed" to "Failed", "all" to "All").forEach { (k, l) ->
                Chip(l, filter == k) { filter = k }
            }
            Spacer(Modifier.width(4.dp))
            Chip("+ New") { ctx.push(Route.NewTask()) }
        }
        if (shown.isEmpty()) Muted(if (filter == "active") "Nothing running or queued." else "No tasks here.", Modifier.padding(24.dp))
        else LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(top = 6.dp, bottom = 20.dp)) {
            item { Group { shown.take(150).forEachIndexed { i, t ->
                if (i > 0) Box(Modifier.padding(start = 38.dp).fillMaxWidth().height(0.5.dp).background(Hair))
                TaskLine(ctx, t)
            } } }
        }
    }
}

@Composable
private fun TaskScreen(ctx: Ctx, id: Int) {
    val office = ctx.office
    val live = office.tasks[id]
    var detail by remember { mutableStateOf<JSONObject?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(id, live?.str("status"), live?.optInt("steps")) { office.obj("tasks/$id")?.let { detail = it } }
    val t = detail ?: live
    TopBar("Task #$id", ctx.pop)
    if (t == null) { Muted("Loading…", Modifier.padding(20.dp)); return }
    val status = t.str("status")
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Text(t.str("title"), color = Ink, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 20.dp))
        FlowRow(Modifier.padding(horizontal = 20.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip(status, true, taskColor(status))
            Chip(office.name(t.str("agent"))) { ctx.push(Route.Person(t.str("agent"), "work")) }
            t.str("project").takeIf { it.isNotBlank() }?.let { Chip(it) }
            Chip(when (val by = t.str("created_by")) { "operator" -> "by you"; "manager" -> "by Claude"; else -> "by $by" })
            if (t.optInt("tokens") > 0) Chip("${t.optInt("tokens") / 1000}k tokens")
        }
        Row(Modifier.padding(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (status in listOf("running", "queued")) Button("Cancel", Red) { scope.launch { office.act("tasks/$id/cancel") } }
            if (status in listOf("failed", "cancelled", "done")) Button("Run again") { scope.launch { office.act("tasks/$id/retry") } }
        }
        val result = t.str("result").ifBlank { t.str("error") }
        if (result.isNotBlank()) { Section(if (t.str("result").isNotBlank()) "Report" else "Problem"); TextBlock(result) }
        if (t.str("body").isNotBlank()) { Section("Brief"); TextBlock(t.str("body")) }
        val events = t.optJSONArray("events").objects().takeLast(40).reversed()
        if (events.isNotEmpty()) {
            Section("Activity")
            Group {
                events.forEach { e ->
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 7.dp)) {
                        Text(clock(e.optDouble("ts")), color = Dim, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.width(48.dp))
                        Text(e.str("text"), color = Ink, fontSize = 13.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

@Composable
private fun TextBlock(text: String, mono: Boolean = false) {
    Box(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Panel).padding(16.dp)) {
        SelectionContainer {
            Text(text, color = Ink, fontSize = if (mono) 12.sp else 14.sp, lineHeight = if (mono) 17.sp else 20.sp,
                fontFamily = if (mono) FontFamily.Monospace else FontFamily.Default)
        }
    }
}

@Composable
private fun NewTaskScreen(ctx: Ctx, agent: String) {
    val office = ctx.office
    var who by remember { mutableStateOf(agent.ifBlank { office.team.firstOrNull()?.str("id").orEmpty() }) }
    var title by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    var project by remember { mutableStateOf("") }
    var after by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    TopBar("New task", ctx.pop)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp).imePadding()) {
        Section("Who")
        FlowRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            office.team.forEach { p -> Chip(p.str("name"), who == p.str("id")) { who = p.str("id") } }
        }
        office.person(who)?.let { Muted(it.str("role"), Modifier.padding(horizontal = 20.dp, vertical = 6.dp)) }
        Section("What")
        Field(title, { title = it }, "Title", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Spacer(Modifier.height(10.dp))
        Field(body, { body = it }, "Details: what to deliver and how you'll judge it", Modifier.padding(horizontal = 16.dp).fillMaxWidth(), lines = 6)
        Section("Optional")
        Field(project, { project = it.filter { c -> c.isLetterOrDigit() || c in "-_" } }, "Project (keeps a shared thread)", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Spacer(Modifier.height(10.dp))
        Field(after, { after = it.filter(Char::isDigit) }, "Start after task # (optional)", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Muted("Agents can't ask questions mid-task, so put everything they need in the details.", Modifier.padding(20.dp))
        Row(Modifier.padding(horizontal = 16.dp)) {
            Button(if (busy) "Assigning…" else "Assign to ${office.name(who)}", enabled = !busy && title.isNotBlank() && who.isNotBlank()) {
                busy = true
                scope.launch {
                    val payload = JSONObject().put("agent", who).put("title", title.trim()).put("body", body.trim()).put("project", project.trim())
                    after.toIntOrNull()?.let { payload.put("after", it) }
                    if (office.act("tasks", payload) == null) { office.notices.tryEmit("Assigned to ${office.name(who)}"); ctx.pop() }
                    busy = false
                }
            }
        }
    }
}

// ------------------------------------------------------------------ meetings

@Composable
private fun MeetingTab(ctx: Ctx) {
    val office = ctx.office
    val m = office.meeting
    if (m == null) { StartMeeting(ctx); return }
    val mid = m.optInt("id")
    val thread = "meeting:$mid"
    val attendees = m.optJSONArray("attendees").let { a -> if (a == null) emptyList() else (0 until a.length()).map { a.optString(it) } }
    val scope = rememberCoroutineScope()
    var handsFree by remember(mid) { mutableStateOf(false) }
    var lastSaid by remember { mutableLongStateOf(0L) }
    var lastReply by remember { mutableLongStateOf(0L) }
    var inviting by remember { mutableStateOf(false) }
    LaunchedEffect(thread, office.connected) { if (office.connected) office.loadThread(thread) }
    DisposableEffect(thread) { onDispose { office.threads.remove(thread); ctx.ears.close() } }
    LaunchedEffect(thread, ctx.speak) {
        office.incoming.collect { msg ->
            if (msg.str("thread") == thread && msg.str("sender") !in listOf("operator", "system")) {
                lastReply = System.currentTimeMillis()
                if (ctx.speak || handsFree) ctx.voice.speak(msg.str("sender"), msg.str("text"))
            }
        }
    }
    val busy = attendees.any { a -> office.agents[a]?.let { it.optBoolean("meeting_busy") || (a == office.managerId && it.str("status") == "working") } == true }
    val busyNow by rememberUpdatedState(busy)
    // Hands-free: listen whenever nobody is talking or thinking, as on the desktop.
    LaunchedEffect(handsFree) {
        while (handsFree) {
            delay(600)
            val now = System.currentTimeMillis()
            val waiting = lastSaid > lastReply && now - lastSaid < 8000
            if (!ctx.voice.speaking && !ctx.ears.listening && !busyNow && !waiting) {
                ctx.ears.listen { words ->
                    if (words.isNotBlank()) { lastSaid = System.currentTimeMillis(); scope.launch { office.say(words) } }
                }
            }
        }
        ctx.ears.stop()
    }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Panel).padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Dot(Sky); Spacer(Modifier.width(8.dp))
                Text(m.str("topic").ifBlank { "Meeting" }, color = Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f),
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("Invite", color = Accent, fontSize = 14.sp, modifier = Modifier.clickable { inviting = !inviting }.padding(6.dp))
                Text("End", color = Red, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.clickable { handsFree = false; scope.launch { office.act("meeting/end") } }.padding(6.dp))
            }
            Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                attendees.forEach { a ->
                    val speakingNow = office.agents[a]?.optBoolean("meeting_busy") == true
                    Box(Modifier.border(2.dp, if (speakingNow) Violet else Color.Transparent, CircleShape).padding(2.dp)) { Avatar(office.person(a), 30) }
                }
            }
            if (inviting) FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                office.roster.filter { it.str("id") !in attendees }.forEach { p ->
                    Chip("+ ${p.str("name")}") { scope.launch { office.act("meeting/invite", JSONObject().put("attendees", JSONArray(listOf(p.str("id"))))) } }
                }
            }
        }
        Muted("Say a name (\"Arjun, …\") to ask one person.", Modifier.padding(horizontal = 20.dp, vertical = 2.dp))
        Messages(ctx, office.threads[thread], typing = if (busy) "Someone is answering…" else "", modifier = Modifier.weight(1f),
            empty = "The meeting has started.", handsFree = handsFree, setHandsFree = { handsFree = it; if (!it) ctx.ears.stop() }) { text ->
            lastSaid = System.currentTimeMillis()
            office.say(text)
        }
    }
}

@Composable
private fun StartMeeting(ctx: Ctx) {
    val office = ctx.office
    var topic by remember { mutableStateOf("") }
    val chosen = remember { mutableStateListOf<String>() }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Section("Call a meeting")
        Field(topic, { topic = it }, "Topic", Modifier.padding(horizontal = 16.dp).fillMaxWidth())
        Section("Who")
        Group {
            office.roster.forEachIndexed { i, p ->
                val id = p.str("id")
                if (i > 0) Box(Modifier.padding(start = 68.dp).fillMaxWidth().height(0.5.dp).background(Hair))
                Line(p.str("name"), p.str("role"), leading = { Avatar(p, 36) },
                    trailing = { Switch(id in chosen, { on -> if (on) chosen.add(id) else chosen.remove(id) }, colors = SwitchDefaults.colors(checkedTrackColor = Accent)) },
                    onClick = { if (id in chosen) chosen.remove(id) else chosen.add(id) })
            }
        }
        Muted("With Claude in the room, it chairs the meeting, writes the minutes and assigns the action items.", Modifier.padding(20.dp))
        Row(Modifier.padding(horizontal = 16.dp)) {
            Button(if (busy) "Starting…" else "Start meeting", enabled = chosen.isNotEmpty() && !busy) {
                busy = true
                scope.launch {
                    office.act("meeting/start", JSONObject().put("topic", topic.trim().ifBlank { "Team meeting" }).put("attendees", JSONArray(chosen.toList())))
                    busy = false
                }
            }
        }
    }
}

// ------------------------------------------------------------------ learning

@Composable
private fun LearningView(ctx: Ctx, study: JSONObject, ask: (String) -> Unit) {
    val office = ctx.office
    val scope = rememberCoroutineScope()
    val pid = study.str("id")
    val progress = study.optJSONObject("progress") ?: JSONObject()
    val topics = progress.optJSONArray("topics").objects().sortedWith(compareBy<JSONObject> { it.str("repo") }.thenByDescending { it.optInt("mastery") })
    val avg = if (topics.isEmpty()) 0.0 else topics.sumOf { it.optInt("mastery") } / topics.size.toDouble()
    val questions = progress.optJSONObject("questions")
    val current = study.optJSONObject("current")
    val active = study.optBoolean("active")
    val now = System.currentTimeMillis() / 1000.0
    val whenText = when {
        current != null -> "In session now: ${current.str("title")}"
        !active -> "Paused"
        study.optInt("today") >= study.optInt("max_per_day") -> "Done for today (${study.optInt("today")}/${study.optInt("max_per_day")})"
        study.optDouble("next_at", 0.0) > 0 -> ((study.optDouble("next_at") - now) / 60).toInt().let { if (it <= 0) "Next session starting shortly" else "Next session in $it min" }
        else -> ""
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Panel).padding(16.dp)) {
                Text(study.str("title"), color = Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Text("${study.optInt("sessions")} sessions · ${study.optInt("today")}/${study.optInt("max_per_day")} today · every ${study.optInt("gap_min")} min", color = Dim, fontSize = 13.sp)
                if (whenText.isNotBlank()) Text(whenText, color = if (current != null) Amber else Dim, fontSize = 13.sp)
                FlowRow(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (active) Chip("Pause") { scope.launch { office.act("study/$pid/pause") } } else Chip("Resume", true) { scope.launch { office.act("study/$pid/resume") } }
                    if (current == null) Chip("Study now") { scope.launch { if (office.act("study/$pid/now") == null) office.notices.tryEmit("Starting a study session") } }
                    study.str("latest_report").takeIf { it.isNotBlank() }?.let { r -> Chip("Latest report") { ctx.push(Route.Files(r)) } }
                    Chip("Notes") { ctx.push(Route.Files(study.str("kb"))) }
                }
            }
        }
        if (topics.isNotEmpty()) item {
            Row(Modifier.padding(horizontal = 20.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(22.dp)) {
                Stat("%.1f".format(avg), "of 5 mastery"); Stat("${topics.size}", "topics")
                Stat("${questions?.optInt("answered") ?: 0}", "answered"); Stat("${questions?.optInt("open") ?: 0}", "open")
            }
        } else item { Muted(study.str("progress_error").ifBlank { "Nothing learned yet. The first session surveys every codebase." }, Modifier.padding(20.dp)) }
        topics.groupBy { it.str("repo").ifBlank { "other" } }.forEach { (repo, list) ->
            item { Section(repo) }
            item {
                Group {
                    list.forEachIndexed { i, t ->
                        if (i > 0) Box(Modifier.padding(start = 16.dp).fillMaxWidth().height(0.5.dp).background(Hair))
                        val name = t.str("title").ifBlank { t.str("id") }
                        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(name, color = Ink, fontSize = 14.sp, modifier = Modifier.weight(1f))
                                Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                                    (1..5).forEach { n -> Box(Modifier.size(width = 12.dp, height = 5.dp).clip(RoundedCornerShape(2.dp)).background(if (n <= t.optInt("mastery")) Green else Raised)) }
                                }
                            }
                            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                                t.str("notes").takeIf { it.isNotBlank() }?.let { n -> Text("Notes", color = Accent, fontSize = 13.sp, modifier = Modifier.clickable { ctx.push(Route.Files("${study.str("kb")}/$n")) }) }
                                t.str("lesson").takeIf { it.isNotBlank() }?.let { n -> Text("Lesson", color = Accent, fontSize = 13.sp, modifier = Modifier.clickable { ctx.push(Route.Files("${study.str("kb")}/$n")) }) }
                                Text("Teach me", color = Accent, fontSize = 13.sp, modifier = Modifier.clickable {
                                    ask("Teach me \"$name\" from the very beginning: explain it simply, show me where it lives in the code, then quiz me.")
                                })
                                Text("Ask", color = Accent, fontSize = 13.sp, modifier = Modifier.clickable { ask("About \"$name\": ") })
                            }
                        }
                    }
                }
            }
        }
        val forOwner = progress.optJSONArray("questions_for_owner")
        if (forOwner != null && forOwner.length() > 0) {
            item { Section("${office.name(study.str("agent"))} asks you") }
            item {
                Group {
                    (0 until forOwner.length()).map { forOwner.optString(it) }.forEach { q ->
                        Line(q, trailing = { Text("Answer", color = Accent, fontSize = 13.sp) }, onClick = { ask("Answer to your question \"$q\": ") })
                    }
                }
            }
        }
        item { Muted("Code is learned only from the local copies (read-only). Bitbucket and the internal git server are blocked; the web is used only for research.", Modifier.padding(20.dp)) }
    }
}

@Composable
private fun Stat(value: String, label: String) {
    Column {
        Text(value, color = Ink, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
        Text(label, color = Dim, fontSize = 12.sp)
    }
}

// ------------------------------------------------------------------ more

@Composable
private fun MoreTab(ctx: Ctx) {
    val office = ctx.office
    val s = office.settings
    val scope = rememberCoroutineScope()
    fun set(key: String, value: Any) = scope.launch { office.act("settings", JSONObject().put(key, value)) }
    val now = System.currentTimeMillis() / 1000.0
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item { Section("Gemini quota") }
        item {
            Group {
                if (office.quotaUntil > now) Line("Out of quota", "The team pauses and resumes by itself at ${clock(office.quotaUntil)}",
                    trailing = { Text("Resume now", color = Accent, fontSize = 14.sp) }, onClick = { set("clear_quota", true) })
                if (office.usage.isEmpty()) Line("Usage not known yet")
                office.usage.forEach { r ->
                    val resets = r.str("resets").let { iso -> runCatching { java.time.OffsetDateTime.parse(iso).toEpochSecond().toDouble() }.getOrNull() }
                    Line(if (r.str("window") == "week") "This week" else "5-hour window", resets?.let { "resets ${clock(it)}" }.orEmpty(),
                        trailing = { Text("${r.str("remaining")} left", color = Ink, fontSize = 14.sp) })
                }
            }
        }
        item { Section("Reports") }
        item {
            Group {
                Line("Standup and evening summary", "Every day at 10:00 and 19:00 (India time), kept and sent to this phone",
                    trailing = { Text("Open", color = Accent, fontSize = 14.sp) }, onClick = { ctx.push(Route.Reports) })
            }
        }
        item { Section("Office") }
        item {
            Group {
                Line("Autopilot", "Claude reviews finished work and follows up by itself",
                    trailing = { Switch(s.optBoolean("autopilot"), { set("autopilot", it) }, colors = SwitchDefaults.colors(checkedTrackColor = Green)) })
                Line("Pause all work", "Running tasks finish; nothing new starts",
                    trailing = { Switch(s.optBoolean("paused"), { set("paused", it) }, colors = SwitchDefaults.colors(checkedTrackColor = Red)) })
                val n = s.optInt("max_parallel", 3)
                Line("Agents working at once", "", trailing = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("−", color = if (n > 1) Accent else Dim, fontSize = 22.sp, modifier = Modifier.clickable(enabled = n > 1) { set("max_parallel", n - 1) }.padding(horizontal = 12.dp))
                        Text("$n", color = Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Text("+", color = if (n < 8) Accent else Dim, fontSize = 22.sp, modifier = Modifier.clickable(enabled = n < 8) { set("max_parallel", n + 1) }.padding(horizontal = 12.dp))
                    }
                })
            }
        }
        if (office.studies.isNotEmpty()) {
            item { Section("Study programs") }
            item {
                Group {
                    office.studies.forEach { st ->
                        Line(st.str("title"), "${office.name(st.str("agent"))} · ${st.optInt("sessions")} sessions · ${if (st.optBoolean("active")) "active" else "paused"}",
                            leading = { Avatar(office.person(st.str("agent")), 32) },
                            onClick = { ctx.push(Route.Person(st.str("agent"), "learning")) })
                    }
                }
            }
        }
        item { Section("Files") }
        item {
            Group {
                Line("Workspace", "Everything the team produces", leading = { Icon(Icons.Filled.Folder, null, tint = Accent) }, onClick = { ctx.push(Route.Files("")) })
                Line("Projects", leading = { Icon(Icons.Filled.Folder, null, tint = Accent) }, onClick = { ctx.push(Route.Files("projects")) })
                Line("Meeting notes", leading = { Icon(Icons.Filled.Folder, null, tint = Accent) }, onClick = { ctx.push(Route.Files("meetings")) })
            }
        }
    }
}

@Composable
private fun FilesScreen(ctx: Ctx, path: String) {
    val office = ctx.office
    var data by remember(path) { mutableStateOf<JSONObject?>(null) }
    var failed by remember(path) { mutableStateOf(false) }
    var image by remember(path) { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    LaunchedEffect(path) {
        val d = office.obj("files?path=${Office.enc(path)}")
        if (d == null) failed = true
        data = d
        if (d?.str("type") == "media" && d.str("mime").startsWith("image/"))
            image = office.bytes("raw?path=${Office.enc(path)}")?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
    }
    TopBar(path.substringAfterLast('/').ifBlank { "Workspace" }, ctx.pop)
    val d = data
    when {
        failed -> Muted("Couldn't open this.", Modifier.padding(20.dp))
        d == null -> Muted("Loading…", Modifier.padding(20.dp))
        d.str("type") == "dir" -> {
            val entries = d.optJSONArray("entries").objects()
            if (entries.isEmpty()) Muted("Empty folder.", Modifier.padding(20.dp))
            else LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
                item {
                    Group {
                        entries.forEachIndexed { i, e ->
                            if (i > 0) Box(Modifier.padding(start = 52.dp).fillMaxWidth().height(0.5.dp).background(Hair))
                            val dir = e.optBoolean("dir")
                            Line(e.str("name"), if (dir) "" else "${size(e.optLong("size"))} · ${ago(e.optDouble("mtime"))}",
                                leading = { Icon(if (dir) Icons.Filled.Folder else Icons.Filled.Description, null, tint = if (dir) Accent else Dim) },
                                onClick = { ctx.push(Route.Files(e.str("path"))) })
                        }
                    }
                }
            }
        }
        d.str("type") == "text" -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 20.dp)) {
            val name = path.lowercase()
            TextBlock(d.str("text") + if (d.optBoolean("truncated")) "\n\n… (the rest is on the computer)" else "",
                mono = !(name.endsWith(".md") || name.endsWith(".txt")))
        }
        image != null -> Image(image!!, path, Modifier.fillMaxWidth().padding(16.dp).clip(RoundedCornerShape(12.dp)))
        else -> Muted("${d.str("mime").ifBlank { "Binary file" }} · ${size(d.optLong("size"))}. Open it on the computer.", Modifier.padding(20.dp))
    }
}

private fun size(n: Long): String = when {
    n < 1024 -> "$n B"
    n < 1024 * 1024 -> "${n / 1024} KB"
    else -> "%.1f MB".format(n / 1048576.0)
}

// ------------------------------------------------------------------ Action Inbox

private val InboxStates = listOf("NEEDS_ATTENTION" to "Needs attention", "IN_PROGRESS" to "In progress", "RESOLVED" to "Resolved")

private fun priorityColor(p: String) = when (p) { "critical" -> Red; "high" -> Amber; else -> Dim }
private fun stateColor(s: String) = when (s) { "NEEDS_ATTENTION" -> Red; "IN_PROGRESS" -> Amber; else -> Green }
private fun stateLabel(s: String) = InboxStates.firstOrNull { it.first == s }?.second ?: s

/** What needs the owner, in the top bar: tap for the Action Inbox. */
@Composable
private fun InboxPill(office: Office, onClick: () -> Unit) {
    val open = office.inbox.optInt("NEEDS_ATTENTION")
    val critical = office.inbox.optInt("critical")
    Text(if (open > 0) "Inbox $open" else "Inbox", color = if (critical > 0) Red else if (open > 0) Amber else Dim,
        fontSize = 12.sp, fontWeight = FontWeight.Medium,
        maxLines = 1,
        modifier = Modifier.heightIn(min = 40.dp).wrapContentHeight().clip(RoundedCornerShape(12.dp)).background(Panel)
            .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp))
}

@Composable
private fun InboxScreen(ctx: Ctx) {
    val office = ctx.office
    val context = androidx.compose.ui.platform.LocalContext.current
    var state by rememberSaveable { mutableStateOf("NEEDS_ATTENTION") }
    var items by remember { mutableStateOf<List<JSONObject>?>(null) }
    var reachable by remember { mutableStateOf(true) }
    LaunchedEffect(state, office.inbox.toString()) {
        val got = office.obj("inbox?state=$state&limit=100")
        reachable = got != null
        items = got?.optJSONArray("items").objects()
    }
    TopBar("Action Inbox", ctx.pop)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            InboxStates.forEach { (key, label) ->
                val n = office.inbox.optInt(key)
                Chip(if (key != "RESOLVED" && n > 0) "$label $n" else label, state == key, stateColor(key)) { state = key }
            }
        }
        when {
            !reachable -> {
                Muted("The computer can't be reached. The last alerts this phone showed:", Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
                Group {
                    OfficeAlerts.recent(context).take(30).forEach { n ->
                        Line(n.str("title"), n.str("text"), leading = { Dot(priorityColor(n.str("priority"))) })
                    }
                }
            }
            items == null -> Muted("Loading…", Modifier.padding(20.dp))
            items!!.isEmpty() -> Muted(if (state == "NEEDS_ATTENTION") "Nothing needs you." else "Nothing here.", Modifier.padding(20.dp))
            else -> Group {
                items!!.forEach { item ->
                    Line(item.str("title"), item.str("text"), leading = { Dot(priorityColor(item.str("priority")), 10) },
                        trailing = { Text(ago(item.optDouble("updated_at")), color = Dim, fontSize = 12.sp) }) {
                        ctx.push(Route.InboxItem(item.optInt("id")))
                    }
                }
            }
        }
    }
}

@Composable
private fun InboxItemScreen(ctx: Ctx, id: Int) {
    val office = ctx.office
    val scope = rememberCoroutineScope()
    var item by remember { mutableStateOf<JSONObject?>(null) }
    var round by remember { mutableStateOf(0) }
    LaunchedEffect(id, round, office.inbox.toString()) { office.obj("inbox/$id")?.let { item = it } }
    TopBar("Inbox #$id", ctx.pop)
    val it = item ?: run { Muted("Loading…", Modifier.padding(20.dp)); return }
    val state = it.str("state")
    val approval = it.str("kind") == "approval"
    fun act(action: String) = scope.launch {
        if (office.act("inbox/$id/$action", JSONObject().put("note", "from the phone")) == null) round++
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Text(it.str("title"), color = Ink, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 20.dp))
        FlowRow(Modifier.padding(horizontal = 20.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip(stateLabel(state), true, stateColor(state))
            Chip(it.str("priority"), false, priorityColor(it.str("priority")))
            it.str("agent").takeIf { a -> a.isNotBlank() }?.let { a -> Chip(office.name(a)) }
            if (it.optInt("task_id") > 0) Chip("Task #${it.optInt("task_id")}") { ctx.push(Route.Task(it.optInt("task_id"))) }
            if (it.optInt("mission_id") > 0) Chip("Mission #${it.optInt("mission_id")}") { ctx.push(Route.Mission(it.optInt("mission_id"))) }
        }
        TextBlock(it.str("text"))
        if (approval && state != "RESOLVED")
            Muted("Approving runs work with the operator's authority, so it is done on the computer with the operator key " +
                "(the office app's Action Inbox, or the office command). From here you can acknowledge it or decline it.",
                Modifier.padding(horizontal = 20.dp, vertical = 10.dp))
        if (state == "RESOLVED")
            Muted("Resolved" + it.str("resolution").takeIf { r -> r.isNotBlank() }?.let { r -> ": $r" }.orEmpty() +
                it.str("resolved_by").takeIf { r -> r.isNotBlank() }?.let { r -> " by $r" }.orEmpty(),
                Modifier.padding(horizontal = 20.dp, vertical = 10.dp))
        FlowRow(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (state == "NEEDS_ATTENTION") Button("Acknowledge") { act("ack") }
            if (approval && state != "RESOLVED") Button("Decline", Red, filled = false) { act("decline") }
            if (!approval && state != "RESOLVED") Button("Resolved", Green, filled = !it.optBoolean("live"), enabled = !it.optBoolean("live")) { act("resolve") }
            if (state == "RESOLVED") Button("Reopen", filled = false) { act("reopen") }
        }
        if (!approval && state != "RESOLVED" && it.optBoolean("live"))
            Muted("Still happening: run the work again or cancel it, and this closes by itself.", Modifier.padding(horizontal = 20.dp))
        val history = it.optJSONArray("history").objects().takeLast(40).reversed()
        if (history.isNotEmpty()) {
            Section("History")
            Group {
                history.forEach { e ->
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 7.dp)) {
                        Text(clock(e.optDouble("ts")), color = Dim, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.width(48.dp))
                        Text(e.str("text"), color = Ink, fontSize = 13.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

// ------------------------------------------------------------------ reports

@Composable
private fun ReportsScreen(ctx: Ctx) {
    val office = ctx.office
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<JSONObject>?>(null) }
    var schedule by remember { mutableStateOf<JSONObject?>(null) }
    var round by remember { mutableStateOf(0) }
    LaunchedEffect(round) {
        items = office.array("reports?limit=60")
        schedule = office.obj("reports/schedule")
    }
    TopBar("Reports", ctx.pop)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        schedule?.optJSONObject("kinds")?.let { k ->
            Muted("Next standup ${k.optJSONObject("standup")?.str("next_local").orEmpty()}, next evening summary " +
                "${k.optJSONObject("evening")?.str("next_local").orEmpty()} (${schedule!!.str("timezone")}).",
                Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
        }
        Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip("Standup now") { scope.launch { office.act("reports/generate", JSONObject().put("kind", "standup")); round++ } }
            Chip("Summary now") { scope.launch { office.act("reports/generate", JSONObject().put("kind", "evening")); round++ } }
        }
        when {
            items == null -> Muted("Loading…", Modifier.padding(20.dp))
            items!!.isEmpty() -> Muted("No reports yet. The first comes at the next scheduled time.", Modifier.padding(20.dp))
            else -> Group {
                items!!.forEach { r ->
                    val status = r.str("status")
                    val missed = status == "missed" || status == "failed"
                    Line(r.str("title"), r.str("summary").ifBlank { status },
                        leading = { Dot(when (status) { "delivered" -> Green; "generated" -> Accent; "failed" -> Red; else -> Dim }) },
                        trailing = { Text(r.str("scheduled_at_local").ifBlank { r.str("generated_at_local") }.takeLast(11), color = Dim, fontSize = 12.sp) },
                        onClick = if (missed) null else ({ ctx.push(Route.Report(r.optInt("id"))) }))
                }
            }
        }
    }
}

@Composable
private fun ReportScreen(ctx: Ctx, id: Int) {
    var report by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(id) { report = ctx.office.obj("reports/$id") }
    TopBar("Report", ctx.pop)
    val r = report ?: run { Muted("Loading…", Modifier.padding(20.dp)); return }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        reportBlocks(r.str("markdown")).forEach { (kind, text) ->
            when (kind) {
                "h1" -> Text(text, color = Ink, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
                "h2" -> Section(text)
                "h3" -> Text(text, color = Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
                "table" -> TextBlock(text, mono = true)
                else -> Text(text, color = if (kind == "note") Dim else Ink, fontSize = 14.sp, lineHeight = 20.sp,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 2.dp))
            }
        }
    }
}

/** The report's Markdown as (kind, text) blocks: headings, tables kept monospaced, the rest as lines. */
internal fun reportBlocks(md: String): List<Pair<String, String>> {
    val out = mutableListOf<Pair<String, String>>()
    val table = StringBuilder()
    fun flush() { if (table.isNotEmpty()) { out += "table" to table.toString().trimEnd(); table.clear() } }
    md.lines().forEach { raw ->
        val line = raw.trimEnd()
        if (line.startsWith("|")) {
            if (!line.startsWith("|---")) table.append(line.trim('|').split("|").joinToString("  ") { it.trim() }).append('\n')
            return@forEach
        }
        flush()
        val plain = line.replace("**", "").replace("`", "")
        when {
            line.isBlank() -> {}
            line.startsWith("### ") -> out += "h3" to plain.removePrefix("### ")
            line.startsWith("## ") -> out += "h2" to plain.removePrefix("## ")
            line.startsWith("# ") -> out += "h1" to plain.removePrefix("# ")
            line.startsWith("> ") -> out += "note" to plain.removePrefix("> ")
            line.startsWith("*") && line.endsWith("*") && !line.startsWith("**") -> out += "note" to plain.trim('*')
            line.startsWith("- ") -> out += "line" to "• " + plain.removePrefix("- ")
            else -> out += "line" to plain
        }
    }
    flush()
    return out
}
