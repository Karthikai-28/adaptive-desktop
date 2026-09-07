// Adaptive Shade notifications v2
//
// Android-style grouping: one collapsible card per application instead of the
// flat chronological list GNOME 42 ships. Slack with six messages is one Slack
// group showing a count, not six loose cards pushing everything else off screen.
//
// This changes ARRANGEMENT ONLY. Every notification is still a
// Calendar.NotificationMessage built from a MessageTray.Notification, so
// delivery, storage, urgency, acknowledgement, actions and dismissal are all
// GNOME's code running unmodified. What this file decides is which card goes
// under which header, and in what order.
//
// It deliberately does NOT subclass MessageList.MessageListSection. That class
// defines `get _messages()` as "every child of _list, unwrapped", so inserting
// group headers into that list would corrupt its own empty/can-clear/clear()
// logic. Implementing the small contract CalendarMessageList actually consumes
// - allowed, empty, canClear, clear(), and the matching notifications - is both
// safer and less code than fighting those assumptions.

/* exported GroupedNotificationSection */

const { St, Clutter, GObject } = imports.gi;
const Main = imports.ui.main;
const Calendar = imports.ui.calendar;
const MessageTray = imports.ui.messageTray;

// Groups larger than this collapse to a summary until clicked.
const COLLAPSE_AFTER = 3;
const GROUP_ICON_SIZE = 20;

