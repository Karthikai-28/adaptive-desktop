#!/usr/bin/env python3
"""Project mode - every repository on the machine, in one view.

Reads the registry written by scripts/project-scan.py, so no git commands run
while the window is open: the scan already recorded branch, dirty count and
last commit for each project.

Ordering is by last commit, most recent first, which is the order that answers
"what am I working on" without being told.
"""

import json
import re
import subprocess
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "com.karthi.AdaptiveProjects"
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REGISTRY = Path.home() / ".config/adaptive-desktop/projects.json"

# Notes live outside the repositories they describe, so reading a project
# never leaves anything behind to commit.
NOTES_DIR = Path.home() / ".local/share/adaptive-desktop/notes"

# Accent per recency band, so the grid reads as a heat map of attention.
FRESH_D, WARM_D, COOL_D = 3, 30, 180


def git(repo, *args, timeout=8):
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""


def _human_size(value):
    for unit in ("B", "K", "M", "G"):
        if value < 1024 or unit == "G":
            return f"{value:.0f}{unit}" if unit != "B" else f"{value}B"
        value /= 1024
    return f"{value:.0f}G"


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
        self.set_default_size(1360, 900)
        self.add_css_class("adaptive-projects")

        self.projects = self._load()
        self.query = ""
        self.doc_scale = 13
        self._doc_css = Gtk.CssProvider()
        self._notes_save_id = 0
        self._doc_current = None

        self._load_css()

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, self._doc_css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._apply_doc_scale()

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
                "favorite": entry.get("metadata", {}).get("favorite", False),
            })

        items.sort(key=lambda p: (not p["favorite"], -p["at"]))
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
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        card.add_css_class(f"band-{band(project['at'])}")
        if project["active"]:
            card.add_css_class("active")
        
        click = Gtk.GestureClick.new()
        click.connect("released", lambda g, n, x, y, p=project: self._activate(p))
        card.add_controller(click)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        name = Gtk.Label(label=project["name"], xalign=0)
        name.add_css_class("card-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_hexpand(True)
        top.append(name)

        fav_btn = Gtk.Button(label="★" if project["favorite"] else "✩")
        fav_btn.add_css_class("flat") # Use transparent style if available, or just a small button
        # To avoid the button looking weird, we could use an icon or remove border.
        fav_btn.connect("clicked", lambda b, p=project: self._toggle_favorite_from_grid(p, b))
        top.append(fav_btn)

        if project["active"]:
            here = Gtk.Label(label="ACTIVE")
            here.add_css_class("chip-active")
            top.append(here)

        card.append(top)

        path = Gtk.Label(label=project["path"].replace(str(Path.home()), "~"),
                         xalign=0)
        path.add_css_class("card-path")
        path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        card.append(path)

        subject = Gtk.Label(label=project["subject"] or "—", xalign=0)
        subject.add_css_class("card-subject")
        subject.set_ellipsize(Pango.EllipsizeMode.END)
        card.append(subject)

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

        card.append(meta)
        return card

    def _toggle_favorite(self, project, button):
        is_fav = not project.get("favorite", False)
        project["favorite"] = is_fav
        patch = json.dumps({"metadata": {"favorite": is_fav}})
        try:
            subprocess.run([
                "gdbus", "call", "--session",
                "--dest", "org.adaptive.ProjectContext",
                "--object-path", "/org/adaptive/ProjectContext",
                "--method", "org.adaptive.ProjectContext.UpdateProject",
                project["id"], patch
            ], timeout=2)
        except Exception:
            pass
        
        button.set_label("★ Unstar" if is_fav else "✩ Star")
        
        # Resort and re-render the grid
        self.projects.sort(key=lambda p: (not p["favorite"], -p["at"]))
        self._render()

    def _toggle_favorite_from_grid(self, project, button):
        is_fav = not project.get("favorite", False)
        project["favorite"] = is_fav
        patch = json.dumps({"metadata": {"favorite": is_fav}})
        try:
            subprocess.run([
                "gdbus", "call", "--session",
                "--dest", "org.adaptive.ProjectContext",
                "--object-path", "/org/adaptive/ProjectContext",
                "--method", "org.adaptive.ProjectContext.UpdateProject",
                project["id"], patch
            ], timeout=2)
        except Exception:
            pass
        
        # We don't strictly need to set_label since _render recreates the grid,
        # but doing it anyway for completeness
        button.set_label("★" if is_fav else "✩")
        
        self.projects.sort(key=lambda p: (not p["favorite"], -p["at"]))
        self._render()

    # --------------------------------------------------------------- analysis

    def _analyze(self, path):
        """Where change concentrates, what moves together, and what to read
        first. All of it derived from history rather than guessed at."""
        raw = git(path, "log", "--no-merges", "--format=\x01%an",
                  "--name-only", "-n", "800", timeout=25)

        churn, owners, pairs = {}, {}, {}

        for block in raw.split("\x01"):
            lines = [l for l in block.splitlines() if l.strip()]
            if not lines:
                continue

            author, files = lines[0], lines[1:]

            for f in files:
                churn[f] = churn.get(f, 0) + 1
                owners.setdefault(f, {})
                owners[f][author] = owners[f].get(author, 0) + 1

            # Files touched in the same commit tend to be coupled. Huge
            # commits say nothing about coupling, so they are skipped.
            if 1 < len(files) <= 12:
                for i, a in enumerate(files):
                    for b in files[i + 1:]:
                        key = (a, b) if a < b else (b, a)
                        pairs[key] = pairs.get(key, 0) + 1

        tracked = [f for f in git(path, "ls-files").splitlines() if f]

        # Entry points worth reading before anything else.
        interesting = (
            "readme", "contributing", "makefile", "dockerfile", "docker-compose",
            "package.json", "pyproject.toml", "requirements.txt", "cargo.toml",
            "go.mod", "setup.py", "main.py", "main.go", "index.js", "index.ts",
            "app.py", "cli.py", "__main__.py", "meson.build", "cmakelists.txt",
        )
        keys = [f for f in tracked
                if f.rsplit("/", 1)[-1].lower() in interesting or
                f.lower().startswith("readme")]
        keys.sort(key=lambda f: (f.count("/"), len(f)))

        # Cheap signals about how the project is kept.
        tests = [f for f in tracked
                 if "test" in f.lower() or "spec" in f.lower()]
        ci = [f for f in tracked
              if f.startswith(".github/workflows") or "gitlab-ci" in f
              or "jenkinsfile" in f.lower()]
        docs = [f for f in tracked if f.lower().startswith("doc")]

        sizes = []
        for f in tracked:
            try:
                sizes.append((f, (Path(path) / f).stat().st_size))
            except Exception:
                pass
        sizes.sort(key=lambda kv: -kv[1])

        return {
            "churn": sorted(churn.items(), key=lambda kv: -kv[1]),
            "owners": owners,
            "pairs": sorted(pairs.items(), key=lambda kv: -kv[1]),
            "keys": keys[:10],
            "tests": tests,
            "ci": ci,
            "docs": docs,
            "sizes": sizes[:8],
            "tracked": len(tracked),
        }

    def _show_analysis(self, project):
        child = self.detail_holder.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.detail_holder.remove(child)
            child = nxt

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        head.add_css_class("header")

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        back = Gtk.Button(label="\u2190  Project")
        back.add_css_class("back")
        back.connect("clicked", lambda *_: self._show_detail(project))
        bar.append(back)
        head.append(bar)

        title = Gtk.Label(label=f"Understanding {project['name']}", xalign=0)
        title.add_css_class("greeting")
        head.append(title)

        note = Gtk.Label(
            label="Read from the last 800 commits and the working tree",
            xalign=0)
        note.add_css_class("greeting-sub")
        head.append(note)

        self.detail_holder.append(head)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.add_css_class("detail-body")

        pending = Gtk.Label(label="Reading history\u2026", xalign=0)
        pending.add_css_class("greeting-sub")
        body.append(pending)

        scroll.set_child(body)
        self.detail_holder.append(scroll)
        self.stack.set_visible_child_name("detail")

        # Let the frame with "Reading history" paint before the git pass.
        GLib.idle_add(self._fill_analysis, project, body, pending)

    def _fill_analysis(self, project, body, pending):
        data = self._analyze(project["path"])
        body.remove(pending)

        body.append(self._section("START HERE"))
        body.append(self._panel(
            "ENTRY POINTS  ·  READ THESE FIRST",
            self._file_list([(f, "") for f in data["keys"]] or
                            [("no obvious entry point", "")])))

        body.append(self._section("WHERE THE CHANGE IS"))
        body.append(self._columns(
            self._panel("HOTSPOTS  ·  MOST-CHANGED FILES",
                        self._hotspots(data["churn"], data["owners"])),
            self._panel("MOVES TOGETHER  ·  CHANGED IN THE SAME COMMIT",
                        self._coupling(data["pairs"])),
        ))

        body.append(self._section("HOW IT IS KEPT"))
        body.append(self._columns(
            self._panel("SIGNALS", self._signals(data)),
            self._panel("LARGEST FILES  ·  WHERE THE WEIGHT IS",
                        self._file_list([
                            (f, _human_size(s)) for f, s in data["sizes"]])),
        ))

        return GLib.SOURCE_REMOVE

    def _file_list(self, rows):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        for name, note in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            label = Gtk.Label(label=name, xalign=0)
            label.add_css_class("commit-subject")
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_hexpand(True)
            row.append(label)

            if note:
                value = Gtk.Label(label=note)
                value.add_css_class("author-count")
                row.append(value)

            box.append(row)

        return box

    def _hotspots(self, churn, owners):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        if not churn:
            return box

        peak = churn[0][1]

        for name, count in churn[:10]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            label = Gtk.Label(label=name, xalign=0)
            label.add_css_class("author")
            label.set_size_request(230, -1)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            row.append(label)

            meter = Gtk.DrawingArea()
            meter.set_content_height(13)
            meter.set_hexpand(True)

            # Many hands on one hot file is the interesting case, so the bar
            # warms as the number of authors climbs.
            hands = len(owners.get(name, {}))

            def draw(_a, cr, width, height, share=count / peak, hands=hands):
                cr.set_source_rgba(1, 1, 1, 0.06)
                cr.rectangle(0, 0, width, height)
                cr.fill()
                if hands > 2:
                    cr.set_source_rgba(0.95, 0.79, 0.42, 0.9)
                else:
                    cr.set_source_rgba(0.47, 0.66, 1.0, 0.9)
                cr.rectangle(0, 0, width * share, height)
                cr.fill()

            meter.set_draw_func(draw)
            row.append(meter)

            value = Gtk.Label(
                label=f"{count}\u00d7 · {hands} author" + ("s" if hands != 1 else ""))
            value.add_css_class("author-count")
            row.append(value)

            box.append(row)

        return box

    def _coupling(self, pairs):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        if not pairs:
            no = Gtk.Label(label="no repeated pairings", xalign=0)
            no.add_css_class("commit-when")
            box.append(no)
            return box

        for (a, b), count in pairs[:8]:
            if count < 2:
                break

            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

            top = Gtk.Label(label=a, xalign=0)
            top.add_css_class("commit-subject")
            top.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            row.append(top)

            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            bottom = Gtk.Label(label=f"\u21b3 {b}", xalign=0)
            bottom.add_css_class("commit-when")
            bottom.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            bottom.set_hexpand(True)
            line.append(bottom)

            value = Gtk.Label(label=f"{count}\u00d7")
            value.add_css_class("author-count")
            line.append(value)

            row.append(line)
            box.append(row)

        return box

    def _signals(self, data):
        rows = []

        tests = len(data["tests"])
        share = (100 * tests / data["tracked"]) if data["tracked"] else 0
        rows.append((
            "Tests",
            f"{tests} files · {share:.0f}% of tree" if tests else "none found",
        ))
        rows.append((
            "Continuous integration",
            ", ".join(data["ci"][:2]) if data["ci"] else "none found",
        ))
        rows.append((
            "Documentation",
            f"{len(data['docs'])} files" if data["docs"] else "none found",
        ))
        rows.append(("Tracked files", str(data["tracked"])))

        return self._file_list(rows)

    # ------------------------------------------------------------------ learn

    def _md_escape(self, value):
        return (value.replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))

    def _md_inline(self, body):
        """Inline markdown to Pango markup. Input must already be escaped."""
        body = re.sub(r"`([^`]+)`",
                      r'<tt><span foreground="#0A84FF">\1</span></tt>', body)
        body = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", body)
        body = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", body)
        body = re.sub(r"\[([^\]]+)\]\([^)]*\)",
                      r'<span foreground="#0A84FF" underline="single">\1</span>',
                      body)
        return body

    # One combined pass, so a keyword inside a string is not coloured twice.
    _CODE_TOKENS = re.compile(
        r'(?P<str>"[^"\n]*"|\'[^\'\n]*\')'
        r"|(?P<com>#[^\n]*|//[^\n]*)"
        r"|(?P<num>\b\d+(?:\.\d+)?\b)"
        r"|(?P<kw>\b(?:def|class|return|import|from|if|elif|else|for|while|"
        r"try|except|finally|with|as|lambda|yield|pass|raise|assert|"
        r"function|const|let|var|new|await|async|export|default|"
        r"public|private|protected|static|void|struct|enum|interface|"
        r"true|false|null|None|True|False|self|this|echo|local)\b)"
    )

    def _md_highlight(self, code):
        """Language-agnostic colouring: strings, comments, numbers, keywords -
        enough to make a block readable without a parser per language."""
        def paint(match):
            kind = match.lastgroup
            colour = {"str": "#30D158", "com": "#636366",
                      "num": "#FF9F0A", "kw": "#5E5CE6"}[kind]
            weight = ' weight="bold"' if kind == "kw" else ""
            style = ' style="italic"' if kind == "com" else ""
            return (f'<span foreground="{colour}"{weight}{style}>'
                    f"{match.group()}</span>")

        return self._CODE_TOKENS.sub(paint, self._md_escape(code))

    def _md_blocks(self, text):
        """Split into blocks so each becomes its own widget - one label cannot
        give a code block its own frame or a copy button."""
        blocks, buffer, table = [], [], []
        code, lang = None, ""

        def flush_text():
            if buffer:
                blocks.append(("text", "\n".join(buffer)))
                buffer.clear()

        def flush_table():
            if table:
                blocks.append(("table", list(table)))
                table.clear()

        for line in text.splitlines():
            if code is not None:
                if line.lstrip().startswith("```"):
                    blocks.append(("code", lang, "\n".join(code)))
                    code, lang = None, ""
                else:
                    code.append(line)
                continue

            fence = re.match(r"^\s*```\s*([\w+-]+)?", line)
            if fence:
                flush_text()
                flush_table()
                code, lang = [], fence.group(1) or ""
                continue

            if line.lstrip().startswith("|"):
                flush_text()
                table.append(line)
                continue

            flush_table()

            heading = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading:
                flush_text()
                blocks.append(("head", len(heading.group(1)), heading.group(2)))
                continue

            if re.match(r"^\s*([-*_])\1{2,}\s*$", line):
                flush_text()
                blocks.append(("rule",))
                continue

            buffer.append(line)

        if code is not None:
            blocks.append(("code", lang, "\n".join(code)))

        flush_text()
        flush_table()
        return blocks

    def _md_text_widget(self, raw):
        out = []

        for line in raw.splitlines():
            body = self._md_escape(line)

            quote = re.match(r"^\s*&gt;\s?(.*)$", body)
            bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", body)
            number = re.match(r"^(\s*)(\d+)\.\s+(.*)$", body)

            if quote:
                body = ('<span foreground="#0A84FF">\u2503</span>  '
                        f"<i>{quote.group(1)}</i>")
            elif bullet:
                body = (f"{bullet.group(1)}   "
                        f'<span foreground="#0A84FF">\u2022</span>  '
                        f"{bullet.group(2)}")
            elif number:
                body = (f"{number.group(1)}   "
                        f'<span foreground="#0A84FF">{number.group(2)}.</span>'
                        f"  {number.group(3)}")

            out.append(self._md_inline(body))

        label = Gtk.Label(xalign=0, yalign=0)
        label.add_css_class("doc-body")
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_selectable(True)
        label.set_markup("\n".join(out))
        return label

    def _md_code_widget(self, lang, code):
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        frame.add_css_class("code-block")

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("code-bar")

        name = Gtk.Label(label=(lang or "text").upper(), xalign=0)
        name.add_css_class("code-lang")
        name.set_hexpand(True)
        bar.append(name)

        copy = Gtk.Button(label="Copy")
        copy.add_css_class("code-copy")

        def do_copy(button):
            display = Gdk.Display.get_default()
            if display:
                display.get_clipboard().set(code)

            button.set_label("Copied")

            def restore():
                button.set_label("Copy")
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(1200, restore)

        copy.connect("clicked", do_copy)
        bar.append(copy)
        frame.append(bar)

        body = Gtk.Label(xalign=0, yalign=0)
        body.add_css_class("doc-code")
        body.set_selectable(True)
        body.set_wrap(False)
        body.set_markup(self._md_highlight(code))

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroll.set_child(body)
        frame.append(scroll)
        return frame

    def _md_table_widget(self, lines):
        rows = []
        for line in lines:
            cells = [c.strip().replace("`", "")
                     for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                continue
            rows.append(cells)

        if not rows:
            return Gtk.Box()

        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        sizes = [max(len(r[i]) for r in rows) for i in range(width)]

        out = []
        for index, row in enumerate(rows):
            cells = "  ".join(self._md_escape(cell).ljust(sizes[i] + 2)
                              for i, cell in enumerate(row))
            if index == 0:
                out.append(f"<b>{cells}</b>")
                out.append('<span foreground="#48484A">'
                           + "\u2500" * min(len(cells), 92) + "</span>")
            else:
                out.append(cells)

        label = Gtk.Label(xalign=0, yalign=0)
        label.add_css_class("doc-table")
        label.set_selectable(True)
        label.set_markup("\n".join(out))

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroll.set_child(label)
        return scroll

    def _md_render(self, container, text):
        child = container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            container.remove(child)
            child = nxt

        for block in self._md_blocks(text):
            kind = block[0]

            if kind == "head":
                label = Gtk.Label(label="", xalign=0)
                label.add_css_class(f"doc-h{min(block[1], 3)}")
                label.set_wrap(True)
                label.set_selectable(True)
                label.set_markup(self._md_inline(self._md_escape(block[2])))
                container.append(label)
            elif kind == "code":
                container.append(self._md_code_widget(block[1], block[2]))
            elif kind == "table":
                container.append(self._md_table_widget(block[1]))
            elif kind == "rule":
                rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                rule.add_css_class("doc-rule")
                container.append(rule)
            elif block[1].strip():
                container.append(self._md_text_widget(block[1]))

    def _show_learn(self, project):
        child = self.detail_holder.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.detail_holder.remove(child)
            child = nxt

        root = Path(project["path"])
        docs = [d for d in git(root, "ls-files", "*.md", "*.markdown",
                               "*.MD").splitlines() if d]

        # README first, then docs/, then the rest - reading order, not
        # alphabetical order.
        def rank(name):
            lower = name.lower()
            if lower.startswith("readme"):
                return (0, name)
            if "/" not in name:
                return (1, name)
            if lower.startswith("doc"):
                return (2, name)
            return (3, name)

        docs.sort(key=rank)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        head.add_css_class("header")

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = Gtk.Button(label="\u2190  Project")
        back.add_css_class("back")
        back.connect("clicked", lambda *_: self._show_detail(project))
        bar.append(back)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        for label, step in (("A\u2212", -1), ("A+", 1)):
            zoom = Gtk.Button(label=label)
            zoom.add_css_class("action")
            zoom.connect("clicked", lambda _b, s=step: self._doc_zoom(s))
            bar.append(zoom)

        notes_toggle = Gtk.ToggleButton(label="Notes")
        notes_toggle.add_css_class("action")
        bar.append(notes_toggle)

        head.append(bar)

        title = Gtk.Label(label=f"Learn {project['name']}", xalign=0)
        title.add_css_class("greeting")
        head.append(title)

        count = Gtk.Label(
            label=(f"{len(docs)} documents in this repository"
                   if docs else "no markdown in this repository"),
            xalign=0)
        count.add_css_class("greeting-sub")
        head.append(count)

        self.detail_holder.append(head)

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        split.set_vexpand(True)

        # --- index -------------------------------------------------------
        index_scroll = Gtk.ScrolledWindow()
        index_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        index_scroll.set_size_request(300, -1)
        index_scroll.add_css_class("doc-index")

        index = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        index.add_css_class("doc-index-list")
        index_scroll.set_child(index)
        split.append(index_scroll)

        # --- reader ------------------------------------------------------
        reader_scroll = Gtk.ScrolledWindow()
        reader_scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                                 Gtk.PolicyType.AUTOMATIC)
        reader_scroll.set_hexpand(True)

        reader = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        reader.add_css_class("doc-page")
        reader_scroll.set_child(reader)
        split.append(reader_scroll)

        notes_pane, notes_view, notes_status, notes_where = self._notes_pane()
        split.append(notes_pane)
        notes_toggle.connect(
            "toggled", lambda b: notes_pane.set_visible(b.get_active()))

        self.detail_holder.append(split)

        self._doc_buttons = []

        def show(name):
            try:
                text = (root / name).read_text(encoding="utf-8",
                                               errors="replace")
            except Exception as error:
                text = f"Could not read {name}: {error}"

            self._md_render(reader, text)
            reader_scroll.get_vadjustment().set_value(0)
            self._load_notes(project, name, notes_view, notes_status,
                             notes_where)

            for button, doc in self._doc_buttons:
                if doc == name:
                    button.add_css_class("selected")
                else:
                    button.remove_css_class("selected")

        for name in docs:
            button = Gtk.Button()
            button.add_css_class("doc-entry")
            button.connect("clicked", lambda _b, n=name: show(n))

            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

            leaf = Gtk.Label(label=name.rsplit("/", 1)[-1], xalign=0)
            leaf.add_css_class("doc-name")
            leaf.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            row.append(leaf)

            if "/" in name:
                where = Gtk.Label(label=name.rsplit("/", 1)[0], xalign=0)
                where.add_css_class("doc-path")
                where.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                row.append(where)

            button.set_child(row)
            index.append(button)
            self._doc_buttons.append((button, name))

        if docs:
            show(docs[0])
        else:
            empty = Gtk.Label(label="Nothing to read here yet.", xalign=0)
            empty.add_css_class("doc-body")
            reader.append(empty)

        notes_view.get_buffer().connect(
            "changed",
            lambda *_: self._queue_notes_save(project, notes_view,
                                              notes_status))

        self.stack.set_visible_child_name("detail")


    # ------------------------------------------------------------------ notes

    def _notes_pane(self):
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pane.add_css_class("notes-pane")
        pane.set_size_request(340, -1)
        pane.set_visible(False)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        title = Gtk.Label(label="YOUR NOTES", xalign=0)
        title.add_css_class("panel-title")
        title.set_hexpand(True)
        head.append(title)

        status = Gtk.Label(label="")
        status.add_css_class("notes-status")
        head.append(status)
        pane.append(head)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        view = Gtk.TextView()
        view.add_css_class("notes-view")
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_top_margin(10)
        view.set_bottom_margin(10)
        view.set_left_margin(12)
        view.set_right_margin(12)
        scroll.set_child(view)
        pane.append(scroll)

        where = Gtk.Label(label="", xalign=0)
        where.add_css_class("notes-path")
        where.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        pane.append(where)

        return pane, view, status, where

    def _notes_path(self, project, doc):
        safe_project = re.sub(r"[^\w.-]", "_", project["name"])
        # Strip the document's own extension before adding ours, or notes for
        # README.md land in README.md.md.
        stem = re.sub(r"\.(md|markdown|MD)$", "", doc)
        safe_doc = re.sub(r"[^\w.-]", "_", stem)
        return NOTES_DIR / safe_project / f"{safe_doc}.md"

    def _load_notes(self, project, doc, view, status, where):
        self._doc_current = (project, doc)
        target = self._notes_path(project, doc)

        existing = ""
        if target.exists():
            try:
                existing = target.read_text(encoding="utf-8")
            except Exception:
                pass

        self._notes_loading = True
        view.get_buffer().set_text(existing)
        self._notes_loading = False

        status.set_text("saved" if existing else "")
        where.set_text(str(target).replace(str(Path.home()), "~"))

    def _queue_notes_save(self, project, view, status):
        if getattr(self, "_notes_loading", False):
            return

        if self._notes_save_id:
            GLib.source_remove(self._notes_save_id)

        # Debounced: writing on every keystroke would hit the disk constantly.
        self._notes_save_id = GLib.timeout_add(
            700, self._save_notes, view, status)

    def _save_notes(self, view, status):
        self._notes_save_id = 0

        if not self._doc_current:
            return GLib.SOURCE_REMOVE

        project, doc = self._doc_current
        buffer = view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(),
                               buffer.get_end_iter(), False)

        target = self._notes_path(project, doc)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            status.set_text("saved " + time.strftime("%H:%M:%S"))
        except Exception as error:
            status.set_text(f"not saved: {error}")

        return GLib.SOURCE_REMOVE

    def _doc_zoom(self, direction):
        self.doc_scale = max(9, min(26, self.doc_scale + direction))
        self._apply_doc_scale()

    def _apply_doc_scale(self):
        size = self.doc_scale
        self._doc_css.load_from_data(f"""
        .doc-body {{ font-size: {size}px; }}
        .doc-code, .doc-table {{ font-size: {max(9, size - 1)}px; }}
        .doc-h1 {{ font-size: {size + 12}px; }}
        .doc-h2 {{ font-size: {size + 6}px; }}
        .doc-h3 {{ font-size: {size + 2}px; }}
        .notes-view {{ font-size: {size}px; }}
        """.encode())

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
        local_branches = [b for b in git(path, "branch", "--format=%(refname:short)").splitlines() if b]
        remote_branches = [b for b in git(path, "branch", "-r", "--format=%(refname:short)").splitlines() 
                           if b and not b.endswith("/HEAD")]
        current_branch = git(path, "branch", "--show-current").strip()
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

        # Top-level structure: where the code actually lives.
        dirs = {}
        for f in files:
            head = f.split("/", 1)[0] if "/" in f else "(root)"
            dirs[head] = dirs.get(head, 0) + 1

        # When the work happens: weekday x hour.
        punch = {}
        for stamp, _, _ in commits:
            local = time.localtime(stamp)
            punch[(local.tm_wday, local.tm_hour)] = punch.get(
                (local.tm_wday, local.tm_hour), 0) + 1

        # Streaks, measured in days that carry at least one commit.
        day_set = {int(s // 86400) for s, _, _ in commits}
        best = run = 0
        if day_set:
            for day in range(min(day_set), max(day_set) + 1):
                run = run + 1 if day in day_set else 0
                best = max(best, run)

        ahead = behind = 0
        counts = git(path, "rev-list", "--left-right", "--count",
                     "HEAD...@{u}").strip()
        if counts and "\t" in counts:
            try:
                ahead, behind = (int(x) for x in counts.split("\t")[:2])
            except ValueError:
                pass

        size = ""
        try:
            out = subprocess.run(["du", "-sh", str(path)], capture_output=True,
                                 text=True, timeout=10).stdout
            size = out.split("\t")[0].strip()
        except Exception:
            pass

        return {
            "commits": commits,
            "files": files,
            "local_branches": local_branches,
            "remote_branches": remote_branches,
            "current_branch": current_branch,
            "branches": local_branches + remote_branches,
            "status": status,
            "exts": sorted(exts.items(), key=lambda kv: -kv[1]),
            "authors": sorted(authors.items(), key=lambda kv: -kv[1]),
            "dirs": sorted(dirs.items(), key=lambda kv: -kv[1]),
            "punch": punch,
            "streak": best,
            "active_days": len(day_set),
            "ahead": ahead,
            "behind": behind,
            "size": size,
        }
    def _branches_list(self, project, branches, current_branch, is_remote):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        if not branches:
            empty = Gtk.Label(label="No branches found", xalign=0)
            empty.add_css_class("commit-when")
            box.append(empty)
            return box

        for branch in branches:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            name = Gtk.Label(label=branch, xalign=0)
            name.add_css_class("commit-subject")
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name.set_hexpand(True)
            row.append(name)

            if not is_remote and branch == current_branch:
                active = Gtk.Label(label="ACTIVE")
                active.add_css_class("chip-active")
                row.append(active)
            else:
                button = Gtk.Button(label="Switch")
                button.add_css_class("action")
                button.connect("clicked", lambda _b, b=branch, r=is_remote: self._switch_branch(project, b, r))
                row.append(button)

            box.append(row)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(250)
        scroll.set_child(box)

        return scroll

    def _switch_branch(self, project, branch, is_remote):
        path = project["path"]
        if is_remote and "/" in branch:
            local_name = branch.split('/', 1)[1]
            git(path, "checkout", local_name)
            if git(path, "branch", "--show-current").strip() != local_name:
                git(path, "checkout", branch)
        else:
            git(path, "checkout", branch)
            
        self._show_detail(project)

    def _working_tree(self, project, status_lines):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        if not status_lines:
            empty = Gtk.Label(label="Clean working tree", xalign=0)
            empty.add_css_class("commit-when")
            box.append(empty)
            return box

        for line in status_lines:
            if len(line) <= 3:
                continue
            state = line[:2]
            filepath = line[3:].strip('"')

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            badge = Gtk.Label(label=state)
            badge.add_css_class("chip-dirty")
            row.append(badge)

            name = Gtk.Label(label=filepath, xalign=0)
            name.add_css_class("commit-subject")
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name.set_hexpand(True)
            row.append(name)

            abs_path = str(Path(project["path"]) / filepath)

            def make_icon_btn(icon_source, tooltip, is_path=False):
                btn = Gtk.Button()
                icon = Gtk.Image.new_from_file(icon_source) if is_path else Gtk.Image.new_from_icon_name(icon_source)
                icon.set_pixel_size(16)
                btn.set_child(icon)
                btn.set_tooltip_text(tooltip)
                btn.add_css_class("action")
                return btn

            btn_ag = make_icon_btn("antigravity", "Open in Antigravity")
            btn_ag.connect("clicked", lambda _b, p=abs_path: subprocess.Popen(["antigravity", p]))
            row.append(btn_ag)

            btn_code = make_icon_btn("/snap/code/current/meta/gui/vscode.png", "Open in VS Code", True)
            btn_code.connect("clicked", lambda _b, p=abs_path: subprocess.Popen(["code", p]))
            row.append(btn_code)

            btn_file = make_icon_btn("system-file-manager-symbolic", "Show in Explorer")
            btn_file.connect("clicked", lambda _b, p=abs_path: subprocess.Popen(["nautilus", "--select", p]))
            row.append(btn_file)

            box.append(row)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(350)
        scroll.set_child(box)

        return scroll

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
            ("Analyze", lambda *_: self._show_analysis(project)),
            ("Learn", lambda *_: self._show_learn(project)),
            ("Set active", lambda *_: self._set_active(project)),
        ):
            button = Gtk.Button(label=label)
            button.add_css_class("action")
            button.connect("clicked", handler)
            bar.append(button)

        def make_head_btn(icon_source, tooltip, handler, is_path=False):
            btn = Gtk.Button()
            icon = Gtk.Image.new_from_file(icon_source) if is_path else Gtk.Image.new_from_icon_name(icon_source)
            icon.set_pixel_size(16)
            btn.set_child(icon)
            btn.set_tooltip_text(tooltip)
            btn.add_css_class("action")
            btn.connect("clicked", handler)
            return btn

        # Favorite Toggle Button
        fav_label = "★ Unstar" if project["favorite"] else "✩ Star"
        fav_toggle = Gtk.Button(label=fav_label)
        fav_toggle.add_css_class("action")
        fav_toggle.connect("clicked", lambda b, p=project: self._toggle_favorite(p, b))
        bar.append(fav_toggle)

        bar.append(make_head_btn("antigravity", "Open in Antigravity", lambda *_: self._open_antigravity(project)))
        bar.append(make_head_btn("/snap/code/current/meta/gui/vscode.png", "Open in VS Code", lambda *_: self._open_vscode(project), True))
        bar.append(make_head_btn("system-file-manager-symbolic", "Open in Files", lambda *_: self._open_files(project)))
        bar.append(make_head_btn("utilities-terminal-symbolic", "Terminal here", lambda *_: self._open_terminal(project)))

        head.append(bar)

        name = Gtk.Label(label=project["name"], xalign=0)
        name.add_css_class("greeting")
        head.append(name)

        where = Gtk.Label(
            label=project["path"].replace(str(Path.home()), "~"), xalign=0)
        where.add_css_class("greeting-sub")
        head.append(where)

        stats = Gtk.FlowBox()
        stats.set_selection_mode(Gtk.SelectionMode.NONE)
        stats.set_max_children_per_line(6)
        stats.set_min_children_per_line(2)
        stats.set_row_spacing(8)
        stats.set_column_spacing(8)
        stats.set_homogeneous(True)
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
            (str(data["active_days"]), "ACTIVE DAYS", "violet"),
            (f'{data["streak"]}d', "LONGEST STREAK", "accent"),
            (data["size"] or "-", "ON DISK", "cyan"),
            (f'+{data["ahead"]}/-{data["behind"]}', "VS ORIGIN", "warning"),
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

        body.append(self._section("WORKING TREE"))
        body.append(self._panel("UNCOMMITTED CHANGES", self._working_tree(project, data["status"])))

        body.append(self._section("BRANCHES"))
        body.append(self._columns(
            self._panel("LOCAL BRANCHES", self._branches_list(project, data["local_branches"], data["current_branch"], is_remote=False)),
            self._panel("REMOTE BRANCHES", self._branches_list(project, data["remote_branches"], data["current_branch"], is_remote=True)),
        ))

        # Time series get the full width - they are read left to right across
        # 26 weeks or 24 hours. Everything else pairs up into two columns.
        body.append(self._section("ACTIVITY"))
        body.append(self._panel("COMMIT ACTIVITY  ·  LAST 26 WEEKS",
                                self._heatmap(data["commits"])))
        body.append(self._panel("COMMITS PER WEEK  ·  LAST 26 WEEKS",
                                self._trend(data["commits"])))
        body.append(self._panel("WHEN THE WORK HAPPENS  ·  WEEKDAY BY HOUR",
                                self._punchcard(data["punch"])))

        body.append(self._section("COMPOSITION"))
        body.append(self._columns(
            self._panel("WHAT IT IS MADE OF",
                        self._languages(data["exts"], len(data["files"]))),
            self._panel("WHERE THE CODE LIVES",
                        self._treemap(data["dirs"], len(data["files"]))),
        ))

        body.append(self._section("PEOPLE & HISTORY"))
        body.append(self._columns(
            self._panel("WHO WORKS ON IT", self._authors(data["authors"])),
            self._panel("RECENT HISTORY", self._history(data["commits"])),
        ))

        scroll.set_child(body)
        self.detail_holder.append(scroll)

        self.stack.set_visible_child_name("detail")

    def _section(self, title):
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("section-title")
        return label

    def _columns(self, left, right):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.set_homogeneous(True)
        left.set_hexpand(True)
        right.set_hexpand(True)
        row.append(left)
        row.append(right)
        return row

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
        area.set_content_height(150)

        def draw(_a, cr, width, _h, *_):
            cell, gap = 17, 4
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

    def _trend(self, commits):
        """Commits per week. The shape says whether a project is accelerating,
        steady, or was finished months ago."""
        weeks = 26
        now = time.time()
        buckets = [0] * weeks

        for stamp, _, _ in commits:
            index = int((now - stamp) // (7 * 86400))
            if 0 <= index < weeks:
                buckets[weeks - 1 - index] += 1

        peak = max(buckets) or 1

        area = Gtk.DrawingArea()
        area.set_content_height(140)

        def draw(_a, cr, width, height, *_):
            step = width / max(weeks - 1, 1)
            pad = 10

            cr.set_line_width(1)
            for i in range(1, 4):
                y = pad + (height - 2 * pad) * i / 4
                cr.set_source_rgba(1, 1, 1, 0.05)
                cr.move_to(0, y)
                cr.line_to(width, y)
                cr.stroke()

            def point(i):
                y = pad + (height - 2 * pad) * (1 - buckets[i] / peak)
                return i * step, y

            cr.move_to(0, height)
            for i in range(weeks):
                cr.line_to(*point(i))
            cr.line_to(width, height)
            cr.close_path()
            cr.set_source_rgba(0.47, 0.66, 1.0, 0.16)
            cr.fill()

            cr.set_line_width(2)
            cr.set_source_rgb(0.47, 0.66, 1.0)
            cr.move_to(*point(0))
            for i in range(1, weeks):
                cr.line_to(*point(i))
            cr.stroke()

            x, y = point(weeks - 1)
            cr.set_source_rgb(0.40, 0.88, 1.0)
            cr.arc(x, y, 3.5, 0, 2 * 3.14159)
            cr.fill()

        area.set_draw_func(draw)
        return area

    def _punchcard(self, punch):
        """Weekday against hour. Shows the rhythm a project is worked to -
        weeknights, weekends, or office hours."""
        peak = max(punch.values(), default=1)

        area = Gtk.DrawingArea()
        area.set_content_height(190)

        def draw(_a, cr, width, height, *_):
            left, top = 44, 10
            cell_w = (width - left - 8) / 24
            cell_h = (height - top - 16) / 7

            cr.select_font_face("Ubuntu")
            cr.set_font_size(10)

            for day in range(7):
                cr.set_source_rgba(1, 1, 1, 0.42)
                cr.move_to(2, top + day * cell_h + cell_h / 2 + 3)
                cr.show_text(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day])

                for hour in range(24):
                    count = punch.get((day, hour), 0)
                    if not count:
                        continue

                    share = count / peak
                    radius = max(1.5, (min(cell_w, cell_h) / 2 - 1) * (0.35 + 0.65 * share))
                    cx = left + hour * cell_w + cell_w / 2
                    cy = top + day * cell_h + cell_h / 2

                    cr.set_source_rgba(0.40, 0.88, 1.0, 0.35 + 0.65 * share)
                    cr.arc(cx, cy, radius, 0, 2 * 3.14159)
                    cr.fill()

            cr.set_source_rgba(1, 1, 1, 0.34)
            for hour in (0, 6, 12, 18, 23):
                cr.move_to(left + hour * cell_w, height - 4)
                cr.show_text(f"{hour:02d}")

        area.set_draw_func(draw)
        return area

    def _treemap(self, dirs, total):
        """Top-level directories by tracked file count, biggest first."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        if not total or not dirs:
            return box

        top = dirs[:8]
        peak = top[0][1]

        for name, count in top:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            label = Gtk.Label(label=name, xalign=0)
            label.add_css_class("author")
            label.set_size_request(160, -1)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            row.append(label)

            meter = Gtk.DrawingArea()
            meter.set_content_height(16)
            meter.set_hexpand(True)

            def draw(_a, cr, width, height, share=count / peak):
                cr.set_source_rgba(1, 1, 1, 0.06)
                cr.rectangle(0, 0, width, height)
                cr.fill()
                cr.set_source_rgba(0.60, 0.55, 1.0, 0.85)
                cr.rectangle(0, 0, width * share, height)
                cr.fill()

            meter.set_draw_func(draw)
            row.append(meter)

            value = Gtk.Label(label=f"{count}  ·  {100 * count / total:.0f}%")
            value.add_css_class("author-count")
            row.append(value)

            box.append(row)

        return box

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
        bar.set_content_height(26)

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
            meter.set_content_height(14)
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

    def _open_antigravity(self, project):
        try:
            subprocess.Popen(["antigravity", project["path"]], start_new_session=True)
        except Exception:
            pass

    def _open_vscode(self, project):
        try:
            subprocess.Popen(["code", project["path"]], start_new_session=True)
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
