const { St, Clutter } = imports.gi;

const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;

let topIndicator = null;
let rail = null;
let overlay = null;
let monitorSignal = null;

let stockLeftVisible = true;
let stockDateVisible = true;


/* =========================================================
 * HELPERS
 * ========================================================= */

function makeLabel(text, styleClass = null) {
    const label = new St.Label({
        text,
        y_align: Clutter.ActorAlign.CENTER,
    });

    if (styleClass)
        label.add_style_class_name(styleClass);

    return label;
}

function makeRailButton(iconName, name, action) {
    const button = new St.Button({
        style_class: 'adaptive-rail-button',
        reactive: true,
        can_focus: true,
        track_hover: true,
        accessible_name: name,
        x_align: Clutter.ActorAlign.CENTER,
        y_align: Clutter.ActorAlign.CENTER,
    });

    const icon = new St.Icon({
        icon_name: iconName,
        style_class: 'adaptive-rail-icon',
        icon_size: 18,
        x_align: Clutter.ActorAlign.CENTER,
        y_align: Clutter.ActorAlign.CENTER,
    });

    button.set_child(icon);
    button.connect('clicked', action);

    return button;
}


/* =========================================================
 * STOCK GNOME CHROME
 * ========================================================= */

function hideStockChrome() {
    if (Main.panel._leftBox) {
        stockLeftVisible = Main.panel._leftBox.visible;
        Main.panel._leftBox.hide();
    }

    const dateMenu = Main.panel.statusArea.dateMenu;

    if (dateMenu) {
        stockDateVisible = dateMenu.visible;
        dateMenu.hide();
    }

    Main.panel.add_style_class_name('adaptive-main-panel');
}

function restoreStockChrome() {
    if (Main.panel._leftBox && stockLeftVisible)
        Main.panel._leftBox.show();

    const dateMenu = Main.panel.statusArea.dateMenu;

    if (dateMenu && stockDateVisible)
        dateMenu.show();

    Main.panel.remove_style_class_name('adaptive-main-panel');
}


/* =========================================================
 * OVERLAY
 * ========================================================= */

function closeOverlay() {
    if (!overlay)
        return;

    overlay.destroy();
    overlay = null;
}

function showOverlay(title, subtitle, items = []) {
    closeOverlay();

    overlay = new St.BoxLayout({
        style_class: 'adaptive-overlay',
        vertical: true,
        reactive: true,
    });

    const header = new St.BoxLayout({
        style_class: 'adaptive-overlay-header',
        vertical: false,
    });

    const headingBox = new St.BoxLayout({
        vertical: true,
        x_expand: true,
    });

    headingBox.add_child(
        makeLabel(title, 'adaptive-overlay-title')
    );

    headingBox.add_child(
        makeLabel(subtitle, 'adaptive-overlay-subtitle')
    );

    const closeButton = new St.Button({
        style_class: 'adaptive-close-button',
        label: '×',
        reactive: true,
    });

    closeButton.connect('clicked', closeOverlay);

    header.add_child(headingBox);
    header.add_child(closeButton);

    overlay.add_child(header);

    overlay.add_child(
        new St.Widget({
            style_class: 'adaptive-separator',
        })
    );

    for (const item of items) {
        const card = new St.Button({
            style_class: 'adaptive-card',
            reactive: true,
            can_focus: true,
        });

        const content = new St.BoxLayout({
            vertical: true,
        });

        content.add_child(
            makeLabel(item.title, 'adaptive-card-title')
        );

        content.add_child(
            makeLabel(item.subtitle, 'adaptive-card-subtitle')
        );

        card.set_child(content);
        overlay.add_child(card);
    }

    Main.layoutManager.addChrome(overlay, {
        affectsStruts: false,
        trackFullscreen: true,
    });

    positionOverlay();
}


/* =========================================================
 * POSITIONING
 * ========================================================= */

function positionRail() {
    if (!rail)
        return;

    const monitor = Main.layoutManager.primaryMonitor;

    if (!monitor)
        return;

    const panelHeight = Main.panel.height;
    const dockWidth = 72;

    rail.set_position(
        monitor.x,
        monitor.y + panelHeight
    );

    rail.set_size(
        dockWidth,
        monitor.height - panelHeight
    );
}

function positionOverlay() {
    if (!overlay)
        return;

    const monitor = Main.layoutManager.primaryMonitor;

    if (!monitor)
        return;

    overlay.set_position(
        monitor.x + 92,
        monitor.y + Main.panel.height + 20
    );
}

function reposition() {
    positionRail();
    positionOverlay();
}


