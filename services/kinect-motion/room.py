"""The room as events: who is here, where, for how long sitting, and what they point at.

Pure Python + numpy. This is the research's "productivity layer": the camera stays inside the
hub, and what leaves it is a small semantic event - room_occupied, person_enter_zone,
sit_reminder, point_at_zone - for Mario, the desktop or Home Assistant to act on.

Zones are rectangles on the floor (x, z in metres, the hub's room frame) or on the TV wall (x, y),
named in ~/.config/adaptive-desktop/motion.json:
  {"zones": [{"name": "sofa", "on": "floor", "x": [-1.2, 0.4], "z": [2.6, 3.6]},
             {"name": "lamp", "on": "wall", "x": [1.0, 1.6], "y": [0.0, 1.8]}],
   "sit_minutes": 45, "slouch_degrees": 25}

The coverage map answers the research's first prototype: where in this room is a body tracked
well? Each floor cell (25 cm) keeps the average share of joints the Kinect really saw there.
"""

import numpy as np

CELL = 0.25
GRID_X = (-2.5, 2.5)
GRID_Z = (0.5, 5.0)


def inside(zone, point):
    keys = ("x", "z") if zone.get("on", "floor") == "floor" else ("x", "y")
    (a0, a1), (b0, b1) = zone[keys[0]], zone[keys[1]]
    return a0 <= point[0] <= a1 and b0 <= point[1] <= b1


class Room:
    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.zones = [z for z in cfg.get("zones", []) if z.get("name")]
        self.sit_seconds = 60.0 * float(cfg.get("sit_minutes", 45))
        self.slouch = float(cfg.get("slouch_degrees", 25))
        self.count = 0
        self.where = {}             # track -> set of zone names
        self.sitting_since = {}     # track -> time
        self.reminded = {}
        self.slouch_since = {}
        nx = int(round((GRID_X[1] - GRID_X[0]) / CELL))
        nz = int(round((GRID_Z[1] - GRID_Z[0]) / CELL))
        self.cov_sum = np.zeros((nz, nx))
        self.cov_n = np.zeros((nz, nx))

    def step(self, bodies, gestures, now):
        """bodies: this frame's sk.Body list; gestures: {track: [events]}. -> events."""
        out = []
        n = len(bodies)
        if n != self.count:
            if self.count == 0:
                out.append({"event": "room_occupied", "people": n})
            elif n == 0:
                out.append({"event": "room_empty"})
            else:
                out.append({"event": "people_count", "people": n})
            self.count = n
        ids = set()
        for b in bodies:
            ids.add(b.id)
            c = b.centre()
            if c is not None:
                self._coverage(c, b)
                now_in = {z["name"] for z in self.zones if z.get("on", "floor") == "floor" and inside(z, c)}
                before = self.where.get(b.id, set())
                for name in now_in - before:
                    out.append({"event": "person_enter_zone", "zone": name, "person": b.id})
                for name in before - now_in:
                    out.append({"event": "person_leave_zone", "zone": name, "person": b.id})
                self.where[b.id] = now_in
            out += self._sitting(b, now)
            for g in gestures.get(b.id, []):
                if g["gesture"] in ("raise_left", "raise_right"):
                    out.append({"event": "raise_hand", "person": b.id, "hand": g["gesture"][6:]})
                elif g["gesture"] == "point":
                    hit = [z["name"] for z in self.zones if z.get("on", "floor") == g["at"]
                           and inside(z, g["point"])]
                    out.append({"event": "point_at_zone" if hit else "point_at", "person": b.id,
                                "zone": hit[0] if hit else None, "on": g["at"], "point": g["point"]})
        for gone in set(self.where) - ids:
            for name in self.where.pop(gone):
                out.append({"event": "person_leave_zone", "zone": name, "person": gone})
        for d in (self.sitting_since, self.reminded, self.slouch_since):
            for gone in set(d) - ids:
                d.pop(gone, None)
        return out

    def _sitting(self, b, now):
        out = []
        if b.posture == "sitting":
            start = self.sitting_since.setdefault(b.id, now)
            if now - start >= self.sit_seconds and now - self.reminded.get(b.id, 0) >= self.sit_seconds:
                self.reminded[b.id] = now
                out.append({"event": "sit_reminder", "person": b.id, "minutes": round((now - start) / 60),
                            "say": "You've been sitting a while. Time to stand up and stretch."})
            lean = b.trunk_lean()
            if lean is not None and lean > self.slouch:
                s = self.slouch_since.setdefault(b.id, now)
                if now - s >= 600:
                    self.slouch_since[b.id] = now
                    out.append({"event": "posture_warning", "person": b.id, "lean": round(lean),
                                "say": "You've been slouching for ten minutes. Sit back and lift your chest."})
            else:
                self.slouch_since.pop(b.id, None)
        else:
            self.sitting_since.pop(b.id, None)
            self.slouch_since.pop(b.id, None)
        return out

    def _coverage(self, c, b):
        i = int((c[1] - GRID_Z[0]) / CELL)
        j = int((c[0] - GRID_X[0]) / CELL)
        if 0 <= i < self.cov_sum.shape[0] and 0 <= j < self.cov_sum.shape[1]:
            self.cov_sum[i, j] += float(np.mean(b.states == 2))
            self.cov_n[i, j] += 1

    def coverage(self):
        """The heat map: rows from near (z = 0.5 m) to far, columns left to right of the picture;
        each cell the share of joints tracked (0..1) or None where nobody stood."""
        with np.errstate(invalid="ignore", divide="ignore"):
            m = self.cov_sum / self.cov_n
        return {"cell": CELL, "x": list(GRID_X), "z": list(GRID_Z),
                "grid": [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in m],
                "samples": int(self.cov_n.sum())}

    def reset_coverage(self):
        self.cov_sum[:] = 0
        self.cov_n[:] = 0
