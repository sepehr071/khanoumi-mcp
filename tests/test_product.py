import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio

LIPSTICK = "golden-rose-sheer-bright-lipstick-112222"


async def test_kh_product_shades(client, api):
    api[f"/api/ntl/v1/products/slug/{LIPSTICK}"] = fixture("product_112222.json")
    out = (await client.call_tool("kh_product", {"product": LIPSTICK})).structured_content
    assert {k: out[k] for k in ("id", "title", "brand", "brand_slug", "final_price", "price", "discount_pct")} == {
        "id": 112222,
        "title": "رژلب شیر برایت گلدن رز (Sheer Bright)",
        "brand": "گلدن رز",
        "brand_slug": "golden-rose",
        "final_price": 1047646,  # the cheapest shade
        "price": 1057980,
        "discount_pct": 1,
    }
    assert (out["rating"], out["rating_count"], out["comment_count"]) == (4.5, 37, 37)
    assert [c["id"] for c in out["categories"]] == [8, 24, 25]
    assert out["variants"][2] == {
        "id": 600041931,
        "shade": "103",
        "size": None,
        "final_price": 1047646,
        "price": 1057980,
        "discount_pct": 1,
        "in_stock": True,
        "max_qty": 5,
        "lead_days": 2,
        "seller": "خانومی",
    }
    # 1 Toman below the base price with 0% off: shown as one price
    assert out["variants"][0]["final_price"] == out["variants"][0]["price"] == 1057979
    assert out["description"].startswith("بافت: جامد") and out["url"] == f"https://www.khanoumi.com/products/{LIPSTICK}"
    assert len(api.calls) == 1


async def test_kh_product_by_id_and_gold_sellers(client, api):
    slug = "venus-gold-rose-18-k-gold-bar-112412"
    api["/api/ntl/v1/products/id/112412"] = {"isSuccess": True, "data": {"id": {"value": 112412}, "slug": slug}}
    api[f"/api/ntl/v1/products/slug/{slug}"] = fixture("product_112412.json")
    out = (await client.call_tool("kh_product", {"product": "112412"})).structured_content
    assert [(v["size"], v["seller"], v["final_price"]) for v in out["variants"]] == [
        ("0.1 g", "طلالند", 3560264),
        ("0.2 g", "طلالند", 6973906),
        ("0.25 g", "ایلونا گالری", 8879270),
    ]
    assert out["badges"] == [] and out["variants"][0]["badges"] == ["Gold", "PromotionExcluded", "Gold18"]
    assert out["variants"][0]["gold"] == {
        "price_per_gram_18k": 26658663,
        "making_fee_pct": 30.5,
        "margin_pct": 0,
        "vat_pct": 10,
        "price_valid_until": "2026-10-06T01:28:16.5542977+03:30",
    }


async def test_kh_product_attributes(client, api):
    slug = "cerita-anti-hair-loss-fortifying-shampoo-with-caffeine-20200"
    api["/api/ntl/v1/products/id/20200"] = fixture("product_by_id.json")  # id -> slug
    api[f"/api/ntl/v1/products/slug/{slug}"] = fixture("product_20200.json")
    out = (await client.call_tool("kh_product", {"product": "20200"})).structured_content
    assert [c.url.path for c in api.calls] == ["/api/ntl/v1/products/id/20200", f"/api/ntl/v1/products/slug/{slug}"]
    assert (out["final_price"], out["price"], out["discount_pct"], out["rating"]) == (469090, 555000, 15, 4.9)
    assert out["attributes"]["نوع مو"] == ["انواع مو"] and "کافئین" in out["attributes"]["ترکیبات کلیدی"]
    assert out["variants"][0]["size"] == "200 ml" and out["variants"][0]["seller"] == "خانومی"
    assert out["authenticity"].startswith("این کالا")


async def test_kh_product_not_found(client, api):
    api["/api/ntl/v1/products/id/99999999"] = {"isSuccess": True, "data": None}
    result = await client.call_tool("kh_product", {"product": "99999999"})
    assert result.is_error and "No product with id 99999999" in result.content[0].text
    result = await client.call_tool("kh_product", {"product": "lipstick-1"})
    assert result.is_error and "HTTP 404" in result.content[0].text
    result = await client.call_tool("kh_product", {"product": "../x"})
    assert result.is_error and len(api.calls) == 2


async def test_kh_reviews(client, api):
    api["/api/cml/v1/products/id/20200/comments"] = fixture("comments.json")
    out = (await client.call_tool("kh_reviews", {"product": "cerita-shampoo-20200", "limit": 5})).structured_content
    assert out["total"] == 212 and len(out["reviews"]) == 5
    assert out["reviews"][1] == {
        "author": "زینب سقائی",
        "buyer": True,
        "date": "2026-09-22",
        "text": "بوش عالیهههععههه خیلییی خوبه پیشنهاد میکنممم",
        "likes": 0,
    }
    assert api.params() == {"page_number": "1", "page_size": "5"}


async def test_kh_reviews_with_photos(client, api):
    api["/api/cml/v1/products/id/20200/comments"] = fixture("comments_photos.json")
    out = (await client.call_tool("kh_reviews", {"product": "20200", "with_photos": True})).structured_content
    assert out["total"] == 3 and all(r["photos"] for r in out["reviews"])
    assert out["reviews"][0]["author"] is None and out["reviews"][0]["date"] == "2024-03-11"
    assert api.params()["has_image"] == "true" and len(api.calls) == 1  # comments are keyed by id: no slug lookup


async def test_unknown_product_is_an_error_not_an_empty_list(client, api):
    api["/api/ntl/v1/products/id/999999999"] = {"isSuccess": True, "data": None}
    api["/api/cml/v1/products/id/999999999/comments"] = {"isSuccess": True, "data": {"totalCount": 0, "items": []}}
    api["/api/ntl/v1/products/slug/foo-999999999/similar"] = {"isSuccess": True, "data": []}
    for name, args in (("kh_reviews", {"product": "999999999"}), ("kh_similar", {"product": "foo-999999999"})):
        result = await client.call_tool(name, args)
        assert result.is_error and "No product with id 999999999" in result.content[0].text


async def test_kh_similar(client, api):
    slug = "synskin-acnes-moisturising-cream-50g-33939"
    api[f"/api/ntl/v1/products/slug/{slug}/similar"] = fixture("similar.json")
    out = (await client.call_tool("kh_similar", {"product": slug})).structured_content
    assert out["count"] == 5 and out["products"][0]["id"] == 30634
    assert all(p["in_stock"] for p in out["products"])  # hasStock is false in this reply; isSalable counts
    api[f"/api/ntl/v1/products/slug/{slug}/complementary"] = fixture("complementary.json")
    out = (await client.call_tool("kh_similar", {"product": slug, "kind": "complementary"})).structured_content
    assert [p["id"] for p in out["products"]] == [28026, 33944] and out["products"][0]["shades"] == 3
