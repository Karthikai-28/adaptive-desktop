"""Adaptive Link - the owner's Google account, and the small space it gives
their devices to find each other in.

Two things, both under an account the owner signs in to with Google:

  sign-in     The computer signs in the way a television does: it shows a
              short code, the owner approves it at google.com/device on any
              device they are already signed in on. Nothing is typed here and
              no password ever reaches this program.
  the space   A Firebase Realtime Database in the owner's own project, with
              one rule: the part under users/<uid> can be read and written
              only by someone signed in as that uid. The computer and the
              phone, signed in to the same account, are the only ones there.

What is kept in the space is small and none of it is secret: each device's
name, certificate fingerprint and addresses, a phone's request to connect,
and the messages two devices exchange to open a direct connection.

What the space is *not* is the authority on who may control this computer.
A device being in the account's space lets it ask. The computer still shows
the request and the owner still approves it here, and every connection after
that is the same mutual TLS as before, checked against the certificate kept
on this machine. The data itself never passes through Google: it goes
directly between the two devices.

The project belongs to the owner (docs/ADAPTIVE_LINK.md says how to make
one, free). Its identifiers are kept in link/cloud.json, the signed-in
session in link/session.json, both readable by the owner only.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import aiohttp

import identity

GOOGLE_DEVICE_CODE = "https://oauth2.googleapis.com/device/code"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
FIREBASE_SIGN_IN = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp"
FIREBASE_REFRESH = "https://securetoken.googleapis.com/v1/token"

PROJECT_KEYS = ("api_key", "database_url", "web_client_id", "device_client_id", "device_client_secret")


class CloudError(Exception):
    pass


# ------------------------------------------------------------------- files

def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_project(link_dir=None):
    """The owner's Firebase project, or None if it is not set up.

    For verify-link.py the same file may also carry "endpoints", pointing
    the four URLs above at a stand-in server.
    """
    data = _read((link_dir or identity.LINK_DIR) / "cloud.json")
    if not data or any(not isinstance(data.get(key), str) or not data[key] for key in PROJECT_KEYS):
        return None
    if not data["database_url"].startswith(("https://", "http://127.0.0.1", "http://localhost")):
        return None
    data["database_url"] = data["database_url"].rstrip("/")
    return data


def save_project(values, link_dir=None):
    project = {key: str(values[key]).strip() for key in PROJECT_KEYS}
    if isinstance(values.get("endpoints"), dict):
        project["endpoints"] = values["endpoints"]
    identity._write_private((link_dir or identity.LINK_DIR) / "cloud.json",
                            (json.dumps(project, indent=2) + "\n").encode())
    return project


def load_session(link_dir=None):
    data = _read((link_dir or identity.LINK_DIR) / "session.json")
    if not data or not data.get("refresh_token") or not data.get("uid"):
        return None
    return data


def save_session(session, link_dir=None):
    identity._write_private((link_dir or identity.LINK_DIR) / "session.json",
                            (json.dumps(session, indent=2) + "\n").encode())


def forget_session(link_dir=None):
    try:
        ((link_dir or identity.LINK_DIR) / "session.json").unlink()
        return True
    except FileNotFoundError:
        return False


def device_id(fingerprint):
    """A device's name in the space: the start of its certificate fingerprint."""
    return fingerprint[:20]


# ------------------------------------------------------------------ account

