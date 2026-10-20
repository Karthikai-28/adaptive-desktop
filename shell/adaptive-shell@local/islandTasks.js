// Dynamic Island Background AI Tasks Provider
//
// Hooks into the local Agent Office daemon (:8790) to track live running tasks.
// Debounces rapid progress logs (1000ms sliding window) and emits lifecycle events.
//
// Reads are plain GETs through Gio. Agent Office only accepts actions as POST,
// which Gio.File cannot send, so cancel goes through curl.

/* exported IslandTaskProvider */
/* global module, setTimeout, clearTimeout */

let Gio, GLib;
try {
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
} catch (e) {
    // Headless test harness
}

var IslandTaskProvider = class IslandTaskProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._officeUrl = options.officeUrl || 'http://127.0.0.1:8790/';
        this._tasksUrl = options.tasksUrl || 'http://127.0.0.1:8790/api/tasks';
        this._eventsUrl = options.eventsUrl || 'http://127.0.0.1:8790/api/events';
        // Enough recent tasks to see each running one leave the running state.
        this._listLimit = options.listLimit || 40;
        this._poster = options.poster || null;             // for tests/mocking
        this._logFetcher = options.logFetcher || null;     // for tests/mocking
        this._activePollMs = options.activePollMs || 3000;  // 3s while tasks are actively running
        this._idlePollMs = options.idlePollMs || 15000;    // 15s while no tasks are active
        this._debounceMs = options.debounceMs || 1000;    // 1000ms sliding debounce for progress updates
        this._customFetcher = options.fetcher || null;     // for tests/mocking

        this._pollTimerId = 0;
        this._debounceTimers = new Map(); // taskId -> timerId
        this._destroyed = false;

        this._knownTasks = new Map(); // taskId -> taskObject
        this._runningTasks = new Map(); // taskId -> taskObject
        this._logs = new Map(); // taskId -> { ts, lines }
        this._cancelling = new Set();
    }

    init() {
        this._destroyed = false;
        this.pollTasks();
        this._scheduleNextPoll();
    }

    _scheduleNextPoll() {
        if (this._destroyed)
            return;
        const interval = this._runningTasks.size > 0 ? this._activePollMs : this._idlePollMs;
        if (typeof GLib !== 'undefined' && GLib.timeout_add) {
            this._pollTimerId = GLib.timeout_add(GLib.PRIORITY_LOW, interval, () => {
                this.pollTasks();
                return GLib.SOURCE_CONTINUE;
            });
        } else if (typeof setTimeout !== 'undefined') {
            this._pollTimerId = setTimeout(() => {
                this.pollTasks();
                this._scheduleNextPoll();
            }, interval);
        }
    }

    pollTasks() {
        if (this._destroyed)
            return;

        if (this._customFetcher) {
            this._customFetcher((err, tasks) => {
                if (!err && tasks)
                    this._processTasks(tasks);
            });
            return;
        }

        if (typeof Gio !== 'undefined' && Gio.File) {
            try {
                const file = Gio.File.new_for_uri(`${this._tasksUrl}?limit=${this._listLimit}`);
                file.load_contents_async(null, (source, res) => {
                    try {
                        const [, contents] = source.load_contents_finish(res);
                        const raw = new TextDecoder('utf-8').decode(contents);
                        const tasks = JSON.parse(raw);
                        this._processTasks(tasks);
                    } catch (e) {
                        // Ignore transient network/daemon hiccups
                    }
                });
            } catch (e) {
                // Ignore
            }
        }
    }

    _processTasks(taskList) {
        if (!Array.isArray(taskList))
            return;

        const currentActive = new Map();
        let changed = false;

        for (const t of taskList) {
            const id = t.id;
            const prev = this._knownTasks.get(id);

            // Record into current state
            this._knownTasks.set(id, { ...t });

            if (t.status === 'running') {
                currentActive.set(id, { ...t });
                if (!prev || prev.steps !== t.steps || prev.status !== t.status)
                    changed = true;
                if (!prev || prev.status !== 'running') {
                    // Task transition: QUEUED -> RUNNING
                    this._emitTaskStarted(t);
                } else if (t.steps !== prev.steps || t.result !== prev.result) {
                    // Progress tick (debounced)
                    this._queueProgressUpdate(t);
                }
            } else if (prev && prev.status === 'running') {
                // Task left running state
                changed = true;
                this._cancelling.delete(id);
                this._logs.delete(id);
                if (t.status === 'completed' || t.status === 'done') {
                    this._emitTaskCompleted(t);
                } else if (t.status === 'failed' || t.status === 'error') {
                    this._emitTaskFailed(t);
                }
            }
        }

        const prevCount = this._runningTasks.size;
        for (const id of this._runningTasks.keys()) {
            if (!currentActive.has(id))
                changed = true;
        }
        this._runningTasks = currentActive;
        if (changed && this._bus && this._bus.notifyStateChange)
            this._bus.notifyStateChange();

        // If running count transitioned to/from 0, adjust poll rate
        if ((prevCount === 0 && currentActive.size > 0) || (prevCount > 0 && currentActive.size === 0)) {
            if (this._pollTimerId) {
                if (typeof GLib !== 'undefined' && GLib.source_remove)
                    GLib.source_remove(this._pollTimerId);
                else if (typeof clearTimeout !== 'undefined')
                    clearTimeout(this._pollTimerId);
                this._pollTimerId = 0;
            }
            this._scheduleNextPoll();
        }
    }

    _emitTaskStarted(task) {
        if (!this._bus) return;
        this._bus.emitEvent('TASK_STARTED', {
            provider: 'task',
            priority: 3, // P3_NORMAL
            dwellMs: 3000,
            taskId: task.id,
            agent: task.agent || 'agent',
            title: task.title || `Task #${task.id}`,
            project: task.project || '',
            status: 'running',
            message: `Started: ${task.title || `Task #${task.id}`}`,
            canCancel: true,
            data: { ...task },
        });
    }

    _queueProgressUpdate(task) {
        const id = task.id;
        // Sliding debounce: if update scheduled, clear it
        if (this._debounceTimers.has(id)) {
            const timer = this._debounceTimers.get(id);
            if (typeof GLib !== 'undefined' && GLib.source_remove)
                GLib.source_remove(timer);
            else if (typeof clearTimeout !== 'undefined')
                clearTimeout(timer);
        }

        const fire = () => {
            this._debounceTimers.delete(id);
            if (this._bus) {
                this._bus.emitEvent('TASK_PROGRESS_UPDATE', {
                    provider: 'task',
                    priority: 4, // P4_AMBIENT
                    dwellMs: 2000,
                    taskId: task.id,
                    agent: task.agent || 'agent',
                    title: task.title || `Task #${task.id}`,
                    project: task.project || '',
                    steps: task.steps || 0,
                    status: 'running',
                    message: `${task.agent || 'Agent'}: step ${task.steps || 0}`,
                    canCancel: true,
                    data: { ...task },
                });
            }
        };

        if (typeof GLib !== 'undefined' && GLib.timeout_add) {
            const tid = GLib.timeout_add(GLib.PRIORITY_LOW, this._debounceMs, () => {
                fire();
                return GLib.SOURCE_REMOVE;
            });
            this._debounceTimers.set(id, tid);
        } else if (typeof setTimeout !== 'undefined') {
            const tid = setTimeout(fire, this._debounceMs);
            this._debounceTimers.set(id, tid);
        }
    }

    _emitTaskCompleted(task) {
        if (!this._bus) return;
        this._bus.emitEvent('TASK_COMPLETED_SUCCESS', {
            provider: 'task',
            priority: 2, // P2_HIGH
            dwellMs: 4000,
            taskId: task.id,
            agent: task.agent || 'agent',
            title: task.title || `Task #${task.id}`,
            project: task.project || '',
            status: 'completed',
            message: `Completed: ${task.title || `Task #${task.id}`}`,
            data: { ...task },
        });
    }

    _emitTaskFailed(task) {
        if (!this._bus) return;
        this._bus.emitEvent('TASK_FAILED_ERROR', {
            provider: 'task',
            priority: 1, // P1_URGENT
            dwellMs: -1, // STICKY
            taskId: task.id,
            agent: task.agent || 'agent',
            title: task.title || `Task #${task.id}`,
            project: task.project || '',
            status: 'failed',
            error: task.error || 'Task failed',
            message: `Failed: ${task.title || `Task #${task.id}`}`,
            data: { ...task },
        });
    }

    cancelTask(taskId, callback) {
        const url = `${this._tasksUrl}/${encodeURIComponent(taskId)}/cancel`;
        const done = (err, ok) => {
            if (!ok)
                this._cancelling.delete(taskId);
            if (this._bus && this._bus.notifyStateChange)
                this._bus.notifyStateChange();
            if (ok)
                this.pollTasks();
            if (callback)
                callback(err, ok);
        };
        this._cancelling.add(taskId);
        if (this._bus && this._bus.notifyStateChange)
            this._bus.notifyStateChange();

        if (this._poster) {
            this._poster(url, done);
            return;
        }
        if (typeof Gio === 'undefined' || !Gio.Subprocess) {
            done(new Error('no HTTP client'), false);
            return;
        }
        try {
            const proc = Gio.Subprocess.new(
                ['curl', '-fsS', '-X', 'POST', '-H', 'X-Office: 1', '--max-time', '10', url],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
            proc.wait_check_async(null, (p, res) => {
                try {
                    done(null, p.wait_check_finish(res));
                } catch (e) {
                    done(e, false);
                }
            });
        } catch (e) {
            done(e, false);
        }
    }

    isCancelling(taskId) {
        return this._cancelling.has(taskId);
    }

    // The last few office events for one task, for the Tasks card's log. Read
    // at most every few seconds and only while the card is on screen.
    fetchTaskLog(taskId, callback, maxAgeMs = 3000) {
        const cached = this._logs.get(taskId);
        const now = Date.now();
        if (cached && now - cached.ts < maxAgeMs) {
            callback(cached.lines);
            return;
        }
        const finish = (events) => {
            const lines = (Array.isArray(events) ? events : []).slice(-4).map(e => ({
                ts: Number(e.ts) || 0,
                text: `${e.kind ? `${e.kind}: ` : ''}${String(e.text || '').replace(/\s+/g, ' ').trim()}`,
            }));
            this._logs.set(taskId, { ts: Date.now(), lines });
            callback(lines);
        };
        if (this._logFetcher) {
            this._logFetcher(taskId, (err, events) => finish(err ? [] : events));
            return;
        }
        if (typeof Gio === 'undefined' || !Gio.File)
            return;
        try {
            const file = Gio.File.new_for_uri(`${this._tasksUrl}/${encodeURIComponent(taskId)}`);
            file.load_contents_async(null, (source, res) => {
                try {
                    const [, contents] = source.load_contents_finish(res);
                    const task = JSON.parse(new TextDecoder('utf-8').decode(contents));
                    finish(task && task.events);
                } catch (e) {
                    finish([]);
                }
            });
        } catch (e) {
            // Ignore
        }
    }

    openOffice() {
        if (typeof Gio === 'undefined' || !Gio.AppInfo)
            return;
        try {
            Gio.AppInfo.launch_default_for_uri(this._officeUrl, null);
        } catch (e) {
            logError(e, '[Adaptive Island] opening Agent Office');
        }
    }

    getActiveTasks() {
        return Array.from(this._runningTasks.values());
    }

    getTask(taskId) {
        return this._knownTasks.get(taskId) || null;
    }

    destroy() {
        this._destroyed = true;
        if (this._pollTimerId) {
            if (typeof GLib !== 'undefined' && GLib.source_remove)
                GLib.source_remove(this._pollTimerId);
            else if (typeof clearTimeout !== 'undefined')
                clearTimeout(this._pollTimerId);
            this._pollTimerId = 0;
        }
        for (const tid of this._debounceTimers.values()) {
            if (typeof GLib !== 'undefined' && GLib.source_remove)
                GLib.source_remove(tid);
            else if (typeof clearTimeout !== 'undefined')
                clearTimeout(tid);
        }
        this._debounceTimers.clear();
        this._logs.clear();
        this._cancelling.clear();
        this._runningTasks.clear();
        this._knownTasks.clear();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandTaskProvider };
}
