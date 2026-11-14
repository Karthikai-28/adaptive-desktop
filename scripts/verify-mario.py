#!/usr/bin/env python3
"""Checks for Mario Hub and Mario Home that need no desktop, model or network.

    scripts/verify-mario.py

Collectors against throwaway git repos and a fake Thinking Space; mail accounts and Gmail thread
links against a stand-in IMAP server; news pictures and article links against stand-in pages;
Mario's decisions (instant answers, answer vs hand-off, the hand-off's limits, Next step); who
answers (Claude, then Gemini at Claude's limit, then the laptop) with recorded CLI replies; the hub
over real HTTP and a WebSocket with stand-in collectors, including its loopback guards; the page's
script syntax. What it does not touch: WebKit on GNOME (the desktop hint, the panel toggle), the real
claude and agy CLIs, LOOM, Ollama, Gmail and the news sites themselves.
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
import engines  # noqa: E402

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
    rss = ('<rss><channel><item><title>Big launch today - The Hindu</title><link>https://news.google.com/a</link>'
           '<pubDate>Thu, 12 Nov 2026 03:00:00 GMT</pubDate><source url="x">The Hindu</source></item>'
           '<item><title>Show HN: a thing</title><link>https://example.com/x</link><pubDate>Thu, 12 Nov 2026 04:00:00 GMT</pubDate></item>'
           '<item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>')
    items = collectors.parse_rss(rss, "Feed")
    check("news: outlet split from the title", items and items[0]["title"] == "Big launch today" and items[0]["source"] == "The Hindu", str(items))
    check("news: only https links", [i["link"] for i in items] == ["https://news.google.com/a", "https://example.com/x"])
    check("news: a broken feed is an empty list", collectors.parse_rss("<rss", "x") == [])
    check("news: off in cards_off", collectors.news({"cards_off": ["news"], "news": []}).get("off") is True)
    media_rss = ('<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>Pic</title><link>https://example.com/p</link>'
                 '<media:content url="https://img.example.com/p.jpg" medium="image"/></item>'
                 '<item><title>Enc</title><link>https://example.com/e</link><enclosure url="https://img.example.com/e.mp3" type="audio/mpeg"/></item></channel></rss>')
    mi = collectors.parse_rss(media_rss, "F")
    check("news: a picture the feed gives is kept, audio is not", [i["image_src"] for i in mi] == ["https://img.example.com/p.jpg", ""], str(mi))
    real_fetch = collectors._fetch
    page = (b'<html><head><meta name="twitter:image" content="https://cdn.example.com/t.jpg">'
            b'<meta content="/img/lead.jpg" property="og:image"></head><body>x</body></html>')
    collectors._fetch = lambda url, *a, **k: ("https://site.example.com/story/1", "text/html", page)
    try:
        check("news: the article's own og:image, made absolute", collectors.page_image("https://site.example.com/story/1")
              == "https://site.example.com/img/lead.jpg")
    finally:
        collectors._fetch = real_fetch
    news_dir = Path(cfg["thinking_space"]).parent / "news"
    real_dir, real_cache, real_resolve, real_shown = collectors.NEWS_DIR, collectors._NEWS_CACHE, collectors.resolve_news, collectors._NEWS_SHOWN
    looked = []

    def fake_resolve(link, image_src=""):
        looked.append(link)
        return {"url": "https://www.thehindu.com/story" if "google" in link else link, "image": "0123456789abcdef.jpg"}
    collectors.NEWS_DIR, collectors._NEWS_CACHE, collectors.resolve_news = news_dir, None, fake_resolve
    collectors._NEWS_SHOWN = {"https://news.google.com/rss/articles/a": "", "https://example.com/x": ""}
    try:
        nm = collectors.news_media({"cards_off": []})["media"]
        again = collectors.news_media({"cards_off": []})["media"]
    finally:
        collectors.NEWS_DIR, collectors._NEWS_CACHE, collectors.resolve_news, collectors._NEWS_SHOWN = real_dir, real_cache, real_resolve, real_shown
    check("news: a Google News link opens the article itself, with its picture",
          nm.get("https://news.google.com/rss/articles/a") == {"url": "https://www.thehindu.com/story", "image": "0123456789abcdef.jpg"}, str(nm))
    check("news: each headline is looked up once and remembered on disk",
          len(looked) == 2 and again == nm and (news_dir / "cache.json").is_file(), str(looked))
    check("news: picture names are plain hashes (nothing else is served)",
          collectors.NEWS_IMAGE_NAME.fullmatch("0123456789abcdef.jpg") and not collectors.NEWS_IMAGE_NAME.fullmatch("../x.jpg")
          and not collectors.NEWS_IMAGE_NAME.fullmatch("0123456789abcdef.svg"))
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
    open_ports = collectors.parse_listening(
        'tcp LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*\n'
        'tcp LISTEN 0 5 0.0.0.0:8443 0.0.0.0:* users:(("python3",pid=9,fd=3))\n'
        'tcp LISTEN 0 5 [::]:22 [::]:*\ntcp LISTEN 0 5 127.0.0.1:8791 0.0.0.0:*\n'
        'tcp LISTEN 0 5 [::1]:631 [::]:*\n')
    check("open to network: loopback left out, ports in order, process named",
          [(r["port"], r["proc"]) for r in open_ports] == [(22, ""), (8443, "python3")], str(open_ports))
    import datetime as _dt
    today = _dt.date.today().strftime("%Y%m%d")
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:%sT093000\nDTEND:%sT100000\nSUMMARY:Stand-up\nEND:VEVENT\n"
           "BEGIN:VEVENT\nDTSTART:20200101T150000\nDTEND:20200101T160000\nRRULE:FREQ=DAILY\nSUMMARY:Planning\nEND:VEVENT\n"
           "BEGIN:VEVENT\nDTSTART:20200101T080000\nSUMMARY:Long ago\nEND:VEVENT\nEND:VCALENDAR") % (today, today)
    events, _ = collectors._ics_events(ics, _dt.date.today())
    titles = [e["title"] for e in events]
    check("calendar: today's events in time order, old ones left out", titles[:1] == ["Stand-up"] and "Long ago" not in titles, str(titles))
    check("calendar: recurring events when the iCal packages are present",
          "Planning" in titles or not (REPO / ".local" / "mario-pydeps").is_dir(), str(titles))
    check("mail without setup says how to set it up", "install-mario.sh --mail" in collectors.mail({"mail": {}})["error"])
    real_kr = collectors.keyring
    collectors.keyring = lambda **k: ""   # as on a laptop with no calendar saved, whatever this one has
    try:
        no_cal = collectors.calendar({})
    finally:
        collectors.keyring = real_kr
    check("calendar without setup says how to set it up", no_cal.get("setup") is True or "error" in no_cal, str(no_cal))
    import imaplib as _imap
    gp = collectors.mail_login_problem(_imap.IMAP4.error(b"[ALERT] Application-specific password required: https://support.google.com/accounts/answer/185833"))
    check("mail: a Google account password is explained, not shown as b'...'",
          gp["fix"] == "app_password" and "b'" not in gp["error"] and "app password" in gp["error"], str(gp))
    import imaplib as _imap2
    calls = []

    class _Box:
        def __init__(self, *a, **k): pass
        def login(self, u, pw):
            calls.append(pw)
            raise _imap2.IMAP4.error(b"[ALERT] Application-specific password required")
    real_ssl, real_kr = _imap2.IMAP4_SSL, collectors.keyring
    _imap2.IMAP4_SSL, collectors.keyring = _Box, (lambda **k: "abcd efgh ijkl mnop")
    try:
        cfg_m = {"mail": {"user": "me@example.com", "imap_host": "imap.example.invalid"}}
        first, second = collectors.mail(cfg_m), collectors.mail(cfg_m)
    finally:
        _imap2.IMAP4_SSL, collectors.keyring = real_ssl, real_kr
    check("mail: an app password shown with spaces is sent as its 16 letters", calls[:1] == ["abcdefghijklmnop"], str(calls))
    check("mail: a refused password is not sent again", len(calls) == 1 and second["fix"] == "app_password", str(calls))
    real_se = collectors.session_env
    collectors.session_env = lambda: {}
    try:
        boot_mail = collectors.mail({"mail": {"user": "me@example.com"}})
        boot_cal = collectors.calendar({})
    finally:
        collectors.session_env = real_se
    check("before login the keyring is left alone and mail/calendar wait for it",
          boot_mail.get("waiting") and boot_cal.get("waiting") and not boot_mail.get("setup") and not boot_cal.get("setup"),
          str((boot_mail, boot_cal)))
    check("the session's display is read from the user manager, not kept from the hub's start",
          collectors.session_env.__doc__ and "show-environment" in Path(collectors.__file__).read_text())
    accts = collectors.mail_accounts({"mail": {"accounts": ["b@gmail.com", {"user": "c@x.org", "imap_host": "imap.x.org"}, "B@gmail.com"],
                                               "user": "a@gmail.com", "main": "c@x.org"}})
    check("mail: every account once, the main one first, the old one-account form kept",
          [a["user"] for a in accts] == ["c@x.org", "b@gmail.com", "a@gmail.com"] and accts[0]["imap_host"] == "imap.x.org", str(accts))
    check("mail: without 'main' the first account is the main one",
          [a["user"] for a in collectors.mail_accounts({"mail": {"accounts": ["x@gmail.com", "y@gmail.com"]}})] == ["x@gmail.com", "y@gmail.com"])
    real_acct = collectors.mail_account
    fake = {"main@gmail.com": {"user": "main@gmail.com", "unread": 2, "items": [{"from": "A", "subject": "old", "when": 10}]},
            "kk@gmail.com": {"user": "kk@gmail.com", "unread": 5, "items": [{"from": "B", "subject": "new", "when": 20}]},
            "off@gmail.com": {"user": "off@gmail.com", "unread": None, "items": [], "fix": "password", "error": "refused"}}
    collectors.mail_account = lambda user, host="": fake[user]
    try:
        both = collectors.mail({"mail": {"accounts": ["kk@gmail.com", "main@gmail.com", "off@gmail.com"], "main": "main@gmail.com"}})
        down = collectors.mail({"mail": {"accounts": ["off@gmail.com", "kk@gmail.com"]}})
        alone = collectors.mail({"mail": {"accounts": ["off@gmail.com"]}})
    finally:
        collectors.mail_account = real_acct
    check("mail: the main account leads, unread adds up, newest first across accounts",
          both["main"] == "main@gmail.com" and [a["user"] for a in both["accounts"]][0] == "main@gmail.com"
          and both["unread"] == 7 and [i["subject"] for i in both["items"]] == ["new", "old"], str(both)[:300])
    check("mail: one refused account does not hide the others", down["unread"] == 5 and "fix" not in down, str(down)[:200])
    check("mail: with nothing to show, the main account says why", alone["unread"] is None and alone["fix"] == "password")
    import imaplib as _imap3

    class _Gmail:
        capabilities = ("IMAP4REV1", "X-GM-EXT-1")
        def __init__(self, *a, **k): pass
        def login(self, u, pw): return "OK", [b""]
        def select(self, *a, **k): return "OK", [b"2"]
        def search(self, *a): return "OK", [b"1 2"]
        def fetch(self, num, what):
            seen.append(what)
            return "OK", [(b"%s (X-GM-THRID 1849283746123456789 BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {90}" % num,
                           b"From: Asha <asha@example.com>\r\nSubject: Lunch\r\nDate: Thu, 12 Nov 2026 10:00:00 +0530\r\n\r\n"), b")"]
        def logout(self): pass
    seen = []
    real_ssl, real_kr = _imap3.IMAP4_SSL, collectors.keyring
    _imap3.IMAP4_SSL, collectors.keyring = _Gmail, (lambda **k: "pw")
    try:
        one = collectors.mail_account("me@gmail.com")
    finally:
        _imap3.IMAP4_SSL, collectors.keyring = real_ssl, real_kr
    check("mail: each message opens its own conversation in Gmail, in its own account",
          one["items"] and one["items"][0]["link"] == f"https://mail.google.com/mail/u/me@gmail.com/#inbox/{1849283746123456789:x}"
          and one["inbox"] == "https://mail.google.com/mail/u/me@gmail.com/#inbox", str(one)[:300])
    check("mail: still read-only (headers peeked, nothing marked read)", seen and all("BODY.PEEK" in w for w in seen), str(seen))
    check("mail: a refused app password asks for a new one",
          collectors.mail_login_problem(_imap.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)"))["fix"] == "password")
    inbox_dir = Path(cfg["thinking_space"]).parent / "notes-fixture" / "LOOM"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "Inbox.md").write_text("# LOOM inbox\n\n- 2026-11-10 09:00  older\n- [x] 2026-11-11 09:00  done\n- 2026-11-12 09:00  newer\n")
    t = collectors.tasks(cfg, notes_dir=inbox_dir.parent)
    check("tasks: open ones only, newest first, with the project", [x["text"] for x in t["open"]] == ["newer", "older"]
          and t["open"][0]["project"] == "LOOM" and t["count"] == 2, str(t))
    h = collectors.health(cfg)
    check("health: an ok flag and a list of issues", isinstance(h.get("ok"), bool) and isinstance(h.get("issues"), list))
    check("LOOM stopped reads as stopped", collectors.loom({"loom_url": "http://127.0.0.1:9"})["running"] is False)
    xbel = ('<xbel><bookmark href="file://%s" visited="2026-11-11T09:00:00Z"><info><metadata><a:applications xmlns:a="x">'
            '<a:application name="gedit"/></a:applications></metadata></info></bookmark>'
            '<bookmark href="file:///gone/x" visited="2026-11-12T09:00:00Z"/></xbel>') % (Path(cfg["repos"][0]) / "a.txt")
    rec = collectors.parse_xbel(xbel)
    check("recent files: existing only, with the app", len(rec) == 1 and rec[0]["app"] == "gedit" and rec[0]["name"] == "a.txt", str(rec))
    dl = collectors.downloads({"downloads": str(cfg["repos"][0])})
    check("downloads: newest first, hidden files skipped", dl["count"] == 2 and dl["files"][0]["name"] in ("a.txt", "b.txt"))
    check("meminfo", collectors.parse_meminfo("MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n")["used_gb"] == 7.6)
    check("a stopped service reads as stopped, not an error",
          collectors.agent_office({"agent_office_url": "http://127.0.0.1:9"})["running"] is False)


def test_usage(cfg):
    print("AI usage")
    import types
    snap = {"other": {"windows": [{"label": "5h", "used": 90}]},
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
    sick = brain.next_steps({"cards": {"health": {"data": {"ok": False, "issues": ["3 security updates waiting"]}}}, "config": {}})
    check("system trouble shows as a Next step with an Update button",
          sick and sick[0]["action"] == {"id": "launch", "arg": "updates", "label": "Update"}, str(sick))
    check("instant: movie pick", "Predestination" in (brain.quick_answer("Pick a movie for tonight", state) or ""))
    check("instant: anything else goes to a model", brain.quick_answer("explain transformers", state) is None)


def test_engines(cfg):
    print("Who answers")
    check("Claude first, then Gemini, the laptop last", engines.order({}) == ["claude", "gemini", "local"])
    check("the laptop stays the last resort whatever the order says", engines.order({"brain": ["gemini", "bogus"]}) == ["gemini", "local"])
    argv = engines.claude_argv(cfg, "hi", session="s1")
    tools = argv[argv.index("--tools") + 1]
    check("Claude answers with web search and fetch only: nothing runs, nothing changes",
          tools == "WebSearch,WebFetch" and "--resume" in argv and "--system-prompt" in argv and "acceptEdits" not in argv, str(argv))
    g = engines.gemini_argv(cfg, "hi")
    check("Gemini answers read-only (agy plan mode, sandboxed, a Gemini model pinned)",
          g[0] == "agy" and g[g.index("--mode") + 1] == "plan" and "--sandbox" in g and g[g.index("--model") + 1].startswith("gemini"), str(g))
    check("a code hand-off to Gemini edits files in the repo only", engines.handoff_argv("gemini", cfg, "p")[:2] == ["agy", "-p"]
          and "accept-edits" in engines.handoff_argv("gemini", cfg, "p"))
    check("no API key reaches either CLI (they stay on the subscriptions)",
          not {"ANTHROPIC_API_KEY", "GEMINI_API_KEY"} & set(engines.clean_env({"ANTHROPIC_API_KEY": "x", "GEMINI_API_KEY": "y", "PATH": "/bin"})))
    ok = engines.parse_claude(0, json.dumps({"type": "result", "is_error": False, "result": "pong", "session_id": "abc",
                                             "modelUsage": {"claude-haiku-5-5": {}, "claude-sonnet-5-5": {}}}), "")
    check("a Claude answer, its session and model", ok == {"answer": "pong", "session": "abc", "model": "claude-sonnet-5-5"}, str(ok))
    lim = engines.parse_claude(1, json.dumps({"type": "result", "is_error": True, "result": "Claude AI usage limit reached|4102444800"}), "")
    check("Claude at its limit is recognised, with when it lifts", lim.get("limited") and lim.get("until") == 4102444800, str(lim))
    other = engines.parse_claude(1, "", "network down")
    check("other Claude failures are not taken for a limit", not other.get("limited") and "network" in other["error"])
    gok = engines.parse_gemini(0, 'warning: x\n{"conversation_id": "c1", "status": "SUCCESS", "response": "pong\\n"}', "")
    check("a Gemini answer after a warning line", gok.get("answer") == "pong" and gok.get("session") == "c1", str(gok))
    check("Gemini out of quota is recognised", engines.parse_gemini(1, "", "429 RESOURCE_EXHAUSTED Individual quota reached")["limited"])
    usage = {"providers": {"claude": {"windows": [{"label": "5h", "used": 100, "resets": 4102444800}, {"label": "Weekly", "used": 40}]},
                           "gemini": {"windows": [{"label": "5h", "used": 100, "resets": 1}]}}}
    check("the usage tile shows Claude at 100 % until its reset", engines.usage_limit(usage, "claude") == 4102444800)
    check("a window that has reset no longer counts", engines.usage_limit(usage, "gemini") is None)
    ctx = engines.context({"cards": {"calendar": {"data": {"events": [{"start": "10:00", "title": "Stand-up"}]}},
                                     "mail": {"data": {"accounts": [{"user": "main@gmail.com", "unread": 3,
                                                                     "items": [{"from": "Asha", "subject": "Lunch"}]}]}},
                                     "tasks": {"data": {"open": [{"text": "ship it"}], "count": 1}}}})
    check("the model gets the day as context (calendar, mail per account, tasks)",
          "10:00 Stand-up" in ctx and "main@gmail.com: 3 unread" in ctx and "Asha: Lunch" in ctx and "ship it" in ctx, ctx)


async def test_answer(cfg):
    print("Claude first, Gemini at Claude's limit")
    import hub as hub_mod
    hub = hub_mod.Hub(cfg, schedule={})
    hub.brain_dir = Path(cfg["thinking_space"]).parent / "brain"
    ran = []
    replies = {}

    def fake_run(argv, cwd, timeout):
        ran.append(argv[0])
        return replies[argv[0]]

    real_run, real_which = hub_mod.engines.run, hub_mod.shutil.which
    hub_mod.engines.run = fake_run
    hub_mod.shutil.which = lambda c: f"/usr/bin/{c}"
    hub.ask_local = lambda text: {"answer": "from the laptop", "via": "LOOM", "model": "", "ms": 1}
    try:
        replies["claude"] = (0, json.dumps({"is_error": False, "result": "Hello from Claude", "session_id": "s1"}), "")
        first = hub.answer("hello")
        check("Claude answers by default", first["engine"] == "claude" and first["answer"] == "Hello from Claude"
              and ran == ["claude"] and hub.brain_status()["engine"] == "claude", str(first))
        check("and keeps one conversation", hub.sessions["claude"] == "s1")
        replies["claude"] = (1, json.dumps({"is_error": True, "result": "You've hit your usage limit · resets 3pm"}), "")
        replies["agy"] = (0, json.dumps({"conversation_id": "g1", "status": "SUCCESS", "response": "Hello from Gemini"}), "")
        ran.clear()
        second = hub.answer("hello again")
        check("Claude at its limit: Gemini answers, and says why", second["engine"] == "gemini"
              and second["answer"] == "Hello from Gemini" and "limit" in second.get("note", "") and ran == ["claude", "agy"], str(second))
        ran.clear()
        third = hub.answer("and again")
        check("while Claude is at its limit Gemini goes first (no wasted call)", third["engine"] == "gemini" and ran == ["agy"], str(ran))
        status = hub.brain_status()
        check("the ask bar says Gemini, and why", status["engine"] == "gemini" and "limit" in status["skipped"].get("claude", ""), str(status))
        check("a code change goes to Gemini (agy) while Claude is out", hub.handoff_engine() == "gemini")
        replies["agy"] = (1, "", "429 RESOURCE_EXHAUSTED")
        fourth = hub.answer("one more")
        check("both clouds out: the laptop answers", fourth["engine"] == "local" and fourth["answer"] == "from the laptop", str(fourth))
        hub.limited.clear()
        hub.cards["usage"] = {"data": {"providers": {"claude": {"windows": [{"label": "Weekly", "used": 100, "resets": time.time() + 3600}]}}}}
        check("the usage tile alone puts Claude aside until its reset", hub.engine_ready("claude", time.time()) is not None
              and hub.brain_status()["engine"] == "gemini")
        hub.cards.pop("usage")
        hub_mod.shutil.which = lambda c: None
        check("without the CLIs the laptop answers", hub.brain_status()["engine"] == "local")
    finally:
        hub_mod.engines.run, hub_mod.shutil.which = real_run, real_which


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
    hub.notes_file = Path(cfg["thinking_space"]).parent / "notes.md"
    collectors.NOTES_DIR = Path(cfg["thinking_space"]).parent / "notes"
    collectors.NEWS_DIR = Path(cfg["thinking_space"]).parent / "news-hub"
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
                check("dev work comes back as a plan, not a run", res.get("route") == "handoff" and res["handoff"]["status"] == "waiting")
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
            async with s.post(base + "/api/action", json={"id": "launch", "arg": "rm"}) as r:
                check("launchers run only their own commands", (await r.json())["ok"] is False)
            hub.cards["news"] = {"data": {"items": [{"title": "t", "link": "https://news.google.com/a"}]}, "at": 0}
            async with s.post(base + "/api/action", json={"id": "open_news", "arg": "https://evil.example/"}) as r:
                check("only headlines shown on Home open", (await r.json())["ok"] is False)
            hub.cards["news_media"] = {"data": {"media": {"https://news.google.com/a": {"url": "https://www.thehindu.com/a", "image": ""}}}, "at": 0}
            opened = []
            real_popen, real_env = hub_mod.subprocess.Popen, hub_mod.launch_env
            hub_mod.subprocess.Popen = lambda cmd, **k: opened.append(cmd)
            hub_mod.launch_env = lambda: {"DISPLAY": ":0"}
            try:
                async with s.post(base + "/api/action", json={"id": "open_news", "arg": "https://news.google.com/a"}) as r:
                    res_open = await r.json()
            finally:
                hub_mod.subprocess.Popen, hub_mod.launch_env = real_popen, real_env
            check("a headline opens the article itself, not Google's redirect page",
                  res_open.get("ok") and opened == [["xdg-open", "https://www.thehindu.com/a"]], str((res_open, opened)))
            img_dir = collectors.NEWS_DIR / "img"
            img_dir.mkdir(parents=True, exist_ok=True)
            (img_dir / "0123456789abcdef.jpg").write_bytes(b"\xff\xd8" + b"0" * 3000)
            async with s.get(base + "/news-img/0123456789abcdef.jpg") as r:
                check("news pictures are served by the hub", r.status == 200 and r.content_type == "image/jpeg")
            async with s.get(base + "/news-img/..%2F..%2Fcache.json") as r:
                check("and nothing else from that folder", r.status == 404)
            async with s.post(base + "/api/action", json={"id": "open_file", "arg": "/etc/shadow"}) as r:
                check("only files shown on Home open", (await r.json())["ok"] is False)
            async with s.post(base + "/api/task", json={"text": "  write   the hub docs "}) as r:
                check("a task is added to the General inbox", (await r.json())["ok"] is True)
            inbox = collectors.NOTES_DIR / "General" / "Inbox.md"
            check("in the Quick Note format", inbox.read_text().rstrip().endswith("  write the hub docs"))
            open_tasks = collectors.tasks(cfg)["open"]
            mine = next(t for t in open_tasks if t["text"] == "write the hub docs")
            async with s.post(base + "/api/task/done", json={"path": "/etc/passwd", "line": 0}) as r:
                check("ticking works only inside Quick Note inboxes", (await r.json())["ok"] is False)
            async with s.post(base + "/api/task/done", json={"path": mine["path"], "line": mine["line"]}) as r:
                check("a task is ticked", (await r.json())["ok"] is True)
            check("and leaves the open list", all(t["text"] != "write the hub docs" for t in collectors.tasks(cfg)["open"]))
            check("ticked as - [x], text kept", "- [x] " in inbox.read_text() and "write the hub docs" in inbox.read_text())
            async with s.post(base + "/api/note", json={"text": "  try   whichllm  "}) as r:
                check("a jotted note is saved", (await r.json())["ok"] is True)
            async with s.get(base + "/api/state") as r:
                notes = (await r.json())["cards"]["notes"]["data"]["items"]
            check("notes come back newest first, tidied", notes and notes[0].endswith("· try whichllm"), str(notes))
    finally:
        await runner.cleanup()


def test_page():
    print("Page and host")
    js = REPO / "apps" / "mario-home" / "static" / "home.js"
    if shutil.which("node"):
        out = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        check("home.js parses", out.returncode == 0, out.stderr[:200])
    html = (REPO / "apps" / "mario-home" / "static" / "index.html").read_text()
    host_text = (REPO / "apps" / "mario-home" / "host.py").read_text()
    import re as _re
    script = js.read_text()
    css = (REPO / "apps" / "mario-home" / "static" / "home.css").read_text()
    cards = _re.findall(r'id="c-([a-z]+)"', html)
    want = ["mail", "today", "tasks", "projects", "thinking", "recent", "note", "weather", "ai", "phone", "news", "week", "next"]
    check("Your day has its thirteen cards, once each", sorted(cards) == sorted(want), str(cards))
    for gone in ("apps", "focus", "downloads", "reels", "system", "loom", "tonight", "cook", "trynext", "agents", "exposure", "usage", "quick"):
        check(f"no {gone} card", f'id="c-{gone}"' not in html)
    drawn = set(_re.findall(r"^  (\w+)\(\) \{", script, _re.M))
    check("every card is drawn", all(c in drawn for c in want if c != "apps"), str([c for c in want if c not in drawn]))
    sys.path.insert(0, str(REPO / "services" / "mario-hub"))
    import hub as hub_mod
    launches = _re.findall(r'data-launch="([a-z]+)"', html)
    check("every app button is a known command", all(k in hub_mod.LAUNCH for k in launches),
          str([k for k in launches if k not in hub_mod.LAUNCH]))
    check("Code and Screenshot use programs this kind of laptop has (Antigravity IDE, Adaptive Annotate)",
          hub_mod.LAUNCH["screenshot"][-1].endswith(("adaptive-annotate/main.py", "--interactive"))
          and hub_mod.editor()[0] != "" and hub_mod.LAUNCH["code"] == hub_mod.editor())
    check("Home leaves the dock's band free at the bottom",
          _re.search(r"\.home \{ --dock: (\d+)px;[^}]*padding: [^;]*var\(--dock\)", css) is not None
          and int(_re.search(r"--dock: (\d+)px", css).group(1)) >= 66)
    check("the mail fix opens Google's app-password page, and the hub allows it",
          "https://myaccount.google.com/apppasswords" in script
          and "https://myaccount.google.com/apppasswords".startswith(hub_mod.OPEN_URL_PREFIXES))
    opens = _re.findall(r'data-open="([^"]+)"', html)
    for gone in ("downloads", "lock"):
        check(f"no {gone} button", f'data-launch="{gone}"' not in html)
    check("Projects, Thinking Space and Recent files are one column wide; Quick note runs down both rows",
          all(_re.search(rf'class="card narrow" id="c-{c}"', html) for c in ("projects", "thinking", "recent"))
          and "repeat(4, minmax(0, 1fr))" in css and "#c-thinking { grid-area: 1 / 2; }" in css
          and "#c-note { grid-area: 1 / 3 / 3 / 4; }" in css)
    check("the page never scrolls; lists scroll inside their tiles",
          _re.search(r"html, body \{[^}]*overflow: hidden", css) is not None and "[hidden] { display: none !important; }" in css
          and _re.search(r"\.rows, \.timeline, \.boards[^{]*\{[^}]*overflow-y: auto", css) is not None
          and ".home { overflow: auto; }" not in css)
    check("talking to Mario draws the microphone's level; the panel comes in when Super+J shows it",
          "voicePhase(" in script and "result.level" in script and "@keyframes drift" in css and "@keyframes panel-in" in css
          and "window.marioShown" in script and "marioShown" in host_text and "fade_in(" in host_text)
    check("no 'all systems up to date' line", "all systems up to date" not in script.lower() and 'id="status"' not in html)
    check("News rolls every 30 seconds", 'setFaces("news", items.map(face), { every: 30000' in script)
    check("News shows each headline's picture, cover-fitted edge to edge, from the hub",
          "/news-img/" in script and 'newsPic(it, "hero")' in script and _re.search(r"\.hero img \{[^}]*object-fit: cover", css))
    check("a mail opens its own conversation; the main account shows first",
          "openUrl(i.link || inbox)" in script and "accounts[0]" in script)
    check("the ask bar says who answers (Claude first), not the old local-first brain",
          "LOOM ready" not in script and "answers locally first" not in script + html and 'id="brain"' in html)
    check("live tiles turn on their own and pause under the pointer",
          "setInterval(" in script and ':hover' in script and all(f'setFaces("{c}"' in script for c in ("projects", "recent", "week", "weather")))
    host = (REPO / "apps" / "mario-home" / "host.py").read_text()
    check("Home is a layer you summon, not the desktop: above the windows, off the taskbar, hidden until asked",
          all(x in host for x in ("WindowTypeHint.DOCK", "set_skip_taskbar_hint(True)", "get_workarea()", "--background",
                                  "HANDLES_COMMAND_LINE", "def hide_home", "notify::is-active"))
          and "WindowTypeHint.DESKTOP" not in host)
    check("Home's tabs: Today is the page, sites get their own view and profile, outside links go to the browser",
          all(x in host for x in ("script-message-received::home", "add_overlay", "set_persistent_storage", "launch_default_for_uri"))
          and all(x in script for x in ("window.homeSpace", "selectTab(", 'tell({ type: "tab"', "webRect()")))
    toggle = (REPO / "scripts" / "adaptive-home.sh").read_text()
    entry = (REPO / "apps" / "mario-home" / "adaptive-mario-home.desktop").read_text()
    check("Super+H sends a message to the running Home and starts it only when there is none",
          "org.gtk.Actions.Activate" in toggle and "com.karthi.MarioHome" in toggle and "host.py" in toggle
          and "--background" in entry)
    gestures = (REPO / "scripts" / "adaptive-gestures.py").read_text()
    check("showing the desktop (double Ctrl) sends Home away too, leaving the wallpaper",
          '"hide", "[]", "{}"' in gestures and "com.karthi.MarioHome" in gestures)
    check("Home's ground is the blurred wallpaper the hub serves",
          '"/glass.png"' in (REPO / "services" / "mario-hub" / "hub.py").read_text() and "/glass.png?" in script and ".backdrop" in css)
    keys = (REPO / "scripts" / "install-keybindings.sh").read_text()
    check("Mario is on Super+J and Super+Space stays the keyboard-layout switch",
          '"adaptive-mario" "Mario"' in keys and '--panel" "<Super>j"' in keys
          and 'adaptive-home.sh" "<Super>h"' in keys and """minimize "['<Super><Alt>h']\"""" in keys
          and "claim_accelerator org.gnome.desktop.wm.keybindings switch-input-source '<Super>space'" in keys
          and "release_accelerator org.gnome.desktop.wm.keybindings switch-input-source" not in keys)
    check("header links open only allowed sites", all(u.startswith(hub_mod.OPEN_URL_PREFIXES) for u in opens), str(opens))
    check("cards draw through fill(), which drops empty slots", script.count(".replaceChildren(") <= 3)
    check("page has the panel and its script", "panel-form" in html and "/static/home.js" in html)
    check("no innerHTML in the page script", "innerHTML" not in script)
    try:
        py_compile.compile(str(REPO / "apps" / "mario-home" / "host.py"), doraise=True)
        check("host.py compiles", True)
    except py_compile.PyCompileError as exc:
        check("host.py compiles", False, str(exc))