var NotificationGroup = GObject.registerClass({
    Signals: {
        'group-changed': {},
        'message-focused': { param_types: [Clutter.Actor.$gtype] },
    },
}, class NotificationGroup extends St.BoxLayout {
    _init(source) {
        super._init({
            style_class: 'adaptive-notif-group',
            vertical: true,
            x_expand: true,
        });

        this.source = source;
        this._messages = [];
        this._expanded = false;

        this._header = new St.Button({
            style_class: 'adaptive-notif-group-header',
            can_focus: true,
            x_expand: true,
        });
        this.add_child(this._header);

        const headerBox = new St.BoxLayout({ x_expand: true });
        this._header.set_child(headerBox);

        this._iconBin = new St.Bin({
            style_class: 'adaptive-notif-group-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        headerBox.add_child(this._iconBin);
        this._updateIcon();

        this._titleLabel = new St.Label({
            text: source.title || '',
            style_class: 'adaptive-notif-group-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        headerBox.add_child(this._titleLabel);

        this._countLabel = new St.Label({
            style_class: 'adaptive-notif-group-count',
            y_align: Clutter.ActorAlign.CENTER,
        });
        headerBox.add_child(this._countLabel);

        this._chevron = new St.Icon({
            icon_name: 'pan-down-symbolic',
            style_class: 'adaptive-notif-group-chevron',
            y_align: Clutter.ActorAlign.CENTER,
        });
        headerBox.add_child(this._chevron);

        this._header.connect('clicked', () => this._toggle());

        this._list = new St.BoxLayout({
            style_class: 'adaptive-notif-group-list',
            vertical: true,
            x_expand: true,
        });
        this.add_child(this._list);

        // "+2 more" - the affordance that says a collapsed group is hiding
        // something, which a chevron alone does not.
        this._moreButton = new St.Button({
            style_class: 'adaptive-notif-more',
            can_focus: true,
            x_expand: true,
        });
        this._moreButton.connect('clicked', () => this._toggle());
        this.add_child(this._moreButton);

        source.connectObject(
            'notify::title', () => (this._titleLabel.text = source.title || ''),
            'icon-updated', () => this._updateIcon(),
            this);

        this._sync();
    }

    _updateIcon() {
        try {
            this._iconBin.child = this.source.createIcon(GROUP_ICON_SIZE);
        } catch (e) {
            // A source that cannot draw its own icon still deserves a group.
            this._iconBin.child = new St.Icon({
                icon_name: 'application-x-executable-symbolic',
                icon_size: GROUP_ICON_SIZE,
            });
        }
    }

    get messages() {
        return this._messages.slice();
    }

    get empty() {
        return this._messages.length === 0;
    }

    get canClear() {
        return this._messages.some(m => m.canClose());
    }

    addMessage(message, urgent) {
        // Urgent notifications go to the top of their group for the same reason
        // GNOME puts them at the top of the flat list.
        const index = urgent ? 0 : this._messages.length;
        this._messages.splice(index, 0, message);
        this._list.insert_child_at_index(message, index);

        message.connectObject(
            'close', () => this._removeMessage(message),
            'destroy', () => this._forgetMessage(message),
            'key-focus-in', () => this.emit('message-focused', message),
            this);

        this._sync();
    }

    _removeMessage(message) {
        // Message.close() only announces the intent; the container is what
        // actually takes the card away.
        this._forgetMessage(message);
        if (message.get_parent())
            message.destroy();
    }

    _forgetMessage(message) {
        const index = this._messages.indexOf(message);
        if (index < 0)
            return;

        this._messages.splice(index, 1);
        this._sync();
        this.emit('group-changed');
    }

    _toggle() {
        this._expanded = !this._expanded;
        this._sync();
    }

    _sync() {
        const total = this._messages.length;
        this._countLabel.text = total > 1 ? `${total}` : '';
        this._countLabel.visible = total > 1;

        const collapsible = total > COLLAPSE_AFTER;
        const showing = this._expanded || !collapsible
            ? total
            : COLLAPSE_AFTER;

        this._messages.forEach((message, i) => {
            message.visible = i < showing;
        });

        this._chevron.visible = collapsible;
        this._chevron.icon_name = this._expanded
            ? 'pan-up-symbolic'
            : 'pan-down-symbolic';

        const hidden = total - showing;
        this._moreButton.visible = collapsible;
        this._moreButton.label = this._expanded
            ? 'Show less'
            : `${hidden} more`;

        this.visible = total > 0;
    }

    clear() {
        for (const message of this._messages.slice()) {
            if (message.canClose())
                message.close();
        }
    }

    destroy() {
        this.source?.disconnectObject(this);
        for (const message of this._messages)
            message.disconnectObject(this);
        this._messages = [];
        super.destroy();
    }
});

var GroupedNotificationSection = GObject.registerClass({
    Properties: {
        'can-clear': GObject.ParamSpec.boolean(
            'can-clear', 'can-clear', 'can-clear',
            GObject.ParamFlags.READABLE, false),
        'empty': GObject.ParamSpec.boolean(
            'empty', 'empty', 'empty',
            GObject.ParamFlags.READABLE, true),
    },
    Signals: {
        'can-clear-changed': {},
        'empty-changed': {},
        'message-focused': { param_types: [Clutter.Actor.$gtype] },
    },
}, class GroupedNotificationSection extends St.BoxLayout {
    _init() {
        super._init({
            style_class: 'message-list-section adaptive-notif-section',
            vertical: true,
            x_expand: true,
        });

        this._groups = new Map();
        this._empty = true;
        this._canClear = false;

        Main.messageTray.connectObject(
            'source-added', (_tray, source) => this._addSource(source),
            'source-removed', (_tray, source) => this._removeSource(source),
            this);

        Main.sessionMode.connectObject('updated', () => this._sync(), this);

        // Adopt whatever is already in the tray. Attaching mid-session must not
        // lose the notifications that arrived before the shade existed.
        for (const source of Main.messageTray.getSources())
            this._addSource(source);

        this._sync();
    }

    // CalendarMessageList reads this to decide whether the whole list shows.
    get allowed() {
        return Main.sessionMode.hasNotifications && !Main.sessionMode.isGreeter;
    }

    get empty() {
        return this._empty;
    }

    get canClear() {
        return this._canClear;
    }

    _addSource(source) {
        if (this._groups.has(source))
            return;

        const group = new NotificationGroup(source);
        group.connectObject(
            'group-changed', () => this._sync(),
            'message-focused', (_g, actor) => this.emit('message-focused', actor),
            this);

        this._groups.set(source, group);
        this.add_child(group);

        source.connectObject(
            'notification-added',
            (_source, notification) => this._addNotification(source, notification),
            this);

        // Same reason as above: a source that already holds notifications when
        // it is adopted must show them, not just future ones.
        for (const notification of source.notifications)
            this._addNotification(source, notification);

        this._sync();
    }

    _removeSource(source) {
        const group = this._groups.get(source);
        if (!group)
            return;

        source.disconnectObject(this);
        this._groups.delete(source);
        group.destroy();
        this._sync();
    }

    _addNotification(source, notification) {
        const group = this._groups.get(source);
        if (!group)
            return;

        const message = new Calendar.NotificationMessage(notification);
        message.setSecondaryActor(new Calendar.TimeLabel(notification.datetime));

        const urgent = notification.urgency === MessageTray.Urgency.CRITICAL;

        notification.connectObject('updated', () => {
            message.setSecondaryActor(new Calendar.TimeLabel(notification.datetime));
        }, message);

        // Acknowledging a non-urgent notification is what stops it re-banner-ing.
        // Urgent ones keep their actions until the user deals with them.
        if (!urgent && this.mapped)
            notification.acknowledged = true;

        group.addMessage(message, urgent);
        this._reorder();
        this._sync();
    }

    // Groups holding an urgent notification float to the top; the rest keep
    // tray order, which is the order their applications last spoke.
    _reorder() {
        const groups = [...this._groups.values()];
        const urgent = groups.filter(g => this._isUrgent(g));

        urgent.forEach((group, i) => {
            if (this.get_children().indexOf(group) !== i)
                this.set_child_at_index(group, i);
        });
    }

    _isUrgent(group) {
        return group.messages.some(m =>
            m.notification &&
            m.notification.urgency === MessageTray.Urgency.CRITICAL);
    }

    vfunc_map() {
        for (const group of this._groups.values()) {
            for (const message of group.messages) {
                if (message.notification &&
                    message.notification.urgency !== MessageTray.Urgency.CRITICAL)
                    message.notification.acknowledged = true;
            }
        }
        super.vfunc_map();
    }

    clear() {
        for (const group of this._groups.values())
            group.clear();
    }

    _sync() {
        const groups = [...this._groups.values()];

        // A source with no notifications keeps its group object - the app is
        // still registered and may speak again - but shows nothing.
        const empty = groups.every(g => g.empty);
        if (this._empty !== empty) {
            this._empty = empty;
            this.notify('empty');
        }

        const canClear = groups.some(g => g.canClear);
        if (this._canClear !== canClear) {
            this._canClear = canClear;
            this.notify('can-clear');
        }

        this.visible = this.allowed && !empty;
    }

    destroy() {
        Main.messageTray.disconnectObject(this);
        Main.sessionMode.disconnectObject(this);
        for (const source of this._groups.keys())
            source.disconnectObject(this);
        this._groups.clear();
        super.destroy();
    }
});
