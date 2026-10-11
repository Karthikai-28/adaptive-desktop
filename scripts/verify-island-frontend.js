// Verification Suite for Dynamic Island Frontend (islandUI.js)
//
// Validates:
// 1. Module export bindings (IslandUI, IslandAnchor, IslandOverlay, IslandTheme, IslandState)
// 2. Lifecycle attachment and state orchestration
// 3. 4 MVP features (Quota, Task, Media, Timer) state rendering
// 4. Multi-activity satellite decoupling
// 5. Expand, contract, and pin operations
// 6. Theme switching ("liquid-glass" and "dark-precision")

const { DynamicIslandBackend } = require("../shell/adaptive-shell@local/dynamicIsland.js");
const { IslandUI, IslandTheme, IslandState } = require("../shell/adaptive-shell@local/islandUI.js");
const { IslandEvents, IslandPriority } = require("../shell/adaptive-shell@local/islandTypes.js");

let passed = 0;
let failed = 0;

function check(condition, message) {
    if (condition) {
        console.log("OK   frontend: " + message);
        passed++;
    } else {
        console.error("FAIL frontend: " + message);
        failed++;
    }
}

console.log("== Dynamic Island Frontend Verification Suite ==\n");

// -- Suite 1: Theme & State Constants --
check(IslandTheme.LIQUID_GLASS === "liquid-glass", "Theme constant LIQUID_GLASS is liquid-glass");
check(IslandTheme.DARK_PRECISION === "dark-precision", "Theme constant DARK_PRECISION is dark-precision");
check(IslandState.IDLE === "idle", "State constant IDLE is idle");
check(IslandState.COMPACT === "compact", "State constant COMPACT is compact");
check(IslandState.SATELLITE === "satellite", "State constant SATELLITE is satellite");
check(IslandState.EXPANDED === "expanded", "State constant EXPANDED is expanded");

// -- Suite 2: Instantiation & Initial Idle State --
const backend = new DynamicIslandBackend();
backend.init();
const ui = new IslandUI(null, { backend, theme: IslandTheme.LIQUID_GLASS });
ui.attach();

let state = ui.getState();
check(state.theme === "liquid-glass", "Default theme is liquid-glass");
check(state.uiState === IslandState.IDLE, "Initial state is IDLE (clock resting anchor)");

// -- Suite 3: Theme Switching --
ui.setTheme(IslandTheme.DARK_PRECISION);
check(ui.getTheme() === "dark-precision", "Theme switched to dark-precision");
check(ui.getState().theme === "dark-precision", "UI state reflects dark-precision");
ui.setTheme("invalid-theme");
check(ui.getTheme() === "dark-precision", "Invalid theme rejected, retains dark-precision");
ui.setTheme(IslandTheme.LIQUID_GLASS);
check(ui.getTheme() === "liquid-glass", "Theme restored to liquid-glass");

// -- Suite 4: Compact State Transitions (4 MVP Features) --

// 1. AI Quota Event
backend.emitEvent(IslandEvents.QUOTA_CAUTION_BREACH, {
    priority: IslandPriority.P2_HIGH,
    dwellMs: 6000,
    provider: "quota",
    message: "Claude 18% remaining",
    data: { percent: 18 },
});
state = ui.getState();
check(state.uiState === IslandState.COMPACT, "AI Quota event surfaces as COMPACT");
check(state.backend.surfacedEvent.type === IslandEvents.QUOTA_CAUTION_BREACH, "Surfaced event is QUOTA_CAUTION_BREACH");

// 2. Expansion into Expanded HUD
ui.expand("quota");
state = ui.getState();
check(state.uiState === IslandState.EXPANDED, "Expanded HUD is EXPANDED");
check(ui._overlay._activeCardType === "quota", "Active card type is quota");

// 3. Pinning
ui.setPinned(true);
check(ui.backend.getState().isPinned === true, "HUD is pinned open");
ui.contract();
check(ui.getState().uiState === IslandState.COMPACT, "Overlay hidden on contract");
ui.setPinned(false);
check(ui.backend.getState().isPinned === false, "HUD is unpinned");

// 4. Background AI Task
backend.emitEvent(IslandEvents.TASK_STARTED, {
    priority: IslandPriority.P3_NORMAL,
    dwellMs: 3000,
    provider: "task",
    title: "Task #14 - Dynamic Island UI",
    data: { title: "Task #14", agent: "Lena", progress: 45 },
});
ui.expand("tasks");
check(ui._overlay._activeCardType === "tasks", "Task card activated on expand");
ui.contract();

// 5. Media Event
backend.emitEvent(IslandEvents.TRACK_CHANGED, {
    priority: IslandPriority.P3_NORMAL,
    dwellMs: 3000,
    provider: "media",
    title: "Midnight City",
    artist: "M83",
});
ui.expand("media");
check(ui._overlay._activeCardType === "media", "Media card activated on expand");
ui.contract();

// 6. Focus Timer Event
backend.emitEvent(IslandEvents.TIMER_STARTED, {
    priority: IslandPriority.P3_NORMAL,
    dwellMs: 3000,
    provider: "timer",
    formatted: "18:42",
    label: "Pomodoro",
});
ui.expand("timer");
check(ui._overlay._activeCardType === "timer", "Timer card activated on expand");
ui.contract();

// -- Suite 5: Multi-Activity Satellite Decoupling --
backend.tasks._runningTasks.set(42, { id: 42, title: "Compile ROS", agent: "arjun" });
backend.media._currentTrack.isPlaying = true;
backend.media._currentTrack.title = "Solaris";
backend.media._currentTrack.artist = "Photek";

const multi = backend.getMultiActivitySlots();
check(multi.primary !== null, "Multi-activity primary slot allocated");
check(multi.primary.type === "task", "Primary slot prioritized AI Task");
check(multi.secondary !== null, "Multi-activity secondary slot allocated");
check(multi.secondary.type === "media", "Secondary slot allocated Now-Playing Media");

ui._updateUI();
state = ui.getState();
check(state.uiState === IslandState.SATELLITE, "Concurrent activities resolve to SATELLITE state");

// -- Suite 6: Teardown & Resource Cleanup --
ui.detach();
check(ui._attached === false, "UI successfully detached");
backend.destroy();
check(backend._destroyed === true, "Backend resources cleanly destroyed");

console.log("\n========================================");
console.log("Summary: " + passed + " passed, " + failed + " failed.");
console.log("========================================");

if (failed > 0) process.exit(1);
