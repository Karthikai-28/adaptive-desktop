#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
UUID="adaptive-shell@local"
SOURCE="$REPO/shell/$UUID"
EXT="$SOURCE/extension.js"
CSS="$SOURCE/stylesheet.css"
WINDOW_CLI="$REPO/scripts/window-cli.py"
TOKENS="$REPO/tokens/adaptive.tokens.json"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$REPO/backups/bottom-dock-v2-$STAMP"
STATE_DIR="$HOME/.config/adaptive-desktop"
STATE_FILE="$STATE_DIR/last-bottom-dock-v2-backup"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

[[ -d "$REPO" ]] || fail "Repository not found: $REPO"
[[ -f "$EXT" ]] || fail "Missing $EXT"
[[ -f "$CSS" ]] || fail "Missing $CSS"
[[ -f "$WINDOW_CLI" ]] || fail "Missing $WINDOW_CLI"
[[ -f "$TOKENS" ]] || fail "Missing $TOKENS"
[[ -x "$REPO/scripts/sync-shell.sh" ]] || fail "Missing executable scripts/sync-shell.sh"

mkdir -p "$BACKUP/shell" "$BACKUP/scripts" "$BACKUP/tokens" "$STATE_DIR"
cp -a "$EXT" "$BACKUP/shell/extension.js"
cp -a "$CSS" "$BACKUP/shell/stylesheet.css"
cp -a "$WINDOW_CLI" "$BACKUP/scripts/window-cli.py"
cp -a "$TOKENS" "$BACKUP/tokens/adaptive.tokens.json"
printf '%s\n' "$BACKUP" > "$STATE_FILE"

echo "Backup created:"
echo "  $BACKUP"

python3 - "$REPO" <<'PY'
from pathlib import Path
import json
import sys

repo = Path(sys.argv[1])
ext_path = repo / "shell/adaptive-shell@local/extension.js"
css_path = repo / "shell/adaptive-shell@local/stylesheet.css"
window_cli_path = repo / "scripts/window-cli.py"
tokens_path = repo / "tokens/adaptive.tokens.json"

MARKER = "Adaptive bottom dock stability v2"


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text, start, end, new, label):
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{label}: start marker not found")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:a] + new + text[b:]


src = ext_path.read_text(encoding="utf-8")

