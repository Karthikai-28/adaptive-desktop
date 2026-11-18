"""Workout history: people, their equipment, sessions, sets and fitness checks. SQLite, local.

Only results are kept - "Karthi, squat, 12 reps, form 92" - never pictures, depth or skeletons
(the research's privacy rule: keep semantic events, not video). The file is readable by you only:
$XDG_DATA_HOME/adaptive-desktop/fitness.db (~/.local/share/...).

Schema versions (PRAGMA user_version), migrated in place on open, never by dropping a table:
    1  people, equipment, sessions, sets, fitness checks (Kinect Fitness)
    2  game results, tracking quality per workout or game (how well the Kinect saw each
       player: share of time seen, losses, update rate, evidence), and saved scans (only what
       you chose to save: a name, where the files are, the measurement report)
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
VERSION = 2
MIGRATIONS = {
    2: """
CREATE TABLE IF NOT EXISTS games (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
    game TEXT NOT NULL, score INTEGER, details TEXT, at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS quality (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
    session_id INTEGER, game_id INTEGER, at REAL NOT NULL, activity TEXT, seconds REAL,
    seen_share REAL, losses INTEGER, lost_seconds REAL, updates_per_s REAL, evidence REAL,
    dark_share REAL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT,
    path TEXT NOT NULL, at REAL NOT NULL, report TEXT);
""",
}


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
        self.migrated = self._migrate()
        if fresh:
            os.chmod(self.path, 0o600)            # your history, yours only

    def _migrate(self):
        """Bring an older file up to VERSION, keeping everything in it. -> versions applied."""
        have = self.db.execute("PRAGMA user_version").fetchone()[0] or 1
        done = []
        for v in range(have + 1, VERSION + 1):
            self.db.executescript(MIGRATIONS[v])
            self.db.execute(f"PRAGMA user_version = {v}")
            done.append(v)
        self.db.commit()
        return done

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

    # -- games and how well the Kinect saw each player

    def add_game(self, uid, game, score, details=None):
        cur = self.db.execute("INSERT INTO games (user_id, game, score, details, at) VALUES (?, ?, ?, ?, ?)",
                              (uid, game, int(score or 0), json.dumps(details or {}), time.time()))
        self.db.commit()
        return cur.lastrowid

    def games(self, uid, days=60):
        rows = self._rows("SELECT * FROM games WHERE user_id = ? AND at >= ? ORDER BY at DESC",
                          uid, time.time() - days * 86400)
        for r in rows:
            r["details"] = json.loads(r["details"] or "{}")
        return rows

    def best_games(self, uid):
        return {r["game"]: r["best"] for r in self._rows(
            "SELECT game, MAX(score) best FROM games WHERE user_id = ? GROUP BY game", uid)}

    def add_quality(self, uid, q, session_id=None, game_id=None):
        self.db.execute(
            "INSERT INTO quality (user_id, session_id, game_id, at, activity, seconds, seen_share, losses,"
            " lost_seconds, updates_per_s, evidence, dark_share) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, session_id, game_id, time.time(), q.get("activity"), q.get("seconds"), q.get("seen_share"),
             q.get("losses"), q.get("lost_seconds"), q.get("updates_per_s"), q.get("evidence"),
             q.get("dark_share")))
        self.db.commit()

    def quality(self, uid, days=60):
        """How well the Kinect saw this person, by activity, over the last `days`."""
        return self._rows(
            "SELECT activity, COUNT(*) n, ROUND(SUM(seconds) / 60.0, 1) minutes,"
            " ROUND(AVG(seen_share), 3) seen_share, SUM(losses) losses, ROUND(AVG(updates_per_s), 1) updates_per_s,"
            " ROUND(AVG(evidence), 2) evidence, ROUND(AVG(dark_share), 2) dark_share"
            " FROM quality WHERE user_id = ? AND at >= ? GROUP BY activity ORDER BY minutes DESC",
            uid, time.time() - days * 86400)

    def movement(self, uid, days=28):
        """Per exercise: repetitions, form, range of motion, tempo and left/right balance, from the
        sets' own per-repetition records (what was measured, never a picture)."""
        out = {}
        rows = self._rows("SELECT s.exercise, s.reps, s.form, s.details FROM sets s JOIN sessions x"
                          " ON x.id = s.session_id WHERE x.user_id = ? AND s.at >= ? ORDER BY s.at",
                          uid, time.time() - days * 86400)
        for r in rows:
            m = out.setdefault(r["exercise"], {"sets": 0, "reps": 0, "form": [], "rom": [], "tempo": [],
                                              "left": 0, "right": 0})
            m["sets"] += 1
            m["reps"] += r["reps"] or 0
            if r["form"] is not None:
                m["form"].append(r["form"])
            d = json.loads(r["details"] or "{}")
            for rec in d.get("record") or []:
                if rec.get("rom") is not None:
                    m["rom"].append(rec["rom"])
                if rec.get("time_s") is not None:
                    m["tempo"].append(rec["time_s"])
            sides = d.get("sides") or {}
            m["left"] += sides.get("left", 0) or 0
            m["right"] += sides.get("right", 0) or 0
        avg = lambda v, k=1: round(sum(v) / len(v), k) if v else None   # noqa: E731
        return {k: {"sets": m["sets"], "reps": m["reps"], "form": avg(m["form"], 0),
                    "rom": avg(m["rom"], 2), "tempo_s": avg(m["tempo"], 2),
                    "sides": {"left": m["left"], "right": m["right"]} if m["left"] + m["right"] else None}
                for k, m in out.items()}

    # -- deleting history

    def delete_session(self, sid):
        self.db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        self.db.commit()

    def delete_history(self, uid=None):
        """Every workout, set, check, game and quality record (of one person, or of everyone);
        the people and their equipment stay."""
        for table in ("quality", "games", "checks", "sessions"):
            if uid is None:
                self.db.execute(f"DELETE FROM {table}")
            else:
                self.db.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        self.db.commit()
        self.db.execute("VACUUM")             # deleted means gone from the file too

    # -- saved scans (only what you chose to save)

    def add_scan(self, name, kind, path, report):
        cur = self.db.execute("INSERT INTO scans (name, kind, path, at, report) VALUES (?, ?, ?, ?, ?)",
                              (name[:80], kind, str(path), time.time(), json.dumps(report)))
        self.db.commit()
        return cur.lastrowid

    def scans(self):
        rows = self._rows("SELECT * FROM scans ORDER BY at DESC")
        for r in rows:
            r["report"] = json.loads(r["report"] or "{}")
        return rows

    def delete_scan(self, scan_id):
        self.db.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
        self.db.commit()

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
