"""Home's own tiles: Movies, Storage, Spotify, Photos, the sticky note and the accounts.

Each collector here returns one plain dict like those in collectors.py; the functions that change
something (mark a film watched, clear a cache, press play, save the sticky) are called by the hub's
POST handlers and say what they did. Nothing here needs a Google sign-in:

- Movies reads the Google Sheet's mirror in the Thinking Space checkout (movies-shows.csv) and keeps
  "watched" marks on this laptop, laid over the Sheet's own Status column.
- Photos reads a Google Photos shared album (the link you paste) and keeps copies in the data folder.
- Spotify is the desktop app, over the session bus (MPRIS).
- Calendars are private iCal addresses in the keyring, one per account.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import collectors
import config as config_mod

DATA_DIR = config_mod.DATA_DIR


def _read_json(path, default):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    tmp.replace(path)


# ------------------------------------------------------------------ movies

MOVIE_MARKS = DATA_DIR / "movies.json"
MOVIE_TYPES = ("movie", "series", "short drama")      # a "List" row is a reel naming several titles


def movie_marks(path=None):
    return _read_json(path or MOVIE_MARKS, {})


def mark_movie(title, watched, path=None):
    """Remember that a title was watched (or was not, after all). Kept here, over the Sheet."""
    title = " ".join(str(title or "").split())
    if not title:
        return {"ok": False, "error": "no title"}
    marks = movie_marks(path)
    marks[title] = {"watched": bool(watched), "at": int(time.time())}
    _write_json(path or MOVIE_MARKS, marks)
    return {"ok": True}


def movies(cfg, today=None, marks_path=None):
    """What to watch: one pick for today and one for tomorrow from the titles still unwatched that a
    subscription carries, then the whole list with its marks."""
    data = cfg["thinking_space"] / "reels" / "data"
    rows = collectors._rows(data / "movies-shows.csv")
    if not rows:
        return {"setup": True, "items": [],
                "error": "No movies-shows.csv in the Thinking Space checkout (the Sheet's nightly mirror)."}
    marks = movie_marks(marks_path)
    items, seen = [], set()
    for r in rows:
        title = (r.get("Title") or "").strip()
        if not title or title in seen or (r.get("Type") or "").strip().lower() not in MOVIE_TYPES:
            continue
        seen.add(title)
        where = (r.get("Where to watch in India") or "").strip()
        service = next((s for s in collectors.SUBSCRIPTIONS if s in where), "")
        mark = marks.get(title)
        in_sheet = (r.get("Status") or "").strip().lower() in collectors.DONE_STATUSES
        items.append({"title": title, "year": (r.get("Year") or "").strip(), "type": (r.get("Type") or "").strip(),
                      "where": service or where[:48],
                      "included": bool(service) and not where.lower().startswith("rent"),
                      "watched": mark["watched"] if mark else in_sheet, "marked": bool(mark)})
    left = [i for i in items if not i["watched"]]
    queue = [i for i in left if i["included"]] or left
    day = (today or dt.date.today()).toordinal()
    pick = lambda n: queue[(day + n) % len(queue)]["title"] if queue else ""  # noqa: E731
    items.sort(key=lambda i: (i["watched"], not i["included"]))
    return {"today": pick(0), "tomorrow": pick(1) if len(queue) > 1 else "", "items": items,
            "left": len(left), "watched": len(items) - len(left), "total": len(items),
            "sheet": collectors._sheet_link(data.parent)}


# ----------------------------------------------------------------- storage

def _du(path, timeout=30):
    """Bytes under `path` on its own filesystem, or None (missing, unreadable, too slow)."""
    if not Path(path).exists():
        return None
    try:
        out = subprocess.run(["du", "-sxk", str(path)], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    first = (out.stdout or "").split("\t")[0].strip()      # du still prints a total past unreadable files
    return int(first) * 1024 if first.isdigit() else None


def _old_tmp(days=7):
    """Your own entries directly in /tmp that nothing has written to for `days` days."""
    cutoff, mine, out = time.time() - days * 86400, os.getuid(), []
    try:
        entries = list(os.scandir("/tmp"))
    except OSError:
        return out
    for e in entries:
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if st.st_uid == mine and st.st_mtime < cutoff and not e.name.startswith((".X", ".ICE", "systemd-", "snap-")):
            out.append(e.path)
    return out


def storage_places(home=None):
    """What can take space back: id -> (label, path, hint, how). how: "clear" (Home may empty it),
    "admin:<command>" (needs your password, so Home only names the command), or "open"."""
    home = Path(home or Path.home())
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return {
        "trash": ("Trash", home / ".local/share/Trash", "Files you already deleted", "clear"),
        "thumbnails": ("Thumbnails", cache / "thumbnails", "Rebuilt as you browse folders", "clear"),
        "pip": ("pip cache", cache / "pip", "Python packages, downloaded again when needed", "clear"),
        "npm": ("npm cache", home / ".npm" / "_cacache", "Node packages, downloaded again when needed", "clear"),
        "gradle": ("Gradle caches", home / ".gradle" / "caches", "The next Android build downloads them again", "clear"),
        "tmp": ("Old temporary files", Path("/tmp"), "Yours in /tmp, untouched for a week", "clear"),
        "chrome": ("Chrome cache", cache / "google-chrome", "Clear it from Chrome's settings", "open"),
        "cache": ("Other app caches", cache, "Everything else in ~/.cache", "open"),
        "downloads": ("Downloads", home / "Downloads", "Sort through what you no longer need", "open"),
        "apt": ("Package downloads", Path("/var/cache/apt/archives"), "Installers apt already used", "admin:sudo apt clean"),
        "journal": ("System logs", Path("/var/log/journal"), "The system journal", "admin:sudo journalctl --vacuum-time=2weeks"),
    }


def storage(cfg, home=None, folders=True):
    """The disk, what is taking it, and what would give some back."""
    home = Path(home or Path.home())
    try:
        disk = shutil.disk_usage(home)
    except OSError as exc:
        return {"error": str(exc), "places": []}
    table = storage_places(home)
    sizes = {}
    for key, (_label, path, _hint, _how) in table.items():
        if key == "tmp":
            sizes[key] = sum(filter(None, (_du(p, 10) for p in _old_tmp()[:200]))) or 0
        else:
            sizes[key] = _du(path)
    # "other caches" is what is left of ~/.cache once the caches named above are taken out
    if sizes.get("cache") is not None:
        inside = sum(sizes.get(k) or 0 for k in ("thumbnails", "pip", "chrome"))
        sizes["cache"] = max(0, sizes["cache"] - inside)
    places = []
    for key, (label, path, hint, how) in table.items():
        size = sizes.get(key)
        if not size or size < 1024 * 1024:           # under a megabyte is not worth a row
            continue
        places.append({"id": key, "label": label, "bytes": size, "hint": hint, "path": str(path),
                       "clear": how == "clear", "admin": how[6:] if how.startswith("admin:") else ""})
    places.sort(key=lambda p: -p["bytes"])
    top = []
    if folders:
        try:
            out = subprocess.run(["du", "-xk", "-d1", str(home)], capture_output=True, text=True, timeout=120)
            for line in (out.stdout or "").splitlines():
                kb, _, path = line.partition("\t")
                if kb.isdigit() and path and Path(path) != home:
                    top.append({"name": Path(path).name, "bytes": int(kb) * 1024, "path": path})
        except (OSError, subprocess.SubprocessError):
            top = []
        top = sorted(top, key=lambda f: -f["bytes"])[:8]
    return {"total": disk.total, "used": disk.used, "free": disk.free,
            "pct": round(disk.used * 100 / disk.total, 1) if disk.total else 0,
            "reclaim": sum(p["bytes"] for p in places if p["clear"]), "places": places, "folders": top}


def clear_storage(key, home=None):
    """Empty one of the places Home may empty. Returns what happened; never touches anything else."""
    entry = storage_places(home).get(str(key))
    if not entry or entry[3] != "clear":
        return {"ok": False, "error": "Home does not clear that one"}
    _label, path, _hint, _how = entry
    before = _du(path) or 0
    try:
        if key == "trash":
            if shutil.which("gio"):
                subprocess.run(["gio", "trash", "--empty"], timeout=120, env={**os.environ, **collectors.session_env()},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                targets = [p for sub in ("files", "info") for p in (path / sub).glob("*")]
                _remove(targets)
        elif key == "tmp":
            _remove(_old_tmp())
        else:
            _remove(list(path.iterdir()) if path.is_dir() else [])
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)[:160]}
    after = 0 if key == "tmp" else (_du(path) or 0)
    return {"ok": True, "freed": max(0, before - after)}


def _remove(paths):
    for p in paths:
        p = Path(p)
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
        except OSError:
            continue


# ----------------------------------------------------------------- spotify

MPRIS = "org.mpris.MediaPlayer2"


def _bus():
    """The session bus of the desktop you are logged in to (the hub may have started before it)."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    address = collectors.session_env().get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("DBUS_SESSION_BUS_ADDRESS") \
        or f"unix:path=/run/user/{os.getuid()}/bus"
    flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    return Gio.DBusConnection.new_for_address_sync(address, flags, None, None)


