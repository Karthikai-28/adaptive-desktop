"""Kinect Arcade's games, decided here and only drawn by the page. Pure Python + numpy.

The page used to number players left to right and score them from whatever joints it had last,
however old. Now every decision runs on the same evidence as Kinect Fitness:

    players    the engine's roster slots (players.py), never positions in the picture
    evidence   a body counts only when the player is `active` (seen this frame, identity sure)
               and the joints a move needs were seen (tracked, or a few inferred:
               skeleton.Body.evidence)
    loss       a player not seen (hidden, unsure, away, stale frames) freezes: their wall stops
               where it is, their round clock stops, their car coasts and cannot hit anything,
               and nothing they did not do is held against them. A wall that arrives while the
               moves it needs cannot be seen is waved through: no point, no life lost

Time is the engine's clock (`tick(now)`, also between camera frames), and every moving thing is
sent with the times it was made and is due, so the page animates smoothly at its own frame rate
while the decisions stay tied to what the camera saw.

    Wall Dodge   walls rush down each player's lane; duck, jump, lean left/right, arms up or
                 arms out to fit through as it arrives. Three lives; walls speed up.
    Pose Match   copy the figure (Star, Robot, Goalpost, T, Skier, Reach up, Half star) and hold
                 it for a second; similarity from joint angles; quicker scores more.
    Body Racer   one road per player, 60 s. Steer an imaginary wheel or lean; hands out to go,
                 back to brake. Coins and cones, placed along the road (a stopped car meets none).
"""

import random

import bodygestures
import skeleton as sk
from skeleton import (L_ANK, L_EL, L_HIP, L_KNEE, L_SH, L_WR, NOSE, R_ANK, R_EL, R_HIP, R_KNEE,
                      R_SH, R_WR)

EVIDENCE = 0.6               # share of a move's joints seen well enough to judge it


def _need(b, ids):
    return b.evidence(ids) >= EVIDENCE and not any(b.states[i] == sk.MISSING for i in ids)


class Lane:
    """What the game keeps per player slot."""

    def __init__(self, slot):
        self.slot = slot
        self.score = 0
        self.status = "active"
        self.stand_hip = None
        self.seen_at = None


class Game:
    key = name = ""
    tutorial = []
    envelope = None

    def __init__(self, slots, now, seed=None):
        self.rng = random.Random(seed)
        self.t0 = now
        self.lanes = {s: self.new_lane(s) for s in slots}
        self.over = False
        self.events = []

    def new_lane(self, slot):
        return Lane(slot)

    def add(self, slot):
        if slot not in self.lanes:
            self.lanes[slot] = self.new_lane(slot)

    def learn(self, lane, b):
        """Standing hip height, learnt while upright and still (duck / jump are against it)."""
        h, k = b.hip_height(), [v for v in (b.knee("left"), b.knee("right")) if v is not None]
        if h is not None and k and min(k) > 160 and (b.trunk_lean() or 0) < 15:
            lane.stand_hip = h if lane.stand_hip is None else 0.95 * lane.stand_hip + 0.05 * h

    def frame(self, slot, b, now):
        """A fresh, sure sighting of this player."""
        lane = self.lanes.get(slot)
        if lane is None:
            return
        lane.seen_at = now
        self.learn(lane, b)
        self.on_frame(lane, b, now)

    def on_frame(self, lane, b, now):
        pass

    def tick(self, now, status):
        """Advance the game to `now`; status: slot -> the roster's player status."""
        for slot, lane in self.lanes.items():
            lane.status = status.get(slot, "away")
        self.on_tick(now)
        out, self.events = self.events, []
        return out

    def emit(self, slot, kind, **kw):
        self.events.append({"type": "game", "game": self.key, "slot": slot, "event": kind, **kw})

    def state(self, now):
        return {"key": self.key, "name": self.name, "over": self.over, "t": round(now, 3),
                "tutorial": self.tutorial,
                "lanes": {str(s): self.lane_state(l, now) for s, l in sorted(self.lanes.items())}}

    def lane_state(self, lane, now):
        return {"slot": lane.slot, "score": lane.score, "status": lane.status}


