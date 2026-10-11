// Dynamic Island Focus Timers Provider
//
// Native timer engine supporting Pomodoro presets and custom countdowns.
// Strict Performance Budget: 0.0% CPU when IDLE or PAUSED (GLib source is destroyed).
// Timer ticks ONLY while actively running.

/* exported IslandTimerProvider */
/* global module, setInterval, clearInterval */

let GLib;
try {
    GLib = imports.gi.GLib;
} catch (e) {
    // Headless test harness
}

var IslandTimerProvider = class IslandTimerProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._timerSourceId = 0;
        this._destroyed = false;

        this._state = {
            status: 'IDLE', // 'IDLE' | 'RUNNING' | 'PAUSED' | 'EXPIRED'
            label: 'Focus Timer',
            preset: 'none', // 'pomodoro' | 'short_break' | 'long_break' | 'custom'
            totalSeconds: 0,
            remainingSeconds: 0,
            elapsedSeconds: 0,
            progressPercent: 0,
        };
    }

    init() {
        this._destroyed = false;
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

        this._state.totalSeconds = Math.max(1, seconds);
        this._state.remainingSeconds = this._state.totalSeconds;
        this._state.elapsedSeconds = 0;
        this._state.progressPercent = 0;
        this._state.label = label;
        this._state.preset = preset;
        this._state.status = 'RUNNING';

        this._startTimerTicker();

        if (this._bus) {
            this._bus.emitEvent('TIMER_STARTED', {
                provider: 'timer',
                priority: 3, // P3_NORMAL
                dwellMs: 3000,
                label: this._state.label,
                totalSeconds: this._state.totalSeconds,
                remainingSeconds: this._state.remainingSeconds,
                formatted: this._formatTime(this._state.remainingSeconds),
                message: `Timer started: ${this._formatTime(this._state.remainingSeconds)}`,
                data: { ...this._state },
            });
        }
    }

    pause() {
        if (this._state.status !== 'RUNNING')
            return;

        this._stopTimerTicker();
        this._state.status = 'PAUSED';

        if (this._bus) {
            this._bus.emitEvent('TIMER_PAUSED', {
                provider: 'timer',
                priority: 4, // P4_AMBIENT
                dwellMs: 2000,
                label: this._state.label,
                remainingSeconds: this._state.remainingSeconds,
                formatted: this._formatTime(this._state.remainingSeconds),
                message: `Timer paused (${this._formatTime(this._state.remainingSeconds)})`,
                data: { ...this._state },
            });
        }
    }

    resume() {
        if (this._state.status !== 'PAUSED')
            return;

        this._state.status = 'RUNNING';
        this._startTimerTicker();

        if (this._bus) {
            this._bus.emitEvent('TIMER_RESUMED', {
                provider: 'timer',
                priority: 4, // P4_AMBIENT
                dwellMs: 2000,
                label: this._state.label,
                remainingSeconds: this._state.remainingSeconds,
                formatted: this._formatTime(this._state.remainingSeconds),
                message: `Timer resumed (${this._formatTime(this._state.remainingSeconds)})`,
                data: { ...this._state },
            });
        }
    }

    reset() {
        this._stopTimerTicker();
        this._state.status = 'IDLE';
        this._state.remainingSeconds = 0;
        this._state.elapsedSeconds = 0;
        this._state.progressPercent = 0;
    }

    extend(additionalSeconds = 300) {
        if (this._state.status === 'IDLE') {
            this.start(additionalSeconds, 'Extended Focus');
            return;
        }

        this._state.totalSeconds += additionalSeconds;
        this._state.remainingSeconds += additionalSeconds;
        this._updateProgress();

        if (this._state.status === 'EXPIRED') {
            this._state.status = 'RUNNING';
            this._startTimerTicker();
        }
    }

    dismiss() {
        this.reset();
    }

    _startTimerTicker() {
        if (this._timerSourceId || this._destroyed)
            return;

        const tick = () => {
            if (this._state.status !== 'RUNNING')
                return false;

            this._state.remainingSeconds = Math.max(0, this._state.remainingSeconds - 1);
            this._state.elapsedSeconds += 1;
            this._updateProgress();

            if (this._state.remainingSeconds <= 0) {
                // Timer finished!
                this._state.status = 'EXPIRED';
                this._stopTimerTicker();

                if (this._bus) {
                    this._bus.emitEvent('TIMER_EXPIRED', {
                        provider: 'timer',
                        priority: 1, // P1_URGENT
                        dwellMs: -1, // STICKY alert until dismissed
                        label: this._state.label,
                        message: `${this._state.label} finished!`,
                        data: { ...this._state },
                    });
                }
                return false;
            }

            if (this._bus) {
                this._bus.emitEvent('TIMER_TICK', {
                    provider: 'timer',
                    priority: 4, // P4_AMBIENT
                    dwellMs: 1000,
                    label: this._state.label,
                    remainingSeconds: this._state.remainingSeconds,
                    formatted: this._formatTime(this._state.remainingSeconds),
                    progressPercent: this._state.progressPercent,
                    data: { ...this._state },
                });
            }

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
            this._timerSourceId = setInterval(() => {
                const keep = tick();
                if (!keep) {
                    clearInterval(this._timerSourceId);
                    this._timerSourceId = 0;
                }
            }, 1000);
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
        return {
            ...this._state,
            formatted: this._formatTime(this._state.remainingSeconds),
        };
    }

    destroy() {
        this._destroyed = true;
        this._stopTimerTicker();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandTimerProvider };
}