/* =========================================================
 * PANELS
 * ========================================================= */

function showProjects() {
    showOverlay(
        'Projects',
        'Switch or create a working context.',
        [
            {
                title: 'No active project',
                subtitle: 'Your registered projects will appear here.',
            },
            {
                title: '+ Add project',
                subtitle: 'Register an existing folder.',
            },
        ]
    );
}

function showWorkspaces() {
    showOverlay(
        'Workspaces',
        'Desktop spaces linked to your active context.',
        [
            {
                title: 'Workspace 01',
                subtitle: 'Current workspace',
            },
            {
                title: '+ New workspace',
                subtitle: 'Create another working space',
            },
        ]
    );
}

function showCommand() {
    showOverlay(
        'Command',
        'Search, open, switch or run.',
        [
            {
                title: 'Applications',
                subtitle: 'Launch installed applications',
            },
            {
                title: 'Files',
                subtitle: 'Find files and folders',
            },
            {
                title: 'Projects',
                subtitle: 'Switch active project',
            },
            {
                title: 'Actions',
                subtitle: 'Run desktop commands',
            },
        ]
    );
}

function showSystem() {
    showOverlay(
        'System Center',
        'Desktop and device controls.',
        [
            {
                title: 'Network',
                subtitle: 'Connectivity and VPN',
            },
            {
                title: 'Performance',
                subtitle: 'CPU, memory and activity',
            },
            {
                title: 'Settings',
                subtitle: 'Adaptive Desktop configuration',
            },
            {
                title: 'Return to Ubuntu',
                subtitle: 'Exit Adaptive Desktop safely',
            },
        ]
    );
}


/* =========================================================
 * RAIL
 * ========================================================= */

function createRail() {
    rail = new St.BoxLayout({
        style_class: 'adaptive-rail',
        vertical: true,
        reactive: true,
        x_expand: false,
        y_expand: false,
    });

    const topGroup = new St.BoxLayout({
        style_class: 'adaptive-rail-top',
        vertical: true,
        x_align: Clutter.ActorAlign.CENTER,
    });

    topGroup.add_child(
        makeRailButton(
            'go-home-symbolic',
            'Home',
            closeOverlay
        )
    );

    topGroup.add_child(
        makeRailButton(
            'folder-symbolic',
            'Projects',
            showProjects
        )
    );

    topGroup.add_child(
        makeRailButton(
            'view-grid-symbolic',
            'Workspaces',
            showWorkspaces
        )
    );

    topGroup.add_child(
        makeRailButton(
            'system-search-symbolic',
            'Command',
            showCommand
        )
    );

    rail.add_child(topGroup);

    const spacer = new St.Widget({
        y_expand: true,
    });

    rail.add_child(spacer);

    const bottomGroup = new St.BoxLayout({
        style_class: 'adaptive-rail-bottom',
        vertical: true,
        x_align: Clutter.ActorAlign.CENTER,
    });

    bottomGroup.add_child(
        makeRailButton(
            'preferences-system-symbolic',
            'System Center',
            showSystem
        )
    );

    rail.add_child(bottomGroup);

    Main.layoutManager.addChrome(rail, {
        affectsStruts: true,
        trackFullscreen: true,
    });

    positionRail();
}


/* =========================================================
 * TOP BAR
 * ========================================================= */

function createTopIndicator() {
    topIndicator = new PanelMenu.Button(
        0.0,
        'Adaptive Desktop',
        false
    );

    const content = new St.BoxLayout({
        style_class: 'adaptive-top-indicator',
    });

    content.add_child(
        makeLabel('ADAPTIVE', 'adaptive-brand')
    );

    content.add_child(
        makeLabel('PROJECT · NONE', 'adaptive-project-state')
    );

    topIndicator.add_child(content);

    Main.panel.addToStatusArea(
        'adaptive-shell',
        topIndicator,
        0,
        'center'
    );
}


/* =========================================================
 * EXTENSION LIFECYCLE
 * ========================================================= */

function init() {
}

function enable() {
    hideStockChrome();
    createTopIndicator();
    createRail();

    monitorSignal = Main.layoutManager.connect(
        'monitors-changed',
        reposition
    );
}

function disable() {
    closeOverlay();

    if (monitorSignal) {
        Main.layoutManager.disconnect(monitorSignal);
        monitorSignal = null;
    }

    if (rail) {
        rail.destroy();
        rail = null;
    }

    if (topIndicator) {
        topIndicator.destroy();
        topIndicator = null;
    }

    restoreStockChrome();
}
