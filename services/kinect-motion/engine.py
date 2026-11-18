"""Kinect Motion's engine: one step per hub frame, for everyone in view.

Pure logic (no HTTP, no camera): server.py feeds it the hub's /api/people state and sends out
what it returns, and calls tick() many times a second whether frames come or not. The checks
drive it with synthetic frames.

    hub state -> fresh? (a repeated or late frame is not evidence)
      bodies -> Filter (smoothing, bone and speed checks) -> Gestures -> Roster (players, safety)
             -> Workout (free / plan / challenge / fitness check) or Game -> Room events -> Pad
    tick      the freshness watchdog: a player not seen for LOST seconds (or no fresh frame at
              all) is lost: their repetition in progress is dropped, a timed step waits while
              nobody is seen, their game lane freezes, the pad lets go, and the page shows a
              recovery cue. It runs between frames, so a camera that stops sending cannot leave
              anything counting or pressed.

Only `active` players (seen in this frame, identity sure) feed counting and games. The play
area comes from the camera's real geometry (calibration.py), not a fixed band.
"""

import time
from collections import deque

import bodygestures
import calibration
import exercises
import games as gameslib
import pad as padlib
import players as playerslib
import room as roomlib
import skeleton as sk
import training

COUNTDOWN = 3.0
SAY_GAP = 2.5          # s between spoken lines for one player
STALE = 0.5            # s: a hub state captured longer ago than this is not evidence
LOST = 0.35            # s without a fresh sighting before a player counts as lost
DEFAULT_SPACE = 2.0    # m of floor in front of the Kinect, unless motion.json says otherwise


