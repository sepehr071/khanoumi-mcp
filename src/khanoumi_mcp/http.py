"""Shared async HTTP client for www.khanoumi.com.

Every tool goes through `api` (the JSON REST API under /api/) or `get_page` (server-rendered
HTML: FAQ, blog). `_send` caps concurrency, retries once when the server drops the connection,
and turns HTTP failures into `ToolError` messages the model can act on. The client keeps the
anonymous cookies the API sets (`x-nusi`, `x-nux`; `uci` only from some calls such as similar).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://www.khanoumi.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0",
    "Accept": "application/json, text/html;q=0.9",
}

MAX_CONCURRENCY = 4

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None


class ApiError(ToolError):
    """A failed upstream call."""


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit
    _transport, _client, _limit = transport, None, None


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # Khanoumi answers direct connections fine; a system proxy is only used when the
        # user opts in with KHANOUMI_MCP_PROXY. One client = one cookie jar for the session.
        _client = httpx.AsyncClient(
            transport=_transport,
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
            trust_env=False,
            proxy=os.environ.get("KHANOUMI_MCP_PROXY") or None,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def api(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET an API path (`/api/ntl/v1/products`, ...) and return the envelope's `data`; None for HTTP 204."""
    r = await _send("GET", f"{BASE}{path}", params={k: v for k, v in (params or {}).items() if v is not None})
    if r.status_code == 204:  # banners and pop-ups: nothing running
        return None
    try:
        body = r.json()
    except ValueError as e:
        raise ApiError(f"khanoumi.com returned a non-JSON response for {path} (HTTP {r.status_code}).") from e
    if not isinstance(body, dict) or not body.get("isSuccess"):
        raise ApiError(f"khanoumi.com rejected the request: {_errors(body) or str(body)[:300]}")
    return body.get("data")


async def get_page(path: str, params: dict[str, Any] | None = None) -> str:
    """GET a site page and return its HTML."""
    return (await _send("GET", f"{BASE}{path}", params=params)).text


async def _send(method: str, url: str, **kwargs: Any) -> httpx.Response:
    client, limit = _get_client()
    for attempt in (1, 2):
        try:
            async with limit:
                r = await client.request(method, url, **kwargs)
            break
        except httpx.TimeoutException as e:
            raise ApiError("khanoumi.com did not answer in time. Try again in a moment.") from e
        except httpx.TransportError as e:
            if attempt == 2:
                raise ApiError(
                    f"Could not reach khanoumi.com ({type(e).__name__}). Check the internet connection, "
                    "or set KHANOUMI_MCP_PROXY."
                ) from e
    if r.status_code >= 400:
        detail = ""
        try:
            detail = _errors(r.json())
        except ValueError:
            pass
        raise ApiError(_status_message(r.status_code) + (f" Site says: {detail}" if detail else ""))
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
