"""Launch one catalog application with the private session's environment.

This helper never contacts the laptop's session bus or changes daemon state.
Desktop entries are expanded as arguments, not interpreted by a shell.
"""
import os
from pathlib import Path
import shlex
import shutil
import sys
import uuid

import phone_form


def arguments(command, name, filename, icon="", files=()):
    result = []
    for token in shlex.split(command):
        if token in ("%f", "%u"):
            result.extend(files[:1])
        elif token in ("%F", "%U"):
            result.extend(files)
        elif token == "%i":
            if icon:
                result.extend(["--icon", icon])
        elif token == "%c":
            result.append(name)
        elif token == "%k":
            result.append(filename)
        elif token in ("%d", "%D", "%n", "%N", "%v", "%m"):
            continue
        else:
            # Embedded field codes (except literal percent) are ambiguous.
            literal = token.replace("%%", "\x01")
            if "%" in literal:
                raise ValueError("unsupported desktop-entry field code")
            result.append(literal.replace("\x01", "%"))
    if not result:
        raise ValueError("empty application command")
    return result


def shares(env):
    """Whether this launch uses the laptop's own profile (the default)."""
    return env is not None and env.get("ADAPTIVE_PHONE_PROFILE", "laptop") == "laptop"


def independent(argv, app_id, root, env=None):
    """The launch arguments of a program that keeps its profile to one copy.

    With the laptop's profile (the default) the app opens with the owner's
    own sign-ins and settings: browsers and editors read their saved logins
    through the laptop's keyring (secrets_bridge.py). Only one copy can have
    a profile open, so the daemon first makes sure no other one does
    (holders). With a profile of the phone's own, it gets a fresh one, kept
    under the session's folder, and settings of the phone's own.

    With the session's environment, the app is also told the phone's form
    factor in its own toolkit's terms (phone_form.adapt)."""
    executable = Path(argv[0]).name.lower()
    name = app_id.lower()
    shared = shares(env)
    profile = None if shared else str(Path(root) / "profiles" / app_id)
    if profile:
        Path(profile).mkdir(parents=True, exist_ok=True)
        if env is not None:
            for key, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
                env[key] = str(Path(root) / folder)
    if "firefox" in name or executable == "firefox":
        if profile:
            argv += ["--no-remote", "--new-instance", "--profile", profile]
    elif any(word in name for word in ("chromium", "google-chrome")) or executable in ("chromium", "chromium-browser", "google-chrome"):
        # The laptop keeps the key to the profile's cookies in its keyring; a
        # fresh profile has none, and a basic store skips the keyring prompt.
        argv += ["--password-store=gnome-libsecret"] if shared else ["--user-data-dir=" + profile, "--no-first-run", "--password-store=basic"]
    elif executable in EDITORS or name in ("code.desktop", "code_code.desktop", "codium.desktop", "antigravity.desktop"):
        # The = form: some editors' entries run Electron itself, whose own
        # parser does not take the value as a separate argument.
        argv += ["--password-store=gnome-libsecret"] if shared else ["--user-data-dir=" + profile, "--new-window", "--password-store=basic"]
    elif profile and ("libreoffice" in name or executable in ("libreoffice", "soffice")):
        argv += ["-env:UserInstallation=" + Path(profile).as_uri()]
    if env is not None:
        argv = phone_form.adapt(argv, app_id, profile, env)
    return argv


EDITORS = ("code", "code-insiders", "codium", "antigravity", "antigravity-ide", "cursor")
# Folders of programs of every kind: an app found there is known by its name.
SHARED_BIN = (Path("/usr/bin"), Path("/bin"), Path("/usr/local/bin"), Path("/usr/sbin"))


def exclusive(argv, app_id):
    """Whether only one running copy can have this app's profile open."""
    executable = Path(argv[0]).name.lower()
    return bool(phone_form.kind(argv, app_id)) or executable in EDITORS or "libreoffice" in app_id.lower() \
        or executable in ("libreoffice", "soffice")


def program(argv, app_id):
    """How this app's processes are recognised: (folder, within, names)."""
    named = snap(argv)
    if named:
        return Path("/snap") / named[0], True, None
    if phone_form.kind(argv, app_id) == "firefox":
        return None, False, {"firefox", "firefox-bin"}
    found = Path(argv[0] if "/" in argv[0] else shutil.which(argv[0]) or argv[0]).resolve()
    if found.parent in SHARED_BIN:
        return None, False, {found.name}
    return found.parent, False, None


