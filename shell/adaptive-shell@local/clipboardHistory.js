// Adaptive clipboard history.
//
// Every text copied to the clipboard, newest first, for the Command palette to
// search and copy back (type "clip" in it). The palette reaches it through
// org.adaptive.Shell (shellActions.js), and copying back goes through the
// shell too: on X11 a clipboard is owned by a process, and the palette closes
// right after the pick, which would take the text with it.
//
// Kept in memory only and never written to disk, so it ends with the session.
// Text a password manager marks as secret is skipped, as is anything copied
// while the screen is locked, and the palette can clear it.

/* exported ClipboardHistory */

const { GLib, Meta, St } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Util = Me.imports.adaptiveUtil;

const TEXT_MIMES = ['text/plain', 'text/plain;charset=utf-8', 'UTF8_STRING', 'STRING', 'TEXT'];

var ClipboardHistory = class ClipboardHistory {
    constructor() {
        this._items = [];
        this._selection = null;
        this._ownerId = 0;
    }

    attach() {
        this._selection = global.display.get_selection();
        this._ownerId = this._selection.connect('owner-changed', (_sel, type) => {
            if (type === Meta.SelectionType.SELECTION_CLIPBOARD)
                this._capture();
        });
    }

    detach() {
        if (this._ownerId) {
            this._selection.disconnect(this._ownerId);
            this._ownerId = 0;
        }
        this._selection = null;
        this._items = [];
    }

    _capture() {
        if (Main.sessionMode.isLocked)
            return;

        const clipboard = St.Clipboard.get_default();
        const mimes = clipboard.get_mimetypes(St.ClipboardType.CLIPBOARD) || [];
        if (Util.isSecretClipboard(mimes))
            return;
        if (mimes.length && !mimes.some(m => TEXT_MIMES.includes(m) || m.startsWith('text/')))
            return;

        clipboard.get_text(St.ClipboardType.CLIPBOARD, (_clip, text) => {
            if (this._ownerId)
                this._items = Util.clipboardPush(this._items, text, Math.floor(GLib.get_real_time() / 1e6));
        });
    }

    // [{ text, at }], newest first.
    history() {
        return this._items.slice();
    }

    // Copies text; it moves to the top of the history when the copy lands.
    copy(text) {
        if (typeof text !== 'string' || !text.length)
            return false;
        St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
        return true;
    }

    clear() {
        this._items = [];
    }
};
