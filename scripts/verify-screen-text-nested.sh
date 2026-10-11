#!/usr/bin/env bash
# Sourced by verify-shell-nested.sh --extra; runs only in its isolated desktop.
# A deterministic recognizer exercises capture, parsing and overlay without packages.
# Set ADAPTIVE_TEST_REAL_OCR=1 with tesseract in PATH for the real engine as well.
text_probe() { probe "return (async () => { $1 })();"; }
ocr_bin="$SANDBOX/ocr-bin"
mkdir -p "$ocr_bin"
cat > "$ocr_bin/tesseract" <<'PY'
#!/usr/bin/python3
import os, sys, time
from pathlib import Path
mode = Path(os.environ['ADAPTIVE_NESTED_SANDBOX']) / 'ocr-mode'
value = mode.read_text().strip() if mode.exists() else ''
if '--list-langs' in sys.argv:
    print('List of available languages (1):\n' + ('fra' if value == 'missing' else 'eng'))
    sys.exit(0)
if value == 'slow':
    time.sleep(40)
if value == 'fail':
    sys.exit(1)
if value != 'empty':
    print('5\t1\t1\t1\t1\t1\t200\t200\t80\t24\t95\tHello')
    print('5\t1\t1\t1\t1\t2\t300\t200\t80\t24\t95\tworld')
    print('5\t1\t1\t1\t2\t1\t200\t240\t80\t24\t95\tAgain')
PY
chmod +x "$ocr_bin/tesseract"
# PATH is changed inside the nested shell only.
text_probe "global._textNotices = []; global._textNotify = Main.notify; Main.notify = (...args) => { global._textNotices.push(args); global._textNotify(...args); }; global._ocrOldPath = imports.gi.GLib.getenv('PATH'); imports.gi.GLib.setenv('PATH', '$ocr_bin:' + global._ocrOldPath, true); global._textTest = new adaptive.screenText.ScreenText(); return true;" >/dev/null
text_start='global._textTest.start();'
text_ready="$SLEEP for (let i = 0; i < 100; i++) { const s = global._textTest._session; if (s && s.words.length && !s.timer) return true; await sleep(50); } return false;"
[ "$(text_probe "$text_start return global._textTest.start() === false;")" = true ]; check $? "screen text: repeated activation refused"
ready="$(text_probe "$text_ready")"
[ "$ready" = true ]; check $? "screen text: real capture, PNG export, recognizer and overlay complete"
if [ "$ready" != true ]; then
    echo "Diagnostic: $ready"
    text_probe 'return {notices: global._textNotices, state: global._textTest._session ? {words: global._textTest._session.words.length, status: global._textTest._session.status?.text} : null};'
fi
[ "$(text_probe 'const s = global._textTest._session; return !!s && !!s.grab && s.words.length === 3 && !imports.gi.GLib.file_test(s.directory, imports.gi.GLib.FileTest.EXISTS);')" = true ]; check $? "screen text: modal active, word boxes loaded, temporary images removed"
[ "$(text_probe 'const t = global._textTest, s = t._session; t._key(s, {get_key_symbol: () => imports.gi.Clutter.KEY_a, get_state: () => imports.gi.Clutter.ModifierType.CONTROL_MASK}); const ok = s.selected.length === 3; t._copy(s); return ok && t._session === null && s.grab === null;')" = true ]; check $? "screen text: Ctrl+A selects all and Copy closes modal"
[ "$(text_probe "return new Promise(r => imports.gi.St.Clipboard.get_default().get_text(imports.gi.St.ClipboardType.CLIPBOARD, (_c, text) => r(text === ['Hello world', 'Again'].join(String.fromCharCode(10)))));")" = true ]; check $? "screen text: clipboard keeps word order and line breaks"
# Escape preserves the current clipboard, including during recognition.
echo slow > "$SANDBOX/ocr-mode"
text_probe "$text_start return true;" >/dev/null
[ "$(text_probe "$SLEEP for (let i=0; i<100 && !global._textTest._session?.proc; i++) await sleep(50); const t=global._textTest, s=t._session; t._key(s, {get_key_symbol: () => imports.gi.Clutter.KEY_Escape}); await sleep(100); return !t._session && !s.grab && !imports.gi.GLib.file_test(s.directory || '/nonexistent', imports.gi.GLib.FileTest.EXISTS);")" = true ]; check $? "screen text: Escape cancels recognition and cleans up"
[ "$(text_probe "return new Promise(r => imports.gi.St.Clipboard.get_default().get_text(imports.gi.St.ClipboardType.CLIPBOARD, (_c, text) => r(text === ['Hello world', 'Again'].join(String.fromCharCode(10)))));")" = true ]; check $? "screen text: cancellation preserves clipboard"
for mode in missing fail; do
    echo "$mode" > "$SANDBOX/ocr-mode"
    [ "$(text_probe "$text_start $SLEEP for (let i=0; i<100; i++) { if (!global._textTest._session) return true; await sleep(50); } return false;")" = true ]
    check $? "screen text: $mode recognition releases modal"