# ------------------------------------------------------------------ Wall Dodge

def _pose_flags(b, lane):
    """Which wall each pose would pass, with None where the joints were not seen well enough."""
    out = {}
    hips = (L_HIP, R_HIP)
    h = b.hip_height() if _need(b, hips) else None
    if h is not None and lane.stand_hip is not None:
        out["duck"] = h < lane.stand_hip - 0.22
        out["jump"] = h > lane.stand_hip + 0.06
    else:
        out["duck"] = out["jump"] = None
    if _need(b, (L_SH, R_SH, L_HIP, R_HIP)):
        lean = bodygestures.lean_of(b)
        out["left"], out["right"] = lean < -0.45, lean > 0.45
    else:
        out["left"] = out["right"] = None
    if _need(b, (L_WR, R_WR, NOSE)):
        up = [b.p(w)[1] - b.p(NOSE)[1] for w in (L_WR, R_WR)]
        out["up"] = min(up) > 0.08
    else:
        out["up"] = None
    if _need(b, (L_SH, R_SH, L_EL, R_EL, L_HIP, R_HIP)):
        ab = [b.abduction(s) for s in ("left", "right")]
        out["out"] = all(a is not None and 70 < a < 115 for a in ab)
    else:
        out["out"] = None
    return out


class WallLane(Lane):
    def __init__(self, slot):
        super().__init__(slot)
        self.lives = 3
        self.wall = None
        self.ok_at = {}            # wall kind -> last time the pose fitted it
        self.unseen_at = {}        # wall kind -> last time its joints could not be judged
        self.passed = 0
        self.streak = 0
        self.last = None           # the last wall's result, for the page's flash


class WallDodge(Game):
    key, name = "walls", "Wall Dodge"
    KINDS = {"duck": "DUCK", "jump": "JUMP", "left": "LEAN LEFT", "right": "LEAN RIGHT",
             "up": "ARMS UP", "out": "ARMS OUT"}
    TRAVEL = 3.6                 # s from the far end to you at the start
    FASTEST = 1.8
    WINDOW = 0.45                # s before arrival in which the pose counts (jumps are brief)
    tutorial = [
        {"pose": "duck", "say": "Duck: bend your knees and drop your hips."},
        {"pose": "jump", "say": "Jump: both feet off the floor as the wall arrives."},
        {"pose": "left", "say": "Lean left or right from the hips."},
        {"pose": "up", "say": "Arms up: both hands above your head."},
        {"pose": "out", "say": "Arms out: straight out to the sides, like a T."},
    ]

    def new_lane(self, slot):
        return WallLane(slot)

    def travel(self, lane):
        return max(self.FASTEST, self.TRAVEL - 0.08 * lane.passed)

    def on_frame(self, lane, b, now):
        for kind, ok in _pose_flags(b, lane).items():
            if ok is None:
                lane.unseen_at[kind] = now
            elif ok:
                lane.ok_at[kind] = now

    def on_tick(self, now):
        for lane in self.lanes.values():
            if lane.lives <= 0:
                continue
            if lane.wall is None:
                kind = self.rng.choice(list(self.KINDS))
                lane.wall = {"kind": kind, "say": self.KINDS[kind], "made": now,
                             "due": now + self.travel(lane), "frozen": None}
                continue
            w = lane.wall
            if lane.status != "active":
                # Not seen: the wall waits where it is.
                if w["frozen"] is None:
                    w["frozen"] = now
                continue
            if w["frozen"] is not None:
                shift = now - w["frozen"]
                w["made"] += shift
                w["due"] += shift
                w["frozen"] = None
            if now < w["due"]:
                continue
            kind = w["kind"]
            fitted = lane.ok_at.get(kind, -1e9) >= w["due"] - self.WINDOW
            unseen = lane.unseen_at.get(kind, -1e9) >= w["due"] - self.WINDOW and not fitted
            fresh = lane.seen_at is not None and now - lane.seen_at < 0.3
            if fitted:
                lane.score += 1 + min(lane.streak, 4)
                lane.passed += 1
                lane.streak += 1
                result = "pass"
            elif unseen or not fresh:
                result = "unseen"        # waved through: the camera could not judge it
            else:
                lane.lives -= 1
                lane.streak = 0
                result = "hit"
            lane.last = {"result": result, "kind": kind, "at": round(now, 3)}
            self.emit(lane.slot, result, wall=kind, score=lane.score, lives=lane.lives)
            lane.wall = None
        if self.lanes and all(lane.lives <= 0 for lane in self.lanes.values()):
            if not self.over:
                self.over = True
                self.emit(None, "over")

    def lane_state(self, lane, now):
        w = lane.wall
        wall = None
        if w is not None:
            frozen = w["frozen"]
            wall = {"kind": w["kind"], "say": w["say"], "made": round(w["made"], 3), "due": round(w["due"], 3),
                    "frozen": None if frozen is None else round(frozen, 3)}
        return {"slot": lane.slot, "score": lane.score, "status": lane.status, "lives": lane.lives,
                "streak": lane.streak, "wall": wall, "last": lane.last,
                "fits": bool(w and lane.ok_at.get(w["kind"], -1e9) > now - 0.2)}


