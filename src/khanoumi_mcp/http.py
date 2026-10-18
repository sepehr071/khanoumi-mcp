"""Shared async HTTP client for www.khanoumi.com.

Every tool goes through `api` (the JSON REST API under /api/) or `get_page` (server-rendered
HTML: FAQ, blog). `_send` caps concurrency, retries transient failures with backoff,
and turns HTTP failures into `ToolError` messages the model can act on. The client keeps the
anonymous cookies the API sets (`x-nusi`, `x-nux`; `uci` only from some calls such as similar).
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from typing import Any

import httpx
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://www.khanoumi.com"

# User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
HEADERS = {"Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8"}
# Same-origin fetch from the site's own pages: Chrome sends Referer but no Origin on a same-origin GET.
API_HEADERS = {
    "Accept": "application/json, text/html;q=0.9",
    "Referer": f"{BASE}/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "priority": "u=0, i",
}

MAX_CONCURRENCY = 2
JITTER = (0.15, 0.6)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
CACHE_TTL = 1200  # seconds, for the FAQ, app config and category tree
CACHE_MAX = 64  # entries; the oldest go first
RETRY_DELAY = 0.5  # seconds; doubles per retry

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_browser_lock: asyncio.Lock | None = None
_cleared: tuple[httpx.AsyncClient, float] | None = None
_cache: dict[tuple, tuple[float, Any]] = {}  # (url, params) -> (expiry, value); only for calls with ttl


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them (API calls are XHR)."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        p = super()._create_request_params(req)
        p["headers"] = [*p["headers"], (b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _proxy_index, _browser_lock, _cleared
    _transport, _client, _limit, _proxy_index, _browser_lock, _cleared = transport, None, None, 0, None, None
    _cache.clear()


async def _same_host(request: httpx.Request) -> None:
    if request.url.host != "www.khanoumi.com":
        # status 0: a refusal, never retried
        raise ApiError(f"Refused a redirect to {request.url.host}: only www.khanoumi.com is allowed.", 0)


def _proxies() -> list[str]:
    """KHANOUMI_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("KHANOUMI_MCP_PROXY", "").split(",") if p.strip()]


# Plain error pages are not challenges: a bare 403 HTML page is often a normal refusal.
_CHALLENGE = re.compile(r"just a moment|captcha|challenge|arvan|attention required|enable javascript", re.I)


def _is_challenge(r: httpx.Response) -> bool:
    """A bot-check page: 403/429/503 with an HTML body that carries a known challenge marker."""
    return (
        r.status_code in (403, 429, 503)
        and "html" in r.headers.get("content-type", "") + r.text[:20].lower()
        and bool(_CHALLENGE.search(r.text[:5000]))
    )


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate: a slower request that failed on an old client must not skip a good proxy.
    The old client is closed late because other requests may still be using it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(30)  # longer than the 30 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # Khanoumi answers direct connections fine; a system proxy is only used when the user opts in with
        # KHANOUMI_MCP_PROXY. One client = one cookie jar for the session. curl_cffi presents Chrome's
        # TLS/HTTP2 fingerprint and default headers; cookies and redirects stay with httpx. The proxy goes to the
        # transport (a client-level proxy would be ignored once a transport is given).
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=30,
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=True,
            event_hooks={"request": [_same_host]},  # also runs on redirect hops: never leave the site with the cookies
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def _cached(key: tuple, ttl: float, fetch) -> Any:
    """Return fetch() memoised for ttl seconds (0 = no cache). Callers must not mutate the result."""
    hit = _cache.get(key)
    if ttl and hit and hit[0] > time.monotonic():
        return hit[1]
    value = await fetch()
    if ttl:
        while len(_cache) >= CACHE_MAX:
            del _cache[next(iter(_cache))]
        _cache[key] = (time.monotonic() + ttl, value)
    return value


async def api(path: str, params: dict[str, Any] | None = None, ttl: float = 0) -> Any:
    """GET an API path (`/api/ntl/v1/products`, ...) and return the envelope's `data`; None for HTTP 204.

    ttl > 0 caches the result that many seconds (only for slow-changing data).
    """
    key = (path, tuple(sorted((k, repr(v)) for k, v in (params or {}).items() if v is not None)))
    return await _cached(key, ttl, lambda: _api(path, params))


async def _api(path: str, params: dict[str, Any] | None) -> Any:
    r = await _send(
        "GET", f"{BASE}{path}", params={k: v for k, v in (params or {}).items() if v is not None}, headers=API_HEADERS
    )
    if r.status_code == 204:  # banners and pop-ups: nothing running
        return None
    try:
        body = r.json()
    except ValueError as e:
        raise ApiError(f"khanoumi.com returned a non-JSON response for {path} (HTTP {r.status_code}).") from e
    if not isinstance(body, dict) or not body.get("isSuccess"):
        raise ApiError(f"khanoumi.com rejected the request: {_errors(body) or str(body)[:300]}")
    return body.get("data")


