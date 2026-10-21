"""SQLite persistence: tasks, chat messages, activity events, meetings, key/value."""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT NOT NULL, title TEXT NOT NULL, body TEXT DEFAULT '', project TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued', created_by TEXT DEFAULT 'operator',
  depends_on INTEGER, attempts INTEGER DEFAULT 0, repo TEXT DEFAULT '',
  created_at REAL, started_at REAL, finished_at REAL,
  result TEXT DEFAULT '', error TEXT DEFAULT '', steps INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0,
  mission_id INTEGER
);
CREATE TABLE IF NOT EXISTS missions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, objective TEXT NOT NULL, project TEXT DEFAULT '', repo TEXT DEFAULT '',
  criteria TEXT DEFAULT '[]', status TEXT NOT NULL DEFAULT 'queued', created_by TEXT DEFAULT 'operator',
  created_at REAL, started_at REAL, finished_at REAL, summary TEXT DEFAULT '', error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread TEXT NOT NULL, sender TEXT NOT NULL, text TEXT NOT NULL, ts REAL, meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread, id);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT NOT NULL, task_id INTEGER, kind TEXT, text TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS events_agent ON events(agent, id);
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT, attendees TEXT, status TEXT DEFAULT 'active',
  started_at REAL, ended_at REAL, minutes_path TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

TASK_FIELDS = ("agent", "title", "body", "project", "status", "created_by", "depends_on",
               "attempts", "created_at", "started_at", "finished_at", "result", "error",
               "steps", "tokens", "repo", "mission_id")
MISSION_FIELDS = ("title", "objective", "project", "repo", "criteria", "status", "created_by",
                  "created_at", "started_at", "finished_at", "summary", "error")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        if "repo" not in {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}:   # older databases
            self.db.execute("ALTER TABLE tasks ADD COLUMN repo TEXT DEFAULT ''")
        if "mission_id" not in {r[1] for r in self.db.execute("PRAGMA table_info(tasks)")}:
            self.db.execute("ALTER TABLE tasks ADD COLUMN mission_id INTEGER")
        self.db.execute("CREATE INDEX IF NOT EXISTS tasks_mission ON tasks(mission_id, id)")

    # ---- key/value ----
    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))

    def delete(self, key):
        self.db.execute("DELETE FROM kv WHERE key=?", (key,))

    def delete_prefix(self, prefix):
        self.db.execute("DELETE FROM kv WHERE key LIKE ?", (prefix.replace("%", r"\%") + "%",))

    # ---- tasks ----
    def add_task(self, agent, title, body="", project="", created_by="operator", depends_on=None, repo="",
                 mission_id=None):
        cur = self.db.execute(
            "INSERT INTO tasks(agent,title,body,project,created_by,depends_on,created_at,repo,mission_id) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (agent, title, body, project, created_by, depends_on, time.time(), repo, mission_id))
        return self.task(cur.lastrowid)

    def task(self, tid):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None

    def update_task(self, tid, **kw):
        bad = set(kw) - set(TASK_FIELDS)
        if bad:
            raise ValueError(f"unknown task fields {bad}")
        sets = ",".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*kw.values(), tid))
        return self.task(tid)

    def tasks(self, agent=None, status=None, limit=200, created_since=None):
        q, args = "SELECT * FROM tasks WHERE 1=1", []
        if agent:
            q += " AND agent=?"; args.append(agent)
        if status:
            st = status.split(",")
            q += f" AND status IN ({','.join('?' * len(st))})"; args += st
        if created_since:
            q += " AND created_at>=?"; args.append(created_since)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        return [dict(r) for r in self.db.execute(q, args)]

    def next_queued(self, agent):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM tasks WHERE agent=? AND status='queued' ORDER BY id", (agent,))]

    # ---- missions ----
    @staticmethod
    def _mission(row):
        return dict(row, criteria=json.loads(row["criteria"] or "[]")) if row else None

    def add_mission(self, title, objective, criteria=None, project="", repo="", created_by="operator"):
        cur = self.db.execute(
            "INSERT INTO missions(title,objective,criteria,project,repo,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
            (title, objective, json.dumps(criteria or []), project, repo, created_by, time.time()))
        return self.mission(cur.lastrowid)

    def mission(self, mid, with_tasks=False):
        row = self.db.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()
        out = self._mission(row)
        if out is not None and with_tasks:
            out["tasks"] = [dict(r) for r in self.db.execute(
                "SELECT * FROM tasks WHERE mission_id=? ORDER BY id", (mid,))]
        return out

    def missions(self, limit=100):
        return [self._mission(r) for r in self.db.execute(
            "SELECT * FROM missions ORDER BY id DESC LIMIT ?", (limit,))]

    def update_mission(self, mid, **kw):
        bad = set(kw) - set(MISSION_FIELDS)
        if bad:
            raise ValueError(f"unknown mission fields {bad}")
        if "criteria" in kw and not isinstance(kw["criteria"], str):
            kw["criteria"] = json.dumps(kw["criteria"])
        sets = ",".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE missions SET {sets} WHERE id=?", (*kw.values(), mid))
        return self.mission(mid, with_tasks=True)

    # ---- messages ----
    def add_message(self, thread, sender, text, meta=None):
        ts = time.time()
        cur = self.db.execute("INSERT INTO messages(thread,sender,text,ts,meta) VALUES(?,?,?,?,?)",
                              (thread, sender, text, ts, json.dumps(meta or {})))
        return {"id": cur.lastrowid, "thread": thread, "sender": sender, "text": text, "ts": ts, "meta": meta or {}}

    def messages(self, thread, limit=100, after_id=0):
        rows = self.db.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE thread=? AND id>? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (thread, after_id, limit)).fetchall()
        return [dict(r, meta=json.loads(r["meta"] or "{}")) for r in rows]

    # ---- activity events ----
    def add_event(self, agent, kind, text, task_id=None):
        ts = time.time()
        cur = self.db.execute("INSERT INTO events(agent,task_id,kind,text,ts) VALUES(?,?,?,?,?)",
                              (agent, task_id, kind, text, ts))
        return {"id": cur.lastrowid, "agent": agent, "task_id": task_id, "kind": kind, "text": text, "ts": ts}

    def events(self, agent=None, task_id=None, limit=100):
        q, args = "SELECT * FROM events WHERE 1=1", []
        if agent:
            q += " AND agent=?"; args.append(agent)
        if task_id:
            q += " AND task_id=?"; args.append(task_id)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        return [dict(r) for r in self.db.execute(q, args)][::-1]

    # ---- meetings ----
    def start_meeting(self, topic, attendees):
        cur = self.db.execute("INSERT INTO meetings(topic,attendees,started_at) VALUES(?,?,?)",
                              (topic, json.dumps(attendees), time.time()))
        return self.meeting(cur.lastrowid)

    def meeting(self, mid):
        row = self.db.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
        return dict(row, attendees=json.loads(row["attendees"])) if row else None

    def active_meeting(self):
        row = self.db.execute("SELECT id FROM meetings WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
        return self.meeting(row[0]) if row else None

    def end_meeting(self, mid, minutes_path=""):
        self.db.execute("UPDATE meetings SET status='ended', ended_at=?, minutes_path=? WHERE id=?",
                        (time.time(), minutes_path, mid))
        return self.meeting(mid)

    def set_attendees(self, mid, attendees):
        self.db.execute("UPDATE meetings SET attendees=? WHERE id=?", (json.dumps(attendees), mid))
