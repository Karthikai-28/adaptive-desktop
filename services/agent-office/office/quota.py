"""Gemini quota: pause when it runs out, resume by itself the moment it is back.

When an agent hits the Gemini limit, the office asks agy for the real reset times (`agy -p /usage`)
and pauses agent work until the exhausted window resets. A watchdog then:
  - resumes as soon as the pause ends, or earlier if /usage shows quota again,
  - re-sends direct messages that could not be answered while the quota was out,
  - and restarts any queued work that is waiting with free slots (so nothing stays stuck).
Study programs, tasks, chats and meetings all go through the same pause.
"""
import asyncio
import datetime as dt
import re
import time

from . import agy
from .config import COMPANY

FALLBACK_S = 5 * 60         # pause when /usage shows no exhausted window (a short rate limit)
PROBE_S = 5 * 60            # while paused, how often to look whether the quota came back early
TICK_S = 30
_RESETS_IN = re.compile(r"resets? in\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?!s))?\s*(?:(\d+)\s*s)?", re.I)


def reset_from_error(err, now=None):
    """The reset time Gemini states in its quota error ("... Resets in 2h44m48s."), or None."""
    m = _RESETS_IN.search(err or "")
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return (time.time() if now is None else now) + d * 86400 + h * 3600 + mi * 60 + s


def _pct(row):
    try:
        return int(str(row.get("remaining", "")).rstrip("%"))
    except ValueError:
        return None


def _ts(iso):
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


class QuotaGuard:
    def __init__(self, office):
        self.o = office
        self.usage = {"ts": 0, "rows": [], "error": ""}
        self.deferred_chats = {}          # agent id -> [(message, sender)] that hit the limit
        self._last_probe = 0
        self._announced = 0
        self._refreshing = None

    def start(self):
        self.o._spawn(self._loop())

    # ------------------------------------------------------------------ /usage
    async def refresh(self):
        if self._refreshing:                       # one /usage call at a time
            return await self._refreshing
        self._refreshing = asyncio.get_running_loop().create_future()
        try:
            proc = await asyncio.create_subprocess_exec(
                "agy", "-p", "/usage", cwd=str(COMPANY), env=agy._env("usage"),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            rows = []
            for line in out.decode(errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].startswith("Gemini"):
                    rows.append({"window": "week" if "Weekly" in parts[1] else "5h",
                                 "remaining": parts[2].strip(), "resets": parts[3].strip() if len(parts) > 3 else ""})
            self.usage = {"ts": time.time(), "rows": rows, "error": "" if rows else "no usage data"}
        except Exception as e:  # usage is advisory; never let it break the office
            self.usage = {"ts": time.time(), "rows": self.usage.get("rows", []), "error": str(e)[:200]}
        await self.o.broadcast({"type": "usage", **self.usage})
        fut, self._refreshing = self._refreshing, None
        fut.set_result(self.usage)
        return self.usage

    def exhausted_until(self):
        """The time the latest exhausted Gemini window resets, or None if none is at 0%."""
        resets = [_ts(r["resets"]) for r in self.usage.get("rows", []) if _pct(r) == 0]
        resets = [x for x in resets if x]
        return max(resets) if resets else None

    # ------------------------------------------------------------------ hitting the limit
    async def hit(self, agent=None, error=""):
        """An agent ran into the limit: pause until the quota really comes back.

        The reset time comes from /usage when it shows an exhausted window (an exact timestamp), else from
        Gemini's error ("... Resets in 2h44m48s"), else a short pause. With a known reset time the office
        just waits for it: no early probing, because every retry re-sends the agent's whole conversation."""
        now = time.time()
        if self.o.quota_until > now and self.o.store.get("quota_known", False):
            return                                                         # already waiting for a known reset
        self.o.quota_until = max(self.o.quota_until, now + FALLBACK_S)    # stop new work right away
        self.o.store.set("quota_until", self.o.quota_until)
        await self.refresh()
        until, stated = self.exhausted_until(), reset_from_error(error, now)
        if until and until > now:
            target, known = until + 60, True
        elif stated:
            target, known = stated + 60, True
        else:
            target, known = now + FALLBACK_S, False
        self.o.quota_until = max(target, self.o.quota_until if known else 0)
        self.o.store.set("quota_until", self.o.quota_until)
        self.o.store.set("quota_known", known)
        if abs(self.o.quota_until - self._announced) < 120:
            return                                                         # this pause was announced already
        self._announced = self.o.quota_until
        self._last_probe = time.time()
        when = dt.datetime.fromtimestamp(self.o.quota_until).strftime("%H:%M" if self.o.quota_until - now < 20 * 3600 else "%a %H:%M")
        await self.o.broadcast({"type": "settings", "settings": self.o.settings(), "quota_until": self.o.quota_until})
        await self.o.toast(f"Gemini quota used up. The team pauses and resumes by itself at {when}.", "warn")
        for aid in self.o.agents:
            await self.o.push_agent(aid)

    def defer_chat(self, aid, batch):
        self.deferred_chats.setdefault(aid, []).extend(batch)

    # ------------------------------------------------------------------ resuming
    async def resume(self, early=False):
        self.o.quota_until = 0
        self.o.store.set("quota_until", 0)
        self.o.store.set("quota_known", False)
        await self.o.broadcast({"type": "settings", "settings": self.o.settings(), "quota_until": 0})
        await self.o.toast("Gemini quota is back" + (" early" if early else "") + " - the team is working again.", "ok")
        for aid, batch in list(self.deferred_chats.items()):
            for item in batch:
                await self.o.chat_q[aid].put(item)
        self.deferred_chats.clear()
        for aid in self.o.agents:
            await self.o.push_agent(aid)
        self.o.kick()

    async def _loop(self):
        await asyncio.sleep(10)
        last_usage = 0
        while True:
            try:
                now = time.time()
                if self.o.quota_until and now >= self.o.quota_until:
                    await self.resume()
                elif self.o.quota_until > now:
                    if now - self._last_probe >= PROBE_S:
                        self._last_probe = now
                        await self.refresh()                       # keeps the usage shown everywhere current
                        rows = self.usage.get("rows", [])
                        # with a known reset time, wait for it; otherwise resume as soon as quota is back
                        if not self.o.store.get("quota_known", False) and rows and all((_pct(r) or 0) > 0 for r in rows):
                            await self.resume(early=True)
                else:
                    if now - last_usage >= 180:                    # keep the top bar fresh
                        last_usage = now
                        self.o._spawn(self.refresh())
                    # anything queued with free slots and nothing running for it? start it
                    s = self.o.settings()
                    if not s["paused"] and len(self.o.task_runs) < s["max_parallel"] and \
                            self.o.store.tasks(status="queued", limit=1):
                        self.o.kick()
            except Exception as e:  # the watchdog must never die
                print(f"quota watchdog: {e}", flush=True)
            await asyncio.sleep(TICK_S)
