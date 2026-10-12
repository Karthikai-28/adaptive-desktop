"""Token ledger: who spends tokens on what, live.

Nothing is estimated. Every Gemini model call an agent makes is recorded by agy in that conversation's
SQLite file (one `steps` row per call, with the call's usage in protobuf); Claude's calls are in its
session transcripts (~/.claude/projects/*/<session>.jsonl); local-model calls are appended by the office
itself to data/usage/<provider>.jsonl with the counts Ollama reports. The ledger re-reads only the files
that changed, every few seconds, and attributes each call:

  provider  which config.json provider served it ("gemini", "local", ...), or "claude" for the manager;
            every view can be narrowed to one provider, so their usage is never mixed

  agent   from the persona the conversation opens with ("You are Maya, ..."), or the study program
  kind    task / study / chat / meeting / other, from the prompt that started that turn
  task    the task number in the prompt ("=== TASK #38") or the study session's task
  step    what the call decided to do next: run a command, read a file, edit, answer, ...

Tokens per call: fresh input (new to the model), re-read context (served from cache: the conversation
sent again with every step), output (thinking included). The office's own task counter only sees fresh
input + output of a task's last attempt; the ledger sees everything.
"""
import asyncio
import glob
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from .config import AGY_HOME, AGY_HOME_LOCAL, DATA, HOME

SCAN_S = 10
CONV_DIRS = [AGY_HOME / ".gemini/antigravity-cli/conversations", AGY_HOME_LOCAL / ".gemini/antigravity-cli/conversations"]
CLAUDE_PROJECTS = HOME / ".claude/projects"
USAGE_DIR = DATA / "usage"                   # <provider>.jsonl, one line per local-model call
KINDS = ("task", "study", "chat", "meeting", "other")


