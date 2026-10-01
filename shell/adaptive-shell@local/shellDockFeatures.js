// Adaptive Shell - dock extras: badges, attention bounce, scrolling, stacks, settings, hotkeys and spring-loading.
//
// Part of the one AdaptiveShellV16 object in extension.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the shell itself and every
// field and method of the other parts is reachable through it.

/* exported ShellDockFeatures */

const { St, Gio, GLib, Clutter, Shell, Meta } = imports.gi;
const Main = imports.ui.main;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;

const Me = ExtensionUtils.getCurrentExtension();
const DockExtras = Me.imports.dockExtras;

var ShellDockFeatures = class ShellDockFeatures {
    // ------------------------------------------------------------ dock extras

    _applyDockSizing() {
        const size = DockExtras.ICON_SIZES[this._dockConfig.iconSize] || 36;
        this._dockIconSize = size;
        // 36px icons had a 54px dock and a 70px reserve; keep the proportions.
        this._dock26SurfaceHeight = size + 18;
        this._dock26ReservedHeight = size + 34;
    }

    _sizeDockButton(button) {
        const size = this._dockIconSize;
        button.set_style(`width: ${size + 12}px; height: ${size + 12}px;`);
        if (button._adaptiveIcon && button._adaptiveIcon instanceof St.Icon)
            button._adaptiveIcon.icon_size = size;
    }

    // A dock button with a theme icon (full colour, like the app icons).
    _themedDockButton(iconName, name, callback) {
        const button = new St.Button({
            reactive: true,
            can_focus: true,
            track_hover: true,
            style_class: 'adaptive-dock-button adaptive-utility-dock-button',
            accessible_name: name,
        });
        button.set_pivot_point(0.5, 1.0);
        const icon = new St.Icon({
            icon_name: iconName,
            icon_size: this._dockIconSize,
            style_class: 'adaptive-app-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        button.set_child(icon);
        button._adaptiveIcon = icon;
        this._sizeDockButton(button);
        button.connect('clicked', () => callback(button));
        this._addTooltip(button, name);
        return button;
    }

    _syncDockUtilities(dock) {
        if (!dock)
            return;
        if (dock.downloads)
            dock.downloads.visible = this._dockConfig.showDownloads !== false;
        if (dock.trash) {
            dock.trash.visible = this._dockConfig.showTrash !== false;
            if (dock.trash._adaptiveIcon) {
                dock.trash._adaptiveIcon.icon_name =
                    this._trash && this._trash.count > 0 ? 'user-trash-full' : 'user-trash';
            }
        }
        for (const button of [dock.downloads, dock.trash, dock.showApps]) {
            if (button)
                this._sizeDockButton(button);
        }
    }

    _installDockExtras() {
        this._launcherEntries = new DockExtras.LauncherEntries(id => this._onLauncherEntry(id));

        this._previews = new DockExtras.WindowPreviews({
            windowsFor: app => this._appWindows(app),
            onActivate: window => Main.activateWindow(window),
            onShow: () => this._hideTooltip(),
        });

        this._trash = new DockExtras.TrashWatcher(() => {
            for (const dock of this._docks || [])
                this._syncDockUtilities(dock);
        });

        const attention = (_display, window) => {
            try {
                const app = Shell.WindowTracker.get_default().get_window_app(window);
                this._markAttention(app);
            } catch (e) {
            }
        };
        this._dockExtraIds = [
            [global.display, global.display.connect('window-demands-attention', attention)],
            [global.display, global.display.connect('window-marked-urgent', attention)],
            // Per-display docks follow windows moved between screens.
            [global.display, global.display.connect('window-entered-monitor', () => {
                if (this._dockConfig.perMonitor && (this._docks || []).length > 1)
                    this._queueWindowListRefresh();
            })],
        ];
        if (Main.xdndHandler) {
            this._dockExtraIds.push([Main.xdndHandler,
                Main.xdndHandler.connect('drag-end', () => this._cancelSpring())]);
        }

        this._installAppHotkeys();
    }

    _removeDockExtras() {
        this._removeAppHotkeys();
        this._cancelSpring();

        for (const [obj, id] of this._dockExtraIds) {
            try {
                obj.disconnect(id);
            } catch (e) {
            }
        }
        this._dockExtraIds = [];

        for (const id of this._dockTimers)
            GLib.Source.remove(id);
        this._dockTimers.clear();
        this._dockLaunching.clear();

        if (this._previews) {
            this._previews.destroy();
            this._previews = null;
        }
        if (this._launcherEntries) {
            this._launcherEntries.destroy();
            this._launcherEntries = null;
        }
        if (this._trash) {
            this._trash.destroy();
            this._trash = null;
        }
    }

    _dockLater(ms, fn) {
        const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
            const again = fn();
            if (!again)
                this._dockTimers.delete(id);
            return again ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
        });
        this._dockTimers.add(id);
        return id;
    }

    // --- badges and progress

    _onLauncherEntry(_desktopId) {
        for (const button of this._dockButtons) {
            if (!button || !button._adaptiveBadge)
                continue;
            this._syncDockBadge(button);
            const entry = this._launcherEntries.lookup(button._adaptiveDockApp);
            if (entry && entry.urgent)
                this._markAttention(button._adaptiveDockApp);
        }
    }

    _syncDockBadge(button) {
        if (!button._adaptiveBadge || !this._launcherEntries)
            return;
        const entry = this._launcherEntries.lookup(button._adaptiveDockApp);

        const count = entry && entry['count-visible'] ? Number(entry.count) || 0 : 0;
        button._adaptiveBadge.visible = count > 0;
        button._adaptiveBadge.text = count > 99 ? '99+' : `${count}`;

        const progress = entry && entry['progress-visible'] ? Number(entry.progress) : -1;
        const showing = progress >= 0 && progress <= 1;
        button._adaptiveProgress.visible = showing;
        if (showing) {
            const width = button._adaptiveProgress.get_width();
            if (width > 0)
                button._adaptiveProgressFill.set_width(Math.round(width * progress));
        }
    }

    // --- attention and bounce

    _markAttention(app) {
        if (!app || this._isFocusedApp(app))
            return;
        const id = app.get_id();
        const fresh = !this._dockAttention.has(id);
        this._dockAttention.add(id);
        for (const button of this._dockButtons) {
            if (button && button._adaptiveDockApp === app)
                button.add_style_class_name('attention');
        }
        if (fresh)
            this._bounceApp(app, 3);
    }

    _bounceApp(app, times = 1) {
        for (const button of this._dockButtons) {
            if (button && button._adaptiveDockApp === app && button._adaptiveIcon)
                this._bounceActor(button._adaptiveIcon, times);
        }
    }

    // The icon, not the button, moves: magnification owns the button's own
    // translation and scale.
    _bounceActor(actor, times) {
        if (actor._adaptiveBouncing)
            return;
        actor._adaptiveBouncing = true;
        const once = remaining => {
            if (remaining <= 0 || !actor.get_stage()) {
                actor._adaptiveBouncing = false;
                if (actor.get_stage())
                    actor.translation_y = 0;
                return;
            }
            actor.ease({
                translation_y: -Math.round(this._dockIconSize * 0.4),
                duration: 190,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => actor.ease({
                    translation_y: 0,
                    duration: 260,
                    mode: Clutter.AnimationMode.EASE_OUT_BOUNCE,
                    onComplete: () => once(remaining - 1),
                }),
            });
        };
        once(times);
    }

    // Bounce until the app puts up a window, or give up after 8 seconds.
    _bounceWhileLaunching(app) {
        const id = app.get_id();
        if (this._dockLaunching.has(id))
            return;
        this._dockLaunching.add(id);
        const started = GLib.get_monotonic_time();
        const tick = () => {
            const done = app.get_n_windows() > 0 ||
                GLib.get_monotonic_time() - started > 8 * 1000000;
            if (done) {
                this._dockLaunching.delete(id);
                return false;
            }
            this._bounceApp(app, 1);
            return true;
        };
        if (tick())
            this._dockLater(520, tick);
    }

    // --- scroll

    _scrollDockApp(app, event, monitorIndex) {
        const now = GLib.get_monotonic_time();
        if (now - this._dockScrollTime < 250000)
            return Clutter.EVENT_STOP;

        const S = Clutter.ScrollDirection;
        const direction = event.get_scroll_direction();
        let step = 0;
        if (direction === S.UP || direction === S.LEFT)
            step = -1;
        else if (direction === S.DOWN || direction === S.RIGHT)
            step = 1;
        else if (direction === S.SMOOTH) {
            const [dx, dy] = event.get_scroll_delta();
            step = Math.sign(dy || dx);
        }
        if (!step)
            return Clutter.EVENT_STOP;

        let windows = this._appWindows(app);
        if (monitorIndex >= 0) {
            const here = windows.filter(w => w.get_monitor() === monitorIndex);
            if (here.length)
                windows = here;
        }
        if (!windows.length)
            return Clutter.EVENT_STOP;

        // A fixed order to step through: recency would reorder on every step.
        windows.sort((a, b) => a.get_stable_sequence() - b.get_stable_sequence());
        const current = windows.indexOf(global.display.focus_window);
        const next = current < 0 ? windows[0]
            : windows[(current + step + windows.length) % windows.length];

        this._dockScrollTime = now;
        if (this._previews)
            this._previews.hide();
        Main.activateWindow(next);
        return Clutter.EVENT_STOP;
    }

    // --- downloads, trash, popups

    _closeDockPopups() {
        this._destroyDockMenus();
        this._hideTooltip();
        if (this._previews)
            this._previews.hide();
    }

    _toggleDownloadsStack(button) {
        const wasOpen = this._dockMenus.some(m => m.isOpen && m.sourceActor === button);
        this._closeDockPopups();
        if (wasOpen)
            return;
        const menu = DockExtras.openDownloadsStack(button, this._dockMenuManager,
            m => this._dockMenus.push(m));
        menu.connect('open-state-changed', (_m, open) => {
            if (!open)
                this._scheduleDockDemagnify();
        });
    }

    _openTrashMenu(button) {
        this._closeDockPopups();
        const menu = new PopupMenu.PopupMenu(button, 0.5, St.Side.BOTTOM);
        menu.actor.add_style_class_name('adaptive-dock-popup');
        Main.uiGroup.add_actor(menu.actor);
        menu.actor.hide();
        this._dockMenuManager.addMenu(menu);
        this._dockMenus.push(menu);

        const open = new PopupMenu.PopupMenuItem('Open');
        open.connect('activate', () => Gio.AppInfo.launch_default_for_uri('trash:///', null));
        menu.addMenuItem(open);

        const count = this._trash ? this._trash.count : 0;
        const empty = new PopupMenu.PopupMenuItem(count ? 'Empty Trash…' : 'Trash Is Empty');
        empty.setSensitive(count > 0);
        empty.connect('activate', () => {
            DockExtras.confirmEmptyTrash(count, () => {
                try {
                    Gio.Subprocess.new(['gio', 'trash', '--empty'], Gio.SubprocessFlags.NONE);
                } catch (e) {
                    logError(e, '[Adaptive Shell] emptying the trash');
                }
            });
        });
        menu.addMenuItem(empty);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const settings = new PopupMenu.PopupMenuItem('Dock Settings…');
        settings.connect('activate', () => GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._openDockSettingsMenu(button);
            return GLib.SOURCE_REMOVE;
        }));
        menu.addMenuItem(settings);
        menu.open();
    }

    // --- dock settings

    _openDockSettingsMenu(anchor) {
        this._closeDockPopups();
        const menu = new PopupMenu.PopupMenu(anchor, 0.5, St.Side.BOTTOM);
        menu.actor.add_style_class_name('adaptive-dock-popup');
        Main.uiGroup.add_actor(menu.actor);
        menu.actor.hide();
        this._dockMenuManager.addMenu(menu);
        this._dockMenus.push(menu);

        const config = this._dockConfig;
        const choice = (title, key, options) => {
            menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(title));
            for (const [value, label] of options) {
                const item = new PopupMenu.PopupMenuItem(label);
                item.setOrnament(config[key] === value
                    ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
                item.connect('activate', () => this._setDockOption(key, value));
                menu.addMenuItem(item);
            }
        };
        choice('Icon Size', 'iconSize', [['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']]);
        choice('Magnification', 'magnification',
            [['off', 'Off'], ['low', 'Low'], ['medium', 'Medium'], ['high', 'High']]);
        choice('Auto-Hide', 'autoHide', [
            ['smart', 'When a Window Is Maximized'],
            ['always', 'Always'],
            ['never', 'Never'],
        ]);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Show'));
        for (const [key, label] of [
            ['showRecent', 'Recent Apps'],
            ['showDownloads', 'Downloads'],
            ['showTrash', 'Trash'],
            ['perMonitor', 'Only Windows on Each Display'],
        ]) {
            const item = new PopupMenu.PopupSwitchMenuItem(label, config[key] !== false);
            item.connect('toggled', (_i, state) => this._setDockOption(key, state));
            menu.addMenuItem(item);
        }

        menu.connect('open-state-changed', (_m, open) => {
            if (!open)
                this._scheduleDockDemagnify();
        });
        menu.open();
    }

    _setDockOption(key, value) {
        DockExtras.writeDockConfig({ [key]: value });
        this._dockConfig = DockExtras.readDockConfig();
        this._applyDockSizing();
        for (const dock of this._docks || [])
            this._syncDockUtilities(dock);
        this._refreshWindowList();
        this._dock26Layout();
    }

    // --- Super+1..9

    // GNOME binds Super+1..9 to the first nine *pinned* apps. These follow
    // the dock as shown - pinned, then open ones - and bounce what launches.
    _installAppHotkeys() {
        const settings = new Gio.Settings({ schema_id: 'org.gnome.shell.keybindings' });
        try {
            for (let i = 1; i <= 9; i++) {
                const name = `switch-to-application-${i}`;
                Main.wm.removeKeybinding(name);
                Main.wm.addKeybinding(name, settings, Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
                    Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
                    () => this._dockHotkey(i));
            }
            this._hotkeysInstalled = true;
        } catch (e) {
            logError(e, '[Adaptive Shell] dock hotkeys');
        }
    }

    _removeAppHotkeys() {
        if (!this._hotkeysInstalled)
            return;
        const settings = new Gio.Settings({ schema_id: 'org.gnome.shell.keybindings' });
        for (let i = 1; i <= 9; i++) {
            const name = `switch-to-application-${i}`;
            try {
                Main.wm.removeKeybinding(name);
                Main.wm.addKeybinding(name, settings, Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
                    Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
                    Main.wm._switchToApplication.bind(Main.wm));
            } catch (e) {
                logError(e, '[Adaptive Shell] restoring GNOME hotkeys');
            }
        }
        this._hotkeysInstalled = false;
    }

    _dockHotkey(n) {
        const entry = (this._dockEntries || [])[n - 1];
        if (!entry)
            return;
        Main.overview.hide();
        this._activateDockApp(entry.app);
    }

    // --- spring-loaded icons (files dragged from other apps)

    _dockSpringLoad(dock, x) {
        const [railX] = dock.rail.get_transformed_position();
        const stageX = railX + x;
        const target = this._dockSlots(dock).find(slot => {
            const [sx] = slot.get_transformed_position();
            const [w] = slot.get_transformed_size();
            return stageX >= sx && stageX < sx + w;
        });
        const app = target ? target._adaptiveDockApp : null;
        if (app === this._springApp)
            return;

        this._cancelSpring();
        this._springApp = app;
        if (!app)
            return;
        this._magnifyDock(target);
        this._springId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 650, () => {
            this._springId = 0;
            const windows = this._appWindows(app);
            if (windows.length)
                Main.activateWindow(windows[0]);
            else
                app.activate();
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancelSpring() {
        if (this._springId) {
            GLib.Source.remove(this._springId);
            this._springId = 0;
        }
        this._springApp = null;
    }
};
