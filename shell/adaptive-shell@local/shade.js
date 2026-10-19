// Adaptive Shade v2 - an information center
//
// The date menu, rebuilt as somewhere to LOOK at things rather than change them.
// It carries a clock, date, physical verification status, and notifications
// grouped per application. All system monitor vitals have moved to their own
// dedicated indicator next to ROS 2.
//
// The calendar column is GNOME's, untouched.
// The popup stays GNOME's. This takes the native CalendarMessageList out of
// #calendarArea, wraps it in a column carrying a header, and puts that column
// back where the list stood. The list itself is never rebuilt, so notification
// delivery, storage, urgency, history and Clear all remain the code GNOME ships.
//
// Because this rearranges actors the shell owns, detach() has to be exact: the
// recorded parent, index and y_expand are what make disabling the extension give
// back a working stock date menu.

/* exported Shade */

const { St, Clutter, GLib } = imports.gi;
const Main = imports.ui.main;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Notifications = Me.imports.notifications;
const AdaptiveUtil = Me.imports.adaptiveUtil;
const AdaptivePaths = Me.imports.adaptivePaths;

// Written by scripts/record-live-verification.py (and Adaptive Settings).
const VERIFICATION_PATH = GLib.build_filenamev([
    AdaptivePaths.adaptiveDir(),
    'verification',
    'live-verification-latest.json',
]);

const CONFIG_PATH = GLib.build_filenamev(
    [GLib.get_user_config_dir(), 'adaptive-desktop', 'shade.json']);

function readConfig() {
    try {
        const [ok, contents] = GLib.file_get_contents(CONFIG_PATH);
        if (!ok)
            return {};
        return JSON.parse(new TextDecoder().decode(contents)) || {};
    } catch (e) {
        return {};
    }
}

