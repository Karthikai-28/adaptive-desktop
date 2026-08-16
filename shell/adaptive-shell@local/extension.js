const { St, Gio, GLib, Clutter } = imports.gi;
const Main = imports.ui.main;
const ExtensionUtils = imports.misc.extensionUtils;

const Me = ExtensionUtils.getCurrentExtension();

let _shell = null;

class AdaptiveShell {
    constructor() {
        this._rail = null;
        this._brandButton = null;
        this._projectLabel = null;
        this._monitorChangedId = 0;
        this._hiddenActors = [];
        this._clockActor = null;
        this._filesLauncher = GLib.build_filenamev([
            GLib.get_home_dir(),
            'adaptive-desktop',
            'scripts',
            'adaptive-files-launch.sh',
        ]);
    }

    enable() {
        log('[Adaptive Shell] enable v1.5');

        this._hideStockLeftItems();
        this._restoreAndStyleStockClock();
        this._buildTopIdentity();
        this._buildRail();

        this._monitorChangedId = Main.layoutManager.connect(
            'monitors-changed',
            () => this._layoutRail()
        );

        this._layoutRail();

        log('[Adaptive Shell] dock ready');
        log('[Adaptive Shell] stock clock/calendar restored');
    }

    disable() {
        log('[Adaptive Shell] disable v1.5');

        if (this._monitorChangedId) {
            Main.layoutManager.disconnect(this._monitorChangedId);
            this._monitorChangedId = 0;
        }

        if (this._rail) {
            Main.layoutManager.removeChrome(this._rail);
            this._rail.destroy();
            this._rail = null;
        }

        if (this._brandButton) {
            this._brandButton.destroy();
            this._brandButton = null;
        }

        if (this._projectLabel) {
            this._projectLabel.destroy();
            this._projectLabel = null;
        }

        if (this._clockActor) {
            this._clockActor.remove_style_class_name('adaptive-stock-clock');
            this._clockActor = null;
        }

        for (const item of this._hiddenActors) {
            try {
                if (item.wasVisible)
                    item.actor.show();
                else
                    item.actor.hide();
            } catch (e) {
                logError(e, '[Adaptive Shell] restoring stock panel actor');
            }
        }
        this._hiddenActors = [];
    }

    _panelActor(item) {
        if (!item)
            return null;

        if (item.container)
            return item.container;

        if (item.actor)
            return item.actor;

        return item;
    }

    _rememberAndHide(actor) {
        if (!actor)
            return;

        try {
            this._hiddenActors.push({
                actor,
                wasVisible: actor.visible,
            });
            actor.hide();
        } catch (e) {
            logError(e, '[Adaptive Shell] hiding stock panel actor');
        }
    }

    _hideStockLeftItems() {
        // We keep the stock dateMenu and all top-right system indicators.
        // Only the legacy Activities / current-app labels are hidden.
        this._rememberAndHide(
            this._panelActor(Main.panel.statusArea.activities)
        );

        this._rememberAndHide(
            this._panelActor(Main.panel.statusArea.appMenu)
        );
    }

    _restoreAndStyleStockClock() {
        const dateMenu = Main.panel.statusArea.dateMenu;
        const actor = this._panelActor(dateMenu);

        if (!actor)
            return;

        // A previous Adaptive Shell build hid this. Force the GNOME clock
        // actor back on-screen. Keeping the real dateMenu preserves the
        // calendar, notifications, appointments and GNOME time formatting.
        try {
            actor.show();
            actor.add_style_class_name('adaptive-stock-clock');
            this._clockActor = actor;
        } catch (e) {
            logError(e, '[Adaptive Shell] restoring dateMenu');
        }
    }

    _buildTopIdentity() {
        this._brandButton = new St.Button({
            style_class: 'adaptive-brand-button',
            reactive: true,
            can_focus: true,
            track_hover: true,
            accessible_name: 'Adaptive Desktop overview',
        });

        const brand = new St.Label({
            text: 'ADAPTIVE',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'adaptive-brand-label',
        });

        this._brandButton.set_child(brand);
        this._brandButton.connect(
            'clicked',
            () => this._showOverview()
        );

        this._projectLabel = new St.Label({
            text: 'PROJECT · NONE',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'adaptive-project-label',
        });

        Main.panel._leftBox.insert_child_at_index(
            this._brandButton,
            0
        );
        Main.panel._leftBox.insert_child_at_index(
            this._projectLabel,
            1
        );
    }

