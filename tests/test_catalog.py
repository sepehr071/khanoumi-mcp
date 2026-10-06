import httpx
import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio

PRODUCTS = "/api/ntl/v1/products"


async def test_kh_search(client, api):
    api[PRODUCTS] = fixture("search.json")
    args = {"query": "کرم مرطوب کننده", "sort": "cheapest", "in_stock_only": True, "min_price": 50000}
    out = (await client.call_tool("kh_search", args)).structured_content
    # total = stock facet (541), not totalCount (551, counts the ad slots); last_page from the requested limit
    assert out["total"] == 541 and out["page"] == 1 and out["last_page"] == 28
    # sponsored items (ad set) are dropped
    assert len(out["products"]) == 6 and 111068 not in [p["id"] for p in out["products"]]
    # site badges only when set ('Chance' = pink box)
    assert {p["id"]: p.get("badges") for p in out["products"]}[73639] == ["Chance"]
    assert out["products"][0] == {
        "id": 86308,
        "slug": "paletta-elderberry-tupe-hydration-cream-100-ml-86308",
        "title": "کرم مرطوب کننده تیوپی مدل ElderBerry مناسب پوست چرب حجم 100 میلی لیتر",
        "brand": "پالتا",
        "final_price": 65000,
        "price": 109000,
        "discount_pct": 40,
        "in_stock": True,
        "url": "https://www.khanoumi.com/products/paletta-elderberry-tupe-hydration-cream-100-ml-86308",
    }
    # leaf categories, biggest first, with the id for kh_browse
    assert out["categories"][0] == {
        "id": 145,
        "title": "آبرسان و مرطوب کننده",
        "path": "skincare/face-care/moisturizer",
        "level": 3,
        "count": 447,
    }
    assert out["brands"][0] == {"slug": "comeon", "name": "کامان", "count": 24} and len(out["brands"]) == 10
    assert api.params() == {
        "query": "کرم مرطوب کننده",
        "sort": "Cheapest",
        "has_stock": "true",
        "from_price": "50000",
        "page_number": "1",
        "page_size": "36",
    }


def _listing(n_organic: int, ads: int):
    """A fake product list that behaves like the API: ads in slots 2, 7, 12, ... of page 1 only, and
    page k > 1 starting at organic page_size*(k-1) - ads (the drift that skips / repeats items)."""
    item = fixture("search.json")["data"]["products"]["items"][0]

    def page(request):
        size, k = int(request.url.params["page_size"]), int(request.url.params["page_number"])
        items, organic = [], max(0, size * (k - 1) - ads)
        for slot in range(size):
            if k == 1 and slot % 5 == 2 and slot // 5 < ads:
                items.append({**item, "id": "9999999", "ad": {"index": slot}})
            elif organic < n_organic:
                items.append({**item, "id": str(organic + 1)})
                organic += 1
        products = {"totalCount": n_organic + ads, "pageSize": size, "items": items}
        facets = {"stockFacet": {"hasStock": {"count": n_organic}, "outOfStock": {"count": 0}}}
        return httpx.Response(200, json={"isSuccess": True, "data": {"products": products, "facets": facets}})

    return page


async def test_kh_search_pages_line_up_despite_ads(client, api):
    api[PRODUCTS] = _listing(1000, ads=15)
    seen = []
    for n in (1, 2, 3):
        out = (await client.call_tool("kh_search", {"query": "رژ لب", "page": n, "limit": 24})).structured_content
        seen += [p["id"] for p in out["products"]]
    assert seen == list(range(1, 73)) and out["total"] == 1000 and out["last_page"] == 42
    assert (api.params()["page_number"], api.params()["page_size"]) == ("1", "88")
    # deep page: page 1 at 300 (285 organic) gives the ad count, then page 2 of 300 (organic 285-584)
    api.calls.clear()
    out = (await client.call_tool("kh_search", {"query": "رژ لب", "page": 12, "limit": 30})).structured_content
    assert [p["id"] for p in out["products"]] == list(range(331, 361))
    assert [(api.params(i)["page_number"], api.params(i)["page_size"]) for i in (0, 1)] == [("1", "300"), ("2", "300")]
    out = (await client.call_tool("kh_search", {"query": "رژ لب", "page": 34, "limit": 30})).structured_content
    assert [p["id"] for p in out["products"]][-1] == 1000 and len(out["products"]) == 10


async def test_kh_search_default_sort_is_omitted(client, api):
    api[PRODUCTS] = fixture("search.json")
    await client.call_tool("kh_search", {"query": "رژ لب"})
    assert "sort" not in api.params() and "has_stock" not in api.params()


async def test_kh_search_bad_price_range(client, api):
    result = await client.call_tool("kh_search", {"query": "رژ لب", "min_price": 5, "max_price": 1})
    assert result.is_error and "min_price" in result.content[0].text and not api.calls


