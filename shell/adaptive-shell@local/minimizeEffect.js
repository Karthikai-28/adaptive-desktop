// Genie minimise: a window is pulled down into its dock icon, and drawn back
// out of it on restore, the way macOS does it.
//
// GNOME's own minimise animation shrinks the window towards the icon
// rectangle the shell was told about (or the top-left corner if it was told
// nothing), so with a bottom dock every window flew to the wrong corner. This
// replaces it: the window texture is bent by a Clutter.DeformEffect so its
// bottom narrows into the icon and the body follows, tip first.

const { Clutter, GObject, Meta } = imports.gi;
const Main = imports.ui.main;

const DURATION_MS = 480;
// How much later the top of the window sets off than its bottom (0 = the
// whole window moves as one, larger = a longer, thinner neck).
const STAGGER = 0.7;
// How sharply the neck flares out to the full window width.
const FLARE = 2.2;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const smooth = v => {
    const t = clamp(v, 0, 1);
    return t * t * (3 - 2 * t);
};

const GenieEffect = GObject.registerClass(
class AdaptiveGenieEffect extends Clutter.DeformEffect {
    _init(origin, size, icon) {
        super._init();
        this._ax = origin.x;
        this._ay = origin.y;
        this._w = size.width;
        this._h = size.height;
        this._ix = icon.x + icon.width / 2;
        this._iy = icon.y + icon.height / 2;
        this._iw = Math.max(8, Math.min(icon.width, this._w));
        this._t = 0;
        this.set_n_tiles(6, 48);
    }

    setProgress(t) {
        this._t = clamp(t, 0, 1);
        this.invalidate();
    }

    vfunc_deform_vertex(width, height, vertex) {
        const t = this._t;
        if (t <= 0)
            return;

        const u = vertex.x / width;
        const v = vertex.y / height;

        const x0 = this._ax;
        const cx = this._ax + this._w / 2;

        const rowY = row => {
            const y = this._ay + row * this._h;
            const s = smooth(clamp(t * (1 + STAGGER) - (1 - row) * STAGGER, 0, 1));
            return y + (this._iy - y) * s;
        };

        const yTop = rowY(0);
        const y1 = rowY(v);

        const g = this._iw / this._w;
        const pinch = smooth(t / 0.55);
        const slide = smooth((t - 0.45) / 0.55);

        // 0 at the icon, 1 at the top of the window.
        const f = clamp((this._iy - y1) / Math.max(this._iy - yTop, 1), 0, 1);
        const flare = 1 - Math.pow(1 - f, FLARE);

        const widthTop = this._w * (1 - (1 - g) * slide);
        const rowWidth = widthTop * (1 - pinch * (1 - g) * (1 - flare));
        const centreTop = cx + (this._ix - cx) * slide;
        const rowCentre = centreTop + (this._ix - centreTop) * pinch * (1 - flare);

        vertex.x = rowCentre - x0 + (u - 0.5) * rowWidth;
        vertex.y = y1 - this._ay;
    }
});

var GenieMinimize = class GenieMinimize {
    // iconRectFor(metaWindow) -> {x, y, width, height} in stage pixels, or null.
    constructor(iconRectFor) {
        this._iconRectFor = iconRectFor;
        this._shellwm = null;
        this._defaults = [];
        this._ids = [];
        this._running = new Map();
    }

    attach() {
        this._shellwm = Main.wm._shellwm;
        for (const name of ['minimize', 'unminimize']) {
            // The stock handler is the first one connected. It is blocked
            // rather than removed, so detach() can hand the animation back.
            const stock = GObject.signal_handler_find(this._shellwm, { signalId: name });
            if (stock) {
                GObject.signal_handler_block(this._shellwm, stock);
                this._defaults.push(stock);
            }
        }
        this._ids.push(this._shellwm.connect('minimize',
            (wm, actor) => this._run(actor, false)));
        this._ids.push(this._shellwm.connect('unminimize',
            (wm, actor) => this._run(actor, true)));
        this._ids.push(this._shellwm.connect('kill-window-effects',
            (wm, actor) => this._finish(actor, true)));
    }

    detach() {
        for (const actor of [...this._running.keys()])
            this._finish(actor, true);
        for (const id of this._ids)
            this._shellwm.disconnect(id);
        this._ids = [];
        for (const id of this._defaults)
            GObject.signal_handler_unblock(this._shellwm, id);
        this._defaults = [];
        this._shellwm = null;
    }

    _stock(actor, restoring) {
        // The GNOME animation, for windows the genie does not suit.
        if (restoring)
            Main.wm._unminimizeWindow(this._shellwm, actor);
        else
            Main.wm._minimizeWindow(this._shellwm, actor);
    }

    _run(actor, restoring) {
        const complete = () => restoring
            ? this._shellwm.completed_unminimize(actor)
            : this._shellwm.completed_minimize(actor);

        try {
            const window = actor.meta_window;
            const types = [Meta.WindowType.NORMAL, Meta.WindowType.MODAL_DIALOG,
                Meta.WindowType.DIALOG];
            if (!types.includes(window.get_window_type()) ||
                !Main.wm._shouldAnimateActor(actor, types) ||
                window.is_monitor_sized()) {
                // _shouldAnimateActor consumed a skip request; do not ask twice.
                complete();
                return;
            }

            const icon = this._iconRectFor(window);
            if (!icon) {
                this._stock(actor, restoring);
                return;
            }
            this._animate(actor, restoring, icon, complete);
        } catch (e) {
            logError(e, '[Adaptive Shell] genie minimise');
            if (!this._finish(actor, true))
                complete();
        }
    }

    _animate(actor, restoring, icon, complete) {
        const [ax, ay] = actor.get_transformed_position();
        const effect = new GenieEffect({ x: ax, y: ay },
            { width: actor.width, height: actor.height }, icon);

        const done = () => this._finish(actor, true);

        const timeline = new Clutter.Timeline({ actor, duration: DURATION_MS });
        const set = progress => effect.setProgress(restoring ? 1 - progress : progress);
        timeline.connect('new-frame', (tl, _ms) => set(tl.get_progress()));
        timeline.connect('completed', done);

        this._running.set(actor, { effect, timeline, complete });

        actor.add_effect_with_name('adaptive-genie', effect);
        set(0);
        if (restoring)
            actor.show();
        timeline.start();
    }

    // Removes the effect and, if an animation was running, tells mutter it is
    // over. Returns whether one was.
    _finish(actor, complete) {
        const run = this._running.get(actor);
        if (!run)
            return false;
        this._running.delete(actor);
        run.timeline.stop();
        actor.remove_effect(run.effect);
        actor.set_scale(1.0, 1.0);
        actor.set_opacity(255);
        if (complete)
            run.complete();
        return true;
    }
};
