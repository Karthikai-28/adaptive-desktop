// Adaptive Shell - pure helpers shared by the shell modules.
//
// Nothing in this file touches GNOME: no imports, no actors, no I/O. That is
// deliberate. GJS resolves everything at call time, so the only code that can
// be proven outside a running gnome-shell is code like this, and
// scripts/verify-shell-helpers.js loads this very file under Node and checks
// it, rather than keeping a copy that could drift.

/* exported parseGitStatus, formatGitStatus, watchdogVerdict, WATCHDOG,
   batteryHealth, verificationSummary, classifyApp, clipboardPush,
   isSecretClipboard, CLIPBOARD_MAX_ITEMS, CLIPBOARD_MAX_CHARS */

// ----------------------------------------------------------------- git

// `git status --porcelain=v1 --branch` -> what the top bar shows.
//
//   ## main...origin/main [ahead 1, behind 2]
//    M file
//   ?? new
//
// Returns null for text that is not porcelain output (not a repository,
// git missing), so the caller can show the project without a status.
function parseGitStatus(text) {
    const lines = String(text || '').split('\n').filter(line => line.length);
    if (!lines.length || !lines[0].startsWith('## '))
        return null;

    const head = lines[0].slice(3);
    const status = { branch: '', ahead: 0, behind: 0, dirty: 0, detached: false };

    if (head.startsWith('No commits yet on ')) {
        status.branch = head.slice('No commits yet on '.length);
    } else if (head.startsWith('HEAD (no branch)')) {
        status.branch = 'detached';
        status.detached = true;
    } else {
        status.branch = head.split('...')[0].split(' ')[0];
        const ahead = head.match(/ahead (\d+)/);
        const behind = head.match(/behind (\d+)/);
        status.ahead = ahead ? parseInt(ahead[1], 10) : 0;
        status.behind = behind ? parseInt(behind[1], 10) : 0;
    }

    status.dirty = lines.length - 1;
    return status;
}

// "main", "main ±3", "main ±3 ↑1 ↓2". The ± is uncommitted files.
function formatGitStatus(status) {
    if (!status)
        return '';
    const parts = [status.branch];
    if (status.dirty)
        parts.push(`±${status.dirty}`);
    if (status.ahead)
        parts.push(`↑${status.ahead}`);
    if (status.behind)
        parts.push(`↓${status.behind}`);
    return parts.join(' ');
}

// ------------------------------------------------------------ watchdog

// A desktop start that does not reach HEALTHY_AFTER_S of uptime, three times
// inside WINDOW_S, is a crash loop. Planned restarts (reload-adaptive-shell.sh)
// and clean disables clear the record, so development does not trip it.
var WATCHDOG = {
    MAX_STARTS: 3,
    WINDOW_S: 10 * 60,
    HEALTHY_AFTER_S: 5 * 60,
};

// state is what ~/.cache/adaptive-desktop/shell-watchdog.json held:
// { starts: [unix seconds...], tripped: bool }. Returns the state to save and
// whether this start must stand down.
function watchdogVerdict(state, now) {
    const previous = state && typeof state === 'object' ? state : {};
    if (previous.tripped)
        return { state: { starts: [], tripped: true }, tripped: true };

    const recent = (Array.isArray(previous.starts) ? previous.starts : [])
        .filter(t => typeof t === 'number' && now - t >= 0 && now - t < WATCHDOG.WINDOW_S);
    recent.push(now);

    if (recent.length >= WATCHDOG.MAX_STARTS)
        return { state: { starts: [], tripped: true }, tripped: true };
    return { state: { starts: recent, tripped: false }, tripped: false };
}

// ------------------------------------------------------------- battery

// values: the battery's sysfs attributes as strings (missing ones absent).
// energy_* are µWh, charge_* µAh; either pair gives the same percentage.
function batteryHealth(values) {
    const v = values || {};
    const num = key => {
        const n = parseInt(v[key], 10);
        return Number.isFinite(n) && n > 0 ? n : 0;
    };

    let full = num('energy_full');
    let design = num('energy_full_design');
    let unit = 'Wh';
    if (!full || !design) {
        full = num('charge_full');
        design = num('charge_full_design');
        unit = 'Ah';
    }
    if (!full || !design)
        return null;

    const cycles = num('cycle_count');
    const limit = num('charge_control_end_threshold');
    return {
        healthPct: Math.round(Math.min(full / design, 1.5) * 100),
        full: full / 1e6,
        design: design / 1e6,
        unit,
        cycles: cycles || null,
        limit: limit && limit < 100 ? limit : null,
    };
}

// --------------------------------------------------------- verification

// report: verification/live-verification-latest.json, or null. total is the
// number of checks, which the recorder writes into the report.
function verificationSummary(report) {
    const checks = report && report.checks ? report.checks : {};
    const total = report && Number.isInteger(report.total) ? report.total : 0;
    let passed = 0;
    let failed = 0;
    for (const id of Object.keys(checks)) {
        const result = checks[id] && checks[id].result;
        if (result === 'pass' || result === 'na')
            passed++;
        else if (result === 'fail')
            failed++;
    }
    const complete = total > 0 && passed >= total;
    let text = total ? `${passed} of ${total} physical checks done` : 'Physical checks not started';
    if (failed)
        text += ` · ${failed} failing`;
    return { passed, failed, total, complete, text };
}

// ------------------------------------------------------------ snapshots

// How a parked window's app is brought back: a terminal opens in the project
// folder, a file manager or editor opens the folder itself, anything else is
// launched as it is.
function classifyApp(appId, categories) {
    const id = String(appId || '').toLowerCase();
    const cats = String(categories || '').split(';').filter(Boolean);
    if (cats.includes('TerminalEmulator') || /terminal|tilix|kitty|alacritty|konsole/.test(id))
        return 'terminal';
    if (cats.includes('FileManager') || id === 'org.gnome.nautilus.desktop')
        return 'folder';
    if (cats.includes('TextEditor') || cats.includes('IDE') ||
        /^(code|codium|code-oss|org\.gnome\.texteditor|org\.gnome\.gedit|sublime_text|jetbrains-.*)\.desktop$/.test(id))
        return 'folder';
    return 'plain';
}

// ------------------------------------------------------------ clipboard

var CLIPBOARD_MAX_ITEMS = 50;
var CLIPBOARD_MAX_CHARS = 20000;

// Password managers mark what they copy so clipboard tools leave it alone.
const SECRET_MIMES = ['x-kde-passwordManagerHint', 'application/x-nspasteboard-concealed-type'];

function isSecretClipboard(mimetypes) {
    return (mimetypes || []).some(m => SECRET_MIMES.includes(m));
}

// Newest first, no duplicates, bounded. Returns a new array.
function clipboardPush(items, text, at) {
    if (typeof text !== 'string' || !text.trim() || text.length > CLIPBOARD_MAX_CHARS)
        return items.slice();
    const rest = items.filter(item => item.text !== text);
    return [{ text, at }, ...rest].slice(0, CLIPBOARD_MAX_ITEMS);
}
