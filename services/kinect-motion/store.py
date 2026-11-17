"""Workout history: people, their equipment, sessions, sets and fitness checks. SQLite, local.

Only results are kept - "Karthi, squat, 12 reps, form 92" - never pictures, depth or skeletons
(the research's privacy rule: keep semantic events, not video). The file is readable by you only:
$XDG_DATA_HOME/adaptive-desktop/fitness.db (~/.local/share/...).
"""

import json
import os
import sqlite3
import time
from pathlib import Path

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "adaptive-desktop"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
    kg REAL, height_cm INTEGER, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS equipment (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
    name TEXT NOT NULL, kg REAL NOT NULL, hands INTEGER NOT NULL DEFAULT 2,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
    started REAL NOT NULL, ended REAL, plan TEXT, kcal REAL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS sets (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL,
    exercise TEXT NOT NULL, target REAL, reps INTEGER, good INTEGER, partials INTEGER, form REAL,
    seconds REAL, load_kg REAL, load_source TEXT, volume REAL, kcal REAL, details TEXT,
    at REAL NOT NULL, FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS checks (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
    at REAL NOT NULL, results TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
"""


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else DATA / "fitness.db"
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not self.path.exists()
        else:
            fresh = False
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        if fresh:
            os.chmod(self.path, 0o600)            # your history, yours only

    def _rows(self, sql, *args):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # -- people

    def users(self):
        return self._rows("SELECT * FROM users ORDER BY name")

    def user(self, uid):
        rows = self._rows("SELECT * FROM users WHERE id = ?", uid)
        return rows[0] if rows else None

    def add_user(self, name, kg=None, height_cm=None):
        name = (name or "").strip()[:40]
        if not name:
            raise ValueError("A name is needed")
        cur = self.db.execute("INSERT OR IGNORE INTO users (name, kg, height_cm, created) VALUES (?, ?, ?, ?)",
                              (name, kg, height_cm, time.time()))
        self.db.commit()
        if cur.lastrowid and cur.rowcount:
            return cur.lastrowid
        return self._rows("SELECT id FROM users WHERE name = ?", name)[0]["id"]

    def update_user(self, uid, **fields):
        allowed = {k: v for k, v in fields.items() if k in ("name", "kg", "height_cm")}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self.db.execute(f"UPDATE users SET {sets} WHERE id = ?", (*allowed.values(), uid))
        self.db.commit()

    def delete_user(self, uid):
        """Forget a person and everything recorded for them."""
        self.db.execute("DELETE FROM users WHERE id = ?", (uid,))
        self.db.commit()

    # -- equipment ("my 5 kg dumbbells": the catalog source of a load)

    def equipment(self, uid):
        return self._rows("SELECT * FROM equipment WHERE user_id = ? ORDER BY kg", uid)

    def add_equipment(self, uid, name, kg, hands=2):
        cur = self.db.execute("INSERT INTO equipment (user_id, name, kg, hands) VALUES (?, ?, ?, ?)",
                              (uid, name.strip()[:40] or f"{kg} kg", float(kg), int(hands)))
        self.db.commit()
        return cur.lastrowid

    def delete_equipment(self, eid):
        self.db.execute("DELETE FROM equipment WHERE id = ?", (eid,))
        self.db.commit()

    # -- sessions and sets

    def start_session(self, uid, plan=None):
        cur = self.db.execute("INSERT INTO sessions (user_id, started, plan) VALUES (?, ?, ?)",
                              (uid, time.time(), plan))
        self.db.commit()
        return cur.lastrowid

    def end_session(self, sid):
        kcal = self.db.execute("SELECT SUM(kcal) FROM sets WHERE session_id = ?", (sid,)).fetchone()[0]
        self.db.execute("UPDATE sessions SET ended = ?, kcal = ? WHERE id = ?", (time.time(), kcal, sid))
        self.db.commit()

    def add_set(self, sid, summary, load_kg=None, load_source="unknown", volume=None, kcal=None, seconds=None):
        details = {k: summary.get(k) for k in ("sides", "balance", "tempo_s", "held", "best", "sway_cm",
                                                "reach_cm", "jump_best_cm", "record")}
        cur = self.db.execute(
            "INSERT INTO sets (session_id, exercise, target, reps, good, partials, form, seconds, load_kg,"
            " load_source, volume, kcal, details, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, summary["exercise"], summary.get("target"), summary.get("reps"), summary.get("good"),
             summary.get("partials"), summary.get("form"), seconds, load_kg, load_source, volume, kcal,
             json.dumps(details), time.time()))
        self.db.commit()
        return cur.lastrowid

    def last_sets(self, uid, exercise, sessions=1):
        """This person's sets of an exercise in their last `sessions` sessions that had it."""
        sids = [r["session_id"] for r in self._rows(
            "SELECT DISTINCT s.session_id FROM sets s JOIN sessions x ON x.id = s.session_id"
            " WHERE x.user_id = ? AND s.exercise = ? ORDER BY s.session_id DESC LIMIT ?", uid, exercise, sessions)]
        if not sids:
            return []
        marks = ",".join("?" * len(sids))
        return self._rows(f"SELECT * FROM sets WHERE session_id IN ({marks}) AND exercise = ? ORDER BY at",
                          *sids, exercise)

    def history(self, uid, days=60):
        since = time.time() - days * 86400
        sessions = self._rows("SELECT * FROM sessions WHERE user_id = ? AND started >= ? ORDER BY started DESC",
                              uid, since)
        for s in sessions:
            s["sets"] = self._rows("SELECT exercise, target, reps, good, partials, form, seconds, load_kg,"
                                   " load_source, volume, kcal FROM sets WHERE session_id = ? ORDER BY at", s["id"])
        return sessions

    def totals(self, uid, days=7):
        since = time.time() - days * 86400
        r = self.db.execute(
            "SELECT COUNT(DISTINCT x.id), SUM(s.reps), SUM(s.kcal), SUM(s.volume), SUM(s.seconds)"
            " FROM sets s JOIN sessions x ON x.id = s.session_id WHERE x.user_id = ? AND x.started >= ?",
            (uid, since)).fetchone()
        days_active = self.db.execute(
            "SELECT COUNT(DISTINCT date(started, 'unixepoch', 'localtime')) FROM sessions"
            " WHERE user_id = ? AND started >= ?", (uid, since)).fetchone()[0]
        return {"sessions": r[0] or 0, "reps": r[1] or 0, "kcal": round(r[2] or 0),
                "volume": round(r[3] or 0), "minutes": round((r[4] or 0) / 60), "days": days_active,
                "streak": self.streak(uid)}

    def streak(self, uid):
        """Days in a row (up to today or yesterday) with a workout."""
        days = [r[0] for r in self.db.execute(
            "SELECT DISTINCT date(started, 'unixepoch', 'localtime') d FROM sessions WHERE user_id = ?"
            " ORDER BY d DESC", (uid,)).fetchall()]
        if not days:
            return 0
        import datetime
        today = datetime.date.today()
        d0 = datetime.date.fromisoformat(days[0])
        if (today - d0).days > 1:
            return 0
        n = 1
        for a, b in zip(days, days[1:]):
            if (datetime.date.fromisoformat(a) - datetime.date.fromisoformat(b)).days == 1:
                n += 1
            else:
                break
        return n

    # -- fitness checks

    def add_check(self, uid, results):
        self.db.execute("INSERT INTO checks (user_id, at, results) VALUES (?, ?, ?)",
                        (uid, time.time(), json.dumps(results)))
        self.db.commit()

    def checks(self, uid):
        rows = self._rows("SELECT * FROM checks WHERE user_id = ? ORDER BY at DESC", uid)
        for r in rows:
            r["results"] = json.loads(r["results"])
        return rows
