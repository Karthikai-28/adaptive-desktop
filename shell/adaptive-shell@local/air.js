/* exported Air */
'use strict';

// Air: the shell's half of hand-gesture control through the Kinect (services/adaptive-air).
//
// The service sees and decides; this draws and acts. It listens for org.adaptive.Air.Frame on
// the session bus (one JSON frame per camera frame, services/adaptive-air/protocol.py) and:
//
//   draws    the reticle where your palm points (rotating arcs; the inner ring closes as you
//            pinch; a ring fills while you hold an open palm up to engage), your hands' skeletons
//            floating over the screen, corner brackets and a scan sweep while engaged, a status
//            chip (source, hand, distance, frame rate), toasts for what a gesture did, a ripple
//            on every click, and a camera indicator in the top bar (with Stop) whenever Air runs
//   acts     moves the real pointer and presses its buttons through Clutter's virtual input
//            devices (no xdotool): click, right-click (thumb on the middle finger), the wheel
//            (V sign), Ctrl + wheel to zoom (V sign pushed forward, or two pinching hands);
//            carries the window under a fist, resizes it with a second fist, throws it
//            (left/right: tile that half, up: maximise, down: minimise), switches workspace on a
//            swipe and opens or closes the overview with two open palms
//
// Nothing here moves the pointer unless the service says Air is engaged, and everything held
// (a pressed button, a carried window) is let go when frames stop. docs/AIR.md.

