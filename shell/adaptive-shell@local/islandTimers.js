// Dynamic Island Focus Timers Provider
//
// Native timer engine supporting Pomodoro presets and custom countdowns.
// Strict Performance Budget: 0.0% CPU when IDLE or PAUSED (GLib source is destroyed).
// Timer ticks ONLY while actively running.
//
// The countdown is a wall-clock deadline, not a counter: a tick recomputes the
// remaining time, so a suspend or a missed tick cannot stretch a session. The
// deadline is saved to ~/.local/state/adaptive-desktop/focus-timer.json and
// restored by init(), so a shell restart keeps the session too.
//
// A focus session (not a break) turns GNOME's Do Not Disturb on through the
// same key the Control Center tile and focus-cli.py use, and gives the user's
// previous setting back when it ends - unless they changed it meanwhile.

/* exported IslandTimerProvider */
/* global module, setInterval, clearInterval */

let Gio, GLib;
try {
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
} catch (e) {
    // Headless test harness
}

const FOCUS_PRESETS = new Set(['pomodoro', 'custom']);

function _defaultStorage() {
    if (typeof GLib === 'undefined' || !GLib.get_user_state_dir)
        return null;
    const dir = GLib.build_filenamev([GLib.get_user_state_dir(), 'adaptive-desktop']);
    const path = GLib.build_filenamev([dir, 'focus-timer.json']);
    return {
        read() {
            try {
                const [ok, bytes] = GLib.file_get_contents(path);
                return ok ? JSON.parse(new TextDecoder().decode(bytes)) : null;
            } catch (e) {
                return null;
            }
        },
        write(data) {
            try {
                GLib.mkdir_with_parents(dir, 0o700);
                if (data)
                    GLib.file_set_contents(path, JSON.stringify(data));
                else if (GLib.file_test(path, GLib.FileTest.EXISTS))
                    Gio.File.new_for_path(path).delete(null);
            } catch (e) {
                logError(e, '[Adaptive Island] saving the focus timer');
            }
        },
    };
}

function _defaultDnd() {
    if (typeof Gio === 'undefined' || !Gio.Settings)
        return null;
    let settings = null;
    try {
        settings = new Gio.Settings({ schema_id: 'org.gnome.desktop.notifications' });
    } catch (e) {
        return null;
    }
    return {
        get: () => !settings.get_boolean('show-banners'),
        set: on => settings.set_boolean('show-banners', !on),
    };
}

