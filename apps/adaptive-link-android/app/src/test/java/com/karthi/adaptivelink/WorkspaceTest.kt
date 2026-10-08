package com.karthi.adaptivelink

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONArray
import org.json.JSONObject

class WorkspaceTest {
    @Test fun everyAdapterHasEditableValidatedProfiles() {
        for (adapter in listOf("browser", "files", "terminal", "editor", "media", "presenter", "universal")) {
            val layouts = starterLayouts("example.desktop", adapter)
            assertTrue(layouts.isNotEmpty())
            assertEquals(1, layouts.count { it.optBoolean("default") })
            for (p in layouts) {
                val clean = publicProfile(p)
                assertEquals("example.desktop", clean.getString("app_id"))
                assertTrue(clean.getJSONArray("controls").length() > 0)
                clean.getJSONArray("controls").rows().forEach { c ->
                    assertTrue(c.getString("id").isNotBlank())
                    c.getJSONArray("steps").rows().filter { it.getString("kind") == "keys" }.forEach {
                        assertNotNull("${it.getString("value")} must be a valid shortcut", Protocol.keys(it.getString("value")))
                    }
                }
            }
        }
    }
    @Test fun exportOnlyIncludesLayoutFields() {
        val dirty = profile("Reading", "firefox.desktop", listOf(control("Copy", step("keys", "ctrl+c"))))
            .put("private_key", "excluded").put("pairing", JSONObject().put("certificate", "excluded")).put("dirty", true)
        val exported = publicProfile(dirty)
        assertFalse(exported.has("private_key"))
        assertFalse(exported.has("pairing"))
        assertFalse(exported.has("dirty"))
        assertEquals(1, exported.getJSONArray("controls").length())
        assertEquals(exported.toString(), publicProfile(exported).toString())
    }
    @Test fun severalProfilesHaveDistinctStableIdentities() {
        val layouts = starterLayouts("code.desktop", "editor")
        assertEquals(listOf("Coding", "Debugging", "Writing"), layouts.map { it.getString("name") })
        assertEquals(3, layouts.map { it.getString("id") }.toSet().size)
        layouts.forEach { assertEquals(it.getString("id"), publicProfile(it).getString("id")) }
    }
    @Test fun copyingDoesNotMutateOriginalSteps() {
        val p = profile("Test", controls = listOf(control("Type", step("text", "original"))))
        val copy = publicProfile(p)
        copy.getJSONArray("controls").getJSONObject(0).getJSONArray("steps").getJSONObject(0).put("value", "changed")
        assertEquals("original", p.getJSONArray("controls").getJSONObject(0).getJSONArray("steps").getJSONObject(0).getString("value"))
    }
    @Test fun invalidImportsAreRejected() {
        for (bad in listOf(profile("Test").put("schema", 2), profile(""),
            profile("Test", controls = listOf(control("Empty"))),
            profile("Test", controls = listOf(control("Unknown", step("unsupported", "x")))))) {
            try { publicProfile(bad); fail("Invalid layout accepted") } catch (_: IllegalArgumentException) { }
        }
    }
}
