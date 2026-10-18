import asyncio
import re
import sys
from pathlib import Path

import httpx
import pytest

from khanoumi_mcp import http

pytestmark = pytest.mark.anyio

BRANDS = "/api/ntl/v1/catalog/brands"
EMPTY = {"isSuccess": True, "data": {"totalCount": 0, "items": []}}


async def test_all_tools_are_read_only(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 12
    for t in tools:
        assert t.name.startswith("kh_"), t.name
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name
        assert t.description and t.title, t.name


async def test_readme_tool_tables_match_the_server(client):
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    listed = re.findall(r"^\| `(kh_\w+)` \|", readme, re.M)
    assert sorted(listed) == sorted(t.name for t in (await client.list_tools()).tools)


async def test_dropped_connection_is_retried_once(client, api):
    attempts = []

    def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)
        return httpx.Response(200, json=EMPTY)

    api[BRANDS] = flaky
    result = await client.call_tool("kh_brands", {})
    assert not result.is_error and len(attempts) == 2


async def test_network_error_after_retry(client, api):
    def down(request):
        raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING]", request=request)

    api[BRANDS] = down
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "Could not reach khanoumi.com (ConnectError)" in result.content[0].text
    assert len(api.calls) == 3


async def test_timeout_is_retried_twice(client, api):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api[BRANDS] = slow
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "did not answer in time" in result.content[0].text and len(api.calls) == 3


@pytest.mark.parametrize(
    ("status", "text"),
    [(404, "HTTP 404"), (429, "rate limiting"), (500, "server error (HTTP 500)"), (403, "blocked"), (401, "logged-in")],
)
async def test_http_errors_are_actionable(client, api, status, text):
    api[BRANDS] = lambda r: httpx.Response(status)
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and text in result.content[0].text


async def test_api_error_codes_are_passed_on(client, api):
    body = {
        "isSuccess": False,
        "errors": [{"code": "invalid.page_size", "message": "The value '500' is not valid.", "property": "page_size"}],
    }
    api[BRANDS] = lambda r: httpx.Response(400, json=body)
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "HTTP 400" in result.content[0].text
    assert "invalid.page_size: The value '500' is not valid." in result.content[0].text


async def test_body_level_errors(client, api):
    api[BRANDS] = {"isSuccess": False, "errors": [{"code": "x", "message": "bad input"}]}
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "x: bad input" in result.content[0].text

    api[BRANDS] = lambda r: httpx.Response(200, text="<html>oops</html>")
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "non-JSON" in result.content[0].text


async def test_cookies_are_kept_between_calls(client, api):
    # The guest session cookies the API sets must ride along on later calls (some calls get 429 without them).
    def first(request):
        return httpx.Response(200, json=EMPTY, headers={"set-cookie": "x-nusi=abc; Path=/"})

    api[BRANDS] = first
    await client.call_tool("kh_brands", {})
    await client.call_tool("kh_brands", {"query": "a"})
    assert "x-nusi=abc" in api.calls[1].headers.get("cookie", "")
    assert "Chrome" not in api.calls[0].headers.get("User-Agent", "")  # the impersonated profile supplies it
    h = api.calls[0].headers
    assert h["Referer"] == "https://www.khanoumi.com/" and h["sec-fetch-mode"] == "cors" and "Origin" not in h


async def test_ttl_cache_serves_repeat_calls(api):
    api["/api/x"] = {"isSuccess": True, "data": {"n": 1}}
    assert await http.api("/api/x", ttl=60) == {"n": 1}
    assert await http.api("/api/x", ttl=60) == {"n": 1}
    assert len(api.calls) == 1
    await http.api("/api/x")  # ttl 0 always fetches
    assert len(api.calls) == 2


async def test_ttl_cache_is_keyed_on_params_and_capped(api):
    api["/api/x"] = {"isSuccess": True, "data": {"n": 1}}
    await http.api("/api/x", {"q": "a"}, ttl=60)
    await http.api("/api/x", {"q": "b"}, ttl=60)
    assert len(api.calls) == 2
    for i in range(http.CACHE_MAX + 5):
        await http.api("/api/x", {"q": i}, ttl=60)
    assert len(http._cache) == http.CACHE_MAX


@pytest.mark.parametrize("status", [429, 503])
async def test_busy_site_is_retried_once(client, api, status):
    replies = [httpx.Response(status, headers={"retry-after": "0"}), httpx.Response(200, json=EMPTY)]
    api[BRANDS] = lambda r: replies.pop(0)
    result = await client.call_tool("kh_brands", {})
    assert not result.is_error and len(api.calls) == 2