# ------------------------------------------------------------------ Pose Match

POSES = [
    {"name": "Star", "a": {"lab": 150, "rab": 150, "lel": 175, "rel": 175, "lkn": 175, "rkn": 175, "feet": 0.7}},
    {"name": "Robot", "a": {"lab": 90, "rab": 90, "lel": 90, "rel": 90, "lkn": 175, "rkn": 175, "feet": 0.25}},
    {"name": "Goalpost", "a": {"lab": 90, "rab": 90, "lel": 95, "rel": 95, "lkn": 120, "rkn": 120, "feet": 0.55}},
    {"name": "T", "a": {"lab": 90, "rab": 90, "lel": 175, "rel": 175, "lkn": 175, "rkn": 175, "feet": 0.25}},
    {"name": "Skier", "a": {"lab": 20, "rab": 20, "lel": 160, "rel": 160, "lkn": 110, "rkn": 110, "feet": 0.3}},
    {"name": "Reach up", "a": {"lab": 170, "rab": 170, "lel": 175, "rel": 175, "lkn": 175, "rkn": 175, "feet": 0.2}},
    {"name": "Half star", "a": {"lab": 135, "rab": 20, "lel": 175, "rel": 175, "lkn": 175, "rkn": 175, "feet": 0.6}},
]
# Which joints each pose angle is read from (all must be seen for that angle to count).
ANGLE_JOINTS = {"lab": (L_HIP, L_SH, L_EL), "rab": (R_HIP, R_SH, R_EL), "lel": (L_SH, L_EL, L_WR),
                "rel": (R_SH, R_EL, R_WR), "lkn": (L_HIP, L_KNEE, L_ANK), "rkn": (R_HIP, R_KNEE, R_ANK),
                "feet": (L_ANK, R_ANK)}


def pose_angles(b):
    """The angles Pose Match compares, from joints that were seen (None where not)."""
    out = {}
    for key, ids in ANGLE_JOINTS.items():
        if any(b.states[i] == sk.MISSING for i in ids) or b.evidence(ids) < 0.75:
            out[key] = None
        elif key == "feet":
            out[key] = b.width(L_ANK, R_ANK)
        else:
            out[key] = sk.angle(b.p(ids[0]), b.p(ids[1]), b.p(ids[2]))
    return out


def similarity(a, target):
    """0..100 from the angles that were seen; 0 when fewer than five were."""
    total, n = 0.0, 0
    for k, want in target.items():
        v = a.get(k)
        if v is None:
            continue
        d = abs(v - want) * 100 if k == "feet" else abs(v - want)     # 1 cm ~ 1 deg
        total += min(d, 90.0)
        n += 1
    return 0.0 if n < 5 else max(0.0, 100.0 - 1.6 * total / n)


