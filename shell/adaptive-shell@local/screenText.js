// Adaptive screen text - copy the text out of any part of the screen.
//
// Drag a rectangle, and the words in it land on the clipboard: GNOME's own
// area selector, the shell's own screenshot of just that area, and tesseract
// reading it. Nothing leaves the machine. Needs `sudo apt install
// tesseract-ocr`, which the notification says if it is missing.
//
// Reached from the Control Center header, the Command palette ("Copy text
// from screen") and org.adaptive.Shell.CopyScreenText.

/* exported ScreenText */

const { Gio, GLib, Shell, St } = imports.gi;
const Main = imports.ui.main;
const Screenshot = imports.ui.screenshot;

const PREVIEW_CHARS = 90;

var ScreenText = class ScreenText {
    constructor() {
        this._busy = false;
    }

    detach() {
        this._busy = false;
    }

    // Starts the selection; the result is reported by notification.
    start() {
        if (this._busy)
            return false;
        if (!GLib.find_program_in_path('tesseract')) {
            Main.notify('Copy text from screen',
                'Text recognition needs tesseract: sudo apt install tesseract-ocr');
            return false;
        }
        this._busy = true;
        this._run().catch(e => {
            if (!e.matches || !e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED)) {
                logError(e, '[Adaptive Screen Text]');
                Main.notify('Copy text from screen', `Failed: ${e.message}`);
            }
        }).finally(() => {
            this._busy = false;
        });
        return true;
    }

    async _run() {
        const rect = await this._selectArea();
        if (!rect || rect.width < 4 || rect.height < 4)
            return;

        const path = GLib.build_filenamev([GLib.get_tmp_dir(),
            `adaptive-screen-text-${GLib.get_real_time()}.png`]);
        try {
            await this._capture(rect, path);
            const text = (await this._recognise(path)).trim();
            if (!text) {
                Main.notify('Copy text from screen', 'No text found in that area');
                return;
            }
            St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
            const preview = text.replace(/\s+/g, ' ');
            Main.notify(`Copied ${text.length} characters`,
                preview.length > PREVIEW_CHARS ? `${preview.slice(0, PREVIEW_CHARS)}…` : preview);
        } finally {
            try {
                Gio.File.new_for_path(path).delete(null);
            } catch (e) {
                // Never written; nothing to remove.
            }
        }
    }

    // GNOME 41+ has selectAsync(); GNOME 40 only the 'finished' signal.
    _selectArea() {
        const area = new Screenshot.SelectArea();
        if (typeof area.selectAsync === 'function')
            return area.selectAsync();
        return new Promise(resolve => {
            area.connect('finished', (_a, rect) => resolve(rect));
            area.show();
        });
    }

    _capture(rect, path) {
        return new Promise((resolve, reject) => {
            const stream = Gio.File.new_for_path(path)
                .replace(null, false, Gio.FileCreateFlags.PRIVATE, null);
            const shooter = new Shell.Screenshot();
            shooter.screenshot_area(rect.x, rect.y, rect.width, rect.height, stream, (s, res) => {
                try {
                    s.screenshot_area_finish(res);
                    stream.close(null);
                    resolve();
                } catch (e) {
                    reject(e);
                }
            });
        });
    }

    _recognise(path) {
        return new Promise((resolve, reject) => {
            const proc = Gio.Subprocess.new(['tesseract', path, '-'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    const [, out] = p.communicate_utf8_finish(res);
                    resolve(out || '');
                } catch (e) {
                    reject(e);
                }
            });
        });
    }
};