if MARKER not in src:
    src = replace_once(
        src,
        "        this._rail = null;\n        this._dockAppsBox = null;",
        "        this._rail = null;\n"
        "        // Adaptive bottom dock stability v2.\n"
        "        // The transparent dock chrome owns the bottom work-area strut.\n"
        "        this._dockChrome = null;\n"
        "        this._dockAppsBox = null;",
        "constructor dock chrome",
    )

    src = replace_once(
        src,
        "        this._tooltip = null;\n",
        "        this._tooltip = null;\n"
        "        this._tooltipTimeoutId = 0;\n"
        "        this._dockDemagnifyId = 0;\n",
        "constructor timers",
    )

    src = replace_once(
        src,
        "        this._focusWindowId = global.display.connect(\n"
        "            'notify::focus-window',\n"
        "            () => this._queueWindowListRefresh()\n"
        "        );",
        "        this._focusWindowId = global.display.connect(\n"
        "            'notify::focus-window',\n"
        "            () => this._syncDockActive()\n"
        "        );",
        "focus signal",
    )

    new_disable = '''    disable() {
        log('[Adaptive Shell] disable');

        if (this._monitorChangedId) {
            Main.layoutManager.disconnect(this._monitorChangedId);
            this._monitorChangedId = 0;
        }

        if (this._overviewShowingId) {
            Main.overview.disconnect(this._overviewShowingId);
            this._overviewShowingId = 0;
        }

        if (this._overviewHiddenId) {
            Main.overview.disconnect(this._overviewHiddenId);
            this._overviewHiddenId = 0;
        }

        if (this._windowCreatedId) {
            global.display.disconnect(this._windowCreatedId);
            this._windowCreatedId = 0;
        }

        if (this._focusWindowId) {
            global.display.disconnect(this._focusWindowId);
            this._focusWindowId = 0;
        }

        if (this._favorites && this._favoritesChangedId) {
            try {
                this._favorites.disconnect(this._favoritesChangedId);
            } catch (e) {
                logError(e, '[Adaptive Shell] disconnect favorites');
            }
            this._favoritesChangedId = 0;
        }

        if (this._appStateChangedId) {
            try {
                Shell.AppSystem.get_default().disconnect(this._appStateChangedId);
            } catch (e) {
                logError(e, '[Adaptive Shell] disconnect app-state');
            }
            this._appStateChangedId = 0;
        }

        if (this._windowRefreshId) {
            GLib.Source.remove(this._windowRefreshId);
            this._windowRefreshId = 0;
        }

        if (this._tooltipTimeoutId) {
            GLib.Source.remove(this._tooltipTimeoutId);
            this._tooltipTimeoutId = 0;
        }

        if (this._dockDemagnifyId) {
            GLib.Source.remove(this._dockDemagnifyId);
            this._dockDemagnifyId = 0;
        }

        this._disconnectWindowSignals();
        this._destroyDockMenus();
        this._hideTooltip();

        if (this._dockChrome) {
            Main.layoutManager.removeChrome(this._dockChrome);
            this._dockChrome.destroy();
            this._dockChrome = null;
            this._rail = null;
        } else if (this._rail) {
            Main.layoutManager.removeChrome(this._rail);
            this._rail.destroy();
            this._rail = null;
        }

        this._dockAppsBox = null;
        this._dockButtons = [];
        this._showAppsButton = null;
        this._favorites = null;
        this._dockMenuManager = null;

        if (this._brandButton) {
            this._brandButton.destroy();
            this._brandButton = null;
        }

        if (this._projectButton) {
            this._projectButton.destroy();
            this._projectButton = null;
        }

        if (this._projectProxy)
            this._projectProxy = null;

        if (this._clockActor) {
            try {
                this._clockActor.remove_style_class_name('adaptive-stock-clock');
            } catch (e) {
                logError(e, '[Adaptive Shell] clock cleanup');
            }
            this._clockActor = null;
        }

        for (const item of this._hiddenActors) {
            try {
                if (item.wasVisible)
                    item.actor.show();
                else
                    item.actor.hide();
            } catch (e) {
                logError(e, '[Adaptive Shell] restore actor');
            }
        }

        this._hiddenActors = [];
    }

'''
    src = replace_between(src, "    disable() {\n", "    _actor(item) {\n", new_disable, "disable")

    new_install = '''    _installRail() {
        this._dockChrome = new St.Widget({
            reactive: false,
            style_class: 'adaptive-dock-reservation',
            layout_manager: new Clutter.BinLayout(),
        });

        this._rail = new St.BoxLayout({
            vertical: false,
            reactive: true,
            style_class: 'adaptive-rail',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.END,
        });

        this._dockChrome.add_child(this._rail);

        this._dockMenuManager = new PopupMenu.PopupMenuManager({
            actor: this._rail,
        });

        this._dockAppsBox = new St.BoxLayout({
            vertical: false,
            reactive: true,
            style_class: 'adaptive-window-list',
        });
        this._rail.add_child(this._dockAppsBox);

        const separator = new St.Widget({
            style_class: 'adaptive-rail-rule',
        });
        this._rail.add_child(separator);

        this._showAppsButton = this._utilityDockButton(
            'apps.svg',
            'Applications',
            () => this._showApplications()
        );
        this._rail.add_child(this._showAppsButton);

        Main.layoutManager.addChrome(
            this._dockChrome,
            {
                affectsStruts: true,
                trackFullscreen: true,
            }
        );
    }

'''
    src = replace_between(src, "    _installRail() {\n", "    _readCommand(argv, callback) {\n", new_install, "install dock")

    new_tooltip = '''    _addTooltip(actor, text) {
        actor.connect('notify::hover', () => {
            if (actor.hover) {
                if (this._dockDemagnifyId) {
                    GLib.Source.remove(this._dockDemagnifyId);
                    this._dockDemagnifyId = 0;
                }

                if (this._tooltipTimeoutId) {
                    GLib.Source.remove(this._tooltipTimeoutId);
                    this._tooltipTimeoutId = 0;
                }

                this._magnifyDock(actor);

                this._tooltipTimeoutId = GLib.timeout_add(
                    GLib.PRIORITY_DEFAULT,
                    280,
                    () => {
                        this._tooltipTimeoutId = 0;
                        if (actor.hover)
                            this._showTooltip(actor, text);
                        return GLib.SOURCE_REMOVE;
                    }
                );
            } else {
                if (this._tooltipTimeoutId) {
                    GLib.Source.remove(this._tooltipTimeoutId);
                    this._tooltipTimeoutId = 0;
                }

                this._hideTooltip();
                this._scheduleDockDemagnify();
            }
        });

        actor.connect('destroy', () => {
            if (this._tooltipTimeoutId) {
                GLib.Source.remove(this._tooltipTimeoutId);
                this._tooltipTimeoutId = 0;
            }
            this._hideTooltip();
        });
    }

    _scheduleDockDemagnify() {
        if (this._dockDemagnifyId)
            GLib.Source.remove(this._dockDemagnifyId);

        this._dockDemagnifyId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            85,
            () => {
                this._dockDemagnifyId = 0;
                const hovered = this._dockButtons.find(
                    button => button && button.hover
                );
                this._magnifyDock(hovered || null);
                return GLib.SOURCE_REMOVE;
            }
        );
    }

'''
    src = replace_between(src, "    _addTooltip(actor, text) {\n", "    _showTooltip(actor, text) {\n", new_tooltip, "hover")

    new_queue = '''    _queueWindowListRefresh() {
        if (this._windowRefreshId)
            return;

        this._windowRefreshId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            110,
            () => {
                this._windowRefreshId = 0;
                this._refreshWindowList();
                return GLib.SOURCE_REMOVE;
            }
        );
    }

'''
    src = replace_between(src, "    _queueWindowListRefresh() {\n", "    _disconnectWindowSignals() {\n", new_queue, "refresh debounce")

    new_refresh = '''    _refreshWindowList() {
        if (!this._dockAppsBox)
            return;

        this._disconnectWindowSignals();
        this._destroyDockMenus();
        this._dockAppsBox.destroy_all_children();
        this._dockButtons = [];

        const favorites = this._favorites || AppFavorites.getAppFavorites();
        const favoriteApps = favorites.getFavorites();
        const favoriteIds = new Set(favoriteApps.map(app => app.get_id()));

        const runningApps = Shell.AppSystem.get_default().get_running()
            .filter(app => !favoriteIds.has(app.get_id()))
            .sort((a, b) => this._appRecentTime(b) - this._appRecentTime(a));

        const apps = favoriteApps.concat(runningApps);

        for (const app of apps) {
            const windows = this._appWindows(app);
            const favorite = favorites.isFavorite(app.get_id());

            if (!favorite && windows.length === 0)
                continue;

            const button = this._appDockButton(app, windows, favorite);
            button._adaptiveDockApp = app;
            this._dockAppsBox.add_child(button);
            this._dockButtons.push(button);

            for (const window of windows) {
                try {
                    this._windowSignalIds.push({
                        window,
                        id: window.connect(
                            'unmanaged',
                            () => this._queueWindowListRefresh()
                        ),
                    });
                } catch (e) {
                    logError(e, '[Adaptive Shell] connect window signal');
                }
            }
        }

        if (this._showAppsButton && !this._dockButtons.includes(this._showAppsButton))
            this._dockButtons.push(this._showAppsButton);

        this._syncDockActive();
        this._layoutRail();
    }

'''
    src = replace_between(src, "    _refreshWindowList() {\n", "    _appWindows(app) {\n", new_refresh, "stable model refresh")

    new_app_button = '''    _appDockButton(app, windows, favorite) {
        const appName = app.get_name() || app.get_id() || 'Application';
        const isActive = this._isFocusedApp(app);

        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: isActive ? 'adaptive-dock-button active' : 'adaptive-dock-button',
            accessible_name: appName,
        });
        button.set_pivot_point(0.5, 1.0);

        const content = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-app-dock-content',
            x_align: Clutter.ActorAlign.CENTER,
        });

        let icon;
        try {
            icon = app.create_icon_texture(36);
        } catch (e) {
            icon = new St.Icon({
                icon_name: 'application-x-executable-symbolic',
                icon_size: 36,
            });
        }
        icon.add_style_class_name('adaptive-app-icon');
        content.add_child(icon);
        content.add_child(this._windowIndicators(windows.length, isActive));
        button.set_child(content);

        this._addTooltip(button, appName);
        button.connect('clicked', () => this._activateDockApp(app));

        button.connect('button-press-event', (_actor, event) => {
            const mouseButton = event.get_button();

            if (mouseButton === 2) {
                this._openNewWindow(app);
                return Clutter.EVENT_STOP;
            }

            if (mouseButton === 3) {
                this._hideTooltip();
                this._openDockMenu(button, app, windows, favorite);
                return Clutter.EVENT_STOP;
            }

            return Clutter.EVENT_PROPAGATE;
        });

        return button;
    }

'''
    src = replace_between(src, "    _appDockButton(app, windows, favorite) {\n", "    _windowIndicators(windowCount, active) {\n", new_app_button, "app button")

    new_menu = '''    _openDockMenu(button, app, windows, favorite) {
        this._destroyDockMenus();
        this._hideTooltip();

        const menu = new PopupMenu.PopupMenu(button, 0.5, St.Side.BOTTOM);
        menu.actor.add_style_class_name('adaptive-dock-popup');
        Main.uiGroup.add_actor(menu.actor);
        menu.actor.hide();
        this._dockMenuManager.addMenu(menu);
        this._dockMenus.push(menu);

        const openItem = new PopupMenu.PopupMenuItem(
            windows.length ? 'Activate' : 'Open'
        );
        openItem.connect('activate', () => this._activateDockApp(app));
        menu.addMenuItem(openItem);

        const canOpenNew =
            typeof app.can_open_new_window !== 'function' ||
            app.can_open_new_window();

        if (canOpenNew) {
            const newWindowItem = new PopupMenu.PopupMenuItem('New Window');
            newWindowItem.connect('activate', () => this._openNewWindow(app));
            menu.addMenuItem(newWindowItem);
        }

        if (windows.length > 1) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            for (const window of windows) {
                const title = window.get_title() || app.get_name() || 'Window';
                const windowItem = new PopupMenu.PopupMenuItem(title);
                windowItem.connect('activate', () => Main.activateWindow(window));
                menu.addMenuItem(windowItem);
            }
        }

        const appId = app.get_id();
        const canFavorite =
            !!appId &&
            !(typeof app.is_window_backed === 'function' && app.is_window_backed());

        if (canFavorite) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

            const favoriteNow = this._favorites
                ? this._favorites.isFavorite(appId)
                : favorite;

            const favoriteItem = new PopupMenu.PopupMenuItem(
                favoriteNow ? 'Remove from Favorites' : 'Add to Favorites'
            );

            favoriteItem.connect('activate', () => {
                const currentlyFavorite = this._favorites.isFavorite(appId);
                if (currentlyFavorite)
                    this._favorites.removeFavorite(appId);
                else
                    this._favorites.addFavorite(appId);

                menu.close();
                this._queueWindowListRefresh();
            });
            menu.addMenuItem(favoriteItem);
        }

        if (windows.length > 0) {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            const closeItem = new PopupMenu.PopupMenuItem(
                windows.length === 1 ? 'Close Window' : `Close ${windows.length} Windows`
            );
            closeItem.connect('activate', () => {
                const timestamp = global.get_current_time();
                for (const window of this._appWindows(app)) {
                    try {
                        window.delete(timestamp);
                    } catch (e) {
                        logError(e, '[Adaptive Shell] close window');
                    }
                }
            });
            menu.addMenuItem(closeItem);
        }

        menu.connect('open-state-changed', (_menu, open) => {
            if (!open)
                this._scheduleDockDemagnify();
        });

        menu.open();
    }

'''
    src = replace_between(src, "    _openDockMenu(button, app, windows, favorite) {\n", "    _utilityDockButton(iconFile, name, callback) {\n", new_menu, "context menu")

    new_magnify = '''    _magnifyDock(activeButton) {
        const activeIndex = activeButton
            ? this._dockButtons.indexOf(activeButton)
            : -1;

        for (let i = 0; i < this._dockButtons.length; i++) {
            const button = this._dockButtons[i];
            if (!button)
                continue;

            let scale = 1.0;
            let lift = 0;

            if (activeIndex >= 0) {
                const distance = Math.abs(i - activeIndex);
                if (distance === 0) {
                    scale = 1.18;
                    lift = -7;
                } else if (distance === 1) {
                    scale = 1.06;
                    lift = -2;
                }
            }

            button.remove_all_transitions();
            button.ease({
                scale_x: scale,
                scale_y: scale,
                translation_y: lift,
                duration: 125,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
        }
    }

'''
    src = replace_between(src, "    _magnifyDock(activeButton) {\n", "    _layoutRail() {\n", new_magnify, "magnify")

    new_layout = '''    _layoutRail() {
        if (!this._dockChrome || !this._rail)
            return;

        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        const reservedHeight = 78;
        const surfaceHeight = 62;

        this._dockChrome.set_position(
            monitor.x,
            monitor.y + monitor.height - reservedHeight
        );
        this._dockChrome.set_size(monitor.width, reservedHeight);

        const [, naturalWidth] = this._rail.get_preferred_width(-1);
        const width = Math.max(
            104,
            Math.min(naturalWidth, monitor.width - 28)
        );

        this._rail.set_size(width, surfaceHeight);
    }

'''
    src = replace_between(src, "    _layoutRail() {\n", "    _showOverview() {\n", new_layout, "layout")

    new_sync = '''    _syncDockActive() {
        for (const button of this._dockButtons) {
            if (!button || !button._adaptiveDockApp)
                continue;

            this._setActorActive(
                button,
                this._isFocusedApp(button._adaptiveDockApp)
            );
        }

        const appsUp = !!(
            Main.overview &&
            Main.overview.visible &&
            this._appsShowing()
        );
        this._setActorActive(this._showAppsButton, appsUp);
    }

'''
    src = replace_between(src, "    _syncDockActive() {\n", "    _runSettingsSection(section) {\n", new_sync, "active sync")

    ext_path.write_text(src, encoding="utf-8")
    print("Patched extension.js")