# ---------------------------------------------------------------- protobuf, just enough to read usage
def _varint(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if x < 0x80:
            return r, i


def _parse(b, depth=0):
    """Schema-less protobuf: [(field, kind, value)], nested messages parsed where they parse cleanly."""
    out, i = [], 0
    try:
        while i < len(b):
            k, i = _varint(b, i)
            f, w = k >> 3, k & 7
            if f == 0:
                return None
            if w == 0:
                v, i = _varint(b, i)
                out.append((f, "v", v))
            elif w == 1:
                i += 8
            elif w == 5:
                i += 4
            elif w == 2:
                n, i = _varint(b, i)
                sub = b[i:i + n]
                i += n
                if i > len(b):
                    return None
                nested = _parse(sub, depth + 1) if depth < 6 and n else None
                out.append((f, "m", nested) if nested else (f, "b", sub))
            else:
                return None
        return out
    except IndexError:
        return None


def _get(t, *path):
    for f in path:
        if not isinstance(t, list):
            return None
        hit = [v for ff, _, v in t if ff == f]
        if not hit:
            return None
        t = hit[0]
    return t


def _raw_field(t, f):
    """A field's bytes even when they happened to parse as a message (text that looks like protobuf)."""
    for ff, kind, v in t or []:
        if ff == f and kind == "b":
            return v
    return None


def _text(b):
    if isinstance(b, bytes):
        try:
            return b.decode()
        except UnicodeDecodeError:
            return b.decode(errors="replace")
    return ""


# ---------------------------------------------------------------- what a turn was for
_TASK = re.compile(r"=== TASK #(\d+)")
_STUDY = re.compile(r"STUDY SESSION (\d+)")
_PERSONA = re.compile(r"You are (\w+), ")


def _kind(prompt):
    m = _TASK.search(prompt)
    if m:
        return "task", int(m.group(1))
    m = _STUDY.search(prompt)
    if m:
        return "study", int(m.group(1))
    if "=== DIRECT MESSAGE ===" in prompt:
        return "chat", None
    if "=== MEETING" in prompt or prompt.startswith("Transcript since you last spoke"):
        return "meeting", None
    return "other", None


def _claude_kind(prompt):
    if "[office autopilot]" in prompt[:4000]:
        return "review"
    if prompt.startswith("[Meeting") or "\n[Meeting" in prompt[:4000]:
        return "minutes" if "has ended" in prompt[:400] else "meeting"
    if "via the office app]:" in prompt:
        return "chat"
    return "other"


def _claude_step(c):
    if c.get("name") == "Bash":
        cmd = str((c.get("input") or {}).get("command", "")).split()
        if len(cmd) > 1 and cmd[0] == "office":
            return f"office {cmd[1].rstrip(';')}"
        return "shell"
    return c.get("name") or "tool"


class Ledger:
    def __init__(self, office):
        self.o = office
        self.files = {}          # conversation db path -> {"sig", "agent", "calls"}
        self.claude = {}         # transcript path -> {"pos", "kind", "msgs": {id: call}, "turn"}
        self.local = {}          # usage file path -> {"pos", "calls"}
        self.agy_provider = getattr(office, "main_agy", None) or "gemini"
        self.version = 0
        self._study_tasks = {}

    def start(self):
        self.o._spawn(self._loop())

    async def _loop(self):
        while True:
            try:
                sids = set(self.o.store.get("mgr:sessions", [])) | {self.o.store.get("mgr:session")} - {None}
                changed = await asyncio.to_thread(self.scan, sids)
                if changed:
                    self.version += 1
                    await self.o.broadcast({"type": "tokens", "version": self.version, "recent": self.recent()})
            except Exception as e:  # the ledger is advisory; never let it hurt the office
                print(f"token ledger: {e}", flush=True)
            await asyncio.sleep(SCAN_S)

    # ------------------------------------------------------------------ reading
    def scan(self, sids=()):
        """Runs in a worker thread: builds new tables and swaps them in whole, so readers never see a
        half-updated one. No database access here (the office store belongs to the event loop)."""
        changed = False
        names = {a["name"].lower(): aid for aid, a in self.o.agents.items()}
        files, claude, loc = dict(self.files), dict(self.claude), dict(self.local)
        seen = set()
        for d in CONV_DIRS:
            for f in glob.glob(str(d / "*.db")):
                seen.add(f)
                sig = tuple(_mtime(f + ext) for ext in ("", "-wal"))
                st = files.get(f)
                if st and st["sig"] == sig:
                    continue
                try:
                    files[f] = {"sig": sig, **self._read_conv(f, names)}
                    changed = True
                except sqlite3.Error:
                    continue      # mid-write; next scan
        for f in set(files) - seen:
            del files[f]
            changed = True
        for sid in sids:
            for f in glob.glob(str(CLAUDE_PROJECTS / "*" / f"{sid}.jsonl")):
                old = claude.get(f) or {"pos": 0, "kind": "other", "turn": 0, "msgs": {}}
                new = {**old, "msgs": dict(old["msgs"])}
                if self._read_claude(f, new):
                    claude[f] = new
                    changed = True
        for f in glob.glob(str(USAGE_DIR / "*.jsonl")):
            old = loc.get(f) or {"pos": 0, "calls": []}
            new = {"pos": old["pos"], "calls": list(old["calls"])}
            if _read_usage(f, new):
                loc[f] = new
                changed = True
        self.files, self.claude, self.local = files, claude, loc
        if changed:
            self._study_tasks = {}
        return changed

    def _read_conv(self, path, names):
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            rows = db.execute("SELECT idx, step_type, metadata, step_payload FROM steps ORDER BY idx").fetchall()
        finally:
            db.close()
        conv = Path(path).stem
        agent, calls, turn = None, [], {"ts": 0, "kind": "other", "ref": None}
        for _, st, md, pl in rows:
            m = _parse(md or b"") or []
            ts = _get(m, 1, 1) or 0
            if st == 14:                                       # a prompt from the office: a new turn
                p = _parse(pl) if pl else None
                prompt = _text(_raw_field(_get(p, 19) if p else None, 2)) or _text(pl or b"")
                if agent is None:
                    hit = _PERSONA.search(prompt[:3000])
                    if hit and hit.group(1).lower() in names:
                        agent = names[hit.group(1).lower()]
                    elif _STUDY.search(prompt):
                        agent = self._study_agent()
                kind, ref = _kind(prompt)
                if kind == "other" and not prompt.strip():
                    kind, ref = turn["kind"], turn["ref"]
                turn = {"ts": ts, "kind": kind, "ref": ref}
            elif st == 15:                                     # one model call
                u = _get(m, 9)
                if not u:
                    continue
                p = _parse(pl) if pl else None
                tool = _text(_get(p, 20, 7, 2)) if p else ""
                calls.append({
                    "ts": ts, "turn": turn["ts"], "conv": conv, "kind": turn["kind"], "ref": turn["ref"],
                    "fresh": _get(u, 2) or 0, "cached": _get(u, 5) or 0, "out": _get(u, 3) or 0,
                    "think": _get(u, 9) or 0, "step": tool or "answer", "model": "gemini",
                    "provider": self.agy_provider})
        return {"agent": agent or "other", "calls": calls}

    def _study_agent(self):
        progs = list(getattr(self.o.study, "programs", {}).values())
        return progs[0]["agent"] if progs else None

    def _read_claude(self, path, st):
        try:
            size = Path(path).stat().st_size
        except OSError:
            return False
        if size <= st["pos"]:
            return False
        with open(path, "rb") as fh:
            fh.seek(st["pos"])
            data = fh.read()
        end = data.rfind(b"\n") + 1                            # only whole lines
        st["pos"] += end
        for line in data[:end].splitlines():
            try:
                r = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            msg = r.get("message") or {}
            ts = _iso(r.get("timestamp"))
            if r.get("type") == "user" and isinstance(msg.get("content"), str) and not r.get("isMeta"):
                prompt = msg["content"]
                k = _claude_kind(prompt)
                if prompt.startswith("[office] You escalated") or prompt.startswith("[office] Opus is not"):
                    k = st["kind"]                              # an escalation continues the same work
                st["kind"], st["turn"] = k, ts
            elif r.get("type") == "assistant" and msg.get("id"):
                u = msg.get("usage") or {}
                steps = [_claude_step(c) for c in msg.get("content") or [] if c.get("type") == "tool_use"]
                prev = st["msgs"].get(msg["id"])
                st["msgs"][msg["id"]] = {
                    "ts": prev["ts"] if prev else ts, "turn": prev["turn"] if prev else st["turn"],
                    "conv": Path(path).stem, "kind": prev["kind"] if prev else st["kind"], "ref": None,
                    "fresh": int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
                    "cached": int(u.get("cache_read_input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
                    "think": int((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
                    "step": (prev["step"] if prev and prev["step"] != "answer" else None) or (steps[0] if steps else "answer"),
                    "model": msg.get("model") or "claude", "provider": "claude"}
        return True

    # ------------------------------------------------------------------ querying
    def calls(self, since=0, agent=None, provider=None):
        """Every call since a time, optionally one agent's, optionally one provider's."""
        mgr = self.o.mgr["id"]
        out = []
        files, claude, loc = self.files, self.claude, self.local
        if agent in (None, mgr) and provider in (None, "claude"):
            for st in claude.values():
                out += [dict(c, agent=mgr) for c in st["msgs"].values() if c["ts"] >= since]
        if agent != mgr and provider in (None, self.agy_provider):
            for st in files.values():
                if agent and st["agent"] != agent:
                    continue
                out += [dict(c, agent=st["agent"]) for c in st["calls"] if c["ts"] >= since]
        if agent != mgr:
            for st in loc.values():
                out += [dict(c) for c in st["calls"] if c["ts"] >= since and (not agent or c["agent"] == agent)
                        and (not provider or c["provider"] == provider)]
        for c in out:
            c["task"] = self._task_of(c)
        return out

    def _task_of(self, c):
        if c["kind"] == "task":
            return c["ref"]
        if c["kind"] == "study" and c["ref"]:
            if not self._study_tasks:
                for t in self.o.store.tasks(limit=100000):
                    m = re.match(r"Study session (\d+)\b", t["title"])
                    if m:
                        self._study_tasks.setdefault((t["agent"], int(m.group(1))), t["id"])
            return self._study_tasks.get((c["agent"], c["ref"]))
        return None

    def recent(self, window=600):
        now = time.time()
        r = Counter()
        for c in self.calls(now - window):
            r[c["agent"]] += _total(c)
        return dict(r)

    def providers(self, cs, now):
        """One summary per provider: the configured ones (even when unused) and the manager's Claude."""
        rows = defaultdict(list)
        for c in cs:
            rows[c["provider"]].append(c)
        out = []
        for pid, p in [*self.o.providers.items(), ("claude", {"engine": "claude", "label": "Claude (manager)", "model": self.o.mgr.get("model", "")})]:
            r = rows.pop(pid, [])
            out.append({"id": pid, "label": p.get("label") or pid, "engine": p["engine"], "model": p.get("model", ""),
                        **_sum(r), "last10m": sum(_total(c) for c in r if c["ts"] >= now - 600)})
        for pid, r in rows.items():               # a provider since removed from config.json: still counted
            out.append({"id": pid, "label": pid, "engine": "", "model": "", **_sum(r),
                        "last10m": sum(_total(c) for c in r if c["ts"] >= now - 600)})
        return out

    def overview(self, since=0, provider=None):
        cs = self.calls(since, provider=provider)
        by_agent = defaultdict(list)
        for c in cs:
            by_agent[c["agent"]].append(c)
        now = time.time()
        agents = []
        for aid, rows in by_agent.items():
            s = _sum(rows)
            s.update(id=aid, kinds=_by(rows, "kind"), last10m=sum(_total(c) for c in rows if c["ts"] >= now - 600),
                     models=_by(rows, "model"), providers=_by(rows, "provider"))
            agents.append(s)
        agents.sort(key=lambda a: -a["total"])
        tasks = defaultdict(list)
        for c in cs:
            if c["task"]:
                tasks[c["task"]].append(c)
        projects = defaultdict(list)
        for tid, rows in tasks.items():
            t = self.o.store.task(tid) or {}
            projects[t.get("project") or "(no project)"] += rows
        gem = [c for c in cs if c["agent"] != self.o.mgr["id"]]
        return {
            "now": now, "since": since, "version": self.version, "provider": provider,
            "providers": self.providers(self.calls(since) if provider else cs, now),
            "totals": _sum(gem), "claude": _sum([c for c in cs if c["agent"] == self.o.mgr["id"]]),
            "agents": agents, "kinds": _by(gem, "kind"), "steps": _steps(gem),
            "projects": sorted(({"project": k, **_sum(v)} for k, v in projects.items()), key=lambda p: -p["total"]),
            "outcomes": self._outcomes(tasks),
            "tasks": self._tasks(tasks)[:30], "timeline": _timeline(cs, since, now),
        }

    def agent(self, aid, since=0, provider=None):
        cs = self.calls(since, aid, provider)
        now = time.time()
        tasks = defaultdict(list)
        for c in cs:
            if c["task"]:
                tasks[c["task"]].append(c)
        runs = defaultdict(list)
        for c in cs:
            runs[(c["conv"], c["turn"])].append(c)
        run_list = []
        for (conv, turn), rows in runs.items():
            t = self.o.store.task(rows[0]["task"]) if rows[0]["task"] else None
            run_list.append({**_sum(rows), "ts": turn or rows[0]["ts"], "end": max(c["ts"] for c in rows),
                             "kind": rows[0]["kind"], "task": rows[0]["task"], "title": t["title"] if t else "",
                             "steps": _by_count(rows, "step"), "models": _by(rows, "model"),
                             "provider": rows[0]["provider"]})
        run_list.sort(key=lambda r: -r["ts"])
        ordered = sorted(cs, key=lambda c: c["ts"])
        return {
            "now": now, "since": since, "version": self.version, "id": aid, "provider": provider,
            "summary": {**_sum(cs), "last10m": sum(_total(c) for c in cs if c["ts"] >= now - 600)},
            "kinds": _by(cs, "kind"), "steps": _steps(cs), "models": _by(cs, "model"),
            "providers": _by(cs, "provider"),
            "tasks": self._tasks(tasks), "runs": run_list[:60], "timeline": _timeline(cs, since, now),
            "context": [{"ts": c["ts"], "ctx": c["fresh"] + c["cached"], "out": c["out"], "kind": c["kind"]}
                        for c in ordered[-400:]],
        }

    def _tasks(self, tasks):
        out = []
        for tid, rows in tasks.items():
            t = self.o.store.task(tid) or {}
            s = _sum(rows)
            s.update(id=tid, agent=t.get("agent") or rows[0]["agent"], title=t.get("title", ""), status=t.get("status", ""),
                     attempts=t.get("attempts", 0), project=t.get("project", ""), office_counted=t.get("tokens", 0),
                     minutes=round(((t.get("finished_at") or 0) - (t.get("started_at") or 0)) / 60, 1) if t.get("finished_at") else None,
                     steps=_by_count(rows, "step"))
            out.append(s)
        return sorted(out, key=lambda t: -t["total"])

    def _outcomes(self, tasks):
        o = defaultdict(list)
        for tid, rows in tasks.items():
            o[(self.o.store.task(tid) or {}).get("status", "unknown")] += rows
        return {k: _sum(v) for k, v in o.items()}


def _read_usage(path, st):
    """New whole lines of a local provider's usage file; False when nothing changed."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return False
    if size < st["pos"]:                  # the file was replaced: read it again from the start
        st["pos"], st["calls"] = 0, []
    if size == st["pos"]:
        return False
    with open(path, "rb") as fh:
        fh.seek(st["pos"])
        data = fh.read()
    end = data.rfind(b"\n") + 1
    st["pos"] += end
    for line in data[:end].splitlines():
        try:
            r = json.loads(line)
            st["calls"].append({k: r.get(k, d) for k, d in (
                ("ts", 0), ("turn", 0), ("conv", ""), ("kind", "other"), ("ref", None), ("fresh", 0), ("cached", 0),
                ("out", 0), ("think", 0), ("step", "answer"), ("model", "local"), ("agent", "other"),
                ("provider", Path(path).stem))})
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            continue
    return True


# ---------------------------------------------------------------- arithmetic
def _total(c):
    return c["fresh"] + c["cached"] + c["out"]


def _sum(rows):
    fresh, cached, out = (sum(c[k] for c in rows) for k in ("fresh", "cached", "out"))
    n = len(rows)
    return {"total": fresh + cached + out, "new": fresh + out, "fresh": fresh, "cached": cached, "out": out,
            "think": sum(c["think"] for c in rows), "calls": n,
            "avg_ctx": round((fresh + cached) / n) if n else 0,
            "max_ctx": max((c["fresh"] + c["cached"] for c in rows), default=0)}


def _by(rows, key):
    d = defaultdict(int)
    for c in rows:
        d[c[key]] += _total(c)
    return dict(d)


def _by_count(rows, key):
    return dict(Counter(c[key] for c in rows).most_common())


def _steps(rows):
    g = defaultdict(list)
    for c in rows:
        g[c["step"]].append(c)
    return sorted(({"step": k, **_sum(v)} for k, v in g.items()), key=lambda s: -s["total"])


def _timeline(rows, since, now):
    start = since or min((c["ts"] for c in rows), default=now - 3600)
    span = max(60, now - start)
    size = 300 if span <= 3 * 3600 else 900 if span <= 12 * 3600 else 3600 if span <= 4 * 86400 else 6 * 3600
    first = int(start // size * size)
    buckets = defaultdict(lambda: defaultdict(int))
    for c in rows:
        buckets[int(c["ts"] // size * size)][c["agent"]] += _total(c)
    n = int((now - first) // size) + 1
    return {"size": size, "start": first,
            "buckets": [{"t": first + i * size, "by": dict(buckets.get(first + i * size, {}))} for i in range(n)]}


def _mtime(p):
    try:
        return Path(p).stat().st_mtime_ns
    except OSError:
        return 0


def _iso(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0