class Workout:
    """What everyone is doing. Modes: idle, free (one exercise, open-ended), plan (a workout's
    steps with rests), challenge (most reps in a time), check (the fitness check, timed steps)."""

    def __init__(self, store=None):
        self.store = store
        self.mode, self.phase = "idle", "idle"
        self.plan = None
        self.index = 0
        self.exercise = None
        self.target = None
        self.seconds = None
        self.trackers = {}          # slot -> exercises.Tracker
        self.phase_at = 0.0
        self.paused_at = None
        self.sessions = {}          # slot -> store session id
        self.loads = {}             # slot -> [{"source", "kg"}]
        self.check_results = {}     # slot -> {exercise: scores}
        self.results = []           # the finished steps of this workout, for the summary
        self.users = {}             # slot -> user id (profile)
        self.held_by = None         # "you" (pressed pause) or "tracking" (nobody seen)
        self.on_start = self.on_finish = None    # the engine's tracking-quality recorder

    # -- control

    def start(self, mode, now, exercise=None, plan=None, seconds=None, target=None):
        self.finish(now)
        if self.on_start:
            self.on_start(now)
        self.mode = mode
        self.results, self.check_results = [], {}
        if mode == "free" or mode == "challenge":
            self.plan = {"name": exercises.CATALOG[exercise].name, "rest": 0,
                         "steps": [{"exercise": exercise, "target": target, "seconds": seconds, "label": None}]}
        else:
            self.plan = training.plan("check" if mode == "check" else plan)
        self.index = 0
        self._begin_step(now)

    def _begin_step(self, now):
        step = self.plan["steps"][self.index]
        self.exercise = step["exercise"]
        ex = exercises.CATALOG[self.exercise]
        self.seconds = step.get("seconds")
        self.target = step.get("target") or (None if self.seconds else ex.target)
        self.trackers = {}
        self.phase, self.phase_at = "ready", now

    def pause(self, now, by="you"):
        if self.phase in ("ready", "go", "rest") and self.paused_at is None:
            self.paused_at, self.held_by = now, by
            return True
        if self.paused_at is not None and by == "you":
            self.held_by = "you"              # a pause you asked for outlasts tracking coming back
        return False

    def resume(self, now, by="you"):
        if self.paused_at is not None and (by == "you" or self.held_by == by):
            self.phase_at += now - self.paused_at
            self.paused_at, self.held_by = None, None
            return True
        return False

    def next(self, now):
        """Skip to the next step (or end)."""
        if self.mode == "idle":
            return []
        out = self._close_step(now)
        if self.index + 1 < len(self.plan["steps"]):
            self.index += 1
            self._begin_step(now)
        else:
            out += self.finish(now)
        return out

    def finish(self, now):
        out = []
        if self.mode != "idle" and self.phase in ("go", "ready"):
            out += self._close_step(now)
        for slot, sid in self.sessions.items():
            if self.store and sid:
                self.store.end_session(sid)
        if self.mode == "check" and self.store:
            for slot, res in self.check_results.items():
                uid = self.users.get(slot)
                if uid:
                    before = self.store.checks(uid)
                    self.store.add_check(uid, res)
                    if before:
                        out.append({"type": "check-compare", "slot": slot,
                                    "compare": training.compare(res, before[0]["results"])})
        if self.mode != "idle":
            done = {"type": "workout-done", "results": self.results}
            if self.on_finish:
                done["quality"] = self.on_finish(now, dict(self.sessions), dict(self.users), None)
            out.append(done)
        self.sessions = {}
        self.mode, self.phase, self.plan, self.trackers = "idle", "idle", None, {}
        self.paused_at, self.held_by = None, None
        return out

    # -- per frame

    def step(self, roster, bodies_by_track, now):
        if self.mode == "idle" or self.paused_at is not None:
            return []
        out = []
        elapsed = now - self.phase_at
        if self.phase == "ready":
            if elapsed >= COUNTDOWN:
                self.phase, self.phase_at = "go", now
                out.append({"type": "go", "exercise": self.exercise})
            return out
        if self.phase == "rest":
            if elapsed >= self.plan["rest"]:
                self.index += 1
                self._begin_step(now)
                out.append({"type": "next", "exercise": self.exercise})
            return out
        # Go: every present player has their own tracker.
        for p in roster.players:
            b = bodies_by_track.get(p.track)
            if b is None:
                continue
            tr = self.trackers.get(p.slot)
            if tr is None:
                tr = self.trackers[p.slot] = exercises.Tracker(self.exercise, self.target)
            if p.warning:                      # not safe right now: nothing counts
                continue
            for e in tr.step(b):
                out.append({**e, "slot": p.slot})
        timed_out = self.seconds is not None and elapsed >= self.seconds
        everyone = self.trackers and all(t.state()["done"] for t in self.trackers.values())
        if timed_out or (self.seconds is None and everyone and self.mode != "free"):
            out += self._close_step(now)
            if self.index + 1 < len(self.plan["steps"]):
                self.phase, self.phase_at = "rest", now
                out.append({"type": "rest", "seconds": self.plan["rest"]})
            else:
                out += self.finish(now)
        return out

    def _close_step(self, now):
        """Record this step for every player who took part."""
        out = []
        step = self.plan["steps"][self.index] if self.plan else None
        ex = exercises.CATALOG[self.exercise] if self.exercise else None
        for slot, tr in self.trackers.items():
            s = tr.summary()
            if not s["reps"] and not s.get("held"):
                continue
            seconds = (s.get("held") if ex.kind == "hold" else
                       sum(r["time_s"] for r in tr.history)) or 0.0
            uid = self.users.get(slot)
            user = self.store.user(uid) if (self.store and uid) else None
            kg_load, source = training.resolve_load(self.loads.get(slot))
            hands = 2 if ex.key in ("curl", "press", "raise", "squat", "lunge") else 1
            rec = {"slot": slot, "exercise": ex.key, "name": ex.name, "reps": s["reps"], "good": s["good"],
                   "form": s.get("form"), "held": s.get("held"), "load_kg": kg_load, "load_source": source,
                   "volume": training.volume(s["reps"], kg_load, hands) if ex.kind != "hold" else None,
                   "kcal": training.kcal(ex.met[0], user and user.get("kg"), seconds),
                   "seconds": round(seconds, 1)}
            if rec["kcal"] is not None:
                rec["kcal"] = round(rec["kcal"], 1)
            if self.mode == "check" and step:
                self.check_results.setdefault(slot, {})[ex.key] = training.check_score(step, s)
                rec["check"] = self.check_results[slot][ex.key]
            if self.store and uid:
                sid = self.sessions.get(slot)
                if not sid:
                    sid = self.sessions[slot] = self.store.start_session(uid, self.mode)
                prev = self.store.last_sets(uid, ex.key)
                self.store.add_set(sid, s, kg_load, source, rec["volume"], rec["kcal"], seconds)
                if ex.kind != "hold":
                    rec["next"] = training.progression(prev + [{"reps": s["reps"], "form": s.get("form")}],
                                                       self.target or ex.target, kg_load)
            self.results.append(rec)
            out.append({"type": "set", **rec})
        self.trackers = {}
        return out

    def state(self, roster, bodies_by_track, now):
        if self.mode == "idle":
            return {"mode": "idle"}
        elapsed = (self.paused_at or now) - self.phase_at
        left = None
        if self.phase == "ready":
            left = COUNTDOWN - elapsed
        elif self.phase == "rest":
            left = self.plan["rest"] - elapsed
        elif self.seconds is not None:
            left = self.seconds - elapsed
        per = {}
        for p in roster.players:
            tr = self.trackers.get(p.slot)
            if tr is not None:
                per[p.slot] = tr.state(bodies_by_track.get(p.track))
        steps = [{"exercise": s["exercise"], "name": exercises.CATALOG[s["exercise"]].name,
                  "target": s.get("target"), "seconds": s.get("seconds"), "label": s.get("label")}
                 for s in self.plan["steps"]]
        ex = exercises.CATALOG[self.exercise]
        return {"mode": self.mode, "phase": self.phase, "paused": self.paused_at is not None,
                "held_by": self.held_by,
                "plan": self.plan["name"], "index": self.index, "steps": steps,
                "exercise": self.exercise, "name": ex.name, "how": ex.how, "kind": ex.kind,
                "target": self.target, "seconds": self.seconds,
                "left": None if left is None else round(max(0.0, left), 1), "players": per}


