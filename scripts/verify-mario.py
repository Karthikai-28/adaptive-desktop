#!/usr/bin/env python3
"""Checks for Mario Hub and Mario Home that need no desktop, model or network.

    scripts/verify-mario.py

Collectors against throwaway git repos and a fake Thinking Space; Mario's decisions (instant
answers, local vs Claude Code, the hand-off's limits, Next step); the hub over real HTTP and a
WebSocket with stand-in collectors, including its loopback guards; the page's script syntax. What
it does not touch: WebKit on GNOME (the desktop hint, the panel toggle), LOOM, Ollama, Claude Code.
"""
import asyncio
import csv
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "mario-hub"))
import brain  # noqa: E402
import collectors  # noqa: E402
import config as config_mod  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def fixture(root):
    """Two git repos (one with an unpushed commit and a changed file) and a Thinking Space copy."""
    origin, work = root / "origin.git", root / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    (work / "a.txt").write_text("a")
    git(work, "add", "a.txt"); git(work, "commit", "-qm", "first")
    git(work, "push", "-q", "origin", "HEAD:main"); git(work, "branch", "-q", "--set-upstream-to=origin/main")
    (work / "b.txt").write_text("b")
    git(work, "add", "b.txt"); git(work, "commit", "-qm", "second, not pushed")
    (work / "a.txt").write_text("changed")

    ts = root / "thinking-space"
    board = ts / "boards" / "builds-tech"
    board.mkdir(parents=True)
    (board / "meta.json").write_text(json.dumps({"title": "Builds & Tech", "url": "https://claude.ai/artifact/x"}))
    rows = [
        {"id": "e1", "data": {"type": "text", "size": "title", "text": "Builds & Tech", "x": 0, "y": 0}},
        {"id": "e10", "data": {"type": "container", "text": "Inbox: build ideas", "x": 1500, "y": 260, "w": 340, "h": 900}},
        {"id": "e5c", "data": {"type": "container", "text": "Jarvis on planetstormer (plan)", "x": 0, "y": 260, "w": 900, "h": 400}},
        {"id": "e37", "data": {"type": "shape", "text": "Next build idea…", "x": 1524, "y": 284}},
        {"id": "e39", "type": "shape", "text": "**Mario Home (11 Nov)**\nmore", "x": 1524, "y": 668},  # flat shape
        {"id": "e5", "data": {"type": "shape", "text": "outside", "x": 10, "y": 10}},
    ]
    (board / "elements.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    hub = ts / "boards" / "hub"
    hub.mkdir()
    (hub / "meta.json").write_text(json.dumps({"title": "Hub"}))
    (hub / "elements.jsonl").write_text(json.dumps({"id": "e45", "data": {"type": "text", "text": "Updated 11 Nov 2026 · x"}}))

    data = ts / "reels" / "data"
    data.mkdir(parents=True)
    write_csv(data / "movies-shows.csv", ["Title", "Where to watch in India", "Status"], [
        ["Predestination", "Prime Video", "Yet to watch"], ["Donnie Darko", "Prime Video", "Yet to watch"],
        ["Zodiac", "Netflix", "Watched"], ["Psycho", "Rent: Prime Video, Apple TV", "Yet to watch"]])
    write_csv(data / "ai-tools.csv", ["Name", "What it does", "Status", "Saved on", "Reel"],
              [["Named in video", "x", "To try", "2026-11-01", "r0"], ["Older tool", "old", "To try", "2025-01-01", "r1"],
               ["Newest tool", "new", "To try", "2026-11-09", "r2"], ["Done tool", "d", "Tried", "2026-11-10", "r3"]])
    write_csv(data / "recipes.csv", ["What it is", "Status", "Saved on", "Reel"],
              [["Pepper chicken", "To cook", "2026-05-16", "c1"], ["Cooked one", "Cooked", "2026-06-01", "c2"]])
    write_csv(data / "all-reels.csv", ["Category", "What it is", "Why it matters", "Saved on", "Link"],
              [["AI", "a", "", "2026-01-01", "l1"], ["AI", "b", "why b", "2026-11-10", "l2"], ["AI", "c", "", "2025-01-01", "l3"]])
    (ts / "reels" / "README.md").write_text("Sheet: [tracker](https://docs.google.com/spreadsheets/d/abc_123/edit)\n")
    write_csv(data / "history.csv", ["Date", "Tab", "Item", "Change", "From", "To", "Reel"],
              [["2026-11-11", "All tabs", "Saved Reels", "Created", "", "", ""]])
    cfg = config_mod.load(root / "none.json")
    cfg.update(repos=[work, root / "missing"], thinking_space=ts, thinking_space_pull_s=0)
    return cfg, work


def test_collectors(cfg, work):
    print("Collectors")
    check("status line with ahead and behind", collectors.parse_status(
        "## main...origin/main [ahead 2, behind 1]\n M x\n?? y\n") == ("main", 2, 1, 2))
    check("status line with no upstream", collectors.parse_status("## master\n") == ("master", 0, 0, 0))
    b = collectors.builds(cfg)["repos"]
    check("missing checkouts are skipped", len(b) == 1)
    r = b[0]
    check("repo: last commit, unpushed and changed", r["subject"] == "second, not pushed" and r["ahead"] == 1
          and r["dirty"] == 1 and r["branch"] == "main", str(r))
    t = collectors.thinking_space(cfg)
    bt = t["boards"][0]
    check("board inbox: both element shapes, placeholder and outside items left out",
          bt["inbox"] == ["Mario Home (11 Nov)"], str(bt["inbox"]))
    check("hub's Updated line", t["updated"].startswith("Updated 11 Nov"))
    rl = collectors.reels(cfg)
    movies = next(x for x in rl["trackers"] if x["id"] == "movies-shows")
    check("tracker progress", (movies["done"], movies["total"]) == (1, 4))
    check("tonight: yet to watch, on a subscription, not a rental",
          rl["tonight"] == {"service": "Prime Video", "titles": ["Predestination", "Donnie Darko"]}, str(rl["tonight"]))
    check("total and last change", rl["total"] == 3 and rl["last_change"]["Change"] == "Created")
    check("board sections, without the Inbox", bt["sections"] == ["Jarvis on planetstormer"], str(bt["sections"]))
    check("try next: newest named untried first", [x["name"] for x in rl["try_next"]] == ["Newest tool", "Older tool"],
          str(rl["try_next"]))
    check("cook next: only what is still to cook", [x["name"] for x in rl["cook"]] == ["Pepper chicken"])
    check("newest saves, with why when known", rl["newest"][0]["what"] == "why b")
    check("the trackers' Google Sheet link", rl["sheet"] == "https://docs.google.com/spreadsheets/d/abc_123/edit")
    check("commit activity: 14 days, today last", len(collectors.builds(cfg)["activity"]) == 14
          and collectors.builds(cfg)["activity"][-1] >= 2)
    check("network rate from two samples", collectors.net_rates(
        "h\nh\n  eth0: 1000 0 0 0 0 0 0 0 500 0 0 0 0 0 0 0\n    lo: 9 0 0 0 0 0 0 0 9 0 0 0 0 0 0 0\n", now=10) is None
          and collectors.net_rates("h\nh\n  eth0: 3000 0 0 0 0 0 0 0 1500 0 0 0 0 0 0 0\n", now=12) == {"down": 1000.0, "up": 500.0})
    check("weather can be turned off (no network)", collectors.weather({**cfg, "cards_off": ["weather"]}) == {"off": True})
    check("LOOM stopped reads as stopped", collectors.loom({"loom_url": "http://127.0.0.1:9"})["running"] is False)
    check("meminfo", collectors.parse_meminfo("MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n")["used_gb"] == 7.6)
    check("a stopped service reads as stopped, not an error",
          collectors.agent_office({"agent_office_url": "http://127.0.0.1:9"})["running"] is False)


def test_usage(cfg):
    print("AI usage")
    import types
    snap = {"codex": {"windows": [{"label": "5h", "used": 90}]},
            "claude": {"windows": [{"label": "5h", "used": 42, "resetsAt": 1}, {"label": "Weekly", "used": 70, "resetsAt": 2},
                                   {"label": "old", "used": 99, "expired": True}]},
            "gemini": {"windows": []}}
    real = collectors._run
    collectors._run = lambda *a, **k: (json.dumps(snap), "")
    try:
        out = collectors.usage({**cfg, "usage_providers": ["claude", "gemini"]})["providers"]
    finally:
        collectors._run = real
    check("only the plans you pay for (Claude, Gemini)", list(out) == ["claude", "gemini"], str(list(out)))
    check("the fullest live window leads", out["claude"]["used"] == 70 and out["claude"]["window"] == "Weekly")
    check("expired windows are dropped", len(out["claude"]["windows"]) == 2)


def test_brain(cfg, work):
    print("Mario's decisions")
    repos = [work, Path("/x/LOOM"), Path("/x/adaptive-desktop")]
    c = brain.classify("fix the dock autohide bug in adaptive desktop", repos)
    check("dev work in a named repo goes to Claude Code", c["route"] == "claude" and c["repo"].endswith("adaptive-desktop"))
    check("a question stays local", brain.classify("what is the weather in Bengaluru", repos)["route"] == "local")
    check("a question about code stays local", brain.classify("how does the loom router pick a model?", repos)["route"] == "local")
    check("outward words are flagged", brain.classify("add a sports skill to LOOM and push it", repos)["outward"])
    plan = brain.plan_handoff("add tests", work)
    check("hand-off: headless, edits only, limits in the prompt", plan["argv"][:2] == ["claude", "-p"]
          and "acceptEdits" in plan["argv"] and "Do not push" in plan["prompt"] and plan["cwd"] == str(work))
    state = {"cards": {"builds": {"data": collectors.builds(cfg)}, "reels": {"data": collectors.reels(cfg)}},
             "config": {"backup_at": "22:40"}}
    steps = brain.next_steps(state)
    check("Next step: unpushed commits first", steps and "not pushed" in steps[0]["text"], str(steps))
    check("Next step: actions carry the repo", steps[0]["action"]["arg"] == str(work))
    now = time.mktime(time.strptime("2026-11-11 21:00", "%Y-%m-%d %H:%M"))
    check("Next step: backup within three hours",
          any("22:40" in s["text"] for s in brain.next_steps({"cards": {}, "config": {"backup_at": "22:40"}}, now)))
    check("instant: movie pick", "Predestination" in (brain.quick_answer("Pick a movie for tonight", state) or ""))
    check("instant: anything else goes to a model", brain.quick_answer("explain transformers", state) is None)


async def test_hub(cfg):
    print("Hub over HTTP and WebSocket")
    import aiohttp
    from aiohttp import web
    import hub as hub_mod

    calls = {"n": 0}

    def fake(_cfg):
        calls["n"] += 1
        return {"n": calls["n"]}

    hub = hub_mod.Hub(cfg, schedule={"fake": (fake, 0.2)})
    port = 18791
    app = hub_mod.make_app(hub, port)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with aiohttp.ClientSession() as s:
            await asyncio.sleep(0.3)
            async with s.get(base + "/api/state") as r:
                st = await r.json()
            check("state has cards, next and presence", "fake" in st["cards"] and "next" in st and st["presence"]["state"] == "ready")
            async with s.get(base + "/api/state", headers={"Host": f"evil.example:{port}"}) as r:
                check("another Host is refused", r.status == 403)
            async with s.post(base + "/api/ask", json={"text": "hi"}, headers={"Origin": "http://evil.example"}) as r:
                check("a cross-site write is refused", r.status == 403)
            async with s.get(base + "/") as r:
                check("the page is served", r.status == 200 and "Mario" in await r.text())
            async with s.ws_connect(base + "/ws") as ws:
                first = json.loads((await ws.receive(timeout=2)).data)
                check("WebSocket starts with the whole state", first["type"] == "state")
                pushed = None
                for _ in range(10):
                    msg = json.loads((await ws.receive(timeout=2)).data)
                    if msg["type"] == "card":
                        pushed = msg
                        break
                check("changed cards are pushed", pushed and pushed["name"] == "fake")
                async with s.post(base + "/api/ask", json={"text": "write tests for the hub in " + Path(cfg["repos"][0]).name}) as r:
                    res = await r.json()
                check("dev work comes back as a plan, not a run", res.get("route") == "claude" and res["handoff"]["status"] == "waiting")
                check("the plan never exposes the command line", "argv" not in res.get("handoff", {}))
                pres = None
                for _ in range(10):
                    msg = json.loads((await ws.receive(timeout=2)).data)
                    if msg["type"] == "presence":
                        pres = msg
                        break
                check("Mario asks first (needs you)", pres and pres["state"] == "needs_you")
                pid = res["handoff"]["id"]
                async with s.post(f"{base}/api/handoff/{pid}", json={"decision": "cancel"}) as r:
                    check("Not now cancels", (await r.json())["status"] == "cancelled")
                async with s.post(f"{base}/api/handoff/{pid}", json={"decision": "run"}) as r:
                    check("a cancelled plan cannot be run", r.status == 409)
            async with s.post(base + "/api/action", json={"id": "terminal", "arg": "/etc"}) as r:
                check("actions only open Mario's own folders", (await r.json())["ok"] is False)
            async with s.post(base + "/api/action", json={"id": "url", "arg": "https://evil.example/"}) as r:
                check("actions only open known kinds of links", (await r.json())["ok"] is False)
            async with s.post(base + "/api/presence", json={"state": "listening"}) as r:
                check("the voice listener can set presence", (await r.json()).get("ok") is True)
    finally:
        await runner.cleanup()


def test_page():
    print("Page and host")
    js = REPO / "apps" / "mario-home" / "static" / "home.js"
    if shutil.which("node"):
        out = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        check("home.js parses", out.returncode == 0, out.stderr[:200])
    html = (REPO / "apps" / "mario-home" / "static" / "index.html").read_text()
    import re as _re
    tiles = _re.findall(r'data-tile="([a-z]+)"', html)
    areas = _re.findall(r'grid-area:(\d+)/(\d+)/(\d+)/(\d+)', html)
    check("fifteen live tiles", len(tiles) == 15 and len(areas) == 15, str(tiles))
    cells = [(r, c) for r0, c0, r1, c1 in (map(int, a) for a in areas) for r in range(r0, r1) for c in range(c0, c1)]
    check("tiles fill the 12 x 6 grid exactly once", sorted(cells) == [(r, c) for r in range(1, 7) for c in range(1, 13)])
    script = js.read_text()
    check("every tile has a renderer", all(f"  {t}(" in script for t in tiles), str([t for t in tiles if f"  {t}(" not in script]))
    check("page has the panel and its script", "panel-form" in html and "/static/home.js" in html)
    check("no innerHTML in the page script", "innerHTML" not in script)
    try:
        py_compile.compile(str(REPO / "apps" / "mario-home" / "host.py"), doraise=True)
        check("host.py compiles", True)
    except py_compile.PyCompileError as exc:
        check("host.py compiles", False, str(exc))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, work = fixture(Path(tmp))
        test_collectors(cfg, work)
        test_usage(cfg)
        test_brain(cfg, work)
        try:
            import aiohttp  # noqa: F401
            asyncio.run(test_hub(cfg))
        except ImportError:
            print("  skip hub checks: python3-aiohttp is not installed")
    test_page()
    print(f"\n{'all passed' if not FAILED else f'{len(FAILED)} failed: ' + ', '.join(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