def _call(bus, dest, path, iface, method, args=None, timeout=1500):
    from gi.repository import Gio
    return bus.call_sync(dest, path, iface, method, args, None, Gio.DBusCallFlags.NO_AUTO_START, timeout, None)


def pick_player(names):
    """Spotify itself, else a browser tab or any other player the session has."""
    players = sorted(n for n in names if n.startswith(MPRIS + "."))
    return next((n for n in players if "spotify" in n.lower()), players[0] if players else "")


def now_playing(props):
    """MPRIS player properties -> what the tile shows."""
    meta = props.get("Metadata") or {}
    artists = meta.get("xesam:artist") or []
    return {"status": props.get("PlaybackStatus") or "Stopped", "title": meta.get("xesam:title") or "",
            "artist": ", ".join(artists) if isinstance(artists, (list, tuple)) else str(artists),
            "album": meta.get("xesam:album") or "", "art_src": meta.get("mpris:artUrl") or "",
            "length": round((meta.get("mpris:length") or 0) / 1e6), "position": round((props.get("Position") or 0) / 1e6),
            "link": meta.get("xesam:url") or "", "can_next": bool(props.get("CanGoNext", True)),
            "can_previous": bool(props.get("CanGoPrevious", True))}


def spotify_bin():
    """The Spotify app's launcher, also where a service's PATH does not reach (snap, flatpak)."""
    for cand in (shutil.which("spotify"), "/snap/bin/spotify", "/var/lib/flatpak/exports/bin/com.spotify.Client",
                 str(Path.home() / ".local/share/flatpak/exports/bin/com.spotify.Client")):
        if cand and Path(cand).exists():
            return cand
    return ""