function readUptime() {
    try {
        const [ok, bytes] = GLib.file_get_contents('/proc/uptime');
        if (ok) {
            const seconds = Number.parseFloat(new TextDecoder().decode(bytes).trim().split(/\s+/)[0]);
            if (Number.isFinite(seconds)) {
                const days = Math.floor(seconds / 86400);
                const hours = Math.floor((seconds % 86400) / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                if (days > 0)
                    return `Up ${days}d ${hours}h`;
                if (hours > 0)
                    return `Up ${hours}h ${minutes}m`;
                return `Up ${minutes}m`;
            }
        }
    } catch (e) {}
    return '';
}

var Shade = class Shade {
    constructor(callbacks) {
        this._callbacks = callbacks || {};

        this._dateMenu = null;
        this._messageList = null;
        this._origParent = null;
        this._origIndex = -1;
        this._origYExpand = true;

        this._container = null;
        this._grouped = null;
        this._placeholder = null;
        this._placeholderParent = null;
        this._stockSection = null;
        this._stockIndex = -1;
        this._openStateId = 0;
        this._clockTimerId = 0;
        this._attached = false;
    }

    // --------------------------------------------------------------- attach

    attach() {
        if (this._attached)
            return;

        const dateMenu = Main.panel.statusArea.dateMenu;
        if (!dateMenu || !dateMenu._messageList) {
            log('[Adaptive Shade] date menu has no message list; staying stock');
            return;
        }

        const messageList = dateMenu._messageList;
        const parent = messageList.get_parent();
        if (!parent) {
            log('[Adaptive Shade] message list is unparented; staying stock');
            return;
        }

        this._origParent = parent;
        this._origIndex = parent.get_children().indexOf(messageList);
        this._origYExpand = messageList.y_expand;
        this._dateMenu = dateMenu;
        this._messageList = messageList;

        try {
            dateMenu.menu.box.add_style_class_name('adaptive-shade-menu');

            this._container = new St.BoxLayout({
                vertical: true,
                style_class: 'adaptive-shade',
                x_expand: true,
                y_expand: true,
            });

            this._buildHeader();

            parent.remove_child(messageList);
            messageList.y_expand = true;
            this._container.add_child(messageList);
            parent.insert_child_at_index(this._container, this._origIndex);

            this._installGroupedNotifications();
            this._unstackPlaceholder();
            this._installNotificationHeader();

            this._openStateId = dateMenu.menu.connect(
                'open-state-changed',
                (menu, isOpen) => this._onOpenStateChanged(isOpen));

            this._attached = true;
            log('[Adaptive Shade] attached to the GNOME date menu');
        } catch (e) {
            logError(e, '[Adaptive Shade] attach failed; reverting to stock');
            this.detach();
        }
    }

    _onOpenStateChanged(isOpen) {
        if (isOpen) {
            this._updateClock();
            this._updateChecks();
            if (!this._clockTimerId) {
                this._clockTimerId = GLib.timeout_add_seconds(
                    GLib.PRIORITY_DEFAULT,
                    1,
                    () => {
                        this._updateClock();
                        return GLib.SOURCE_CONTINUE;
                    }
                );
            }
        } else {
            if (this._clockTimerId) {
                GLib.Source.remove(this._clockTimerId);
                this._clockTimerId = 0;
            }
        }
    }

    // Swap GNOME's flat notification list for the per-app grouped one.
    _installGroupedNotifications() {
        if (readConfig().notificationGrouping === false) {
            log('[Adaptive Shade] notification grouping disabled by config');
            return;
        }

        const list = this._messageList;
        const sectionList = list._sectionList;
        const stock = list._notificationSection;

        if (!sectionList || !stock) {
            log('[Adaptive Shade] no notification section to group; staying stock');
            return;
        }

        try {
            this._stockIndex = sectionList.get_children().indexOf(stock);
            sectionList.remove_child(stock);
            this._stockSection = stock;

            this._grouped = new Notifications.GroupedNotificationSection();
            list._addSection(this._grouped);

            log('[Adaptive Shade] notifications grouped by application');
        } catch (e) {
            logError(e, '[Adaptive Shade] grouping failed; restoring GNOME list');
            this._restoreStockNotifications();
        }
    }

    _restoreStockNotifications() {
        if (this._grouped) {
            try {
                this._grouped.destroy();
            } catch (e) {
                logError(e, '[Adaptive Shade] destroying grouped section');
            }
            this._grouped = null;
        }

        if (this._stockSection && this._messageList) {
            try {
                const sectionList = this._messageList._sectionList;
                if (sectionList && !this._stockSection.get_parent()) {
                    const index = Math.max(0, Math.min(
                        this._stockIndex, sectionList.get_children().length));
                    sectionList.insert_child_at_index(this._stockSection, index);
                }
            } catch (e) {
                logError(e, '[Adaptive Shade] restoring GNOME notification list');
            }
        }

        this._stockSection = null;
        this._stockIndex = -1;
    }

    _unstackPlaceholder() {
        const list = this._messageList;
        const placeholder = list._placeholder;
        const scrollView = list._scrollView;
        const box = scrollView ? scrollView.get_parent() : null;

        if (!placeholder || !box || placeholder.get_parent() !== list)
            return;

        try {
            this._placeholder = placeholder;
            this._placeholderParent = list;
            this._placeholderExpand = placeholder.y_expand;
            this._placeholderAlign = placeholder.y_align;

            list.remove_child(placeholder);
            box.insert_child_at_index(
                placeholder, box.get_children().indexOf(scrollView));

            placeholder.y_expand = true;
            placeholder.y_align = Clutter.ActorAlign.CENTER;
            this._placeholderXAlign = placeholder.x_align;
            placeholder.x_align = Clutter.ActorAlign.CENTER;

            if (placeholder._label) {
                this._placeholderText = placeholder._label.text;
                placeholder._label.text = 'You\u2019re all caught up';
            }

            if (placeholder._icon) {
                this._placeholderIconAlign = placeholder._icon.x_align;
                placeholder._icon.x_align = Clutter.ActorAlign.CENTER;
            }
        } catch (e) {
            logError(e, '[Adaptive Shade] moving the empty-state placeholder');
            this._placeholder = null;
        }
    }

    _restackPlaceholder() {
        if (!this._placeholder || !this._placeholderParent) {
            this._placeholder = null;
            this._placeholderParent = null;
            return;
        }

        try {
            const holder = this._placeholder.get_parent();
            if (holder)
                holder.remove_child(this._placeholder);

            this._placeholder.y_expand = this._placeholderExpand;
            this._placeholder.y_align = this._placeholderAlign;
            this._placeholder.x_align = this._placeholderXAlign;
            if (this._placeholder._label && this._placeholderText)
                this._placeholder._label.text = this._placeholderText;
            if (this._placeholder._icon &&
                this._placeholderIconAlign !== undefined)
                this._placeholder._icon.x_align = this._placeholderIconAlign;
            this._placeholderParent.add_child(this._placeholder);
        } catch (e) {
            logError(e, '[Adaptive Shade] restoring the empty-state placeholder');
        }

        this._placeholder = null;
        this._placeholderParent = null;
    }

    _installNotificationHeader() {
        const list = this._messageList;
        const scrollView = list._scrollView;
        const box = scrollView ? scrollView.get_parent() : null;
        const controls = box && box.get_children().find(
            child => child.has_style_class_name &&
                child.has_style_class_name('message-list-controls'));

        if (!controls)
            return;

        try {
            this._controls = controls;
            this._controlsIndex = box.get_children().indexOf(controls);
            box.set_child_at_index(controls, 0);
            controls.add_style_class_name('adaptive-notif-header');

            const heading = new St.BoxLayout({
                style_class: 'adaptive-notif-heading',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            heading.add_child(new St.Label({
                text: 'Notifications',
                style_class: 'adaptive-notif-heading-label',
                y_align: Clutter.ActorAlign.CENTER,
            }));
            this._notifCount = new St.Label({
                style_class: 'adaptive-notif-heading-count',
                y_align: Clutter.ActorAlign.CENTER,
                visible: false,
            });
            heading.add_child(this._notifCount);
            controls.insert_child_at_index(heading, 0);
            this._notifHeading = heading;

            const clear = list._clearButton;
            if (clear) {
                this._clearXExpand = clear.x_expand;
                this._clearLabel = clear.label;
                clear.x_expand = false;
                clear.label = 'Clear all';

                if (list._placeholder)
                    clear.visible = !list._placeholder.visible;
            }

            if (this._grouped) {
                this._grouped.connectObject(
                    'notify::count', () => this._syncNotifCount(), this);
                this._syncNotifCount();
            }
        } catch (e) {
            logError(e, '[Adaptive Shade] building the notification header');
        }
    }

    _syncNotifCount() {
        if (!this._notifCount || !this._grouped)
            return;

        const count = this._grouped.count;
        this._notifCount.text = `${count}`;
        this._notifCount.visible = count > 0;
    }

    _removeNotificationHeader() {
        if (this._grouped)
            this._grouped.disconnectObject(this);

        if (this._notifHeading) {
            this._notifHeading.destroy();
            this._notifHeading = null;
            this._notifCount = null;
        }

        const clear = this._messageList && this._messageList._clearButton;
        if (clear && this._clearLabel !== undefined) {
            clear.x_expand = this._clearXExpand;
            clear.label = this._clearLabel;
        }
        this._clearLabel = undefined;

        if (this._controls) {
            try {
                this._controls.remove_style_class_name('adaptive-notif-header');
                const box = this._controls.get_parent();
                if (box) {
                    const index = Math.max(0, Math.min(
                        this._controlsIndex, box.get_n_children() - 1));
                    box.set_child_at_index(this._controls, index);
                }
            } catch (e) {
                logError(e, '[Adaptive Shade] restoring the notification controls');
            }
        }
        this._controls = null;
    }

    // --------------------------------------------------------------- detach

    detach() {
        if (this._clockTimerId) {
            GLib.Source.remove(this._clockTimerId);
            this._clockTimerId = 0;
        }

        this._removeNotificationHeader();
        this._restoreStockNotifications();
        this._restackPlaceholder();

        if (this._dateMenu) {
            try {
                this._dateMenu.menu.box.remove_style_class_name(
                    'adaptive-shade-menu');
            } catch (e) {
                logError(e, '[Adaptive Shade] untagging the popup');
            }
        }

        if (this._openStateId && this._dateMenu) {
            try {
                this._dateMenu.menu.disconnect(this._openStateId);
            } catch (e) {
                logError(e, '[Adaptive Shade] disconnect open-state');
            }
        }
        this._openStateId = 0;

        if (this._messageList && this._origParent) {
            try {
                const holder = this._messageList.get_parent();
                if (holder)
                    holder.remove_child(this._messageList);

                this._messageList.y_expand = this._origYExpand;

                const index = Math.max(0, Math.min(
                    this._origIndex, this._origParent.get_children().length));
                this._origParent.insert_child_at_index(this._messageList, index);
            } catch (e) {
                logError(e, '[Adaptive Shade] restoring the message list');
            }
        }

        if (this._container) {
            try {
                this._container.destroy();
            } catch (e) {
                logError(e, '[Adaptive Shade] destroying the shade');
            }
            this._container = null;
        }

        this._messageList = null;
        this._origParent = null;
        this._origIndex = -1;
        this._origYExpand = true;
        this._dateMenu = null;
        this._attached = false;
    }

    close() {
        if (this._dateMenu && this._dateMenu.menu)
            this._dateMenu.menu.close();
    }

    // --------------------------------------------------------------- header

    _buildHeader() {
        const header = new St.BoxLayout({
            style_class: 'adaptive-shade-header',
            x_expand: true,
        });
        this._container.add_child(header);

        const text = new St.BoxLayout({
            vertical: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        header.add_child(text);

        const clock = new St.BoxLayout({ style_class: 'adaptive-shade-clock' });
        text.add_child(clock);

        this._timeLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-time',
        });
        clock.add_child(this._timeLabel);

        this._secondsLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-seconds',
            y_align: Clutter.ActorAlign.END,
        });
        clock.add_child(this._secondsLabel);

        this._dateLabel = new St.Label({
            text: '',
            style_class: 'adaptive-shade-date',
        });
        text.add_child(this._dateLabel);

        this._uptimeChip = new St.BoxLayout({
            style_class: 'adaptive-shade-uptime',
            y_align: Clutter.ActorAlign.START,
            visible: false,
        });
        this._uptimeChip.add_child(new St.Widget({
            style_class: 'adaptive-shade-live-dot',
            y_align: Clutter.ActorAlign.CENTER,
        }));
        this._uptimeLabel = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._uptimeChip.add_child(this._uptimeLabel);
        header.add_child(this._uptimeChip);

        this._checksLabel = new St.Label({
            style_class: 'adaptive-shade-checks',
            x_expand: true,
            visible: false,
        });
        this._container.add_child(this._checksLabel);

        this._updateClock();
    }

    _updateChecks() {
        let report = null;
        try {
            const [ok, contents] = GLib.file_get_contents(VERIFICATION_PATH);
            report = ok ? JSON.parse(new TextDecoder().decode(contents)) : null;
        } catch (e) {
            report = null;
        }
        const summary = AdaptiveUtil.verificationSummary(report);
        this._checksLabel.text = `${summary.text} · record them in Adaptive Settings`;
        this._checksLabel.visible = !summary.complete;
        if (summary.failed)
            this._checksLabel.add_style_class_name('adaptive-shade-checks-failing');
        else
            this._checksLabel.remove_style_class_name('adaptive-shade-checks-failing');
    }

    _updateClock() {
        const now = GLib.DateTime.new_now_local();
        this._timeLabel.text = now.format('%H:%M');
        this._secondsLabel.text = now.format(':%S');
        this._dateLabel.text = now.format('%A, %-d %B %Y');

        const uptime = readUptime();
        this._uptimeLabel.text = uptime;
        this._uptimeChip.visible = !!uptime;
    }
};
