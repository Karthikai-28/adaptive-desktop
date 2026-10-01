// Adaptive Shell - pure helpers shared by the shell modules.
//
// Nothing in this file touches GNOME: no imports, no actors, no I/O. That is
// deliberate. GJS resolves everything at call time, so the only code that can
// be proven outside a running gnome-shell is code like this, and
// scripts/verify-shell-helpers.js loads this very file under Node and checks
// it, rather than keeping a copy that could drift.

/* exported parseGitStatus, formatGitStatus, watchdogVerdict, WATCHDOG,
   batteryHealth, verificationSummary, classifyApp, clipboardPush,
   clipboardPushImage, clipboardPin, clipboardClear, clipboardTrim, pngSize,
   formatBytes, isSecretClipboard, CLIPBOARD_MAX_ITEMS, CLIPBOARD_MAX_CHARS,
   CLIPBOARD_MAX_PINS, CLIPBOARD_MAX_IMAGES, CLIPBOARD_MAX_IMAGE_BYTES,
   DROPDOWN_ROLE, dropdownTerminalKind, dropdownArgv, dropdownRect,
   isDropdownWindow */

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
var CLIPBOARD_MAX_PINS = 20;
// Images are held as the bytes that were copied, so they are few and bounded.
var CLIPBOARD_MAX_IMAGES = 5;
var CLIPBOARD_MAX_IMAGE_BYTES = 8 * 1024 * 1024;

// Password managers mark what they copy so clipboard tools leave it alone.
const SECRET_MIMES = ['x-kde-passwordManagerHint', 'application/x-nspasteboard-concealed-type'];

function isSecretClipboard(mimetypes) {
    return (mimetypes || []).some(m => SECRET_MIMES.includes(m));
}

// Drop the oldest unpinned entries until the list fits. A pinned entry is
// never dropped to make room.
function clipboardTrim(items) {
    const kept = items.slice();
    for (let i = kept.length - 1; i >= 0 && kept.length > CLIPBOARD_MAX_ITEMS; i--) {
        if (!kept[i].pinned)
            kept.splice(i, 1);
    }
    let images = kept.filter(item => item.kind === 'image').length;
    for (let i = kept.length - 1; i >= 0 && images > CLIPBOARD_MAX_IMAGES; i--) {
        if (kept[i].kind === 'image' && !kept[i].pinned) {
            kept.splice(i, 1);
            images--;
        }
    }
    return kept;
}

// Newest first, no duplicates, bounded. Returns a new array. Copying a text
// that is already there moves it to the top and keeps its pin.
function clipboardPush(items, text, at, id = 0) {
    if (typeof text !== 'string' || !text.trim() || text.length > CLIPBOARD_MAX_CHARS)
        return items.slice();
    const earlier = items.find(item => item.kind !== 'image' && item.text === text);
    const rest = items.filter(item => item !== earlier);
    const entry = { text, at };
    if (id)
        entry.id = id;
    if (earlier && earlier.pinned)
        entry.pinned = true;
    return clipboardTrim([entry, ...rest]);
}

// An image entry: { kind: 'image', id, at, mime, size, width, height, hash }.
// The bytes themselves stay with the caller, keyed by id. A copy of the same
// image again (same hash and size) moves it to the top.
function clipboardPushImage(items, image) {
    if (!image || !image.size || image.size > CLIPBOARD_MAX_IMAGE_BYTES)
        return items.slice();
    const earlier = items.find(item => item.kind === 'image' &&
        item.hash === image.hash && item.size === image.size);
    const rest = items.filter(item => item !== earlier);
    const entry = { ...image, kind: 'image', text: '' };
    if (earlier && earlier.pinned)
        entry.pinned = true;
    return clipboardTrim([entry, ...rest]);
}

// Pin or unpin the entry with that id. Returns a new array, unchanged if the
// id is unknown or the pins are full.
function clipboardPin(items, id, pinned) {
    const target = items.find(item => item.id === id);
    if (!target || !!target.pinned === !!pinned)
        return items.slice();
    if (pinned && items.filter(item => item.pinned).length >= CLIPBOARD_MAX_PINS)
        return items.slice();
    return items.map(item => {
        if (item !== target)
            return item;
        const copy = { ...item };
        if (pinned)
            copy.pinned = true;
        else
            delete copy.pinned;
        return copy;
    });
}

// "Clear history" forgets what was copied; what you pinned on purpose stays.
function clipboardClear(items) {
    return items.filter(item => item.pinned);
}

// Width and height from a PNG's header, or null if the bytes are not a PNG.
// bytes: anything indexable holding the first 24 bytes of the file.
function pngSize(bytes) {
    const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    if (!bytes || bytes.length < 24 || signature.some((b, i) => bytes[i] !== b))
        return null;
    const u32 = at => ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0;
    return { width: u32(16), height: u32(20) };
}

// "1.2 MB", "340 KB", "912 B"
function formatBytes(size) {
    if (size >= 1024 * 1024)
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    if (size >= 1024)
        return `${Math.round(size / 1024)} KB`;
    return `${size} B`;
}

// ------------------------------------------------------ drop-down terminal

var DROPDOWN_ROLE = 'adaptive-dropdown';
const DROPDOWN_DEFAULT_HEIGHT = 0.45;

// Which terminal to use: the one asked for if it is installed, otherwise
// Terminator, otherwise GNOME Terminal. '' if there is none.
function dropdownTerminalKind(wanted, isInstalled) {
    const known = ['terminator', 'gnome-terminal'];
    if (known.includes(wanted) && isInstalled(wanted))
        return wanted;
    return known.find(isInstalled) || '';
}

// The command that opens the terminal in folder, carrying our window role
// (X11) so it can be found again after the shell restarts.
function dropdownArgv(kind, folder) {
    if (kind === 'terminator') {
        return ['terminator', '--borderless', `--role=${DROPDOWN_ROLE}`,
            `--working-directory=${folder}`];
    }
    return ['gnome-terminal', `--role=${DROPDOWN_ROLE}`, `--working-directory=${folder}`];
}

// Whether a window that has just appeared is the terminal we started. The
// role says so on X11; on Wayland there is no role, and the class has to do.
function isDropdownWindow(kind, wmClass, role) {
    if (role === DROPDOWN_ROLE)
        return true;
    if (role)
        return false;
    const name = String(wmClass || '').toLowerCase();
    return kind === 'terminator' ? name.includes('terminator') : name.includes('gnome-terminal');
}

// Across the top of the work area: full width, a fraction of its height.
function dropdownRect(area, fraction) {
    let share = Number(fraction);
    if (!Number.isFinite(share) || share < 0.2 || share > 1)
        share = DROPDOWN_DEFAULT_HEIGHT;
    return {
        x: area.x,
        y: area.y,
        width: area.width,
        height: Math.max(120, Math.round(area.height * share)),
    };
}
