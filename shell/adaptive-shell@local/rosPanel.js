// Adaptive ROS 2 panel
//
// A top-bar indicator just left of Network: the ROS 2 graph this computer
// sees (nodes, topics, services, actions, ros2_control controllers, TF, its
// health) and the tools used with it (RViz2, Gazebo, rqt, launch files,
// rosbag, a terminal on the same setup).
//
// tools/ros_info.py does all the ROS work; the shell never loads ROS.
// `status` (the setup, installed and running tools, files, saved setups and
// launches) runs each time the panel opens. `watch` keeps one hidden rclpy
// node while the panel is open, and a minute after it closes (polling slower
// then): it prints the graph whenever it changes and answers what an expanded
// row asks for. `runs` is polled while something the panel started runs, so
// a crash or a finished recording reaches the Dynamic Island even when the
// panel is closed. Whatever writes to ROS takes a second, confirming click.
// docs/ROS2_PANEL.md has the whole picture.

/* exported RosPanel */

const { Clutter, Gio, GLib, GObject, Pango, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CC = Me.imports.ccUtil;
const Sparkline = Me.imports.sparkline;

const HELPER = Me.dir.get_child('tools').get_child('ros_info.py').get_path();
const LIST_MAX_HEIGHT = 680;
const KEEP_WATCHING_S = 60;
const STOP_GRACE_MS = 2000;
const COPIED_MS = 1100;
const REQUEST_REPLY_TIMEOUT_MS = 7000;
// A call may wait 10 s for its service, a goal 30 s for its result.
const CALL_REPLY_TIMEOUT_MS = 15000;
const GOAL_REPLY_TIMEOUT_MS = 40000;
// The helper ends a plot after ten minutes; this only catches a lost reply.
const PLOT_REPLY_TIMEOUT_MS = 610000;
const PLOT_SAMPLES = 120;
const LOG_LINES = 60;
const PLOT_ACCENT = '#0A84FF';
const ARM_MS = 5000;
const RUNS_POLL_S = 5;
const PAGE_ROWS = 40;
const STATUS_FOLLOW_MS = 3000;
const TF_ROWS = 200;
const CRASH_SHOWN_S = 24 * 3600;
const SOURCE_HINTS = { panel: 'set here', default: 'default', project: 'from the active project' };
const LIFECYCLE_CLASSES = {
    active: 'adaptive-network-good',
    inactive: 'adaptive-network-warn',
    unconfigured: 'adaptive-network-warn',
    finalized: 'adaptive-network-bad',
};
const LIFECYCLE_NEXT = {
    unconfigured: ['configure'],
    inactive: ['activate', 'cleanup'],
    active: ['deactivate'],
};
const CONTROLLER_NEXT = { unconfigured: 'configure', inactive: 'activate', active: 'deactivate' };
// Tools with a window: once one opens, the menu gets out of its way.
const WINDOWED = new Set(['rviz2', 'gazebo', 'rqt', 'rqt_graph', 'plotjuggler']);
const TOOL_NAMES = {
    rviz2: 'RViz2', gazebo: 'Gazebo', rqt: 'rqt', rqt_graph: 'rqt_graph',
    demo: 'The demo', launch: 'Launch', bag: 'Rosbag', node: 'Node', build: 'Build', plot: 'rqt_plot',
    plotjuggler: 'PlotJuggler',
};
const PAUSABLE = new Set(['build', 'launch', 'node']);
// Sections a search unfolds, so what matches is seen, not only counted.
const SEARCHED = new Set(['nodes', 'topics', 'services', 'actions']);
const GROUP_TRANSITIONS = ['configure', 'activate', 'deactivate', 'cleanup'];
// rcl_interfaces ParameterType: 5 to 9 are the arrays (5 of bytes).
const PARAMETER_ARRAY = new Set([5, 6, 7, 8, 9]);

function copy(text) {
    St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
}

function plural(count, one, many = `${one}s`) {
    return `${count} ${count === 1 ? one : many}`;
}

// "/a", "/a and /b", "/a, /b and 3 more".
function names(list) {
    if (list.length <= 2)
        return list.join(' and ');
    return `${list.slice(0, 2).join(', ')} and ${list.length - 2} more`;
}

function bytes(count) {
    if (count < 1024)
        return `${Math.round(count)} B`;
    if (count < 1024 * 1024)
        return `${(count / 1024).toFixed(1)} KB`;
    if (count < 1024 * 1024 * 1024)
        return `${(count / 1024 / 1024).toFixed(1)} MB`;
    return `${(count / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function seconds(total) {
    total = Math.max(0, Math.round(total));
    if (total < 60)
        return `${total} s`;
    const minutes = Math.floor(total / 60);
    if (minutes < 60)
        return `${minutes}:${String(total % 60).padStart(2, '0')}`;
    return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function ago(epochSeconds) {
    const passed = Date.now() / 1000 - epochSeconds;
    if (passed < 60)
        return 'just now';
    if (passed < 3600)
        return `${Math.floor(passed / 60)} min ago`;
    return `${Math.floor(passed / 3600)} h ago`;
}

function rateText(rate) {
    if (!rate.count)
        return `No messages in ${rate.window} s`;
    if (rate.count === 1)
        return `1 message in ${rate.window} s`;
    return `${rate.hz.toFixed(rate.hz < 10 ? 2 : 1)} Hz · ${bytes(rate.bytes_per_s)}/s · ${bytes(rate.size)} each`;
}

function valueText(value) {
    if (value === null || value === undefined)
        return 'not set';
    const text = Array.isArray(value) ? `[${value.join(', ')}]` : String(value);
    return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

// A parameter as it is typed back: strings bare, the rest as JSON.
function draftText(value) {
    return typeof value === 'string' ? value : JSON.stringify(value);
}

function title(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

// One block of the list, which asks for its whole height as its minimum too.
// A scrolled St list lays its children out at their minimum heights once it is
// taller than the dropdown, and that squeezed whatever can shrink: wrapped text
// to its first line, a dropdown's choices (the plot's field list) to nothing.
const Block = GObject.registerClass(class AdaptiveRosBlock extends St.BoxLayout {
    vfunc_get_preferred_height(forWidth) {
        const [, natural] = super.vfunc_get_preferred_height(forWidth);
        return [natural, natural];
    }
});

// Text that keeps every line. St.Label ellipsizes by default, and a wrapped,
// ellipsized label asks for one line only, so the scrolled list squeezed a
// reply or a preview to its first line and drew the rest over its neighbours.
function wrapped(label) {
    label.clutter_text.line_wrap = true;
    label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    return label;
}

// A saved launch's name from its file and arguments, in what a name may hold.
function launchName(file, args) {
    const stem = GLib.path_get_basename(file).replace(/\.launch\.(py|xml|yaml)$/, '');
    const text = [stem, ...args].join(' ').replace(/[^\w .:+-]/g, '-');
    return text.slice(0, 40).trim() || 'launch';
}

var RosPanel = class RosPanel {
    constructor() {
        this._button = null;
        this._icon = null;
        this._openStateId = 0;
        this._sessionId = 0;
        this._stopId = 0;
        this._scrollId = 0;
        this._renderId = 0;
        this._renderPending = false;
        this._armId = 0;
        this._runsId = 0;
        this._followId = 0;
        this._statusAt = 0;
        // The graph's node names, to notice processes coming and going.
        this._nodesKey = null;
        this._status = null;
        this._graph = null;
        this._graphVersion = 0;
        // The running `watch`: { proc, stdin, lines, cancellable }.
        this._watch = null;
        this._watchSetup = '';
        this._watchError = '';
        this._nextId = 1;
        this._pending = new Map();
        // What is unfolded: 'section:topics', 'node:/talker', 'iface:<where>:<type>'.
        this._expanded = new Set(['section:nodes']);
        // Replies for expanded rows: 'node:/x' and 'topic:/x' -> { busy, data, error }.
        this._details = new Map();
        // Type -> { busy, data, error }; topic -> { busy, data, error }.
        this._interfaces = new Map();
        this._rates = new Map();
        this._samples = new Map();
        this._tf = null;
        this._health = null;
        // 'call:/x', 'goal:/x', 'publish:/x' -> { text, busy, reply }.
        this._composers = new Map();
        this._quickCalls = new Map();     // service name -> { busy, reply }: one-tap calls
        this._plotTopics = new Set();     // topics picked to open together in PlotJuggler
        // Section -> how many rows it shows.
        this._pages = new Map();
        // The list is rebuilt in blocks; one whose inputs did not change is kept.
        this._blocks = new Map();
        this._out = null;
        // Tool (or 'setup', 'bag', 'op:/node') -> { text, error }.
        this._notes = {};
        this._domainDraft = null;
        this._setupDraft = null;
        this._launchDraft = null;
        this._parameterDraft = null;
        this._paramProfileDraft = null;
        // A parameter profile compared with the running node before applying.
        this._paramDiff = null;
        this._profileDraft = null;
        // A run's log, filtered, under Running from here: { tool, query, severity, text }.
        this._logView = null;
        this._bagDraft = null;
        // Topics ticked for the next recording; null records what the list shows.
        this._bagTopics = null;
        this._tfLookup = null;
        this._plotDraft = null;
        // The live plot: { topic, field, values, id }; its strip is redrawn in place.
        this._plot = null;
        this._lifecycleSelection = new Set();
        this._lifecycleResult = null;
        // The focused graph view: { kind, name, back: [...] }.
        this._focus = null;
        this._scrollToBlock = null;     // a block just opened (plot, graph view): scroll to it
        this._keptScroll = null;        // the position a pending scroll restore puts back
        this._searchText = '';
        // Sections folded by hand during this search.
        this._searchFolded = new Set();
        // Per-package builds also build what the package depends on.
        this._buildUpTo = false;
        // The one write waiting for its confirming click: { key, until }.
        this._armed = null;
        // From `runs`: what the panel started that runs, and how runs ended.
        this._runs = null;
        this._seenEnds = new Set();
        this._dismissed = new Set();
        this._diagnosticSignature = '';
        this._presentFavorites = null;
        this._attachedAt = Date.now() / 1000;
    }

    attach() {
        try {
            this._attach();
        } catch (e) {
            try {
                this.detach();
            } catch (cleanupError) {
                logError(cleanupError, '[Adaptive ROS] cleaning up failed attach');
            }
            throw e;
        }
    }

    _attach() {
        this._button = new PanelMenu.Button(0.5, 'ROS 2', false);
        this._icon = new St.Icon({
            gicon: CC.extensionIcon('ros-symbolic'),
            style_class: 'system-status-icon',
        });
        this._button.add_child(this._icon);

        this._button.menu.box.add_style_class_name('adaptive-cc-menu');
        const root = new St.BoxLayout({
            style_class: 'adaptive-cc adaptive-ros',
            vertical: true,
            x_expand: true,
        });
        this._button.menu.box.add_child(root);

        const header = new St.BoxLayout({ style_class: 'adaptive-usb-header', x_expand: true });
        header.add_child(new St.Label({
            text: 'ROS 2',
            style_class: 'adaptive-usb-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        }));
        this._summary = new St.Label({
            style_class: 'adaptive-usb-summary',
            y_align: Clutter.ActorAlign.CENTER,
        });
        header.add_child(this._summary);
        root.add_child(header);

        this._search = new St.Entry({
            style_class: 'adaptive-cc-entry adaptive-ros-search',
            hint_text: 'Search nodes, topics, services, actions and types',
            can_focus: true,
            x_expand: true,
        });
        this._search.clutter_text.connect('text-changed', () => {
            this._searchText = this._search.get_text().trim().toLowerCase();
            this._searchFolded.clear();
            this._render();
        });
        // Escape clears a search first; with none it closes the menu as usual.
        this._search.clutter_text.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() !== Clutter.KEY_Escape || !this._search.get_text())
                return Clutter.EVENT_PROPAGATE;
            this._search.set_text('');
            return Clutter.EVENT_STOP;
        });
        root.add_child(this._search);

        this._scroll = new St.ScrollView({
            style_class: 'adaptive-cc-scroll vfade',
            overlay_scrollbars: true,
            x_expand: true,
        });
        this._scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        this._list = new St.BoxLayout({
            style_class: 'adaptive-cc-list',
            vertical: true,
            x_expand: true,
        });
        this._scroll.add_actor(this._list);
        root.add_child(this._scroll);
        // Below the list, so it stays in view however far the list is scrolled:
        // the topics picked for PlotJuggler, and Open.
        this._footer = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-footer' });
        root.add_child(this._footer);

        // Just left of Network (or of whatever is leftmost of ours).
        const rightBox = Main.panel._rightBox;
        const neighbour = Main.panel.statusArea['adaptive-network'] ||
            Main.panel.statusArea['adaptive-tasks'] || Main.panel.statusArea['adaptive-usb'] ||
            Main.panel.statusArea.aggregateMenu;
        const index = neighbour ? Math.max(0, rightBox.get_children().indexOf(neighbour.container)) : 0;
        Main.panel.addToStatusArea('adaptive-ros', this._button, index, 'right');

        this._openStateId = this._button.menu.connect('open-state-changed', (_m, open) => {
            if (open) {
                this._cancelStop();
                this._setWatchMode(true);
                this._loadStatus(() => this._startWatch());
                this._render();
            } else {
                this._domainDraft = null;
                this._setupDraft = null;
                this._launchDraft = null;
                this._parameterDraft = null;
                this._paramProfileDraft = null;
                this._paramDiff = null;
                this._profileDraft = null;
                this._bagDraft = null;
                this._stopPlot();
                this._disarm();
                this._scrollToBlock = null;
                this._setWatchMode(false);
                this._scheduleStop();
            }
        });
        this._sessionId = Main.sessionMode.connect('updated', () => this._syncSession());
        this._syncSession();
        // A recording or a launch from before a shell restart is picked up.
        this._pollRuns();
        log('[Adaptive ROS] panel indicator installed');
    }

    detach() {
        if (this._sessionId) {
            Main.sessionMode.disconnect(this._sessionId);
            this._sessionId = 0;
        }
        this._cancelStop();
        for (const id of ['_scrollId', '_renderId', '_armId', '_runsId', '_followId']) {
            if (this[id]) {
                GLib.source_remove(this[id]);
                this[id] = 0;
            }
        }
        this._stopWatch();
        this._blocks.clear();
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    _syncSession() {
        if (this._button)
            this._button.container.visible = !Main.sessionMode.isLocked && !Main.sessionMode.isGreeter;
    }

    // The top-bar icon: red while recording, orange while /diagnostics errs.
    _syncIndicator() {
        if (!this._icon)
            return;
        const recording = !!(this._runs && this._runs.recording);
        const backend = Main._dynamicIsland && Main._dynamicIsland.backend;
        if (backend && backend.setRosRecording)
            backend.setRosRecording(recording ? this._runs.recording : null);
        const alarmed = this._diagnosticSignature && this._diagnosticSignature !== '[]';
        this._icon.remove_style_class_name('adaptive-ros-recording');
        this._icon.remove_style_class_name('adaptive-ros-attention');
        if (recording)
            this._icon.add_style_class_name('adaptive-ros-recording');
        else if (alarmed)
            this._icon.add_style_class_name('adaptive-ros-attention');
    }

    // ------------------------------------------------------- one-shot helper

    _helper(args, done) {
        try {
            const proc = Gio.Subprocess.new(['/usr/bin/python3', HELPER, ...args],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            proc.communicate_utf8_async(null, null, (p, result) => {
                let data = null;
                try {
                    const [, stdout] = p.communicate_utf8_finish(result);
                    data = JSON.parse(stdout);
                } catch (e) {
                    logError(e, `[Adaptive ROS] ${args[0]}`);
                }
                if (this._button)
                    done(data || { ok: false, error: 'The ROS helper failed' });
            });
        } catch (e) {
            logError(e, '[Adaptive ROS] helper');
            done({ ok: false, error: 'The ROS helper did not start' });
        }
    }

    _loadStatus(then = null, refresh = false) {
        this._helper(refresh ? ['status', 'refresh'] : ['status'], data => {
            if (data && data.installed !== undefined)
                this._status = data;
            // ~/.zshrc, ~/.bashrc or ros2.json changed while the watcher kept running.
            if (this._watch && this._setupKey() !== this._watchSetup)
                this._restartWatch();
            if (then)
                then();
            this._queueRender();
        });
    }

    _set(key, value) {
        this._setMany([key, value]);
    }

    _setMany(pairs) {
        this._applySetup(['set', ...pairs]);
    }

    // Anything that changes the setup answers with the whole new status.
    _applySetup(args) {
        this._helper(args, reply => {
            if (reply.ok) {
                this._status = reply;
                this._notes.setup = null;
                this._restartWatch();
            } else {
                this._notes.setup = { text: reply.error, error: true };
            }
            this._render();
        });
    }

    _launch(tool, file = null, args = []) {
        this._notes[tool] = { text: 'Starting…' };
        this._render();
        this._helper(['launch', tool, ...(file ? [file, ...args] : [])], reply => this._started(tool, reply));
    }

    _launchSaved(name) {
        this._notes.launch = { text: `Starting ${name}…` };
        this._render();
        this._helper(['launch-saved', name], reply => this._started('launch', reply));
    }

    _started(tool, reply) {
        this._notes[tool] = reply.ok ? null : { text: reply.error, error: true };
        if (reply.ok && WINDOWED.has(tool))
            this._button.menu.close();
        this._loadStatus();
        this._pollRuns();
    }

    _stop(tool) {
        this._notes[tool] = { text: 'Stopping…' };
        this._render();
        this._helper(['stop', tool], () => {
            this._notes[tool] = null;
            this._loadStatus();
            this._pollRuns();
        });
    }

    // The windows of a running tool, found by the processes `status` saw.
    _show(tool) {
        const pids = this._status.tools[tool].pids;
        const window = global.get_window_actors()
            .map(actor => actor.meta_window)
            .find(w => pids.includes(w.get_pid()));
        if (window) {
            Main.activateWindow(window);
            this._button.menu.close();
        } else {
            this._notes[tool] = { text: 'Running, but its window is not open yet' };
            this._render();
        }
    }

    // A terminal of the helper's: the ROS terminal, the Gazebo install, a log.
    _terminal(...args) {
        this._button.menu.close();
        this._helper(args, reply => {
            if (!reply.ok)
                Main.notify('ROS 2', reply.error);
        });
    }

    _openFolder(path) {
        try {
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(path, null), null);
            this._button.menu.close();
        } catch (e) {
            logError(e, '[Adaptive ROS] opening a folder');
        }
    }

    // ---------------------------------------------------------------- runs

    // `runs` while something started here runs: crashes and recordings are
    // noticed with the panel closed too.
    _pollRuns() {
        if (this._runsId) {
            GLib.source_remove(this._runsId);
            this._runsId = 0;
        }
        this._helper(['runs'], reply => {
            if (!reply.ok)
                return;
            const before = this._runs;
            this._runs = reply;
            this._noticeRuns(before, reply);
            if (this._logView && this._button.menu.isOpen)
                this._loadLogView(true);
            this._syncIndicator();
            const running = Object.values(reply.running || {}).some(list => list.length);
            if (running) {
                this._runsId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, RUNS_POLL_S, () => {
                    this._runsId = 0;
                    this._pollRuns();
                    return GLib.SOURCE_REMOVE;
                });
            }
            // Something ended or started while open: the tool rows follow.
            const pgids = runs => JSON.stringify(Object.values((runs && runs.running) || {})
                .flat().map(entry => entry.pgid).sort());
            if (this._button.menu.isOpen && pgids(before) !== pgids(reply))
                this._loadStatus();
            else
                this._queueRender();
        });
    }

    _noticeRuns(before, now) {
        for (const entry of now.history || []) {
            const key = `${entry.pgid}:${entry.ended}`;
            if (this._seenEnds.has(key))
                continue;
            this._seenEnds.add(key);
            if (entry.crashed && entry.ended > this._attachedAt) {
                const name = (entry.meta && entry.meta.name) || TOOL_NAMES[entry.tool] || entry.tool;
                this._island('ROS_RUN_FAILED', 1, `${name} exited with code ${entry.returncode}`, '⚠');
            }
        }
        const was = before && before.recording;
        const is = now.recording;
        if (!was && is && before)
            this._island('ROS_RECORDING', 3, `Recording ${this._recordingTopics(is)}`, '●');
        else if (was && !is)
            this._island('ROS_RECORDING', 3, `Recording saved · ${bytes(was.size || 0)}`, '●');
    }

    _recordingTopics(recording) {
        return recording.topics === 'all' ? 'every topic' : plural(recording.topics || 0, 'topic');
    }

    // The Dynamic Island when it is there, a notification for what matters
    // otherwise. The island hides the text while the screen is shared.
    _island(type, priority, message, icon = '✦', data = {}) {
        const island = Main._dynamicIsland;
        if (island && island.backend && island.backend.emitEvent) {
            island.backend.emitEvent(type, {
                provider: 'ros', priority, dwellMs: priority === 1 ? -1 : 4000,
                title: 'ROS 2', message, icon, data,
            });
        } else if (priority <= 2) {
            Main.notify('ROS 2', message);
        }
    }

    // --------------------------------------------------------------- watch

    _startWatch() {
        if (this._watch || !this._status || !this._status.installed)
            return;
        let proc;
        try {
            proc = Gio.Subprocess.new(['/usr/bin/python3', HELPER, 'watch'],
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE |
                Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (e) {
            logError(e, '[Adaptive ROS] watch');
            this._watchError = 'The ROS helper did not start';
            return;
        }
        const watch = {
            proc,
            stdin: proc.get_stdin_pipe(),
            lines: new Gio.DataInputStream({ base_stream: proc.get_stdout_pipe(), close_base_stream: true }),
            cancellable: new Gio.Cancellable(),
        };
        this._watch = watch;
        this._watchSetup = this._setupKey();
        this._watchError = '';
        this._forgetGraph();
        this._readLine(watch);
    }

    // Everything learned from one watcher; a new one asks again.
    _forgetGraph() {
        this._graph = null;
        this._details.clear();
        this._rates.clear();
        this._samples.clear();
        this._tf = null;
        this._tfLookup = null;
        this._health = null;
        this._stopPlot();
        this._lifecycleResult = null;
        this._presentFavorites = null;
        this._nodesKey = null;
        for (const composer of this._composers.values())
            composer.busy = false;
    }

    // What the watcher's view depends on; a change means starting it again.
    _setupKey() {
        const s = this._status || {};
        return JSON.stringify([s.distro, s.domain, s.localhost, s.rmw, s.workspace]);
    }

    _readLine(watch) {
        watch.lines.read_line_async(GLib.PRIORITY_DEFAULT, watch.cancellable, (stream, result) => {
            let line = null;
            try {
                [line] = stream.read_line_finish_utf8(result);
            } catch (e) {
                if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    logError(e, '[Adaptive ROS] reading the graph');
            }
            if (this._watch !== watch)
                return;
            if (line === null) {
                this._watchEnded();
                return;
            }
            this._onMessage(line);
            this._readLine(watch);
        });
    }

    _onMessage(line) {
        let message;
        try {
            message = JSON.parse(line);
        } catch (e) {
            return;
        }
        if (message.type === 'graph') {
            this._graph = message;
            this._graphVersion++;
            this._notifyDiagnosticChange(message.diagnostics);
            this._notifyLostFavorites(message);
            this._fetchExpandedDetails();
            this._followNodes(message);
            this._queueRender();
        } else if (message.type === 'reply') {
            const pending = this._pending.get(message.id);
            this._pending.delete(message.id);
            if (pending) {
                if (pending.timeoutId)
                    GLib.source_remove(pending.timeoutId);
                pending.done(message);
            }
        } else if (message.type === 'progress') {
            const pending = this._pending.get(message.id);
            if (pending && pending.progress)
                pending.progress(message);
        } else if (message.type === 'error') {
            this._watchError = message.error;
            this._render();
        }
    }

    // Nodes come and go with the processes that run them (an RViz opened in
    // a terminal, a demo stopped elsewhere), so the tool rows are read again
    // when the node names change; not more than every few seconds.
    _followNodes(graph) {
        const key = graph.nodes.map(node => node.name).join('\n');
        if (key === this._nodesKey)
            return;
        const first = this._nodesKey === null;
        this._nodesKey = key;
        if (first || this._followId || !this._button.menu.isOpen)
            return;
        // The last change in a burst is the one that counts, so wait it out.
        const wait = Math.max(0, this._statusAt + STATUS_FOLLOW_MS - Date.now());
        this._followId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, wait, () => {
            this._followId = 0;
            this._statusAt = Date.now();
            this._loadStatus();
            return GLib.SOURCE_REMOVE;
        });
    }

    // The watcher exited by itself: say so, and fail what was waiting on it.
    _watchEnded() {
        this._watch = null;
        if (!this._watchError)
            this._watchError = 'The ROS helper stopped';
        this._failPending();
        this._render();
    }

    _failPending() {
        const pending = [...this._pending.values()];
        this._pending.clear();
        for (const item of pending) {
            if (item.timeoutId)
                GLib.source_remove(item.timeoutId);
            item.done({ error: 'The ROS helper stopped' });
        }
    }

    // Closing stdin is how the watcher is asked to quit; it is killed if it
    // has not after a moment.
    _stopWatch() {
        const watch = this._watch;
        if (!watch)
            return;
        this._watch = null;
        this._failPending();
        watch.cancellable.cancel();
        try {
            watch.stdin.close(null);
        } catch (e) {
            // Already gone.
        }
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, STOP_GRACE_MS, () => {
            if (watch.proc.get_identifier())
                watch.proc.force_exit();
            return GLib.SOURCE_REMOVE;
        });
    }

    _restartWatch() {
        this._stopWatch();
        this._watchError = '';
        this._forgetGraph();
        this._interfaces.clear();
        this._startWatch();
    }

    _scheduleStop() {
        this._cancelStop();
        this._stopId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, KEEP_WATCHING_S, () => {
            this._stopId = 0;
            this._stopWatch();
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancelStop() {
        if (this._stopId) {
            GLib.source_remove(this._stopId);
            this._stopId = 0;
        }
    }

    _request(cmd, fields, done, timeoutMs = REQUEST_REPLY_TIMEOUT_MS, progress = null) {
        if (!this._watch) {
            done({ error: 'ROS 2 is not being watched' });
            return 0;
        }
        const id = this._nextId++;
        const pending = { done, cmd, fields, progress, timeoutId: 0 };
        pending.timeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, timeoutMs, () => {
            if (this._pending.get(id) === pending) {
                this._pending.delete(id);
                done({ error: 'The ROS helper did not answer in time' });
            }
            return GLib.SOURCE_REMOVE;
        });
        this._pending.set(id, pending);
        try {
            const text = `${JSON.stringify({ id, cmd, ...fields })}\n`;
            this._watch.stdin.write_all(new TextEncoder().encode(text), null);
        } catch (e) {
            this._pending.delete(id);
            GLib.source_remove(pending.timeoutId);
            done({ error: 'The ROS helper stopped' });
        }
        return id;
    }

    _setWatchMode(active) {
        if (!this._watch)
            return;
        this._request('mode', { active }, () => {});
    }

    _fetchExpandedDetails() {
        if (!this._graph)
            return;
        for (const node of this._graph.nodes || []) {
            const key = `node:${node.name}`;
            if (this._expanded.has(key) && !this._details.has(key))
                this._fetchNode(node);
        }
        for (const topic of this._graph.topics || []) {
            const key = `topic:${topic.name}`;
            if (this._expanded.has(key) && !this._details.has(key))
                this._fetch(this._details, key, 'topic', { name: topic.name });
        }
        if (this._expanded.has('section:health'))
            this._fetchHealth();
    }

    // Asks for `key`'s details once per unfolding; the reply lands in `map`.
    _fetch(map, key, cmd, fields, timeoutMs = REQUEST_REPLY_TIMEOUT_MS) {
        map.set(key, { busy: true });
        this._request(cmd, fields, reply => {
            map.set(key, { busy: false, data: reply.error ? null : reply, error: reply.error || '' });
            this._queueRender();
        }, timeoutMs);
    }

    _toggle(key, onOpen = null) {
        if (this._expanded.has(key)) {
            this._expanded.delete(key);
            const ids = [];
            for (const [id, request] of this._pending) {
                if (!['hz', 'sample'].includes(request.cmd)) continue;
                // A parent section/node can contain any of the measured topics.
                if (key.startsWith('section:') || key.startsWith('node:') || key === `topic:${request.fields.name}`) {
                    ids.push(id);
                    GLib.source_remove(request.timeoutId);
                    this._pending.delete(id);
                    (request.cmd === 'hz' ? this._rates : this._samples).delete(request.fields.name);
                }
            }
            if (ids.length) this._request('cancel', { ids }, () => {});
        } else {
            this._expanded.add(key);
            if (onOpen)
                onOpen();
        }
        this._render();
    }

    _toggleInterface(where, type) {
        this._toggle(`iface:${where}:${type}`, () => {
            const known = this._interfaces.get(type);
            if (!known || known.error)
                this._fetch(this._interfaces, type, 'interface', { type });
        });
    }

    _measure(topic) {
        const rate = this._rates.get(topic);
        if (!(rate && rate.busy))
            this._fetch(this._rates, topic, 'hz', { name: topic });
        this._render();
    }

    _sample(topic) {
        const sample = this._samples.get(topic);
        if (sample && !sample.busy && (sample.data || sample.error)) {
            // A second click folds the preview away.
            this._samples.delete(topic);
        } else if (!(sample && sample.busy)) {
            this._fetch(this._samples, topic, 'sample', { name: topic });
        }
        this._render();
    }

    _fetchTf() {
        this._tf = { busy: true };
        this._request('tf', {}, reply => {
            this._tf = { busy: false, data: reply.error ? null : reply, error: reply.error || '' };
            this._queueRender();
        });
        this._render();
    }

    // QoS mismatches need every topic's endpoints, so they are asked for only
    // while Health is unfolded, once per graph.
    _fetchHealth() {
        if (!this._watch || (this._health && (this._health.busy || this._health.version === this._graphVersion)))
            return;
        const version = this._graphVersion;
        this._health = { ...(this._health || {}), busy: true, version };
        this._request('health', {}, reply => {
            this._health = { busy: false, version, data: reply.error ? null : reply, error: reply.error || '' };
            this._queueRender();
        });
    }

    _notifyDiagnosticChange(diagnostics) {
        const bad = (diagnostics && diagnostics.items || []).filter(item => item.level >= 2);
        const signature = JSON.stringify(bad.map(item => [item.name, item.level, item.message]));
        const changed = signature !== this._diagnosticSignature;
        this._diagnosticSignature = signature;
        this._syncIndicator();
        if (!changed || !bad.length)
            return;
        const worst = bad[0];
        this._island('ROS_DIAGNOSTIC_ERROR', 1, `${worst.name}: ${worst.message || 'Error'}`, '⚠',
            { count: bad.length, level: worst.level });
    }

    // A starred node that leaves the graph is worth knowing about.
    _notifyLostFavorites(graph) {
        const starred = (this._status && this._status.favorites || []).filter(item => item.kind === 'node');
        const present = new Set(graph.nodes.map(node => node.name));
        const now = new Set(starred.filter(item => present.has(item.name)).map(item => item.name));
        if (this._presentFavorites) {
            for (const name of this._presentFavorites) {
                if (!now.has(name) && starred.some(item => item.name === name))
                    this._island('ROS_NODE_LOST', 2, `${name} left the ROS graph`, '⚠');
            }
        }
        this._presentFavorites = now;
    }

    _isFavorite(kind, name) {
        return !!(this._status && (this._status.favorites || [])
            .some(item => item.kind === kind && item.name === name));
    }

    _toggleFavorite(kind, name) {
        this._helper(['favorite', kind, name], reply => {
            if (reply.ok && this._status) {
                this._status.favorites = reply.favorites;
                if (this._graph)
                    this._presentFavorites = null;
            } else if (!reply.ok) {
                this._notes.setup = { text: reply.error, error: true };
            }
            this._render();
        });
    }

    _hasPlotJuggler() {
        const tool = this._status && this._status.tools.plotjuggler;
        return !!(tool && tool.installed);
    }

    // PlotJuggler subscribed to exactly these topics: one from a topic's Plot,
    // or the ones picked on their rows.
    _openPlotJuggler(topics) {
        this._notes.plotjuggler = { text: `Opening PlotJuggler with ${names(topics)}…` };
        this._render();
        this._helper(['plotjuggler', ...topics], reply => {
            this._notes.plotjuggler = reply.ok ? null : { text: reply.error, error: true };
            if (reply.ok)
                this._button.menu.close();
            this._loadStatus();
            this._pollRuns();
            this._render();
        });
    }

    // Picks a topic for PlotJuggler; the Topics section opens the picked ones together.
    _plotPickButton(name) {
        const picked = this._plotTopics.has(name);
        return CC.makeRoundButton(picked ? 'object-select-symbolic' : 'list-add-symbolic',
            picked ? `Take ${name} out of the PlotJuggler set` : `Add ${name} to the PlotJuggler set`, () => {
                if (picked)
                    this._plotTopics.delete(name);
                else
                    this._plotTopics.add(name);
                this._render();
            }, picked ? 'adaptive-ros-expand adaptive-ros-picked' : 'adaptive-ros-expand');
    }

    _plotJugglerBar() {
        const note = this._notes.plotjuggler;
        if (!this._hasPlotJuggler() || (!this._plotTopics.size && !note))
            return null;
        const picked = [...this._plotTopics].sort();
        return CC.makeRow({
            icon: 'utilities-system-monitor-symbolic',
            title: picked.length ? `PlotJuggler · ${plural(picked.length, 'topic')}` : 'PlotJuggler',
            subtitle: note ? note.text : names(picked),
            alert: !!(note && note.error),
            actions: picked.length ? [
                { label: 'Open in PlotJuggler', quiet: true, onClick: () => this._openPlotJuggler(picked) },
                { label: 'Clear', quiet: true, onClick: () => { this._plotTopics.clear(); this._render(); } },
            ] : null,
        });
    }

    _favoriteButton(kind, name) {
        const active = this._isFavorite(kind, name);
        return CC.makeRoundButton(active ? 'starred-symbolic' : 'non-starred-symbolic',
            active ? `Remove ${name} from favourites` : `Add ${name} to favourites`,
            () => this._toggleFavorite(kind, name), 'adaptive-ros-expand');
    }

    // Shows one item: the search narrows the graph to it, its row unfolded.
    _find(kind, name) {
        this._expanded.add(`section:${kind}s`);
        if (kind === 'node' || kind === 'topic')
            this._expanded.add(`${kind}:${name}`);
        this._search.set_text(name);
        this._fetchExpandedDetails();
    }

    // A name, namespace, type or diagnostic message matches; the other names
    // an item carries (a node's topics) do not, or every node would match /rosout.
    _matches(item) {
        if (!this._searchText)
            return true;
        const words = [item.name, item.short, item.namespace, item.message, item.hardware_id, ...(item.types || [])];
        return words.some(word => typeof word === 'string' && word.toLowerCase().includes(this._searchText));
    }

    // ------------------------------------------------------- confirmed writes

    // A write runs on the second click within a few seconds; the first only
    // arms it, and the button says what the next click does.
    _confirmed(key, action) {
        if (this._isArmed(key)) {
            this._disarm();
            action();
        } else {
            this._disarm();
            this._armed = { key, until: Date.now() + ARM_MS };
            this._armId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ARM_MS, () => {
                this._armId = 0;
                this._armed = null;
                this._render();
                return GLib.SOURCE_REMOVE;
            });
        }
        this._render();
    }

    _isArmed(key) {
        return !!(this._armed && this._armed.key === key && Date.now() <= this._armed.until);
    }

    _disarm() {
        this._armed = null;
        if (this._armId) {
            GLib.source_remove(this._armId);
            this._armId = 0;
        }
    }

    // What Record records: the topics the graph shows (narrowed by the
    // search), or every topic (`null`) before the graph is known.
    _topicsToRecord() {
        if (this._bagTopics)
            return [...this._bagTopics].sort();
        return this._graph ? this._graph.topics
            .filter(topic => !topic.system && this._matches(topic))
            .map(topic => topic.name) : null;
    }

    _recordTopics() {
        const topics = this._topicsToRecord();
        if (topics && !topics.length) {
            this._notes.bag = { text: this._bagTopics ? 'No topic to record: tick one under Topics'
                : 'No topic to record: the search shows none', error: true };
            this._render();
            return;
        }
        this._confirmed('bag:record', () => {
            this._notes.bag = { text: 'Starting the recording…' };
            this._helper(['bag-start', ...(topics || ['--all'])], reply => {
                this._notes.bag = reply.ok ? null : { text: reply.error, error: true };
                this._loadStatus();
                this._pollRuns();
            });
        });
    }

    _playBag(path, options = null) {
        options = options || { rate: '1', loop: false, clock: false };
        this._notes.bag = { text: 'Starting playback…' };
        this._render();
        this._helper(['bag-play', path, String(options.rate || 1),
            ...(options.loop ? ['loop'] : []), ...(options.clock ? ['clock'] : [])], reply => {
            this._notes.bag = reply.ok ? null : { text: reply.error, error: true };
            this._bagDraft = null;
            this._loadStatus();
            this._pollRuns();
        });
    }

    _bagControl(operation) {
        this._helper(['bag-control', operation], reply => {
            this._notes.bag = reply.ok ? null : { text: reply.error, error: true };
            this._pollRuns();
        });
    }

    _lifecycle(node, transition) {
        this._confirmed(`lifecycle:${node.name}:${transition}`, () => {
            const note = `op:${node.name}`;
            this._notes[note] = { text: `${title(transition)}…` };
            this._request('lifecycle', { node: node.name, transition }, reply => {
                this._notes[note] = reply.error ? { text: reply.error, error: true } : null;
                this._fetchNode(node);
            });
        });
    }

    _setParameter(node, parameter, text) {
        this._confirmed(`parameter:${node.name}:${parameter.name}`, () => {
            this._parameterDraft = null;
            const note = `op:${node.name}`;
            this._notes[note] = { text: `Setting ${parameter.name}…` };
            this._request('set_parameter', {
                node: node.name, name: parameter.name, value: text, ptype: parameter.ptype || 0,
            }, reply => {
                this._notes[note] = reply.error ? { text: `${parameter.name}: ${reply.error}`, error: true } : null;
                this._fetchNode(node);
            });
        });
    }

    _switchController(controller, op) {
        this._confirmed(`controller:${controller.manager}:${controller.name}:${op}`, () => {
            this._controllerDraft = null;
            this._notes.controllers = { text: `${title(op)} ${controller.name}…` };
            this._request('controller', { manager: controller.manager, name: controller.name, op }, reply => {
                this._notes.controllers = reply.error ? { text: reply.error, error: true } : null;
                this._render();
            });
        });
    }

    // A composer: the fields of a service request, action goal or message,
    // started from an empty one of its type, sent on a confirmed click.
    _toggleComposer(key, kind, type) {
        if (this._composers.has(key)) {
            this._composers.delete(key);
            this._render();
            return;
        }
        const composer = { text: '', busy: false, reply: null };
        this._composers.set(key, composer);
        this._request('template', { kind, type }, reply => {
            if (this._composers.get(key) === composer && !composer.text) {
                composer.text = reply.error ? '' : JSON.stringify(reply.values || {});
                composer.fields = reply.fields || [];
                composer.values = reply.values || {};
                composer.error = reply.error || '';
            }
            this._render();
        });
        this._render();
    }

    _send(key, cmd, name, type) {
        const composer = this._composers.get(key);
        if (!composer || composer.busy || !composer.fields) return;
        if (composer.error) { this._render(); return; }
        // A call with nothing to fill in (std_srvs/Trigger: take off, land) goes on
        // the first tap; anything carrying values is confirmed first.
        const confirm = cmd === 'call' && !composer.fields.length
            ? (_key, action) => { this._disarm(); action(); this._render(); }
            : (k, action) => this._confirmed(k, action);
        confirm(`send:${key}`, () => {
            composer.busy = true;
            composer.reply = null;
            const timeout = cmd === 'goal' ? GOAL_REPLY_TIMEOUT_MS : CALL_REPLY_TIMEOUT_MS;
            composer.requestId = this._request(cmd, { name, type, value: composer.text }, reply => {
                composer.busy = false;
                composer.requestId = 0;
                composer.reply = reply;
                this._queueRender();
            }, timeout, progress => {
                composer.feedback = progress;
                this._queueRender();
            });
        });
    }

    // One tap calls a service whose request has no fields (std_srvs/Trigger or
    // Empty: take off, land, reset) straight from its row; the row says how it went.
    _quickCall(service) {
        const state = this._quickCalls.get(service.name);
        if (state && state.busy)
            return;
        this._quickCalls.set(service.name, { busy: true, reply: state ? state.reply : null });
        this._render();
        this._request('call', { name: service.name, type: service.types[0], value: '' }, reply => {
            this._quickCalls.set(service.name, { busy: false, reply });
            this._queueRender();
        }, CALL_REPLY_TIMEOUT_MS);
    }

    // [subtitle, failed] for a service row: the last one-tap call, or null.
    _quickCallText(name) {
        const state = this._quickCalls.get(name);
        if (!state)
            return null;
        if (state.busy)
            return ['Calling…', false];
        const reply = state.reply || {};
        if (reply.error)
            return [`✗ ${reply.error}`, true];
        if (reply.success === false)
            return [`✗ ${reply.message || 'The service refused'}`, true];
        return [`✓ ${reply.message || 'Called'}`, false];
    }

    _quickCallAction(service) {
        if (!service || !service.no_request || !service.servers.length)
            return null;
        const state = this._quickCalls.get(service.name);
        return { label: state && state.busy ? 'Calling…' : 'Call', quiet: true, onClick: () => this._quickCall(service) };
    }

    _cancelGoal(composer) {
        if (!composer.requestId)
            return;
        this._request('cancel_goal', { goal_id: composer.requestId }, reply => {
            if (reply.error)
                composer.reply = reply;
            this._queueRender();
        });
    }

    _restart(entry) {
        const meta = entry.meta || {};
        if (entry.tool === 'launch' && meta.file)
            this._launch('launch', meta.file, meta.args || []);
        else if (entry.tool === 'bag' && meta.play)
            this._playBag(meta.play);
        else if (entry.tool === 'plotjuggler' && meta.topics)
            this._openPlotJuggler(meta.topics);
        else
            this._launch(entry.tool, meta.file || null);
        this._dismissed.add(`${entry.pgid}:${entry.ended}`);
    }

    // -------------------------------------------------------------- render

    // Now, for what the user did.
    _render() {
        if (this._renderId) {
            GLib.source_remove(this._renderId);
            this._renderId = 0;
        }
        this._renderPending = false;
        this._renderNow();
    }

    // Soon, for what the graph did: bursts become one render, and none lands
    // while the user types in the list (it would take the entry away).
    _queueRender() {
        if (!this._button || !this._button.menu.isOpen)
            return;
        if (this._editing()) {
            this._renderPending = true;
            return;
        }
        if (this._renderId)
            return;
        this._renderId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._renderId = 0;
            this._renderNow();
            return GLib.SOURCE_REMOVE;
        });
    }

    _editing() {
        const focus = global.stage.get_key_focus();
        return !!focus && this._list.contains(focus) && focus instanceof Clutter.Text;
    }

    // What several blocks show; a change rebuilds them all. What only one
    // block shows is in that block's own inputs.
    _viewKey() {
        const map = m => [...m.entries()];
        return JSON.stringify([
            [...this._expanded].sort(), map(this._details), map(this._interfaces), map(this._rates),
            map(this._samples), map(this._composers), map(this._quickCalls), [...this._plotTopics], map(this._pages),
            this._notes, this._searchText,
            this._parameterDraft, this._packagePath, this._armed && this._armed.key,
            this._status && this._status.favorites,
            this._paramProfileDraft, this._paramDiff, this._profileDraft, this._logView, this._bagDraft,
            [...this._searchFolded], this._buildUpTo,
            this._bagTopics && [...this._bagTopics], this._tfLookup, this._plotDraft,
            [...this._lifecycleSelection], this._lifecycleResult, this._focus,
            this._status && [this._status.parameter_profiles, this._status.robot_profiles],
        ]);
    }

    _renderNow() {
        if (!this._button || !this._button.menu.isOpen)
            return;
        const adjustment = this._scroll.vscroll.adjustment;
        // A click often renders twice in a row (now, and when its reply comes:
        // Call it…, Preview, Hz, Plot). The second render comes before the first
        // has put the scroll back, when the rebuilt list has reset it to the top,
        // so it keeps the position the first one saw.
        const scrolled = this._scrollId && this._keptScroll !== null ? this._keptScroll : adjustment.value;
        this._keptScroll = scrolled;
        const status = this._status;
        const view = this._viewKey();
        const used = new Set();

        // A block's actors are kept while its inputs and the view stay the
        // same, so a graph change rebuilds only the sections it touched.
        const block = (id, inputs, build) => {
            used.add(id);
            const sig = `${view}\n${JSON.stringify(inputs)}`;
            let cached = this._blocks.get(id);
            if (!cached || cached.sig !== sig) {
                if (cached)
                    cached.actor.destroy();
                this._out = new Block({ vertical: true, x_expand: true });
                build();
                cached = { sig, actor: this._out };
                this._blocks.set(id, cached);
            }
            this._list.add_child(cached.actor);
        };

        this._summary.text = this._summaryText();
        this._footer.destroy_all_children();
        const bar = status && status.installed ? this._plotJugglerBar() : null;
        if (bar)
            this._footer.add_child(bar);
        this._footer.visible = !!bar;
        this._list.remove_all_children();
        if (!status) {
            block('reading', [], () => this._out.add_child(
                CC.makeRow({ icon: CC.extensionIcon('ros-symbolic'), title: 'Reading…' })));
        } else if (!status.installed) {
            block('missing', [], () => this._out.add_child(CC.makeRow({
                icon: 'dialog-warning-symbolic',
                title: 'ROS 2 is not installed',
                subtitle: 'Nothing under /opt/ros has a setup.bash',
            })));
        } else {
            const runs = this._runs || {};
            block('setup', [status, this._domainDraft, this._setupDraft, runs.build, (runs.running || {}).build],
                () => this._out.add_child(this._setup(status)));
            block('launch', [status, this._runs, this._launchDraft, [...this._dismissed], this._graph !== null],
                () => this._addLaunch(status));
            this._addGraph(status, block);
        }
        for (const [id, cached] of this._blocks) {
            if (!used.has(id)) {
                cached.actor.destroy();
                this._blocks.delete(id);
            }
        }
        this._out = null;

        const [, natural] = this._list.get_preferred_height(-1);
        this._scroll.set_height(Math.min(natural, this._listRoom()));
        // The rebuilt list is not laid out yet; put the scroll back once it is.
        if (this._scrollId)
            GLib.source_remove(this._scrollId);
        this._scrollId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._scrollId = 0;
            if (!this._button)
                return GLib.SOURCE_REMOVE;
            const target = this._scrollToBlock && this._blocks.get(this._scrollToBlock);
            if (!target) {
                this._scrollToBlock = null;
                this._keptScroll = null;
                adjustment.value = Math.min(scrolled, adjustment.upper - adjustment.page_size);
                return GLib.SOURCE_REMOVE;
            }
            // The plot and the graph view sit below the setup and the launchers:
            // show the one just opened. A new block has no place until the list
            // is laid out, so try again for a few frames until it has one (a render
            // in between cancels this and tries again with the block it built).
            let tries = 0;
            this._scrollId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 16, () => {
                const actor = target.actor;
                const placed = actor.get_stage() && actor.has_allocation() &&
                    adjustment.upper >= actor.get_y() + Math.min(actor.get_height(), adjustment.page_size);
                if (!placed && ++tries < 30)
                    return GLib.SOURCE_CONTINUE;
                this._scrollId = 0;
                this._scrollToBlock = null;
                this._keptScroll = null;
                // A little above the block, so its title clears the list's top fade.
                if (actor.get_stage())
                    adjustment.value = Math.max(0, Math.min(actor.get_y() - 12, adjustment.upper - adjustment.page_size));
                return GLib.SOURCE_REMOVE;
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    // How tall the list may be: 680 px, or less on a short screen, so the footer
    // (Open in PlotJuggler) below it stays on the screen.
    _listRoom() {
        const monitor = Main.layoutManager.findMonitorForActor(this._button) || Main.layoutManager.primaryMonitor;
        if (!monitor || !this._scroll.is_mapped())
            return LIST_MAX_HEIGHT;
        const [, top] = this._scroll.get_transformed_position();
        const [, footer] = this._footer.visible ? this._footer.get_preferred_height(-1) : [0, 0];
        const room = monitor.y + monitor.height - top - footer - 24;      // 24: the menu's own bottom edge
        return Math.max(200, Math.min(LIST_MAX_HEIGHT, Math.floor(room)));
    }

    _summaryText() {
        const status = this._status;
        if (!status || !status.installed)
            return '';
        const parts = [title(status.distro), `domain ${status.domain}`];
        if (this._graph)
            parts.push(plural(this._graph.nodes.length, 'node'));
        if (this._runs && this._runs.recording)
            parts.push('recording');
        return parts.join(' · ');
    }

    // --------------------------------------------------------- small pieces

    _smallButton(label, onClick, extraClass = '') {
        const button = new St.Button({
            style_class: `adaptive-tasks-sort ${extraClass}`.trim(),
            label,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        button.connect('clicked', onClick);
        return button;
    }

    // Buttons in a row; `armed` ones ask for the confirming click.
    _buttons(items) {
        const actions = items.filter(Boolean);
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-buttons',
            vertical: actions.reduce((n, item) => n + item.label.length, 0) > 54 });
        for (const item of actions) {
            box.add_child(this._smallButton(item.label, item.onClick,
                item.armed ? 'adaptive-ros-armed' : ''));
        }
        return box;
    }

    _note(text, error = false) {
        const label = new St.Label({
            text,
            style_class: error ? 'adaptive-network-ssh-error' : 'adaptive-ros-meta',
        });
        return wrapped(label);
    }

    // An entry in the list. A render that the graph asks for waits until it
    // loses focus.
    _textEntry({ text = '', hint = '', multiline = false, onChange = null, onActivate = null,
        onEscape = null, focus = false, extraClass = '' }) {
        const entry = new St.Entry({
            style_class: `adaptive-cc-entry ${extraClass}`.trim(),
            text,
            hint_text: hint,
            can_focus: true,
            x_expand: true,
        });
        const inner = entry.clutter_text;
        if (multiline) {
            inner.single_line_mode = false;
            inner.activatable = false;
            inner.line_wrap = true;
            inner.ellipsize = Pango.EllipsizeMode.NONE;
            inner.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        }
        if (onChange)
            inner.connect('text-changed', () => onChange(entry.get_text()));
        if (onActivate)
            inner.connect('activate', () => onActivate(entry.get_text()));
        inner.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() !== Clutter.KEY_Escape || !onEscape)
                return Clutter.EVENT_PROPAGATE;
            onEscape();
            return Clutter.EVENT_STOP;
        });
        inner.connect('key-focus-out', () => {
            if (this._renderPending)
                this._queueRender();
        });
        if (focus) {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                if (entry.get_stage()) {
                    entry.grab_key_focus();
                    inner.set_cursor_position(-1);
                }
                return GLib.SOURCE_REMOVE;
            });
        }
        return entry;
    }

    // Inline dropdowns reserve their full height; choices never float over neighbours.
    _dropdown(label, items, onSelect, selected = '') {
        const box = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-dropdown' });
        const key = `select:${label}`;
        const open = this._expanded.has(key);
        const toggle = this._smallButton(`${label} · ${selected || `${items.length} choices`}  ${open ? '▴' : '▾'}`,
            () => this._toggle(key), 'adaptive-ros-select');
        toggle.x_expand = true;
        toggle.get_child().x_align = Clutter.ActorAlign.START;
        toggle.get_child().ellipsize = Pango.EllipsizeMode.MIDDLE;
        box.add_child(toggle);
        if (!open)
            return box;
        const list = new St.BoxLayout({ vertical: true, x_expand: true });
        const scroll = new St.ScrollView({ style_class: 'adaptive-ros-options', x_expand: true,
            overlay_scrollbars: true, hscrollbar_policy: St.PolicyType.NEVER, vscrollbar_policy: St.PolicyType.AUTOMATIC });
        scroll.add_actor(list);
        const fill = text => {
            list.destroy_all_children();
            for (const item of items.filter(i => `${i.name} ${i.path || ''}`.toLowerCase().includes(text.toLowerCase()))) {
                const button = new St.Button({ label: item.name, x_expand: true, can_focus: true,
                    style_class: 'adaptive-ros-option', accessible_name: item.path || item.name });
                button.get_child().x_align = Clutter.ActorAlign.START;
                button.get_child().ellipsize = Pango.EllipsizeMode.MIDDLE;
                button.connect('clicked', () => { this._expanded.delete(key); onSelect(item); this._render(); });
                list.add_child(button);
            }
        };
        if (items.length > 6)
            box.add_child(this._textEntry({ hint: 'Filter choices…', onChange: fill }));
        fill('');
        box.add_child(scroll);
        return box;
    }

    _addFiles(files, label, onClick, active = null) {
        if (files.length)
            this._out.add_child(this._dropdown(label, files, file => onClick(file.path, file),
                active ? (files.find(active) || {}).name : ''));
    }

    // -------------------------------------------------------------- setup

    // Domain, discovery, middleware and workspace, each changed by a click;
    // saved setups; the active project's workspace.
    _setup(status) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form adaptive-network-facts adaptive-ros-setup',
            vertical: true,
            x_expand: true,
        });
        const grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({ column_spacing: 12, row_spacing: 2 }),
            x_expand: true,
        });
        box.add_child(grid);
        let row = 0;
        const key = text => grid.layout_manager.attach(new St.Label({
            text,
            style_class: 'adaptive-usb-key',
            y_align: Clutter.ActorAlign.CENTER,
        }), 0, row, 1, 1);
        const line = (name, value, hint, onClick) => {
            key(name);
            const content = new St.BoxLayout({ style_class: 'adaptive-ros-value-box' });
            content.add_child(new St.Label({ text: value }));
            if (hint)
                content.add_child(new St.Label({ text: hint, style_class: 'adaptive-ros-hint' }));
            const button = new St.Button({
                style_class: 'adaptive-network-value',
                child: content,
                x_expand: true,
                x_align: Clutter.ActorAlign.START,
                can_focus: !!onClick,
                reactive: !!onClick,
            });
            if (onClick)
                button.connect('clicked', onClick);
            grid.layout_manager.attach(button, 1, row, 1, 1);
            row++;
        };
        const from = status.from;
        const hint = name => from[name] === 'shell' ? `from ${status.shell_rc}` : SOURCE_HINTS[from[name]];

        if (this._domainDraft !== null) {
            key('Domain');
            grid.layout_manager.attach(this._textEntry({
                text: this._domainDraft,
                hint: '0 to 232, Enter to use it',
                extraClass: 'adaptive-ros-domain-entry',
                focus: true,
                onChange: text => {
                    this._domainDraft = text;
                },
                onActivate: () => {
                    const value = this._domainDraft.trim();
                    this._domainDraft = null;
                    if (/^\d+$/.test(value) && Number(value) !== status.domain)
                        this._set('domain', value);
                    else
                        this._render();
                },
                onEscape: () => {
                    this._domainDraft = null;
                    this._render();
                },
            }), 1, row++, 1, 1);
        } else {
            line('Domain', String(status.domain), hint('domain'), () => {
                this._domainDraft = String(status.domain);
                this._render();
            });
        }

        box.add_child(this._dropdown('Discovery', [{name: 'This computer only', path: '1'},
            {name: 'Whole network', path: '0'}], item => this._set('localhost', item.path),
        status.localhost ? 'This computer only' : 'Whole network'));
        box.add_child(this._dropdown('Middleware', status.middlewares.map(m => ({name: m.name, path: m.id})),
            item => this._set('rmw', item.path), status.rmw_name));

        const named = status.workspaces.find(w => w.path === status.workspace);
        box.add_child(this._dropdown('Workspace', [{ name: 'None', path: 'none' }, ...status.workspaces, {name: 'Choose path…', path: 'custom'}], item => {
            if (item.path === 'custom') { this._expanded.add('workspace:path'); return; }
            this._packagePath = '';
            this._set('workspace', item.path);
        }, named ? named.name : 'None'));
        if (this._expanded.has('workspace:path'))
            box.add_child(this._textEntry({ hint: 'Workspace path… (Enter to use)', focus: true,
                onActivate: text => { this._packagePath = ''; this._expanded.delete('workspace:path'); this._set('workspace', text.trim()); },
                onEscape: () => this._toggle('workspace:path') }));
        const packages = status.packages || [];
        if (!packages.some(p => p.path === this._packagePath))
            this._packagePath = '';
        if (status.workspace) {
            if (status.tools.build.installed)
                this._addBuild(box, status, named ? named.name : 'the workspace');
            this._addPackages(box, status, packages);
        } else {
            box.add_child(this._note('Choose a workspace to list its packages and build them'));
        }

        for (const issue of status.environment || [])
            box.add_child(this._note(issue.text, issue.level === 'error'));

        this._addRobotProfiles(box, status, named);

        this._addSetups(box, status);

        const footer = (text, buttons, error = false) => {
            const bar = new St.BoxLayout({ style_class: 'adaptive-ros-setup-footer', x_expand: true });
            const label = new St.Label({
                text,
                style_class: error ? 'adaptive-network-ssh-error' : 'adaptive-ros-hint',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            bar.add_child(wrapped(label));
            bar.add_child(this._buttons(buttons));
            box.add_child(bar);
        };

        const other = (status.elsewhere || [])[0];
        if (other && !this._notes.setup) {
            footer(`${other.count} ROS ${other.count === 1 ? 'process runs' : 'processes run'} on domain ` +
                `${other.domain}${other.localhost ? ', this computer only' : ''}` +
                `${other.rmw_name ? ` · ${other.rmw_name}` : ''}`, [{
                label: 'Watch them',
                onClick: () => {
                    const pairs = ['domain', String(other.domain), 'localhost', other.localhost ? '1' : '0'];
                    if ((status.middlewares || []).some(item => item.id === other.rmw))
                        pairs.push('rmw', other.rmw);
                    this._setMany(pairs);
                },
            }]);
        }

        // The active project holds a workspace the panel does not use.
        const project = status.project;
        if (from.workspace === 'project') {
            footer(`Following ${project ? project.name : 'the active project'}'s workspace`, [{
                label: 'Stop following', onClick: () => this._set('follow_project', ''),
            }]);
        } else if (project && project.workspace && project.workspace !== status.workspace &&
                   from.workspace !== 'panel') {
            footer(`${project.name} has a ROS workspace`, [
                { label: 'Use it', onClick: () => this._set('workspace', project.workspace) },
                { label: 'Always follow', onClick: () => this._set('follow_project', '1') },
            ]);
        }

        const note = this._notes.setup;
        const changed = Object.values(from).includes('panel');
        if (note || changed) {
            footer(note ? note.text : `Changed here; your terminals still use ${status.shell_rc}`,
                changed ? [{
                    label: `Follow ${status.shell_rc}`,
                    onClick: () => {
                        this._notes.setup = null;
                        this._set('all', '');
                    },
                }] : [], !!note);
        }
        return box;
    }

    // Saved setups (domain, discovery, middleware, workspace) as chips; the
    // one in use is lit.
    _addSetups(box, status) {
        const setups = status.setups || [];
        const same = item => item.domain === status.domain && item.localhost === status.localhost &&
            (item.rmw || '') === (status.rmw_set ? status.rmw : '') &&
            (item.workspace || '') === (status.workspace || '');
        const current = setups.find(same);
        const flow = new St.BoxLayout({
            style_class: 'adaptive-ros-setups', vertical: true,
            x_expand: true,
        });
        if (setups.length)
            flow.add_child(this._dropdown('Saved setups', setups, item => this._applySetup(['use-setup', item.name]),
                current ? current.name : 'Choose…'));
        if (this._setupDraft === null) {
            flow.add_child(this._smallButton(current ? `Forget ${current.name}` : 'Save this setup', () => {
                if (current) {
                    this._confirmed(`forget-setup:${current.name}`, () => this._editSetups(['forget-setup', current.name]));
                } else {
                    const ws = status.workspaces.find(w => w.path === status.workspace);
                    this._setupDraft = `${ws ? ws.name.split('/').pop() : 'ROS'} · domain ${status.domain}`;
                    this._render();
                }
            }, current && this._isArmed(`forget-setup:${current.name}`) ? 'adaptive-ros-armed' : ''));
            box.add_child(flow);
            return;
        }
        box.add_child(flow);
        box.add_child(this._textEntry({
            text: this._setupDraft,
            hint: 'A name for this setup, Enter to save it',
            focus: true,
            onChange: text => {
                this._setupDraft = text;
            },
            onActivate: text => {
                this._setupDraft = null;
                this._editSetups(['save-setup', text.trim()]);
            },
            onEscape: () => {
                this._setupDraft = null;
                this._render();
            },
        }));
    }

    _editSetups(args) {
        this._helper(args, reply => {
            if (reply.ok && this._status)
                this._status.setups = reply.setups;
            this._notes.setup = reply.ok ? null : { text: reply.error, error: true };
            this._render();
        });
    }

    // colcon build of everything; while a build runs, how far it is.
    _addBuild(box, status, workspaceName) {
        const builds = ((this._runs && this._runs.running) || status.runs || {}).build || [];
        const progress = (this._runs && this._runs.running ? this._runs.build : status.build) || {};
        const note = this._notes.build;
        const failed = progress.failed || [];
        let subtitle = note ? note.text : `Every package in ${workspaceName}, the way it was built last`;
        if (builds.length) {
            const done = (progress.finished || []).length;
            const started = Math.max(done, (progress.started || []).length);
            subtitle = `${builds[0].paused ? 'Paused' : 'Building'} · ${done} of ${plural(started, 'package')} done` +
                `${failed.length ? ` · ${failed.join(', ')} failed` : ''}`;
        }
        box.add_child(CC.makeRow({
            icon: 'system-run-symbolic',
            title: builds.length ? builds[0].meta.name || 'Build' : 'colcon build',
            subtitle,
            alert: !!(note && note.error) || failed.length > 0,
            active: builds.length > 0,
            actions: builds.length ? [
                { label: 'Log', quiet: true, onClick: () => this._openLogView('build') },
                { label: 'Stop', onClick: () => this._stop('build') },
            ] : [{ label: 'Build all', onClick: () => this._buildWorkspace([]) }],
        }));
        if (builds.length && progress.last)
            box.add_child(this._note(progress.last));
    }

    // The workspace's packages, each with its own Build; a click on one
    // narrows the launch files and nodes below to it.
    _addPackages(box, status, packages) {
        const building = (((this._runs && this._runs.running) || status.runs || {}).build || []).length > 0;
        const folded = this._expanded.has('workspace:packages-folded');
        const unbuilt = packages.filter(p => !p.built).length;
        const heading = new St.BoxLayout({ style_class: 'adaptive-ros-launch-heading', x_expand: true });
        const toggle = this._smallButton(`${folded ? '▸' : '▾'}  Packages · ${packages.length}` +
            `${unbuilt ? ` · ${unbuilt} not built` : ''}`, () => this._toggle('workspace:packages-folded'), 'adaptive-ros-select');
        toggle.x_expand = true;
        toggle.get_child().x_align = Clutter.ActorAlign.START;
        heading.add_child(toggle);
        if (packages.length && status.tools.build.installed) {
            heading.add_child(this._smallButton(`${this._buildUpTo ? '✓' : '○'} With dependencies`, () => {
                this._buildUpTo = !this._buildUpTo;
                this._render();
            }));
        }
        box.add_child(heading);
        if (folded)
            return;
        if (!packages.length) {
            box.add_child(this._note('No package.xml under this workspace\'s sources'));
            return;
        }
        for (const pkg of packages) {
            const selected = pkg.path === this._packagePath;
            const select = () => {
                this._packagePath = selected ? '' : pkg.path;
                this._launchDraft = null;
                this._render();
            };
            const facts = [pkg.built ? plural(pkg.executables.length, 'executable') : 'not built yet'];
            if (selected)
                facts.push('launch files and nodes below are this package\'s');
            box.add_child(CC.makeRow({
                icon: pkg.built ? 'package-x-generic-symbolic' : 'dialog-warning-symbolic',
                title: pkg.name,
                subtitle: facts.join(' · '),
                active: selected,
                onActivate: select,
                actions: [
                    { label: selected ? 'Show all' : 'Select', quiet: true, onClick: select },
                    building || !status.tools.build.installed ? null : {
                        label: 'Build', quiet: true, onClick: () => this._buildWorkspace([pkg.name], this._buildUpTo),
                    },
                ].filter(Boolean),
            }));
        }
    }

    _buildWorkspace(packages, upTo = false) {
        this._notes.build = { text: 'Starting the build…' };
        this._render();
        this._helper(['build', ...(upTo && packages.length ? ['--up-to'] : []), ...packages], reply => {
            this._notes.build = reply.ok ? null : { text: reply.error, error: true };
            this._loadStatus();
            this._pollRuns();
        });
    }

    // A robot profile: this setup with its package, favourites and saved
    // launches. The one matching the setup now is shown as in use.
    _addRobotProfiles(box, status, named) {
        const profiles = status.robot_profiles || [];
        const current = profiles.find(p => p.domain === status.domain && !!p.localhost === !!status.localhost &&
            (p.rmw || '') === (status.rmw_set ? status.rmw : '') && (p.workspace || '') === (status.workspace || ''));
        const note = this._notes.profile;
        box.add_child(CC.makeRow({
            icon: 'user-bookmarks-symbolic',
            title: current ? `Robot profile · ${current.name}` : 'Robot profile',
            subtitle: note ? note.text : current ? 'In use: the setup matches it'
                : 'Keeps this setup with its package, favourites and saved launches',
            alert: !!(note && note.error),
            actions: [
                { label: 'Save…', quiet: true, onClick: () => {
                    this._profileDraft = current ? current.name : named ? named.name : 'Robot';
                    this._render();
                } },
                current ? { label: 'Forget', quiet: true, onClick: () => this._forgetRobotProfile(current.name) } : null,
            ].filter(Boolean),
        }));
        if (this._profileDraft !== null) {
            box.add_child(this._textEntry({ text: this._profileDraft || '', hint: 'Profile name, Enter to save', focus: true,
                onChange: text => { this._profileDraft = text; },
                onActivate: text => this._saveRobotProfile(text),
                onEscape: () => { this._profileDraft = null; this._render(); } }));
        }
        if (profiles.length)
            box.add_child(this._dropdown('Use profile', profiles, item => this._useRobotProfile(item.name),
                current ? current.name : `${profiles.length} saved`));
    }

    _forgetRobotProfile(name) {
        this._helper(['forget-robot-profile', name], reply => {
            if (reply.ok)
                this._status.robot_profiles = reply.robot_profiles;
            this._notes.profile = reply.ok ? null : { text: reply.error, error: true };
            this._render();
        });
    }

    _saveRobotProfile(name) {
        const selected = (this._status.packages || []).find(p => p.path === this._packagePath);
        this._helper(['save-robot-profile', name.trim(), selected ? selected.name : ''], reply => {
            if (reply.ok) {
                this._profileDraft = null;
                this._status.robot_profiles = reply.robot_profiles;
            }
            this._notes.profile = reply.ok ? null : { text: reply.error, error: true };
            this._render();
        });
    }

    _useRobotProfile(name) {
        this._helper(['use-robot-profile', name], reply => {
            if (reply.ok) {
                this._status = reply;
                this._notes.profile = null;
                const selected = (reply.packages || []).find(p => p.name === (reply.profile || {}).package);
                this._packagePath = selected ? selected.path : '';
                this._restartWatch();
            } else {
                this._notes.profile = { text: reply.error, error: true };
            }
            this._render();
        });
    }

    // -------------------------------------------------------------- launch

    _addLaunch(status) {
        const heading = new St.BoxLayout({ style_class: 'adaptive-ros-launch-heading', x_expand: true });
        const label = CC.makeHeading('Launch');
        label.x_expand = true;
        heading.add_child(label);
        heading.add_child(this._smallButton('Rescan files', () => this._loadStatus(null, true)));
        this._out.add_child(heading);

        this._out.add_child(this._toolRow(status, 'rviz2', 'video-display-symbolic', 'RViz2',
            'Topics, TF and robot models in 3D'));
        if (status.tools.rviz2.installed)
            this._addFiles(status.rviz_configs, 'Open with', file => this._launch('rviz2', file));

        if (status.tools.gazebo.installed) {
            this._out.add_child(this._toolRow(status, 'gazebo', 'applications-engineering-symbolic',
                'Gazebo', status.gazebo_flavour === 'classic' ? 'Gazebo Classic, empty world' : 'Simulator, empty world'));
            this._addFiles(status.worlds, 'World', file => this._launch('gazebo', file));
        } else {
            this._out.add_child(CC.makeRow({
                icon: 'applications-engineering-symbolic',
                title: 'Gazebo',
                subtitle: `Not installed · ${status.gazebo_install}`,
                action: { label: 'Install…', quiet: true, onClick: () => this._terminal('install-gazebo') },
            }));
        }

        const actions = [];
        if (status.tools.rqt.installed)
            actions.push({ label: 'rqt', quiet: true, onClick: () => this._launch('rqt') });
        if (status.tools.rqt_graph.installed)
            actions.push({ label: 'Graph', quiet: true, onClick: () => this._launch('rqt_graph') });
        actions.push({ label: 'Terminal', quiet: true, onClick: () => this._terminal('terminal') });
        const note = this._notes.rqt || this._notes.rqt_graph;
        this._out.add_child(CC.makeRow({
            icon: 'utilities-terminal-symbolic',
            title: 'Tools',
            subtitle: note ? note.text : 'rqt, the node graph, a terminal on this setup',
            alert: !!(note && note.error),
            actions,
        }));

        if (status.tools.launch.installed)
            this._addLaunchFiles(status);
        const executables = (status.packages || []).filter(p => !this._packagePath || p.path === this._packagePath)
            .flatMap(p => p.executables.map(e => ({ ...e, name: `${p.name} / ${e.name}` })));
        this._addFiles(executables, 'Executable nodes', file => this._launch('node', file));
        if (status.workspace && !executables.length)
            this._out.add_child(this._note('No installed executable nodes in this selection'));
        const nodeRuns = (status.runs || {}).node || [];
        if (nodeRuns.length)
            this._out.add_child(CC.makeRow({ icon: 'system-run-symbolic', title: 'Workspace nodes',
                subtitle: nodeRuns.map(r => r.meta.name).join(', '), actions: [
                    { label: 'Log', onClick: () => this._terminal('open-log', 'node') },
                    { label: 'Stop', onClick: () => this._stop('node') },
                ] }));
        this._addRunManager(status);
        this._addCrashes(status);
        if (status.tools.bag.installed)
            this._addBags(status);
    }

    // Everything started from the panel in one list: its log, pause, restart, stop.
    _addRunManager(status) {
        const running = (this._runs && this._runs.running) || status.runs || {};
        const entries = Object.entries(running).flatMap(([tool, runs]) => runs.map(run => ({ tool, ...run })));
        const now = Date.now() / 1000;
        this._section('run-manager', `Running from here · ${entries.length}`, () => {
            if (!entries.length)
                this._out.add_child(this._note('Nothing started from this panel is running'));
            for (const run of entries) {
                const meta = run.meta || {};
                const recording = run.tool === 'bag' && !meta.play;
                this._out.add_child(CC.makeRow({
                    icon: run.tool === 'build' ? 'system-run-symbolic' : 'media-playback-start-symbolic',
                    title: meta.name || TOOL_NAMES[run.tool] || title(run.tool),
                    subtitle: `${TOOL_NAMES[run.tool] || title(run.tool)} · ${run.paused ? 'paused · ' : ''}` +
                        `${seconds(now - (run.started || now))}`,
                    active: !run.paused,
                    actions: [
                        { label: 'Log', quiet: true, onClick: () => this._openLogView(run.tool) },
                        PAUSABLE.has(run.tool) ? {
                            label: run.paused ? 'Resume' : 'Pause', quiet: true,
                            onClick: () => this._controlRun(run.tool, run.paused ? 'resume' : 'pause'),
                        } : null,
                        recording ? null : { label: 'Restart', quiet: true, onClick: () => this._restartRun(run) },
                        { label: 'Stop', onClick: () => this._stop(run.tool) },
                    ].filter(Boolean),
                }));
                const note = this._notes[run.tool];
                if (note && note.error)
                    this._out.add_child(this._note(note.text, true));
            }
            if (this._logView)
                this._addLogView(this._logView);
        });
    }

    _addLogView(view) {
        this._out.add_child(new St.Label({ text: `${TOOL_NAMES[view.tool] || title(view.tool)} log`,
            style_class: 'adaptive-ros-group' }));
        this._out.add_child(this._dropdown('Show', ['all', 'warning', 'error'].map(name => ({ name: title(name), path: name })),
            item => { view.severity = item.path; this._loadLogView(); }, title(view.severity)));
        this._out.add_child(this._textEntry({ text: view.query, hint: 'Filter the log, Enter to apply…',
            onChange: text => { view.query = text; }, onActivate: () => this._loadLogView() }));
        const output = new St.Label({ text: view.loading && !view.text ? 'Reading…' : view.text || 'No matching lines',
            style_class: 'adaptive-ros-definition adaptive-ros-log' });
        wrapped(output).clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        this._out.add_child(output);
        if (view.lines > view.shown)
            this._out.add_child(this._note(`The last ${view.shown} of ${view.lines} lines`));
        this._out.add_child(this._buttons([
            { label: 'Follow in a terminal', onClick: () => this._terminal('open-log', view.tool) },
            { label: 'Close', onClick: () => { this._logView = null; this._render(); } },
        ]));
    }

    _openLogView(tool) {
        this._logView = { tool, query: '', severity: 'all', text: '', lines: 0, shown: 0, loading: true };
        this._expanded.add('section:run-manager');
        this._loadLogView();
    }

    // `quiet`: the poll's refresh, which renders only when the text changed.
    _loadLogView(quiet = false) {
        const view = this._logView;
        if (!view || (quiet && view.loading))
            return;
        view.loading = true;
        this._helper(['log-tail', view.tool, view.query, view.severity, String(LOG_LINES)], reply => {
            if (this._logView !== view)
                return;
            view.loading = false;
            const text = reply.ok ? reply.text : reply.error;
            if (quiet && text === view.text)
                return;
            view.text = text;
            view.lines = reply.lines || 0;
            view.shown = text ? text.split('\n').length : 0;
            if (quiet)
                this._queueRender();
            else
                this._render();
        });
        if (!quiet)
            this._render();
    }

    _controlRun(tool, operation) {
        this._helper(['run-control', tool, operation], reply => {
            this._notes[tool] = reply.ok ? null : { text: reply.error, error: true };
            this._pollRuns();
        });
    }

    // Stop it, then start the same thing again.
    _restartRun(run) {
        const meta = run.meta || {};
        this._helper(['stop', run.tool], () => {
            if (run.tool === 'build')
                this._buildWorkspace(meta.packages || [], !!meta.up_to);
            else if (run.tool === 'plot')
                this._openRqtPlot(meta.expression);
            else if (run.tool === 'plotjuggler')
                this._openPlotJuggler(meta.topics || []);
            else
                this._restart({ tool: run.tool, meta, pgid: run.pgid, ended: 0 });
        });
    }

    _toolRow(status, tool, icon, name, idle) {
        const info = status.tools[tool];
        const note = this._notes[tool];
        const running = info.pids.length > 0;
        const owned = (info.owned_pids || []).length > 0;
        const external = (info.external_pids || []).length > 0;
        if (!info.installed)
            return CC.makeRow({ icon, title: name, subtitle: 'Not installed' });
        return CC.makeRow({
            icon,
            title: name,
            subtitle: note ? note.text : owned && external ? 'Running here and outside the panel'
                : owned ? 'Running · started here' : external ? 'Running outside the panel' : idle,
            alert: !!(note && note.error),
            active: running,
            // The plain pill is the red one, for what ends something.
            actions: running ? [
                { label: 'Show', quiet: true, onClick: () => this._show(tool) },
                ...(owned ? [{ label: 'Log', quiet: true, onClick: () => this._terminal('open-log', tool) }] : []),
                ...(owned ? [{ label: 'Stop', onClick: () => this._stop(tool) }] : []),
            ] : [
                { label: 'Open', quiet: true, onClick: () => this._launch(tool) },
            ],
        });
    }

    // Saved launches start at a click; a workspace launch file first asks for
    // its arguments, and can be saved with them.
    _addLaunchFiles(status) {
        const runs = (status.runs || {}).launch || [];
        const saved = (status.saved_launches || []).filter(item => !this._packagePath || item.file.startsWith(`${this._packagePath}/`));
        const files = (status.launch_files || []).filter(f => !this._packagePath || f.path.startsWith(`${this._packagePath}/`))
            .map(f => ({ ...f, name: status.workspace ? f.path.replace(`${status.workspace}/src/`, '') : f.name }));
        if (!runs.length && !saved.length && !files.length)
            return;
        const note = this._notes.launch;
        const running = runs.map(run => run.meta.name || 'A launch');
        this._out.add_child(CC.makeRow({
            icon: 'system-run-symbolic',
            title: 'Launch files',
            subtitle: note ? note.text : running.length ? `${names(running)} running · started here`
                : 'Saved launches, and the launch files in your workspaces',
            alert: !!(note && note.error),
            active: running.length > 0,
            actions: running.length ? [
                { label: 'Log', quiet: true, onClick: () => this._terminal('open-log', 'launch') },
                { label: 'Stop', onClick: () => this._stop('launch') },
            ] : [],
        }));
        this._addFiles(saved.map(item => ({ ...item, path: item.name })), 'Saved', name => this._launchSaved(name));
        this._addFiles(files, 'Files', path => {
            const last = saved.find(item => item.file === path);
            this._launchDraft = { file: path, text: last ? last.args.join(' ') : '', loading: true, arguments: [] };
            const draft = this._launchDraft;
            this._helper(['launch-args', path], reply => {
                if (this._launchDraft !== draft)
                    return;
                draft.loading = false;
                draft.arguments = reply.ok ? reply.arguments : [];
                draft.argumentError = reply.ok ? '' : reply.error;
                for (const argument of draft.arguments) {
                    const previous = (last ? last.args : []).find(value => value.startsWith(`${argument.name}:=`));
                    argument.value = previous ? previous.slice(argument.name.length + 2) : argument.default;
                }
                draft.text = draft.arguments.length ? '' : draft.text;
                this._render();
            });
            this._render();
        }, file => this._launchDraft && this._launchDraft.file === file.path);

        const draft = this._launchDraft;
        if (!draft)
            return;
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-detail', vertical: true, x_expand: true });
        box.add_child(new St.Label({ text: draft.file.replace(GLib.get_home_dir(), '~'), style_class: 'adaptive-ros-meta' }));
        // Only what differs from a default is passed (and saved).
        const args = () => draft.arguments && draft.arguments.length
            ? draft.arguments.filter(argument => argument.value !== '' && argument.value !== argument.default)
                .map(argument => `${argument.name}:=${argument.value}`)
            : draft.text.split(/\s+/).filter(Boolean);
        const go = () => {
            const missing = (draft.arguments || []).find(argument => argument.required && !argument.value);
            if (missing) {
                draft.error = `${missing.name} has no default; give it a value`;
                this._render();
                return;
            }
            this._launchDraft = null;
            this._launch('launch', draft.file, args());
        };
        const cancel = () => {
            this._launchDraft = null;
            this._render();
        };
        if (draft.loading) {
            box.add_child(this._note('Reading the arguments it declares…'));
        } else if (draft.arguments && draft.arguments.length) {
            for (const argument of draft.arguments) {
                const about = [argument.name, argument.required ? 'required' : '', argument.description];
                box.add_child(this._note(about.filter(Boolean).join(' · ')));
                if (argument.choices.length) {
                    box.add_child(this._dropdown(`Argument ${argument.name}`, argument.choices.map(name => ({ name })),
                        item => { argument.value = item.name; }, argument.value || 'Choose…'));
                } else {
                    box.add_child(this._textEntry({ text: argument.value || '',
                        hint: argument.required ? 'Required' : `Default ${argument.default || '(empty)'}`,
                        onChange: text => { argument.value = text; }, onActivate: go, onEscape: cancel }));
                }
            }
            if (draft.error)
                box.add_child(this._note(draft.error, true));
        } else {
            if (draft.argumentError)
                box.add_child(this._note(`Argument discovery: ${draft.argumentError}`));
            box.add_child(this._textEntry({
                text: draft.text,
                hint: 'Arguments: name:=value …, Enter to launch',
                focus: true,
                onChange: text => { draft.text = text; },
                onActivate: go,
                onEscape: cancel,
            }));
        }
        const savedHere = saved.find(item => item.file === draft.file);
        box.add_child(this._buttons([
            { label: 'Launch', onClick: go },
            {
                label: 'Save', onClick: () => {
                    this._helper(['save-launch', launchName(draft.file, args()), draft.file, ...args()], reply => {
                        if (reply.ok && this._status)
                            this._status.saved_launches = reply.saved_launches;
                        this._notes.launch = reply.ok ? null : { text: reply.error, error: true };
                        this._render();
                    });
                },
            },
            savedHere ? {
                label: `Forget ${savedHere.name}`, onClick: () => {
                    this._helper(['forget-launch', savedHere.name], reply => {
                        if (reply.ok && this._status)
                            this._status.saved_launches = reply.saved_launches;
                        this._render();
                    });
                },
            } : null,
            { label: 'Cancel', onClick: () => {
                this._launchDraft = null;
                this._render();
            } },
        ]));
        this._out.add_child(box);
    }

    // What the panel started that then exited by itself with an error.
    _addCrashes(status) {
        const history = (this._runs && this._runs.history) || status.history || [];
        const now = Date.now() / 1000;
        const crashes = history.filter(entry => entry.crashed && now - entry.ended < CRASH_SHOWN_S &&
            !this._dismissed.has(`${entry.pgid}:${entry.ended}`));
        for (const entry of crashes.slice(0, 3)) {
            const name = (entry.meta && entry.meta.name) || TOOL_NAMES[entry.tool] || entry.tool;
            const restartable = entry.tool !== 'bag' || (entry.meta && entry.meta.play);
            this._out.add_child(CC.makeRow({
                icon: 'dialog-error-symbolic',
                title: `${name} exited with code ${entry.returncode}`,
                subtitle: `${ago(entry.ended)} · after ${seconds(entry.ended - entry.started)}`,
                alert: true,
                actions: [
                    { label: 'Log', quiet: true, onClick: () => this._terminal('open-log', entry.tool) },
                    restartable ? { label: 'Restart', quiet: true, onClick: () => this._restart(entry) } : null,
                    {
                        label: 'Dismiss', quiet: true, onClick: () => {
                            this._dismissed.add(`${entry.pgid}:${entry.ended}`);
                            this._render();
                        },
                    },
                ].filter(Boolean),
            }));
        }
    }

    _addBags(status) {
        const recording = (this._runs && this._runs.running) ? this._runs.recording : status.recording;
        const runs = ((this._runs && this._runs.running) || status.runs || {}).bag || [];
        const playing = runs.find(run => run.meta && run.meta.play);
        const note = this._notes.bag;
        const picking = this._expanded.has('bag:topics') && this._graph && !(recording || playing);
        const topics = picking ? this._graph.topics.filter(topic => !topic.system) : [];
        // Opening the picker starts from what the list shows; made before the
        // subtitle, so the row says "Records N chosen topics" straight away.
        if (picking && !this._bagTopics)
            this._bagTopics = new Set(topics.filter(topic => this._matches(topic)).map(topic => topic.name));
        let subtitle;
        if (this._isArmed('bag:record')) {
            const chosen = this._topicsToRecord();
            subtitle = `Confirm to record ${chosen ? plural(chosen.length, 'topic') : 'every topic'} ` +
                `to ${status.bag_dir.replace(GLib.get_home_dir(), '~')}`;
        } else if (note)
            subtitle = note.text;
        else if (recording)
            subtitle = `Recording ${this._recordingTopics(recording)} · ${bytes(recording.size || 0)} · ` +
                `${seconds(Date.now() / 1000 - (recording.started || Date.now() / 1000))}`;
        else if (playing)
            subtitle = `Playing ${playing.meta.name}`;
        else
            subtitle = `Records ${this._searchText ? 'the topics the search shows' : 'every topic shown below'}` +
                `${status.bag_free ? ` · ${bytes(status.bag_free)} free` : ''}`;
        const busy = !!(recording || playing);
        const paused = runs.some(run => run.paused);
        const pausable = !!playing || !!status.bag_recording_pauses;
        if (busy && paused && !note)
            subtitle = `Paused · ${subtitle}`;
        else if (!busy && !note && this._bagTopics && !this._isArmed('bag:record'))
            subtitle = `Records ${plural(this._bagTopics.size, 'chosen topic')}`;
        this._out.add_child(CC.makeRow({
            icon: 'media-record-symbolic',
            title: 'Rosbag',
            subtitle,
            alert: !!(note && note.error),
            active: busy,
            actions: busy ? [
                { label: 'Log', quiet: true, onClick: () => this._openLogView('bag') },
                pausable ? { label: paused ? 'Resume' : 'Pause', quiet: true,
                    onClick: () => this._bagControl(paused ? 'resume' : 'pause') } : null,
                { label: 'Stop', onClick: () => this._stop('bag') },
            ].filter(Boolean) : [
                { label: 'Topics', quiet: true, onClick: () => this._toggle('bag:topics') },
                { label: this._isArmed('bag:record') ? 'Confirm' : 'Record', quiet: true, onClick: () => this._recordTopics() },
            ],
        }));
        if (picking) {
            for (const topic of topics) {
                const selected = this._bagTopics.has(topic.name);
                this._out.add_child(this._smallButton(`${selected ? '✓' : '○'} ${topic.name}`, () => {
                    if (selected)
                        this._bagTopics.delete(topic.name);
                    else
                        this._bagTopics.add(topic.name);
                    this._render();
                }, 'adaptive-ros-select'));
            }
            this._out.add_child(this._buttons([
                { label: 'All', onClick: () => { this._bagTopics = new Set(topics.map(topic => topic.name)); this._render(); } },
                { label: 'None', onClick: () => { this._bagTopics = new Set(); this._render(); } },
                { label: 'What the list shows', onClick: () => { this._bagTopics = null; this._toggle('bag:topics'); } },
            ]));
        }
        for (const bag of status.bags || []) {
            const parts = [];
            if (bag.duration_s !== undefined)
                parts.push(seconds(bag.duration_s));
            if (bag.messages !== undefined)
                parts.push(plural(bag.messages, 'message'));
            if (bag.topics !== undefined)
                parts.push(plural(bag.topics, 'topic'));
            parts.push(bytes(bag.size || 0));
            this._out.add_child(CC.makeRow({
                icon: 'folder-symbolic',
                title: bag.name,
                subtitle: parts.join(' · '),
                actions: [
                    busy ? null : { label: 'Play…', quiet: true, onClick: () => {
                        this._bagDraft = { path: bag.path, rate: '1', loop: false, clock: false };
                        this._render();
                    } },
                    { label: 'Folder', quiet: true, onClick: () => this._openFolder(bag.path) },
                ].filter(Boolean),
            }));
            if (this._bagDraft && this._bagDraft.path === bag.path) {
                const draft = this._bagDraft;
                this._out.add_child(this._textEntry({ text: draft.rate, hint: 'Playback speed · 0.1 to 10',
                    onChange: text => { draft.rate = text; } }));
                this._out.add_child(this._buttons([
                    { label: `${draft.loop ? '✓' : '○'} Loop`, onClick: () => { draft.loop = !draft.loop; this._render(); } },
                    { label: `${draft.clock ? '✓' : '○'} Publish clock`, onClick: () => { draft.clock = !draft.clock; this._render(); } },
                    { label: 'Start playback', onClick: () => this._playBag(bag.path, draft) },
                    { label: 'Cancel', onClick: () => { this._bagDraft = null; this._render(); } },
                ]));
            }
        }
    }

    // --------------------------------------------------------------- graph

    _addGraph(status, block) {
        if (this._watchError) {
            block('graph-error', [this._watchError], () => this._out.add_child(CC.makeRow({
                icon: 'dialog-warning-symbolic',
                title: 'Cannot see the ROS graph',
                subtitle: this._watchError,
                alert: true,
                action: { label: 'Retry', quiet: true, onClick: () => this._restartWatch() },
            })));
            return;
        }
        const graph = this._graph;
        if (!graph) {
            block('graph-wait', [status.domain, status.localhost], () => this._out.add_child(CC.makeRow({
                icon: CC.extensionIcon('ros-symbolic'),
                title: 'Looking for nodes…',
                subtitle: `Domain ${status.domain}${status.localhost ? ' · this computer only' : ''}`,
            })));
            return;
        }

        const filtered = {
            nodes: graph.nodes.filter(item => this._matches(item)),
            topics: graph.topics.filter(item => this._matches(item)),
            services: graph.services.filter(item => this._matches(item)),
            actions: graph.actions.filter(item => this._matches(item)),
        };
        const countLabel = (name, shown, total) =>
            `${name} · ${shown}${shown !== total ? ` of ${total}` : ''}`;
        const issues = this._issues(graph);
        const tfWarnings = this._tf && this._tf.data ? this._tf.data.warnings : [];

        block('health', [issues, graph.diagnostics, this._health, tfWarnings],
            () => this._addHealth(graph, issues, tfWarnings));
        block('favorites', [graph, status.favorites], () => this._addFavorites(graph));
        if (this._focus)
            block('focus', [graph.nodes, graph.topics], () => this._addFocus(graph));
        const plot = this._plot;
        if (plot)
            block('plot', [plot.topic, plot.field, plot.error, plot.done], () => this._addPlot(plot));

        const demo = status.tools.demo;
        const stopDemo = (demo.owned_pids || []).length
            ? { label: 'Stop demo', onClick: () => this._stop('demo') } : null;
        block('nodes', [filtered.nodes, graph.topics, graph.services, graph.actions, graph.nodes.length,
            demo, status.domain, status.localhost], () => {
            this._section('nodes', countLabel('Nodes', filtered.nodes.length, graph.nodes.length), () => {
                if (!filtered.nodes.length) {
                    this._out.add_child(CC.makeRow({
                        icon: CC.extensionIcon('ros-symbolic'),
                        title: this._searchText ? 'No nodes match the search' : `No nodes on domain ${status.domain}`,
                        subtitle: this._searchText ? 'Try a node, namespace, topic or type'
                            : status.localhost ? 'Only this computer is searched (localhost only)'
                                : 'Nothing is running on this domain',
                        action: demo.installed && !demo.pids.length ? {
                            label: 'Start demo', quiet: true, onClick: () => this._launch('demo'),
                        } : null,
                    }));
                }
                this._paged('nodes', filtered.nodes, node => {
                    this._out.add_child(this._nodeRow(node));
                    if (this._expanded.has(`node:${node.name}`))
                        this._out.add_child(this._nodeDetails(node));
                });
            }, stopDemo);
        });

        const lifecycleNodes = graph.nodes.filter(node => node.lifecycle);
        if (lifecycleNodes.length > 1)
            block('lifecycle', [lifecycleNodes.map(node => node.name)], () => this._addLifecycleGroup(lifecycleNodes));

        block('topics', [filtered.topics, graph.topics.length], () => {
            this._section('topics', countLabel('Topics', filtered.topics.length, graph.topics.length), () => {
                if (this._hasPlotJuggler() && filtered.topics.some(t => t.publishers.length))
                    this._out.add_child(this._note('Tap + on topics to plot several together in PlotJuggler'));
                const ordered = [...filtered.topics.filter(t => !t.system), ...filtered.topics.filter(t => t.system)];
                this._paged('topics', ordered, topic => this._addTopic(topic));
            });
        });
        block('services', [filtered.services, graph.services.length], () => {
            this._section('services', countLabel('Services', filtered.services.length, graph.services.length), () => {
                this._paged('services', filtered.services, service =>
                    this._addEndpoint('service', service, 'system-run-symbolic', 'served by', 'called by'));
            });
        });
        block('actions', [filtered.actions, graph.actions.length], () => {
            this._section('actions', countLabel('Actions', filtered.actions.length, graph.actions.length), () => {
                this._paged('actions', filtered.actions, action =>
                    this._addEndpoint('action', action, 'media-playback-start-symbolic', 'served by', 'used by'));
            });
        });
        const hasTf = graph.topics.some(topic => topic.name === '/tf' || topic.name === '/tf_static');
        if (hasTf)
            block('tf', [this._tf], () => this._addTf());
        if (graph.controllers)
            block('controllers', [graph.controllers], () => this._addControllers(graph.controllers));

        block('footer', [graph.hidden], () => {
            const hidden = graph.hidden;
            const folded = [];
            if (hidden.nodes)
                folded.push(plural(hidden.nodes, 'hidden node'));
            if (hidden.parameter_services)
                folded.push(plural(hidden.parameter_services, 'parameter service'));
            this._out.add_child(new St.Label({
                text: `${folded.length ? `Not listed: ${folded.join(', ')} · ` : ''}Live · click a name to copy it`,
                style_class: 'adaptive-network-note',
            }));
        });
    }

    // At most a page of rows; a button shows the next.
    _paged(id, items, add) {
        const shown = this._pages.get(id) || PAGE_ROWS;
        for (const item of items.slice(0, shown))
            add(item);
        if (items.length > shown) {
            const more = Math.min(PAGE_ROWS, items.length - shown);
            const bar = new St.BoxLayout({ style_class: 'adaptive-ros-more', x_expand: true });
            bar.add_child(new St.Label({
                text: `${items.length - shown} more`,
                style_class: 'adaptive-ros-hint',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            }));
            bar.add_child(this._smallButton(`Show ${more} more`, () => {
                this._pages.set(id, shown + PAGE_ROWS);
                this._render();
            }));
            this._out.add_child(bar);
        }
    }

    // What looks wrong in the graph itself, without asking anything more.
    _issues(graph) {
        const issues = [];
        for (const node of graph.nodes) {
            if (node.copies > 1)
                issues.push({ error: true, kind: 'node', name: node.name, text: `${node.copies} nodes are called ${node.name}` });
        }
        for (const topic of graph.topics) {
            if (!topic.publishers.length && topic.subscribers.length && !topic.system) {
                issues.push({ kind: 'topic', name: topic.name,
                    text: `${topic.name}: ${names(topic.subscribers)} listen${topic.subscribers.length === 1 ? 's' : ''}, nobody publishes` });
            }
        }
        for (const [kind, list, verb] of [['service', graph.services, 'call'], ['action', graph.actions, 'use']]) {
            for (const item of list) {
                if (!item.servers.length && item.clients.length) {
                    issues.push({ kind, name: item.name,
                        text: `${item.name}: ${names(item.clients)} ${verb}${item.clients.length === 1 ? 's' : ''} it, no server` });
                }
            }
        }
        return issues;
    }

    _addHealth(graph, issues, tfWarnings) {
        const diagnostics = graph.diagnostics || {};
        const counts = diagnostics.counts || {};
        const qos = (this._health && this._health.data && this._health.data.qos) || [];
        const troubled = (diagnostics.items || []).filter(item => item.level >= 1);
        const total = issues.length + qos.length + troubled.length + tfWarnings.length;
        const errors = issues.filter(i => i.error).length + qos.length + (counts.error || 0) + (counts.stale || 0);
        const summary = !total ? 'OK' : errors ? `${plural(total, 'issue')}, ${errors} serious` : plural(total, 'issue');
        this._section('health', `Health · ${summary}`, () => {
            const issueRow = (icon, text, alert, item = null) => this._out.add_child(CC.makeRow({
                icon,
                title: text,
                alert,
                action: item ? { label: 'Find', quiet: true, onClick: () => this._find(item.kind, item.name) } : null,
            }));
            for (const issue of issues)
                issueRow(issue.error ? 'dialog-error-symbolic' : 'dialog-warning-symbolic', issue.text, !!issue.error, issue);
            if (this._health && this._health.busy && !this._health.data)
                this._out.add_child(this._note('Checking QoS on every topic…'));
            else if (this._health && this._health.error)
                this._out.add_child(this._note(this._health.error, true));
            for (const item of qos)
                issueRow('dialog-error-symbolic', `QoS on ${item.topic}: ${item.warning}`, true, { kind: 'topic', name: item.topic });
            for (const warning of tfWarnings)
                issueRow('dialog-warning-symbolic', `TF: ${warning}`, false);
            if (diagnostics.available || (diagnostics.items || []).length) {
                this._out.add_child(new St.Label({
                    text: `Diagnostics · ${counts.ok || 0} OK, ${counts.warn || 0} warning, ` +
                        `${counts.error || 0} error, ${counts.stale || 0} stale`,
                    style_class: 'adaptive-ros-group adaptive-ros-group-row',
                }));
                const labels = ['OK', 'Warning', 'Error', 'Stale'];
                for (const item of (diagnostics.items || []).filter(i => this._matches(i))) {
                    this._out.add_child(CC.makeRow({
                        icon: item.level >= 2 ? 'dialog-error-symbolic'
                            : item.level === 1 ? 'dialog-warning-symbolic' : 'emblem-ok-symbolic',
                        title: item.name,
                        subtitle: `${labels[item.level] || 'Error'}${item.message ? ` · ${item.message}` : ''}`,
                        alert: item.level >= 2,
                    }));
                }
            }
            if (!total && !(diagnostics.items || []).length) {
                this._out.add_child(CC.makeRow({
                    icon: 'emblem-ok-symbolic',
                    title: 'Nothing looks wrong',
                    subtitle: 'Every listened topic has a publisher and every client a server',
                }));
            }
        }, null, () => this._fetchHealth());
    }

    // Starred items as a compact dashboard; one gone from the graph says so.
    _addFavorites(graph) {
        const favorites = (this._status.favorites || []).filter(item => this._matches(item));
        if (!favorites.length)
            return;
        this._section('favorites', `Favourites · ${favorites.length}`, () => {
            for (const item of favorites) {
                const found = (graph[`${item.kind}s`] || []).find(candidate => candidate.name === item.name);
                let subtitle = title(item.kind);
                if (!found) {
                    subtitle = `${subtitle} · not in the graph now`;
                } else if (item.kind === 'node') {
                    subtitle = `Node · ${plural(found.publishers.length, 'publisher')} · ` +
                        `${plural(found.subscribers.length, 'subscriber')}`;
                } else if (item.kind === 'topic') {
                    const rate = this._rates.get(item.name);
                    subtitle = rate && rate.data ? rateText(rate.data)
                        : `Topic · ${plural(found.publishers.length, 'publisher')} · ${plural(found.subscribers.length, 'subscriber')}`;
                } else {
                    subtitle = found.servers.length ? `${title(item.kind)} · served by ${names(found.servers)}`
                        : `${title(item.kind)} · no server`;
                    const called = item.kind === 'service' ? this._quickCallText(item.name) : null;
                    if (called)
                        subtitle = called[0];
                }
                const quick = item.kind === 'service' && found ? this._quickCallAction(found) : null;
                const row = CC.makeRow({
                    icon: 'starred-symbolic',
                    title: item.name,
                    subtitle,
                    alert: !found || !!(item.kind === 'service' && (this._quickCallText(item.name) || [])[1]),
                    actions: [
                        quick,
                        item.kind === 'topic' && found && found.publishers.length
                            ? { label: 'Hz', quiet: true, onClick: () => this._measure(item.name) } : null,
                        found ? { label: 'Find', quiet: true, onClick: () => this._find(item.kind, item.name) } : null,
                    ].filter(Boolean),
                });
                row.get_child().add_child(this._favoriteButton(item.kind, item.name));
                this._out.add_child(row);
            }
        });
    }

    // The TF tree, indented under each root: static frames, the rate and age
    // of moving ones.
    _addTf() {
        const tf = this._tf;
        const frames = tf && tf.data ? tf.data.frames : [];
        const text = `TF tree${frames.length ? ` · ${plural(frames.length, 'frame')}` : ''}`;
        this._section('tf', text, () => {
            if (!tf || tf.busy) {
                this._out.add_child(CC.makeRow({
                    icon: 'view-refresh-symbolic',
                    title: tf ? 'Reading TF…' : 'Read the TF tree',
                    subtitle: 'Listens to /tf and /tf_static for 1.5 seconds',
                }));
                return;
            }
            if (tf.error) {
                this._out.add_child(CC.makeRow({
                    icon: 'dialog-warning-symbolic', title: 'Cannot read TF', subtitle: tf.error, alert: true,
                }));
                return;
            }
            const children = new Map();
            for (const frame of frames) {
                if (!children.has(frame.parent))
                    children.set(frame.parent, []);
                children.get(frame.parent).push(frame);
            }
            let rows = 0;
            const add = (name, depth, frame) => {
                if (rows++ >= TF_ROWS)
                    return;
                const line = new St.BoxLayout({ style_class: 'adaptive-ros-tf-row', x_expand: true });
                line.set_style(`padding-left: ${12 + depth * 14}px;`);
                const button = this._copyName(name);
                line.add_child(button);
                let meta = depth ? '' : 'root';
                if (frame)
                    meta = frame.static ? 'static' : `${frame.hz} Hz${frame.age_ms !== undefined ? ` · ${frame.age_ms} ms old` : ''}`;
                line.add_child(new St.Label({
                    text: meta,
                    style_class: frame && frame.age_ms > 1000 ? 'adaptive-ros-meta adaptive-network-warn' : 'adaptive-ros-meta',
                    y_align: Clutter.ActorAlign.CENTER,
                }));
                this._out.add_child(line);
                for (const child of children.get(name) || [])
                    add(child.child, depth + 1, child);
            };
            for (const root of tf.data.roots)
                add(root, 0, null);
            if (!frames.length)
                this._out.add_child(this._note('No transforms arrived'));
            if (rows > TF_ROWS || tf.data.truncated)
                this._out.add_child(this._note(`Showing ${Math.min(rows, TF_ROWS)} frames`));
            if (frames.length)
                this._addTfLookup(frames, tf.data.roots);
        }, { label: tf && !tf.busy ? 'Read again' : 'Read', onClick: () => this._fetchTf() },
        () => {
            if (!this._tf)
                this._fetchTf();
        });
    }

    // Pick two frames: are they connected, and where is one in the other.
    _addTfLookup(frames, roots) {
        const parent = new Map(frames.map(frame => [frame.child, frame.parent]));
        const rootOf = name => {
            const seen = new Set();
            while (parent.has(name) && !seen.has(name)) {
                seen.add(name);
                name = parent.get(name);
            }
            return name;
        };
        const choices = [...new Set([...roots, ...frames.map(frame => frame.child)])].sort().map(name => ({ name }));
        const lookup = this._tfLookup || { source: '', target: '' };
        const pick = which => item => {
            this._tfLookup = { source: lookup.source, target: lookup.target, [which]: item.name };
        };
        this._out.add_child(new St.Label({ text: 'Where one frame is in another', style_class: 'adaptive-ros-group' }));
        this._out.add_child(this._dropdown('Frame', choices, pick('source'), lookup.source || 'Choose…'));
        this._out.add_child(this._dropdown('Seen from', choices, pick('target'), lookup.target || 'Choose…'));
        if (!lookup.source || !lookup.target)
            return;
        if (lookup.source === lookup.target) {
            this._out.add_child(this._note('Choose two different frames'));
            return;
        }
        const [a, b] = [rootOf(lookup.source), rootOf(lookup.target)];
        if (a !== b) {
            this._out.add_child(this._note(`Not connected: ${lookup.source} is in the ${a} tree, ` +
                `${lookup.target} in the ${b} tree`, true));
            return;
        }
        const reply = lookup.reply;
        if (reply && reply.error) {
            this._out.add_child(this._note(reply.error, true));
        } else if (reply) {
            const fixed = list => list.map(value => value.toFixed(3)).join('  ');
            const lines = [
                `Position  ${fixed(reply.translation)} m`,
                `Roll, pitch, yaw  ${fixed(reply.rpy)}°`,
                `Quaternion  ${fixed(reply.rotation)}`,
                reply.age_ms === null || reply.age_ms === undefined ? 'Static' : `${reply.age_ms} ms old`,
            ];
            const label = new St.Label({ text: lines.join('\n'), style_class: 'adaptive-ros-definition' });
            this._out.add_child(label);
        }
        this._out.add_child(this._buttons([{
            label: lookup.busy ? 'Looking up…' : reply ? 'Look up again' : 'Look up',
            onClick: () => this._lookupTf(),
        }]));
    }

    _lookupTf() {
        const lookup = this._tfLookup;
        if (!lookup || lookup.busy)
            return;
        lookup.busy = true;
        lookup.reply = null;
        this._request('tf_lookup', { source: lookup.source, target: lookup.target }, reply => {
            if (this._tfLookup !== lookup)
                return;
            this._tfLookup = { source: lookup.source, target: lookup.target, busy: false, reply };
            this._queueRender();
        });
        this._render();
    }

    // One transition for several lifecycle nodes, and how each one took it.
    _addLifecycleGroup(nodes) {
        this._section('lifecycle', `Lifecycle group · ${plural(nodes.length, 'node')}`, () => {
            const outcome = this._lifecycleResult;
            for (const node of nodes) {
                const chosen = this._lifecycleSelection.has(node.name);
                const result = outcome && outcome.results ? outcome.results[node.name] : undefined;
                const after = result === undefined ? '' : result ? ` · ${outcome.transition} done` : ` · turned ${outcome.transition} down`;
                this._out.add_child(this._smallButton(`${chosen ? '✓' : '○'} ${node.name}${after}`, () => {
                    if (chosen)
                        this._lifecycleSelection.delete(node.name);
                    else
                        this._lifecycleSelection.add(node.name);
                    this._render();
                }, result === false ? 'adaptive-ros-select adaptive-network-warn' : 'adaptive-ros-select'));
            }
            const chosen = nodes.map(node => node.name).filter(name => this._lifecycleSelection.has(name));
            this._out.add_child(this._buttons([
                { label: 'All', onClick: () => { nodes.forEach(node => this._lifecycleSelection.add(node.name)); this._render(); } },
                { label: 'None', onClick: () => { this._lifecycleSelection.clear(); this._render(); } },
            ]));
            if (!chosen.length) {
                this._out.add_child(this._note('Tick the nodes, then choose a transition'));
            } else {
                this._out.add_child(this._buttons(GROUP_TRANSITIONS.map(transition => {
                    const armed = this._isArmed(`lifecycle-group:${transition}`);
                    return { label: armed ? `Confirm ${transition} ${chosen.length}` : title(transition), armed,
                        onClick: () => this._lifecycleGroup(transition, chosen) };
                })));
            }
            if (outcome && outcome.busy)
                this._out.add_child(this._note(`${title(outcome.transition)}…`));
            else if (outcome && outcome.error)
                this._out.add_child(this._note(outcome.error, true));
        });
    }

    _lifecycleGroup(transition, names) {
        this._confirmed(`lifecycle-group:${transition}`, () => {
            this._lifecycleResult = { busy: true, transition };
            this._request('lifecycle_group', { nodes: names, transition }, reply => {
                this._lifecycleResult = { transition, results: reply.results || {}, error: reply.error || '' };
                for (const node of this._graph ? this._graph.nodes : []) {
                    if (names.includes(node.name) && this._expanded.has(`node:${node.name}`))
                        this._fetchNode(node);
                }
                this._queueRender();
            }, CALL_REPLY_TIMEOUT_MS);
        });
    }

    // A node with the topics in and out of it, or a topic with the nodes on
    // either end; a click on a neighbour moves the focus there.
    _focusOn(kind, name) {
        const back = this._focus ? [...this._focus.back, { kind: this._focus.kind, name: this._focus.name }] : [];
        this._focus = { kind, name, back: back.slice(-10) };
        this._expanded.add('section:focus');
        this._scrollToBlock = 'focus';
        this._render();
    }

    _addFocus(graph) {
        const focus = this._focus;
        const topics = new Map(graph.topics.map(topic => [topic.name, topic]));
        const node = focus.kind === 'node' ? graph.nodes.find(item => item.name === focus.name) : null;
        const topic = focus.kind === 'topic' ? topics.get(focus.name) : null;
        const goBack = () => {
            const previous = focus.back[focus.back.length - 1];
            this._focus = previous ? { ...previous, back: focus.back.slice(0, -1) } : null;
            this._render();
        };
        this._section('focus', `Graph view · ${focus.name}`, () => {
            if (!node && !topic) {
                this._out.add_child(this._note(`${focus.name} is no longer in the graph`));
                return;
            }
            const side = (heading, items, empty) => {
                this._out.add_child(new St.Label({ text: heading, style_class: 'adaptive-ros-group' }));
                if (!items.length)
                    this._out.add_child(this._note(empty));
                for (const item of items) {
                    const line = new St.BoxLayout({ style_class: 'adaptive-ros-focus-row', x_expand: true });
                    const button = this._smallButton(item.name, () => this._focusOn(item.kind, item.name), 'adaptive-ros-name');
                    button.get_child().ellipsize = Pango.EllipsizeMode.MIDDLE;
                    line.add_child(button);
                    if (item.meta) {
                        const meta = new St.Label({ text: item.meta, style_class: 'adaptive-ros-meta', x_expand: true,
                            y_align: Clutter.ActorAlign.CENTER });
                        meta.clutter_text.ellipsize = Pango.EllipsizeMode.END;
                        line.add_child(meta);
                    }
                    this._out.add_child(line);
                }
            };
            const peers = (list, own) => (list || []).filter(name => name !== own);
            if (node) {
                side('In ↓  topics it subscribes to', node.subscribers.map(t => {
                    const from = peers((topics.get(t.name) || {}).publishers, node.name);
                    return { kind: 'topic', name: t.name, meta: from.length ? `from ${names(from)}` : 'nobody publishes it' };
                }), 'Subscribes to nothing');
                this._out.add_child(new St.Label({ text: `●  ${node.name}`, style_class: 'adaptive-ros-focus-centre' }));
                side('Out ↓  topics it publishes', node.publishers.map(t => {
                    const to = peers((topics.get(t.name) || {}).subscribers, node.name);
                    return { kind: 'topic', name: t.name, meta: to.length ? `to ${names(to)}` : 'no subscribers' };
                }), 'Publishes nothing');
            } else {
                side('In ↓  publishers', topic.publishers.map(name => ({ kind: 'node', name })), 'Nobody publishes it');
                this._out.add_child(new St.Label({ text: `●  ${topic.name} · ${topic.types.join(', ')}`,
                    style_class: 'adaptive-ros-focus-centre' }));
                side('Out ↓  subscribers', topic.subscribers.map(name => ({ kind: 'node', name })), 'Nobody subscribes');
            }
        }, { label: focus.back.length ? 'Back' : 'Close', onClick: goBack });
    }

    // A heading that folds the rows `fill` adds under it.
    _section(id, text, fill, extra = null, onOpen = null) {
        const key = `section:${id}`;
        const searching = !!this._searchText && SEARCHED.has(id);
        const open = searching ? !this._searchFolded.has(key) : this._expanded.has(key);
        const heading = new St.BoxLayout({ style_class: 'adaptive-tasks-heading adaptive-ros-section', x_expand: true });
        const content = new St.BoxLayout({ style_class: 'adaptive-ros-section-box' });
        content.add_child(new St.Icon({
            icon_name: open ? 'pan-down-symbolic' : 'pan-end-symbolic',
            style_class: 'adaptive-ros-chevron',
            y_align: Clutter.ActorAlign.CENTER,
        }));
        content.add_child(new St.Label({
            text,
            style_class: 'adaptive-cc-list-heading',
            y_align: Clutter.ActorAlign.CENTER,
        }));
        const toggle = new St.Button({
            style_class: 'adaptive-ros-section-toggle',
            child: content,
            can_focus: true,
            x_expand: true,
            x_align: Clutter.ActorAlign.START,
            accessible_name: open ? `Fold ${id}` : `Unfold ${id}`,
        });
        toggle.connect('clicked', () => {
            if (!searching) {
                this._toggle(key, onOpen);
            } else {
                if (open)
                    this._searchFolded.add(key);
                else
                    this._searchFolded.delete(key);
                this._render();
            }
        });
        heading.add_child(toggle);
        if (extra)
            heading.add_child(this._smallButton(extra.label, extra.onClick));
        this._out.add_child(heading);
        if (open)
            fill();
    }

    // A row with an expand button at its end; the whole row toggles too.
    _expandable(key, row, onOpen = null) {
        const open = this._expanded.has(key);
        const expand = CC.makeRoundButton(open ? 'pan-down-symbolic' : 'pan-end-symbolic',
            open ? 'Show less' : 'Show more', () => this._toggle(key, onOpen), 'adaptive-ros-expand');
        row.get_child().add_child(expand);
        return row;
    }

    _nodeRow(node) {
        const key = `node:${node.name}`;
        const parts = [];
        const count = (list, one, many) => {
            if (list.length)
                parts.push(plural(list.length, one, many));
        };
        count(node.publishers, 'publisher');
        count(node.subscribers, 'subscriber');
        count(node.services, 'service');
        count(node.clients, 'client');
        count(node.action_servers, 'action server');
        count(node.action_clients, 'action client');
        let subtitle = parts.join(' · ') || 'No topics, services or actions';
        if (node.lifecycle)
            subtitle = `Lifecycle · ${subtitle}`;
        if (node.copies > 1)
            subtitle = `${node.copies} nodes share this name · ${subtitle}`;
        const row = CC.makeRow({
            icon: CC.extensionIcon('ros-node-symbolic'),
            title: node.name,
            subtitle,
            alert: node.copies > 1,
            onActivate: () => this._toggle(key, () => this._fetchNode(node)),
        });
        row.get_child().add_child(this._favoriteButton('node', node.name));
        return this._expandable(key, row, () => this._fetchNode(node));
    }

    _fetchNode(node) {
        this._fetch(this._details, `node:${node.name}`, 'node', { name: node.name });
    }

    _nodeDetails(node) {
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-detail', vertical: true, x_expand: true });
        const detail = this._details.get(`node:${node.name}`) || { busy: true };
        const data = detail.data || {};
        const qos = data.qos || {};
        const graph = this._graph;
        const byName = list => new Map(list.map(item => [item.name, item]));
        const topics = byName(graph.topics);
        const services = byName(graph.services);
        const actions = byName(graph.actions);
        const others = list => (list || []).filter(name => name !== node.name);
        const where = `node:${node.name}`;

        const group = (label, items, entry) => {
            if (!items.length)
                return;
            box.add_child(new St.Label({ text: label, style_class: 'adaptive-ros-group' }));
            for (const item of items)
                box.add_child(entry(item));
        };
        const qosText = name => {
            const q = qos[name];
            return q ? `${q.reliability} · ${q.durability}` : '';
        };

        group('Publishes', node.publishers, t => {
            const peers = others((topics.get(t.name) || {}).subscribers);
            return this._entry(where, t.name, t.types, [
                peers.length ? `to ${names(peers)}` : 'no subscribers', qosText(`publishers:${t.name}`),
            ], { rate: true, sample: true });
        });
        group('Subscribes', node.subscribers, t => {
            const peers = others((topics.get(t.name) || {}).publishers);
            return this._entry(where, t.name, t.types, [
                peers.length ? `from ${names(peers)}` : 'nobody publishes it', qosText(`subscribers:${t.name}`),
            ], { rate: peers.length > 0, sample: peers.length > 0, warn: !peers.length });
        });
        group('Services', node.services, s => {
            const peers = others((services.get(s.name) || {}).clients);
            return this._entry(where, s.name, s.types, [peers.length ? `called by ${names(peers)}` : '']);
        });
        group('Calls', node.clients, s => {
            const peers = others((services.get(s.name) || {}).servers);
            return this._entry(where, s.name, s.types, [peers.length ? `served by ${names(peers)}` : 'no server'],
                { warn: !peers.length });
        });
        group('Action servers', node.action_servers, a => {
            const peers = others((actions.get(a.name) || {}).clients);
            return this._entry(where, a.name, a.types, [peers.length ? `used by ${names(peers)}` : '']);
        });
        group('Action clients', node.action_clients, a => {
            const peers = others((actions.get(a.name) || {}).servers);
            return this._entry(where, a.name, a.types, [peers.length ? `served by ${names(peers)}` : 'no server'],
                { warn: !peers.length });
        });

        box.add_child(this._buttons([{ label: 'Show in the graph view', onClick: () => this._focusOn('node', node.name) }]));

        if (node.lifecycle) {
            box.add_child(new St.Label({ text: 'Lifecycle', style_class: 'adaptive-ros-group' }));
            const state = data.lifecycle;
            const line = new St.BoxLayout({ style_class: 'adaptive-ros-buttons', x_expand: true });
            line.add_child(new St.Label({
                text: detail.busy ? 'Asking…' : state ? title(state) : 'Did not answer',
                style_class: `adaptive-ros-param ${LIFECYCLE_CLASSES[state] || ''}`.trim(),
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            }));
            if (!detail.busy && state) {
                line.add_child(this._buttons((LIFECYCLE_NEXT[state] || []).map(transition => {
                    const armed = this._isArmed(`lifecycle:${node.name}:${transition}`);
                    return { label: armed ? `Confirm ${transition}` : title(transition), armed,
                        onClick: () => this._lifecycle(node, transition) };
                })));
            }
            box.add_child(line);
        }
        if (node.parameter_services) {
            box.add_child(new St.Label({ text: 'Parameters · click a value to change it', style_class: 'adaptive-ros-group' }));
            const profiles = (this._status.parameter_profiles || []).filter(profile => profile.node === node.name);
            const controls = new St.BoxLayout({ vertical: true, x_expand: true });
            if (profiles.length)
                controls.add_child(this._dropdown(`Parameter profile ${node.name}`, profiles,
                    profile => this._compareParameterProfile(node.name, profile.name), 'Compare and restore…'));
            const diff = this._paramDiff && this._paramDiff.node === node.name ? this._paramDiff : null;
            if (diff)
                this._addParameterDiff(controls, diff);
            if (this._paramProfileDraft && this._paramProfileDraft.node === node.name) {
                controls.add_child(this._textEntry({ text: this._paramProfileDraft.name, hint: 'Profile name', focus: true,
                    onChange: text => { this._paramProfileDraft.name = text; },
                    onActivate: text => this._parameterProfile('save', node.name, text),
                    onEscape: () => { this._paramProfileDraft = null; this._render(); } }));
            } else {
                controls.add_child(this._smallButton('Save parameter profile', () => {
                    this._paramProfileDraft = { node: node.name, name: node.name.split('/').pop() || 'parameters' };
                    this._render();
                }));
            }
            box.add_child(controls);
            if (detail.busy) {
                box.add_child(this._note('Reading…'));
            } else if (data.parameters) {
                box.add_child(this._parameters(data.parameters, node));
                if (data.parameters_truncated)
                    box.add_child(this._note(`Showing ${data.parameters.length} of ${data.parameter_total} parameters`));
            } else if (!detail.error) {
                box.add_child(this._note('Did not answer in time'));
            }
        }
        if (node.enclave && node.enclave !== '/') {
            box.add_child(new St.Label({ text: 'Enclave', style_class: 'adaptive-ros-group' }));
            box.add_child(new St.Label({ text: node.enclave, style_class: 'adaptive-ros-param' }));
        }
        if (detail.error)
            box.add_child(this._note(detail.error, true));
        const note = this._notes[`op:${node.name}`];
        if (note)
            box.add_child(this._note(note.text, note.error));
        return box;
    }

    _compareParameterProfile(node, name) {
        const diff = { node, name, busy: true };
        this._paramDiff = diff;
        this._helper(['parameter-profile', 'diff', node, name], reply => {
            if (this._paramDiff !== diff)
                return;
            this._paramDiff = { node, name, busy: false, error: reply.ok ? '' : reply.error,
                changes: reply.changes || [], unchanged: reply.unchanged || 0 };
            this._render();
        });
    }

    _addParameterDiff(box, diff) {
        if (diff.busy) {
            box.add_child(this._note(`Comparing ${diff.name} with the running node…`));
            return;
        }
        if (diff.error) {
            box.add_child(this._note(diff.error, true));
        } else {
            box.add_child(this._note(diff.changes.length
                ? `${diff.name} would change ${plural(diff.changes.length, 'parameter')}` +
                  `${diff.unchanged ? `; ${diff.unchanged} already match` : ''}`
                : `${diff.name} matches the node as it is`));
            const lines = diff.changes.map(change => change.missing
                ? `${change.name}: not declared now → ${valueText(change.saved)}`
                : `${change.name}: ${valueText(change.current)} → ${valueText(change.saved)}`);
            if (lines.length)
                box.add_child(new St.Label({ text: lines.join('\n'), style_class: 'adaptive-ros-definition' }));
        }
        const key = `param-profile:${diff.node}:${diff.name}`;
        const armed = this._isArmed(key);
        box.add_child(this._buttons([
            diff.changes && diff.changes.length ? { label: armed ? `Confirm restoring ${diff.name}` : 'Restore', armed,
                onClick: () => this._confirmed(key, () => this._parameterProfile('apply', diff.node, diff.name)) } : null,
            { label: 'Cancel', onClick: () => { this._paramDiff = null; this._render(); } },
        ]));
    }

    _parameterProfile(operation, node, name) {
        this._helper(['parameter-profile', operation, node, name.trim()], reply => {
            this._paramProfileDraft = null;
            this._paramDiff = null;
            if (reply.ok)
                this._status.parameter_profiles = reply.parameter_profiles;
            const skipped = reply.read_only ? `, ${reply.read_only} read-only left as they are` : '';
            this._notes[`op:${node}`] = reply.ok ? {
                text: operation === 'save' ? 'Parameter profile saved' : `Restored ${plural(reply.applied || 0, 'parameter')}${skipped}`,
            } : { text: reply.error, error: true };
            if (operation === 'apply' && reply.ok) {
                const graphNode = (this._graph.nodes || []).find(item => item.name === node);
                if (graphNode) this._fetchNode(graphNode);
            }
            this._render();
        });
    }

    // Values are buttons: a click edits one (in its own type), Enter arms
    // the change and a second Enter sends it. Long arrays are read-only.
    _parameters(parameters, node) {
        if (!parameters.length)
            return this._note('None');
        const grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({ column_spacing: 10, row_spacing: 1 }),
            x_expand: true,
        });
        const pageKey = `parameters:${node.name}`;
        const count = this._pages.get(pageKey) || 40;
        parameters.slice(0, count).forEach((parameter, row) => {
            const key = new St.Label({ text: parameter.name, style_class: 'adaptive-ros-param-key' });
            key.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
            grid.layout_manager.attach(key, 0, row, 1, 1);
            const draftKey = `${node.name}:${parameter.name}`;
            if (parameter.ptype === undefined) {
                grid.layout_manager.attach(this._smallButton(parameter.loading ? 'Reading…' : 'Read value', () => {
                    if (parameter.loading) return;
                    parameter.loading = true;
                    this._request('parameter', { node: node.name, name: parameter.name }, reply => {
                        parameter.loading = false;
                        if (!reply.error) Object.assign(parameter, reply);
                        else this._notes[`op:${node.name}`] = { text: reply.error, error: true };
                        this._render();
                    });
                    this._render();
                }), 1, row, 1, 1);
            } else if (this._parameterDraft && this._parameterDraft.key === draftKey) {
                const armed = this._isArmed(`parameter:${node.name}:${parameter.name}`);
                grid.layout_manager.attach(this._textEntry({
                    text: this._parameterDraft.text,
                    hint: PARAMETER_ARRAY.has(parameter.ptype) ? 'A list, like [1, 2, 3]' : 'The new value',
                    extraClass: armed ? 'adaptive-ros-parameter-entry adaptive-ros-armed-entry' : 'adaptive-ros-parameter-entry',
                    focus: true,
                    onChange: text => {
                        if (this._parameterDraft && this._parameterDraft.key === draftKey)
                            this._parameterDraft.text = text;
                    },
                    onActivate: text => this._setParameter(node, parameter, text),
                    onEscape: () => {
                        this._parameterDraft = null;
                        this._disarm();
                        this._render();
                    },
                }), 1, row, 1, 1);
                if (armed) {
                    grid.layout_manager.attach(new St.Label({
                        text: 'Enter again to set it',
                        style_class: 'adaptive-ros-meta adaptive-network-warn',
                        y_align: Clutter.ActorAlign.CENTER,
                    }), 2, row, 1, 1);
                }
            } else if (parameter.truncated) {
                const value = new St.Label({
                    text: `${valueText(parameter.value)} (${parameter.truncated} items)`,
                    style_class: 'adaptive-ros-param',
                });
                value.clutter_text.ellipsize = Pango.EllipsizeMode.END;
                grid.layout_manager.attach(value, 1, row, 1, 1);
            } else {
                const value = new St.Button({
                    label: valueText(parameter.value),
                    style_class: 'adaptive-ros-param adaptive-ros-param-edit',
                    can_focus: true,
                    x_expand: true,
                    x_align: Clutter.ActorAlign.START,
                    accessible_name: `Change parameter ${parameter.name}`,
                });
                value.connect('clicked', () => {
                    this._parameterDraft = { key: draftKey, text: draftText(parameter.value) };
                    this._disarm();
                    this._render();
                });
                grid.layout_manager.attach(value, 1, row, 1, 1);
            }
        });
        if (count < parameters.length)
            grid.layout_manager.attach(this._smallButton(`Show more · ${count} of ${parameters.length}`, () => {
                this._pages.set(pageKey, count + 40);
                this._render();
            }), 0, count, 2, 1);
        return grid;
    }

    // One topic, service or action inside an expanded row: its name (click
    // to copy), its types (click for the definition), what is on the other
    // end, and for topics Hz and Preview.
    _entry(where, name, types, meta, { rate = false, sample = false, warn = false } = {}) {
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-entry', vertical: true, x_expand: true });
        const top = new St.BoxLayout({ x_expand: true });
        top.add_child(this._copyName(name));
        if (rate)
            top.add_child(this._rateButton(name));
        if (sample)
            top.add_child(this._sampleButton(name));
        if (sample && types.length) {
            top.add_child(this._smallButton('Plot', () => this._hasPlotJuggler()
                ? this._openPlotJuggler([name]) : this._preparePlot(name, types[0]), 'adaptive-ros-rate'));
        }
        box.add_child(top);

        const bottom = new St.BoxLayout({ style_class: 'adaptive-ros-entry-meta', x_expand: true });
        for (const type of types)
            bottom.add_child(this._typeButton(where, type));
        const text = meta.filter(Boolean).join(' · ');
        if (text) {
            const label = new St.Label({
                text,
                style_class: warn ? 'adaptive-ros-meta adaptive-network-warn' : 'adaptive-ros-meta',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            label.clutter_text.ellipsize = Pango.EllipsizeMode.END;
            bottom.add_child(label);
        }
        box.add_child(bottom);

        const measured = this._rates.get(name);
        if (rate && measured && measured.error)
            box.add_child(this._note(measured.error, true));
        if (sample && this._samples.has(name))
            box.add_child(this._preview(this._samples.get(name)));
        if (this._plotDraft && this._plotDraft.topic === name) {
            const draft = this._plotDraft;
            if (draft.loading)
                box.add_child(this._note('Reading numeric fields…'));
            else if (draft.fields.length)
                box.add_child(this._dropdown(`Plot field ${name}`, draft.fields.map(path => ({ name: path })),
                    item => this._startPlot(name, item.name), draft.selected || 'Choose…'));
            else
                box.add_child(this._note(draft.error || 'This message has no numeric scalar fields', true));
        }
        for (const type of types) {
            if (this._expanded.has(`iface:${where}:${type}`))
                box.add_child(this._definition(type));
        }
        return box;
    }

    _preparePlot(topic, type) {
        const draft = { topic, type, fields: [], loading: true, error: '' };
        this._plotDraft = draft;
        this._request('template', { kind: 'topic', type }, reply => {
            if (this._plotDraft !== draft)
                return;
            draft.loading = false;
            draft.error = reply.error || '';
            draft.fields = (reply.fields || []).filter(field =>
                /^(u?int|float|double)/.test(field.type) && !field.type.includes('[') && !field.type.includes('sequence'))
                .map(field => field.path.join('/'));
            this._render();
        });
        this._render();
    }

    // A live strip of one numeric field; new values redraw it in place, so the
    // list is not rebuilt four times a second.
    _startPlot(topic, field) {
        this._stopPlot();
        const plot = { topic, field, values: [], count: 0, error: '', done: false, id: 0, strip: null, label: null };
        this._plot = plot;
        this._plotDraft = null;
        this._expanded.add('section:plot');
        this._scrollToBlock = 'plot';
        plot.id = this._request('plot', { name: topic, field }, reply => {
            if (this._plot !== plot)
                return;
            plot.id = 0;
            plot.done = true;
            plot.error = reply.error || '';
            this._queueRender();
        }, PLOT_REPLY_TIMEOUT_MS, progress => {
            if (this._plot !== plot)
                return;
            for (const [, value] of progress.values)
                plot.values.push(value);
            plot.values.splice(0, Math.max(0, plot.values.length - PLOT_SAMPLES));
            plot.count = progress.count;
            if (plot.strip)
                plot.strip.setValues(plot.values);
            if (plot.label)
                plot.label.text = this._plotText(plot);
        });
        this._render();
    }

    _stopPlot() {
        const plot = this._plot;
        this._plot = null;
        if (!plot || !plot.id)
            return;
        const pending = this._pending.get(plot.id);
        if (pending) {
            GLib.source_remove(pending.timeoutId);
            this._pending.delete(plot.id);
        }
        if (this._watch)
            this._request('cancel', { ids: [plot.id] }, () => {});
    }

    _plotText(plot) {
        const values = plot.values;
        if (!values.length)
            return plot.done ? 'No values arrived' : 'Waiting for messages…';
        const number = value => String(Number(value.toPrecision(5)));
        return `Now ${number(values[values.length - 1])} · low ${number(Math.min(...values))} · ` +
            `high ${number(Math.max(...values))} · ${plural(plot.count, 'message')}`;
    }

    _addPlot(plot) {
        this._section('plot', `Plot · ${plot.topic}/${plot.field}`, () => {
            const strip = new Sparkline.Sparkline(PLOT_ACCENT, 'range', PLOT_SAMPLES);
            strip.actor.add_style_class_name('adaptive-ros-plot');
            strip.setValues(plot.values);
            const label = new St.Label({ text: this._plotText(plot), style_class: 'adaptive-ros-meta' });
            plot.strip = strip;
            plot.label = label;
            // The block is rebuilt with the list; only the newest strip is fed.
            strip.actor.connect('destroy', () => {
                if (plot.strip === strip) {
                    plot.strip = null;
                    plot.label = null;
                }
            });
            this._out.add_child(strip.actor);
            this._out.add_child(label);
            if (plot.error)
                this._out.add_child(this._note(plot.error, true));
            const rqt = this._status.tools.plot && this._status.tools.plot.installed;
            this._out.add_child(this._buttons([
                rqt ? { label: 'Open in rqt_plot', onClick: () => this._openRqtPlot(`${plot.topic}/${plot.field}`) } : null,
                plot.done ? { label: 'Plot again', onClick: () => this._startPlot(plot.topic, plot.field) } : null,
                { label: plot.done ? 'Close' : 'Stop', onClick: () => {
                    this._stopPlot();
                    this._render();
                } },
            ]));
        });
    }

    // The larger plot in its own window.
    _openRqtPlot(expression) {
        this._helper(['plot', expression], reply => {
            if (reply.ok) {
                this._button.menu.close();
                this._pollRuns();
            } else if (this._plot) {
                this._plot.error = reply.error;
                this._render();
            }
        });
    }

    // The previewed message: an image as its thumbnail, else its fields.
    _preview(sampled) {
        const box = new St.BoxLayout({ vertical: true, x_expand: true });
        if (sampled.busy) {
            box.add_child(this._note('Waiting for a message…'));
            return box;
        }
        if (sampled.error) {
            box.add_child(this._note(sampled.error, true));
            return box;
        }
        const data = sampled.data;
        const facts = [data.type_name];
        if (data.age_ms !== undefined)
            facts.push(`${data.age_ms} ms old`);
        box.add_child(this._note(facts.join(' · ')));
        if (data.image) {
            // Shown at its own aspect, at most the thumbnail's width.
            const width = data.image_width || 240;
            const height = data.image_height ? Math.round(240 * data.image_height / width) : 180;
            const picture = new St.Widget({
                style_class: 'adaptive-ros-thumbnail',
                width: 240,
                height: Math.min(height, 240),
            });
            picture.set_style(`background-image: url("${data.image}");`);
            box.add_child(picture);
        } else if (data.image_error) {
            box.add_child(this._note(data.image_error, true));
        }
        const label = new St.Label({
            text: `${data.text}${data.truncated ? '\n…' : ''}`,
            style_class: 'adaptive-ros-definition',
        });
        box.add_child(wrapped(label));
        return box;
    }

    _copyName(name) {
        const label = new St.Label({ text: name, x_align: Clutter.ActorAlign.START });
        label.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
        const button = new St.Button({
            style_class: 'adaptive-ros-name',
            child: label,
            can_focus: true,
            x_expand: true,
            x_align: Clutter.ActorAlign.START,
        });
        button.connect('clicked', () => {
            copy(name);
            label.text = 'Copied';
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, COPIED_MS, () => {
                if (label.get_stage())
                    label.text = name;
                return GLib.SOURCE_REMOVE;
            });
        });
        return button;
    }

    _typeButton(where, type) {
        const open = this._expanded.has(`iface:${where}:${type}`);
        const button = new St.Button({
            style_class: open ? 'adaptive-ros-type adaptive-ros-type-open' : 'adaptive-ros-type',
            label: type,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        button.connect('clicked', () => this._toggleInterface(where, type));
        return button;
    }

    _rateButton(topic) {
        const rate = this._rates.get(topic);
        return this._smallButton(rate && rate.busy ? 'Measuring…' : rate && rate.data ? rateText(rate.data) : 'Hz',
            () => this._measure(topic), 'adaptive-ros-rate');
    }

    _sampleButton(topic) {
        const sample = this._samples.get(topic);
        return this._smallButton(sample && sample.busy ? 'Waiting…' : sample ? 'Hide' : 'Preview',
            () => this._sample(topic), 'adaptive-ros-rate');
    }

    _definition(type) {
        const known = this._interfaces.get(type) || { busy: true };
        const label = new St.Label({
            text: known.busy ? 'Reading…' : known.error || known.data.text,
            style_class: known.error ? 'adaptive-ros-definition adaptive-network-warn' : 'adaptive-ros-definition',
        });
        return wrapped(label);
    }

    // The fields to send, what sending does, and what came back.
    _composer(key, cmd, name, type, verb) {
        const composer = this._composers.get(key);
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-composer', vertical: true, x_expand: true });
        box.add_child(new St.Label({ text: `${verb} · request fields`, style_class: 'adaptive-ros-group' }));
        if (!composer.fields)
            box.add_child(this._note('Loading fields…'));
        else if (!composer.fields.length && !composer.error)
            box.add_child(this._note(cmd === 'publish' ? 'This message has no fields' : 'This request has no fields'));
        for (const field of composer.fields || []) {
            box.add_child(this._note(`${field.path.join('.')} · ${field.type}`));
            const isString = /^(w?string)(<|$)/.test(field.type);
            const update = value => {
                let target = composer.values;
                for (const part of field.path.slice(0, -1)) target = target[part];
                target[field.path[field.path.length - 1]] = value;
                composer.text = JSON.stringify(composer.values);
                this._disarm();
            };
            if (field.type === 'boolean' || field.type === 'bool') {
                box.add_child(this._dropdown(field.path.join('.'), [{ name: 'false' }, { name: 'true' }],
                    item => { field.value = item.name === 'true'; update(field.value); }, String(field.value)));
            } else {
                box.add_child(this._textEntry({ text: field.input === undefined ?
                    (isString ? String(field.value) : JSON.stringify(field.value)) : field.input,
                    hint: field.type.includes('sequence') || field.type.includes('[') ? '[value, …]' : field.type,
                    onChange: text => {
                        field.input = text;
                        try {
                            const value = isString ? text : JSON.parse(text);
                            field.invalid = false;
                            update(value);
                        } catch (_) { field.invalid = true; }
                        composer.error = composer.fields.some(f => f.invalid) ? 'Enter a valid value for each field' : '';
                    },
                }));
            }
        }
        if (composer.error) box.add_child(this._note(composer.error, true));
        const armed = this._isArmed(`send:${key}`);
        box.add_child(this._buttons([
            {
                label: composer.busy ? 'Waiting…' : armed ? `Confirm: ${verb.toLowerCase()} ${name}` : verb,
                armed,
                onClick: () => this._send(key, cmd, name, type),
            },
            cmd === 'goal' && composer.busy ? {
                label: 'Cancel goal', onClick: () => this._cancelGoal(composer),
            } : null,
            { label: 'Close', onClick: () => this._toggleComposer(key) },
        ]));
        if (composer.feedback)
            box.add_child(this._note(`Feedback ${composer.feedback.feedback} · ${composer.feedback.text}`));
        const reply = composer.reply;
        if (reply && reply.error) {
            box.add_child(this._note(reply.error, true));
        } else if (reply) {
            const parts = [];
            if (reply.status)
                parts.push(title(reply.status));
            if (reply.feedback)
                parts.push(plural(reply.feedback, 'feedback message'));
            if (reply.subscribers !== undefined)
                parts.push(`Sent to ${plural(reply.subscribers, 'subscriber')}`);
            if (parts.length)
                box.add_child(this._note(parts.join(' · ')));
            if (reply.text) {
                box.add_child(wrapped(new St.Label({ text: reply.text, style_class: 'adaptive-ros-definition' })));
            }
        }
        return box;
    }

    _addTopic(topic) {
        const key = `topic:${topic.name}`;
        const fetch = () => this._fetch(this._details, key, 'topic', { name: topic.name });
        const row = CC.makeRow({
            icon: 'network-transmit-receive-symbolic',
            title: topic.name,
            subtitle: `${topic.types.join(', ')} · ${plural(topic.publishers.length, 'publisher')} · ` +
                `${plural(topic.subscribers.length, 'subscriber')}`,
            onActivate: () => this._toggle(key, fetch),
        });
        if (topic.publishers.length && this._hasPlotJuggler())
            row.get_child().add_child(this._plotPickButton(topic.name));
        row.get_child().add_child(this._favoriteButton('topic', topic.name));
        this._out.add_child(this._expandable(key, row, fetch));
        if (!this._expanded.has(key))
            return;

        const box = new St.BoxLayout({ style_class: 'adaptive-ros-detail', vertical: true, x_expand: true });
        box.add_child(this._entry(key, topic.name, topic.types, [], {
            rate: topic.publishers.length > 0, sample: topic.publishers.length > 0,
        }));
        const detail = this._details.get(key) || { busy: true };
        const ends = (label, list, fallback) => {
            box.add_child(new St.Label({ text: label, style_class: 'adaptive-ros-group' }));
            if (detail.data) {
                if (!list.length)
                    box.add_child(this._note('None'));
                for (const end of list)
                    box.add_child(this._entry(key, end.node, [], [`${end.reliability} · ${end.durability}`]));
            } else {
                box.add_child(this._note(detail.busy ? fallback.join(', ') || 'Reading…' : detail.error));
            }
        };
        const data = detail.data || {};
        for (const warning of data.qos_warnings || [])
            box.add_child(this._note(`QoS: ${warning}`, true));
        ends('Published by', data.publishers || [], topic.publishers);
        ends('Subscribed by', data.subscribers || [], topic.subscribers);
        box.add_child(this._buttons([{ label: 'Show in the graph view', onClick: () => this._focusOn('topic', topic.name) }]));
        this._addComposerToggle(box, `publish:${topic.name}`, 'publish', topic.name, topic.types[0],
            'topic', 'Publish', 'Publish one message…');
        this._out.add_child(box);
    }

    _addComposerToggle(box, key, cmd, name, type, kind, verb, open) {
        if (!type)
            return;
        if (this._composers.has(key)) {
            box.add_child(this._composer(key, cmd, name, type, verb));
        } else {
            const bar = new St.BoxLayout({ style_class: 'adaptive-ros-buttons' });
            bar.add_child(this._smallButton(open, () => this._toggleComposer(key, kind, type)));
            box.add_child(bar);
        }
    }

    // A service or an action: who serves it, who calls it, and a way to call
    // it (or send a goal) once it has a server.
    _addEndpoint(kind, item, icon, servedBy, usedBy) {
        const key = `${kind}:${item.name}`;
        const parts = [item.types.join(', ')];
        parts.push(item.servers.length ? `${servedBy} ${names(item.servers)}` : 'no server');
        if (item.clients.length)
            parts.push(plural(item.clients.length, 'client'));
        const called = kind === 'service' ? this._quickCallText(item.name) : null;
        const quick = kind === 'service' ? this._quickCallAction(item) : null;
        const row = CC.makeRow({
            icon,
            title: item.name,
            subtitle: called ? called[0] : parts.join(' · '),
            alert: !item.servers.length || !!(called && called[1]),
            actions: quick ? [quick] : null,
            onActivate: () => this._toggle(key),
        });
        row.get_child().add_child(this._favoriteButton(kind, item.name));
        this._out.add_child(this._expandable(key, row));
        if (!this._expanded.has(key))
            return;
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-detail', vertical: true, x_expand: true });
        box.add_child(this._entry(key, item.name, item.types, []));
        for (const [label, list] of [[title(servedBy), item.servers], [title(usedBy), item.clients]]) {
            if (!list.length)
                continue;
            box.add_child(new St.Label({ text: label, style_class: 'adaptive-ros-group' }));
            for (const name of list)
                box.add_child(this._entry(key, name, [], []));
        }
        if (item.servers.length) {
            if (kind === 'service')
                this._addComposerToggle(box, `call:${item.name}`, 'call', item.name, item.types[0], 'service', 'Call', 'Call it…');
            else
                this._addComposerToggle(box, `goal:${item.name}`, 'goal', item.name, item.types[0], 'action', 'Send goal', 'Send a goal…');
        }
        this._out.add_child(box);
    }

    _addControllers(controllers) {
        const list = controllers.list || [];
        this._section('controllers', `Controllers · ${list.length}`, () => {
            if (controllers.error) {
                this._out.add_child(CC.makeRow({
                    icon: 'preferences-system-symbolic',
                    title: 'A controller manager is running',
                    subtitle: controllers.error,
                }));
            }
            for (const manager of [...new Set([...(controllers.managers || []), ...list.map(c => c.manager)])]) {
                this._out.add_child(this._textEntry({ hint: `Load controller on ${manager} (name, Enter twice)`,
                    text: this._controllerDraft && this._controllerDraft.manager === manager ? this._controllerDraft.name : '',
                    focus: !!(this._controllerDraft && this._controllerDraft.manager === manager),
                    onChange: name => { this._controllerDraft = { manager, name }; },
                    onActivate: name => { if (name.trim()) this._switchController({ manager, name: name.trim() }, 'load'); } }));
            }
            for (const controller of list) {
                const op = CONTROLLER_NEXT[controller.state];
                const armed = op && this._isArmed(`controller:${controller.manager}:${controller.name}:${op}`);
                this._out.add_child(CC.makeRow({
                    icon: 'preferences-system-symbolic',
                    title: controller.name,
                    subtitle: `${title(controller.state)} · ${controller.type} · ${controller.manager}`,
                    active: controller.state === 'active',
                    actions: [op ? {
                        label: armed ? `Confirm ${op}` : title(op),
                        quiet: !armed,
                        onClick: () => this._switchController(controller, op),
                    } : null, controller.state !== 'active' ? {
                        label: this._isArmed(`controller:${controller.manager}:${controller.name}:unload`) ? 'Confirm unload' : 'Unload',
                        onClick: () => this._switchController(controller, 'unload'),
                    } : null].filter(Boolean),
                }));
            }
            const note = this._notes.controllers;
            if (note)
                this._out.add_child(this._note(note.text, note.error));
        });
    }
};
