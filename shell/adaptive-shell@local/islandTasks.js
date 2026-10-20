// Dynamic Island Background AI Tasks Provider
//
// Hooks into the local Agent Office daemon (:8790) to track live running tasks.
// Debounces rapid progress logs (1000ms sliding window) and emits lifecycle events.
//
// Reads are plain GETs through Gio. Agent Office only accepts actions as POST,
// which Gio.File cannot send, so cancel goes through curl.

/* exported IslandTaskProvider */
/* global module, setTimeout, clearTimeout */

let Gio, GLib, Soup, ByteArray;
try {
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
    Soup = imports.gi.Soup;
    ByteArray = imports.byteArray;
} catch (e) {
    // Headless test harness
}

var IslandTaskProvider = class IslandTaskProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._officeUrl = options.officeUrl || 'http://127.0.0.1:8790/';
        this._tasksUrl = options.tasksUrl || 'http://127.0.0.1:8790/api/tasks';
        this._eventsUrl = options.eventsUrl || 'http://127.0.0.1:8790/api/events';
        this._listLimit = options.listLimit || 1000;
        this._poster = options.poster || null;             // for tests/mocking
        this._logFetcher = options.logFetcher || null;     // for tests/mocking
        this._activePollMs = options.activePollMs || 3000;  // 3s while tasks are actively running
        this._idlePollMs = options.idlePollMs || 15000;    // 15s while no tasks are active
        this._livePollMs = options.livePollMs || 60000;    // consistency check while WebSocket is healthy
        this._debounceMs = options.debounceMs || 1000;    // 1000ms sliding debounce for progress updates
        this._customFetcher = options.fetcher || null;     // for tests/mocking

        this._pollTimerId = 0;
        this._pollInFlight = false;
        this._debounceTimers = new Map(); // taskId -> timerId
        this._destroyed = false;

        this._knownTasks = new Map(); // taskId -> taskObject
        this._runningTasks = new Map(); // taskId -> taskObject
        this._logs = new Map(); // taskId -> { ts, lines }
        this._logInFlight = new Map(); // taskId -> callbacks
        this._cancelling = new Set();
        this._wsSession = null;
        this._wsConnection = null;
        this._wsReconnectId = 0;
        this._wsPingId = 0;
        this._liveUpdates = options.liveUpdates !== false;
    }

    init() {
        this._destroyed = false;
        this._connectLiveUpdates();
        this.pollTasks(() => this._scheduleNextPoll());
    }

    _scheduleNextPoll() {
        if (this._destroyed)
            return;
        const interval = this._wsConnection ? this._livePollMs
            : this._runningTasks.size > 0 ? this._activePollMs : this._idlePollMs;
        if (typeof GLib !== 'undefined' && GLib.timeout_add) {
            this._pollTimerId = GLib.timeout_add(GLib.PRIORITY_LOW, interval, () => {
                this._pollTimerId = 0;
                this.pollTasks(() => this._scheduleNextPoll());
                return GLib.SOURCE_REMOVE;
            });
        } else if (typeof setTimeout !== 'undefined') {
            this._pollTimerId = setTimeout(() => {
                this._pollTimerId = 0;
                this.pollTasks(() => this._scheduleNextPoll());
            }, interval);
        }
    }

    _connectLiveUpdates() {
        if (!this._liveUpdates || this._destroyed || this._wsConnection ||
            typeof Soup === 'undefined' || !Soup.Session || !Soup.Message)
            return;
        try {
            this._wsSession = this._wsSession || new Soup.Session();
            const wsUrl = this._officeUrl.replace(/^http/, 'ws').replace(/\/?$/, '/ws');
            const origin = this._officeUrl.replace(/\/$/, '');
            const message = Soup.Message.new('GET', wsUrl);
            this._wsSession.websocket_connect_async(
                message, origin, null, null, (session, res) => {
                    if (this._destroyed)
                        return;
                    try {
                        const connection = session.websocket_connect_finish(res);
                        this._wsConnection = connection;
                        connection.connect('message', (_conn, type, bytes) => {
                            if (type !== Soup.WebsocketDataType.TEXT)
                                return;
                            try {
                                const text = ByteArray.toString(bytes.get_data());
                                this._handleLiveMessage(JSON.parse(text));
                            } catch (e) {}
                        });
                        connection.connect('closed', () => {
                            this._wsConnection = null;
                            this._stopLivePing();
                            this._scheduleLiveReconnect();
                        });
                        this._startLivePing();
                    } catch (e) {
                        this._scheduleLiveReconnect();
                    }
                });
        } catch (e) {
            this._scheduleLiveReconnect();
        }
    }

    _handleLiveMessage(message) {
        if (!message || this._destroyed)
            return;
        if (message.type === 'state' && Array.isArray(message.tasks)) {
            // The Office snapshot intentionally caps history. Preserve a
            // running task learned from the exhaustive status query when it is
            // older than that snapshot window.
            const ids = new Set(message.tasks.map(task => task.id));
            const merged = [...this._runningTasks.values()]
                .filter(task => !ids.has(task.id));
            merged.push(...message.tasks);
            this._processTasks(merged);
        } else if (message.type === 'task' && message.task) {
            const tasks = [...this._runningTasks.values()]
                .filter(task => task.id !== message.task.id);
            tasks.push(message.task);
            this._processTasks(tasks);
        } else if (message.type === 'event' && message.event && message.event.task_id) {
            const id = message.event.task_id;
            const cached = this._logs.get(id);
            const events = cached ? cached.events.slice() : [];
            events.push(message.event);
            const recent = events.slice(-4);
            const lines = recent.map(event => ({
                ts: Number(event.ts) || 0,
                text: `${event.kind ? `${event.kind}: ` : ''}${String(event.text || '').replace(/\s+/g, ' ').trim()}`,
            }));
            this._logs.set(id, { ts: Date.now(), events: recent, lines });
            if (this._runningTasks.has(id) && this._bus && this._bus.notifyStateChange)
                this._bus.notifyStateChange();
        }
    }

    _startLivePing() {
        this._stopLivePing();
        if (typeof GLib === 'undefined' || !GLib.timeout_add_seconds)
            return;
        this._wsPingId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, 25, () => {
            if (!this._wsConnection)
                return GLib.SOURCE_REMOVE;
            try {
                this._wsConnection.send_text('ping');
            } catch (e) {
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopLivePing() {
        if (this._wsPingId && typeof GLib !== 'undefined') {
            GLib.source_remove(this._wsPingId);
            this._wsPingId = 0;
        }
    }

    _scheduleLiveReconnect() {
        if (this._destroyed || this._wsReconnectId || typeof GLib === 'undefined')
            return;
        this._wsReconnectId = GLib.timeout_add_seconds(GLib.PRIORITY_LOW, 5, () => {
            this._wsReconnectId = 0;
            this._connectLiveUpdates();
            return GLib.SOURCE_REMOVE;
        });
    }

    pollTasks(done = null) {
        if (this._destroyed) {
            if (done) done();
            return;
        }
        if (this._pollInFlight) {
            if (done) done();
            return;
        }
        this._pollInFlight = true;
        const finish = (err, tasks) => {
            this._pollInFlight = false;
            if (!this._destroyed && !err && tasks)
                this._processTasks(tasks);
            if (done) done();
        };

        if (this._customFetcher) {
            try {
                this._customFetcher(finish);
            } catch (e) {
                finish(e, null);
            }
            return;
        }

        if (typeof Gio !== 'undefined' && Gio.File) {
            try {
                // Status filtering is what guarantees an old, long-running task
                // cannot fall behind a page of recently completed work.
                const file = Gio.File.new_for_uri(
                    `${this._tasksUrl}?status=running&limit=${this._listLimit}`);
                file.load_contents_async(null, (source, res) => {
                    try {
                        const [, contents] = source.load_contents_finish(res);
                        const raw = new TextDecoder('utf-8').decode(contents);
                        finish(null, JSON.parse(raw));
                    } catch (e) {
                        finish(e, null);
                    }
                });
            } catch (e) {
                finish(e, null);
            }
        } else {
            finish(new Error('no HTTP client'), null);
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
                this._knownTasks.delete(id);
            }
        }

        for (const [id, previous] of this._runningTasks) {
            if (!currentActive.has(id)) {
                changed = true;
                if (!taskList.some(task => task.id === id))
                    this._resolveTaskOutcome(id, previous);
            }
        }
        this._runningTasks = currentActive;
        // A light state heartbeat keeps the visible age and selected log fresh;
        // closed cards still skip their expensive rendering.
        if ((changed || currentActive.size > 0) && this._bus && this._bus.notifyStateChange)
            this._bus.notifyStateChange();
    }

    _resolveTaskOutcome(taskId, previous) {
        if (typeof Gio === 'undefined' || !Gio.File)
            return;
        try {
            const file = Gio.File.new_for_uri(`${this._tasksUrl}/${encodeURIComponent(taskId)}`);
            file.load_contents_async(null, (source, res) => {
                if (this._destroyed)
                    return;
                try {
                    const [, contents] = source.load_contents_finish(res);
                    const task = JSON.parse(new TextDecoder('utf-8').decode(contents));
                    this._knownTasks.set(taskId, { ...task });
                    this._cancelling.delete(taskId);
                    this._logs.delete(taskId);
                    if (task.status === 'completed' || task.status === 'done')
                        this._emitTaskCompleted(task);
                    else if (task.status === 'failed' || task.status === 'error')
                        this._emitTaskFailed(task);
                    this._knownTasks.delete(taskId);
                } catch (e) {
                    this._knownTasks.set(taskId, { ...previous, status: 'unknown' });
                }
            });
        } catch (e) {}
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
        if (this._logInFlight.has(taskId)) {
            this._logInFlight.get(taskId).push(callback);
            return;
        }
        this._logInFlight.set(taskId, [callback]);
        const finish = (events) => {
            const lines = (Array.isArray(events) ? events : []).slice(-4).map(e => ({
                ts: Number(e.ts) || 0,
                text: `${e.kind ? `${e.kind}: ` : ''}${String(e.text || '').replace(/\s+/g, ' ').trim()}`,
            }));
            this._logs.set(taskId, { ts: Date.now(), events: Array.isArray(events) ? events.slice(-4) : [], lines });
            const callbacks = this._logInFlight.get(taskId) || [];
            this._logInFlight.delete(taskId);
            for (const cb of callbacks)
                cb(lines);
        };
        if (this._logFetcher) {
            this._logFetcher(taskId, (err, events) => finish(err ? [] : events));
            return;
        }
        if (typeof Gio === 'undefined' || !Gio.File) {
            finish([]);
            return;
        }
        try {
            const file = Gio.File.new_for_uri(
                `${this._eventsUrl}?task_id=${encodeURIComponent(taskId)}&limit=4`);
            file.load_contents_async(null, (source, res) => {
                try {
                    const [, contents] = source.load_contents_finish(res);
                    finish(JSON.parse(new TextDecoder('utf-8').decode(contents)));
                } catch (e) {
                    finish([]);
                }
            });
        } catch (e) {
            finish([]);
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
        this._stopLivePing();
        if (this._wsReconnectId && typeof GLib !== 'undefined') {
            GLib.source_remove(this._wsReconnectId);
            this._wsReconnectId = 0;
        }
        if (this._wsConnection) {
            try {
                this._wsConnection.close(Soup.WebsocketCloseCode.NORMAL, 'extension disabled');
            } catch (e) {}
            this._wsConnection = null;
        }
        if (this._wsSession && this._wsSession.abort)
            this._wsSession.abort();
        this._wsSession = null;
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
        this._logInFlight.clear();
        this._cancelling.clear();
        this._runningTasks.clear();
        this._knownTasks.clear();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandTaskProvider };
}
