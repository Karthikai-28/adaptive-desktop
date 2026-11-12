"""What Mario's Home shows, gathered from this machine. Each collector returns one card's data.

A collector reads only local things: git checkouts, files, the loopback ports of services that
already run here (Agent Office, Ollama, LOOM), the Adaptive Link control socket, /proc and /sys.
None of them opens credentials or calls a remote API; the one network step, pulling the Thinking
Space checkout, is git's own and is opt-in by interval. A collector never raises: a part that
cannot be read comes back as {"error": "..."} and the card says so in one line.
"""
import csv
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DONE_STATUSES = {"watched", "tried", "cooked", "favourite", "favorite", "done", "used", "visited", "played"}
TRACKERS = [  # csv stem, label, verb for "done"
    ("movies-shows", "Movies & shows", "watched"),
    ("ai-tools", "AI tools", "tried"),
    ("claude-agents", "Claude & agents", "tried"),
    ("websites", "Websites", "tried"),
    ("coding-ui", "Coding & UI", "tried"),
    ("recipes", "Recipes", "cooked"),
    ("places-fun", "Places & fun", "done"),
    ("games", "Games", "played"),
]
SUBSCRIPTIONS = ("Netflix", "Prime Video", "JioHotstar", "MUBI", "Lionsgate Play")


def _run(args, cwd=None, timeout=10):
    try:
        out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if out.returncode != 0:
        return None, (out.stderr or out.stdout).strip()[:200]
    return out.stdout, ""


def _http_json(url, timeout=2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "null"), ""
    except Exception as exc:  # noqa: BLE001 - any failure is "not reachable"
        return None, str(getattr(exc, "reason", exc))[:160]