const { Clutter, Gio, GLib, Meta, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const Me = imports.misc.extensionUtils.getCurrentExtension();
const Tokens = Me.imports.designTokens;

const BUS_NAME = 'org.adaptive.Air';
const PATH = '/org/adaptive/Air';
const STALE_MS = 3500;
const RETICLE = 220;
const BRACKET = 96;
const HOLO_HAND = 0.17;   // a drawn hand, wrist to middle fingertip, as a share of screen height

const BONES = [
    [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11],
    [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];
const TIPS = [4, 8, 12, 16, 20];
const PALM = [0, 5, 9, 13, 17];

function rgb(name) {
    const hex = Tokens.COLOR[name];
    return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
}

function source(cr, name, alpha) {
    const [r, g, b] = rgb(name);
    cr.setSourceRGBA(r, g, b, alpha);
}

var Air = class Air {
    // runAction(name): the shell's own actions (shellActions.js Run), e.g. 'workspace-right'.
    constructor({ runAction } = {}) {
        this._runAction = runAction || (() => false);
        this._signalId = 0;
        this._frame = null;
        this._phase = 0;
        this._lastFrameAt = 0;
        this._staleId = 0;
        this._buttonDown = false;
        this._grabbed = null;
        this._lastGrabbed = null;
        this._engaged = false;
        this._note = null;
        this._pointerAt = null;
        this._vptr = null;
        this._vkbd = null;
        this._history = [];
        this._resizedTo = null;     // the last events acted on, newest last (for checks and debugging)
        this._indicator = null;
        this._toastId = 0;
        this._skelHands = null;
    }

    attach() {
        this._signalId = Gio.DBus.session.signal_subscribe(BUS_NAME, BUS_NAME, 'Frame', PATH, null,
            Gio.DBusSignalFlags.NONE, (_c, _s, _p, _i, _n, params) => {
                let frame;
                try {
                    frame = JSON.parse(params.deep_unpack()[0]);
                } catch (e) {
                    return;
                }
                try {
                    this._onFrame(frame);
                } catch (e) {
                    logError(e, '[Adaptive Shell] Air frame');
                }
            });
        this._build();
    }

    detach() {
        if (this._signalId) {
            Gio.DBus.session.signal_unsubscribe(this._signalId);
            this._signalId = 0;
        }
        this._letGo();
        if (this._staleId) {
            GLib.source_remove(this._staleId);
            this._staleId = 0;
        }
        if (this._toastId) {
            GLib.source_remove(this._toastId);
            this._toastId = 0;
        }
        this._dropIndicator();
        if (this._layer) {
            this._layer.destroy();
            this._layer = null;
        }
        this._vptr = null;
        this._vkbd = null;
    }

    // ---------------------------------------------------------------- building

    _build() {
        this._layer = new St.Widget({ reactive: false, visible: false, x: 0, y: 0 });
        Main.uiGroup.add_child(this._layer);

        this._skeleton = new St.DrawingArea({ reactive: false });
        this._skeleton.connect('repaint', a => this._paintSkeleton(a));
        this._layer.add_child(this._skeleton);

        this._reticle = new St.DrawingArea({ reactive: false, width: RETICLE, height: RETICLE });
        this._reticle.connect('repaint', a => this._paintReticle(a));
        this._layer.add_child(this._reticle);

        this._readout = new St.Label({ style_class: 'adaptive-air-readout', reactive: false });
        this._layer.add_child(this._readout);

        this._brackets = [0, 1, 2, 3].map(corner => {
            const area = new St.DrawingArea({ reactive: false, width: BRACKET, height: BRACKET,
                opacity: 0 });
            area.connect('repaint', a => this._paintBracket(a, corner));
            this._layer.add_child(area);
            return area;
        });

        this._sweep = new St.Widget({ style_class: 'adaptive-air-sweep', reactive: false,
            opacity: 0, height: 2 });
        this._layer.add_child(this._sweep);

        this._chip = new St.Label({ style_class: 'adaptive-air-chip', reactive: false, opacity: 0 });
        this._layer.add_child(this._chip);

        this._toast = new St.Label({ style_class: 'adaptive-air-toast', reactive: false, opacity: 0 });
        this._toast.set_pivot_point(0.5, 0.5);
        this._layer.add_child(this._toast);
    }

    _monitor() {
        return Main.layoutManager.primaryMonitor;
    }

    // ---------------------------------------------------------------- frames

    _onFrame(f) {
        const now = GLib.get_monotonic_time() / 1000;
        const dt = this._lastFrameAt ? Math.min(0.1, (now - this._lastFrameAt) / 1000) : 0;
        this._lastFrameAt = now;
        this._phase += dt;
        this._frame = f;
        this._armStale();
        this._syncIndicator(f);

        if (f.note && f.note !== this._note)
            this._showToast(f.note, 4200);
        this._note = f.note || null;

        const mon = this._monitor();
        const px = Math.round(mon.x + f.cursor.x * mon.width);
        const py = Math.round(mon.y + f.cursor.y * mon.height);

        for (const ev of f.events || [])
            this._onEvent(ev, px, py, f);

        if (f.engaged && !this._engaged)
            this._onEvent({ type: 'engage' }, px, py, f);   // a missed engage event
        if (!f.engaged && this._engaged)
            this._onEvent({ type: 'disengage' }, px, py, f);

        if (f.engaged) {
            if (this._grabbed && f.resize)
                this._resize(f.resize);
            else if (this._grabbed && f.grab)
                this._carry(px, py);
            else
                this._movePointer(px, py);
            if (!f.pressed && this._buttonDown)
                this._button(false);
        }

        this._render(f, px, py, mon);
    }

    _onEvent(ev, px, py, f) {
        this._history.push(ev.type);
        if (this._history.length > 60)
            this._history.shift();
        switch (ev.type) {
        case 'engage':
            this._engaged = true;
            this._enter();
            this._showToast('Air engaged');
            break;
        case 'disengage':
            this._engaged = false;
            this._letGo();
            this._leave();
            break;
        case 'press':
            this._movePointer(px, py);
            this._button(true);
            break;
        case 'release':
            this._button(false);
            break;
        case 'click':
            this._ripple(px, py);
            break;
        case 'push':
            this._movePointer(px, py);
            this._button(true);
            this._button(false);
            break;
        case 'right-click':
            this._movePointer(px, py);
            this._secondaryClick();
            this._ripple(px, py, 'adaptive-air-ripple-secondary');
            break;
        case 'scroll':
            this._scroll(ev.dx || 0, ev.dy || 0);
            if (ev.wave)
                this._showToast(ev.dy > 0 ? '\u2193  Scroll' : '\u2191  Scroll', 500);
            break;
        case 'carry-left':
        case 'carry-right':
            this._carryAcross(ev.type === 'carry-left' ? Meta.MotionDirection.LEFT : Meta.MotionDirection.RIGHT);
            break;
        case 'zoom':
            this._zoom(ev.steps || 0);
            break;
        case 'grab':
            this._grab(px, py);
            break;
        case 'resize-start':
            this._resizeStart();
            break;
        case 'resize-end':
            this._resizeEnd(px, py);
            break;
        case 'drop':
            this._drop();
            break;
        case 'throw-left':
        case 'throw-right':
        case 'throw-up':
        case 'throw-down':
            this._throw(ev.type.slice(6));
            break;
        case 'swipe-left':
            // The hand pushes the desktop away to the left: the next one comes in from the right.
            this._runAction('workspace-right');
            this._showToast('Next desktop  →');
            break;
        case 'swipe-right':
            this._runAction('workspace-left');
            this._showToast('←  Previous desktop');
            break;
        case 'swipe-up':
            Main.overview.toggle();
            this._showToast(Main.overview.visible ? 'Overview' : 'Desktop');
            break;
        case 'spread':
            if (!Main.overview.visible)
                Main.overview.show();
            this._showToast('Every window');
            break;
        case 'collapse':
            if (Main.overview.visible)
                Main.overview.hide();
            this._showToast('Back to work');
            break;
        }
    }

    // ---------------------------------------------------------------- acting

    _device() {
        if (!this._vptr) {
            const seat = Clutter.get_default_backend().get_default_seat();
            this._vptr = seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
        }
        return this._vptr;
    }

    _keyboard() {
        if (!this._vkbd) {
            const seat = Clutter.get_default_backend().get_default_seat();
            this._vkbd = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        }
        return this._vkbd;
    }

    _secondaryClick() {
        const dev = this._device();
        for (const state of [Clutter.ButtonState.PRESSED, Clutter.ButtonState.RELEASED])
            dev.notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_SECONDARY, state);
    }

    // Wheel steps: dy > 0 is the wheel turned down (the page moves up), dx > 0 is to the right.
    _scroll(dx, dy) {
        const dev = this._device();
        const send = (n, plus, minus) => {
            for (let i = 0; i < Math.min(Math.abs(n), 5); i++) {
                dev.notify_discrete_scroll(GLib.get_monotonic_time(), n > 0 ? plus : minus,
                    Clutter.ScrollSource.WHEEL);
            }
        };
        send(dy, Clutter.ScrollDirection.DOWN, Clutter.ScrollDirection.UP);
        send(dx, Clutter.ScrollDirection.RIGHT, Clutter.ScrollDirection.LEFT);
    }

    // Zoom is Ctrl + wheel, which browsers, Files, editors and image viewers all understand.
    _zoom(steps) {
        if (!steps)
            return;
        const kbd = this._keyboard();
        kbd.notify_keyval(GLib.get_monotonic_time(), Clutter.KEY_Control_L, Clutter.KeyState.PRESSED);
        this._scroll(0, -steps);    // wheel up zooms in
        kbd.notify_keyval(GLib.get_monotonic_time(), Clutter.KEY_Control_L, Clutter.KeyState.RELEASED);
    }

    _movePointer(x, y) {
        if (this._pointerAt && Math.abs(this._pointerAt[0] - x) < 1 &&
            Math.abs(this._pointerAt[1] - y) < 1)
            return;
        this._pointerAt = [x, y];
        this._device().notify_absolute_motion(GLib.get_monotonic_time(), x, y);
    }

    _button(down) {
        if (down === this._buttonDown)
            return;
        this._buttonDown = down;
        this._device().notify_button(GLib.get_monotonic_time(), Clutter.BUTTON_PRIMARY,
            down ? Clutter.ButtonState.PRESSED : Clutter.ButtonState.RELEASED);
    }

    _letGo() {
        if (this._buttonDown && this._vptr)
            this._button(false);
        this._buttonDown = false;
        this._grabbed = null;
    }

    _windowAt(x, y) {
        const ws = global.workspace_manager.get_active_workspace();
        const kinds = [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG];
        const actors = global.get_window_actors().slice().reverse();   // topmost first
        for (const actor of actors) {
            const w = actor.meta_window;
            if (!w || w.minimized || !w.showing_on_its_workspace() || !w.located_on_workspace(ws))
                continue;
            if (!kinds.includes(w.get_window_type()))
                continue;
            const r = w.get_frame_rect();
            if (x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height)
                return w;
        }
        return null;
    }

    _grab(px, py) {
        const w = this._windowAt(px, py);
        if (!w) {
            this._showToast('Nothing to grab here');
            return;
        }
        if (w.get_maximized())
            w.unmaximize(Meta.MaximizeFlags.BOTH);
        w.activate(global.get_current_time());
        const r = w.get_frame_rect();
        const inside = px >= r.x && px < r.x + r.width && py >= r.y && py < r.y + r.height;
        // A window that was maximised shrinks under the hand: hold it by its title bar instead.
        this._grabbed = inside
            ? { win: w, dx: r.x - px, dy: r.y - py }
            : { win: w, dx: -Math.round(r.width / 2), dy: -24 };
        this._lastGrabbed = w;
        this._showToast(w.get_title() ? `Holding ${w.get_title()}` : 'Holding window', 900);
    }

    _carry(px, py) {
        const g = this._grabbed;
        if (!g.win.get_compositor_private()) {     // closed while held
            this._grabbed = null;
            return;
        }
        g.win.move_frame(true, Math.round(px + g.dx), Math.round(py + g.dy));
    }

    _resizeStart() {
        const g = this._grabbed;
        if (!g)
            return;
        const r = g.win.get_frame_rect();
        g.base = { x: r.x, y: r.y, width: r.width, height: r.height,
            cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
        this._showToast('Resize', 700);
    }

    _resize(scale) {
        const g = this._grabbed;
        if (!g || !g.base || !g.win.get_compositor_private())
            return;
        const area = Main.layoutManager.getWorkAreaForMonitor(g.win.get_monitor());
        const w = Math.round(Math.max(320, Math.min(area.width, g.base.width * scale)));
        const h = Math.round(Math.max(220, Math.min(area.height, g.base.height * scale)));
        const x = Math.round(Math.max(area.x, Math.min(area.x + area.width - w, g.base.cx - w / 2)));
        const y = Math.round(Math.max(area.y, Math.min(area.y + area.height - h, g.base.cy - h / 2)));
        g.win.move_resize_frame(true, x, y, w, h);
        this._resizedTo = { width: w, height: h };
    }

    _resizeEnd(px, py) {
        const g = this._grabbed;
        if (!g)
            return;
        // Carry on holding it from wherever the hand now is over it.
        const r = g.win.get_frame_rect();
        g.dx = Math.max(-r.width + 20, Math.min(-20, r.x - px));
        g.dy = Math.max(-r.height + 20, Math.min(-10, r.y - py));
        g.base = null;
    }

    // A held window taken to the screen's side goes to the desktop that side, and so do you.
    _carryAcross(direction) {
        const g = this._grabbed;
        if (!g || !g.win.get_compositor_private())
            return;
        const here = global.workspace_manager.get_active_workspace();
        const there = here.get_neighbor(direction);
        if (!there || there === here) {
            this._showToast('No desktop that way', 800);
            return;
        }
        g.win.change_workspace(there);
        there.activate_with_focus(g.win, global.get_current_time());
        this._showToast(direction === Meta.MotionDirection.LEFT ? '\u2190  Window to the previous desktop'
            : 'Window to the next desktop  \u2192', 900);
    }

    _drop() {
        this._grabbed = null;
    }

    _throw(direction) {
        const w = this._lastGrabbed;
        if (!w || !w.get_compositor_private())
            return;
        const area = Main.layoutManager.getWorkAreaForMonitor(w.get_monitor());
        const half = Math.round(area.width / 2);
        if (direction === 'up') {
            w.maximize(Meta.MaximizeFlags.BOTH);
            this._showToast('Maximised');
        } else if (direction === 'down') {
            w.minimize();
            this._showToast('Minimised');
        } else {
            if (w.get_maximized())
                w.unmaximize(Meta.MaximizeFlags.BOTH);
            const x = direction === 'left' ? area.x : area.x + half;
            w.move_resize_frame(true, x, area.y, half, area.height);
            this._showToast(direction === 'left' ? '←  Left half' : 'Right half  →');
        }
        this._lastGrabbed = null;
    }

    // ---------------------------------------------------------------- staying honest

    _armStale() {
        if (this._staleId)
            GLib.source_remove(this._staleId);
        this._staleId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, STALE_MS, () => {
            this._staleId = 0;
            // The service stopped (or crashed): let go of everything and take the HUD down.
            this._engaged = false;
            this._letGo();
            this._leave();
            this._frame = null;
            if (this._layer)
                this._layer.hide();
            this._dropIndicator();
            return GLib.SOURCE_REMOVE;
        });
    }

    _syncIndicator(f) {
        if (!this._indicator) {
            const button = new PanelMenu.Button(0.0, 'Air', false);
            this._indicatorIcon = new St.Icon({ icon_name: 'camera-web-symbolic',
                style_class: 'system-status-icon adaptive-air-indicator' });
            button.add_child(this._indicatorIcon);
            this._statusItem = new PopupMenu.PopupMenuItem('', { reactive: false });
            this._noteItem = new PopupMenu.PopupMenuItem('', { reactive: false });
            this._noteItem.label.clutter_text.line_wrap = true;
            button.menu.addMenuItem(this._statusItem);
            button.menu.addMenuItem(this._noteItem);
            button.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            button.menu.addAction('Stop Air', () => this._stopService());
            Main.panel.addToStatusArea('adaptive-air', button, 0, 'right');
            this._indicator = button;
        }
        const where = { kinect: 'Kinect', webcam: 'Webcam', none: 'No camera' }[f.source] || f.source;
        const waiting = { 'kinect-unpowered': 'Kinect has no power', 'no-camera': 'no camera',
            starting: 'starting', stopping: 'stopping' }[f.status];
        this._statusItem.label.text = `Air · ${where}${f.fps ? ` · ${Math.round(f.fps)} fps` : ''}` +
            (waiting ? ` · ${waiting}`
                : f.engaged ? ' · engaged' : ' · raise an open palm to engage');
        this._noteItem.label.text = f.note || 'Camera pictures never leave the laptop or touch the disk.';
        if (f.engaged)
            this._indicatorIcon.add_style_class_name('adaptive-air-engaged');
        else
            this._indicatorIcon.remove_style_class_name('adaptive-air-engaged');
    }

    _dropIndicator() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }

    _stopService() {
        Gio.DBus.session.call(BUS_NAME, PATH, BUS_NAME, 'Stop', null, null,
            Gio.DBusCallFlags.NONE, 2000, null, null);
    }

    // ---------------------------------------------------------------- drawing

    _render(f, px, py, mon) {
        const visible = f.engaged || f.engage > 0 || (f.hands && f.hands.length > 0);
        this._layer.visible = visible || this._toast.opacity > 0;
        if (!this._layer.visible)
            return;
        Main.uiGroup.set_child_above_sibling(this._layer, null);

        // Reticle: at the pointer when engaged, over the palm while engaging.
        let rx = px, ry = py;
        const primary = (f.hands || []).find(h => h.primary) || (f.hands || [])[0];
        if (!f.engaged && primary) {
            rx = mon.x + PALM.reduce((s, i) => s + primary.pts[i][0], 0) / PALM.length * mon.width;
            ry = mon.y + PALM.reduce((s, i) => s + primary.pts[i][1], 0) / PALM.length * mon.height;
        }
        const showReticle = f.engaged || f.engage > 0;
        this._reticle.visible = showReticle;
        if (showReticle) {
            this._reticle.set_position(Math.round(rx - RETICLE / 2), Math.round(ry - RETICLE / 2));
            this._reticle.queue_repaint();
        }

        this._readout.visible = f.engaged && !!primary;
        if (this._readout.visible) {
            const depth = primary.depth ? `${(primary.depth / 1000).toFixed(2)} m` : '';
            const pose = { scroll: 'scroll', zoom: 'zoom', lzoom: 'zoom', resize: 'resize', palms: 'two palms' }[f.mode] ||
                (this._grabbed ? 'holding' : primary.pose);
            this._readout.text = [depth, pose.toUpperCase()].filter(Boolean).join('  ·  ');
            this._readout.set_position(Math.round(rx + RETICLE * 0.36), Math.round(ry + RETICLE * 0.22));
        }

        this._placeSkeleton(f, mon);

        if (f.engaged) {
            const hand = primary ? (primary.side === 'Left' ? 'left hand' : 'right hand') : 'no hand';
            const parts = ['AIR', (f.source || '').toUpperCase(), hand.toUpperCase()];
            if (primary && primary.depth)
                parts.push(`${(primary.depth / 1000).toFixed(2)} M`);
            if (f.hands && f.hands.length > 1)
                parts.push('TWO HANDS');
            if (f.mode && f.mode !== 'grab')
                parts.push(f.mode.toUpperCase());
            parts.push(`${Math.round(f.fps || 0)} FPS`);
            this._chip.text = parts.join('   ·   ');
            const [, natural] = this._chip.get_preferred_width(-1);
            this._chip.set_position(Math.round(mon.x + (mon.width - natural) / 2),
                mon.y + Main.panel.height + 14);
        }
    }

    // Each hand is drawn as a hologram of a fixed size around its own palm: the palms stay where
    // the hands really are (two-hand gestures read right), but a hand never covers half the screen.
    _placeSkeleton(f, mon) {
        const hands = f.hands || [];
        const target = HOLO_HAND * mon.height;
        this._skelHands = hands.map(h => {
            const raw = h.pts.map(([x, y]) => [mon.x + x * mon.width, mon.y + y * mon.height]);
            const cx = PALM.reduce((s, i) => s + raw[i][0], 0) / PALM.length;
            const cy = PALM.reduce((s, i) => s + raw[i][1], 0) / PALM.length;
            const span = Math.hypot(raw[12][0] - raw[0][0], raw[12][1] - raw[0][1]) || 1;
            const k = Math.min(1, target / span);
            return { hand: h, pts: raw.map(([x, y]) => [cx + (x - cx) * k, cy + (y - cy) * k]) };
        });
        if (!hands.length) {
            this._skeleton.visible = false;
            return;
        }
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const { pts } of this._skelHands) {
            for (const [x, y] of pts) {
                x0 = Math.min(x0, x); y0 = Math.min(y0, y);
                x1 = Math.max(x1, x); y1 = Math.max(y1, y);
            }
        }
        const pad = 24;
        const left = Math.max(mon.x, Math.floor(x0) - pad);
        const top = Math.max(mon.y, Math.floor(y0) - pad);
        const right = Math.min(mon.x + mon.width, Math.ceil(x1) + pad);
        const bottom = Math.min(mon.y + mon.height, Math.ceil(y1) + pad);
        if (right - left < 8 || bottom - top < 8) {
            this._skeleton.visible = false;
            return;
        }
        this._skelBox = { left, top };
        this._skeleton.visible = true;
        this._skeleton.set_position(left, top);
        this._skeleton.set_size(right - left, bottom - top);
        this._skeleton.queue_repaint();
    }

    _paintSkeleton(area) {
        const cr = area.get_context();
        const f = this._frame;
        const box = this._skelBox;
        if (f && box && this._skelHands) {
            const { left, top } = box;
            for (const { hand: h, pts: abs } of this._skelHands) {
                const strong = f.engaged ? (h.primary ? 0.8 : 0.5) : 0.45;
                const pts = abs.map(([x, y]) => [x - left, y - top]);
                const tone = h.pose === 'fist' ? 'warn' : 'cyan';
                cr.setLineCap(1);   // round
                for (const [width, alpha] of [[9, 0.10], [5, 0.18], [2, 0.85]]) {
                    cr.setLineWidth(width);
                    source(cr, tone, alpha * strong);
                    for (const [a, b] of BONES) {
                        cr.moveTo(pts[a][0], pts[a][1]);
                        cr.lineTo(pts[b][0], pts[b][1]);
                    }
                    cr.stroke();
                }
                for (let i = 0; i < pts.length; i++) {
                    const tip = TIPS.includes(i);
                    const pinchTip = (i === 4 || i === 8) && h.pinch > 0.2;
                    if (tip) {
                        source(cr, pinchTip ? 'accent' : tone, 0.25 * strong);
                        cr.arc(pts[i][0], pts[i][1], pinchTip ? 9 + 6 * h.pinch : 8, 0, 2 * Math.PI);
                        cr.fill();
                    }
                    source(cr, 'white', 0.9 * strong);
                    cr.arc(pts[i][0], pts[i][1], tip ? 3.5 : 2.2, 0, 2 * Math.PI);
                    cr.fill();
                }
            }
        }
        cr.$dispose();
    }

    _paintReticle(area) {
        const cr = area.get_context();
        const f = this._frame;
        if (f) {
            const c = RETICLE / 2;
            const t = this._phase;
            const primary = (f.hands || []).find(h => h.primary);
            const pinch = primary ? primary.pinch : 0;
            const tone = this._grabbed || f.mode === 'resize' ? 'warn' : 'accent';
            const tau = 2 * Math.PI;

            if (!f.engaged) {
                // Engaging: a faint ring and an arc that fills while the palm is held still.
                cr.setLineWidth(2);
                source(cr, 'white', 0.18);
                cr.arc(c, c, 70, 0, tau);
                cr.stroke();
                cr.setLineWidth(5);
                source(cr, 'accent', 0.95);
                cr.arc(c, c, 70, -Math.PI / 2, -Math.PI / 2 + tau * f.engage);
                cr.stroke();
                source(cr, 'cyan', 0.8);
                cr.arc(c, c, 4 + 10 * f.engage, 0, tau);
                cr.fill();
                cr.$dispose();
                return;
            }

            // Tick ring, slowly turning
            for (let i = 0; i < 60; i++) {
                const a = i / 60 * tau + t * 0.25;
                const major = i % 5 === 0;
                const r0 = major ? 86 : 91;
                cr.setLineWidth(major ? 2 : 1);
                source(cr, 'cyan', major ? 0.65 : 0.25);
                cr.moveTo(c + Math.cos(a) * r0, c + Math.sin(a) * r0);
                cr.lineTo(c + Math.cos(a) * 96, c + Math.sin(a) * 96);
                cr.stroke();
            }
            // Three arcs turning one way, two thinner ones the other
            cr.setLineWidth(3.5);
            source(cr, tone, 0.95);
            for (let k = 0; k < 3; k++) {
                const a = t * 1.3 + k * tau / 3;
                cr.newSubPath();
                cr.arc(c, c, 74, a, a + 1.25);
            }
            cr.stroke();
            cr.setLineWidth(1.5);
            source(cr, 'cyan', 0.7);
            for (let k = 0; k < 2; k++) {
                const a = -t * 0.9 + k * Math.PI;
                cr.newSubPath();
                cr.arc(c, c, 60, a, a + 1.9);
            }
            cr.stroke();
            // Inner ring: closes as the pinch closes; filled while the button is held
            const r = 44 - 26 * pinch;
            if (f.pressed) {
                source(cr, tone, 0.35);
                cr.arc(c, c, r, 0, tau);
                cr.fill();
            }
            cr.setLineWidth(2);
            source(cr, 'white', 0.9);
            cr.arc(c, c, r, 0, tau);
            cr.stroke();
            // Crosshair gaps and the centre
            source(cr, 'white', 0.75);
            cr.setLineWidth(1.5);
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
                cr.moveTo(c + dx * (r + 6), c + dy * (r + 6));
                cr.lineTo(c + dx * (r + 16), c + dy * (r + 16));
            }
            cr.stroke();
            if (f.mode === 'scroll') {
                // Chevrons above and below: the wheel is under your hand.
                cr.setLineWidth(3);
                source(cr, 'cyan', 0.95);
                for (const dir of [-1, 1]) {
                    for (const k of [0, 1]) {
                        const yy = c + dir * (r + 26 + k * 9);
                        cr.moveTo(c - 9, yy - dir * 6);
                        cr.lineTo(c, yy);
                        cr.lineTo(c + 9, yy - dir * 6);
                    }
                }
                cr.stroke();
            } else if (f.mode === 'zoom' || f.mode === 'lzoom') {
                // A magnifier's plus at the centre.
                cr.setLineWidth(3);
                source(cr, 'cyan', 0.95);
                cr.moveTo(c - 12, c); cr.lineTo(c + 12, c);
                cr.moveTo(c, c - 12); cr.lineTo(c, c + 12);
                cr.stroke();
            } else if (f.mode === 'resize') {
                cr.setLineWidth(3);
                source(cr, 'warn', 0.95);
                for (const [dx, dy] of [[1, 1], [-1, -1], [1, -1], [-1, 1]]) {
                    const ex = c + dx * (r + 30), ey = c + dy * (r + 30);
                    cr.moveTo(c + dx * (r + 14), c + dy * (r + 14));
                    cr.lineTo(ex, ey);
                    cr.moveTo(ex - dx * 9, ey); cr.lineTo(ex, ey); cr.lineTo(ex, ey - dy * 9);
                }
                cr.stroke();
            }
            source(cr, tone, 1);
            cr.arc(c, c, 3, 0, tau);
            cr.fill();
        }
        cr.$dispose();
    }

    _paintBracket(area, corner) {
        const cr = area.get_context();
        const s = BRACKET;
        const fx = corner % 2 === 0 ? 1 : -1;
        const fy = corner < 2 ? 1 : -1;
        const ox = fx > 0 ? 2 : s - 2;
        const oy = fy > 0 ? 2 : s - 2;
        cr.setLineCap(1);
        for (const [width, alpha] of [[7, 0.15], [2.5, 0.95]]) {
            cr.setLineWidth(width);
            source(cr, 'accent', alpha);
            cr.moveTo(ox, oy + fy * (s - 30));
            cr.lineTo(ox, oy);
            cr.lineTo(ox + fx * (s - 30), oy);
            cr.stroke();
        }
        source(cr, 'cyan', 0.8);
        cr.arc(ox + fx * 10, oy + fy * 10, 2.5, 0, 2 * Math.PI);
        cr.fill();
        cr.setLineWidth(1);
        source(cr, 'cyan', 0.5);
        cr.moveTo(ox + fx * 18, oy + fy * 10);
        cr.lineTo(ox + fx * 44, oy + fy * 10);
        cr.stroke();
        cr.$dispose();
    }

    // ---------------------------------------------------------------- motion

    _enter() {
        const mon = this._monitor();
        const inset = 22;
        const top = mon.y + Main.panel.height + inset;
        const spots = [
            [mon.x + inset, top], [mon.x + mon.width - inset - BRACKET, top],
            [mon.x + inset, mon.y + mon.height - inset - BRACKET],
            [mon.x + mon.width - inset - BRACKET, mon.y + mon.height - inset - BRACKET],
        ];
        this._brackets.forEach((b, i) => {
            b.set_position(spots[i][0], spots[i][1]);
            b.remove_all_transitions();
            b.translation_x = (i % 2 === 0 ? -1 : 1) * 40;
            b.translation_y = (i < 2 ? -1 : 1) * 40;
            b.ease({ opacity: 255, translation_x: 0, translation_y: 0,
                duration: Tokens.STATE_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
        });
        this._sweep.remove_all_transitions();
        this._sweep.set_position(mon.x, top);
        this._sweep.width = mon.width;
        this._sweep.translation_y = 0;
        this._sweep.opacity = 255;
        this._sweep.ease({ translation_y: mon.height - (top - mon.y) - inset, duration: Tokens.GENIE_MS,
            mode: Clutter.AnimationMode.EASE_IN_OUT_QUAD,
            onComplete: () => this._sweep.ease({ opacity: 0, duration: Tokens.PANEL_MS }) });
        this._chip.remove_all_transitions();
        this._chip.ease({ opacity: 255, duration: Tokens.STATE_MS });
    }

    _leave() {
        if (!this._layer)
            return;
        this._brackets.forEach((b, i) => {
            b.remove_all_transitions();
            b.ease({ opacity: 0, translation_x: (i % 2 === 0 ? -1 : 1) * 40,
                translation_y: (i < 2 ? -1 : 1) * 40, duration: Tokens.PANEL_MS,
                mode: Clutter.AnimationMode.EASE_IN_QUAD });
        });
        this._chip.remove_all_transitions();
        this._chip.ease({ opacity: 0, duration: Tokens.PANEL_MS });
    }

    _showToast(text, ms = 1100) {
        if (!this._layer)
            return;
        const mon = this._monitor();
        this._layer.show();
        Main.uiGroup.set_child_above_sibling(this._layer, null);
        this._toast.text = text;
        const [, natural] = this._toast.get_preferred_width(-1);
        this._toast.set_position(Math.round(mon.x + (mon.width - natural) / 2),
            Math.round(mon.y + mon.height * 0.2));
        this._toast.remove_all_transitions();
        this._toast.scale_x = this._toast.scale_y = 0.92;
        this._toast.ease({ opacity: 255, scale_x: 1, scale_y: 1, duration: Tokens.PANEL_MS,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD });
        if (this._toastId)
            GLib.source_remove(this._toastId);
        this._toastId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            this._toastId = 0;
            this._toast.ease({ opacity: 0, duration: Tokens.STATE_MS });
            return GLib.SOURCE_REMOVE;
        });
    }

    _ripple(x, y, styleClass = 'adaptive-air-ripple') {
        if (!this._layer)
            return;
        const size = 44;
        const ring = new St.Widget({ style_class: styleClass, reactive: false,
            width: size, height: size, x: x - size / 2, y: y - size / 2 });
        ring.set_pivot_point(0.5, 0.5);
        this._layer.add_child(ring);
        ring.ease({ scale_x: 2.6, scale_y: 2.6, opacity: 0, duration: Tokens.GENIE_MS,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD, onComplete: () => ring.destroy() });
    }
};