var IslandTimerProvider = class IslandTimerProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._now = options.now || (() => Date.now());
        this._storage = options.storage !== undefined ? options.storage : _defaultStorage();
        this._dnd = options.dnd !== undefined ? options.dnd : _defaultDnd();
        this._digestSource = null;
        this._timerSourceId = 0;
        this._destroyed = false;

        // While a focus session holds Do Not Disturb: the setting it replaced.
        this._dndHeld = null;
        this._digestMark = null;

        this._state = {
            status: 'IDLE', // 'IDLE' | 'RUNNING' | 'PAUSED' | 'EXPIRED'
            label: 'Focus Timer',
            preset: 'none', // 'pomodoro' | 'short_break' | 'long_break' | 'custom'
            totalSeconds: 0,
            remainingSeconds: 0,
            elapsedSeconds: 0,
            progressPercent: 0,
            deadline: 0, // ms since epoch while RUNNING
            lastDigest: '',
        };
    }

    init() {
        this._destroyed = false;
        this._restore();
    }

    // Where the end-of-focus digest comes from: { mark(), summary(mark) }.
    setDigestSource(source) {
        this._digestSource = source || null;
        if (source && this._isFocus() && this._digestMark === null &&
            (this._state.status === 'RUNNING' || this._state.status === 'PAUSED'))
            this._digestMark = source.mark();
    }

    startPomodoro() {
        this.start(25 * 60, 'Pomodoro', 'pomodoro');
    }

    startBreak(minutes = 5) {
        const p = minutes === 5 ? 'short_break' : 'long_break';
        this.start(minutes * 60, `${minutes}m Break`, p);
    }

    start(seconds, label = 'Focus Timer', preset = 'custom') {
        this._stopTimerTicker();
        const wasFocus = this._isFocus() &&
            (this._state.status === 'RUNNING' || this._state.status === 'PAUSED');

        this._state.totalSeconds = Math.max(1, Math.round(seconds));
        this._state.remainingSeconds = this._state.totalSeconds;
        this._state.elapsedSeconds = 0;
        this._state.progressPercent = 0;
        this._state.label = label;
        this._state.preset = preset;
        this._state.status = 'RUNNING';
        this._state.deadline = this._now() + this._state.totalSeconds * 1000;
        this._state.lastDigest = '';

        if (this._isFocus()) {
            this._holdDnd();
            if (!wasFocus || this._digestMark === null)
                this._digestMark = this._digestSource ? this._digestSource.mark() : null;
        } else {
            this._releaseDnd();
            this._digestMark = null;
        }

        this._startTimerTicker();
        this._save();

        this._emit('TIMER_STARTED', 3, 3000, {
            totalSeconds: this._state.totalSeconds,
            remainingSeconds: this._state.remainingSeconds,
            formatted: this._formatTime(this._state.remainingSeconds),
            message: `Timer started: ${this._formatTime(this._state.remainingSeconds)}`,
        });
    }

    pause() {
        if (this._state.status !== 'RUNNING')
            return;

        this._syncRemaining();
        this._stopTimerTicker();
        this._state.status = 'PAUSED';
        this._state.deadline = 0;
        this._save();

        this._emit('TIMER_PAUSED', 4, 2000, {
            remainingSeconds: this._state.remainingSeconds,
            formatted: this._formatTime(this._state.remainingSeconds),
            message: `Timer paused (${this._formatTime(this._state.remainingSeconds)})`,
        });
    }

    resume() {
        if (this._state.status !== 'PAUSED')
            return;

        this._state.status = 'RUNNING';
        this._state.deadline = this._now() + this._state.remainingSeconds * 1000;
        this._startTimerTicker();
        this._save();

        this._emit('TIMER_RESUMED', 4, 2000, {
            remainingSeconds: this._state.remainingSeconds,
            formatted: this._formatTime(this._state.remainingSeconds),
            message: `Timer resumed (${this._formatTime(this._state.remainingSeconds)})`,
        });
    }

    reset() {
        const endedFocus = this._isFocus() &&
            (this._state.status === 'RUNNING' || this._state.status === 'PAUSED');
        this._stopTimerTicker();
        const digest = endedFocus ? this._takeDigest() : '';
        this._releaseDnd();
        this._state.status = 'IDLE';
        this._state.remainingSeconds = 0;
        this._state.elapsedSeconds = 0;
        this._state.progressPercent = 0;
        this._state.deadline = 0;
        this._state.lastDigest = digest;
        this._save();

        if (digest) {
            this._emit('TIMER_DIGEST', 2, 6000, {
                digest,
                message: `Focus ended · ${digest}`,
            });
        }
        this._notifyState();
    }

    extend(additionalSeconds = 300) {
        if (this._state.status === 'IDLE') {
            this.start(additionalSeconds, 'Extended Focus');
            return;
        }

        this._state.totalSeconds += additionalSeconds;
        if (this._state.status === 'RUNNING') {
            this._state.deadline += additionalSeconds * 1000;
            this._syncRemaining();
        } else if (this._state.status === 'EXPIRED') {
            this._state.status = 'RUNNING';
            this._state.remainingSeconds = additionalSeconds;
            this._state.deadline = this._now() + additionalSeconds * 1000;
            if (this._isFocus())
                this._holdDnd();
            this._startTimerTicker();
        } else {
            this._state.remainingSeconds += additionalSeconds;
        }
        this._updateProgress();
        this._save();
        this._notifyState();
    }

    dismiss() {
        this.reset();
    }

    // ------------------------------------------------------------ internals

    _isFocus() {
        return FOCUS_PRESETS.has(this._state.preset);
    }

    _emit(type, priority, dwellMs, extra) {
        if (!this._bus)
            return;
        this._bus.emitEvent(type, {
            provider: 'timer',
            priority,
            dwellMs,
            label: this._state.label,
            ...extra,
            data: { ...this._state },
        });
    }

    _notifyState() {
        if (this._bus && this._bus.notifyStateChange)
            this._bus.notifyStateChange();
    }

    _syncRemaining() {
        if (this._state.status !== 'RUNNING' || !this._state.deadline)
            return;
        const left = Math.max(0, Math.ceil((this._state.deadline - this._now()) / 1000));
        this._state.remainingSeconds = Math.min(left, this._state.totalSeconds);
        this._state.elapsedSeconds = this._state.totalSeconds - this._state.remainingSeconds;
        this._updateProgress();
    }

    _expire() {
        this._state.status = 'EXPIRED';
        this._state.remainingSeconds = 0;
        this._state.deadline = 0;
        this._updateProgress();
        this._stopTimerTicker();
        const digest = this._isFocus() ? this._takeDigest() : '';
        this._state.lastDigest = digest;
        this._releaseDnd();
        this._save();

        this._emit('TIMER_EXPIRED', 1, -1, {
            digest,
            message: digest
                ? `${this._state.label} finished · ${digest}`
                : `${this._state.label} finished!`,
        });
    }

    _takeDigest() {
        const mark = this._digestMark;
        this._digestMark = null;
        if (mark === null || !this._digestSource)
            return '';
        try {
            return this._digestSource.summary(mark) || '';
        } catch (e) {
            return '';
        }
    }

    _holdDnd() {
        if (!this._dnd || this._dndHeld !== null)
            return;
        try {
            this._dndHeld = this._dnd.get();
            if (!this._dndHeld)
                this._dnd.set(true);
        } catch (e) {
            this._dndHeld = null;
        }
    }

    _releaseDnd() {
        if (!this._dnd || this._dndHeld === null)
            return;
        try {
            // Only undo what focus did: if the user turned DND off meanwhile, or
            // it was already on before the session, leave it as it is.
            if (!this._dndHeld && this._dnd.get())
                this._dnd.set(false);
        } catch (e) {}
        this._dndHeld = null;
    }

    _save() {
        if (!this._storage)
            return;
        const s = this._state;
        if (s.status === 'IDLE' && this._dndHeld === null) {
            this._storage.write(null);
            return;
        }
        this._storage.write({
            status: s.status,
            label: s.label,
            preset: s.preset,
            totalSeconds: s.totalSeconds,
            remainingSeconds: s.remainingSeconds,
            deadline: s.deadline,
            dndHeld: this._dndHeld,
        });
    }

    _restore() {
        const saved = this._storage ? this._storage.read() : null;
        if (!saved || !saved.status)
            return;

        this._dndHeld = typeof saved.dndHeld === 'boolean' ? saved.dndHeld : null;
        const s = this._state;
        s.label = saved.label || s.label;
        s.preset = saved.preset || 'custom';
        s.totalSeconds = Math.max(1, Number(saved.totalSeconds) || 1);

        if (saved.status === 'RUNNING' && saved.deadline > 0) {
            s.status = 'RUNNING';
            s.deadline = saved.deadline;
            this._syncRemaining();
            if (s.remainingSeconds <= 0)
                this._expire();
            else
                this._startTimerTicker();
        } else if (saved.status === 'PAUSED') {
            s.status = 'PAUSED';
            s.remainingSeconds = Math.max(0, Math.min(s.totalSeconds,
                Number(saved.remainingSeconds) || 0));
            s.elapsedSeconds = s.totalSeconds - s.remainingSeconds;
            this._updateProgress();
        } else {
            // EXPIRED or unknown: the session is over; give DND back.
            s.status = 'IDLE';
            this._releaseDnd();
            this._save();
        }
    }

    _startTimerTicker() {
        if (this._timerSourceId || this._destroyed)
            return;

        const tick = () => {
            if (this._state.status !== 'RUNNING')
                return false;

            this._syncRemaining();

            if (this._state.remainingSeconds <= 0) {
                this._timerSourceId = 0;
                this._expire();
                return false;
            }

            this._emit('TIMER_TICK', 4, 1000, {
                remainingSeconds: this._state.remainingSeconds,
                formatted: this._formatTime(this._state.remainingSeconds),
                progressPercent: this._state.progressPercent,
            });

            return true;
        };

        if (typeof GLib !== 'undefined' && GLib.timeout_add) {
            this._timerSourceId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
                const keep = tick();
                if (!keep)
                    this._timerSourceId = 0;
                return keep ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
            });
        } else if (typeof setInterval !== 'undefined') {
            const id = setInterval(() => {
                if (!tick()) {
                    clearInterval(id);
                    if (this._timerSourceId === id)
                        this._timerSourceId = 0;
                }
            }, 1000);
            this._timerSourceId = id;
        }
    }

    _stopTimerTicker() {
        if (this._timerSourceId) {
            if (typeof GLib !== 'undefined' && GLib.source_remove)
                GLib.source_remove(this._timerSourceId);
            else if (typeof clearInterval !== 'undefined')
                clearInterval(this._timerSourceId);
            this._timerSourceId = 0;
        }
    }

    _updateProgress() {
        if (this._state.totalSeconds > 0) {
            const ratio = (this._state.totalSeconds - this._state.remainingSeconds) / this._state.totalSeconds;
            this._state.progressPercent = Math.min(100, Math.max(0, Math.round(ratio * 100)));
        } else {
            this._state.progressPercent = 0;
        }
    }

    _formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    getState() {
        this._syncRemaining();
        return {
            ...this._state,
            isFocus: this._isFocus(),
            dndHeld: this._dndHeld !== null,
            formatted: this._formatTime(this._state.remainingSeconds),
        };
    }

    // Shell teardown is not the end of a session: the deadline and the held
    // DND stay saved so the next init() picks them up.
    destroy() {
        this._destroyed = true;
        this._stopTimerTicker();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandTimerProvider };
}
