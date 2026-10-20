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

// The panel clock must survive notifications, including long media titles.
const { IslandAnchor } = require("../shell/adaptive-shell@local/islandUI.js");
const anchor = new IslandAnchor(ui);
const actor = () => ({ visible: true, text: "", add_style_class_name() {}, remove_style_class_name() {} });
for (const key of ["_actor", "_pillButton", "_idleBox", "_idleClockLabel", "_idleSparkLabel",
    "_compactBox", "_compactIconLabel", "_compactTextLabel", "_compactSecondaryLabel",
    "_satelliteButton", "_satelliteIconLabel"])
    anchor[key] = actor();
anchor.syncClock("12:34");
for (const type of ["TASK_STARTED", "TRACK_CHANGED", "TIMER_STARTED", "QUOTA_CAUTION_BREACH"]) {
    anchor.renderState({ surfacedEvent: { type, payload: { title: "A long notification title" } }, quota: {} }, "liquid-glass");
    check(anchor._idleBox.visible && anchor._idleClockLabel.text === "12:34", `Clock remains visible for ${type}`);
    check(anchor._compactBox.visible, `Activity remains visible beside clock for ${type}`);
}
anchor.renderState({ quota: {}, multiActivity: {} }, "liquid-glass");
check(anchor._idleBox.visible && !anchor._compactBox.visible, "Returning to idle preserves clock and removes activity");

// Exercise an interrupted close using the actual overlay implementation.
const vm = require("vm");
const fs = require("fs");
const context = {
    module: { exports: {} }, require: require("module").createRequire(require.resolve("../shell/adaptive-shell@local/islandUI.js")),
    imports: { gi: { Clutter: { AnimationMode: { EASE_OUT_CUBIC: 1, EASE_OUT_QUAD: 2 } } },
        ui: { main: { layoutManager: {
            findMonitorForActor: () => ({ x: 1920, width: 1280 }),
        } } }, misc: { extensionUtils: { getCurrentExtension: () => null } } },
    global: { stage: { connect: () => 1, disconnect() {} } },
};
vm.runInNewContext(fs.readFileSync(require.resolve("../shell/adaptive-shell@local/islandUI.js"), "utf8"), context);
const overlay = new context.module.exports.IslandOverlay(ui);
let transition;
overlay._actor = {
    opacity: 255, width: 400, visible: true,
    set_width(w) { this.width = w; }, set_position(x, y) { this.x = x; this.y = y; },
    remove_all_transitions() {}, ease(options) { transition = options; },
};
const anchorActor = {
    get_transformed_position: () => [1920, 100], get_transformed_size: () => [100, 24],
    connect: () => 1,
};
overlay.showOverlay(anchorActor);
check(overlay._actor.x === 1932 && overlay._actor.y === 132, "Overlay respects monitor edge and panel vertical offset");
overlay.hideOverlay();
const closing = transition;
overlay.showOverlay(anchorActor);
closing.onComplete();
check(overlay._actor.visible, "Interrupted closing callback cannot hide a reopened card");
check(transition.duration === 220 && transition.translation_y === 0, "Reopening settles to the anchor without bounce");

// Clicking the island opens the shared center even with an active event.
const centerMenu = { isOpen: false, toggle() { this.isOpen = !this.isOpen; } };
context.imports.ui.main.panel = { statusArea: { dateMenu: { menu: centerMenu } } };
const centerUI = new context.module.exports.IslandUI(null, { backend });
centerUI.toggleCenter();
check(centerUI.isCenterOpen(), "Island opens the calendar and system notification center");
centerUI.expand("timer");
check(!centerUI.isExpanded(), "Floating preview stays closed while unified center is open");
centerUI.toggleCenter();
check(!centerUI.isCenterOpen(), "Second click closes the unified center");

const usageOverlay = new context.module.exports.IslandOverlay(ui);
usageOverlay._titleIcon = {};
usageOverlay._titleLabel = {};
usageOverlay._badgeLabel = {};
const nowS = Date.now() / 1000;
usageOverlay._renderQuotaData({ quota: { codex: { ts: nowS, windows: [
    { label: "5h", used: 100, resetsAt: nowS + 3600 },
    { label: "Weekly", used: 75, resetsAt: nowS - 10 },
] } } });
const usage = usageOverlay._usageModel;
check(usage[0].rows[0].text === "100% used", "Exhausted Codex window shows 100% used");
check(usage[0].rows[1].text === "reset, awaiting update", "Ended Codex window never invents a refill");
check(usage[1].unavailable && usage[1].rows.length === 0, "Missing Claude limits never display sample values");
check(usageOverlay._badgeLabel.text === "USED", "Usage card is labelled as used");