def _unix_json(path, route="/status", timeout=2.0):
    """GET a JSON route over a Unix socket (the Adaptive Link control socket)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(f"GET {route} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
            data = b""
            while chunk := s.recv(65536):
                data += chunk
    except OSError as exc:
        return None, str(exc)[:160]
    head, _, body = data.partition(b"\r\n\r\n")
    if b" 200 " not in head.split(b"\r\n", 1)[0]:
        return None, head.split(b"\r\n", 1)[0].decode(errors="replace")
    try:
        return json.loads(body.decode()), ""
    except ValueError as exc:
        return None, str(exc)


# ------------------------------------------------------------------ builds

_BRANCH = re.compile(r"^## (?P<branch>[^. ]+)(?:\.\.\.\S+)?(?: \[(?P<track>[^\]]+)\])?")


def parse_status(text):
    """`git status --porcelain=v1 --branch` -> (branch, ahead, behind, changed files)."""
    lines = text.splitlines()
    branch, ahead, behind = "", 0, 0
    if lines and lines[0].startswith("## "):
        m = _BRANCH.match(lines[0])
        if m:
            branch = m.group("branch")
            for part in (m.group("track") or "").split(","):
                part = part.strip()
                if part.startswith("ahead "):
                    ahead = int(part[6:])
                elif part.startswith("behind "):
                    behind = int(part[7:])
        lines = lines[1:]
    return branch, ahead, behind, len([l for l in lines if l.strip()])


def repo(path):
    path = Path(path)
    if not (path / ".git").exists():
        return None
    log, err = _run(["git", "-C", str(path), "log", "-1", "--format=%h%x1f%ct%x1f%s"])
    if log is None:
        return {"name": path.name, "error": err}
    sha, when, subject = (log.strip().split("\x1f") + ["", "", ""])[:3]
    status, _ = _run(["git", "-C", str(path), "status", "--porcelain=v1", "--branch"])
    branch, ahead, behind, dirty = parse_status(status or "")
    return {"name": path.name, "path": str(path), "branch": branch, "sha": sha,
            "when": int(when or 0), "subject": subject, "dirty": dirty, "ahead": ahead, "behind": behind}


def activity(paths, days=14, now=None):
    """Commits per day over the last `days` days across all repos, oldest day first."""
    now = now or time.time()
    today = int((now - time.timezone) // 86400)
    counts = [0] * days
    for path in paths:
        if not (Path(path) / ".git").exists():
            continue
        out, _ = _run(["git", "-C", str(path), "log", f"--since={days}.days", "--format=%ct", "--all"])
        for line in (out or "").split():
            day = today - int((int(line) - time.timezone) // 86400)
            if 0 <= day < days:
                counts[days - 1 - day] += 1
    return counts


def builds(cfg):
    rows = [r for r in (repo(p) for p in cfg["repos"]) if r]
    rows.sort(key=lambda r: r.get("when", 0), reverse=True)
    days = activity(cfg["repos"])
    return {"repos": rows, "activity": days, "week": sum(days[-7:])}


# ------------------------------------------------------------ thinking space

def read_elements(path):
    """elements.jsonl in either shape the backup has written: {"id", "data": {...}} or {"id", ...}."""
    out = []
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else row
        out.append({"id": row.get("id"), **{k: v for k, v in data.items() if k != "id"}})
    return out


def _inside(el, box):
    x, y = el.get("x"), el.get("y")
    if not all(isinstance(v, (int, float)) for v in (x, y)):
        return False
    return box["x"] <= x < box["x"] + box.get("w", 0) and box["y"] <= y < box["y"] + box.get("h", 0)


def board_summary(folder):
    folder = Path(folder)
    try:
        meta = json.loads((folder / "meta.json").read_text())
    except (OSError, ValueError):
        meta = {}
    els = read_elements(folder / "elements.jsonl")
    title = meta.get("title") or next((e.get("text", "") for e in els if e.get("size") == "title"), folder.name)
    inbox = next((e for e in els if e.get("type") == "container" and str(e.get("text", "")).lower().startswith("inbox")), None)
    items = []
    if inbox:
        for e in els:
            text = str(e.get("text", "")).strip()
            if e is inbox or e.get("type") not in ("shape", "text") or not _inside(e, inbox):
                continue
            if not text or text.endswith("…") and len(text) < 40:  # the empty "Next idea…" sticky
                continue
            items.append(re.sub(r"[*_`]", "", text.splitlines()[0])[:80])
    updated = next((e.get("text") for e in els if str(e.get("text", "")).startswith("Updated ")), "")
    sections = [re.sub(r"\s*\(.*?\)", "", str(e.get("text", ""))).strip() for e in els
                if e.get("type") == "container" and e is not inbox and str(e.get("text", "")).strip()]
    return {"slug": folder.name, "title": title, "url": meta.get("url", ""), "inbox": items, "sections": sections[:4],
            "elements": len(els), "updated": updated}


def maybe_pull(path, every_s, stamp_file):
    """git pull --ff-only the Thinking Space checkout at most every `every_s` seconds."""
    if every_s <= 0 or not (Path(path) / ".git").exists():
        return ""
    try:
        last = float(Path(stamp_file).read_text())
    except (OSError, ValueError):
        last = 0.0
    if time.time() - last < every_s:
        return ""
    Path(stamp_file).parent.mkdir(parents=True, exist_ok=True)
    Path(stamp_file).write_text(str(time.time()))
    _, err = _run(["git", "-C", str(path), "pull", "--ff-only", "--quiet"], timeout=60)
    return err


def thinking_space(cfg, stamp_file=None):
    root = cfg["thinking_space"]
    if not (root / "boards").is_dir():
        return {"error": f"no Thinking Space checkout at {root}", "boards": []}
    pull_err = maybe_pull(root, cfg.get("thinking_space_pull_s", 0),
                          stamp_file or root / ".git" / "mario-last-pull")
    boards = [board_summary(d) for d in sorted((root / "boards").iterdir()) if d.is_dir()]
    hub = next((b for b in boards if b["slug"] == "hub"), None)
    last, _ = _run(["git", "-C", str(root), "log", "-1", "--format=%ct%x1f%s"])
    when, _, subject = (last or "").strip().partition("\x1f")
    return {"boards": [b for b in boards if b["slug"] != "hub"], "hub": hub,
            "updated": (hub or {}).get("updated", ""), "pull_error": pull_err,
            "last_backup": {"when": int(when or 0), "subject": subject}}


# -------------------------------------------------------------------- reels

def _rows(path):
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def reels(cfg):
    data = cfg["thinking_space"] / "reels" / "data"
    if not data.is_dir():
        return {"error": "no reels/data in the Thinking Space checkout", "trackers": []}
    trackers = []
    for stem, label, verb in TRACKERS:
        rows = _rows(data / f"{stem}.csv")
        if not rows:
            continue
        done = sum(1 for r in rows if str(r.get("Status", "")).strip().lower() in DONE_STATUSES)
        trackers.append({"id": stem, "label": label, "verb": verb, "done": done, "total": len(rows)})
    movies = _rows(data / "movies-shows.csv")
    tonight = [r for r in movies if r.get("Status", "").strip().lower() == "yet to watch"
               and any(s in r.get("Where to watch in India", "") for s in SUBSCRIPTIONS)
               and not r.get("Where to watch in India", "").lower().startswith("rent")]
    picks = {}
    for r in tonight:
        service = next(s for s in SUBSCRIPTIONS if s in r["Where to watch in India"])
        picks.setdefault(service, []).append(r.get("Title", ""))
    service = max(picks, key=lambda s: len(picks[s]), default="")
    history = _rows(data / "history.csv")
    every = _rows(data / "all-reels.csv")
    total = len(every)
    newest = [{"category": r.get("Category", ""), "what": r.get("Why it matters") or r.get("What it is", ""),
               "saved": r.get("Saved on", ""), "link": r.get("Link", "")} for r in _newest(every)[:4]]
    watch = [{"title": r.get("Title", ""), "where": next(s for s in SUBSCRIPTIONS if s in r["Where to watch in India"]),
              "year": r.get("Year", ""), "type": r.get("Type", "")} for r in tonight][:6]
    return {"total": total, "trackers": trackers,
            "tonight": {"service": service, "titles": picks.get(service, [])[:2]},
            "watch": watch, "try_next": try_next(data), "cook": to_cook(data), "sheet": _sheet_link(data.parent),
            "history": history[-4:][::-1], "newest": newest, "last_change": history[-1] if history else None}


def _sheet_link(reels_dir):
    """The Google Sheet the trackers live in, as the backup's reels/README.md links it."""
    try:
        m = re.search(r"https://docs\.google\.com/spreadsheets/d/[\w-]+[^\s)\]]*", (reels_dir / "README.md").read_text())
    except OSError:
        return ""
    return m.group(0) if m else ""


