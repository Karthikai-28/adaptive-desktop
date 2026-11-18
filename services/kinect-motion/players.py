"""Who is playing: joining, keeping each player through crossings and exits, and where it is safe.

Pure Python + numpy. The hub numbers everyone it sees (people.py) and does the frame-to-frame
work: one global assignment per frame on predicted position, depth and body proportions, with
crossings it cannot be sure of marked `identity: "unsure"`, and numbers it gave up on listed in
`retired`. A player here owns one hub number at a time, and is in one of these states:

    active    seen in this frame, identity sure: counting, coaching and game decisions run
    unsure    seen, but the hub is not sure this is still them (mid-crossing): nothing counts
    hidden    not seen in this frame, the hub still holds their number (behind someone)
    rejoin    the hub retired their number (it could not tell two people apart): they must
              raise a hand to be this player again; nobody is matched to them automatically
    away      out of view; matched back automatically when someone comes in who is clearly
              them (where they left, as tall, the same limb lengths), and only when exactly one
              candidate is: two possible matches mean "raise a hand" instead of a guess

Joining: in a group, raising a hand for a moment joins (the research's "raise hand to join");
alone, you join just by being there. Up to four players.

Safety: whether the player's activity fits where they stand (calibration.Space, from the camera's
real geometry; a fixed band only when there is no floor yet), and players too close to swing an
arm. The page pauses that player and says why.
"""

import math

import numpy as np

import skeleton as sk

SLOTS = 4
REJOIN_SECONDS = 25.0     # a player who left keeps their slot this long
REJOIN_METRES = 1.2       # and is matched back within this distance of where they were
HEIGHT_MATCH_CM = 5.0
LIMB_MATCH = 0.04         # m: limb lengths must agree this well
AMBIGUOUS = 1.0           # cost margin: two candidates closer than this = no automatic rejoin
SPACING = 0.9             # m between two players' centres: an arm's swing
NEAR_TV = 1.3             # m: the fallback band when the camera's geometry is not known yet
FAR = 4.2
HALF_FOV = math.radians(57.0 / 2)    # Kinect v1 horizontal field of view (57 deg)
LIMBS = {"upper_arm": ((sk.L_SH, sk.L_EL), (sk.R_SH, sk.R_EL)),
         "forearm": ((sk.L_EL, sk.L_WR), (sk.R_EL, sk.R_WR)),
         "thigh": ((sk.L_HIP, sk.L_KNEE), (sk.R_HIP, sk.R_KNEE)),
         "shin": ((sk.L_KNEE, sk.L_ANK), (sk.R_KNEE, sk.R_ANK)),
         "shoulders": ((sk.L_SH, sk.R_SH),)}


class Player:
    def __init__(self, slot, track, pos, height_cm, t):
        self.slot, self.track = slot, track
        self.pos, self.height_cm = pos, height_cm
        self.seen = t
        self.joined = t
        self.profile = None           # a user id from the store, chosen on the page
        self.warning = None
        self.status = "active"
        self.limbs = {}               # name -> list of tracked lengths (m)

    def signature(self):
        return {k: float(np.median(v)) for k, v in self.limbs.items() if len(v) >= 5}

    def learn(self, body):
        for name, bones in LIMBS.items():
            vals = [float(np.linalg.norm(body.joints[a] - body.joints[b])) for a, b in bones
                    if body.states[a] == sk.TRACKED and body.states[b] == sk.TRACKED]
            if vals:
                lst = self.limbs.setdefault(name, [])
                lst.append(float(np.mean(vals)))
                del lst[:-60]

    @property
    def here(self):
        return self.status in ("active", "unsure")

    def to_dict(self, now):
        return {"slot": self.slot, "track": self.track, "profile": self.profile,
                "here": self.status == "active", "status": self.status, "warning": self.warning,
                "seen_ago": round(max(0.0, now - self.seen), 2),
                "pos": None if self.pos is None else [round(float(self.pos[0]), 2), round(float(self.pos[1]), 2)],
                "height_cm": self.height_cm}


def in_zone(pos, near=NEAR_TV, far=FAR, margin=0.35):
    """The fallback before the camera's geometry is known: is a floor point (x, z) inside a
    fixed band? -> (ok, why)."""
    x, z = float(pos[0]), float(pos[1])
    if z < near:
        return False, "Step back from the TV"
    if z > far:
        return False, "Come a little closer"
    if abs(x) > z * math.tan(HALF_FOV) - margin:
        return False, "Move towards the middle"
    return True, None


def limb_cost(sig, body):
    """How unlike a player's limb lengths this body's tracked limbs are (0 alike), or None."""
    p = Player(0, 0, None, None, 0)
    p.learn(body)
    now = {k: v[0] for k, v in p.limbs.items()}
    terms = [abs(sig[k] - v) / LIMB_MATCH for k, v in now.items() if k in sig]
    return float(np.mean(terms)) if len(terms) >= 2 else None


