// Dynamic Island Backend Orchestrator & Event Queue Bus
//
// Manages the 4 MVP providers, priority queue, burst debouncing,
// dwell transitions, multi-activity decoupling, and privacy sanitization.
// Provides a clean, event-driven subscription interface for Lena's frontend.

/* exported DynamicIslandBackend */
/* global require, module, setTimeout, clearTimeout */

let Gio, GLib;
try {
    Gio = imports.gi.Gio;
    GLib = imports.gi.GLib;
} catch (e) {
    // Headless test harness
}

let Me = null;
try {
    Me = imports.misc.extensionUtils.getCurrentExtension();
} catch (e) {
    Me = null;
}

function _loadModule(name) {
    if (Me && Me.imports && Me.imports[name])
        return Me.imports[name];
    try {
        if (typeof imports !== 'undefined' && imports[name])
            return imports[name];
    } catch (e) {}
    try {
        if (typeof require !== 'undefined')
            return require(`./${name}.js`);
    } catch (e) {}
    return {};
}

const Types = _loadModule('islandTypes');
const Quota = _loadModule('islandQuota');
const Tasks = _loadModule('islandTasks');
const Media = _loadModule('islandMedia');
const Timers = _loadModule('islandTimers');

const { IslandEvents = {}, IslandPriority = {}, IslandDwellMs = {}, ActivityPrecedence = {} } = Types;

const QUEUE_CAPACITY = 8;
const ROUTINE_EVENT_TTL_MS = 15000; // 15s TTL for routine events

