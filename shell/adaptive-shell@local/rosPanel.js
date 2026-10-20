// Adaptive ROS 2 panel
//
// A top-bar indicator just left of Network: the ROS 2 graph this computer
// sees (nodes, topics, services, actions, ros2_control controllers) and the
// tools used with it (RViz2, Gazebo, rqt, a terminal on the same setup).
//
// tools/ros_info.py does all the ROS work; the shell never loads ROS.
// `status` (the setup, installed and running tools, RViz configs, worlds)
// runs each time the panel opens. `watch` keeps one hidden rclpy node while
// the panel is open, and a minute after it closes: it prints the graph
// whenever it changes and answers what an expanded row asks for - a node's
// parameters, lifecycle state and QoS, a type's definition, a topic's rate.
// docs/ROS2_PANEL.md has the whole picture.

/* exported RosPanel */

const { Clutter, Gio, GLib, Pango, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const CC = Me.imports.ccUtil;

const HELPER = Me.dir.get_child('tools').get_child('ros_info.py').get_path();
const LIST_MAX_HEIGHT = 680;
const KEEP_WATCHING_S = 60;
const STOP_GRACE_MS = 2000;
const COPIED_MS = 1100;
const REQUEST_REPLY_TIMEOUT_MS = 7000;
const SOURCE_HINTS = { panel: 'set here', default: 'default' };
const LIFECYCLE_CLASSES = {
    active: 'adaptive-network-good',
    inactive: 'adaptive-network-warn',
    unconfigured: 'adaptive-network-warn',
    finalized: 'adaptive-network-bad',
};

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
    return `${(count / 1024 / 1024).toFixed(1)} MB`;
}

function rateText(rate) {
    if (!rate.count)
        return `No messages in ${rate.window} s`;
    if (rate.count === 1)
        return `1 message in ${rate.window} s`;
    return `${rate.hz.toFixed(rate.hz < 10 ? 2 : 1)} Hz · ${bytes(rate.bytes_per_s)}/s`;
}

