"""Share targets for Files: LocalSend, Slack, Bluetooth, a nearby phone,
Gmail, the mail app, and the clipboard.

Every target starts a program and returns at once. Nothing here blocks the
Files window, and nothing runs in a Python thread (Files' embedded Python
never releases the GIL - see adaptive_preview.py); folders that must become a
zip first are zipped by a Gio.Subprocess whose completion arrives on the main
loop.

Order matters and is fixed: LocalSend and Slack first, the everyday two.
"""

import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

HERE = Path(__file__).resolve().parent
ZIP_DIR = Path(GLib.get_user_cache_dir()) / "adaptive-files" / "share"
# Snap apps (LocalSend) can only read non-hidden paths in Home; anything else
# is copied here first.
SNAP_OUTBOX = Path.home() / "Public" / "Shared"

LOCALSEND = "/snap/bin/localsend"
SLACK_DESKTOP = "slack_slack.desktop"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _env():
    # Files runs with GTK_THEME pinned to Adaptive; other toolkits (LocalSend
    # is Flutter) should draw with their own defaults.
    env = dict(os.environ)
    env.pop("GTK_THEME", None)
    return env


def _spawn(argv):
    subprocess.Popen(argv, env=_env(), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def available():
    """Which targets can work on this machine, in menu order."""
    targets = []
    if os.path.exists(LOCALSEND):
        targets.append("localsend")
    if Gio.DesktopAppInfo.new(SLACK_DESKTOP) is not None:
        targets.append("slack")
    if shutil.which("bluetooth-sendto"):
        targets.append("bluetooth")
    targets.append("nearby")
    targets.append("gmail")
    if shutil.which("xdg-email") and _mail_app():
        targets.append("email")
    targets += ["copy-files", "copy-paths"]
    return targets


def _mail_app():
    info = Gio.AppInfo.get_default_for_uri_scheme("mailto")
    return info.get_display_name() if info else None


LABELS = {
    "localsend": "LocalSend",
    "slack": "Slack",
    "bluetooth": "Bluetooth…",
    "nearby": "Nearby Phone (QR Code)…",
    "gmail": "Gmail",
    "email": "Email",
    "copy-files": "Copy Files",
    "copy-paths": "Copy Paths",
}

ICONS = {
    "localsend": "/snap/localsend/current/meta/gui/localsend.png",
    "slack": "/snap/slack/current/usr/share/pixmaps/slack.png",
    "bluetooth": "bluetooth-active-symbolic",
    "nearby": "phone-symbolic",
    "gmail": "mail-send-symbolic",
    "email": "mail-message-new-symbolic",
    "copy-files": "edit-copy-symbolic",
    "copy-paths": "insert-link-symbolic",
}


def label(target):
    if target == "email":
        app = _mail_app()
        return f"Email ({app})" if app else "Email"
    return LABELS[target]


# ------------------------------------------------------------------
# Clipboard (xclip keeps serving it after it returns, as copy/paste needs)
# ------------------------------------------------------------------


def _clip(data, mime):
    proc = subprocess.Popen(["xclip", "-selection", "clipboard", "-t", mime, "-i"],
                            stdin=subprocess.PIPE, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.stdin.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    proc.stdin.close()


def _uri(path):
    return Gio.File.new_for_path(path).get_uri()


def copy_files(paths):
    """What Files' own Copy puts on the clipboard: paste into any file
    manager, or into apps that take files (Slack, Chrome) as attachments."""
    _clip("\r\n".join(_uri(p) for p in paths) + "\r\n", "text/uri-list")


def copy_files_for_file_managers(paths):
    _clip("copy\n" + "\n".join(_uri(p) for p in paths), "x-special/gnome-copied-files")


def copy_paths(paths):
    _clip("\n".join(paths), "UTF8_STRING")


def copy_image(path):
    """An image as pixels, which every chat and mail composer can paste."""
    suffix = Path(path).suffix.casefold()
    if suffix == ".png":
        data = Path(path).read_bytes()
    else:
        from io import BytesIO
        from PIL import Image
        buffer = BytesIO()
        with Image.open(path) as image:
            image.save(buffer, "PNG")
        data = buffer.getvalue()
    _clip(data, "image/png")


# ------------------------------------------------------------------
# Folders become zips where the target cannot take a folder
# ------------------------------------------------------------------


def with_zipped_folders(paths, done, notify):
    """Call done(files) with every folder in paths replaced by a zip of it.
    Zipping runs as a subprocess; done runs on the main loop."""
    folders = [p for p in paths if os.path.isdir(p)]
    if not folders:
        done(list(paths))
        return

    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    results = {p: p for p in paths if not os.path.isdir(p)}
    pending = [len(folders)]
    notify("Compressing…", ", ".join(os.path.basename(f) for f in folders[:3]))

    for folder in folders:
        name = os.path.basename(folder.rstrip("/")) or "folder"
        target = ZIP_DIR / f"{name}.zip"
        if target.exists():
            target.unlink()
        # zip runs from the parent folder so the archive holds "name/…".
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        launcher.set_cwd(os.path.dirname(folder.rstrip("/")) or "/")
        proc = launcher.spawnv(["zip", "-r", "-q", "-y", str(target), name])

        def finished(process, result, folder=folder, target=target):
            try:
                process.wait_check_finish(result)
                results[folder] = str(target)
            except GLib.Error:
                notify("Couldn't compress", os.path.basename(folder))
            pending[0] -= 1
            if pending[0] == 0:
                done([results[p] for p in paths if p in results])

        proc.wait_check_async(None, finished)


# ------------------------------------------------------------------
# Targets
# ------------------------------------------------------------------


def _snap_readable(path):
    home = str(Path.home())
    if not path.startswith(home + os.sep):
        return False
    rel = path[len(home) + 1:]
    return not any(part.startswith(".") for part in rel.split(os.sep))


def localsend(paths, notify):
    ready = []
    for path in paths:
        if _snap_readable(path):
            ready.append(path)
            continue
        # LocalSend is a snap and cannot see outside Home or into hidden
        # folders; hand it a copy it can read.
        SNAP_OUTBOX.mkdir(parents=True, exist_ok=True)
        target = SNAP_OUTBOX / os.path.basename(path.rstrip("/"))
        if os.path.isdir(path):
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)
        ready.append(str(target))
    _spawn([LOCALSEND, *ready])
    notify("Opening LocalSend", f"{len(ready)} item(s) ready to send - pick a nearby device")


def slack(paths, notify):
    def go(files):
        if len(files) == 1 and Path(files[0]).suffix.casefold() in IMAGE_SUFFIXES:
            copy_image(files[0])
        else:
            copy_files(files)
        info = Gio.DesktopAppInfo.new(SLACK_DESKTOP)
        if info is not None:
            info.launch([], None)
        notify("Copied for Slack",
               "Open a conversation and press Ctrl+V to attach, then send.")

    with_zipped_folders(paths, go, notify)


def bluetooth(paths, notify):
    with_zipped_folders(paths, lambda files: _spawn(["bluetooth-sendto", *files]), notify)


def gmail(paths, notify):
    def go(files):
        names = ", ".join(os.path.basename(f) for f in files)
        query = urllib.parse.urlencode({
            "view": "cm",
            "fs": "1",
            "su": names[:200],
        }, quote_via=urllib.parse.quote)
        copy_files(files)
        Gio.AppInfo.launch_default_for_uri(f"https://mail.google.com/mail/?{query}", None)
        notify("Gmail draft opened",
               "Press Ctrl+V in the draft to attach, or drag the files in from Files.")

    with_zipped_folders(paths, go, notify)


def email(paths, notify):
    def go(files):
        names = ", ".join(os.path.basename(f) for f in files)
        argv = ["xdg-email", "--subject", names[:200]]
        for f in files:
            argv += ["--attach", f]
        _spawn(argv)

    with_zipped_folders(paths, go, notify)


def nearby(paths, notify):
    _spawn(["/usr/bin/python3", str(HERE / "nearby_share.py"), *paths])


def run(target, paths, notify):
    paths = [p for p in paths if p]
    if not paths:
        return
    if target == "localsend":
        localsend(paths, notify)
    elif target == "slack":
        slack(paths, notify)
    elif target == "bluetooth":
        bluetooth(paths, notify)
    elif target == "nearby":
        nearby(paths, notify)
    elif target == "gmail":
        gmail(paths, notify)
    elif target == "email":
        email(paths, notify)
    elif target == "copy-files":
        copy_files(paths)
        notify("Copied", "Paste into another app or a chat to attach.")
    elif target == "copy-paths":
        copy_paths(paths)
        notify("Path copied", paths[0] if len(paths) == 1 else f"{len(paths)} paths")