else:
    print("extension.js already contains bottom dock stability v2")

css = css_path.read_text(encoding="utf-8")
if MARKER not in css:
    css += '''

/* Adaptive bottom dock stability v2 */
.adaptive-dock-reservation {
    background-color: transparent;
}

.adaptive-rail {
    margin-bottom: 7px;
    padding: 5px 10px 4px 10px;
    spacing: 6px;
    border-radius: 18px;
}

.adaptive-window-list {
    spacing: 4px;
}

.adaptive-dock-button {
    width: 48px;
    height: 50px;
    padding: 2px 3px 1px 3px;
    border-radius: 13px;
}

.adaptive-app-icon,
.adaptive-dock-icon {
    icon-size: 36px;
}

.adaptive-app-dock-content {
    spacing: 1px;
}

.adaptive-running-indicators {
    height: 5px;
    spacing: 3px;
}

.adaptive-rail-rule {
    width: 1px;
    height: 34px;
    margin: 8px 2px 6px 2px;
}

.adaptive-dock-popup .popup-menu-content {
    min-width: 190px;
}
'''
    css_path.write_text(css, encoding="utf-8")
    print("Patched stylesheet.css")
else:
    print("stylesheet.css already contains bottom dock stability v2")

wc = window_cli_path.read_text(encoding="utf-8")
if "DOCK_RESERVED_HEIGHT = 88" in wc:
    wc = wc.replace("DOCK_RESERVED_HEIGHT = 88", "DOCK_RESERVED_HEIGHT = 78", 1)