def _newest(rows, key="Saved on"):
    return sorted(rows, key=lambda r: r.get(key, ""), reverse=True)


def try_next(data, per_list=2):
    """Newest named things still to try: two each from AI tools, Claude & agents and websites."""
    picks = []
    for stem, label in (("ai-tools", "AI tool"), ("claude-agents", "Claude & agents"), ("websites", "Website")):
        rows = [r for r in _newest(_rows(data / f"{stem}.csv"))
                if str(r.get("Status", "")).strip().lower() == "to try"
                and (r.get("Name") or r.get("What it is", "")) not in ("", "Named in video", "See reel")
                and not str(r.get("What it is", "")).startswith(("No caption", "See reel"))]
        for r in rows[:per_list]:
            name = r.get("Name") or r.get("What it is", "")
            what = r.get("What it does", "") if r.get("Name") else (r.get("Creator", ""))
            picks.append({"kind": label, "name": name[:90], "what": what[:90], "link": r.get("Reel", "")})
    return picks


def to_cook(data, limit=4):
    rows = [r for r in _newest(_rows(data / "recipes.csv")) if str(r.get("Status", "")).strip().lower() == "to cook"
            and r.get("What it is", "") not in ("", "See reel")]
    return [{"name": r["What it is"][:80], "link": r.get("Reel", "")} for r in rows[:limit]]


# ------------------------------------------------------------ agent office

def agent_office(cfg):
    base = cfg["agent_office_url"].rstrip("/")
    health, err = _http_json(base + "/api/health")
    if health is None:
        return {"running": False, "error": err}
    state, _ = _http_json(base + "/api/state", timeout=3)
    agents, active = [], []
    if isinstance(state, dict):
        for a in state.get("agents") or []:
            if isinstance(a, dict):
                agents.append({"id": a.get("id"), "name": a.get("name") or a.get("id"),
                               "status": a.get("status") or a.get("state") or "idle",
                               "provider": a.get("provider") or a.get("engine") or ""})
        for m in state.get("missions") or []:
            if isinstance(m, dict) and str(m.get("status", "")).lower() in ("running", "active", "queued"):
                active.append({"id": m.get("id"), "title": m.get("title") or m.get("goal") or m.get("id")})
    return {"running": True, "paused": bool(health.get("paused")), "agents": agents[:6], "missions": active[:3]}


# ----------------------------------------------------------------- usage

def usage(cfg):
    script = Path(cfg.get("adaptive_repo") or Path(__file__).resolve().parents[2]) / \
        "shell" / "adaptive-shell@local" / "quotaSnapshot.py"
    out, err = _run([sys.executable, str(script)], timeout=20)
    if out is None:
        return {"error": err, "providers": {}}
    try:
        snap = json.loads(out)
    except ValueError:
        return {"error": "quotaSnapshot printed no JSON", "providers": {}}
    providers = {}
    for name in cfg.get("usage_providers", ["claude", "gemini"]):
        p = snap.get(name) if isinstance(snap, dict) else None
        if not isinstance(p, dict):
            providers[name] = {"used": None, "window": "", "windows": [], "stale": True, "error": "no data"}
            continue
        live = [w for w in p.get("windows") or [] if not w.get("expired")]
        top = max(live, key=lambda w: w.get("used", 0), default=None)
        providers[name] = {"used": top["used"] if top else None, "window": top["label"] if top else "",
                           "windows": [{"label": w.get("label", ""), "used": w.get("used"),
                                        "resets": w.get("resetsAt")} for w in live],
                           "stale": bool(p.get("stale")), "error": p.get("error", "")}
    return {"providers": providers}


# ---------------------------------------------------------------- system

_last_cpu = {}


def _cpu_percent(stat_text, key="cpu"):
    fields = next((l.split() for l in stat_text.splitlines() if l.startswith("cpu ")), None)
    if not fields:
        return None
    vals = [int(v) for v in fields[1:]]
    idle, total = vals[3] + (vals[4] if len(vals) > 4 else 0), sum(vals)
    prev = _last_cpu.get(key)
    _last_cpu[key] = (idle, total)
    if not prev or total == prev[1]:
        return None
    return round(100 * (1 - (idle - prev[0]) / (total - prev[1])), 1)


