// Adaptive clipboard history.
//
// What was copied to the clipboard, newest first, for the Command palette to
// search and copy back (type "clip" in it): text, and the last few images.
// The palette reaches it through org.adaptive.Shell (shellActions.js), and
// copying back goes through the shell too: on X11 a clipboard is owned by a
// process, and the palette closes right after the pick, which would take the
// content with it.
//
// Kept in memory only and never written to disk, so it ends with the session.
// Text a password manager marks as secret is skipped, as is anything copied
// while the screen is locked. An entry can be pinned: it is then kept when
// the history fills up and when it is cleared. The rules themselves (bounds,
// pins, de-duplication) are adaptiveUtil's and checked under Node.

/* exported ClipboardHistory */

const { GLib, Meta, St } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Util = Me.imports.adaptiveUtil;

const TEXT_MIMES = ['text/plain', 'text/plain;charset=utf-8', 'UTF8_STRING', 'STRING', 'TEXT'];
const IMAGE_MIME = 'image/png';

var ClipboardHistory = class ClipboardHistory {
    constructor() {
        this._items = [];
        // The copied bytes of each image entry, by its id.
        this._images = new Map();
        this._nextId = 1;
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
        this._images.clear();
    }

    _capture() {
        if (Main.sessionMode.isLocked)
            return;

        const clipboard = St.Clipboard.get_default();
        const mimes = clipboard.get_mimetypes(St.ClipboardType.CLIPBOARD) || [];
        if (Util.isSecretClipboard(mimes))
            return;

        const hasText = mimes.some(m => TEXT_MIMES.includes(m) || m.startsWith('text/'));
        // A copied image usually comes with no text at all. When an app offers
        // both (a spreadsheet range, a web page selection) the text is what
        // was meant.
        if (!hasText && mimes.includes(IMAGE_MIME)) {
            clipboard.get_content(St.ClipboardType.CLIPBOARD, IMAGE_MIME, (_clip, bytes) => {
                if (this._ownerId && bytes)
                    this._setItems(Util.clipboardPushImage(this._items, this._imageEntry(bytes)));
            });
            return;
        }
        if (mimes.length && !hasText)
            return;

        clipboard.get_text(St.ClipboardType.CLIPBOARD, (_clip, text) => {
            if (this._ownerId) {
                this._setItems(Util.clipboardPush(
                    this._items, text, Math.floor(GLib.get_real_time() / 1e6), this._nextId++));
            }
        });
    }

    _imageEntry(bytes) {
        const size = bytes.get_size();
        if (!size || size > Util.CLIPBOARD_MAX_IMAGE_BYTES)
            return null;
        const dimensions = Util.pngSize(bytes.get_data().subarray(0, 24)) || { width: 0, height: 0 };
        const id = this._nextId++;
        this._images.set(id, bytes);
        return {
            id,
            at: Math.floor(GLib.get_real_time() / 1e6),
            mime: IMAGE_MIME,
            size,
            hash: bytes.hash(),
            width: dimensions.width,
            height: dimensions.height,
        };
    }

    // Replace the list, and let go of the bytes of any image that fell out.
    _setItems(items) {
        this._items = items;
        const alive = new Set(items.filter(item => item.kind === 'image').map(item => item.id));
        for (const id of this._images.keys()) {
            if (!alive.has(id))
                this._images.delete(id);
        }
    }

    // [{ id, text, at, pinned?, kind?, size?, width?, height? }], newest first.
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

    // Copies an entry back by id: the only way to an image, which has no text.
    copyItem(id) {
        const item = this._items.find(entry => entry.id === id);
        if (!item)
            return false;
        if (item.kind !== 'image')
            return this.copy(item.text);
        const bytes = this._images.get(id);
        if (!bytes)
            return false;
        St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, item.mime, bytes);
        return true;
    }

    pin(id, pinned) {
        const before = this._items.find(entry => entry.id === id);
        this._setItems(Util.clipboardPin(this._items, id, pinned));
        const after = this._items.find(entry => entry.id === id);
        return !!before && !!after && !!after.pinned === !!pinned;
    }

    // Forgets everything except what is pinned.
    clear() {
        this._setItems(Util.clipboardClear(this._items));
    }
};