elif "DOCK_RESERVED_HEIGHT = 78" not in wc:
    raise SystemExit("window-cli.py: expected DOCK_RESERVED_HEIGHT = 88 or 78")
window_cli_path.write_text(wc, encoding="utf-8")

tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
shell = tokens.setdefault("shell", {})
shell.update({
    "dock.height": 62,
    "dock.reserved_height": 78,
    "dock.icon": 36,
    "dock.item.width": 48,
    "dock.bottom_margin": 7,
    "dock.hover.scale": 1.18,
    "dock.neighbor.scale": 1.06,
    "dock.hover.duration_ms": 125,
    "dock.hover.release_delay_ms": 85,
})
tokens_path.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
print("Patched window geometry and tokens")
PY

cat > "$REPO/scripts/verify-bottom-dock-v2.sh" <<'VERIFY'
#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
EXT="$REPO/shell/adaptive-shell@local/extension.js"
CSS="$REPO/shell/adaptive-shell@local/stylesheet.css"

echo "===== BOTTOM DOCK v2 ====="
node --check "$EXT"
echo "PASS: extension.js syntax"
python3 -m py_compile "$REPO/scripts/window-cli.py"
echo "PASS: window-cli.py syntax"
python3 -m json.tool "$REPO/tokens/adaptive.tokens.json" >/dev/null
echo "PASS: token JSON"

