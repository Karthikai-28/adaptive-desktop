#!/usr/bin/env python3
"""Start the real Files (the Nautilus fork) with the inspector and browse.

The inspector (extension/adaptive_preview.py and extension/adaptive_files/)
only runs inside Nautilus, so nothing else can check it. This starts the fork
on a virtual display with a throwaway HOME and its own session bus, loading
the inspector from the repository rather than the installed copy, opens a
folder holding one of each kind of file it previews, walks the selection
through all of them with the keyboard, and then reads the inspector's own
log: any traceback fails the check.

    scripts/verify-files-inspector.py

Skips if the fork is not built (scripts/build-nautilus-fork.sh).
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PREFIX = REPO / ".local" / "adaptive-nautilus"
sys.path.insert(0, str(REPO / "scripts"))
import sandbox_display  # noqa: E402


def make_tree(root):
    """One of everything the inspector has a preview for."""
    import cairo
    root.mkdir(parents=True)
    (root / "notes.txt").write_text("plain text\n" * 20)
    (root / "script.py").write_text("def main():\n    return 1\n")
    (root / "data.json").write_text('{"a": [1, 2, 3]}\n')
    (root / "table.csv").write_text("a,b\n1,2\n3,4\n")
    (root / "page.md").write_text("# Title\n\nSome *markdown*.\n")
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 48)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.2, 0.5, 0.9)
    ctx.paint()
    surface.write_to_png(str(root / "picture.png"))
    shutil.make_archive(str(root / "bundle"), "zip", root_dir=str(root), base_dir="notes.txt")
    (root / "empty.bin").write_bytes(b"\x00" * 512)
    (root / "subfolder").mkdir()
    (root / "subfolder" / "inside.txt").write_text("x")
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    (repo / "tracked.txt").write_text("x")


def inner(sandbox, check):
    home = Path.home()
    tree = home / "browse"
    make_tree(tree)

    # The inspector from the repository, where nautilus-python looks for a
    # user's own extensions. The fork's share folder is left out of
    # XDG_DATA_DIRS so the installed copy is not loaded a second time.
    extensions = home / ".local/share/nautilus-python/extensions"
    extensions.mkdir(parents=True)
    shutil.copy(REPO / "extension/adaptive_preview.py", extensions)
    shutil.copytree(REPO / "extension/adaptive_files", extensions / "adaptive_files",
                    ignore=shutil.ignore_patterns("__pycache__"))

    env = dict(os.environ)
    env.update({
        "PATH": f"{PREFIX}/bin:{env['PATH']}",
        "LD_LIBRARY_PATH": f"{PREFIX}/lib/x86_64-linux-gnu:{PREFIX}/lib:{env.get('LD_LIBRARY_PATH', '')}",
        "XDG_DATA_DIRS": "/usr/local/share:/usr/share",
        "GSETTINGS_SCHEMA_DIR": f"{PREFIX}/share/glib-2.0/schemas",
        "ADAPTIVE_FILES_PREFIX": str(PREFIX),
        "ADAPTIVE_FILES_PREVIEW_CSS": str(REPO / "extension/preview.css"),
        "GDK_BACKEND": "x11",
        "GTK_THEME": "Adwaita:dark",
    })
    typelibs = PREFIX / "lib/x86_64-linux-gnu/girepository-1.0"
    if typelibs.is_dir():
        env["GI_TYPELIB_PATH"] = f"{typelibs}:{env.get('GI_TYPELIB_PATH', '')}"

    # The Project Context Service on this private bus, with the browsed
    # folder's repository as the active project, so the inspector's project
    # section has a real service to read.
    service = subprocess.Popen([sys.executable, str(REPO / "services/project-context/main.py")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def project(method, *args):
        return subprocess.run(
            ["gdbus", "call", "--session", "-d", "org.adaptive.ProjectContext",
             "-o", "/org/adaptive/ProjectContext", "-m", f"org.adaptive.ProjectContext.{method}", *args],
            capture_output=True, text=True).stdout.strip()

    for _ in range(50):
        if project("ListProjects"):
            break
        time.sleep(0.1)
    project("SetActiveProject", project("AddProject", str(tree / "repo"), "Repo").strip("(),'"))

    # Wide enough for the inspector, which hides itself in a narrow window.
    # Set as Files' own remembered size: with no window manager on the
    # virtual display, nothing else gets to resize it.
    subprocess.run(["gsettings", "set", "org.gnome.nautilus.window-state", "initial-size", "(1260, 860)"],
                   env=env, check=False, capture_output=True)

    log = home / ".cache/adaptive-files/preview-extension.log"
    output = open(sandbox / "nautilus.log", "w")
    nautilus = subprocess.Popen([str(PREFIX / "bin/nautilus"), "--new-window", str(tree)],
                                env=env, stdout=output, stderr=subprocess.STDOUT)

    def xdo(*args):
        return subprocess.run(["xdotool", *args], capture_output=True, text=True).stdout.strip()

    def area(candidate):
        import re
        match = re.search(r"Geometry: (\d+)x(\d+)", xdo("getwindowgeometry", candidate))
        return int(match.group(1)) * int(match.group(2)) if match else 0

    def files_window():
        """The Files window: of its class, the largest (the others are the
        tiny helper windows every GTK app keeps)."""
        candidates = [(area(c), c) for c in xdo("search", "--class", "Nautilus").split()]
        candidates = [c for c in candidates if c[0] > 10000]
        return max(candidates)[1] if candidates else ""

    window = ""
    for _ in range(120):
        window = files_window()
        if window:
            break
        time.sleep(0.25)
    check(bool(window), "Files opens a window")
    if not window:
        nautilus.kill()
        print(Path(sandbox / "nautilus.log").read_text()[-1500:])
        return

    time.sleep(3)
    check(log.exists(), "the inspector loaded (it started its log)")

    # There is no window manager here, so the window is placed and focused
    # directly, and input goes in as real pointer and key events.
    xdo("windowmove", window, "0", "0")
    xdo("windowfocus", "--sync", window)
    time.sleep(2)
    size = xdo("getwindowgeometry", window)
    check("1270x" in size or "1260x" in size, f"the window is wide enough to show the inspector ({size.splitlines()[-1].strip()})")

    # Walk the selection across every entry, so each kind of preview is
    # built: text, code, JSON, CSV, Markdown, an image, an archive, a binary,
    # a folder and a git repository. Click the first icon, then arrow along.
    xdo("mousemove", "300", "110", "click", "1")
    time.sleep(1.0)
    entries = len(list(tree.iterdir()))
    for _ in range(entries):
        xdo("key", "Right")
        time.sleep(0.7)
    if os.environ.get("ADAPTIVE_FILES_SCREENSHOT"):
        subprocess.run(["import", "-window", "root", os.environ["ADAPTIVE_FILES_SCREENSHOT"]], check=False)
    xdo("key", "ctrl+a")
    time.sleep(1.0)
    xdo("key", "Escape")
    time.sleep(0.5)
    # Into the repository folder and back out: the folder summary and the
    # project section.
    xdo("mousemove", "300", "110", "click", "--repeat", "2", "--delay", "120", "1")
    time.sleep(2.0)
    xdo("key", "alt+Up")
    time.sleep(1.5)

    check(nautilus.poll() is None, "Files is still running after browsing")
    text = log.read_text(errors="replace") if log.exists() else ""
    # A dead inspector logs no exceptions either; these lines only appear
    # when it attached itself and built each preview.
    check("Inspector packed beside" in text, "the inspector attached itself inside the window")
    built = [name for name in ("data.json", "page.md", "script.py", "table.csv") if f"language: {name}" in text]
    check(len(built) == 4, f"a source preview was built for each text file ({', '.join(built)})")
    check("thumbnail" in text.lower(), "the picture's preview went through the thumbnailer")
    check(f"{tree}/repo" in text, "opening a folder reached the inspector")
    tracebacks = text.count("Traceback (most recent call last)")
    check(tracebacks == 0, f"the inspector logged no exceptions ({tracebacks})")
    if tracebacks:
        start = text.index("Traceback (most recent call last)")
        print(text[max(0, start - 300):start + 1500])
    native = Path(sandbox / "nautilus.log").read_text(errors="replace")
    python_errors = [line for line in native.splitlines()
                     if "Traceback" in line or "adaptive_preview" in line or "adaptive_files" in line]
    check(not python_errors, f"Nautilus reported no Python errors ({len(python_errors)})")
    for line in python_errors[:8]:
        print("   ", line[:200])

    service.terminate()
    nautilus.terminate()
    try:
        nautilus.wait(timeout=10)
    except subprocess.TimeoutExpired:
        nautilus.kill()
    (sandbox / "inspector.log").write_text(text)


def controller_calls():
    """Every self._method() the controller calls is defined somewhere in it.

    The controller is one class spread over adaptive_preview.py and the
    inspector_*.py mixins. A method moved or renamed in one file and still
    called from another is an AttributeError only when that code runs, so it
    is checked here, across all of them, without starting anything.
    """
    import ast
    import re
    files = [REPO / "extension/adaptive_preview.py"] + sorted((REPO / "extension/adaptive_files").glob("inspector_*.py"))
    classes = {"PreviewController", "HostMixin", "FolderMixin", "FileMixin", "InfoMixin", "WidgetsMixin"}
    defined, called = set(), {}
    for path in files:
        source = path.read_text()
        for node in ast.parse(source).body:
            if isinstance(node, ast.ClassDef) and node.name in classes:
                defined |= {m.name for m in node.body if isinstance(m, ast.FunctionDef)}
                segment = ast.get_source_segment(source, node)
                # A callback stored on the object is called like a method.
                defined |= set(re.findall(r"self\.(_\w+)\s*=(?!=)", segment))
                for name in re.findall(r"self\.(_\w+)\(", segment):
                    called.setdefault(name, path.name)
    missing = sorted(name for name in called if name not in defined)
    for name in missing:
        print(f"FAIL self.{name}() is called in {called[name]} but defined nowhere in the controller")
    if not missing:
        print(f"OK   {len(called)} controller methods called, all defined across {len(files)} files")
    return not missing


def main():
    if not controller_calls():
        return 1
    if not (PREFIX / "bin/nautilus").exists():
        print("SKIP Files inspector: the Nautilus fork is not built")
        return 0
    if not shutil.which("xdotool"):
        print("SKIP Files inspector: xdotool is not installed")
        return 0
    return sandbox_display.run(__file__, inner, "Files inspector", timeout=240)


if __name__ == "__main__":
    sys.exit(main())
