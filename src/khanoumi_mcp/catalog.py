"""Finding products: search, cheapest offers, category / brand / tag listings, filters, categories, brands, deals."""

from __future__ import annotations

import asyncio
import html
import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import BASE, ApiError, api
from .registry import tool

PRODUCTS = "/api/ntl/v1/products"

Query = Annotated[
    str,
    Field(
        min_length=2,
        max_length=100,
        description="Product name or keyword, Persian or English, e.g. 'کرم مرطوب کننده' or 'cerave'.",
    ),
]
CategoryId = Annotated[
    int | None,
    Field(ge=1, le=1_000_000, description="Category id from kh_categories or kh_search, e.g. 145 (moisturizers)."),
]
Slug = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")]
Brands = Annotated[
    list[Slug] | None,
    Field(max_length=10, description="Brand slugs from kh_brands / kh_filters (OR), e.g. ['simple', 'cerave']."),
]
TagSlug = Annotated[
    str | None,
    Field(
        pattern=r"^[A-Za-z0-9._-]{1,80}$",
        description="Collection / campaign tag slug from kh_deals (the part after /tags/), e.g. 'festival-js' (pink box).",
    ),
]
MinPrice = Annotated[int | None, Field(ge=0, description="Minimum payable price in Toman, e.g. 500000.")]
MaxPrice = Annotated[int | None, Field(ge=1, description="Maximum payable price in Toman, e.g. 1500000.")]
InStock = Annotated[bool, Field(description="Only products that can be ordered now.")]
Page = Annotated[int, Field(ge=1, le=200, description="Page number, from 1.")]

SORTS = {"popular": None, "cheapest": "Cheapest", "most_expensive": "MostExpensive", "newest": "Newest"}
Sort = Annotated[
    Literal["popular", "cheapest", "most_expensive", "newest"],
    Field(
        description="Order: popular (the site's default, most visited), cheapest / most_expensive (payable price), newest."
    ),
]


@tool("Search products")
async def kh_search(
    query: Query,
    sort: Sort = "popular",
    in_stock_only: InStock = False,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    page: Page = 1,
    limit: Annotated[
        int,
        Field(ge=1, le=60, description="Products per page (sponsored items are left out)."),
    ] = 20,
) -> dict[str, Any]:
    """Search Khanoumi products by keyword: price, discount and stock of each match, sponsored items removed.

    Use first for "price of X" / "do you have X". Also returns the categories (ids for kh_browse)
    and brands (slugs) that match best. For the cheapest in-stock match use kh_find_cheapest;
    to filter by skin type, color or brand use kh_filters + kh_browse; shades, sellers and
    per-shade prices: kh_product.
    """
    _check_range(min_price, max_price)
    data, out = await _window(
        page,
        limit,
        query=query.strip(),
        sort=sort,
        in_stock_only=in_stock_only,
        min_price=min_price,
        max_price=max_price,
    )
    facets = data.get("facets") or {}
    leaves = sorted(_flat_categories(facets.get("categories") or [], leaves=True), key=lambda c: -c["count"])
    return {
        **out,
        "categories": leaves[:8],
        "brands": [_brand_facet(b) for b in (facets.get("brandFacets") or [])[:10]],
    }


