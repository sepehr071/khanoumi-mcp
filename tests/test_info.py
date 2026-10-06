import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio


@pytest.fixture
def store(api):
    api["/api/ntl/v1/app/configurations"] = fixture("config.json")
    api["/faq"] = fixture("faq.html")
    return api


async def test_kh_store_info_delivery(client, store):
    out = (await client.call_tool("kh_store_info", {})).structured_content
    assert out["packaging_cost"] == 20000
    assert out["free_shipping_from"] is None  # 200,000,000 Toman: no basket-wide free shipping
    assert {x["section"] for x in out["faq"]} == {"ارسال و تحویل کالا"}
    first = out["faq"][0]
    assert first["question"] == "هزینه بسته\u200cبندی و ارسال به چه صورت می\u200cباشد؟"
    assert "119 هزار تومان" in first["answer"] and "113 هزار تومان" in first["answer"]


async def test_kh_store_info_topics_and_query(client, store):
    out = (await client.call_tool("kh_store_info", {"topic": "all"})).structured_content
    assert {x["section"] for x in out["faq"]} == {"ضمانت خانومی", "ارسال و تحویل کالا"} and len(out["faq"]) == 22
    out = (
        await client.call_tool("kh_store_info", {"topic": "guarantee", "query": "انقضای محصولات"})
    ).structured_content
    assert [x["question"] for x in out["faq"]] == ["آیا خانومی تاریخ انقضای محصولات را تضمین می\u200cکند؟"]
    out = (await client.call_tool("kh_store_info", {"topic": "returns"})).structured_content
    assert out["faq"] == []  # not in the trimmed fixture


async def test_kh_store_info_layout_change(client, api):
    api["/api/ntl/v1/app/configurations"] = fixture("config.json")
    api["/faq"] = "<html><body>new layout</body></html>"
    result = await client.call_tool("kh_store_info", {})
    assert result.is_error and "layout may have changed" in result.content[0].text


async def test_kh_blog_search(client, api):
    api["/blog/"] = fixture("blog.html")
    out = (await client.call_tool("kh_blog_search", {"query": "شامپو"})).structured_content
    assert out["page"] == 1 and out["last_page"] == 13 and len(out["posts"]) == 3
    assert out["posts"][0] == {
        "title": "شامپو خشک چیست و چه کاربردی دارد؟ مزایا، معایب و روش استفاده",
        "category": "آرایش مو",
        "date": "6 مرداد 1405",
        "excerpt": "شستن مداوم و هر روزه مو، به موها آسیب می\u200cزند و البته وقت\u200cگیر است. در چنین شرایطی برای ایجاد ظاهر…",
        "url": "https://www.khanoumi.com/blog/dry-shampoo/",
    }
    assert api.params() == {"s": "شامپو"}


async def test_kh_blog_search_next_page(client, api):
    api["/blog/page/2/"] = fixture("blog.html")
    out = (await client.call_tool("kh_blog_search", {"query": "شامپو", "page": 2})).structured_content
    assert out["page"] == 2 and out["posts"] and api.calls[0].url.path == "/blog/page/2/"