async def test_kh_find_cheapest(client, api):
    api[PRODUCTS] = fixture("search.json")
    out = (await client.call_tool("kh_find_cheapest", {"query": "کرم پالتا", "category_id": 145})).structured_content
    # only titles/brands containing every word, cheapest first
    assert [(o["id"], o["final_price"]) for o in out["offers"]] == [(86308, 65000), (86300, 65000)]
    assert out["scanned"] == 6 and out["total_matches"] == 541 and not out["complete"]
    assert api.params() == {
        "query": "کرم پالتا",
        "cat_id": "145",
        "sort": "Cheapest",
        "has_stock": "true",
        "page_number": "1",
        "page_size": "300",
    }
    out = (
        await client.call_tool("kh_find_cheapest", {"query": "کرم پالتا", "match_all_words": False})
    ).structured_content
    prices = [o["final_price"] for o in out["offers"]]
    assert len(prices) == 6 and prices == sorted(prices)


async def test_kh_find_cheapest_pages_with_a_fixed_size(client, api):
    item = fixture("search.json")["data"]["products"]["items"][0]

    def page(request):
        n = int(request.url.params["page_size"])
        products = {"totalCount": 2000, "pageSize": n, "items": [item] * n}
        return httpx.Response(200, json={"isSuccess": True, "data": {"products": products}})

    api[PRODUCTS] = page
    out = (await client.call_tool("kh_find_cheapest", {"query": "کرم", "scan": 700, "limit": 50})).structured_content
    assert [api.params(i)["page_number"] for i in range(len(api.calls))] == ["1"]  # 300 matches >= limit: stop
    assert out["complete"] and len(out["offers"]) == 50
    out = (await client.call_tool("kh_find_cheapest", {"query": "سرم", "scan": 700})).structured_content
    calls = [(api.params(i)["page_number"], api.params(i)["page_size"]) for i in range(1, len(api.calls))]
    assert calls == [("1", "300"), ("2", "300"), ("3", "300")] and out["scanned"] == 900 and not out["complete"]


async def test_kh_browse(client, api):
    api[PRODUCTS] = fixture("browse.json")
    api["/api/cml/v1/tags/slug/festival-js"] = fixture("tag_info.json")
    args = {
        "category_id": 145,
        "brands": ["simple", "cerave"],
        "tag": "festival-js",
        "sort": "most_expensive",
        "max_price": 5000000,
        "colors": ["3"],
        "facets": ["facetKey.skin-type:oily", "facetKey.gender:female"],
        "limit": 10,
    }
    out = (await client.call_tool("kh_browse", args)).structured_content
    assert out["total"] == 2064 and out["page"] == 1 and out["last_page"] == 207
    assert [p["id"] for p in out["products"]] == [106224, 116488, 116627, 116486]  # 72294 is sponsored
    # no discount: price is the payable price (the site shows one number)
    assert out["products"][2]["final_price"] == out["products"][2]["price"] == 3979999
    sent = api.calls[-1].url.params
    assert sent.get_list("facet") == ["facetKey.skin-type:oily", "facetKey.gender:female"]  # repeated = AND
    assert dict(sent) | {"facet": None} == {
        "cat_id": "145",
        "tag_id": "2311",
        "brand": "simple,cerave",
        "color": "3",
        "facet": None,
        "sort": "MostExpensive",
        "to_price": "5000000",
        "page_number": "1",
        "page_size": "26",
    }


async def test_kh_browse_needs_a_source(client, api):
    result = await client.call_tool("kh_browse", {"sort": "cheapest"})
    assert result.is_error and "at least one" in result.content[0].text and not api.calls
    result = await client.call_tool("kh_browse", {"brands": ["../x"]})
    assert result.is_error and not api.calls


async def test_kh_browse_unknown_tag(client, api):
    result = await client.call_tool("kh_browse", {"tag": "nope"})
    assert result.is_error and "HTTP 404" in result.content[0].text and "record.not.found" in result.content[0].text


async def test_kh_browse_unknown_category(client, api):
    api[PRODUCTS] = _listing(0, ads=0)
    result = await client.call_tool("kh_browse", {"category_id": 999999, "in_stock_only": True})
    assert result.is_error and "No category with id 999999" in result.content[0].text
    assert api.params() == {"cat_id": "999999", "page_number": "1", "page_size": "1"}  # re-checked without filters