done
echo empty > "$SANDBOX/ocr-mode"
[ "$(text_probe "$text_start $SLEEP for (let i=0; i<100; i++) { const s=global._textTest._session; if (s?.status?.text.startsWith('No text')) { const ok=!s.copy.reactive; global._textTest._close(s); return ok; } await sleep(50); } return false;")" = true ]; check $? "screen text: no-text state cannot overwrite clipboard"
rm -f "$SANDBOX/ocr-mode"
[ "$(text_probe "$text_start $SLEEP await sleep(500); global._textTest.detach(); await sleep(100); return !global._textTest._session && !global._textTest.start();")" = true ]; check $? "screen text: detach cancels and prevents reopening"
# A monitor reconfiguration must release the grab even during recognition.
echo slow > "$SANDBOX/ocr-mode"
[ "$(text_probe "global._textTest = new adaptive.screenText.ScreenText(); $text_start $SLEEP await sleep(500); Main.layoutManager.emit('monitors-changed'); await sleep(100); return !global._textTest._session;")" = true ]; check $? "screen text: display change cancels selection"
[ "$(text_probe "$text_start $SLEEP await sleep(600); Main.screenShield.lock(false); await sleep(500); const closed=!global._textTest._session; const refused=!global._textTest.start(); Main.screenShield.deactivate(false); await sleep(700); return closed && refused;")" = true ]; check $? "screen text: lock cancels selection and refuses new capture"
[ "$(text_probe "imports.gi.GLib.setenv('PATH', '/nonexistent', true); const refused=!global._textTest.start(); imports.gi.GLib.setenv('PATH', '$ocr_bin:' + global._ocrOldPath, true); return refused && !global._textTest._session;")" = true ]; check $? "screen text: missing executable leaves the clipboard and modal alone"
# Check the actual 30-second deadline with short D-Bus calls (each call has its own timeout).
text_probe "$text_start return true;" >/dev/null
text_finished() { [ "$(text_probe 'return !global._textTest._session;')" = true ]; }
wait_for 35 text_finished
check $? "screen text: hung recognizer is terminated after 30 seconds"
[ "$(text_probe "return global._textNotices.some(n => n[1].includes('timed out'));")" = true ]; check $? "screen text: timeout reports a useful message"
rm -f "$SANDBOX/ocr-mode"
text_probe "imports.gi.GLib.setenv('PATH', global._ocrOldPath, true); return true;" >/dev/null
if [ "${ADAPTIVE_TEST_REAL_OCR:-0}" = 1 ]; then
    . "$REPO/scripts/verify-screen-text-real.sh"
fi
text_probe "imports.gi.GLib.setenv('PATH', global._ocrOldPath, true); Main.notify = global._textNotify; delete global._textNotify; delete global._textNotices; delete global._textTest; delete global._ocrOldPath; return true;" >/dev/null
