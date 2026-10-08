package com.karthi.adaptivelink

import android.content.Context
import android.util.AtomicFile
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

internal fun JSONArray?.rows(): List<JSONObject> = if (this == null) emptyList() else
    (0 until length()).mapNotNull { optJSONObject(it) }
internal fun JSONObject.copyJson() = JSONObject(toString())
internal fun freshId() = UUID.randomUUID().toString()
internal fun step(kind: String, value: String, scope: String = "app", args: JSONObject = JSONObject()) =
    JSONObject().put("kind", kind).put("value", value).put("scope", scope).put("args", args).put("cwd", "~")
internal fun control(label: String, vararg steps: JSONObject) = JSONObject().put("id", freshId())
    .put("label", label).put("page", "Main").put("mode", "button").put("steps", JSONArray(steps.toList()))
internal fun profile(name: String, app: String = "", controls: List<JSONObject> = emptyList()) = JSONObject()
    .put("schema", 1).put("id", freshId()).put("name", name).put("app_id", app).put("revision", 0)
    .put("pages", JSONArray(listOf("Main"))).put("controls", JSONArray(controls))

/** Explicit public projection: imports/exports cannot carry pairing or private cache data. */
internal fun publicProfile(raw: JSONObject): JSONObject {
    require(raw.optInt("schema", 1) == 1) { "Unsupported layout version" }
    val pages = raw.optJSONArray("pages") ?: JSONArray(listOf("Main"))
    require(pages.length() in 1..12) { "Use 1 to 12 pages" }
    val controls = raw.optJSONArray("controls").rows()
    require(controls.size <= 120) { "Too many controls" }
    val result = profile(raw.optString("name").take(80), raw.optString("app_id").take(250))
        .put("id", raw.optString("id").ifBlank { freshId() }).put("revision", raw.optInt("revision"))
        .put("default", raw.optBoolean("default")).put("pages", JSONArray(pages.toString()))
    require(result.getString("name").isNotBlank()) { "A layout needs a name" }
    result.put("controls", JSONArray(controls.map { c ->
        val steps = c.optJSONArray("steps").rows()
        require(steps.size in 1..30) { "Use 1 to 30 steps per control" }
        val label = c.optString("label").take(80)
        require(label.isNotBlank()) { "A control needs a label" }
        val made = control(label).put("id", c.optString("id").ifBlank { freshId() })
            .put("page", c.optString("page", "Main")).put("mode", c.optString("mode", "button"))
            .put("icon", c.optString("icon").take(24)).put("wide", c.optBoolean("wide"))
            .put("emphasis", c.optBoolean("emphasis"))
        made.put("steps", JSONArray(steps.map { s ->
            require(s.optString("kind") in WorkspaceKinds) { "Unknown action kind" }
            require(s.optString("value").length <= 8000) { "Action is too long" }
            step(s.getString("kind"), s.optString("value"), s.optString("scope", "app"),
                s.optJSONObject("args")?.copyJson() ?: JSONObject())
                .put("cwd", s.optString("cwd", "~")).put("prompt", s.optBoolean("prompt"))
        }))
        made
    }))
    return result
}
internal val WorkspaceKinds = listOf("keys", "text", "action", "launch", "command", "delay", "wait-window", "layout", "media", "volume")

