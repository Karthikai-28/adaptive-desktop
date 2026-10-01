/* exported init, enable, disable */
'use strict';

// Test-only probe for scripts/verify-shell-nested.sh.
//
// GNOME 41+ refuses org.gnome.Shell.Eval to other processes, so a check
// running outside the shell cannot see a panel button, open a menu or count
// its items - which is where a GJS module actually breaks. This exports that
// one ability on the sandbox's private session bus:
//
//   org.adaptive.Probe.Eval(js) -> JSON of what the snippet returned
//
// The snippet is the body of a function given Main, global, imports and
// `adaptive` (the Adaptive extension's module scope). A promise is awaited.
//
// It evaluates code, so it only starts when ADAPTIVE_NESTED_SANDBOX names the
// sandbox the verifier made, and it is never copied anywhere but that sandbox.

const { Gio, GLib } = imports.gi;
const Main = imports.ui.main;
const ExtensionUtils = imports.misc.extensionUtils;

const PATH = '/org/adaptive/Probe';
const XML = `
<node>
  <interface name="org.adaptive.Probe">
    <method name="Eval">
      <arg type="s" name="js" direction="in"/>
      <arg type="s" name="json" direction="out"/>
    </method>
  </interface>
</node>`;

class Probe {
    EvalAsync([js], invocation) {
        const reply = value => invocation.return_value(new GLib.Variant('(s)', [value]));
        const fail = e => reply(JSON.stringify({ error: `${e}`, stack: e && e.stack ? e.stack : '' }));
        try {
            const adaptive = Main.extensionManager.lookup('adaptive-shell@local');
            const body = new Function('Main', 'global', 'imports', 'adaptive', js);
            Promise.resolve(body(Main, global, imports, adaptive ? adaptive.imports : null))
                .then(value => reply(JSON.stringify(value === undefined ? null : value)), fail);
        } catch (e) {
            fail(e);
        }
    }
}

let _export = null;

function init() {
}

function enable() {
    const sandbox = GLib.getenv('ADAPTIVE_NESTED_SANDBOX');
    if (!sandbox || !GLib.get_home_dir().startsWith(sandbox)) {
        log('[Adaptive Probe] not in the verifier sandbox; staying off');
        return;
    }
    _export = Gio.DBusExportedObject.wrapJSObject(XML, new Probe());
    _export.export(Gio.DBus.session, PATH);
}

function disable() {
    if (_export) {
        _export.unexport();
        _export = null;
    }
}