// -- Suite 5b: Overview, tab badges, and drawing only what is visible --
const { describeOverview, describeBadges } = require("../shell/adaptive-shell@local/islandUI.js");
const ovState = {
    quota: { claude: { ts: nowS, windows: [{ label: "5h", used: 62, resetsAt: nowS + 3600 },
        { label: "Weekly", used: 91, resetsAt: nowS + 86400 }] } },
    tasks: [{ id: 1, title: "Index repo" }, { id: 2, title: "Write docs" }],
    media: { title: "Teardrop", artist: "Massive Attack", isPlaying: true },
    timer: { status: "RUNNING", formatted: "18:42", label: "Pomodoro" },
};
const ov = describeOverview(ovState, nowS);
check(ov.quota.text === "Claude Weekly · 91% used" && ov.quota.level === "caution", "Overview names the tightest AI limit");
check(ov.tasks.text === "2 running", "Overview counts running tasks");
check(ov.media.text === "Teardrop · Massive Attack", "Overview shows the current track");
check(ov.timer.text.startsWith("18:42 left"), "Overview shows focus time remaining");
check(describeOverview({ tasks: [{ title: "Secret" }], isScreenSharing: true }).tasks.text === "1 running",
    "Overview hides a task title while the screen is shared");
const privateOverview = describeOverview({
    quota: ovState.quota,
    media: { title: "Private song", artist: "Private artist", isPlaying: true },
    isScreenSharing: true,
});
check(privateOverview.quota.text === "Hidden while sharing" &&
    privateOverview.media.text === "Media playing",
"Overview hides AI usage and media metadata while the screen is shared");
const badges = describeBadges(ovState, nowS);
check(badges.tasks.text === "2" && badges.media.text === "▶" && badges.timer.text === "18:42",
    "Tabs carry live badges: task count, playing, countdown");
check(badges.quota.text === "!" && badges.quota.level === "caution", "AI usage tab warns when a limit is tight");
const quiet = describeBadges({ timer: { status: "IDLE" } }, nowS);
check(!quiet.tasks.text && !quiet.media.text && !quiet.timer.text && !quiet.quota.text, "Idle features show no badge");

let overlayRenders = 0;
const realRender = ui._overlay.renderState.bind(ui._overlay);
ui._overlay.renderState = (...args) => { overlayRenders++; return realRender(...args); };
ui.contract();
ui._updateUI();
check(overlayRenders === 0, "A closed floating card is not redrawn on state changes");
ui.expand("media");
check(overlayRenders === 1 && ui._overlay._activeCardType === "media", "Opening the card draws it once, on the right card");
ui.contract();
ui._overlay.renderState = realRender;

const uiSource = fs.readFileSync(require.resolve("../shell/adaptive-shell@local/islandUI.js"), "utf8");
check(!/shade\._[a-zA-Z]/.test(uiSource) && uiSource.includes("mountActivityCenter"),
    "Activity Center mounts through the Shade API, not a private field");
check(!/Task #14|Midnight City|Agent: Lena/.test(uiSource), "No demo data is left in the cards");
check(uiSource.includes('notify::screencast-in-progress') && uiSource.includes('setDormant'),
    "Screen recording privacy and dormant quota polling are wired to the live UI");
check(!uiSource.includes('MAX_TASK_ROWS'), "The Tasks card renders every running task");
check(!/new St\.Button\(\{[^}]*can_focus: false/.test(uiSource.slice(uiSource.indexOf("var IslandOverlay"))),
    "Every card control can take keyboard focus");

// -- Suite 6: Teardown & Resource Cleanup --
ui.detach();
check(ui._attached === false, "UI successfully detached");
backend.destroy();
check(backend._destroyed === true, "Backend resources cleanly destroyed");

console.log("\n========================================");
console.log("Summary: " + passed + " passed, " + failed + " failed.");
console.log("========================================");

if (failed > 0) process.exit(1);
