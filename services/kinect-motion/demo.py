"""Two synthetic people for `server.py --demo`: the pages and checks without a Kinect.

They take turns through the moves in synthetic.MOVES, a few repetitions each, in the hub's
/api/people format (joints in the room frame, all tracked), at the hub's usual rate."""

import time

import numpy as np

import synthetic

PLAYLIST = ("squat", "jack", "curl", "press", "raise", "squat-lean", "shallow")
REPS = 5


class Demo:
    def __init__(self, people=2):
        self.t0 = time.time()
        self.people = people
        self.rng = np.random.default_rng(3)
        self.seq = 0

    def move_at(self, t, offset):
        """Which move, and how far into it, at time t."""
        t += offset
        k = 0
        while True:
            name = PLAYLIST[k % len(PLAYLIST)]
            length = synthetic.MOVES[name][2] * REPS
            if t < length:
                return name, t
            t -= length
            k += 1

    def next(self):
        now = time.time()
        t = now - self.t0
        self.seq += 1
        people = []
        for i in range(self.people):
            name, tt = self.move_at(t, offset=7.0 * i)
            x = -0.6 + 1.3 * i if self.people > 1 else 0.0
            J = synthetic.move(name, tt, x=x, z=2.8 + 0.3 * i, height=1.75 - 0.12 * i)
            J = J + self.rng.normal(0, 0.008, J.shape)
            people.append({"id": i + 1, "colour": i, "posture": "standing", "height_cm": 175 - 12 * i,
                           "distance": round(2.8 + 0.3 * i, 2), "skeleton": None, "demo_move": name,
                           "joints": [[round(float(a), 3) for a in j] + [2] for j in J]})
        return {"people": people, "count": len(people), "captured": now - 0.045, "seq": self.seq,
                "running": True, "source": "demo", "mode": "demo"}