def parse_meminfo(text):
    kv = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if rest.strip():
            kv[name] = int(rest.split()[0])
    total, avail = kv.get("MemTotal", 0), kv.get("MemAvailable", 0)
    return {"total_gb": round(total / 1048576, 1), "used_gb": round((total - avail) / 1048576, 1)}


def _gpu():
    if not shutil.which("nvidia-smi"):
        return None
    out, _ = _run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                   "--format=csv,noheader,nounits"], timeout=4)
    if not out:
        return None
    name, util, used, total = [s.strip() for s in out.splitlines()[0].split(",")][:4]
    return {"name": name.replace("NVIDIA GeForce ", ""), "util": float(util),
            "vram_used_gb": round(float(used) / 1024, 1), "vram_total_gb": round(float(total) / 1024, 1)}


def _battery():
    for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            return {"percent": int((d / "capacity").read_text()),
                    "status": (d / "status").read_text().strip().lower()}
        except (OSError, ValueError):
            continue
    return None


_last_net = {}


def net_rates(dev_text, now=None):
    """Bytes/s down and up across real interfaces since the previous call (/proc/net/dev)."""
    now = now or time.time()
    rx = tx = 0
    for line in dev_text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        if not rest or name == "lo" or name.startswith(("docker", "veth", "virbr", "br-")):
            continue
        f = rest.split()
        rx, tx = rx + int(f[0]), tx + int(f[8])
    prev = _last_net.get("all")
    _last_net["all"] = (now, rx, tx)
    if not prev or now <= prev[0]:
        return None
    dt_s = now - prev[0]
    return {"down": max(0, (rx - prev[1]) / dt_s), "up": max(0, (tx - prev[2]) / dt_s)}


def system(cfg):
    out = {"host": socket.gethostname()}
    try:
        du = shutil.disk_usage("/")
        out["disk"] = {"used_gb": round(du.used / 1e9), "total_gb": round(du.total / 1e9)}
        out["uptime_h"] = round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1)
        out["net"] = net_rates(Path("/proc/net/dev").read_text())
    except (OSError, ValueError, IndexError):
        pass
    try:
        out["cpu"] = _cpu_percent(Path("/proc/stat").read_text())
        out["mem"] = parse_meminfo(Path("/proc/meminfo").read_text())
    except OSError as exc:
        out["error"] = str(exc)
    out["gpu"] = _gpu()
    out["battery"] = _battery()
    loaded, err = _http_json(cfg["ollama_url"].rstrip("/") + "/api/ps")
    out["ollama"] = {"running": loaded is not None, "error": err,
                     "models": [m.get("name") for m in (loaded or {}).get("models", [])]}
    return out


# ------------------------------------------------------------------ phone

def phone(cfg):
    sock = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "adaptive-link.sock"
    if not sock.exists():
        return {"linked": False, "error": "Adaptive Link is not running"}
    state, err = _unix_json(sock)
    if state is None:
        return {"linked": False, "error": err}
    p = state.get("phone") or {}
    return {"linked": bool(p), "name": p.get("name", ""), "present": bool(state.get("present")),
            "listening": bool(state.get("listening")), "problem": state.get("problem") or ""}


# ------------------------------------------------------------------- LOOM

def loom(cfg):
    health, err = _http_json(cfg["loom_url"].rstrip("/") + "/api/health", timeout=2)
    if not isinstance(health, dict):
        return {"running": False, "error": err}
    return {"running": True, "model": health.get("active_model") or "auto",
            "models": len(health.get("available_models") or []),
            "ollama": bool(health.get("ollama_reachable")), "warming_up": bool(health.get("warming_up")),
            "confirm_shell": bool((health.get("permissions") or {}).get("confirm_shell", True))}


# ---------------------------------------------------------------- weather

WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Showers", 81: "Showers", 82: "Heavy showers",
       95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}