    _buildRail() {
        this._rail = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-rail',
            reactive: true,
        });

        const top = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-rail-group',
        });

        top.add_child(
            this._makeDockButton(
                'overview.svg',
                'Overview',
                () => this._showOverview()
            )
        );

        top.add_child(
            this._makeDockButton(
                'files.svg',
                'Adaptive Files',
                () => this._openFiles()
            )
        );

        top.add_child(
            this._makeDockButton(
                'apps.svg',
                'Applications',
                () => this._showApplications()
            )
        );

        top.add_child(
            this._makeDockButton(
                'workspaces.svg',
                'Workspaces',
                () => this._showWorkspaces()
            )
        );

        top.add_child(
            this._makeDockButton(
                'search.svg',
                'Search',
                () => this._showSearch()
            )
        );

        this._rail.add_child(top);

        const spacer = new St.Widget({
            y_expand: true,
        });
        this._rail.add_child(spacer);

        const bottom = new St.BoxLayout({
            vertical: true,
            style_class: 'adaptive-rail-group adaptive-rail-bottom',
        });

        bottom.add_child(
            this._makeDockButton(
                'settings.svg',
                'Settings',
                () => this._openSettings()
            )
        );

        this._rail.add_child(bottom);

        Main.layoutManager.addChrome(
            this._rail,
            {
                affectsStruts: true,
                trackFullscreen: true,
            }
        );
    }

    _makeDockButton(iconFile, accessibleName, callback) {
        const path = GLib.build_filenamev([
            Me.path,
            'assets',
            'dock',
            iconFile,
        ]);

        const gicon = Gio.FileIcon.new(
            Gio.File.new_for_path(path)
        );

        const icon = new St.Icon({
            gicon,
            style_class: 'adaptive-dock-icon',
        });

        const button = new St.Button({
            style_class: 'adaptive-dock-button',
            reactive: true,
            can_focus: true,
            track_hover: true,
            accessible_name: accessibleName,
        });

        button.set_child(icon);

        button.connect('clicked', () => {
            try {
                callback();
            } catch (e) {
                logError(
                    e,
                    `[Adaptive Shell] ${accessibleName} action`
                );
                Main.notifyError(
                    'Adaptive Desktop',
                    `${accessibleName} could not be opened.`
                );
            }
        });

        return button;
    }

    _layoutRail() {
        if (!this._rail)
            return;

        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        const panelHeight = Math.max(
            Main.panel.height || 0,
            24
        );

        const railWidth = 58;
        const railHeight = Math.max(
            1,
            monitor.height - panelHeight
        );

        this._rail.set_position(
            monitor.x,
            monitor.y + panelHeight
        );

        this._rail.set_size(
            railWidth,
            railHeight
        );
    }

    _showOverview() {
        Main.overview.show();
    }

    _showApplications() {
        if (typeof Main.overview.showApps === 'function')
            Main.overview.showApps();
        else
            Main.overview.show();
    }

    _showWorkspaces() {
        Main.overview.show();
    }

    _showSearch() {
        // GNOME Shell's overview is the system search surface. Once shown,
        // typing immediately enters search without us depending on private
        // search-controller APIs.
        Main.overview.show();
    }

    _openFiles() {
        if (GLib.file_test(
            this._filesLauncher,
            GLib.FileTest.IS_EXECUTABLE
        )) {
            this._spawn([this._filesLauncher]);
            return;
        }

        // Fail-safe fallback: Files remains reachable even if the Adaptive
        // launcher was accidentally removed.
        this._spawn(['nautilus', '--new-window']);
    }

    _openSettings() {
        this._spawn(['gnome-control-center']);
    }

    _spawn(argv) {
        try {
            Gio.Subprocess.new(
                argv,
                Gio.SubprocessFlags.NONE
            );
        } catch (e) {
            logError(
                e,
                `[Adaptive Shell] spawn failed: ${argv.join(' ')}`
            );
            Main.notifyError(
                'Adaptive Desktop',
                `Could not start ${argv[0]}.`
            );
        }
    }
}

function init() {
}

function enable() {
    _shell = new AdaptiveShell();
    _shell.enable();
}

function disable() {
    if (_shell) {
        _shell.disable();
        _shell = null;
    }
}
