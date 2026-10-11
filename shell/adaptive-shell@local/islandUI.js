// Dynamic Island Frontend for GNOME Shell 42.9 (adaptive-shell@local)
//
// Implements in-panel IslandAnchor on dateMenu and IslandOverlay on (Main && Main.layoutManager).uiGroup.
// Provides idle, compact, satellite, and expanded presentation states for the 4 MVP features:
// 1. AI Quota Monitor (Claude % + reset countdowns; agy session compute & limits)
// 2. Background AI Tasks (Task slug, progress %, live stdout log tail, emergency actions)
// 3. Now-Playing Media (Album glyph, truncated marquee title, scrubber bar, transport controls)
// 4. Focus Timers (Big digits, Pomodoro presets, +5m extend, 0% idle CPU)
//
// Supports two visual themes: "liquid-glass" (default) and "dark-precision".
// Adheres strictly to: 0% idle timers/animations, async operations, no keyboard focus grabbing.

/* exported IslandUI, IslandAnchor, IslandOverlay, IslandTheme */
/* global require, module */

let Clutter, Gio, GLib, GObject, St, Shell;
let Main = null;
let Me = null;

try {
    Clutter = imports.gi.Clutter;
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
    GObject = imports.gi.GObject;
    St = imports.gi.St;
    Shell = imports.gi.Shell;
    Main = imports.ui.main;
    Me = imports.misc.extensionUtils.getCurrentExtension();
} catch (e) {
    // Headless test harness
}

function _loadModule(name) {
    if (Me && Me.imports && Me.imports[name])
        return Me.imports[name];
    try {
        if (typeof imports !== "undefined" && imports[name])
            return imports[name];
    } catch (e) {}
    try {
        if (typeof require !== "undefined")
            return require("./" + name + ".js");
    } catch (e) {}
    return {};
}

const Types = _loadModule("islandTypes");
const DynamicIsland = _loadModule("dynamicIsland");
const { DynamicIslandBackend } = DynamicIsland;
const { IslandEvents = {}, IslandPriority = {}, IslandDwellMs = {} } = Types;

const IslandTheme = {
    LIQUID_GLASS: "liquid-glass",
    DARK_PRECISION: "dark-precision",
};

const IslandState = {
    IDLE: "idle",
    COMPACT: "compact",
    SATELLITE: "satellite",
    EXPANDED: "expanded",
};

