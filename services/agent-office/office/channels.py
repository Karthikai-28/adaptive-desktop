"""Messaging channels that the office pushes notifications to, besides its own page and Adaptive Link.

Adaptive Link is the active mobile channel and needs nothing here: it pulls the numbered notifications
itself (services/adaptive-link/office_gateway.py). A channel in this module is one the office has to push to,
such as WhatsApp in the future. Every channel is:

- outbound only: it tells, it never asks. Nothing a channel receives can acknowledge, approve or start
  work; approvals stay behind the operator key (server.py, /api/inbox/{id}/approve);
- concise: a title and a short line (`concise`), no task bodies, reports or file paths;
- off unless config.json says otherwise (`"notifications": {"<name>": {"enabled": true, ...}}`).

The Dispatcher keeps each channel's position in the `deliveries` table (as "push:<name>"), so whatever a
channel could not take stays undelivered and is sent again, in order, after a backoff.
"""
import asyncio
import time

from .journal import log

RANK = {"normal": 0, "high": 1, "critical": 2}
BACKOFF_S = (30, 60, 120, 300, 900)


def concise(note, limit=280):
    """The words a messaging channel may carry: the title and the start of the text, nothing else."""
    text = " ".join(str(note.get("text") or "").split())
    line = f"{note.get('title') or 'Agent Office'}: {text}" if text else str(note.get("title") or "Agent Office")
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"


class Channel:
    name = ""

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    @property
    def enabled(self):
        return bool(self.cfg.get("enabled"))

    def accepts(self, note):
        return RANK.get(note.get("priority"), 0) >= RANK.get(self.cfg.get("min_priority", "high"), 1)

    async def send(self, note):
        raise NotImplementedError


class WhatsApp(Channel):
    """Planned: concise alerts and, later, read-only status questions. Disabled by default, and there is no
    sender yet, so enabling it only records failed deliveries; it can never authorise anything."""
    name = "whatsapp"

    async def send(self, note):
        raise RuntimeError("the WhatsApp channel has no sender yet")


KINDS = {WhatsApp.name: WhatsApp}


def from_config(cfg):
    out = []
    for name, c in (cfg.get("notifications") or {}).items():
        if name in KINDS:
            out.append(KINDS[name](c))
    return out


class Dispatcher:
    def __init__(self, journal, channels):
        self.journal = journal
        self.channels = [c for c in channels if c.enabled]
        self.retry_at = {}              # channel name -> monotonic time of its next attempt
        self.failures = {}

    def key(self, ch):
        return f"push:{ch.name}"

    async def once(self):
        """Send each enabled channel what it has not confirmed yet, oldest first; stop a channel at its first
        failure so nothing is skipped."""
        for ch in self.channels:
            if time.monotonic() < self.retry_at.get(ch.name, 0):
                continue
            through = self.journal.delivery(self.key(ch))["through"]
            for note in self.journal.notifications(after=through, limit=50):
                try:
                    if ch.accepts(note):
                        await ch.send({**note, "message": concise(note)})
                except Exception as e:
                    n = self.failures[ch.name] = self.failures.get(ch.name, 0) + 1
                    self.retry_at[ch.name] = time.monotonic() + BACKOFF_S[min(n, len(BACKOFF_S)) - 1]
                    self.journal.delivery_failed(self.key(ch), e)
                    log("warning", "channel delivery failed", channel=ch.name, notification=note["id"], error=str(e))
                    break
                self.failures[ch.name] = 0
                self.journal.delivered(self.key(ch), note["id"])

    async def run(self):
        while self.channels:
            try:
                await self.once()
            except Exception as e:
                log("error", "dispatcher", error=str(e))
            await self.journal.wait(self.journal.notification_head(), 30)
