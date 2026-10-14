// Dynamic Island Frontend for GNOME Shell 42.9 (adaptive-shell@local)
//
// Implements in-panel IslandAnchor on dateMenu and IslandOverlay on (Main && Main.layoutManager).uiGroup.
// Provides idle, compact, satellite, and expanded presentation states for the 4 MVP features:
// 1. AI usage (how much of the Codex, Claude and Gemini limits is used, with reset times)
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
const { describeUsage = () => [] } = _loadModule("islandQuota");
const USAGE_TRACK_PX = 132;
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
            y_align: Clutter.ActorAlign.CENTER,
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
            text: "✦",
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
            x_expand: true,
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
        if (this._ui.isCenterOpen()) return;
        const state = this._ui.backend.getState();
        if (!state.surfacedEvent && !(state.multiActivity && state.multiActivity.primary)) return;
        this._ui.backend.pauseDwell();

        // Deliberate hover intent avoids opening while crossing the panel.
        if (!this._hoverDwellTimerId) {
            this._hoverDwellTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
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
            if (this._ui.isCenterOpen() || this._actor.hover || (this._ui._overlay.getActor() && this._ui._overlay.getActor().hover))
                return GLib.SOURCE_REMOVE;
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
        this._ui.toggleCenter();
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

        this._idleSparkLabel.visible = !hasSurfaced && !hasPrimary;

        // Keep the clock present in every presentation state.
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
            this._idleBox.visible = true;
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
            this._compactTextLabel.text = p.message || "AI usage";
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
    constructor(uiController, embedded = false) {
        this._ui = uiController;
        this._embedded = embedded;
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
        this._usageRefreshButton = null;
        this._usageRefreshResetId = 0;
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
        this._anchorAllocationId = 0;
        this._anchorActor = null;
    }

    build() {
        if (!St) return;

        this._actor = new St.Widget({
            style_class: "adaptive-island-overlay",
            layout_manager: new Clutter.BinLayout(),
            reactive: false,
            visible: false,
            can_focus: false,
            track_hover: true,
            opacity: 0,
        });

        // Set dimensions (372px x 208px default)
        this._actor.set_width(400);

        const mainLayout = new St.BoxLayout({
            style_class: "adaptive-island-overlay-inner",
            x_expand: true,
            y_expand: true,
            x_align: Clutter.ActorAlign.FILL,
            y_align: Clutter.ActorAlign.FILL,
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
            text: "AI usage",
            style_class: "adaptive-island-card-title",
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._badgeLabel = new St.Label({
            text: "ACTIVE",
            style_class: "adaptive-island-card-badge",
            y_align: Clutter.ActorAlign.CENTER,
        });


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

        if (this._embedded) {
            this._pinButton.hide();
            this._closeButton.hide();
            this._actor.add_style_class_name("adaptive-island-embedded");
            this._actor.set_width(-1);
            this._actor.x_expand = true;
            this._actor.opacity = 255;
            this._actor.visible = true;
            this._actor.reactive = true;
            return;
        }

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
        this._actor.connect("enter-event", () => {
            this._ui._anchor._clearGraceExitTimer();
            this._ui.backend.pauseDwell();
        });
        this._actor.connect("leave-event", () => this._ui._anchor._onMouseLeave());

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
            style_class: "adaptive-island-card adaptive-island-quota-card", vertical: true,
        });
        this._usageViews = {};
        for (const { key, name } of describeUsage({})) {
            const card = new St.BoxLayout({ style_class: "adaptive-island-subcard adaptive-island-usage", vertical: true });
            const head = new St.BoxLayout({ vertical: false });
            head.add_child(new St.Label({ text: name, style_class: "adaptive-island-subcard-title", x_expand: true }));
            const status = new St.Label({ text: "", style_class: "adaptive-island-subtext", y_align: Clutter.ActorAlign.CENTER });
            head.add_child(status);
            const rows = new St.BoxLayout({ vertical: true, style_class: "adaptive-island-usage-rows" });
            card.add_child(head);
            card.add_child(rows);
            this._usageViews[key] = { status, rows };
            this._quotaCard.add_child(card);
        }
        const refresh = new St.Button({ label: "Refresh usage", can_focus: true,
            style_class: "adaptive-island-btn", x_align: Clutter.ActorAlign.END });
        this._usageRefreshButton = refresh;
        refresh.connect("clicked", () => {
            if (!refresh.reactive)
                return;
            refresh.reactive = false;
            refresh.label = "Refreshing…";
            this._ui.backend.quota.refresh(ok => {
                if (!this._usageRefreshButton)
                    return;
                refresh.label = ok ? "Updated" : "Refresh failed";
                refresh.reactive = true;
                if (this._usageRefreshResetId && GLib)
                    GLib.source_remove(this._usageRefreshResetId);
                if (GLib) {
                    this._usageRefreshResetId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1800, () => {
                        this._usageRefreshResetId = 0;
                        if (this._usageRefreshButton)
                            this._usageRefreshButton.label = "Refresh usage";
                        return GLib.SOURCE_REMOVE;
                    });
                } else {
                    refresh.label = "Refresh usage";
                }
            });
        });
        this._quotaCard.add_child(refresh);
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
        const chipsRow = new St.BoxLayout({ vertical: false, style_class: "adaptive-island-actions" });
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
        const ctrlRow = new St.BoxLayout({ vertical: false, style_class: "adaptive-island-actions", y_align: Clutter.ActorAlign.CENTER });
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

        // Let the active card determine its height; fixed heights clip controls.
        this._actor.remove_style_class_name("caution");
        this._actor.remove_style_class_name("critical");

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
        this._titleLabel.text = "AI usage";
        this._badgeLabel.text = "USED";
        const now = Date.now() / 1000;
        this._usageModel = describeUsage(state.quota || {}, now);
        if (!this._usageViews || typeof St === "undefined")
            return;
        const when = (seconds, withDay) => {
            const date = new Date(seconds * 1000);
            if (!Number.isFinite(date.getTime()))
                return "";
            const sameDay = date.toDateString() === new Date().toDateString();
            return date.toLocaleString([], withDay || !sameDay
                ? { weekday: "short", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
        };
        const inTime = (seconds) => {
            const m = Math.max(0, Math.round((seconds - now) / 60));
            return m >= 1440 ? `${Math.floor(m / 1440)}d ${Math.floor(m % 1440 / 60)}h` : m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
        };
        for (const p of this._usageModel) {
            const view = this._usageViews[p.key];
            if (!view)
                continue;
            view.status.text = p.unavailable ? "" : p.ts ? `${p.stale ? "Last read" : "Updated"} ${when(p.ts)}` : "";
            view.rows.destroy_all_children();
            if (p.unavailable) {
                view.rows.add_child(new St.Label({ text: p.unavailable, style_class: "adaptive-island-subtext" }));
                continue;
            }
            for (const r of p.rows) {
                const line = new St.BoxLayout({ vertical: false, style_class: "adaptive-island-usage-row" });
                line.add_child(new St.Label({ text: r.label, style_class: "adaptive-island-usage-label", y_align: Clutter.ActorAlign.CENTER }));
                const track = new St.Widget({ style_class: "adaptive-island-progress-track", y_align: Clutter.ActorAlign.CENTER });
                track.set_width(USAGE_TRACK_PX);
                const color = r.level === "critical" ? "red" : r.level === "caution" ? "amber" : "green";
                const fill = new St.Widget({ style_class: `adaptive-island-progress-fill adaptive-island-fill-${color}` });
                fill.set_width(r.used === null ? 0 : Math.max(r.used > 0 ? 3 : 0, Math.round(USAGE_TRACK_PX * r.used / 100)));
                track.add_child(fill);
                line.add_child(track);
                line.add_child(new St.Label({ text: r.text, x_expand: true, x_align: Clutter.ActorAlign.END,
                    style_class: `adaptive-island-usage-value adaptive-island-usage-${r.level}`, y_align: Clutter.ActorAlign.CENTER }));
                view.rows.add_child(line);
                if (r.resetsAt)
                    view.rows.add_child(new St.Label({ text: r.used === null ? `Window ended ${when(r.resetsAt)}`
                        : `Resets ${when(r.resetsAt, r.label !== "5h")} · in ${inTime(r.resetsAt)}`, style_class: "adaptive-island-subtext adaptive-island-usage-reset" }));
            }
        }
    }

    _renderTasksData(state) {
        this._titleIcon.text = "⟳";
        this._titleLabel.text = "Background tasks";
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
        this._titleLabel.text = "Now playing";

        const m = state.media || {};
        this._mediaTitleLabel.text = m.title || "No Media Playing";
        this._mediaArtistLabel.text = m.artist || "Unknown Artist";
        this._badgeLabel.text = m.isPlaying ? "PLAYING" : "PAUSED";
        this._mediaPlayBtn.label = m.isPlaying ? "⏸" : "▶";
    }

    _renderTimerData(state) {
        this._titleIcon.text = "⏱";
        this._titleLabel.text = "Focus timer";

        const t = state.timer || {};
        this._timerDigitsLabel.text = t.formatted || "00:00";
        this._timerStatusTag.text = t.status || "IDLE";
        this._badgeLabel.text = t.status || "IDLE";
        this._timerPauseBtn.label = t.status === "RUNNING" ? "Pause" : "Resume";
    }

    _positionOverlay() {
        const anchorActor = this._anchorActor;
        if (!anchorActor || !this._actor) return;
        // Use stage coordinates so secondary monitors and panel offsets work.
        const monitor = Main.layoutManager.findMonitorForActor(anchorActor) || Main.layoutManager.primaryMonitor;
        const [ax, ay] = anchorActor.get_transformed_position();
        const [aw, ah] = anchorActor.get_transformed_size();
        const width = Math.min(400, monitor.width - 24);
        this._actor.set_width(width);
        const targetX = Math.max(monitor.x + 12,
            Math.min(ax + (aw - width) / 2, monitor.x + monitor.width - width - 12));
        this._actor.set_position(Math.round(targetX), Math.round(ay + ah + 8));

    }

    showOverlay(anchorActor) {
        if (this._isExpanded) return;
        this._isExpanded = true;
        if (!this._actor) return;
        this._actor.visible = true;
        this._actor.reactive = true;

        this._anchorActor = anchorActor;
        this._positionOverlay();
        if (!this._anchorAllocationId) {
            this._anchorAllocationId = anchorActor.connect("notify::allocation", () => {
                if (this._isExpanded) this._positionOverlay();
            });
        }

        // Apply blur effect
        if (this._blurEffect && this._actor.add_effect_with_name) {
            try {
                if (this._actor.get_effect && !this._actor.get_effect("island-blur")) {
                    this._actor.add_effect_with_name("island-blur", this._blurEffect);
                }
            } catch (e) {}
        }

        // Cancel an interrupted close without jumping back to the starting frame.
        this._actor.remove_all_transitions();
        if (this._actor.opacity === 0)
            this._actor.translation_y = -6;
        if (Clutter && this._actor.ease) {
            this._actor.ease({
                translation_y: 0,
                opacity: 255,
                duration: 220,
                mode: Clutter.AnimationMode.EASE_OUT_CUBIC,
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
        this._actor.remove_all_transitions();

        if (this._stageClickId && global.stage) {
            global.stage.disconnect(this._stageClickId);
            this._stageClickId = 0;
        }

        if (Clutter && this._actor.ease) {
            this._actor.ease({
                translation_y: -6,
                opacity: 0,
                duration: 160,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    if (!this._actor || this._isExpanded) return;
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
        if (this._usageRefreshResetId && GLib) {
            GLib.source_remove(this._usageRefreshResetId);
            this._usageRefreshResetId = 0;
        }
        this._usageRefreshButton = null;
        if (this._anchorAllocationId && this._anchorActor) {
            this._anchorActor.disconnect(this._anchorAllocationId);
            this._anchorAllocationId = 0;
        }
        this._anchorActor = null;
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
        this._centerOverlay = null;
        this._centerSection = null;
        this._centerFeature = "quota";
        this._centerButtons = [];
        this._menuOpenId = 0;
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

        this._buildCenter();
        if (dateMenu && dateMenu.menu) {
            this._menuOpenId = dateMenu.menu.connect("open-state-changed", (menu, open) => {
                if (open) {
                    this._anchor._clearGraceExitTimer();
                    if (this._anchor._hoverDwellTimerId) {
                        GLib.source_remove(this._anchor._hoverDwellTimerId);
                        this._anchor._hoverDwellTimerId = 0;
                    }
                    this.contract();
                    this._backend.pauseDwell();
                } else {
                    this._backend.resumeDwell();
                }
            });
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

    _buildCenter() {
        const shade = this._extension && this._extension._shade;
        if (!St || !shade || !shade._systemSection) return;
        this._centerSection = new St.BoxLayout({ vertical: true,
            style_class: "adaptive-island-center", x_expand: true });
        const tabs = new St.BoxLayout({ style_class: "adaptive-island-actions", x_expand: true });
        for (const [feature, label] of [["quota", "AI usage"], ["tasks", "Tasks"], ["media", "Music"], ["timer", "Focus"]]) {
            const button = new St.Button({ label, can_focus: true, x_expand: true,
                style_class: "adaptive-island-chip" });
            button.connect("clicked", () => {
                this._centerFeature = feature;
                this._updateUI();
            });
            tabs.add_child(button);
            this._centerButtons.push([feature, button]);
        }
        this._centerSection.add_child(tabs);
        this._centerOverlay = new IslandOverlay(this, true);
        this._centerOverlay.build();
        this._centerSection.add_child(this._centerOverlay.getActor());
        // Share the system scroll area so small displays keep their calendar
        // and notifications accessible without a second scrolling container.
        shade._systemSection.insert_child_at_index(this._centerSection, 0);
    }

    isCenterOpen() {
        const menu = Main && Main.panel && Main.panel.statusArea.dateMenu;
        return !!(menu && menu.menu && menu.menu.isOpen);
    }

    toggleCenter() {
        const dateMenu = Main && Main.panel && Main.panel.statusArea.dateMenu;
        if (!dateMenu || !dateMenu.menu) return;
        this.contract();
        dateMenu.menu.toggle();
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

        if (this._centerOverlay) {
            this._centerOverlay.destroy();
            this._centerOverlay = null;
        }
        if (this._centerSection) {
            this._centerSection.destroy();
            this._centerSection = null;
        }
        this._centerButtons = [];

        // Restore dateMenu clock box
        const dateMenu = (Main && (Main && Main.panel)) ? (Main && Main.panel).statusArea.dateMenu : null;
        if (dateMenu) {
            if (this._menuOpenId) {
                dateMenu.menu.disconnect(this._menuOpenId);
                this._menuOpenId = 0;
            }
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
        if (this._centerOverlay) {
            this._centerOverlay.renderState(state, this._theme, this._centerFeature);
            for (const [feature, button] of this._centerButtons) {
                if (feature === this._centerFeature) button.add_style_pseudo_class("checked");
                else button.remove_style_pseudo_class("checked");
            }
        }
    }

    expand(targetFeature = null, forcedState = null) {
        if (this.isCenterOpen()) return;
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