@tool("Find cheapest product")
async def kh_find_cheapest(
    query: Query,
    category_id: CategoryId = None,
    match_all_words: Annotated[
        bool,
        Field(
            description="Keep only products whose Persian or English title or brand contains every word of the query."
        ),
    ] = True,
    scan: Annotated[
        int, Field(ge=50, le=900, description="Max search results to scan, cheapest first, 300 per request.")
    ] = 300,
    limit: Annotated[int, Field(ge=1, le=50, description="Max offers to return.")] = 20,
) -> dict[str, Any]:
    """Find the cheapest in-stock products for a keyword, one flat list sorted by payable price (Toman).

    Use when the user wants the lowest price for X. The site sorts in-stock matches by payable
    price; this drops sponsored items and, by default, loose matches whose title lacks a query
    word. Narrow with category_id (kh_categories / kh_search). final_price is the cheapest shade:
    check the chosen shade with kh_product. complete=false: matches go on past `scanned`, raise scan.
    """
    words = _norm(query).split()
    offers: list[dict[str, Any]] = []
    scanned, total, size = 0, 0, min(300, scan)  # the same page size on every page keeps the offsets aligned
    for page in range(1, -(-scan // size) + 1):
        data = await _list(
            query=query.strip(), category_id=category_id, sort="cheapest", in_stock_only=True, page=page, limit=size
        )
        items = _organic(data)
        scanned = scanned + len(items)
        if page == 1:
            total = _total(data)
        for p in items:
            text = _norm(
                " ".join(str(x or "") for x in (p.get("nameFa"), p.get("nameEn"), *(p.get("brand") or {}).values()))
            )
            if not match_all_words or all(w in text for w in words):
                offers.append(_item(p))
        # Sorted by price: once `limit` offers are in, later pages only hold dearer ones.
        if len(offers) >= limit or not items or scanned >= total:
            break
    offers.sort(key=lambda o: o["final_price"] or 0)
    return {
        "scanned": scanned,
        "total_matches": total,
        "complete": len(offers) >= limit or scanned >= total,
        "offers": offers[:limit],
    }


@tool("Browse a category, brand or tag")
async def kh_browse(
    category_id: CategoryId = None,
    brands: Brands = None,
    tag: TagSlug = None,
    query: Annotated[
        str | None, Field(min_length=2, max_length=100, description="Optional keyword inside the listing.")
    ] = None,
    sort: Sort = "popular",
    in_stock_only: InStock = False,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    colors: Annotated[
        list[Annotated[str, Field(pattern=r"^\d{1,6}$")]] | None,
        Field(max_length=10, description="Color ids from kh_filters (OR), e.g. ['3'] (red)."),
    ] = None,
    facets: Annotated[
        list[Annotated[str, Field(pattern=r"^facetKey\.[\w.-]{1,60}:[\w.-]{1,80}$")]] | None,
        Field(
            max_length=6,
            description="Attribute filter keys from kh_filters, all must match (AND), e.g. ['facetKey.skin-type:oily'].",
        ),
    ] = None,
    page: Page = 1,
    limit: Annotated[int, Field(ge=1, le=60, description="Products per page (sponsored items are left out).")] = 24,
) -> dict[str, Any]:
    """List the products of a category, brand(s) or campaign tag with sorting, price range and filters.

    Use for "cheapest CeraVe moisturizer", "sunscreens for oily skin under 800,000 Toman", "newest
    Golden Rose lipsticks", "everything in today's pink box". Pass at least one of category_id
    (kh_categories), brands (kh_brands) or tag (kh_deals). Filter ids (brands, colors, skin / hair
    type, free-from, ingredient facets) and the price range come from kh_filters. There is no
    rating or discount sort: check candidates with kh_product / kh_reviews. Details: kh_product.
    """
    if category_id is None and not brands and tag is None:
        raise ApiError("Pass at least one of category_id, brands or tag.")
    _check_range(min_price, max_price)
    _, out = await _window(
        page,
        limit,
        query=query,
        category_id=category_id,
        brands=brands,
        tag_id=await _tag_id(tag) if tag else None,
        sort=sort,
        in_stock_only=in_stock_only,
        min_price=min_price,
        max_price=max_price,
        colors=colors,
        facets=facets,
    )
    # An unknown category id is an empty listing, not an error: tell it apart from a filter that matches nothing.
    if not out["total"] and category_id is not None and not _total(await _list(category_id=category_id, limit=1)):
        raise ApiError(f"No category with id {category_id} on khanoumi.com. Get category ids from kh_categories.")
    return out


@tool("Filters of a listing")
async def kh_filters(
    category_id: CategoryId = None,
    brands: Brands = None,
    tag: TagSlug = None,
    query: Annotated[
        str | None, Field(min_length=2, max_length=100, description="Keyword, alone or inside the listing.")
    ] = None,
    group: Annotated[
        str | None,
        Field(
            min_length=2,
            description="Return only attribute groups whose name contains this, in full, e.g. 'نوع پوست' (skin type).",
        ),
    ] = None,
) -> dict[str, Any]:
    """List the filters of a category, brand, tag or search: sub-categories, brands, colors and attribute facets
    (skin type, hair type, free-from, ingredients, gender, ...) with ids and product counts, plus price range and stock counts.

    Use before kh_browse: pass brand slugs as brands, color ids as colors, facet keys as facets.
    Brands are cut to the 40 biggest and each attribute group to 25 values (`omitted` says how many
    more); ask for one group to see it all. Prices in Toman. price_range is on the list price before
    discount (min 0 = out-of-stock items), so its max can be above the dearest payable price.
    """
    if category_id is None and not brands and tag is None and query is None:
        raise ApiError("Pass at least one of category_id, brands, tag or query.")
    data = await _list(
        query=query, category_id=category_id, brands=brands, tag_id=await _tag_id(tag) if tag else None, page=1, limit=1
    )
    f = data.get("facets") or {}
    groups = []
    for g in f.get("dynamicFacets") or []:
        name = (g.get("key") or {}).get("displayNameFa") or ""
        if group and _norm(group) not in _norm(name):
            continue
        values = [
            {"key": v.get("key"), "name": v.get("displayNameFa"), "count": v.get("count")}
            for v in g.get("values") or []
        ]
        cut = len(values) if group else 25
        groups.append(
            {"group": name, "values": values[:cut], **({"omitted": len(values) - cut} if len(values) > cut else {})}
        )
    if group and not groups:
        names = ", ".join((g.get("key") or {}).get("displayNameFa") or "" for g in f.get("dynamicFacets") or [])
        raise ApiError(f"No filter group matching '{group}'. Groups here: {names}")
    brand_facets = f.get("brandFacets") or []
    price, stock = f.get("priceFacet") or {}, f.get("stockFacet") or {}
    return {
        "total": _total(data),
        "in_stock": (stock.get("hasStock") or {}).get("count"),
        "out_of_stock": (stock.get("outOfStock") or {}).get("count"),
        "price_range": {"min": price.get("fromPrice"), "max": price.get("toPrice")},
        "categories": sorted(_flat_categories(f.get("categories") or [], leaves=True), key=lambda c: -c["count"])[:20],
        "brands": [_brand_facet(b) for b in brand_facets[:40]],
        **({"brands_omitted": len(brand_facets) - 40} if len(brand_facets) > 40 else {}),
        "colors": [
            {"id": c.get("key"), "name": c.get("displayNameFa"), "count": c.get("count")}
            for c in f.get("colorFacets") or []
        ],
        "facets": groups,
    }


@tool("List categories")
async def kh_categories(
    query: Annotated[
        str | None,
        Field(
            min_length=2,
            description="Optional filter on the Persian name or English slug, any level, e.g. 'ضد آفتاب' or 'shampoo'.",
        ),
    ] = None,
    max_level: Annotated[
        int, Field(ge=1, le=4, description="Deepest level to list when no query is given (1 = top level).")
    ] = 2,
) -> dict[str, Any]:
    """List Khanoumi's category tree with ids, URL paths and product counts.

    Use to get a category_id for kh_browse / kh_filters / kh_find_cheapest. Without a query only
    levels up to max_level are listed; with a query every level is searched. kh_search also
    returns the categories matching a keyword.
    """
    data = await _list(page=1, limit=1)
    categories = _flat_categories((data.get("facets") or {}).get("categories") or [])
    if query:
        q = _norm(query)
        categories = [c for c in categories if q in _norm(c["title"]) or q in c["path"].lower()]
    else:
        categories = [c for c in categories if c["level"] <= max_level]
    return {"categories": categories}


@tool("Find brands")
async def kh_brands(
    query: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=60,
            description="Brand name, Persian or English, e.g. 'سیمپل' or 'cerave'. Empty = all, A-Z.",
        ),
    ] = None,
    page: Page = 1,
    limit: Annotated[int, Field(ge=1, le=300, description="Brands per page.")] = 50,
) -> dict[str, Any]:
    """Find brands by name (about 3,200 brands) with their slugs.

    Use to get the brand slug for kh_browse / kh_filters `brands`, e.g. 'simple', 'cerave'.
    """
    data = await api("/api/ntl/v1/catalog/brands", {"query": query, "page_number": page, "page_size": limit})
    return {
        "total": int(data.get("totalCount") or 0),
        "page": page,
        "brands": [
            {
                "slug": b.get("slug"),
                "name": b.get("nameFa"),
                "name_en": b.get("nameEn"),
                "url": f"{BASE}/brands/{b.get('slug')}",
            }
            for b in data.get("items") or []
        ],
    }