def running(argv, app_id, proc="/proc"):
    """(pid, environment) of each of this app's processes, wherever it runs."""
    folder, within, names = program(argv, app_id)
    for entry in os.listdir(proc):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            exe = Path(os.readlink(f"{proc}/{entry}/exe").removesuffix(" (deleted)"))
            environ = Path(f"{proc}/{entry}/environ").read_bytes().split(b"\0")
        except OSError:
            continue
        if "crashpad" in exe.name:
            continue   # outlives the app for a moment; it holds nothing
        if exe.name in names if names is not None else (folder in exe.parents if within else exe.parent == folder):
            yield int(entry), environ


def holders(argv, app_id, root, proc="/proc"):
    """This app's processes outside the phone session at root: {"laptop": [pid], "phone": [pid]}.

    A phone session's processes carry ADAPTIVE_MOBILE_ROOT; another phone's
    copy holds the profile just as the laptop's does."""
    mine = ("ADAPTIVE_MOBILE_ROOT=" + str(root)).encode()
    found = {"laptop": [], "phone": []}
    for pid, environ in running(argv, app_id, proc):
        if mine not in environ:
            found["phone" if any(item.startswith(b"ADAPTIVE_MOBILE_ROOT=") for item in environ) else "laptop"].append(pid)
    return found


def entry(app_id):
    from gi.repository import Gio
    try:
        info = Gio.DesktopAppInfo.new(app_id)
    except TypeError:   # PyGObject's answer for an app that is not installed
        info = None
    if info is None:
        raise ValueError("application is no longer installed")
    return info, arguments(info.get_string("Exec"), info.get_name(), info.get_filename(), info.get_string("Icon") or "")


def holding(app_id, root, profile="laptop"):
    """Who else has this app's profile open, when it is the laptop's; nobody otherwise."""
    if profile != "laptop":
        return {"laptop": [], "phone": []}
    try:
        _, argv = entry(app_id)
    except ValueError:
        return {"laptop": [], "phone": []}   # the launch itself says it is gone
    if not exclusive(argv, app_id):
        return {"laptop": [], "phone": []}
    return holders(argv, app_id, root)


def mine(app_id, root):
    """This app's processes in the phone session at root."""
    try:
        _, argv = entry(app_id)
    except ValueError:
        return []
    marker = ("ADAPTIVE_MOBILE_ROOT=" + str(root)).encode()
    return [pid for pid, environ in running(argv, app_id) if marker in environ]


def snap(argv):
    """(snap, app) for a command that is a snap, else None."""
    found = Path(argv[0] if "/" in argv[0] else shutil.which(argv[0]) or argv[0])
    if found.parent != Path("/snap/bin"):
        return None
    name, _, app = found.name.partition(".")
    return name, app or name


def confined(argv, app_id, root, env):
    """A snap reads only its own folders and refuses to start outside a scope
    named for it: its profiles, settings and X authority go where it can read
    them, still apart from the laptop's copy of the same snap (with a profile
    of the phone's own; with the laptop's, the snap's own folders)."""
    name, app = snap(argv)
    base = Path.home() / "snap" / name / "common" / "adaptive-phone" / Path(root).name
    # Its X authority goes here whichever profile it uses.
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    for key, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
        if shares(env):
            # The snap's own folders, which its laptop copy uses too.
            env.pop(key, None)
            continue
        (base / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
        env[key] = str(base / folder)
    xauthority = base / "Xauthority"
    fd = os.open(xauthority, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(Path(env["XAUTHORITY"]).read_bytes())
    env["XAUTHORITY"] = str(xauthority)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    argv = independent(argv, app_id, base, env)
    if shutil.which("systemd-run"):
        argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--unit", f"snap.{name}.{app}-{uuid.uuid4()}", "--", *argv]
    return argv


def main():
    from gi.repository import Gio
    app_id = sys.argv[1]
    info = Gio.DesktopAppInfo.new(app_id)
    if info is None:
        raise ValueError("application is no longer installed")
    argv = arguments(info.get_string("Exec"), info.get_name(), info.get_filename(), info.get_string("Icon") or "", sys.argv[2:])
    if exclusive(argv, app_id) and shares(os.environ) and holding(app_id, os.environ["ADAPTIVE_MOBILE_ROOT"])["laptop"]:
        # It would hand itself to the laptop's copy and open there.
        raise ValueError("open on the laptop")
    env = dict(os.environ)
    if snap(argv):
        argv = confined(argv, app_id, env["ADAPTIVE_MOBILE_ROOT"], env)
    else:
        argv = independent(argv, app_id, env["ADAPTIVE_MOBILE_ROOT"], env)
    if info.get_boolean("Terminal"):
        argv = ["kterm-terminal", "-x", *argv]
    cwd = info.get_string("Path")
    os.chdir(cwd if cwd and Path(cwd).is_dir() else str(Path.home()))
    os.execvpe(argv[0], argv, env)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never print launch arguments, document names or environment values.
        sys.stderr.write("Application could not start independently; check its desktop entry and session compatibility.\n")
        sys.exit(1)