def spotify(cfg):
    """What Spotify is playing, from the desktop app over the session bus."""
    from gi.repository import GLib
    installed = bool(spotify_bin())
    try:
        bus = _bus()
        names = _call(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames").unpack()[0]
        player = pick_player(names)
        if not player:
            return {"running": False, "installed": installed}
        props = _call(bus, player, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll",
                      GLib.Variant("(s)", (MPRIS + ".Player",))).unpack()[0]
    except Exception as exc:  # noqa: BLE001  no session bus yet, or the player went away mid-call
        return {"running": False, "installed": installed, "error": str(exc)[:120]}
    data = now_playing(props)
    art = ""
    src = data.pop("art_src")
    if src.startswith("https://"):
        name = hashlib.sha1(src.encode()).hexdigest()[:16]
        have = next((p.name for p in (collectors.NEWS_DIR / "img").glob(name + ".*") if p.suffix != ".part"), "")
        art = have or collectors.save_news_image(src)
    return {"running": True, "installed": installed, "player": player.rsplit(".", 1)[-1].split(".instance")[0],
            "is_spotify": "spotify" in player.lower(), "art": art, **data}


def spotify_control(cmd):
    method = {"playpause": "PlayPause", "next": "Next", "previous": "Previous"}.get(str(cmd))
    if not method:
        return {"ok": False, "error": "unknown control"}
    try:
        bus = _bus()
        names = _call(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames").unpack()[0]
        player = pick_player(names)
        if not player:
            return {"ok": False, "error": "Nothing is playing. Open Spotify first."}
        _call(bus, player, "/org/mpris/MediaPlayer2", MPRIS + ".Player", method)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:120]}
    return {"ok": True}


# ------------------------------------------------------------------ photos

