// Dynamic Island Frontend for GNOME Shell 42.9 (adaptive-shell@local)
//
// Implements in-panel IslandAnchor on dateMenu and IslandOverlay on (Main && Main.layoutManager).uiGroup.
// Provides idle, compact, satellite, and expanded presentation states for the 4 MVP features:
// 1. AI usage (how much of the Codex, Claude and Gemini limits is used, with reset times)
// 2. Background AI Tasks (every running Agent Office task, its live event log, Cancel)
// 3. Now-Playing Media (cover art, elapsed/length, seekable scrubber, transport, player switch)
// 4. Focus Timers (Big digits, Pomodoro presets, +5m extend, Do Not Disturb while focusing)
//
// The same cards, plus an Overview, also live in the Shade as the Activity
// Center: IslandUI builds it and hands it to Shade.mountActivityCenter().
// Cards are only drawn while they are on screen, so a provider update while
// the menu is closed costs nothing beyond the panel pill.
//
// Supports two visual themes: "liquid-glass" (default) and "dark-precision".
// Adheres strictly to: 0% idle timers/animations, async operations, no keyboard focus grabbing.

/* exported IslandUI, IslandAnchor, IslandOverlay, IslandTheme, describeOverview, describeBadges */
/* global require, module */

let Clutter, Gio, GLib, GObject, Pango, St, Shell;
let Main = null;
let Me = null;

