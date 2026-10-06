import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_kh_store_info(client):
    data = await call(client, "kh_store_info", {"topic": "delivery"})
    assert data["packaging_cost"] > 0 and len(data["faq"]) >= 5
    assert any("تومان" in x["answer"] for x in data["faq"])


async def test_kh_blog_search(client):
    data = await call(client, "kh_blog_search", {"query": "ضد آفتاب"})
    assert len(data["posts"]) >= 5 and data["posts"][0]["url"].startswith("https://www.khanoumi.com/blog/")