grep -q 'Adaptive bottom dock stability v2' "$EXT"
echo "PASS: stability marker"
grep -q 'this._dockChrome = new St.Widget' "$EXT"
grep -q 'affectsStruts: true' "$EXT"
echo "PASS: bottom work-area reservation"
grep -A2 "'notify::focus-window'," "$EXT" | grep -q '_syncDockActive'
echo "PASS: focus does not rebuild dock"
grep -q 'Add to Favorites' "$EXT"
grep -q 'Remove from Favorites' "$EXT"
echo "PASS: right-click favorites actions"
grep -q '_scheduleDockDemagnify' "$EXT"
echo "PASS: hover stabilization"
grep -q 'DOCK_RESERVED_HEIGHT = 78' "$REPO/scripts/window-cli.py"
echo "PASS: tiling geometry matches dock"
grep -q 'adaptive-dock-reservation' "$CSS"
echo "PASS: reservation CSS"

echo
echo "Favorites:"
gsettings get org.gnome.shell favorite-apps || true

echo
echo "Manual checks:"
echo "  1. Maximized ChatGPT/browser composer stays above the dock."
echo "  2. Moving across icons does not rapidly shrink/grow the dock."
echo "  3. Right-click menu stays open."
echo "  4. Non-favorite app shows Add to Favorites."
echo "  5. Favorite app shows Remove from Favorites."
echo "  6. One icon per app remains; window dots update."
VERIFY
chmod +x "$REPO/scripts/verify-bottom-dock-v2.sh"

