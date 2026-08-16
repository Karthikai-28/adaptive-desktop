#!/usr/bin/env python3
from pathlib import Path
import re
import shutil

path = Path.home() / "adaptive-desktop/shell/adaptive-shell@local/extension.js"
if not path.exists():
    raise SystemExit(f"Adaptive Shell not found: {path}")

src = path.read_text()
backup = path.with_name("extension.js.before-files-integration")
if not backup.exists():
    shutil.copy2(path, backup)

# Ensure Gio + GLib are imported.
if "Gio" not in src.split("imports.gi", 1)[0]:
    src = re.sub(
        r"const\s*\{\s*St\s*,\s*Clutter\s*\}\s*=\s*imports\.gi\s*;",
        "const { St, Clutter, Gio, GLib } = imports.gi;",
        src,
        count=1,
    )

if "function launchAdaptiveFiles()" not in src:
    anchor = "function createRail()"
    index = src.find(anchor)
    if index < 0:
        raise SystemExit("Could not find createRail(); no changes written.")

    helper = r"""
function launchAdaptiveFiles() {
    const launcher = GLib.build_filenamev([
        GLib.get_home_dir(),
        '.local',
        'bin',
        'adaptive-files',
    ]);

    try {
        Gio.Subprocess.new(
            [launcher],
            Gio.SubprocessFlags.NONE
        );
    } catch (error) {
        logError(error, 'Adaptive Files launch failed');
    }
}

function makeRailAssetButton(assetName, name, action) {
    const button = new St.Button({
        style_class: 'adaptive-rail-button',
        reactive: true,
        can_focus: true,
        track_hover: true,
        accessible_name: name,
        x_align: Clutter.ActorAlign.CENTER,
        y_align: Clutter.ActorAlign.CENTER,
    });

    const assetPath = GLib.build_filenamev([
        GLib.get_home_dir(),
        'adaptive-desktop',
        'apps',
        'adaptive-files',
        'assets',
        assetName,
    ]);

    const icon = new St.Icon({
        gicon: new Gio.FileIcon({
            file: Gio.File.new_for_path(assetPath),
        }),
        style_class: 'adaptive-rail-icon',
        icon_size: 20,
    });

    button.set_child(icon);
    button.connect('clicked', action);
    return button;
}

"""
    src = src[:index] + helper + src[index:]

if "makeRailAssetButton(" not in src[src.find("function createRail()"):]:
    pattern = re.compile(
        r"(topGroup\.add_child\(\s*makeRailButton\(\s*'go-home-symbolic'.*?\)\s*\);)",
        re.S,
    )
    match = pattern.search(src)
    if not match:
        raise SystemExit(
            "Could not locate the Home button in createRail(). "
            "No changes written; apply the launcher manually."
        )

    insertion = match.group(1) + r"""

    topGroup.add_child(
        makeRailAssetButton(
            'folder-nav.svg',
            'Files',
            launchAdaptiveFiles
        )
    );"""

    src = src[:match.start()] + insertion + src[match.end():]

path.write_text(src)
print(f"Patched: {path}")
print(f"Backup:  {backup}")
print("Now sync and reload adaptive-shell@local.")
