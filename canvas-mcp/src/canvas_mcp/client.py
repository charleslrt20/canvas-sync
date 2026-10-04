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

# Hosts Canvas redirects file downloads to (Instructure's file CDN).
FILE_CDN_SUFFIXES = (".inscloudgate.net", ".instructure.com", ".s3.amazonaws.com")
MAX_DOWNLOAD_BYTES = 50_000_000
_LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')

_STATUS_MESSAGES = {
    401: "Canvas token invalid or expired",
    403: "no permission to view this in Canvas",
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
        self._host = urlsplit(self._base).hostname
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
        """Return (file metadata, file bytes) for a Canvas file."""
        meta = self.get(f"/files/{int(file_id)}")
        if (meta.get("size") or 0) > MAX_DOWNLOAD_BYTES:
            raise CanvasError("file too large to read (over 50 MB)")
        url = meta.get("url")
        if not url:
            raise CanvasError("file has no download URL (it may be locked)")
        for _ in range(5):
            resp = self._send(url, auth=urlsplit(url).hostname == self._host, check_host=True)
            if resp.is_redirect:
                url = str(resp.next_request.url) if resp.next_request else resp.headers["Location"]
                continue
            self._raise_for_status(resp)
            if len(resp.content) > MAX_DOWNLOAD_BYTES:
                raise CanvasError("file too large to read (over 50 MB)")
            return meta, resp.content
        raise CanvasError("too many redirects downloading file")

    # -- internals -------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._api}{path}"

    def _cached(self, key: tuple, fetch: Callable[[], Any]) -> Any:
        hit = self._cache.get(key)
        now = self._clock()
        if hit and hit[0] > now:
            return hit[1]
        value = fetch()
        self._cache[key] = (now + self._ttl, value)
        return value

    def _check_api_url(self, url: str) -> None:
        parts = urlsplit(url)
        path = parts.path
        if parts.hostname != self._host or not path.startswith("/api/v1/") or ".." in path:
            raise CanvasError(f"request not allowed: {path}")
        api_path = path[len("/api/v1"):]
        if not any(p.match(api_path) for p in ALLOWED_PATHS):
            raise CanvasError(f"request not allowed: {api_path}")

    def _check_download_host(self, url: str) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or not (host == self._host or host.endswith(FILE_CDN_SUFFIXES)):
            raise CanvasError(f"download host not allowed: {host}")

    def _get_json(self, url: str, params) -> tuple[Any, str | None]:
        self._check_api_url(url)
        resp = self._send(url, params=params, auth=True)
        self._raise_for_status(resp)
        match = _LINK_NEXT.search(resp.headers.get("Link", ""))
        next_url = match.group(1) if match else None
        if next_url:
            self._check_api_url(next_url)
        return resp.json(), next_url

    def _send(self, url: str, *, params=None, auth: bool, check_host: bool = False) -> httpx.Response:
        if check_host:
            self._check_download_host(url)
        return self._request("GET", url, params=params, auth=auth)

    def _request(self, method: str, url: str, *, params=None, auth: bool = True) -> httpx.Response:
        if method != "GET":
            raise CanvasError("this Canvas client is read-only")
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
        try:
            return self._http.request("GET", url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise CanvasError(f"could not reach Canvas ({type(exc).__name__})") from None

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        if resp.status_code in _STATUS_MESSAGES:
            raise CanvasError(_STATUS_MESSAGES[resp.status_code])
        if resp.status_code >= 500:
            raise CanvasError(f"Canvas is having problems (HTTP {resp.status_code})")
        raise CanvasError(f"Canvas request failed (HTTP {resp.status_code})")