async def test_redirect_off_site_is_refused(client, api):
    api[BRANDS] = lambda r: httpx.Response(302, headers={"location": "https://evil.example/x"})
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "only www.khanoumi.com" in result.content[0].text


async def test_raw_mcp_reply_is_one_text_block_without_schemas(api):
    from mcp import Client
    from mcp.types import TextContent

    from khanoumi_mcp.server import mcp

    api[BRANDS] = EMPTY
    async with Client(mcp) as raw:  # no conftest patch: what a real client receives
        tools = (await raw.list_tools()).tools
        assert all(t.output_schema is None for t in tools)
        assert not any("title" in p for t in tools for p in t.input_schema.get("properties", {}).values())
        result = await raw.call_tool("kh_brands", {})
    assert len(result.content) == 1 and isinstance(result.content[0], TextContent)
    assert result.structured_content is None and "\n" not in result.content[0].text


def test_is_challenge():
    html = {"content-type": "text/html"}
    assert http._is_challenge(httpx.Response(403, text="<html>Just a moment...</html>", headers=html))
    assert not http._is_challenge(httpx.Response(403, text="<html>Access Denied</html>", headers=html))
    assert not http._is_challenge(httpx.Response(403, json={"isSuccess": False}))
    assert not http._is_challenge(httpx.Response(200, text="<html></html>", headers=html))


async def test_403_is_not_retried(client, api):
    api[BRANDS] = lambda r: httpx.Response(403, json={"isSuccess": False})
    assert (await client.call_tool("kh_brands", {})).is_error and len(api.calls) == 1


async def test_proxy_list_rotates_on_connect_error(monkeypatch, api):
    monkeypatch.setenv("KHANOUMI_MCP_PROXY", "http://p1:1, http://p2:2")
    assert http._proxies() == ["http://p1:1", "http://p2:2"]

    def boom(request):
        raise httpx.ConnectError("down", request=request)

    api[BRANDS] = boom
    http._get_client()
    with pytest.raises(http.ApiError):
        await http._once("GET", http.BASE + BRANDS)
    assert http._proxy_index == 1 and http._client is None  # rebuilt with the next proxy on the next call


async def test_stale_client_does_not_rotate(monkeypatch, api):
    monkeypatch.setenv("KHANOUMI_MCP_PROXY", "http://p1:1, http://p2:2")
    old, _ = http._get_client()
    http._next_proxy(old)
    new, _ = http._get_client()
    assert http._proxy_index == 1 and new is not old
    http._next_proxy(old)  # a late failure on the retired client must not skip the proxy now in use
    assert http._proxy_index == 1 and http._client is new


async def test_challenge_cleared_by_browser_once(monkeypatch, api):
    runs = []

    async def fake_browser(proxy):
        runs.append(proxy)
        await asyncio.sleep(0.01)
        return [{"name": "clearance", "value": "ok", "domain": "www.khanoumi.com", "path": "/"}]

    monkeypatch.setattr(http, "_browser_cookies", fake_browser)

    def guarded(request):
        if "clearance=ok" not in request.headers.get("cookie", ""):
            return httpx.Response(403, text="<html>Just a moment</html>", headers={"content-type": "text/html"})
        return httpx.Response(200, json=EMPTY)

    api[BRANDS] = guarded
    await asyncio.gather(http.api(BRANDS, {"a": 1}), http.api(BRANDS, {"a": 2}))
    assert len(runs) == 1  # the second caller reused the cookies the first one fetched


async def test_challenge_without_patchright(monkeypatch, api):
    monkeypatch.setitem(sys.modules, "patchright.async_api", None)  # makes the import fail
    api[BRANDS] = lambda r: httpx.Response(403, text="<html>Just a moment</html>")
    with pytest.raises(http.ApiError, match=r"khanoumi-mcp\[browser\].*patchright install chromium"):
        await http.api(BRANDS)


async def test_retry_after_is_honoured_and_capped(monkeypatch, api):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(http.asyncio, "sleep", fake_sleep)
    replies = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(503, headers={"Retry-After": "999"}),
        httpx.Response(200, json=EMPTY),
    ]
    api[BRANDS] = lambda r: replies.pop(0)
    await http.api(BRANDS)
    assert [w for w in waits if w] == [3, http.MAX_RETRY_WAIT]
    api[BRANDS] = lambda r: httpx.Response(429)
    api.calls.clear()
    with pytest.raises(http.ApiError):
        await http.api(BRANDS)
    assert len(api.calls) == 3  # gives up after MAX_RETRIES