def weather(cfg):
    """Open-Meteo (no key, no account): now, today's range and the next hours. The one card
    that reaches the internet; turn it off with "cards_off": ["weather"]."""
    w = cfg.get("weather") or {}
    if "weather" in cfg.get("cards_off", []) or not w.get("lat"):
        return {"off": True}
    url = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,weather_code,apparent_temperature"
           "&hourly=temperature_2m,precipitation_probability&daily=temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max&timezone=auto&forecast_days=1").format(**w)
    data, err = _http_json(url, timeout=6)
    if not isinstance(data, dict) or "current" not in data:
        return {"error": err or "no forecast", "place": w.get("name", "")}
    cur, daily, hourly = data["current"], data.get("daily", {}), data.get("hourly", {})
    now_hour = cur.get("time", "")[:13]
    times = hourly.get("time", [])
    start = next((i for i, t in enumerate(times) if t[:13] >= now_hour), 0)
    hours = [{"h": times[i][11:13], "t": round(hourly["temperature_2m"][i]),
              "rain": (hourly.get("precipitation_probability") or [0] * len(times))[i]}
             for i in range(start, min(start + 6, len(times)))]
    first = lambda k: (daily.get(k) or [None])[0]  # noqa: E731
    return {"place": w.get("name", ""), "temp": round(cur.get("temperature_2m", 0)),
            "feels": round(cur.get("apparent_temperature", 0)), "sky": WMO.get(cur.get("weather_code"), ""),
            "high": first("temperature_2m_max"), "low": first("temperature_2m_min"),
            "rain": first("precipitation_probability_max"), "hours": hours}


# ------------------------------------------------------------ local files

def parse_xbel(text, limit=8):
    """GTK's recently-used.xbel -> newest local files that still exist: name, path, app, when."""
    import xml.etree.ElementTree as ET
    from datetime import datetime
    from urllib.parse import unquote, urlparse
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for bm in root.findall("bookmark"):
        href = bm.get("href", "")
        if not href.startswith("file://"):
            continue
        path = unquote(urlparse(href).path)
        stamp = bm.get("visited") or bm.get("modified") or ""
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00")[:26] + ("+00:00" if stamp.endswith("Z") else "")).timestamp()
        except ValueError:
            when = 0
        app = next((a.get("name", "") for a in bm.iter() if a.tag.endswith("application")), "")
        try:
            size = Path(path).stat().st_size
        except OSError:
            size = None
        out.append({"name": Path(path).name, "path": path, "app": app, "when": int(when), "size": size})
    out.sort(key=lambda r: r["when"], reverse=True)
    return [r for r in out if r["size"] is not None][:limit]


def recent(cfg):
    xbel = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "recently-used.xbel"
    try:
        return {"files": parse_xbel(xbel.read_text(errors="replace"))}
    except OSError:
        return {"files": []}


def downloads(cfg):
    folder = Path(os.path.expanduser(cfg.get("downloads", "~/Downloads")))
    try:
        entries = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")
                   and not p.name.endswith((".part", ".crdownload"))]
    except OSError:
        return {"files": [], "error": f"no {folder}"}
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return {"folder": str(folder), "count": len(entries),
            "files": [{"name": p.name, "path": str(p), "size": p.stat().st_size, "when": int(p.stat().st_mtime)}
                      for p in entries[:5]]}


def processes(cfg):
    """Busiest processes right now (top's one-shot sample, not lifetime averages)."""
    out, err = _run(["top", "-b", "-n", "2", "-d", "0.5", "-w", "200", "-o", "%CPU"], timeout=6)
    rows = []
    last = (out or "").split("\ntop - ")[-1]  # the second sample: CPU over the last half second
    for line in last.splitlines():
        f = line.split()
        if len(f) >= 12 and f[0].isdigit():
            try:
                rows.append({"name": " ".join(f[11:])[:28], "cpu": float(f[8].replace(",", ".")),
                             "mem": float(f[9].replace(",", "."))})
            except ValueError:
                continue
    rows = [r for r in rows if r["name"] not in ("top",)]
    return {"top": rows[:5], "error": err if out is None else ""}


def agent_sessions(cfg):
    """Claude / agy sessions kept by terminal/agent.py on its private tmux server."""
    if not shutil.which("tmux"):
        return {"sessions": []}
    sock = os.environ.get("ADAPTIVE_AGENT_SOCKET", "adaptive-agents")
    out, _ = _run(["tmux", "-L", sock, "list-sessions", "-F",
                   "#{session_name}\t#{session_path}\t#{session_activity}\t#{session_attached}"], timeout=3)
    rows = []
    for line in (out or "").splitlines():
        f = line.split("\t")
        if len(f) < 4:
            continue
        name, path, when, attached = f[:4]
        rows.append({"name": name, "agent": re.sub(r"-\d+$", "", name), "folder": Path(path).name or path,
                     "when": int(when or 0), "attached": attached not in ("", "0")})
    rows.sort(key=lambda r: r["when"], reverse=True)
    return {"sessions": rows[:6]}


_LOOPBACK = ("127.", "[::1]", "::1", "localhost")


