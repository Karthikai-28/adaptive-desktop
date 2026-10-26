package com.karthi.adaptivelink

import org.json.JSONObject

/** Small, serializable navigation history used by the mobile shell. */
internal object ShellRoutes {
    val destinations = setOf("home", "drawer", "recents", "control", "connections", "native", "app", "continue")

    fun normalize(value: String): String {
        val routes = value.split('|').filter { it in destinations }.takeLast(24)
        return (routes.ifEmpty { listOf("home") }).joinToString("|")
    }

    fun push(value: String, destination: String): String {
        require(destination in destinations)
        val routes = normalize(value).split('|').toMutableList()
        if (routes.lastOrNull() != destination) routes.add(destination)
        return routes.takeLast(24).joinToString("|")
    }

    fun pop(value: String): Pair<String, String> {
        val routes = normalize(value).split('|').toMutableList()
        if (routes.size > 1) routes.removeAt(routes.lastIndex)
        val stack = routes.joinToString("|")
        return stack to routes.last()
    }
}

/** A reconnectable identity; server session IDs deliberately never enter it. */
internal data class ContinuityDescriptor(val computer: String, val appId: String, val windowId: Int,
                                         val presentation: String = "mirror", val destination: String = "continue") {
    fun json(): String = JSONObject().put("computer", computer).put("app_id", appId).put("window_id", windowId)
        .put("presentation", presentation).put("destination", destination).toString()

    fun matches(computer: String, appId: String, windowId: Int): Boolean =
        this.computer == computer && this.appId == appId && this.windowId == windowId

    companion object {
        fun parse(value: String): ContinuityDescriptor? = runCatching {
            val json = JSONObject(value)
            val presentation = json.optString("presentation", "mirror")
            ContinuityDescriptor(json.getString("computer"), json.getString("app_id"), json.getInt("window_id"),
                if (presentation == "phone-display") presentation else "mirror", json.optString("destination", "continue"))
        }.getOrNull()?.takeIf { it.computer.isNotBlank() && it.appId.isNotBlank() && it.windowId > 0 }
    }
}
