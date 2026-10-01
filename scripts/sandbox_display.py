"""Run a GTK check on a virtual display, away from the real session.

Shared by the verify-*.py scripts that open a real window. The script calls
run(__file__, inner): the first time that re-runs it under xvfb-run and
dbus-run-session with a throwaway HOME, and inside that it calls
inner(sandbox, check), which opens windows and reports with check(ok, text).

Nothing inside can see or change the registry, notes, snippets or settings of
the person running it, and no window appears on their screen.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

INNER = "ADAPTIVE_GTK_SANDBOX"


def run(script, inner, name, timeout=180):
    return _inner(inner, name) if os.environ.get(INNER) else _outer(script, name, timeout)


def _outer(script, name, timeout):
    for tool in ("xvfb-run", "dbus-run-session"):
        if not shutil.which(tool):
            print(f"SKIP {name}: {tool} is not installed")
            return 0
    sandbox = tempfile.mkdtemp(prefix="adaptive-gtk.")
    home = Path(sandbox) / "home"
    (home / ".config").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("DCONF_PROFILE", "WAYLAND_DISPLAY", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                        "XDG_CACHE_HOME", "DBUS_SESSION_BUS_ADDRESS")}
    runtime = Path(sandbox) / "run"
    runtime.mkdir(mode=0o700)
    env.update({"HOME": str(home), INNER: sandbox, "GSK_RENDERER": "cairo", "GDK_BACKEND": "x11",
                "NO_AT_BRIDGE": "1", "XDG_RUNTIME_DIR": str(runtime)})
    try:
        done = subprocess.run(
            ["xvfb-run", "-a", "-s", "-screen 0 1280x900x24", "dbus-run-session", "--",
             sys.executable, str(Path(script).resolve())],
            env=env, capture_output=True, text=True, timeout=timeout)
        results = Path(sandbox) / "results.txt"
        if not results.exists():
            print(f"FAIL {name} did not start")
            print(done.stdout[-2000:], done.stderr[-2000:])
            return 1
        print(results.read_text(), end="")
        # What the check printed besides its results is the detail of a
        # failure (a traceback, the last lines of a log): show it then.
        if done.returncode != 0 and done.stdout.strip():
            print(done.stdout[-4000:])
        return done.returncode
    finally:
        if os.environ.get("ADAPTIVE_KEEP_SANDBOX"):
            print(f"Sandbox kept: {sandbox}")
        else:
            shutil.rmtree(sandbox, ignore_errors=True)


def _inner(inner, name):
    sandbox = Path(os.environ[INNER])
    lines = []
    failures = []

    def check(condition, message):
        lines.append(f"{'OK  ' if condition else 'FAIL'} {message}")
        if not condition:
            failures.append(message)

    try:
        inner(sandbox, check)
    except Exception as error:  # noqa: BLE001 - a crash is a failed check, not a silent pass
        check(False, f"the check script raised {error!r}: {traceback.format_exc(limit=4)}")

    if not lines:
        failures.append("no checks ran")
        lines.append(f"FAIL {name}: nothing was checked")
    lines.append("")
    lines.append(f"{len(failures)} check(s) failed" if failures else f"{name} checks passed")
    (sandbox / "results.txt").write_text("\n".join(lines) + "\n")
    return 1 if failures else 0