def parse_listening(text):
    """`ss -ltnuHp` -> services this machine offers to the network (loopback left out)."""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        proto, local = f[0], f[4]
        addr, _, port = local.rpartition(":")
        if addr.startswith(_LOOPBACK) or "%lo" in addr:
            continue
        m = re.search(r'users:\(\("([^"]+)"', line)
        out.append({"proto": proto, "addr": addr or "*", "port": int(port) if port.isdigit() else port,
                    "proc": m.group(1) if m else ""})
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: (r["port"] if isinstance(r["port"], int) else 1 << 20, r["proto"])):
        key = (r["proto"], r["port"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def listening(cfg):
    out, err = _run(["ss", "-ltnuHp"], timeout=4)
    if out is None:
        return {"error": err, "open": []}
    rows = parse_listening(out)
    return {"open": rows[:8], "count": len(rows)}


def read_notes(path, limit=4):
    try:
        lines = [l for l in Path(path).read_text().splitlines() if l.startswith("- ")]
    except OSError:
        return []
    return [l[2:] for l in lines[-limit:]][::-1]


# ------------------------------------------------------------- your day

# What the desktop session hands to user services when you log in. The hub is a user service that
# can start before anyone logs in (lingering), and the display can change between logins, so this is
# read when it is needed, never kept from the hub's own start.
SESSION_KEYS = ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "DCONF_PROFILE",
                "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "XDG_SESSION_DESKTOP", "XDG_DATA_DIRS",
                "XDG_CONFIG_DIRS", "DESKTOP_SESSION", "GNOME_SETUP_DISPLAY", "SSH_AUTH_SOCK")


def session_env():
    """The logged-in desktop's variables (DISPLAY and the rest) from the user manager, or {} when
    no desktop session is up yet."""
    out, _ = _run(["systemctl", "--user", "show-environment"], timeout=3)
    env = {}
    for line in (out or "").splitlines():
        key, _, val = line.partition("=")
        if key in SESSION_KEYS:
            env[key] = val
    return env if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") else {}


class KeyringNotReady(Exception):
    """The keyring cannot be asked yet: nobody is logged in, or it is still locked."""


def keyring(**attrs):
    """A secret from the GNOME keyring (secret-tool), or "" when it is not stored. Never logged.
    Raises KeyringNotReady before you log in (the login unlocks it): asking then would start a
    keyring daemon outside the session or wait on an unlock prompt nobody can see."""
    if not shutil.which("secret-tool"):
        return ""
    env = session_env()
    if not env:
        raise KeyringNotReady("not logged in")
    args = ["secret-tool", "lookup"]
    for k, v in attrs.items():
        args += [k, str(v)]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5, env={**os.environ, **env})
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeyringNotReady(str(exc)) from exc
    if out.returncode != 0 and out.stderr.strip():
        raise KeyringNotReady(out.stderr.strip()[:120])   # no secret service, locked, refused
    return (out.stdout or "").strip()


KEYRING_WAIT = "Waiting for the keyring: it opens when you log in."


def _decode(value):
    from email.header import decode_header, make_header
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001 - a broken header still shows something
        return value or ""


_MAIL_REFUSED = {}   # hash of (host, user, password) -> why Gmail refused it, for this hub run


def mail(cfg):
    """Unread mail in the inbox, newest first, read-only over IMAP (nothing is marked read).
    The password (a Google app password) lives in the keyring: install-mario.sh --mail."""
    import imaplib
    from email.utils import parseaddr, parsedate_to_datetime
    m = cfg.get("mail") or {}
    user, host = m.get("user", ""), m.get("imap_host", "imap.gmail.com")
    if not user:
        return {"setup": True, "error": "Mail is not set up: scripts/install-mario.sh --mail"}
    try:
        password = keyring(service="mario-mail", account=user)
    except KeyringNotReady:
        return {"waiting": True, "error": KEYRING_WAIT, "unread": None, "items": []}
    if not password:
        return {"setup": True, "error": "No mail password in the keyring: scripts/install-mario.sh --mail"}
    # Google shows an app password as four groups of four letters; it is the 16 letters that count
    if re.fullmatch(r"(?:[a-zA-Z]{4}\s*){4}", password.strip()):
        password = re.sub(r"\s+", "", password)
    # A password Gmail refused is not sent again (repeated failed logins with an account password
    # can trip Google's security alerts); saving a new one with install-mario.sh --mail changes the key.
    import hashlib
    key = hashlib.sha256(f"{host}\0{user}\0{password}".encode()).hexdigest()
    if key in _MAIL_REFUSED:
        return {**_MAIL_REFUSED[key], "unread": None, "items": [], "user": user}
    try:
        box = imaplib.IMAP4_SSL(host, timeout=15)
        try:
            box.login(user, password)
        except imaplib.IMAP4.error as exc:
            _MAIL_REFUSED[key] = mail_login_problem(exc)
            return {**_MAIL_REFUSED[key], "unread": None, "items": [], "user": user}
        box.select("INBOX", readonly=True)
        _, ids = box.search(None, "UNSEEN")
        unread = ids[0].split() if ids and ids[0] else []
        items = []
        for num in reversed(unread[-4:]):
            _, data = box.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            raw = data[0][1].decode(errors="replace") if data and data[0] else ""
            head = {}
            for line in raw.replace("\r\n ", " ").splitlines():
                key, _, val = line.partition(":")
                head[key.strip().lower()] = val.strip()
            name, addr = parseaddr(_decode(head.get("from", "")))
            try:
                when = int(parsedate_to_datetime(head.get("date", "")).timestamp())
            except (TypeError, ValueError):
                when = 0
            items.append({"from": name or addr, "subject": _decode(head.get("subject", "")) or "(no subject)", "when": when})
        box.logout()
    except imaplib.IMAP4.error as exc:
        return {"error": f"Gmail answered: {_imap_text(exc)[:90]}", "unread": None, "items": []}
    except OSError:
        return {"waiting": True, "error": f"Can't reach {host} right now. Mail comes back when the laptop is online.",
                "unread": None, "items": []}
    return {"unread": len(unread), "items": items, "user": user}


