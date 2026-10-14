// Dynamic Island AI Quota Provider
//
// How much of each AI plan's limits is used: Codex, Claude and Gemini, side by side.
// quotaSnapshot.py reads what each tool already records on this machine (Codex session rollouts,
// Claude Code's cached plan usage, agy's /usage via the Agent Office on loopback) and prints one
// shape per provider: { ts, stale, error, windows: [{ label, used, resetsAt, expired }] }.
// Hard rule: NEVER reads credentials, tokens, or calls external APIs.

/* exported IslandQuotaProvider, describeUsage, PROVIDERS */
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
const { IslandEvents = {}, IslandPriority = {}, IslandDwellMs = {} } = Types;

const DEFAULT_ACTIVE_POLL_MS = 60000;   // 60s when visible/compact
const DEFAULT_IDLE_POLL_MS   = 300000;  // 300s when dormant/idle

var PROVIDERS = [['codex', 'Codex'], ['claude', 'Claude'], ['gemini', 'Gemini']];
const CAUTION_USED = 80;
const CRITICAL_USED = 95;
const LEVELS = { normal: 0, caution: 1, critical: 2 };

const _blank = error => ({ ts: 0, stale: true, error: error || 'Not read yet', windows: [] });

function _clean(p) {
    if (!p || typeof p !== 'object')
        return _blank('Unavailable');
    const windows = (Array.isArray(p.windows) ? p.windows : []).filter(w =>
        w && typeof w.used === 'number' && isFinite(w.used) && w.used >= 0 && w.used <= 100);
    return { ts: Number(p.ts) || 0, stale: !!p.stale, error: p.error ? String(p.error) : '', windows };
}

// The tightest live window of a provider: the one closest to its limit.
function _tightest(p, now) {
    let best = null;
    for (const w of p.windows) {
        if (w.expired || w.resetsAt <= now)
            continue;
        if (!best || w.used > best.used)
            best = w;
    }
    return best;
}

function _level(used) {
    return used >= CRITICAL_USED ? 'critical' : used >= CAUTION_USED ? 'caution' : 'normal';
}

// What the usage card shows, as plain data (kept out of the widgets so it can be tested headless).
function describeUsage(data, now) {
    now = now || Date.now() / 1000;
    return PROVIDERS.map(([key, name]) => {
        const p = _clean((data || {})[key]);
        const rows = p.windows.map(w => {
            const expired = w.expired || w.resetsAt <= now;
            return {
                label: w.label,
                used: expired ? null : Math.round(w.used),
                text: expired ? 'reset, awaiting update' : `${Math.round(w.used)}% used`,
                resetsAt: w.resetsAt,
                level: expired ? 'normal' : _level(w.used),
            };
        });
        const tight = _tightest(p, now);
        return {
            key, name, rows,
            ts: p.ts,
            stale: p.stale,
            unavailable: rows.length ? '' : (p.error || 'Unavailable'),
            level: tight ? _level(tight.used) : 'normal',
        };
    });
}