PHOTOS_DIR = DATA_DIR / "photos"
PHOTO_NAME = re.compile(r"[0-9a-f]{16}\.jpg")
ALBUM_PREFIXES = ("https://photos.app.goo.gl/", "https://photos.google.com/share/")
# an item in the album page's data: ["<id>",["https://lh3.googleusercontent.com/pw/...",width,height,
ALBUM_ITEM = re.compile(r'\["(https://lh3\.googleusercontent\.com/pw/[A-Za-z0-9_\-]+)",(\d+),(\d+)')
ALBUM_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')


def parse_album(html):
    """A shared album's page -> (title, [{src, w, h}]) in the album's order, each picture once."""
    import html as html_mod
    title = ALBUM_TITLE.search(html)
    items, seen = [], set()
    for src, w, h in ALBUM_ITEM.findall(html):
        if src not in seen and int(w) >= 200 and int(h) >= 200:      # smaller ones are owner avatars
            seen.add(src)
            items.append({"src": src, "w": int(w), "h": int(h)})
    return (html_mod.unescape(title.group(1)) if title else ""), items


def photos(cfg, folder=None, fetch=None, per_run=24):
    """The pictures of your shared Google Photos album, copied here so the tile needs no network to
    turn. New pictures arrive a batch per run; ones taken out of the album are removed."""
    album = str((cfg.get("photos") or {}).get("album") or "")
    limit = int((cfg.get("photos") or {}).get("max") or 60)
    if not album.startswith(ALBUM_PREFIXES):
        return {"setup": True, "items": []}
    folder = Path(folder or PHOTOS_DIR)
    fetch = fetch or collectors._fetch
    try:
        _, _kind, body = fetch(album, 6_000_000, {"User-Agent": collectors.NEWS_UA}, timeout=20)
        title, found = parse_album(body.decode(errors="replace"))
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", None) in (404, 410):     # Google answered: the link itself is gone
            return {"album": album, "items": [], "fix": True,
                    "error": "That album link no longer opens. It may have been unshared; paste a new link."}
        kept = sorted(p.name for p in folder.glob("*.jpg"))
        return {"album": album, "items": [{"name": n} for n in kept], "waiting": True,
                "error": f"Can't reach Google Photos right now ({str(exc)[:60]})."}
    if not found:
        return {"album": album, "items": [], "fix": True,
                "error": "No pictures found at that link. Share the album (\"Create link\") and paste that link."}
    folder.mkdir(parents=True, exist_ok=True)
    items, fetched = [], 0
    for it in found[:limit]:
        name = hashlib.sha1(it["src"].encode()).hexdigest()[:16] + ".jpg"
        if not (folder / name).exists():
            if fetched >= per_run:
                continue
            try:
                _, kind, data = fetch(it["src"] + "=w1600-h1200-rj", 8_000_000, {"User-Agent": collectors.NEWS_UA}, timeout=25)
            except Exception:  # noqa: BLE001
                continue
            if not str(kind).startswith("image/") or len(data) < 2000:
                continue
            tmp = folder / (name + ".part")
            tmp.write_bytes(data)
            tmp.replace(folder / name)
            fetched += 1
        items.append({"name": name, "w": it["w"], "h": it["h"]})
    keep = {i["name"] for i in items}
    if len(found) <= limit or len(keep) >= limit:
        for p in folder.glob("*.jpg"):
            if p.name not in keep:
                p.unlink(missing_ok=True)
                (folder / "thumbs" / p.name).unlink(missing_ok=True)
    return {"album": album, "title": title, "items": items, "count": len(found),
            "more": len([f for f in found[:limit]]) - len(items)}


def photo_thumb(name, folder=None, size=(240, 180)):
    """A small copy of one picture for the viewer's strip, made once and kept beside the pictures.
    Without Pillow, or for a file it cannot read: the picture itself."""
    folder = Path(folder or PHOTOS_DIR)
    full, small = folder / name, folder / "thumbs" / name
    try:
        if small.is_file() and small.stat().st_mtime >= full.stat().st_mtime:
            return small
        from PIL import Image, ImageOps
        with Image.open(full) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail(size)
            small.parent.mkdir(parents=True, exist_ok=True)
            tmp = small.with_suffix(".part")
            im.save(tmp, "JPEG", quality=80)
            tmp.replace(small)
        return small
    except Exception:  # noqa: BLE001
        return full


