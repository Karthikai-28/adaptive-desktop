// Adaptive Shell - display changes and bringing back windows stranded off-screen.
//
// Part of the one AdaptiveShellV16 object in extension.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the shell itself and every
// field and method of the other parts is reachable through it.

/* exported ShellDisplays */

const { GLib, Meta } = imports.gi;
const Main = imports.ui.main;

var ShellDisplays = class ShellDisplays {
    // A display appearing or disappearing can leave windows somewhere the
    // user cannot reach them.
    _onDisplaysChanged() {
        this._runDisplayGuard();

        // Mutter relocates windows itself when a monitor goes away, so give it
        // a moment and only clean up what it left behind. Running immediately
        // would fight it and move windows twice.
        if (this._rescueTimerId)
            GLib.Source.remove(this._rescueTimerId);

        this._rescueTimerId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            1500,
            () => {
                this._rescueTimerId = 0;
                this._rescueStrandedWindows();
                return GLib.SOURCE_REMOVE;
            }
        );
    }

    // An HDMI port can report "connected" with nothing plugged into it, and
    // then windows get placed on a screen that does not physically exist.
    _runDisplayGuard() {
        if (!GLib.file_test(this._displayGuard, GLib.FileTest.IS_EXECUTABLE))
            return;

        // A single unplug arrives as several monitors-changed events, and each
        // one would otherwise spawn its own xrandr.
        const now = GLib.get_monotonic_time();
        if (this._displayGuardRunAt && now - this._displayGuardRunAt < 3000000)
            return;

        this._displayGuardRunAt = now;
        this._spawn([this._displayGuard]);
    }

    _windowVisibleFraction(rect, monitors) {
        const area = rect.width * rect.height;
        if (!area)
            return 1;

        let best = 0;

        for (const monitor of monitors) {
            const ox = Math.max(
                0,
                Math.min(rect.x + rect.width, monitor.x + monitor.width) -
                    Math.max(rect.x, monitor.x)
            );
            const oy = Math.max(
                0,
                Math.min(rect.y + rect.height, monitor.y + monitor.height) -
                    Math.max(rect.y, monitor.y)
            );

            best = Math.max(best, ox * oy);
        }

        return best / area;
    }

    // Windows left on a monitor that no longer exists are still open and still
    // running - they are just nowhere you can click. Bring them back.
    _rescueStrandedWindows() {
        const monitors = Main.layoutManager.monitors || [];
        if (!monitors.length)
            return;

        const primary = Main.layoutManager.primaryIndex;
        const work = Main.layoutManager.getWorkAreaForMonitor(primary);
        let rescued = 0;

        for (const actor of global.get_window_actors()) {
            const window = actor.meta_window;
            if (!window)
                continue;

            try {
                if (window.is_override_redirect())
                    continue;

                const type = window.get_window_type();
                if (
                    type !== Meta.WindowType.NORMAL &&
                    type !== Meta.WindowType.DIALOG &&
                    type !== Meta.WindowType.MODAL_DIALOG
                )
                    continue;

                const rect = window.get_frame_rect();

                // Half on screen is still reachable - a title bar is enough to
                // drag it back. Only rescue what is genuinely gone.
                if (this._windowVisibleFraction(rect, monitors) >= 0.5)
                    continue;

                log(`[Adaptive Shell] rescuing "${window.get_title()}" from `
                    + `${rect.width}x${rect.height}+${rect.x}+${rect.y}`);

                window.move_to_monitor(primary);

                // move_to_monitor keeps the window's relative position, which
                // for a window that was off the right of a wider screen can
                // still land it outside. Clamp it into the work area.
                const moved = window.get_frame_rect();
                const x = Math.max(
                    work.x,
                    Math.min(moved.x, work.x + work.width - moved.width)
                );
                const y = Math.max(
                    work.y,
                    Math.min(moved.y, work.y + work.height - moved.height)
                );

                if (x !== moved.x || y !== moved.y)
                    window.move_frame(true, x, y);

                rescued += 1;
            } catch (e) {
                logError(e, '[Adaptive Shell] rescue window');
            }
        }

        if (rescued)
            Main.notify(
                'Adaptive Desktop',
                rescued === 1
                    ? 'Moved 1 window back from a disconnected display.'
                    : `Moved ${rescued} windows back from a disconnected display.`
            );
    }
};
