// Adaptive Shell - where each dock sits, and when it hides and comes back.
//
// Part of the one AdaptiveShellV16 object in extension.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the shell itself and every
// field and method of the other parts is reachable through it.

/* exported ShellDockAutohide */

const { St, GLib, Clutter, Shell, Meta } = imports.gi;
const Main = imports.ui.main;
const Layout = imports.ui.layout;

var ShellDockAutohide = class ShellDockAutohide {
    _dock26MonitorCount() {
        try {
            return Main.layoutManager.monitors.length;
        } catch (e) {
            return 0;
        }
    }

    _dock26PrimaryMonitorIndex() {
        try {
            const index = global.display.get_primary_monitor();
            if (
                Number.isInteger(index) &&
                index >= 0 &&
                index < this._dock26MonitorCount()
            )
                return index;
        } catch (e) {
        }
        return 0;
    }

    _dock26Monitor(index) {
        const monitors = Main.layoutManager.monitors || [];
        if (
            Number.isInteger(index) &&
            index >= 0 &&
            index < monitors.length
        )
            return monitors[index];

        const fallback = this._dock26PrimaryMonitorIndex();
        return monitors[fallback] ||
            Main.layoutManager.primaryMonitor ||
            null;
    }

    _dock26WindowMonitor(window) {
        if (window) {
            try {
                const index = window.get_monitor();
                if (
                    Number.isInteger(index) &&
                    index >= 0 &&
                    index < this._dock26MonitorCount()
                )
                    return index;
            } catch (e) {
            }
        }

        try {
            const current = global.display.get_current_monitor();
            if (
                Number.isInteger(current) &&
                current >= 0 &&
                current < this._dock26MonitorCount()
            )
                return current;
        } catch (e) {
        }

        return this._dock26PrimaryMonitorIndex();
    }

    _dock26EnsureTargetMonitor() {
        const count = this._dock26MonitorCount();

        if (!count) {
            this._dock26TargetMonitor = -1;
            return;
        }

        if (
            !Number.isInteger(this._dock26TargetMonitor) ||
            this._dock26TargetMonitor < 0 ||
            this._dock26TargetMonitor >= count
        ) {
            this._dock26TargetMonitor =
                this._dock26WindowMonitor(
                    global.display.get_focus_window()
                );
        }
    }

    _dock26DestroyHotEdges() {
        for (const entry of this._dock26HotEdges) {
            if (!entry || !entry.actor)
                continue;

            try {
                Main.layoutManager.removeChrome(entry.actor);
            } catch (e) {
            }

            try {
                entry.actor.destroy();
            } catch (e) {
            }
        }

        this._dock26HotEdges = [];

        if (this._dock26Pressure) {
            this._dock26Pressure.destroy();
            this._dock26Pressure = null;
        }

        for (const barrier of this._dock26Barriers) {
            try {
                barrier.destroy();
            } catch (e) {
            }
        }

        this._dock26Barriers = [];
    }

    _dock26SupportsBarriers() {
        try {
            return global.display.supports_extended_barriers();
        } catch (e) {
            return false;
        }
    }

    // A mouse button held down means a drag - selecting cells or text,
    // resizing a row - that happens to run into the bottom of the screen.
    // macOS does not bring the Dock up for that, and neither does this.
    _dock26PointerButtonHeld() {
        try {
            const [, , mods] = global.get_pointer();
            return !!(mods & (
                Clutter.ModifierType.BUTTON1_MASK |
                Clutter.ModifierType.BUTTON2_MASK |
                Clutter.ModifierType.BUTTON3_MASK
            ));
        } catch (e) {
            return false;
        }
    }

    _dock26RebuildHotEdges() {
        this._dock26DestroyHotEdges();

        // Indexes are renumbered when a display is plugged or unplugged, so a
        // remembered target can now point at a different screen - or at none.
        // Re-resolve from the pointer's own monitor instead of trusting it.
        this._dock26ClearReveals();
        this._dock26TargetMonitor = -1;

        if (this._dock26SupportsBarriers())
            this._dock26BuildBarriers();
        else
            this._dock26BuildFallbackEdges();

        this._dock26EnsureTargetMonitor();
        this._dock26SyncTargetFromFocus(false);
        this._dock26Layout();
    }

    _dock26BuildBarriers() {
        const monitors = Main.layoutManager.monitors || [];

        this._dock26Pressure = new Layout.PressureBarrier(
            this._dock26PressureThreshold,
            this._dock26PressureTimeoutMs,
            Shell.ActionMode.NORMAL
        );

        // Barriers never fire their hit while a button is down, so a drag
        // selection running into the bottom edge builds up no pressure.
        this._dock26Pressure.setEventFilter(
            () => this._dock26PointerButtonHeld()
        );

        // The trigger signal says nothing about which barrier was pushed, and
        // the barrier needs the event back to let the pointer through to a
        // monitor stacked underneath. Each barrier's own hit handler runs
        // before the pressure barrier's (it is connected first) and records it.
        let lastHit = null;

        this._dock26Pressure.connect('trigger', () => {
            const hit = lastHit;
            lastHit = null;
            if (!hit)
                return;

            this._dock26RequestReveal(hit.barrier._adaptiveMonitor);

            try {
                hit.barrier.release(hit.event);
            } catch (e) {
            }
        });

        monitors.forEach((monitor, index) => {
            const y = monitor.y + monitor.height;

            try {
                const barrier = new Meta.Barrier({
                    display: global.display,
                    x1: monitor.x,
                    x2: monitor.x + monitor.width,
                    y1: y,
                    y2: y,
                    directions: Meta.BarrierDirection.NEGATIVE_Y,
                });

                barrier._adaptiveMonitor = index;
                barrier.connect('hit', (b, event) => {
                    lastHit = { barrier: b, event };
                });

                this._dock26Pressure.addBarrier(barrier);
                this._dock26Barriers.push(barrier);
            } catch (e) {
                logError(e, `[Adaptive Shell] dock barrier monitor ${index}`);
            }
        });

        log(`[Adaptive Shell] dock reveal: pressure barriers on `
            + `${this._dock26Barriers.length} monitor(s)`);
    }

    _dock26BuildFallbackEdges() {
        const monitors = Main.layoutManager.monitors || [];

        monitors.forEach((monitor, index) => {
            const edge = new St.Widget({
                reactive: true,
                track_hover: true,
                style_class: 'adaptive-dock-hot-edge',
            });

            edge.set_position(
                monitor.x,
                monitor.y + monitor.height -
                    this._dock26HotEdgeHeight
            );
            edge.set_size(
                monitor.width,
                this._dock26HotEdgeHeight
            );

            edge.connect(
                'enter-event',
                () => {
                    this._dock26OnEdgeEnter(index);
                    return Clutter.EVENT_PROPAGATE;
                }
            );

            edge.connect(
                'leave-event',
                () => {
                    this._dock26CancelReveal();
                    return Clutter.EVENT_PROPAGATE;
                }
            );

            Main.layoutManager.addChrome(
                edge,
                {
                    affectsStruts: false,
                    trackFullscreen: false,
                }
            );

            this._dock26HotEdges.push({
                actor: edge,
                index,
            });
        });

        log(`[Adaptive Shell] dock reveal: no extended barriers, `
            + `${this._dock26HotEdges.length} dwell edge(s)`);
    }

    _dock26EdgeForMonitor(index) {
        const entry = this._dock26HotEdges.find(
            item => item.index === index
        );
        return entry ? entry.actor : null;
    }

    _dock26WindowFullyMaximized(window) {
        if (!window)
            return false;

        try {
            if (
                typeof window.is_maximized === 'function'
            )
                return !!window.is_maximized();
        } catch (e) {
        }

        try {
            const flags = window.get_maximize_flags();
            return !!(
                (flags & Meta.MaximizeFlags.HORIZONTAL) &&
                (flags & Meta.MaximizeFlags.VERTICAL)
            );
        } catch (e) {
        }

        try {
            return !!(
                window.maximized_horizontally &&
                window.maximized_vertically
            );
        } catch (e) {
            return false;
        }
    }

    // Mutter's get_monitor_in_fullscreen() tracks the *topmost* window, so it
    // flips false the moment anything stacks above the fullscreen window - a
    // quick-settings menu, a Ctrl+Alt+T terminal, a file-picker for an upload.
    // The dock would then reveal itself over content that is still fullscreen.
    // So it is only one of two signals: the workspace scan below reports a
    // fullscreen window on this monitor no matter what sits on top of it.
    _dock26MonitorInFullscreen(index) {
        // Mutter asserts rather than returning false for an index it does not
        // have, and this one is -1 before the first resolve and stale for a
        // moment after a display is unplugged.
        const monitors = this._dock26MonitorCount();
        const valid = Number.isInteger(index) && index >= 0 && index < monitors;

        try {
            if (
                valid &&
                typeof global.display
                    .get_monitor_in_fullscreen === 'function'
            ) {
                if (!!global.display.get_monitor_in_fullscreen(index))
                    return true;
            }
        } catch (e) {
        }

        try {
            const workspace =
                global.workspace_manager.get_active_workspace();

            if (!workspace)
                return false;

            for (const window of workspace.list_windows()) {
                try {
                    // A minimized fullscreen window is not on screen, so it
                    // must not keep the dock suppressed.
                    if (
                        window.get_monitor() === index &&
                        window.is_fullscreen() &&
                        !window.minimized
                    )
                        return true;
                } catch (e) {
                }
            }
        } catch (e) {
        }

        return false;
    }

    // Deliberately not "the focused window is maximized". A quick-settings
    // menu, a Ctrl+Alt+T terminal or an upload dialog takes focus away from
    // the maximized window without moving it, and a focus-only test then said
    // "nothing is maximized" and revealed the dock over content the user was
    // still reading. What matters is whether a maximized window occupies this
    // monitor at all.
    _dock26MonitorHasFocusedMaximized(index) {
        if (!this._dock26HideOnMaximized)
            return false;

        const focused = global.display.get_focus_window();

        try {
            if (
                focused &&
                focused.get_monitor() === index &&
                this._dock26WindowFullyMaximized(focused)
            )
                return true;
        } catch (e) {
        }

        try {
            const workspace =
                global.workspace_manager.get_active_workspace();

            if (!workspace)
                return false;

            for (const window of workspace.list_windows()) {
                try {
                    if (
                        window.get_monitor() === index &&
                        !window.minimized &&
                        this._dock26WindowFullyMaximized(window)
                    )
                        return true;
                } catch (e) {
                }
            }
        } catch (e) {
        }

        return false;
    }

    _dock26RaiseAboveWindows(dock) {
        const rail = dock && dock.rail;
        if (!rail)
            return;

        try {
            const parent = rail.get_parent();
            if (parent)
                parent.set_child_above_sibling(rail, null);
        } catch (e) {
        }
    }

    _dock26Locked() {
        return (
            Main.sessionMode.isLocked ||
            Main.sessionMode.currentMode === 'unlock-dialog'
        );
    }

    _dock26MonitorNeedsHide(index) {
        // Setting visible=false from outside does not survive: the dock's own
        // layout pass runs afterwards and shows it again. Locked has to be one
        // of the dock's own reasons to stay down.
        if (this._dock26Locked())
            return true;

        // In the Overview nothing covers the dock, and it has to be there to
        // take apps dragged from the app grid.
        if (Main.overview && Main.overview.visible)
            return false;

        // Dock Settings → Auto-hide. "always" keeps it down until reached
        // for; "never" keeps it up except over fullscreen content.
        const mode = this._dockConfig.autoHide;
        if (mode === 'always')
            return true;
        if (mode === 'never')
            return this._dock26MonitorInFullscreen(index);

        return (
            this._dock26MonitorInFullscreen(index) ||
            this._dock26MonitorHasFocusedMaximized(index)
        );
    }

    // Focus used to move the dock to the focused window's monitor, which is
    // exactly why the other screen had none. Every monitor has its own dock
    // now, so focus only affects whether a dock should hide behind a
    // fullscreen or maximized window on its own monitor.
    _dock26SyncTargetFromFocus(_forceMove = true) {
        this._dock26WatchFocusWindow();
        this._dock26SyncVisibility();
    }

    _dock26DisconnectFocusWindow() {
        if (!this._dock26FocusWindow) {
            this._dock26FocusSignalIds = [];
            return;
        }

        for (const id of this._dock26FocusSignalIds) {
            try {
                this._dock26FocusWindow.disconnect(id);
            } catch (e) {
            }
        }

        this._dock26FocusSignalIds = [];
        this._dock26FocusWindow = null;
    }

    _dock26WatchFocusWindow() {
        this._dock26DisconnectFocusWindow();

        const window = global.display.get_focus_window();
        if (!window)
            return;

        this._dock26FocusWindow = window;

        const changed = () => this._dock26SyncVisibility();

        for (const signal of [
            'notify::maximized-horizontally',
            'notify::maximized-vertically',
            'notify::fullscreen',
            'size-changed',
            'position-changed',
        ]) {
            try {
                const id = window.connect(signal, changed);
                this._dock26FocusSignalIds.push(id);
            } catch (e) {
            }
        }
    }

    _dock26CancelReveal() {
        if (!this._dock26RevealTimerId)
            return;

        GLib.Source.remove(this._dock26RevealTimerId);
        this._dock26RevealTimerId = 0;
    }

    _dock26CancelHide() {
        for (const dock of this._docks || [])
            this._dockCancelHide(dock);
    }

    // Nothing is being deliberately reached for any more, on any screen.
    _dock26ClearReveals() {
        for (const dock of this._docks || [])
            dock.revealed = false;
    }

    // Fallback only (no extended barriers): the pointer has to rest on the
    // 1px edge, so passing over it on the way to something does nothing.
    _dock26OnEdgeEnter(index) {
        this._dock26CancelReveal();

        this._dock26RevealTimerId =
            GLib.timeout_add(
                GLib.PRIORITY_DEFAULT,
                this._dock26RevealDelayMs,
                () => {
                    this._dock26RevealTimerId = 0;

                    const edge =
                        this._dock26EdgeForMonitor(index);

                    if (
                        edge &&
                        edge.hover &&
                        !this._dock26PointerButtonHeld()
                    )
                        this._dock26RequestReveal(index);

                    return GLib.SOURCE_REMOVE;
                }
            );
    }

    // A deliberate reach for the dock on this monitor.
    _dock26RequestReveal(index) {
        const dock = this._dockForMonitor(index);

        log(`[Adaptive Shell] dock reveal request monitor ${index}, `
            + `dock ${dock ? 'found' : 'MISSING'}`);

        if (!dock)
            return;

        this._dockCancelHide(dock);
        this._dock26TargetMonitor = index;

        // Never over a locked screen; everywhere else the reveal is
        // honoured, fullscreen included.
        dock.revealed = !this._dock26Locked();
        this._dock26Layout();

        if (dock.revealed)
            this._dock26WatchPointer(dock);
    }

    // Is the pointer still using the dock? Over it, in the gap between it and
    // the screen edge (where the push that revealed it left the pointer), or
    // in one of its menus.
    _dock26PointerHoldsDock(dock) {
        if (!dock)
            return false;

        // An auto-hidden dock stays up for the whole of a drag, or the drop
        // target would slide away from under the icon being dragged.
        if (this._dockDrag)
            return true;

        // The previews float above the dock; moving into them keeps it up.
        if (this._previews && this._previews.hovered)
            return true;

        if (dock.rail && dock.rail.hover)
            return true;

        if (this._dockMenus.some(menu => menu.isOpen))
            return true;

        const monitor = (Main.layoutManager.monitors || [])[dock.index];
        const zone = dock.zone;
        if (!monitor || !zone)
            return false;

        try {
            const [px, py] = global.get_pointer();
            const slack = 8;

            return (
                px >= zone.x - slack &&
                px < zone.x + zone.width + slack &&
                py >= zone.y - slack &&
                py < monitor.y + monitor.height
            );
        } catch (e) {
            return false;
        }
    }

    // A revealed dock never sees a leave-event if the pointer never entered
    // it - the push leaves the pointer on the edge, below the dock. So while
    // it is revealed, watch where the pointer is and put it away once the
    // pointer has moved off, the way the macOS Dock does.
    _dock26WatchPointer(dock) {
        if (!dock || dock.pointerWatchId)
            return;

        dock.pointerWatchId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            this._dock26PointerPollMs,
            () => {
                if (!dock.revealed) {
                    dock.pointerWatchId = 0;
                    return GLib.SOURCE_REMOVE;
                }

                if (this._dock26PointerHoldsDock(dock))
                    this._dockCancelHide(dock);
                else if (!dock.hideId)
                    this._dockScheduleHide(dock);

                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    _dock26StopWatchingPointer(dock) {
        if (dock && dock.pointerWatchId) {
            GLib.Source.remove(dock.pointerWatchId);
            dock.pointerWatchId = 0;
        }
    }

    _dock26ShowDock(dock, animated) {
        const rail = dock && dock.rail;
        if (!rail)
            return;

        rail.reactive = true;
        rail.show();
        rail.remove_all_transitions();

        if (!animated) {
            rail.opacity = 255;
            rail.translation_y = 0;
            return;
        }

        rail.ease({
            opacity: 255,
            translation_y: 0,
            duration: this._dock26RevealDurationMs,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this._dock26UpdateRegions(),
        });
    }

    _dock26HideDock(dock, animated) {
        const rail = dock && dock.rail;
        if (!rail)
            return;

        // The pointer can still be over an icon when the dock slides away, and
        // the tooltip would then be left floating on the wallpaper with no dock
        // under it.
        this._hideTooltip();

        rail.reactive = false;
        rail.remove_all_transitions();

        const offset =
            this._dock26SurfaceHeight +
            this._dock26BottomGap + 8;

        if (!animated) {
            rail.opacity = 0;
            rail.translation_y = offset;
            return;
        }

        rail.ease({
            opacity: 0,
            translation_y: offset,
            duration: this._dock26HideDurationMs,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this._dock26UpdateRegions(),
        });
    }

    // The dock should be exactly as wide as what it shows.
    _dock26ContentWidth(rail = this._rail) {
        if (!rail)
            return 0;

        const children = rail
            .get_children()
            .filter(child => child.visible);

        let content = 0;

        for (const child of children) {
            const [, natural] = child.get_preferred_width(
                this._dock26SurfaceHeight
            );
            content += Math.ceil(natural);

            // Margins sit outside the preferred width, so leaving them out
            // makes the dock narrower than its own contents.
            try {
                const childNode = child.get_theme_node();
                content +=
                    childNode.get_margin(St.Side.LEFT) +
                    childNode.get_margin(St.Side.RIGHT);
            } catch (e) {
            }
        }

        let spacing = 0;
        let padding = 0;

        try {
            const node = rail.get_theme_node();
            spacing = node.get_length('spacing');
            padding =
                node.get_horizontal_padding() +
                node.get_border_width(St.Side.LEFT) +
                node.get_border_width(St.Side.RIGHT);
        } catch (e) {
        }

        if (children.length > 1)
            content += spacing * (children.length - 1);

        const width = Math.ceil(content + padding);

        // One NaN from a theme lookup would land in set_size() and assert.
        return Number.isFinite(width) ? width : 0;
    }

    _dock26Layout() {
        for (const dock of this._docks || [])
            this._dock26LayoutOne(dock);

        this._dock26LayoutReservation();
        this._dock26QueueRelayout();
        this._dock26UpdateRegions();
    }

    // The 1px strut sits on the primary monitor. It never grows: an
    // auto-hiding dock is an overlay, and a strut that toggled between 70px
    // and 1px re-ran the work-area calculation and visibly resized every
    // maximized window on the screen.
    _dock26LayoutReservation() {
        if (!this._dockChrome)
            return;

        const monitor = this._dock26Monitor(
            this._dock26PrimaryMonitorIndex()
        );
        if (!monitor)
            return;

        this._dockChrome.set_position(
            monitor.x,
            monitor.y + monitor.height - 1
        );
        this._dockChrome.set_size(monitor.width, 1);
    }

    _dock26LayoutOne(dock) {
        if (!dock || !dock.rail)
            return;

        const index = dock.index;

        // Deliberately not _dock26Monitor(), which falls back to the primary
        // monitor for an unknown index. Between a display being unplugged and
        // the docks being rebuilt that would stack two docks on one screen.
        const monitor = (Main.layoutManager.monitors || [])[index];
        if (!monitor) {
            dock.rail.hide();
            return;
        }

        // Width is summed from the children rather than taken from
        // get_preferred_width(). Some child over-claimed, so the rail was
        // allocated ~540px wider than its icons; the box was centred correctly
        // but the icons packed against its right edge, which reads as a dock
        // sitting well right of centre.
        const naturalWidth = this._dock26ContentWidth(dock.rail);
        dock.contentWidth = naturalWidth;

        const width = Math.max(
            100,
            Math.min(
                Math.ceil(naturalWidth),
                monitor.width - 24
            )
        );

        // Centre on this monitor, then clamp inside it. With an external
        // display attached the X screen is the union of both monitors, so a
        // stale or screen-sized geometry here pushed the dock off-centre
        // towards the second monitor instead of sitting in the middle of the
        // one it belongs to.
        const centred =
            monitor.x +
            Math.round((monitor.width - width) / 2);

        const x = Math.max(
            monitor.x,
            Math.min(centred, monitor.x + monitor.width - width)
        );

        const y =
            monitor.y +
            monitor.height -
            this._dock26SurfaceHeight -
            this._dock26BottomGap;

        // A 1024px-wide monitor cannot fit the whole dock. Clip only in that
        // case, so the overflow stops at the screen edge instead of painting
        // across onto the neighbouring monitor - and so the dock's shadow is
        // left intact everywhere it does fit.
        dock.rail.clip_to_allocation = naturalWidth > width;

        dock.rail.set_position(x, y);
        dock.rail.set_size(
            width,
            this._dock26SurfaceHeight
        );
        dock.zone = { x, y, width };

        // Logged on change only, so a misplaced dock can be diagnosed from the
        // journal without a running Looking Glass.
        const placement = `${width}x${this._dock26SurfaceHeight}+${x}+${y}`;
        if (dock.placement !== placement) {
            dock.placement = placement;
            log(`[Adaptive Shell] dock monitor ${index}: ${placement} `
                + `(monitor ${monitor.width}x${monitor.height}`
                + `+${monitor.x}+${monitor.y})`);
        }

        const hidden =
            this._dock26MonitorNeedsHide(index);

        if (hidden && this._dock26Locked()) {
            // Locked is the only absolute: nothing of the desktop goes on top
            // of the lock screen, hot edge included.
            dock.revealed = false;
            this._dock26HideDock(dock, true);
        } else if (hidden) {
            // Fullscreen suppresses the dock appearing *by itself*, which was
            // the original complaint, but reaching for the bottom edge is a
            // deliberate request and still works.
            if (dock.revealed) {
                this._dock26ShowDock(dock, true);
                this._dock26RaiseAboveWindows(dock);
            } else {
                this._dock26HideDock(dock, true);
            }
        } else {
            dock.revealed = false;
            this._dock26ShowDock(dock, false);
        }
    }

    // Icons can finish allocating after the layout ran, leaving a dock centred
    // on a stale width. Re-check once on idle and correct if it moved.
    _dock26QueueRelayout() {
        if (!this._dock26RelayoutId) {
            this._dock26RelayoutId = GLib.idle_add(
                GLib.PRIORITY_DEFAULT_IDLE,
                () => {
                    this._dock26RelayoutId = 0;

                    // Compare against the width the layout was computed
                    // from, not against the dock's allocated width. The
                    // allocated width is clamped to the monitor and to a
                    // minimum, so on a narrow screen it legitimately differs
                    // from the content width forever - and comparing those two
                    // made this idle re-run the layout, re-arm itself, and spin
                    // the shell's main loop until GC was starved out.
                    const stale = (this._docks || []).some(dock => {
                        if (!dock.rail)
                            return false;

                        const settled =
                            this._dock26ContentWidth(dock.rail);

                        return settled > 0 &&
                            Math.abs(settled - (dock.contentWidth || 0)) > 1;
                    });

                    if (stale && this._dock26SettlePasses < 4) {
                        this._dock26SettlePasses += 1;
                        this._dock26Layout();
                    } else {
                        this._dock26SettlePasses = 0;
                    }

                    return GLib.SOURCE_REMOVE;
                }
            );
        }
    }

    // The X input region is built from each chrome actor's transformed
    // position, translation included, but the layout manager only rebuilds it
    // when an actor's allocation or visibility changes - never for an ease of
    // translation_y. Queued at the start of a slide, it captured the dock where
    // it was, not where it was going: a revealed dock was drawn but its clicks
    // fell through to the window underneath, and a hidden one left an
    // invisible patch at the bottom of the screen that swallowed them. So the
    // show and hide eases queue it again when they land.
    _dock26UpdateRegions() {
        try {
            if (
                typeof Main.layoutManager
                    ._queueUpdateRegions === 'function'
            )
                Main.layoutManager._queueUpdateRegions();
        } catch (e) {
            logError(
                e,
                '[Adaptive Shell] v2.6 work-area update'
            );
        }
    }

    _dock26SyncVisibility() {
        this._dock26EnsureTargetMonitor();
        this._dock26Layout();
    }

    _dock26ConnectRuntime() {
        this._dock26RebuildHotEdges();

        if (!this._dock26FullscreenSignalId) {
            try {
                this._dock26FullscreenSignalId =
                    global.display.connect(
                        'in-fullscreen-changed',
                        () => {
                            this._dock26ClearReveals();
                            this._dock26SyncVisibility();
                        }
                    );
            } catch (e) {
                logError(
                    e,
                    '[Adaptive Shell] v2.6 fullscreen signal'
                );
            }
        }

        if (!this._dock26FocusChangedId) {
            this._dock26FocusChangedId =
                global.display.connect(
                    'notify::focus-window',
                    () =>
                        this._dock26SyncTargetFromFocus(true)
                );
        }

        if (!this._dock26WindowEnteredMonitorId) {
            try {
                this._dock26WindowEnteredMonitorId =
                    global.display.connect(
                        'window-entered-monitor',
                        (_display, monitorIndex, window) => {
                            if (
                                window ===
                                global.display.get_focus_window()
                            ) {
                                this._dock26TargetMonitor =
                                    monitorIndex;
                                this._dock26SyncVisibility();
                            }
                        }
                    );
            } catch (e) {
            }
        }

        if (!this._dock26MonitorsChangedId) {
            this._dock26MonitorsChangedId =
                Main.layoutManager.connect(
                    'monitors-changed',
                    () => {
                        // A new display needs its own dock, and a removed one
                        // leaves a dock pointing at a monitor index that no
                        // longer exists.
                        this._buildDocks();
                        this._refreshWindowList();
                        this._dock26RebuildHotEdges();
                    }
                );
        }

        this._dock26SyncTargetFromFocus(true);
    }

    _dock26Cleanup() {
        this._dock26CancelReveal();
        this._dock26CancelHide();
        this._dock26DisconnectFocusWindow();
        this._dock26DestroyHotEdges();

        if (this._dock26FullscreenSignalId) {
            try {
                global.display.disconnect(
                    this._dock26FullscreenSignalId
                );
            } catch (e) {
            }
            this._dock26FullscreenSignalId = 0;
        }

        if (this._dock26FocusChangedId) {
            try {
                global.display.disconnect(
                    this._dock26FocusChangedId
                );
            } catch (e) {
            }
            this._dock26FocusChangedId = 0;
        }

        if (this._dock26WindowEnteredMonitorId) {
            try {
                global.display.disconnect(
                    this._dock26WindowEnteredMonitorId
                );
            } catch (e) {
            }
            this._dock26WindowEnteredMonitorId = 0;
        }

        if (this._dock26MonitorsChangedId) {
            try {
                Main.layoutManager.disconnect(
                    this._dock26MonitorsChangedId
                );
            } catch (e) {
            }
            this._dock26MonitorsChangedId = 0;
        }
    }
};
