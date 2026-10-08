#!/usr/bin/env python3
"""Which laptop apps open on the phone in a session of their own.

    scripts/link-mobile-compat.py APP_ID...    try the apps named
    scripts/link-mobile-compat.py --all        try every installed app

Each app is started in a private display made for this run, as a phone
session would start it, and is given SECONDS (default 20) to show a window.
Nothing appears on this screen and no phone's profiles are touched: the run
has a throwaway directory of its own beside the phones' sessions,
removed at the end.

The result is kept where the phone's app drawer reads it, so an app that
cannot open independently says so there before it is tapped:

    works       a window of its own appeared
    no-window   it started, but no window appeared in the session
    failed      it exited with an error before showing a window
"""

import argparse
import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "adaptive-link"))

import desktop  # noqa: E402
import identity  # noqa: E402
import mobile_session  # noqa: E402


async def attempt(app, seconds, root):
    """The state one app reached in a session made for it alone."""
    s = mobile_session.MobileSession(root, "compatibility-" + app["id"])
    try:
        await s.start()
        await s.spawn(app["id"], app["name"])
        catalog = [app]
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(.5)
            await s.refresh(catalog)
            state = s.apps[app["id"]]["state"]
            if state in ("running", "failed"):
                return state
        return "no-window"
    finally:
        await s.close()
        # A snap kept its trial profile in its own folder (mobile_launch.confined).
        for trial in Path.home().glob("snap/*/common/adaptive-phone/" + s.root.name):
            shutil.rmtree(trial, ignore_errors=True)


async def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("apps", nargs="*", help="desktop-entry IDs, such as firefox_firefox.desktop")
    parser.add_argument("--all", action="store_true", help="every app in the catalog")
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    missing = mobile_session.MobileDesktop.capabilities()["missing"]
    if missing:
        sys.exit("Phone sessions need: " + ", ".join(missing))
    catalog = desktop.applications(True)
    wanted = catalog if args.all else [a for a in catalog if a["id"] in args.apps]
    unknown = set(args.apps) - {a["id"] for a in catalog}
    if unknown:
        sys.exit("Not in the catalog: " + ", ".join(sorted(unknown)))
    if not wanted:
        parser.print_usage()
        return 2
    record = identity.LINK_DIR / "mobile" / "compatibility.json"
    # Beside the phones' own sessions, so confinement (snaps cannot see a
    # private /tmp) treats the trial exactly as it would treat a phone.
    record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix="compat.", dir=record.parent))
    worst = 0
    try:
        for app in wanted:
            state = await attempt(app, args.seconds, root)
            mobile_session.record_compatibility(record, app["id"], state)
            result = mobile_session.COMPATIBILITY[state]
            worst = max(worst, result != "works")
            print(f"{result:10} {app['id']}  ({app['name']})", flush=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\nKept in {record}")
    return worst


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
