"""Who is playing: joining, keeping each player across exits, and the safe play area.

Pure Python + numpy. The hub numbers everyone it sees, but a number is not a person: someone who
walks out of view and back gets a new one. A player therefore keeps their slot (colour, profile,
running count) and is matched back by where they stand and how tall they are; the hub measures
height in centimetres while people stand straight (people.py).

Joining: in a group, raising a hand for a moment joins (the research's "raise hand to join");
alone, you join just by being there. Up to four players.

Safety: the floor area the Kinect sees well, players too close to one another to swing an arm,
and anyone too near the TV. The page pauses that player and says why.
"""

import math

import numpy as np

SLOTS = 4
REJOIN_SECONDS = 25.0     # a player who left keeps their slot this long
REJOIN_METRES = 1.2       # and is matched back within this distance of where they were
HEIGHT_MATCH_CM = 5.0
SPACING = 0.9             # m between two players' centres: an arm's swing
NEAR_TV = 1.3             # m: closer and depth fails and feet leave the picture
FAR = 4.2
HALF_FOV = math.radians(57.0 / 2)    # Kinect v1 horizontal field of view (57 deg)


class Player:
    def __init__(self, slot, track, pos, height_cm, t):
        self.slot, self.track = slot, track
        self.pos, self.height_cm = pos, height_cm
        self.seen = t
        self.joined = t
        self.profile = None           # a user id from the store, chosen on the page
        self.warning = None

    def to_dict(self, now):
        return {"slot": self.slot, "track": self.track, "profile": self.profile,
                "here": now - self.seen < 0.6, "warning": self.warning,
                "pos": None if self.pos is None else [round(float(self.pos[0]), 2), round(float(self.pos[1]), 2)],
                "height_cm": self.height_cm}


def in_zone(pos, near=NEAR_TV, far=FAR, margin=0.35):
    """Is a floor point (x, z) where the Kinect sees a whole body well? -> (ok, why)."""
    x, z = float(pos[0]), float(pos[1])
    if z < near:
        return False, "Step back from the TV"
    if z > far:
        return False, "Come a little closer"
    if abs(x) > z * math.tan(HALF_FOV) - margin:
        return False, "Move towards the middle"
    return True, None


class Roster:
    """The players. update(bodies, now) after every frame; join() from a raised hand."""

    def __init__(self, auto_solo=True):
        self.players = []
        self.auto_solo = auto_solo
        self.spacing = SPACING

    def by_track(self, track):
        return next((p for p in self.players if p.track == track), None)

    def free_slot(self):
        used = {p.slot for p in self.players}
        return next((s for s in range(SLOTS) if s not in used), None)

    def join(self, body, now):
        """Give this body a slot (no-op if it has one). Returns the Player or None if full."""
        p = self.by_track(body.id)
        if p is not None:
            return p
        slot = self.free_slot()
        if slot is None:
            return None
        p = Player(slot, body.id, body.centre(), body.height_cm, now)
        self.players.append(p)
        return p

    def leave(self, slot):
        self.players = [p for p in self.players if p.slot != slot]

    def update(self, bodies, now):
        """Follow tracks to players; bring back players who stepped out. -> events."""
        events = []
        current = {b.id: b for b in bodies}
        for p in self.players:
            b = current.get(p.track)
            if b is not None:
                p.seen = now
                c = b.centre()
                if c is not None:
                    p.pos = c
                if b.height_cm:
                    p.height_cm = b.height_cm
        # A track nobody owns, near where a missing player was (and as tall): that player is back.
        missing = [p for p in self.players if p.track not in current and now - p.seen < REJOIN_SECONDS]
        owned = {p.track for p in self.players}
        for b in bodies:
            if b.id in owned or not missing:
                continue
            c = b.centre()
            best, best_d = None, REJOIN_METRES
            for p in missing:
                if p.pos is None or c is None:
                    continue
                d = float(np.linalg.norm(c - p.pos))
                if p.height_cm and b.height_cm and abs(p.height_cm - b.height_cm) > HEIGHT_MATCH_CM:
                    continue
                if d < best_d:
                    best, best_d = p, d
            if best is not None:
                events.append({"type": "rejoined", "slot": best.slot, "from": best.track, "to": b.id})
                best.track, best.seen = b.id, now
                missing.remove(best)
                owned.add(b.id)
        # Gone for good.
        for p in [p for p in self.players if now - p.seen >= REJOIN_SECONDS]:
            events.append({"type": "left", "slot": p.slot})
            self.players.remove(p)
        # Alone in the room: you are the player.
        if self.auto_solo and not self.players and len(bodies) == 1:
            p = self.join(bodies[0], now)
            if p:
                events.append({"type": "joined", "slot": p.slot, "auto": True})
        self._safety(now, events)
        return events

    def _safety(self, now, events):
        here = [p for p in self.players if now - p.seen < 0.6 and p.pos is not None]
        for p in here:
            ok, why = in_zone(p.pos)
            warning = None if ok else why
            for q in here:
                if q is not p and float(np.linalg.norm(p.pos - q.pos)) < self.spacing:
                    warning = "Too close to another player: spread out"
            if warning != p.warning:
                events.append({"type": "safety", "slot": p.slot, "warning": warning})
            p.warning = warning

    def state(self, now):
        return [p.to_dict(now) for p in sorted(self.players, key=lambda p: p.slot)]
