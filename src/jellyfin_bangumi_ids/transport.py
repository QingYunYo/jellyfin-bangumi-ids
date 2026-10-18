"""Tiny HTTP helpers shared by the Jellyfin and Bangumi clients (stdlib only)."""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

USER_AGENT = "jellyfin-bangumi-ids/1.0 (+https://github.com/)"


class NetError(Exception):
    """A network failure that survived the retries."""


class HttpError(Exception):
    """Non-retryable HTTP status."""

    def __init__(self, status: int, body: str, url: str):
        super().__init__("HTTP %s for %s: %s" % (status, url, (body or "")[:200]))
        self.status = status
        self.body = body
        self.url = url


def force_ipv4() -> None:
    """Prefer IPv4 for every later getaddrinfo call.

    Jellyfin hosts often run on NAS boxes with broken/blocked IPv6; a dual-stack
    DNS answer with a poisoned AAAA record makes urllib wait ~20 s per request.
    """
    _orig = socket.getaddrinfo

    def only_v4(host, port, family=0, type=0, proto=0, flags=0):
        return _orig(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = only_v4  # type: ignore[assignment]


def build_url(base: str, path: str, params: Optional[Dict[str, Any]] = None) -> str:
    url = base.rstrip("/") + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
    return url


def request(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    method: Optional[str] = None,
    timeout: float = 20,
    retries: int = 0,
) -> bytes:
    """GET/POST with optional exponential backoff. Returns the raw body."""
    attempt = 0
    last: Optional[Exception] = None
    while attempt <= retries:
        attempt += 1
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("User-Agent", USER_AGENT)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt <= retries:
                last = exc
                time.sleep(1.5 * attempt)
                continue
            raise HttpError(exc.code, text, url) from exc
        except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
            last = exc
            if attempt <= retries:
                time.sleep(1.5 * attempt)
                continue
    raise NetError("%s (%s)" % (url, last))


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 20,
             retries: int = 0) -> Any:
    raw = request(url, headers=headers, timeout=timeout, retries=retries)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def post_json(url: str, payload: Any, headers: Optional[Dict[str, str]] = None,
              timeout: float = 20, retries: int = 0) -> Any:
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw = request(url, headers=hdrs, body=body, method="POST", timeout=timeout, retries=retries)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return raw.decode("utf-8", "replace")
