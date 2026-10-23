// The ROS 2 panel's New package dialog: a wizard in four steps, the way an IDE
// starts a project. 1 Template (C++ or Python node, component, library,
// interfaces, launch and config, empty), 2 Configure (name, node name, where in
// ~/ros2_ws/src, description, maintainer, licence), 3 Dependencies (everything
// on the left, what the package gets on the right; what the template needs is
// fixed), 4 Review (files, the command, build now, use ~/ros2_ws in the panel),
// then Create, and a result page. The helper does the work and checks it all
// again: `ros_info.py pkg-catalog` and `pkg-create`.

/* exported PackageWizard */

const { Clutter, GLib, GObject, Pango, St } = imports.gi;
const Main = imports.ui.main;
const ModalDialog = imports.ui.modalDialog;

const Me = imports.misc.extensionUtils.getCurrentExtension();
const Model = Me.imports.rosPackageModel;

const WIDTH = 860;
const BODY_HEIGHT = 470;
const LABEL_COLUMN = 134;

function label(text, styleClass = '', wrap = false) {
    const item = new St.Label({ text, style_class: styleClass });
    if (wrap) {
        item.clutter_text.line_wrap = true;
        item.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    }
    return item;
}

function chip(text, checked, onClick, extraClass = '') {
    const button = new St.Button({ label: text, can_focus: true, toggle_mode: false,
        style_class: `adaptive-ros-wizard-chip ${extraClass}`.trim() });
    if (checked)
        button.add_style_pseudo_class('checked');
    button.connect('clicked', onClick);
    return button;
}

// Chips in rows that wrap at `width`. Clutter.FlowLayout gives every chip the
// widest one's cell, and collapses to nothing inside a scroll view.
function chipRows(chips, width) {
    const box = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-wizard-chips' });
    let row = null;
    let used = 0;
    for (const item of chips) {
        const guess = (item.label || '').length * 7.4 + 30;
        if (!row || used + guess > width) {
            row = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-chip-row' });
            box.add_child(row);
            used = 0;
        }
        row.add_child(item);
        used += guess + 6;
    }
    return box;
}

function home(path) {
    const dir = GLib.get_home_dir();
    return path === dir || path.startsWith(`${dir}/`) ? `~${path.slice(dir.length)}` : path;
}

function scroller(child) {
    const scroll = new St.ScrollView({ style_class: 'adaptive-ros-wizard-scroll', x_expand: true, y_expand: true,
        overlay_scrollbars: true, hscrollbar_policy: St.PolicyType.NEVER, vscrollbar_policy: St.PolicyType.AUTOMATIC });
    scroll.add_actor(child);
    return scroll;
}

