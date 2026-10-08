package com.karthi.adaptivelink

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

@Composable
internal fun LayoutManager(activity: MainActivity, client: LinkClient, cache: WorkspaceStore, app: String, title: String,
                           selected: JSONObject?, onBack: () -> Unit, test: ((JSONObject) -> Unit)? = null) {
    val scope = rememberCoroutineScope()
    var all by remember { mutableStateOf(cache.profiles()) }
    var editing by remember { mutableStateOf<JSONObject?>(null) }
    var note by remember { mutableStateOf("") }
    var exportText by remember { mutableStateOf("") }
    var imported by remember { mutableStateOf<JSONObject?>(null) }
    var deleting by remember { mutableStateOf<JSONObject?>(null) }
    var globalRun by remember { mutableStateOf("") }
    var globalConfirmation by remember { mutableStateOf<JSONObject?>(null) }
    suspend fun sync() { note = cache.sync(client); all = cache.profiles() }
    fun globalTest(c: JSONObject, confirmed: Boolean = false) {
        if (test != null) { test(c); return }
        if (globalRun.isNotEmpty()) return
        scope.launch {
            val answer = client.post("/v1/control-runs", JSONObject().put("request_id", freshId()).put("steps", c.getJSONArray("steps")).put("confirm", confirmed))
            if (answer?.optBoolean("confirm") == true) globalConfirmation = c
            else if (answer?.optBoolean("ok") == true) globalRun = answer.getJSONObject("run").getString("id")
            else note = answer?.optString("error") ?: "Offline · action was not queued"
        }
    }
    WorkspaceForeground(activity) {
        val rid = globalRun
        if (rid.isNotEmpty()) scope.launch { client.post("/v1/control-runs", JSONObject().put("operation", "cancel").put("id", rid)) }
    }
    LaunchedEffect(globalRun) {
        if (globalRun.isNotEmpty()) while (true) {
            val r = client.get("/v1/control-runs?id=$globalRun")?.optJSONArray("runs")?.optJSONObject(0)
            note = r?.let { "${it.optString("state")} ${it.optInt("step")}/${it.optInt("total")} ${it.optString("error")}" } ?: "Disconnected"
            if (r == null || r.optString("state") != "running") { globalRun = ""; break }
            delay(500)
        }
    }
    DisposableEffect(globalRun) { val rid = globalRun; onDispose {
        if (rid.isNotEmpty()) CoroutineScope(Dispatchers.IO).launch { client.post("/v1/control-runs", JSONObject().put("operation", "cancel").put("id", rid)) }
    } }
    val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        if (uri != null) runCatching { activity.contentResolver.openOutputStream(uri)?.use { it.write(exportText.toByteArray()) } }
            .onSuccess { note = "Layout exported" }.onFailure { note = "Export failed: ${it.message}" }
    }
    val importFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) runCatching {
            val text = activity.contentResolver.openInputStream(uri)!!.use { it.readNBytes(1_048_577) }
            require(text.size <= 1_048_576) { "Layout is too large" }
            publicProfile(JSONObject(String(text))).put("id", freshId()).put("revision", 0).put("app_id", app).put("default", false)
        }.onSuccess { imported = it }.onFailure { note = "Import failed: ${it.message}" }
    }
    LaunchedEffect(Unit) { sync() }
    BackHandler { if (editing != null) { editing = null } else onBack() }
    val edit = editing
    if (edit != null) {
        Column(Modifier.fillMaxSize()) {
            if (globalRun.isNotEmpty()) Row(verticalAlignment = Alignment.CenterVertically) {
                Text(note, Modifier.weight(1f))
                Button(onClick = { scope.launch { client.post("/v1/control-runs", JSONObject().put("operation", "cancel").put("id", globalRun)) } }) { Text("Stop") }
            }
            Box(Modifier.weight(1f)) { ProfileEditor(edit, cache, client, onCancel = { editing = null }, onSave = {
            runCatching { cache.save(it); cache.draft(null); editing = null; all = cache.profiles(); scope.launch { sync() } }
                .onFailure { note = it.message.orEmpty() }
        }, onTest = { globalTest(it) }) }
        }
    } else Column(Modifier.fillMaxSize()) {
        TopBar(title, onBack) { TextButton(onClick = { editing = profile("New layout", app) }) { Text("New") } }
        Row(Modifier.horizontalScroll(rememberScrollState())) {
            TextButton(onClick = { activity.awayOnPurpose = true; importFile.launch(arrayOf("application/json", "text/plain")) }) { Text("Import") }
            TextButton(onClick = { scope.launch { sync() } }) { Text("Sync") }
            cache.draft()?.takeIf { it.optString("app_id") == app }?.let { draft -> TextButton(onClick = { editing = draft }) { Text("Recover draft") } }
        }
        Text(note, Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.bodySmall)
        if (globalRun.isNotEmpty()) Button(onClick = { scope.launch { client.post("/v1/control-runs", JSONObject().put("operation", "cancel").put("id", globalRun)) } }) { Text("Stop") }
        LazyColumn(Modifier.weight(1f)) {
            items(all.filter { it.optString("app_id") == app }, key = { it.optString("id") }) { p ->
                Column(Modifier.fillMaxWidth().padding(12.dp)) {
                    Text(p.optString("name") + if (p.optBoolean("default")) " · Default" else "", style = MaterialTheme.typography.titleMedium)
                    Text("${p.optJSONArray("controls")?.length() ?: 0} controls" + if (p.optBoolean("dirty")) " · Saved on phone" else "", style = MaterialTheme.typography.bodySmall)
                    Row(Modifier.horizontalScroll(rememberScrollState())) {
                        TextButton(onClick = { editing = p.copyJson() }) { Text("Edit / Rename") }
                        TextButton(onClick = { editing = p.copyJson().put("id", freshId()).put("revision", 0).put("name", p.optString("name") + " copy").put("default", false) }) { Text("Duplicate") }
                        TextButton(onClick = { cache.save(p.copyJson().put("default", true)); all = cache.profiles(); scope.launch { sync() } }) { Text("Set default") }
                        TextButton(onClick = { exportText = publicProfile(p).toString(2); activity.awayOnPurpose = true; export.launch(p.optString("name") + ".json") }) { Text("Export") }
                        TextButton(onClick = { deleting = p }) { Text("Delete") }
                    }
                    if (app.isEmpty()) Row(Modifier.horizontalScroll(rememberScrollState())) {
                        p.optJSONArray("controls").rows().forEach { c -> OutlinedButton(enabled = globalRun.isEmpty(), onClick = { globalTest(c) }) { Text(c.optString("label")) } }
                    }
                }
            }
        }
    }
    imported?.let { p -> AlertDialog(onDismissRequest = { imported = null }, title = { Text("Review imported layout") }, text = {
        Column(Modifier.heightIn(max = 400.dp).verticalScroll(rememberScrollState())) {
            Text(p.optString("name"))
            p.optJSONArray("controls").rows().forEach { c ->
                Text(c.optString("label"), style = MaterialTheme.typography.titleSmall)
                c.optJSONArray("steps").rows().forEach { Text("${it.optString("kind")}: ${it.optString("value")}", style = MaterialTheme.typography.bodySmall) }
            }
        }
    }, confirmButton = { TextButton(onClick = { editing = p; imported = null }) { Text("Review in editor") } }, dismissButton = { TextButton(onClick = { imported = null }) { Text("Cancel") } }) }
    deleting?.let { p -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Delete ${p.optString("name")}?") },
        confirmButton = { TextButton(onClick = { cache.delete(p); all = cache.profiles(); deleting = null; scope.launch { sync() } }) { Text("Delete") } },
        dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel") } }) }

    globalConfirmation?.let { c -> AlertDialog(onDismissRequest = { globalConfirmation = null }, title = { Text("Confirm ${c.optString("label")}") },
        text = { Text("This includes an action that cannot be undone.") }, confirmButton = { TextButton(onClick = { globalConfirmation = null; globalTest(c, true) }) { Text("Run") } },
        dismissButton = { TextButton(onClick = { globalConfirmation = null }) { Text("Cancel") } }) }

}