try {
    Clutter = imports.gi.Clutter;
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
    GObject = imports.gi.GObject;
    Pango = imports.gi.Pango;
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

const CENTER_TABS = [
    ["overview", "Overview"],
    ["quota", "AI usage"],
    ["tasks", "Tasks"],
    ["media", "Music"],
    ["timer", "Focus"],
];

// -----------------------------------------------------------------------------
// Pure summaries (tested headless)
// -----------------------------------------------------------------------------

function _formatUs(us) {
    const total = Math.max(0, Math.floor((Number(us) || 0) / 1e6));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const ss = `${s < 10 ? "0" : ""}${s}`;
    return h > 0 ? `${h}:${m < 10 ? "0" : ""}${m}:${ss}` : `${m}:${ss}`;
}

function _formatAge(seconds) {
    const m = Math.max(0, Math.floor(seconds / 60));
    if (m < 1)
        return "just started";
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
}

// The single most-used AI limit, or null when nothing has been read.
function _tightestUsage(quota, now) {
    let tight = null;
    for (const p of describeUsage(quota || {}, now)) {
        if (p.unavailable)
            continue;
        for (const r of p.rows) {
            if (r.used === null || r.used === undefined)
                continue;
            if (!tight || r.used > tight.used)
                tight = { ...r, provider: p.name };
        }
    }
    return tight;
}

// One line per feature for the Overview tab.
function describeOverview(state, now = Date.now() / 1000) {
    const tasks = state.tasks || [];
    const media = state.media || {};
    const timer = state.timer || {};
    const hidden = !!state.isScreenSharing;
    const tight = hidden ? null : _tightestUsage(state.quota, now);

    let timerText = "Off";
    if (timer.status === "RUNNING")
        timerText = `${timer.formatted} left · ${timer.label || "Focus"}`;
    else if (timer.status === "PAUSED")
        timerText = `Paused at ${timer.formatted}`;
    else if (timer.status === "EXPIRED")
        timerText = "Finished";

    return {
        quota: hidden ? { text: "Hidden while sharing", level: "normal" } : tight
            ? { text: `${tight.provider} ${tight.label} · ${tight.text}`, level: tight.level }
            : { text: "No limits read yet", level: "normal" },
        tasks: {
            text: tasks.length === 0 ? "None running"
                : tasks.length === 1 ? (state.isScreenSharing ? "1 running" : `${tasks[0].title || "1 running"}`)
                : `${tasks.length} running`,
            level: "normal",
        },
        media: {
            text: hidden && media.title ? "Media playing" : media.title
                ? `${media.isPlaying ? "" : "Paused · "}${media.title}${media.artist ? ` · ${media.artist}` : ""}`
                : "Nothing playing",
            level: "normal",
        },
        timer: { text: timerText, level: timer.status === "EXPIRED" ? "caution" : "normal" },
    };
}

// The small live badge on each Activity Center tab; "" hides it.
function describeBadges(state, now = Date.now() / 1000) {
    const tasks = state.tasks || [];
    const media = state.media || {};
    const timer = state.timer || {};
    const tight = _tightestUsage(state.quota, now);
    return {
        overview: { text: "", level: "normal" },
        quota: tight && tight.level !== "normal"
            ? { text: "!", level: tight.level } : { text: "", level: "normal" },
        tasks: { text: tasks.length ? `${tasks.length}` : "", level: "normal" },
        media: { text: media.isPlaying ? "▶" : "", level: "normal" },
        timer: {
            text: timer.status === "RUNNING" || timer.status === "PAUSED" ? timer.formatted || ""
                : timer.status === "EXPIRED" ? "0:00" : "",
            level: timer.status === "EXPIRED" ? "caution" : "normal",
        },
    };
}

function _ellipsize(label) {
    if (label && label.clutter_text && Pango)
        label.clutter_text.ellipsize = Pango.EllipsizeMode.END;
    return label;
}

function _button(label, styleClass, accessibleName, onClicked) {
    const button = new St.Button({
        label,
        style_class: styleClass,
        can_focus: true,
        accessible_name: accessibleName || label,
    });
    if (onClicked)
        button.connect("clicked", onClicked);
    return button;
}

function _setLevelClass(actor, prefix, level) {
    for (const l of ["normal", "caution", "critical"])
        actor.remove_style_class_name(`${prefix}-${l}`);
    actor.add_style_class_name(`${prefix}-${level || "normal"}`);
}

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
            accessible_name: "Clock and activity. Opens notifications and the Activity Center",
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
        _ellipsize(this._compactTextLabel);

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
            accessible_name: "Second activity",
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
            this._compactTextLabel.text = type === "TIMER_DIGEST" || type === "TIMER_EXPIRED"
                ? p.message || "Focus ended"
                : p.formatted || (p.data && p.data.formatted) || "Focus";
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
// IslandOverlay: Floating 400px HUD mounted to (Main && Main.layoutManager).uiGroup,
// or (embedded) the card stack of the Shade's Activity Center
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
        this._overviewCard = null;
        this._overviewRows = null;
        this._quotaCard = null;
        this._usageRefreshButton = null;
        this._usageRefreshResetId = 0;
        this._usageSignature = "";
        this._tasksCard = null;
        this._mediaCard = null;
        this._timerCard = null;

        this._taskList = null;
        this._taskEmpty = null;
        this._taskLogBox = null;
        this._taskSignature = "";
        this._selectedTaskId = null;

        this._mediaArtIcon = null;
        this._mediaArtFallback = null;
        this._mediaArtUrl = null;
        this._mediaTitleLabel = null;
        this._mediaArtistLabel = null;
        this._mediaPlayerButton = null;
        this._mediaElapsedLabel = null;
        this._mediaDurationLabel = null;
        this._mediaScrubTrack = null;
        this._mediaScrubberFill = null;
        this._mediaPrevBtn = null;
        this._mediaPlayBtn = null;
        this._mediaNextBtn = null;

        this._timerDigitsLabel = null;
        this._timerStatusTag = null;
        this._timerTrack = null;
        this._timerFill = null;
        this._timerProgress = 0;
        this._timerNoteLabel = null;
        this._timerPauseBtn = null;
        this._timerResetBtn = null;

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
            can_focus: true,
            accessible_name: "Keep this card open",
        });
        this._pinButton.set_child(new St.Label({ text: "📌", y_align: Clutter.ActorAlign.CENTER }));

        this._closeButton = new St.Button({
            style_class: "adaptive-island-card-btn adaptive-island-close-btn",
            can_focus: true,
            accessible_name: "Close",
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

        if (this._embedded)
            this._buildOverviewCard();
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

    // A card: the Overview's rows, or a feature's controls.
    _showFeature(feature) {
        if (this._embedded)
            this._ui.selectCenterFeature(feature);
        else
            this._ui.expand(feature);
    }

    _buildOverviewCard() {
        this._overviewCard = new St.BoxLayout({
            style_class: "adaptive-island-card adaptive-island-overview-card",
            vertical: true,
            visible: false,
        });
        this._overviewRows = {};
        for (const [feature, icon, name] of [["quota", "✦", "AI usage"], ["tasks", "⟳", "Tasks"],
            ["media", "♫", "Music"], ["timer", "⏱", "Focus"]]) {
            const row = new St.Button({
                style_class: "adaptive-island-overview-row",
                can_focus: true,
                x_expand: true,
                accessible_name: name,
            });
            const box = new St.BoxLayout({ vertical: false, x_expand: true });
            box.add_child(new St.Label({ text: icon, style_class: "adaptive-island-overview-icon",
                y_align: Clutter.ActorAlign.CENTER }));
            box.add_child(new St.Label({ text: name, style_class: "adaptive-island-overview-name",
                y_align: Clutter.ActorAlign.CENTER }));
            const value = _ellipsize(new St.Label({ text: "", x_expand: true,
                x_align: Clutter.ActorAlign.END, y_align: Clutter.ActorAlign.CENTER,
                style_class: "adaptive-island-overview-value" }));
            box.add_child(value);
            row.set_child(box);
            row.connect("clicked", () => this._showFeature(feature));
            this._overviewCard.add_child(row);
            this._overviewRows[feature] = { row, value, name };
        }
        this._cardContentBox.add_child(this._overviewCard);
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

        this._taskList = new St.BoxLayout({ style_class: "adaptive-island-task-list", vertical: true });
        this._tasksCard.add_child(this._taskList);

        this._taskEmpty = new St.Label({
            text: "No Agent Office tasks are running.",
            style_class: "adaptive-island-subtext",
        });
        this._tasksCard.add_child(this._taskEmpty);

        // Monospace log of the selected task's latest office events
        this._taskLogBox = new St.BoxLayout({
            style_class: "adaptive-island-terminal",
            vertical: true,
            visible: false,
        });
        this._tasksCard.add_child(this._taskLogBox);

        const actionsRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER });
        actionsRow.add_child(new St.Widget({ x_expand: true }));
        actionsRow.add_child(_button("Open Agent Office", "adaptive-island-btn", null, () => {
            this._ui.closeAll();
            this._ui.backend.tasks.openOffice();
        }));
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
        const trackRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER,
            style_class: "adaptive-island-media-row" });
        const artBox = new St.Widget({
            style_class: "adaptive-island-media-art",
            layout_manager: new Clutter.BinLayout(),
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._mediaArtFallback = new St.Label({ text: "♫", style_class: "adaptive-island-media-art-icon",
            x_align: Clutter.ActorAlign.CENTER, y_align: Clutter.ActorAlign.CENTER,
            x_expand: true, y_expand: true });
        this._mediaArtIcon = new St.Icon({ style_class: "adaptive-island-media-art-image",
            icon_size: 48, visible: false });
        artBox.add_child(this._mediaArtFallback);
        artBox.add_child(this._mediaArtIcon);
        trackRow.add_child(artBox);

        const infoBox = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        this._mediaTitleLabel = _ellipsize(new St.Label({ text: "", style_class: "adaptive-island-val-bold" }));
        this._mediaArtistLabel = _ellipsize(new St.Label({ text: "", style_class: "adaptive-island-subtext" }));
        this._mediaPlayerButton = new St.Button({
            style_class: "adaptive-island-player-btn",
            can_focus: true,
            x_align: Clutter.ActorAlign.START,
            label: "",
        });
        this._mediaPlayerButton.connect("clicked", () => this._ui.backend.media.cyclePlayer());
        infoBox.add_child(this._mediaTitleLabel);
        infoBox.add_child(this._mediaArtistLabel);
        infoBox.add_child(this._mediaPlayerButton);
        trackRow.add_child(infoBox);

        this._mediaCard.add_child(trackRow);

        // Scrubber: click or arrow keys to seek
        const scrubRow = new St.BoxLayout({ vertical: false, y_align: Clutter.ActorAlign.CENTER,
            style_class: "adaptive-island-scrub-row" });
        this._mediaElapsedLabel = new St.Label({ text: "0:00", style_class: "adaptive-island-subtext adaptive-island-time",
            y_align: Clutter.ActorAlign.CENTER });
        this._mediaDurationLabel = new St.Label({ text: "", style_class: "adaptive-island-subtext adaptive-island-time",
            y_align: Clutter.ActorAlign.CENTER });

        this._mediaScrubTrack = new St.Widget({
            style_class: "adaptive-island-progress-track adaptive-island-scrubber",
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
            reactive: true,
            can_focus: true,
            track_hover: true,
            accessible_name: "Track position",
        });
        this._mediaScrubberFill = new St.Widget({ style_class: "adaptive-island-progress-fill adaptive-island-fill-green" });
        this._mediaScrubTrack.add_child(this._mediaScrubberFill);
        this._mediaScrubTrack.connect("notify::width", () => this.renderMediaProgress());
        this._mediaScrubTrack.connect("button-release-event", (actor, event) => {
            const [x] = event.get_coords();
            const [tx] = actor.get_transformed_position();
            if (actor.width > 0)
                this._ui.backend.media.seekToFraction((x - tx) / actor.width);
            return Clutter.EVENT_STOP;
        });
        this._mediaScrubTrack.connect("key-press-event", (actor, event) => {
            const key = event.get_key_symbol();
            if (key === Clutter.KEY_Left || key === Clutter.KEY_Right) {
                this._ui.backend.media.seekBy(key === Clutter.KEY_Left ? -5 : 5);
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        scrubRow.add_child(this._mediaElapsedLabel);
        scrubRow.add_child(this._mediaScrubTrack);
        scrubRow.add_child(this._mediaDurationLabel);
        this._mediaCard.add_child(scrubRow);

        // Transport Controls
        const transportRow = new St.BoxLayout({
            style_class: "adaptive-island-transport-row",
            vertical: false,
            x_align: Clutter.ActorAlign.CENTER,
        });

        this._mediaPrevBtn = _button("⏮", "adaptive-island-transport-btn", "Previous track",
            () => this._ui.backend.media.previous());
        transportRow.add_child(this._mediaPrevBtn);

        this._mediaPlayBtn = _button("⏸", "adaptive-island-transport-btn adaptive-island-btn-play", "Pause",
            () => this._ui.backend.media.playPause());
        transportRow.add_child(this._mediaPlayBtn);

        this._mediaNextBtn = _button("⏭", "adaptive-island-transport-btn", "Next track",
            () => this._ui.backend.media.next());
        transportRow.add_child(this._mediaNextBtn);

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
        this._timerDigitsLabel = new St.Label({ text: "0:00", style_class: "adaptive-island-big-digits" });
        digitsRow.add_child(this._timerDigitsLabel);
        digitsRow.add_child(new St.Widget({ x_expand: true }));
        this._timerStatusTag = new St.Label({ text: "IDLE", style_class: "adaptive-island-status-active",
            y_align: Clutter.ActorAlign.CENTER });
        digitsRow.add_child(this._timerStatusTag);
        this._timerCard.add_child(digitsRow);

        this._timerTrack = new St.Widget({ style_class: "adaptive-island-progress-track", x_expand: true });
        this._timerFill = new St.Widget({ style_class: "adaptive-island-progress-fill adaptive-island-fill-cyan" });
        this._timerTrack.add_child(this._timerFill);
        this._timerTrack.connect("notify::width", () => this._sizeTimerFill());
        this._timerCard.add_child(this._timerTrack);

        this._timerNoteLabel = new St.Label({ text: "", style_class: "adaptive-island-subtext", visible: false });
        if (this._timerNoteLabel.clutter_text)
            this._timerNoteLabel.clutter_text.line_wrap = true;
        this._timerCard.add_child(this._timerNoteLabel);

        // Preset Chips
        const chipsRow = new St.BoxLayout({ vertical: false, style_class: "adaptive-island-actions" });
        chipsRow.add_child(_button("25m Focus", "adaptive-island-chip", "Start a 25 minute focus session",
            () => this._ui.backend.timers.startPomodoro()));
        chipsRow.add_child(_button("5m Break", "adaptive-island-chip", "Start a 5 minute break",
            () => this._ui.backend.timers.startBreak(5)));
        chipsRow.add_child(_button("15m Long Break", "adaptive-island-chip", "Start a 15 minute break",
            () => this._ui.backend.timers.startBreak(15)));
        this._timerCard.add_child(chipsRow);

        // Controls
        const ctrlRow = new St.BoxLayout({ vertical: false, style_class: "adaptive-island-actions", y_align: Clutter.ActorAlign.CENTER });
        ctrlRow.add_child(_button("+5m", "adaptive-island-btn", "Add five minutes",
            () => this._ui.backend.timers.extend(300)));

        ctrlRow.add_child(new St.Widget({ x_expand: true }));

        this._timerPauseBtn = _button("Pause", "adaptive-island-btn", "Pause the timer", () => {
            const t = this._ui.backend.timers.getState();
            if (t.status === "RUNNING")
                this._ui.backend.timers.pause();
            else
                this._ui.backend.timers.resume();
        });
        ctrlRow.add_child(this._timerPauseBtn);

        this._timerResetBtn = _button("Stop", "adaptive-island-btn", "Stop the timer",
            () => this._ui.backend.timers.reset());
        ctrlRow.add_child(this._timerResetBtn);

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
            }
            card = card || "quota";
        }
        if (card === "overview" && !this._embedded)
            card = "quota";
        this._activeCardType = card;

        if (!this._actor) return;

        // Apply theme styling
        this._actor.remove_style_class_name("adaptive-island-theme-liquid-glass");
        this._actor.remove_style_class_name("adaptive-island-theme-dark-precision");
        this._actor.add_style_class_name("adaptive-island-theme-" + activeTheme);

        // Pin button state
        if (state.isPinned) {
            this._pinButton.add_style_class_name("pinned");
            this._pinButton.accessible_name = "Let this card close by itself";
        } else {
            this._pinButton.remove_style_class_name("pinned");
            this._pinButton.accessible_name = "Keep this card open";
        }

        // Hide all cards, show active card
        if (this._overviewCard)
            this._overviewCard.visible = card === "overview";
        this._quotaCard.visible = card === "quota";
        this._tasksCard.visible = card === "tasks";
        this._mediaCard.visible = card === "media";
        this._timerCard.visible = card === "timer";

        // Let the active card determine its height; fixed heights clip controls.
        this._actor.remove_style_class_name("caution");
        this._actor.remove_style_class_name("critical");

        // Update card data
        if (card === "overview") {
            this._renderOverviewData(state);
        } else if (card === "quota") {
            this._renderQuotaData(state);
        } else if (card === "tasks") {
            this._renderTasksData(state);
        } else if (card === "media") {
            this._renderMediaData(state);
        } else if (card === "timer") {
            this._renderTimerData(state);
        }
    }

    _renderOverviewData(state) {
        this._titleIcon.text = "✦";
        this._titleLabel.text = "Activity";
        this._badgeLabel.text = "NOW";
        if (!this._overviewRows)
            return;
        const summary = describeOverview(state);
        for (const [feature, view] of Object.entries(this._overviewRows)) {
            const line = summary[feature];
            view.value.text = line.text;
            view.row.accessible_name = `${view.name}: ${line.text}`;
            _setLevelClass(view.value, "adaptive-island-overview-value", line.level);
        }
    }

    _renderQuotaData(state) {
        this._titleIcon.text = "✦";
        this._titleLabel.text = "AI usage";
        const hidden = !!state.isScreenSharing;
        this._badgeLabel.text = hidden ? "HIDDEN" : "USED";
        const now = Date.now() / 1000;
        this._usageModel = describeUsage(hidden ? {} : state.quota || {}, now);
        if (hidden) {
            this._usageModel = this._usageModel.map(provider => ({
                ...provider,
                unavailable: "Hidden while screen sharing",
            }));
        }
        if (!this._usageViews || typeof St === "undefined")
            return;
        // Rebuilding the rows is the costliest thing a card does; skip it when
        // nothing a row shows (to the minute) has changed.
        const signature = JSON.stringify(this._usageModel) + Math.floor(now / 60);
        if (signature === this._usageSignature)
            return;
        this._usageSignature = signature;
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

        const tasks = state.tasks || [];
        this._badgeLabel.text = tasks.length ? `${tasks.length} RUNNING` : "IDLE";
        if (!this._taskList)
            return;

        const tasksApi = this._ui.backend.tasks;
        const hidden = !!state.isScreenSharing;
        const now = Date.now() / 1000;
        if (!tasks.some(t => t.id === this._selectedTaskId))
            this._selectedTaskId = tasks.length ? tasks[0].id : null;

        const signature = JSON.stringify([hidden, this._selectedTaskId, Math.floor(now / 60),
            tasks.map(t => [t.id, t.title, t.agent, t.steps, t.started_at, tasksApi.isCancelling(t.id)])]);
        if (signature !== this._taskSignature) {
            this._taskSignature = signature;
            this._taskList.destroy_all_children();
            for (const t of tasks)
                this._taskList.add_child(this._buildTaskRow(t, hidden, now, tasksApi.isCancelling(t.id)));
        }
        this._taskEmpty.visible = tasks.length === 0;

        // The log is the one thing that is not in the state: read it for the
        // selected task while the card is on screen, never while sharing.
        const selected = this._selectedTaskId;
        if (selected === null || hidden) {
            this._taskLogBox.visible = false;
            return;
        }
        tasksApi.fetchTaskLog(selected, lines => this._renderTaskLog(selected, lines));
    }

    _buildTaskRow(task, hidden, now, cancelling) {
        const title = hidden ? "AI task in progress" : task.title || `Task #${task.id}`;
        const row = new St.BoxLayout({ style_class: "adaptive-island-task-row", vertical: false });
        if (task.id === this._selectedTaskId)
            row.add_style_class_name("selected");

        const info = new St.Button({ can_focus: true, x_expand: true,
            style_class: "adaptive-island-task-info",
            accessible_name: `Show the log for ${title}` });
        const text = new St.BoxLayout({ vertical: true, x_expand: true });
        text.add_child(_ellipsize(new St.Label({ text: title, style_class: "adaptive-island-task-title" })));
        const age = task.started_at ? ` · ${_formatAge(now - task.started_at)}` : "";
        text.add_child(_ellipsize(new St.Label({
            text: `${task.agent || "Agent"} · step ${task.steps || 0}${age}`,
            style_class: "adaptive-island-subtext",
        })));
        info.set_child(text);
        info.connect("clicked", () => {
            this._selectedTaskId = task.id;
            this._ui.refresh();
        });
        row.add_child(info);

        const cancel = _button(cancelling ? "Cancelling…" : "Cancel",
            "adaptive-island-btn adaptive-island-btn-alert", `Cancel ${title}`,
            () => this._ui.backend.tasks.cancelTask(task.id));
        cancel.reactive = !cancelling;
        cancel.y_align = Clutter.ActorAlign.CENTER;
        row.add_child(cancel);
        return row;
    }

    _renderTaskLog(taskId, lines) {
        if (!this._taskLogBox || taskId !== this._selectedTaskId)
            return;
        this._taskLogBox.destroy_all_children();
        if (!lines.length) {
            this._taskLogBox.add_child(new St.Label({ text: "Waiting for the first step…",
                style_class: "adaptive-island-terminal-line" }));
        }
        lines.forEach((line, i) => {
            const time = line.ts ? new Date(line.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
            const label = _ellipsize(new St.Label({
                text: `${time ? `[${time}] ` : ""}${line.text}`,
                style_class: "adaptive-island-terminal-line",
            }));
            if (i === lines.length - 1)
                label.add_style_class_name("active");
            this._taskLogBox.add_child(label);
        });
        this._taskLogBox.visible = true;
    }

    _renderMediaData(state) {
        this._titleIcon.text = "♫";
        this._titleLabel.text = "Now playing";

        const m = state.media || {};
        this._badgeLabel.text = !m.title ? "IDLE" : m.isPlaying ? "PLAYING" : "PAUSED";
        if (!this._mediaTitleLabel)
            return;

        this._mediaTitleLabel.text = m.title || "Nothing playing";
        this._mediaArtistLabel.text = m.title
            ? [m.artist, m.album].filter(Boolean).join(" · ") || "Unknown artist"
            : "Play something in any media app to control it here.";
        this._mediaPlayBtn.label = m.isPlaying ? "⏸" : "▶";
        this._mediaPlayBtn.accessible_name = m.isPlaying ? "Pause" : "Play";
        this._mediaPlayBtn.reactive = !!m.playerBusName;
        this._mediaPrevBtn.reactive = !!m.playerBusName && m.canGoPrevious !== false;
        this._mediaNextBtn.reactive = !!m.playerBusName && m.canGoNext !== false;

        // Cover art: GNOME's own media message loads it the same way.
        if (m.artUrl !== this._mediaArtUrl) {
            this._mediaArtUrl = m.artUrl;
            let gicon = null;
            if (m.artUrl && Gio) {
                try {
                    gicon = new Gio.FileIcon({ file: Gio.File.new_for_uri(m.artUrl) });
                } catch (e) {
                    gicon = null;
                }
            }
            this._mediaArtIcon.gicon = gicon;
            this._mediaArtIcon.visible = !!gicon;
            this._mediaArtFallback.visible = !gicon;
        }

        const players = this._ui.backend.media.getPlayers ? this._ui.backend.media.getPlayers() : [];
        const switchable = players.length > 1;
        this._mediaPlayerButton.visible = !!m.playerBusName;
        this._mediaPlayerButton.label = switchable
            ? `${m.identity} · switch (${players.length})` : m.identity || "";
        this._mediaPlayerButton.reactive = switchable;
        this._mediaPlayerButton.can_focus = switchable;
        this._mediaPlayerButton.accessible_name = switchable
            ? `Playing in ${m.identity}. Switch to another player` : `Playing in ${m.identity}`;

        this.renderMediaProgress(m);
    }

    // Elapsed time and the scrubber. Called by the 1 s ticker that runs only
    // while this card is on screen and something is playing.
    renderMediaProgress(track = null) {
        if (!this._mediaScrubberFill || !this._mediaCard.visible)
            return;
        const m = track || this._ui.backend.media.getCurrentTrack();
        const length = m.lengthUs || 0;
        const position = Math.min(m.positionUs || 0, length || Infinity);
        this._mediaElapsedLabel.text = m.title ? _formatUs(position) : "";
        this._mediaDurationLabel.text = length > 0 ? _formatUs(length) : m.title ? "Live" : "";
        const width = this._mediaScrubTrack.width;
        this._mediaScrubberFill.set_width(length > 0 && width > 0
            ? Math.round(width * Math.min(1, position / length)) : 0);
        this._mediaScrubTrack.reactive = !!m.canSeek;
        this._mediaScrubTrack.can_focus = !!m.canSeek;
        this._mediaScrubTrack.accessible_name = length > 0
            ? `Track position ${_formatUs(position)} of ${_formatUs(length)}` : "Track position";
    }

    _sizeTimerFill() {
        if (!this._timerFill || !this._timerTrack)
            return;
        this._timerFill.set_width(Math.round(this._timerTrack.width * this._timerProgress / 100));
    }

    _renderTimerData(state) {
        this._titleIcon.text = "⏱";
        this._titleLabel.text = "Focus timer";

        const t = state.timer || {};
        const status = t.status || "IDLE";
        this._badgeLabel.text = status;
        if (!this._timerDigitsLabel)
            return;

        this._timerDigitsLabel.text = t.formatted || "0:00";
        this._timerStatusTag.text = status === "IDLE" ? "IDLE" : `${(t.label || "Focus").toUpperCase()} · ${status}`;
        this._timerProgress = status === "IDLE" ? 0 : t.progressPercent || 0;
        this._sizeTimerFill();

        const live = status === "RUNNING" || status === "PAUSED";
        this._timerPauseBtn.visible = live;
        this._timerPauseBtn.label = status === "RUNNING" ? "Pause" : "Resume";
        this._timerPauseBtn.accessible_name = status === "RUNNING" ? "Pause the timer" : "Resume the timer";
        this._timerResetBtn.visible = status !== "IDLE";
        this._timerResetBtn.label = live ? "Stop" : "Dismiss";

        let note = "";
        if (live && t.dndHeld)
            note = "Do Not Disturb is on until this session ends.";
        else if (!live && t.lastDigest)
            note = `While you focused: ${t.lastDigest}.`;
        this._timerNoteLabel.text = note;
        this._timerNoteLabel.visible = !!note;
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
        this._shade = null;
        this._centerOverlay = null;
        this._centerSection = null;
        this._centerFeature = "overview";
        this._centerTabs = new Map(); // feature -> { button, badge, label }
        this._menuOpenId = 0;
        this._progressTimerId = 0;
        this._screencastNotifyId = 0;
        this._screencastSource = null;
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

        try {

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
                    this._syncScreenSharingFromShell();
                    this._anchor._clearGraceExitTimer();
                    if (this._anchor._hoverDwellTimerId) {
                        GLib.source_remove(this._anchor._hoverDwellTimerId);
                        this._anchor._hoverDwellTimerId = 0;
                    }
                    this.contract();
                    this._backend.pauseDwell();
                    if (this._centerFeature === "media")
                        this._backend.media.refreshPosition();
                    this._updateUI();
                } else {
                    this._backend.resumeDwell();
                    this._syncProgressTicker();
                }
            });
        }

        // 4. Hook Backend Event Subscriptions
        this._surfacedUnsub = this._backend.onSurfaced((bus, event) => this._onSurfaced(event));
        this._tuckedUnsub = this._backend.onTucked((bus, event) => this._onTucked(event));
        this._stateUnsub = this._backend.onStateChange((bus, state) => this._onStateChange(state));

        // 5. The Focus timer's end-of-session digest reads the Shade's list.
        // Install this before init(): a restored deadline may already have
        // elapsed, in which case restore emits its digest immediately.
        if (this._shade && this._backend.timers.setDigestSource) {
            const shade = this._shade;
            this._backend.timers.setDigestSource({
                mark: () => shade.notificationMark(),
                summary: mark => {
                    const s = shade.notificationsSince(mark);
                    if (!s || !s.count)
                        return "";
                    return `${s.count} notification${s.count === 1 ? "" : "s"} from ` +
                        `${s.apps} app${s.apps === 1 ? "" : "s"}`;
                },
            });
        }

        // 6. Initialize backend
        if (this._ownsBackend) {
            this._backend.init();
        }

        this._watchScreenSharing();

        if (typeof Main !== "undefined" && Main) {
            Main._dynamicIsland = this;
        }

        this._updateUI();
        } catch (e) {
            // attach() changes Shell-owned actors. Always put them back before
            // the extension drops this object after a failed installation.
            try {
                this.detach();
            } catch (cleanupError) {
                logError(cleanupError, "[Adaptive Island] cleaning up failed attach");
            }
            throw e;
        }
    }

    _watchScreenSharing() {
        const ui = Main && Main.screenshotUI;
        this._screencastSource = ui || null;
        this._syncScreenSharingFromShell();
        if (!ui || !ui.connect)
            return;
        try {
            this._screencastNotifyId = ui.connect("notify::screencast-in-progress",
                () => this._syncScreenSharingFromShell());
        } catch (e) {
            this._screencastNotifyId = 0;
        }
    }

    _syncScreenSharingFromShell() {
        const ui = this._screencastSource || (Main && Main.screenshotUI);
        this._backend.setScreenSharing(!!(ui && ui.screencast_in_progress));
    }

    _syncProviderActivity(state = null) {
        if (!this._backend.quota || !this._backend.quota.setDormant)
            return;
        state = state || this._backend.getState();
        const eventIsQuota = !!(state.surfacedEvent &&
            (state.surfacedEvent.payload || {}).provider === "quota");
        const centerShowsQuota = this.isCenterOpen() &&
            (this._centerFeature === "overview" || this._centerFeature === "quota");
        const overlayShowsQuota = this._overlay && this._overlay._isExpanded &&
            this._overlay._activeCardType === "quota";
        this._backend.quota.setDormant(!(eventIsQuota || centerShowsQuota || overlayShowsQuota));
    }

    // The Activity Center: tabs over an embedded card stack, mounted into the
    // Shade through its public API.
    _buildCenter() {
        const shade = this._extension && this._extension._shade;
        if (!St || !shade || !shade.mountActivityCenter) return;
        this._centerSection = new St.BoxLayout({ vertical: true,
            style_class: "adaptive-island-center", x_expand: true });
        const tabs = new St.BoxLayout({ style_class: "adaptive-island-actions adaptive-island-tabs", x_expand: true });
        for (const [feature, label] of CENTER_TABS) {
            const button = new St.Button({ can_focus: true, x_expand: true,
                style_class: "adaptive-island-chip adaptive-island-tab",
                accessible_name: label, toggle_mode: false });
            const box = new St.BoxLayout({ x_align: Clutter.ActorAlign.CENTER });
            box.add_child(new St.Label({ text: label, y_align: Clutter.ActorAlign.CENTER }));
            const badge = new St.Label({ text: "", style_class: "adaptive-island-tab-badge",
                y_align: Clutter.ActorAlign.CENTER, visible: false });
            box.add_child(badge);
            button.set_child(box);
            button.connect("clicked", () => this.selectCenterFeature(feature));
            tabs.add_child(button);
            this._centerTabs.set(feature, { button, badge, label });
        }
        this._centerSection.add_child(tabs);
        this._centerOverlay = new IslandOverlay(this, true);
        this._centerOverlay.build();
        this._centerSection.add_child(this._centerOverlay.getActor());
        if (!shade.mountActivityCenter(this._centerSection)) {
            this._centerOverlay.destroy();
            this._centerOverlay = null;
            this._centerSection.destroy();
            this._centerSection = null;
            this._centerTabs.clear();
            return;
        }
        this._shade = shade;
    }

    selectCenterFeature(feature) {
        this._centerFeature = feature;
        if (feature === "media")
            this._backend.media.refreshPosition();
        this._updateUI();
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

    // Before handing off to another app (Agent Office in the browser).
    closeAll() {
        this.contract();
        const dateMenu = Main && Main.panel && Main.panel.statusArea.dateMenu;
        if (dateMenu && dateMenu.menu && dateMenu.menu.isOpen)
            dateMenu.menu.close();
    }

    detach() {
        if (!this._attached) return;
        this._attached = false;

        // Disconnect backend listeners
        if (this._surfacedUnsub) { this._surfacedUnsub(); this._surfacedUnsub = null; }
        if (this._tuckedUnsub) { this._tuckedUnsub(); this._tuckedUnsub = null; }
        if (this._stateUnsub) { this._stateUnsub(); this._stateUnsub = null; }
        this._stopProgressTicker();

        if (this._screencastNotifyId && this._screencastSource) {
            try {
                this._screencastSource.disconnect(this._screencastNotifyId);
            } catch (e) {}
        }
        this._screencastNotifyId = 0;
        this._screencastSource = null;

        if (this._backend.timers.setDigestSource)
            this._backend.timers.setDigestSource(null);
        if (this._ownsBackend) {
            this._backend.destroy();
        }

        if (this._shade && this._centerSection)
            this._shade.unmountActivityCenter(this._centerSection);
        this._shade = null;
        if (this._centerOverlay) {
            this._centerOverlay.destroy();
            this._centerOverlay = null;
        }
        if (this._centerSection) {
            this._centerSection.destroy();
            this._centerSection = null;
        }
        this._centerTabs.clear();

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

    refresh() {
        this._updateUI();
    }

    // The pill always follows the state. The floating card and the Activity
    // Center are only drawn while someone can see them; opening either
    // renders it fresh.
    _updateUI(forcedState = null, renderOverlay = false) {
        const state = forcedState || this._backend.getState();
        this._anchor.renderState(state, this._theme);
        if (renderOverlay || this._overlay._isExpanded)
            this._overlay.renderState(state, this._theme, this._forcedFeature);
        if (this._centerOverlay && this.isCenterOpen()) {
            this._centerOverlay.renderState(state, this._theme, this._centerFeature);
            const badges = describeBadges(state);
            for (const [feature, tab] of this._centerTabs) {
                if (feature === this._centerFeature) tab.button.add_style_pseudo_class("checked");
                else tab.button.remove_style_pseudo_class("checked");
                const badge = badges[feature] || { text: "", level: "normal" };
                tab.badge.text = badge.text;
                tab.badge.visible = !!badge.text;
                _setLevelClass(tab.badge, "adaptive-island-tab-badge", badge.level);
                tab.button.accessible_name = badge.text ? `${tab.label}, ${badge.text}` : tab.label;
            }
        }
        this._syncProviderActivity(state);
        this._syncProgressTicker();
    }

    // A 1 s redraw of the music scrubber, alive only while a Music card is on
    // screen and the track is moving.
    _syncProgressTicker() {
        const mediaShown = (this._centerOverlay && this._centerFeature === "media" && this.isCenterOpen()) ||
            (this._overlay._isExpanded && this._overlay._activeCardType === "media");
        let moving = false;
        if (mediaShown) {
            const track = this._backend.media.getCurrentTrack();
            moving = track.isPlaying && track.lengthUs > 0;
        }
        if (!(GLib && mediaShown && moving)) {
            this._stopProgressTicker();
            return;
        }
        if (this._progressTimerId)
            return;
        this._progressTimerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._overlay.renderMediaProgress();
            if (this._centerOverlay)
                this._centerOverlay.renderMediaProgress();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopProgressTicker() {
        if (this._progressTimerId && GLib) {
            GLib.source_remove(this._progressTimerId);
            this._progressTimerId = 0;
        }
    }

    expand(targetFeature = null, forcedState = null) {
        if (this.isCenterOpen()) return;
        this._forcedFeature = targetFeature;
        if (targetFeature === "media")
            this._backend.media.refreshPosition();
        this._updateUI(forcedState, true);
        this._overlay.showOverlay(this._anchor.getActor());
        this._syncProgressTicker();
    }

    contract(forcedState = null) {
        this._forcedFeature = null;
        this._overlay.hideOverlay();
        this._syncProgressTicker();
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
    module.exports = { IslandUI, IslandAnchor, IslandOverlay, IslandTheme, IslandState,
        describeOverview, describeBadges };
}