@tool("Current deals and discount codes")
async def kh_deals(
    limit: Annotated[int, Field(ge=1, le=100, description="Max deals to return.")] = 30,
) -> dict[str, Any]:
    """List today's featured deals from the Khanoumi home page (the daily pink box "جعبه صورتی" and the other
    product rows), biggest discount first, plus the public discount code of the current pop-up campaign.

    Use for "what's on sale" / "best discounts today". pink_box_ends_in_seconds is the time left in
    the daily deal box. Each section's `tag` lists all of its products with kh_browse(tag=...).
    The voucher code is entered at checkout; its conditions are in voucher.text.
    """
    errors: list[str] = []
    home, popup = await asyncio.gather(
        api("/api/cml/v1/pages"), _soft("voucher", api("/api/cml/v1/pop-up-elements", {"isHomePage": "true"}), errors)
    )
    sections, deals, seen, ends = [], [], set(), None
    for c in (home or {}).get("components") or []:
        if c.get("type") != "ProductList":
            continue
        pink = c.get("designType") == "PinkBox"
        if pink:
            ends = c.get("deactivationCountdownSecs")
        for tab in c.get("items") or []:
            title = tab.get("title") or c.get("title")
            sections.append(
                {"title": title, "pink_box": pink, "tag": _tag_slug(tab.get("link")), "link": _url(tab.get("link"))}
            )
            for entry in tab.get("items") or []:
                p = entry.get("product") or {}
                if p.get("id") and p["id"] not in seen:
                    seen.add(p["id"])
                    deals.append({**_landing_product(p), "section": title})
    deals.sort(key=lambda d: -d["discount_pct"])
    voucher = None
    if popup and popup.get("voucherCode"):
        voucher = {
            "code": popup["voucherCode"],
            "title": popup.get("title"),
            "text": _text(popup.get("description")),
            "link": _url(popup.get("link")),
        }
    return {
        "pink_box_ends_in_seconds": ends,
        "voucher": voucher,
        "sections": sections,
        "count": len(deals),
        "deals": deals[:limit],
        **({"errors": errors} if errors else {}),
    }


