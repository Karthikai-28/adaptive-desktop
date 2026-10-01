// Adaptive crash watchdog.
//
// If the desktop is built three times inside ten minutes without once staying
// up five minutes, something in it is taking the shell down, and building it
// a fourth time would only repeat that. So the extension stands down: no dock,
// no panels, stock GNOME, and a notification saying why. Adaptive Settings
// (Updates & Recovery) shows the state and re-arms it.
//
// A clean disable (logout, turning the extension off) and a planned restart
// (scripts/reload-adaptive-shell.sh) clear the record, so ordinary use and
// development never count against it. The rule itself is
// adaptiveUtil.watchdogVerdict, checked by scripts/verify-shell-helpers.js.
//
// State: ~/.cache/adaptive-desktop/shell-watchdog.json

/* exported recordStart, markHealthy, healthyAfterSeconds */

const { GLib } = imports.gi;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Util = Me.imports.adaptiveUtil;

const STATE_PATH = GLib.build_filenamev(
    [GLib.get_user_cache_dir(), 'adaptive-desktop', 'shell-watchdog.json']);

function read() {
    try {
        const [ok, bytes] = GLib.file_get_contents(STATE_PATH);
        return ok ? JSON.parse(new TextDecoder().decode(bytes)) : {};
    } catch (e) {
        return {};
    }
}

function write(state) {
    try {
        GLib.mkdir_with_parents(GLib.path_get_dirname(STATE_PATH), 0o755);
        GLib.file_set_contents(STATE_PATH, `${JSON.stringify(state)}\n`);
    } catch (e) {
        logError(e, '[Adaptive Watchdog] saving state');
    }
}

// Call as the desktop is about to be built. True means: do not build it.
function recordStart() {
    const now = Math.floor(GLib.get_real_time() / 1e6);
    const verdict = Util.watchdogVerdict(read(), now);
    write(verdict.state);
    return verdict.tripped;
}

// The desktop has stayed up, or is being taken down on purpose.
function markHealthy() {
    const state = read();
    if (state.tripped)
        return;
    write({ starts: [], tripped: false });
}

function healthyAfterSeconds() {
    return Util.WATCHDOG.HEALTHY_AFTER_S;
}
