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


def independent(argv, app_id, root):
    """Known single-instance programs must never use the laptop profile."""
    executable = Path(argv[0]).name.lower()
    name = app_id.lower()
    profile = str(Path(root) / "profiles" / app_id)
    Path(profile).mkdir(parents=True, exist_ok=True)
    if "firefox" in name or executable == "firefox":
        argv += ["--no-remote", "--new-instance", "--profile", profile]
    elif any(word in name for word in ("chromium", "google-chrome")) or executable in ("chromium", "chromium-browser", "google-chrome"):
        # A basic password store: the session's fresh keyring would otherwise
        # open a "choose a keyring password" prompt before the browser.
        argv += ["--user-data-dir=" + profile, "--no-first-run", "--password-store=basic"]
    elif executable in ("code", "code-insiders", "codium", "antigravity", "antigravity-ide", "cursor") or name in ("code.desktop", "code_code.desktop", "codium.desktop", "antigravity.desktop"):
        # The = form: some editors' entries run Electron itself, whose own
        # parser does not take the value as a separate argument.
        argv += ["--user-data-dir=" + profile, "--new-window", "--password-store=basic"]
    elif "libreoffice" in name or executable in ("libreoffice", "soffice"):
        argv += ["-env:UserInstallation=" + Path(profile).as_uri()]
    return argv


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
    them, still apart from the laptop's copy of the same snap."""
    name, app = snap(argv)
    base = Path.home() / "snap" / name / "common" / "adaptive-phone" / Path(root).name
    for key, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
        (base / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
        env[key] = str(base / folder)
    xauthority = base / "Xauthority"
    fd = os.open(xauthority, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(Path(env["XAUTHORITY"]).read_bytes())
    env["XAUTHORITY"] = str(xauthority)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    argv = independent(argv, app_id, base)
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
    env = dict(os.environ)
    if snap(argv):
        argv = confined(argv, app_id, env["ADAPTIVE_MOBILE_ROOT"], env)
    else:
        argv = independent(argv, app_id, env["ADAPTIVE_MOBILE_ROOT"])
    if info.get_boolean("Terminal"):
        argv = ["x-terminal-emulator", "-e", *argv]
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
