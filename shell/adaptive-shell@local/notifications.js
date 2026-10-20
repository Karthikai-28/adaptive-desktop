// Adaptive Shade notifications v3
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
//
// Order: urgent first, then newest first - inside a group and between groups
// (notificationOrder.js holds the rule, so it can be tested headless). Each
// card is stamped with an arrival sequence; the Focus timer's end-of-session
// digest is "what arrived after sequence N" (summarySince()).

/* exported GroupedNotificationSection */

const { St, Clutter, GObject } = imports.gi;
const Main = imports.ui.main;
const Util = imports.misc.util;
const Calendar = imports.ui.calendar;
const MessageTray = imports.ui.messageTray;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const NotificationOrder = Me.imports.notificationOrder;

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

        this.source = null;
        this._messages = [];
        this._metadata = new Map();
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

        // Something in here is critical: a red dot beside the name.
        this._urgentDot = new St.Widget({
            style_class: 'adaptive-notif-group-urgent',
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });

        this._titleLabel = new St.Label({
            style_class: 'adaptive-notif-group-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        headerBox.add_child(this._titleLabel);
        headerBox.add_child(this._urgentDot);

        this._countLabel = new St.Label({
            style_class: 'adaptive-notif-group-count',
            y_align: Clutter.ActorAlign.CENTER,
        });
        headerBox.add_child(this._countLabel);

        this._clearButton = new St.Button({
            label: 'Clear',
            style_class: 'adaptive-notif-group-clear',
            can_focus: true,
            accessible_name: 'Clear notifications from this application',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._clearButton.connect('clicked', () => this.clear());
        headerBox.add_child(this._clearButton);

        // GNOME 42's Settings cannot open on one application's page, so this
        // opens the Notifications panel; the app is one click away there.
        this._settingsButton = new St.Button({
            style_class: 'adaptive-notif-group-settings',
            can_focus: true,
            accessible_name: 'Notification settings',
            y_align: Clutter.ActorAlign.CENTER,
            child: new St.Icon({ icon_name: 'emblem-system-symbolic', icon_size: 14 }),
        });
        this._settingsButton.connect('clicked', () => {
            Main.panel.closeCalendar();
            Util.spawn(['gnome-control-center', 'notifications']);
        });
        headerBox.add_child(this._settingsButton);

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

        this.setSource(source);
        this._sync();
    }

    // The source whose name and icon head the card. A group can outlive the
    // source it was created for (see GroupedNotificationSection._groupKey), so
    // the section hands it another one when that happens.
    setSource(source) {
        this.source?.disconnectObject(this);
        this.source = source;

        this._syncTitle();
        this._updateIcon();

        source.connectObject(
            'notify::title', () => this._syncTitle(),
            'icon-updated', () => this._updateIcon(),
            this);
    }

    _syncTitle() {
        const title = this.source.title || '';
        this._titleLabel.text = title;
        this._header.accessible_name = `${title} notifications`;
        this._clearButton.accessible_name = `Clear notifications from ${title || 'this application'}`;
        this._settingsButton.accessible_name = `Notification settings for ${title || 'this application'}`;
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

    get urgent() {
        return this._messages.some(message => {
            const meta = this._metadata.get(message);
            return meta && meta.urgent;
        });
    }

    get latestSequence() {
        return this._messages.reduce((latest, message) => {
            const meta = this._metadata.get(message);
            return Math.max(latest, meta ? meta.sequence : 0);
        }, 0);
    }

    countSince(sequence) {
        return this._messages.filter(message => {
            const meta = this._metadata.get(message);
            return meta && meta.sequence > sequence;
        }).length;
    }

    addMessage(message, urgent, sequence) {
        // Urgent messages come first; within each urgency band the newest card
        // comes first. A collapsed group must never hide the message that just
        // arrived behind three older cards.
        const meta = { urgent: !!urgent, sequence };
        const index = this._messages.findIndex(existing =>
            NotificationOrder.compareMessages(
                meta, this._metadata.get(existing) || {}) < 0);
        const target = index < 0 ? this._messages.length : index;
        this._messages.splice(target, 0, message);
        this._metadata.set(message, meta);
        this._list.insert_child_at_index(message, target);

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
        this._metadata.delete(message);
        this._sync();
        this.emit('group-changed');
    }

    _toggle() {
        this._expanded = !this._expanded;
        this._sync();
    }

    setExpanded(expanded) {
        this._expanded = !!expanded;
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
        this._clearButton.visible = this.canClear;
        const urgent = this.urgent;
        this._urgentDot.visible = urgent;
        if (urgent)
            this.add_style_class_name('urgent');
        else
            this.remove_style_class_name('urgent');
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
        this._metadata.clear();
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
        // Total notifications across every group, for the shade's header badge.
        'count': GObject.ParamSpec.int(
            'count', 'count', 'count',
            GObject.ParamFlags.READABLE, 0, 0x7fffffff, 0),
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

        // Groups are keyed by application, not by source: see _groupKey().
        this._groups = new Map();
        this._sourceKeys = new Map();
        this._empty = true;
        this._canClear = false;
        this._count = 0;
        this._sequence = 0;

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

    get count() {
        return this._count;
    }

    // One card per application. Most apps keep a single source for their
    // lifetime, but some - notify-send, scripts, several Electron builds - open
    // a fresh source for every notification, and grouping by source gave each
    // of those its own one-item card. Sources are merged on the application
    // when GNOME knows it, and on the name the source shows otherwise.
    _groupKey(source) {
        try {
            const id = source.app && source.app.get_id();
            if (id)
                return `app:${id}`;
        } catch (e) {
            // No usable app; fall through to the title.
        }
        return `title:${source.title || ''}`;
    }

    _groupFor(source) {
        return this._groups.get(this._sourceKeys.get(source)) || null;
    }

    _addSource(source) {
        if (this._sourceKeys.has(source))
            return;

        const key = this._groupKey(source);
        this._sourceKeys.set(source, key);

        if (!this._groups.has(key)) {
            const group = new NotificationGroup(source);
            group.connectObject(
                'group-changed', () => {
                    this._reorder();
                    this._sync();
                },
                'message-focused', (_g, actor) => this.emit('message-focused', actor),
                this);

            this._groups.set(key, group);
            this.add_child(group);
        }

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
        const key = this._sourceKeys.get(source);
        if (key === undefined)
            return;

        source.disconnectObject(this);
        this._sourceKeys.delete(source);

        const group = this._groups.get(key);
        if (group) {
            // The card stays while any source of the same application is
            // still around; it only needs a live source to take its name from.
            const heir = [...this._sourceKeys].find(([, k]) => k === key);
            if (heir) {
                if (group.source === source)
                    group.setSource(heir[0]);
            } else {
                this._groups.delete(key);
                group.destroy();
            }
        }

        this._sync();
    }

    _addNotification(source, notification) {
        const group = this._groupFor(source);
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

        group.addMessage(message, urgent, ++this._sequence);
        this._reorder();
        this._sync();
    }

    // Urgent groups float to the top. The rest follow the application that
    // spoke most recently. Re-running this when a message closes also demotes a
    // group after its final critical notification is dismissed.
    _reorder() {
        const groups = [...this._groups.values()].sort((a, b) =>
            NotificationOrder.compareGroups({
                urgent: a.urgent,
                latestSequence: a.latestSequence,
            }, {
                urgent: b.urgent,
                latestSequence: b.latestSequence,
            }));

        groups.forEach((group, i) => {
            if (this.get_children().indexOf(group) !== i)
                this.set_child_at_index(group, i);
        });
    }

    // The arrival stamp of the newest notification so far.
    get sequence() {
        return this._sequence;
    }

    // What arrived after `sequence` and is still unread in the list.
    summarySince(sequence) {
        let count = 0;
        let apps = 0;
        for (const group of this._groups.values()) {
            const n = group.countSince(sequence);
            count += n;
            if (n > 0)
                apps++;
        }
        return { count, apps };
    }

    setAllExpanded(expanded) {
        for (const group of this._groups.values())
            group.setExpanded(expanded);
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
        const canClear = groups.some(g => g.canClear);
        const count = groups.reduce((n, g) => n + g.messages.length, 0);

        // Set visibility BEFORE notifying property changes. GNOME's
        // CalendarMessageList._sync() fires synchronously from notify::empty
        // and checks both `s.empty` and `s.visible` on each section. If
        // visible is still stale when that handler runs, GNOME miscalculates
        // the placeholder and clear-button state — showing "all caught up"
        // over a live notification and hiding the Clear button.
        this.visible = this.allowed && !empty;

        if (this._empty !== empty) {
            this._empty = empty;
            this.notify('empty');
        }

        if (this._canClear !== canClear) {
            this._canClear = canClear;
            this.notify('can-clear');
        }

        if (this._count !== count) {
            this._count = count;
            this.notify('count');
        }
    }

    destroy() {
        Main.messageTray.disconnectObject(this);
        Main.sessionMode.disconnectObject(this);
        for (const source of this._sourceKeys.keys())
            source.disconnectObject(this);
        this._sourceKeys.clear();
        this._groups.clear();
        super.destroy();
    }
});
