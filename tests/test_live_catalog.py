import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def call(client, name, args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_kh_search(client):
    data = await call(client, "kh_search", {"query": "کرم مرطوب کننده", "sort": "cheapest", "in_stock_only": True})
    prices = [p["final_price"] for p in data["products"]]
    assert data["total"] > 100 and prices and prices == sorted(prices) and prices[0] > 0
    assert any(c["id"] == 145 for c in data["categories"]) and data["brands"]


async def test_kh_search_pages_neither_skip_nor_repeat(client):
    # Pages of 20 on the raw API skip and repeat items around the ads; they must equal one 60-item page.
    args = {"query": "رژ لب"}
    pages = [await call(client, "kh_search", {**args, "page": n}) for n in (1, 2, 3)]
    one = await call(client, "kh_search", {**args, "limit": 60})
    ids = [p["id"] for page in pages for p in page["products"]]
    assert len(ids) == 60 and ids == [p["id"] for p in one["products"]]


async def test_kh_find_cheapest(client):
    data = await call(client, "kh_find_cheapest", {"query": "شامپو", "limit": 10})
    prices = [o["final_price"] for o in data["offers"]]
    assert len(prices) == 10 and prices == sorted(prices) and prices[0] > 0
    assert all("شامپو" in o["title"] and o["in_stock"] for o in data["offers"])


async def test_kh_browse(client):
    args = {
        "category_id": 145,
        "facets": ["facetKey.skin-type:oily"],
        "sort": "cheapest",
        "in_stock_only": True,
        "max_price": 1000000,
        "limit": 12,
    }
    data = await call(client, "kh_browse", args)
    prices = [p["final_price"] for p in data["products"]]
    assert data["total"] > 5 and prices == sorted(prices) and all(0 < p <= 1000000 for p in prices)


async def test_kh_filters(client):
    data = await call(client, "kh_filters", {"category_id": 145})
    skin = next(g for g in data["facets"] if g["group"] == "نوع پوست")
    assert any(v["key"] == "facetKey.skin-type:oily" for v in skin["values"])
    assert data["brands"] and data["price_range"]["max"] > 0 and data["in_stock"] > 0


async def test_kh_categories(client):
    data = await call(client, "kh_categories", {"query": "moisturizer"})
    assert any(c["id"] == 145 and c["path"] == "skincare/face-care/moisturizer" for c in data["categories"])


async def test_kh_brands(client):
    data = await call(client, "kh_brands", {"query": "cerave"})
    assert data["brands"][0]["slug"] == "cerave"


async def test_kh_deals(client):
    data = await call(client, "kh_deals", {"limit": 10})
    pcts = [d["discount_pct"] for d in data["deals"]]
    assert pcts and pcts == sorted(pcts, reverse=True) and data["sections"]
    assert all(d["final_price"] <= d["price"] for d in data["deals"]) and "errors" not in data