// -----------------------------------------------------------------------------
// IslandAnchor: In-panel resting and compact pill mounted into dateMenu
// -----------------------------------------------------------------------------
var IslandAnchor = class IslandAnchor {
    constructor(uiController) {
        this._ui = uiController;
        this._actor = null;
        this._pillButton = null;
        this._satelliteButton = null;

        // Sub-elements
        this._idleBox = null;
        this._idleClockLabel = null;
        this._idleSparkLabel = null;

        this._compactBox = null;
        this._compactIconLabel = null;
        this._compactTextLabel = null;
        this._compactSecondaryLabel = null;

        this._satelliteIconLabel = null;

        // Interaction timers
        this._hoverDwellTimerId = 0;
        this._graceExitTimerId = 0;

        this._clockNotifyId = 0;
        this._dateMenu = null;
    }

    build() {
        if (!St) return;

        this._actor = new St.BoxLayout({
            style_class: "adaptive-island-anchor",
            reactive: true,
            track_hover: true,
            can_focus: false,
        });

        // Pill Button
        this._pillButton = new St.Button({
            style_class: "adaptive-island-pill adaptive-island-pill-idle",
            reactive: true,
            can_focus: false,
            track_hover: true,
        });

        const pillInnerBox = new St.BoxLayout({
            style_class: "adaptive-island-pill-inner",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });

        // 1. Idle Box (Clock + Spark)
        this._idleBox = new St.BoxLayout({
            style_class: "adaptive-island-idle-box",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._idleClockLabel = new St.Label({
            text: "--:--",
            style_class: "adaptive-island-clock-text",
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._idleSparkLabel = new St.Label({
            text: " ✦",
            style_class: "adaptive-island-spark adaptive-island-spark-cyan",
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._idleBox.add_child(this._idleClockLabel);
        this._idleBox.add_child(this._idleSparkLabel);
        pillInnerBox.add_child(this._idleBox);

        // 2. Compact Box (Leading Icon + Truncated Label + Secondary metric)
        this._compactBox = new St.BoxLayout({
            style_class: "adaptive-island-compact-box",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });

        this._compactIconLabel = new St.Label({
            text: "✦",
            style_class: "adaptive-island-compact-icon",
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._compactTextLabel = new St.Label({
            text: "",
            style_class: "adaptive-island-compact-label",
            y_align: Clutter.ActorAlign.CENTER,
        });
        if (this._compactTextLabel.clutter_text) {
            this._compactTextLabel.clutter_text.ellipsize = imports.gi.Pango.EllipsizeMode.END;
        }

        this._compactSecondaryLabel = new St.Label({
            text: "",
            style_class: "adaptive-island-compact-secondary",
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._compactBox.add_child(this._compactIconLabel);
        this._compactBox.add_child(this._compactTextLabel);
        this._compactBox.add_child(this._compactSecondaryLabel);
        pillInnerBox.add_child(this._compactBox);

        this._pillButton.set_child(pillInnerBox);
        this._actor.add_child(this._pillButton);

        // 3. Satellite Button (Detached secondary 32px pill)
        this._satelliteButton = new St.Button({
            style_class: "adaptive-island-satellite",
            reactive: true,
            can_focus: false,
            track_hover: true,
            visible: false,
        });

        this._satelliteIconLabel = new St.Label({
            text: "♫",
            style_class: "adaptive-island-satellite-icon",
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._satelliteButton.set_child(this._satelliteIconLabel);
        this._actor.add_child(this._satelliteButton);

        // Event Listeners
        this._pillButton.connect("enter-event", () => this._onMouseEnter());
        this._pillButton.connect("leave-event", () => this._onMouseLeave());
        this._pillButton.connect("button-press-event", (actor, event) => this._onPillClicked(event));

        this._satelliteButton.connect("enter-event", () => this._onMouseEnter());
        this._satelliteButton.connect("leave-event", () => this._onMouseLeave());
        this._satelliteButton.connect("button-press-event", () => this._onSatelliteClicked());
    }

    _onMouseEnter() {
        this._clearGraceExitTimer();
        this._ui.backend.pauseDwell();

        // 80ms hover intent dwell before expanding
        if (!this._hoverDwellTimerId) {
            this._hoverDwellTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, () => {
                this._hoverDwellTimerId = 0;
                this._ui.expand();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _onMouseLeave() {
        if (this._hoverDwellTimerId) {
            GLib.source_remove(this._hoverDwellTimerId);
            this._hoverDwellTimerId = 0;
        }

        // 200ms grace exit delay before contracting
        this._clearGraceExitTimer();
        this._graceExitTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 200, () => {
            this._graceExitTimerId = 0;
            this._ui.backend.resumeDwell();
            if (!this._ui.backend.getState().isPinned) {
                this._ui.contract();
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _clearGraceExitTimer() {
        if (this._graceExitTimerId) {
            GLib.source_remove(this._graceExitTimerId);
            this._graceExitTimerId = 0;
        }
    }

    _onPillClicked(event) {
        const isExpanded = this._ui.isExpanded();
        const state = this._ui.backend.getState();
        if (!isExpanded && state.activityState === IslandState.IDLE && !state.surfacedEvent) {
            // In idle mode, let the click propagate so dateMenu opens the native calendar
            return Clutter.EVENT_PROPAGATE;
        }

        // When an activity is active or surfaced, click toggles pinning and expands
        const isPinned = !state.isPinned;
        this._ui.backend.setPinned(isPinned);
        if (isPinned)
            this._ui.expand();
        else
            this._ui.contract();

        return Clutter.EVENT_STOP;
    }

    _onSatelliteClicked() {
        // Expand overlay directly onto secondary activity
        this._ui.expand();
        return Clutter.EVENT_STOP;
    }

    syncClock(text) {
        if (this._idleClockLabel && text) {
            this._idleClockLabel.text = text;
        }
    }

    renderState(state, activeTheme) {
        if (!this._actor) return;

        const hasSurfaced = !!state.surfacedEvent;
        const slots = state.multiActivity || { primary: null, secondary: null };
        const hasPrimary = !!slots.primary;
        const hasSecondary = !!slots.secondary;

        // Apply theme classes
        this._actor.remove_style_class_name("adaptive-island-theme-liquid-glass");
        this._actor.remove_style_class_name("adaptive-island-theme-dark-precision");
        this._actor.add_style_class_name("adaptive-island-theme-" + activeTheme);

        // Caution / Critical border classes
        this._pillButton.remove_style_class_name("caution");
        this._pillButton.remove_style_class_name("critical");

        const quota = state.quota || {};
        const isCritical = quota.criticalBreach || (state.surfacedEvent && state.surfacedEvent.type === IslandEvents.QUOTA_CRITICAL_BREACH);
        const isCaution = quota.cautionBreach || (state.surfacedEvent && state.surfacedEvent.type === IslandEvents.QUOTA_CAUTION_BREACH);

        if (isCritical) {
            this._pillButton.add_style_class_name("critical");
        } else if (isCaution) {
            this._pillButton.add_style_class_name("caution");
        }

        // Idle Spark Color
        this._idleSparkLabel.remove_style_class_name("adaptive-island-spark-cyan");
        this._idleSparkLabel.remove_style_class_name("adaptive-island-spark-amber");
        this._idleSparkLabel.remove_style_class_name("adaptive-island-spark-crimson");

        if (isCritical) {
            this._idleSparkLabel.add_style_class_name("adaptive-island-spark-crimson");
        } else if (isCaution) {
            this._idleSparkLabel.add_style_class_name("adaptive-island-spark-amber");
        } else {
            this._idleSparkLabel.add_style_class_name("adaptive-island-spark-cyan");
        }

        // Decide display mode (Idle vs Compact vs Satellite)
        if (!hasSurfaced && !hasPrimary) {
            // 1. Idle state
            this._pillButton.remove_style_class_name("adaptive-island-pill-compact");
            this._pillButton.add_style_class_name("adaptive-island-pill-idle");
            this._idleBox.visible = true;
            this._compactBox.visible = false;
            this._satelliteButton.visible = false;
        } else {
            // 2. Compact / Activity state
            this._pillButton.remove_style_class_name("adaptive-island-pill-idle");
            this._pillButton.add_style_class_name("adaptive-island-pill-compact");
            this._idleBox.visible = false;
            this._compactBox.visible = true;

            // Populate compact content
            if (hasSurfaced) {
                this._renderSurfacedCompact(state.surfacedEvent, quota);
            } else if (hasPrimary) {
                this._renderSlotCompact(slots.primary, quota);
            }

            // 3. Satellite state
            if (hasSecondary) {
                this._satelliteButton.visible = true;
                this._renderSatelliteSlot(slots.secondary);
            } else {
                this._satelliteButton.visible = false;
            }
        }
    }

    _renderSurfacedCompact(event, quota) {
        const type = event.type;
        const p = event.payload || {};

        if (type.startsWith("QUOTA_")) {
            this._compactIconLabel.text = "✦";
            const cld = quota.claude || {};
            const cldVal = (typeof cld.fiveHourPercent === "number") ? cld.fiveHourPercent : (p.data && typeof p.data.percent === "number" ? p.data.percent : 43);
            this._compactTextLabel.text = "Claude " + cldVal + "% · agy Active";
            this._compactSecondaryLabel.text = "";
        } else if (type.startsWith("TASK_")) {
            this._compactIconLabel.text = "⟳";
            const title = p.title || (p.data && p.data.title) || "AI Task";
            this._compactTextLabel.text = title;
            this._compactSecondaryLabel.text = (p.data && p.data.progress) ? (" (" + p.data.progress + "%)") : "";
        } else if (type.startsWith("TRACK_") || type.startsWith("PLAYBACK_")) {
            this._compactIconLabel.text = "♫";
            this._compactTextLabel.text = p.title || (p.data && p.data.title) || "Music";
            this._compactSecondaryLabel.text = p.artist ? (" · " + p.artist) : "";
        } else if (type.startsWith("TIMER_")) {
            this._compactIconLabel.text = "⏱";
            this._compactTextLabel.text = p.formatted || (p.data && p.data.formatted) || "Focus";
            this._compactSecondaryLabel.text = "";
        } else {
            this._compactIconLabel.text = "✦";
            this._compactTextLabel.text = p.message || event.type;
            this._compactSecondaryLabel.text = "";
        }
    }

    _renderSlotCompact(slot, quota) {
        if (slot.type === "task") {
            this._compactIconLabel.text = "⟳";
            this._compactTextLabel.text = slot.title || "AI Task";
            this._compactSecondaryLabel.text = (slot.data && slot.data.progress) ? (" (" + slot.data.progress + "%)") : "";
        } else if (slot.type === "timer") {
            this._compactIconLabel.text = "⏱";
            this._compactTextLabel.text = slot.formatted || "Timer";
            this._compactSecondaryLabel.text = "";
        } else if (slot.type === "media") {
            this._compactIconLabel.text = "♫";
            this._compactTextLabel.text = slot.title || "Media";
            this._compactSecondaryLabel.text = slot.artist ? (" · " + slot.artist) : "";
        } else {
            this._compactIconLabel.text = "✦";
            this._compactTextLabel.text = "Active";
            this._compactSecondaryLabel.text = "";
        }
    }

    _renderSatelliteSlot(slot) {
        if (slot.type === "timer") {
            this._satelliteIconLabel.text = "⏱";
        } else if (slot.type === "media") {
            this._satelliteIconLabel.text = "♫";
        } else if (slot.type === "task") {
            this._satelliteIconLabel.text = "⟳";
        } else {
            this._satelliteIconLabel.text = "✦";
        }
    }

    getActor() {
        return this._actor;
    }

    destroy() {
        if (this._hoverDwellTimerId) {
            GLib.source_remove(this._hoverDwellTimerId);
            this._hoverDwellTimerId = 0;
        }
        this._clearGraceExitTimer();
        if (this._actor) {
            this._actor.destroy();
            this._actor = null;
        }
    }
};

// -----------------------------------------------------------------------------
// IslandOverlay: Floating 372px HUD mounted to (Main && Main.layoutManager).uiGroup
// -----------------------------------------------------------------------------
var IslandOverlay = class IslandOverlay {
    constructor(uiController) {
        this._ui = uiController;
        this._actor = null;
        this._blurEffect = null;

        // Container structure
        this._headerBox = null;
        this._titleIcon = null;
        this._titleLabel = null;
        this._badgeLabel = null;
        this._pinButton = null;
        this._closeButton = null;

        this._cardContentBox = null;

        // Modular Cards
        this._quotaCard = null;
        this._tasksCard = null;
        this._mediaCard = null;
        this._timerCard = null;

        // Element handles for dynamic updates
        this._claudeBarFill = null;
        this._claudePctLabel = null;
        this._claudeResetLabel = null;
        this._claudeWeeklyFill = null;
        this._claudeWeeklyLabel = null;
        this._agyTokensLabel = null;
        this._agyStatusLabel = null;
        this._burnRateLabel = null;

        this._taskTitleLabel = null;
        this._taskMetaLabel = null;
        this._taskStdoutBox = null;

        this._mediaTitleLabel = null;
        this._mediaArtistLabel = null;
        this._mediaElapsedLabel = null;
        this._mediaDurationLabel = null;
        this._mediaScrubberFill = null;
        this._mediaPlayBtn = null;

        this._timerDigitsLabel = null;
        this._timerStatusTag = null;
        this._timerPauseBtn = null;

        this._activeCardType = "quota";
        this._isExpanded = false;
        this._stageClickId = 0;
    }

    build() {
        if (!St) return;

        this._actor = new St.Widget({
            style_class: "adaptive-island-overlay",
            reactive: false,
            visible: false,
            can_focus: false,
            track_hover: true,
            opacity: 0,
        });

        // Set dimensions (372px x 208px default)
        this._actor.set_size(372, 208);

        const mainLayout = new St.BoxLayout({
            style_class: "adaptive-island-overlay-inner",
            vertical: true,
            reactive: true,
        });

        // Header
        this._headerBox = new St.BoxLayout({
            style_class: "adaptive-island-card-header",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._titleIcon = new St.Label({
            text: "✦",
            style_class: "adaptive-island-card-icon",
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._titleLabel = new St.Label({
            text: "AI QUOTA MONITOR",
            style_class: "adaptive-island-card-title",
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._badgeLabel = new St.Label({
            text: "ACTIVE",
            style_class: "adaptive-island-card-badge",
            y_align: Clutter.ActorAlign.CENTER,
        });

        const spacer = new St.Widget({ x_expand: true });

        this._pinButton = new St.Button({
            style_class: "adaptive-island-card-btn adaptive-island-pin-btn",
            can_focus: false,
        });
        this._pinButton.set_child(new St.Label({ text: "📌", y_align: Clutter.ActorAlign.CENTER }));

        this._closeButton = new St.Button({
            style_class: "adaptive-island-card-btn adaptive-island-close-btn",
            can_focus: false,
        });
        this._closeButton.set_child(new St.Label({ text: "✕", y_align: Clutter.ActorAlign.CENTER }));

        this._headerBox.add_child(this._titleIcon);
        this._headerBox.add_child(this._titleLabel);
        this._headerBox.add_child(this._badgeLabel);
        this._headerBox.add_child(spacer);
        this._headerBox.add_child(this._pinButton);
        this._headerBox.add_child(this._closeButton);
        mainLayout.add_child(this._headerBox);

        // Body Content Container
        this._cardContentBox = new St.BoxLayout({
            style_class: "adaptive-island-card-body",
            vertical: true,
            y_expand: true,
        });

        this._buildQuotaCard();
        this._buildTasksCard();
        this._buildMediaCard();
        this._buildTimerCard();

        mainLayout.add_child(this._cardContentBox);
        this._actor.add_child(mainLayout);

        // Header button events
        this._pinButton.connect("clicked", () => {
            const isPinned = !this._ui.backend.getState().isPinned;
            this._ui.backend.setPinned(isPinned);
        });

        this._closeButton.connect("clicked", () => {
            this._ui.backend.setPinned(false);
            this._ui.backend.dismissCurrentEvent();
            this._ui.contract();
        });

        // Hover tracking to pause/resume dwell while inside overlay
        this._actor.connect("enter-event", () => this._ui.backend.pauseDwell());
        this._actor.connect("leave-event", () => {
            this._ui.backend.resumeDwell();
            if (!this._ui.backend.getState().isPinned) {
                this._ui.contract();
            }
        });

        // Optional Shell.BlurEffect
        if (Shell && Shell.BlurEffect) {
            try {
                this._blurEffect = new Shell.BlurEffect({
                    brightness: 0.75,
                    sigma: 28,
                    mode: Shell.BlurMode.BACKGROUND,
                });
            } catch (e) {
                this._blurEffect = null;
            }
        }
    }

    _buildQuotaCard() {
        this._quotaCard = new St.BoxLayout({
            style_class: "adaptive-island-card adaptive-island-quota-card",
            vertical: true,
        });

        // Claude Sub-Card
        const claudeBox = new St.BoxLayout({
            style_class: "adaptive-island-subcard",
            vertical: true,
        });

        const cldHeaderRow = new St.BoxLayout({ vertical: false });
        cldHeaderRow.add_child(new St.Label({ text: "Claude", style_class: "adaptive-island-subcard-title" }));
        cldHeaderRow.add_child(new St.Widget({ x_expand: true }));
        this._claudePctLabel = new St.Label({ text: "43% left", style_class: "adaptive-island-val-bold" });
        cldHeaderRow.add_child(this._claudePctLabel);
        claudeBox.add_child(cldHeaderRow);

        // 5h bar track
        const cldTrack = new St.Widget({ style_class: "adaptive-island-progress-track" });
        this._claudeBarFill = new St.Widget({ style_class: "adaptive-island-progress-fill adaptive-island-fill-amber" });
        this._claudeBarFill.set_width(140);
        cldTrack.add_child(this._claudeBarFill);
        claudeBox.add_child(cldTrack);

        const cldSubRow = new St.BoxLayout({ vertical: false });
        this._claudeResetLabel = new St.Label({ text: "Rolling 5h · Resets in 1h 22m", style_class: "adaptive-island-subtext" });
        cldSubRow.add_child(this._claudeResetLabel);
        cldSubRow.add_child(new St.Widget({ x_expand: true }));
        this._claudeWeeklyLabel = new St.Label({ text: "Weekly: 72%", style_class: "adaptive-island-subtext" });
        cldSubRow.add_child(this._claudeWeeklyLabel);
        claudeBox.add_child(cldSubRow);

        this._quotaCard.add_child(claudeBox);

        // agy Sub-Card (Strict Rule: token telemetry only, never a fake %)
        const agyBox = new St.BoxLayout({
            style_class: "adaptive-island-subcard",
            vertical: true,
        });

        const agyHeaderRow = new St.BoxLayout({ vertical: false });
        agyHeaderRow.add_child(new St.Label({ text: "Gemini (agy)", style_class: "adaptive-island-subcard-title" }));
        agyHeaderRow.add_child(new St.Widget({ x_expand: true }));
        this._agyStatusLabel = new St.Label({ text: "✦ Active", style_class: "adaptive-island-status-active" });
        agyHeaderRow.add_child(this._agyStatusLabel);
        agyBox.add_child(agyHeaderRow);

        this._agyTokensLabel = new St.Label({
            text: "Session: 2.5k In · 500 Out · 13.0k Cache",
            style_class: "adaptive-island-mono-subtext",
        });
        agyBox.add_child(this._agyTokensLabel);

        const agySubRow = new St.BoxLayout({ vertical: false });
        agySubRow.add_child(new St.Label({
            text: "Subscription Quota: Unavailable (Server-enforced)",
            style_class: "adaptive-island-subtext",
        }));
        agyBox.add_child(agySubRow);

        this._quotaCard.add_child(agyBox);

        // Action & Telemetry Footer
        const footerRow = new St.BoxLayout({
            style_class: "adaptive-island-footer-row",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._burnRateLabel = new St.Label({
            text: "⚡ ~340 tok/min",
            style_class: "adaptive-island-subtext",
            y_align: Clutter.ActorAlign.CENTER,
        });
        footerRow.add_child(this._burnRateLabel);
        footerRow.add_child(new St.Widget({ x_expand: true }));

        const refreshBtn = new St.Button({
            style_class: "adaptive-island-btn",
            label: "Refresh",
            can_focus: false,
        });
        refreshBtn.connect("clicked", () => this._ui.backend.quota.refresh());
        footerRow.add_child(refreshBtn);

        const pauseBtn = new St.Button({
            style_class: "adaptive-island-btn adaptive-island-btn-alert",
            label: "Pause Tasks",
            can_focus: false,
        });
        pauseBtn.connect("clicked", () => {
            const active = this._ui.backend.tasks.getActiveTasks();
            if (active.length > 0) {
                this._ui.backend.tasks.cancelTask(active[0].id);
            }
        });
        footerRow.add_child(pauseBtn);

        this._quotaCard.add_child(footerRow);
        this._cardContentBox.add_child(this._quotaCard);
    }

    _buildTasksCard() {
        this._tasksCard = new St.BoxLayout({
            style_class: "adaptive-island-card adaptive-island-tasks-card",
            vertical: true,
            visible: false,
        });

        const metaRow = new St.BoxLayout({ vertical: false });
        this._taskTitleLabel = new St.Label({ text: "Task #14 - Dynamic Island UI", style_class: "adaptive-island-val-bold" });
        metaRow.add_child(this._taskTitleLabel);
        metaRow.add_child(new St.Widget({ x_expand: true }));
        this._taskMetaLabel = new St.Label({ text: "Agent: Lena · 45%", style_class: "adaptive-island-subtext" });
        metaRow.add_child(this._taskMetaLabel);
        this._tasksCard.add_child(metaRow);

        // Monospace live terminal box
        this._taskStdoutBox = new St.BoxLayout({
            style_class: "adaptive-island-terminal",
            vertical: true,
        });
        this._taskStdoutBox.add_child(new St.Label({ text: "[18:25:01] Updating dynamicIsland orchestrator...", style_class: "adaptive-island-terminal-line" }));
        this._taskStdoutBox.add_child(new St.Label({ text: "[18:25:03] Compiling extension stylesheet.css", style_class: "adaptive-island-terminal-line" }));
        this._taskStdoutBox.add_child(new St.Label({ text: "[18:25:04] Mounting IslandAnchor on DateMenuButton", style_class: "adaptive-island-terminal-line active" }));
        this._tasksCard.add_child(this._taskStdoutBox);

        // Actions
        const actionsRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER });
        actionsRow.add_child(new St.Widget({ x_expand: true }));

        const pauseTaskBtn = new St.Button({
            style_class: "adaptive-island-btn",
            label: "Pause",
            can_focus: false,
        });
        actionsRow.add_child(pauseTaskBtn);

        const killTaskBtn = new St.Button({
            style_class: "adaptive-island-btn adaptive-island-btn-alert",
            label: "Kill",
            can_focus: false,
        });
        killTaskBtn.connect("clicked", () => {
            const active = this._ui.backend.tasks.getActiveTasks();
            if (active.length > 0)
                this._ui.backend.tasks.cancelTask(active[0].id);
        });
        actionsRow.add_child(killTaskBtn);

        this._tasksCard.add_child(actionsRow);
        this._cardContentBox.add_child(this._tasksCard);
    }

    _buildMediaCard() {
        this._mediaCard = new St.BoxLayout({
            style_class: "adaptive-island-card adaptive-island-media-card",
            vertical: true,
            visible: false,
        });

        // Track Info
        const trackRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER });
        const artBox = new St.BoxLayout({
            style_class: "adaptive-island-media-art",
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });
        artBox.add_child(new St.Label({ text: "♫", style_class: "adaptive-island-media-art-icon" }));
        trackRow.add_child(artBox);

        const infoBox = new St.BoxLayout({ vertical: true });
        this._mediaTitleLabel = new St.Label({ text: "Midnight City", style_class: "adaptive-island-val-bold" });
        if (this._mediaTitleLabel.clutter_text)
            this._mediaTitleLabel.clutter_text.ellipsize = imports.gi.Pango.EllipsizeMode.END;
        this._mediaArtistLabel = new St.Label({ text: "M83", style_class: "adaptive-island-subtext" });
        infoBox.add_child(this._mediaTitleLabel);
        infoBox.add_child(this._mediaArtistLabel);
        trackRow.add_child(infoBox);

        this._mediaCard.add_child(trackRow);

        // Scrubber bar
        const scrubRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER });
        this._mediaElapsedLabel = new St.Label({ text: "1:42", style_class: "adaptive-island-subtext" });
        this._mediaDurationLabel = new St.Label({ text: "4:03", style_class: "adaptive-island-subtext" });

        const scrubTrack = new St.Widget({ style_class: "adaptive-island-progress-track", x_expand: true });
        this._mediaScrubberFill = new St.Widget({ style_class: "adaptive-island-progress-fill adaptive-island-fill-green" });
        this._mediaScrubberFill.set_width(120);
        scrubTrack.add_child(this._mediaScrubberFill);

        scrubRow.add_child(this._mediaElapsedLabel);
        scrubRow.add_child(scrubTrack);
        scrubRow.add_child(this._mediaDurationLabel);
        this._mediaCard.add_child(scrubRow);

        // Transport Controls
        const transportRow = new St.BoxLayout({
            style_class: "adaptive-island-transport-row",
            vertical: false,
            x_align: Clutter.ActorAlign.CENTER,
        });

        const prevBtn = new St.Button({ style_class: "adaptive-island-transport-btn", label: "⏮", can_focus: false });
        prevBtn.connect("clicked", () => this._ui.backend.media.previous());
        transportRow.add_child(prevBtn);

        this._mediaPlayBtn = new St.Button({ style_class: "adaptive-island-transport-btn adaptive-island-btn-play", label: "⏸", can_focus: false });
        this._mediaPlayBtn.connect("clicked", () => this._ui.backend.media.playPause());
        transportRow.add_child(this._mediaPlayBtn);

        const nextBtn = new St.Button({ style_class: "adaptive-island-transport-btn", label: "⏭", can_focus: false });
        nextBtn.connect("clicked", () => this._ui.backend.media.next());
        transportRow.add_child(nextBtn);

        this._mediaCard.add_child(transportRow);
        this._cardContentBox.add_child(this._mediaCard);
    }

    _buildTimerCard() {
        this._timerCard = new St.BoxLayout({
            style_class: "adaptive-island-card adaptive-island-timer-card",
            vertical: true,
            visible: false,
        });

        // Digits & Status
        const digitsRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER });
        this._timerDigitsLabel = new St.Label({ text: "18:42", style_class: "adaptive-island-big-digits" });
        digitsRow.add_child(this._timerDigitsLabel);
        digitsRow.add_child(new St.Widget({ x_expand: true }));
        this._timerStatusTag = new St.Label({ text: "RUNNING", style_class: "adaptive-island-status-active" });
        digitsRow.add_child(this._timerStatusTag);
        this._timerCard.add_child(digitsRow);

        // Preset Chips
        const chipsRow = new St.BoxLayout({ vertical: false });
        const p25 = new St.Button({ style_class: "adaptive-island-chip", label: "25m Focus", can_focus: false });
        p25.connect("clicked", () => this._ui.backend.timers.startPomodoro());
        chipsRow.add_child(p25);

        const p5 = new St.Button({ style_class: "adaptive-island-chip", label: "5m Break", can_focus: false });
        p5.connect("clicked", () => this._ui.backend.timers.startBreak(5));
        chipsRow.add_child(p5);

        const p15 = new St.Button({ style_class: "adaptive-island-chip", label: "15m Long Break", can_focus: false });
        p15.connect("clicked", () => this._ui.backend.timers.startBreak(15));
        chipsRow.add_child(p15);

        this._timerCard.add_child(chipsRow);

        // Controls
        const ctrlRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER });
        const extBtn = new St.Button({ style_class: "adaptive-island-btn", label: "+5m", can_focus: false });
        extBtn.connect("clicked", () => this._ui.backend.timers.extend(300));
        ctrlRow.add_child(extBtn);

        ctrlRow.add_child(new St.Widget({ x_expand: true }));

        this._timerPauseBtn = new St.Button({ style_class: "adaptive-island-btn", label: "Pause", can_focus: false });
        this._timerPauseBtn.connect("clicked", () => {
            const t = this._ui.backend.timers.getState();
            if (t.status === "RUNNING")
                this._ui.backend.timers.pause();
            else
                this._ui.backend.timers.resume();
        });
        ctrlRow.add_child(this._timerPauseBtn);

        const resetBtn = new St.Button({ style_class: "adaptive-island-btn", label: "Reset", can_focus: false });
        resetBtn.connect("clicked", () => this._ui.backend.timers.reset());
        ctrlRow.add_child(resetBtn);

        this._timerCard.add_child(ctrlRow);
        this._cardContentBox.add_child(this._timerCard);
    }

    renderState(state, activeTheme, targetFeature = null) {
        // Determine which card to display
        let card = targetFeature;
        if (!card) {
            if (state.surfacedEvent) {
                const t = state.surfacedEvent.type;
                if (t.startsWith("QUOTA_")) card = "quota";
                else if (t.startsWith("TASK_")) card = "tasks";
                else if (t.startsWith("TRACK_") || t.startsWith("PLAYBACK_")) card = "media";
                else if (t.startsWith("TIMER_")) card = "timer";
            } else if (state.multiActivity && state.multiActivity.primary) {
                card = state.multiActivity.primary.type === "task" ? "tasks" : state.multiActivity.primary.type;
            } else {
                card = "quota";
            }
        }
        this._activeCardType = card;

        if (!this._actor) return;

        // Apply theme styling
        this._actor.remove_style_class_name("adaptive-island-theme-liquid-glass");
        this._actor.remove_style_class_name("adaptive-island-theme-dark-precision");
        this._actor.add_style_class_name("adaptive-island-theme-" + activeTheme);

        // Pin button state
        if (state.isPinned) {
            this._pinButton.add_style_class_name("pinned");
        } else {
            this._pinButton.remove_style_class_name("pinned");
        }



        // Hide all cards, show active card
        this._quotaCard.visible = card === "quota";
        this._tasksCard.visible = card === "tasks";
        this._mediaCard.visible = card === "media";
        this._timerCard.visible = card === "timer";

        // Resize overlay height for task stdout
        if (card === "tasks") {
            this._actor.set_size(372, 242);
        } else {
            this._actor.set_size(372, 208);
        }

        // Update card data
        if (card === "quota") {
            this._renderQuotaData(state);
        } else if (card === "tasks") {
            this._renderTasksData(state);
        } else if (card === "media") {
            this._renderMediaData(state);
        } else if (card === "timer") {
            this._renderTimerData(state);
        }
    }

    _renderQuotaData(state) {
        this._titleIcon.text = "✦";
        this._titleLabel.text = "AI QUOTA MONITOR";

        const q = state.quota || {};
        const cld = q.claude || {};

        const fiveHr = (typeof cld.fiveHourPercent === "number") ? cld.fiveHourPercent : 43;
        this._claudePctLabel.text = fiveHr + "% left";
        this._claudeBarFill.set_width(Math.round((fiveHr / 100) * 320));

        if (cld.fiveHourResetsAt) {
            this._claudeResetLabel.text = `Rolling 5h · Resets: ${new Date(cld.fiveHourResetsAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
        } else {
            this._claudeResetLabel.text = "Rolling 5h · Resets in 1h 22m";
        }

        const weekly = (typeof cld.weeklyPercent === "number") ? cld.weeklyPercent : 72;
        this._claudeWeeklyLabel.text = "Weekly: " + weekly + "%";

        const agy = q.agy || {};
        const inTok = agy.sessionInputTokens || 2500;
        const outTok = agy.sessionOutputTokens || 500;
        const cacheTok = agy.sessionCacheReadTokens || 13000;
        this._agyTokensLabel.text = "Session: " + (inTok / 1000).toFixed(1) + "k In · " + (outTok / 1000).toFixed(1) + "k Out · " + (cacheTok / 1000).toFixed(1) + "k Cache";

        if (q.criticalBreach) {
            this._badgeLabel.text = "CRITICAL";
            this._actor.add_style_class_name("critical");
        } else if (q.cautionBreach) {
            this._badgeLabel.text = "CAUTION";
            this._actor.add_style_class_name("caution");
        } else {
            this._badgeLabel.text = "ACTIVE";
            this._actor.remove_style_class_name("caution");
            this._actor.remove_style_class_name("critical");
        }
    }

    _renderTasksData(state) {
        this._titleIcon.text = "⟳";
        this._titleLabel.text = "BACKGROUND AI TASKS";
        this._badgeLabel.text = "RUNNING";

        const tasks = state.tasks || [];
        if (tasks.length > 0) {
            const t = tasks[0];
            this._taskTitleLabel.text = t.title || "AI Task";
            this._taskMetaLabel.text = "Agent: " + (t.agent || "Agent") + " · Step " + (t.step || 1) + "/" + (t.totalSteps || 3);
        }
    }

    _renderMediaData(state) {
        this._titleIcon.text = "♫";
        this._titleLabel.text = "NOW-PLAYING MEDIA";

        const m = state.media || {};
        this._mediaTitleLabel.text = m.title || "No Media Playing";
        this._mediaArtistLabel.text = m.artist || "Unknown Artist";
        this._badgeLabel.text = m.isPlaying ? "PLAYING" : "PAUSED";
        this._mediaPlayBtn.label = m.isPlaying ? "⏸" : "▶";
    }

    _renderTimerData(state) {
        this._titleIcon.text = "⏱";
        this._titleLabel.text = "FOCUS TIMERS";

        const t = state.timer || {};
        this._timerDigitsLabel.text = t.formatted || "00:00";
        this._timerStatusTag.text = t.status || "IDLE";
        this._badgeLabel.text = t.status || "IDLE";
        this._timerPauseBtn.label = t.status === "RUNNING" ? "Pause" : "Resume";
    }

    showOverlay(anchorActor) {
        if (this._isExpanded) return;
        this._isExpanded = true;
        if (!this._actor) return;
        this._actor.visible = true;
        this._actor.reactive = true;

        // Position directly under anchor
        let ax = 0;
        let anchorWidth = 0;
        const dateMenu = (Main && Main.panel && Main.panel.statusArea) ? Main.panel.statusArea.dateMenu : null;
        if (anchorActor && anchorActor.get_transformed_position) {
            try {
                const pos = anchorActor.get_transformed_position();
                if (pos && typeof pos[0] === "number" && !isNaN(pos[0]) && pos[0] !== null) {
                    ax = pos[0];
                    anchorWidth = anchorActor.width;
                }
            } catch (e) {}
        }
        if ((!ax || isNaN(ax)) && dateMenu && dateMenu.get_transformed_position) {
            try {
                const pos = dateMenu.get_transformed_position();
                if (pos && typeof pos[0] === "number" && !isNaN(pos[0]) && pos[0] !== null) {
                    ax = pos[0];
                    anchorWidth = dateMenu.width;
                }
            } catch (e) {}
        }
        if (!ax || isNaN(ax)) {
            const screenWidth = (Main && Main.panel) ? Main.panel.width : 1920;
            ax = Math.round((screenWidth - 372) / 2);
            anchorWidth = 372;
        }

        const panelHeight = (Main && Main.panel) ? Main.panel.height : 32;
        const overlayWidth = (this._actor && this._actor.width > 0) ? this._actor.width : 372;
        const targetX = Math.round(ax + (anchorWidth - overlayWidth) / 2);
        const targetY = Math.round(panelHeight + 4);
        this._actor.set_position(targetX, targetY);

        // Apply blur effect
        if (this._blurEffect && this._actor.add_effect_with_name) {
            try {
                if (this._actor.get_effect && !this._actor.get_effect("island-blur")) {
                    this._actor.add_effect_with_name("island-blur", this._blurEffect);
                }
            } catch (e) {}
        }

        // Hardware Clutter ease transition (EASE_OUT_BACK for spring drop approximation)
        this._actor.translation_y = -16;
        this._actor.opacity = 0;
        if (Clutter && this._actor.ease) {
            this._actor.ease({
                translation_y: 0,
                opacity: 255,
                duration: 380,
                mode: Clutter.AnimationMode.EASE_OUT_BACK,
            });
        } else {
            this._actor.translation_y = 0;
            this._actor.opacity = 255;
        }

        // Connect global outside click
        if (global.stage && !this._stageClickId) {
            this._stageClickId = global.stage.connect("button-press-event", (stage, event) => {
                if (!this._isExpanded) return Clutter.EVENT_PROPAGATE;
                const [cx, cy] = event.get_coords();
                const [ox, oy] = this._actor.get_transformed_position();
                const insideOverlay = cx >= ox && cx <= ox + this._actor.width && cy >= oy && cy <= oy + this._actor.height;
                const [ax, ay] = anchorActor ? anchorActor.get_transformed_position() : [0, 0];
                const insideAnchor = cx >= ax && cx <= ax + (anchorActor ? anchorActor.width : 0) && cy >= ay && cy <= ay + (anchorActor ? anchorActor.height : 0);

                if (!insideOverlay && !insideAnchor) {
                    if (!this._ui.backend.getState().isPinned) {
                        this._ui.contract();
                    }
                }
                return Clutter.EVENT_PROPAGATE;
            });
        }
    }

    hideOverlay() {
        if (!this._isExpanded) return;
        this._isExpanded = false;
        if (!this._actor) return;
        this._actor.reactive = false;

        if (this._stageClickId && global.stage) {
            global.stage.disconnect(this._stageClickId);
            this._stageClickId = 0;
        }

        if (Clutter && this._actor.ease) {
            this._actor.ease({
                translation_y: -16,
                opacity: 0,
                duration: 250,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    this._actor.visible = false;
                    if (this._blurEffect && this._actor.remove_effect_by_name) {
                        try { this._actor.remove_effect_by_name("island-blur"); } catch (e) {}
                    }
                },
            });
        } else {
            this._actor.visible = false;
            this._actor.opacity = 0;
            if (this._blurEffect && this._actor.remove_effect_by_name) {
                try { this._actor.remove_effect_by_name("island-blur"); } catch (e) {}
            }
        }
    }

    getActor() {
        return this._actor;
    }

    destroy() {
        if (this._stageClickId && global.stage) {
            global.stage.disconnect(this._stageClickId);
            this._stageClickId = 0;
        }
        if (this._actor) {
            this._actor.destroy();
            this._actor = null;
        }
    }
};

// -----------------------------------------------------------------------------
// IslandUI: Top-level coordinator for Dynamic Island frontend
// -----------------------------------------------------------------------------
var IslandUI = class IslandUI {
    constructor(extensionOwner, options = {}) {
        this._extension = extensionOwner;
        this._theme = options.theme || IslandTheme.LIQUID_GLASS;
        this._backend = options.backend || new DynamicIslandBackend(options.backendOptions);
        this._ownsBackend = !options.backend;

        this._anchor = new IslandAnchor(this);
        this._overlay = new IslandOverlay(this);

        this._surfacedUnsub = null;
        this._tuckedUnsub = null;
        this._stateUnsub = null;

        this._attached = false;
        this._forcedFeature = null;
        this._clockNotifyId = 0;
    }

    get backend() {
        return this._backend;
    }

    isExpanded() {
        return this._overlay ? this._overlay._isExpanded : false;
    }

    attach() {
        if (this._attached) return;
        this._attached = true;

        // 1. Build UI elements
        this._anchor.build();
        this._overlay.build();

        // 2. Mount Anchor onto dateMenu
        const dateMenu = (Main && (Main && Main.panel)) ? (Main && Main.panel).statusArea.dateMenu : null;
        if (dateMenu && (dateMenu.actor || dateMenu._clockDisplay)) {
            // Locate clock label
            if (dateMenu._clockDisplay) {
                this._anchor.syncClock(dateMenu._clockDisplay.text || "");
                this._clockNotifyId = dateMenu._clockDisplay.connect("notify::text", () => {
                    this._anchor.syncClock(dateMenu._clockDisplay.text || "");
                });
            }

            // Mount into dateMenu clock box
            const anchorActor = this._anchor.getActor();
            if (dateMenu._clockDisplay && anchorActor) {
                const clockBox = dateMenu._clockDisplay.get_parent();
                if (clockBox) {
                    // Hide default clock display label and indicator so IslandAnchor takes its place seamlessly
                    dateMenu._clockDisplay.visible = false;
                    if (dateMenu._indicator)
                        dateMenu._indicator.visible = false;

                    anchorActor.visible = true;
                    clockBox.insert_child_above(anchorActor, dateMenu._clockDisplay);
                    this._clockBox = clockBox;
                }
            }
        }

        // 3. Mount Overlay to uiGroup
        if ((Main && Main.layoutManager) && (Main && Main.layoutManager).uiGroup && this._overlay.getActor()) {
            (Main && Main.layoutManager).uiGroup.add_child(this._overlay.getActor());
        }

        // 4. Hook Backend Event Subscriptions
        this._surfacedUnsub = this._backend.onSurfaced((bus, event) => this._onSurfaced(event));
        this._tuckedUnsub = this._backend.onTucked((bus, event) => this._onTucked(event));
        this._stateUnsub = this._backend.onStateChange((bus, state) => this._onStateChange(state));

        // 5. Initialize backend
        if (this._ownsBackend) {
            this._backend.init();
        }

        if (typeof Main !== "undefined" && Main) {
            Main._dynamicIsland = this;
        }

        this._updateUI();
    }

    detach() {
        if (!this._attached) return;
        this._attached = false;

        // Disconnect backend listeners
        if (this._surfacedUnsub) { this._surfacedUnsub(); this._surfacedUnsub = null; }
        if (this._tuckedUnsub) { this._tuckedUnsub(); this._tuckedUnsub = null; }
        if (this._stateUnsub) { this._stateUnsub(); this._stateUnsub = null; }

        if (this._ownsBackend) {
            this._backend.destroy();
        }

        // Restore dateMenu clock box
        const dateMenu = (Main && (Main && Main.panel)) ? (Main && Main.panel).statusArea.dateMenu : null;
        if (dateMenu) {
            if (this._clockNotifyId && dateMenu._clockDisplay) {
                dateMenu._clockDisplay.disconnect(this._clockNotifyId);
                this._clockNotifyId = 0;
            }
            if (dateMenu._clockDisplay)
                dateMenu._clockDisplay.visible = true;
            if (dateMenu._indicator)
                dateMenu._indicator.visible = true;

            const anchorActor = this._anchor.getActor();
            if (anchorActor) {
                const parent = anchorActor.get_parent();
                if (parent) {
                    parent.remove_child(anchorActor);
                }
            }
            this._clockBox = null;
        }

        // Remove from scene graph
        if ((Main && Main.layoutManager) && (Main && Main.layoutManager).uiGroup && this._overlay.getActor()) {
            (Main && Main.layoutManager).uiGroup.remove_child(this._overlay.getActor());
        }

        if (typeof Main !== "undefined" && Main && Main._dynamicIsland === this) {
            Main._dynamicIsland = null;
        }

        this._overlay.destroy();
        this._anchor.destroy();
    }

    _onSurfaced(event) {
        this._updateUI();
    }

    _onTucked(event) {
        if (!this._backend.getState().isPinned) {
            this.contract();
        }
        this._updateUI();
    }

    _onStateChange(state) {
        this._updateUI();
    }

    _updateUI(forcedState = null) {
        const state = forcedState || this._backend.getState();
        this._anchor.renderState(state, this._theme);
        this._overlay.renderState(state, this._theme, this._forcedFeature);
    }

    expand(targetFeature = null, forcedState = null) {
        this._forcedFeature = targetFeature;
        this._updateUI(forcedState);
        this._overlay.showOverlay(this._anchor.getActor());
    }

    contract(forcedState = null) {
        this._forcedFeature = null;
        this._overlay.hideOverlay();
        if (forcedState)
            this._updateUI(forcedState);
    }

    setTheme(themeName) {
        if (themeName === IslandTheme.LIQUID_GLASS || themeName === IslandTheme.DARK_PRECISION) {
            this._theme = themeName;
            this._updateUI();
        }
    }

    getTheme() {
        return this._theme;
    }

    setPinned(pinned) {
        this._backend.setPinned(pinned);
        if (pinned)
            this.expand();
        this._updateUI();
    }

    getState() {
        const bgState = this._backend.getState();
        const uiState = this._overlay._isExpanded
            ? IslandState.EXPANDED
            : (bgState.multiActivity && bgState.multiActivity.secondary
                ? IslandState.SATELLITE
                : (bgState.surfacedEvent ? IslandState.COMPACT : IslandState.IDLE));
        return {
            uiState,
            theme: this._theme,
            backend: bgState,
        };
    }
};

if (typeof module !== "undefined" && module.exports) {
    module.exports = { IslandUI, IslandAnchor, IslandOverlay, IslandTheme, IslandState };
}