/** Atomic phone cache, partitioned by the paired computer's certificate identity. */
internal class WorkspaceStore(context: Context, computer: Computer, legacy: Store) {
    private val disk = AtomicFile(File(context.filesDir, "workspace-${computer.fingerprint}.json"))
    private val syncLock = Mutex()
    private var data = try { JSONObject(disk.openRead().bufferedReader().use { it.readText() }) }
        catch (_: java.io.FileNotFoundException) { JSONObject() }
        catch (_: org.json.JSONException) {
            // Preserve malformed bytes for recovery before opening an empty cache.
            disk.baseFile.copyTo(File(disk.baseFile.path + ".recovery"), overwrite = true)
            JSONObject()
        }
    init {
        if (!data.has("profiles")) data.put("profiles", JSONArray())
        if (!data.optBoolean("migrated")) {
            data.put("legacy_backup", Control.listToJson(legacy.controls))
            if (legacy.controls.isNotEmpty()) {
                val controls = legacy.controls.map { c ->
                    val s = when (c.kind) {
                        "action" -> when (c.value) {
                            "play-pause", "next" -> step("media", c.value, "global")
                            "mute" -> step("volume", "mute", "global")
                            else -> step("action", c.value, "global")
                        }
                        else -> step(c.kind, c.value, "global")
                    }
                    control(c.label, s)
                }
                val migrated = profile("My controls", "", controls).put("dirty", true)
                data.getJSONArray("profiles").put(migrated)
            }
            data.put("migrated", true)
            persist()
        }
    }
    @Synchronized private fun persist() {
        val out = disk.startWrite()
        try { out.write(data.toString().toByteArray()); disk.finishWrite(out) }
        catch (error: Exception) { disk.failWrite(out); throw error }
    }
    @Synchronized fun profiles(): List<JSONObject> = data.optJSONArray("profiles").rows().map { it.copyJson() }
    @Synchronized fun save(value: JSONObject) {
        val item = publicProfile(value).put("dirty", true)
        data.put("profiles", JSONArray(profiles().filterNot { it.optString("id") == item.optString("id") } + item))
        persist()
    }
    @Synchronized fun draft(value: JSONObject?) { data.put("draft", value?.copyJson()); persist() }
    @Synchronized fun draft(): JSONObject? = data.optJSONObject("draft")?.copyJson()
    @Synchronized fun delete(item: JSONObject) {
        data.put("profiles", JSONArray(profiles().filterNot { it.optString("id") == item.optString("id") }))
        if (item.optInt("revision") > 0) data.put("deleted", (data.optJSONArray("deleted") ?: JSONArray()).put(
            JSONObject().put("id", item.getString("id")).put("revision", item.getInt("revision"))))
        persist()
    }
    @Synchronized fun selected(app: String): String = data.optJSONObject("selected")?.optString(app).orEmpty()
    @Synchronized fun select(app: String, id: String) {
        data.put("selected", (data.optJSONObject("selected") ?: JSONObject()).put(app, id)); persist()
    }
    @Synchronized fun favorites(): Set<String> = data.optJSONArray("favorites")?.let { a -> (0 until a.length()).map { a.getString(it) }.toSet() } ?: emptySet()
    @Synchronized fun favorite(id: String) {
        val all = favorites().toMutableSet(); if (!all.add(id)) all.remove(id)
        data.put("favorites", JSONArray(all.toList())); persist()
    }
    @Synchronized fun recent(id: String) {
        data.put("recent", JSONArray((listOf(id) + recents().filterNot { it == id }).take(20))); persist()
    }
    @Synchronized fun recents(): List<String> = data.optJSONArray("recent")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()
    @Synchronized fun catalog(): List<JSONObject> = data.optJSONArray("apps").rows()
    @Synchronized fun catalog(apps: JSONArray) { data.put("apps", apps); persist() }

    suspend fun sync(client: LinkClient): String = syncLock.withLock {
        var message = "Layouts saved on computer"
        val removed = synchronized(this) { data.optJSONArray("deleted").rows().map { it.copyJson() } }
        for (item in removed) {
            val reply = client.post("/v1/control-profiles", item.copyJson().put("operation", "delete")) ?: return@withLock "Offline · changes saved on phone"
            if (!reply.optBoolean("ok")) { message = reply.optString("error"); continue }
            synchronized(this) {
                data.put("deleted", JSONArray(data.optJSONArray("deleted").rows().filterNot { it.optString("id") == item.optString("id") })); persist()
            }
        }
        for (item in profiles().filter { it.optBoolean("dirty") }) {
            val reply = client.post("/v1/control-profiles", JSONObject().put("profile", publicProfile(item)).put("revision", item.optInt("revision")))
                ?: return@withLock "Offline · changes saved on phone"
            if (!reply.optBoolean("ok")) return@withLock reply.optString("error", "Could not synchronize layouts")
            val saved = reply.getJSONObject("profile")
            synchronized(this) {
                val current = profiles()
                // An edit made while the request was in flight stays pending.
                if (current.firstOrNull { it.optString("id") == item.optString("id") }?.toString() == item.toString()) {
                    data.put("profiles", JSONArray(current.filterNot { it.optString("id") == item.optString("id") } + saved))
                    persist()
                }
            }
            if (reply.optBoolean("conflict")) message = "Both edits kept · conflict copy created"
        }
        val remote = client.get("/v1/control-profiles") ?: return@withLock "Offline · changes saved on phone"
        if (!remote.optBoolean("ok")) return@withLock "This computer does not support saved layouts yet"
        synchronized(this) {
            val pending = profiles().filter { it.optBoolean("dirty") }
            val pendingIds = pending.map { it.optString("id") }.toSet()
            val deleted = data.optJSONArray("deleted").rows().map { it.optString("id") }.toSet()
            data.put("profiles", JSONArray(remote.optJSONArray("profiles").rows().filterNot { it.optString("id") in pendingIds || it.optString("id") in deleted } + pending))
            persist()
        }
        message
    }
}