def _imap_text(exc):
    """imaplib hands the server's reply over as bytes inside the exception: b'[ALERT] ...'."""
    arg = exc.args[0] if exc.args else exc
    text = arg.decode(errors="replace") if isinstance(arg, (bytes, bytearray)) else str(arg)
    return re.sub(r"^\[[A-Z-]+\]\s*", "", text).strip()


def mail_login_problem(exc):
    """A Gmail login refusal -> what to do about it (`fix` tells Home which help to show)."""
    text = _imap_text(exc)
    if "application-specific password" in text.lower():
        return {"fix": "app_password",
                "error": "Gmail needs an app password here, not your Google password."}
    if "invalid credentials" in text.lower() or "authenticationfailed" in text.lower():
        return {"fix": "password", "error": "Gmail turned the saved app password down (wrong, or revoked)."}
    return {"fix": "password", "error": f"Gmail refused the login: {text[:90]}"}


def _ics_events(text, day):
    """Events on `day` (a date) from an iCal feed, recurring ones included when the
    icalendar / recurring_ical_events packages are there (install-mario.sh puts them in
    .local/mario-pydeps); otherwise single events only."""
    import datetime as dt
    pydeps = Path(__file__).resolve().parents[2] / ".local" / "mario-pydeps"
    if pydeps.is_dir() and str(pydeps) not in sys.path:
        sys.path.append(str(pydeps))
    start = dt.datetime.combine(day, dt.time.min).astimezone()
    end = start + dt.timedelta(days=1)
    out = []
    try:
        import icalendar
        import recurring_ical_events
        cal = icalendar.Calendar.from_ical(text)
        for ev in recurring_ical_events.of(cal).between(start, end):
            s, e = ev.get("DTSTART").dt, (ev.get("DTEND").dt if ev.get("DTEND") else None)
            all_day = not isinstance(s, dt.datetime)
            if not all_day:
                s = s.astimezone()
                e = e.astimezone() if isinstance(e, dt.datetime) else None
            out.append({"title": str(ev.get("SUMMARY", "")), "all_day": all_day,
                        "start": "" if all_day else s.strftime("%H:%M"),
                        "minutes": int((e - s).total_seconds() // 60) if e and not all_day else 0,
                        "where": str(ev.get("LOCATION", "") or "")})
        return sorted(out, key=lambda x: (not x["all_day"], x["start"])), ""
    except ImportError:
        pass
    # plain fallback: one-off timed events only
    for block in text.split("BEGIN:VEVENT")[1:]:
        if "RRULE:" in block:
            continue
        fields = {}
        for line in block.replace("\r\n ", "").replace("\n ", "").splitlines():
            key, _, val = line.partition(":")
            fields[key.split(";")[0]] = val
        raw = fields.get("DTSTART", "")
        try:
            if raw.endswith("Z"):
                s = dt.datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone()
            elif "T" in raw:
                s = dt.datetime.strptime(raw, "%Y%m%dT%H%M%S").astimezone()
            else:
                continue
        except ValueError:
            continue
        if s.date() == day:
            out.append({"title": fields.get("SUMMARY", ""), "all_day": False, "start": s.strftime("%H:%M"),
                        "minutes": 0, "where": fields.get("LOCATION", "")})
    return sorted(out, key=lambda x: x["start"]), "recurring events need: scripts/install-mario.sh"


def calendar(cfg):
    """Today's events from your calendar's private iCal address (kept in the keyring:
    install-mario.sh --calendar). Read-only."""
    import datetime as dt
    try:
        url = keyring(service="mario-calendar", account="ical")
    except KeyringNotReady:
        return {"waiting": True, "error": KEYRING_WAIT, "events": []}
    if not url:
        return {"setup": True, "error": "Calendar is not set up: scripts/install-mario.sh --calendar"}
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            text = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        # Google answers 404 once the secret address is reset, and for the calendar's public address
        return {"fix": True, "events": [],
                "error": f"Google would not hand over the calendar ({exc.code}). Use the calendar's current "
                         "\"Secret address in iCal format\"."}
    except Exception as exc:  # noqa: BLE001
        return {"waiting": True, "events": [],
                "error": f"Can't reach the calendar right now ({str(getattr(exc, 'reason', exc))[:60]})."}
    if "BEGIN:VCALENDAR" not in text[:2000]:
        return {"fix": True, "events": [],
                "error": "That address is not a calendar feed. Use \"Secret address in iCal format\" (it ends in .ics)."}
    events, note = _ics_events(text, dt.date.today())
    return {"events": events[:8], "note": note}


NOTES_DIR = Path.home() / ".local/share/adaptive-desktop/notes"


def tasks(cfg, notes_dir=None):
    """Open tasks from every Quick Note inbox (Super+Alt+N, the palette's todo mode),
    newest first, with the project each belongs to."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project-context"))
    import extras
    notes_dir = Path(notes_dir or NOTES_DIR)
    out = []
    for inbox in sorted(notes_dir.glob("*/Inbox.md")):
        try:
            text = inbox.read_text(encoding="utf-8")
        except OSError:
            continue
        for t in extras.parse_tasks(text):
            if not t["done"]:
                out.append({"text": t["text"], "stamp": t["stamp"], "line": t["line"],
                            "path": str(inbox), "project": inbox.parent.name})
    out.sort(key=lambda t: t["stamp"], reverse=True)
    return {"open": out[:8], "count": len(out)}


def health(cfg):
    """One line for the status strip: pending updates, disk, battery, failed user services."""
    issues = []
    out = ""
    if Path("/usr/lib/update-notifier/apt-check").exists():
        try:  # apt-check prints "updates;security" on stderr
            out = subprocess.run(["/usr/lib/update-notifier/apt-check"], capture_output=True, text=True, timeout=30).stderr
        except (OSError, subprocess.SubprocessError):
            out = ""
    try:
        updates, security = [int(x) for x in (out or "").strip().split(";")[:2]]
    except ValueError:
        updates = security = 0
    if security:
        issues.append(f"{security} security update{'s' * (security > 1)}")
    elif updates:
        issues.append(f"{updates} update{'s' * (updates > 1)} available")
    du = shutil.disk_usage("/")
    if du.used / du.total > 0.9:
        issues.append(f"disk {round(100 * du.used / du.total)}% full")
    bat = _battery()
    if bat and bat["percent"] < 15 and bat["status"] != "charging":
        issues.append(f"battery {bat['percent']}%")
    failed, _ = _run(["systemctl", "--user", "--failed", "--no-legend", "--plain"], timeout=5)
    names = [l.split()[0] for l in (failed or "").splitlines() if l.strip()]
    if names:
        issues.append(f"{names[0]} failed")
    return {"ok": not issues, "issues": issues, "battery": bat}


# ------------------------------------------------------------------- news

def parse_rss(text, feed_name, limit=12):
    """RSS 2.0 items -> [{title, source, link, when, feed}]. Google News puts the outlet after
    " - " in the title and in <source>; other feeds use the feed's own name."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        try:
            when = int(parsedate_to_datetime(item.findtext("pubDate") or "").timestamp())
        except (TypeError, ValueError):
            when = 0
        out.append({"title": title[:220], "source": source or feed_name, "link": link, "when": when, "feed": feed_name})
        if len(out) >= limit:
            break
    return out


def news(cfg):
    """Headlines from the configured feeds, newest first, the same story only once."""
    if "news" in cfg.get("cards_off", []):
        return {"off": True, "items": []}
    items, errors = [], []
    for feed in cfg.get("news") or []:
        try:
            req = urllib.request.Request(feed["url"], headers={"User-Agent": "MarioHub/1 (+adaptive-desktop)"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                items += parse_rss(resp.read().decode(errors="replace"), feed.get("name", ""))
        except Exception as exc:  # noqa: BLE001 - one feed down must not empty the tile
            errors.append(f"{feed.get('name', 'feed')}: {str(getattr(exc, 'reason', exc))[:60]}")
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: x["when"], reverse=True):
        key = re.sub(r"\W+", " ", it["title"].lower()).strip()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return {"items": unique[:30], "errors": errors}


# ------------------------------------------------------------- schedule

# card name -> (collector, seconds between runs)
SCHEDULE = {
    "system": (system, 3),
    "agent_office": (agent_office, 10),
    "phone": (phone, 15),
    "builds": (builds, 30),
    "usage": (usage, 60),
    "thinking_space": (thinking_space, 120),
    "reels": (reels, 120),
    "loom": (loom, 15),
    "weather": (weather, 900),
    "recent": (recent, 20),
    "downloads": (downloads, 20),
    "processes": (processes, 5),
    "agent_sessions": (agent_sessions, 10),
    "listening": (listening, 30),
    "mail": (mail, 120),
    "calendar": (calendar, 300),
    "tasks": (tasks, 5),
    "health": (health, 300),
    "news": (news, 900),
}