# ------------------------------------------------------------- sticky note

STICKY = DATA_DIR / "sticky.md"
STICKY_MAX = 6000
TIDY_PROMPT = ("Tidy this scribbled sticky note into clean notes. Keep every fact, name, number and date; "
               "fix wording and spelling; group related points under short headings where it helps; turn "
               "things to do into '- [ ]' lines. Answer with the Markdown note only, no preamble.\n\n"
               "[Sticky note]\n")


def read_sticky(path=None):
    try:
        return Path(path or STICKY).read_text(encoding="utf-8")[:STICKY_MAX]
    except OSError:
        return ""


def write_sticky(text, path=None):
    path = Path(path or STICKY)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(str(text or "")[:STICKY_MAX], encoding="utf-8")
    tmp.replace(path)
    return {"ok": True}


def notes_dir(cfg):
    """Where notes are filed: "notes_dir" in mario.json (config.py's default is ~/Documents/Mario
    Notes). A settings dict without it files nothing, so a check with made-up settings can never
    write into your Documents."""
    where = cfg.get("notes_dir")
    return Path(os.path.expanduser(str(where))) if where else None


def file_note(cfg, text, heading="", now=None):
    """Add a note to today's page of Mario Notes -> that file."""
    now = now or dt.datetime.now()
    folder = notes_dir(cfg)
    if folder is None:
        raise OSError("no notes folder is set (notes_dir)")
    folder.mkdir(parents=True, exist_ok=True)
    page = folder / f"{now:%Y-%m-%d}.md"
    start = "" if page.exists() else f"# {now:%A, %d %B %Y}\n"
    with open(page, "a", encoding="utf-8") as f:
        f.write(f"{start}\n## {now:%H:%M}{' · ' + heading if heading else ''}\n\n{str(text).strip()}\n")
    return page


def rough_tidy(text):
    """Without anyone to ask: the scribble as a plain list, one point per line."""
    lines = [re.sub(r"^[-*•\d.)\s]+", "", ln).strip() for ln in str(text).splitlines()]
    return "\n".join(f"- {ln[0].upper() + ln[1:]}" for ln in lines if ln)


def sticky_state(cfg, path=None):
    folder = notes_dir(cfg)
    page = folder / f"{dt.date.today():%Y-%m-%d}.md" if folder else None
    try:
        filed = len(re.findall(r"^## ", page.read_text(encoding="utf-8"), flags=re.M)) if page else 0
    except OSError:
        filed = 0
    return {"text": read_sticky(path), "filed": filed, "folder": str(folder or ""), "page": str(page) if filed else ""}


# ---------------------------------------------------------------- accounts

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
ICAL = re.compile(r"https://[^\s]+", re.I)


def account_list(cfg):
    """Every account with what is synced for it: {user, imap_host, mail, calendar, main}. Both
    switches are on unless mario.json says otherwise."""
    m = cfg.get("mail") or {}
    host = m.get("imap_host") or "imap.gmail.com"
    raw = m.get("accounts") or ([m["user"]] if m.get("user") else [])
    out, seen = [], set()
    for a in raw:
        a = a if isinstance(a, dict) else {"user": a}
        user = str(a.get("user") or "").strip()
        if not user or user in seen:
            continue
        seen.add(user)
        out.append({"user": user, "imap_host": a.get("imap_host") or host,
                    "mail": a.get("mail", True) is not False, "calendar": a.get("calendar", True) is not False})
    main = m.get("main") if m.get("main") in seen else (out[0]["user"] if out else "")
    out.sort(key=lambda a: a["user"] != main)
    for a in out:
        a["main"] = a["user"] == main
    return out


def calendar_feeds(cfg, lookup=None):
    """The iCal addresses to read: one per account whose calendar is synced. The address saved
    before accounts existed (keyring account "ical") belongs to the main account."""
    lookup = lookup or collectors.keyring
    feeds = []
    for a in account_list(cfg):
        url = lookup(service="mario-calendar", account=a["user"]) or (lookup(service="mario-calendar", account="ical")
                                                                      if a["main"] else "")
        if url and a["calendar"]:
            feeds.append({"user": a["user"], "url": url})
    if not account_list(cfg):
        url = lookup(service="mario-calendar", account="ical")
        if url:
            feeds.append({"user": "", "url": url})
    return feeds


