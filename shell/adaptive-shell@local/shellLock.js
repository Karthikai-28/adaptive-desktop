// Adaptive Shell - the Adaptive lock screen and its always-on display.
//
// Part of the one AdaptiveShellV16 object in extension.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the shell itself and every
// field and method of the other parts is reachable through it.

/* exported ShellLock */

const { St, Gio, GLib, Clutter, Shell } = imports.gi;
const Main = imports.ui.main;

const Pango = imports.gi.Pango;

// Always-on-display tuning. The drift keeps a static clock from ghosting an
// OLED; the ambient level is what it settles to once nobody is looking.
const LOCK_AMBIENT_AFTER_S = 12;
const LOCK_AMBIENT_OPACITY = 145;
const LOCK_DRIFT_INTERVAL_S = 90;
const LOCK_DRIFT_RADIUS_PX = 14;
// Idle time on the lock screen before the screen-saver state takes over.
const AOD_IDLE_MS = 30 * 1000;

var ShellLock = class ShellLock {
    _lockHideDesktopChrome(hidden) {
        const actors = (this._docks || []).map(dock => dock.rail);
        actors.push(this._dockChrome);

        for (const actor of actors) {
            if (!actor)
                continue;

            try {
                actor.visible = !hidden;
            } catch (e) {
            }
        }

        if (hidden)
            this._hideTooltip();

        // Ask the dock to re-evaluate, so it hides through its own path too.
        try {
            this._dock26Layout();
        } catch (e) {
        }
    }

    _lockScreenStart() {
        this._lockAttempts = 0;

        // Installed up front and driven by its own timer. Tying either to the
        // unlock dialog meant both died with it: screenShield.js destroys the
        // dialog when it blanks, which is exactly when the always-on layer is
        // supposed to take over.
        this._aodInstall();

        if (!this._lockTickId) {
            this._lockTickId = GLib.timeout_add_seconds(
                GLib.PRIORITY_DEFAULT,
                1,
                () => {
                    try {
                        this._lockTick();
                    } catch (e) {
                        logError(e, '[Adaptive Shell] lock tick');
                        this._lockTickId = 0;
                        return GLib.SOURCE_REMOVE;
                    }

                    return GLib.SOURCE_CONTINUE;
                }
            );
        }

        // The dialog is built lazily, so it may not exist the moment the
        // extension is enabled into unlock-dialog mode.
        this._lockAttachId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            300,
            () => {
                let done = false;

                try {
                    done = this._lockScreenAttach();
                } catch (e) {
                    logError(e, '[Adaptive Shell] lock screen attach');
                    done = true;
                }

                this._lockAttempts += 1;

                if (done || this._lockAttempts > 25) {
                    this._lockAttachId = 0;
                    return GLib.SOURCE_REMOVE;
                }

                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    _lockScreenAttach() {
        const shield = Main.screenShield;
        const dialog = shield ? shield._dialog : null;

        if (!dialog || !dialog._clock || !dialog._clock._time)
            return false;

        const clock = dialog._clock;

        if (clock._adaptiveLock)
            return true;

        clock._adaptiveLock = true;

        // GNOME leaves the prompt column at its natural alignment, which puts
        // the password box off to one side of the shield.
        try {
            dialog._promptBox.x_align = Clutter.ActorAlign.CENTER;
            dialog._promptBox.x_expand = true;
        } catch (e) {
        }

        // GNOME blurs and dims the wallpaper behind the password prompt. Show
        // it as it is instead: the effect stays attached but does nothing.
        // GNOME re-runs _updateBackgroundEffects on scale and monitor changes,
        // so it is replaced rather than applied once.
        try {
            dialog._updateBackgroundEffects = () => {
                for (const widget of dialog._backgroundGroup) {
                    const effect = widget.get_effect('blur');
                    if (effect)
                        effect.set({ brightness: 1.0, sigma: 0 });
                }
            };
            dialog._updateBackgroundEffects();
        } catch (e) {
            logError(e, '[Adaptive Shell] lock wallpaper');
        }

        const activity = new St.Label({
            style_class: 'adaptive-lock-activity',
            x_align: Clutter.ActorAlign.CENTER,
        });
        activity.clutter_text.line_wrap = true;
        activity.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        activity.visible = false;

        try {
            clock.insert_child_below(activity, clock._hint);
        } catch (e) {
            clock.add_child(activity);
        }

        // St.Label ellipsizes by default. The label was sized for "01:20", so
        // appending seconds overflowed it and Pango replaced them with an
        // ellipsis - the seconds showed up as dots.
        try {
            clock._time.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
            clock._time.clutter_text.line_wrap = false;
            clock._time.x_expand = true;
        } catch (e) {
        }

        this._lockClock = clock;
        this._lockActivity = activity;

        // GNOME's own _updateClock() writes the wall clock's HH:MM into the
        // same label once a minute, which wiped the seconds every time the
        // minute rolled over. Wrapping it - rather than racing it from a
        // timer - means the date still updates GNOME's way and the seconds
        // are re-applied in the same frame, so the format never flickers.
        if (!clock._adaptiveUpdateClock) {
            clock._adaptiveUpdateClock = clock._updateClock.bind(clock);

            clock._updateClock = () => {
                clock._adaptiveUpdateClock();

                try {
                    this._lockApplyTime();
                } catch (e) {
                }
            };
        }

        this._lockTick();

        // Only the dialog's own bits are dropped here. The session is still
        // locked, so the always-on layer and the timer keep running.
        clock.connect('destroy', () => this._lockDetachDialog());

        log('[Adaptive Shell] lock screen clock extended');
        return true;
    }

    _lockTick() {
        // The dialog may be gone while the session stays locked; the always-on
        // layer below is what keeps the time on screen after that.
        this._lockApplyTime();

        if (this._lockAlive(this._lockActivity)) {
            this._lockActivity.text = this._lockActivitySummary();
            this._lockActivity.visible = !!this._lockActivity.text;
        }

        this._aodUpdate();

        this._lockTicks = (this._lockTicks || 0) + 1;
        this._lockAmbientStep();
    }

    // Always-on behaviour, borrowed from how phones do it.
    //
    // A static bright clock left on an OLED for hours is exactly how panels
    // acquire ghosting, so the clock drifts slowly around a small orbit and
    // settles to a dimmer level once nobody is interacting. Both are cheap:
    // one translation and one opacity, on the tick that already runs.
    _lockAmbientStep() {
        if (!this._lockAlive(this._lockClock))
            return;

        const ticks = this._lockTicks;

        // Fade to the ambient level a few seconds in, so the clock is bright
        // at the moment of locking and quiet afterwards.
        if (ticks === LOCK_AMBIENT_AFTER_S) {
            this._lockClock.ease({
                opacity: LOCK_AMBIENT_OPACITY,
                duration: 1200,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
        }

        if (ticks % LOCK_DRIFT_INTERVAL_S !== 0)
            return;

        // Eight positions around a small circle: one full lap per
        // 8 * LOCK_DRIFT_INTERVAL_S, far slower than the eye tracks.
        const stop = (ticks / LOCK_DRIFT_INTERVAL_S) % 8;
        const angle = (stop / 8) * 2 * Math.PI;

        this._lockClock.ease({
            translation_x: Math.round(Math.cos(angle) * LOCK_DRIFT_RADIUS_PX),
            translation_y: Math.round(Math.sin(angle) * LOCK_DRIFT_RADIUS_PX),
            duration: 2500,
            mode: Clutter.AnimationMode.EASE_IN_OUT_QUAD,
        });
    }

    // Always-on layer.
    //
    // GNOME fades its unlock dialog out once the session is idle, leaving a
    // plain black shield - which is why the screen went "just black". This
    // clock lives on the shield group itself rather than inside that dialog,
    // so it survives the fade the way a phone's always-on display does.
    _aodInstall() {
        if (this._aodBox)
            return;

        const group = Main.layoutManager.screenShieldGroup;
        if (!group)
            return;

        const box = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-aod',
            reactive: false,
        });

        this._aodTime = new St.Label({
            style_class: 'adaptive-aod-time',
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._aodTime.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;

        this._aodDate = new St.Label({
            style_class: 'adaptive-aod-date',
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._aodDate.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;

        box.add_child(this._aodTime);
        box.add_child(this._aodDate);

        group.add_child(box);

        try {
            group.set_child_above_sibling(box, null);
        } catch (e) {
        }

        this._aodBox = box;

        this._aodLayout();
        this._aodUpdate();
    }

    _aodLayout() {
        if (!this._aodBox)
            return;

        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        const [, width] = this._aodBox.get_preferred_width(-1);
        const [, height] = this._aodBox.get_preferred_height(width);

        this._aodBox.set_position(
            monitor.x + Math.round((monitor.width - width) / 2),
            monitor.y + Math.round((monitor.height - height) / 2)
        );
    }

    _aodUpdate() {
        if (!this._aodBox)
            return;

        const now = GLib.DateTime.new_now_local();

        this._aodTime.text = now.format(this._lockTimeFormat || '%H:%M:%S').trim();
        this._aodDate.text = now.format('%A %e %B').replace(/\s+/g, ' ').trim();

        // Drive the screen-saver state directly instead of waiting for GNOME
        // to fade its dialog. With the always-on switch on, the session never
        // goes idle by GNOME's reckoning, so that fade never happens and the
        // lock UI would simply sit there for ever. Phones do this by idle
        // time, so this does too: after AOD_IDLE_MS with no input the dialog
        // steps aside and the bare clock takes the screen; any input brings it
        // straight back.
        let idle = 0;

        try {
            idle = global.backend.get_core_idle_monitor().get_idletime();
        } catch (e) {
        }

        const show = idle >= AOD_IDLE_MS;
        const dialog = Main.screenShield ? Main.screenShield._dialog : null;

        // Hide what the dialog *shows*, not the dialog itself. The dialog is
        // the opaque cover over the session: hiding it outright let the
        // desktop - dock and panel included - show through underneath.
        if (dialog) {
            for (const part of [dialog._clock, dialog._notifications]) {
                if (!part)
                    continue;

                try {
                    part.visible = !show;
                } catch (e) {
                }
            }
        }

        if (show !== this._aodShown) {
            this._aodShown = show;
            log(`[Adaptive Shell] always-on layer ${show ? 'shown' : 'hidden'}`);
        }

        this._aodBox.visible = show;
        this._aodLayout();
    }

    _aodRemove() {
        this._lockRestoreDialogParts();

        try {
            const dialog = Main.screenShield ? Main.screenShield._dialog : null;
            if (dialog)
                dialog.visible = true;
        } catch (e) {
        }

        this._aodShown = false;

        if (!this._aodBox)
            return;

        try {
            this._aodBox.destroy();
        } catch (e) {
        }

        this._aodBox = null;
        this._aodTime = null;
        this._aodDate = null;
    }

    _lockAlive(actor) {
        // A destroyed actor keeps its JS wrapper, so the usual truthiness test
        // passes and the next property access asserts inside Clutter.
        try {
            return !!actor && actor.get_stage() !== null;
        } catch (e) {
            return false;
        }
    }

    _lockApplyTime() {

        // The 12/24-hour preference is read once and cached: this runs every
        // second, and building a Gio.Settings each time would be wasteful.
        if (this._lockTimeFormat === undefined) {
            this._lockTimeFormat = '%H:%M:%S';

            try {
                const iface = new Gio.Settings({
                    schema_id: 'org.gnome.desktop.interface',
                });

                if (iface.get_string('clock-format') === '12h')
                    this._lockTimeFormat = '%l:%M:%S %p';
            } catch (e) {
            }
        }

        if (!this._lockClock || !this._lockAlive(this._lockClock._time)) {
            this._lockDetachDialog();
            return;
        }

        const now = GLib.DateTime.new_now_local();
        this._lockClock._time.text = now.format(this._lockTimeFormat).trim();
    }

    _lockActivitySummary() {
        try {
            const running = Shell.AppSystem.get_default().get_running();

            if (!running.length)
                return '';

            const names = running
                .map(app => app.get_name())
                .filter(name => !!name)
                .sort();

            const shown = names.slice(0, 4).join(' · ');
            const extra = names.length - Math.min(names.length, 4);

            const label = running.length === 1
                ? '1 APP RUNNING'
                : `${running.length} APPS RUNNING`;

            return extra > 0
                ? `${label}\n${shown} +${extra}`
                : `${label}\n${shown}`;
        } catch (e) {
            return '';
        }
    }

    _lockRestoreDialogParts() {
        const dialog = Main.screenShield ? Main.screenShield._dialog : null;
        if (!dialog)
            return;

        for (const part of [dialog._clock, dialog._notifications]) {
            if (!part)
                continue;

            try {
                part.visible = true;
            } catch (e) {
            }
        }
    }

    _lockDetachDialog() {
        if (this._lockClock && this._lockClock._adaptiveUpdateClock) {
            try {
                this._lockClock._updateClock =
                    this._lockClock._adaptiveUpdateClock;
                this._lockClock._adaptiveUpdateClock = null;
            } catch (e) {
            }
        }

        this._lockClock = null;
        this._lockActivity = null;
    }

    _lockScreenStop() {
        if (this._lockAttachId) {
            GLib.Source.remove(this._lockAttachId);
            this._lockAttachId = 0;
        }

        if (this._lockTickId) {
            GLib.Source.remove(this._lockTickId);
            this._lockTickId = 0;
        }

        if (this._lockActivity) {
            try {
                this._lockActivity.destroy();
            } catch (e) {
            }
            this._lockActivity = null;
        }

        if (this._lockClock) {
            try {
                this._lockClock.remove_all_transitions();
                this._lockClock.opacity = 255;
                this._lockClock.translation_x = 0;
                this._lockClock.translation_y = 0;
            } catch (e) {
            }

            if (this._lockClock._adaptiveUpdateClock) {
                this._lockClock._updateClock =
                    this._lockClock._adaptiveUpdateClock;
                this._lockClock._adaptiveUpdateClock = null;
            }

            this._lockClock._adaptiveLock = false;
            this._lockClock = null;
        }

        this._aodRemove();
        this._lockTicks = 0;
        this._lockTimeFormat = undefined;
    }
};
