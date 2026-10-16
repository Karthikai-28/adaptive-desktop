// Adaptive Shell - where the adaptive-desktop checkout is, for the modules
// that run its scripts. The decision is AdaptiveUtil.resolveAdaptiveDir (pure,
// checked under Node); this only gathers what it decides from.

/* exported adaptiveDir */

const { GLib } = imports.gi;
const ExtensionUtils = imports.misc.extensionUtils;
const Me = ExtensionUtils.getCurrentExtension();
const AdaptiveUtil = Me.imports.adaptiveUtil;

// What install.sh recorded in ~/.config/adaptive-desktop/repo, or null.
function _recorded() {
    try {
        const path = GLib.build_filenamev([GLib.get_user_config_dir(), 'adaptive-desktop', 'repo']);
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? new TextDecoder().decode(bytes) : null;
    } catch (_e) {
        return null;
    }
}

function adaptiveDir() {
    return AdaptiveUtil.resolveAdaptiveDir(
        GLib.get_home_dir(),
        GLib.getenv('ADAPTIVE_REPO') || GLib.getenv('ADAPTIVE_DESKTOP_DIR'),
        Me.dir ? Me.dir.get_path() : null,
        _recorded());
}
