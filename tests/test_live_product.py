import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_kh_product(client):
    data = await call(client, "kh_product", {"product": "golden-rose-sheer-bright-lipstick-112222"})
    assert data["brand_slug"] == "golden-rose" and len(data["variants"]) >= 5
    assert all(v["shade"] for v in data["variants"]) and data["final_price"] == min(
        v["final_price"] for v in data["variants"] if v["final_price"]
    )
    assert 0 < data["rating"] <= 5


async def test_kh_reviews(client):
    data = await call(client, "kh_reviews", {"product": "20200", "limit": 5})
    assert data["total"] >= 100 and len(data["reviews"]) == 5 and data["reviews"][0]["text"]


async def test_kh_similar(client):
    data = await call(client, "kh_similar", {"product": "cerita-anti-hair-loss-fortifying-shampoo-with-caffeine-20200"})
    assert data["count"] >= 5 and all(p["slug"] for p in data["products"])
