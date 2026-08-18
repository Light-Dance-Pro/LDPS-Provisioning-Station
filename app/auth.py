"""Operator authentication for the Station's own HTTP + WebSocket surface.

WHY THIS EXISTS
The Station holds the manufacturer API key — an authority far greater than any single
operator action, since it mints cloud-signed identities and spends quota. Every route
was reachable by anyone who could open the port, which made the Station a remote control
for that credential. This gives it a notion of WHO is asking.

DESIGN NOTES (each of these was a real bug in an earlier draft)

* Pure ASGI, not BaseHTTPMiddleware. BaseHTTPMiddleware only sees scope["type"] == "http",
  so a WebSocket upgrade slips straight past it. /ws broadcasts provision events that
  carry the plaintext recovery key, so leaving it open would have defeated the point while
  looking fixed.

* Basic auth cannot cover WebSockets: the browser WebSocket API cannot set an
  Authorization header. So a successful HTTP auth also sets an HttpOnly cookie, and the
  WS handshake is authorised by that cookie (browsers do send cookies on a same-origin
  handshake). The cookie carries a derived token, never the secret itself.

* Loopback is exempt. Reaching 127.0.0.1 already requires being on the box, where the
  secret file lives anyway. This keeps the unattended kiosk browser and the on-Pi helper
  scripts (ldps-bind-dongle.sh, ldps-kiosk.sh) working with no credential handling, while
  everything arriving over the network must authenticate.

* Fail CLOSED. A missing or empty secret file raises at startup rather than silently
  serving unauthenticated — the failure mode that would quietly undo all of this.

* SameSite=Strict on the cookie, plus no CORS wildcard, keeps a hostile page in a factory
  browser from driving the API through the operator's own session.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

SECRET_FILE = os.environ.get("LDPS_SECRET_FILE", "/etc/ldps-station/operator.secret")
COOKIE_NAME = "ldps_op"
REALM = "LDPS Provisioning Station"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def load_secret() -> str:
    """Read the shared operator secret. Raises if absent — never returns empty."""
    try:
        with open(SECRET_FILE) as f:
            secret = f.read().strip()
    except OSError as e:
        raise RuntimeError(
            f"operator secret unreadable at {SECRET_FILE} ({e}). The Station refuses to "
            f"start unauthenticated. Create it with:\n"
            f"  install -d -m 750 {os.path.dirname(SECRET_FILE)}\n"
            f"  openssl rand -base64 24 > {SECRET_FILE} && chmod 600 {SECRET_FILE}"
        ) from e
    if not secret:
        raise RuntimeError(f"operator secret at {SECRET_FILE} is empty — refusing to start")
    return secret


def _cookie_token(secret: str) -> str:
    """Derived WS token, so the cookie never carries the secret itself."""
    return hmac.new(secret.encode(), b"ldps-ws-v1", hashlib.sha256).hexdigest()


class OperatorAuth:
    """ASGI middleware guarding both HTTP and WebSocket scopes."""

    def __init__(self, app, secret: str) -> None:
        self.app = app
        self._secret = secret.encode()
        self._token = _cookie_token(secret)

    # ---- helpers ---------------------------------------------------------
    def _is_loopback(self, scope) -> bool:
        client = scope.get("client") or ("", 0)
        return (client[0] or "") in LOOPBACK

    def _headers(self, scope) -> dict:
        return {k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in (scope.get("headers") or [])}

    def _basic_ok(self, header: str) -> bool:
        if not header.lower().startswith("basic "):
            return False
        try:
            raw = base64.b64decode(header[6:], validate=True).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            return False
        _, _, password = raw.partition(":")
        return hmac.compare_digest(password.encode(), self._secret)

    def _cookie_ok(self, header: str) -> bool:
        for part in header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                return hmac.compare_digest(value, self._token)
        return False

    # ---- ASGI ------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or self._is_loopback(scope):
            return await self.app(scope, receive, send)

        headers = self._headers(scope)
        cookie_ok = self._cookie_ok(headers.get("cookie", ""))

        if scope["type"] == "websocket":
            # No Authorization header is possible here — the cookie is the only route in.
            if cookie_ok:
                return await self.app(scope, receive, send)
            await send({"type": "websocket.close", "code": 1008})
            return

        if cookie_ok:
            return await self.app(scope, receive, send)

        if self._basic_ok(headers.get("authorization", "")):
            # Authorised: issue the cookie so the SPA's WebSocket can connect too.
            cookie = (f"{COOKIE_NAME}={self._token}; Path=/; HttpOnly; SameSite=Strict")

            async def send_with_cookie(message):
                if message["type"] == "http.response.start":
                    message = dict(message)
                    message["headers"] = list(message.get("headers") or []) + [
                        (b"set-cookie", cookie.encode("latin-1"))
                    ]
                await send(message)

            return await self.app(scope, receive, send_with_cookie)

        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"www-authenticate", f'Basic realm="{REALM}"'.encode("latin-1")),
                (b"content-type", b"application/json"),
            ],
        })
        await send({"type": "http.response.body",
                    "body": b'{"error":"authentication required"}'})