var PackageWizard = GObject.registerClass(
class AdaptiveRosPackageWizard extends ModalDialog.ModalDialog {
    // helper(args, done) runs ros_info.py; openFolder(path); onCreated(reply) refreshes the panel.
    _init({ helper, openFolder, onCreated }) {
        super._init({ styleClass: 'adaptive-ros-wizard', destroyOnClose: true });
        // As large as the screen allows: 860 x 470 on this machine's 1920 x 1200.
        const monitor = Main.layoutManager.primaryMonitor || { width: 1280, height: 800 };
        const scale = St.ThemeContext.get_for_stage(global.stage).scale_factor;
        this._width = Math.max(560, Math.min(WIDTH, monitor.width / scale - 80)) - 48;
        const bodyHeight = Math.max(260, Math.min(BODY_HEIGHT, monitor.height / scale - 300));
        this.contentLayout.style = `width: ${this._width}px;`;
        this._helperCall = helper;
        this._openFolder = openFolder;
        this._onCreated = onCreated;
        this._step = 0;
        this._catalog = null;
        this._error = '';
        this._busy = false;
        this._result = null;
        this._query = '';
        this._category = 'Recommended';
        this._form = {
            template: null, name: '', nodeName: '', nodeNameEdited: false, libraryName: '', libraryNameEdited: false,
            location: 'src', description: '', maintainerName: '', maintainerEmail: '', license: 'Apache-2.0',
            interfaces: ['msg'], selected: [], build: true, useWorkspace: false, openFolder: false,
        };

        const header = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-header', x_expand: true });
        const titles = new St.BoxLayout({ vertical: true, x_expand: true });
        titles.add_child(label('New ROS 2 package', 'adaptive-ros-wizard-title'));
        this._subtitle = label('In ~/ros2_ws/src', 'adaptive-ros-wizard-subtitle');
        titles.add_child(this._subtitle);
        header.add_child(titles);
        this._steps = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-steps', y_align: Clutter.ActorAlign.CENTER });
        header.add_child(this._steps);
        this.contentLayout.add_child(header);

        this._body = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-wizard-body',
            style: `height: ${bodyHeight}px;` });
        this.contentLayout.add_child(this._body);
        this._footer = label('', 'adaptive-ros-wizard-error', true);
        this.contentLayout.add_child(this._footer);

        this._render();
        this._helperCall(['pkg-catalog'], reply => this._loaded(reply));
    }

    _loaded(reply) {
        if (!reply.ok) {
            this._error = reply.error || 'The package catalog could not be read';
            this._render();
            return;
        }
        this._catalog = reply;
        const d = reply.defaults || {};
        const s = this._form;
        s.template = reply.templates.find(t => t.id === d.template) || reply.templates[0];
        s.maintainerName = d.maintainer_name || '';
        s.maintainerEmail = d.maintainer_email || '';
        s.license = d.license || 'Apache-2.0';
        s.location = reply.locations.some(l => l.name === d.location) ? d.location : 'src';
        s.selected = Model.initialSelection(s.template, reply.packages);
        s.build = reply.colcon;
        s.useWorkspace = !reply.panel_workspace;
        this._subtitle.text = `In ~/ros2_ws/src · ROS 2 ${reply.distro}`;
        this._render();
    }

    // -------------------------------------------------------------- frame

    _render() {
        this._body.destroy_all_children();
        this._steps.destroy_all_children();
        this._footer.text = this._error;
        this._footer.visible = !!this._error;
        if (this._result) {
            this._renderDone();
            return;
        }
        Model.STEPS.forEach((name, i) => {
            const item = label(`${i + 1}  ${name}`, 'adaptive-ros-wizard-step');
            if (i === this._step)
                item.add_style_pseudo_class('checked');
            else if (i < this._step)
                item.add_style_class_name('adaptive-ros-wizard-step-done');
            this._steps.add_child(item);
        });
        if (!this._catalog) {
            this._body.add_child(label(this._error ? 'The dialog cannot continue.' : 'Reading the installed packages…',
                'adaptive-ros-wizard-hint'));
            this._setButtons([{ label: 'Cancel', action: () => this.close(), key: Clutter.KEY_Escape }]);
            return;
        }
        [this._renderTemplate, this._renderConfigure, this._renderDependencies, this._renderReview][this._step].call(this);
        const last = this._step === Model.STEPS.length - 1;
        const problem = this._stepProblem();
        this._setButtons([
            { label: 'Cancel', action: () => this.close(), key: Clutter.KEY_Escape },
            this._step > 0 ? { label: 'Back', action: () => this._go(-1) } : null,
            { label: this._busy ? 'Creating…' : last ? 'Create' : 'Next',
                action: () => (last ? this._create() : this._go(1)),
                // Enter in the dependency search adds the first match instead.
                default: this._step !== 2, disabled: !!problem || this._busy },
        ]);
    }

    _setButtons(items) {
        this.clearButtons();
        for (const item of items.filter(Boolean)) {
            const button = this.addButton(item);
            if (item.disabled) {
                button.reactive = false;
                button.add_style_pseudo_class('insensitive');
            }
        }
    }

    // Why Next cannot be pressed yet ('' when it can).
    _stepProblem() {
        const s = this._form;
        if (this._step === 1 || this._step === 3) {
            const name = Model.validateName(s.name, this._catalog, s.template);
            if (!name.ok)
                return name.error || 'Name the package';
            if (Model.hasField(s.template, 'node_name') && s.nodeName && !Model.validateIdentifier(s.nodeName))
                return 'The node name must be an identifier';
            if (Model.hasField(s.template, 'library_name') && s.libraryName && !Model.validateIdentifier(s.libraryName))
                return 'The library name must be an identifier';
            if (!Model.validateEmail(s.maintainerEmail))
                return 'The email does not look like an address';
            if (Model.hasField(s.template, 'interfaces') && !s.interfaces.length)
                return 'Pick at least one kind of interface';
        }
        return '';
    }

    _go(delta) {
        if (delta > 0 && this._stepProblem())
            return;
        this._error = '';
        this._step = Math.max(0, Math.min(Model.STEPS.length - 1, this._step + delta));
        this._render();
    }

    _focusLater(entry) {
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            if (entry.get_stage()) {
                entry.grab_key_focus();
                entry.clutter_text.set_cursor_position(-1);
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _entry(text, hint, onChange, focus = false) {
        const entry = new St.Entry({ style_class: 'adaptive-cc-entry', text, hint_text: hint, can_focus: true,
            x_expand: true });
        entry.clutter_text.connect('text-changed', () => onChange(entry.get_text()));
        if (focus)
            this._focusLater(entry);
        return entry;
    }

    _field(box, title, child, note = null) {
        const row = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-field', x_expand: true });
        row.add_child(label(title, 'adaptive-ros-wizard-label'));
        const right = new St.BoxLayout({ vertical: true, x_expand: true });
        right.add_child(child);
        if (note)
            right.add_child(note);
        row.add_child(right);
        box.add_child(row);
        return row;
    }

    // -------------------------------------------------------------- 1 template

    _renderTemplate() {
        this._body.add_child(label('What kind of package?', 'adaptive-ros-wizard-heading'));
        const grid = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-wizard-grid' });
        const templates = this._catalog.templates;
        const across = this._width >= 740 ? 4 : 3;
        for (let i = 0; i < templates.length; i += across) {
            const row = new St.BoxLayout({ x_expand: true, style_class: 'adaptive-ros-wizard-grid-row' });
            row.layout_manager.homogeneous = true;
            for (const template of templates.slice(i, i + across))
                row.add_child(this._templateCard(template));
            grid.add_child(row);
        }
        this._body.add_child(scroller(grid));
        const t = this._form.template;
        this._body.add_child(label(`${t.title}: ${t.subtitle}. Built with ${t.build_type}` +
            `${t.required.length ? `; needs ${t.required.join(', ')}` : ''}.`, 'adaptive-ros-wizard-hint', true));
    }

    _templateCard(template) {
        const selected = this._form.template.id === template.id;
        const card = new St.Button({ style_class: 'adaptive-ros-wizard-card', can_focus: true, x_expand: true,
            accessible_name: template.title });
        if (selected)
            card.add_style_pseudo_class('checked');
        const box = new St.BoxLayout({ vertical: true, x_expand: true });
        box.add_child(new St.Icon({ icon_name: template.icon, style_class: 'adaptive-ros-wizard-card-icon',
            x_align: Clutter.ActorAlign.START }));
        box.add_child(label(template.title, 'adaptive-ros-wizard-card-title'));
        box.add_child(label(template.subtitle, 'adaptive-ros-wizard-card-subtitle', true));
        box.add_child(label(template.language, 'adaptive-ros-wizard-badge'));
        card.set_child(box);
        card.connect('clicked', () => this._chooseTemplate(template));
        return card;
    }

    _chooseTemplate(template) {
        const s = this._form;
        if (s.template.id === template.id) {
            this._go(1);                         // a second click on the chosen one moves on
            return;
        }
        // The old template's own dependencies go; anything picked by hand stays.
        const old = new Set([...s.template.required, ...s.template.suggested]);
        const kept = s.selected.filter(name => !old.has(name));
        s.template = template;
        s.selected = [...Model.initialSelection(template, this._catalog.packages), ...kept]
            .filter((name, i, all) => all.indexOf(name) === i);
        this._render();
    }

    // -------------------------------------------------------------- 2 configure

    _renderConfigure() {
        const s = this._form;
        const form = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-wizard-form' });
        const nameNote = label('', 'adaptive-ros-wizard-hint', true);
        const showName = () => {
            const check = Model.validateName(s.name, this._catalog, s.template);
            nameNote.text = check.error || check.warning ||
                (s.name ? `~/ros2_ws/${s.location}/${s.name}` : 'Lowercase letters, digits and _, starting with a letter');
            nameNote.style_class = check.error ? 'adaptive-ros-wizard-error' : check.warning
                ? 'adaptive-ros-wizard-warning' : 'adaptive-ros-wizard-hint';
        };
        let nodeEntry = null;
        const name = this._entry(s.name, 'my_robot_driver', text => {
            s.name = text.trim();
            if (nodeEntry && !s.nodeNameEdited) {
                s.nodeName = s.name ? `${s.name}_node` : '';
                nodeEntry.text = s.nodeName;
                s.nodeNameEdited = false;
            }
            if (!s.libraryNameEdited)
                s.libraryName = s.name;
            showName();
            this._refreshButtons();
        }, true);
        this._field(form, 'Package name', name, nameNote);
        showName();

        if (Model.hasField(s.template, 'node_name')) {
            nodeEntry = this._entry(s.nodeName || (s.name ? `${s.name}_node` : ''), 'my_node', text => {
                s.nodeName = text.trim();
                s.nodeNameEdited = true;
                this._refreshButtons();
            });
            this._field(form, s.template.id === 'cpp_component' ? 'Component' : 'Node name', nodeEntry,
                label(s.template.id === 'cpp_component' ? 'Also the executable that runs it alone'
                    : 'The executable, and the name the node runs under', 'adaptive-ros-wizard-hint'));
        }
        if (Model.hasField(s.template, 'library_name')) {
            this._field(form, 'Library name', this._entry(s.libraryName || s.name, 'my_library', text => {
                s.libraryName = text.trim();
                s.libraryNameEdited = true;
                this._refreshButtons();
            }));
        }
        const chipWidth = this._width - LABEL_COLUMN - 16;
        if (Model.hasField(s.template, 'interfaces')) {
            const kinds = [];
            for (const [kind, title] of [['msg', 'Message  msg/Status.msg'], ['srv', 'Service  srv/Command.srv'],
                ['action', 'Action  action/Task.action']]) {
                const on = s.interfaces.includes(kind);
                kinds.push(chip(`${on ? '✓' : '○'}  ${title}`, on, () => {
                    s.interfaces = on ? s.interfaces.filter(k => k !== kind) : [...s.interfaces, kind];
                    this._render();
                }));
            }
            this._field(form, 'Starter files', chipRows(kinds, chipWidth));
        }

        const places = [];
        for (const place of this._catalog.locations) {
            places.push(chip(`~/ros2_ws/${place.name}`, s.location === place.name, () => {
                s.location = place.name;
                this._render();
            }));
        }
        this._field(form, 'Location', chipRows(places, chipWidth));
        this._field(form, 'Description', this._entry(s.description, 'What the package does', text => {
            s.description = text;
        }));
        const who = new St.BoxLayout({ x_expand: true, style_class: 'adaptive-ros-wizard-pair' });
        who.add_child(this._entry(s.maintainerName, 'Your name', text => { s.maintainerName = text; }));
        const emailNote = label('', 'adaptive-ros-wizard-error');
        emailNote.visible = false;
        who.add_child(this._entry(s.maintainerEmail, 'you@example.com', text => {
            s.maintainerEmail = text.trim();
            emailNote.text = Model.validateEmail(s.maintainerEmail) ? '' : 'This does not look like an email address';
            emailNote.visible = !!emailNote.text;
            this._refreshButtons();
        }));
        this._field(form, 'Maintainer', who, emailNote);
        const licenses = [];
        for (const name of this._catalog.licenses) {
            licenses.push(chip(name, s.license === name, () => {
                s.license = name;
                this._render();
            }));
        }
        this._field(form, 'Licence', chipRows(licenses, chipWidth));
        this._body.add_child(scroller(form));
    }

    // Typing changes whether Next works without rebuilding the form under the cursor.
    _refreshButtons() {
        const problem = this._stepProblem();
        const next = this.buttonLayout.get_last_child();
        if (next) {
            next.reactive = !problem && !this._busy;
            if (next.reactive)
                next.remove_style_pseudo_class('insensitive');
            else
                next.add_style_pseudo_class('insensitive');
        }
    }

    // -------------------------------------------------------------- 3 dependencies

    _renderDependencies() {
        const s = this._form;
        const columns = new St.BoxLayout({ x_expand: true, y_expand: true, style_class: 'adaptive-ros-wizard-columns' });

        const left = new St.BoxLayout({ vertical: true, x_expand: true, y_expand: true,
            style_class: 'adaptive-ros-wizard-column' });
        const search = this._entry(this._query, 'Search every package, or type a name to add it', text => {
            this._query = text;
            fill();
        }, true);
        search.clutter_text.connect('activate', () => {
            const first = Model.availableDependencies(this._catalog.packages, { query: this._query,
                category: this._category, selected: s.selected, template: s.template, limit: 1 }).rows[0];
            if (first) {
                this._query = '';
                this._add(first.name);
            }
        });
        left.add_child(search);
        const categories = [];
        for (const name of ['Recommended', 'All', ...this._catalog.categories]) {
            if (!['Recommended', 'All'].includes(name) && !this._catalog.packages.some(r => r.category === name))
                continue;
            categories.push(chip(name, this._category === name && !this._query.trim(), () => {
                this._category = name;
                this._query = '';
                this._render();
            }, 'adaptive-ros-wizard-chip-small'));
        }
        left.add_child(chipRows(categories, this._width - 314 - 10));
        const list = new St.BoxLayout({ vertical: true, x_expand: true });
        left.add_child(scroller(list));
        const fill = () => {
            list.destroy_all_children();
            const found = Model.availableDependencies(this._catalog.packages, { query: this._query,
                category: this._category, selected: s.selected, template: s.template });
            for (const row of found.rows)
                list.add_child(this._dependencyRow(row, false));
            if (!found.rows.length)
                list.add_child(label(this._query ? 'Nothing matches' : 'Everything here is selected',
                    'adaptive-ros-wizard-hint'));
            if (found.more)
                list.add_child(label(`${found.more} more · search to narrow the list`, 'adaptive-ros-wizard-hint'));
        };
        fill();

        const right = new St.BoxLayout({ vertical: true, y_expand: true,
            style_class: 'adaptive-ros-wizard-column adaptive-ros-wizard-selected' });
        const chosen = Model.selectedDependencies(this._catalog.packages, s.selected, s.template);
        right.add_child(label(`The package depends on · ${chosen.length}`, 'adaptive-ros-wizard-heading'));
        const picked = new St.BoxLayout({ vertical: true, x_expand: true });
        for (const row of chosen)
            picked.add_child(this._dependencyRow(row, true));
        if (!chosen.length)
            picked.add_child(label('Nothing yet. Add packages from the left.', 'adaptive-ros-wizard-hint', true));
        right.add_child(scroller(picked));
        const missing = Model.missingDependencies(this._catalog.packages, s.selected);
        if (missing.length) {
            right.add_child(label(`Not installed: ${missing.join(', ')}. After creating, Install with rosdep ` +
                'gets them.', 'adaptive-ros-wizard-warning', true));
        }

        columns.add_child(left);
        columns.add_child(right);
        this._body.add_child(columns);
    }

    _dependencyRow(row, selected) {
        const box = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-dep', x_expand: true });
        const text = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        const top = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-dep-top' });
        top.add_child(label(row.name, 'adaptive-ros-wizard-dep-name'));
        if (row.required)
            top.add_child(label('template', 'adaptive-ros-wizard-badge'));
        if (row.workspace)
            top.add_child(label('workspace', 'adaptive-ros-wizard-badge'));
        if (!row.installed)
            top.add_child(label(row.custom ? 'typed' : 'not installed', 'adaptive-ros-wizard-badge adaptive-ros-wizard-badge-warn'));
        text.add_child(top);
        const about = row.required ? 'Needed by the template' : row.description;
        if (about) {
            const line = label(about, 'adaptive-ros-wizard-dep-about');
            line.clutter_text.ellipsize = Pango.EllipsizeMode.END;
            text.add_child(line);
        }
        box.add_child(text);
        if (!row.required) {
            const button = new St.Button({ style_class: 'adaptive-ros-wizard-dep-button', can_focus: true,
                label: selected ? '✕' : 'Add', accessible_name: `${selected ? 'Remove' : 'Add'} ${row.name}`,
                y_align: Clutter.ActorAlign.CENTER });
            button.connect('clicked', () => (selected ? this._remove(row.name) : this._add(row.name)));
            box.add_child(button);
        }
        return box;
    }

    _add(name) {
        if (!this._form.selected.includes(name))
            this._form.selected.push(name);
        this._render();
    }

    _remove(name) {
        this._form.selected = this._form.selected.filter(n => n !== name);
        this._render();
    }

    // -------------------------------------------------------------- 4 review

    _renderReview() {
        const s = this._form;
        const c = this._catalog;
        const missing = Model.missingDependencies(c.packages, s.selected);
        const location = (c.locations.find(l => l.name === s.location) || c.locations[0]).path;
        const columns = new St.BoxLayout({ x_expand: true, y_expand: true, style_class: 'adaptive-ros-wizard-columns' });
        const left = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'adaptive-ros-wizard-form' });
        const fact = (title, value) => {
            const row = new St.BoxLayout({ style_class: 'adaptive-ros-wizard-fact', x_expand: true });
            row.add_child(label(title, 'adaptive-ros-wizard-label'));
            row.add_child(label(value, 'adaptive-ros-wizard-value', true));
            left.add_child(row);
        };
        fact('Package', `${s.name}  ·  ${s.template.title}`);
        fact('Folder', `~/ros2_ws/${s.location}/${s.name}`);
        fact('Build type', s.template.build_type);
        if (Model.hasField(s.template, 'node_name'))
            fact(s.template.id === 'cpp_component' ? 'Component' : 'Node', s.nodeName || `${s.name}_node`);
        if (Model.hasField(s.template, 'library_name'))
            fact('Library', s.libraryName || s.name);
        fact('Maintainer', `${s.maintainerName || '(your user name)'}${s.maintainerEmail ? ` <${s.maintainerEmail}>` : ''}`);
        fact('Licence', s.license);
        fact('Depends on', s.selected.join(', ') || 'nothing');
        if (missing.length)
            left.add_child(label(`Not installed yet: ${missing.join(', ')}. The package is created; building it ` +
                'waits until they are installed.', 'adaptive-ros-wizard-warning', true));

        left.add_child(label('After creating', 'adaptive-ros-wizard-heading'));
        const options = [];
        const option = (on, text, flip) => {
            options.push(chip(`${on ? '✓' : '○'}  ${text}`, on, () => { flip(); this._render(); }));
        };
        if (c.colcon)
            option(s.build, 'Build it now (colcon, this package)', () => { s.build = !s.build; });
        if (c.panel_workspace !== c.workspace)
            option(s.useWorkspace, 'Use ~/ros2_ws in the ROS 2 panel', () => { s.useWorkspace = !s.useWorkspace; });
        option(s.openFolder, 'Open the folder', () => { s.openFolder = !s.openFolder; });
        left.add_child(chipRows(options, this._width - 314 - 10));
        if (c.panel_workspace && c.panel_workspace !== c.workspace && !s.useWorkspace)
            left.add_child(label(`The panel stays on ${home(c.panel_workspace)}; ` +
                'the build runs in ~/ros2_ws all the same.', 'adaptive-ros-wizard-hint', true));

        const right = new St.BoxLayout({ vertical: true, y_expand: true,
            style_class: 'adaptive-ros-wizard-column adaptive-ros-wizard-selected' });
        right.add_child(label('Files', 'adaptive-ros-wizard-heading'));
        const files = new St.BoxLayout({ vertical: true, x_expand: true });
        files.add_child(label(`${s.name}/`, 'adaptive-ros-wizard-file adaptive-ros-wizard-file-root'));
        for (const file of Model.filesFor(Model.specFor(s), s.template))
            files.add_child(label(`  ${file}`, 'adaptive-ros-wizard-file'));
        right.add_child(scroller(files));
        right.add_child(label('Runs', 'adaptive-ros-wizard-heading'));
        right.add_child(label(Model.commandFor(Model.specFor(s), s.template, location),
            'adaptive-ros-wizard-command', true));

        columns.add_child(scroller(left));
        columns.add_child(right);
        this._body.add_child(columns);
    }

    _create() {
        if (this._busy || this._stepProblem())
            return;
        this._busy = true;
        this._error = '';
        this._render();
        const spec = Model.specFor(this._form);
        this._helperCall(['pkg-create', JSON.stringify(spec)], reply => {
            this._busy = false;
            if (!reply.ok) {
                this._error = reply.error || 'The package was not created';
                this._render();
                return;
            }
            this._result = reply;
            if (this._form.openFolder)
                this._openFolder(reply.path);
            this._onCreated(reply);
            this._render();
        });
    }

    // -------------------------------------------------------------- done

    _renderDone() {
        const r = this._result;
        const path = home(r.path);
        this._body.add_child(label(`✓  ${r.name} is ready`, 'adaptive-ros-wizard-done'));
        this._body.add_child(label(`${path} · ${r.files.length} files`, 'adaptive-ros-wizard-subtitle'));
        const lines = [];
        if (r.build)
            lines.push(r.build.ok ? 'Building it now. The ROS 2 panel shows the progress under colcon build and ' +
                'Running from here.' : `Not built: ${r.build.error}`);
        if (r.workspace_set)
            lines.push('The ROS 2 panel now uses ~/ros2_ws.');
        if ((r.missing || []).length)
            lines.push(`Still to install: ${r.missing.join(', ')}. Install with rosdep opens a terminal for it.`);
        for (const line of lines)
            this._body.add_child(label(line, line.startsWith('Not built') ? 'adaptive-ros-wizard-warning'
                : 'adaptive-ros-wizard-hint', true));
        const files = new St.BoxLayout({ vertical: true, x_expand: true });
        for (const file of r.files)
            files.add_child(label(file, 'adaptive-ros-wizard-file'));
        this._body.add_child(scroller(files));
        this._setButtons([
            (r.missing || []).length ? { label: 'Install with rosdep', action: () => this._helperCall(
                ['pkg-install-deps', r.path], () => {}) } : null,
            { label: 'Open folder', action: () => { this._openFolder(r.path); this.close(); } },
            { label: 'Done', action: () => this.close(), default: true },
        ]);
    }
});