def accounts(cfg):
    """The accounts as Home's account sheet shows them, with what each still needs."""
    out = []
    try:
        for a in account_list(cfg):
            has_cal = bool(collectors.keyring(service="mario-calendar", account=a["user"])
                           or (a["main"] and collectors.keyring(service="mario-calendar", account="ical")))
            out.append({"user": a["user"], "main": a["main"], "mail": a["mail"], "calendar": a["calendar"],
                        "has_password": bool(collectors.keyring(service="mario-mail", account=a["user"])),
                        "has_calendar": has_cal})
    except collectors.KeyringNotReady:
        return {"waiting": True, "error": collectors.KEYRING_WAIT,
                "accounts": [{"user": a["user"], "main": a["main"], "mail": a["mail"], "calendar": a["calendar"]}
                             for a in account_list(cfg)]}
    return {"accounts": out}


def store_secret(service, account, secret, label):
    """Into the GNOME keyring, on standard input: never an argument, never logged."""
    env = collectors.session_env()
    if not shutil.which("secret-tool") or not env:
        return "The keyring is not available (libsecret-tools, and a logged-in session)."
    try:
        done = subprocess.run(["secret-tool", "store", f"--label={label}", "service", service, "account", account],
                              input=str(secret), text=True, capture_output=True, timeout=10, env={**os.environ, **env})
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)[:120]
    return "" if done.returncode == 0 else (done.stderr.strip()[:120] or "The keyring refused it.")


def clear_secret(service, account):
    env = collectors.session_env()
    if shutil.which("secret-tool") and env:
        subprocess.run(["secret-tool", "clear", "service", service, "account", account], capture_output=True,
                       timeout=10, env={**os.environ, **env})


def edit_accounts(cfg_file, op, user="", what="", on=True, secret="", store=store_secret, clear=clear_secret):
    """One change to the accounts in mario.json (and the keyring for a secret). Returns {ok} or {error}."""
    user = str(user or "").strip()
    if not EMAIL.fullmatch(user):
        return {"ok": False, "error": "That is not an email address."}
    raw = _read_json(cfg_file, {})
    mail = raw.get("mail") if isinstance(raw.get("mail"), dict) else {}
    current = account_list({"mail": mail})
    entries = {a["user"]: {"user": a["user"], "mail": a["mail"], "calendar": a["calendar"],
                           **({"imap_host": a["imap_host"]} if a["imap_host"] != (mail.get("imap_host") or "imap.gmail.com") else {})}
               for a in current}
    main = next((a["user"] for a in current if a["main"]), "")
    if op == "add":
        if user in entries:
            return {"ok": False, "error": "That account is already here."}
        entries[user] = {"user": user, "mail": True, "calendar": True}
        main = main or user
    elif user not in entries:
        return {"ok": False, "error": "No such account."}
    elif op == "remove":
        entries.pop(user)
        clear("mario-mail", user)
        clear("mario-calendar", user)
        main = main if main != user else next(iter(entries), "")
    elif op == "main":
        main = user
    elif op == "sync" and what in ("mail", "calendar"):
        entries[user][what] = bool(on)
    elif op == "secret" and what in ("mail", "calendar"):
        secret = str(secret or "").strip()
        if what == "mail":
            secret = secret.replace(" ", "")          # Google shows app passwords in four groups
            if len(secret) < 8:
                return {"ok": False, "error": "That is too short for an app password."}
        elif not ICAL.fullmatch(secret) or ".ics" not in secret:
            return {"ok": False, "error": "Paste the calendar's \"Secret address in iCal format\" (it ends in .ics)."}
        problem = store(f"mario-{what}", user, secret,
                        f"Mario {what} {user}" + (" (IMAP app password)" if what == "mail" else " (private iCal address)"))
        if problem:
            return {"ok": False, "error": problem}
        entries[user][what] = True
    else:
        return {"ok": False, "error": "unknown change"}
    mail = {k: v for k, v in mail.items() if k not in ("user", "accounts", "main")}
    mail.update({"accounts": list(entries.values()), "main": main})
    raw["mail"] = mail
    _write_json(cfg_file, raw)
    return {"ok": True}


