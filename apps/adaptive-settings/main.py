#!/usr/bin/env python3
"""Adaptive Settings - the sections gnome-control-center has no panel for.

Settings is gnome-control-center under the Adaptive skin (docs/BACKLOG.md,
Milestone 8). What it cannot hold are the parts that only exist in Adaptive
Desktop, so they live here, in three sections:

  Projects & Workspaces   the project registry, each project's workspace and
                          focus profile, and how many workspaces there are
  Search & Commands       Adaptive's keyboard shortcuts, the file index the
                          palette searches, and the overview's project search
  Updates & Recovery      this checkout's updates, Ubuntu's, the session, the
                          way back to Ubuntu, and the live verification record

Like the Shade, it reimplements nothing: every control is a view onto a
backend that already exists (see backend.py), and every change applies at once.

    main.py [--section projects|search|system]
"""

import json
import shutil
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend as B  # noqa: E402

APP_ID = "com.karthi.AdaptiveSettings"
HERE = Path(__file__).resolve().parent

BUS_NAME = "org.adaptive.ProjectContext"
OBJECT_PATH = "/org/adaptive/ProjectContext"
DBUS_TIMEOUT_MS = 3000

SECTIONS = [
    ("projects", "Projects & Workspaces"),
    ("search", "Search & Commands"),
    ("system", "Updates & Recovery"),
]

WORKSPACE_SLOTS = 9
WORKSPACE_LABELS = ["None"] + [f"Workspace {n}" for n in range(1, WORKSPACE_SLOTS + 1)]
FOCUS_LABELS = ["No preference", "Focus on", "Focus off"]
RESULT_IDS = ["pending", "pass", "fail", "na"]
RESULT_LABELS = ["Pending", "Pass", "Fail", "N/A"]
TOAST_S = 4


def settings_for(schema_id):
    """Gio.Settings, or None when the schema is not installed.

    Gio.Settings.new() aborts the process on an unknown schema instead of
    raising, so it is looked up first.
    """
    source = Gio.SettingsSchemaSource.get_default()
    if source and source.lookup(schema_id, True):
        return Gio.Settings.new(schema_id)
    return None


def run_async(argv, callback=None):
    """Run argv off the main loop; callback(ok, stdout, stderr)."""
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as error:
        if callback:
            callback(False, "", error.message)
        return

    def done(p, res):
        try:
            _, out, err = p.communicate_utf8_finish(res)
            ok = p.get_successful()
        except GLib.Error as error:
            out, err, ok = "", error.message, False
        if callback:
            callback(ok, out or "", err or "")

    proc.communicate_utf8_async(None, None, done)


def label(text, css=None, xalign=0.0, wrap=False):
    widget = Gtk.Label(label=text, xalign=xalign)
    if wrap:
        widget.set_wrap(True)
    if css:
        widget.add_css_class(css)
    return widget


def button(text, callback, css="quiet"):
    widget = Gtk.Button(label=text)
    widget.add_css_class(css)
    widget.set_valign(Gtk.Align.CENTER)
    widget.connect("clicked", lambda *_: callback())
    return widget


def dropdown(labels, selected=0):
    widget = Gtk.DropDown.new_from_strings(labels)
    widget.add_css_class("choice")
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_selected(selected)
    return widget


