// Adaptive Shade sparkline v1.7
//
// A fixed-width history strip drawn with Cairo. St has no chart primitive, so
// this is an St.DrawingArea with a repaint handler, the same approach the
// Projects app uses for its Cairo trend charts - shared visual language, but a
// separate implementation, since that one is GTK4 and this is Clutter/St.
//
// The sample buffer is a fixed-length array, never a growing one: the shade can
// sit open for hours and the memory it holds must not depend on how long.

/* exported Sparkline */

const { St, Clutter } = imports.gi;
const Cairo = imports.cairo;

const SAMPLES = 60;

function hexToRgb(hex) {
    return [
        parseInt(hex.slice(1, 3), 16) / 255,
        parseInt(hex.slice(3, 5), 16) / 255,
        parseInt(hex.slice(5, 7), 16) / 255,
    ];
}

var Sparkline = class Sparkline {
    // `accent` is a #rrggbb string; `scale` is the value that reaches the top of
    // the strip. Percentages pass 100; unbounded series (network throughput)
    // pass null and get rescaled to their own running peak.
    constructor(accent, scale = 100) {
        this._accent = hexToRgb(accent);
        this._scale = scale;
        this._values = new Array(SAMPLES).fill(NaN);
        this._peak = 0;

        this.actor = new St.DrawingArea({
            style_class: 'adaptive-shade-sparkline',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._repaintId = this.actor.connect(
            'repaint',
            () => this._repaint()
        );
    }

    push(value) {
        this._values.shift();
        this._values.push(value);

        if (this._scale === null) {
            // Autoscaling to the peak of the visible window only, so an old
            // burst does not flatten the chart forever after it scrolls off.
            this._peak = this._values.reduce(
                (max, v) => (Number.isFinite(v) && v > max ? v : max),
                0
            );
        }

        this.actor.queue_repaint();
    }

    reset() {
        this._values = new Array(SAMPLES).fill(NaN);
        this._peak = 0;
        this.actor.queue_repaint();
    }

    destroy() {
        if (this._repaintId) {
            this.actor.disconnect(this._repaintId);
            this._repaintId = 0;
        }
        this.actor.destroy();
        this.actor = null;
    }

    _repaint() {
        const cr = this.actor.get_context();
        const [width, height] = this.actor.get_surface_size();

        if (width <= 0 || height <= 0) {
            cr.$dispose();
            return;
        }

        const [r, g, b] = this._accent;

        // A flat baseline so an idle chart still reads as a chart rather than
        // as a rendering failure.
        cr.setLineWidth(1);
        cr.setSourceRGBA(r, g, b, 0.14);
        cr.moveTo(0, height - 0.5);
        cr.lineTo(width, height - 0.5);
        cr.stroke();

        const scale = this._scale !== null
            ? this._scale
            : Math.max(this._peak, 1);

        // Leave a pixel of headroom top and bottom so a pegged series does not
        // get its stroke clipped in half by the edge of the surface.
        const inset = 1.5;
        const usable = Math.max(1, height - inset * 2);
        const step = width / (SAMPLES - 1);

        const points = [];
        for (let i = 0; i < SAMPLES; i++) {
            const value = this._values[i];
            if (!Number.isFinite(value))
                continue;

            const clamped = Math.max(0, Math.min(1, value / scale));
            points.push({
                x: i * step,
                y: inset + (1 - clamped) * usable,
            });
        }

        // One point is not a line. Wait for a second sample.
        if (points.length < 2) {
            cr.$dispose();
            return;
        }

        // Fill under the trace first, then stroke over it.
        cr.moveTo(points[0].x, height);
        for (const point of points)
            cr.lineTo(point.x, point.y);
        cr.lineTo(points[points.length - 1].x, height);
        cr.closePath();
        cr.setSourceRGBA(r, g, b, 0.16);
        cr.fill();

        cr.setLineWidth(1.5);
        cr.setLineJoin(Cairo.LineJoin.ROUND);
        cr.setSourceRGBA(r, g, b, 0.9);
        cr.moveTo(points[0].x, points[0].y);
        for (const point of points.slice(1))
            cr.lineTo(point.x, point.y);
        cr.stroke();

        cr.$dispose();
    }
};