async def get_page(path: str, params: dict[str, Any] | None = None, ttl: float = 0) -> str:
    """GET a site page and return its HTML (ttl > 0 caches it that many seconds)."""

    async def fetch() -> str:
        return (await _send("GET", f"{BASE}{path}", params=params, headers=PAGE_HEADERS)).text

    return await _cached((path, tuple(sorted((params or {}).items()))), ttl, fetch)


async def _send(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Every call is a GET, so a timeout, network error, 5xx or 429 is retried up to MAX_RETRIES times with
    jittered exponential backoff, or after Retry-After when sent. Other 4xx (403 too) are never retried."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await _once(method, url, **kwargs)
        except ApiError as e:
            if attempt == MAX_RETRIES or (e.status is not None and e.status < 500 and e.status != 429):
                raise
            wait = e.retry_after if e.retry_after is not None else RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
    raise AssertionError("unreachable")


async def _request(client: httpx.AsyncClient, limit: asyncio.Semaphore, method: str, url: str, **kwargs: Any):
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            return await client.request(method, url, **kwargs)
    except httpx.TimeoutException as e:
        raise ApiError("khanoumi.com did not answer in time. Try again in a moment.") from e
    except httpx.TransportError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach khanoumi.com ({type(e).__name__}). Check the internet connection, "
            "or set KHANOUMI_MCP_PROXY."
        ) from e


async def _browser_cookies(proxy: str | None) -> list[dict[str, Any]]:
    """Open the home page in headless patchright, wait for the challenge to clear, return the cookies."""
    try:
        from patchright.async_api import async_playwright
    except ImportError as e:
        raise ApiError(
            "Khanoumi served a bot-check page. Install the browser extra (`pip install khanoumi-mcp[browser]`, or "
            "`uvx --with patchright==1.63.0 khanoumi-mcp`) and run `patchright install chromium`.",
            403,
        ) from e
    u = httpx.URL(proxy) if proxy else None
    opts = u and {"server": f"{u.scheme}://{u.host}:{u.port}", "username": u.username, "password": u.password}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=opts)
        try:
            page = await browser.new_page()
            await page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_function(
                "!/just a moment|access denied|attention required|arvancloud/i.test(document.title)", timeout=30_000
            )
            return await browser.contexts[0].cookies()
        finally:
            await browser.close()


async def _clear_challenge(client: httpx.AsyncClient) -> None:
    """Rung 2: let a real browser pass the bot check once and share its cookies with the httpx jar."""
    global _browser_lock, _cleared
    _browser_lock = _browser_lock or asyncio.Lock()
    async with _browser_lock:  # one browser at a time; callers that waited reuse the cookies just fetched
        if _cleared and _cleared[0] is client and time.monotonic() - _cleared[1] < 30:
            return
        proxies = _proxies()
        try:
            cookies = await _browser_cookies(proxies[_proxy_index % len(proxies)] if proxies else None)
        except ApiError:
            raise
        except Exception as e:
            raise ApiError(f"Khanoumi bot check was not cleared by the browser ({type(e).__name__}).", 403) from e
        for c in cookies:
            client.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        _cleared = (client, time.monotonic())


async def _once(method: str, url: str, **kwargs: Any) -> httpx.Response:
    client, limit = _get_client()
    r = await _request(client, limit, method, url, **kwargs)
    if _is_challenge(r):
        _next_proxy(client)
        client, limit = _get_client()
        await _clear_challenge(client)
        r = await _request(client, limit, method, url, **kwargs)  # one retry; a second block is final
        if _is_challenge(r):
            _next_proxy(client)
    if r.status_code >= 400:
        detail = ""
        try:
            detail = _errors(r.json())
        except ValueError:
            pass
        retry_after = r.headers.get("retry-after", "")
        raise ApiError(
            _status_message(r.status_code) + (f" Site says: {detail}" if detail else ""),
            r.status_code,
            float(retry_after) if r.status_code in (429, 503) and retry_after.replace(".", "", 1).isdigit() else None,
        )
    return r


def _errors(body: Any) -> str:
    """'code: message' of the API's error list, e.g. 'product_not_found: The product with given id ...'."""
    errors = body.get("errors") if isinstance(body, dict) else None
    return "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors or [] if isinstance(e, dict))[:300]


def _status_message(code: int) -> str:
    if code == 400:
        return "khanoumi.com rejected the parameters (HTTP 400)."
    if code == 401:
        return "This needs a logged-in Khanoumi account (HTTP 401); this server is read-only and has no login."
    if code == 403:
        return "khanoumi.com blocked the request (HTTP 403). Turn off VPN/proxy or set KHANOUMI_MCP_PROXY."
    if code == 404:
        return "Not found on khanoumi.com (HTTP 404). Check the product slug, category id, brand slug or tag slug."
    if code == 429:
        return "khanoumi.com is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"khanoumi.com had a server error (HTTP {code}). Try again later."
    return f"khanoumi.com rejected the request (HTTP {code})."
