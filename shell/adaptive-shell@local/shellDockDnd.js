// Adaptive Shell - dock drag and drop: reordering, pinning and unpinning.
//
// Part of the one AdaptiveShellV16 object in extension.js, kept in its own
// file by subject. The methods of the class below are copied onto that object
// when the extension loads, so `this` here is the shell itself and every
// field and method of the other parts is reachable through it.

/* exported ShellDockDnd */

const { St } = imports.gi;
const Main = imports.ui.main;
const DND = imports.ui.dnd;

// How far above the dock a pinned icon must be let go to unpin it.
const DOCK_REMOVE_DISTANCE = 90;

var ShellDockDnd = class ShellDockDnd {
    // ------------------------------------------------------ dock drag & drop
    //
    // The dock's order is GNOME's favorites list (the pinned apps, in order)
    // followed by open apps that are not pinned. So every drop is a change to
    // favorites: moving a pinned app moves it in the list, and dropping any
    // other app - an open one from the dock, or one from the app grid - pins
    // it where it lands. Dragging a pinned app well above the dock and
    // letting go unpins it.

    _installDockDnd() {
        this._dockDragMonitor = {
            dragMotion: event => this._dockDragMotion(event),
        };
        DND.addDragMonitor(this._dockDragMonitor);

        // App-grid drags are GNOME's own; these say when one starts and ends.
        this._overviewDragIds = [
            Main.overview.connect('item-drag-begin', () => {
                if (!this._dockDrag)
                    this._dockDrag = { app: null, button: null, external: true };
                this._dock26Layout();
            }),
            Main.overview.connect('item-drag-end', () => this._dockExternalDragEnd()),
            Main.overview.connect('item-drag-cancelled', () => this._dockExternalDragEnd()),
        ];
    }

    _removeDockDnd() {
        if (this._dockDragMonitor) {
            DND.removeDragMonitor(this._dockDragMonitor);
            this._dockDragMonitor = null;
        }
        for (const id of this._overviewDragIds)
            Main.overview.disconnect(id);
        this._overviewDragIds = [];
        this._dockRemovePlaceholder();
        this._dockShowRemoveHint(false);
        this._dockDrag = null;
    }

    _dockExternalDragEnd() {
        if (this._dockDrag && this._dockDrag.external) {
            this._dockDrag = null;
            this._dockRemovePlaceholder();
            this._dockFlushRefresh();
        }
    }

    _dockDragBegin(button, app) {
        this._hideTooltip();
        if (this._previews)
            this._previews.hide();
        const favorite = this._favorites.isFavorite(app.get_id());
        this._dockDrag = { app, button, favorite, removing: false, external: false };

        // The icon leaves its slot; a gap follows the pointer instead.
        button.hide();
        const dock = this._docks.find(d => d.appsBox.contains(button));
        if (dock)
            this._dockPlacePlaceholder(dock, this._dockSlotIndex(dock, button));
    }

    _dockDragCancelled() {
        const drag = this._dockDrag;
        // Not dropped anywhere: put the icon back before the snap-back
        // animation measures where to fly to.
        if (drag && !drag.removing && drag.button) {
            drag.button.show();
            this._dockRemovePlaceholder();
        }
        if (drag && drag.removing && drag.favorite) {
            try {
                this._favorites.removeFavorite(drag.app.get_id());
            } catch (e) {
                logError(e, '[Adaptive Shell] removing from the dock');
            }
        }
    }

    _dockDragEnd() {
        const drag = this._dockDrag;
        if (drag && drag.button) {
            try {
                drag.button.show();
            } catch (e) {
                // Already gone with a rebuilt dock.
            }
        }
        this._dockDrag = null;
        this._dockRemovePlaceholder();
        this._dockShowRemoveHint(false);
        this._dockFlushRefresh();
        this._dock26Layout();
    }

    _dockFlushRefresh() {
        if (this._dockRefreshPending) {
            this._dockRefreshPending = false;
            this._queueWindowListRefresh();
        }
    }

    // The app a drag is carrying: a dock icon's, or an app-grid icon's.
    _dockDragApp(source) {
        const app = source && source.app;
        return app && typeof app.get_id === 'function' ? app : null;
    }

    // Visible app icons of a dock, in order, without the one being dragged.
    _dockSlots(dock) {
        return dock.appsBox.get_children().filter(child =>
            child !== this._dockPlaceholder && child._adaptiveDockApp && child.visible);
    }

    _dockSlotIndex(dock, button) {
        const all = dock.appsBox.get_children().filter(c =>
            c !== this._dockPlaceholder && c._adaptiveDockApp);
        const before = all.slice(0, all.indexOf(button));
        return before.filter(c => c.visible).length;
    }

    // Where a pointer at rail-relative x would drop: the number of visible
    // icons whose centre it has passed.
    _dockIndexAt(dock, x) {
        const [railX] = dock.rail.get_transformed_position();
        const stageX = railX + x;
        let index = 0;
        for (const slot of this._dockSlots(dock)) {
            const [sx] = slot.get_transformed_position();
            const [w] = slot.get_transformed_size();
            if (stageX > sx + w / 2)
                index++;
        }
        return index;
    }

    _dockPlacePlaceholder(dock, index) {
        if (!this._dockPlaceholder) {
            this._dockPlaceholder = new St.Widget({ style_class: 'adaptive-dock-placeholder' });
        }
        const ph = this._dockPlaceholder;
        const slots = this._dockSlots(dock);
        const parent = ph.get_parent();
        if (parent && parent !== dock.appsBox)
            parent.remove_child(ph);
        if (!ph.get_parent())
            dock.appsBox.add_child(ph);

        if (index < slots.length)
            dock.appsBox.set_child_below_sibling(ph, slots[index]);
        else
            dock.appsBox.set_child_above_sibling(ph, null);
        ph._adaptiveIndex = index;
        ph._adaptiveDock = dock;
    }

    _dockRemovePlaceholder() {
        const ph = this._dockPlaceholder;
        if (ph) {
            ph.destroy();
            this._dockPlaceholder = null;
        }
    }

    _dockDragOver(dock, source, x) {
        // A file dragged from another app (Files, a browser): the shell cannot
        // take the drop, so hovering an app's icon brings that app forward to
        // drop into - the way GNOME's own dock does it.
        if (source === Main.xdndHandler) {
            this._dockSpringLoad(dock, x);
            return DND.DragMotionResult.CONTINUE;
        }

        const app = this._dockDragApp(source);
        if (!app)
            return DND.DragMotionResult.NO_DROP;

        this._dockPlacePlaceholder(dock, this._dockIndexAt(dock, x));
        this._dockShowRemoveHint(false);
        if (this._dockDrag)
            this._dockDrag.removing = false;

        return source._adaptiveDockItem
            ? DND.DragMotionResult.MOVE_DROP
            : DND.DragMotionResult.COPY_DROP;
    }

    _dockAcceptDrop(dock, source, x) {
        const app = this._dockDragApp(source);
        if (!app)
            return false;

        const id = app.get_id();
        const index = this._dockIndexAt(dock, x);

        // The dock shows installed favorites only, but the saved list can
        // still hold apps since uninstalled, and GNOME inserts by position in
        // the saved list. So land before the app the gap sits in front of,
        // looked up in the saved list; past the last pinned app, append.
        const shown = this._favorites.getFavorites().map(a => a.get_id()).filter(p => p !== id);
        const saved = global.settings.get_strv('favorite-apps').filter(p => p !== id);
        const before = shown[index];
        const position = before ? saved.indexOf(before) : -1;

        try {
            if (this._favorites.isFavorite(id))
                this._favorites.moveFavoriteToPos(id, position);
            else
                this._favorites.addFavoriteAtPos(id, position);
        } catch (e) {
            logError(e, '[Adaptive Shell] dock drop');
            return false;
        }
        return true;
    }

    // Follows every drag: drops the gap when the pointer leaves the dock, and
    // for a pinned dock icon dragged well above it, offers removal.
    _dockDragMotion(event) {
        const onDock = (this._docks || []).some(d =>
            d.rail && event.targetActor && d.rail.contains(event.targetActor));
        if (!onDock && this._dockPlaceholder)
            this._dockRemovePlaceholder();
        if (!onDock)
            this._cancelSpring();

        const drag = this._dockDrag;
        if (drag && !drag.external && drag.favorite && !onDock) {
            const dock = this._docks.find(d => d.zone) || null;
            const top = dock ? dock.zone.y : global.stage.height;
            drag.removing = event.y < top - DOCK_REMOVE_DISTANCE;
            this._dockShowRemoveHint(drag.removing, event.x, event.y);
            if (event.dragActor)
                event.dragActor.opacity = drag.removing ? 120 : 255;
        } else if (drag && drag.removing) {
            drag.removing = false;
            this._dockShowRemoveHint(false);
        }
        return DND.DragMotionResult.CONTINUE;
    }

    _dockShowRemoveHint(show, x = 0, y = 0) {
        if (!show) {
            if (this._dockRemoveLabel) {
                this._dockRemoveLabel.destroy();
                this._dockRemoveLabel = null;
            }
            return;
        }
        if (!this._dockRemoveLabel) {
            this._dockRemoveLabel = new St.Label({
                text: 'Remove from Dock',
                style_class: 'adaptive-dock-remove-hint',
            });
            Main.uiGroup.add_child(this._dockRemoveLabel);
        }
        const label = this._dockRemoveLabel;
        label.set_position(Math.round(x + 28), Math.round(y - 12));
        Main.uiGroup.set_child_above_sibling(label, null);
    }
};