class Roster:
    """The players. update(bodies, now, hub) after every frame; join() from a raised hand."""

    def __init__(self, auto_solo=True):
        self.players = []
        self.auto_solo = auto_solo
        self.spacing = SPACING
        self.space = None             # calibration.Space, set by the engine when the floor is known
        self.activity = None          # what everyone is doing (an ENVELOPES key), for safety

    def by_track(self, track):
        return next((p for p in self.players if p.track == track), None)

    def by_slot(self, slot):
        return next((p for p in self.players if p.slot == slot), None)

    def free_slot(self):
        used = {p.slot for p in self.players}
        return next((s for s in range(SLOTS) if s not in used), None)

    def join(self, body, now):
        """Give this body a slot (no-op if it has one): a player waiting to rejoin first, else a
        free slot. Returns the Player or None if full."""
        p = self.by_track(body.id)
        if p is not None:
            return p
        waiting = sorted((q for q in self.players if q.status == "rejoin"), key=lambda q: q.slot)
        if waiting:
            p = waiting[0]
            p.track, p.seen, p.status = body.id, now, "active"
            p.pos = body.centre() if body.centre() is not None else p.pos
            return p
        slot = self.free_slot()
        if slot is None:
            return None
        p = Player(slot, body.id, body.centre(), body.height_cm, now)
        self.players.append(p)
        return p

    def leave(self, slot):
        self.players = [p for p in self.players if p.slot != slot]

    def update(self, bodies, now, hub=None):
        """Follow tracks to players; bring back players who stepped out. -> events.

        hub: the hub's state (for `hidden` and `retired`), or None."""
        hub = hub or {}
        events = []
        current = {b.id: b for b in bodies}
        hidden = {h["id"] for h in hub.get("hidden") or []}
        retired = {r["id"] for r in hub.get("retired") or []}
        for p in self.players:
            b = current.get(p.track)
            before = p.status
            if b is not None:
                p.seen = now
                c = b.centre()
                if c is not None:
                    p.pos = c
                if b.height_cm:
                    p.height_cm = b.height_cm
                p.status = "unsure" if getattr(b, "identity", "sure") == "unsure" else "active"
                if p.status == "active":
                    p.learn(b)
            elif p.status == "rejoin":
                pass
            elif p.track in retired:
                p.status = "rejoin"
            elif p.track in hidden:
                p.status = "hidden"
            else:
                p.status = "away"
            if p.status != before:
                events.append({"type": "status", "slot": p.slot, "status": p.status, "was": before})
        events += self._rematch(bodies, now)
        # Gone for good.
        for p in [p for p in self.players if now - p.seen >= REJOIN_SECONDS]:
            events.append({"type": "left", "slot": p.slot})
            self.players.remove(p)
        # Alone in the room: you are the player.
        if self.auto_solo and not self.players and len(bodies) == 1 and \
                getattr(bodies[0], "identity", "sure") == "sure":
            p = self.join(bodies[0], now)
            if p:
                events.append({"type": "joined", "slot": p.slot, "auto": True})
        self._safety(now, events)
        return events

    def _rematch(self, bodies, now):
        """Away players and newcomers: back automatically only when it is clearly them."""
        owned = {p.track for p in self.players}
        away = [p for p in self.players if p.status == "away" and now - p.seen < REJOIN_SECONDS]
        fresh = [b for b in bodies if b.id not in owned and getattr(b, "identity", "sure") == "sure"]
        if not away or not fresh:
            return []
        cost = {}
        for p in away:
            sig = p.signature()
            for b in fresh:
                c = b.centre()
                if p.pos is None or c is None:
                    continue
                d = float(np.linalg.norm(c - p.pos))
                if d > REJOIN_METRES:
                    continue
                if p.height_cm and b.height_cm and abs(p.height_cm - b.height_cm) > HEIGHT_MATCH_CM:
                    continue
                lc = limb_cost(sig, b) if sig else None
                if lc is not None and lc > 2.0:        # limbs clearly someone else's
                    continue
                cost[(p.slot, b.id)] = d / 0.4 + (0.0 if lc is None else lc)
        events = []
        for p in away:
            mine = sorted((c, bid) for (slot, bid), c in cost.items() if slot == p.slot)
            if not mine:
                continue
            c, bid = mine[0]
            # Somebody else could be this person just as well, or this person could be
            # another away player just as well: ask instead of guessing.
            rivals = [x for x, _ in mine[1:] if x - c < AMBIGUOUS]
            others = [cc for (slot, b2), cc in cost.items() if b2 == bid and slot != p.slot and cc - c < AMBIGUOUS]
            if rivals or others:
                if p.status != "rejoin":
                    p.status = "rejoin"
                    events.append({"type": "status", "slot": p.slot, "status": "rejoin", "was": "away",
                                   "why": "ambiguous"})
                continue
            events.append({"type": "rejoined", "slot": p.slot, "from": p.track, "to": bid})
            p.track, p.seen, p.status = bid, now, "active"
            for k in [k for k in cost if k[1] == bid or k[0] == p.slot]:
                cost.pop(k)
        return events

    def _safety(self, now, events):
        here = [p for p in self.players if p.status == "active" and p.pos is not None]
        for p in self.players:
            if p not in here:
                continue
            if self.space is not None:
                ok, why = self.space.fits(self.activity or "squat", p.pos,
                                          (p.height_cm or 175) / 100)
            else:
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
