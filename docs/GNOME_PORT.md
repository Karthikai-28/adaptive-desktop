# Porting to GNOME 45+ and Wayland — assessment

Status: **not started, by decision.** This branch targets Ubuntu 22.04 and
GNOME Shell 42 on X11 (see the README: "Do not broaden compatibility on this
branch without preserving Jammy/GNOME 42 first"). This page records what a
port would involve, so the decision can be made with the cost in view.

Why it will come up: standard support for Ubuntu 22.04 ends in April 2027.
Ubuntu 24.04 ships GNOME 46 and defaults to Wayland.

Nothing here has been run on GNOME 45 or later; it is an inventory of this
repository's code against the changes GNOME made, and should be read as an
estimate.

## The shell extension

31 modules, about 16,900 lines, in `shell/adaptive-shell@local/`.

**One extension cannot serve both.** GNOME 45 loads extensions as ES modules;
GNOME 42 cannot load an ES module extension, and 45 cannot load a legacy one.
A port is a second build of the extension, not a compatibility layer, and
Jammy would have to keep the current one.

| What changes | Where it is used here | Size of the work |
| --- | --- | --- |
| `imports.gi.*`, `imports.ui.*`, `imports.misc.*` become `import ... from 'gi://...'` and `resource:///...` | about 106 import lines across every module | Mechanical |
| `Me.imports.x` becomes a relative `import` | 45 places; the two classes spread over files (`extension.js` + `shell*.js`, `controlCenter.js` + `cc*.js`) copy methods onto a prototype, which works unchanged with ES modules | Mechanical |
| `init/enable/disable` functions become a default-exported `Extension` class | `extension.js` | Small |
| `log()` / `logError()` globals are gone (`console.*`) | 129 calls | Mechanical |
| `ExtensionUtils.getCurrentExtension()` is gone | 18 imports | Mechanical |
| **The system menu was replaced by Quick Settings (GNOME 43)**; `Main.panel.statusArea.aggregateMenu` no longer exists | The whole Control Center is built on it (`controlCenter.js`, `cc*.js`, about 3,900 lines), and five other modules reach for it | **Rewrite.** GNOME's Quick Settings already provides tiles and sliders, so much of the Control Center would be re-based on it or dropped |
| The date menu's internals moved | The Shade reaches into them in 19 places (`shade.js`, `notifications.js`) | Rework, checked against each release |
| `add_actor` / `remove_actor` removed (GNOME 46) | 9 calls | Small |
| `imports.ui.status.volume` and `rfkill` restructured for Quick Settings | Control Center | Part of the rewrite above |
| Screenshot UI internals | `screenText.js`, screen-record tile | Rework |

The dock (`shellDock*.js`, about 3,100 lines) uses stable Clutter, St and Meta
APIs and should port with little more than the import changes; so should the
lock screen module, the project indicator, clipboard history, snapshots and
the drop-down terminal.

## Outside the shell: X11 assumptions

These work only on X11 today and need a Wayland answer, whatever the GNOME
version:

| Component | X11 dependency | On Wayland |
| --- | --- | --- |
| Command palette (`apps/adaptive-command`) | positions and focuses its own window with `xdotool` | A normal app cannot place itself. Either the shell places it (as it does the drop-down terminal), or the palette becomes a shell surface |
| `scripts/window-cli.py` (tiling, placement) | `xdotool`, `wmctrl` | Move into the shell, which can do all of it natively |
| `scripts/adaptive-gestures.py` | reads libinput itself because X11 has no touchpad gestures | Unnecessary: GNOME's own gestures exist on Wayland. The service would be dropped |
| `scripts/adaptive-display-guard.py` | `xrandr` | Mutter's DisplayConfig D-Bus API, or drop it if the ghost-output problem does not occur under Wayland |
| Drop-down terminal | finds its window by X11 role after a shell restart | Already falls back to the window class when there is no role |
| `scripts/adaptive-lid-watch.sh`, lock preview | X11 tools | Re-check against Wayland session behaviour |

The Nautilus fork is a separate question: it is Nautilus 42 with the GTK 3
extension API. Nautilus 43+ moved to GTK 4 and removed
`LocationWidgetProvider`, which is how the inspector attaches. On a newer
Ubuntu the inspector would need the fork carried forward or a different
attachment.

## What is already in place for a port

- `scripts/verify-shell-nested.sh` loads the extension into a real nested
  GNOME Shell and exercises it. On a machine with GNOME 46 the same script
  would test a ported extension, which is the only practical way to port
  16,900 lines without a second physical machine.
- `scripts/verify-shell-imports.py` and `verify-shell-methods.py` check
  cross-file references statically; both need a small update for `import`
  syntax.
- Decisions were moved out of GNOME-specific code into `adaptiveUtil.js`
  (no imports, tested under Node), which ports as it is.

## A reasonable order, if it is done

1. A 24.04 virtual machine with the nested-shell check running there.
2. Mechanical conversion of every module to ES modules; get the dock, lock
   screen and palette bridge loading.
3. Decide the Control Center's future on Quick Settings before porting any
   of it.
4. Shade and notifications against the new date menu.
5. Move window placement into the shell and retire the X11 helpers.
6. Decide what happens to the Nautilus fork.
