// Select English words directly on a frozen screen; recognition stays local.
/* exported ScreenText */
const { Clutter, Gio, GLib, Shell, St } = imports.gi;
const Main = imports.ui.main;
// Loads GNOME 42's promisified Screenshot methods.
const Screenshot = imports.ui.screenshot;
const Me = imports.misc.extensionUtils.getCurrentExtension();
const Model = Me.imports.screenTextModel;

const SETUP = 'Install text recognition: sudo apt install tesseract-ocr tesseract-ocr-eng python3-pil';
const TIMEOUT_MS = 30000;

var ScreenText = class ScreenText {
    constructor() {
        this._session = null;
        this._detached = false;
    }

    detach() {
        this._detached = true;
        this._close(this._session);
    }

    start() {
        if (this._detached || this._session || Main.sessionMode.isLocked || Main.sessionMode.isGreeter)
            return false;
        if (!GLib.find_program_in_path('tesseract')) {
            Main.notify('Copy Text from Screen', SETUP);
            return false;
        }
        const s = { words: [], selected: [], anchor: -1, dragging: false, signals: [],
            cancellable: new Gio.Cancellable(), timer: 0, proc: null, actor: null, grab: null };
        this._session = s;
        s.signals.push([Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => this._close(s))]);
        s.signals.push([Main.sessionMode, Main.sessionMode.connect('updated', () => {
            if (Main.sessionMode.isLocked || Main.sessionMode.isGreeter)
                this._close(s);
        })]);
        this._run(s).catch(e => {
            if (this._session === s) {
                const message = e.message || 'Text recognition failed';
                this._close(s);
                Main.notify('Copy Text from Screen', message);
            }
        });
        return true;
    }

    async _run(s) {
        try {
            // Allow the initiating menu/palette to disappear before taking the snapshot.
            await new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, 200, () => {
                resolve();
                return GLib.SOURCE_REMOVE;
            }));
            if (this._session !== s)
                return;
            const monitors = Main.layoutManager.monitors.map(m => ({ x: m.x, y: m.y, width: m.width, height: m.height }));
            const [content] = await new Shell.Screenshot().screenshot_stage_to_content();
            if (this._session !== s)
                return;
            const texture = content.get_texture();
            this._show(s, content);
            s.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, TIMEOUT_MS, () => {
                s.timer = 0;
                this._close(s);
                Main.notify('Copy Text from Screen', 'Recognition timed out. Try again with a simpler screen.');
                return GLib.SOURCE_REMOVE;
            });
            const languages = await this._command(s, ['tesseract', '--list-langs']);
            if (this._session !== s)
                return;
            if (!languages.split(/\r?\n/).some(line => line.trim() === 'eng'))
                throw new Error(SETUP);
            s.directory = GLib.dir_make_tmp('adaptive-screen-text-XXXXXX');
            s.files = [];
            const scaleX = texture.get_width() / global.screen_width;
            const scaleY = texture.get_height() / global.screen_height;
            for (let i = 0; i < monitors.length; i++) {
                if (this._session !== s)
                    return;
                const monitor = monitors[i];
                const path = GLib.build_filenamev([s.directory, `${i}.png`]);
                s.files.push(path);
                const stream = Gio.File.new_for_path(path).create(Gio.FileCreateFlags.PRIVATE, null);
                try {
                    const left = Math.round(monitor.x * scaleX), top = Math.round(monitor.y * scaleY);
                    const right = Math.round((monitor.x + monitor.width) * scaleX);
                    const bottom = Math.round((monitor.y + monitor.height) * scaleY);
                    // Keep native pixels, even on scaled displays. No cursor is composited.
                    await Shell.Screenshot.composite_to_stream(texture, left, top,
                        right - left, bottom - top, 1, null, 0, 0, 1, stream);
                } finally {
                    stream.close(null);
                }
                if (this._session !== s)
                    return;
                const prepared = GLib.build_filenamev([s.directory, `${i}-ocr.png`]);
                s.files.push(prepared);
                const helper = GLib.build_filenamev([Me.path, 'tools', 'screen_text_image.py']);
                const size = JSON.parse(await this._command(s, ['/usr/bin/python3', '-s', helper, path, prepared],
                    'Could not prepare the image. Install python3-pil and try again.'));
                if (this._session !== s)
                    return;
                const tsv = await this._command(s, ['tesseract', prepared, 'stdout', '-l', 'eng', '-c', 'tessedit_create_tsv=1']);
                if (this._session !== s)
                    return;
                s.words.push(...Model.mapWords(Model.parseTsv(tsv, i), size.width, size.height, monitor));
            }
            GLib.source_remove(s.timer);
            s.timer = 0;
            s.ready = true;
            s.status.text = s.words.length ? 'Drag to select words · Double-click a line · Ctrl+A selects all · Esc cancels' :
                'No text found. Press Esc and try a clearer or larger image.';
            s.canvas.queue_repaint();
        } finally {
            this._removeFiles(s);
        }
    }

    _command(s, argv, failure = 'Text recognition failed. Check that the English Tesseract data is installed.') {
        return new Promise((resolve, reject) => {
            const proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            s.proc = proc;
            proc.communicate_utf8_async(null, s.cancellable, (p, result) => {
                if (s.proc === proc)
                    s.proc = null;
                try {
                    const [, stdout] = p.communicate_utf8_finish(result);
                    if (!p.get_successful())
                        throw new Error(failure);
                    resolve(stdout || '');
                } catch (e) {
                    reject(e);
                }
            });
        });
    }

    _show(s, content) {
        s.actor = new St.Widget({ reactive: true, can_focus: true, x: 0, y: 0,
            width: global.screen_width, height: global.screen_height,
            accessible_name: 'Select text from screen' });
        s.actor.add_child(new Clutter.Actor({ content, width: global.screen_width, height: global.screen_height }));
        s.canvas = new St.DrawingArea({ width: global.screen_width, height: global.screen_height });
        s.actor.add_child(s.canvas);
        s.canvas.connect('repaint', () => this._paint(s));
        const bar = new St.BoxLayout({ style: 'background-color: #1c1c1e; color: #f5f5f7; padding: 12px; spacing: 12px; border-radius: 12px;' });
        s.status = new St.Label({ text: 'Recognizing English text… · Esc cancels', y_align: Clutter.ActorAlign.CENTER });
        bar.add_child(s.status);
        s.copy = new St.Button({ label: 'Copy', can_focus: true, reactive: false,
            style: 'background-color: #0a84ff; color: white; padding: 8px 16px; border-radius: 8px;' });
        s.copy.opacity = 100;
        s.copy.connect('clicked', () => this._copy(s));
        bar.add_child(s.copy);
        const move = new St.Button({ label: 'Move', can_focus: true,
            accessible_name: 'Move toolbar to the other edge', style: 'padding: 8px; color: #f5f5f7;' });
        bar.add_child(move);
        const cancel = new St.Button({ label: 'Cancel', can_focus: true,
            style: 'padding: 8px 12px; color: #f5f5f7;' });
        cancel.connect('clicked', () => this._close(s));
        bar.add_child(cancel);
        s.actor.add_child(bar);
        const monitor = Main.layoutManager.currentMonitor || Main.layoutManager.primaryMonitor;
        bar.set_position(monitor.x + 24, monitor.y + 24);
        let atTop = true;
        move.connect('clicked', () => {
            atTop = !atTop;
            bar.y = atTop ? monitor.y + 24 : monitor.y + monitor.height - bar.height - 24;
        });
        // Keep long help text within the current monitor.
        bar.width = Math.max(250, monitor.width - 48);
        s.status.x_expand = true;
        s.status.clutter_text.ellipsize = imports.gi.Pango.EllipsizeMode.END;
        s.actor.connect('key-press-event', (_actor, event) => this._key(s, event));
        s.actor.connect('button-press-event', (_actor, event) => {
            if (!s.ready || bar.contains(event.get_source()) || event.get_button() !== 1)
                return Clutter.EVENT_PROPAGATE;
            const [x, y] = event.get_coords();
            const index = Model.hitWord(s.words, x, y);
            // Mutter 42's Clutter.Event has no click-count accessor. Respect
            // the desktop's double-click timing and distance explicitly.
            const now = GLib.get_monotonic_time() / 1000;
            const settings = Clutter.Settings.get_default();
            const previous = s.lastPress;
            const doubleClick = index >= 0 && previous && previous.index === index &&
                now - previous.time <= settings.double_click_time &&
                Math.hypot(x - previous.x, y - previous.y) <= settings.double_click_distance;
            s.lastPress = doubleClick ? null : { index, x, y, time: now };
            s.anchor = index;
            s.dragging = index >= 0 && !doubleClick;
            this._select(s, doubleClick ? Model.lineWords(s.words, index) : index < 0 ? [] : [index]);
            return Clutter.EVENT_STOP;
        });
        s.actor.connect('motion-event', (_actor, event) => {
            if (!s.dragging)
                return Clutter.EVENT_PROPAGATE;
            const [x, y] = event.get_coords();
            const indices = Model.passage(s.words, s.anchor, Model.hitWord(s.words, x, y));
            if (indices.length)
                this._select(s, indices);
            return Clutter.EVENT_STOP;
        });
        s.actor.connect('button-release-event', () => {
            s.dragging = false;
            return Clutter.EVENT_PROPAGATE;
        });
        Main.layoutManager.addTopChrome(s.actor);
        s.grab = Main.pushModal(s.actor, { actionMode: Shell.ActionMode.NONE });
        if (s.grab.get_seat_state() !== Clutter.GrabState.ALL)
            throw new Error('Could not activate text selection. Close the other dialog and try again.');
        s.actor.grab_key_focus();
    }

    _key(s, event) {
        const key = event.get_key_symbol();
        if (key === Clutter.KEY_Escape) {
            this._close(s);
            return Clutter.EVENT_STOP;
        }
        if (event.get_state() & Clutter.ModifierType.CONTROL_MASK) {
            if (key === Clutter.KEY_a || key === Clutter.KEY_A) {
                this._select(s, s.words.map((_, i) => i));
                return Clutter.EVENT_STOP;
            }
            if (key === Clutter.KEY_c || key === Clutter.KEY_C) {
                this._copy(s);
                return Clutter.EVENT_STOP;
            }
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _select(s, indices) {
        if (!s.ready)
            return;
        s.selected = indices;
        s.copy.reactive = indices.length > 0;
        s.copy.opacity = indices.length ? 255 : 100;
        s.canvas.queue_repaint();
    }

    _paint(s) {
        const cr = s.canvas.get_context();
        const selected = new Set(s.selected);
        for (let i = 0; i < s.words.length; i++) {
            const w = s.words[i];
            cr.rectangle(w.x - 1, w.y - 1, w.width + 2, w.height + 2);
            if (selected.has(i)) {
                cr.setSourceRGBA(0.04, 0.52, 1, 0.38);
                cr.fill();
            } else {
                cr.setSourceRGBA(0.04, 0.52, 1, 0.65);
                cr.setLineWidth(1);
                cr.stroke();
            }
        }
        cr.$dispose();
    }

    _copy(s) {
        if (this._session !== s)
            return;
        const text = Model.selectionText(s.words, s.selected);
        if (!text)
            return;
        St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
        this._close(s);
        Main.notify('Text copied', `${text.length} characters copied to the clipboard`);
    }

    _removeFiles(s) {
        for (const path of [...(s.files || []), ...(s.directory ? [s.directory] : [])]) {
            try {
                Gio.File.new_for_path(path).delete(null);
            } catch (e) {
                if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                    logError(e, '[Adaptive Screen Text] removing temporary capture');
            }
        }
    }

    _close(s) {
        if (!s || this._session !== s)
            return;
        this._session = null;
        if (s.timer)
            GLib.source_remove(s.timer);
        s.timer = 0;
        s.cancellable.cancel();
        if (s.proc)
            s.proc.force_exit();
        for (const [object, id] of s.signals)
            object.disconnect(id);
        s.signals = [];
        if (s.grab)
            Main.popModal(s.grab);
        s.grab = null;
        if (s.actor)
            s.actor.destroy();
        s.actor = null;
        this._removeFiles(s);
    }
};
