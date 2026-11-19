"""The Agent Office (services/agent-office), from a paired phone.

The office listens on 127.0.0.1 only and turns away other hosts and origins, so a phone cannot
reach it directly, and nothing new is opened for it. Instead the link carries it, inside the same
mutual TLS as everything else, at home or away:

  /v1/office/api/<path>   the office's /api/<path> (GET and POST, bodies and query passed through)
  /v1/office/ws           its live updates, relayed both ways

Directing the office means directing agents that run commands, so it takes the commands switch
(allow_exec): a device held back from commands is held back from the office too.

The office's alerts (a failed or blocked task, an approval waiting, a quota stop: services/agent-office
office/journal.py) reach the phone without it watching the Office page: `follow` long-polls the office's
numbered notifications and hands each new one to /v1/events as kind "office". They are not remembered
here; the office keeps every one, and a phone that was away fetches what it missed from
/v1/office/api/notifications?after=<the last it showed>, in order, and confirms them.
"""
import asyncio
import json
import os
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web

FOLLOW_WAIT_S = 25          # the office holds a notification request open this long when there is nothing new
FOLLOW_RETRY_S = 30         # the office is not running: look again after this

CONFIG = Path(__file__).resolve().parent.parent / "agent-office" / "config.json"
SWITCH = "allow_exec"


def office_port():
    if os.environ.get("OFFICE_PORT", "").isdigit():
        return int(os.environ["OFFICE_PORT"])
    try:
        return int(json.loads(CONFIG.read_text()).get("port", 8790))
    except (OSError, ValueError, TypeError):
        return 8790


def _error(status, message):
    return web.json_response({"ok": False, "error": message}, status=status)


class OfficeGateway:
    def __init__(self, link):
        self.link = link
        self._session = None
        self.followed = None        # the last office notification id handed to the phones

    def routes(self, add):
        add.add_get("/v1/office/ws", self.h_ws)
        add.add_get("/v1/office/api/{tail:.*}", self.h_api)
        add.add_post("/v1/office/api/{tail:.*}", self.h_api)

    def _http(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=3, sock_read=120))
        return self._session

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def base(self):
        return f"127.0.0.1:{office_port()}"

    async def h_api(self, request):
        if not self.link._allowed(SWITCH):
            return _error(403, "the office needs the commands switch, which is off for this device")
        tail = request.match_info["tail"]
        headers = {"X-Office": "1"} if request.method == "POST" else {}
        # who is asking, for the office's records only: "phone" grants nothing the operator key would
        headers["X-Office-Actor"] = "phone"
        phone = request.get("phone") or {}
        if phone.get("fingerprint"):
            headers["X-Office-Device"] = str(phone["fingerprint"]).replace(":", "")[:16]
        if request.content_type:
            headers["Content-Type"] = request.content_type
        body = await request.read() if request.method == "POST" else None
        if request.method == "POST":
            self.link.audit.write(request["peer"], "office", f"{tail}")
        try:
            async with self._http().request(request.method, f"http://{self.base}/api/{tail}",
                                            params=request.query, data=body, headers=headers) as up:
                out = web.StreamResponse(status=up.status, headers={
                    "Content-Type": up.headers.get("Content-Type", "application/octet-stream")})
                if up.content_length is not None:
                    out.content_length = up.content_length
                await out.prepare(request)
                async for chunk in up.content.iter_chunked(64 * 1024):
                    await out.write(chunk)
                await out.write_eof()
                return out
        except aiohttp.ClientConnectorError:
            return _error(503, "the office is not running on the computer")
        except asyncio.TimeoutError:
            return _error(504, "the office did not answer in time")

    async def h_ws(self, request):
        if not self.link._allowed(SWITCH):
            return _error(403, "the office needs the commands switch, which is off for this device")
        try:
            up = await self._http().ws_connect(f"ws://{self.base}/ws", origin=f"http://{self.base}",
                                               heartbeat=20, max_msg_size=0)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return _error(503, "the office is not running on the computer")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
        await ws.prepare(request)
        self.link._track(ws)

        async def down():                       # office -> phone
            async for m in up:
                if m.type == WSMsgType.TEXT:
                    await ws.send_str(m.data)
                elif m.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        async def upward():                     # phone -> office (keep-alives)
            async for m in ws:
                if m.type == WSMsgType.TEXT:
                    await up.send_str(m.data)
                elif m.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        tasks = [asyncio.create_task(down()), asyncio.create_task(upward())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await up.close()
            await ws.close()
        return ws

    # ------------------------------------------ alerts, without the Office page open

    async def follow(self):
        """Hand each new office notification to the listening phones, as it is made."""
        while True:
            try:
                if self.followed is None:          # start at the newest: older ones are the phone's own catch-up
                    self.followed = (await self._notifications(0, 0))["head"]
                got = await self._notifications(self.followed, FOLLOW_WAIT_S, limit=50)
                for n in got["notifications"]:
                    self.followed = max(self.followed, n["id"])
                    if self.link._allowed(SWITCH):
                        self.link.events.add("office", n["title"], n["text"], app="Agent Office", keep=False,
                                             data={"office": _brief(n)})
                if got["head"] < self.followed:    # the office's database was replaced: start again from it
                    self.followed = got["head"]
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, KeyError):
                # keep the place: what the office made while it was away or restarting is handed on once it
                # answers again (a replaced database is noticed by its head going back, above)
                await asyncio.sleep(FOLLOW_RETRY_S)

    async def _notifications(self, after, wait, limit=100):
        async with self._http().get(f"http://{self.base}/api/notifications",
                                    params={"after": str(after), "wait": str(wait), "limit": str(limit)},
                                    timeout=aiohttp.ClientTimeout(total=wait + 15)) as up:
            up.raise_for_status()
            return await up.json()


def _brief(n):
    """What the phone needs to show a notification and open what it is about."""
    return {k: n.get(k) for k in ("id", "priority", "group", "title", "text", "agent", "task_id", "mission_id",
                                  "inbox_id", "report_id", "created_at")}
