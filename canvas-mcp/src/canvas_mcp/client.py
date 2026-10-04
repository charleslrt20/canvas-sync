"""Read-only Canvas REST client.

Every request goes through `_request`, which refuses anything but GET and any
API path not on the allowlist *before* touching the network. The token is only
ever sent to the Canvas host and never appears in errors or reprs.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

ALLOWED_PATHS = [
    re.compile(p)
    for p in (
        r"^/courses$",
        r"^/courses/\d+/assignments/\d+$",
        r"^/courses/\d+/students/submissions$",
        r"^/courses/\d+/files$",
        r"^/planner/items$",
        r"^/users/self/missing_submissions$",
        r"^/announcements$",
        r"^/files/\d+$",
    )
]

# The first download hop on the Canvas host itself must be a file-download URL.
_CANVAS_DOWNLOAD_PATH = re.compile(r"/(courses/\d+/)?files/\d+/download")
# Hosts Canvas redirects file downloads to (Instructure's file CDN). The token is never sent there.
FILE_CDN_SUFFIXES = (".canvas-user-content.com", ".inscloudgate.net", ".instructure.com", ".s3.amazonaws.com")
MAX_DOWNLOAD_BYTES = 50_000_000
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')

_TOKEN_INVALID = "Canvas token invalid or expired"
_NO_PERMISSION = "no permission to view this in Canvas"
_STATUS_MESSAGES = {
    401: _TOKEN_INVALID,  # refined in _raise_for_status: Canvas also uses 401 for "not authorized"
    403: _NO_PERMISSION,
    404: "not found in Canvas",
    429: "Canvas rate limited the request, retry in a minute",
}


class CanvasError(Exception):
    """Short, model-readable error. Never contains the token."""


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        ttl: float = 600,
        max_pages: int = 10,
        clock: Callable[[], float] = time.monotonic,
        http: httpx.Client | None = None,
    ) -> None:
        if not token:
            raise CanvasError("CANVAS_TOKEN is not set")
        self._base = base_url.rstrip("/")
        base = urlsplit(self._base)
        self._origin = (base.scheme, base.hostname, base.port)
        self._host = base.hostname
        self._api = f"{self._base}/api/v1"
        self._token = token
        self._ttl = ttl
        self._max_pages = max_pages
        self._clock = clock
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._http = http or httpx.Client(timeout=30, follow_redirects=False)

    def __repr__(self) -> str:
        return f"CanvasClient(base_url={self._base!r})"

    # -- public API ----------------------------------------------------------

    def get(self, path: str, params: list[tuple[str, str]] | None = None) -> Any:
        """GET one API resource (first page only)."""
        return self._cached(("get", path, tuple(params or ())), lambda: self._get_json(self._url(path), params)[0])

    def get_all(self, path: str, params: list[tuple[str, str]] | None = None) -> list:
        """GET a paginated list, following Link rel="next" up to max_pages."""

        def fetch() -> list:
            items: list = []
            url, page_params = self._url(path), params
            for _ in range(self._max_pages):
                data, next_url = self._get_json(url, page_params)
                items.extend(data if isinstance(data, list) else [data])
                if not next_url:
                    break
                url, page_params = next_url, None  # next link already carries the query
            return items

        return self._cached(("all", path, tuple(params or ())), fetch)

    def download(self, file_id: int) -> tuple[dict, bytes]:
        """Return (file metadata, file bytes) for a Canvas file, streamed with a size cap."""
        meta = self.get(f"/files/{int(file_id)}")
        if (meta.get("size") or 0) > MAX_DOWNLOAD_BYTES:
            raise CanvasError("file too large to read (over 50 MB)")
        url = meta.get("url")
        if not url:
            raise CanvasError("file has no download URL (it may be locked)")
        for _ in range(5):
            self._check_download_url(url)
            on_canvas = urlsplit(url).hostname == self._host
            next_url, data = self._stream_get(url, auth=on_canvas)
            if next_url is None:
                return meta, data
            url = next_url
        raise CanvasError("too many redirects downloading file")

    # -- internals -------------------------------------------------------------

    def _url(self, path: str) -> str:
        if not any(p.fullmatch(path) for p in ALLOWED_PATHS):
            raise CanvasError(f"request not allowed: {path!r}")
        return f"{self._api}{path}"

    def _cached(self, key: tuple, fetch: Callable[[], Any]) -> Any:
        now = self._clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        value = fetch()
        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}  # drop expired entries
        self._cache[key] = (now + self._ttl, value)
        return value

    def _check_api_url(self, url: str) -> None:
        parts = urlsplit(url)
        path = parts.path
        if (parts.scheme, parts.hostname, parts.port) != self._origin or not path.startswith("/api/v1/"):
            raise CanvasError(f"request not allowed: {path}")
        api_path = path[len("/api/v1"):]
        if not any(p.fullmatch(api_path) for p in ALLOWED_PATHS):
            raise CanvasError(f"request not allowed: {api_path}")

    def _check_download_url(self, url: str) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https":
            raise CanvasError(f"download not allowed over {parts.scheme or 'unknown scheme'}")
        if host == self._host:
            if not _CANVAS_DOWNLOAD_PATH.fullmatch(parts.path):
                raise CanvasError(f"download path not allowed: {parts.path}")
        elif not host.endswith(FILE_CDN_SUFFIXES):
            raise CanvasError(f"download host not allowed: {host}")

    def _get_json(self, url: str, params) -> tuple[Any, str | None]:
        self._check_api_url(url)
        resp = self._request("GET", url, params=params, auth=True)
        if resp.is_redirect:  # API calls never legitimately redirect; don't follow, don't parse
            raise CanvasError(f"Canvas request failed (unexpected redirect, HTTP {resp.status_code})")
        self._raise_for_status(resp)
        match = _LINK_NEXT.search(resp.headers.get("Link", ""))
        next_url = match.group(1) if match else None
        if next_url:
            self._check_api_url(next_url)
        try:
            return resp.json(), next_url
        except ValueError:
            raise CanvasError("Canvas sent an unreadable response") from None

    def _stream_get(self, url: str, *, auth: bool) -> tuple[str | None, bytes]:
        """GET a file; returns (redirect_url, b"") or (None, body). Stops reading at the size cap."""
        headers = self._auth_headers(auth)
        try:
            with self._http.stream("GET", url, headers=headers) as resp:
                if resp.is_redirect:
                    return str(resp.next_request.url) if resp.next_request else resp.headers["Location"], b""
                if resp.status_code >= 400:
                    resp.read()  # small error body, needed to tell a bad token from "not authorized"
                self._raise_for_status(resp)
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_DOWNLOAD_BYTES:
                        raise CanvasError("file too large to read (over 50 MB)")
                return None, bytes(body)
        except httpx.HTTPError as exc:
            raise CanvasError(f"could not reach Canvas ({type(exc).__name__})") from None

    def _request(self, method: str, url: str, *, params=None, auth: bool = True) -> httpx.Response:
        if method != "GET":
            raise CanvasError("this Canvas client is read-only")
        try:
            return self._http.request("GET", url, params=params, headers=self._auth_headers(auth))
        except httpx.HTTPError as exc:
            raise CanvasError(f"could not reach Canvas ({type(exc).__name__})") from None

    def _auth_headers(self, auth: bool) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if auth else {}

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        if resp.status_code == 401:
            # Canvas uses 401 both for a bad token (with WWW-Authenticate / "Invalid access
            # token") and for "user not authorized to perform that action" with a good one.
            try:
                body = resp.text.lower()
            except httpx.ResponseNotRead:  # streamed download error before the body was read
                body = ""
            bad_token = "WWW-Authenticate" in resp.headers or "invalid access token" in body or "expired" in body
            raise CanvasError(_TOKEN_INVALID if bad_token else _NO_PERMISSION)
        if resp.status_code in _STATUS_MESSAGES:
            raise CanvasError(_STATUS_MESSAGES[resp.status_code])
        if resp.status_code >= 500:
            raise CanvasError(f"Canvas is having problems (HTTP {resp.status_code})")
        raise CanvasError(f"Canvas request failed (HTTP {resp.status_code})")