internal fun starterLayouts(app: String, adapter: String): List<JSONObject> {
    fun keys(label: String, value: String) = control(label, step("keys", value))
    fun layout(name: String, vararg controls: JSONObject) = profile(name, app, controls.toList())
    val common = arrayOf(keys("Copy", "ctrl+c"), keys("Paste", "ctrl+v"), keys("Undo", "ctrl+z"), keys("Find", "ctrl+f"), keys("Escape", "Escape"))
    return when (adapter) {
        "browser" -> listOf(layout("Reading", keys("Back", "alt+Left"), keys("Forward", "alt+Right"), keys("Find", "ctrl+f"), keys("Zoom in", "ctrl+plus"), keys("Zoom out", "ctrl+minus")),
            layout("Research", keys("New tab", "ctrl+t"), keys("Next tab", "ctrl+Tab"), keys("Previous tab", "ctrl+shift+Tab"), keys("Reopen tab", "ctrl+shift+t"), keys("Address", "ctrl+l")),
            layout("Meetings", keys("Full screen", "F11"), keys("Next tab", "ctrl+Tab")))
        "editor" -> listOf(layout("Coding", keys("Save", "ctrl+s"), keys("Command palette", "ctrl+shift+p"), keys("Terminal", "ctrl+grave"), *common),
            layout("Debugging", keys("Continue", "F5"), keys("Step over", "F10"), keys("Step into", "F11"), keys("Breakpoint", "F9"), keys("Stop", "shift+F5")),
            layout("Writing", keys("Save", "ctrl+s"), keys("Select all", "ctrl+a"), *common))
        "terminal" -> listOf(layout("Terminal", keys("Interrupt", "ctrl+c"), keys("Clear", "ctrl+l"), keys("Tab", "Tab"), keys("History up", "Up"), keys("History down", "Down"), keys("Paste", "ctrl+shift+v")))
        "presenter" -> listOf(layout("Presenting", keys("Start", "F5"), keys("Next", "Right"), keys("Previous", "Left"), keys("Blank", "b"), keys("End", "Escape")),
            layout("Rehearsal", keys("Start here", "shift+F5"), keys("Next", "Right"), keys("Previous", "Left"), keys("End", "Escape")))
        "media" -> listOf(layout("Playback", control("Play / pause", step("media", "play-pause")),
            control("Back 10s", step("media", "seek", args = JSONObject().put("seconds", -10))), control("Forward 10s", step("media", "seek", args = JSONObject().put("seconds", 10))), control("Next", step("media", "next")), control("Previous", step("media", "previous")),
            control("Volume", step("volume", "50", "global")).put("mode", "slider"), control("Mute", step("volume", "mute", "global")).put("mode", "toggle")))
        "files" -> listOf(layout("Files", keys("Home", "alt+Home"), keys("Parent folder", "alt+Up"), keys("Search", "ctrl+f"), keys("New folder", "ctrl+shift+n"), *common))
        else -> listOf(layout("Basic", *common))
    }.mapIndexed { i, p -> p.put("default", i == 0) }
}