class Engine:
    def __init__(self, store=None, cfg=None):
        cfg = cfg or {}
        self.filter = sk.Filter()
        self.roster = playerslib.Roster(auto_solo=cfg.get("auto_solo", True))
        self.gestures = {}
        self.workout = Workout(store)
        self.room = roomlib.Room(cfg)
        self.store = store
        self.pad_profile = None      # wheel / lean / keys while the pad is on
        self.pad_slot = 0
        self.latency = deque(maxlen=300)
        self.said = {}
        self.events = deque(maxlen=200)
        self.bodies = {}
        self.wheel = {}
        self.last_gestures = {}
        self.cfg = cfg
        self.game = None
        self.last_frame = None       # the hub's frame number last used
        self.last_capture = 0.0      # when the last fresh frame was taken (wall clock)
        self.fresh = False
        self.dropped = {"repeated": 0, "late": 0}
        self.lost = {}               # slot -> True while that player is lost
        self.hub = {}
        self.space = None
        self.space_key = None
        self.space_state = None
        self.quality = {}            # slot -> how well the Kinect saw them in this activity
        self.q_last = None
        self.workout.on_start = self._quality_start
        self.workout.on_finish = self._quality_finish

    # -- tracking quality, per player and activity (kept with the results, never the frames)

    def _quality_start(self, now):
        self.quality, self.q_last = {}, now

    def _quality_note(self, now):
        """In tick(): time seen and lost per player while something is under way."""
        if not self.live():
            self.q_last = now
            return
        dt = 0.0 if self.q_last is None else max(0.0, min(0.5, now - self.q_last))
        self.q_last = now
        for p in self.roster.players:
            q = self.quality.setdefault(p.slot, {"seconds": 0.0, "seen": 0.0, "losses": 0, "lost_seconds": 0.0,
                                                 "frames": 0, "evidence": 0.0, "dark": 0})
            q["seconds"] += dt
            if self.lost.get(p.slot):
                q["lost_seconds"] += dt
            else:
                q["seen"] += dt

    def _quality_frame(self, active, hub):
        if not self.live():
            return
        key = self.activity()
        joints = exercises.CATALOG[key].joints if key in exercises.CATALOG else \
            (sk.L_SH, sk.R_SH, sk.L_HIP, sk.R_HIP, sk.L_WR, sk.R_WR, sk.L_KNEE, sk.R_KNEE)
        for p in self.roster.players:
            b = active.get(p.track)
            q = self.quality.get(p.slot)
            if b is None or q is None:
                continue
            q["frames"] += 1
            q["evidence"] += b.evidence(joints)
            q["dark"] += hub.get("mode") == "ir"

    def _quality_summary(self, slot, activity):
        q = self.quality.get(slot)
        if not q or q["seconds"] < 1.0:
            return None
        return {"activity": activity, "seconds": round(q["seconds"], 1),
                "seen_share": round(q["seen"] / q["seconds"], 3), "losses": q["losses"],
                "lost_seconds": round(q["lost_seconds"], 1),
                "updates_per_s": round(q["frames"] / q["seen"], 1) if q["seen"] > 0.5 else None,
                "evidence": round(q["evidence"] / q["frames"], 2) if q["frames"] else None,
                "dark_share": round(q["dark"] / q["frames"], 2) if q["frames"] else None}

    def _quality_finish(self, now, sessions, users, game_ids):
        activity = self.workout.exercise if game_ids is None else self.game.key
        self.last_quality = {}
        for slot in list(self.quality):
            summary = self._quality_summary(slot, activity if game_ids is None else self.game.key)
            if summary is None:
                continue
            self.last_quality[slot] = summary
            uid = users.get(slot)
            if self.store and uid and (sessions.get(slot) or (game_ids or {}).get(slot)):
                self.store.add_quality(uid, summary, session_id=sessions.get(slot),
                                       game_id=(game_ids or {}).get(slot))
        self.quality = {}
        return self.last_quality

    # -- the play area, from the camera

    def _calibrate(self, hub):
        cam = calibration.Camera.from_hub(hub)
        if cam is None:
            return
        room = (hub.get("room") or {}).get("far")
        # The owner's floor space (motion.json "space_m"; null = only the room's own end).
        limit = self.cfg.get("space_m", DEFAULT_SPACE)
        key = (cam.key(), room and round(room, 1), limit)
        if key != self.space_key:
            self.space = calibration.Space(cam, round(room, 1) if room else None, limit)
            self.space_key, self.space_state = key, None
            self.roster.space = self.space

    def activity(self):
        """What everyone is doing now: an exercise or a game key (calibration.ENVELOPES)."""
        if self.game is not None and not self.game.over:
            return self.game.key
        if self.workout.mode != "idle" and self.workout.exercise:
            return self.workout.exercise
        return None

    def live(self):
        """A workout or game is under way (the hub then keeps infrared without colour checks)."""
        return (self.workout.mode != "idle" and self.workout.phase in ("ready", "go", "rest")) or \
            (self.game is not None and not self.game.over) or getattr(self, "live_override", False)

    # -- one hub state

    def _usable(self, hub, now):
        """Is this hub state new evidence? Repeated frames and late ones are not."""
        frame = hub.get("frame", hub.get("seq"))
        captured = hub.get("captured")
        if frame is not None and self.last_frame is not None:
            if frame == self.last_frame or 0 < self.last_frame - frame < 100000:
                self.dropped["repeated"] += 1
                return False
        if captured is not None and now - captured > STALE:
            self.dropped["late"] += 1
            return False
        if frame is not None:
            self.last_frame = frame
        return True

    def step(self, hub, now=None):
        """One hub state -> (events, say lines). Call state() for the screen."""
        now = time.time() if now is None else now
        self.hub = hub
        self._calibrate(hub)
        if not self._usable(hub, now):
            return [], []
        t = hub.get("captured") or now
        if hub.get("captured"):
            self.latency.append(max(0.0, now - hub["captured"]))
            self.last_capture = hub["captured"]
        else:
            self.last_capture = now
        bodies = []
        for person in hub.get("people") or []:
            if not person.get("joints"):
                continue
            bodies.append(self.filter(sk.Body.from_hub(person, t)))
        self.bodies = {b.id: b for b in bodies}
        for gone in set(self.gestures) - set(self.bodies):
            self.gestures.pop(gone)
        known = set(self.bodies) | {h["id"] for h in hub.get("hidden") or []}
        for gone in set(self.filter.filters) - known:
            self.filter.forget(gone)
        busy = self.workout.phase == "go" or (self.game is not None and not self.game.over)
        g_by = {b.id: self.gestures.setdefault(b.id, bodygestures.Gestures()).step(b, busy) for b in bodies}
        self.last_gestures = g_by
        self.roster.activity = self.activity()
        # Roster events keep their own type: joined / rejoined / left / status / safety.
        events = list(self.roster.update(bodies, now, hub))
        events += self.tick(now)                  # who is lost or back, before anything counts
        events += self._controls(g_by, now)
        active = self.active_bodies()
        events += self.workout.step(self.roster, active, now)
        self._quality_frame(active, hub)
        if self.game is not None:
            for p in self.roster.players:
                b = active.get(p.track)
                if b is not None and not p.warning:
                    self.game.frame(p.slot, b, now)
        events += [{"type": "room", **e} for e in self.room.step(bodies, g_by, now)]
        for b in bodies:
            self.wheel[b.id] = bodygestures.steering(b)
        for e in events:
            self.events.append({"t": round(now, 2), **e})
        return events, self._sayings(events, now)

    def active_bodies(self):
        """The bodies that may be counted and scored: active players' only, from a fresh frame."""
        return {p.track: self.bodies[p.track] for p in self.roster.players
                if p.status == "active" and p.track in self.bodies and not self.lost.get(p.slot)}

    # -- between frames: the watchdog

    def tick(self, now=None):
        """Freshness and game time. Call often (the server: 30 times a second)."""
        now = time.time() if now is None else now
        self.fresh = now - self.last_capture < STALE
        events = []
        for p in self.roster.players:
            lost = not self.fresh or p.status != "active" or now - p.seen > LOST
            was = self.lost.get(p.slot)
            self.lost[p.slot] = lost
            if lost != bool(was) and (was is not None or lost):
                if lost and p.slot in self.quality:
                    self.quality[p.slot]["losses"] += 1
                tr = self.workout.trackers.get(p.slot)
                if lost and tr is not None:
                    tr.interrupt()
                events.append({"type": "tracking", "slot": p.slot, "lost": lost,
                               "status": p.status if self.fresh else "stale",
                               "say": "I've lost you. Step back into view." if lost and
                               self.workout.phase == "go" else None})
        for slot in [s for s in self.lost if self.roster.by_slot(s) is None]:
            self.lost.pop(slot)
        # A timed step or countdown waits while no player is seen.
        w = self.workout
        if w.mode != "idle" and w.phase in ("ready", "go") and self.roster.players:
            if all(self.lost.get(p.slot) for p in self.roster.players):
                # From the last sighting: the unseen moments before "lost" do not run the clock.
                last = max(p.seen for p in self.roster.players)
                if w.pause(min(now, max(last, w.phase_at)), by="tracking"):
                    events.append({"type": "paused", "by": "tracking"})
            elif w.held_by == "tracking" and w.resume(now, by="tracking"):
                events.append({"type": "resumed", "by": "tracking"})
        if self.game is not None:
            status = {p.slot: ("active" if not self.lost.get(p.slot) and not p.warning else
                               ("warning" if p.warning else p.status)) for p in self.roster.players}
            was_over = self.game.over
            events += self.game.tick(now, status)
            if self.game.over and not was_over:
                events += self._game_over(now)
        self._quality_note(now)
        return events

    def _game_over(self, now):
        """Save each named player's score (and how well they were seen); -> a summary event."""
        g = self.game
        results, ids, users = {}, {}, {}
        for slot, lane in g.lanes.items():
            p = self.roster.by_slot(slot)
            results[slot] = {"score": lane.score}
            if p is not None and p.profile and self.store:
                users[slot] = p.profile
                ids[slot] = self.store.add_game(p.profile, g.key, lane.score, g.lane_state(lane, now))
        self.live_override = True
        self._quality_finish(now, {}, users, ids)
        self.live_override = False
        return [{"type": "game-over", "game": g.key, "results": results,
                 "quality": getattr(self, "last_quality", {})}]

    # -- games

    def start_game(self, key, now, seed=None, **kw):
        self.join_everyone(now)
        self._quality_start(now)
        self.game = gameslib.make(key, [p.slot for p in self.roster.players], now, seed, **kw)
        return self.game

    def stop_game(self, now=None):
        """Stop the game; a game stopped part way still saves its scores."""
        out = []
        if self.game is not None and not self.game.over:
            self.game.over = True
            out = self._game_over(time.time() if now is None else now)
        self.game = None
        return out

    def join_everyone(self, now):
        """No players yet: everyone in view joins (nearest the middle first, up to four). Only
        people the hub is sure of; their slots then stay theirs, wherever they move."""
        if self.roster.players:
            return []
        out = []
        sure = [b for b in self.bodies.values() if b.identity == "sure"]
        for b in sorted(sure, key=lambda b: abs(b.centre()[0]) if b.centre() is not None else 9):
            p = self.roster.join(b, now)
            if p:
                out.append({"type": "joined", "slot": p.slot})
        if self.game is not None:
            for p in self.roster.players:
                self.game.add(p.slot)
        return out

    def _controls(self, g_by, now):
        """Whole-body controls: join, pause / resume, next, recalibrate."""
        out = []
        for track, gs in g_by.items():
            p = self.roster.by_track(track)
            for g in gs:
                name = g["gesture"]
                if p is None and name in ("raise_left", "raise_right"):
                    b = self.bodies[track]
                    if b.identity != "sure":
                        continue
                    waiting = any(q.status == "rejoin" for q in self.roster.players)
                    joined = self.roster.join(b, now)
                    if joined:
                        out.append({"type": "rejoined" if waiting else "joined", "slot": joined.slot})
                        if self.game is not None:
                            self.game.add(joined.slot)
                elif p is not None and name == "hands_up":
                    if self.workout.pause(now):
                        out.append({"type": "paused", "slot": p.slot})
                    elif self.workout.resume(now):
                        out.append({"type": "resumed", "slot": p.slot})
                elif p is not None and name == "swipe_left" and self.workout.phase != "go":
                    out += self.workout.next(now)
                elif p is not None and name == "t_pose":
                    self.filter.forget(track)
                    out.append({"type": "calibrated", "slot": p.slot})
        return out

    def _sayings(self, events, now):
        """What to say aloud: one line per player at most every SAY_GAP seconds."""
        lines = []
        for e in events:
            text = None
            if e["type"] in ("cue", "partial", "unsure") or (e["type"] == "rep" and e.get("say")):
                text = e.get("say")
            elif e["type"] == "go":
                text = f"Go! {exercises.CATALOG[e['exercise']].name}."
            elif e["type"] == "rest":
                text = f"Rest for {e['seconds']} seconds."
            elif e["type"] == "next":
                text = f"Next: {exercises.CATALOG[e['exercise']].name}."
            elif e["type"] == "joined":
                text = f"Player {e['slot'] + 1}, you're in."
            elif e["type"] == "rejoined" and e.get("from") is None:
                text = f"Player {e['slot'] + 1}, you're back."
            elif e["type"] == "status" and e["status"] == "rejoin":
                text = f"Player {e['slot'] + 1}, raise a hand so I know which one you are."
            elif e["type"] == "tracking" and e.get("say"):
                text = e["say"]
            elif e["type"] == "safety" and e.get("warning"):
                text = e["warning"]
            elif e["type"] == "workout-done":
                text = "Workout done. Well done!"
            elif e["type"] == "room" and e.get("say"):
                text = e["say"]
            if not text:
                continue
            who = e.get("slot", -1)
            if now - self.said.get(who, 0) >= SAY_GAP or e["type"] in ("go", "workout-done", "rest"):
                self.said[who] = now
                lines.append(text)
        return lines

    def pad_outputs(self):
        """What the virtual pad should send now (for the pad player): everything released unless
        that player is active and fresh."""
        p = next((p for p in self.roster.players if p.slot == self.pad_slot), None)
        if (self.pad_profile is None or p is None or p.track not in self.bodies
                or p.status != "active" or self.lost.get(p.slot, True)):
            return padlib.outputs(self.pad_profile or "wheel", None, 0.0, [], False)
        g = self.gestures.get(p.track)
        return padlib.outputs(self.pad_profile, self.wheel.get(p.track), g.lean if g else 0.0,
                              self.last_gestures.get(p.track, []), True)

    def latency_ms(self):
        if not self.latency:
            return None
        s = sorted(self.latency)
        pick = lambda q: round(1000 * s[min(len(s) - 1, int(q * len(s)))])   # noqa: E731
        return {"p50": pick(0.5), "p95": pick(0.95), "max": round(1000 * s[-1]), "n": len(s)}

    def state(self, hub, now=None):
        now = time.time() if now is None else now
        people = []
        fresh = now - self.last_capture < STALE
        for person in (hub.get("people") or []) if fresh else []:
            b = self.bodies.get(person["id"])
            pl = self.roster.by_track(person["id"])
            g = self.gestures.get(person["id"])
            people.append({
                "id": person["id"], "colour": person.get("colour", 0), "posture": person.get("posture"),
                "height_cm": person.get("height_cm"), "distance": person.get("distance"),
                "skeleton": person.get("skeleton"), "slot": pl.slot if pl else None,
                "joints": None if b is None else [None if b.states[i] == 0 else
                                                  [round(float(v), 3) for v in b.joints[i]] + [int(b.states[i])]
                                                  for i in range(33)],
                "lean": round(g.lean, 2) if g else None,
                "wheel": self.wheel.get(person["id"]),
                "pointing": g.pointing if g else None,
            })
        if self.space is not None and self.space_state is None:
            self.space_state = self.space.to_dict()
            self.space_state["tilt_hint"] = calibration.suggest_tilt(self.space)
        players = self.roster.state(now)
        for p in players:
            p["lost"] = bool(self.lost.get(p["slot"]))
        return {"people": people, "players": players, "t": round(now, 3), "fresh": fresh,
                "workout": self.workout.state(self.roster, self.bodies, now),
                "game": None if self.game is None else self.game.state(now),
                "latency": self.latency_ms(), "pad": self.pad_profile,
                "tracking": {"visible": len(people), "hidden": len(hub.get("hidden") or []) if fresh else 0,
                             "active": sum(1 for p in players if p["status"] == "active" and not p["lost"]),
                             "dropped": dict(self.dropped), "frame": self.last_frame},
                "space": self.space_state,
                "hub": {k: hub.get(k) for k in ("running", "source", "mode", "size", "error", "floor", "count",
                                                "room", "epoch", "timing")}}