async def test_kh_filters(client, api):
    api[PRODUCTS] = fixture("browse.json")
    out = (await client.call_tool("kh_filters", {"category_id": 145})).structured_content
    assert (out["total"], out["in_stock"], out["out_of_stock"]) == (2064, 618, 1446)
    assert out["price_range"] == {"min": 0, "max": 8914800}
    assert out["categories"] == [
        {
            "id": 145,
            "title": "آبرسان و مرطوب کننده",
            "path": "skincare/face-care/moisturizer",
            "level": 3,
            "count": 2064,
        }
    ]
    assert len(out["brands"]) == 40 and out["brands_omitted"] == 5
    assert out["brands"][0] == {"slug": "comeon", "name": "کامان", "count": 52}
    assert out["colors"] == [{"id": "17", "name": "کرم ، بژ", "count": 16}]
    skin = next(g for g in out["facets"] if g["group"] == "نوع پوست")
    assert {"key": "facetKey.skin-type:oily", "name": "چرب"} in [
        {k: v[k] for k in ("key", "name")} for v in skin["values"]
    ]
    ingredients = next(g for g in out["facets"] if g["group"] == "ترکیبات کلیدی")
    assert len(ingredients["values"]) == 25 and ingredients["omitted"] == 13
    assert api.params() == {"cat_id": "145", "page_number": "1", "page_size": "1"}


async def test_kh_filters_one_group(client, api):
    api[PRODUCTS] = fixture("browse.json")
    out = (await client.call_tool("kh_filters", {"query": "کرم", "group": "کلیدی"})).structured_content
    assert [g["group"] for g in out["facets"]] == ["ترکیبات کلیدی"] and len(out["facets"][0]["values"]) == 38
    result = await client.call_tool("kh_filters", {"category_id": 145, "group": "xyz"})
    assert result.is_error and "Groups here" in result.content[0].text and "نوع پوست" in result.content[0].text


async def test_kh_categories(client, api):
    api[PRODUCTS] = fixture("categories.json")
    out = (await client.call_tool("kh_categories", {})).structured_content
    assert out["categories"][0] == {
        "id": 620,
        "title": "عطر و اسپری",
        "path": "scented-products",
        "level": 1,
        "count": 12183,
    }
    assert {c["level"] for c in out["categories"]} == {1, 2}
    out = (await client.call_tool("kh_categories", {"query": "pocket"})).structured_content
    assert out["categories"][0]["id"] == 634 and all("pocket" in c["path"] for c in out["categories"])
    out = (await client.call_tool("kh_categories", {"max_level": 3})).structured_content
    assert 3 in {c["level"] for c in out["categories"]}


async def test_kh_brands(client, api):
    api["/api/ntl/v1/catalog/brands"] = fixture("brands.json")
    out = (await client.call_tool("kh_brands", {"query": "سیمپل"})).structured_content
    assert out == {
        "total": 1,
        "page": 1,
        "brands": [
            {"slug": "simple", "name": "سیمپل", "name_en": "Simple", "url": "https://www.khanoumi.com/brands/simple"}
        ],
    }
    assert api.params() == {"query": "سیمپل", "page_number": "1", "page_size": "50"}


async def test_kh_deals(client, api):
    api["/api/cml/v1/pages"] = fixture("home.json")
    api["/api/cml/v1/pop-up-elements"] = fixture("popup.json")
    out = (await client.call_tool("kh_deals", {"limit": 5})).structured_content
    assert out["pink_box_ends_in_seconds"] == 52294
    assert out["voucher"] == {
        "code": "PAYC9UCG",
        "title": "کد تخفیف 500 هزار تومانی !",
        "text": "کد 500 هزار تومانی درگاه اسنپ پی برای خرید 4 میلیون تومان",
        "link": "https://www.khanoumi.com/tags/festival-js",
    }
    assert out["sections"][0] == {
        "title": "جعبه صورتی",
        "pink_box": True,
        "tag": "festival-js",
        "link": "https://www.khanoumi.com/tags/festival-js",
    }
    assert out["count"] == 18 and len(out["deals"]) == 5
    pcts = [d["discount_pct"] for d in out["deals"]]
    assert pcts == sorted(pcts, reverse=True)
    assert out["deals"][0] == {
        "id": 75156,
        "slug": "revival-mineral-clay-cleaniser-150ml-75156",
        "title": "ژل شستشوی صورت کائولن 150میل",
        "brand": "رویوال",
        "final_price": 439750,
        "price": 879500,
        "discount_pct": 50,
        "in_stock": True,
        "url": "https://www.khanoumi.com/products/revival-mineral-clay-cleaniser-150ml-75156",
        "section": "جعبه صورتی",
    }
    assert "errors" not in out


async def test_kh_deals_without_popup(client, api):
    api["/api/cml/v1/pages"] = fixture("home.json")
    api["/api/cml/v1/pop-up-elements"] = lambda r: httpx.Response(204)  # nothing running
    out = (await client.call_tool("kh_deals", {})).structured_content
    assert out["voucher"] is None and "errors" not in out and out["deals"]
    api["/api/cml/v1/pop-up-elements"] = lambda r: httpx.Response(500)
    out = (await client.call_tool("kh_deals", {})).structured_content
    assert out["voucher"] is None and "HTTP 500" in out["errors"][0] and out["deals"]
