// Adaptive Shell - Cast's state, for the Control Center tile and the island.
//
// apps/adaptive-cast publishes $XDG_RUNTIME_DIR/adaptive-cast.json on every
// change. This watches that one file and runs the Cast launcher for commands,
// so the shell never talks to a TV itself. One watcher is shared: acquire()
// it, connect('changed', fn) like a GObject, and release() when done.

/* exported acquire, release, isActive, ACTIVE_STATES */

const { Gio, GLib } = imports.gi;
const Me = imports.misc.extensionUtils.getCurrentExtension();
const AdaptivePaths = Me.imports.adaptivePaths;
const CC = Me.imports.ccUtil;

var ACTIVE_STATES = ['preparing', 'connecting', 'negotiating', 'streaming', 'reconnecting'];

function isActive(state) {
    return !!state && ACTIVE_STATES.includes(state.state);
}

class CastStatus {
    constructor() {
        this._path = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'adaptive-cast.json']);
        this._handlers = new Map();
        this._nextId = 1;
        this._state = null;
        this._monitor = Gio.File.new_for_path(this._path)
            .monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, null);
        this._monitorId = this._monitor.connect('changed', () => this._read());
        this._read();
    }

    get state() {
        return this._state;
    }

    _read() {
        let data = null;
        try {
            const [ok, bytes] = GLib.file_get_contents(this._path);
            data = ok ? JSON.parse(new TextDecoder().decode(bytes)) : null;
        } catch (e) {
            data = null;
        }
        // A Cast that crashed leaves its last state behind.
        if (data && data.pid && !GLib.file_test(`/proc/${data.pid}`, GLib.FileTest.EXISTS))
            data = null;
        if (JSON.stringify(data) === JSON.stringify(this._state))
            return;
        this._state = data;
        for (const callback of this._handlers.values()) {
            try {
                callback(this, data);
            } catch (e) {
                logError(e, '[Adaptive Shell] cast status listener');
            }
        }
    }

    connect(_signal, callback) {
        const id = this._nextId++;
        this._handlers.set(id, callback);
        return id;
    }

    disconnect(id) {
        this._handlers.delete(id);
    }

    // Commands go to the running Cast (it starts one if none is running).
    // The action script returns at once; Cast itself runs as long as it casts.
    run(...args) {
        const launcher = GLib.build_filenamev([AdaptivePaths.adaptiveDir(), 'scripts',
            'adaptive-cast-action.sh']);
        CC.run([launcher, ...args], () => {});
    }

    toggle() {
        this.run('--toggle');
    }

    stop() {
        this.run('--stop');
    }

    open() {
        this.run();
    }

    freeze(on) {
        this.run(on ? '--freeze' : '--resume');
    }

    curtain(on) {
        this.run(...(on ? ['--curtain'] : ['--resume']));
    }

    destroy() {
        if (this._monitor) {
            this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
            this._monitor = null;
        }
        this._handlers.clear();
    }
}

let _shared = null;
let _users = 0;

function acquire() {
    if (!_shared)
        _shared = new CastStatus();
    _users++;
    return _shared;
}

function release() {
    _users = Math.max(0, _users - 1);
    if (_users === 0 && _shared) {
        _shared.destroy();
        _shared = null;
    }
}
