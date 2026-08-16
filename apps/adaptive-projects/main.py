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


def git(repo, *args, timeout=8):
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


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
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(
            Gtk.StackTransitionType.SLIDE_LEFT_RIGHT
        )
        self.stack.set_transition_duration(180)
        self.set_child(self.stack)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        self.stack.add_named(root, "grid")

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

        self.detail_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.detail_holder.add_css_class("root")
        self.stack.add_named(self.detail_holder, "detail")

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
        """Open the project's own view. Files is one action inside it, not the
        thing a click does - a project is more than a folder."""
        self._show_detail(project)

    # ----------------------------------------------------------------- detail

    def _repo_detail(self, path):
        """One pass of git per project, only when its view is opened."""
        log = git(path, "log", "--format=%ct\x1f%an\x1f%s", "-n", "1500")

        commits = []
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3 and parts[0].isdigit():
                commits.append((int(parts[0]), parts[1], parts[2]))

        files = [f for f in git(path, "ls-files").splitlines() if f]
        branches = [b for b in git(path, "branch", "--format=%(refname:short)")
                    .splitlines() if b]
        status = [s for s in git(path, "status", "--porcelain").splitlines() if s]

        exts = {}
        for f in files:
            name = f.rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else "other"
            if len(ext) > 8:
                ext = "other"
            exts[ext] = exts.get(ext, 0) + 1

        authors = {}
        for _, author, _ in commits:
            authors[author] = authors.get(author, 0) + 1

        return {
            "commits": commits,
            "files": files,
            "branches": branches,
            "status": status,
            "exts": sorted(exts.items(), key=lambda kv: -kv[1]),
            "authors": sorted(authors.items(), key=lambda kv: -kv[1]),
        }

    def _show_detail(self, project):
        child = self.detail_holder.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.detail_holder.remove(child)
            child = nxt

        data = self._repo_detail(project["path"])

        # --- header -------------------------------------------------------
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        head.add_css_class("header")

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        back = Gtk.Button(label="\u2190  All projects")
        back.add_css_class("back")
        back.connect("clicked", lambda *_: self.stack.set_visible_child_name("grid"))
        bar.append(back)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        for label, handler in (
            ("Set active", lambda *_: self._set_active(project)),
            ("Open in Files", lambda *_: self._open_files(project)),
            ("Terminal here", lambda *_: self._open_terminal(project)),
        ):
            button = Gtk.Button(label=label)
            button.add_css_class("action")
            button.connect("clicked", handler)
            bar.append(button)

        head.append(bar)

        name = Gtk.Label(label=project["name"], xalign=0)
        name.add_css_class("greeting")
        head.append(name)

        where = Gtk.Label(
            label=project["path"].replace(str(Path.home()), "~"), xalign=0)
        where.add_css_class("greeting-sub")
        head.append(where)

        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        stats.add_css_class("stats")

        first = min((c[0] for c in data["commits"]), default=0)
        age = f"{int((time.time() - first) / 86400)}d" if first else "-"

        for value, label, accent in (
            (str(project["commits"] or len(data["commits"])), "COMMITS", "accent"),
            (str(len(data["files"])), "TRACKED FILES", "cyan"),
            (str(len(data["authors"])), "CONTRIBUTORS", "violet"),
            (str(len(data["branches"])), "BRANCHES", "accent"),
            (str(len(data["status"])), "UNCOMMITTED", "warning"),
            (age, "AGE", "cyan"),
        ):
            stats.append(self._stat(value, label, accent))

        head.append(stats)
        self.detail_holder.append(head)

        # --- body ---------------------------------------------------------
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.add_css_class("detail-body")

        body.append(self._panel("COMMIT ACTIVITY  ·  LAST 26 WEEKS",
                                self._heatmap(data["commits"])))
        body.append(self._panel("WHAT IT IS MADE OF",
                                self._languages(data["exts"], len(data["files"]))))
        body.append(self._panel("WHO WORKS ON IT",
                                self._authors(data["authors"])))
        body.append(self._panel("RECENT HISTORY",
                                self._history(data["commits"])))

        scroll.set_child(body)
        self.detail_holder.append(scroll)

        self.stack.set_visible_child_name("detail")

    def _panel(self, title, content):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("panel")

        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("panel-title")
        box.append(label)
        box.append(content)
        return box

    def _heatmap(self, commits):
        """A year-style contribution grid: 26 weeks across, one column per week.
        Density is what tells you whether a project is alive."""
        days = {}
        for stamp, _, _ in commits:
            days[int(stamp // 86400)] = days.get(int(stamp // 86400), 0) + 1

        today = int(time.time() // 86400)
        peak = max(days.values(), default=1)

        area = Gtk.DrawingArea()
        area.set_content_height(104)

        def draw(_a, cr, width, _h, *_):
            cell, gap = 12, 3
            weeks = 26
            for w in range(weeks):
                for d in range(7):
                    offset = (weeks - 1 - w) * 7 + (6 - d)
                    count = days.get(today - offset, 0)
                    x = w * (cell + gap)
                    y = d * (cell + gap)

                    if count:
                        level = min(1.0, count / max(peak, 1))
                        # cyan -> accent as the day gets busier
                        cr.set_source_rgba(0.40 + 0.07 * level,
                                           0.66 + 0.02 * level,
                                           1.0, 0.22 + 0.78 * level)
                    else:
                        cr.set_source_rgba(1, 1, 1, 0.05)

                    cr.rectangle(x, y, cell, cell)
                    cr.fill()

        area.set_draw_func(draw)
        return area

    def _languages(self, exts, total):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        if not total:
            return box

        palette = [
            (0.47, 0.66, 1.0), (0.40, 0.88, 1.0), (0.60, 0.55, 1.0),
            (0.95, 0.79, 0.42), (0.40, 0.85, 0.71), (1.0, 0.48, 0.56),
        ]
        top = exts[:6]

        bar = Gtk.DrawingArea()
        bar.set_content_height(16)

        def draw(_a, cr, width, height, *_):
            x = 0.0
            for i, (_, count) in enumerate(top):
                share = count / total
                w = share * width
                r, g, b = palette[i % len(palette)]
                cr.set_source_rgb(r, g, b)
                cr.rectangle(x, 0, max(w - 2, 1), height)
                cr.fill()
                x += w

            if x < width:
                cr.set_source_rgba(1, 1, 1, 0.10)
                cr.rectangle(x, 0, width - x, height)
                cr.fill()

        bar.set_draw_func(draw)
        box.append(bar)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for i, (ext, count) in enumerate(top):
            item = Gtk.Label(
                label=f"{ext}  {100 * count / total:.0f}%")
            item.add_css_class("legend")
            item.add_css_class(f"legend-{i}")
            legend.append(item)

        box.append(legend)
        return box

    def _authors(self, authors):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        if not authors:
            return box

        peak = authors[0][1]

        for author, count in authors[:5]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            who = Gtk.Label(label=author, xalign=0)
            who.add_css_class("author")
            who.set_size_request(180, -1)
            who.set_ellipsize(Pango.EllipsizeMode.END)
            row.append(who)

            meter = Gtk.DrawingArea()
            meter.set_content_height(10)
            meter.set_hexpand(True)

            def draw(_a, cr, width, height, share=count / peak):
                cr.set_source_rgba(1, 1, 1, 0.06)
                cr.rectangle(0, 0, width, height)
                cr.fill()
                cr.set_source_rgb(0.47, 0.66, 1.0)
                cr.rectangle(0, 0, width * share, height)
                cr.fill()

            meter.set_draw_func(draw)
            row.append(meter)

            total = Gtk.Label(label=str(count))
            total.add_css_class("author-count")
            row.append(total)

            box.append(row)

        return box

    def _history(self, commits):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        for stamp, author, subject in commits[:12]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            when = Gtk.Label(label=relative(stamp), xalign=0)
            when.add_css_class("commit-when")
            when.set_size_request(78, -1)
            row.append(when)

            what = Gtk.Label(label=subject, xalign=0)
            what.add_css_class("commit-subject")
            what.set_ellipsize(Pango.EllipsizeMode.END)
            what.set_hexpand(True)
            row.append(what)

            who = Gtk.Label(label=author)
            who.add_css_class("commit-author")
            row.append(who)

            box.append(row)

        return box

    # --------------------------------------------------------------- actions

    def _set_active(self, project):
        try:
            subprocess.Popen(
                [str(REPO / "scripts/project-cli.py"), "switch", project["id"]],
                cwd=str(REPO), start_new_session=True,
            )
        except Exception:
            pass

    def _open_files(self, project):
        try:
            Gio.AppInfo.launch_default_for_uri(
                Path(project["path"]).as_uri(), None)
        except Exception:
            pass

    def _open_terminal(self, project):
        try:
            subprocess.Popen(["gnome-terminal", "--working-directory",
                              project["path"]], start_new_session=True)
        except Exception:
            pass


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