class PoseLane(Lane):
    def __init__(self, slot):
        super().__init__(slot)
        self.held = 0.0
        self.done = False
        self.sim = 0.0
        self.seen = 0
        self.last_t = None


class PoseMatch(Game):
    key, name = "pose", "Pose Match"
    ROUND = 9.0
    HOLD = 1.0
    MATCH = 78.0
    tutorial = [{"pose": "T", "say": "Copy the white figure."},
                {"pose": "T", "say": "Hold it still for a second: the ring fills."},
                {"pose": "T", "say": "The quicker you match, the more points."}]

    def __init__(self, slots, now, seed=None):
        super().__init__(slots, now, seed)
        self.k = self.rng.randrange(len(POSES))
        self.round = 1
        self.since = now
        self.paused_for = 0.0
        self.pause_from = None

    def new_lane(self, slot):
        return PoseLane(slot)

    def on_frame(self, lane, b, now):
        lane.sim = similarity(pose_angles(b), POSES[self.k]["a"])
        lane.seen = sum(v is not None for v in pose_angles(b).values())
        dt = 0.0 if lane.last_t is None else min(0.2, now - lane.last_t)
        lane.last_t = now
        if lane.done:
            return
        if lane.sim >= self.MATCH:
            lane.held += dt
            if lane.held >= self.HOLD:
                lane.done = True
                quick = max(0.0, 60.0 - 10.0 * self.elapsed(now))
                lane.score += round(lane.sim + quick)
                self.emit(lane.slot, "match", pose=POSES[self.k]["name"], score=lane.score)
        else:
            lane.held = 0.0

    def elapsed(self, now):
        paused = self.paused_for + ((now - self.pause_from) if self.pause_from is not None else 0.0)
        return now - self.since - paused

    def on_tick(self, now):
        playing = [l for l in self.lanes.values() if not l.done]
        for lane in self.lanes.values():
            if lane.status != "active":
                lane.held, lane.last_t = 0.0, None
        # Everyone still trying is out of sight: the round clock waits for them.
        stalled = bool(playing) and all(l.status != "active" for l in playing)
        if stalled and self.pause_from is None:
            self.pause_from = now
        elif not stalled and self.pause_from is not None:
            self.paused_for += now - self.pause_from
            self.pause_from = None
        if (self.lanes and all(l.done for l in self.lanes.values())) or self.elapsed(now) >= self.ROUND:
            self.k = (self.k + 1 + self.rng.randrange(len(POSES) - 1)) % len(POSES)
            self.round += 1
            self.since, self.paused_for, self.pause_from = now, 0.0, None
            for l in self.lanes.values():
                l.held, l.done = 0.0, False
            self.emit(None, "round", pose=POSES[self.k]["name"], round=self.round)

    def state(self, now):
        out = super().state(now)
        out.update(pose=POSES[self.k], round=self.round,
                   left=round(max(0.0, self.ROUND - self.elapsed(now)), 2),
                   paused=self.pause_from is not None)
        return out

    def lane_state(self, lane, now):
        return {"slot": lane.slot, "score": lane.score, "status": lane.status, "sim": round(lane.sim),
                "held": round(min(1.0, lane.held / self.HOLD), 2), "done": lane.done, "seen": lane.seen}


# ------------------------------------------------------------------ Body Racer

class Car(Lane):
    def __init__(self, slot):
        super().__init__(slot)
        self.x = 0.0
        self.speed = 0.0
        self.dist = 0.0
        self.coins = 0
        self.hits = 0
        self.bump = None
        self.steer = self.gas = self.brake = 0.0
        self.input_at = None
        self.items = []            # [{"d": metres along the road, "x": -1..1, "coin": bool}]
        self.next_item = 30.0