var DynamicIslandBackend = class DynamicIslandBackend {
    constructor(options = {}) {
        this._options = options;
        this._destroyed = false;

        // Event Queue
        this._queue = []; // Array of queued event items
        this._surfacedEvent = null; // Currently displayed event
        this._dwellTimerId = 0;
        this._dwellRemainingMs = 0;
        this._dwellStartTs = 0;
        this._isDwellPaused = false;
        this._isPinned = false;
        this._isScreenSharing = false;

        // Subscriptions
        this._surfacedListeners = new Set();
        this._tuckedListeners = new Set();
        this._stateChangeListeners = new Set();

        // Providers
        this.quota = new Quota.IslandQuotaProvider({ bus: this, ...options.quotaOptions });
        this.tasks = new Tasks.IslandTaskProvider({ bus: this, ...options.taskOptions });
        this.media = new Media.IslandMediaProvider({ bus: this, ...options.mediaOptions });
        this.timers = new Timers.IslandTimerProvider({ bus: this, ...options.timerOptions });

        // State hash cache for deduplication
        this._lastEventHash = '';
    }

    init() {
        this._destroyed = false;
        this.quota.init();
        this.tasks.init();
        this.media.init();
        this.timers.init();
    }

    // ----------------------------------------------------------------- Event Ingestion
    emitEvent(eventType, payload) {
        if (this._destroyed)
            return;

        const priority = payload.priority || IslandPriority.P4_AMBIENT;
        const dwellMs = payload.dwellMs !== undefined ? payload.dwellMs : IslandDwellMs.P3_NORMAL;
        const now = Date.now();

        // 1. Compute state hash for deduplication (quiet state rule)
        const hash = `${eventType}:${JSON.stringify(payload.data || {})}:${payload.message || ''}`;
        if (hash === this._lastEventHash && priority > IslandPriority.P1_URGENT) {
            return; // Duplicate event state, suppress UI re-surfacing
        }
        this._lastEventHash = hash;

        const eventItem = {
            id: `${now}-${Math.random().toString(36).substr(2, 6)}`,
            type: eventType,
            priority,
            dwellMs,
            remainingDwellMs: dwellMs,
            createdTs: now,
            // Keep the source payload so ending screen sharing restores the
            // real card. Projection happens every time state leaves the bus,
            // which also protects events that were already surfaced or queued.
            payload,
        };

        // 3. Evaluate preemption or queue insertion
        this._ingestEvent(eventItem);
    }

    _ingestEvent(eventItem) {
        if (!this._surfacedEvent) {
            // Nothing currently displayed -> surface immediately
            this._surfaceEvent(eventItem);
            return;
        }

        // Check if incoming event preempts currently surfaced event
        if (eventItem.priority < this._surfacedEvent.priority) {
            // Higher priority (P1 < P2 < P3 < P4 numerically)
            this._preemptCurrentEvent(eventItem);
        } else {
            // Lower or equal priority -> enqueue
            this._enqueueEvent(eventItem);
        }
    }

    _enqueueEvent(eventItem) {
        // Prune expired events
        this._pruneQueue();

        if (this._queue.length >= QUEUE_CAPACITY) {
            // Drop lowest priority item with shortest remaining TTL
            let worstIdx = -1;
            let worstPriority = -1;
            for (let i = 0; i < this._queue.length; i++) {
                if (this._queue[i].priority > worstPriority) {
                    worstPriority = this._queue[i].priority;
                    worstIdx = i;
                }
            }
            if (worstIdx >= 0 && worstPriority >= eventItem.priority) {
                this._queue.splice(worstIdx, 1);
            } else {
                return; // Queue full with higher priority items
            }
        }

        // Insert ordered by priority ASC, tie-breaking FIFO
        let inserted = false;
        for (let i = 0; i < this._queue.length; i++) {
            if (eventItem.priority < this._queue[i].priority) {
                this._queue.splice(i, 0, eventItem);
                inserted = true;
                break;
            }
        }
        if (!inserted) {
            this._queue.push(eventItem);
        }
    }

    _preemptCurrentEvent(newEvent) {
        const interrupted = this._surfacedEvent;
        this._clearDwellTimer();

        // Calculate remaining dwell for the interrupted item
        if (interrupted.dwellMs > 0) {
            const elapsed = Date.now() - this._dwellStartTs;
            interrupted.remainingDwellMs = Math.max(500, interrupted.dwellMs - elapsed);
        }

        // If interrupted item has valid TTL, re-queue it
        if (interrupted.dwellMs === -1 || (interrupted.remainingDwellMs > 0 && interrupted.priority <= IslandPriority.P3_NORMAL)) {
            this._enqueueEvent(interrupted);
        }

        this._surfacedEvent = null;
        this._surfaceEvent(newEvent);
    }

    _surfaceEvent(eventItem) {
        this._surfacedEvent = eventItem;
        this._dwellStartTs = Date.now();
        this._dwellRemainingMs = eventItem.remainingDwellMs || eventItem.dwellMs;
        this._isDwellPaused = false;

        // Notify UI subscribers
        this._notifySurfaced(eventItem);
        this._notifyStateChange();

        // Schedule auto-tuck unless sticky (-1)
        if (this._dwellRemainingMs > 0) {
            this._scheduleDwellTimer(this._dwellRemainingMs);
        }
    }

    _scheduleDwellTimer(durationMs) {
        this._clearDwellTimer();
        const tick = () => {
            this._dwellTimerId = 0;
            if (!this._isPinned) {
                this._tuckCurrentEvent();
            }
        };

        if (typeof GLib !== 'undefined' && GLib.timeout_add) {
            this._dwellTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, durationMs, () => {
                tick();
                return GLib.SOURCE_REMOVE;
            });
        } else if (typeof setTimeout !== 'undefined') {
            this._dwellTimerId = setTimeout(tick, durationMs);
        }
    }

    _clearDwellTimer() {
        if (this._dwellTimerId) {
            if (typeof GLib !== 'undefined' && GLib.source_remove)
                GLib.source_remove(this._dwellTimerId);
            else if (typeof clearTimeout !== 'undefined')
                clearTimeout(this._dwellTimerId);
            this._dwellTimerId = 0;
        }
    }

    _tuckCurrentEvent() {
        const tucked = this._surfacedEvent;
        this._clearDwellTimer();
        this._surfacedEvent = null;

        if (tucked) {
            this._notifyTucked(tucked);
        }

        // Check if next queued event is waiting
        this._pruneQueue();
        if (this._queue.length > 0) {
            const next = this._queue.shift();
            this._surfaceEvent(next);
        } else {
            this._notifyStateChange();
        }
    }

    _pruneQueue() {
        const now = Date.now();
        this._queue = this._queue.filter(item => {
            if (item.dwellMs === -1)
                return true; // Sticky never expires from queue
            return (now - item.createdTs) < ROUTINE_EVENT_TTL_MS;
        });
    }

    // ----------------------------------------------------------------- Interaction Overrides
    pauseDwell() {
        if (!this._surfacedEvent || this._isDwellPaused || this._surfacedEvent.dwellMs <= 0)
            return;

        const elapsed = Date.now() - this._dwellStartTs;
        this._dwellRemainingMs = Math.max(0, this._dwellRemainingMs - elapsed);
        this._clearDwellTimer();
        this._isDwellPaused = true;
    }

    resumeDwell() {
        if (!this._surfacedEvent || !this._isDwellPaused || this._isPinned)
            return;

        this._isDwellPaused = false;
        this._dwellStartTs = Date.now();
        const resumeMs = Math.max(1000, this._dwellRemainingMs);
        this._scheduleDwellTimer(resumeMs);
    }

    setPinned(pinned) {
        this._isPinned = Boolean(pinned);
        if (this._isPinned) {
            this._clearDwellTimer();
        } else {
            if (this._surfacedEvent && this._surfacedEvent.dwellMs > 0) {
                this.resumeDwell();
            } else if (!this._surfacedEvent && this._queue.length > 0) {
                this._tuckCurrentEvent();
            }
        }
        this._notifyStateChange();
    }

    dismissCurrentEvent() {
        this._tuckCurrentEvent();
    }

    setScreenSharing(active) {
        const sharing = Boolean(active);
        if (this._isScreenSharing === sharing)
            return;
        this._isScreenSharing = sharing;
        this._notifyStateChange();
    }

    _sanitizeForPrivacy(eventType, payload) {
        const copy = { ...payload };
        if (copy.provider === 'quota') {
            copy.message = '✦ Active';
            copy.remaining = '✦ Active';
            copy.data = { privacyHidden: true };
        } else if (copy.provider === 'task') {
            copy.title = 'AI Task in Progress';
            copy.message = 'Agent: Task in Progress';
            copy.agent = 'Agent';
            copy.project = '';
            copy.error = '';
            copy.data = copy.data ? {
                id: copy.data.id,
                status: copy.data.status,
                steps: copy.data.steps,
                title: 'AI Task',
            } : { title: 'AI Task' };
        } else if (copy.provider === 'media') {
            copy.title = 'Media playing';
            copy.artist = '';
            copy.album = '';
            copy.artUrl = '';
            copy.message = 'Media playing';
            copy.data = { privacyHidden: true };
        } else if (copy.provider === 'ros') {
            copy.title = 'ROS 2 alert';
            copy.message = 'ROS 2 needs attention';
            copy.data = copy.data ? {
                count: copy.data.count,
                level: copy.data.level,
                privacyHidden: true,
            } : { privacyHidden: true };
        }
        return copy;
    }

    _projectEvent(eventItem) {
        if (!eventItem || !this._isScreenSharing)
            return eventItem;
        return {
            ...eventItem,
            payload: this._sanitizeForPrivacy(eventItem.type, eventItem.payload || {}),
        };
    }

    // ----------------------------------------------------------------- Multi-Activity Decoupling
    setRosRecording(recording) {
        if (JSON.stringify(this._rosRecording || null) === JSON.stringify(recording || null)) return;
        this._rosRecording = recording;
        this.notifyStateChange();
    }

    getMultiActivitySlots() {
        const activeTasks = this.tasks.getActiveTasks();
        const media = this.media.getCurrentTrack();
        const timer = this.timers.getState();

        let primary = null;
        let secondary = null;

        const candidates = [];
        if (this._rosRecording) {
            candidates.push({ type: 'ros', rank: 0,
                title: this._isScreenSharing ? 'Recording active' : 'ROS 2 · recording',
                data: this._isScreenSharing ? { recording: true } : this._rosRecording });
        }

        if (activeTasks.length > 0) {
            candidates.push({
                type: 'task',
                rank: ActivityPrecedence.TASK,
                title: this._isScreenSharing ? 'AI task in progress' : activeTasks[0].title,
                agent: this._isScreenSharing ? '' : activeTasks[0].agent,
                data: this._isScreenSharing
                    ? { id: activeTasks[0].id, status: activeTasks[0].status, title: 'AI task' }
                    : activeTasks[0],
            });
        }
        if (timer.status === 'RUNNING') {
            candidates.push({
                type: 'timer',
                rank: ActivityPrecedence.TIMER,
                title: timer.label,
                formatted: timer.formatted,
                data: timer,
            });
        }
        if (media.isPlaying) {
            candidates.push({
                type: 'media',
                rank: ActivityPrecedence.MEDIA,
                title: this._isScreenSharing ? 'Media playing' : media.title,
                artist: this._isScreenSharing ? '' : media.artist,
                data: this._isScreenSharing ? { isPlaying: true, privacyHidden: true } : media,
            });
        }

        // Sort candidates by rank (TASK=1, TIMER=2, MEDIA=3)
        candidates.sort((a, b) => a.rank - b.rank);

        if (candidates.length > 0)
            primary = candidates[0];
        if (candidates.length > 1)
            secondary = candidates[1];

        return { primary, secondary, overflowCount: Math.max(0, candidates.length - 2) };
    }

    // ----------------------------------------------------------------- UI State Accessor
    getState() {
        const rawQuota = this.quota.getData();
        const rawTasks = this.tasks.getActiveTasks();
        const rawMedia = this.media.getCurrentTrack();
        const quota = this._isScreenSharing ? {
            privacyHidden: true,
            criticalBreach: rawQuota.criticalBreach,
            cautionBreach: rawQuota.cautionBreach,
        } : rawQuota;
        const tasks = this._isScreenSharing ? rawTasks.map(task => ({
            id: task.id,
            status: task.status,
            steps: task.steps,
            started_at: task.started_at,
            title: 'AI task in progress',
            agent: 'Agent',
        })) : rawTasks;
        const media = this._isScreenSharing ? {
            ...rawMedia,
            title: rawMedia.title ? 'Media playing' : '',
            artist: '',
            album: '',
            artUrl: '',
            identity: rawMedia.playerBusName ? 'Media player' : '',
            privacyHidden: true,
        } : rawMedia;
        return {
            surfacedEvent: this._projectEvent(this._surfacedEvent),
            queueLength: this._queue.length,
            isPinned: this._isPinned,
            isScreenSharing: this._isScreenSharing,
            multiActivity: this.getMultiActivitySlots(),
            quota,
            tasks,
            media,
            timer: this.timers.getState(),
        };
    }

    // ----------------------------------------------------------------- Subscriptions
    onEventSurfaced(cb) {
        this._surfacedListeners.add(cb);
        return () => this._surfacedListeners.delete(cb);
    }

    onEventTucked(cb) {
        this._tuckedListeners.add(cb);
        return () => this._tuckedListeners.delete(cb);
    }

    onStateChanged(cb) {
        this._stateChangeListeners.add(cb);
        return () => this._stateChangeListeners.delete(cb);
    }

    onSurfaced(cb) {
        return this.onEventSurfaced(cb);
    }

    onTucked(cb) {
        return this.onEventTucked(cb);
    }

    onStateChange(cb) {
        return this.onStateChanged(cb);
    }

    offSurfaced(cb) {
        this._surfacedListeners.delete(cb);
    }

    offTucked(cb) {
        this._tuckedListeners.delete(cb);
    }

    offStateChange(cb) {
        this._stateChangeListeners.delete(cb);
    }

    _notifySurfaced(eventItem) {
        const projected = this._projectEvent(eventItem);
        for (const cb of this._surfacedListeners) {
            try { cb(this, projected); } catch (e) { /* ignore listener exception */ }
        }
    }

    _notifyTucked(eventItem) {
        const projected = this._projectEvent(eventItem);
        for (const cb of this._tuckedListeners) {
            try { cb(this, projected); } catch (e) { /* ignore listener exception */ }
        }
    }

    // For providers whose state changed without anything worth surfacing
    // (a task cancelled, a timer reset, a seek): redraw what is on screen.
    notifyStateChange() {
        if (!this._destroyed)
            this._notifyStateChange();
    }

    _notifyStateChange() {
        const state = this.getState();
        for (const cb of this._stateChangeListeners) {
            try { cb(this, state); } catch (e) { /* ignore listener exception */ }
        }
    }

    destroy() {
        this._destroyed = true;
        this._clearDwellTimer();
        this.quota.destroy();
        this.tasks.destroy();
        this.media.destroy();
        this.timers.destroy();
        this._queue = [];
        this._surfacedEvent = null;
        this._surfacedListeners.clear();
        this._tuckedListeners.clear();
        this._stateChangeListeners.clear();
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { DynamicIslandBackend };
}
