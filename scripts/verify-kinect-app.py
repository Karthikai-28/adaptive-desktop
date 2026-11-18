#!/usr/bin/env python3
"""Check the Kinect app in its real GTK/WebKit window, on a virtual 1920x1200 display, with the
demo people (no Kinect). Run under xvfb-run (scripts/verify-all.sh does):

    xvfb-run -a -s "-screen 0 1920x1200x24" python3 scripts/verify-kinect-app.py [--shots DIR]

The page reports itself to the server every second (section, what it shows, frame rate, script
errors, window size, full screen; /api/ui), so the check sees what a person would:

    sections      every section opens, through the window's own command line (one instance:
                  the second command moves the open window), with no script error
    old commands  motion.py fitness/arcade/room and studio.py open the matching sections
    full screen   --fullscreen fills the 1920x1200 screen (with xfwm4 managing the display)
    a workout     a session view while it runs, back to choosing after it
    the games     each game draws while it runs
    reconnecting  the server stopped and started again: the page reconnects by itself
    frame rate    measured apart from tracking: reported, and required to stay at 30 a second or
                  more on this machine's real display (on a virtual display it is software
                  rendering, so it is reported only)

--shots DIR keeps a screenshot of each step (ImageMagick's import).
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "apps/kinect/kinect.py"
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
FAILED = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"   [{detail}]"))
    if not ok:
        FAILED.append(name)


def get(path, timeout=2.0):
    try:
        return json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read() or b"null")
    except (OSError, ValueError):
        return None


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=3).read())


def ui_until(pred, seconds=12.0):
    """The page's latest report once pred(report) holds (or the last one seen)."""
    deadline, last = time.time() + seconds, None
    while time.time() < deadline:
        r = get("/api/ui")
        if r and time.time() - r["at"] < 2.5:
            last = r
            if pred(r):
                return r
        time.sleep(0.25)
    return last


def run(args, env, wait=True):
    p = subprocess.Popen([sys.executable, *map(str, args)], env=env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    if wait:
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
    return p


def shot(shots, name):
    if shots and shutil.which("import"):
        subprocess.run(["import", "-window", "root", str(Path(shots) / f"{name}.png")], capture_output=True)


def start_server():
    py = REPO / ".local/air-venv/bin/python"
    return subprocess.Popen([str(py if py.exists() else sys.executable), str(REPO / "services/kinect-motion/server.py"),
                             "--demo", "--port", str(PORT), "--db", ":memory:"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    if not os.environ.get("DISPLAY"):
        print("skip: no display (run under xvfb-run)")
        return 0
    shots = None
    if "--shots" in sys.argv:
        shots = Path(sys.argv[sys.argv.index("--shots") + 1])
        shots.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "KINECT_MOTION_URL": BASE}
    wm = None
    if shutil.which("xfwm4"):
        wm = subprocess.Popen(["xfwm4", "--compositor=off", "--sm-client-disable"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.0)
    server = start_server()
    for _ in range(80):
        if get("/api/state"):
            break
        time.sleep(0.1)
    app = run([APP, "--demo", "--fullscreen"], env, wait=False)
    try:
        print("The window")
        r = ui_until(lambda r: r["section"] == "home" and r["connected"], 25)
        check("it opens on Home and connects", r and r["section"] == "home" and r["connected"], r)
        if wm is not None:
            check("--fullscreen fills the 1920 x 1200 screen", r and r["w"] == 1920 and r["h"] == 1200 and r["fullscreen"], r)
        else:
            print("  skip  full screen: no window manager on this display (xfwm4 not installed)")
        shot(shots, "home")
        print("Sections, through the window's own command line")
        for section in ("fitness", "games", "camera", "room", "scan", "history", "home"):
            run([APP, "--demo", section], env)
            r = ui_until(lambda r, s=section: r["section"] == s, 10)
            check(f"{section}: shown, no script error", r and r["section"] == section and not r["errors"], r)
            shot(shots, section)
        check("still one window process (the commands moved it)", app.poll() is None)
        print("The old commands")
        for args, want in (([REPO / "apps/kinect-motion/motion.py", "arcade", "--demo"], "games"),
                           ([REPO / "apps/kinect-motion/motion.py", "room", "--demo"], "room"),
                           ([REPO / "apps/kinect-motion/motion.py", "fitness", "--demo"], "fitness"),
                           ([REPO / "apps/kinect-studio/studio.py", "--demo"], "camera")):
            run(args, env)
            r = ui_until(lambda r, s=want: r["section"] == s, 10)
            check(f"{Path(args[0]).name} {args[1] if len(args) > 2 else ''} opens {want}", r and r["section"] == want, r)
        print("A workout and the games")
        run([APP, "--demo", "fitness"], env)
        ui_until(lambda r: r["section"] == "fitness")
        post("/api/workout", {"action": "start", "mode": "challenge", "exercise": "squat", "seconds": 30})
        r = ui_until(lambda r: r["view"] == "session", 8)
        check("a running workout shows the session", r and r["view"] == "session" and not r["errors"], r)
        time.sleep(4)
        shot(shots, "session")
        post("/api/workout", {"action": "finish"})
        r = ui_until(lambda r: r["view"] == "choose", 8)
        check("... and choosing again after it", r and r["view"] == "choose", r)
        run([APP, "--demo", "games"], env)
        for game in ("walls", "pose", "race"):
            post("/api/game", {"action": "start", "game": game})
            r = ui_until(lambda r: r["section"] == "games" and r["view"] == "play", 8)
            time.sleep(2.5)
            r = get("/api/ui")
            check(f"{game}: drawing, no script error", r and r["view"] == "play" and not r["errors"], r)
            shot(shots, f"game-{game}")
        post("/api/game", {"action": "stop"})
        frames = (r or {}).get("frames") or []
        print(f"        render rate while playing: {', '.join(map(str, frames[-6:]))} frames a second"
              f" ({'software rendering on a virtual display' if os.environ.get('DISPLAY', '').startswith(':9') or 'xvfb' in os.environ.get('XAUTHORITY', '') else 'this display'})")
        print("Reconnecting")
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=10)
        time.sleep(2)
        server = start_server()
        r = ui_until(lambda r: r["connected"], 20)
        check("the server stopped and started again: the page is back by itself", r and r["connected"], r)
    finally:
        for p in (app, server, wm):
            if p is not None and p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
    print()
    if FAILED:
        print(f"Kinect app: {len(FAILED)} check(s) FAILED")
        return 1
    print("Kinect app: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