cat > "$REPO/scripts/rollback-bottom-dock-v2.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${ADAPTIVE_REPO:-$HOME/adaptive-desktop}"
STATE_FILE="$HOME/.config/adaptive-desktop/last-bottom-dock-v2-backup"

[[ -f "$STATE_FILE" ]] || {
    echo "No bottom-dock-v2 backup pointer." >&2
    exit 2
}

BACKUP="$(cat "$STATE_FILE")"
[[ -d "$BACKUP" ]] || {
    echo "Backup missing: $BACKUP" >&2
    exit 3
}

cp -a "$BACKUP/shell/extension.js" "$REPO/shell/adaptive-shell@local/extension.js"
cp -a "$BACKUP/shell/stylesheet.css" "$REPO/shell/adaptive-shell@local/stylesheet.css"
cp -a "$BACKUP/scripts/window-cli.py" "$REPO/scripts/window-cli.py"
cp -a "$BACKUP/tokens/adaptive.tokens.json" "$REPO/tokens/adaptive.tokens.json"

"$REPO/scripts/sync-shell.sh"

echo "Bottom dock v2 rollback restored and synced."
echo "Apply with:"
echo "  $REPO/scripts/reload-adaptive-shell.sh --restart-shell"
ROLLBACK
chmod +x "$REPO/scripts/rollback-bottom-dock-v2.sh"

"$REPO/scripts/verify-bottom-dock-v2.sh"
"$REPO/scripts/sync-shell.sh"

echo
echo "============================================================"
echo "BOTTOM DOCK v2 PATCH INSTALLED"
echo "============================================================"
echo
echo "Apply the new GNOME Shell JavaScript with:"
echo "  cd $REPO"
echo "  ./scripts/reload-adaptive-shell.sh --restart-shell"
echo
echo "Then verify:"
echo "  ./scripts/verify-bottom-dock-v2.sh"
echo
echo "Rollback:"
echo "  ./scripts/rollback-bottom-dock-v2.sh"