async def _list(
    *,
    query: str | None = None,
    category_id: int | None = None,
    brands: list[str] | None = None,
    tag_id: int | None = None,
    sort: str = "popular",
    in_stock_only: bool = False,
    min_price: int | None = None,
    max_price: int | None = None,
    colors: list[str] | None = None,
    facets: list[str] | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """GET /api/ntl/v1/products: one endpoint for search, category, brand, tag and facet listings."""
    params: dict[str, Any] = {
        "query": query,
        "cat_id": category_id,
        "tag_id": tag_id,
        "brand": ",".join(brands) if brands else None,  # comma list = OR
        "color": ",".join(colors) if colors else None,
        "facet": facets or None,  # repeated param = AND
        "sort": SORTS[sort],
        "has_stock": "true" if in_stock_only else None,
        "from_price": min_price,
        "to_price": max_price,
        "page_number": page,
        "page_size": limit,
    }
    data = await api(PRODUCTS, params)
    return data if isinstance(data, dict) else {}


async def _tag_id(slug: str) -> int:
    data = await api(f"/api/cml/v1/tags/slug/{slug}")
    if not data or not data.get("id"):
        raise ApiError(f"No tag '{slug}' on khanoumi.com. Get tag slugs from kh_deals.")
    return int(data["id"])


async def _soft(name: str, call: Any, errors: list[str]) -> Any:
    """Await an optional extra call; on failure note it in `errors` and return None."""
    try:
        return await call
    except ApiError as e:
        errors.append(f"{name}: {e}")
        return None


async def _window(page: int, limit: int, **filters: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Organic products [(page-1)*limit, page*limit) of a listing, and the first reply (facets).

    The API's own paging skips and repeats products when sponsored slots fall inside a page (for
    most page sizes), so this reads from page 1 and slices. Pages of 300 line up: the ads (up to
    15 seen, all in the first ~75 slots) sit on page 1 only, so page k starts at organic 300(k-1)-ads.
    """
    start, end = (page - 1) * limit, page * limit
    # ponytail: +16 covers the 15 ads seen per listing; more ads would shorten the page by the excess.
    first = await _list(**filters, page=1, limit=min(300, end + 16))
    organic, offset, total = _organic(first), 0, _total(first)
    if end > len(organic) and start < total and len((first.get("products") or {}).get("items") or []) == 300:
        ads = 300 - len(organic)
        k0 = (start + ads) // 300 + 1
        if k0 > 1:
            organic, offset = [], 300 * (k0 - 1) - ads
        for k in range(max(k0, 2), (end - 1 + ads) // 300 + 2):
            organic += _organic(await _list(**filters, page=k, limit=300))
    out = {
        "total": total,
        "page": page,
        "last_page": -(-total // limit),
        "products": [_item(p) for p in organic[start - offset : end - offset]],
    }
    return first, out


def _organic(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The non-sponsored items of a product-list reply (`ad` set = a sponsored slot)."""
    return [p for p in (data.get("products") or {}).get("items") or [] if not p.get("ad")]


def _total(data: dict[str, Any]) -> int:
    """Organic match count. totalCount also counts the sponsored slots; the stock facet does not."""
    stock = (data.get("facets") or {}).get("stockFacet") or {}
    if stock:
        return sum(int((stock.get(k) or {}).get("count") or 0) for k in ("hasStock", "outOfStock"))
    return int((data.get("products") or {}).get("totalCount") or 0)


def _item(p: dict[str, Any]) -> dict[str, Any]:
    """A product of a list reply (search, listing, similar). Prices are Toman."""
    final, price, pct = p.get("effectivePrice"), p.get("basePrice"), int(p.get("discountPercent") or 0)
    brand = p.get("brand") or {}
    return {
        "id": int(p["id"]),
        "slug": p.get("slug"),
        "title": (p.get("nameFa") or "").strip(),
        "brand": brand.get("nameFa") or brand.get("nameEn"),
        "final_price": final or None,
        "price": (final if not pct else price) or None,  # no offer: the site shows only the payable price
        "discount_pct": pct,
        "in_stock": bool(p.get("isSalable")),  # hasStock is always false in similar / complementary replies
        **({"shades": p["colorsCount"]} if (p.get("colorsCount") or 0) > 1 else {}),
        **({"badges": b} if (b := _badges(p.get("flags"))) else {}),
        "url": f"{BASE}/products/{p.get('slug')}",
    }


def _badges(flags: str | None) -> list[str]:
    """The site's product badges ('Chance, New' -> ['Chance', 'New']): FreeShipping, Chance, New, Bestseller, Gold, ..."""
    return [f for f in (s.strip() for s in (flags or "").split(",")) if f and f != "None"]


def _landing_product(p: dict[str, Any]) -> dict[str, Any]:
    """A product inside a home / landing ProductList component (salesPrice instead of effectivePrice)."""
    final, price, pct = p.get("salesPrice"), p.get("basePrice"), int(p.get("discountPercent") or 0)
    return {
        "id": int(p["id"]),
        "slug": p.get("slug"),
        "title": (p.get("nameFa") or "").strip(),
        "brand": (p.get("brand") or {}).get("nameFa"),
        "final_price": final or None,
        "price": (final if not pct else price) or None,
        "discount_pct": pct,
        "in_stock": bool(p.get("isSalable")),
        "url": f"{BASE}/products/{p.get('slug')}",
    }


def _flat_categories(nodes: list[dict[str, Any]], leaves: bool = False) -> list[dict[str, Any]]:
    """Flatten the facet category tree: id, title, URL path, level, product count."""
    out: list[dict[str, Any]] = []
    for n in nodes:
        crumbs = n.get("breadcrumb") or []
        children = n.get("children") or []
        if crumbs and (not leaves or not children):
            path = "/".join(c.get("slug") or "" for c in crumbs)
            out.append(
                {
                    "id": int(crumbs[-1]["id"]),
                    "title": n.get("displayNameFa") or crumbs[-1].get("nameFa"),
                    "path": path,
                    "level": len(crumbs),
                    "count": n.get("count") or 0,
                }
            )
        out += _flat_categories(children, leaves)
    return out


def _brand_facet(b: dict[str, Any]) -> dict[str, Any]:
    return {"slug": b.get("key"), "name": b.get("displayNameFa") or b.get("displayNameEn"), "count": b.get("count")}


def _check_range(min_price: int | None, max_price: int | None) -> None:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError("min_price must be <= max_price.")


def _tag_slug(link: str | None) -> str | None:
    m = re.match(r"^/tags/([^/?#]+)", link or "")
    return m.group(1) if m else None


def _url(link: str | None) -> str | None:
    return (BASE + link if link.startswith("/") else link) if link else None


def _text(fragment: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _norm(s: str) -> str:
    """Match Persian text loosely: Arabic ي/ك as Persian, half-space as space, case-insensitive."""
    return re.sub(r"\s+", " ", s.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip().lower()