var IslandQuotaProvider = class IslandQuotaProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._activePollMs = options.activePollMs || DEFAULT_ACTIVE_POLL_MS;
        this._idlePollMs = options.idlePollMs || DEFAULT_IDLE_POLL_MS;
        this._transcriptPath = options.transcriptPath || null;
        this._customFetcher = options.fetcher || null; // for tests/mocking

        this._pollTimerId = 0;
        this._isDormant = false;
        this._destroyed = false;

        this._usage = { codex: _blank(), claude: _blank(), gemini: _blank() };
        this._levels = { codex: 'normal', claude: 'normal', gemini: 'normal' };
        this._peak = { codex: 0, claude: 0, gemini: 0 };
        this._error = '';

        this._agyData = {
            status: 'healthy',
            sessionTokens: { input: 0, output: 0, cache: 0, total: 0 },
            remainingPercent: null,
            limit: null,
            resetTime: null,
            unavailableReason: 'Server-enforced (Google AI Pro)',
            lastTurnAt: '',
        };

        this._snapshotProcess = null;
        this._queuedRefreshCallbacks = [];
        this._transcriptMonitor = null;
        this._transcriptCancellable = null;
    }

    init() {
        this._destroyed = false;
        this._initAgyWatcher();
        this.poll();
        this._scheduleNextPoll();
    }

    setDormant(dormant) {
        if (this._isDormant === dormant)
            return;
        this._isDormant = dormant;
        if (this._pollTimerId && typeof GLib !== 'undefined' && GLib.source_remove) {
            GLib.source_remove(this._pollTimerId);
            this._pollTimerId = 0;
        } else if (this._pollTimerId && typeof clearTimeout !== 'undefined') {
            clearTimeout(this._pollTimerId);
            this._pollTimerId = 0;
        }
        this._scheduleNextPoll();
    }

    _scheduleNextPoll() {
        if (this._destroyed)
            return;
        const interval = this._isDormant ? this._idlePollMs : this._activePollMs;
        if (typeof GLib !== 'undefined' && GLib.timeout_add) {
            this._pollTimerId = GLib.timeout_add(GLib.PRIORITY_LOW, interval, () => {
                this.poll();
                return GLib.SOURCE_CONTINUE;
            });
        } else if (typeof setTimeout !== 'undefined') {
            this._pollTimerId = setTimeout(() => {
                this.poll();
                this._scheduleNextPoll();
            }, interval);
        }
    }

    // kept for callers written before Codex and Gemini were added
    pollClaude() {
        this.poll();
    }

    poll(force = false, done = null) {
        if (this._destroyed) {
            if (done) done(false);
            return;
        }

        if (this._customFetcher) {
            this._customFetcher((err, data) => {
                if (err) {
                    this.handleFailure(err.message || String(err));
                    if (done) done(false);
                } else {
                    this.applySnapshot(data);
                    if (done) done(true);
                }
            }, force);
            return;
        }

        if (typeof Gio === 'undefined' || !Me) {
            if (done) done(false);
            return;
        }
        if (this._snapshotProcess) {
            // A manual click must not disappear behind a scheduled background poll.
            if (force)
                this._queuedRefreshCallbacks.push(done);
            else if (done)
                done(false);
            return;
        }
        try {
            const args = ['python3', `${Me.path}/quotaSnapshot.py`];
            if (force)
                args.push('--refresh');
            const proc = Gio.Subprocess.new(args,
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            this._snapshotProcess = proc;
            proc.communicate_utf8_async(null, null, (source, res) => {
                this._snapshotProcess = null;
                if (this._destroyed)
                    return;
                let ok = false;
                try {
                    const [, output] = source.communicate_utf8_finish(res);
                    if (!source.get_successful())
                        throw new Error('Usage snapshot unavailable');
                    this.applySnapshot(JSON.parse(output));
                    ok = true;
                } catch (e) {
                    this.handleFailure(e.message || 'Usage snapshot unavailable');
                }
                if (done) done(ok);
                const queued = this._queuedRefreshCallbacks.splice(0);
                if (queued.length)
                    this.poll(true, result => queued.forEach(cb => { if (cb) cb(result); }));
            });
        } catch (e) {
            this.handleFailure(e.message || 'Usage snapshot unavailable');
            if (done) done(false);
        }
    }

    applySnapshot(data) {
        const now = Date.now() / 1000;
        for (const [key] of PROVIDERS)
            this._usage[key] = _clean((data || {})[key]);
        this._error = '';

        // Speak up only when something changes: a provider crossing 80% or 95% used, or a reset.
        let event = null;
        for (const [key, name] of PROVIDERS) {
            const tight = _tightest(this._usage[key], now);
            if (!tight)
                continue;
            const level = _level(tight.used);
            const before = this._levels[key];
            const used = Math.round(tight.used);
            const resets = new Date(tight.resetsAt * 1000).toISOString();
            if (LEVELS[level] > LEVELS[before]) {
                const critical = level === 'critical';
                const e = {
                    type: critical ? IslandEvents.QUOTA_CRITICAL_BREACH || 'QUOTA_CRITICAL_BREACH'
                        : IslandEvents.QUOTA_CAUTION_BREACH || 'QUOTA_CAUTION_BREACH',
                    payload: {
                        provider: 'quota',
                        priority: critical ? IslandPriority.P1_URGENT || 1 : IslandPriority.P2_HIGH || 2,
                        dwellMs: critical ? IslandDwellMs.P1_STICKY || -1 : IslandDwellMs.P2_CAUTION || 6000,
                        message: `${name} ${tight.label} limit ${used}% used`,
                        source: key, window: tight.label, used, resets,
                        canPauseTasks: critical,
                    },
                };
                if (!event || LEVELS[level] > LEVELS[event.level])
                    event = { ...e, level };
            } else if (this._peak[key] >= 60 && used <= 20 && !event) {
                event = {
                    level: 'normal',
                    type: IslandEvents.QUOTA_RESET_CONFIRMED || 'QUOTA_RESET_CONFIRMED',
                    payload: {
                        provider: 'quota',
                        priority: IslandPriority.P3_NORMAL || 3,
                        dwellMs: IslandDwellMs.P3_NORMAL || 3000,
                        message: `${name} limits reset (${used}% used)`,
                        source: key, window: tight.label, used, resets,
                    },
                };
            }
            this._levels[key] = level;
            this._peak[key] = used <= 20 ? used : Math.max(this._peak[key], used);
        }

        if (!this._bus)
            return;
        if (event)
            this._bus.emitEvent(event.type, { ...event.payload, data: this.getData() });
        else if (this._bus._notifyStateChange)
            this._bus._notifyStateChange();       // refresh open views without surfacing anything
    }

    handleFailure(errorMsg) {
        this._error = errorMsg;
        for (const [key] of PROVIDERS)
            this._usage[key] = { ...this._usage[key], stale: true };
        if (this._bus && this._bus._notifyStateChange)
            this._bus._notifyStateChange();
    }

    _initAgyWatcher() {
        if (!this._transcriptPath && typeof GLib !== 'undefined') {
            const home = GLib.get_home_dir();
            const brainDir = `${home}/.gemini/antigravity-cli/brain`;
            if (typeof Gio !== 'undefined') {
                const gDir = Gio.File.new_for_path(brainDir);
                try {
                    if (gDir.query_exists(null)) {
                        const enumerator = gDir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
                        let info;
                        while ((info = enumerator.next_file(null)) !== null) {
                            const name = info.get_name();
                            const candidate = `${brainDir}/${name}/.system_generated/logs/transcript.jsonl`;
                            if (Gio.File.new_for_path(candidate).query_exists(null)) {
                                this._transcriptPath = candidate;
                                break;
                            }
                        }
                    }
                } catch (e) {
                    // Sandbox / not found
                }
            }
        }

        if (this._transcriptPath) {
            this._setupTranscriptMonitor(this._transcriptPath);
            this._readAgyTranscript(this._transcriptPath);
        }
    }

    _setupTranscriptMonitor(filePath) {
        if (typeof Gio === 'undefined' || !Gio.File)
            return;
        try {
            const file = Gio.File.new_for_path(filePath);
            this._transcriptCancellable = new Gio.Cancellable();
            this._transcriptMonitor = file.monitor_file(Gio.FileMonitorFlags.NONE, this._transcriptCancellable);
            this._transcriptMonitor.connect('changed', (_mon, _file, _other, eventType) => {
                if (eventType === Gio.FileMonitorEvent.CHANGED || eventType === Gio.FileMonitorEvent.CHANGES_DONE_HINT) {
                    this._readAgyTranscript(filePath);
                }
            });
        } catch (e) {
            // Test harness fallback
        }
    }

    _readAgyTranscript(filePath) {
        if (typeof Gio === 'undefined' || !Gio.File)
            return;
        try {
            const file = Gio.File.new_for_path(filePath);
            file.load_contents_async(null, (source, res) => {
                try {
                    const [, contents] = source.load_contents_finish(res);
                    const text = new TextDecoder('utf-8').decode(contents);
                    this.parseTranscriptText(text);
                } catch (e) {
                    // Ignore transient read errors during append
                }
            });
        } catch (e) {
            // Ignore
        }
    }

    parseTranscriptText(text) {
        if (!text) return;
        const lines = text.trim().split('\n');
        let totalIn = 0;
        let totalOut = 0;
        let totalCache = 0;
        let lastTimestamp = '';

        for (const line of lines) {
            try {
                const rec = JSON.parse(line);
                if (rec.input_tokens !== null && rec.input_tokens !== undefined) {
                    totalIn += Number(rec.input_tokens) || 0;
                    totalOut += Number(rec.output_tokens) || 0;
                    totalCache += Number(rec.cache_read_tokens) || 0;
                    if (rec.created_at)
                        lastTimestamp = rec.created_at;
                }
            } catch (e) {
                // Ignore corrupt line
            }
        }

        this._agyData.sessionTokens = {
            input: totalIn,
            output: totalOut,
            cache: totalCache,
            total: totalIn + totalOut,
        };
        this._agyData.lastTurnAt = lastTimestamp;
        this._agyData.status = 'healthy';

        if (this._bus && this._bus._notifyStateChange)
            this._bus._notifyStateChange();
    }

    refresh(done = null) {
        this.poll(true, done);
        if (this._transcriptPath)
            this._readAgyTranscript(this._transcriptPath);
    }

    getData() {
        const levels = Object.values(this._levels);
        return {
            codex: { ...this._usage.codex },
            claude: { ...this._usage.claude },
            gemini: { ...this._usage.gemini },
            agy: { ...this._agyData },
            error: this._error,
            criticalBreach: levels.includes('critical'),
            cautionBreach: levels.includes('caution'),
        };
    }

    destroy() {
        this._destroyed = true;
        if (this._snapshotProcess) {
            this._snapshotProcess.force_exit();
            this._snapshotProcess = null;
        }
        for (const cb of this._queuedRefreshCallbacks.splice(0))
            if (cb) cb(false);
        if (this._pollTimerId && typeof GLib !== 'undefined' && GLib.source_remove) {
            GLib.source_remove(this._pollTimerId);
            this._pollTimerId = 0;
        } else if (this._pollTimerId && typeof clearTimeout !== 'undefined') {
            clearTimeout(this._pollTimerId);
            this._pollTimerId = 0;
        }
        if (this._transcriptCancellable) {
            this._transcriptCancellable.cancel();
            this._transcriptCancellable = null;
        }
        if (this._transcriptMonitor) {
            this._transcriptMonitor.cancel();
            this._transcriptMonitor = null;
        }
    }
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { IslandQuotaProvider, describeUsage, PROVIDERS };
}