@Composable
private fun ProfileEditor(original: JSONObject, cache: WorkspaceStore, client: LinkClient, onCancel: () -> Unit,
                          onSave: (JSONObject) -> Unit, onTest: (JSONObject) -> Unit) {
    var draft by remember(original.optString("id")) { mutableStateOf(original.copyJson()) }
    var selected by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf("") }
    var wide by remember { mutableStateOf(false) }
    var pageName by remember { mutableStateOf("") }
    fun update(next: JSONObject) { draft = next; cache.draft(next) }
    fun move(id: String, by: Int) {
        val list = draft.optJSONArray("controls").rows().toMutableList()
        val at = list.indexOfFirst { it.optString("id") == id }
        if (at >= 0 && at + by in list.indices) { val item = list.removeAt(at); list.add(at + by, item); update(draft.copyJson().put("controls", JSONArray(list))) }
    }
    fun save(copy: Boolean) {
        runCatching {
            val checked = publicProfile(draft)
            if (copy) checked.put("id", freshId()).put("revision", 0).put("default", false)
            onSave(checked)
        }.onFailure { error = it.message.orEmpty() }
    }
    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar("Edit layout", onCancel) { TextButton(onClick = { save(false) }) { Text("Save") } }
        OutlinedTextField(draft.optString("name"), { update(draft.copyJson().put("name", it.take(80))) }, label = { Text("Layout name") }, modifier = Modifier.fillMaxWidth().padding(8.dp))
        Row(Modifier.horizontalScroll(rememberScrollState())) {
            TextButton(onClick = { selected = control("New button", step("keys", "Return", if (draft.optString("app_id").isEmpty()) "global" else "app")) }) { Text("Add button") }
            TextButton(onClick = { wide = !wide }) { Text(if (wide) "Portrait preview" else "Landscape preview") }
            TextButton(onClick = { save(true) }) { Text("Save as") }
            TextButton(onClick = onCancel) { Text("Cancel") }
        }
        Row(Modifier.padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(pageName, { pageName = it.take(40) }, label = { Text("New page or group") }, modifier = Modifier.weight(1f), singleLine = true)
            TextButton(enabled = pageName.isNotBlank(), onClick = {
                val pages = draft.getJSONArray("pages"); val names = (0 until pages.length()).map { pages.getString(it) }
                if (pageName !in names && names.size < 12) update(draft.copyJson().put("pages", JSONArray(names + pageName)))
                pageName = ""
            }) { Text("Add") }
        }
        Text("Tap to edit · hold and drag to reorder · actions run only with Test action", Modifier.padding(8.dp), style = MaterialTheme.typography.bodySmall)
        if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
        Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
            Box(if (wide) Modifier.fillMaxWidth() else Modifier.widthIn(max = 360.dp)) {
                ControlGrid(draft, true, onPress = { selected = it.copyJson() }, editing = true, onMove = ::move)
            }
        }
    }
    selected?.let { c -> ControlEditor(c, draft, client, onDismiss = { selected = null }, onSave = { changed ->
        val list = draft.optJSONArray("controls").rows().toMutableList()
        val at = list.indexOfFirst { it.optString("id") == changed.optString("id") }
        if (at >= 0) list[at] = changed else list.add(changed)
        update(draft.copyJson().put("controls", JSONArray(list))); selected = null
    }, onDelete = {
        update(draft.copyJson().put("controls", JSONArray(draft.optJSONArray("controls").rows().filterNot { it.optString("id") == c.optString("id") }))); selected = null
    }, onTest = onTest, onMove = { move(c.getString("id"), it) }) }
}

