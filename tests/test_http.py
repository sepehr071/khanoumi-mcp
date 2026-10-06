import re
from pathlib import Path

import httpx
import pytest

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
    assert len(api.calls) == 2


async def test_timeout_is_not_retried(client, api):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api[BRANDS] = slow
    result = await client.call_tool("kh_brands", {})
    assert result.is_error and "did not answer in time" in result.content[0].text and len(api.calls) == 1


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
    assert "Chrome" in api.calls[0].headers["User-Agent"]