class Account:
    """The signed-in owner: who they are, and a token that proves it."""

    def __init__(self, project, link_dir=None):
        self.project = project
        self.link_dir = link_dir or identity.LINK_DIR
        self.session = load_session(self.link_dir)
        self._token = ""
        self._expires = 0.0
        self._http = None
        endpoints = project.get("endpoints") or {}
        self._device_code_url = endpoints.get("device_code", GOOGLE_DEVICE_CODE)
        self._google_token_url = endpoints.get("google_token", GOOGLE_TOKEN)
        self._sign_in_url = endpoints.get("sign_in", FIREBASE_SIGN_IN)
        self._refresh_url = endpoints.get("refresh", FIREBASE_REFRESH)

    @property
    def signed_in(self):
        return self.session is not None

    @property
    def email(self):
        return (self.session or {}).get("email", "")

    @property
    def uid(self):
        return (self.session or {}).get("uid", "")

    def http(self):
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._http

    async def close(self):
        if self._http is not None and not self._http.closed:
            await self._http.close()

    async def _post_form(self, url, data, params=None):
        async with self.http().post(url, data=data, params=params) as reply:
            try:
                body = await reply.json(content_type=None)
            except ValueError:
                body = {}
            return reply.status, body if isinstance(body, dict) else {}

    # ---- signing in, the way a television does

    async def begin_sign_in(self):
        """Ask Google for a code. Returns {user_code, verification_url,
        device_code, interval, expires_in}: the first two are shown to the
        owner, who enters the code at the address on any signed-in device."""
        status, body = await self._post_form(self._device_code_url, {
            "client_id": self.project["device_client_id"], "scope": "openid email"})
        if status != 200 or "device_code" not in body:
            raise CloudError(body.get("error_description") or body.get("error") or f"Google answered {status}")
        return {"user_code": body["user_code"],
                "verification_url": body.get("verification_url") or body.get("verification_uri", ""),
                "device_code": body["device_code"],
                "interval": int(body.get("interval", 5)), "expires_in": int(body.get("expires_in", 1800))}

    async def finish_sign_in(self, started):
        """Wait for the owner to approve the code, then sign in. Returns the
        email address signed in as."""
        deadline = time.monotonic() + started["expires_in"]
        interval = max(1, started["interval"])
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            status, body = await self._post_form(self._google_token_url, {
                "client_id": self.project["device_client_id"],
                "client_secret": self.project["device_client_secret"],
                "device_code": started["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            if status == 200 and body.get("id_token"):
                return await self._exchange(body["id_token"])
            error = body.get("error", "")
            if error == "slow_down":
                interval += 2
            elif error not in ("authorization_pending", ""):
                raise CloudError(body.get("error_description") or error)
        raise CloudError("the code was not approved in time")

    async def _exchange(self, google_id_token):
        """A Google identity token for a session in the owner's project."""
        async with self.http().post(self._sign_in_url, params={"key": self.project["api_key"]}, json={
                "postBody": f"id_token={google_id_token}&providerId=google.com",
                "requestUri": "http://localhost", "returnSecureToken": True}) as reply:
            body = await reply.json(content_type=None)
        if reply.status != 200 or not body.get("refreshToken"):
            raise CloudError((body.get("error") or {}).get("message", f"sign-in answered {reply.status}"))
        if not body.get("emailVerified", True):
            raise CloudError("that account's email address is not verified")
        self.session = {"uid": body["localId"], "email": body.get("email", ""),
                        "refresh_token": body["refreshToken"], "signed_in_at": int(time.time())}
        save_session(self.session, self.link_dir)
        self._token, self._expires = body["idToken"], time.monotonic() + int(body.get("expiresIn", 3600)) - 120
        return self.session["email"]

    def sign_out(self):
        self.session = None
        self._token, self._expires = "", 0.0
        return forget_session(self.link_dir)

    async def token(self):
        """A current token for the database, refreshed when it is about to lapse."""
        if not self.session:
            raise CloudError("not signed in")
        if self._token and time.monotonic() < self._expires:
            return self._token
        status, body = await self._post_form(
            self._refresh_url, {"grant_type": "refresh_token", "refresh_token": self.session["refresh_token"]},
            params={"key": self.project["api_key"]})
        if status != 200 or not body.get("id_token"):
            message = (body.get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else ""
            if "TOKEN_EXPIRED" in message or "USER_DISABLED" in message or "INVALID_REFRESH_TOKEN" in message:
                self.sign_out()
                raise CloudError("the sign-in is no longer valid; sign in again")
            raise CloudError(message or f"token refresh answered {status}")
        self._token, self._expires = body["id_token"], time.monotonic() + int(body.get("expires_in", 3600)) - 120
        return self._token

    # ---- the space

    def _url(self, path):
        return f"{self.project['database_url']}/users/{self.uid}/{path.strip('/')}.json"

    async def get(self, path):
        async with self.http().get(self._url(path), params={"auth": await self.token()}) as reply:
            if reply.status != 200:
                raise CloudError(f"database answered {reply.status}")
            return await reply.json(content_type=None)

    async def put(self, path, value):
        async with self.http().put(self._url(path), params={"auth": await self.token()}, json=value) as reply:
            if reply.status != 200:
                raise CloudError(f"database answered {reply.status}")

    async def patch(self, path, value):
        async with self.http().patch(self._url(path), params={"auth": await self.token()}, json=value) as reply:
            if reply.status != 200:
                raise CloudError(f"database answered {reply.status}")

    async def delete(self, path):
        async with self.http().delete(self._url(path), params={"auth": await self.token()}) as reply:
            if reply.status != 200:
                raise CloudError(f"database answered {reply.status}")

    async def watch(self, path, on_change):
        """Call on_change(subpath, value) for the current contents of path
        and for every change after, until cancelled. Returns only on error.

        This is the database's event stream: one long request, so a phone's
        request reaches the computer at once and nothing is polled.
        """
        timeout = aiohttp.ClientTimeout(total=None, sock_read=90)
        async with self.http().get(self._url(path), params={"auth": await self.token()},
                                   headers={"Accept": "text/event-stream"}, timeout=timeout) as reply:
            if reply.status != 200:
                raise CloudError(f"database answered {reply.status}")
            event = ""
            async for raw in reply.content:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    if event in ("put", "patch"):
                        try:
                            data = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        if isinstance(data, dict):
                            await on_change(str(data.get("path", "/")), data.get("data"))
                    elif event in ("auth_revoked", "cancel"):
                        # The token lapsed (hourly): the caller reconnects.
                        return


def environment_ok():
    """Whether the peer-to-peer library is installed where the daemon looks."""
    return (Path(__file__).resolve().parent.parent.parent / ".local" / "link-pydeps").is_dir() or \
        bool(os.environ.get("ADAPTIVE_LINK_PYDEPS"))
