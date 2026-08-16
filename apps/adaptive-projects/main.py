#!/usr/bin/env python3
"""Project mode - every repository on the machine, in one view.

Reads the registry written by scripts/project-scan.py, so no git commands run
while the window is open: the scan already recorded branch, dirty count and
last commit for each project.

Ordering is by last commit, most recent first, which is the order that answers
"what am I working on" without being told.
"""

import json
import subprocess
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "com.karthi.AdaptiveProjects"
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REGISTRY = Path.home() / ".config/adaptive-desktop/projects.json"

# Accent per recency band, so the grid reads as a heat map of attention.
FRESH_D, WARM_D, COOL_D = 3, 30, 180


def relative(stamp):
    if not stamp:
        return "no commits"

    delta = max(0, int(time.time()) - stamp)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if delta >= size:
            return f"{delta // size}{unit} ago"
    return "just now"


def band(stamp):
    if not stamp:
        return "idle"

    days = (time.time() - stamp) / 86400
    if days <= FRESH_D:
        return "fresh"
    if days <= WARM_D:
        return "warm"
    if days <= COOL_D:
        return "cool"
    return "idle"


class Projects(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Projects")
        self.set_default_size(1180, 780)
        self.add_css_class("adaptive-projects")

        self.projects = self._load()
        self.query = ""

        self._load_css()
        self._build()
        self._render()

    # ------------------------------------------------------------------ data

    def _load(self):
        try:
            data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            return []

        items = []
        for entry in data.get("projects", {}).values():
            git = entry.get("metadata", {}).get("git", {})
            items.append({
                "id": entry.get("id", ""),
                "name": entry.get("name", "?"),
                "path": entry.get("path", ""),
                "branch": git.get("branch", "-"),
                "dirty": git.get("dirty", 0),
                "commits": git.get("commits", 0),
                "subject": git.get("last_commit_subject", ""),
                "at": git.get("last_commit_at", 0),
                "remote": git.get("remote", ""),
                "active": entry.get("id") == data.get("active_id"),
            })

        items.sort(key=lambda p: -p["at"])
        return items

    def _visible(self):
        if not self.query:
            return self.projects

        q = self.query.casefold()
        return [
            p for p in self.projects
            if q in p["name"].casefold()
            or q in p["path"].casefold()
            or q in p["branch"].casefold()
        ]

    # ---------------------------------------------------------------- chrome

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(HERE / "style.css"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        self.set_child(root)

        # --- header: greeting, then the numbers worth knowing at a glance ---
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.add_css_class("header")

        hour = time.localtime().tm_hour
        greeting = ("Good morning" if hour < 12
                    else "Good afternoon" if hour < 18
                    else "Good evening")

        title = Gtk.Label(label=greeting, xalign=0)
        title.add_css_class("greeting")
        header.append(title)

        sub = Gtk.Label(label="What are you working on?", xalign=0)
        sub.add_css_class("greeting-sub")
        header.append(sub)

        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        stats.add_css_class("stats")

        dirty = sum(1 for p in self.projects if p["dirty"])
        recent = sum(1 for p in self.projects if band(p["at"]) == "fresh")
        commits = sum(p["commits"] for p in self.projects)

        for value, label, accent in (
            (str(len(self.projects)), "REPOSITORIES", "accent"),
            (str(recent), "TOUCHED THIS WEEK", "cyan"),
            (str(dirty), "WITH CHANGES", "warning"),
            (f"{commits:,}", "COMMITS", "violet"),
        ):
            stats.append(self._stat(value, label, accent))

        header.append(stats)

        search = Gtk.SearchEntry()
        search.props.placeholder_text = "Filter by name, path or branch"
        search.add_css_class("filter")
        search.connect("search-changed", self._on_filter)
        header.append(search)

        root.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.grid = Gtk.FlowBox()
        self.grid.set_valign(Gtk.Align.START)
        self.grid.set_max_children_per_line(3)
        self.grid.set_min_children_per_line(1)
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_row_spacing(12)
        self.grid.set_column_spacing(12)
        self.grid.add_css_class("grid")
        scroll.set_child(self.grid)

        root.append(scroll)

        self.footer = Gtk.Label(label="", xalign=0)
        self.footer.add_css_class("footer")
        root.append(self.footer)

    def _stat(self, value, label, accent):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.add_css_class("stat")
        box.add_css_class(f"stat-{accent}")

        big = Gtk.Label(label=value, xalign=0)
        big.add_css_class("stat-value")
        box.append(big)

        small = Gtk.Label(label=label, xalign=0)
        small.add_css_class("stat-label")
        box.append(small)

        return box

    # ---------------------------------------------------------------- render

    def _render(self):
        child = self.grid.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt

        shown = self._visible()

        for project in shown:
            self.grid.append(self._card(project))

        self.footer.set_text(
            f"{len(shown)} of {len(self.projects)} projects · sorted by last commit"
        )

    def _card(self, project):
        card = Gtk.Button()
        card.add_css_class("card")
        card.add_css_class(f"band-{band(project['at'])}")
        if project["active"]:
            card.add_css_class("active")
        card.connect("clicked", lambda _b, p=project: self._activate(p))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        name = Gtk.Label(label=project["name"], xalign=0)
        name.add_css_class("card-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_hexpand(True)
        top.append(name)

        if project["active"]:
            here = Gtk.Label(label="ACTIVE")
            here.add_css_class("chip-active")
            top.append(here)

        box.append(top)

        path = Gtk.Label(label=project["path"].replace(str(Path.home()), "~"),
                         xalign=0)
        path.add_css_class("card-path")
        path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        box.append(path)

        subject = Gtk.Label(label=project["subject"] or "—", xalign=0)
        subject.add_css_class("card-subject")
        subject.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(subject)

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        branch = Gtk.Label(label=project["branch"])
        branch.add_css_class("chip")
        branch.set_ellipsize(Pango.EllipsizeMode.END)
        meta.append(branch)

        if project["dirty"]:
            dirty = Gtk.Label(label=f"{project['dirty']} changed")
            dirty.add_css_class("chip-dirty")
            meta.append(dirty)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        meta.append(spacer)

        when = Gtk.Label(label=relative(project["at"]))
        when.add_css_class("card-when")
        meta.append(when)

        box.append(meta)
        card.set_child(box)
        return card

    # --------------------------------------------------------------- actions

    def _on_filter(self, entry):
        self.query = entry.get_text().strip()
        self._render()

    def _activate(self, project):
        """Make it the active project, then open it."""
        try:
            subprocess.Popen(
                [str(REPO / "scripts/project-cli.py"), "switch", project["id"]],
                cwd=str(REPO), start_new_session=True,
            )
        except Exception:
            pass

        try:
            Gio.AppInfo.launch_default_for_uri(
                Path(project["path"]).as_uri(), None
            )
        except Exception:
            pass

        self.close()


class ProjectsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = Projects(self)
        window.present()


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    ProjectsApp().run()