class BodyRacer(Game):
    key, name = "race", "Body Racer"
    LENGTH = 60.0
    DT = 1 / 30
    tutorial = [{"pose": "wheel", "say": "Hold an imaginary steering wheel in front of you."},
                {"pose": "wheel", "say": "Tilt it to steer. Push your hands out to go faster."},
                {"pose": "wheel", "say": "Pull your hands back to your chest to brake."}]

    def __init__(self, slots, now, seed=None, steer="wheel"):
        super().__init__(slots, now, seed)
        self.steer_by = steer
        self.last = now
        self.played = 0.0
        for lane in self.lanes.values():
            self._items(lane)

    def new_lane(self, slot):
        return Car(slot)

    def _items(self, car):
        while car.next_item < car.dist + 400:
            car.items.append({"d": car.next_item, "x": round(self.rng.uniform(-0.85, 0.85), 2),
                              "coin": self.rng.random() < 0.55})
            car.next_item += self.rng.uniform(18, 34)

    def on_frame(self, car, b, now):
        if self.steer_by == "lean":
            car.steer, car.gas, car.brake = bodygestures.lean_of(b), 0.8, 0.0
        else:
            w = bodygestures.steering(b) if _need(b, (L_WR, R_WR, L_SH, R_SH)) else None
            if w is None:
                car.steer = car.gas = 0.0
                car.brake = 0.0
            else:
                car.steer, car.gas, car.brake = w["wheel"], w["throttle"], w["brake"]
        car.input_at = now

    def on_tick(self, now):
        dt_total = max(0.0, min(0.5, now - self.last))
        self.last = now
        steps = int(round(dt_total / self.DT))
        anyone = any(c.status == "active" for c in self.lanes.values())
        for _ in range(steps):
            if not self.over and anyone:
                self.played += self.DT
            for car in self.lanes.values():
                self._drive(car, self.DT)
        if self.played >= self.LENGTH and not self.over:
            self.over = True
            self.emit(None, "over", results={str(s): {"dist": round(c.dist), "coins": c.coins, "hits": c.hits}
                                             for s, c in self.lanes.items()})

    def _drive(self, car, dt):
        live = car.status == "active" and car.input_at is not None and car.seen_at is not None \
            and self.last - car.input_at < 0.3
        gas = car.gas if live and not self.over else 0.0
        brake = car.brake if live else 0.0
        steer = car.steer if live else 0.0
        car.speed += (gas * 1.6 - brake * 2.2 - car.speed * 0.35) * dt
        car.speed = max(0.0, min(2.2, car.speed))
        car.x = max(-1.0, min(1.0, car.x + steer * 1.4 * dt * (0.4 + car.speed / 2.2)))
        before = car.dist
        car.dist += car.speed * dt * 60
        self._items(car)
        for it in car.items:
            if before < it["d"] <= car.dist and not it.get("done"):
                it["done"] = True
                if not live:                    # not seen: no penalty, no prize
                    continue
                if abs(it["x"] - car.x) < 0.18:
                    if it["coin"]:
                        car.coins += 1
                        self.emit(car.slot, "coin", coins=car.coins)
                    else:
                        car.hits += 1
                        car.speed *= 0.3
                        car.bump = self.last
                        self.emit(car.slot, "bump", hits=car.hits)
        car.items = [it for it in car.items if it["d"] > car.dist - 40]
        car.score = int(car.dist) + 25 * car.coins

    def state(self, now):
        out = super().state(now)
        out.update(left=round(max(0.0, self.LENGTH - self.played), 1), steer=self.steer_by)
        return out

    def lane_state(self, car, now):
        return {"slot": car.slot, "score": car.score, "status": car.status, "x": round(car.x, 3),
                "speed": round(car.speed, 3), "dist": round(car.dist, 1), "coins": car.coins,
                "hits": car.hits, "bump": car.bump, "input": {"steer": round(car.steer, 2),
                                                             "gas": round(car.gas, 2), "brake": car.brake},
                "items": [{"d": round(it["d"], 1), "x": it["x"], "coin": it["coin"]}
                          for it in car.items if not it.get("done") and it["d"] < car.dist + 160]}


GAMES = {g.key: g for g in (WallDodge, PoseMatch, BodyRacer)}


def make(key, slots, now, seed=None, **kw):
    return GAMES[key](slots, now, seed, **kw)