async def test_after_boot(cfg):
    print("After a restart")
    import hub as hub_mod
    calls = {"n": 0}

    def waiting(_cfg):
        calls["n"] += 1
        return {"waiting": True, "n": calls["n"]}

    real_wait, real_se = hub_mod.WAIT_RETRY_S, hub_mod.collectors.session_env
    hub_mod.WAIT_RETRY_S = 0.05
    hub = hub_mod.Hub(cfg, schedule={"mail": (waiting, 3600)})
    task = asyncio.create_task(hub.run_collector("mail"))
    await asyncio.sleep(0.4)
    task.cancel()
    hub_mod.WAIT_RETRY_S = real_wait
    check("a card waiting for the login looks again within seconds, not at its usual interval", calls["n"] >= 3, str(calls))
    hub_mod.collectors.session_env = lambda: {}
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        saved = dict(os.environ)
        os.environ.clear(); os.environ.update(env)
        out = hub.action("launch", "calculator")
    finally:
        os.environ.clear(); os.environ.update(saved)
        hub_mod.collectors.session_env = real_se
    check("with nobody logged in a launcher says so instead of failing silently", out["ok"] is False and "session" in out["error"], str(out))
    hub_mod.collectors.session_env = lambda: {"DISPLAY": ":7", "XAUTHORITY": "/x"}
    try:
        check("programs open on the display of the current login", hub_mod.launch_env()["DISPLAY"] == ":7")
    finally:
        hub_mod.collectors.session_env = real_se


def main():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, work = fixture(Path(tmp))
        test_collectors(cfg, work)
        test_usage(cfg)
        test_brain(cfg, work)
        test_engines(cfg)
        try:
            import aiohttp  # noqa: F401
            asyncio.run(test_answer(cfg))
            asyncio.run(test_hub(cfg))
            asyncio.run(test_after_boot(cfg))
        except ImportError:
            print("  skip hub checks: python3-aiohttp is not installed")
    test_page()
    print(f"\n{'all passed' if not FAILED else f'{len(FAILED)} failed: ' + ', '.join(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
