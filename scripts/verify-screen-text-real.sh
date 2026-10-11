#!/usr/bin/env bash
# Sourced from the screen text nested verifier when a real engine is in PATH.
# The fixture is rendered as pixels so the recognizer never receives its text.
[ "$(text_probe "
    const {St, Clutter} = imports.gi;
    global._ocrFixture = new St.DrawingArea({x: 60, y: 180, width: 650, height: 220});
    global._ocrFixture.connect('repaint', actor => {
        const cr = actor.get_context();
        cr.setSourceRGB(1, 1, 1); cr.paint();
        cr.setSourceRGB(0, 0, 0); cr.selectFontFace('Sans', 0, 0); cr.setFontSize(32);
        cr.moveTo(25, 65); cr.showText('Visible image text');
        cr.moveTo(25, 120); cr.showText('Copy these English words');
        cr.\$dispose();
    });
    Main.layoutManager.addTopChrome(global._ocrFixture);
    $SLEEP await sleep(300);
    global._textTest = new adaptive.screenText.ScreenText();
    return global._textTest.start();")" = true ]; check $? "screen text: real English OCR starts on rendered bitmap"
real_ready() {
    [ "$(text_probe 'const s=global._textTest._session; return !!s && s.ready;')" = true ]
}
wait_for 35 real_ready
check $? "screen text: real English recognition completes"
[ "$(text_probe 'const s=global._textTest._session; if (!s) return false; const text=s.words.map(w=>w.text).join(" "); return text.includes("Visible image text") && text.includes("Copy these English words");')" = true ]; check $? "screen text: real OCR reads the bitmap words"
# Check a real mouse click using Mutter's virtual pointer, not a handler stub.
[ "$(text_probe "
    const {Clutter} = imports.gi;
    const s=global._textTest._session;
    const i=s.words.findIndex(w=>w.text==='Visible');
    if(i<0) return false;
    const w=s.words[i];
    global._ocrPointer=Clutter.get_default_backend().get_default_seat().create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
    global._ocrPointer.notify_absolute_motion(imports.gi.GLib.get_monotonic_time(), w.x+w.width/2, w.y+w.height/2);
    $SLEEP await sleep(100);
    global._ocrPointer.notify_button(imports.gi.GLib.get_monotonic_time(), 1, Clutter.ButtonState.PRESSED);
    await sleep(100);
    global._ocrPointer.notify_button(imports.gi.GLib.get_monotonic_time(), 1, Clutter.ButtonState.RELEASED);
    await sleep(100);
    return s.selected.length===1 && s.selected[0]===i;")" = true ]; check $? "screen text: real pointer selects the recognized word"
# Drag backwards across the first line, then double-click to select that line.
[ "$(text_probe "
    const {Clutter} = imports.gi, s=global._textTest._session;
    const first=s.words.findIndex(w=>w.text==='Visible');
    const last=s.words.findIndex(w=>w.text==='text' && w.lineId===s.words[first]?.lineId);
    if(first<0 || last<0) return false;
    const a=s.words[last], b=s.words[first], pointer=global._ocrPointer;
    $SLEEP await sleep(400);
    pointer.notify_absolute_motion(imports.gi.GLib.get_monotonic_time(), a.x+a.width/2, a.y+a.height/2); await sleep(80);
    pointer.notify_button(imports.gi.GLib.get_monotonic_time(), 1, Clutter.ButtonState.PRESSED); await sleep(80);
    pointer.notify_absolute_motion(imports.gi.GLib.get_monotonic_time(), b.x+b.width/2, b.y+b.height/2); await sleep(80);
    pointer.notify_button(imports.gi.GLib.get_monotonic_time(), 1, Clutter.ButtonState.RELEASED); await sleep(80);
    return adaptive.screenTextModel.selectionText(s.words, s.selected)==='Visible image text';")" = true ]; check $? "screen text: real reverse drag selects words in reading order"
[ "$(text_probe "
    const {Clutter} = imports.gi, s=global._textTest._session, pointer=global._ocrPointer;
    $SLEEP await sleep(400);
    for(let i=0;i<2;i++) {
        pointer.notify_button(imports.gi.GLib.get_monotonic_time(), 1, Clutter.ButtonState.PRESSED); await sleep(50);
        pointer.notify_button(imports.gi.GLib.get_monotonic_time(), 1, Clutter.ButtonState.RELEASED); await sleep(50);
    }
    return adaptive.screenTextModel.selectionText(s.words, s.selected)==='Visible image text';")" = true ]; check $? "screen text: real double-click selects a line"
text_probe "const stream=imports.gi.Gio.File.new_for_path('$SANDBOX/screen-text-overlay.png').replace(null,false,imports.gi.Gio.FileCreateFlags.PRIVATE,null); try { await new imports.gi.Shell.Screenshot().screenshot(false,stream); } finally { stream.close(null); } return true;" >/dev/null
text_probe 'global._textTest.detach(); global._ocrFixture.destroy(); delete global._ocrFixture; delete global._ocrPointer; return true;' >/dev/null
