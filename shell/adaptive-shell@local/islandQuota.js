// Dynamic Island AI Quota Provider
//
// Telemetry provider for Claude Code and agy (Gemini on Google AI Pro).
// Reads ONLY non-secret local sources (localhost :8790/api/usage & transcript.jsonl).
// Hard rule: NEVER reads credentials, tokens, or calls external APIs.

/* exported IslandQuotaProvider */
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
const USAGE_URL = 'http://127.0.0.1:8790/api/usage';

var IslandQuotaProvider = class IslandQuotaProvider {
    constructor(options = {}) {
        this._bus = options.bus || null;
        this._activePollMs = options.activePollMs || DEFAULT_ACTIVE_POLL_MS;
        this._idlePollMs = options.idlePollMs || DEFAULT_IDLE_POLL_MS;
        this._usageUrl = options.usageUrl || USAGE_URL;
        this._transcriptPath = options.transcriptPath || null;
        this._customFetcher = options.fetcher || null; // for tests/mocking

        this._pollTimerId = 0;
        this._isDormant = false;
        this._destroyed = false;

        this._claudeData = {
            window5h: { remaining: '100%', percent: 100, resets: '' },
            weekly:   { remaining: '100%', percent: 100, resets: '' },
            ts: 0,
            stale: false,
            staleSince: 0,
            error: '',
        };

        this._agyData = {
            status: 'healthy',
            sessionTokens: { input: 0, output: 0, cache: 0, total: 0 },
            remainingPercent: null,
            limit: null,
            resetTime: null,
            unavailableReason: 'Server-enforced (Google AI Pro)',
            lastTurnAt: '',
        };

        this._prev5hPercent = 100;
        this._prevWeeklyPercent = 100;

        this._transcriptMonitor = null;
        this._transcriptCancellable = null;
    }

    init() {
        this._destroyed = false;
        this._initAgyWatcher();
        this.pollClaude();
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
                this.pollClaude();
                return GLib.SOURCE_CONTINUE;
            });
        } else if (typeof setTimeout !== 'undefined') {
            this._pollTimerId = setTimeout(() => {
                this.pollClaude();
                this._scheduleNextPoll();
            }, interval);
        }
    }

    pollClaude() {
        if (this._destroyed)
            return;

        if (this._customFetcher) {
            this._customFetcher((err, data) => {
                if (err)
                    this._handleClaudeFailure(err.message || String(err));
                else
                    this._handleClaudeSuccess(data);
            });
            return;
        }

        // Standard Gio HTTP async read from local agent-office loopback
        if (typeof Gio !== 'undefined' && Gio.File) {
            try {
                const file = Gio.File.new_for_uri(this._usageUrl);
                file.load_contents_async(null, (source, res) => {
                    try {
                        const [, contents] = source.load_contents_finish(res);
                        const raw = new TextDecoder('utf-8').decode(contents);
                        const parsed = JSON.parse(raw);
                        this._handleClaudeSuccess(parsed);
                    } catch (e) {
                        this._handleClaudeFailure(e.message || 'Fetch failed');
                    }
                });
            } catch (e) {
                this._handleClaudeFailure(e.message || 'Connection error');
            }
        }
    }

    _handleClaudeSuccess(data) {
        if (!data || !Array.isArray(data.rows)) {
            this._handleClaudeFailure('Invalid usage payload');
            return;
        }

        const now = Math.floor(Date.now() / 1000);
        let parsed5h = null;
        let parsedWeek = null;

        for (const row of data.rows) {
            const remStr = String(row.remaining || '');
            const pct = parseInt(remStr.replace('%', ''), 10);
            const val = {
                remaining: remStr || 'N/A',
                percent: isNaN(pct) ? null : pct,
                resets: row.resets || '',
            };
            if (row.window === '5h')
                parsed5h = val;
            else if (row.window === 'week')
                parsedWeek = val;
        }

        if (parsed5h)
            this._claudeData.window5h = parsed5h;
        if (parsedWeek)
            this._claudeData.weekly = parsedWeek;

        this._claudeData.ts = data.ts || now;
        this._claudeData.stale = false;
        this._claudeData.staleSince = 0;
        this._claudeData.error = '';

        this._evaluateClaudeThresholds();
    }

    _handleClaudeFailure(errorMsg) {
        const now = Math.floor(Date.now() / 1000);
        this._claudeData.stale = true;
        if (!this._claudeData.staleSince)
            this._claudeData.staleSince = now;
        this._claudeData.error = errorMsg;

        if (this._bus) {
            this._bus.emitEvent(IslandEvents.QUOTA_UPDATED || 'QUOTA_UPDATED', {
                provider: 'quota',
                priority: IslandPriority.P4_AMBIENT || 4,
                dwellMs: IslandDwellMs.P4_AMBIENT || 2000,
                data: this.getData(),
            });
        }
    }

    _evaluateClaudeThresholds() {
        const cur5h = this._claudeData.window5h.percent;
        if (cur5h === null)
            return;

        // 1. Critical breach (<= 5%)
        if (cur5h <= 5 && (this._prev5hPercent > 5 || this._prev5hPercent === null)) {
            if (this._bus) {
                this._bus.emitEvent(IslandEvents.QUOTA_CRITICAL_BREACH || 'QUOTA_CRITICAL_BREACH', {
                    provider: 'quota',
                    priority: IslandPriority.P1_URGENT || 1,
                    dwellMs: IslandDwellMs.P1_STICKY || -1,
                    message: `Claude quota critical (${cur5h}% remaining)`,
                    window: '5h',
                    remaining: `${cur5h}%`,
                    resets: this._claudeData.window5h.resets,
                    canPauseTasks: true,
                    data: this.getData(),
                });
            }
        }
        // 2. Caution breach (<= 20%)
        else if (cur5h <= 20 && cur5h > 5 && this._prev5hPercent > 20) {
            if (this._bus) {
                this._bus.emitEvent(IslandEvents.QUOTA_CAUTION_BREACH || 'QUOTA_CAUTION_BREACH', {
                    provider: 'quota',
                    priority: IslandPriority.P2_HIGH || 2,
                    dwellMs: IslandDwellMs.P2_CAUTION || 6000,
                    message: `Claude quota low (${cur5h}% remaining)`,
                    window: '5h',
                    remaining: `${cur5h}%`,
                    resets: this._claudeData.window5h.resets,
                    data: this.getData(),
                });
            }
        }
        // 3. Reset confirmed (jump upward > 20%)
        else if (cur5h >= 80 && this._prev5hPercent !== null && this._prev5hPercent < 40) {
            if (this._bus) {
                this._bus.emitEvent(IslandEvents.QUOTA_RESET_CONFIRMED || 'QUOTA_RESET_CONFIRMED', {
                    provider: 'quota',
                    priority: IslandPriority.P3_NORMAL || 3,
                    dwellMs: IslandDwellMs.P3_NORMAL || 3000,
                    message: `Claude rate limits refreshed (${cur5h}%)`,
                    window: '5h',
                    remaining: `${cur5h}%`,
                    data: this.getData(),
                });
            }
        } else {
            // Routine update
            if (this._bus) {
                this._bus.emitEvent(IslandEvents.QUOTA_UPDATED || 'QUOTA_UPDATED', {
                    provider: 'quota',
                    priority: IslandPriority.P4_AMBIENT || 4,
                    dwellMs: IslandDwellMs.P4_AMBIENT || 2000,
                    data: this.getData(),
                });
            }
        }

        this._prev5hPercent = cur5h;
        this._prevWeeklyPercent = this._claudeData.weekly.percent;
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

        if (this._bus) {
            this._bus.emitEvent(IslandEvents.QUOTA_UPDATED || 'QUOTA_UPDATED', {
                provider: 'quota',
                priority: IslandPriority.P4_AMBIENT || 4,
                dwellMs: IslandDwellMs.P4_AMBIENT || 2000,
                data: this.getData(),
            });
        }
    }

    refresh() {
        this.pollClaude();
        if (this._transcriptPath)
            this._readAgyTranscript(this._transcriptPath);
    }

    getData() {
        return {
            claude: { ...this._claudeData },
            agy: { ...this._agyData },
        };
    }

    destroy() {
        this._destroyed = true;
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
    module.exports = { IslandQuotaProvider };
}