@Composable
private fun ControlEditor(original: JSONObject, profile: JSONObject, client: LinkClient, onDismiss: () -> Unit,
                          onSave: (JSONObject) -> Unit, onDelete: () -> Unit, onTest: (JSONObject) -> Unit, onMove: (Int) -> Unit) {
    var label by remember { mutableStateOf(original.optString("label")) }
    var icon by remember { mutableStateOf(original.optString("icon")) }
    var wide by remember { mutableStateOf(original.optBoolean("wide")) }
    var emphasis by remember { mutableStateOf(original.optBoolean("emphasis")) }
    var page by remember { mutableStateOf(original.optString("page", "Main")) }
    var mode by remember { mutableStateOf(original.optString("mode", "button")) }
    var steps by remember { mutableStateOf(original.optJSONArray("steps").rows().map { it.copyJson() }) }
    var error by remember { mutableStateOf("") }
    var actions by remember { mutableStateOf(emptyList<JSONObject>()) }
    LaunchedEffect(Unit) { actions = client.get("/v1/actions")?.optJSONArray("actions").rows() }
    fun made() = original.copyJson().put("label", label).put("icon", icon).put("wide", wide).put("emphasis", emphasis)
        .put("page", page).put("mode", mode).put("steps", JSONArray(steps))
    fun validate(): JSONObject {
        val c = made()
        require(label.isNotBlank()) { "Give this control a label" }
        require(steps.size in 1..30) { "Use 1 to 30 steps" }
        steps.forEach { s ->
            if (s.optString("kind") == "keys") require(Protocol.keys(s.optString("value")) != null) { "Invalid shortcut" }
            if (s.optString("kind") == "delay") require(s.optString("value").toDoubleOrNull()?.let { it in 0.0..10.0 } == true) { "Delay must be 0–10 seconds" }
        }
        if (mode == "hold") require(steps.size == 1 && steps[0].optString("kind") == "keys" && !steps[0].optString("value").contains('+')) { "Hold needs one key" }
        if (mode in listOf("slider", "toggle")) require(steps.size == 1 && steps[0].optString("kind") == "volume") { "Sliders and toggles need readable volume state" }
        return c
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(Modifier.fillMaxSize().imePadding()) {
                TopBar("Edit button", onDismiss) { TextButton(onClick = { runCatching { onSave(validate()) }.onFailure { error = it.message.orEmpty() } }) { Text("Done") } }
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(label, { label = it.take(80) }, label = { Text("Label") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(icon, { icon = it.take(24) }, label = { Text("Icon or symbol") }, modifier = Modifier.fillMaxWidth())
                    Choice("Page", page, profile.getJSONArray("pages").let { a -> (0 until a.length()).map { a.getString(it) } }) { page = it }
                    Choice("Control", mode, listOf("button", "hold", "slider", "toggle")) { mode = it }
                    Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(wide, { wide = it }); Text("Wide"); Checkbox(emphasis, { emphasis = it }); Text("Blue emphasis") }
                    Row { TextButton(onClick = { onMove(-1) }) { Text("Move earlier") }; TextButton(onClick = { onMove(1) }) { Text("Move later") } }
                    Text("Steps · stop on failure · maximum 2 minutes", style = MaterialTheme.typography.titleMedium)
                    steps.forEachIndexed { index, s ->
                        fun change(next: JSONObject) { steps = steps.mapIndexed { i, old -> if (i == index) next else old } }
                        ElevatedCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text("Step ${index + 1}", Modifier.weight(1f))
                                    TextButton(enabled = index > 0, onClick = { val list = steps.toMutableList(); val item = list.removeAt(index); list.add(index - 1, item); steps = list }) { Text("↑") }
                                    TextButton(onClick = { steps = steps.filterIndexed { i, _ -> i != index } }) { Text("Remove") }
                                }
                                Choice("Action", s.optString("kind"), WorkspaceKinds) { change(s.copyJson().put("kind", it).put("value", "")) }
                                Choice("Target", s.optString("scope", "app"), if (profile.optString("app_id").isBlank()) listOf("global") else listOf("app", "global")) { change(s.copyJson().put("scope", it)) }
                                val kind = s.optString("kind")
                                if (kind == "launch") Choice("Open", s.optJSONObject("args")?.optString("type", "app") ?: "app", listOf("app", "file", "folder", "url")) {
                                    change(s.copyJson().put("args", JSONObject().put("type", it)))
                                }
                                if (kind == "action" && actions.isNotEmpty()) Choice("Registered action", s.optString("value"), actions.map { it.optString("id") }) { change(s.copyJson().put("value", it)) }
                                OutlinedTextField(s.optString("value"), { change(s.copyJson().put("value", it)) }, label = { Text(when (kind) {
                                    "keys" -> "Shortcut, e.g. ctrl+s"; "command" -> "Command"; "delay" -> "Seconds (0–10)";
                                    "layout" -> "Layout name or ID"; "wait-window" -> "Desktop app ID to wait for";
                                    "media" -> "play-pause, next, previous, seek"; "volume" -> "0–100, up, down, mute"; else -> "Value"
                                }) }, modifier = Modifier.fillMaxWidth())
                                if (kind == "media" && s.optString("value") == "seek") OutlinedTextField(
                                    (s.optJSONObject("args")?.optInt("seconds") ?: 0).toString(), { value ->
                                        value.toIntOrNull()?.let { change(s.copyJson().put("args", JSONObject().put("seconds", it))) }
                                    }, label = { Text("Seconds forward or backward") })
                                if (kind == "command") OutlinedTextField(s.optString("cwd", "~"), { change(s.copyJson().put("cwd", it)) }, label = { Text("Working directory") })
                                if (kind == "text") Row(verticalAlignment = Alignment.CenterVertically) {
                                    Checkbox(s.optBoolean("prompt"), { change(s.copyJson().put("prompt", it)) }); Text("Ask for text when pressed")
                                }
                                if (kind == "action") {
                                    val entry = actions.firstOrNull { it.optString("id") == s.optString("value") }
                                    Text(entry?.optString("say")?.ifBlank { entry.optString("id") } ?: "Action ID from the computer", style = MaterialTheme.typography.bodySmall)
                                    val args = s.optJSONObject("args") ?: JSONObject()
                                    var argName by remember(index, kind) { mutableStateOf("") }
                                    var argValue by remember(index, kind) { mutableStateOf("") }
                                    args.keys().asSequence().toList().forEach { key -> OutlinedTextField(args.optString(key), { change(s.copyJson().put("args", args.copyJson().put(key, it))) }, label = { Text(key) }) }
                                    OutlinedTextField(argName, { argName = it }, label = { Text("Parameter name") })
                                    OutlinedTextField(argValue, { argValue = it }, label = { Text("Parameter value") })
                                    TextButton(enabled = argName.isNotBlank(), onClick = { change(s.copyJson().put("args", args.copyJson().put(argName, argValue))); argName = ""; argValue = "" }) { Text("Add parameter") }
                                }
                            }
                        }
                    }
                    TextButton(enabled = steps.size < 30, onClick = { steps = steps + step("keys", "Return", if (profile.optString("app_id").isBlank()) "global" else "app") }) { Text("Add step") }
                    if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
                    Row {
                        OutlinedButton(onClick = { runCatching { onTest(validate()) }.onFailure { error = it.message.orEmpty() } }) { Text("Test action") }
                        TextButton(onClick = onDelete) { Text("Delete button") }
                    }
                }
            }
        }
    }
}

@Composable
private fun Choice(label: String, value: String, choices: List<String>, onChange: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.heightIn(min = 48.dp)) { Text("$label: $value") }
        DropdownMenu(expanded, onDismissRequest = { expanded = false }) {
            choices.forEach { choice -> DropdownMenuItem(text = { Text(choice) }, onClick = { onChange(choice); expanded = false }) }
        }
    }
}