def _location(host, path, address=None, timeout=10):
    """Where https://host/path redirects to. With `address`, connect there but still as `host`:
    the certificate is checked against the name, so a wrong address cannot pass for Google."""
    import http.client
    import socket
    import ssl
    raw = socket.create_connection((address or host, 443), timeout=timeout)
    conn = http.client.HTTPSConnection(host, timeout=timeout)
    conn.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    try:
        conn.request("GET", path, headers={"User-Agent": collectors.NEWS_UA})
        return conn.getresponse().getheader("Location") or ""
    finally:
        conn.close()


def expand_album_link(url, location=_location, lookup=None):
    """A short photos.app.goo.gl link -> the photos.google.com/share/… address behind it.

    Some providers answer the name goo.gl with an address of their own, where nothing listens (seen
    on this laptop's connection), so the short link never loads although Google Photos itself does.
    The plain way and a lookup through Google's public DNS over HTTPS run side by side, and the
    first long link either one finds is kept: waiting for the plain way to time out first cost ~20 s
    (one dead IPv6 and one dead IPv4 address), long enough for the save to look broken."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if parts.hostname != "photos.app.goo.gl":
        return url
    lookup = lookup or (lambda name: collectors._http_json(f"https://dns.google/resolve?name={name}&type=A", timeout=8)[0])

    def plain():
        return location(parts.hostname, parts.path)

    def through_google():
        for record in (lookup(parts.hostname) or {}).get("Answer") or []:
            if record.get("type") == 1:
                try:
                    found = location(parts.hostname, parts.path, record.get("data"))
                except OSError:
                    continue
                if found.startswith(ALBUM_PREFIXES[1]):
                    return found
        return ""

    pool = ThreadPoolExecutor(max_workers=2)
    pending = {pool.submit(plain), pool.submit(through_google)}
    try:
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for job in done:
                try:
                    found = job.result() or ""
                except Exception:  # noqa: BLE001 - a dead address or an unreachable resolver
                    continue
                if found.startswith(ALBUM_PREFIXES[1]):
                    return found
        return ""
    finally:
        pool.shutdown(wait=False)               # the slower way finishes on its own; nobody waits for it


ALBUM_IN_TEXT = re.compile(r"(?:https?://)?(photos\.app\.goo\.gl/[A-Za-z0-9_\-]+|photos\.google\.com/(?:u/\d+/)?share/[^\s\"'<>]+)")


def album_link(text):
    """What was pasted -> the album link in it: text around the link (a phone's share sheet), a
    missing https:// and a signed-in /u/1/ are all fine. '' when there is no album link."""
    found = ALBUM_IN_TEXT.search(str(text or ""))
    return "https://" + re.sub(r"^photos\.google\.com/u/\d+/", "photos.google.com/", found.group(1)) if found else ""


def set_album(cfg_file, album, expand=expand_album_link):
    pasted = str(album or "").strip()
    if not pasted:          # an empty box is a slip, never a reason to forget the album you have
        return {"ok": False, "error": "Paste the album's link first: in Google Photos choose Share, then Create link."}
    album = album_link(pasted)
    if not album:
        return {"ok": False, "error": "Paste a Google Photos shared album link (photos.app.goo.gl/… )."}
    if album:
        album = expand(album)
        if not album:
            return {"ok": False, "error": "That short link could not be opened from this network. Open the album in "
                                          "a browser and paste the long address (photos.google.com/share/…)."}
        if "key=" not in album:
            return {"ok": False, "error": "That is the album's own address, which only you can open. In Google Photos "
                                          "choose Share, then Create link, and paste that link."}
    raw = _read_json(cfg_file, {})
    photos_cfg = raw.get("photos") if isinstance(raw.get("photos"), dict) else {}
    photos_cfg["album"] = album
    raw["photos"] = photos_cfg
    _write_json(cfg_file, raw)
    return {"ok": True}


SCHEDULE = {
    "movies": (movies, 300),
    "storage": (storage, 1800),
    "spotify": (spotify, 3),
    "photos": (photos, 1800),
    "accounts": (accounts, 300),
}