function valueText(value) {
    if (value === null || value === undefined)
        return 'not set';
    const text = Array.isArray(value) ? `[${value.join(', ')}]` : String(value);
    return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

function title(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

var RosPanel = class RosPanel {
    constructor() {
        this._button = null;
        this._openStateId = 0;
        this._sessionId = 0;
        this._stopId = 0;
        this._scrollId = 0;
        this._status = null;
        this._graph = null;
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
        // Type -> { busy, text, error }; topic -> { busy, data, error }.
        this._interfaces = new Map();
        this._rates = new Map();
        // Tool -> { text, error } after Open or Stop.
        this._notes = {};
        this._domainDraft = null;
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
        this._button.add_child(new St.Icon({
            gicon: CC.extensionIcon('ros-symbolic'),
            style_class: 'system-status-icon',
        }));

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
                this._setWatchMode(false);
                this._scheduleStop();
            }
        });
        this._sessionId = Main.sessionMode.connect('updated', () => this._syncSession());
        this._syncSession();
        log('[Adaptive ROS] panel indicator installed');
    }

    detach() {
        if (this._sessionId) {
            Main.sessionMode.disconnect(this._sessionId);
            this._sessionId = 0;
        }
        this._cancelStop();
        if (this._scrollId) {
            GLib.source_remove(this._scrollId);
            this._scrollId = 0;
        }
        this._stopWatch();
        if (this._button) {
            this._button.destroy();
            this._button = null;
        }
    }

    _syncSession() {
        if (this._button)
            this._button.container.visible = !Main.sessionMode.isLocked && !Main.sessionMode.isGreeter;
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

    _loadStatus(then = null) {
        this._helper(['status'], data => {
            if (data && data.installed !== undefined)
                this._status = data;
            // ~/.zshrc, ~/.bashrc or ros2.json changed while the watcher kept running.
            if (this._watch && this._setupKey() !== this._watchSetup)
                this._restartWatch();
            if (then)
                then();
            this._render();
        });
    }

    _set(key, value) {
        this._setMany([key, value]);
    }

    _setMany(pairs) {
        this._helper(['set', ...pairs], reply => {
            if (reply.ok) {
                this._status = reply;
                this._restartWatch();
            } else {
                this._notes.setup = { text: reply.error, error: true };
            }
            this._render();
        });
    }

    _launch(tool, file = null) {
        this._notes[tool] = { text: 'Starting…' };
        this._render();
        this._helper(['launch', tool, ...(file ? [file] : [])], reply => {
            this._notes[tool] = reply.ok ? null : { text: reply.error, error: true };
            if (reply.ok && tool !== 'demo')
                this._button.menu.close();
            this._loadStatus();
        });
    }

    _stop(tool) {
        this._notes[tool] = { text: 'Stopping…' };
        this._render();
        this._helper(['stop', tool], () => {
            this._notes[tool] = null;
            this._loadStatus();
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

    _terminal(command) {
        this._button.menu.close();
        this._helper([command], reply => {
            if (!reply.ok)
                Main.notify('ROS 2', reply.error);
        });
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
        this._graph = null;
        this._details.clear();
        this._rates.clear();
        this._readLine(watch);
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
            this._fetchExpandedDetails();
            this._render();
        } else if (message.type === 'reply') {
            const pending = this._pending.get(message.id);
            this._pending.delete(message.id);
            if (pending) {
                if (pending.timeoutId)
                    GLib.source_remove(pending.timeoutId);
                pending.done(message);
            }
        } else if (message.type === 'error') {
            this._watchError = message.error;
            this._render();
        }
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
        this._graph = null;
        this._watchError = '';
        this._details.clear();
        this._interfaces.clear();
        this._rates.clear();
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

    _request(cmd, fields, done) {
        if (!this._watch) {
            done({ error: 'ROS 2 is not being watched' });
            return;
        }
        const id = this._nextId++;
        const pending = { done, timeoutId: 0 };
        pending.timeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT,
            REQUEST_REPLY_TIMEOUT_MS, () => {
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
    }

    // Asks for `key`'s details once per unfolding; the reply lands in `map`.
    _fetch(map, key, cmd, fields) {
        map.set(key, { busy: true });
        this._request(cmd, fields, reply => {
            map.set(key, { busy: false, data: reply.error ? null : reply, error: reply.error || '' });
            this._render();
        });
    }

    _toggle(key, onOpen = null) {
        if (this._expanded.has(key)) {
            this._expanded.delete(key);
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

    // -------------------------------------------------------------- render

    _render() {
        if (!this._button || !this._button.menu.isOpen)
            return;
        const adjustment = this._scroll.vscroll.adjustment;
        const scrolled = adjustment.value;
        const status = this._status;

        this._summary.text = this._summaryText();
        this._list.destroy_all_children();
        if (!status) {
            this._list.add_child(CC.makeRow({ icon: CC.extensionIcon('ros-symbolic'), title: 'Reading…' }));
        } else if (!status.installed) {
            this._list.add_child(CC.makeRow({
                icon: 'dialog-warning-symbolic',
                title: 'ROS 2 is not installed',
                subtitle: 'Nothing under /opt/ros has a setup.bash',
            }));
        } else {
            this._list.add_child(this._setup(status));
            this._addLaunch(status);
            this._addGraph(status);
        }

        const [, natural] = this._list.get_preferred_height(-1);
        this._scroll.set_height(Math.min(natural, LIST_MAX_HEIGHT));
        // The rebuilt list is not laid out yet; put the scroll back once it is.
        if (this._scrollId)
            GLib.source_remove(this._scrollId);
        this._scrollId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._scrollId = 0;
            if (this._button)
                adjustment.value = Math.min(scrolled, adjustment.upper - adjustment.page_size);
            return GLib.SOURCE_REMOVE;
        });
    }

    _summaryText() {
        const status = this._status;
        if (!status || !status.installed)
            return '';
        const parts = [title(status.distro), `domain ${status.domain}`];
        if (this._graph)
            parts.push(plural(this._graph.nodes.length, 'node'));
        return parts.join(' · ');
    }

    // Domain, discovery, middleware and workspace, each changed by a click.
    _setup(status) {
        const box = new St.BoxLayout({
            style_class: 'adaptive-cc-form adaptive-network-facts',
            vertical: true,
            x_expand: true,
        });
        const grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({ column_spacing: 12, row_spacing: 2 }),
            x_expand: true,
        });
        box.add_child(grid);
        let row = 0;
        const line = (key, value, hint, onClick) => {
            grid.layout_manager.attach(new St.Label({
                text: key,
                style_class: 'adaptive-usb-key',
                y_align: Clutter.ActorAlign.CENTER,
            }), 0, row, 1, 1);
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
        const hint = key => from[key] === 'shell' ? `from ${status.shell_rc}` : SOURCE_HINTS[from[key]];

        if (this._domainDraft !== null) {
            grid.layout_manager.attach(new St.Label({
                text: 'Domain',
                style_class: 'adaptive-usb-key',
                y_align: Clutter.ActorAlign.CENTER,
            }), 0, row++, 1, 1);
            const entry = new St.Entry({
                style_class: 'adaptive-cc-entry adaptive-ros-domain-entry',
                hint_text: '0 to 232, Enter to use it',
                text: this._domainDraft,
                can_focus: true,
                x_expand: true,
            });
            entry.clutter_text.connect('text-changed', () => {
                this._domainDraft = entry.get_text();
            });
            entry.clutter_text.connect('activate', () => {
                const value = this._domainDraft.trim();
                this._domainDraft = null;
                if (/^\d+$/.test(value) && Number(value) !== status.domain)
                    this._set('domain', value);
                else
                    this._render();
            });
            entry.clutter_text.connect('key-press-event', (_actor, event) => {
                if (event.get_key_symbol() !== Clutter.KEY_Escape)
                    return Clutter.EVENT_PROPAGATE;
                this._domainDraft = null;
                this._render();
                return Clutter.EVENT_STOP;
            });
            grid.layout_manager.attach(entry, 1, row - 1, 1, 1);
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                if (entry.get_stage()) {
                    entry.grab_key_focus();
                    entry.clutter_text.set_cursor_position(-1);
                }
                return GLib.SOURCE_REMOVE;
            });
        } else {
            line('Domain', String(status.domain), hint('domain'), () => {
                this._domainDraft = String(status.domain);
                this._render();
            });
        }

        line('Discovery', status.localhost ? 'This computer only' : 'Whole network',
            hint('localhost'), () => this._set('localhost', status.localhost ? '0' : '1'));

        const middlewares = status.middlewares.map(m => m.id);
        line('Middleware', status.rmw_name, hint('rmw'), middlewares.length > 1 ? () => {
            const next = middlewares[(middlewares.indexOf(status.rmw) + 1) % middlewares.length];
            this._set('rmw', next);
        } : null);

        const choices = ['none', ...status.workspaces.map(w => w.path)];
        const current = status.workspace || 'none';
        const named = status.workspaces.find(w => w.path === status.workspace);
        line('Workspace', named ? named.name : 'None', hint('workspace'),
            choices.length > 1 ? () => {
                this._set('workspace', choices[(choices.indexOf(current) + 1) % choices.length]);
            } : null);

        const other = (status.elsewhere || [])[0];
        if (other && !this._notes.setup) {
            const footer = new St.BoxLayout({ style_class: 'adaptive-ros-setup-footer', x_expand: true });
            footer.add_child(new St.Label({
                text: `${other.count} ROS ${other.count === 1 ? 'process runs' : 'processes run'} on domain ` +
                    `${other.domain}${other.localhost ? ', this computer only' : ''}` +
                    `${other.rmw_name ? ` · ${other.rmw_name}` : ''}`,
                style_class: 'adaptive-ros-hint',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            }));
            const follow = new St.Button({
                style_class: 'adaptive-tasks-sort',
                label: 'Watch them',
                can_focus: true,
            });
            follow.connect('clicked', () => {
                const pairs = ['domain', String(other.domain),
                    'localhost', other.localhost ? '1' : '0'];
                if ((status.middlewares || []).some(item => item.id === other.rmw))
                    pairs.push('rmw', other.rmw);
                this._setMany(pairs);
            });
            footer.add_child(follow);
            box.add_child(footer);
        }

        const note = this._notes.setup;
        const changed = Object.values(from).includes('panel');
        if (note || changed) {
            const footer = new St.BoxLayout({ style_class: 'adaptive-ros-setup-footer', x_expand: true });
            footer.add_child(new St.Label({
                text: note ? note.text : `Changed here; your terminals still use ${status.shell_rc}`,
                style_class: note ? 'adaptive-network-ssh-error' : 'adaptive-ros-hint',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            }));
            if (changed) {
                const reset = new St.Button({
                    style_class: 'adaptive-tasks-sort',
                    label: `Follow ${status.shell_rc}`,
                    can_focus: true,
                });
                reset.connect('clicked', () => {
                    this._notes.setup = null;
                    this._set('all', '');
                });
                footer.add_child(reset);
            }
            box.add_child(footer);
        }
        return box;
    }

    // -------------------------------------------------------------- launch

    _addLaunch(status) {
        this._list.add_child(CC.makeHeading('Launch'));
        this._list.add_child(this._toolRow(status, 'rviz2', 'video-display-symbolic', 'RViz2',
            'Topics, TF and robot models in 3D'));
        if (status.tools.rviz2.installed)
            this._addFiles(status.rviz_configs, 'Open with', file => this._launch('rviz2', file));

        if (status.tools.gazebo.installed) {
            this._list.add_child(this._toolRow(status, 'gazebo', 'applications-engineering-symbolic',
                'Gazebo', status.gazebo_flavour === 'classic' ? 'Gazebo Classic, empty world' : 'Simulator, empty world'));
            this._addFiles(status.worlds, 'World', file => this._launch('gazebo', file));
        } else {
            this._list.add_child(CC.makeRow({
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
        this._list.add_child(CC.makeRow({
            icon: 'utilities-terminal-symbolic',
            title: 'Tools',
            subtitle: note ? note.text : 'rqt, the node graph, a terminal on this setup',
            alert: !!(note && note.error),
            actions,
        }));
    }

    _toolRow(status, tool, icon, name, idle) {
        const info = status.tools[tool];
        const note = this._notes[tool];
        const running = info.pids.length > 0;
        const owned = (info.owned_pids || []).length > 0;
        const external = (info.external_pids || []).length > 0;
        if (!info.installed) {
            return CC.makeRow({ icon, title: name, subtitle: 'Not installed' });
        }
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
                ...(owned ? [{ label: 'Stop', onClick: () => this._stop(tool) }] : []),
            ] : [
                { label: 'Open', quiet: true, onClick: () => this._launch(tool) },
            ],
        });
    }

    // Recent .rviz configs or worlds, as chips under their tool.
    _addFiles(files, label, onClick) {
        if (!files.length)
            return;
        const flow = new St.Widget({
            style_class: 'adaptive-ros-chips',
            layout_manager: new Clutter.FlowLayout({ column_spacing: 6, row_spacing: 6, homogeneous: false }),
            x_expand: true,
        });
        flow.add_child(new St.Label({ text: label, style_class: 'adaptive-ros-hint adaptive-ros-chip-label' }));
        for (const file of files) {
            const chip = new St.Button({
                style_class: 'adaptive-ros-chip',
                label: file.name,
                can_focus: true,
            });
            chip.connect('clicked', () => onClick(file.path));
            flow.add_child(chip);
        }
        this._list.add_child(flow);
    }

    // --------------------------------------------------------------- graph

    _addGraph(status) {
        if (this._watchError) {
            this._list.add_child(CC.makeRow({
                icon: 'dialog-warning-symbolic',
                title: 'Cannot see the ROS graph',
                subtitle: this._watchError,
                alert: true,
                action: { label: 'Retry', quiet: true, onClick: () => this._restartWatch() },
            }));
            return;
        }
        const graph = this._graph;
        if (!graph) {
            this._list.add_child(CC.makeRow({
                icon: CC.extensionIcon('ros-symbolic'),
                title: 'Looking for nodes…',
                subtitle: `Domain ${status.domain}${status.localhost ? ' · this computer only' : ''}`,
            }));
            return;
        }

        const demo = status.tools.demo;
        const stopDemo = (demo.owned_pids || []).length
            ? { label: 'Stop demo', onClick: () => this._stop('demo') } : null;
        this._section('nodes', `Nodes · ${graph.nodes.length}`, () => {
            if (!graph.nodes.length) {
                this._list.add_child(CC.makeRow({
                    icon: CC.extensionIcon('ros-symbolic'),
                    title: `No nodes on domain ${status.domain}`,
                    subtitle: status.localhost
                        ? 'Only this computer is searched (localhost only)'
                        : 'Nothing is running on this domain',
                    action: demo.installed && !demo.pids.length ? {
                        label: 'Start demo', quiet: true, onClick: () => this._launch('demo'),
                    } : null,
                }));
            }
            for (const node of graph.nodes) {
                this._list.add_child(this._nodeRow(node));
                if (this._expanded.has(`node:${node.name}`))
                    this._list.add_child(this._nodeDetails(node));
            }
        }, stopDemo);

        this._section('topics', `Topics · ${graph.topics.length}`, () => {
            const ordered = [...graph.topics.filter(t => !t.system), ...graph.topics.filter(t => t.system)];
            for (const topic of ordered)
                this._addTopic(topic);
        });
        this._section('services', `Services · ${graph.services.length}`, () => {
            for (const service of graph.services)
                this._addEndpoint('service', service, 'system-run-symbolic', 'served by', 'called by');
        });
        this._section('actions', `Actions · ${graph.actions.length}`, () => {
            for (const action of graph.actions)
                this._addEndpoint('action', action, 'media-playback-start-symbolic', 'served by', 'used by');
        });
        if (graph.controllers)
            this._addControllers(graph.controllers);

        const hidden = graph.hidden;
        const folded = [];
        if (hidden.nodes)
            folded.push(plural(hidden.nodes, 'hidden node'));
        if (hidden.parameter_services)
            folded.push(plural(hidden.parameter_services, 'parameter service'));
        this._list.add_child(new St.Label({
            text: `${folded.length ? `Not listed: ${folded.join(', ')} · ` : ''}Live · click a name to copy it`,
            style_class: 'adaptive-network-note',
        }));
    }

    // A heading that folds the rows `fill` adds under it.
    _section(id, text, fill, extra = null) {
        const key = `section:${id}`;
        const open = this._expanded.has(key);
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
        toggle.connect('clicked', () => this._toggle(key));
        heading.add_child(toggle);
        if (extra) {
            const button = new St.Button({
                style_class: 'adaptive-tasks-sort',
                label: extra.label,
                can_focus: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            button.connect('clicked', extra.onClick);
            heading.add_child(button);
        }
        this._list.add_child(heading);
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
        const qosText = key => {
            const q = qos[key];
            return q ? `${q.reliability} · ${q.durability}` : '';
        };

        group('Publishes', node.publishers, t => {
            const peers = others((topics.get(t.name) || {}).subscribers);
            return this._entry(where, t.name, t.types, [
                peers.length ? `to ${names(peers)}` : 'no subscribers', qosText(`publishers:${t.name}`),
            ], { rate: true });
        });
        group('Subscribes', node.subscribers, t => {
            const peers = others((topics.get(t.name) || {}).publishers);
            return this._entry(where, t.name, t.types, [
                peers.length ? `from ${names(peers)}` : 'nobody publishes it', qosText(`subscribers:${t.name}`),
            ], { rate: peers.length > 0, warn: !peers.length });
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

        if (node.lifecycle) {
            box.add_child(new St.Label({ text: 'Lifecycle', style_class: 'adaptive-ros-group' }));
            const state = data.lifecycle;
            box.add_child(new St.Label({
                text: detail.busy ? 'Asking…' : state ? title(state) : 'Did not answer',
                style_class: `adaptive-ros-param ${LIFECYCLE_CLASSES[state] || ''}`.trim(),
            }));
        }
        if (node.parameter_services) {
            box.add_child(new St.Label({ text: 'Parameters', style_class: 'adaptive-ros-group' }));
            if (detail.busy) {
                box.add_child(new St.Label({ text: 'Reading…', style_class: 'adaptive-ros-meta' }));
            } else if (data.parameters) {
                box.add_child(this._parameters(data.parameters));
                if (data.parameters_truncated) {
                    box.add_child(new St.Label({
                        text: `Showing ${data.parameters.length} of ${data.parameter_total} parameters`,
                        style_class: 'adaptive-ros-meta',
                    }));
                }
            } else if (!detail.error) {
                box.add_child(new St.Label({ text: 'Did not answer in time', style_class: 'adaptive-ros-meta' }));
            }
        }
        if (node.enclave && node.enclave !== '/') {
            box.add_child(new St.Label({ text: 'Enclave', style_class: 'adaptive-ros-group' }));
            box.add_child(new St.Label({ text: node.enclave, style_class: 'adaptive-ros-param' }));
        }
        if (detail.error)
            box.add_child(new St.Label({ text: detail.error, style_class: 'adaptive-network-ssh-error' }));
        return box;
    }

    _parameters(parameters) {
        if (!parameters.length)
            return new St.Label({ text: 'None', style_class: 'adaptive-ros-meta' });
        const grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({ column_spacing: 10, row_spacing: 1 }),
            x_expand: true,
        });
        parameters.forEach((parameter, row) => {
            const key = new St.Label({ text: parameter.name, style_class: 'adaptive-ros-param-key' });
            key.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
            grid.layout_manager.attach(key, 0, row, 1, 1);
            const value = new St.Label({ text: valueText(parameter.value), style_class: 'adaptive-ros-param' });
            value.clutter_text.ellipsize = Pango.EllipsizeMode.END;
            grid.layout_manager.attach(value, 1, row, 1, 1);
        });
        return grid;
    }

    // One topic, service or action inside an expanded row: its name (click
    // to copy), its types (click for the definition), what is on the other
    // end, and for topics a Hz button.
    _entry(where, name, types, meta, { rate = false, warn = false } = {}) {
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-entry', vertical: true, x_expand: true });
        const top = new St.BoxLayout({ x_expand: true });
        top.add_child(this._copyName(name));
        if (rate)
            top.add_child(this._rateButton(name));
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
            box.add_child(new St.Label({ text: measured.error, style_class: 'adaptive-network-ssh-error' }));
        for (const type of types) {
            if (this._expanded.has(`iface:${where}:${type}`))
                box.add_child(this._definition(type));
        }
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
        const button = new St.Button({
            style_class: 'adaptive-tasks-sort adaptive-ros-rate',
            label: rate && rate.busy ? 'Measuring…' : rate && rate.data ? rateText(rate.data) : 'Hz',
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        button.connect('clicked', () => this._measure(topic));
        return button;
    }

    _definition(type) {
        const known = this._interfaces.get(type) || { busy: true };
        const label = new St.Label({
            text: known.busy ? 'Reading…' : known.error || known.data.text,
            style_class: known.error ? 'adaptive-ros-definition adaptive-network-warn' : 'adaptive-ros-definition',
        });
        label.clutter_text.line_wrap = true;
        return label;
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
        this._list.add_child(this._expandable(key, row, fetch));
        if (!this._expanded.has(key))
            return;

        const box = new St.BoxLayout({ style_class: 'adaptive-ros-detail', vertical: true, x_expand: true });
        box.add_child(this._entry(key, topic.name, topic.types, [], { rate: topic.publishers.length > 0 }));
        const detail = this._details.get(key) || { busy: true };
        const ends = (label, list, fallback) => {
            box.add_child(new St.Label({ text: label, style_class: 'adaptive-ros-group' }));
            if (detail.data) {
                if (!list.length)
                    box.add_child(new St.Label({ text: 'None', style_class: 'adaptive-ros-meta' }));
                for (const end of list) {
                    box.add_child(this._entry(key, end.node, [], [`${end.reliability} · ${end.durability}`]));
                }
            } else {
                box.add_child(new St.Label({
                    text: detail.busy ? fallback.join(', ') || 'Reading…' : detail.error,
                    style_class: 'adaptive-ros-meta',
                }));
            }
        };
        const data = detail.data || {};
        ends('Published by', data.publishers || [], topic.publishers);
        ends('Subscribed by', data.subscribers || [], topic.subscribers);
        this._list.add_child(box);
    }

    // A service or an action: who serves it, who calls it.
    _addEndpoint(kind, item, icon, servedBy, usedBy) {
        const key = `${kind}:${item.name}`;
        const parts = [item.types.join(', ')];
        parts.push(item.servers.length ? `${servedBy} ${names(item.servers)}` : 'no server');
        if (item.clients.length)
            parts.push(plural(item.clients.length, 'client'));
        const row = CC.makeRow({
            icon,
            title: item.name,
            subtitle: parts.join(' · '),
            alert: !item.servers.length,
            onActivate: () => this._toggle(key),
        });
        this._list.add_child(this._expandable(key, row));
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
        this._list.add_child(box);
    }

    _addControllers(controllers) {
        const list = controllers.list || [];
        this._section('controllers', `Controllers · ${list.length}`, () => {
            if (controllers.error) {
                this._list.add_child(CC.makeRow({
                    icon: 'preferences-system-symbolic',
                    title: 'A controller manager is running',
                    subtitle: controllers.error,
                }));
            }
            for (const controller of list) {
                this._list.add_child(CC.makeRow({
                    icon: 'preferences-system-symbolic',
                    title: controller.name,
                    subtitle: `${title(controller.state)} · ${controller.type} · ${controller.manager}`,
                    active: controller.state === 'active',
                }));
            }
        });
    }
};