class Card(Gtk.Box):
    def __init__(self, title, subtitle=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("card")
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head.add_css_class("card-head")
        head.append(label(title, "card-title"))
        self.subtitle = label(subtitle, "card-subtitle", wrap=True)
        self.subtitle.set_visible(bool(subtitle))
        head.append(self.subtitle)
        self.append(head)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(self.body)

    def set_subtitle(self, text):
        self.subtitle.set_text(text)
        self.subtitle.set_visible(bool(text))

    def clear(self):
        child = self.body.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.body.remove(child)
            child = nxt

    def row(self, title, hint="", *widgets):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        title_label = label(title, "row-title", wrap=True)
        text.append(title_label)
        hint_label = label(hint, "row-hint", wrap=True)
        hint_label.set_visible(bool(hint))
        text.append(hint_label)
        box.append(text)
        for widget in widgets:
            box.append(widget)
        box.title = title_label
        box.hint = hint_label
        self.body.append(box)
        return box


def set_hint(row, text, css=None):
    row.hint.set_text(text)
    row.hint.set_visible(bool(text))
    for name in ("warn", "good"):
        row.hint.remove_css_class(name)
    if css:
        row.hint.add_css_class(css)


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Adaptive Settings")
        self.set_default_size(980, 760)
        self.add_css_class("adaptive-settings")
        self._load_css()

        self.proxy = None
        self.ahead_behind = None
        self.repo = None
        self._toast_id = 0

        overlay = Gtk.Overlay()
        self.set_child(overlay)

        shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        overlay.set_child(shell)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)

        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self.stack)
        sidebar.add_css_class("sidebar")
        shell.append(sidebar)
        shell.append(self.stack)

        builders = {
            "projects": self._projects_page,
            "search": self._search_page,
            "system": self._system_page,
        }
        for name, title in SECTIONS:
            self.stack.add_titled(self._page(title, builders[name]()), name, title)

        self.toast = label("", "toast", xalign=0.5)
        self.toast.set_halign(Gtk.Align.CENTER)
        self.toast.set_valign(Gtk.Align.END)
        self.toast.set_visible(False)
        overlay.add_overlay(self.toast)

        self._connect_projects()
        self._refresh_projects()
        self._refresh_shortcuts()
        self._refresh_index()
        self._refresh_repo()
        self._refresh_session()
        self._refresh_verification()

    # ---------------------------------------------------------------- frame

    def _load_css(self):
        # GTK4 without libadwaita does not follow the desktop's colour scheme;
        # ask for its dark variant so dropdowns and popovers are dark too.
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(HERE / "style.css"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _page(self, title, cards):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("page")
        page.append(label(title, "title"))
        for card in cards:
            page.append(card)
        scroll.set_child(page)
        return scroll

    def show_section(self, name):
        if name in dict(SECTIONS):
            self.stack.set_visible_child_name(name)

    def notify(self, text):
        self.toast.set_text(text)
        self.toast.set_visible(True)
        if self._toast_id:
            GLib.source_remove(self._toast_id)

        def hide():
            self._toast_id = 0
            self.toast.set_visible(False)
            return GLib.SOURCE_REMOVE

        self._toast_id = GLib.timeout_add_seconds(TOAST_S, hide)

    def confirm(self, heading, body, action_label, on_yes):
        # Gtk.MessageDialog is deprecated from GTK 4.10, but Gtk.AlertDialog
        # only arrived then; Jammy ships GTK 4.6.
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE, text=heading)
        dialog.props.secondary_text = body
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(action_label, Gtk.ResponseType.ACCEPT)

        def answered(d, response):
            d.destroy()
            if response == Gtk.ResponseType.ACCEPT:
                on_yes()

        dialog.connect("response", answered)
        dialog.present()

    # ===================================================== Projects & Workspaces

    def _projects_page(self):
        self.projects_card = Card(
            "Projects",
            "Switching to a project moves to its workspace and applies its focus "
            "profile. Changes are saved by the Project Context Service.")
        self.projects_actions = Gtk.Box(spacing=8)
        self.projects_actions.add_css_class("card-actions")
        self.projects_actions.append(button("Add folder…", self._add_project, "accent"))
        self.projects_actions.append(button("Clear active project", self._clear_active))

        workspaces = Card("Workspaces", "GNOME's workspace settings for this session only.")
        self.mutter = settings_for("org.gnome.mutter")
        self.wm_prefs = settings_for("org.gnome.desktop.wm.preferences")

        if self.mutter:
            dynamic = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.mutter.bind("dynamic-workspaces", dynamic, "active",
                             Gio.SettingsBindFlags.DEFAULT)
            workspaces.row("Add and remove workspaces as needed",
                           "Off keeps a fixed number, which project workspaces rely on.",
                           dynamic)

        if self.wm_prefs:
            count = Gtk.SpinButton.new_with_range(1, 16, 1)
            count.set_valign(Gtk.Align.CENTER)
            self.wm_prefs.bind("num-workspaces", count, "value",
                               Gio.SettingsBindFlags.DEFAULT)
            if self.mutter:
                self.mutter.bind("dynamic-workspaces", count, "sensitive",
                                 Gio.SettingsBindFlags.GET
                                 | Gio.SettingsBindFlags.INVERT_BOOLEAN)
            workspaces.row("Number of workspaces", "", count)

        if self.mutter:
            primary = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.mutter.bind("workspaces-only-on-primary", primary, "active",
                             Gio.SettingsBindFlags.DEFAULT)
            workspaces.row("Workspaces on the primary display only",
                           "Other displays stay put when you switch.", primary)

        if not (self.mutter or self.wm_prefs):
            workspaces.row("Workspace settings are unavailable",
                           "GNOME's mutter schemas are not installed.")

        focus = Card("Focus")
        self.notif = settings_for("org.gnome.desktop.notifications")
        if self.notif:
            focus_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.notif.bind("show-banners", focus_switch, "active",
                            Gio.SettingsBindFlags.DEFAULT
                            | Gio.SettingsBindFlags.INVERT_BOOLEAN)
            focus.row("Focus now",
                      "Hides notification banners. They still collect in the Shade.",
                      focus_switch)

        return [self.projects_card, workspaces, focus]

    def _connect_projects(self):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                None, BUS_NAME, OBJECT_PATH, BUS_NAME, None)
        except GLib.Error:
            self.proxy = None
            return

        self.proxy.connect("g-signal", lambda *_: self._refresh_projects())
        self.proxy.connect("notify::g-name-owner", lambda *_: self._refresh_projects())

    def _call(self, method, signature=None, values=None):
        """A synchronous call to the Project Context Service, or None."""
        if not self.proxy or not self.proxy.get_name_owner():
            return None
        try:
            params = GLib.Variant(signature, values) if signature else None
            return self.proxy.call_sync(method, params, Gio.DBusCallFlags.NONE,
                                        DBUS_TIMEOUT_MS, None).unpack()
        except GLib.Error as error:
            self.notify(f"Project Context Service: {error.message}")
            return None

    def _refresh_projects(self):
        card = self.projects_card
        card.clear()

        listed = self._call("ListProjects")
        online = listed is not None
        if online:
            projects = json.loads(listed[0] or "{}")
            active_id = (self._call("GetActiveProject") or ("",))[0]
        else:
            projects, active_id = B.projects_from_file()
            card.row("Project Context Service is not running",
                     "Showing the saved registry read-only. It starts with the "
                     "Adaptive session; ./scripts/install-project-context-service.sh "
                     "installs it.")

        if not projects:
            card.row("No projects yet",
                     "Add a folder to make it a project. Projects scanned by "
                     "scripts/project-scan.py appear here too.")

        for project in B.sorted_projects(projects, active_id):
            self._project_row(card, project, project.get("id") == active_id, online)

        self.projects_actions.set_sensitive(online)
        card.body.append(self.projects_actions)

    def _project_row(self, card, project, active, online):
        pid = project.get("id", "")
        name = project.get("name", pid)
        hint = B.home_relative(project.get("path", ""))
        if active:
            hint = f"Active · {hint}"

        workspace = dropdown(WORKSPACE_LABELS,
                             B.workspace_choice(project.get("workspace_index", -1),
                                                WORKSPACE_SLOTS))
        workspace.set_tooltip_text("Workspace to switch to when this project becomes active")
        workspace.connect("notify::selected", lambda d, _p: self._update_project(
            pid, {"workspace_index": d.get_selected() - 1}))

        focus = dropdown(FOCUS_LABELS, B.focus_choice(project))
        focus.set_tooltip_text("Notification banners while this project is active")
        focus.connect("notify::selected", lambda d, _p: self._update_project(
            pid, {"metadata": {"focus": B.FOCUS_CHOICES[d.get_selected()]}}))

        menu = Gtk.MenuButton(icon_name="view-more-symbolic", valign=Gtk.Align.CENTER)
        menu.add_css_class("quiet")
        menu.set_popover(self._project_popover(pid, name, active))

        row = card.row(name, hint, workspace, focus, menu)
        if active:
            row.add_css_class("active")
        for widget in (workspace, focus, menu):
            widget.set_sensitive(online)

    def _project_popover(self, pid, name, active):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("popover-body")

        def make_active():
            popover.popdown()
            self._call("SetActiveProject", "(s)", (pid,))

        def remove():
            popover.popdown()
            self.confirm(
                f"Remove {name}?",
                "Only the project entry is removed. The folder and its files "
                "are not touched.",
                "Remove",
                lambda: self._call("RemoveProject", "(s)", (pid,)))

        if not active:
            box.append(button("Make active", make_active))

        entry = Gtk.Entry(text=name)
        entry.set_placeholder_text("Project name")

        def rename():
            new_name = entry.get_text().strip()
            if new_name and new_name != name:
                popover.popdown()
                self._call("RenameProject", "(ss)", (pid, new_name))

        entry.connect("activate", lambda *_: rename())
        rename_row = Gtk.Box(spacing=6)
        rename_row.append(entry)
        rename_row.append(button("Rename", rename))
        box.append(rename_row)

        box.append(button("Remove from projects…", remove, "destructive"))
        popover.set_child(box)
        return popover

    def _update_project(self, pid, patch):
        result = self._call("UpdateProject", "(ss)", (pid, json.dumps(patch)))
        if result is not None and not result[0]:
            self.notify("That project no longer exists")

    def _add_project(self):
        chooser = Gtk.FileChooserNative.new(
            "Add a folder as a project", self, Gtk.FileChooserAction.SELECT_FOLDER,
            "Add", "Cancel")

        def chosen(native, response):
            folder = native.get_file() if response == Gtk.ResponseType.ACCEPT else None
            native.destroy()
            path = folder.get_path() if folder else None
            if not path:
                return
            result = self._call("AddProject", "(ss)", (path, Path(path).name))
            if result:
                self.notify(f"Added {Path(path).name}")

        chooser.connect("response", chosen)
        self._chooser = chooser  # FileChooserNative is not kept alive by GTK
        chooser.show()

    def _clear_active(self):
        self._call("SetActiveProject", "(s)", ("",))

    # ======================================================== Search & Commands

    def _search_page(self):
        self.shortcuts_card = Card(
            "Keyboard shortcuts",
            "Adaptive's own shortcuts. A shortcut GNOME's window manager already "
            "uses would never fire, so those are refused.")

        self.index_card = Card(
            "File search",
            "The Command palette searches plocate's index, plus a live walk of "
            "recent files in your home folder.")
        self.index_row = self.index_card.row(
            "File index", "", button("Refresh now", self._refresh_plocate))

        overview = Card("Overview search")
        provider = Gtk.Switch(valign=Gtk.Align.CENTER, active=B.project_provider_enabled())
        provider.connect("notify::active", self._toggle_provider)
        overview.row("Show projects in the Activities search",
                     "Typing a project name in the overview offers to switch to it.",
                     provider)

        palette = Card("Command palette")
        palette.row("Open the palette",
                    "Applications, files, projects, settings and actions in one field.",
                    button("Open", lambda: run_async(
                        [str(B.REPO / "scripts" / "adaptive-command-launch.sh")])))
        gestures = B.REPO / "apps" / "adaptive-gestures" / "main.py"
        if gestures.exists():
            palette.row("Touchpad gestures", "Three- and four-finger swipes.",
                        button("Open", lambda: run_async([sys.executable, str(gestures)])))

        return [self.shortcuts_card, palette, self.index_card, overview]

    def _refresh_shortcuts(self):
        card = self.shortcuts_card
        card.clear()
        shortcuts = B.adaptive_shortcuts()
        if not shortcuts:
            card.row("No Adaptive shortcuts are installed",
                     "Run ./scripts/install-keybindings.sh to add them.")
            return

        for shortcut in shortcuts:
            entry = Gtk.Entry(text=shortcut["binding"], valign=Gtk.Align.CENTER)
            entry.add_css_class("accel")
            entry.set_width_chars(16)
            entry.set_placeholder_text("Disabled")
            row = card.row(shortcut["name"], "", entry)
            entry.connect("activate", self._apply_shortcut, shortcut, row, shortcuts)
            apply = button("Set", lambda e=entry, s=shortcut, r=row:
                           self._apply_shortcut(e, s, r, shortcuts))
            row.append(apply)

    def _apply_shortcut(self, entry, shortcut, row, shortcuts):
        accel = entry.get_text().strip()
        if accel:
            parsed = Gtk.accelerator_parse(accel)
            ok, key = parsed[0], parsed[1]
            if not ok or not key:
                set_hint(row, f'"{accel}" is not a shortcut. Write it like <Super><Alt>t.', "warn")
                return
            accel = Gtk.accelerator_name(parsed[1], parsed[2])

        wanted = B.normalize_accel(accel)
        clashes = [s["name"] for s in shortcuts
                   if s is not shortcut and B.normalize_accel(s["binding"]) == wanted and wanted]
        clashes += B.find_conflicts(accel, B.grabbing_bindings())
        if clashes:
            set_hint(row, "Already used by " + ", ".join(clashes), "warn")
            return

        ok, err = B.set_shortcut(shortcut["path"], accel)
        if not ok:
            set_hint(row, err or "gsettings refused the change", "warn")
            return
        shortcut["binding"] = accel
        entry.set_text(accel)
        set_hint(row, "Saved" if accel else "Disabled", "good")

    def _refresh_index(self):
        db = B.plocate_db()
        if db is None:
            set_hint(self.index_row,
                     "plocate is not installed, so only the home-folder walk runs. "
                     "sudo apt install plocate", "warn")
            return
        try:
            age = GLib.get_real_time() / 1e6 - db.stat().st_mtime
        except OSError:
            age = None
        stale = age is None or age > 2 * 86400
        set_hint(self.index_row,
                 f"{B.describe_age(age).capitalize()}. Rebuilt daily by a system timer.",
                 "warn" if stale else None)

    def _refresh_plocate(self):
        set_hint(self.index_row, "Rebuilding… (asks for your password)")

        def rebuilt(ok, _out, err):
            self._refresh_index()
            self.notify("File index rebuilt" if ok else f"Not rebuilt: {err.strip() or 'cancelled'}")

        run_async(["pkexec", "updatedb"], rebuilt)

    def _toggle_provider(self, switch, _pspec):
        ok, err = B.set_project_provider(switch.get_active())
        if not ok:
            self.notify(err or "Could not change the overview search")

    # ===================================================== Updates & Recovery

    def _system_page(self):
        self.repo_card = Card("Adaptive Desktop")
        self.repo_row = self.repo_card.row("Checking…", "")
        self.repo_check = button("Check for updates", self._check_updates)
        self.repo_update = button("Update", self._update_repo, "accent")
        self.repo_update.set_sensitive(False)
        self.repo_row.append(self.repo_check)
        self.repo_row.append(self.repo_update)
        self.repo_restart = button("Restart shell", lambda: run_async(
            [str(B.REPO / "scripts" / "reload-adaptive-shell.sh"), "--restart-shell"]))
        self.repo_restart.set_visible(False)
        self.repo_status = self.repo_card.row("", "", self.repo_restart)
        self.repo_status.set_visible(False)

        ubuntu = Card("Ubuntu", "Ubuntu stays underneath and updates on its own schedule.")
        self.apt_row = ubuntu.row("Software updates", "Checking…")
        if shutil.which("update-manager"):
            self.apt_row.append(button("Software Updater",
                                       lambda: run_async(["update-manager"])))
        if B.APT_CHECK.exists():
            run_async([str(B.APT_CHECK)], self._apt_checked)
        else:
            set_hint(self.apt_row, "update-notifier is not installed")

        self.session_card = Card(
            "Session & recovery",
            "Normal Ubuntu is always one logout away. Choose it from the gear "
            "menu on the login screen.")

        self.verify_card = Card("Live verification")

        return [self.repo_card, ubuntu, self.session_card, self.verify_card]

    def _refresh_repo(self):
        self.repo = B.repo_state()
        row = self.repo_row
        title = row.title
        if self.repo is None:
            title.set_text("Not a git checkout")
            set_hint(row, str(B.REPO))
            self.repo_check.set_sensitive(False)
            return

        r = self.repo
        title.set_text(f"{r['branch']} · {r['head']}" + (f" · {r['tag']}" if r["tag"] else ""))
        hint = f"{r['subject']} ({r['date']})"
        if r["dirty"]:
            hint += f"\n{r['dirty']} uncommitted change(s)"
        set_hint(row, hint)
        self._show_update_state()

    def _check_updates(self):
        self.repo_check.set_sensitive(False)
        self._repo_message("Fetching…")

        def fetched(ok, _out, err):
            self.repo_check.set_sensitive(True)
            if not ok:
                self.ahead_behind = None
                self._repo_message(f"Could not reach the remote: {err.strip()}", "warn")
                return
            counts = B.git("rev-list", "--left-right", "--count", "HEAD...@{u}")
            self.ahead_behind = B.parse_ahead_behind(counts)
            self._refresh_repo()

        run_async(["git", "-C", str(B.REPO), "fetch", "--quiet"], fetched)

    def _show_update_state(self):
        blocker = B.update_blocker(self.repo, self.ahead_behind)
        self.repo_update.set_sensitive(not blocker)
        if self.ahead_behind is None:
            self._repo_message("")
        elif blocker:
            self._repo_message(blocker, None if blocker == "Already up to date" else "warn")
        else:
            behind = self.ahead_behind[1]
            self._repo_message(f"{behind} new commit(s) on {self.repo['upstream']}", "good")

    def _repo_message(self, text, css=None):
        self.repo_status.set_visible(bool(text))
        self.repo_restart.set_visible(False)
        title = self.repo_status.title
        title.set_text(text)
        for name in ("warn", "good"):
            title.remove_css_class(name)
        if css:
            title.add_css_class(css)

    def _update_repo(self):
        self.repo_update.set_sensitive(False)
        self._repo_message("Updating…")

        def synced(ok, _out, err):
            if not ok:
                self._repo_message(f"Pulled, but syncing the shell failed: {err.strip()}", "warn")
                return
            self._repo_message("Updated. Restart GNOME Shell to load the new shell code.", "good")
            self.repo_restart.set_visible(True)

        def pulled(ok, _out, err):
            self.ahead_behind = None
            self._refresh_repo()
            if not ok:
                self._repo_message(f"Update stopped: {err.strip()}", "warn")
                return
            run_async([str(B.REPO / "scripts" / "sync-shell.sh")], synced)

        run_async(["git", "-C", str(B.REPO), "pull", "--ff-only", "--quiet"], pulled)

    def _apt_checked(self, _ok, out, err):
        counts = B.parse_apt_check(err or out)
        if counts is None:
            set_hint(self.apt_row, "Could not read the update count")
        elif counts[0] == 0:
            set_hint(self.apt_row, "Ubuntu is up to date", "good")
        else:
            upgrades, security = counts
            text = f"{upgrades} update(s) available"
            if security:
                text += f", {security} of them security updates"
            set_hint(self.apt_row, text, "warn" if security else None)

    def _refresh_session(self):
        card = self.session_card
        card.clear()
        facts = B.session_facts()

        kind = facts.get("session_desktop") or "unknown"
        card.row("This session",
                 f"{kind} · {facts.get('session_type') or 'unknown display server'}"
                 f" · dconf profile {facts.get('dconf_profile') or 'default'}")

        fallback = card.row("Ubuntu fallback", "")
        if facts.get("ubuntu_session_entry"):
            set_hint(fallback, "Available on the login screen", "good")
        else:
            set_hint(fallback, "No Ubuntu session entry found in /usr/share/xsessions", "warn")

        card.row("Return to Ubuntu", "Logs out. Pick Ubuntu from the gear menu on the login screen.",
                 button("Log out…", lambda: run_async(["gnome-session-quit", "--logout"])))
        card.row("Recovery steps",
                 "What to run from a TTY (Ctrl+Alt+F3) if this session ever stops starting.",
                 button("Copy", self._copy_recovery))

        clamshell = Gtk.Switch(valign=Gtk.Align.CENTER, active=B.clamshell_enabled())
        clamshell.connect("notify::active", lambda s, _p: B.set_clamshell(s.get_active()))
        card.row("Keep running with the lid closed",
                 "Only while an external display is connected. Otherwise closing "
                 "the lid locks and suspends, and on battery it always suspends.",
                 clamshell)

    def _copy_recovery(self):
        text = "\n".join(B.recovery_steps()) + "\n"
        clipboard = self.get_display().get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_for_value(text))
        self.notify("Recovery steps copied")

    def _refresh_verification(self):
        card = self.verify_card
        card.clear()
        try:
            checks = B.verification()
        except Exception as error:  # the recorder is another file; never take the window down
            card.set_subtitle(f"Could not read the verification record: {error}")
            return

        done = sum(1 for _c, entry in checks if entry.get("result") in ("pass", "na"))
        failed = sum(1 for _c, entry in checks if entry.get("result") == "fail")
        summary = f"{done} of {len(checks)} physical checks recorded as passing"
        if failed:
            summary += f", {failed} failing"
        card.set_subtitle(
            summary + ". These can only be proven on the machine, so record them here "
            "as you test them. Saved by scripts/record-live-verification.py.")

        for check, entry in checks:
            result = entry.get("result", "pending")
            choice = dropdown(RESULT_LABELS, RESULT_IDS.index(result) if result in RESULT_IDS else 0)
            row = card.row(check["prompt"], entry.get("note", ""), choice)
            if result == "fail":
                row.add_css_class("failed")
            choice.connect("notify::selected", self._record_check, check["id"], result)

    def _record_check(self, choice, _pspec, check_id, previous):
        picked = RESULT_IDS[choice.get_selected()]
        if picked == "pending":
            # The recorder has no "un-record"; put the dropdown back.
            choice.set_selected(RESULT_IDS.index(previous) if previous in RESULT_IDS else 0)
            return
        if picked == previous:
            return
        try:
            B.record_verification(check_id, picked)
        except OSError as error:
            self.notify(f"Not recorded: {error}")
            return
        # Rebuilding the list from inside the dropdown's own signal would
        # destroy it mid-emission; do it once the handler has returned.
        GLib.idle_add(lambda: self._refresh_verification() and False)


class SettingsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        section = None
        for i, arg in enumerate(args):
            if arg == "--section" and i + 1 < len(args):
                section = args[i + 1]
            elif arg.startswith("--section="):
                section = arg.split("=", 1)[1]

        window = self.get_active_window() or SettingsWindow(self)
        if section:
            window.show_section(section)
        window.present()
        return 0


if __name__ == "__main__":
    raise SystemExit(SettingsApp().run(sys.argv))
