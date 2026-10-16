"""Store rules (shipping, packaging, returns, payment from the FAQ) and the Khanoumi blog."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .catalog import _norm, _text
from .http import BASE, CACHE_TTL, ApiError, api, get_page
from .registry import tool

# FAQ section titles on /faq, by topic.
TOPICS = {
    "guarantee": "ضمانت خانومی",
    "order": "ثبت سفارش",
    "pink_box": "جعبه صورتی و شانس",
    "order_edit": "ویرایش سفارش",
    "tracking": "پیگیری سفارش",
    "delivery": "ارسال و تحویل کالا",
    "returns": "بازگشت کالا",
    "comments": "قوانین انتشار دیدگاه",
    "payment": "پرداخت و استرداد",
    "gold": "قیمت گذاری خرید و دریافت فاکتور طلا",
}


@tool("Shipping, returns and store rules")
async def kh_store_info(
    topic: Annotated[
        Literal[
            "all",
            "delivery",
            "returns",
            "payment",
            "guarantee",
            "order",
            "pink_box",
            "tracking",
            "order_edit",
            "comments",
            "gold",
        ],
        Field(
            description="FAQ section: delivery (fees, times), returns, payment, guarantee (authenticity, expiry), ...; all = about 80 answers, clipped."
        ),
    ] = "delivery",
    query: Annotated[
        str | None,
        Field(
            min_length=2, max_length=60, description="Only questions or answers containing this, e.g. 'هزینه ارسال'."
        ),
    ] = None,
    full_text: Annotated[bool, Field(description="Do not clip answers when topic is all.")] = False,
) -> dict[str, Any]:
    """Get Khanoumi's order rules from the official FAQ: packaging cost, shipping fees and times, returns,
    payment and refunds, authenticity guarantee, pink-box rules.

    Use for "how much is shipping", "can I return it", and the true order cost (formula in the server
    instructions; the fees are in the delivery answers). With topic=all and no query, answers are
    cut to 300 characters (end with …); pick a topic or a query, or set full_text=true, for full text.
    """
    config, doc = await asyncio.gather(
        api("/api/ntl/v1/app/configurations", ttl=CACHE_TTL), get_page("/faq", ttl=CACHE_TTL)
    )
    faq = _faq(doc)
    if not faq:
        raise ApiError("Could not read the FAQ page of khanoumi.com; the page layout may have changed.")
    if topic != "all":
        faq = [x for x in faq if x["section"] == TOPICS[topic]]
    elif not query and not full_text:
        faq = [{**x, "answer": x["answer"][:300] + "…" if len(x["answer"]) > 300 else x["answer"]} for x in faq]
    if query:
        q = _norm(query)
        faq = [x for x in faq if q in _norm(x["question"] + " " + x["answer"])]
    free_from = (config or {}).get("freeShipmentCartMinPrice")
    return {
        "packaging_cost": (config or {}).get("packagingCost"),
        # 200,000,000 Toman on 2026-10-05: in effect no basket-wide free shipping, only per-item tags.
        "free_shipping_from": free_from if free_from and free_from < 100_000_000 else None,
        "faq": faq,
        "url": f"{BASE}/faq",
    }


@tool("Search the beauty blog")
async def kh_blog_search(
    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=80,
            description="Topic, Persian works best, e.g. 'شامپو ریزش مو' or 'روتین پوست چرب'.",
        ),
    ],
    page: Annotated[int, Field(ge=1, le=50, description="Page number, from 1 (20 posts per page).")] = 1,
) -> dict[str, Any]:
    """Search the Khanoumi magazine (مجله خانومی): buying guides, care routines, ingredient explainers, with links.

    Use when the user asks what suits them or how to use something; then find products with kh_search.
    """
    path = f"/blog/page/{page}/" if page > 1 else "/blog/"
    doc = await get_page(path, {"s": query.strip()})
    posts = []
    for block in re.split(r'<li class="post-item', doc)[1:]:
        link = re.search(r'<h2 class="post-title"><a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not link or not link.group(1).startswith(BASE + "/"):  # scraped href: only on-site links
            continue
        cat = re.search(r'class="post-cat[^"]*">([^<]+)<', block)
        date = re.search(r'class="date meta-item[^"]*">([^<]+)<', block)
        excerpt = re.search(r'class="post-excerpt">(.*?)</p>', block, re.S)
        posts.append(
            {
                "title": _text(link.group(2)),
                "category": _text(cat.group(1)) if cat else None,
                "date": _text(date.group(1)) if date else None,  # Persian (Jalali) date as shown
                "excerpt": _text(excerpt.group(1)) if excerpt else None,
                "url": link.group(1),
            }
        )
    pages = [int(n) for n in re.findall(r"/blog/page/(\d+)/\?s=", doc)]
    return {"page": page, "last_page": max(pages + [page]), "posts": posts}


def _faq(doc: str) -> list[dict[str, str]]:
    """Q&A of the FAQ page, each with its section title. The answers are server-rendered from a bundle constant."""
    out = []
    parts = re.split(r'<span class="mb-1\.5[^"]*">([^<]+)</span>', doc)
    for i in range(1, len(parts) - 1, 2):
        section = _text(parts[i])
        for q, a in re.findall(
            r'<span class="py-2">(.*?)</span>.*?<p[^>]*SafeHtml[^>]*>(.*?)</p></div>', parts[i + 1], re.S
        ):
            out.append({"section": section, "question": _text(q), "answer": _text(a)})
    return out
